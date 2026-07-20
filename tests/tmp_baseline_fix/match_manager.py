import os
import threading
import time as time_mod
from datetime import datetime
import chess

from chess_logic import INITIAL_BOARD, apply_move, is_in_check
from engine_registry import resolve_engine
from sse_hub import sse_notify


class MatchState:
    """对局状态管理类，封装所有对局相关的状态和操作

    将全局可变状态封装为类实例，提供线程安全的状态访问和修改方法，
    支持多对局并发，提升可测试性和可维护性。
    """

    def __init__(self, time_base=96000, time_inc=800, total_games=2):
        self._lock = threading.RLock()
        self._state = {
            "active": False,
            "board": [row[:] for row in INITIAL_BOARD],
            "move_history": [],
            "last_move": None,
            "engine1_name": "",
            "engine2_name": "",
            "engine1_time": time_base,
            "engine2_time": time_base,
            "current_side": "w",
            "game_over": False,
            "game_result": "",
            "move_count": 0,
            "time_base": time_base,
            "time_inc": time_inc,
            "ep_target": None,
            "castling": {"K": True, "Q": True, "k": True, "q": True},
            "score1": 0,
            "score2": 0,
            "games_played": 0,
            "total_games": total_games,
            "white_name": "",
            "black_name": "",
        }

    # ---- 属性访问 ----

    @property
    def active(self):
        with self._lock:
            return self._state["active"]

    @property
    def game_over(self):
        with self._lock:
            return self._state["game_over"]

    @property
    def move_history(self):
        with self._lock:
            return list(self._state["move_history"])

    @property
    def board(self):
        with self._lock:
            return self._state["board"]

    @property
    def ep_target(self):
        with self._lock:
            return self._state["ep_target"]

    @property
    def castling(self):
        with self._lock:
            return self._state["castling"]

    @property
    def last_move_history_slice(self):
        """获取最近6步走法历史，用于日志输出"""
        with self._lock:
            return self._state["move_history"][-6:]

    # ---- 字典式访问（向后兼容 web_chess.py） ----

    def __getitem__(self, key):
        with self._lock:
            return self._state[key]

    def __setitem__(self, key, value):
        with self._lock:
            self._state[key] = value

    def get(self, key, default=None):
        with self._lock:
            return self._state.get(key, default)

    # ---- 状态修改方法 ----

    def set_active(self, active):
        with self._lock:
            self._state["active"] = active

    def set_engine_names(self, engine1_name, engine2_name):
        with self._lock:
            self._state["engine1_name"] = engine1_name
            self._state["engine2_name"] = engine2_name

    def set_game_over(self, is_over, result=""):
        with self._lock:
            self._state["game_over"] = is_over
            if result:
                self._state["game_result"] = result

    def add_score(self, winner_is_white, even_game):
        """根据胜负方和是否偶数局更新比分"""
        with self._lock:
            if winner_is_white:
                if even_game:
                    self._state["score1"] += 1
                else:
                    self._state["score2"] += 1
            else:
                if even_game:
                    self._state["score2"] += 1
                else:
                    self._state["score1"] += 1

    def add_draw_score(self):
        """和棋时双方各加0.5分"""
        with self._lock:
            self._state["score1"] += 0.5
            self._state["score2"] += 0.5

    def reset_game(self, white_name, black_name, game_idx):
        """重置单局游戏状态"""
        with self._lock:
            self._state["board"] = [row[:] for row in INITIAL_BOARD]
            self._state["move_history"] = []
            self._state["last_move"] = None
            self._state["game_over"] = False
            self._state["game_result"] = f"第{game_idx + 1}局: {white_name}(白) vs {black_name}(黑)"
            self._state["move_count"] = 0
            self._state["ep_target"] = None
            self._state["castling"] = {"K": True, "Q": True, "k": True, "q": True}
            self._state["engine1_time"] = self._state["time_base"]
            self._state["engine2_time"] = self._state["time_base"]
            self._state["white_name"] = white_name
            self._state["black_name"] = black_name

    def add_move(self, uci_move, move_num, times):
        """添加走法到历史记录并更新状态"""
        with self._lock:
            self._state["move_history"].append(uci_move)
            self._state["last_move"] = uci_move
            self._state["move_count"] = move_num + 1
            self._state["engine1_time"] = times[0]
            self._state["engine2_time"] = times[1]

    def update_board(self, new_board, new_ep, new_castling):
        """更新棋盘状态"""
        with self._lock:
            self._state["board"] = new_board
            self._state["ep_target"] = new_ep
            self._state["castling"] = new_castling

    def update_times(self, times):
        """更新引擎时间"""
        with self._lock:
            self._state["engine1_time"] = times[0]
            self._state["engine2_time"] = times[1]

    def set_games_played(self, count):
        with self._lock:
            self._state["games_played"] = count

    def init_match(self, time_base, time_inc, total_games):
        """初始化对局参数"""
        with self._lock:
            self._state["active"] = True
            self._state["game_over"] = False
            self._state["game_result"] = "正在启动..."
            self._state["score1"] = 0
            self._state["score2"] = 0
            self._state["games_played"] = 0
            self._state["total_games"] = total_games
            self._state["time_base"] = time_base
            self._state["time_inc"] = time_inc

    # ---- 序列化 ----

    def to_dict(self):
        """转换为字典格式，用于序列化和SSE传输"""
        with self._lock:
            ms = self._state
            current = "w" if len(ms["move_history"]) % 2 == 0 else "b"

            san_moves = self._compute_san_moves(ms["move_history"])
            fen = self._compute_fen(ms["move_history"])

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

    @staticmethod
    def _compute_san_moves(move_history):
        """计算 SAN 格式的着法列表"""
        try:
            cb = chess.Board()
            san_moves = []
            for uci_m in move_history:
                mv = chess.Move.from_uci(uci_m)
                san_moves.append(cb.san(mv))
                cb.push(mv)
            return san_moves
        except Exception:
            return list(move_history)

    @staticmethod
    def _compute_fen(move_history):
        """计算当前局面的 FEN 字符串"""
        try:
            cb = chess.Board()
            for uci_m in move_history:
                cb.push(chess.Move.from_uci(uci_m))
            return cb.fen()
        except Exception:
            return ""


