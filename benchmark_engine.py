import chess
import time
from engine import ChessEngine

POSITIONS = [
    ("start", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
    ("middlegame", "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"),
    ("tactical", "rnbqkb1r/ppp2ppp/4pn2/3p4/2PP4/2N5/PP2PPPP/R1BQKBNR w KQkq - 0 4"),
    ("endgame", "8/2k5/4p3/3pP3/2P5/2K5/8/8 w - - 0 1"),
]

TIME_LIMITS = [0.5, 1.0, 2.0]

def benchmark():
    print("=" * 70)
    print("Engine Performance Benchmark")
    print("=" * 70)

    for name, fen in POSITIONS:
        board = chess.Board(fen)
        print(f"\nPosition: {name} ({fen})")
        print("-" * 70)
        print(f"{'Time':>8} {'Depth':>6} {'Nodes':>10} {'NPS':>10} {'Best Move':>10}")
        print("-" * 70)

        for time_limit in TIME_LIMITS:
            engine = ChessEngine()
            engine.time_limit = time_limit

            start = time.perf_counter()
            best_move, nodes = engine.find_best_move(board, max_depth=10)
            elapsed = time.perf_counter() - start

            nps = int(nodes / elapsed) if elapsed > 0 else 0
            print(f"{time_limit:>8.1f}s {10:>6} {nodes:>10} {nps:>10} {str(best_move):>10}")

    print("\n" + "=" * 70)

if __name__ == "__main__":
    benchmark()
