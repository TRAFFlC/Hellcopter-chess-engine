#!/usr/bin/env python3
"""PGN对弈记录可视化工具 - 读取match_records中的pgn文件复原对弈记录"""

import json
import os
import re
import subprocess
import sys
import time
import threading
from pathlib import Path
from collections import defaultdict

from flask import Flask, jsonify, request, Response

import chess
import chess.pgn

BASE_DIR = Path(__file__).parent.resolve()
MATCH_RECORDS_DIR = BASE_DIR / "match_records"
VELVET_DEFAULT_PATH = BASE_DIR / "test_engines" / "Velvet" / "velvet-v8.1.1-x86_64-avx2.exe"

app = Flask(__name__)
app.config["VELVET_PATH"] = str(VELVET_DEFAULT_PATH)

_analysis_store = {}
_analysis_counter = [0]
_analysis_lock = threading.Lock()


class VelvetEngine:
    def __init__(self, engine_path):
        self.engine_path = str(engine_path)
        self.process = None

    def start(self):
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        self.process = subprocess.Popen(
            [self.engine_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            **kwargs,
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
            except Exception:
                self.process.kill()
            self.process = None

    def _send(self, cmd):
        if self.process and self.process.stdin:
            self.process.stdin.write(cmd + "\n")
            self.process.stdin.flush()

    def _read_line(self, timeout=30.0):
        if not self.process or not self.process.stdout:
            raise RuntimeError("Engine not running")
        start = time.time()
        while True:
            line = self.process.stdout.readline()
            if line:
                return line.strip()
            if time.time() - start > timeout:
                raise TimeoutError("Engine response timeout")
            time.sleep(0.005)

    def _wait_for(self, target, timeout=10.0):
        start = time.time()
        while True:
            line = self._read_line(timeout - (time.time() - start))
            if target in line:
                return
            if time.time() - start > timeout:
                raise TimeoutError(f"Timeout waiting for {target}")

    def new_game(self):
        self._send("ucinewgame")
        self._send("isready")
        self._wait_for("readyok")

    def analyze_position(self, fen, depth=20, time_limit=0.5):
        self._send(f"position fen {fen}")
        self._send("isready")
        self._wait_for("readyok")
        if time_limit > 0:
            self._send(f"go movetime {int(time_limit * 1000)}")
        else:
            self._send(f"go depth {depth}")

        best_move = None
        score_cp = None
        score_mate = None
        is_mate = False
        max_depth = 0

        while True:
            line = self._read_line(60.0)
            if line.startswith("bestmove"):
                parts = line.split()
                if len(parts) >= 2:
                    best_move = parts[1]
                break
            if line.startswith("info") and "score" in line:
                depth_match = re.search(r"depth\s+(\d+)", line)
                if depth_match:
                    max_depth = int(depth_match.group(1))
                mate_match = re.search(r"score\s+mate\s+(-?\d+)", line)
                score_match = re.search(r"score\s+cp\s+(-?\d+)", line)
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
            "is_mate": is_mate,
            "mate_in": score_mate,
            "depth": max_depth,
        }


def parse_score_from_comment(comment):
    if not comment:
        return None, None, None
    mate_match = re.search(r"M(-?\d+)", comment)
    if mate_match:
        mate_in = int(mate_match.group(1))
        score = 32767 if mate_in > 0 else -32767
        return score, None, mate_in
    score_match = re.search(r"([+-]?\d+(?:\.\d+)?)", comment)
    depth_match = re.search(r"/(\d+)", comment)
    time_match = re.search(r"([\d.]+)s", comment)
    depth = int(depth_match.group(1)) if depth_match else None
    move_time = float(time_match.group(1)) if time_match else None
    if score_match:
        val = float(score_match.group(1))
        if abs(val) < 100:
            score = int(val * 100)
        else:
            score = int(val)
        return score, depth, move_time
    return None, depth, move_time


def extract_opponent_info(dirname):
    name = dirname
    date_match = re.match(r"^(\d{8}_\d{6})-", name)
    date_str = ""
    if date_match:
        date_str = date_match.group(1)
        name = name[len(date_match.group(0)):]

    if "-vs-" in name:
        parts = name.split("-vs-")
        engine1 = parts[0].strip()
        engine2 = parts[1].strip() if len(parts) > 1 else ""
    elif "_vs_" in name:
        parts = name.split("_vs_")
        engine1 = parts[0].strip()
        engine2 = parts[1].strip() if len(parts) > 1 else ""
    else:
        parts = name.split("-")
        engine1 = parts[0] if parts else name
        engine2 = parts[-1] if len(parts) > 1 else ""

    return engine1, engine2, date_str


def list_matches():
    if not MATCH_RECORDS_DIR.exists():
        return {"opponents": {}}

    opponents = defaultdict(list)
    for entry in sorted(MATCH_RECORDS_DIR.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        pgn_file = entry / "match.pgn"
        if not pgn_file.exists():
            continue

        engine1, engine2, date_str = extract_opponent_info(entry.name)
        analysis_file = entry / "velvet_analysis.json"
        has_analysis = analysis_file.exists()

        game_count = 0
        try:
            with open(pgn_file, encoding="latin-1") as f:
                while True:
                    game = chess.pgn.read_game(f)
                    if game is None:
                        break
                    game_count += 1
        except Exception:
            pass

        match_info = {
            "dir_name": entry.name,
            "path": str(pgn_file.relative_to(BASE_DIR)).replace("\\", "/"),
            "engine1": engine1,
            "engine2": engine2,
            "date": date_str,
            "game_count": game_count,
            "has_analysis": has_analysis,
        }

        opp_key = engine2 if engine2 else engine1
        opponents[opp_key].append(match_info)

    sorted_opponents = {}
    for k in sorted(opponents.keys()):
        sorted_opponents[k] = opponents[k]

    return {"opponents": sorted_opponents}


def parse_pgn_games(pgn_path, game_index=None):
    full_path = BASE_DIR / pgn_path
    if not full_path.exists():
        return {"error": "PGN file not found"}

    games = []
    with open(full_path, encoding="latin-1") as f:
        while True:
            game = chess.pgn.read_game(f)
            if game is None:
                break
            games.append(game)

    total_count = len(games)
    if game_index is not None:
        if game_index < 0 or game_index >= total_count:
            return {"error": "Game index out of range"}
        games = [games[game_index]]

    result_games = []
    for idx, game in enumerate(games):
        gi = game_index if game_index is not None else idx
        headers = dict(game.headers)
        board = game.board()
        moves = []
        positions = [{"fen": board.fen(), "score_white": 0}]
        prev_score_white = 0

        node = game
        ply = 0
        while node.variations:
            next_node = node.variation(0)
            move = next_node.move
            san = board.san(move)
            uci = move.uci()
            fen_before = board.fen()
            is_white = board.turn == chess.WHITE
            comment = next_node.comment if hasattr(next_node, "comment") else ""

            raw_score, depth, move_time = parse_score_from_comment(comment)

            if raw_score is not None:
                if is_white:
                    score_white = raw_score
                else:
                    score_white = -raw_score
            else:
                score_white = prev_score_white

            ply += 1
            move_data = {
                "ply": ply,
                "move_number": (ply + 1) // 2,
                "san": san,
                "uci": uci,
                "fen_before": fen_before,
                "is_white": is_white,
                "raw_score": raw_score,
                "score_white": score_white,
                "depth": depth,
                "time": move_time,
                "comment": comment,
            }
            moves.append(move_data)

            board.push(move)
            positions.append({
                "fen": board.fen(),
                "score_white": score_white,
            })
            prev_score_white = score_white
            node = next_node

        result_games.append({
            "game_index": gi,
            "headers": headers,
            "moves": moves,
            "positions": positions,
            "initial_fen": game.board().fen(),
        })

    return {"games": result_games, "total_games": total_count}


def run_analysis_stream(analysis_id, pgn_tasks, depth, time_limit):
    velvet = VelvetEngine(app.config["VELVET_PATH"])
    total_to_analyze = sum(len(t["game_indices"]) for t in pgn_tasks)
    global_seq = 0
    try:
        velvet.start()
        for task in pgn_tasks:
            pgn_path = task["pgn_path"]
            game_indices = task["game_indices"]
            all_games_analysis = []

            for gi in game_indices:
                game_data = parse_pgn_games(pgn_path, game_index=gi)
                if "error" in game_data:
                    yield f"data: {json.dumps({'type': 'error', 'message': game_data['error'], 'pgn_path': pgn_path})}\n\n"
                    continue

                for game in game_data["games"]:
                    velvet.new_game()
                    yield f"data: {json.dumps({'type': 'game_start', 'game_index': game['game_index'], 'game_seq': global_seq, 'total_to_analyze': total_to_analyze, 'pgn_path': pgn_path})}\n\n"

                    game_analysis_moves = []
                    white_name = game["headers"].get("White", "")
                    black_name = game["headers"].get("Black", "")
                    hellcopter_color = ""
                    if "hellcopter" in white_name.lower():
                        hellcopter_color = "white"
                    elif "hellcopter" in black_name.lower():
                        hellcopter_color = "black"

                    prev_velvet_cp_white = None
                    positions = game["positions"]
                    for move_idx, move in enumerate(game["moves"]):
                        fen_before = move["fen_before"]
                        fen_after = positions[move_idx + 1]["fen"] if move_idx + 1 < len(positions) else None
                        try:
                            result_before = velvet.analyze_position(fen_before, depth=depth, time_limit=time_limit)
                            score_before_cp = result_before["score_cp"]
                            if score_before_cp is not None and not move["is_white"]:
                                score_before_cp = -score_before_cp

                            score_after_cp = None
                            if fen_after:
                                result_after = velvet.analyze_position(fen_after, depth=depth, time_limit=time_limit)
                                score_after_cp = result_after["score_cp"]
                                if score_after_cp is not None and not move["is_white"]:
                                    score_after_cp = -score_after_cp

                            is_hellcopter = False
                            if "hellcopter" in white_name.lower() and move["is_white"]:
                                is_hellcopter = True
                            elif "hellcopter" in black_name.lower() and not move["is_white"]:
                                is_hellcopter = True

                            score_diff = 0
                            if score_before_cp is not None and score_after_cp is not None:
                                score_diff = score_after_cp - score_before_cp

                            error_type = None
                            if abs(score_diff) >= 300:
                                error_type = "重大失误"
                            elif abs(score_diff) >= 100:
                                error_type = "失误"
                            elif abs(score_diff) >= 50:
                                error_type = "不准确"

                            game_analysis_moves.append({
                                "move_number": move["ply"],
                                "san_move": move["san"],
                                "uci_move": move["uci"],
                                "fen_before": fen_before,
                                "is_white_move": move["is_white"],
                                "is_hellcopter_move": is_hellcopter,
                                "velvet_best_move": result_before["best_move"],
                                "velvet_score": score_after_cp if score_after_cp is not None else score_before_cp,
                                "velvet_depth": result_before["depth"],
                                "velvet_is_mate": result_before["is_mate"],
                                "velvet_mate_in": result_before["mate_in"],
                                "score_diff": score_diff,
                                "error_type": error_type,
                            })

                            prev_velvet_cp_white = score_after_cp if score_after_cp is not None else score_before_cp

                            analysis_event = {
                                "type": "position",
                                "game_index": game["game_index"],
                                "ply": move["ply"],
                                "san": move["san"],
                                "is_white": move["is_white"],
                                "velvet_best_move": result_before["best_move"],
                                "velvet_score_cp": score_after_cp if score_after_cp is not None else score_before_cp,
                                "velvet_depth": result_before["depth"],
                                "velvet_is_mate": result_before["is_mate"],
                                "velvet_mate_in": result_before["mate_in"],
                                "score_diff": score_diff,
                                "error_type": error_type,
                                "is_hellcopter": is_hellcopter,
                                "pgn_path": pgn_path,
                            }
                            yield f"data: {json.dumps(analysis_event, ensure_ascii=False)}\n\n"
                        except Exception as e:
                            yield f"data: {json.dumps({'type': 'error', 'ply': move['ply'], 'message': str(e), 'pgn_path': pgn_path})}\n\n"

                    game_analysis = {
                        "game_number": game["game_index"] + 1,
                        "hellcopter_color": hellcopter_color,
                        "opponent": black_name if hellcopter_color == "white" else white_name,
                        "result": game["headers"].get("Result", "*"),
                        "score_perspective": "white",
                        "moves": game_analysis_moves,
                    }
                    all_games_analysis.append(game_analysis)

                    yield f"data: {json.dumps({'type': 'game_complete', 'game_index': game['game_index'], 'pgn_path': pgn_path})}\n\n"
                    global_seq += 1

            full_path = BASE_DIR / pgn_path
            analysis_path = full_path.parent / "velvet_analysis.json"
            existing = []
            if analysis_path.exists():
                try:
                    with open(analysis_path, encoding="utf-8") as f:
                        existing = json.load(f)
                except Exception:
                    existing = []
            existing_by_gn = {g.get("game_number"): g for g in existing}
            for ga in all_games_analysis:
                existing_by_gn[ga["game_number"]] = ga
            merged = sorted(existing_by_gn.values(), key=lambda x: x.get("game_number", 0))
            with open(analysis_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)

            yield f"data: {json.dumps({'type': 'pgn_complete', 'pgn_path': pgn_path, 'saved_to': str(analysis_path.relative_to(BASE_DIR)).replace(chr(92), '/')})}\n\n"

        yield f"data: {json.dumps({'type': 'batch_complete'})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    finally:
        velvet.stop()


@app.route("/")
def index():
    return Response(HTML_TEMPLATE, mimetype="text/html")


@app.route("/api/matches")
def api_matches():
    return jsonify(list_matches())


@app.route("/api/game")
def api_game():
    pgn_path = request.args.get("path", "")
    game_index = request.args.get("index", None)
    if game_index is not None:
        game_index = int(game_index)
    return jsonify(parse_pgn_games(pgn_path, game_index=game_index))


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.json or {}
    pgn_path = data.get("path", "")
    game_index = data.get("game_index", None)
    depth = data.get("depth", 20)
    time_limit = data.get("time_limit", 0.5)
    batch = data.get("batch", False)
    force = data.get("force", False)
    global_mode = data.get("global", False)

    pgn_tasks = []

    if global_mode:
        matches_data = list_matches()
        for opp, match_list in matches_data.get("opponents", {}).items():
            for m in match_list:
                pgn_p = m["path"]
                full_p = BASE_DIR / pgn_p
                if not full_p.exists():
                    continue
                game_data = parse_pgn_games(pgn_p)
                if "error" in game_data:
                    continue
                g_indices = list(range(game_data["total_games"]))
                if not force:
                    analysis_path = full_p.parent / "velvet_analysis.json"
                    if analysis_path.exists():
                        try:
                            with open(analysis_path, encoding="utf-8") as f:
                                existing = json.load(f)
                            analyzed_gns = {g.get("game_number") for g in existing if g.get("moves")}
                            g_indices = [i for i in g_indices if (i + 1) not in analyzed_gns]
                        except Exception:
                            pass
                if g_indices:
                    pgn_tasks.append({"pgn_path": pgn_p, "game_indices": g_indices})
    elif batch:
        full_path = BASE_DIR / pgn_path
        if not full_path.exists():
            return jsonify({"error": "PGN file not found"}), 404
        game_data = parse_pgn_games(pgn_path)
        if "error" in game_data:
            return jsonify({"error": game_data["error"]}), 400
        game_indices = list(range(game_data["total_games"]))
        if not force:
            analysis_path = full_path.parent / "velvet_analysis.json"
            if analysis_path.exists():
                try:
                    with open(analysis_path, encoding="utf-8") as f:
                        existing = json.load(f)
                    analyzed_gns = {g.get("game_number") for g in existing if g.get("moves")}
                    game_indices = [i for i in game_indices if (i + 1) not in analyzed_gns]
                except Exception:
                    pass
        if game_indices:
            pgn_tasks.append({"pgn_path": pgn_path, "game_indices": game_indices})
    else:
        full_path = BASE_DIR / pgn_path
        if not full_path.exists():
            return jsonify({"error": "PGN file not found"}), 404
        if game_index is None:
            game_index = 0
        pgn_tasks.append({"pgn_path": pgn_path, "game_indices": [game_index]})

    if not pgn_tasks:
        return jsonify({"analysis_id": None, "skipped": True, "message": "所有对局已分析"})

    with _analysis_lock:
        _analysis_counter[0] += 1
        analysis_id = str(_analysis_counter[0])

    _analysis_store[analysis_id] = {
        "pgn_tasks": pgn_tasks,
        "depth": depth,
        "time_limit": time_limit,
    }

    return jsonify({"analysis_id": analysis_id})


@app.route("/api/analyze_stream/<analysis_id>")
def api_analyze_stream(analysis_id):
    if analysis_id not in _analysis_store:
        return jsonify({"error": "Analysis not found"}), 404

    info = _analysis_store.pop(analysis_id)

    def generate():
        for chunk in run_analysis_stream(
            analysis_id,
            info["pgn_tasks"],
            info["depth"],
            info["time_limit"],
        ):
            yield chunk

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.route("/api/existing_analysis")
def api_existing_analysis():
    pgn_path = request.args.get("path", "")
    full_path = BASE_DIR / pgn_path
    analysis_path = full_path.parent / "velvet_analysis.json"
    if not analysis_path.exists():
        return jsonify({"has_analysis": False})

    try:
        with open(analysis_path, encoding="utf-8") as f:
            data = json.load(f)
        analyzed_game_numbers = [g.get("game_number") for g in data if g.get("moves")]
        return jsonify({"has_analysis": True, "data": data, "analyzed_game_numbers": analyzed_game_numbers})
    except Exception as e:
        return jsonify({"has_analysis": False, "error": str(e)})


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PGN 对弈可视化</title>
<style>
:root {
    --bg: #0f1419;
    --surface: #1a1f2e;
    --surface2: #232a3b;
    --border: #2d3548;
    --text: #e2e8f0;
    --text2: #8892a4;
    --accent: #6366f1;
    --accent2: #818cf8;
    --green: #22c55e;
    --yellow: #eab308;
    --orange: #f97316;
    --red: #ef4444;
    --board-light: #ecd5ac;
    --board-dark: #a87b50;
    --highlight: rgba(255,255,0,0.35);
    --best-move: rgba(0,150,255,0.35);
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    height: 100vh;
    overflow: hidden;
    display: flex;
    flex-direction: column;
}
.header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 16px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
}
.header h1 {
    font-size: 16px;
    font-weight: 600;
    letter-spacing: 0.5px;
}
.header-info {
    font-size: 13px;
    color: var(--text2);
}
.main {
    display: flex;
    flex: 1;
    overflow: hidden;
}
.sidebar {
    width: 260px;
    background: var(--surface);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
    overflow: hidden;
}
.sidebar-header {
    padding: 10px 12px;
    font-size: 13px;
    font-weight: 600;
    border-bottom: 1px solid var(--border);
    color: var(--text2);
    text-transform: uppercase;
    letter-spacing: 1px;
}
.match-list {
    flex: 1;
    overflow-y: auto;
    padding: 4px 0;
}
.match-list::-webkit-scrollbar { width: 6px; }
.match-list::-webkit-scrollbar-track { background: transparent; }
.match-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
.opponent-group { margin-bottom: 2px; }
.opponent-header {
    padding: 8px 12px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--accent2);
    user-select: none;
}
.opponent-header:hover { background: var(--surface2); }
.opponent-header .arrow {
    transition: transform 0.2s;
    font-size: 10px;
    color: var(--text2);
}
.opponent-header .arrow.open { transform: rotate(90deg); }
.opponent-header .count {
    margin-left: auto;
    font-size: 11px;
    color: var(--text2);
    font-weight: 400;
}
.match-item {
    padding: 6px 12px 6px 28px;
    font-size: 12px;
    cursor: pointer;
    color: var(--text2);
    border-left: 2px solid transparent;
    transition: all 0.15s;
}
.match-item:hover { background: var(--surface2); color: var(--text); }
.match-item.active {
    background: var(--surface2);
    color: var(--text);
    border-left-color: var(--accent);
}
.match-item .match-date { color: var(--text2); font-size: 11px; }
.match-item .match-engines { color: var(--text); font-weight: 500; }
.match-item .match-games { font-size: 11px; color: var(--text2); margin-top: 2px; }
.match-item .has-analysis {
    display: inline-block;
    width: 6px; height: 6px;
    background: var(--green);
    border-radius: 50%;
    margin-left: 4px;
    vertical-align: middle;
}
.center {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
.board-row {
    display: flex;
    flex: 1;
    min-height: 0;
}
.board-area {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 12px;
    flex-shrink: 0;
    min-width: 0;
    height: 100%;
}
.board-container {
    position: relative;
}
.board {
    display: grid;
    grid-template-columns: repeat(8, 1fr);
    border: 2px solid var(--border);
    border-radius: 2px;
    overflow: hidden;
    user-select: none;
}
.square {
    aspect-ratio: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: min(4.5vw, 42px);
    line-height: 1;
    position: relative;
}
.square.light { background: var(--board-light); }
.square.dark { background: var(--board-dark); }
.square.highlight { background: var(--highlight) !important; }
.square.best-move-highlight { background: var(--best-move) !important; }
.square .piece { text-shadow: none; }
.square .piece.white-piece {
    color: #ffffff;
    -webkit-text-stroke: 1px #333;
    filter: drop-shadow(0 1px 1px rgba(0,0,0,0.5));
}
.square .piece.black-piece {
    color: #1a1a1a;
    -webkit-text-stroke: 0.5px #555;
    filter: drop-shadow(0 1px 1px rgba(0,0,0,0.3));
}
.rank-label, .file-label {
    position: absolute;
    font-size: 10px;
    font-weight: 600;
    opacity: 0.6;
}
.rank-label { top: 1px; left: 2px; }
.file-label { bottom: 0; right: 2px; }
.square.light .rank-label, .square.light .file-label { color: var(--board-dark); }
.square.dark .rank-label, .square.dark .file-label { color: var(--board-light); }
.board-controls {
    display: flex;
    gap: 6px;
    margin-top: 8px;
    align-items: center;
}
.board-controls button {
    background: var(--surface2);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 4px 10px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
}
.board-controls button:hover { background: var(--border); }
.board-controls button.active { background: var(--accent); border-color: var(--accent); }
.move-panel {
    flex: 1;
    min-width: 260px;
    display: flex;
    flex-direction: column;
    border-left: 1px solid var(--border);
}
.game-tabs {
    display: flex;
    border-bottom: 1px solid var(--border);
    overflow-x: auto;
    flex-shrink: 0;
}
.game-tab {
    padding: 6px 14px;
    font-size: 12px;
    cursor: pointer;
    color: var(--text2);
    border-bottom: 2px solid transparent;
    white-space: nowrap;
    transition: all 0.15s;
}
.game-tab:hover { color: var(--text); background: var(--surface2); }
.game-tab.active { color: var(--accent2); border-bottom-color: var(--accent); }
.tab-analyzed {
    color: #22c55e;
    font-size: 10px;
    margin-left: 3px;
}
.move-list-container {
    flex: 1;
    overflow-y: auto;
    padding: 4px;
}
.move-list-container::-webkit-scrollbar { width: 6px; }
.move-list-container::-webkit-scrollbar-track { background: transparent; }
.move-list-container::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
.move-row {
    display: flex;
    align-items: stretch;
    font-size: 13px;
    font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
}
.move-number {
    width: 32px;
    text-align: right;
    padding: 3px 6px 3px 2px;
    color: var(--text2);
    font-size: 12px;
    flex-shrink: 0;
}
.move-cell {
    flex: 1;
    padding: 3px 6px;
    cursor: pointer;
    border-radius: 3px;
    transition: background 0.1s;
    display: flex;
    align-items: center;
    gap: 4px;
}
.move-cell:hover { background: var(--surface2); }
.move-cell.active { background: var(--accent); color: white; }
.move-cell .score-badge {
    font-size: 10px;
    padding: 0 3px;
    border-radius: 2px;
    font-weight: 600;
}
.move-cell .score-badge.blunder { background: var(--red); color: white; }
.move-cell .score-badge.mistake { background: var(--orange); color: white; }
.move-cell .score-badge.inaccuracy { background: var(--yellow); color: black; }
.move-cell .score-badge.good { background: var(--green); color: white; }
.move-cell .velvet-best {
    font-size: 10px;
    color: var(--accent2);
    opacity: 0.8;
}
.analysis-info {
    padding: 8px 12px;
    border-top: 1px solid var(--border);
    font-size: 12px;
    color: var(--text2);
    flex-shrink: 0;
    max-height: 80px;
    overflow-y: auto;
}
.analysis-info .best-move { color: var(--accent2); font-weight: 600; }
.analysis-info .error { color: var(--red); }
.chart-area {
    height: 130px;
    min-height: 80px;
    background: var(--surface);
    border-top: 1px solid var(--border);
    position: relative;
    flex-shrink: 0;
}
.chart-area canvas {
    width: 100%;
    height: 100%;
    display: block;
}
.chart-tooltip {
    position: absolute;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
    pointer-events: none;
    z-index: 100;
    display: none;
    box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}
.playback {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    padding: 6px 16px;
    background: var(--surface);
    border-top: 1px solid var(--border);
    flex-shrink: 0;
}
.playback button {
    background: var(--surface2);
    border: 1px solid var(--border);
    color: var(--text);
    width: 32px;
    height: 28px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
}
.playback button:hover { background: var(--border); }
.playback button.active { background: var(--accent); border-color: var(--accent); }
.playback select {
    background: var(--surface2);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 12px;
    margin-left: 8px;
}
.playback .ply-info {
    font-size: 12px;
    color: var(--text2);
    margin: 0 12px;
    min-width: 80px;
    text-align: center;
}
.analysis-controls {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-left: auto;
}
.analysis-controls button {
    width: auto;
    padding: 0 10px;
    font-size: 12px;
}
.analysis-controls #btnForceAnalyze {
    background: #5c2d2d;
    border-color: #8b3a3a;
}
.analysis-controls #btnForceAnalyze:hover:not(:disabled) {
    background: #7a3333;
}
.analysis-controls .analyzing {
    color: var(--yellow);
    font-size: 12px;
}
.progress-bar {
    height: 2px;
    background: var(--border);
    position: relative;
}
.progress-bar .fill {
    height: 100%;
    background: var(--accent);
    transition: width 0.3s;
    width: 0%;
}
.empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text2);
    font-size: 14px;
}
</style>
</head>
<body>
<div class="header">
    <h1>&#9822; PGN 对弈可视化</h1>
    <div class="header-info" id="headerInfo">选择左侧对局开始浏览</div>
