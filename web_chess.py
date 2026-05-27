import os
import json
import queue
import threading

from flask import Flask, jsonify, request, send_from_directory, Response

from chess_logic import INITIAL_BOARD, apply_move, GameState
from engine_comm import Engine
from engine_registry import ENGINE_REGISTRY, ENGINE_PATH
from match_manager import match_state, match_board_to_dict, match_lock, run_engine_match
from sse_hub import sse_add_listener, sse_remove_listener, sse_notify

app = Flask(__name__, static_folder="web_static", static_url_path="/static")

DEFAULT_MOVE_TIME = 3000

game = GameState(move_time=DEFAULT_MOVE_TIME)
engine = Engine(ENGINE_PATH)


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

    with game.lock:
        if game.engine_thinking or game.game_over:
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
        best = engine.get_best_move(game.move_history, move_time)
        with game.lock:
            game.engine_thinking = False
            if best:
                game.make_move(best)
                game.check_game_over()

    t = threading.Thread(target=engine_think, daemon=True)
    t.start()

    with game.lock:
        return jsonify(game.to_dict())


@app.route("/api/new_game", methods=["POST"])
def new_game():
    data = request.json or {}
    player_color = data.get("playerColor", "w")
    move_time = data.get("moveTime", DEFAULT_MOVE_TIME)

    with game.lock:
        game.reset()
        game.player_color = player_color
        game.move_time = move_time

    engine.new_game()

    if player_color == "b":
        with game.lock:
            game.engine_thinking = True

        def engine_first():
            best = engine.get_best_move([], move_time)
            with game.lock:
                game.engine_thinking = False
                if best:
                    game.make_move(best)
                    game.check_game_over()

        t = threading.Thread(target=engine_first, daemon=True)
        t.start()

    with game.lock:
        return jsonify(game.to_dict())


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
    data = request.json or {}
    time_base = data.get("timeBase", 96000)
    time_inc = data.get("timeInc", 800)
    total_games = data.get("totalGames", 5)
    engine1_id = data.get("engine1Id", "chess3super")
    engine2_id = data.get("engine2Id", "hellcopter")
    engine1_opts = data.get("engine1Options", {})
    engine2_opts = data.get("engine2Options", {})

    with match_lock:
        if match_state["active"]:
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

    with match_lock:
        match_state["active"] = True
        match_state["game_over"] = False
        match_state["game_result"] = "正在启动..."
        match_state["score1"] = 0
        match_state["score2"] = 0
        match_state["games_played"] = 0
        match_state["total_games"] = total_games
        match_state["time_base"] = time_base
        match_state["time_inc"] = time_inc

    t = threading.Thread(target=run_engine_match, args=(
        engine1_id, engine2_id, e1_name, e2_name,
        time_base, time_inc, total_games, extra_opts
    ), daemon=True)
    t.start()

    return jsonify(match_board_to_dict())


@app.route("/api/match/stop", methods=["POST"])
def stop_match():
    with match_lock:
        match_state["active"] = False
    return jsonify(match_board_to_dict())


if __name__ == "__main__":
    if not engine.start():
        print("警告: Chess3Super 引擎无法启动，人机对弈模式不可用")
        print("引擎对弈模式仍可正常使用")
    else:
        print("Chess3Super 引擎已就绪")

    os.makedirs("web_static", exist_ok=True)

    print("=" * 52)
    print("   Chess Arena - 引擎对弈竞技场")
    print("   人机对弈: http://localhost:5000")
    print("   引擎对弈: http://localhost:5000/match")
    print("-" * 52)
    print("   已注册引擎:")
    for entry in ENGINE_REGISTRY:
        p = entry["protocol"]
        proto_tag = "UCI" if p == "uci" else "XBoard" if p == "xboard" else "TSCP" if p == "tscp" else p.upper()
        print(f"     [{proto_tag:>6}] {entry['name']}")
    print("=" * 52)

    try:
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
    finally:
        engine.quit()
