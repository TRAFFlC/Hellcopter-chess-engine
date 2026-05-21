"""
多条件验证套件 - Validation Suite

实现三重验证流程：
1. 自战验证：检查参数是否导致异常行为
2. 对抗老版本验证：确保新参数优于旧版本
3. 对抗多引擎验证：防止过拟合

双重时间控制验证：
- 标准验证（96+0.8s）
- 慢棋验证（300+2.0s）

异常行为检测：
- 检测"自杀式弃子"
- 检测异常低搜索深度
- 检测异常评估分数

使用方法:
    python validation_suite.py --config v1.5.0 --baseline v1.4.0
    python validation_suite.py --config v1.5.0 --quick
    python validation_suite.py --config v1.5.0 --full
"""

import os
import sys
import json
import subprocess
import shutil
import tempfile
import re
import time
import platform
import argparse
import math
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum

import chess

BASE_DIR = Path(__file__).parent.resolve()
CONFIGS_DIR = BASE_DIR / "configs"
VALIDATION_RESULTS_DIR = BASE_DIR / "validation_results"

TIME_CONTROLS = {
    "standard": {"base": 96, "increment": 0.8, "tc_string": "96+0.8"},
    "slow": {"base": 300, "increment": 2.0, "tc_string": "300+2.0"},
}

REFERENCE_ENGINES = {
    "sargon": {"dir": "test_engines/sargon 1163", "exe": "sargon-engine-static-link.exe", "proto": "uci", "elo": 1163},
    "rainman": {"dir": "test_engines/Rainman 1427", "exe": "rainman.exe", "proto": "xboard", "elo": 1427},
    "shallowblue": {"dir": "test_engines/ShallowBlue 1575", "exe": "shallowblue.exe", "proto": "uci", "elo": 1575},
    "tscp181": {"dir": "test_engines/TSCP 1607", "exe": "tscp181.exe", "proto": "xboard", "elo": 1607},
    "apollo": {"dir": "test_engines/Apollo 1663", "exe": "apollo.exe", "proto": "uci", "elo": 1663},
    "monarch": {"dir": "test_engines/Monarch 2005/Monarch(v1.7)", "exe": "Monarch(v1.7).exe", "proto": "uci", "elo": 2005},
}