</div>
<div class="main">
    <div class="sidebar">
        <div class="sidebar-header">对局记录</div>
        <div class="match-list" id="matchList"></div>
    </div>
    <div class="center">
        <div class="board-row">
            <div class="board-area">
                <div class="board-container">
                    <div class="board" id="board"></div>
                </div>
                <div class="board-controls">
                    <button onclick="flipBoard()" title="翻转棋盘">&#8693;</button>
                    <button onclick="toggleCoords()" id="btnCoords" class="active" title="坐标">a1</button>
                </div>
            </div>
            <div class="move-panel">
                <div class="game-tabs" id="gameTabs"></div>
                <div class="move-list-container" id="moveList">
                    <div class="empty-state">加载对局后显示着法列表</div>
                </div>
                <div class="analysis-info" id="analysisInfo"></div>
                <div class="chart-area">
                    <canvas id="scoreChart"></canvas>
                    <div class="chart-tooltip" id="chartTooltip"></div>
                </div>
            </div>
        </div>
        <div class="progress-bar" id="progressBar"><div class="fill" id="progressFill"></div></div>
        <div class="playback">
            <button onclick="goFirst()" title="起始">&#9198;</button>
            <button onclick="goPrev()" title="上一步">&#9664;</button>
            <button onclick="toggleAutoPlay()" id="btnPlay" title="自动播放">&#9654;</button>
            <button onclick="goNext()" title="下一步">&#9654;</button>
            <button onclick="goLast()" title="末尾">&#9197;</button>
            <div class="ply-info" id="plyInfo">0 / 0</div>
            <select id="speedSelect" onchange="changeSpeed()">
                <option value="3000">0.5x</option>
                <option value="1500">1x</option>
                <option value="750" selected>2x</option>
                <option value="400">4x</option>
                <option value="200">8x</option>
            </select>
            <div class="analysis-controls">
                <button onclick="startAnalysis()" id="btnAnalyze" title="Velvet分析当前对局">&#9881; 分析</button>
                <button onclick="startGlobalAnalysis(false)" id="btnBatchAnalyze" title="分析所有未分析的对局（所有PGN）">&#9881; 分析全部</button>
                <button onclick="startGlobalAnalysis(true)" id="btnForceAnalyze" title="强制重新分析所有对局（所有PGN）">&#8635; 重分析</button>
                <span class="analyzing" id="analyzingLabel" style="display:none">&#9699; 分析中...</span>
            </div>
        </div>
    </div>
