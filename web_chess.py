import os
import json
import queue
import threading
import time as _time
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory, Response

from chess_logic import INITIAL_BOARD, apply_move, GameState
from engine_comm import Engine
from engine_registry import ENGINE_REGISTRY, ENGINE_PATH, _detect_syzygy_path, resolve_engine
from match_manager import match_state, match_board_to_dict, match_lock, run_engine_match
from sse_hub import sse_add_listener, sse_remove_listener, sse_notify

app = Flask(__name__, static_folder="web_static", static_url_path="/static")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MOVE_TIME = 3000
DEFAULT_ENGINE_ID = os.environ.get("HELLCOPTER_ENGINE", "hellcopter")

game = GameState(move_time=DEFAULT_MOVE_TIME)

# 游戏代际计数器，用于防止新游戏开始后旧引擎搜索结果被误用
_game_gen = 0
# 当前引擎思考线程引用，用于 new_game 时等待其完成
_engine_thread = None

_engine_obj, _engine_entry = resolve_engine(DEFAULT_ENGINE_ID)
if _engine_obj:
    engine = _engine_obj
else:
    engine = Engine(ENGINE_PATH)
    engine.syzygy_path = _detect_syzygy_path()

_engine_started = False


@app.route("/api/health", methods=["GET"])
def health_check():
    """引擎健康检查端点"""
    engine_alive = engine.is_alive() if engine.process else False
    dll_loaded = False
    try:
        import engine_wrapper
        dll_loaded = engine_wrapper.is_loaded()
    except Exception:
        pass
    return jsonify({
        "engine_alive": engine_alive,
        "dll_loaded": dll_loaded,
        "engine_started": _engine_started,
        "engine_path": getattr(engine, 'engine_path', 'unknown'),
    })


@app.route("/api/lock_test", methods=["POST"])
def lock_test():
    """测试锁是否正常"""
    import time as _time
    _t0 = _time.time()
    acquired = match_lock.acquire(timeout=5)
    elapsed = _time.time() - _t0
    if acquired:
        match_lock.release()
    return jsonify({"acquired": acquired, "elapsed": round(elapsed, 4)})


@app.route("/")
def index():
    return send_from_directory("web_static", "index.html")


@app.route("/api/state", methods=["GET"])
def get_state():
    with game.lock:
        return jsonify(game.to_dict())


@app.route("/api/move", methods=["POST"])
def make_move():
    data = request.json
    uci_move = data.get("move", "")
    print(f"[WEB] make_move: uci={uci_move}")

    with game.lock:
        if game.engine_thinking or game.game_over:
            print(f"[WEB] make_move: rejected, engine_thinking={game.engine_thinking}, game_over={game.game_over}")
            return jsonify({"error": "无法走棋"}), 400

        current = "w" if len(game.move_history) % 2 == 0 else "b"
        if current != game.player_color:
            return jsonify({"error": "不是你的回合"}), 400

        legal = game.get_legal_moves()
        if uci_move not in legal:
            return jsonify({"error": "非法走法"}), 400

        game.make_move(uci_move)
        game.check_game_over()

        if game.game_over:
            return jsonify(game.to_dict())

        game.engine_thinking = True
        move_time = game.move_time

    def engine_think():
        gen = _game_gen
        print(f"[WEB] engine_think: started, gen={gen}, move_history={game.move_history}")
        try:
            best = engine.get_best_move(game.move_history, move_time)
            print(f"[WEB] engine_think: got best={best}")
        except Exception as e:
            print(f"[WEB] engine_think: exception {e}")
            best = None
        with game.lock:
            game.engine_thinking = False
            if gen != _game_gen:
                print(f"[WEB] engine_think: gen mismatch {gen}!={_game_gen}, discarding")
                return
            if best and best != "0000" and len(best) >= 4:
                legal = game.get_legal_moves()
                if best in legal:
                    try:
                        game.make_move(best)
                        game.check_game_over()
                        print(f"[WEB] engine_think: applied move {best}, history={game.move_history}")
                    except Exception as e:
                        print(f"[WEB] engine_think: make_move error {e}")
                        game.game_over = True
                        game.game_result = "引擎返回了非法走法"
                else:
                    print(f"[WEB] engine_think: illegal move {best}, legal={legal[:5]}...")
                    game.game_over = True
                    game.game_result = "引擎返回了非法走法"
            else:
                game.check_game_over()
                if not game.game_over:
                    game.game_over = True
                    game.game_result = "引擎无法找到走法"

    t = threading.Thread(target=engine_think, daemon=True)
    t.start()
    global _engine_thread
    _engine_thread = t

    with game.lock:
        return jsonify(game.to_dict())


