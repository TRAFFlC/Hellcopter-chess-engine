"""
Texel Tuning 评估参数优化器

Texel Tuning 是一种基于逻辑回归的评估参数优化方法：
1. 使用大量带结果标注的安静局面
2. 通过 sigmoid 函数将评估值映射到胜率
3. 最小化预测胜率与实际结果的误差
4. 使用梯度下降优化参数

核心公式：
- sigmoid(x) = 1 / (1 + exp(-x/K))
- 误差函数 E = Σ (sigmoid(eval) - result)²
- 梯度计算: ∂E/∂p = Σ 2 * (sigmoid - result) * sigmoid * (1 - sigmoid) * ∂eval/∂p

使用方法:
    python texel_tuner.py --positions quiet_positions.json --output tuned_config.json
    python texel_tuner.py --positions quiet_positions.json --params piece_values --iterations 1000
"""

import argparse
import json
import math
import random
import time
import chess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field


@dataclass
class TuningConfig:
    K: float = 1.0
    learning_rate: float = 0.01
    momentum: float = 0.9
    batch_size: int = 1000
    iterations: int = 1000
    early_stop_patience: int = 50
    early_stop_threshold: float = 1e-6
    regularization: float = 0.001
    param_step: int = 1


@dataclass
class TuningResult:
    initial_error: float
    final_error: float
    iterations_completed: int
    best_params: Dict[str, Any]
    error_history: List[float] = field(default_factory=list)
    param_history: List[Dict[str, Any]] = field(default_factory=list)
    elapsed_time: float = 0.0


def sigmoid(x: float, K: float = 1.0) -> float:
    if K == 0:
        K = 1.0
    scaled = x / K
    if scaled > 20:
        return 1.0 - 1e-10
    if scaled < -20:
        return 1e-10
    return 1.0 / (1.0 + math.exp(-scaled))


def sigmoid_derivative(sigmoid_val: float) -> float:
    return sigmoid_val * (1.0 - sigmoid_val)


