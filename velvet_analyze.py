#!/usr/bin/env python3
"""
Velvet引擎分析工具 - 分析Hellcopter的对局败着

使用Velvet引擎对PGN文件中的对局进行深度分析，
识别Hellcopter的错误着法并分析错误原因。
"""

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import chess
import chess.pgn


class ErrorType(Enum):
    MISSED_MATE = "漏杀"
    BIG_BLUNDER = "重大失误"
    MISTAKE = "失误"
    INACCURACY = "不准确"
    GOOD = "好棋"


@dataclass
class MoveAnalysis:
    move_number: int
    san_move: str
    uci_move: str
    fen_before: str
    fen_after: str
    hellcopter_score: Optional[int] = None
    velvet_best_move: Optional[str] = None
    velvet_score: Optional[int] = None
    velvet_depth: int = 0
    velvet_is_mate: bool = False
    velvet_mate_in: Optional[int] = None
    score_diff: int = 0
    error_type: ErrorType = ErrorType.GOOD
    error_reasons: list = field(default_factory=list)
    is_hellcopter_move: bool = False


@dataclass
class GameAnalysis:
    game_number: int
    hellcopter_color: Optional[str] = None
    opponent: Optional[str] = None
    result: Optional[str] = None
    moves: list = field(default_factory=list)
    blunders: list = field(default_factory=list)


class VelvetEngine:
    def __init__(self, engine_path: str, debug: bool = False):
        self.engine_path = engine_path
        self.debug = debug
        self.process: Optional[subprocess.Popen] = None
        self._buffer = ""

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
        start = time.time()
        while True:
            line = self._read_line(timeout - (time.time() - start))
            lines.append(line)
            if target in line:
                return lines
            if time.time() - start > timeout:
                raise TimeoutError(f"Timeout waiting for {target}")

    def new_game(self):
        self._send("ucinewgame")
        self._send("isready")
        self._wait_for("readyok")

    def set_position(self, fen: Optional[str] = None, moves: Optional[list] = None):
        cmd = "position"
        if fen:
            cmd += f" fen {fen}"
        else:
            cmd += " startpos"
        if moves:
            cmd += " moves " + " ".join(moves)
        self._send(cmd)

    def analyze(self, depth: int = 20, time_limit: float = 0.5) -> dict:
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


def parse_hellcopter_score(comment: str) -> Optional[int]:
    if not comment:
        return None
    mate_match = re.search(r"M(-?\d+)", comment)
    if mate_match:
        mate_in = int(mate_match.group(1))
        if mate_in > 0:
            return 32767 - (mate_in - 1) * 2
        else:
            return -32767 - (mate_in + 1) * 2
    cp_match = re.search(r"([+-]?\d+(?:\.\d+)?)", comment)
    if cp_match:
        val = float(cp_match.group(1))
        if abs(val) < 100:
            return int(val * 100)
        return int(val)
    return None


def determine_error_type(
    score_diff: int,
    velvet_is_mate: bool,
    velvet_mate_in: Optional[int],
    hellcopter_is_mate: bool = False,
) -> ErrorType:
    if velvet_is_mate and velvet_mate_in and velvet_mate_in > 0:
        if not hellcopter_is_mate:
            return ErrorType.MISSED_MATE
    if abs(score_diff) >= 300:
        return ErrorType.BIG_BLUNDER
    if abs(score_diff) >= 100:
        return ErrorType.MISTAKE
    if abs(score_diff) >= 50:
        return ErrorType.INACCURACY
    return ErrorType.GOOD


def analyze_error_reasons(
    analysis: MoveAnalysis,
    hellcopter_eval: Optional[int],
    velvet_eval: Optional[int],
    velvet_depth: int,
) -> list:
    reasons = []
    if analysis.error_type == ErrorType.MISSED_MATE:
        reasons.append(f"漏杀：Velvet发现{analysis.velvet_mate_in}步杀，但Hellcopter错过了")
        if hellcopter_eval is not None and velvet_eval is not None:
            eval_diff = abs(hellcopter_eval - velvet_eval)
            if eval_diff > 200:
                reasons.append(f"评估差异巨大（{eval_diff}分），可能评估函数存在问题")
        return reasons
    if hellcopter_eval is not None and velvet_eval is not None:
        eval_diff = abs(hellcopter_eval - velvet_eval)
        if eval_diff > 100:
            reasons.append(f"评估问题：Hellcopter评估({hellcopter_eval})与Velvet({velvet_eval})差异{eval_diff}分")
    if velvet_depth > 0:
        if velvet_depth >= 20:
            reasons.append(f"搜索深度：Velvet搜索深度{velvet_depth}，Hellcopter可能搜索深度不足")
    if analysis.velvet_best_move and analysis.uci_move != analysis.velvet_best_move:
        reasons.append(f"着法选择：Hellcopter选择{analysis.san_move}，Velvet推荐{chess.Move.from_uci(analysis.velvet_best_move).uci()}")
    if analysis.score_diff > 100:
        reasons.append(f"分数损失：{analysis.score_diff}分（约{analysis.score_diff/100:.1f}个兵）")
    if not reasons:
        reasons.append("轻微偏差，可能是搜索顺序或剪枝导致的")
    return reasons


