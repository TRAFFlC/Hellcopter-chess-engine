import json
import os
import shutil
import sys
import threading
import time
import chess
import engine
import engine_wrapper
import book_provider


class UCIEngine:
    def __init__(self):
        self.board = chess.Board()
        self.eng = engine.ChessEngine()
        self.position_history = []
        self.search_thread = None
        self.stop_event = threading.Event()
        self._search_gen = 0  # 搜索代际计数器，防止过期搜索输出 bestmove
        self.book_manager = book_provider.BookManager()
        self._book_config = {
            'mode': 'internal',
            'own_book': True,
            'path': '',
            'max_ply': 20,
            'randomness': 0,
            'min_score': -9999,
            'exit_bonus_time': 0.1,
            'tournament_mode': False
        }
        self._load_opening_book()
        self._init_syzygy()

    def send(self, msg):
        print(msg, flush=True)

    def _load_opening_book(self):
        if self._book_config['path']:
            book_path = self._book_config['path']
        elif getattr(sys, 'frozen', False):
            # exe 模式：检查多个候选路径
            candidates = [
                os.path.join(sys._MEIPASS, "Goi5.1.bin"),
                os.path.join(sys._MEIPASS, "dist", "Goi5.1.bin"),
                os.path.join(os.path.dirname(sys.executable), "Goi5.1.bin"),
            ]
            book_path = ""
            for p in candidates:
                if os.path.isfile(p):
                    book_path = p
                    break
            if not book_path:
                book_path = candidates[0]  # fallback
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
            book_path = os.path.join(base_path, "dist", "Goi5.1.bin")

        self.book_manager.configure(
            mode=self._book_config['mode'],
            own_book=self._book_config['own_book'],
            book_path=book_path,
            max_ply=self._book_config['max_ply'],
            randomness=self._book_config['randomness'] / 100.0,
            min_score=self._book_config['min_score'],
            exit_bonus_time=self._book_config['exit_bonus_time'],
            tournament_mode=self._book_config['tournament_mode']
        )

    def _init_syzygy(self):
        # 候选路径列表
        candidates = []

        if getattr(sys, 'frozen', False):
            # exe 模式：优先检查 exe 所在目录，再检查临时解压目录
            exe_dir = os.path.dirname(sys.executable)
            candidates.append(os.path.join(exe_dir, "syzygy"))
            candidates.append(os.path.join(sys._MEIPASS, "dist", "syzygy"))
            candidates.append(os.path.join(sys._MEIPASS, "syzygy"))
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
            candidates.append(os.path.join(base_path, "dist", "syzygy"))

        for syzygy_path in candidates:
            if os.path.isdir(syzygy_path) and any(
                f.endswith(".rtbw") for f in os.listdir(syzygy_path)
            ):
                result = engine_wrapper.init_syzygy(syzygy_path)
                if result > 0:
                    self.send(
                        f"info string Syzygy loaded: {syzygy_path} (TB_LARGEST={result})")
                    return
                else:
                    self.send(
                        f"info string Syzygy path found but failed to load: {syzygy_path}")

        self.send("info string Syzygy not found")

    def cmd_uci(self):
        self.send("id name Hellcopter")
        self.send("id author Trafflc")

        self.send("option name OwnBook type check default true")
        self.send("option name BookPath type string default")
        self.send(
            "option name BookMode type combo default internal var off var internal var generic var hybrid")
        self.send("option name BookMaxPly type spin default 20 min 0 max 100")
        self.send("option name BookRandomness type spin default 0 min 0 max 100")
        self.send(
            "option name BookMinScore type spin default -9999 min -32767 max 32767")
        self.send(
            "option name BookExitBonusTime type spin default 10 min 0 max 100")
        self.send("option name TournamentMode type check default false")
        self.send("option name Ponder type check default false")

        self.send("uciok")

    def cmd_isready(self):
        self.send("readyok")

    def cmd_ucinewgame(self):
        self._stop_search()
        env_path = os.environ.get("ENGINE_PARAMS")
        if env_path and os.path.isfile(env_path):
            dest = os.path.join(os.getcwd(), "engine_params.json")
            src_real = os.path.realpath(env_path)
            dest_real = os.path.realpath(dest)
            if src_real != dest_real:
                shutil.copy2(env_path, dest)
        self.eng = engine.ChessEngine()
        self.position_history = []
        self.board = chess.Board()

    def cmd_position(self, args):
        tokens = args.split()
        if not tokens:
            return

        idx = 0
        if tokens[idx] == "startpos":
            self.board = chess.Board()
            idx += 1
        elif tokens[idx] == "fen":
            idx += 1
            fen_parts = []
            while idx < len(tokens) and tokens[idx] != "moves":
                fen_parts.append(tokens[idx])
                idx += 1
            self.board = chess.Board(" ".join(fen_parts))
        else:
            return

        self.position_history = []
        self.position_history.append(
            engine_wrapper.compute_hash(self.board.fen()))

        if idx < len(tokens) and tokens[idx] == "moves":
            idx += 1
            while idx < len(tokens):
                try:
                    move = chess.Move.from_uci(tokens[idx])
                    self.board.push(move)
                    self.position_history.append(
                        engine_wrapper.compute_hash(self.board.fen()))
                except ValueError:
                    pass
                idx += 1

    def cmd_go(self, args):
        self._stop_search()
        self.stop_event.clear()
        self._search_gen += 1
        gen = self._search_gen

        current_ply = self.board.fullmove_number * 2 - \
            (2 if self.board.turn == chess.WHITE else 1)

        # 诊断日志：记录开局库查找
        self.send(
            f"info string [DIAG] cmd_go: book_loaded={self.book_manager.loaded}, mode={self.book_manager._mode}, ply={current_ply}")

        book_move = self.book_manager.get_book_move(self.board, current_ply)

        # 诊断日志：记录开局库结果
        self.send(f"info string [DIAG] cmd_go: book_move={book_move}")

        if book_move:
            try:
                move = chess.Move.from_uci(book_move)
                if move in self.board.legal_moves:
                    # Book hit: return immediately without searching
                    self.send(
                        f"info depth 0 score cp 0 nodes 0 time 0 pv {book_move}")
                    self.send(f"bestmove {book_move}")
                    return
            except ValueError:
                pass

        params = {}
        tokens = args.split()
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t in ("wtime", "btime", "winc", "binc", "depth",
                     "movetime", "movestime", "movestogo") and i + 1 < len(tokens):
                params[t] = int(tokens[i + 1])
                i += 2
            else:
                i += 1

        infinite = "infinite" in tokens
        pondering = "ponder" in tokens
        if pondering:
            infinite = True
        optimal_time, max_time, remaining, inc = self._compute_time(params)

        # 出书后的时间调整：刚离开开局库时大幅减少思考时间
        # 开局库相当于标准答案，不需要过度思考
        book_exit_factor = self.book_manager.get_book_exit_time_factor()
        if book_exit_factor < 1.0:
            optimal_time *= book_exit_factor
            max_time *= book_exit_factor

        exit_bonus = self.book_manager.get_exit_bonus_time(optimal_time)
        if exit_bonus > 0:
            optimal_time += exit_bonus

        # 注意：max_depth=0（默认）让 C 端按时间控制（time_limit）。
        # max_depth>0 时 C 端会忽略 time_limit、改跑固定深度（time_limit 被替换为 3600s，
        # 见 src/engine_search_root.c 的 fallback 逻辑）。
        max_depth = params.get("depth", 0)

        time_left_for_engine = 0.0
        increment_for_engine = 0.0
        moves_to_go_for_engine = 0
        move_number_for_engine = 0

        if not infinite and "movetime" not in params and "movestime" not in params:
            time_left_for_engine = remaining
            increment_for_engine = inc
            move_number_for_engine = self.board.fullmove_number
            if "movestogo" in params:
                moves_to_go_for_engine = params["movestogo"]

        board_copy = self.board.copy()
        hist_copy = list(self.position_history)

        self.search_thread = threading.Thread(
            target=self._search_worker,
            args=(board_copy, hist_copy, optimal_time, max_depth, infinite,
                  time_left_for_engine, increment_for_engine,
                  moves_to_go_for_engine, move_number_for_engine, gen),
            daemon=True,
        )
        self.search_thread.start()

    def _compute_time(self, params):
        movetime = params.get("movetime") or params.get("movestime")
        if movetime is not None:
            optimal = movetime / 1000.0
            return optimal, optimal, 0.0, 0.0

        wtime = params.get("wtime")
        btime = params.get("btime")
        winc = params.get("winc", 0)
        binc = params.get("binc", 0)

        if self.board.turn == chess.WHITE and wtime is not None:
            inc = winc / 1000.0
            remaining = wtime / 1000.0
        elif self.board.turn == chess.BLACK and btime is not None:
            inc = binc / 1000.0
            remaining = btime / 1000.0
        else:
            return 2.0, 2.0, 0.0, 0.0

        move_num = self.board.fullmove_number

        if move_num <= 10:
            estimated_moves_left = 40 - move_num
            time_fraction = 0.5
        elif move_num <= 20:
            estimated_moves_left = 30
            time_fraction = 0.8
        elif move_num <= 40:
            estimated_moves_left = max(15, 50 - move_num)
            time_fraction = 1.0
        else:
            estimated_moves_left = max(10, 60 - move_num)
            time_fraction = 1.2

        optimal = remaining / estimated_moves_left + inc * 0.85
        optimal = min(optimal, remaining * 0.5)
        optimal *= time_fraction

        if inc > 0:
            optimal = max(optimal, inc * 0.9)

        if remaining < inc * 3 and inc > 0:
            optimal = min(optimal, inc * 0.95)

        try:
            legal_moves = list(self.board.legal_moves)
            if len(legal_moves) > 30:
                optimal *= 1.2
            elif len(legal_moves) > 20:
                optimal *= 1.1
        except Exception:
            pass

        optimal = max(0.05, optimal)
        max_time = min(remaining * 0.6, optimal * 5)
        return optimal, max_time, remaining, inc

    def _search_worker(self, board, pos_hist, time_limit, max_depth, infinite,
                       time_left=0.0, increment=0.0, moves_to_go=0, move_number=0,
                       gen=0):
        if infinite:
            search_time = 3600.0  # ponder/infinite: 搜索直到收到 stop
        else:
            search_time = time_limit

        search_start = time.perf_counter()
        fen = board.fen()
        try:
            uci_move, score, nodes = engine_wrapper.search_with_score(
                fen, search_time, max_depth, position_history=pos_hist,
                time_left=time_left, increment=increment,
                moves_to_go=moves_to_go, move_number=move_number
            )
        except Exception:
            uci_move, score, nodes = None, 0, 0

        elapsed = time.perf_counter() - search_start

        # 检查代际计数器：如果已有新搜索启动，跳过输出
        if gen != self._search_gen:
            return

        if uci_move and len(uci_move) >= 4:
            try:
                move = chess.Move.from_uci(uci_move)
                if move in board.legal_moves:
                    # Get actual depth from engine
                    try:
                        depth = engine_wrapper.get_last_search_info(
                            0)  # 0 = depth
                    except:
                        depth = 1
                    time_ms = int(elapsed * 1000)
                    MATE_SCORE = 900000
                    if score > MATE_SCORE - 100:
                        # Winning mate: convert ply distance to full moves
                        mate_in = (MATE_SCORE - score + 1) // 2
                        self.send(
                            f"info depth {depth} score mate {mate_in} nodes {nodes} time {time_ms}")
                    elif score < -(MATE_SCORE - 100):
                        # Losing mate: negative full moves
                        mate_in = -((MATE_SCORE + score + 1) // 2)
                        self.send(
                            f"info depth {depth} score mate {mate_in} nodes {nodes} time {time_ms}")
                    else:
                        self.send(
                            f"info depth {depth} score cp {score} nodes {nodes} time {time_ms}")
                    self.send(f"bestmove {uci_move}")
                else:
                    self.send("bestmove 0000")
            except ValueError:
                self.send("bestmove 0000")
        else:
            self.send("bestmove 0000")

    def _stop_search(self, discard=True):
        if discard:
            self._search_gen += 1
        self.stop_event.set()
        self.eng.search_aborted = True
        engine_wrapper.set_engine_abort(1)
        if self.search_thread is not None and self.search_thread.is_alive():
            self.search_thread.join(timeout=3.0)
            if self.search_thread.is_alive():
                self.send(
                    "info string WARNING: search thread did not stop within 3s")
        engine_wrapper.set_engine_abort(0)
        self.search_thread = None

    def cmd_stop(self):
        # UCI stop: 如果搜索线程正在运行，让它输出当前找到的最佳走法
        # 关键：不递增 _search_gen，这样搜索线程的 gen 检查会通过
        if self.search_thread is not None and self.search_thread.is_alive():
            # 搜索仍在运行，设置 abort 并等待线程完成
            self.stop_event.set()
            self.eng.search_aborted = True
            engine_wrapper.set_engine_abort(1)
            self.search_thread.join(timeout=3.0)
            engine_wrapper.set_engine_abort(0)
            if self.search_thread.is_alive():
                # 线程未在3秒内停止，递增 gen 丢弃其结果，输出兜底
                self._search_gen += 1
                self.search_thread = None
                self.send("bestmove 0000")
            else:
                # 线程已停止，它应该已经输出了 bestmove（gen 匹配）
                self.search_thread = None
        else:
            # 搜索已完成或未启动，bestmove 已由 _search_worker 输出
            self.search_thread = None

    def cmd_setoption(self, args):
        tokens = args.split()
        name_idx = -1
        value_idx = -1

        for i, t in enumerate(tokens):
            if t == "name" and i + 1 < len(tokens):
                name_idx = i + 1
            elif t == "value" and i + 1 < len(tokens):
                value_idx = i + 1

        if name_idx < 0:
            return

        name = tokens[name_idx]
        value = tokens[value_idx] if value_idx >= 0 else ""

        # 诊断日志：记录所有选项变更
        self.send(f"info string [DIAG] setoption: name={name} value={value}")

        if name == "OwnBook":
            self._book_config['own_book'] = value.lower() == 'true'
        elif name == "BookPath":
            self._book_config['path'] = value
        elif name == "BookMode":
            self._book_config['mode'] = value
        elif name == "BookMaxPly":
            self._book_config['max_ply'] = int(value)
        elif name == "BookRandomness":
            self._book_config['randomness'] = int(value)
        elif name == "BookMinScore":
            self._book_config['min_score'] = int(value)
        elif name == "BookExitBonusTime":
            self._book_config['exit_bonus_time'] = int(value) / 100.0
        elif name == "TournamentMode":
            self._book_config['tournament_mode'] = value.lower() == 'true'
        elif name == "SyzygyPath":
            if value:
                result = engine_wrapper.init_syzygy(value)
                if result > 0:
                    self.send(
                        f"info string Syzygy loaded: {value} (TB_LARGEST={result})")
                else:
                    self.send(f"info string Syzygy failed to load: {value}")
            return

        self._load_opening_book()

    def run(self):
        while True:
            try:
                line = input()
            except EOFError:
                break

            line = line.strip()
            if not line:
                continue

            parts = line.split(None, 1)
            cmd = parts[0]
            arg = parts[1] if len(parts) > 1 else ""

            if cmd == "uci":
                self.cmd_uci()
            elif cmd == "isready":
                self.cmd_isready()
            elif cmd == "ucinewgame":
                self.cmd_ucinewgame()
            elif cmd == "position":
                self.cmd_position(arg)
            elif cmd == "go":
                self.cmd_go(arg)
            elif cmd == "stop":
                self.cmd_stop()
            elif cmd == "setoption":
                self.cmd_setoption(arg)
            elif cmd == "quit":
                self._stop_search()
                break


def main():
    uci = UCIEngine()
    uci.run()


if __name__ == "__main__":
    main()
