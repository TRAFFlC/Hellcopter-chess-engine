import time, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine_wrapper as ew

FENS = [
    ("startpos", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
    ("kiwipete", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq -"),
    ("endgame", "8/5p2/8/2k3P1/p3P3/2K5/1P6/8 b - - - - -"),
    ("tactical", "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPP2PPP/RNB1K2R w KQkq -"),
]

print("=== Hellcopter depth search (5s each, max_depth=0) ===")
print(f"{'pos':<14} {'depth':<7} {'nodes':<10} {'nps':<10} {'score':<7} {'time':<6}")
print("-"*60)
for label, fen in FENS:
    t0 = time.time()
    move, nodes = ew.search(fen, 5.0, 0)
    dt = time.time() - t0
    depth = ew.get_last_search_info(0)
    score = ew.get_last_search_info(2)
    nps = int(nodes / dt) if dt > 0 else 0
    print(f"{label:<14} {depth:<7} {nodes:<10,} {nps:<10,} {score/100:+.2f}  {dt:<6.2f}")
print("\nNote: Velvet bench (46 positions) total: 2.1s, 3.4M nodes, 1.63M NPS (avg)")
print("Velvet single-pos 5s depth estimated 15-20 from bench data.")
