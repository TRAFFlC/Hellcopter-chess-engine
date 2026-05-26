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
                     "movetime", "movestime", "movestogo") and i + 1 < len(tokens):
                params[t] = int(tokens[i + 1])
                i += 2
            else:
                i += 1

        infinite = "infinite" in tokens
        optimal_time, max_time = self._compute_time(params)
        max_depth = params.get("depth", 100)

        time_left_for_engine = 0.0
        increment_for_engine = 0.0
        moves_to_go_for_engine = 0
        move_number_for_engine = 0

        if not infinite and "movetime" not in params and "movestime" not in params:
            time_left_for_engine = max_time

        board_copy = self.board.copy()
        hist_copy = list(self.position_history)

        self.search_thread = threading.Thread(
            target=self._search_worker,
            args=(board_copy, hist_copy, optimal_time, max_depth, infinite,
                  time_left_for_engine, increment_for_engine,
                  moves_to_go_for_engine, move_number_for_engine),
            daemon=True,
        )
        self.search_thread.start()

    def _compute_time(self, params):
        movetime = params.get("movetime") or params.get("movestime")
        if movetime is not None:
            optimal = movetime / 1000.0
            return optimal, optimal

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
            return 2.0, 2.0

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

        optimal = max(0.05, optimal)
        max_time = min(remaining * 0.6, optimal * 5)
        return optimal, max_time

    def _search_worker(self, board, pos_hist, time_limit, max_depth, infinite,
                        time_left=0.0, increment=0.0, moves_to_go=0, move_number=0):
        if infinite:
            search_time = 2.0
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
