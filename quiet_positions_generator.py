"""
安静局面生成器 - 用于 Texel Tuning

从随机自战中提取安静局面（非战术局面），用于评估参数优化。
安静局面是指：
1. 不是将军局面
2. 没有明显的战术威胁（如悬子、强制走法等）
3. 局面相对稳定，评估函数的准确性更重要

使用方法:
    python quiet_positions_generator.py                    # 生成默认10000个局面
    python quiet_positions_generator.py --num-positions 50000  # 生成50000个局面
    python quiet_positions_generator.py --output my_positions.json  # 指定输出文件
"""

import argparse
import json
import random
import time
import chess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional


class QuietPositionGenerator:
    MIN_PIECES = 6
    MAX_PIECES = 32
    MIN_MOVES_FOR_QUIET = 10
    TACTICAL_THRESHOLD = 150
    
    def __init__(self, seed: Optional[int] = None):
        if seed is not None:
            random.seed(seed)
        self.positions_generated = 0
        self.games_played = 0
        self.total_moves = 0
        
    def is_quiet_position(self, board: chess.Board) -> bool:
        if board.is_check():
            return False
        
        if board.is_checkmate():
            return False
            
        piece_count = len(board.piece_map())
        if piece_count < self.MIN_PIECES or piece_count > self.MAX_PIECES:
            return False
            
        if self._has_hanging_piece(board):
            return False
            
        if self._has_tactical_threat(board):
            return False
            
        return True
    
    def _has_hanging_piece(self, board: chess.Board) -> bool:
        for square in chess.SQUARES:
            piece = board.piece_at(square)
            if piece is None:
                continue
            
            if board.is_attacked_by(not piece.color, square):
                attackers = board.attackers(not piece.color, square)
                defenders = board.attackers(piece.color, square)
                
                if len(attackers) > len(defenders):
                    return True
                    
                attacker_values = []
                for attacker_sq in attackers:
                    attacker = board.piece_at(attacker_sq)
                    if attacker:
                        attacker_values.append(self._piece_value(attacker.piece_type))
                
                defender_values = []
                for defender_sq in defenders:
                    defender = board.piece_at(defender_sq)
                    if defender:
                        defender_values.append(self._piece_value(defender.piece_type))
                
                piece_val = self._piece_value(piece.piece_type)
                if attacker_values and min(attacker_values) < piece_val:
                    return True
                    
        return False
    
    def _has_tactical_threat(self, board: chess.Board) -> bool:
        capture_moves = []
        check_moves = []
        
        for move in board.legal_moves:
            if board.is_capture(move):
                capture_moves.append(move)
            board.push(move)
            if board.is_check():
                check_moves.append(move)
            board.pop()
            
        if len(capture_moves) > 3:
            return True
            
        if len(check_moves) > 1:
            return True
            
        return False
    
    def _piece_value(self, piece_type: int) -> int:
        values = {
            chess.PAWN: 100,
            chess.KNIGHT: 320,
            chess.BISHOP: 340,
            chess.ROOK: 500,
            chess.QUEEN: 900,
            chess.KING: 20000
        }
        return values.get(piece_type, 0)
    
    def play_random_game(self, max_moves: int = 200) -> Tuple[List[Dict], str]:
        board = chess.Board()
        positions = []
        moves_made = 0
        
        while not board.is_game_over() and moves_made < max_moves:
            if moves_made >= self.MIN_MOVES_FOR_QUIET:
                if self.is_quiet_position(board):
                    result = self._get_expected_result(board)
                    positions.append({
                        "fen": board.fen(),
                        "result": result,
                        "move_number": moves_made,
                        "piece_count": len(board.piece_map())
                    })
            
            legal_moves = list(board.legal_moves)
            move = random.choice(legal_moves)
            board.push(move)
            moves_made += 1
            
        game_result = board.result() if board.is_game_over() else "*"
        self.games_played += 1
        self.total_moves += moves_made
        
        return positions, game_result
    
    def _get_expected_result(self, board: chess.Board) -> float:
        if board.is_checkmate():
            return 0.0 if board.turn == chess.WHITE else 1.0
            
        if board.is_stalemate() or board.is_insufficient_material():
            return 0.5
            
        if board.can_claim_draw():
            return 0.5
            
        return 0.5
    
    def generate_positions(self, num_positions: int, 
                          max_games: int = 100000,
                          progress_callback: Optional[callable] = None) -> List[Dict]:
        all_positions = []
        games = 0
        
        while len(all_positions) < num_positions and games < max_games:
            positions, _ = self.play_random_game()
            all_positions.extend(positions)
            games += 1
            
            if progress_callback and games % 100 == 0:
                progress_callback(len(all_positions), games)
        
        if len(all_positions) > num_positions:
            all_positions = random.sample(all_positions, num_positions)
            
        self.positions_generated = len(all_positions)
        return all_positions
    
    def generate_positions_with_results(self, num_positions: int,
                                        max_games: int = 100000,
                                        progress_callback: Optional[callable] = None) -> List[Dict]:
        all_positions = []
        games = 0
        
        while len(all_positions) < num_positions and games < max_games:
            board = chess.Board()
            game_positions = []
            moves_made = 0
            max_moves = 200
            
            while not board.is_game_over() and moves_made < max_moves:
                if moves_made >= self.MIN_MOVES_FOR_QUIET:
                    if self.is_quiet_position(board):
                        game_positions.append({
                            "fen": board.fen(),
                            "move_number": moves_made,
                            "piece_count": len(board.piece_map())
                        })
                
                legal_moves = list(board.legal_moves)
                move = random.choice(legal_moves)
                board.push(move)
                moves_made += 1
            
            game_result = board.result()
            result_value = self._parse_game_result(game_result)
            
            for pos in game_positions:
                pos["result"] = result_value
                all_positions.append(pos)
            
            games += 1
            self.games_played += 1
            self.total_moves += moves_made
            
            if progress_callback and games % 100 == 0:
                progress_callback(len(all_positions), games)
        
        if len(all_positions) > num_positions:
            all_positions = random.sample(all_positions, num_positions)
            
        self.positions_generated = len(all_positions)
        return all_positions
    
    def _parse_game_result(self, result: str) -> float:
        if result == "1-0":
            return 1.0
        elif result == "0-1":
            return 0.0
        elif result == "1/2-1/2":
            return 0.5
        else:
            return 0.5
    
    def get_statistics(self) -> Dict:
        return {
            "positions_generated": self.positions_generated,
            "games_played": self.games_played,
            "total_moves": self.total_moves,
            "avg_moves_per_game": self.total_moves / max(1, self.games_played),
            "avg_positions_per_game": self.positions_generated / max(1, self.games_played)
        }