</div>

<script>
const PIECES = {
    'K':'♚','Q':'♛','R':'♜','B':'♝','N':'♞','P':'♟',
    'k':'♚','q':'♛','r':'♜','b':'♝','n':'♞','p':'♟'
};

let state = {
    matches: null,
    currentPath: null,
    currentGameIndex: 0,
    totalGames: 0,
    game: null,
    currentPly: 0,
    boardFlipped: false,
    showCoords: true,
    autoPlayTimer: null,
    autoPlaySpeed: 750,
    analysisMap: {},
    eventSource: null,
    analyzing: false,
    analysisProgress: 0,
    lastMoveFrom: null,
    lastMoveTo: null,
    bestMoveFrom: null,
    bestMoveTo: null,
    analyzedGameNumbers: [],
};

function fenToBoard(fen) {
    const rows = fen.split(' ')[0].split('/');
    const board = [];
    for (const row of rows) {
        const boardRow = [];
        for (const ch of row) {
            if (ch >= '1' && ch <= '8') {
                for (let i = 0; i < parseInt(ch); i++) boardRow.push(null);
            } else {
                boardRow.push(ch);
            }
        }
        board.push(boardRow);
    }
    return board;
}

function uciToSquares(uci) {
    if (!uci || uci.length < 4) return null;
    const from = uci.substring(0, 2);
    const to = uci.substring(2, 4);
    return { from, to };
}

