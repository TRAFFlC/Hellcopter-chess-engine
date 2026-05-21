import argparse
import json
import os
import subprocess
import sys
import time
import re
from datetime import datetime
from typing import Optional

import chess
import engine_wrapper


VELVET_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "test_engines", "Velvet", "velvet-v8.1.1-x86_64-avx2.exe"
)

OPPONENTS = {
    "tscp181": {
        "path": os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "test_engines", "TSCP 1607", "tscp181.exe"),
        "proto": "xboard",
    },
    "apollo": {
        "path": os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "test_engines", "Apollo 1663", "apollo.exe"),
        "proto": "uci",
    },

    "monarch": {
        "path": os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "test_engines", "Monarch 2005", "Monarch(v1.7)", "Monarch(v1.7).exe"),
        "proto": "uci",
    },
}

MAX_HALF_MOVES = 6
TIME_PER_MOVE = 0.5


def get_position_key(board: chess.Board) -> str:
    parts = board.fen().split()
    return f"{parts[0]} {parts[1]}"


def evaluate_with_hellcopter(board: chess.Board, time_limit: float = 0.3) -> int:
    fen = board.fen()
    try:
        _, score, _ = engine_wrapper.search_with_score(fen, time_limit, 10)
        return score
    except Exception:
        return 0


