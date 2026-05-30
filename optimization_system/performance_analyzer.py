"""
性能分析器模块

使用Velvet引擎对Hellcopter的对局进行深度分析，识别性能问题：
- 致命错误（评估偏差>500分）
- 性能问题（评估偏差100-500分）
- 搜索深度差异（>10层）
- 开局异常行为
- 残局转化失败
"""

import json
import os
import sys
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
from pathlib import Path

import chess
import chess.pgn


class IssueType(Enum):
    FATAL_ERROR = "致命错误"
    PERFORMANCE_ISSUE = "性能问题"
    SEARCH_ISSUE = "搜索问题"
    OPENING_ISSUE = "开局异常"
    ENDGAME_ISSUE = "残局问题"
    BUG = "BUG"
    OPTIMIZATION = "优化"


class ErrorSeverity(Enum):
    CRITICAL = "严重"
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


@dataclass
class PerformanceIssue:
    issue_type: IssueType
    severity: ErrorSeverity
    description: str
    fen: str
    move_number: int
    uci_move: str
    score_diff: int
    velvet_score: Optional[int] = None
    hellcopter_score: Optional[int] = None
    velvet_depth: int = 0
    hellcopter_depth: int = 0
    frequency: int = 1
    recommendations: List[str] = field(default_factory=list)


@dataclass
class AnalysisReport:
    report_id: str
    timestamp: str
    total_games: int
    total_moves: int
    issues: List[PerformanceIssue] = field(default_factory=list)
    opening_issues: List[PerformanceIssue] = field(default_factory=list)
    endgame_issues: List[PerformanceIssue] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "timestamp": self.timestamp,
            "total_games": self.total_games,
            "total_moves": self.total_moves,
            "issues": [
                {
                    "issue_type": i.issue_type.value,
                    "severity": i.severity.value,
                    "description": i.description,
                    "fen": i.fen,
                    "move_number": i.move_number,
                    "uci_move": i.uci_move,
                    "score_diff": i.score_diff,
                    "velvet_score": i.velvet_score,
                    "hellcopter_score": i.hellcopter_score,
                    "velvet_depth": i.velvet_depth,
                    "hellcopter_depth": i.hellcopter_depth,
                    "frequency": i.frequency,
                    "recommendations": i.recommendations,
                }
                for i in self.issues
            ],
            "opening_issues": [i.to_dict() for i in self.opening_issues],
            "endgame_issues": [i.to_dict() for i in self.endgame_issues],
            "summary": self.summary,
        }