function squareToRC(sq) {
    const file = sq.charCodeAt(0) - 97;
    const rank = parseInt(sq[1]) - 1;
    return { row: 7 - rank, col: file };
}

function renderBoard() {
    const boardEl = document.getElementById('board');
    if (!state.game) {
        boardEl.innerHTML = '';
        return;
    }
    const pos = state.game.positions[state.currentPly];
    if (!pos) return;
    const board = fenToBoard(pos.fen);
    const boardRow = document.querySelector('.board-row');
    const rowH = boardRow.clientHeight;
    const rowW = boardRow.clientWidth;
    const movePanel = document.querySelector('.move-panel');
    const mpMinW = movePanel ? parseInt(getComputedStyle(movePanel).minWidth) || 260 : 260;
    const maxByH = rowH - 60;
    const maxByW = rowW - mpMinW - 24;
    const size = Math.min(maxByH, maxByW, 800);
    const sqSize = Math.max(Math.floor(size / 8), 20);
    boardEl.style.width = sqSize * 8 + 'px';
    boardEl.style.height = sqSize * 8 + 'px';
    boardEl.style.gridTemplateColumns = `repeat(8, ${sqSize}px)`;
    boardEl.style.gridTemplateRows = `repeat(8, ${sqSize}px)`;

    let html = '';
    for (let r = 0; r < 8; r++) {
        for (let c = 0; c < 8; c++) {
            const dr = state.boardFlipped ? 7 - r : r;
            const dc = state.boardFlipped ? 7 - c : c;
            const isLight = (dr + dc) % 2 === 0;
            const piece = board[dr][dc];
            let cls = isLight ? 'light' : 'dark';

            const sqFile = String.fromCharCode(97 + dc);
            const sqRank = (8 - dr).toString();
            const sqName = sqFile + sqRank;

            if (state.lastMoveFrom && sqName === state.lastMoveFrom) cls += ' highlight';
            if (state.lastMoveTo && sqName === state.lastMoveTo) cls += ' highlight';
            if (state.bestMoveFrom && sqName === state.bestMoveFrom) cls += ' best-move-highlight';
            if (state.bestMoveTo && sqName === state.bestMoveTo) cls += ' best-move-highlight';

            html += `<div class="square ${cls}" style="font-size:${Math.floor(sqSize*0.75)}px">`;
            if (piece) html += `<span class="piece ${piece === piece.toUpperCase() ? 'white-piece' : 'black-piece'}">${PIECES[piece]}</span>`;
            if (state.showCoords) {
                if (c === 0) html += `<span class="rank-label">${sqRank}</span>`;
                if (r === 7) html += `<span class="file-label">${sqFile}</span>`;
            }
            html += '</div>';
        }
    }
    boardEl.innerHTML = html;
}

