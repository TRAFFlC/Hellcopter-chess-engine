import chess
import logging
import random
import time

import engine_wrapper

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 300,
    chess.BISHOP: 320,
    chess.ROOK: 480,
    chess.QUEEN: 900,
    chess.KING: 20000
}

# Piece-Square Tables (from White's perspective, a1=0, h8=63)
# Pawn: MG = middlegame, EG = endgame
PST_PAWN_MG = [
    0,   0,   0,   0,   0,   0,   0,   0,
    50,  50,  50,  50,  50,  50,  50,  50,
    10,  20,  25,  30,  30,  25,  20,  10,
    5,  10,  15,  25,  25,  15,  10,   5,
    0,   5,  10,  20,  20,  10,   5,   0,
    0,  -5, -10,   5,   5, -10,  -5,   0,
    0,   5,  10, -20, -20,  10,   5,   0,
    0,   0,   0,   0,   0,   0,   0,   0,
]

PST_PAWN_EG = [
    0,   0,   0,   0,   0,   0,   0,   0,
    100, 100, 100, 100, 100, 100, 100, 100,
    60,  60,  60,  60,  60,  60,  60,  60,
    40,  40,  40,  40,  40,  40,  40,  40,
    25,  25,  25,  25,  25,  25,  25,  25,
    10,  10,  10,  10,  10,  10,  10,  10,
    0,   0,   0,   0,   0,   0,   0,   0,
    0,   0,   0,   0,   0,   0,   0,   0,
]

PST_KNIGHT_MG = [
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20,   0,   0,   0,   0, -20, -40,
    -30,   0,  10,  15,  15,  10,   0, -30,
    -30,   5,  15,  20,  20,  15,   5, -30,
    -30,   0,  15,  20,  20,  15,   0, -30,
    -30,   5,  10,  15,  15,  10,   5, -30,
    -40, -20,   0,   5,   5,   0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50,
]

PST_KNIGHT_EG = [
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20,   0,   5,   5,   0, -20, -40,
    -30,   5,  15,  20,  20,  15,   5, -30,
    -30,  10,  20,  25,  25,  20,  10, -30,
    -30,  10,  20,  25,  25,  20,  10, -30,
    -30,   5,  15,  20,  20,  15,   5, -30,
    -40, -20,   0,   5,   5,   0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50,
]

PST_BISHOP_MG = [
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -10,   0,  10,  10,  10,  10,   0, -10,
    -10,   5,   5,  10,  10,   5,   5, -10,
    -10,   0,   5,  10,  10,   5,   0, -10,
    -10,  10,  10,  10,  10,  10,  10, -10,
    -10,   5,   0,   0,   0,   0,   5, -10,
    -20, -10, -10, -10, -10, -10, -10, -20,
]

PST_BISHOP_EG = [
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -10,   0,  10,  15,  15,  10,   0, -10,
    -10,  10,  15,  20,  20,  15,  10, -10,
    -10,  10,  15,  20,  20,  15,  10, -10,
    -10,   0,  10,  15,  15,  10,   0, -10,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -20, -10, -10, -10, -10, -10, -10, -20,
]

PST_ROOK_MG = [
    0,   0,   0,   5,   5,   0,   0,   0,
    5,  10,  10,  10,  10,  10,  10,   5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    0,   0,   0,   5,   5,   0,   0,   0,
]

PST_ROOK_EG = [
    10,  10,  10,  10,  10,  10,  10,  10,
    10,  10,  10,  10,  10,  10,  10,  10,
    5,   5,   5,   5,   5,   5,   5,   5,
    0,   0,   0,   0,   0,   0,   0,   0,
    -5,  -5,  -5,  -5,  -5,  -5,  -5,  -5,
    -5,  -5,  -5,  -5,  -5,  -5,  -5,  -5,
    -5,  -5,  -5,  -5,  -5,  -5,  -5,  -5,
    0,   0,   0,   0,   0,   0,   0,   0,
]