@app.route("/api/new_game", methods=["POST"])
def new_game():
    global _game_gen, _engine_thread, _engine_started
    data = request.json or {}
    player_color = data.get("playerColor", "w")
    move_time = data.get("moveTime", DEFAULT_MOVE_TIME)
    print(f"[WEB] new_game: playerColor={player_color}, moveTime={move_time}")

    # 引擎健康检查
    if not _engine_started or not engine.is_alive():
        print(f"[WEB] new_game: engine not alive, attempting restart...")
        try:
            if engine.process and engine.is_alive():
                engine.quit()
            ok = engine.start()
            if ok:
                _engine_started = True
                print(f"[WEB] new_game: engine restarted successfully")
            else:
                print(f"[WEB] new_game: engine restart FAILED")
                return jsonify({"error": "引擎无法启动，请检查 engine_core.dll 是否存在并重新编译", "gameOver": True, "gameResult": "引擎无法启动"}), 500
        except Exception as e:
            print(f"[WEB] new_game: engine restart exception: {e}")
            return jsonify({"error": f"引擎启动异常: {e}", "gameOver": True, "gameResult": "引擎无法启动"}), 500

    with game.lock:
        game.reset()
        game.player_color = player_color
        game.move_time = move_time
        game.engine_thinking = False
        _game_gen += 1
        print(f"[WEB] new_game: game reset, _game_gen={_game_gen}")

    # 如果引擎正在搜索，先发送 stop 中断搜索，然后等待引擎线程完成
    if engine._searching:
        print(f"[WEB] new_game: engine is searching, sending stop...")
        engine.send("stop")

    # 等待引擎思考线程完成（最多3秒）
    if _engine_thread is not None and _engine_thread.is_alive():
        print(f"[WEB] new_game: waiting for engine thread to finish...")
        _engine_thread.join(timeout=3)
        if _engine_thread.is_alive():
            print(f"[WEB] new_game: WARNING - engine thread still alive after 3s")
        else:
            print(f"[WEB] new_game: engine thread finished")
    _engine_thread = None

    # 现在引擎已空闲，安全调用 new_game
    print(f"[WEB] new_game: calling engine.new_game()...")
    engine.new_game()
    print(f"[WEB] new_game: engine.new_game() done")

    if player_color == "b":
        with game.lock:
            game.engine_thinking = True
        print(f"[WEB] new_game: starting engine_first thread")

        def engine_first():
            gen = _game_gen
            print(f"[WEB] engine_first: started, gen={gen}")
            try:
                best = engine.get_best_move([], move_time)
                print(f"[WEB] engine_first: got best={best}")
            except Exception as e:
                print(f"[WEB] engine_first: exception {e}")
                best = None
            with game.lock:
                game.engine_thinking = False
                if gen != _game_gen:
                    print(f"[WEB] engine_first: gen mismatch {gen}!={_game_gen}, discarding")
                    return
                if best and best != "0000" and len(best) >= 4:
                    legal = game.get_legal_moves()
                    if best in legal:
                        try:
                            game.make_move(best)
                            game.check_game_over()
                            print(f"[WEB] engine_first: applied move {best}, history={game.move_history}")
                        except Exception as e:
                            print(f"[WEB] engine_first: make_move error {e}")
                            game.game_over = True
                            game.game_result = "引擎返回了非法走法"
                    else:
                        print(f"[WEB] engine_first: illegal move {best}, legal={legal[:5]}...")
                        game.game_over = True
                        game.game_result = "引擎返回了非法走法"
                else:
                    game.check_game_over()
                    if not game.game_over:
                        game.game_over = True
                        game.game_result = "引擎无法找到走法"

        t = threading.Thread(target=engine_first, daemon=True)
        t.start()
        _engine_thread = t

    with game.lock:
        result = game.to_dict()
        print(f"[WEB] new_game: returning, engineThinking={result['engineThinking']}, gameOver={result['gameOver']}")
        return jsonify(result)