function renderMoveList() {
    const container = document.getElementById('moveList');
    if (!state.game) {
        container.innerHTML = '<div class="empty-state">加载对局后显示着法列表</div>';
        return;
    }
    const moves = state.game.moves;
    let html = '';
    let moveNum = 0;
    for (let i = 0; i < moves.length; i++) {
        const m = moves[i];
        if (m.is_white) {
            moveNum = m.move_number;
            html += `<div class="move-row">`;
            html += `<div class="move-number">${moveNum}.</div>`;
            html += renderMoveCell(m, i);
            if (i + 1 < moves.length && !moves[i + 1].is_white) {
                html += renderMoveCell(moves[i + 1], i + 1);
                i++;
            } else {
                html += `<div class="move-cell"></div>`;
            }
            html += '</div>';
        }
    }
    container.innerHTML = html;
    scrollToActiveMove();
}

function renderMoveCell(m, idx) {
    let cls = 'move-cell';
    if (state.currentPly === m.ply) cls += ' active';

    let scoreBadge = '';
    const analysis = state.analysisMap[m.ply];
    if (analysis && analysis.error_type) {
        const et = analysis.error_type;
        let badgeCls = 'good';
        let label = '';
        if (et === '重大失误') { badgeCls = 'blunder'; label = '??'; }
        else if (et === '失误') { badgeCls = 'mistake'; label = '?'; }
        else if (et === '不准确') { badgeCls = 'inaccuracy'; label = '?!'; }
        if (label) scoreBadge = `<span class="score-badge ${badgeCls}">${label}</span>`;
    }

    let velvetBest = '';
    if (analysis && analysis.velvet_best_move && analysis.velvet_best_move !== m.uci) {
        velvetBest = `<span class="velvet-best" title="Velvet推荐">${analysis.velvet_best_move}</span>`;
    }

    return `<div class="${cls}" onclick="goToPly(${m.ply})" data-ply="${m.ply}">
        ${m.san}${scoreBadge}${velvetBest}
    </div>`;
}