class VelvetEngine:
    """Velvet引擎封装"""

    def __init__(self, engine_path: str, debug: bool = False):
        self.engine_path = engine_path
        self.debug = debug
        self.process: Optional[subprocess.Popen] = None

    def start(self):
        self.process = subprocess.Popen(
            [self.engine_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._send("uci")
        self._wait_for("uciok")
        self._send("isready")
        self._wait_for("readyok")

    def stop(self):
        if self.process:
            try:
                self._send("quit")
                self.process.wait(timeout=5)
            except:
                self.process.kill()
            self.process = None

    def _send(self, command: str):
        if self.debug:
            print(f"[VELVET IN] {command}")
        if self.process and self.process.stdin:
            self.process.stdin.write(command + "\n")
            self.process.stdin.flush()

    def _read_line(self, timeout: float = 10.0) -> str:
        if not self.process or not self.process.stdout:
            raise RuntimeError("Engine not running")
        import time
        start = time.time()
        while True:
            line = self.process.stdout.readline()
            if line:
                line = line.strip()
                if self.debug and line:
                    print(f"[VELVET OUT] {line}")
                return line
            if time.time() - start > timeout:
                raise TimeoutError("Engine response timeout")
            time.sleep(0.01)

    def _wait_for(self, target: str, timeout: float = 10.0) -> list:
        lines = []
        import time
        start = time.time()
        while True:
            line = self._read_line(timeout - (time.time() - start))
            lines.append(line)
            if target in line:
                return lines
            if time.time() - start > timeout:
                raise TimeoutError(f"Timeout waiting for {target}")

    def analyze(self, fen: str, depth: int = 20, time_limit: float = 0.5) -> dict:
        self._send(f"position fen {fen}")
        if time_limit > 0:
            time_ms = int(time_limit * 1000)
            self._send(f"go movetime {time_ms}")
        else:
            self._send(f"go depth {depth}")

        best_move = None
        score_cp = None
        score_mate = None
        is_mate = False
        max_depth = 0

        while True:
            line = self._read_line(30.0)
            if line.startswith("bestmove"):
                parts = line.split()
                if len(parts) >= 2:
                    best_move = parts[1]
                break
            if line.startswith("info") and "score" in line:
                depth_match = re.search(r"depth\s+(\d+)", line)
                if depth_match:
                    max_depth = int(depth_match.group(1))
                score_match = re.search(r"score\s+cp\s+(-?\d+)", line)
                mate_match = re.search(r"score\s+mate\s+(-?\d+)", line)
                if mate_match:
                    is_mate = True
                    score_mate = int(mate_match.group(1))
                    score_cp = 32767 if score_mate > 0 else -32767
                elif score_match:
                    is_mate = False
                    score_cp = int(score_match.group(1))

        return {
            "best_move": best_move,
            "score_cp": score_cp,
            "score_mate": score_mate,
            "is_mate": is_mate,
            "depth": max_depth,
        }


class PerformanceAnalyzer:
    """性能分析器"""

    def __init__(self, config_manager, velvet_path: str):
        self.config_manager = config_manager
        self.velvet_path = velvet_path
        self.velvet: Optional[VelvetEngine] = None
        self.issues: List[PerformanceIssue] = []
        self.opening_issues: List[PerformanceIssue] = []
        self.endgame_issues: List[PerformanceIssue] = []
        self.issue_counter: Dict[str, int] = {}

    def start(self):
        if not os.path.isfile(self.velvet_path):
            raise FileNotFoundError(f"Velvet引擎未找到: {self.velvet_path}")
        self.velvet = VelvetEngine(self.velvet_path)
        self.velvet.start()

    def stop(self):
        if self.velvet:
            self.velvet.stop()
            self.velvet = None

    def analyze_pgn(self, pgn_path: str, hellcopter_name: str = "Hellcopter",
                    depth: int = 20, time_limit: float = 0.5) -> AnalysisReport:
        """分析PGN文件中的所有对局"""
        self.issues = []
        self.opening_issues = []
        self.endgame_issues = []
        self.issue_counter = {}

        report_id = f"analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        total_games = 0
        total_moves = 0

        if not os.path.isfile(pgn_path):
            raise FileNotFoundError(f"PGN文件未找到: {pgn_path}")

        with open(pgn_path, encoding="latin-1") as f:
            while True:
                game = chess.pgn.read_game(f)
                if game is None:
                    break
                total_games += 1
                self._analyze_game(game, hellcopter_name, depth, time_limit)
                total_moves += len(list(game.mainline_moves()))

        report = AnalysisReport(
            report_id=report_id,
            timestamp=datetime.now().isoformat(),
            total_games=total_games,
            total_moves=total_moves,
            issues=self.issues,
            opening_issues=self.opening_issues,
            endgame_issues=self.endgame_issues,
            summary=self._generate_summary(),
        )

        return report

    def _analyze_game(self, game: chess.pgn.Game, hellcopter_name: str,
                      depth: int, time_limit: float):
        board = game.board()
        move_number = 0
        prev_score = 0

        white_player = game.headers.get("White", "")
        black_player = game.headers.get("Black", "")

        if hellcopter_name.lower() in white_player.lower():
            hellcopter_color = chess.WHITE
        elif hellcopter_name.lower() in black_player.lower():
            hellcopter_color = chess.BLACK
        else:
            return

        node = game
        while node.variations:
            next_node = node.variation(0)
            move = next_node.move
            move_number += 1

            if board.turn == hellcopter_color:
                self._analyze_move(board, move, move_number, prev_score,
                                   depth, time_limit, hellcopter_color)

            board.push(move)
            node = next_node

    def _analyze_move(self, board: chess.Board, move: chess.Move, move_number: int,
                      prev_score: int, depth: int, time_limit: float,
                      hellcopter_color: bool):
        fen = board.fen()
        is_opening = move_number <= 10
        is_endgame = self._is_endgame(board)

        try:
            velvet_result = self.velvet.analyze(fen, depth=depth, time_limit=time_limit)
        except Exception:
            return

        velvet_score = velvet_result["score_cp"]
        velvet_depth = velvet_result["depth"]
        velvet_best = velvet_result["best_move"]

        if velvet_score is None:
            return

        if board.turn == chess.BLACK:
            velvet_score = -velvet_score

        if move.uci() != velvet_best and velvet_best:
            try:
                self.velvet._send(f"position fen {fen} moves {move.uci()}")
                after_result = self.velvet.analyze(depth=depth, time_limit=time_limit)
                if after_result["score_cp"] is not None:
                    score_after = after_result["score_cp"]
                    if board.turn == chess.BLACK:
                        score_after = -score_after
                    score_diff = prev_score - score_after

                    issue = self._classify_issue(
                        score_diff, velvet_score, velvet_depth,
                        is_opening, is_endgame, fen, move_number,
                        move.uci(), velvet_best, velvet_result
                    )

                    if issue:
                        self._add_issue(issue)
            except Exception:
                pass

    def _is_endgame(self, board: chess.Board) -> bool:
        """判断是否为残局"""
        piece_count = len(board.piece_map())
        queens = len(board.pieces(chess.QUEEN, chess.WHITE)) + len(board.pieces(chess.QUEEN, chess.BLACK))
        return piece_count <= 10 or (piece_count <= 14 and queens == 0)

    def _classify_issue(self, score_diff: int, velvet_score: int, velvet_depth: int,
                        is_opening: bool, is_endgame: bool, fen: str,
                        move_number: int, uci_move: str, velvet_best: str,
                        velvet_result: dict) -> Optional[PerformanceIssue]:
        """分类问题类型"""
        if abs(score_diff) < 50:
            return None

        if velvet_result.get("is_mate") and velvet_result.get("score_mate", 0) > 0:
            issue_type = IssueType.FATAL_ERROR
            severity = ErrorSeverity.CRITICAL
            description = f"漏杀：Velvet发现{velvet_result['score_mate']}步杀"
            recommendations = ["检查搜索深度", "检查评估函数中的将杀检测", "优化着法排序"]
        elif abs(score_diff) >= 500:
            issue_type = IssueType.FATAL_ERROR
            severity = ErrorSeverity.CRITICAL
            description = f"致命错误：分数损失{abs(score_diff)}分"
            recommendations = ["检查评估函数", "检查搜索剪枝", "检查着法生成"]
        elif abs(score_diff) >= 100:
            issue_type = IssueType.PERFORMANCE_ISSUE
            severity = ErrorSeverity.HIGH if abs(score_diff) >= 300 else ErrorSeverity.MEDIUM
            description = f"性能问题：分数损失{abs(score_diff)}分"
            recommendations = ["优化搜索参数", "调整评估权重"]
        else:
            issue_type = IssueType.PERFORMANCE_ISSUE
            severity = ErrorSeverity.LOW
            description = f"轻微偏差：分数损失{abs(score_diff)}分"
            recommendations = ["微调参数"]

        if velvet_depth >= 20 and move_number > 10:
            recommendations.append("考虑增加搜索深度")

        if is_opening:
            issue_type = IssueType.OPENING_ISSUE
            recommendations.append("检查开局库配置")
        elif is_endgame:
            issue_type = IssueType.ENDGAME_ISSUE
            recommendations.append("检查残局评估函数")

        return PerformanceIssue(
            issue_type=issue_type,
            severity=severity,
            description=description,
            fen=fen,
            move_number=move_number,
            uci_move=uci_move,
            score_diff=abs(score_diff),
            velvet_score=velvet_score,
            velvet_depth=velvet_depth,
            recommendations=recommendations,
        )

    def _add_issue(self, issue: PerformanceIssue):
        key = f"{issue.issue_type.value}_{issue.fen}_{issue.uci_move}"
        if key in self.issue_counter:
            self.issue_counter[key] += 1
            for existing in self.issues:
                if existing.fen == issue.fen and existing.uci_move == issue.uci_move:
                    existing.frequency += 1
                    return
        else:
            self.issue_counter[key] = 1

        self.issues.append(issue)

        if issue.issue_type == IssueType.OPENING_ISSUE:
            self.opening_issues.append(issue)
        elif issue.issue_type == IssueType.ENDGAME_ISSUE:
            self.endgame_issues.append(issue)

    def _generate_summary(self) -> Dict[str, Any]:
        fatal_count = sum(1 for i in self.issues if i.issue_type == IssueType.FATAL_ERROR)
        perf_count = sum(1 for i in self.issues if i.issue_type == IssueType.PERFORMANCE_ISSUE)
        search_count = sum(1 for i in self.issues if i.issue_type == IssueType.SEARCH_ISSUE)
        opening_count = len(self.opening_issues)
        endgame_count = len(self.endgame_issues)

        return {
            "fatal_errors": fatal_count,
            "performance_issues": perf_count,
            "search_issues": search_count,
            "opening_issues": opening_count,
            "endgame_issues": endgame_count,
            "total_issues": len(self.issues),
            "unique_positions": len(self.issue_counter),
            "most_common_issue": self._get_most_common_issue(),
        }

    def _get_most_common_issue(self) -> Optional[str]:
        if not self.issue_counter:
            return None
        return max(self.issue_counter, key=self.issue_counter.get)

    def save_report(self, report: AnalysisReport, output_path: Optional[str] = None):
        if output_path is None:
            output_path = self.config_manager.get_output_path(
                f"performance_report_{report.report_id}.json"
            )
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"性能分析报告已保存: {output_path}")
