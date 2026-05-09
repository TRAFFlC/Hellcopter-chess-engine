import chess
import time
from engine import ChessEngine


def score_single_move(board, move, depth=6):
    """Score a single move with fresh engine instance."""
    engine = ChessEngine()
    engine.time_limit = 60.0  # Very generous for single move
    engine.search_aborted = False
    engine.nodes_searched = 0
    engine.start_time = time.perf_counter()

    board.push(move)
    score = engine.negamax(board, depth - 1, -float('inf'), float('inf'), 0)
    board.pop()

    nodes = engine.nodes_searched
    aborted = engine.search_aborted

    if score is not None:
        return -score, nodes, aborted
    else:
        return None, nodes, aborted


def analyze_position(fen, depth=6):
    board = chess.Board(fen)
    print(f"\n{'='*60}")
    print(f"FEN: {fen}")
    print(f"Position:\n{board}")
    print(f"\nSide to move: {'White' if board.turn == chess.WHITE else 'Black'}")
    print(f"\nEngine analysis (depth {depth}):")
    print("-" * 60)

    legal_moves = list(board.legal_moves)
    print(f"Total legal moves: {len(legal_moves)}")

    scored = []
    for move in legal_moves:
        san = board.san(move)
        print(f"  Scoring {san}...", end=" ", flush=True)
        score, nodes, aborted = score_single_move(board, move, depth)
        if score is not None:
            print(f"score={score:6d}, nodes={nodes:6d}")
            scored.append((score, move, nodes))
        else:
            print(f"ABORTED (nodes={nodes})")
            scored.append((-999999, move, nodes))  # Penalize aborted searches

    scored.sort(key=lambda x: x[0], reverse=True)

    print(f"\nAll moves ranked by score:")
    print("-" * 60)
    for i, (score, move, nodes) in enumerate(scored, 1):
        marker = " <-- BEST" if i == 1 else ""
        print(f"  {i:2d}. {board.san(move):8s} = {score:6d} (nodes: {nodes:6d}){marker}")

    best_move = scored[0][1]
    best_score = scored[0][0]
    print(f"\nBest move: {best_move.uci()} ({board.san(best_move)}) = {best_score}")
    return best_move


if __name__ == "__main__":
    # Test 1: Black responds to 1.e4
    print("\n" + "="*60)
    print("TEST 1: Black to move after 1.e4")
    print("="*60)
    analyze_position("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")

    # Test 2: Complex middlegame position
    print("\n" + "="*60)
    print("TEST 2: Black to move after 1.e4 Nf6 2.e5 Nd5 3.d4 Nc6 4.Bb5 e6 5.Bxc6")
    print("="*60)
    analyze_position("r1bqkb1r/pppp1ppp/2B1pn2/4Np2/3P4/8/PPP2PPP/RNBQK2R b KQkq - 0 5")