function scrollToActiveMove() {
    const active = document.querySelector('.move-cell.active');
    if (active) active.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function renderGameTabs() {
    const tabs = document.getElementById('gameTabs');
    if (!state.totalGames || state.totalGames <= 1) {
        tabs.innerHTML = '';
        tabs.style.display = 'none';
        return;
    }
    tabs.style.display = 'flex';
    let html = '';
    for (let i = 0; i < state.totalGames; i++) {
        const cls = i === state.currentGameIndex ? 'active' : '';
        const analyzed = state.analyzedGameNumbers.includes(i + 1);
        const badge = analyzed ? '<span class="tab-analyzed">&#10003;</span>' : '';
        html += `<div class="game-tab ${cls}" onclick="loadGame(${i})">对局 ${i + 1}${badge}</div>`;
    }
    tabs.innerHTML = html;
}

function renderAnalysisInfo() {
    const el = document.getElementById('analysisInfo');
    if (!state.game || state.currentPly === 0) {
        el.innerHTML = '';
        return;
    }
    const m = state.game.moves[state.currentPly - 1];
    if (!m) { el.innerHTML = ''; return; }
    const analysis = state.analysisMap[state.currentPly];
    let html = '';
    if (analysis) {
        const who = m.is_white ? '白方' : '黑方';
        html += `<span class="best-move">Velvet推荐: ${analysis.velvet_best_move || '?'}</span>`;
        html += ` | 深度: ${analysis.velvet_depth}`;
        if (analysis.velvet_is_mate) {
            html += ` | <span class="error">杀棋: ${analysis.velvet_mate_in > 0 ? '+' : ''}${analysis.velvet_mate_in}</span>`;
        } else if (analysis.velvet_score_cp !== null) {
            const sc = (analysis.velvet_score_cp / 100).toFixed(2);
            html += ` | 评估: ${sc}`;
        }
        if (analysis.error_type) {
            html += ` | <span class="error">${analysis.error_type} (${(analysis.score_diff/100).toFixed(2)})</span>`;
        }
    } else {
        const sc = m.raw_score;
        if (sc !== null && sc !== undefined) {
            const disp = Math.abs(sc) > 500 ? (sc > 0 ? '+M' : '-M') : (sc / 100).toFixed(2);
            html += `${m.is_white ? '白方' : '黑方'}评估: ${disp}`;
        }
    }
    el.innerHTML = html;
}

function updatePlyInfo() {
    const total = state.game ? state.game.positions.length - 1 : 0;
    document.getElementById('plyInfo').textContent = `${state.currentPly} / ${total}`;
}

function goToPly(ply) {
    if (!state.game) return;
    const maxPly = state.game.positions.length - 1;
    ply = Math.max(0, Math.min(ply, maxPly));
    state.currentPly = ply;

    state.lastMoveFrom = null;
    state.lastMoveTo = null;
    state.bestMoveFrom = null;
    state.bestMoveTo = null;

    if (ply > 0) {
        const m = state.game.moves[ply - 1];
        const squares = uciToSquares(m.uci);
        if (squares) {
            state.lastMoveFrom = squares.from;
            state.lastMoveTo = squares.to;
        }
    }

    const analysis = state.analysisMap[ply];
    if (analysis && analysis.velvet_best_move) {
        const bsq = uciToSquares(analysis.velvet_best_move);
        if (bsq) {
            state.bestMoveFrom = bsq.from;
            state.bestMoveTo = bsq.to;
        }
    }

    renderBoard();
    renderMoveList();
    renderScoreChart();
    renderAnalysisInfo();
    updatePlyInfo();
}

function goNext() { goToPly(state.currentPly + 1); }
function goPrev() { goToPly(state.currentPly - 1); }
function goFirst() { goToPly(0); }
function goLast() { if (state.game) goToPly(state.game.positions.length - 1); }

function flipBoard() {
    state.boardFlipped = !state.boardFlipped;
    renderBoard();
}

function toggleCoords() {
    state.showCoords = !state.showCoords;
    document.getElementById('btnCoords').classList.toggle('active', state.showCoords);
    renderBoard();
}

let autoPlayTimer = null;
function toggleAutoPlay() {
    if (autoPlayTimer) {
        clearInterval(autoPlayTimer);
        autoPlayTimer = null;
        document.getElementById('btnPlay').textContent = '▶';
        document.getElementById('btnPlay').classList.remove('active');
    } else {
        const speed = parseInt(document.getElementById('speedSelect').value);
        autoPlayTimer = setInterval(() => {
            if (state.game && state.currentPly < state.game.positions.length - 1) {
                goNext();
            } else {
                toggleAutoPlay();
            }
        }, speed);
        document.getElementById('btnPlay').textContent = '⏸';
        document.getElementById('btnPlay').classList.add('active');
    }
}

function changeSpeed() {
    if (autoPlayTimer) {
        toggleAutoPlay();
        toggleAutoPlay();
    }
}

async function loadMatchList() {
    const resp = await fetch('/api/matches');
    state.matches = await resp.json();
    renderMatchList();
}

function renderMatchList() {
    const container = document.getElementById('matchList');
    const opponents = state.matches.opponents;
    let html = '';
    for (const [opp, matches] of Object.entries(opponents)) {
        html += `<div class="opponent-group">`;
        html += `<div class="opponent-header" onclick="toggleGroup(this)">
            <span class="arrow">&#9654;</span>
            ${opp}
            <span class="count">${matches.length}</span>
        </div>`;
        html += `<div class="opponent-matches" style="display:none">`;
        for (const m of matches) {
            const dateFormatted = m.date ? `${m.date.slice(0,4)}-${m.date.slice(4,6)}-${m.date.slice(6,8)}` : '';
            html += `<div class="match-item" data-path="${m.path.replace(/\\/g, '\\\\')}" onclick="selectMatch(this)">
                <div class="match-engines">${m.engine1} vs ${m.engine2}${m.has_analysis ? '<span class="has-analysis"></span>' : ''}</div>
                <div class="match-date">${dateFormatted}</div>
                <div class="match-games">${m.game_count} 局</div>
            </div>`;
        }
        html += '</div></div>';
    }
    container.innerHTML = html;
    const firstHeader = container.querySelector('.opponent-header');
    if (firstHeader) toggleGroup(firstHeader);
}

function toggleGroup(el) {
    const arrow = el.querySelector('.arrow');
    const matches = el.nextElementSibling;
    if (matches.style.display === 'none') {
        matches.style.display = 'block';
        arrow.classList.add('open');
    } else {
        matches.style.display = 'none';
        arrow.classList.remove('open');
    }
}

async function selectMatch(el) {
    document.querySelectorAll('.match-item').forEach(e => e.classList.remove('active'));
    el.classList.add('active');
    state.currentPath = el.dataset.path;
    state.analysisMap = {};
    await loadGame(0);
}

async function loadGame(index) {
    if (!state.currentPath) return;
    state.currentGameIndex = index;
    if (autoPlayTimer) toggleAutoPlay();

    try {
    const resp = await fetch(`/api/game?path=${encodeURIComponent(state.currentPath)}&index=${index}`);
    const data = await resp.json();

    if (data.error) {
        document.getElementById('headerInfo').textContent = '错误: ' + data.error;
        return;
    }

    state.totalGames = data.total_games;
    state.game = data.games[0];
    state.currentPly = 0;
    state.lastMoveFrom = null;
    state.lastMoveTo = null;
    state.bestMoveFrom = null;
    state.bestMoveTo = null;

    const h = state.game.headers;
    document.getElementById('headerInfo').textContent =
        `${h.White || '?'} vs ${h.Black || '?'} | ${h.Result || '*'} | ${h.Opening || ''}`;

    renderGameTabs();
    renderBoard();
    renderMoveList();
    renderScoreChart();
    renderAnalysisInfo();
    updatePlyInfo();

    loadExistingAnalysis();
    } catch(e) {
        console.error('加载对局失败:', e);
        document.getElementById('headerInfo').textContent = '加载失败: ' + e.message;
    }
}

async function loadExistingAnalysis() {
    if (!state.currentPath) return;
    const resp = await fetch(`/api/existing_analysis?path=${encodeURIComponent(state.currentPath)}`);
    const data = await resp.json();
    if (!data.has_analysis) {
        state.analyzedGameNumbers = [];
        renderGameTabs();
        return;
    }

    state.analyzedGameNumbers = data.analyzed_game_numbers || [];

    for (const game of data.data) {
        if (game.game_number !== state.currentGameIndex + 1) continue;
        const isWhitePerspective = game.score_perspective === 'white';
        for (const m of game.moves) {
            if (m.velvet_score === null && m.velvet_score !== 0 && !m.velvet_best_move) continue;
            let scoreWhite = m.velvet_score;
            if (!isWhitePerspective && scoreWhite !== null && scoreWhite !== undefined) {
                const isWhiteMove = m.is_white_move !== undefined
                    ? m.is_white_move
                    : m.move_number % 2 === 1;
                if (!isWhiteMove) {
                    scoreWhite = -scoreWhite;
                }
            }
            state.analysisMap[m.move_number] = {
                velvet_best_move: m.velvet_best_move,
                velvet_score_cp: scoreWhite,
                velvet_depth: m.velvet_depth,
                velvet_is_mate: m.velvet_is_mate,
                velvet_mate_in: m.velvet_mate_in,
                score_diff: m.score_diff,
                error_type: m.error_type,
            };
        }
    }
    renderMoveList();
    renderScoreChart();
    renderGameTabs();
}

async function startAnalysis() {
    if (state.analyzing) return;
    if (!state.currentPath) return;

    state.analyzing = true;
    document.getElementById('analyzingLabel').style.display = 'inline';
    document.getElementById('btnAnalyze').disabled = true;
    document.getElementById('btnBatchAnalyze').disabled = true;
    document.getElementById('btnForceAnalyze').disabled = true;

    const body = {
        path: state.currentPath,
        depth: 20,
        time_limit: 0.5,
        game_index: state.currentGameIndex,
    };

    const resp = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (data.skipped) {
        state.analyzing = false;
        const label = document.getElementById('analyzingLabel');
        label.textContent = '✓ 已分析';
        label.style.color = '#22c55e';
        label.style.display = 'inline';
        setTimeout(() => {
            label.textContent = '⟳ 分析中...';
            label.style.color = '';
            label.style.display = 'none';
        }, 2000);
        document.getElementById('btnAnalyze').disabled = false;
        document.getElementById('btnBatchAnalyze').disabled = false;
        document.getElementById('btnForceAnalyze').disabled = false;
        return;
    }
    if (data.error) {
        state.analyzing = false;
        document.getElementById('analyzingLabel').style.display = 'none';
        document.getElementById('btnAnalyze').disabled = false;
        document.getElementById('btnBatchAnalyze').disabled = false;
        document.getElementById('btnForceAnalyze').disabled = false;
        return;
    }

    const es = new EventSource(`/api/analyze_stream/${data.analysis_id}`);
    let totalPlies = state.game ? state.game.positions.length - 1 : 1;
    let processedPlies = 0;

    es.onmessage = function(event) {
        const d = JSON.parse(event.data);

        if (d.type === 'position') {
            if (d.game_index === state.currentGameIndex) {
                state.analysisMap[d.ply] = {
                    velvet_best_move: d.velvet_best_move,
                    velvet_score_cp: d.velvet_score_cp,
                    velvet_depth: d.velvet_depth,
                    velvet_is_mate: d.velvet_is_mate,
                    velvet_mate_in: d.velvet_mate_in,
                    score_diff: d.score_diff,
                    error_type: d.error_type,
                };
                processedPlies++;
                const pct = Math.min(100, Math.round((processedPlies / totalPlies) * 100));
                document.getElementById('progressFill').style.width = pct + '%';

                if (d.ply === state.currentPly) {
                    const bsq = uciToSquares(d.velvet_best_move);
                    if (bsq) {
                        state.bestMoveFrom = bsq.from;
                        state.bestMoveTo = bsq.to;
                    }
                    renderBoard();
                }
                renderMoveList();
                renderScoreChart();
                renderAnalysisInfo();
            }
        } else if (d.type === 'game_start') {
            if (d.game_index === state.currentGameIndex) {
                processedPlies = 0;
                totalPlies = state.game ? state.game.positions.length - 1 : 1;
            }
        } else if (d.type === 'game_complete') {
            if (d.game_index === state.currentGameIndex) {
                document.getElementById('progressFill').style.width = '100%';
                setTimeout(() => {
                    document.getElementById('progressFill').style.width = '0%';
                }, 1000);
            }
        } else if (d.type === 'batch_complete') {
            es.close();
            state.analyzing = false;
            document.getElementById('analyzingLabel').style.display = 'none';
            document.getElementById('btnAnalyze').disabled = false;
            document.getElementById('btnBatchAnalyze').disabled = false;
            document.getElementById('btnForceAnalyze').disabled = false;
            loadMatchList();
        } else if (d.type === 'error') {
            console.error('Analysis error:', d.message);
        }
    };

    es.onerror = function() {
        es.close();
        state.analyzing = false;
        document.getElementById('analyzingLabel').style.display = 'none';
        document.getElementById('btnAnalyze').disabled = false;
        document.getElementById('btnBatchAnalyze').disabled = false;
        document.getElementById('btnForceAnalyze').disabled = false;
        document.getElementById('progressFill').style.width = '0%';
    };
}

async function startGlobalAnalysis(force) {
    if (state.analyzing) return;

    state.analyzing = true;
    const label = document.getElementById('analyzingLabel');
    label.textContent = '⟳ 准备全局分析...';
    label.style.color = '';
    label.style.display = 'inline';
    document.getElementById('btnAnalyze').disabled = true;
    document.getElementById('btnBatchAnalyze').disabled = true;
    document.getElementById('btnForceAnalyze').disabled = true;

    const body = {
        depth: 20,
        time_limit: 0.5,
        global: true,
    };
    if (force) body.force = true;

    const resp = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (data.skipped) {
        state.analyzing = false;
        label.textContent = '✓ 全部已分析';
        label.style.color = '#22c55e';
        label.style.display = 'inline';
        setTimeout(() => {
            label.textContent = '⟳ 分析中...';
            label.style.color = '';
            label.style.display = 'none';
        }, 2000);
        document.getElementById('btnAnalyze').disabled = false;
        document.getElementById('btnBatchAnalyze').disabled = false;
        document.getElementById('btnForceAnalyze').disabled = false;
        return;
    }
    if (data.error) {
        state.analyzing = false;
        label.style.display = 'none';
        document.getElementById('btnAnalyze').disabled = false;
        document.getElementById('btnBatchAnalyze').disabled = false;
        document.getElementById('btnForceAnalyze').disabled = false;
        return;
    }

    const es = new EventSource(`/api/analyze_stream/${data.analysis_id}`);
    let totalPlies = state.game ? state.game.positions.length - 1 : 1;
    let processedPlies = 0;

    es.onmessage = function(event) {
        const d = JSON.parse(event.data);
        const isCurrentPgn = d.pgn_path === state.currentPath;

        if (d.type === 'position') {
            if (isCurrentPgn && d.game_index === state.currentGameIndex) {
                state.analysisMap[d.ply] = {
                    velvet_best_move: d.velvet_best_move,
                    velvet_score_cp: d.velvet_score_cp,
                    velvet_depth: d.velvet_depth,
                    velvet_is_mate: d.velvet_is_mate,
                    velvet_mate_in: d.velvet_mate_in,
                    score_diff: d.score_diff,
                    error_type: d.error_type,
                };
                processedPlies++;
                const pct = Math.min(100, Math.round((processedPlies / totalPlies) * 100));
                document.getElementById('progressFill').style.width = pct + '%';

                if (d.ply === state.currentPly) {
                    const bsq = uciToSquares(d.velvet_best_move);
                    if (bsq) {
                        state.bestMoveFrom = bsq.from;
                        state.bestMoveTo = bsq.to;
                    }
                    renderBoard();
                }
                renderMoveList();
                renderScoreChart();
                renderAnalysisInfo();
            }
        } else if (d.type === 'game_start') {
            if (isCurrentPgn && d.game_index === state.currentGameIndex) {
                processedPlies = 0;
                totalPlies = state.game ? state.game.positions.length - 1 : 1;
            }
            if (d.total_to_analyze > 1) {
                label.textContent = `⟳ 全局分析 ${d.game_seq + 1}/${d.total_to_analyze}...`;
            }
        } else if (d.type === 'game_complete') {
            if (isCurrentPgn) {
                const gn = d.game_index + 1;
                if (!state.analyzedGameNumbers.includes(gn)) {
                    state.analyzedGameNumbers.push(gn);
                }
                renderGameTabs();
            }
            if (isCurrentPgn && d.game_index === state.currentGameIndex) {
                document.getElementById('progressFill').style.width = '100%';
                setTimeout(() => {
                    document.getElementById('progressFill').style.width = '0%';
                }, 1000);
            }
        } else if (d.type === 'pgn_complete') {
            if (isCurrentPgn) {
                loadExistingAnalysis();
            }
        } else if (d.type === 'batch_complete') {
            es.close();
            state.analyzing = false;
            label.textContent = '✓ 全局分析完成';
            label.style.color = '#22c55e';
            label.style.display = 'inline';
            document.getElementById('btnAnalyze').disabled = false;
            document.getElementById('btnBatchAnalyze').disabled = false;
            document.getElementById('btnForceAnalyze').disabled = false;
            loadMatchList();
            setTimeout(() => {
                label.textContent = '⟳ 分析中...';
                label.style.color = '';
                label.style.display = 'none';
            }, 5000);
        } else if (d.type === 'error') {
            console.error('Analysis error:', d.message);
        }
    };

    es.onerror = function() {
        es.close();
        state.analyzing = false;
        label.style.display = 'none';
        document.getElementById('btnAnalyze').disabled = false;
        document.getElementById('btnBatchAnalyze').disabled = false;
        document.getElementById('btnForceAnalyze').disabled = false;
        document.getElementById('progressFill').style.width = '0%';
    };
}

function renderScoreChart() {
    const canvas = document.getElementById('scoreChart');
    const container = canvas.parentElement;
    const dpr = window.devicePixelRatio || 1;
    const rect = container.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    canvas.style.width = rect.width + 'px';
    canvas.style.height = rect.height + 'px';

    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    const W = rect.width;
    const H = rect.height;

    ctx.fillStyle = '#1a1f2e';
    ctx.fillRect(0, 0, W, H);

    if (!state.game || state.game.positions.length < 2) return;

    const positions = state.game.positions;
    const moves = state.game.moves;
    const n = positions.length;

    const padL = 50, padR = 20, padT = 15, padB = 25;
    const chartW = W - padL - padR;
    const chartH = H - padT - padB;

    let scores = positions.map(p => p.score_white);
    for (let i = 0; i < n; i++) {
        const analysis = state.analysisMap[i];
        if (analysis && analysis.velvet_score_cp !== null && analysis.velvet_score_cp !== undefined) {
            scores[i] = analysis.velvet_score_cp;
        }
    }

    const CLAMP = 1500;
    const clamped = scores.map(s => Math.max(-CLAMP, Math.min(CLAMP, s)));
    const maxAbs = Math.max(200, ...clamped.map(s => Math.abs(s)));

    function xForPly(ply) {
        return padL + (ply / Math.max(1, n - 1)) * chartW;
    }
    function yForScore(sc) {
        const norm = sc / maxAbs;
        return padT + chartH / 2 - norm * (chartH / 2);
    }

    ctx.strokeStyle = '#2d3548';
    ctx.lineWidth = 0.5;
    const gridLines = [-1000, -500, 0, 500, 1000].filter(v => Math.abs(v) <= maxAbs);
    for (const v of gridLines) {
        const y = yForScore(v);
        ctx.beginPath();
        ctx.moveTo(padL, y);
        ctx.lineTo(W - padR, y);
        ctx.stroke();
    }

    ctx.fillStyle = '#8892a4';
    ctx.font = '10px system-ui';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (const v of gridLines) {
        const y = yForScore(v);
        const label = v === 0 ? '0' : (v > 0 ? '+' : '') + (v / 100).toFixed(1);
        ctx.fillText(label, padL - 6, y);
    }

    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    const step = Math.max(1, Math.floor(n / 15));
    for (let i = 0; i < n; i += step) {
        const x = xForPly(i);
        const moveNum = Math.floor(i / 2) + (i % 2 === 0 ? 1 : 0.5);
        if (i % 2 === 0 || i === n - 1) {
            ctx.fillText(Math.ceil(i / 2).toString(), x, H - padB + 6);
        }
    }

    ctx.beginPath();
    ctx.moveTo(xForPly(0), yForScore(clamped[0]));
    for (let i = 1; i < n; i++) {
        ctx.lineTo(xForPly(i), yForScore(clamped[i]));
    }
    ctx.strokeStyle = '#6366f1';
    ctx.lineWidth = 2;
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(xForPly(0), yForScore(0));
    ctx.lineTo(xForPly(0), yForScore(clamped[0]));
    for (let i = 1; i < n; i++) {
        ctx.lineTo(xForPly(i), yForScore(clamped[i]));
    }
    ctx.lineTo(xForPly(n - 1), yForScore(0));
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, padT, 0, padT + chartH);
    grad.addColorStop(0, 'rgba(34,197,94,0.25)');
    grad.addColorStop(0.5, 'rgba(100,100,100,0.05)');
    grad.addColorStop(1, 'rgba(239,68,68,0.25)');
    ctx.fillStyle = grad;
    ctx.fill();

    for (let i = 1; i < n; i++) {
        const analysis = state.analysisMap[i];
        if (analysis && analysis.error_type) {
            const x = xForPly(i);
            const y = yForScore(clamped[i]);
            let color = '#ef4444';
            let radius = 5;
            if (analysis.error_type === '不准确') { color = '#eab308'; radius = 4; }
            else if (analysis.error_type === '失误') { color = '#f97316'; radius = 4; }
            ctx.beginPath();
            ctx.arc(x, y, radius, 0, Math.PI * 2);
            ctx.fillStyle = color;
            ctx.fill();
            ctx.strokeStyle = '#0f1419';
            ctx.lineWidth = 1.5;
            ctx.stroke();
        }
    }

    if (state.currentPly >= 0 && state.currentPly < n) {
        const x = xForPly(state.currentPly);
        ctx.beginPath();
        ctx.moveTo(x, padT);
        ctx.lineTo(x, padT + chartH);
        ctx.strokeStyle = 'rgba(255,255,255,0.5)';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 3]);
        ctx.stroke();
        ctx.setLineDash([]);

        const y = yForScore(clamped[state.currentPly]);
        ctx.beginPath();
        ctx.arc(x, y, 5, 0, Math.PI * 2);
        ctx.fillStyle = '#fff';
        ctx.fill();
        ctx.strokeStyle = '#6366f1';
        ctx.lineWidth = 2;
        ctx.stroke();
    }

    canvas._chartData = { padL, padR, padT, padB, chartW, chartH, n, maxAbs, clamped, scores, xForPly, yForScore };
}