class VelvetEngine:
    def __init__(self, path: str):
        self.path = path
        self.process: Optional[subprocess.Popen] = None
        
    def start(self):
        self.process = subprocess.Popen(
            [self.path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._send("uci")
        self._wait_for("uciok")
        
    def _send(self, cmd: str):
        if self.process and self.process.stdin:
            self.process.stdin.write(cmd + "\n")
            self.process.stdin.flush()
            
    def _wait_for(self, target: str, timeout: float = 10.0) -> Optional[str]:
        if not self.process or not self.process.stdout:
            return None
        start = time.perf_counter()
        while True:
            if time.perf_counter() - start > timeout:
                return None
            line = self.process.stdout.readline().strip()
            if target in line:
                return line
            
    def _read_until_bestmove(self, timeout: float = 5.0) -> Optional[str]:
        if not self.process or not self.process.stdout:
            return None
        start = time.perf_counter()
        while True:
            if time.perf_counter() - start > timeout:
                return None
            line = self.process.stdout.readline().strip()
            if line.startswith("bestmove"):
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1]
        return None
    
    def new_game(self):
        self._send("ucinewgame")
        self._send("isready")
        self._wait_for("readyok")
        
    def set_position(self, moves: list[str] = None):
        if moves:
            self._send(f"position startpos moves {' '.join(moves)}")
        else:
            self._send("position startpos")
            
    def go(self, time_ms: int = 500) -> Optional[str]:
        self._send(f"go movetime {time_ms}")
        return self._read_until_bestmove(timeout=time_ms / 1000.0 + 2.0)
    
    def quit(self):
        self._send("quit")
        if self.process:
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()


class XBoardEngine:
    def __init__(self, path: str):
        self.path = path
        self.process: Optional[subprocess.Popen] = None
        
    def start(self):
        self.process = subprocess.Popen(
            [self.path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._send("xboard")
        self._send("protover 2")
        time.sleep(0.5)
        self._send("new")
        
    def _send(self, cmd: str):
        if self.process and self.process.stdin:
            self.process.stdin.write(cmd + "\n")
            self.process.stdin.flush()
            
    def _read_until_move(self, timeout: float = 5.0) -> Optional[str]:
        if not self.process or not self.process.stdout:
            return None
        start = time.perf_counter()
        while True:
            if time.perf_counter() - start > timeout:
                return None
            try:
                line = self.process.stdout.readline().strip()
            except:
                return None
            if line.startswith("move "):
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1]
            if re.match(r'^[a-h][1-8][a-h][1-8][qrbn]?$', line):
                return line
        return None
    
    def new_game(self):
        self._send("new")
        
    def set_position(self, board: chess.Board = None):
        self._send("new")
        if board is None:
            self._send("force")
            return
        if board.turn == chess.BLACK:
            self._send("force")
            self._send("e2e4")
            self._send("d7d5")
            self._send("e4e5")
            self._send("force")
        else:
            self._send("force")
        moves = []
        for move in board.move_stack:
            moves.append(move.uci())
        for m in moves:
            self._send(m)
            
    def go(self, time_ms: int = 500) -> Optional[str]:
        self._send(f"st {time_ms / 1000.0}")
        self._send("go")
        return self._read_until_move(timeout=time_ms / 1000.0 + 2.0)
    
    def quit(self):
        self._send("quit")
        if self.process:
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()


class UCIEngine:
    def __init__(self, path: str):
        self.path = path
        self.process: Optional[subprocess.Popen] = None
        
    def start(self):
        self.process = subprocess.Popen(
            [self.path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._send("uci")
        self._wait_for("uciok")
        
    def _send(self, cmd: str):
        if self.process and self.process.stdin:
            self.process.stdin.write(cmd + "\n")
            self.process.stdin.flush()
            
    def _wait_for(self, target: str, timeout: float = 10.0) -> Optional[str]:
        if not self.process or not self.process.stdout:
            return None
        start = time.perf_counter()
        while True:
            if time.perf_counter() - start > timeout:
                return None
            line = self.process.stdout.readline().strip()
            if target in line:
                return line
            
    def _read_until_bestmove(self, timeout: float = 5.0) -> Optional[str]:
        if not self.process or not self.process.stdout:
            return None
        start = time.perf_counter()
        while True:
            if time.perf_counter() - start > timeout:
                return None
            line = self.process.stdout.readline().strip()
            if line.startswith("bestmove"):
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1]
        return None
    
    def new_game(self):
        self._send("ucinewgame")
        self._send("isready")
        self._wait_for("readyok")
        
    def set_position(self, moves: list[str] = None):
        if moves:
            self._send(f"position startpos moves {' '.join(moves)}")
        else:
            self._send("position startpos")
            
    def go(self, time_ms: int = 500) -> Optional[str]:
        self._send(f"go movetime {time_ms}")
        return self._read_until_bestmove(timeout=time_ms / 1000.0 + 2.0)
    
    def quit(self):
        self._send("quit")
        if self.process:
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()


def create_engine(opponent_key: str):
    if opponent_key not in OPPONENTS:
        raise ValueError(f"Unknown opponent: {opponent_key}")
    
    config = OPPONENTS[opponent_key]
    if not os.path.isfile(config["path"]):
        raise FileNotFoundError(f"Engine not found: {config['path']}")
    
    if config["proto"] == "xboard":
        return XBoardEngine(config["path"])
    else:
        return UCIEngine(config["path"])


def play_game(velvet: VelvetEngine, opponent, verbose: bool = False, time_per_move: float = 0.5) -> list[tuple[str, str]]:
    velvet.new_game()
    opponent.new_game()
    
    board = chess.Board()
    moves: list[str] = []
    positions: list[tuple[str, str]] = []
    
    velvet.set_position()
    opponent.set_position()
    
    current_turn = "velvet"
    
    while len(moves) < MAX_HALF_MOVES:
        if board.is_game_over():
            break
            
        if current_turn == "velvet":
            move_uci = velvet.go(int(time_per_move * 1000))
        else:
            move_uci = opponent.go(int(time_per_move * 1000))
        
        if not move_uci:
            if verbose:
                print(f"  No move from {current_turn}, game ended")
            break
            
        try:
            move = chess.Move.from_uci(move_uci)
            if move not in board.legal_moves:
                if verbose:
                    print(f"  Illegal move {move_uci} from {current_turn}")
                break
        except ValueError:
            if verbose:
                print(f"  Invalid move format: {move_uci}")
            break
        
        pos_key = get_position_key(board)
        positions.append((pos_key, move_uci))
        
        board.push(move)
        moves.append(move_uci)
        
        if verbose:
            print(f"  {len(moves)}. {current_turn}: {move_uci}")
        
        current_turn = "opponent" if current_turn == "velvet" else "velvet"
        
        if current_turn == "velvet":
            velvet.set_position(moves)
        else:
            if isinstance(opponent, XBoardEngine):
                opponent.set_position(board)
            else:
                opponent.set_position(moves)
    
    return positions


def generate_opening_book(opponents: list[str], rounds: int, output_path: str, verbose: bool = False, time_per_move: float = 0.5):
    velvet = VelvetEngine(VELVET_PATH)
    if not os.path.isfile(VELVET_PATH):
        print(f"Error: Velvet engine not found at {VELVET_PATH}")
        sys.exit(1)
    
    velvet.start()
    
    book = {
        "version": "1.0",
        "generated_at": datetime.now().strftime("%Y-%m-%d"),
        "time_per_move": time_per_move,
        "entries": {}
    }
    
    try:
        for opp_name in opponents:
            print(f"\n=== Playing against {opp_name} ===", flush=True)
            
            try:
                opponent = create_engine(opp_name)
                opponent.start()
            except Exception as e:
                print(f"  Error starting {opp_name}: {e}")
                continue
            
            try:
                for r in range(rounds):
                    print(f"\nRound {r + 1}/{rounds}", flush=True)
                    
                    if verbose:
                        print("  Playing as White:")
                    positions = play_game(velvet, opponent, verbose, time_per_move)
                    
                    for pos_key, move in positions:
                        if pos_key not in book["entries"]:
                            book["entries"][pos_key] = {
                                "moves": [],
                                "preferred": None,
                                "hellcopter_eval": {}
                            }
                        entry = book["entries"][pos_key]
                        if move not in entry["moves"]:
                            entry["moves"].append(move)
                    
                    print(f"  Collected {len(positions)} positions", flush=True)
                    
            finally:
                opponent.quit()
                
    finally:
        velvet.quit()
    
    print("\n=== Evaluating positions with Hellcopter ===", flush=True)
    total = len(book["entries"])
    for i, (pos_key, entry) in enumerate(book["entries"].items()):
        if verbose or (i + 1) % 10 == 0:
            print(f"  Evaluating {i + 1}/{total}: {pos_key[:30]}...")
        
        fen_parts = pos_key.split()
        fen = f"{fen_parts[0]} {fen_parts[1]} - - 0 1"
        board = chess.Board(fen)
        
        best_score = -999999
        best_move = None
        
        for move_uci in entry["moves"]:
            try:
                move = chess.Move.from_uci(move_uci)
                if move not in board.legal_moves:
                    continue
                board.push(move)
                score = -evaluate_with_hellcopter(board)
                board.pop()
                
                entry["hellcopter_eval"][move_uci] = score
                
                if score > best_score:
                    best_score = score
                    best_move = move_uci
            except Exception:
                continue
        
        if best_move:
            entry["preferred"] = best_move
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(book, f, indent=2, ensure_ascii=False)
    
    print(f"\n=== Opening book saved to {output_path} ===", flush=True)
    print(f"Total positions: {len(book['entries'])}", flush=True)
    
    return book


def main():
    parser = argparse.ArgumentParser(description="Opening book generator for Hellcopter")
    
    parser.add_argument("--generate", action="store_true",
                       help="Generate opening book")
    parser.add_argument("--opponents", type=str, default="tscp181,apollo,monarch",
                       help="Comma-separated list of opponents")
    parser.add_argument("--rounds", type=int, default=10,
                       help="Number of rounds per opponent")
    parser.add_argument("--output", type=str, default="opening_book.json",
                       help="Output JSON file path")
    parser.add_argument("--time", type=float, default=0.5,
                       help="Time per move in seconds (default: 0.5)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Verbose output")
    
    args = parser.parse_args()
    
    if args.generate:
        opponents = [o.strip().lower() for o in args.opponents.split(",")]
        
        for opp in opponents:
            if opp not in OPPONENTS:
                print(f"Error: Unknown opponent '{opp}'")
                print(f"Available opponents: {', '.join(OPPONENTS.keys())}")
                sys.exit(1)
        
        output_path = args.output
        if not os.path.isabs(output_path):
            output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_path)
        
        generate_opening_book(opponents, args.rounds, output_path, args.verbose, args.time)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
