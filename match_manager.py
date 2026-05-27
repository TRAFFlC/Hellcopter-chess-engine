import threading
import time as time_mod

from chess_logic import INITIAL_BOARD, apply_move
from engine_registry import resolve_engine
from sse_hub import sse_notify

match_state = {
    "active": False,
    "board": [row[:] for row in INITIAL_BOARD],
    "move_history": [],
    "last_move": None,
    "engine1_name": "",
    "engine2_name": "",
    "engine1_time": 0,
    "engine2_time": 0,
    "current_side": "w",
    "game_over": False,
    "game_result": "",
    "move_count": 0,
    "time_base": 96000,
    "time_inc": 800,
    "ep_target": None,
    "castling": {"K": True, "Q": True, "k": True, "q": True},
    "score1": 0,
    "score2": 0,
    "games_played": 0,
    "total_games": 2,
    "white_name": "",
    "black_name": "",
}

match_lock = threading.Lock()


def match_board_to_dict():
    ms = match_state
    current = "w" if len(ms["move_history"]) % 2 == 0 else "b"
    return {
        "board": ms["board"],
        "moveHistory": ms["move_history"],
        "lastMove": ms["last_move"],
        "engine1Name": ms["engine1_name"],
        "engine2Name": ms["engine2_name"],
        "whiteName": ms["white_name"],
        "blackName": ms["black_name"],
        "engine1Time": ms["engine1_time"],
        "engine2Time": ms["engine2_time"],
        "currentSide": current,
        "gameOver": ms["game_over"],
        "gameResult": ms["game_result"],
        "moveCount": ms["move_count"],
        "active": ms["active"],
        "score1": ms["score1"],
        "score2": ms["score2"],
        "gamesPlayed": ms["games_played"],
        "totalGames": ms["total_games"],
    }