# 模块级单例，保持向后兼容
match_state = MatchState()
match_lock = match_state._lock


def match_board_to_dict():
    """向后兼容：将当前对局状态转换为字典"""
    return match_state.to_dict()


def _engine_is_alive(eng):
    return eng.process is not None and eng.process.poll() is None


def _has_legal_moves(move_history):
    """检查当前局面是否有合法走法"""
    try:
        cb = chess.Board()
        for uci_m in move_history:
            cb.push(chess.Move.from_uci(uci_m))
        return any(True for _ in cb.legal_moves)
    except Exception:
        return False


def _compute_position_key(board, castling, side):
    """计算局面位置键，用于三次重复检测"""
    pos_key = "".join("".join(row) for row in board)
    pos_key += f" {'w' if side == 0 else 'b'}"
    castling_str = ""
    if castling.get("K"):
        castling_str += "K"
    if castling.get("Q"):
        castling_str += "Q"
    if castling.get("k"):
        castling_str += "k"
    if castling.get("q"):
        castling_str += "q"
    pos_key += castling_str
    ep_sq = castling.get("ep_square", "-")
    if ep_sq:
        pos_key += str(ep_sq)
    else:
        pos_key += "-"
    return pos_key


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
        if not _engine_is_alive(eng):
            print(f"[MATCH-DBG] {tag} -> path C: engine died during ponder!")
            return None, None
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
    # 给主线程时间完成 HTTP 响应，避免 GIL 竞争导致请求卡死
    time_mod.sleep(0.2)

    extra_opts = extra_opts or {}
    e1, entry1 = resolve_engine(engine1_id, extra_opts.get(engine1_id, {}))
    e2, entry2 = resolve_engine(engine2_id, extra_opts.get(engine2_id, {}))

    if not e1 or not e2:
        match_state.set_game_over(True, "引擎配置无效")
        match_state.set_active(False)
        sse_notify(match_board_to_dict())
        return

    match_state.set_engine_names(engine1_name, engine2_name)

    try:
        if not e1.start():
            match_state.set_game_over(True, f"{engine1_name} 启动失败")
            match_state.set_active(False)
            sse_notify(match_board_to_dict())
            return
        if not e2.start():
            match_state.set_game_over(True, f"{engine2_name} 启动失败")
            match_state.set_active(False)
            sse_notify(match_board_to_dict())
            return

        for game_idx in range(total_games):
            if not match_state.active:
                break

            even_game = (game_idx % 2 == 0)
            if even_game:
                white_engine, black_engine = e1, e2
                white_name, black_name = engine1_name, engine2_name
            else:
                white_engine, black_engine = e2, e1
                white_name, black_name = engine2_name, engine1_name

            white_engine.new_game()
            black_engine.new_game()

            if (white_engine.process is None or white_engine.process.poll() is not None):
                match_state.set_game_over(True, f"{white_name} 引擎进程异常退出")
                match_state.add_score(winner_is_white=False, even_game=even_game)
                sse_notify(match_board_to_dict())
                break
            if (black_engine.process is None or black_engine.process.poll() is not None):
                match_state.set_game_over(True, f"{black_name} 引擎进程异常退出")
                match_state.add_score(winner_is_white=True, even_game=even_game)
                sse_notify(match_board_to_dict())
                break

            match_state.reset_game(white_name, black_name, game_idx)
            sse_notify(match_board_to_dict())

            times = [time_base, time_base]
            repetition_count = {}
            last_ponder_moves = {0: None, 1: None}

            for move_num in range(300):
                if not match_state.active:
                    break

                side = move_num % 2
                eng = white_engine if side == 0 else black_engine
                opp_eng = black_engine if side == 0 else white_engine
                eng_name = white_name if side == 0 else black_name

                if not _engine_is_alive(eng):
                    if opp_eng.is_pondering():
                        opp_eng.stop_ponder()
                    match_state.set_game_over(True, f"{eng_name} 引擎进程异常退出")
                    match_state.add_score(winner_is_white=(side == 1), even_game=even_game)
                    sse_notify(match_board_to_dict())
                    break

                wtime = times[0]
                btime = times[1]

                move_start = time_mod.time()

                opp_side = 1 - side
                ponder_from_opponent = last_ponder_moves.get(side)
                current_history = match_state.move_history
                opp_actual_move = current_history[-1] if current_history else None
                ponder_hit = (ponder_from_opponent is not None and
                              opp_actual_move is not None and
                              ponder_from_opponent == opp_actual_move)

                eng_is_hellcopter = (engine1_id == "hellcopter" and eng is e1) or (engine2_id == "hellcopter" and eng is e2)
                best_move, ponder_move = _engine_get_move_with_ponder(
                    eng, current_history, wtime, btime, time_inc, time_inc,
                    ponder_move_from_opponent=ponder_hit,
                    use_ponder=eng_is_hellcopter
                )

                last_ponder_moves[side] = ponder_move if eng_is_hellcopter else None

                elapsed = int((time_mod.time() - move_start) * 1000)

                if not best_move or len(best_move) < 4 or best_move == "0000" or best_move == "(none)":
                    print(f"[MATCH] {eng_name} 返回无效走法: '{best_move}', move_num={move_num}, history={match_state.last_move_history_slice}")
                    if opp_eng.is_pondering():
                        opp_eng.stop_ponder()
                    in_check = is_in_check(match_state.board, side)
                    has_legal_moves = _has_legal_moves(current_history)
                    if in_check:
                        winner_side = 1 - side
                        winner_name = white_name if winner_side == 0 else black_name
                        match_state.set_game_over(True, f"{eng_name} 被将杀，{winner_name} 获胜！")
                        match_state.add_score(winner_is_white=(winner_side == 0), even_game=even_game)
                    elif has_legal_moves:
                        winner_side = 1 - side
                        winner_name = white_name if winner_side == 0 else black_name
                        match_state.set_game_over(True, f"{eng_name} 返回无效走法（有合法走法但返回0000），{winner_name} 获胜！")
                        match_state.add_score(winner_is_white=(winner_side == 0), even_game=even_game)
                    else:
                        match_state.set_game_over(True, f"{eng_name} 无合法走法（逼和），和棋！")
                        match_state.add_draw_score()
                    sse_notify(match_board_to_dict())
                    break

                if best_move[0:2] == best_move[2:4] and best_move != "0000":
                    print(f"[MATCH] {eng_name} 返回非法走法: '{best_move}' (起止格相同), move_num={move_num}")
                    if opp_eng.is_pondering():
                        opp_eng.stop_ponder()
                    winner_side = 1 - side
                    winner_name = white_name if winner_side == 0 else black_name
                    match_state.set_game_over(True, f"{eng_name} 返回非法走法 '{best_move}'（起止格相同），{winner_name} 获胜！")
                    match_state.add_score(winner_is_white=(winner_side == 0), even_game=even_game)
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
                    match_state.set_game_over(True, f"{eng_name} 超时，{winner_name} 获胜！")
                    match_state.add_score(winner_is_white=(winner_side == 0), even_game=even_game)
                    sse_notify(match_board_to_dict())
                    break

                # 验证并应用走法
                move_applied = False
                with match_state._lock:
                    chess_board = chess.Board()
                    rebuild_ok = True
                    for prev_move in match_state._state["move_history"]:
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
                            match_state._state["game_over"] = True
                            winner_side = 1 - side
                            winner_name = white_name if winner_side == 0 else black_name
                            match_state._state["game_result"] = f"{eng_name} 返回非法走法 '{best_move}'，{winner_name} 获胜！"
                            match_state.add_score(winner_is_white=(winner_side == 0), even_game=even_game)
                            sse_notify(match_board_to_dict())
                            break
                    except ValueError:
                        print(f"[MATCH] {eng_name} 返回无效走法格式: '{best_move}', move_num={move_num}")
                        if opp_eng.is_pondering():
                            opp_eng.stop_ponder()
                        match_state._state["game_over"] = True
                        winner_side = 1 - side
                        winner_name = white_name if winner_side == 0 else black_name
                        match_state._state["game_result"] = f"{eng_name} 返回无效走法 '{best_move}'，{winner_name} 获胜！"
                        match_state.add_score(winner_is_white=(winner_side == 0), even_game=even_game)
                        sse_notify(match_board_to_dict())
                        break

                    match_state._state["move_history"].append(best_move)
                    try:
                        new_board, new_ep, new_castling = apply_move(
                            match_state._state["board"], best_move,
                            match_state._state["ep_target"], match_state._state["castling"]
                        )
                        match_state._state["board"] = new_board
                        match_state._state["ep_target"] = new_ep
                        match_state._state["castling"] = new_castling
                    except Exception as ex:
                        print(f"[MATCH] {eng_name} 走法应用失败: '{best_move}', 异常={ex}, move_num={move_num}, history={match_state._state['move_history'][-6:]}")
                        if opp_eng.is_pondering():
                            opp_eng.stop_ponder()
                        winner_side = 1 - side
                        winner_name = white_name if winner_side == 0 else black_name
                        match_state._state["game_over"] = True
                        match_state._state["game_result"] = f"{eng_name} 返回非法走法 '{best_move}'，{winner_name} 获胜！"
                        match_state.add_score(winner_is_white=(winner_side == 0), even_game=even_game)
                        sse_notify(match_board_to_dict())
                        break
                    match_state._state["last_move"] = best_move
                    match_state._state["move_count"] = move_num + 1
                    match_state._state["engine1_time"] = times[0]
                    match_state._state["engine2_time"] = times[1]
                    move_applied = True

                if not move_applied:
                    break

                pos_key = _compute_position_key(match_state.board, match_state.castling, side)
                repetition_count[pos_key] = repetition_count.get(pos_key, 0) + 1
                if repetition_count[pos_key] >= 3:
                    if opp_eng.is_pondering():
                        opp_eng.stop_ponder()
                    match_state.set_game_over(True, "三次重复，和棋！")
                    match_state.add_draw_score()
                    sse_notify(match_board_to_dict())
                    break

                # 50步和棋规则检测
                halfmove = match_state.get("halfmove_clock", 0)
                if halfmove >= 100:
                    if opp_eng.is_pondering():
                        opp_eng.stop_ponder()
                    match_state.set_game_over(True, "50步无吃子无兵动，和棋！")
                    match_state.add_draw_score()
                    sse_notify(match_board_to_dict())
                    break

                sse_notify(match_board_to_dict())

                opp_is_hellcopter = (engine1_id == "hellcopter" and opp_eng is e1) or (engine2_id == "hellcopter" and opp_eng is e2)
                if opp_is_hellcopter and opp_eng.protocol == "uci" and not match_state.game_over:
                    opp_wtime = times[0] if opp_side == 0 else times[1]
                    opp_btime = times[1] if opp_side == 0 else times[0]
                    # 对手引擎 ponder：使用对手引擎上次返回的 ponder 着法
                    # 这样对手引擎在 "假设对手走了 ponder 着法" 的位置上搜索
                    opp_ponder_move = opp_eng.get_ponder_move()
                    opp_eng.start_ponder(
                        match_state.move_history,
                        opp_wtime, opp_btime, time_inc, time_inc,
                        ponder_move=opp_ponder_move
                    )

                time_mod.sleep(0.1)

            match_state.set_games_played(game_idx + 1)
            if not match_state.game_over:
                match_state.set_game_over(True, "超过300步，和棋！")
                match_state.add_draw_score()
            sse_notify(match_board_to_dict())

            # 保存对局记录
            try:
                from web_chess import _save_game_pgn
                result_str = match_state._state.get("game_result", "*")
                if "白方" in result_str or "1-0" in result_str:
                    pgn_result = "1-0"
                elif "黑方" in result_str or "0-1" in result_str:
                    pgn_result = "0-1"
                elif "和棋" in result_str or "1/2" in result_str:
                    pgn_result = "1/2-1/2"
                else:
                    pgn_result = "*"
                _save_game_pgn(
                    match_state.move_history,
                    white_name, black_name,
                    pgn_result,
                    game_id=f"game_{datetime.now().strftime('%Y%m%d_%H%M%S')}_g{game_idx + 1}"
                )
            except Exception as ex:
                print(f"[MATCH] Failed to save game: {ex}")

    finally:
        e1.quit()
        e2.quit()
        match_state.set_active(False)
        sse_notify(match_board_to_dict())