PST_QUEEN_MG = [
    -20, -10, -10,  -5,  -5, -10, -10, -20,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -10,   0,   5,   5,   5,   5,   0, -10,
    -5,   0,   5,   5,   5,   5,   0,  -5,
    0,   0,   5,   5,   5,   5,   0,  -5,
    -10,   5,   5,   5,   5,   5,   0, -10,
    -10,   0,   5,   0,   0,   0,   0, -10,
    -20, -10, -10,  -5,  -5, -10, -10, -20,
]

PST_QUEEN_EG = [
    -20, -10, -10,  -5,  -5, -10, -10, -20,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -10,   0,   5,  10,  10,   5,   0, -10,
    -5,   0,  10,  15,  15,  10,   0,  -5,
    0,   0,  10,  15,  15,  10,   0,  -5,
    -10,   5,   5,  10,  10,   5,   0, -10,
    -10,   0,   5,   5,   5,   5,   0, -10,
    -20, -10, -10,  -5,  -5, -10, -10, -20,
]

PST_KING_MG = [
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -20, -30, -30, -40, -40, -30, -30, -20,
    -10, -20, -20, -20, -20, -20, -20, -10,
    20,  20,   0,   0,   0,   0,  20,  20,
    20,  30,  10,   0,   0,  10,  30,  20,
]

PST_KING_EG = [
    -50, -40, -30, -20, -20, -30, -40, -50,
    -30, -20, -10,   0,   0, -10, -20, -30,
    -30, -10,  20,  30,  30,  20, -10, -30,
    -30, -10,  30,  40,  40,  30, -10, -30,
    -30, -10,  30,  40,  40,  30, -10, -30,
    -30, -10,  20,  30,  30,  20, -10, -30,
    -30, -30,   0,   0,   0,   0, -30, -30,
    -50, -30, -30, -30, -30, -30, -30, -50,
]

CENTER_SQUARES = [chess.D4, chess.E4, chess.D5, chess.E5]
EXTENDED_CENTER = [chess.C3, chess.D3, chess.E3, chess.F3,
                   chess.C4, chess.F4,
                   chess.C5, chess.F5,
                   chess.C6, chess.D6, chess.E6, chess.F6]


# Precompute file and rank masks for bitboard operations
_FILE_MASKS = [0] * 8
_RANK_MASKS = [0] * 8
for f in range(8):
    for r in range(8):
        sq = chess.square(f, r)
        _FILE_MASKS[f] |= 1 << sq
        _RANK_MASKS[r] |= 1 << sq


def _popcount(bb):
    return bin(bb).count('1')


# ============================================================================
# ATTACK MASKS - Precomputed bitboards for fast attack detection
# ============================================================================

# Knight attack masks: KNIGHT_ATTACKS[sq] = bitboard of squares a knight on sq attacks
KNIGHT_ATTACKS = [0] * 64
for sq in range(64):
    mask = 0
    file = chess.square_file(sq)
    rank = chess.square_rank(sq)
    for df, dr in ((-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)):
        nf, nr = file + df, rank + dr
        if 0 <= nf <= 7 and 0 <= nr <= 7:
            mask |= 1 << chess.square(nf, nr)
    KNIGHT_ATTACKS[sq] = mask

# King attack masks: KING_ATTACKS[sq] = bitboard of squares a king on sq attacks
KING_ATTACKS = [0] * 64
for sq in range(64):
    mask = 0
    file = chess.square_file(sq)
    rank = chess.square_rank(sq)
    for df, dr in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
        nf, nr = file + df, rank + dr
        if 0 <= nf <= 7 and 0 <= nr <= 7:
            mask |= 1 << chess.square(nf, nr)
    KING_ATTACKS[sq] = mask