TEST_POSITIONS = [
    ("初始局面", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
    ("意大利开局", "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 2 3"),
    ("西西里防御", "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"),
    ("复杂战术", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"),
    ("残局", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"),
    ("王翼攻击", "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"),
    ("后翼弃兵", "rnbqkb1r/p2ppppp/5n2/2p5/2P5/5N2/PP1PPPPP/RNBQKB1R w KQkq - 0 3"),
    ("中局复杂", "r1bq1rk1/ppp2ppp/2n1pn2/3p4/2PP4/2N1PN2/PP2BPPP/R1BQK2R w KQ - 0 7"),
]


class ValidationStatus(Enum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    SKIP = "skip"


@dataclass
class AnomalyRecord:
    anomaly_type: str
    description: str
    fen: str
    move: str
    severity: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GameResult:
    status: str
    moves: int
    nodes: int
    time_elapsed: float
    result: str
    anomalies: List[AnomalyRecord] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class MatchResult:
    wins: int
    losses: int
    draws: int
    total: int
    win_rate: float
    elo_diff: float
    games_data: List[Dict] = field(default_factory=list)


@dataclass
class ValidationResult:
    test_name: str
    status: ValidationStatus
    score: float
    details: Dict[str, Any]
    message: str
    anomalies: List[AnomalyRecord] = field(default_factory=list)


class AnomalyDetector:
    SUICIDE_PIECE_VALUES = {
        chess.PAWN: 100,
        chess.KNIGHT: 300,
        chess.BISHOP: 320,
        chess.ROOK: 480,
        chess.QUEEN: 900,
    }
    
    def __init__(self, min_depth: int = 4, max_score_change: int = 300):
        self.min_depth = min_depth
        self.max_score_change = max_score_change
        self.anomalies: List[AnomalyRecord] = []
    
    def detect_suicide_sacrifice(self, board: chess.Board, move: chess.Move, 
                                  prev_score: int, curr_score: int) -> Optional[AnomalyRecord]:
        if board.is_capture(move):
            captured_piece = board.piece_at(move.to_square)
            if captured_piece and captured_piece.piece_type != chess.PAWN:
                piece_value = self.SUICIDE_PIECE_VALUES.get(captured_piece.piece_type, 0)
                moving_piece = board.piece_at(move.from_square)
                if moving_piece:
                    moving_value = self.SUICIDE_PIECE_VALUES.get(moving_piece.piece_type, 0)
                    if moving_value >= piece_value * 2:
                        if prev_score > 0 and curr_score < -200:
                            return AnomalyRecord(
                                anomaly_type="suicide_sacrifice",
                                description=f"疑似自杀式弃子: {move.uci()}, 分数从 {prev_score} 降至 {curr_score}",
                                fen=board.fen(),
                                move=move.uci(),
                                severity="high",
                                details={"prev_score": prev_score, "curr_score": curr_score, 
                                        "piece_value": piece_value}
                            )
        return None
    
    def detect_low_search_depth(self, depth: int, nodes: int, time_limit: float) -> Optional[AnomalyRecord]:
        if depth < self.min_depth and nodes > 1000 and time_limit > 0.5:
            return AnomalyRecord(
                anomaly_type="low_search_depth",
                description=f"搜索深度异常低: depth={depth}, nodes={nodes}, time={time_limit}s",
                fen="",
                move="",
                severity="medium",
                details={"depth": depth, "nodes": nodes, "time_limit": time_limit}
            )
        return None
    
    def detect_abnormal_score(self, score: int, prev_score: int, move_num: int) -> Optional[AnomalyRecord]:
        if move_num < 10:
            return None
        score_change = abs(score - prev_score)
        if score_change > self.max_score_change:
            return AnomalyRecord(
                anomaly_type="abnormal_score_change",
                description=f"分数异常变化: {prev_score} -> {score} (变化 {score_change})",
                fen="",
                move="",
                severity="medium",
                details={"prev_score": prev_score, "score": score, "change": score_change}
            )
        return None
    
    def check_material_balance(self, board: chess.Board, score: int) -> Optional[AnomalyRecord]:
        material = 0
        for square in chess.SQUARES:
            piece = board.piece_at(square)
            if piece:
                value = self.SUICIDE_PIECE_VALUES.get(piece.piece_type, 0)
                if piece.color == chess.WHITE:
                    material += value
                else:
                    material -= value
        
        if board.turn == chess.BLACK:
            material = -material
        
        expected_score_range = abs(material) + 200
        if abs(score) > expected_score_range + 500:
            return AnomalyRecord(
                anomaly_type="score_material_mismatch",
                description=f"分数与物质不平衡不匹配: score={score}, material={material}",
                fen=board.fen(),
                move="",
                severity="low",
                details={"score": score, "material": material}
            )
        return None


class SelfPlayValidator:
    def __init__(self, time_limit: float = 0.1, max_depth: int = 8, max_games: int = 5):
        self.time_limit = time_limit
        self.max_depth = max_depth
        self.max_games = max_games
        self.anomaly_detector = AnomalyDetector()
    
    def run_single_game(self, engine, game_num: int) -> GameResult:
        board = chess.Board()
        moves = []
        nodes_total = 0
        start_time = time.perf_counter()
        position_history = []
        anomalies = []
        prev_score = 0
        
        while not board.is_game_over():
            try:
                fen = board.fen()
                hash_val = engine.compute_hash(fen)
                position_history.append(hash_val)
                
                uci_move, score, nodes = engine.search_with_score(
                    fen,
                    time_limit=self.time_limit,
                    max_depth=self.max_depth,
                    position_history=position_history,
                    use_smp=False
                )
                
                move = chess.Move.from_uci(uci_move)
                if move not in board.legal_moves:
                    return GameResult(
                        status="illegal_move",
                        moves=len(moves),
                        nodes=nodes_total,
                        time_elapsed=time.perf_counter() - start_time,
                        result="error",
                        error=f"非法走法: {uci_move}"
                    )
                
                anomaly = self.anomaly_detector.detect_suicide_sacrifice(
                    board, move, prev_score, score
                )
                if anomaly:
                    anomalies.append(anomaly)
                
                anomaly = self.anomaly_detector.check_material_balance(board, score)
                if anomaly:
                    anomalies.append(anomaly)
                
                if len(moves) > 0:
                    anomaly = self.anomaly_detector.detect_abnormal_score(
                        score, prev_score, len(moves)
                    )
                    if anomaly:
                        anomalies.append(anomaly)
                
                prev_score = -score
                board.push(move)
                moves.append(uci_move)
                nodes_total += nodes
                
                if len(moves) > 500:
                    return GameResult(
                        status="max_moves",
                        moves=len(moves),
                        nodes=nodes_total,
                        time_elapsed=time.perf_counter() - start_time,
                        result="draw",
                        anomalies=anomalies
                    )
                    
            except AssertionError as e:
                return GameResult(
                    status="assertion_failed",
                    moves=len(moves),
                    nodes=nodes_total,
                    time_elapsed=time.perf_counter() - start_time,
                    result="error",
                    error=str(e),
                    anomalies=anomalies
                )
            except Exception as e:
                return GameResult(
                    status="error",
                    moves=len(moves),
                    nodes=nodes_total,
                    time_elapsed=time.perf_counter() - start_time,
                    result="error",
                    error=str(e),
                    anomalies=anomalies
                )
        
        return GameResult(
            status="completed",
            moves=len(moves),
            nodes=nodes_total,
            time_elapsed=time.perf_counter() - start_time,
            result=board.result(),
            anomalies=anomalies
        )
    
    def validate(self, engine) -> ValidationResult:
        results = []
        total_anomalies = []
        passed = 0
        failed = 0
        
        for i in range(1, self.max_games + 1):
            result = self.run_single_game(engine, i)
            results.append(result)
            total_anomalies.extend(result.anomalies)
            
            if result.status == "completed":
                passed += 1
            else:
                failed += 1
        
        high_severity_count = sum(1 for a in total_anomalies if a.severity == "high")
        
        if failed > 0 or high_severity_count > 0:
            status = ValidationStatus.FAIL
            score = 0.0
        elif len(total_anomalies) > 0:
            status = ValidationStatus.WARNING
            score = 0.7
        else:
            status = ValidationStatus.PASS
            score = 1.0
        
        return ValidationResult(
            test_name="自战验证",
            status=status,
            score=score,
            details={
                "total_games": self.max_games,
                "passed": passed,
                "failed": failed,
                "anomaly_count": len(total_anomalies),
                "high_severity_count": high_severity_count,
            },
            message=f"完成 {passed}/{self.max_games} 局, 发现 {len(total_anomalies)} 个异常",
            anomalies=total_anomalies
        )


class VersionComparisonValidator:
    def __init__(self, baseline_config: str, tc: str = "96+0.8", rounds: int = 5):
        self.baseline_config = baseline_config
        self.tc = tc
        self.rounds = rounds
    
    def resolve_config_path(self, config_ref: str) -> Path:
        if Path(config_ref).is_absolute() and Path(config_ref).exists():
            return Path(config_ref)
        
        path = CONFIGS_DIR / f"{config_ref}.json"
        if path.exists():
            return path
        
        raise FileNotFoundError(f"配置文件未找到: {config_ref}")
    
    def find_cutechess(self) -> Path:
        candidates = [
            BASE_DIR / "cutechess-cli.exe",
            BASE_DIR / "cutechess-cli",
            Path("cutechess-cli"),
        ]
        for c in candidates:
            if c.exists():
                return c
        raise FileNotFoundError("cutechess-cli 未找到")
    
    def create_uci_adapter(self, temp_dir: Path, config_path: Path, label: str) -> Path:
        from config import load_and_resolve_config
        
        dest_params = temp_dir / "engine_params.json"
        resolved = load_and_resolve_config(str(config_path))
        with open(dest_params, "w", encoding="utf-8") as f:
            json.dump(resolved, f, indent=2)
        
        dest_params_fwd = str(dest_params).replace("\\", "/")
        base_dir_fwd = str(BASE_DIR).replace("\\", "/")
        script_path = temp_dir / f"uci_adapter_{label}.py"
        
        with open(script_path, "w", encoding="utf-8") as f:
            f.write("import os\n")
            f.write("import sys\n\n")
            f.write(f'os.environ["ENGINE_PARAMS"] = "{dest_params_fwd}"\n')
            f.write(f'sys.path.insert(0, "{base_dir_fwd}")\n\n')
            f.write("from uci_engine import UCIEngine\n\n")
            f.write('if __name__ == "__main__":\n')
            f.write("    uci = UCIEngine()\n")
            f.write("    uci.run()\n")
        
        return script_path
    
    def run_match(self, config_a: str, config_b: str) -> MatchResult:
        config_a_path = self.resolve_config_path(config_a)
        config_b_path = self.resolve_config_path(config_b)
        
        temp_dir_a = Path(tempfile.mkdtemp(prefix="val_match_a_"))
        temp_dir_b = Path(tempfile.mkdtemp(prefix="val_match_b_"))
        
        try:
            script_a = self.create_uci_adapter(temp_dir_a, config_a_path, "a")
            script_b = self.create_uci_adapter(temp_dir_b, config_b_path, "b")
            
            cutechess = self.find_cutechess()
            python_exe = sys.executable or "python"
            
            cmd = [
                str(cutechess),
                "-engine", f"name={config_a}", "proto=uci",
                f"cmd={python_exe}", f"arg={script_a}", f"dir={temp_dir_a}",
                "-engine", f"name={config_b}", "proto=uci",
                f"cmd={python_exe}", f"arg={script_b}", f"dir={temp_dir_b}",
                "-each", f"tc={self.tc}",
                "-rounds", str(self.rounds),
                "-repeat"
            ]
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            
            wins = losses = draws = 0
            for line in process.stdout:
                match = re.search(r"Score.*?:\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)", line)
                if match:
                    wins = int(match.group(1))
                    losses = int(match.group(2))
                    draws = int(match.group(3))
            
            process.wait()
            
            total = wins + losses + draws
            win_rate = (wins + 0.5 * draws) / total if total > 0 else 0.5
            
            if win_rate == 0:
                elo_diff = -1000
            elif win_rate == 1:
                elo_diff = 1000
            else:
                elo_diff = -400 * math.log((1 - win_rate) / win_rate) / math.log(10)
            
            return MatchResult(
                wins=wins,
                losses=losses,
                draws=draws,
                total=total,
                win_rate=win_rate,
                elo_diff=elo_diff
            )
        finally:
            shutil.rmtree(temp_dir_a, ignore_errors=True)
            shutil.rmtree(temp_dir_b, ignore_errors=True)
    
    def validate(self, new_config: str) -> ValidationResult:
        try:
            result = self.run_match(new_config, self.baseline_config)
            
            if result.elo_diff >= 0:
                status = ValidationStatus.PASS
                score = min(1.0, 0.5 + result.elo_diff / 100)
            elif result.elo_diff >= -20:
                status = ValidationStatus.WARNING
                score = 0.5
            else:
                status = ValidationStatus.FAIL
                score = 0.0
            
            return ValidationResult(
                test_name="版本对比验证",
                status=status,
                score=score,
                details={
                    "new_config": new_config,
                    "baseline_config": self.baseline_config,
                    "wins": result.wins,
                    "losses": result.losses,
                    "draws": result.draws,
                    "win_rate": result.win_rate,
                    "elo_diff": result.elo_diff,
                },
                message=f"Elo差值: {result.elo_diff:.1f} ({result.wins}-{result.draws}-{result.losses})"
            )
        except Exception as e:
            return ValidationResult(
                test_name="版本对比验证",
                status=ValidationStatus.FAIL,
                score=0.0,
                details={"error": str(e)},
                message=f"验证失败: {e}"
            )


class MultiEngineValidator:
    def __init__(self, opponents: List[str], tc: str = "96+0.8", rounds: int = 3):
        self.opponents = opponents
        self.tc = tc
        self.rounds = rounds
    
    def find_cutechess(self) -> Path:
        candidates = [
            BASE_DIR / "cutechess-cli.exe",
            BASE_DIR / "cutechess-cli",
        ]
        for c in candidates:
            if c.exists():
                return c
        raise FileNotFoundError("cutechess-cli 未找到")
    
    def check_engine_exists(self, opponent_key: str) -> Tuple[bool, str]:
        opp = REFERENCE_ENGINES.get(opponent_key)
        if not opp:
            return False, ""
        opp_exe = BASE_DIR / opp["dir"] / opp["exe"]
        return opp_exe.exists(), str(opp_exe)
    
    def create_uci_adapter(self, temp_dir: Path, config_path: Path) -> Path:
        from config import load_and_resolve_config
        
        dest_params = temp_dir / "engine_params.json"
        resolved = load_and_resolve_config(str(config_path))
        with open(dest_params, "w", encoding="utf-8") as f:
            json.dump(resolved, f, indent=2)
        
        dest_params_fwd = str(dest_params).replace("\\", "/")
        base_dir_fwd = str(BASE_DIR).replace("\\", "/")
        script_path = temp_dir / "uci_adapter.py"
        
        with open(script_path, "w", encoding="utf-8") as f:
            f.write("import os\n")
            f.write("import sys\n\n")
            f.write(f'os.environ["ENGINE_PARAMS"] = "{dest_params_fwd}"\n')
            f.write(f'sys.path.insert(0, "{base_dir_fwd}")\n\n')
            f.write("from uci_engine import UCIEngine\n\n")
            f.write('if __name__ == "__main__":\n')
            f.write("    uci = UCIEngine()\n")
            f.write("    uci.run()\n")
        
        return script_path
    
    def run_single_match(self, config_path: Path, opponent_key: str, uci_script: Path) -> MatchResult:
        exists, opp_exe = self.check_engine_exists(opponent_key)
        if not exists:
            return MatchResult(wins=0, losses=0, draws=0, total=0, win_rate=0, elo_diff=-1000)
        
        opp = REFERENCE_ENGINES[opponent_key]
        cutechess = self.find_cutechess()
        python_exe = sys.executable or "python"
        
        cmd = [
            str(cutechess),
            "-engine", f"name=Hellcopter", "proto=uci",
            f"cmd={python_exe}", f"arg={uci_script}", f"dir={uci_script.parent}",
            "-engine", f"name={opponent_key}", f"proto={opp['proto']}", f"cmd={opp_exe}",
            "-each", f"tc={self.tc}",
            "-rounds", str(self.rounds),
            "-repeat"
        ]
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        wins = losses = draws = 0
        for line in process.stdout:
            match = re.search(r"Score.*?:\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)", line)
            if match:
                wins = int(match.group(1))
                losses = int(match.group(2))
                draws = int(match.group(3))
        
        process.wait()
        
        total = wins + losses + draws
        win_rate = (wins + 0.5 * draws) / total if total > 0 else 0.5
        
        if win_rate == 0:
            elo_diff = -1000
        elif win_rate == 1:
            elo_diff = 1000
        else:
            elo_diff = -400 * math.log((1 - win_rate) / win_rate) / math.log(10)
        
        return MatchResult(wins=wins, losses=losses, draws=draws, total=total, 
                          win_rate=win_rate, elo_diff=elo_diff)
    
    def validate(self, config: str) -> ValidationResult:
        config_path = CONFIGS_DIR / f"{config}.json"
        if not config_path.exists():
            return ValidationResult(
                test_name="多引擎验证",
                status=ValidationStatus.FAIL,
                score=0.0,
                details={"error": f"配置未找到: {config}"},
                message=f"配置未找到: {config}"
            )
        
        temp_dir = Path(tempfile.mkdtemp(prefix="val_multi_"))
        try:
            uci_script = self.create_uci_adapter(temp_dir, config_path)
            
            results = {}
            total_elo_diff = 0
            valid_count = 0
            
            for opp in self.opponents:
                match_result = self.run_single_match(config_path, opp, uci_script)
                results[opp] = {
                    "wins": match_result.wins,
                    "losses": match_result.losses,
                    "draws": match_result.draws,
                    "win_rate": match_result.win_rate,
                    "elo_diff": match_result.elo_diff,
                    "opponent_elo": REFERENCE_ENGINES[opp]["elo"]
                }
                
                if match_result.total > 0:
                    total_elo_diff += match_result.elo_diff
                    valid_count += 1
            
            avg_elo_diff = total_elo_diff / valid_count if valid_count > 0 else -1000
            
            if avg_elo_diff >= 50:
                status = ValidationStatus.PASS
                score = min(1.0, 0.5 + avg_elo_diff / 200)
            elif avg_elo_diff >= 0:
                status = ValidationStatus.WARNING
                score = 0.5
            else:
                status = ValidationStatus.FAIL
                score = 0.0
            
            return ValidationResult(
                test_name="多引擎验证",
                status=status,
                score=score,
                details={
                    "opponents": results,
                    "average_elo_diff": avg_elo_diff,
                },
                message=f"平均Elo差值: {avg_elo_diff:.1f}"
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TimeControlValidator:
    def __init__(self, baseline_config: str, rounds: int = 5):
        self.baseline_config = baseline_config
        self.rounds = rounds
    
    def validate(self, config: str) -> ValidationResult:
        quick_validator = VersionComparisonValidator(
            self.baseline_config, 
            TIME_CONTROLS["quick"]["tc_string"], 
            self.rounds
        )
        slow_validator = VersionComparisonValidator(
            self.baseline_config, 
            TIME_CONTROLS["slow"]["tc_string"], 
            self.rounds
        )
        
        quick_result = quick_validator.validate(config)
        slow_result = slow_validator.validate(config)
        
        quick_score = quick_result.details.get("elo_diff", -1000)
        slow_score = slow_result.details.get("elo_diff", -1000)
        
        if quick_score >= 0 and slow_score >= 0:
            status = ValidationStatus.PASS
            score = min(1.0, 0.5 + (quick_score + slow_score) / 200)
        elif quick_score >= -20 or slow_score >= -20:
            status = ValidationStatus.WARNING
            score = 0.5
        else:
            status = ValidationStatus.FAIL
            score = 0.0
        
        return ValidationResult(
            test_name="双重时间控制验证",
            status=status,
            score=score,
            details={
                "quick_tc": TIME_CONTROLS["quick"]["tc_string"],
                "slow_tc": TIME_CONTROLS["slow"]["tc_string"],
                "quick_elo_diff": quick_score,
                "slow_elo_diff": slow_score,
                "quick_result": quick_result.details,
                "slow_result": slow_result.details,
            },
            message=f"标准: {quick_score:.1f} Elo, 慢棋: {slow_score:.1f} Elo"
        )


class ValidationReport:
    def __init__(self, config: str, baseline: str):
        self.config = config
        self.baseline = baseline
        self.timestamp = datetime.now().isoformat()
        self.results: List[ValidationResult] = []
    
    def add_result(self, result: ValidationResult):
        self.results.append(result)
    
    def get_overall_status(self) -> ValidationStatus:
        if any(r.status == ValidationStatus.FAIL for r in self.results):
            return ValidationStatus.FAIL
        if any(r.status == ValidationStatus.WARNING for r in self.results):
            return ValidationStatus.WARNING
        return ValidationStatus.PASS
    
    def get_overall_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.score for r in self.results) / len(self.results)
    
    def to_dict(self) -> Dict:
        return {
            "config": self.config,
            "baseline": self.baseline,
            "timestamp": self.timestamp,
            "overall_status": self.get_overall_status().value,
            "overall_score": self.get_overall_score(),
            "results": [
                {
                    "test_name": r.test_name,
                    "status": r.status.value,
                    "score": r.score,
                    "message": r.message,
                    "details": r.details,
                    "anomalies": [
                        {
                            "type": a.anomaly_type,
                            "description": a.description,
                            "severity": a.severity,
                            "fen": a.fen,
                            "move": a.move,
                        }
                        for a in r.anomalies
                    ]
                }
                for r in self.results
            ]
        }
    
    def save(self, path: Path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
    
    def print_summary(self):
        print("\n" + "=" * 70)
        print("验证报告摘要")
        print("=" * 70)
        print(f"配置: {self.config}")
        print(f"基线: {self.baseline}")
        print(f"时间: {self.timestamp}")
        print(f"总体状态: {self.get_overall_status().value.upper()}")
        print(f"总体得分: {self.get_overall_score():.2f}")
        print("-" * 70)
        
        for result in self.results:
            status_icon = {
                ValidationStatus.PASS: "✓",
                ValidationStatus.FAIL: "✗",
                ValidationStatus.WARNING: "⚠",
                ValidationStatus.SKIP: "-",
            }.get(result.status, "?")
            
            print(f"{status_icon} {result.test_name}: {result.message}")
            if result.anomalies:
                for anomaly in result.anomalies[:3]:
                    print(f"    - [{anomaly.severity}] {anomaly.description}")
        
        print("=" * 70)


class ValidationSuite:
    def __init__(self, config: str, baseline: str, quick_mode: bool = False):
        self.config = config
        self.baseline = baseline
        self.quick_mode = quick_mode
        self.report = ValidationReport(config, baseline)
    
    def run_self_play_validation(self) -> ValidationResult:
        print("\n[1/4] 运行自战验证...")
        
        import engine_wrapper as engine
        engine.reload_library()
        
        validator = SelfPlayValidator(
            time_limit=0.1 if self.quick_mode else 0.2,
            max_depth=6 if self.quick_mode else 8,
            max_games=3 if self.quick_mode else 5
        )
        
        result = validator.validate(engine)
        self.report.add_result(result)
        
        print(f"  结果: {result.status.value} - {result.message}")
        return result
    
    def run_version_comparison(self) -> ValidationResult:
        print("\n[2/4] 运行版本对比验证...")
        
        tc = TIME_CONTROLS["quick"]["tc_string"] if self.quick_mode else TIME_CONTROLS["slow"]["tc_string"]
        rounds = 3 if self.quick_mode else 5
        
        validator = VersionComparisonValidator(self.baseline, tc, rounds)
        result = validator.validate(self.config)
        self.report.add_result(result)
        
        print(f"  结果: {result.status.value} - {result.message}")
        return result
    
    def run_multi_engine_validation(self) -> ValidationResult:
        print("\n[3/4] 运行多引擎验证...")
        
        opponents = ["sargon", "shallowblue"] if self.quick_mode else ["sargon", "shallowblue", "tscp181", "apollo"]
        tc = TIME_CONTROLS["quick"]["tc_string"] if self.quick_mode else TIME_CONTROLS["slow"]["tc_string"]
        rounds = 2 if self.quick_mode else 3
        
        validator = MultiEngineValidator(opponents, tc, rounds)
        result = validator.validate(self.config)
        self.report.add_result(result)
        
        print(f"  结果: {result.status.value} - {result.message}")
        return result
    
    def run_time_control_validation(self) -> ValidationResult:
        print("\n[4/4] 运行双重时间控制验证...")
        
        if self.quick_mode:
            validator = VersionComparisonValidator(
                self.baseline, 
                TIME_CONTROLS["quick"]["tc_string"], 
                3
            )
            result = validator.validate(self.config)
            result.test_name = "双重时间控制验证 (标准模式)"
            self.report.add_result(result)
            print(f"  结果: {result.status.value} - {result.message}")
            return result
        
        validator = TimeControlValidator(self.baseline, rounds=5)
        result = validator.validate(self.config)
        self.report.add_result(result)
        
        print(f"  结果: {result.status.value} - {result.message}")
        return result
    
    def run_full_validation(self) -> ValidationReport:
        print("=" * 70)
        print("多条件验证套件")
        print("=" * 70)
        print(f"配置: {self.config}")
        print(f"基线: {self.baseline}")
        print(f"模式: {'快速' if self.quick_mode else '完整'}")
        print("=" * 70)
        
        self.run_self_play_validation()
        self.run_version_comparison()
        self.run_multi_engine_validation()
        self.run_time_control_validation()
        
        VALIDATION_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = VALIDATION_RESULTS_DIR / f"validation_{timestamp}_{self.config}.json"
        self.report.save(report_path)
        
        self.report.print_summary()
        print(f"\n验证报告已保存: {report_path}")
        
        return self.report


def main():
    parser = argparse.ArgumentParser(description="多条件验证套件")
    parser.add_argument("--config", "-c", required=True, help="待验证的配置版本 (如 v1.5.0)")
    parser.add_argument("--baseline", "-b", default="v1.4.0", help="基线配置版本 (默认: v1.4.0)")
    parser.add_argument("--quick", "-q", action="store_true", help="快速验证模式")
    parser.add_argument("--full", "-f", action="store_true", help="完整验证模式 (默认)")
    
    args = parser.parse_args()
    
    quick_mode = args.quick and not args.full
    
    suite = ValidationSuite(
        config=args.config,
        baseline=args.baseline,
        quick_mode=quick_mode
    )
    
    report = suite.run_full_validation()
    
    if report.get_overall_status() == ValidationStatus.FAIL:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