def analyze_game(
    game: chess.pgn.Game,
    velvet: VelvetEngine,
    game_num: int,
    depth: int = 20,
    time_limit: float = 0.5,
    hellcopter_name: str = "Hellcopter",
) -> GameAnalysis:
    result = GameAnalysis(game_number=game_num)
    white_player = game.headers.get("White", "")
    black_player = game.headers.get("Black", "")
    if hellcopter_name.lower() in white_player.lower():
        result.hellcopter_color = "white"
        result.opponent = black_player
    elif hellcopter_name.lower() in black_player.lower():
        result.hellcopter_color = "black"
        result.opponent = white_player
    else:
        result.hellcopter_color = "white"
        result.opponent = black_player
    result.result = game.headers.get("Result", "*")
    board = game.board()
    move_number = 0
    prev_score = 0
    moves_list = []
    node = game
    while node.variations:
        next_node = node.variation(0)
        move = next_node.move
        moves_list.append(move.uci())
        node = next_node
    velvet.new_game()
    node = game
    while node.variations:
        next_node = node.variation(0)
        move = next_node.move
        san_move = board.san(move)
        uci_move = move.uci()
        fen_before = board.fen()
        move_number += 1
        is_hellcopter_move = False
        if result.hellcopter_color == "white" and board.turn == chess.WHITE:
            is_hellcopter_move = True
        elif result.hellcopter_color == "black" and board.turn == chess.BLACK:
            is_hellcopter_move = True
        comment = next_node.comment if hasattr(next_node, "comment") else ""
        hellcopter_score = parse_hellcopter_score(comment)
        analysis = MoveAnalysis(
            move_number=move_number,
            san_move=san_move,
            uci_move=uci_move,
            fen_before=fen_before,
            fen_after="",
            is_hellcopter_move=is_hellcopter_move,
            hellcopter_score=hellcopter_score,
        )
        if is_hellcopter_move:
            velvet.set_position(fen=fen_before)
            try:
                velvet_result = velvet.analyze(depth=depth, time_limit=time_limit)
                analysis.velvet_best_move = velvet_result["best_move"]
                analysis.velvet_score = velvet_result["score_cp"]
                analysis.velvet_depth = velvet_result["depth"]
                analysis.velvet_is_mate = velvet_result["is_mate"]
                analysis.velvet_mate_in = velvet_result["score_mate"]
                if velvet_result["is_mate"] and velvet_result["score_mate"]:
                    if velvet_result["score_mate"] > 0:
                        analysis.velvet_score = 32767
                    else:
                        analysis.velvet_score = -32767
                if analysis.velvet_score is not None:
                    if board.turn == chess.BLACK:
                        adjusted_velvet_score = -analysis.velvet_score
                    else:
                        adjusted_velvet_score = analysis.velvet_score
                    score_after = adjusted_velvet_score
                    if board.turn == chess.BLACK:
                        analysis.score_diff = prev_score - score_after
                    else:
                        analysis.score_diff = prev_score - score_after
                    if analysis.velvet_best_move and analysis.uci_move != analysis.velvet_best_move:
                        velvet.set_position(fen=fen_before)
                        velvet.set_position(fen=fen_before)
                        velvet._send(f"position fen {fen_before} moves {uci_move}")
                        after_result = velvet.analyze(depth=depth, time_limit=time_limit)
                        if after_result["score_cp"] is not None:
                            score_after_move = after_result["score_cp"]
                            if board.turn == chess.BLACK:
                                score_after_move = -score_after_move
                            analysis.score_diff = prev_score - score_after_move
                    analysis.error_type = determine_error_type(
                        analysis.score_diff,
                        analysis.velvet_is_mate,
                        analysis.velvet_mate_in,
                    )
                    analysis.error_reasons = analyze_error_reasons(
                        analysis,
                        hellcopter_score,
                        analysis.velvet_score,
                        analysis.velvet_depth,
                    )
                    prev_score = score_after
            except Exception as e:
                analysis.error_reasons.append(f"分析错误: {str(e)}")
        else:
            if hellcopter_score is not None:
                if board.turn == chess.BLACK:
                    prev_score = -hellcopter_score
                else:
                    prev_score = hellcopter_score
        board.push(move)
        analysis.fen_after = board.fen()
        result.moves.append(analysis)
        node = next_node
    for move in result.moves:
        if move.is_hellcopter_move and move.error_type != ErrorType.GOOD:
            result.blunders.append(move)
    result.blunders.sort(key=lambda m: (
        0 if m.error_type == ErrorType.MISSED_MATE else
        1 if m.error_type == ErrorType.BIG_BLUNDER else
        2 if m.error_type == ErrorType.MISTAKE else 3,
        -abs(m.score_diff)
    ))
    return result