# KING_SURROUNDINGS[sq] = list of up to 8 surrounding squares (no bitboard, just square indices)
KING_SURROUNDINGS = [[] for _ in range(64)]
for sq in range(64):
    file = chess.square_file(sq)
    rank = chess.square_rank(sq)
    for df, dr in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
        nf, nr = file + df, rank + dr
        if 0 <= nf <= 7 and 0 <= nr <= 7:
            KING_SURROUNDINGS[sq].append(chess.square(nf, nr))

# Pawn attack masks: PAWN_ATTACKS[color][sq] = bitboard of squares a pawn of color on sq attacks
PAWN_ATTACKS = [[0] * 64, [0] * 64]
for sq in range(64):
    file = chess.square_file(sq)
    rank = chess.square_rank(sq)
    # White pawns attack upward (increasing rank)
    if rank < 7:
        if file > 0:
            PAWN_ATTACKS[chess.WHITE][sq] |= 1 << chess.square(file - 1, rank + 1)
        if file < 7:
            PAWN_ATTACKS[chess.WHITE][sq] |= 1 << chess.square(file + 1, rank + 1)
    # Black pawns attack downward (decreasing rank)
    if rank > 0:
        if file > 0:
            PAWN_ATTACKS[chess.BLACK][sq] |= 1 << chess.square(file - 1, rank - 1)
        if file < 7:
            PAWN_ATTACKS[chess.BLACK][sq] |= 1 << chess.square(file + 1, rank - 1)


# ============================================================================
# PAWN SHIELD HELPERS - Fast precomputed masks for common king positions
# ============================================================================

# Precompute pawn shield masks for common castled king positions
# Each mask is a bitboard of the shield squares; we count friendly pawns on those squares
_PAWN_SHIELD_MASK_KINGSIDE_WHITE = 0
for f in (5, 6, 7):
    for r in (1, 2):
        _PAWN_SHIELD_MASK_KINGSIDE_WHITE |= 1 << chess.square(f, r)

_PAWN_SHIELD_MASK_QUEENSIDE_WHITE = 0
for f in (0, 1, 2):
    for r in (1, 2):
        _PAWN_SHIELD_MASK_QUEENSIDE_WHITE |= 1 << chess.square(f, r)

_PAWN_SHIELD_MASK_KINGSIDE_BLACK = 0
for f in (5, 6, 7):
    for r in (6, 5):
        _PAWN_SHIELD_MASK_KINGSIDE_BLACK |= 1 << chess.square(f, r)

_PAWN_SHIELD_MASK_QUEENSIDE_BLACK = 0
for f in (0, 1, 2):
    for r in (6, 5):
        _PAWN_SHIELD_MASK_QUEENSIDE_BLACK |= 1 << chess.square(f, r)


def _pawn_shield_kingside_white(board):
    pawns = board.pieces_mask(chess.PAWN, chess.WHITE)
    count = _popcount(pawns & _PAWN_SHIELD_MASK_KINGSIDE_WHITE)
    return 20 if count >= 2 else 0


def _pawn_shield_queenside_white(board):
    pawns = board.pieces_mask(chess.PAWN, chess.WHITE)
    count = _popcount(pawns & _PAWN_SHIELD_MASK_QUEENSIDE_WHITE)
    return 20 if count >= 2 else 0


def _pawn_shield_kingside_black(board):
    pawns = board.pieces_mask(chess.PAWN, chess.BLACK)
    count = _popcount(pawns & _PAWN_SHIELD_MASK_KINGSIDE_BLACK)
    return 20 if count >= 2 else 0


def _pawn_shield_queenside_black(board):
    pawns = board.pieces_mask(chess.PAWN, chess.BLACK)
    count = _popcount(pawns & _PAWN_SHIELD_MASK_QUEENSIDE_BLACK)
    return 20 if count >= 2 else 0


