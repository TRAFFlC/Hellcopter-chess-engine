import os
import shutil
import threading
import time
import chess
import engine
import engine_wrapper


class UCIEngine:
    def __init__(self):
        self.board = chess.Board()
        self.eng = engine.ChessEngine()
        self.position_history = []
        self.search_thread = None
        self.stop_event = threading.Event()

    def send(self, msg):
        print(msg, flush=True)

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
            shutil.copy2(env_path, os.path.join(os.getcwd(), "engine_params.json"))
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

        estimated_moves_left = max(10, 40 - self.board.fullmove_number)
        if estimated_moves_left > 20:
            estimated_moves_left = 20 + (estimated_moves_left - 20) * 0.5

        time_limit = remaining / estimated_moves_left + inc * 0.85
        time_limit = min(time_limit, remaining * 0.5)

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
                    depth = max_depth if max_depth < 100 else 1
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