def run_engine_match(engine1_id, engine2_id, engine1_name, engine2_name,
                     time_base, time_inc, total_games, extra_opts=None):
    extra_opts = extra_opts or {}
    e1, entry1 = resolve_engine(engine1_id, extra_opts.get(engine1_id, {}))
    e2, entry2 = resolve_engine(engine2_id, extra_opts.get(engine2_id, {}))

    if not e1 or not e2:
        with match_lock:
            match_state["game_result"] = "引擎配置无效"
            match_state["active"] = False
        sse_notify(match_board_to_dict())
        return

    with match_lock:
        match_state["engine1_name"] = engine1_name
        match_state["engine2_name"] = engine2_name

    try:
        if not e1.start():
            with match_lock:
                match_state["game_result"] = f"{engine1_name} 启动失败"
                match_state["game_over"] = True
                match_state["active"] = False
            sse_notify(match_board_to_dict())
            return
        if not e2.start():
            with match_lock:
                match_state["game_result"] = f"{engine2_name} 启动失败"
                match_state["game_over"] = True
                match_state["active"] = False
            sse_notify(match_board_to_dict())
            return

        for game_idx in range(total_games):
            if not match_state["active"]:
                break

            even_game = (game_idx % 2 == 0)
            if even_game:
                white_engine, black_engine = e1, e2
                white_name, black_name = engine1_name, engine2_name
            else:
                white_engine, black_engine = e2, e1
                white_name, black_name = engine2_name, engine1_name

            def add_score(winner_is_white):
                if winner_is_white:
                    if even_game:
                        match_state["score1"] += 1
                    else:
                        match_state["score2"] += 1
                else:
                    if even_game:
                        match_state["score2"] += 1
                    else:
                        match_state["score1"] += 1

            white_engine.new_game()
            black_engine.new_game()

            if (white_engine.process is None or white_engine.process.poll() is not None):
                with match_lock:
                    match_state["game_over"] = True
                    match_state["game_result"] = f"{white_name} 引擎进程异常退出"
                    add_score(False)
                sse_notify(match_board_to_dict())
                break
            if (black_engine.process is None or black_engine.process.poll() is not None):
                with match_lock:
                    match_state["game_over"] = True
                    match_state["game_result"] = f"{black_name} 引擎进程异常退出"
                    add_score(True)
                sse_notify(match_board_to_dict())
                break

            with match_lock:
                match_state["board"] = [row[:] for row in INITIAL_BOARD]
                match_state["move_history"] = []
                match_state["last_move"] = None
                match_state["game_over"] = False
                match_state["game_result"] = f"第{game_idx+1}局: {white_name}(白) vs {black_name}(黑)"
                match_state["move_count"] = 0
                match_state["ep_target"] = None
                match_state["castling"] = {"K": True, "Q": True, "k": True, "q": True}
                match_state["engine1_time"] = time_base
                match_state["engine2_time"] = time_base
                match_state["white_name"] = white_name
                match_state["black_name"] = black_name
            sse_notify(match_board_to_dict())

            times = [time_base, time_base]
            repetition_count = {}

            for move_num in range(300):
                if not match_state["active"]:
                    break

                side = move_num % 2
                eng = white_engine if side == 0 else black_engine
                eng_name = white_name if side == 0 else black_name

                wtime = times[0]
                btime = times[1]

                move_start = time_mod.time()

                best_move = eng.get_best_move_with_time(
                    match_state["move_history"], wtime, btime, time_inc, time_inc,
                    match_state["board"], match_state["ep_target"], match_state["castling"]
                )

                elapsed = int((time_mod.time() - move_start) * 1000)

                if not best_move or len(best_move) < 4 or best_move == "0000" or best_move == "(none)":
                    winner_side = 1 - side
                    winner_name = white_name if winner_side == 0 else black_name
                    with match_lock:
                        match_state["game_over"] = True
                        match_state["game_result"] = f"{eng_name} 无合法走法，{winner_name} 获胜！"
                        add_score(winner_side == 0)
                    sse_notify(match_board_to_dict())
                    break

                if best_move[0:2] == best_move[2:4] and best_move != "0000":
                    winner_side = 1 - side
                    winner_name = white_name if winner_side == 0 else black_name
                    with match_lock:
                        match_state["game_over"] = True
                        match_state["game_result"] = f"{eng_name} 返回非法走法 '{best_move}'（起止格相同），{winner_name} 获胜！"
                        add_score(winner_side == 0)
                    sse_notify(match_board_to_dict())
                    break

                times[side] = times[side] - elapsed + time_inc
                if times[side] <= 0:
                    winner_side = 1 - side
                    winner_name = white_name if winner_side == 0 else black_name
                    with match_lock:
                        match_state["game_over"] = True
                        match_state["game_result"] = f"{eng_name} 超时，{winner_name} 获胜！"
                        add_score(winner_side == 0)
                    sse_notify(match_board_to_dict())
                    break

                with match_lock:
                    match_state["move_history"].append(best_move)
                    try:
                        new_board, new_ep, new_castling = apply_move(
                            match_state["board"], best_move,
                            match_state["ep_target"], match_state["castling"]
                        )
                        match_state["board"] = new_board
                        match_state["ep_target"] = new_ep
                        match_state["castling"] = new_castling
                    except Exception:
                        winner_side = 1 - side
                        winner_name = white_name if winner_side == 0 else black_name
                        match_state["game_over"] = True
                        match_state["game_result"] = f"{eng_name} 返回非法走法 '{best_move}'，{winner_name} 获胜！"
                        add_score(winner_side == 0)
                        sse_notify(match_board_to_dict())
                        break
                    match_state["last_move"] = best_move
                    match_state["move_count"] = move_num + 1
                    match_state["engine1_time"] = times[0]
                    match_state["engine2_time"] = times[1]

                pos_key = "".join("".join(row) for row in match_state["board"])
                repetition_count[pos_key] = repetition_count.get(pos_key, 0) + 1
                if repetition_count[pos_key] >= 3:
                    with match_lock:
                        match_state["game_over"] = True
                        match_state["game_result"] = "三次重复，和棋！"
                        match_state["score1"] += 0.5
                        match_state["score2"] += 0.5
                    sse_notify(match_board_to_dict())
                    break

                sse_notify(match_board_to_dict())
                time_mod.sleep(0.1)

            with match_lock:
                match_state["games_played"] = game_idx + 1
            sse_notify(match_board_to_dict())

    finally:
        e1.quit()
        e2.quit()
        with match_lock:
            match_state["active"] = False
        sse_notify(match_board_to_dict())