@app.route("/api/undo", methods=["POST"])
def undo_move():
    with game.lock:
        if game.engine_thinking or game.game_over:
            return jsonify({"error": "无法悔棋"}), 400
        if len(game.move_history) < 2:
            return jsonify({"error": "没有可以悔棋的步"}), 400

        game.move_history.pop()
        game.move_history.pop()
        game.board = [row[:] for row in INITIAL_BOARD]
        game.ep_target = None
        game.castling = {"K": True, "Q": True, "k": True, "q": True}
        game.last_move = None
        for m in game.move_history:
            new_board, new_ep, new_castling = apply_move(
                game.board, m, game.ep_target, game.castling
            )
            game.board = new_board
            game.ep_target = new_ep
            game.castling = new_castling
        game.check_game_over()

        return jsonify(game.to_dict())


@app.route("/match")
def match_page():
    return send_from_directory("web_static", "match.html")


@app.route("/api/match/state", methods=["GET"])
def get_match_state():
    return jsonify(match_board_to_dict())


@app.route("/api/match/stream", methods=["GET"])
def match_stream():
    def generate():
        q = queue.Queue(maxsize=64)
        sse_add_listener(q)
        try:
            yield f"data: {json.dumps(match_board_to_dict(), ensure_ascii=False)}\n\n"
            while True:
                try:
                    data = q.get(timeout=30)
                    yield f"data: {data}\n\n"
                except queue.Empty:
                    yield f": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            sse_remove_listener(q)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/engines", methods=["GET"])
def get_engines():
    result = []
    for entry in ENGINE_REGISTRY:
        result.append({
            "id": entry["id"],
            "name": entry["name"],
            "protocol": entry["protocol"],
            "options": entry.get("options", []),
        })
    return jsonify(result)