def print_summary(analyses: list):
    print("\n" + "=" * 60)
    print("分析摘要")
    print("=" * 60)
    total_games = len(analyses)
    total_moves = sum(len(a.moves) for a in analyses)
    hellcopter_moves = sum(1 for a in analyses for m in a.moves if m.is_hellcopter_move)
    total_blunders = sum(len(a.blunders) for a in analyses)
    missed_mates = sum(1 for a in analyses for m in a.blunders if m.error_type == ErrorType.MISSED_MATE)
    big_blunders = sum(1 for a in analyses for m in a.blunders if m.error_type == ErrorType.BIG_BLUNDER)
    mistakes = sum(1 for a in analyses for m in a.blunders if m.error_type == ErrorType.MISTAKE)
    inaccuracies = sum(1 for a in analyses for m in a.blunders if m.error_type == ErrorType.INACCURACY)
    print(f"\n对局总数: {total_games}")
    print(f"总着法数: {total_moves}")
    print(f"Hellcopter着法数: {hellcopter_moves}")
    print(f"\n错误统计:")
    print(f"  漏杀: {missed_mates}")
    print(f"  重大失误(>300分): {big_blunders}")
    print(f"  失误(100-300分): {mistakes}")
    print(f"  不准确(50-100分): {inaccuracies}")
    print(f"  总计: {total_blunders}")
    print("\n" + "=" * 60)
    print("败着详情（按优先级排序）")
    print("=" * 60)
    for game_analysis in analyses:
        if not game_analysis.blunders:
            continue
        print(f"\n对局 {game_analysis.game_number}:")
        print(f"  Hellcopter执: {game_analysis.hellcopter_color}")
        print(f"  对手: {game_analysis.opponent}")
        print(f"  结果: {game_analysis.result}")
        print(f"\n  败着列表:")
        for i, blunder in enumerate(game_analysis.blunders, 1):
            priority = "【最高优先级】" if blunder.error_type == ErrorType.MISSED_MATE else ""
            print(f"\n    {i}. 第{blunder.move_number}着 {blunder.san_move} - {blunder.error_type.value} {priority}")
            print(f"       分数损失: {blunder.score_diff}分")
            if blunder.velvet_best_move:
                try:
                    board = chess.Board(blunder.fen_before)
                    best_san = board.san(chess.Move.from_uci(blunder.velvet_best_move))
                    print(f"       Velvet推荐: {best_san}")
                except:
                    print(f"       Velvet推荐: {blunder.velvet_best_move}")
            if blunder.velvet_is_mate and blunder.velvet_mate_in:
                print(f"       Velvet发现: {blunder.velvet_mate_in}步杀")
            print(f"       错误原因:")
            for reason in blunder.error_reasons:
                print(f"         - {reason}")


def save_json(analyses: list, output_path: str):
    output = []
    for game_analysis in analyses:
        game_data = {
            "game_number": game_analysis.game_number,
            "hellcopter_color": game_analysis.hellcopter_color,
            "opponent": game_analysis.opponent,
            "result": game_analysis.result,
            "moves": [],
            "blunders": []
        }
        for move in game_analysis.moves:
            move_data = {
                "move_number": move.move_number,
                "san_move": move.san_move,
                "uci_move": move.uci_move,
                "fen_before": move.fen_before,
                "fen_after": move.fen_after,
                "is_hellcopter_move": move.is_hellcopter_move,
                "hellcopter_score": move.hellcopter_score,
                "velvet_best_move": move.velvet_best_move,
                "velvet_score": move.velvet_score,
                "velvet_depth": move.velvet_depth,
                "velvet_is_mate": move.velvet_is_mate,
                "velvet_mate_in": move.velvet_mate_in,
                "score_diff": move.score_diff,
                "error_type": move.error_type.value if move.error_type != ErrorType.GOOD else None,
                "error_reasons": move.error_reasons
            }
            game_data["moves"].append(move_data)
        for blunder in game_analysis.blunders:
            blunder_data = {
                "move_number": blunder.move_number,
                "san_move": blunder.san_move,
                "uci_move": blunder.uci_move,
                "fen_before": blunder.fen_before,
                "error_type": blunder.error_type.value,
                "score_diff": blunder.score_diff,
                "velvet_best_move": blunder.velvet_best_move,
                "velvet_score": blunder.velvet_score,
                "velvet_mate_in": blunder.velvet_mate_in,
                "error_reasons": blunder.error_reasons
            }
            game_data["blunders"].append(blunder_data)
        output.append(game_data)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n详细报告已保存到: {output_path}")