function initChartInteraction() {
    const canvas = document.getElementById('scoreChart');
    const tooltip = document.getElementById('chartTooltip');
    let dragging = false;

    function getPlyFromEvent(e) {
        if (!canvas._chartData || !state.game) return -1;
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const cd = canvas._chartData;
        const ply = Math.round(((mx - cd.padL) / cd.chartW) * (cd.n - 1));
        return Math.max(0, Math.min(ply, cd.n - 1));
    }

    function showTooltip(e) {
        if (!canvas._chartData || !state.game) return;
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const cd = canvas._chartData;

        const ply = Math.round(((mx - cd.padL) / cd.chartW) * (cd.n - 1));
        if (ply < 0 || ply >= cd.n) {
            tooltip.style.display = 'none';
            return;
        }

        const score = cd.scores[ply];
        const scoreStr = Math.abs(score) > 3000 ? (score > 0 ? '+M' : '-M') : ((score / 100).toFixed(2));
        let moveStr = '';
        if (ply > 0) {
            const m = state.game.moves[ply - 1];
            moveStr = `${m.move_number}. ${m.is_white ? '' : '...'}${m.san}`;
        } else {
            moveStr = '初始局面';
        }

        const analysis = state.analysisMap[ply];
        let analysisStr = '';
        if (analysis && analysis.error_type) {
            analysisStr = ` | ${analysis.error_type}`;
        }

        tooltip.innerHTML = `<div>${moveStr}</div><div>评估: ${scoreStr}${analysisStr}</div>`;
        tooltip.style.display = 'block';

        let tx = mx + 12;
        let ty = my - 40;
        if (tx + 150 > rect.width) tx = mx - 160;
        if (ty < 0) ty = my + 12;
        tooltip.style.left = tx + 'px';
        tooltip.style.top = ty + 'px';
    }

    canvas.addEventListener('mousemove', function(e) {
        if (dragging) {
            const ply = getPlyFromEvent(e);
            if (ply >= 0) goToPly(ply);
        }
        showTooltip(e);
    });

    canvas.addEventListener('mouseleave', function() {
        tooltip.style.display = 'none';
        dragging = false;
        canvas.style.cursor = '';
    });

    canvas.addEventListener('mousedown', function(e) {
        dragging = true;
        canvas.style.cursor = 'grabbing';
        const ply = getPlyFromEvent(e);
        if (ply >= 0) goToPly(ply);
        e.preventDefault();
    });

    document.addEventListener('mouseup', function() {
        if (dragging) {
            dragging = false;
            canvas.style.cursor = '';
        }
    });

    canvas.addEventListener('click', function(e) {
        if (!canvas._chartData || !state.game) return;
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const cd = canvas._chartData;

        const ply = Math.round(((mx - cd.padL) / cd.chartW) * (cd.n - 1));
        if (ply >= 0 && ply < cd.n) {
            goToPly(ply);
        }
    });
}

