import os
import threading
import time as time_mod
import chess

from chess_logic import INITIAL_BOARD, apply_move, is_in_check
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

    san_moves = []
    try:
        cb = chess.Board()
        for uci_m in ms["move_history"]:
            mv = chess.Move.from_uci(uci_m)
            san_moves.append(cb.san(mv))
            cb.push(mv)
    except Exception:
        san_moves = list(ms["move_history"])

    fen = ""
    try:
        cb2 = chess.Board()
        for uci_m in ms["move_history"]:
            cb2.push(chess.Move.from_uci(uci_m))
        fen = cb2.fen()
    except Exception:
        fen = ""

    return {
        "board": ms["board"],
        "moveHistory": ms["move_history"],
        "sanMoves": san_moves,
        "fen": fen,
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


def _engine_is_alive(eng):
    return eng.process is not None and eng.process.poll() is None


def _engine_get_move_with_ponder(eng, move_history, wtime, btime, winc, binc,
                                  ponder_move_from_opponent=None,
                                  use_ponder=True):
    tag = os.path.basename(eng.engine_path)
    pondering = eng.is_pondering()
    alive = _engine_is_alive(eng)
    print(f"[MATCH-DBG] {tag} protocol={eng.protocol} pondering={pondering} alive={alive} hist_len={len(move_history)} use_ponder={use_ponder}")

    if eng.protocol != "uci":
        print(f"[MATCH-DBG] {tag} -> path A: non-uci, calling get_best_move_with_time")
        return eng.get_best_move_with_time(
            move_history, wtime, btime, winc, binc), None

    if not use_ponder:
        print(f"[MATCH-DBG] {tag} -> path N: ponder disabled, calling get_best_move_with_time")
        if pondering:
            eng.stop_ponder()
        best = eng.get_best_move_with_time(
            move_history, wtime, btime, winc, binc)
        print(f"[MATCH-DBG] {tag} -> path N: got best={best}")
        return best, None

    if pondering and ponder_move_from_opponent:
        print(f"[MATCH-DBG] {tag} -> path B: ponderhit (sending position first)")
        # 必须先发送 position 命令更新引擎内部局面到对手走子后的状态
        eng.send("position startpos moves " + " ".join(move_history))
        eng.send_ponderhit()
        best, new_ponder = eng.wait_for_bestmove_ponder(timeout=60)
        if best is None:
            eng.stop_ponder()
        return best, new_ponder

    if pondering:
        print(f"[MATCH-DBG] {tag} -> path C: stop ponder")
        eng.stop_ponder()
        print(f"[MATCH-DBG] {tag} -> path C: calling get_best_move_with_time")
        best = eng.get_best_move_with_time(
            move_history, wtime, btime, winc, binc)
        ponder = eng.get_ponder_move()
        print(f"[MATCH-DBG] {tag} -> path C: got best={best}")
        return best, ponder

    if not _engine_is_alive(eng):
        print(f"[MATCH-DBG] {tag} -> path D: engine NOT alive!")
        return None, None

    print(f"[MATCH-DBG] {tag} -> path E: calling get_best_move_with_time")
    best = eng.get_best_move_with_time(
        move_history, wtime, btime, winc, binc)
    ponder = eng.get_ponder_move()
    print(f"[MATCH-DBG] {tag} -> path E: got best={best}")
    return best, ponder


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
            last_ponder_moves = {0: None, 1: None}

            for move_num in range(300):
                if not match_state["active"]:
                    break

                side = move_num % 2
                eng = white_engine if side == 0 else black_engine
                opp_eng = black_engine if side == 0 else white_engine
                eng_name = white_name if side == 0 else black_name

                if not _engine_is_alive(eng):
                    if opp_eng.is_pondering():
                        opp_eng.stop_ponder()
                    with match_lock:
                        match_state["game_over"] = True
                        match_state["game_result"] = f"{eng_name} 引擎进程异常退出"
                        add_score(side == 1)
                    sse_notify(match_board_to_dict())
                    break

                wtime = times[0]
                btime = times[1]

                move_start = time_mod.time()

                opp_side = 1 - side
                ponder_from_opponent = last_ponder_moves.get(side)
                opp_actual_move = match_state["move_history"][-1] if match_state["move_history"] else None
                ponder_hit = (ponder_from_opponent is not None and
                              opp_actual_move is not None and
                              ponder_from_opponent == opp_actual_move)

                eng_is_hellcopter = (engine1_id == "hellcopter" and eng is e1) or (engine2_id == "hellcopter" and eng is e2)
                best_move, ponder_move = _engine_get_move_with_ponder(
                    eng, match_state["move_history"], wtime, btime, time_inc, time_inc,
                    ponder_move_from_opponent=ponder_hit,
                    use_ponder=eng_is_hellcopter
                )

                last_ponder_moves[side] = ponder_move if eng_is_hellcopter else None

                elapsed = int((time_mod.time() - move_start) * 1000)

                if not best_move or len(best_move) < 4 or best_move == "0000" or best_move == "(none)":
                    print(f"[MATCH] {eng_name} 返回无效走法: '{best_move}', move_num={move_num}, history={match_state['move_history'][-6:]}")
                    if opp_eng.is_pondering():
                        opp_eng.stop_ponder()
                    in_check = is_in_check(match_state["board"], side)
                    # Check if there are actually legal moves (engine misbehaving vs true mate/stalemate)
                    has_legal_moves = False
                    try:
                        import chess as chess_lib
                        cb = chess_lib.Board()
                        for uci_m in match_state["move_history"]:
                            cb.push(chess_lib.Move.from_uci(uci_m))
                        has_legal_moves = any(True for _ in cb.legal_moves)
                    except:
                        pass
                    with match_lock:
                        match_state["game_over"] = True
                        if in_check:
                            winner_side = 1 - side
                            winner_name = white_name if winner_side == 0 else black_name
                            match_state["game_result"] = f"{eng_name} 被将杀，{winner_name} 获胜！"
                            add_score(winner_side == 0)
                        elif has_legal_moves:
                            # Engine returned 0000 but has legal moves - engine fault, opponent wins
                            winner_side = 1 - side
                            winner_name = white_name if winner_side == 0 else black_name
                            match_state["game_result"] = f"{eng_name} 返回无效走法（有合法走法但返回0000），{winner_name} 获胜！"
                            add_score(winner_side == 0)
                        else:
                            match_state["game_result"] = f"{eng_name} 无合法走法（逼和），和棋！"
                            match_state["score1"] += 0.5
                            match_state["score2"] += 0.5
                    sse_notify(match_board_to_dict())
                    break

                if best_move[0:2] == best_move[2:4] and best_move != "0000":
                    print(f"[MATCH] {eng_name} 返回非法走法: '{best_move}' (起止格相同), move_num={move_num}")
                    if opp_eng.is_pondering():
                        opp_eng.stop_ponder()
                    winner_side = 1 - side
                    winner_name = white_name if winner_side == 0 else black_name
                    with match_lock:
                        match_state["game_over"] = True
                        match_state["game_result"] = f"{eng_name} 返回非法走法 '{best_move}'（起止格相同），{winner_name} 获胜！"
                        add_score(winner_side == 0)
                    sse_notify(match_board_to_dict())
                    break

                min_elapsed = max(200, time_inc)
                actual_elapsed = elapsed
                if elapsed < min_elapsed:
                    time_mod.sleep((min_elapsed - elapsed) / 1000.0)
                times[side] = times[side] - actual_elapsed + time_inc
                if times[side] <= 0:
                    if opp_eng.is_pondering():
                        opp_eng.stop_ponder()
                    winner_side = 1 - side
                    winner_name = white_name if winner_side == 0 else black_name
                    with match_lock:
                        match_state["game_over"] = True
                        match_state["game_result"] = f"{eng_name} 超时，{winner_name} 获胜！"
                        add_score(winner_side == 0)
                    sse_notify(match_board_to_dict())
                    break

                with match_lock:
                    chess_board = chess.Board()
                    rebuild_ok = True
                    for prev_move in match_state["move_history"]:
                        try:
                            chess_board.push(chess.Move.from_uci(prev_move))
                        except Exception:
                            rebuild_ok = False
                            break
                    try:
                        chess_move = chess.Move.from_uci(best_move)
                        if chess_move not in chess_board.legal_moves:
                            print(f"[MATCH] {eng_name} 返回非法走法: '{best_move}', move_num={move_num}, FEN={chess_board.fen()}")
                            if opp_eng.is_pondering():
                                opp_eng.stop_ponder()
                            match_state["game_over"] = True
                            winner_side = 1 - side
                            winner_name = white_name if winner_side == 0 else black_name
                            match_state["game_result"] = f"{eng_name} 返回非法走法 '{best_move}'，{winner_name} 获胜！"
                            add_score(winner_side == 0)
                            sse_notify(match_board_to_dict())
                            break
                    except ValueError:
                        print(f"[MATCH] {eng_name} 返回无效走法格式: '{best_move}', move_num={move_num}")
                        if opp_eng.is_pondering():
                            opp_eng.stop_ponder()
                        match_state["game_over"] = True
                        winner_side = 1 - side
                        winner_name = white_name if winner_side == 0 else black_name
                        match_state["game_result"] = f"{eng_name} 返回无效走法 '{best_move}'，{winner_name} 获胜！"
                        add_score(winner_side == 0)
                        sse_notify(match_board_to_dict())
                        break

                    match_state["move_history"].append(best_move)
                    try:
                        new_board, new_ep, new_castling = apply_move(
                            match_state["board"], best_move,
                            match_state["ep_target"], match_state["castling"]
                        )
                        match_state["board"] = new_board
                        match_state["ep_target"] = new_ep
                        match_state["castling"] = new_castling
                    except Exception as ex:
                        print(f"[MATCH] {eng_name} 走法应用失败: '{best_move}', 异常={ex}, move_num={move_num}, history={match_state['move_history'][-6:]}")
                        if opp_eng.is_pondering():
                            opp_eng.stop_ponder()
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
                pos_key += f" {'w' if side == 0 else 'b'}"
                pos_key += str(match_state.get("castling_rights", ""))
                ep_sq = match_state.get("ep_square", "-")
                if ep_sq:
                    pos_key += str(ep_sq)
                else:
                    pos_key += "-"
                repetition_count[pos_key] = repetition_count.get(pos_key, 0) + 1
                if repetition_count[pos_key] >= 3:
                    if opp_eng.is_pondering():
                        opp_eng.stop_ponder()
                    with match_lock:
                        match_state["game_over"] = True
                        match_state["game_result"] = "三次重复，和棋！"
                        match_state["score1"] += 0.5
                        match_state["score2"] += 0.5
                    sse_notify(match_board_to_dict())
                    break

                # 50步和棋规则检测
                halfmove = match_state.get("halfmove_clock", 0)
                if halfmove >= 100:
                    if opp_eng.is_pondering():
                        opp_eng.stop_ponder()
                    with match_lock:
                        match_state["game_over"] = True
                        match_state["game_result"] = "50步无吃子无兵动，和棋！"
                        match_state["score1"] += 0.5
                        match_state["score2"] += 0.5
                    sse_notify(match_board_to_dict())
                    break

                sse_notify(match_board_to_dict())

                opp_is_hellcopter = (engine1_id == "hellcopter" and opp_eng is e1) or (engine2_id == "hellcopter" and opp_eng is e2)
                if opp_is_hellcopter and opp_eng.protocol == "uci" and not match_state["game_over"]:
                    opp_wtime = times[0] if opp_side == 0 else times[1]
                    opp_btime = times[1] if opp_side == 0 else times[0]
                    # 对手引擎 ponder：使用对手引擎上次返回的 ponder 着法
                    # 这样对手引擎在 "假设对手走了 ponder 着法" 的位置上搜索
                    opp_ponder_move = opp_eng.get_ponder_move()
                    opp_eng.start_ponder(
                        match_state["move_history"],
                        opp_wtime, opp_btime, time_inc, time_inc,
                        ponder_move=opp_ponder_move
                    )

                time_mod.sleep(0.1)

            with match_lock:
                match_state["games_played"] = game_idx + 1
                if not match_state["game_over"]:
                    match_state["game_over"] = True
                    match_state["game_result"] = "超过300步，和棋！"
                    match_state["score1"] += 0.5
                    match_state["score2"] += 0.5
            sse_notify(match_board_to_dict())

    finally:
        e1.quit()
        e2.quit()
        with match_lock:
            match_state["active"] = False
        sse_notify(match_board_to_dict())
