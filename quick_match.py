import subprocess
import sys
import os
import time
import chess
import chess.pgn
import io

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HELLCOPTER_EXE = os.path.join(BASE_DIR, "dist", "Hellcopter.exe")
APOLLO_EXE = os.path.join(BASE_DIR, "test_engines", "Apollo 1663", "apollo.exe")
MONARCH_EXE = os.path.join(BASE_DIR, "test_engines", "Monarch 2005", "Monarch(v1.7)", "Monarch(v1.7).exe")

class UCIEngine:
    def __init__(self, path, name="Engine"):
        self.path = path
        self.name = name
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen(
            [self.path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=os.path.dirname(self.path) if os.path.dirname(self.path) else "."
        )
        self.send("uci")
        self.wait_for("uciok", timeout=10)
        self.send("isready")
        self.wait_for("readyok", timeout=10)

    def send(self, cmd):
        self.proc.stdin.write(cmd + "\n")
        self.proc.stdin.flush()

    def wait_for(self, token, timeout=30):
        start = time.time()
        while time.time() - start < timeout:
            line = self.proc.stdout.readline().strip()
            if token in line:
                return line
        return ""

    def go(self, wtime, btime, winc=0, binc=0, depth=None):
        if depth:
            cmd = f"go depth {depth}"
        else:
            cmd = f"go wtime {wtime} btime {btime} winc {winc} binc {binc}"
        self.send(cmd)
        bestmove = None
        info_line = ""
        while True:
            line = self.proc.stdout.readline().strip()
            if line.startswith("bestmove"):
                parts = line.split()
                bestmove = parts[1] if len(parts) > 1 else None
                break
            if line.startswith("info"):
                info_line = line
        return bestmove, info_line

    def set_option(self, name, value):
        self.send(f"setoption name {name} value {value}")

    def quit(self):
        try:
            self.send("quit")
            self.proc.wait(timeout=5)
        except:
            self.proc.kill()

def play_game_with_details(white_engine, black_engine, wtime_ms=60000, btime_ms=60000,
              winc_ms=500, binc_ms=500, max_moves=200):
    board = chess.Board()
    moves = []
    wtime = wtime_ms
    btime = btime_ms
    details = []

    for move_num in range(max_moves):
        if board.is_game_over():
            break

        engine = white_engine if board.turn == chess.WHITE else black_engine
        is_white = board.turn == chess.WHITE

        pos_cmd = "position startpos moves " + " ".join(moves) if moves else "position startpos"
        engine.send(pos_cmd)
        engine.send("isready")
        engine.wait_for("readyok", timeout=5)

        t_start = time.time()
        bestmove, info = engine.go(wtime=int(wtime), btime=int(btime), winc=winc_ms, binc=binc_ms)
        elapsed = time.time() - t_start
        t_ms = int(elapsed * 1000)

        score_cp = None
        depth = None
        if info:
            parts = info.split()
            for i, p in enumerate(parts):
                if p == "score" and i + 2 < len(parts) and parts[i+1] == "cp":
                    score_cp = int(parts[i+2])
                if p == "depth" and i + 1 < len(parts):
                    try:
                        depth = int(parts[i+1])
                    except:
                        pass

        if is_white:
            wtime = max(wtime - t_ms + winc_ms, 100)
        else:
            btime = max(btime - t_ms + binc_ms, 100)

        if not bestmove or len(bestmove) < 4:
            result = "1-0" if not is_white else "0-1"
            return result, moves, board, details

        try:
            move = chess.Move.from_uci(bestmove)
            if move not in board.legal_moves:
                promo_map = {"q": chess.QUEEN, "r": chess.ROOK, "b": chess.BISHOP, "n": chess.KNIGHT}
                found = False
                for p in promo_map:
                    try:
                        m = chess.Move(move.from_square, move.to_square, promotion=promo_map[p])
                        if m in board.legal_moves:
                            move = m
                            found = True
                            break
                    except:
                        pass
                if not found:
                    result = "1-0" if not is_white else "0-1"
                    return result, moves, board, details
            board.push(move)
            moves.append(bestmove)
        except:
            result = "1-0" if not is_white else "0-1"
            return result, moves, board, details

        details.append({
            "move_num": move_num + 1,
            "uci": bestmove,
            "score": score_cp,
            "depth": depth,
            "time_ms": t_ms,
            "is_hellcopter": (is_white and engine == white_engine) or (not is_white and engine == black_engine),
        })

        if wtime <= 0:
            return "0-1", moves, board, details
        if btime <= 0:
            return "1-0", moves, board, details

    if board.is_checkmate():
        return ("0-1" if board.turn == chess.WHITE else "1-0"), moves, board, details
    if board.is_stalemate() or board.is_insufficient_material():
        return "1/2-1/2", moves, board, details
    return "1/2-1/2", moves, board, details

def analyze_endgame(details, moves):
    hellcopter_details = [d for d in details if d["is_hellcopter"]]
    if not hellcopter_details:
        return

    late_moves = [d for d in hellcopter_details if d["move_num"] > 60]
    if not late_moves:
        return

    print("\n  === Hellcopter Late-Game Analysis (move > 60) ===")
    for d in late_moves[-10:]:
        score_str = f"{d['score']}cp" if d['score'] is not None else "?"
        print(f"    Move {d['move_num']}: {d['uci']} score={score_str} depth={d['depth']} time={d['time_ms']}ms")

    endgame_moves = [d for d in hellcopter_details if d["move_num"] > 100]
    if endgame_moves:
        scores = [d['score'] for d in endgame_moves if d['score'] is not None]
        if scores:
            avg_score = sum(scores) / len(scores)
            max_score = max(scores)
            min_score = min(scores)
            print(f"  Endgame (move>100) stats: avg={avg_score:.0f}cp max={max_score}cp min={min_score}cp")

            positive_count = sum(1 for s in scores if s > 50)
            if positive_count > len(scores) * 0.5 and avg_score > 50:
                print(f"  WARNING: Hellcopter had advantage (+{avg_score:.0f}cp avg) but couldn't convert!")
                print(f"  This suggests endgame evaluation/conversion weakness")

def main():
    args = sys.argv[1:]
    opponent = args[0] if args else "apollo"
    num_games = int(args[1]) if len(args) > 1 else 4

    opponent_map = {
        "apollo": APOLLO_EXE,
        "monarch": MONARCH_EXE,
        "self": HELLCOPTER_EXE,
    }

    if opponent not in opponent_map:
        print(f"Unknown opponent: {opponent}. Available: {list(opponent_map.keys())}")
        return

    opp_path = opponent_map[opponent]

    wtime_ms = 60000
    btime_ms = 60000
    inc_ms = 500

    results = {"win": 0, "loss": 0, "draw": 0}

    for game_i in range(num_games):
        white_is_hellcopter = (game_i % 2 == 0)

        hellcopter = UCIEngine(HELLCOPTER_EXE, "Hellcopter")
        opp_engine = UCIEngine(opp_path, opponent.capitalize())

        try:
            hellcopter.start()
            opp_engine.start()
        except Exception as e:
            print(f"Failed to start engines: {e}")
            hellcopter.quit()
            opp_engine.quit()
            continue

        if white_is_hellcopter:
            result, moves, board, details = play_game_with_details(
                hellcopter, opp_engine, wtime_ms, btime_ms, inc_ms, inc_ms)
        else:
            result, moves, board, details = play_game_with_details(
                opp_engine, hellcopter, wtime_ms, btime_ms, inc_ms, inc_ms)

        hellcopter.quit()
        opp_engine.quit()

        if white_is_hellcopter:
            if result == "1-0": results["win"] += 1
            elif result == "0-1": results["loss"] += 1
            else: results["draw"] += 1
        else:
            if result == "0-1": results["win"] += 1
            elif result == "1-0": results["loss"] += 1
            else: results["draw"] += 1

        color_str = "W" if white_is_hellcopter else "B"
        print(f"\nGame {game_i+1}/{num_games} [Hellcopter={color_str}]: {result} ({len(moves)} moves)")
        print(f"  Running total: W:{results['win']} D:{results['draw']} L:{results['loss']}")

        pgn_file = os.path.join(BASE_DIR, f"game_{game_i+1}_{opponent}.txt")
        with open(pgn_file, 'w') as f:
            f.write(f"Result: {result}\n")
            f.write(f"Hellcopter: {color_str}\n")
            f.write(f"Moves: {' '.join(moves)}\n")

        analyze_endgame(details, moves)

        if result == "0-1" and white_is_hellcopter or result == "1-0" and not white_is_hellcopter:
            print(f"\n  === LOSS DETAILS ===")
            print(f"  Last 20 moves: {' '.join(moves[-20:])}")

    print(f"\n{'='*60}")
    print(f"FINAL vs {opponent.capitalize()} ({num_games} games, {wtime_ms/1000}s+{inc_ms/1000}s)")
    print(f"Wins: {results['win']}  Draws: {results['draw']}  Losses: {results['loss']}")
    total = results['win'] + results['draw'] + results['loss']
    if total > 0:
        score_pct = (results['win'] + results['draw'] * 0.5) / total * 100
        print(f"Score: {score_pct:.1f}%")

if __name__ == "__main__":
    main()
