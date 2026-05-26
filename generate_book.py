import struct
import os
import sys

try:
    import chess
except ImportError:
    print("需要安装 python-chess: pip install chess")
    sys.exit(1)

POLYGLOT_RANDOMS = None

def init_polyglot():
    global POLYGLOT_RANDOMS
    if POLYGLOT_RANDOMS is not None:
        return

    POLYGLOT_RANDOMS = []
    rng_state = 0xD9348E5E5A5A5A5A

    def next_random():
        nonlocal rng_state
        rng_state ^= (rng_state >> 12) & 0xFFFFFFFFFFFFFFFF
        rng_state ^= (rng_state << 25) & 0xFFFFFFFFFFFFFFFF
        rng_state ^= (rng_state >> 27) & 0xFFFFFFFFFFFFFFFF
        return (rng_state * 0x2545F4914F6CDD1D) & 0xFFFFFFFFFFFFFFFF

    for _ in range(1851):
        POLYGLOT_RANDOMS.append(next_random())

def polyglot_hash(board):
    init_polyglot()
    h = 0

    piece_map = {
        chess.PAWN: 0, chess.KNIGHT: 1, chess.BISHOP: 2,
        chess.ROOK: 3, chess.QUEEN: 4, chess.KING: 5
    }

    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece:
            piece_idx = piece_map[piece.piece_type]
            if piece.color == chess.BLACK:
                piece_idx += 6
            idx = 64 * piece_idx + square
            h ^= POLYGLOT_RANDOMS[idx]

    castling = board.castling_rights
    castling_idx = 0
    if castling & chess.BB_H1:
        castling_idx |= 1
    if castling & chess.BB_A1:
        castling_idx |= 2
    if castling & chess.BB_H8:
        castling_idx |= 4
    if castling & chess.BB_A8:
        castling_idx |= 8
    if castling_idx:
        h ^= POLYGLOT_RANDOMS[768 + castling_idx - 1]

    if board.ep_square is not None:
        ep_file = chess.square_file(board.ep_square)
        h ^= POLYGLOT_RANDOMS[772 + ep_file]

    if board.turn == chess.BLACK:
        h ^= POLYGLOT_RANDOMS[780]

    return h

def encode_move(move):
    from_sq = move.from_square
    to_sq = move.to_square

    promo = 0
    if move.promotion:
        promo_map = {chess.KNIGHT: 1, chess.BISHOP: 2, chess.ROOK: 3, chess.QUEEN: 4}
        promo = promo_map.get(move.promotion, 0)

    return from_sq | (to_sq << 6) | (promo << 12)