def generate_blunder_memory(analysis_results: list, output_path: str):
    new_entries = []
    for game_analysis in analysis_results:
        for move in game_analysis.moves:
            if move.is_hellcopter_move and abs(move.score_diff) >= 300:
                if move.velvet_best_move and move.uci_move != move.velvet_best_move:
                    new_entries.append({
                        "fen": move.fen_before,
                        "bad_move": move.uci_move,
                        "good_move": move.velvet_best_move,
                        "score_loss": abs(move.score_diff),
                    })
    existing_entries = []
    if Path(output_path).exists():
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            if isinstance(existing_data, dict) and "entries" in existing_data:
                existing_entries = existing_data["entries"]
        except (json.JSONDecodeError, IOError):
            existing_entries = []
    existing_keys = {(e["fen"], e["bad_move"]) for e in existing_entries}
    merged_entries = list(existing_entries)
    for entry in new_entries:
        key = (entry["fen"], entry["bad_move"])
        if key not in existing_keys:
            merged_entries.append(entry)
            existing_keys.add(key)
    output_data = {
        "version": 1,
        "entries": merged_entries,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"\n败着记忆已保存到: {output_path} (共{len(merged_entries)}条记录，新增{len(merged_entries) - len(existing_entries)}条)")


def main():
    parser = argparse.ArgumentParser(
        description="使用Velvet引擎分析Hellcopter的对局败着"
    )
    parser.add_argument(
        "--pgn",
        required=True,
        help="PGN文件路径"
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=20,
        help="分析深度（默认20）"
    )
    parser.add_argument(
        "--time",
        type=float,
        default=0.5,
        help="每步分析时间（秒，默认0.5）"
    )
    parser.add_argument(
        "--output",
        default="analysis.json",
        help="输出JSON文件路径（默认analysis.json）"
    )
    parser.add_argument(
        "--engine",
        default=r"e:\world\python\chess\test_engines\Velvet\velvet-v8.1.1-x86_64-avx2.exe",
        help="Velvet引擎路径"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="显示UCI通信调试信息"
    )
    parser.add_argument(
        "--blunder-memory",
        default=None,
        help="败着记忆文件路径（如指定，分析完成后自动输出败着记忆）"
    )
    args = parser.parse_args()
    pgn_path = Path(args.pgn)
    if not pgn_path.exists():
        print(f"错误: PGN文件不存在: {pgn_path}")
        sys.exit(1)
    engine_path = Path(args.engine)
    if not engine_path.exists():
        print(f"错误: Velvet引擎不存在: {engine_path}")
        sys.exit(1)
    print(f"初始化Velvet引擎: {engine_path}")
    velvet = VelvetEngine(str(engine_path), debug=args.debug)
    try:
        velvet.start()
        print("引擎初始化成功")
        print(f"\n读取PGN文件: {pgn_path}")
        analyses = []
        game_num = 0
        with open(pgn_path, encoding="latin-1") as f:
            while True:
                game = chess.pgn.read_game(f)
                if game is None:
                    break
                game_num += 1
                print(f"\n分析对局 {game_num}...")
                try:
                    game_analysis = analyze_game(
                        game,
                        velvet,
                        game_num,
                        depth=args.depth,
                        time_limit=args.time,
                    )
                    analyses.append(game_analysis)
                    blunder_count = len(game_analysis.blunders)
                    print(f"  完成，发现 {blunder_count} 个败着")
                except Exception as e:
                    print(f"  分析失败: {e}")
        if not analyses:
            print("未找到有效对局")
            return
        print_summary(analyses)
        save_json(analyses, args.output)
        if args.blunder_memory:
            generate_blunder_memory(analyses, args.blunder_memory)
    finally:
        print("\n关闭引擎...")
        velvet.stop()


if __name__ == "__main__":
    main()
