"""Extract positions from PGN with side-to-move result labels."""
import os
import sys
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def extract_positions(pgn_path: str, min_ply: int = 8, max_ply: int = 80,
                      max_per_game: int = 35) -> list:
    import chess.pgn
    positions = []
    game_count = 0
    skipped_no_result = 0
    skipped_material = 0

    t0 = time.time()
    with open(pgn_path, encoding="utf-8", errors="replace") as f:
        while True:
            game = chess.pgn.read_game(f)
            if game is None:
                break

            game_count += 1
            if game_count % 5000 == 0:
                elapsed = time.time() - t0
                rate = game_count / elapsed
                print(f"  ...{game_count} games scanned ({len(positions)} positions, "
                      f"{rate:.0f} games/s)")

            result = game.headers.get("Result", "*")
            if result == "1-0":
                white_outcome = 1.0
            elif result == "0-1":
                white_outcome = 0.0
            elif result == "1/2-1/2":
                white_outcome = 0.5
            else:
                skipped_no_result += 1
                continue

            board = game.board()
            taken = 0
            for i, move in enumerate(game.mainline_moves()):
                ply = i + 1
                if ply < min_ply:
                    board.push(move)
                    continue
                if ply > max_ply:
                    break

                board.push(move)

                # Skip if too little material left
                total_material = sum(
                    1 for sq in chess.SQUARES
                    if (p := board.piece_at(sq)) and p.piece_type != chess.KING
                )
                if total_material < 2:
                    skipped_material += 1
                    continue

                # Store outcome from side-to-move perspective
                fen = board.fen()
                stm = fen.split(" ")[1]  # 'w' or 'b'
                stm_outcome = white_outcome if stm == 'w' else 1.0 - white_outcome

                positions.append((fen, stm_outcome))
                taken += 1
                if taken >= max_per_game:
                    break

    elapsed = time.time() - t0
    print(f"  Done: {game_count} games, {len(positions)} positions [{elapsed:.0f}s]")
    return positions, game_count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pgn", required=True, help="Input PGN")
    parser.add_argument("--output", required=True, help="Output JSON cache")
    parser.add_argument("--max-per-game", type=int, default=35)
    parser.add_argument("--min-ply", type=int, default=8)
    parser.add_argument("--max-ply", type=int, default=80)
    args = parser.parse_args()

    print(f"Extracting positions from {args.pgn}")
    print(f"  max_per_game={args.max_per_game}")
    print(f"  ply range: [{args.min_ply}, {args.max_ply}]")

    positions, game_count = extract_positions(
        args.pgn, args.min_ply, args.max_ply, args.max_per_game
    )

    data = {
        "source": args.pgn,
        "total_games": game_count,
        "total_positions": len(positions),
        "positions": [{"fen": p[0], "result": p[1]} for p in positions],
    }
    with open(args.output, "w") as f:
        json.dump(data, f)
    print(f"Saved {len(positions)} positions to {args.output}")


if __name__ == "__main__":
    main()