@app.route("/api/match/start", methods=["POST"])
def start_match():
    print("[WEB] start_match: BEGIN", flush=True)
    data = request.json or {}
    time_base = data.get("timeBase", 96000)
    time_inc = data.get("timeInc", 800)
    total_games = data.get("totalGames", 5)
    engine1_id = data.get("engine1Id", "chess3super")
    engine2_id = data.get("engine2Id", "hellcopter")
    engine1_opts = data.get("engine1Options", {})
    engine2_opts = data.get("engine2Options", {})
    print(f"[WEB] start_match: e1={engine1_id} e2={engine2_id}", flush=True)

    with match_lock:
        if match_state.active:
            return jsonify({"error": "对弈正在进行中"}), 400

    extra_opts = {}

    if engine1_id == "velvet":
        limit_e1 = data.get("velvetLimitStrength1", False)
        elo_e1 = data.get("velvetElo1", 2000)
        if limit_e1:
            extra_opts["velvet"] = {"limitStrength": True, "UCI_Elo": int(elo_e1)}
    if engine2_id == "velvet":
        limit_e2 = data.get("velvetLimitStrength2", False)
        elo_e2 = data.get("velvetElo2", 2000)
        if limit_e2:
            extra_opts["velvet"] = extra_opts.get("velvet", {})
            extra_opts["velvet"]["limitStrength"] = True
            extra_opts["velvet"]["UCI_Elo"] = int(elo_e2)

    for eid, opts in engine1_opts.items():
        if opts:
            extra_opts[eid] = extra_opts.get(eid, {})
            extra_opts[eid].update(opts)
    for eid, opts in engine2_opts.items():
        if opts:
            extra_opts[eid] = extra_opts.get(eid, {})
            extra_opts[eid].update(opts)

    e1_name = next((e["name"] for e in ENGINE_REGISTRY if e["id"] == engine1_id), engine1_id)
    e2_name = next((e["name"] for e in ENGINE_REGISTRY if e["id"] == engine2_id), engine2_id)
    print(f"[WEB] start_match: calling init_match...", flush=True)

    match_state.init_match(time_base, time_inc, total_games)
    print(f"[WEB] start_match: init_match done, getting response_data...", flush=True)

    # 先获取响应数据，再启动线程，避免线程中的锁竞争阻塞响应
    response_data = match_board_to_dict()
    print(f"[WEB] start_match: response_data ready, starting thread...", flush=True)

    t = threading.Thread(target=run_engine_match, args=(
        engine1_id, engine2_id, e1_name, e2_name,
        time_base, time_inc, total_games, extra_opts
    ), daemon=True)
    t.start()
    print(f"[WEB] start_match: thread started, returning response", flush=True)

    return jsonify(response_data)


@app.route("/api/match/stop", methods=["POST"])
def stop_match():
    match_state.set_active(False)
    if not match_state.game_over:
        match_state.set_game_over(True, "手动停止对弈")
    return jsonify(match_board_to_dict())


# ---- Velvet FEN 分析 ----

GAMES_DIR = os.path.join(BASE_DIR, "saved_games")


@app.route("/analyze")
def analyze_page():
    return send_from_directory("web_static", "analyze.html")


@app.route("/review")
def review_page():
    return send_from_directory("web_static", "review.html")


@app.route("/api/analyze", methods=["POST"])
def analyze_fen():
    """使用 Velvet 引擎分析 FEN 局面"""
    data = request.json or {}
    fen = data.get("fen", "")
    depth = data.get("depth", 20)
    multi_pv = data.get("multiPv", 3)

    if not fen:
        return jsonify({"error": "缺少 FEN"}), 400

    try:
        from engine_registry import VELVET_PATH
        vel = Engine(VELVET_PATH, protocol="uci")
        sz = _detect_syzygy_path()
        if sz:
            vel.syzygy_path = sz
        if not vel.start():
            return jsonify({"error": "Velvet 引擎启动失败"}), 500

        try:
            # 设置 MultiPV
            if multi_pv > 1:
                vel.send(f"setoption name MultiPV value {multi_pv}")

            vel.send(f"position fen {fen}")
            vel.send(f"go depth {depth}")

            lines = []
            deadline = _time.time() + 120
            while _time.time() < deadline:
                line = vel.readline(timeout=5)
                if line is None:
                    break
                if line.startswith("info") and "score" in line and " pv " in line:
                    lines.append(line)
                if line.startswith("bestmove"):
                    break

            # 解析 info 行，保留每个深度的最后一行
            parsed = {}
            for info_line in lines:
                parts = info_line.split()
                try:
                    d_idx = parts.index("depth")
                    d = int(parts[d_idx + 1])
                    mpv_idx = parts.index("multipv") if "multipv" in parts else -1
                    mpv = int(parts[mpv_idx + 1]) if mpv_idx >= 0 else 1
                    s_idx = parts.index("score")
                    score_type = parts[s_idx + 1]
                    score_val = int(parts[s_idx + 2])
                    pv_idx = parts.index("pv")
                    pv_moves = parts[pv_idx + 1:]
                    key = (d, mpv)
                    existing = parsed.get(key)
                    pv_len = len(pv_moves)
                    if existing is None or pv_len > len(existing["pv"]):
                        parsed[key] = {
                            "depth": d,
                            "multipv": mpv,
                            "scoreType": score_type,
                            "score": score_val,
                            "pv": pv_moves,
                            "move": pv_moves[0] if pv_moves else "",
                        }
                except (ValueError, IndexError):
                    pass

            # 取每个 multipv 的最深结果
            result_lines = []
            for mpv in range(1, multi_pv + 1):
                best = None
                for (d, m), v in parsed.items():
                    if m == mpv:
                        if best is None or d > best["depth"]:
                            best = v
                if best:
                    result_lines.append(best)

            return jsonify({"lines": result_lines})
        finally:
            vel.quit()
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---- 对局保存与复盘 ----