OPENINGS = [
    "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 b7b5 a4b3 d7d6 c2c3 f8g7 c1g5 e8g8 g5f6 g7f6 d2d3 c6e5 b3e5 d6e5 f3e5 f6e5 d1d2 c7c6 a1d1 f8d8 f2f3 d8d7 d3f1 d7e7 f1e2 e5f6 e2f3 a8d8 d2e3 f6e5 e3e2 e5f6 e2d2 d8d7 d1e1 e7d7 e1d1 d7e7 d1e1 e7d7 e1d1",
    "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 b7b5 a4b3 d7d6 c2c3 f8g7 c1f4 e8g8 b1d2 c6a5 b3a4 a5c4 d2c4 b5c4 a4b5 a6b5 d1d3 c8b7 f4g3 d6d5 e4d5 f6d5 c4c3 b5c4 d3c4 d5b6 c4d3 b6d5 d3d2 d5f6 b2b3 c7c5 a1c1 a8c8 c1c2 f8d8 f3e5 g7e5 g3e5 d8d2 e5d4",
    "e2e4 e7e5 g1f3 b8c6 f1c4 f8c5 c2c3 g8f6 d2d4 e5d4 c3d4 c5b4 b1d2 d7d5 e4d5 f6d5 d4d5 d8d5 c4b5 c6a5 b5d7 c7c6 d7c6 b8c6 d2b3 d5d6 a2a3 b4e7 c1e3 e7f6 e1g1 e8g8 a1c1 a8e8 c1c6 f6g5 e3g5 d6g5 f3e5 g5e5 c6c8 e8c8 b3c5 e5c5 a3a4 c5c4",
    "e2e4 e7e5 g1f3 b8c6 f1c4 f8c5 d2d3 g8f6 c1g5 d7d6 b1c3 h7h6 g5h4 c6a5 c4b5 c7c6 b5a4 g7g5 h4g3 a5c4 d3d4 c4b2 d1d2 b2a4 d2a5 b7b5 a5c3 c5d6 c3b2 d6b4 a1d1 e5d4 f3d4 a8e8 e1g1 e8e5 d4f5 e5e2 b2e2 f6d5 e2e7 d8f6 e7e3 b4d6 f5d6 f6d6 e3b6 d5f4 b6c7 d6d2 d1d2 f4d2",
    "e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3 a7a6 c1g5 e7e6 f2f4 b8d7 g5f6 d8f6 d4e2 f6g6 d1d2 f8e7 f1e2 e8g8 e1c1 e7f6 c3d5 a6a5 a2a3 b7b6 c1b1 c8b7 e2f3 e6e5 f4e5 d6e5 f3e4 f6e7 d5b6 c7b6 d2e3 g6e6 e4g5 e6g6 g5e6 f7e6 e3g3 g8h8 b1a1 e5e4 a1b1 f8c8 b1c1 c8c4 c1b1 c4c2 b1a1 c2a2 a1b1 a2c2 b1a1 c2c5 a1b1 c5a5 b1c1",
    "d2d4 g8f6 c2c4 e7e6 g1f3 d7d5 b1c3 f8e7 c1g5 d5c4 a2a4 c7c5 d4c5 e7c5 e4e5 f6e4 g5e7 d8d1 e1d1 c5e7 c3e4 e7e6 e4g5 e6g8 f3g5 e8g8 f1c4 b8d7 g5f3 d7c5 c4e2 a7a6 a4a5 h7h6 f3e5 g8h7 e2f3 c5e6 f3e2 e6c5 e2c4 c5e6 c4e2 e6c5 e2c4",
    "e2e4 e7e6 d2d4 d7d5 b1d2 c7c5 g1f3 c5d4 f3d4 b8c6 d4c6 d8c6 c1d2 f8d6 e4e5 d6c7 f1d3 c8d7 e1g1 e8g8 d2c3 a8c8 c3b4 c7b6 d1g4 g8h8 g4h4 h7h6 h4f4 f7f6 e5f6 g7f6 f4b4 b6c7 b4c4 c6c4 d3c4 d7c6 c4d3 c6e8 f1e2 f8f6 e2f3 f6f8 f3h5 f8f6 h5f3 f6f8 f3h5",
    "e2e4 c7c6 d2d4 d7d5 b1c3 d5e4 c3e4 b8d7 e4f3 g8f6 c1f4 d7f6 d1c1 c8f5 c1b1 e7e6 f1d3 f5d3 b1d3 d8b6 b2b3 e6e5 d4e5 f6e5 f4e5 b6e5 f3e5 d3e5 d3e5 e5e5",
    "d2d4 d7d5 c2c4 e7e6 b1c3 g8f6 c1g5 d5c4 g1f3 c7c5 d4c5 e8g7 e4e5 f6d5 g5e7 c4c3 b2c3 d5c3 d1a4 c3a2 e1c1 a2b4 a4b4 f8c5 b4c3 c5e7 c1b1 b7b6 b1a1 e7c5 c3c5 b6c5 a1a7 c8b7 a7a8 e6e5 f3e5 b7e4 e5c6 e4b7 c6a5 b7f3 a5c6 f3c6 a8c8 c6a4 c8c5 a4b3 c5c1 b3d2 c1c2 d2f3 c2c4 f3d2",
    "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 b7b5 a4b3 f8c5 c2c3 d7d6 b1d2 a6a5 a2a4 b5a4 b3a4 c8b7 d2c4 e8g7 c4b6 d8d7 b6c8 a8b8 c1e3 c5b6 a1a4 b6e3 f2e3 b8b2 d1c1 b2e2 c1c7 d7c8 c7c8 f6e8 c8c6 e2e3 c6a6 e3b3 a6a8 b3b2 a8c8 a4a7 c8c7 a7c7 g7f8 c7c5 f8e7 c5c7 e7f8 c7c5",
    "e2e4 c7c5 g1f3 e7e6 d2d4 c5d4 f3d4 g8f6 b1c3 b8c6 c1g5 d7d6 d1d2 h7h6 g5f4 e8g8 e1c1 a7a6 f1d3 d8c7 a2a3 b7b5 c3a4 b5a4 d3a4 f8d7 c1b1 c6d4 f4d6 d4f3 d2f2 f3d4 f2d2 d7c6 a4c6 c7c6 d2d4 a8b8 d4d2 c6c5 d2d3 c5c4 d3d2 c4c3 b2c3 b8b1 c3b1 d4f3 d2d3 f3d4 d3d2 d4f3 d2d3",
    "e2e4 e7e5 g1f3 b8c6 f1c4 f8c5 d2d3 g8f6 c1g5 d7d6 b1c3 h7h6 g5h4 c6a5 c4b5 c7c6 b5a4 g7g5 h4g3 a5c4 d3d4 c4b2 d1d2 b2a4 d2a5 b7b5 a5c3 c5d6 c3b2 d6b4 a1d1 e5d4 f3d4 a8e8 e1g1 e8e5 d4f5 e5e2 b2e2 f6d5 e2e7 d8f6 e7e3 b4d6 f5d6 f6d6 e3b6 d5f4 b6c7 d6d2 d1d2 f4d2",
    "d2d4 g8f6 c2c4 g7g6 g1f3 f8g7 g2g3 d7d6 f1g2 e8g8 b1c3 c7c5 d4d5 b8a6 e1g1 a6c7 c1g5 h7h6 g5e3 g6g5 b2b4 c5b4 a1b1 b4b3 c3b5 b3a2 b1a1 a2b3 b5d6 b7b6 d6c8 c7d5 c4d5 d8c8 d1b3 c8b7 b3b7 a8b8 g3g4 g5g4 e3g5 h6g5 f3g5 b8b7 g5e6 b7b4 e6c7 b4e4 c7e6 e4e2 e6g5 e2g2 g1g2",
    "e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3 a7a6 c1g5 e7e6 f2f4 b8d7 g5f6 d8f6 d4e2 f6g6 d1d2 f8e7 f1e2 e8g8 e1c1 e7f6 c3d5 a6a5 a2a3 b7b6 c1b1 c8b7 e2f3 e6e5 f4e5 d6e5 f3e4 f6e7 d5b6 c7b6 d2e3 g6e6 e4g5 e6g6 g5e6 f7e6 e3g3 g8h8 b1a1 e5e4 a1b1 f8c8 b1c1 c8c4 c1b1 c4c2 b1a1 c2a2 a1b1 a2c2 b1a1 c2c5 a1b1 c5a5 b1c1",
    "e2e4 e7e6 d2d4 d7d5 e4e5 f8d6 b1d2 c7c5 c1g4 d6e7 g4e6 f7e6 g1f3 b8d7 d2b3 c5c4 b3c1 g8h6 f1e2 e8g8 e1g1 d7f8 d1c2 f8g6 c1b2 d5d4 b2a3 c8d7 f3e5 d7e8 a3d6 d8d6 c2d2 d6e5 d2d4 e5d4 e2f3 g6e5 f3e2 e5g6 e2d1 g6e5 d1c2 e5c4 c2d3 c4e5 d3c2 e5c4 c2d3",
    "d2d4 g8f6 c2c4 e7e6 g1f3 d7d5 b1c3 f8e7 c1g5 d5c4 g1f3 c7c5 d4c5 e8g7 e4e5 f6d5 g5e7 c4c3 b2c3 d5c3 d1a4 c3a2 e1c1 a2b4 a4b4 f8c5 b4c3 c5e7 c1b1 b7b6 b1a1 e7c5 c3c5 b6c5 a1a7 c8b7 a7a8 e6e5 f3e5 b7e4 e5c6 e4b7 c6a5 b7f3 a5c6 f3c6 a8c8 c6a4 c8c5 a4b3 c5c1 b3d2 c1c2 d2f3 c2c4 f3d2",
    "e2e4 e7e5 g1f3 b8c6 f1c4 f8c5 c2c3 g8f6 d2d4 e5d4 c3d4 c5b4 b1d2 d7d5 e4d5 f6d5 d4d5 d8d5 c4b5 c6a5 b5d7 c7c6 d7c6 b8c6 d2b3 d5d6 a2a3 b4e7 c1e3 e7f6 e1g1 e8g8 a1c1 a8e8 c1c6 f6g5 e3g5 d6g5 f3e5 g5e5 c6c8 e8c8 b3c5 e5c5 a3a4 c5c4",
    "d2d4 d7d5 c2c4 d5c4 g1f3 g8f6 b1c3 e7e6 e4e4 b8d7 f1c4 c7c6 e1g1 f8e7 c4e2 d7b6 e2b5 a7a5 b5e2 c8d7 e4e5 f6e4 c3e4 d8c7 f1e1 a8c8 c1f4 c6c5 d4c5 e7c5 e4c3 c5f8 f4e5 b6d7 e5d4 c7b6 b2b3 b6a6 a2a3 a6b6 c3e4 d7e5 e4c5 b6c7 c5e6 f7e6 d4e5 c7e7 e6e7 e7e7",
    "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 b7b5 a4b3 d7d6 c2c3 f8g7 d2d3 c8b7 b1d2 e8g8 a2a4 b5a4 b3a4 a8b8 a4a5 b8b4 d1e2 b4e4 e2e4 e4e4 d2f3 e4e4 f3g5 e4e4 g5e6 f8e8 e6g7 e8e4 d3d4 e4g4 g7e6 g4g2 g1g2 g7g2 e6c5 g2g5 c5e4 g5g4 e4c5 g4g5 c5e6 g5g4",
    "e2e4 c7c5 g1f3 b8c6 d2d4 c5d4 f3d4 g8f6 b1c3 d7d5 e4d5 f6d5 d4c6 b7c6 c1g5 d8b6 g5f6 b6f6 d1d2 e7e6 a1d1 f8d6 f1e2 c8d7 e1c1 e8g8 c3b5 c6b5 d2b4 d7c6 b4b5 c6f3 g2f3 a8c8 e2f3 d6f4 f3f4 f6f4 c1c2 f4f5 d1d7 f5f7 f2f3 g8f8 d7c7 c8c7 b5c7 f8e7 c7b6 e7d6 b6a5 d6c5 a5a6 f7b7 a6a7 b7b4 a7a8 b4e4 a8c8 e4e5 c8c5 e5e2 c5c4 e2f3 c4c3 f3e4 c3c2 e4d5 c2c1 d5e4 c1b2 e4d5 b2a3 d5c4 a3b2 c4d4 b2c1 d4d5 c1b2 d5d4 b2c1 d4c4 c1b2 c4b4 b2c1 b4a4 c1b2 a4b4 b2c1 b4a4",
]