class ParameterSet:
    def __init__(self):
        self.piece_values = {
            chess.PAWN: 100,
            chess.KNIGHT: 320,
            chess.BISHOP: 340,
            chess.ROOK: 500,
            chess.QUEEN: 900,
        }
        self.pst_weights = {
            'pawn_mg_scale': 1.0,
            'pawn_eg_scale': 1.0,
            'knight_mg_scale': 1.0,
            'knight_eg_scale': 1.0,
            'bishop_mg_scale': 1.0,
            'bishop_eg_scale': 1.0,
            'rook_mg_scale': 1.0,
            'rook_eg_scale': 1.0,
            'queen_mg_scale': 1.0,
            'queen_eg_scale': 1.0,
            'king_mg_scale': 1.0,
            'king_eg_scale': 1.0,
        }
        self.pawn_structure = {
            'doubled_pawn_penalty': 20,
            'isolated_pawn_penalty': 15,
            'passed_pawn_base': 40,
            'passed_pawn_scale': 15,
            'pawn_chain_bonus': 10,
        }
        self.eval_weights = {
            'bishop_pair_bonus': 30,
            'center_control': 15,
            'extended_center': 5,
        }
        
    def to_dict(self) -> Dict:
        return {
            'piece_values': {
                'pawn': self.piece_values[chess.PAWN],
                'knight': self.piece_values[chess.KNIGHT],
                'bishop': self.piece_values[chess.BISHOP],
                'rook': self.piece_values[chess.ROOK],
                'queen': self.piece_values[chess.QUEEN],
            },
            'pst_weights': self.pst_weights.copy(),
            'pawn_structure': self.pawn_structure.copy(),
            'eval_weights': self.eval_weights.copy(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ParameterSet':
        params = cls()
        if 'piece_values' in data:
            pv = data['piece_values']
            params.piece_values[chess.PAWN] = pv.get('pawn', 100)
            params.piece_values[chess.KNIGHT] = pv.get('knight', 320)
            params.piece_values[chess.BISHOP] = pv.get('bishop', 340)
            params.piece_values[chess.ROOK] = pv.get('rook', 500)
            params.piece_values[chess.QUEEN] = pv.get('queen', 900)
        if 'pst_weights' in data:
            params.pst_weights.update(data['pst_weights'])
        if 'pawn_structure' in data:
            params.pawn_structure.update(data['pawn_structure'])
        if 'eval_weights' in data:
            params.eval_weights.update(data['eval_weights'])
        return params
    
    def get_tunable_params(self) -> Dict[str, Tuple[float, float, float]]:
        params = {}
        for piece, val in self.piece_values.items():
            name = f"piece_{chess.piece_name(piece)}"
            params[name] = (val, 50, 2000 if piece == chess.QUEEN else 1000)
        for name, val in self.pawn_structure.items():
            params[f"pawn_{name}"] = (val, 0, 100)
        for name, val in self.eval_weights.items():
            params[f"eval_{name}"] = (val, 0, 100)
        return params
    
    def set_param(self, name: str, value: float):
        if name.startswith("piece_"):
            piece_name = name[6:]
            piece_map = {
                'pawn': chess.PAWN,
                'knight': chess.KNIGHT,
                'bishop': chess.BISHOP,
                'rook': chess.ROOK,
                'queen': chess.QUEEN,
            }
            if piece_name in piece_map:
                self.piece_values[piece_map[piece_name]] = int(value)
        elif name.startswith("pawn_"):
            param_name = name[5:]
            if param_name in self.pawn_structure:
                self.pawn_structure[param_name] = int(value)
        elif name.startswith("eval_"):
            param_name = name[5:]
            if param_name in self.eval_weights:
                self.eval_weights[param_name] = int(value)


class SimpleEvaluator:
    PST_PAWN_MG = [
        0,   0,   0,   0,   0,   0,   0,   0,
        50,  50,  50,  50,  50,  50,  50,  50,
        10,  20,  25,  30,  30,  25,  20,  10,
        5,  10,  15,  25,  25,  15,  10,   5,
        0,   5,  10,  20,  20,  10,   5,   0,
        0,  -5, -10,   5,   5, -10,  -5,   0,
        0,   5,  10, -20, -20,  10,   5,   0,
        0,   0,   0,   0,   0,   0,   0,   0,
    ]
    
    PST_KNIGHT_MG = [
        -50, -40, -30, -30, -30, -30, -40, -50,
        -40, -20,   0,   0,   0,   0, -20, -40,
        -30,   0,  10,  15,  15,  10,   0, -30,
        -30,   5,  15,  20,  20,  15,   5, -30,
        -30,   0,  15,  20,  20,  15,   0, -30,
        -30,   5,  10,  15,  15,  10,   5, -30,
        -40, -20,   0,   5,   5,   0, -20, -40,
        -50, -40, -30, -30, -30, -30, -40, -50,
    ]
    
    PST_BISHOP_MG = [
        -20, -10, -10, -10, -10, -10, -10, -20,
        -10,   0,   0,   0,   0,   0,   0, -10,
        -10,   0,  10,  10,  10,  10,   0, -10,
        -10,   5,   5,  10,  10,   5,   5, -10,
        -10,   0,   5,  10,  10,   5,   0, -10,
        -10,  10,  10,  10,  10,  10,  10, -10,
        -10,   5,   0,   0,   0,   0,   5, -10,
        -20, -10, -10, -10, -10, -10, -10, -20,
    ]
    
    PST_ROOK_MG = [
        0,   0,   0,   5,   5,   0,   0,   0,
        5,  10,  10,  10,  10,  10,  10,   5,
        -5,   0,   0,   0,   0,   0,   0,  -5,
        -5,   0,   0,   0,   0,   0,   0,  -5,
        -5,   0,   0,   0,   0,   0,   0,  -5,
        -5,   0,   0,   0,   0,   0,   0,  -5,
        -5,   0,   0,   0,   0,   0,   0,  -5,
        0,   0,   0,   5,   5,   0,   0,   0,
    ]
    
    PST_QUEEN_MG = [
        -20, -10, -10,  -5,  -5, -10, -10, -20,
        -10,   0,   0,   0,   0,   0,   0, -10,
        -10,   0,   5,   5,   5,   5,   0, -10,
        -5,   0,   5,   5,   5,   5,   0,  -5,
        0,   0,   5,   5,   5,   5,   0,  -5,
        -10,   5,   5,   5,   5,   5,   0, -10,
        -10,   0,   5,   0,   0,   0,   0, -10,
        -20, -10, -10,  -5,  -5, -10, -10, -20,
    ]
    
    PST_KING_MG = [
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -20, -30, -30, -40, -40, -30, -30, -20,
        -10, -20, -20, -20, -20, -20, -20, -10,
        20,  20,   0,   0,   0,   0,  20,  20,
        20,  30,  10,   0,   0,  10,  30,  20,
    ]
    
    CENTER_SQUARES = [chess.D4, chess.E4, chess.D5, chess.E5]
    EXTENDED_CENTER = [chess.C3, chess.D3, chess.E3, chess.F3,
                       chess.C4, chess.F4, chess.C5, chess.F5,
                       chess.C6, chess.D6, chess.E6, chess.F6]
    
    def __init__(self, params: ParameterSet):
        self.params = params
    
    def evaluate(self, board: chess.Board) -> int:
        score = 0
        
        for color in (chess.WHITE, chess.BLACK):
            sign = 1 if color == chess.WHITE else -1
            
            for piece_type in [chess.PAWN, chess.KNIGHT, chess.BISHOP, 
                              chess.ROOK, chess.QUEEN]:
                value = self.params.piece_values.get(piece_type, 100)
                pieces = board.pieces(piece_type, color)
                score += sign * value * len(pieces)
                
                pst_score = self._get_pst_score(board, piece_type, color, pieces)
                score += sign * pst_score
            
            king_sq = board.king(color)
            if king_sq is not None:
                king_table = self.PST_KING_MG
                if color == chess.WHITE:
                    score += sign * king_table[king_sq]
                else:
                    score += sign * king_table[chess.square_mirror(king_sq)]
        
        if len(board.pieces(chess.BISHOP, chess.WHITE)) >= 2:
            score += self.params.eval_weights.get('bishop_pair_bonus', 30)
        if len(board.pieces(chess.BISHOP, chess.BLACK)) >= 2:
            score -= self.params.eval_weights.get('bishop_pair_bonus', 30)
        
        score += self._evaluate_pawn_structure(board)
        
        center_bonus = self.params.eval_weights.get('center_control', 15)
        extended_bonus = self.params.eval_weights.get('extended_center', 5)
        for sq in self.CENTER_SQUARES:
            piece = board.piece_at(sq)
            if piece:
                score += center_bonus if piece.color == chess.WHITE else -center_bonus
        for sq in self.EXTENDED_CENTER:
            piece = board.piece_at(sq)
            if piece:
                score += extended_bonus if piece.color == chess.WHITE else -extended_bonus
        
        return score
    
    def _get_pst_score(self, board: chess.Board, piece_type: int, 
                       color: bool, pieces: chess.SquareSet) -> int:
        tables = {
            chess.PAWN: self.PST_PAWN_MG,
            chess.KNIGHT: self.PST_KNIGHT_MG,
            chess.BISHOP: self.PST_BISHOP_MG,
            chess.ROOK: self.PST_ROOK_MG,
            chess.QUEEN: self.PST_QUEEN_MG,
        }
        
        table = tables.get(piece_type)
        if table is None:
            return 0
        
        pst_score = 0
        for sq in pieces:
            if color == chess.WHITE:
                pst_score += table[sq]
            else:
                pst_score += table[chess.square_mirror(sq)]
        
        return pst_score
    
    def _evaluate_pawn_structure(self, board: chess.Board) -> int:
        score = 0
        
        doubled = self.params.pawn_structure.get('doubled_pawn_penalty', 20)
        isolated = self.params.pawn_structure.get('isolated_pawn_penalty', 15)
        passed_base = self.params.pawn_structure.get('passed_pawn_base', 40)
        passed_scale = self.params.pawn_structure.get('passed_pawn_scale', 15)
        
        for color in (chess.WHITE, chess.BLACK):
            sign = 1 if color == chess.WHITE else -1
            pawns = list(board.pieces(chess.PAWN, color))
            
            files = {}
            for sq in pawns:
                f = chess.square_file(sq)
                files[f] = files.get(f, 0) + 1
            
            for count in files.values():
                if count >= 2:
                    score -= sign * doubled * (count - 1)
            
            file_set = set(files.keys())
            for sq in pawns:
                f = chess.square_file(sq)
                if (f - 1) not in file_set and (f + 1) not in file_set:
                    score -= sign * isolated
            
            enemy_pawns = list(board.pieces(chess.PAWN, not color))
            for sq in pawns:
                rank = chess.square_rank(sq)
                file = chess.square_file(sq)
                is_passed = True
                for enemy_sq in enemy_pawns:
                    enemy_rank = chess.square_rank(enemy_sq)
                    enemy_file = chess.square_file(enemy_sq)
                    if color == chess.WHITE:
                        if enemy_rank > rank and abs(enemy_file - file) <= 1:
                            is_passed = False
                            break
                    else:
                        if enemy_rank < rank and abs(enemy_file - file) <= 1:
                            is_passed = False
                            break
                
                if is_passed:
                    if color == chess.WHITE:
                        score += sign * (passed_base + passed_scale * (rank - 1))
                    else:
                        score += sign * (passed_base + passed_scale * (7 - rank))
        
        return score


class TexelTuner:
    def __init__(self, config: Optional[TuningConfig] = None):
        self.config = config or TuningConfig()
        self.params = ParameterSet()
        self.evaluator = SimpleEvaluator(self.params)
        self.positions: List[Dict] = []
        
    def load_positions(self, path: str):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.positions = data.get('positions', [])
        print(f"加载了 {len(self.positions)} 个局面")
        
    def set_positions(self, positions: List[Dict]):
        self.positions = positions
        
    def compute_error(self, positions: Optional[List[Dict]] = None) -> float:
        if positions is None:
            positions = self.positions
        
        total_error = 0.0
        K = self.config.K
        
        for pos in positions:
            fen = pos['fen']
            result = pos['result']
            
            board = chess.Board(fen)
            eval_score = self.evaluator.evaluate(board)
            
            if board.turn == chess.BLACK:
                eval_score = -eval_score
            
            predicted = sigmoid(eval_score, K)
            error = (predicted - result) ** 2
            total_error += error
        
        return total_error / len(positions) if positions else 0.0
    
    def compute_gradient(self, param_name: str, positions: Optional[List[Dict]] = None) -> float:
        if positions is None:
            positions = self.positions
        
        epsilon = 1.0
        K = self.config.K
        total_gradient = 0.0
        
        original_value = self._get_param_value(param_name)
        
        for pos in positions:
            fen = pos['fen']
            result = pos['result']
            board = chess.Board(fen)
            
            self._set_param_value(param_name, original_value + epsilon)
            eval_plus = self.evaluator.evaluate(board)
            if board.turn == chess.BLACK:
                eval_plus = -eval_plus
            
            self._set_param_value(param_name, original_value - epsilon)
            eval_minus = self.evaluator.evaluate(board)
            if board.turn == chess.BLACK:
                eval_minus = -eval_minus
            
            self._set_param_value(param_name, original_value)
            
            eval_deriv = (eval_plus - eval_minus) / (2 * epsilon)
            
            eval_current = self.evaluator.evaluate(board)
            if board.turn == chess.BLACK:
                eval_current = -eval_current
            
            predicted = sigmoid(eval_current, K)
            sig_deriv = sigmoid_derivative(predicted)
            
            gradient = 2 * (predicted - result) * sig_deriv * eval_deriv / K
            total_gradient += gradient
        
        return total_gradient / len(positions) if positions else 0.0
    
    def _get_param_value(self, param_name: str) -> float:
        if param_name.startswith("piece_"):
            piece_name = param_name[6:]
            piece_map = {
                'pawn': chess.PAWN,
                'knight': chess.KNIGHT,
                'bishop': chess.BISHOP,
                'rook': chess.ROOK,
                'queen': chess.QUEEN,
            }
            return float(self.params.piece_values.get(piece_map[piece_name], 100))
        elif param_name.startswith("pawn_"):
            param_key = param_name[5:]
            return float(self.params.pawn_structure.get(param_key, 0))
        elif param_name.startswith("eval_"):
            param_key = param_name[5:]
            return float(self.params.eval_weights.get(param_key, 0))
        return 0.0
    
    def _set_param_value(self, param_name: str, value: float):
        self.params.set_param(param_name, value)
        self.evaluator = SimpleEvaluator(self.params)
    
    def tune(self, params_to_tune: Optional[List[str]] = None,
             progress_callback: Optional[Callable] = None) -> TuningResult:
        if not self.positions:
            raise ValueError("没有加载局面数据，请先调用 load_positions()")
        
        if params_to_tune is None:
            params_to_tune = list(self.params.get_tunable_params().keys())
        
        print(f"\n开始 Texel Tuning")
        print(f"局面数: {len(self.positions)}")
        print(f"待优化参数: {len(params_to_tune)}")
        print(f"迭代次数: {self.config.iterations}")
        print(f"学习率: {self.config.learning_rate}")
        print(f"K值: {self.config.K}")
        print()
        
        initial_error = self.compute_error()
        print(f"初始误差: {initial_error:.6f}")
        
        best_error = initial_error
        best_params = self.params.to_dict()
        error_history = [initial_error]
        param_history = [self.params.to_dict()]
        
        velocities = {name: 0.0 for name in params_to_tune}
        patience_counter = 0
        
        start_time = time.perf_counter()
        
        for iteration in range(1, self.config.iterations + 1):
            batch = self._get_batch()
            
            for param_name in params_to_tune:
                gradient = self.compute_gradient(param_name, batch)
                
                reg_gradient = self.config.regularization * self._get_param_value(param_name)
                gradient += reg_gradient
                
                velocities[param_name] = (self.config.momentum * velocities[param_name] 
                                         - self.config.learning_rate * gradient)
                
                new_value = self._get_param_value(param_name) + velocities[param_name]
                new_value = self._clamp_param(param_name, new_value)
                new_value = round(new_value / self.config.param_step) * self.config.param_step
                
                self._set_param_value(param_name, new_value)
            
            current_error = self.compute_error()
            error_history.append(current_error)
            param_history.append(self.params.to_dict())
            
            if current_error < best_error - self.config.early_stop_threshold:
                best_error = current_error
                best_params = self.params.to_dict()
                patience_counter = 0
            else:
                patience_counter += 1
            
            if progress_callback:
                progress_callback(iteration, current_error, best_error)
            elif iteration % 100 == 0 or iteration == 1:
                print(f"迭代 {iteration:5d}: 误差 = {current_error:.6f}, 最佳 = {best_error:.6f}")
            
            if patience_counter >= self.config.early_stop_patience:
                print(f"\n早停于迭代 {iteration}，误差无改善")
                break
        
        elapsed = time.perf_counter() - start_time
        
        self.params = ParameterSet.from_dict(best_params)
        
        result = TuningResult(
            initial_error=initial_error,
            final_error=best_error,
            iterations_completed=iteration,
            best_params=best_params,
            error_history=error_history,
            param_history=param_history,
            elapsed_time=elapsed
        )
        
        print()
        print("=" * 60)
        print("优化完成")
        print("=" * 60)
        print(f"初始误差: {initial_error:.6f}")
        print(f"最终误差: {best_error:.6f}")
        print(f"误差降低: {(initial_error - best_error) / initial_error * 100:.2f}%")
        print(f"迭代次数: {iteration}")
        print(f"耗时: {elapsed:.2f} 秒")
        
        return result
    
    def _get_batch(self) -> List[Dict]:
        if self.config.batch_size >= len(self.positions):
            return self.positions
        return random.sample(self.positions, self.config.batch_size)
    
    def _clamp_param(self, param_name: str, value: float) -> float:
        tunable = self.params.get_tunable_params()
        if param_name in tunable:
            _, min_val, max_val = tunable[param_name]
            return max(min_val, min(max_val, value))
        return value
    
    def optimize_K(self, positions: Optional[List[Dict]] = None,
                   K_range: Tuple[float, float] = (0.5, 2.0),
                   K_step: float = 0.1) -> float:
        if positions is None:
            positions = self.positions[:min(10000, len(self.positions))]
        
        print("\n优化 K 值...")
        best_K = self.config.K
        best_error = float('inf')
        
        K = K_range[0]
        while K <= K_range[1]:
            self.config.K = K
            error = self.compute_error(positions)
            print(f"  K = {K:.2f}, 误差 = {error:.6f}")
            if error < best_error:
                best_error = error
                best_K = K
            K += K_step
        
        self.config.K = best_K
        print(f"最佳 K 值: {best_K:.2f}")
        return best_K


def save_tuning_result(result: TuningResult, output_path: str):
    data = {
        "version": "1.0",
        "created_at": datetime.now().isoformat(),
        "initial_error": result.initial_error,
        "final_error": result.final_error,
        "error_reduction_percent": (result.initial_error - result.final_error) / result.initial_error * 100,
        "iterations": result.iterations_completed,
        "elapsed_seconds": result.elapsed_time,
        "best_params": result.best_params,
        "error_history_sample": result.error_history[::max(1, len(result.error_history) // 100)],
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"\n结果已保存到 {output_path}")


def generate_config_from_params(params: Dict, base_config_path: Optional[str] = None,
                                output_path: str = "tuned_config.json") -> str:
    config = {
        "version": f"texel_tuned_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "created_at": datetime.now().isoformat(),
        "description": "Texel Tuning 优化结果",
        "parameters": {
            "piece_values": params.get("piece_values", {}),
            "eval_weights": {
                "bishop_pair_bonus": params.get("eval_weights", {}).get("bishop_pair_bonus", 30),
                "doubled_pawn_penalty": -params.get("pawn_structure", {}).get("doubled_pawn_penalty", 20),
                "isolated_pawn_penalty": -params.get("pawn_structure", {}).get("isolated_pawn_penalty", 15),
            }
        }
    }
    
    if base_config_path and Path(base_config_path).exists():
        with open(base_config_path, 'r', encoding='utf-8') as f:
            base = json.load(f)
        if "base_version" in base:
            config["base_version"] = base["base_version"]
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    print(f"配置已保存到 {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Texel Tuning 评估参数优化")
    parser.add_argument("--positions", "-p", type=str, required=True,
                       help="局面数据文件路径")
    parser.add_argument("--output", "-o", type=str, default="tuning_result.json",
                       help="输出结果文件路径")
    parser.add_argument("--config-output", type=str, default=None,
                       help="生成的配置文件路径")
    parser.add_argument("--iterations", "-i", type=int, default=1000,
                       help="迭代次数 (默认: 1000)")
    parser.add_argument("--learning-rate", "-lr", type=float, default=0.01,
                       help="学习率 (默认: 0.01)")
    parser.add_argument("--batch-size", "-b", type=int, default=1000,
                       help="批次大小 (默认: 1000)")
    parser.add_argument("--K", type=float, default=1.0,
                       help="sigmoid 缩放因子 K (默认: 1.0)")
    parser.add_argument("--optimize-K", action="store_true",
                       help="先优化 K 值")
    parser.add_argument("--params", type=str, nargs='+', default=None,
                       help="要优化的参数列表")
    parser.add_argument("--quiet", "-q", action="store_true",
                       help="静默模式")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Texel Tuning 评估参数优化器")
    print("=" * 60)
    
    config = TuningConfig(
        K=args.K,
        learning_rate=args.learning_rate,
        batch_size=args.batch_size,
        iterations=args.iterations,
    )
    
    tuner = TexelTuner(config)
    tuner.load_positions(args.positions)
    
    if args.optimize_K:
        tuner.optimize_K()
    
    result = tuner.tune(params_to_tune=args.params)
    
    save_tuning_result(result, args.output)
    
    if args.config_output:
        generate_config_from_params(result.best_params, output_path=args.config_output)
    
    print()
    print("=" * 60)
    print("优化后的参数")
    print("=" * 60)
    for key, value in result.best_params.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    import random
    main()
