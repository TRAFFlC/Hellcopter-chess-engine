import json
import os
import shutil
import sys
import threading
import time
import chess
import engine
import engine_wrapper


class OpeningBook:
    def __init__(self):
        self.entries = {}
        self.loaded = False
        
    def load(self, path: str):
        if not os.path.isfile(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.entries = data.get("entries", {})
            self.loaded = True
            return True
        except Exception:
            return False
    
    def get_position_key(self, board: chess.Board) -> str:
        parts = board.fen().split()
        return f"{parts[0]} {parts[1]}"
    
    def lookup(self, board: chess.Board) -> tuple[str | None, dict]:
        if not self.loaded:
            return None, {}
        pos_key = self.get_position_key(board)
        entry = self.entries.get(pos_key)
        if not entry:
            return None, {}
        preferred = entry.get("preferred")
        evals = entry.get("hellcopter_eval", {})
        return preferred, evals


class UCIEngine:
    def __init__(self):
        self.board = chess.Board()
        self.eng = engine.ChessEngine()
        self.position_history = []
        self.search_thread = None
        self.stop_event = threading.Event()
        self.opening_book = OpeningBook()
        self._load_opening_book()

    def send(self, msg):
        print(msg, flush=True)
    
    def _load_opening_book(self):
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        book_path = os.path.join(base_path, "opening_book.json")
        if self.opening_book.load(book_path):
            pass

    def cmd_uci(self):
        self.send("id name Hellcopter")
        self.send("id author Trafflc")
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

        preferred_move, evals = self.opening_book.lookup(self.board)
        if preferred_move:
            try:
                move = chess.Move.from_uci(preferred_move)
                if move in self.board.legal_moves:
                    score = evals.get(preferred_move, 0)
                    self.send(f"info depth 0 score cp {score} nodes 0 time 0 pv {preferred_move}")
                    self.send(f"bestmove {preferred_move}")
                    return
            except ValueError:
                pass

        params = {}
        tokens = args.split()
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t in ("wtime", "btime", "winc", "binc", "depth",
                     "movetime", "movestime") and i + 1 < len(tokens):
                params[t] = int(tokens[i + 1])
                i += 2
            else:
                i += 1

        infinite = "infinite" in tokens
        time_limit = self._compute_time(params)
        max_depth = params.get("depth", 100)

        board_copy = self.board.copy()
        hist_copy = list(self.position_history)

        self.search_thread = threading.Thread(
            target=self._search_worker,
            args=(board_copy, hist_copy, time_limit, max_depth, infinite),
            daemon=True,
        )
        self.search_thread.start()

    def _compute_time(self, params):
        movetime = params.get("movetime") or params.get("movestime")
        if movetime is not None:
            return movetime / 1000.0

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
            return 2.0

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

        time_limit = remaining / estimated_moves_left + inc * 0.85
        time_limit = min(time_limit, remaining * 0.5)
        time_limit *= time_fraction

        if inc > 0:
            time_limit = max(time_limit, inc * 0.9)

        if remaining < inc * 3 and inc > 0:
            time_limit = min(time_limit, inc * 0.95)

        return max(0.05, time_limit)

    def _search_worker(self, board, pos_hist, time_limit, max_depth, infinite):
        if infinite:
            search_time = 2.0
        else:
            search_time = time_limit

        search_start = time.perf_counter()
        fen = board.fen()
        try:
            uci_move, score, nodes = engine_wrapper.search_with_score(
                fen, search_time, max_depth, position_history=pos_hist
            )
        except Exception:
            uci_move, score, nodes = None, 0, 0

        elapsed = time.perf_counter() - search_start

        if uci_move and len(uci_move) >= 4:
            try:
                move = chess.Move.from_uci(uci_move)
                if move in board.legal_moves:
                    # Get actual depth from engine
                    try:
                        depth = engine_wrapper.get_last_search_info(0)  # 0 = depth
                    except:
                        depth = 1
                    time_ms = int(elapsed * 1000)
                    if abs(score) >= 30000:
                        mate_in = (32767 - abs(score) + 1) // 2
                        if score < 0:
                            mate_in = -mate_in
                        self.send(f"info depth {depth} score mate {mate_in} nodes {nodes} time {time_ms}")
                    else:
                        self.send(f"info depth {depth} score cp {score} nodes {nodes} time {time_ms}")
                    self.send(f"bestmove {uci_move}")
                else:
                    self.send("bestmove 0000")
            except ValueError:
                self.send("bestmove 0000")
        else:
            self.send("bestmove 0000")

    def _stop_search(self):
        self.stop_event.set()
        self.eng.search_aborted = True
        if self.search_thread is not None and self.search_thread.is_alive():
            self.search_thread.join()
        self.search_thread = None

    def cmd_stop(self):
        self._stop_search()

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
            elif cmd == "quit":
                self._stop_search()
                break


def main():
    uci = UCIEngine()
    uci.run()


if __name__ == "__main__":
    main()