def generate_book():
    entries = []
    seen = set()

    for opening_str in OPENINGS:
        board = chess.Board()
        moves = opening_str.split()

        for move_uci in moves:
            try:
                move = chess.Move.from_uci(move_uci)
                if move not in board.legal_moves:
                    break

                h = polyglot_hash(board)
                encoded = encode_move(move)

                key = (h, encoded)
                if key not in seen:
                    entries.append((h, encoded, 1, 0))
                    seen.add(key)

                board.push(move)

                if board.fullmove_number > 12:
                    break
            except:
                break

    entries.sort(key=lambda x: x[0])

    return entries

def write_polyglot_book(entries, filename):
    with open(filename, 'wb') as f:
        for h, move, weight, learn in entries:
            f.write(struct.pack('>QHHI', h, move, weight, learn))

def main():
    print("生成 Polyglot 开局库...")
    print(f"包含 {len(OPENINGS)} 条主线变化")

    entries = generate_book()

    print(f"共 {len(entries)} 个开局位置")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    dist_dir = os.path.join(script_dir, "dist")
    os.makedirs(dist_dir, exist_ok=True)

    book_path = os.path.join(dist_dir, "book.bin")
    write_polyglot_book(entries, book_path)

    size = os.path.getsize(book_path)
    print(f"写入: {book_path}")
    print(f"文件大小: {size:,} 字节 ({size/1024:.1f} KB)")

if __name__ == "__main__":
    main()