def _pawn_shield_generic(board, color, king_square):
    """For non-standard king positions: count friendly pawns on ranks 2/3 (white)
    or 6/5 (black) within 1 file of the king."""
    kf = chess.square_file(king_square)
    if color == chess.WHITE:
        target_ranks = (1, 2)
        pawns = board.pieces_mask(chess.PAWN, chess.WHITE)
    else:
        target_ranks = (6, 5)
        pawns = board.pieces_mask(chess.PAWN, chess.BLACK)
    mask = 0
    for f in (kf - 1, kf, kf + 1):
        if 0 <= f <= 7:
            for r in target_ranks:
                mask |= 1 << chess.square(f, r)
    count = _popcount(pawns & mask)
    return 20 if count >= 2 else 0


def is_endgame(board):
    white_queens = _popcount(board.pieces_mask(chess.QUEEN, chess.WHITE))
    black_queens = _popcount(board.pieces_mask(chess.QUEEN, chess.BLACK))
    if white_queens == 0 and black_queens == 0:
        return True
    white_minors = _popcount(board.pieces_mask(chess.KNIGHT, chess.WHITE)) + \
        _popcount(board.pieces_mask(chess.BISHOP, chess.WHITE))
    white_rooks = _popcount(board.pieces_mask(chess.ROOK, chess.WHITE))
    black_minors = _popcount(board.pieces_mask(chess.KNIGHT, chess.BLACK)) + \
        _popcount(board.pieces_mask(chess.BISHOP, chess.BLACK))
    black_rooks = _popcount(board.pieces_mask(chess.ROOK, chess.BLACK))
    if white_queens + black_queens <= 1 and white_rooks == 0 and black_rooks == 0 and white_minors <= 1 and black_minors <= 1:
        return True
    return False


def _game_phase(board):
    """返回 0-24 的整数，0=纯残局，24=纯开局"""
    npm = 0
    for color in (chess.WHITE, chess.BLACK):
        npm += len(board.pieces(chess.KNIGHT, color)) * 3
        npm += len(board.pieces(chess.BISHOP, color)) * 3
        npm += len(board.pieces(chess.ROOK, color)) * 5
        npm += len(board.pieces(chess.QUEEN, color)) * 9
    # 开局约 31，残局约 0，映射到 0-24
    phase = npm * 24 // 31
    return min(24, max(0, phase))


