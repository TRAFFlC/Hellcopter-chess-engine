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

    def send(self, msg):
        print(msg, flush=True)
    
    def _load_opening_book(self):
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        book_path = self._book_config['path'] or os.path.join(base_path, "dist", "book.bin")
        
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

    def cmd_uci(self):
        self.send("id name Hellcopter")
        self.send("id author Trafflc")
        
        self.send("option name OwnBook type check default true")
        self.send("option name BookPath type string default")
        self.send("option name BookMode type combo default internal var off var internal var generic var hybrid")
        self.send("option name BookMaxPly type spin default 20 min 0 max 100")
        self.send("option name BookRandomness type spin default 0 min 0 max 100")
        self.send("option name BookMinScore type spin default -9999 min -32767 max 32767")
        self.send("option name BookExitBonusTime type spin default 10 min 0 max 100")
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

        current_ply = self.board.fullmove_number * 2 - (2 if self.board.turn == chess.WHITE else 1)
        book_move = self.book_manager.get_book_move(self.board, current_ply)
        if book_move:
            try:
                move = chess.Move.from_uci(book_move)
                if move in self.board.legal_moves:
                    self.send(f"info depth 0 score cp 0 nodes 0 time 0 pv {book_move}")
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
        optimal_time, max_time, remaining, inc = self._compute_time(params)
        
        exit_bonus = self.book_manager.get_exit_bonus_time(optimal_time)
        if exit_bonus > 0:
            optimal_time += exit_bonus
        
        max_depth = params.get("depth", 100)

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
                  moves_to_go_for_engine, move_number_for_engine),
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
        engine_wrapper.set_engine_abort(1)
        if self.search_thread is not None and self.search_thread.is_alive():
            self.search_thread.join()
        engine_wrapper.set_engine_abort(0)
        self.search_thread = None

    def cmd_stop(self):
        self._stop_search()

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