def _ensure_games_dir():
    os.makedirs(GAMES_DIR, exist_ok=True)


def _save_game_pgn(move_history, white_name, black_name, result, game_id=None):
    """保存对局为 JSON 格式（包含 PGN 信息）"""
    _ensure_games_dir()
    if not game_id:
        game_id = f"game_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    try:
        import chess as _chess
        board = _chess.Board()
        san_moves = []
        for uci_m in move_history:
            mv = _chess.Move.from_uci(uci_m)
            san_moves.append(board.san(mv))
            board.push(mv)
        final_fen = board.fen()
    except Exception:
        san_moves = list(move_history)
        final_fen = ""

    game_data = {
        "id": game_id,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "white": white_name,
        "black": black_name,
        "result": result,
        "moves": list(move_history),
        "sanMoves": san_moves,
        "finalFen": final_fen,
    }

    filepath = os.path.join(GAMES_DIR, f"{game_id}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(game_data, f, ensure_ascii=False, indent=2)

    print(f"[WEB] Game saved: {filepath}")
    return game_id


@app.route("/api/games", methods=["GET"])
def list_games():
    """列出所有保存的对局"""
    _ensure_games_dir()
    games = []
    for fname in sorted(os.listdir(GAMES_DIR), reverse=True):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(GAMES_DIR, fname), "r", encoding="utf-8") as f:
                    data = json.load(f)
                games.append({
                    "id": data.get("id", fname[:-5]),
                    "date": data.get("date", ""),
                    "white": data.get("white", "?"),
                    "black": data.get("black", "?"),
                    "result": data.get("result", "*"),
                    "moveCount": len(data.get("moves", [])),
                })
            except Exception:
                pass
    return jsonify({"games": games})


@app.route("/api/games/<game_id>", methods=["GET"])
def get_game(game_id):
    """获取对局详情"""
    filepath = os.path.join(GAMES_DIR, f"{game_id}.json")
    if not os.path.isfile(filepath):
        return jsonify({"error": "对局不存在"}), 404
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    engine_name = _engine_entry["name"] if _engine_entry else "Unknown"
    if not engine.start():
        print(f"警告: {engine_name} 引擎无法启动，人机对弈模式不可用")
        print("引擎对弈模式仍可正常使用")
    else:
        _engine_started = True
        print(f"{engine_name} 引擎已就绪")

    os.makedirs("web_static", exist_ok=True)

    print("=" * 52)
    print("   Chess Arena - 引擎对弈竞技场")
    print("   人机对弈: http://localhost:5000")
    print("   引擎对弈: http://localhost:5000/match")
    print("   局面分析: http://localhost:5000/analyze")
    print("   对局复盘: http://localhost:5000/review")
    print("-" * 52)
    print("   已注册引擎:")
    for entry in ENGINE_REGISTRY:
        p = entry["protocol"]
        proto_tag = "UCI" if p == "uci" else "XBoard" if p == "xboard" else "TSCP" if p == "tscp" else p.upper()
        print(f"     [{proto_tag:>6}] {entry['name']}")
    print("=" * 52)

    try:
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False, threaded=True)
    finally:
        engine.quit()