def save_positions(positions: List[Dict], output_path: str, metadata: Optional[Dict] = None):
    data = {
        "version": "1.0",
        "created_at": datetime.now().isoformat(),
        "num_positions": len(positions),
        "metadata": metadata or {}
    }
    
    if positions and "result" in positions[0]:
        results = [p["result"] for p in positions]
        data["result_distribution"] = {
            "white_wins": sum(1 for r in results if r == 1.0),
            "black_wins": sum(1 for r in results if r == 0.0),
            "draws": sum(1 for r in results if r == 0.5)
        }
    
    data["positions"] = positions
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"已保存 {len(positions)} 个局面到 {output_path}")


def load_positions(input_path: str) -> List[Dict]:
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    positions = data.get("positions", [])
    print(f"从 {input_path} 加载了 {len(positions)} 个局面")
    return positions


def main():
    parser = argparse.ArgumentParser(description="生成安静局面用于 Texel Tuning")
    parser.add_argument("--num-positions", "-n", type=int, default=10000,
                       help="要生成的局面数量 (默认: 10000)")
    parser.add_argument("--output", "-o", type=str, default="quiet_positions.json",
                       help="输出文件路径 (默认: quiet_positions.json)")
    parser.add_argument("--seed", "-s", type=int, default=None,
                       help="随机种子 (用于可重复生成)")
    parser.add_argument("--max-games", type=int, default=100000,
                       help="最大游戏数限制 (默认: 100000)")
    parser.add_argument("--quiet", "-q", action="store_true",
                       help="静默模式，不显示进度")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("安静局面生成器 - Texel Tuning 数据准备")
    print("=" * 60)
    print(f"目标局面数: {args.num_positions}")
    print(f"输出文件: {args.output}")
    print(f"随机种子: {args.seed if args.seed else '随机'}")
    print()
    
    generator = QuietPositionGenerator(seed=args.seed)
    
    start_time = time.perf_counter()
    
    def progress_callback(num_positions, num_games):
        if not args.quiet:
            elapsed = time.perf_counter() - start_time
            rate = num_positions / elapsed if elapsed > 0 else 0
            print(f"\r已生成 {num_positions} 个局面 ({num_games} 局游戏, "
                  f"{rate:.1f} 局面/秒)", end="", flush=True)
    
    positions = generator.generate_positions_with_results(
        num_positions=args.num_positions,
        max_games=args.max_games,
        progress_callback=None if args.quiet else progress_callback
    )
    
    elapsed = time.perf_counter() - start_time
    
    if not args.quiet:
        print()
    
    print()
    print("=" * 60)
    print("生成统计")
    print("=" * 60)
    stats = generator.get_statistics()
    print(f"生成局面数: {stats['positions_generated']}")
    print(f"游戏局数: {stats['games_played']}")
    print(f"总步数: {stats['total_moves']}")
    print(f"平均每局步数: {stats['avg_moves_per_game']:.1f}")
    print(f"平均每局局面数: {stats['avg_positions_per_game']:.1f}")
    print(f"耗时: {elapsed:.2f} 秒")
    print(f"生成速率: {stats['positions_generated'] / elapsed:.1f} 局面/秒")
    
    metadata = {
        "generator": "QuietPositionGenerator",
        "seed": args.seed,
        "elapsed_seconds": elapsed,
        "statistics": stats
    }
    
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_positions(positions, str(output_path), metadata)
    
    print()
    print("=" * 60)
    print("结果分布")
    print("=" * 60)
    results = [p["result"] for p in positions]
    white_wins = sum(1 for r in results if r == 1.0)
    black_wins = sum(1 for r in results if r == 0.0)
    draws = sum(1 for r in results if r == 0.5)
    print(f"白胜: {white_wins} ({100*white_wins/len(positions):.1f}%)")
    print(f"黑胜: {black_wins} ({100*black_wins/len(positions):.1f}%)")
    print(f"和棋: {draws} ({100*draws/len(positions):.1f}%)")
    print("=" * 60)


if __name__ == "__main__":
    main()
