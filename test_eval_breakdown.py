import chess
import time
from engine import ChessEngine, PIECE_VALUES, PST_PAWN_MG, PST_PAWN_EG, PST_KNIGHT, PST_BISHOP, PST_ROOK_MG, PST_ROOK_EG, PST_QUEEN, PST_KING_MG, PST_KING_EG, CENTER_SQUARES, EXTENDED_CENTER, _game_phase


def evaluate_breakdown(board):
    """拆解评估函数的每个组成部分。"""
    score = 0
    piece_at = board.piece_at
    eg = False  # Simplified for opening position
    phase = _game_phase(board)

    breakdown = {
        'material': 0,
        'pst_pawn': 0,
        'pst_knight': 0,
        'pst_bishop': 0,
        'pst_rook': 0,
        'pst_queen': 0,
        'pst_king': 0,
        'center_control': 0,
        'extended_center': 0,
        'pawn_structure': 0,
        'king_safety': 0,
        'total': 0
    }

    # Material + PST
    for color in (chess.WHITE, chess.BLACK):
        sign = 1 if color == chess.WHITE else -1
        for piece_type in range(1, 7):
            value = PIECE_VALUES[piece_type]
            pieces = board.pieces(piece_type, color)
            material_score = sign * value * len(pieces)
            breakdown['material'] += material_score
            score += material_score

            if piece_type == chess.KING:
                table = PST_KING_MG
            elif piece_type == chess.PAWN:
                table = PST_PAWN_MG
            elif piece_type == chess.ROOK:
                table = PST_ROOK_MG
            else:
                tables = {chess.KNIGHT: PST_KNIGHT, chess.BISHOP: PST_BISHOP, chess.QUEEN: PST_QUEEN}
                table = tables[piece_type]

            pst_key = {chess.PAWN: 'pst_pawn', chess.KNIGHT: 'pst_knight',
                      chess.BISHOP: 'pst_bishop', chess.ROOK: 'pst_rook',
                      chess.QUEEN: 'pst_queen', chess.KING: 'pst_king'}[piece_type]

            if color == chess.WHITE:
                for sq in pieces:
                    s = sign * table[sq]
                    breakdown[pst_key] += s
                    score += s
            else:
                for sq in pieces:
                    s = sign * table[chess.square_mirror(sq)]
                    breakdown[pst_key] += s
                    score += s

    # Center control
    for sq in CENTER_SQUARES:
        piece = piece_at(sq)
        if piece:
            s = 15 if piece.color == chess.WHITE else -15
            breakdown['center_control'] += s
            score += s

    # Extended center
    for sq in EXTENDED_CENTER:
        piece = piece_at(sq)
        if piece:
            s = 5 if piece.color == chess.WHITE else -5
            breakdown['extended_center'] += s
            score += s

    # King safety (simplified)
    # ... skip for now, just show the main components

    breakdown['total'] = score
    return breakdown


def compare_moves(fen, move1_san, move2_san):
    """比较两个走法在走完后的评估差异。"""
    board = chess.Board(fen)
    print(f"\n{'='*70}")
    print(f"FEN: {fen}")
    print(f"Position:\n{board}")
    print(f"\nComparing: {move1_san} vs {move2_san}")
    print("="*70)

    # Initial position breakdown
    print("\n--- Initial Position Breakdown ---")
    init_breakdown = evaluate_breakdown(board)
    for key, val in init_breakdown.items():
        print(f"  {key:20s}: {val:6d}")

    for move_san in [move1_san, move2_san]:
        move = board.parse_san(move_san)
        board.push(move)

        print(f"\n--- After {move_san} ---")
        breakdown = evaluate_breakdown(board)
        for key, val in breakdown.items():
            print(f"  {key:20s}: {val:6d}")

        # Show specific piece changes
        print(f"\n  Piece positions after {move_san}:")
        for sq in chess.SQUARES:
            piece = board.piece_at(sq)
            if piece:
                print(f"    {chess.square_name(sq)}: {piece.symbol()}")

        board.pop()


def analyze_move_sequence():
    """分析 1.e4 e5 和 1.e4 Nf6 的差异。"""
    print("\n" + "="*70)
    print("ANALYSIS 1: 1.e4 e5")
    print("="*70)
    compare_moves(
        "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "e5", "Nf6"
    )


if __name__ == "__main__":
    analyze_move_sequence()