class ChessEngine:
    MAX_TT_SIZE = 500000
    QSEARCH_MAX_DEPTH = 5
    DELTA = 900

    def __init__(self):
        self.transposition_table = {}
        self.killer_moves = [[None, None] for _ in range(64)]
        self.history_table = {}
        self.nodes_searched = 0
        self.start_time = 0
        self.time_limit = 2.0
        self.search_aborted = False
        self.best_move_this_iter = None
        self.best_score_this_iter = None

    def get_opening_move(self, board):
        return None

    def compute_zobrist_hash(self, board):
        logging.warning("compute_zobrist_hash is deprecated and returns 0")
        return 0

    def check_time(self):
        logging.warning("check_time is deprecated and is a no-op")

    def evaluate_king_safety(self, board):
        white_king_score = 0
        black_king_score = 0

        for color in (chess.WHITE, chess.BLACK):
            king_square = board.king(color)
            if king_square is None:
                continue

            enemy_color = not color

            attackers_penalty = 0
            # Check king surroundings for enemy attacks using precomputed list
            for sq in KING_SURROUNDINGS[king_square]:
                if board.is_attacked_by(enemy_color, sq):
                    attackers_penalty += 10

            pawn_shield_bonus = 0
            if color == chess.WHITE:
                if king_square in (chess.G1, chess.H1):
                    pawn_shield_bonus = _pawn_shield_kingside_white(board)
                elif king_square in (chess.A1, chess.B1, chess.C1):
                    pawn_shield_bonus = _pawn_shield_queenside_white(board)
                else:
                    pawn_shield_bonus = _pawn_shield_generic(board, color, king_square)
            else:
                if king_square in (chess.G8, chess.H8):
                    pawn_shield_bonus = _pawn_shield_kingside_black(board)
                elif king_square in (chess.A8, chess.B8, chess.C8):
                    pawn_shield_bonus = _pawn_shield_queenside_black(board)
                else:
                    pawn_shield_bonus = _pawn_shield_generic(board, color, king_square)

            king_score = -attackers_penalty + pawn_shield_bonus
            if color == chess.WHITE:
                white_king_score = king_score
            else:
                black_king_score = king_score

        return white_king_score, black_king_score

    def evaluate_pawn_structure(self, board):
        white_score = 0
        black_score = 0

        white_pawns = list(board.pieces(chess.PAWN, chess.WHITE))
        black_pawns = list(board.pieces(chess.PAWN, chess.BLACK))

        # 叠兵检测
        white_files = {}
        for sq in white_pawns:
            file = chess.square_file(sq)
            white_files[file] = white_files.get(file, 0) + 1
        for count in white_files.values():
            if count >= 2:
                white_score -= 20 * (count - 1)

        black_files = {}
        for sq in black_pawns:
            file = chess.square_file(sq)
            black_files[file] = black_files.get(file, 0) + 1
        for count in black_files.values():
            if count >= 2:
                black_score -= 20 * (count - 1)

        # 孤兵检测
        white_file_set = set(white_files.keys())
        black_file_set = set(black_files.keys())

        for sq in white_pawns:
            file = chess.square_file(sq)
            if (file - 1) not in white_file_set and (file + 1) not in white_file_set:
                white_score -= 15

        for sq in black_pawns:
            file = chess.square_file(sq)
            if (file - 1) not in black_file_set and (file + 1) not in black_file_set:
                black_score -= 15

        # 通路兵奖励 - 预计算每file的最高/最低rank
        black_max_rank_per_file = {}
        for sq in black_pawns:
            f = chess.square_file(sq)
            r = chess.square_rank(sq)
            if f not in black_max_rank_per_file or r > black_max_rank_per_file[f]:
                black_max_rank_per_file[f] = r

        white_min_rank_per_file = {}
        for sq in white_pawns:
            f = chess.square_file(sq)
            r = chess.square_rank(sq)
            if f not in white_min_rank_per_file or r < white_min_rank_per_file[f]:
                white_min_rank_per_file[f] = r

        for sq in white_pawns:
            file = chess.square_file(sq)
            rank = chess.square_rank(sq)
            is_passed = True
            for f in (file - 1, file, file + 1):
                if f in black_max_rank_per_file and black_max_rank_per_file[f] > rank:
                    is_passed = False
                    break
            if is_passed:
                white_score += 40 + 15 * (rank - 1)

        for sq in black_pawns:
            file = chess.square_file(sq)
            rank = chess.square_rank(sq)
            is_passed = True
            for f in (file - 1, file, file + 1):
                if f in white_min_rank_per_file and white_min_rank_per_file[f] < rank:
                    is_passed = False
                    break
            if is_passed:
                black_score += 40 + 15 * (7 - rank)

        # 落后兵检测
        for sq in white_pawns:
            file = chess.square_file(sq)
            rank = chess.square_rank(sq)
            # a) 同列前方有友方兵阻挡
            has_friendly_ahead = False
            for other_sq in white_pawns:
                if other_sq == sq:
                    continue
                other_file = chess.square_file(other_sq)
                other_rank = chess.square_rank(other_sq)
                if other_file == file and other_rank > rank:
                    has_friendly_ahead = True
                    break
            if not has_friendly_ahead:
                continue
            # b) 相邻列没有同排或更高排的白兵可以保护它
            has_adjacent_support = False
            for other_sq in white_pawns:
                if other_sq == sq:
                    continue
                other_file = chess.square_file(other_sq)
                other_rank = chess.square_rank(other_sq)
                if other_file in (file - 1, file + 1) and other_rank >= rank:
                    has_adjacent_support = True
                    break
            if has_adjacent_support:
                continue
            # c) 该兵无法通过前进得到其他兵的保护（前方对角线没有友方兵）
            can_be_protected_by_advance = False
            for other_sq in white_pawns:
                if other_sq == sq:
                    continue
                other_file = chess.square_file(other_sq)
                other_rank = chess.square_rank(other_sq)
                if other_file in (file - 1, file + 1) and other_rank == rank + 1:
                    can_be_protected_by_advance = True
                    break
            if not can_be_protected_by_advance:
                white_score -= 20

        for sq in black_pawns:
            file = chess.square_file(sq)
            rank = chess.square_rank(sq)
            # a) 同列前方有友方兵阻挡（rank 更小）
            has_friendly_ahead = False
            for other_sq in black_pawns:
                if other_sq == sq:
                    continue
                other_file = chess.square_file(other_sq)
                other_rank = chess.square_rank(other_sq)
                if other_file == file and other_rank < rank:
                    has_friendly_ahead = True
                    break
            if not has_friendly_ahead:
                continue
            # b) 相邻列没有同排或更低排的黑兵可以保护它
            has_adjacent_support = False
            for other_sq in black_pawns:
                if other_sq == sq:
                    continue
                other_file = chess.square_file(other_sq)
                other_rank = chess.square_rank(other_sq)
                if other_file in (file - 1, file + 1) and other_rank <= rank:
                    has_adjacent_support = True
                    break
            if has_adjacent_support:
                continue
            # c) 该兵无法通过前进得到其他兵的保护（前方对角线没有友方兵）
            can_be_protected_by_advance = False
            for other_sq in black_pawns:
                if other_sq == sq:
                    continue
                other_file = chess.square_file(other_sq)
                other_rank = chess.square_rank(other_sq)
                if other_file in (file - 1, file + 1) and other_rank == rank - 1:
                    can_be_protected_by_advance = True
                    break
            if not can_be_protected_by_advance:
                black_score -= 20

        # 兵链奖励
        for sq in white_pawns:
            file = chess.square_file(sq)
            rank = chess.square_rank(sq)
            for df in (-1, 1):
                support_file = file + df
                if 0 <= support_file <= 7:
                    support_sq = chess.square(support_file, rank - 1)
                    if support_sq in white_pawns:
                        white_score += 10
                        break

        for sq in black_pawns:
            file = chess.square_file(sq)
            rank = chess.square_rank(sq)
            for df in (-1, 1):
                support_file = file + df
                if 0 <= support_file <= 7:
                    support_sq = chess.square(support_file, rank + 1)
                    if support_sq in black_pawns:
                        black_score += 10
                        break

        return white_score, black_score

    def evaluate(self, board):
        score = 0
        piece_at = board.piece_at

        # Material + PST in single pass
        eg = is_endgame(board)
        king_table = PST_KING_EG if eg else PST_KING_MG
        phase = _game_phase(board)

        for color in (chess.WHITE, chess.BLACK):
            sign = 1 if color == chess.WHITE else -1
            for piece_type in range(1, 7):
                value = PIECE_VALUES[piece_type]
                pieces = board.pieces(piece_type, color)
                score += sign * value * len(pieces)
                if piece_type == chess.KING:
                    table = king_table
                # Tapered evaluation for pieces with MG/EG tables
                if piece_type == chess.PAWN:
                    mg_table = PST_PAWN_MG
                    eg_table = PST_PAWN_EG
                    if color == chess.WHITE:
                        for sq in pieces:
                            mg = mg_table[sq]
                            eg = eg_table[sq]
                            tapered = (phase * mg + (24 - phase) * eg) // 24
                            score += sign * tapered
                    else:
                        for sq in pieces:
                            mg = mg_table[chess.square_mirror(sq)]
                            eg = eg_table[chess.square_mirror(sq)]
                            tapered = (phase * mg + (24 - phase) * eg) // 24
                            score += sign * tapered
                elif piece_type == chess.KNIGHT:
                    mg_table = PST_KNIGHT_MG
                    eg_table = PST_KNIGHT_EG
                    if color == chess.WHITE:
                        for sq in pieces:
                            mg = mg_table[sq]
                            eg = eg_table[sq]
                            tapered = (phase * mg + (24 - phase) * eg) // 24
                            score += sign * tapered
                    else:
                        for sq in pieces:
                            mg = mg_table[chess.square_mirror(sq)]
                            eg = eg_table[chess.square_mirror(sq)]
                            tapered = (phase * mg + (24 - phase) * eg) // 24
                            score += sign * tapered
                elif piece_type == chess.BISHOP:
                    mg_table = PST_BISHOP_MG
                    eg_table = PST_BISHOP_EG
                    if color == chess.WHITE:
                        for sq in pieces:
                            mg = mg_table[sq]
                            eg = eg_table[sq]
                            tapered = (phase * mg + (24 - phase) * eg) // 24
                            score += sign * tapered
                    else:
                        for sq in pieces:
                            mg = mg_table[chess.square_mirror(sq)]
                            eg = eg_table[chess.square_mirror(sq)]
                            tapered = (phase * mg + (24 - phase) * eg) // 24
                            score += sign * tapered
                elif piece_type == chess.ROOK:
                    mg_table = PST_ROOK_MG
                    eg_table = PST_ROOK_EG
                    if color == chess.WHITE:
                        for sq in pieces:
                            mg = mg_table[sq]
                            eg = eg_table[sq]
                            tapered = (phase * mg + (24 - phase) * eg) // 24
                            score += sign * tapered
                    else:
                        for sq in pieces:
                            mg = mg_table[chess.square_mirror(sq)]
                            eg = eg_table[chess.square_mirror(sq)]
                            tapered = (phase * mg + (24 - phase) * eg) // 24
                            score += sign * tapered
                elif piece_type == chess.QUEEN:
                    mg_table = PST_QUEEN_MG
                    eg_table = PST_QUEEN_EG
                    if color == chess.WHITE:
                        for sq in pieces:
                            mg = mg_table[sq]
                            eg = eg_table[sq]
                            tapered = (phase * mg + (24 - phase) * eg) // 24
                            score += sign * tapered
                    else:
                        for sq in pieces:
                            mg = mg_table[chess.square_mirror(sq)]
                            eg = eg_table[chess.square_mirror(sq)]
                            tapered = (phase * mg + (24 - phase) * eg) // 24
                            score += sign * tapered
                else:
                    if color == chess.WHITE:
                        for sq in pieces:
                            score += sign * table[sq]
                    else:
                        for sq in pieces:
                            score += sign * table[chess.square_mirror(sq)]

        # Bishop pair bonus
        if len(board.pieces(chess.BISHOP, chess.WHITE)) >= 2:
            score += 30
        if len(board.pieces(chess.BISHOP, chess.BLACK)) >= 2:
            score -= 30

        # Simple pin detection
        for color in (chess.WHITE, chess.BLACK):
            sign = 1 if color == chess.WHITE else -1
            king_sq = board.king(color)
            if king_sq is None:
                continue
            enemy_color = not color
            enemy_sliders = (
                board.pieces(chess.ROOK, enemy_color)
                | board.pieces(chess.BISHOP, enemy_color)
                | board.pieces(chess.QUEEN, enemy_color)
            )
            for attacker_sq in enemy_sliders:
                # Must be aligned on same rank/file/diagonal
                if not chess.BB_RAYS[king_sq][attacker_sq]:
                    continue
                between = chess.between(king_sq, attacker_sq)
                our_pieces_between = board.occupied_co[color] & between
                if our_pieces_between.bit_count() == 1:
                    pinned_sq = (our_pieces_between & -
                                 our_pieces_between).bit_length() - 1
                    pinned_piece = board.piece_at(pinned_sq)
                    if pinned_piece and pinned_piece.piece_type > chess.PAWN:
                        score += -25 * sign

        # 兵结构评估
        white_pawn_score, black_pawn_score = self.evaluate_pawn_structure(
            board)
        score += white_pawn_score - black_pawn_score

        for sq in CENTER_SQUARES:
            piece = piece_at(sq)
            if piece:
                score += 15 if piece.color == chess.WHITE else -15

        # 王安全性评估
        white_king_score, black_king_score = self.evaluate_king_safety(board)
        score += white_king_score - black_king_score

        for sq in EXTENDED_CENTER:
            piece = piece_at(sq)
            if piece:
                score += 5 if piece.color == chess.WHITE else -5

        # 被将军惩罚 (固定白方视角: 白方被将军则减分, 黑方被将军则加分)
        if board.is_check():
            if board.turn == chess.WHITE:
                score -= 50
            else:
                score += 50

        return score

    def order_moves(self, board, tt_move=None, killers=None):
        logging.warning(
            "order_moves is deprecated; returning board.legal_moves")
        return list(board.legal_moves)

    def update_hash_for_move(self, board, move, board_hash, moving_piece, captured_piece=None):
        logging.warning(
            "update_hash_for_move is deprecated and returns board_hash unchanged")
        return board_hash

    def quiescence_search(self, board, alpha, beta, qdepth=0):
        logging.warning("quiescence_search is deprecated and returns 0")
        return 0

    def negamax(self, board, depth, alpha, beta, board_hash):
        logging.warning("negamax is deprecated and returns 0")
        return 0

    def find_best_move(self, board, max_depth, top_n=1, score_tolerance=0,
                       position_history=None):
        self.nodes_searched = 0
        self.start_time = time.perf_counter()
        self.search_aborted = False
        self.history_table.clear()
        self.killer_moves = [[None, None] for _ in range(64)]

        legal_moves = list(board.legal_moves)
        if not legal_moves:
            return None, 0

        if top_n != 1 or score_tolerance != 0:
            logging.info(
                "top_n and score_tolerance are not supported by the C engine; returning single best move")

        fen = board.fen()
        try:
            uci, nodes = engine_wrapper.search(fen, self.time_limit, max_depth,
                                               position_history=position_history)
            self.nodes_searched = nodes
            if not uci or len(uci) < 4:
                logging.warning(f"C engine returned invalid UCI: '{uci}'")
                return None, 0
            move = chess.Move.from_uci(uci)
            if move not in legal_moves:
                logging.warning(
                    f"C engine returned illegal move {uci}, attempting shallow fallback")
                fallback_engine = ChessEngine()
                fallback_engine.time_limit = max(0.5, self.time_limit * 0.5)
                try:
                    uci2, nodes2 = engine_wrapper.search(fen, fallback_engine.time_limit, 4,
                                                         position_history=position_history)
                    if uci2 and len(uci2) >= 4:
                        move2 = chess.Move.from_uci(uci2)
                        if move2 in legal_moves:
                            logging.warning(f"Fallback succeeded: {uci2}")
                            return move2, nodes2
                except Exception:
                    pass
                logging.warning("Fallback failed, returning None")
                return None, 0
            return move, nodes
        except Exception as e:
            logging.error(f"C engine search failed: {e}")
            try:
                engine_wrapper.reload_library()
                uci_fb, nodes_fb = engine_wrapper.search(fen, max(0.5, self.time_limit * 0.5), 4,
                                                         position_history=position_history)
                if uci_fb and len(uci_fb) >= 4:
                    move_fb = chess.Move.from_uci(uci_fb)
                    if move_fb in legal_moves:
                        logging.warning(f"Engine recovery succeeded: {uci_fb}")
                        return move_fb, nodes_fb
            except Exception:
                pass
            return None, 0


# Fixed-parameter wrapper for game.py
def find_best_move(board, level=None, time_limit=None, max_depth=None,
                   position_history=None):
    engine = ChessEngine()
    engine.time_limit = time_limit if time_limit is not None else 2.0
    depth = max_depth if max_depth is not None else 10
    best_move, _ = engine.find_best_move(board, max_depth=depth,
                                          position_history=position_history)
    return best_move