document.addEventListener('keydown', function(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
    switch (e.key) {
        case 'ArrowLeft': goPrev(); e.preventDefault(); break;
        case 'ArrowRight': goNext(); e.preventDefault(); break;
        case 'Home': goFirst(); e.preventDefault(); break;
        case 'End': goLast(); e.preventDefault(); break;
        case ' ': toggleAutoPlay(); e.preventDefault(); break;
        case 'f': case 'F': flipBoard(); e.preventDefault(); break;
    }
});

window.addEventListener('resize', function() {
    renderBoard();
    renderScoreChart();
});

loadMatchList();
initChartInteraction();
</script>
</body>
</html>"""


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PGN对弈记录可视化工具")
    parser.add_argument("--port", type=int, default=5000, help="端口号 (默认5000)")
    parser.add_argument("--engine", type=str, default=str(VELVET_DEFAULT_PATH), help="Velvet引擎路径")
    args = parser.parse_args()

    if not Path(args.engine).exists():
        print(f"警告: Velvet引擎未找到: {args.engine}")
        print("分析功能将不可用，但浏览功能正常。")

    app.config["VELVET_PATH"] = args.engine
    print(f"\n  PGN对弈可视化工具已启动")
    print(f"  访问: http://localhost:{args.port}\n")
    app.run(debug=False, port=args.port, threaded=True)
