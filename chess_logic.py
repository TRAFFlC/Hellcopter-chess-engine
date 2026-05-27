import threading

PIECE_UNICODE = {
    "K": "\u2654", "Q": "\u2655", "R": "\u2656", "B": "\u2657", "N": "\u2658", "P": "\u2659",
    "k": "\u265A", "q": "\u265B", "r": "\u265C", "b": "\u265D", "n": "\u265E", "p": "\u265F",
}

INITIAL_BOARD = [
    ["r", "n", "b", "q", "k", "b", "n", "r"],
    ["p", "p", "p", "p", "p", "p", "p", "p"],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    ["P", "P", "P", "P", "P", "P", "P", "P"],
    ["R", "N", "B", "Q", "K", "B", "N", "R"],
]


def board_to_fen(board, side_to_move, castling=None, ep_target=None):
    rows = []
    for r in range(8):
        empty = 0
        row_str = ""
        for c in range(8):
            piece = board[r][c]
            if piece == ".":
                empty += 1
            else:
                if empty > 0:
                    row_str += str(empty)
                    empty = 0
                row_str += piece
        if empty > 0:
            row_str += str(empty)
        rows.append(row_str)
    fen = "/".join(rows)
    fen += " " + side_to_move
    if castling:
        c_str = ""
        if castling.get("K"):
            c_str += "K"
        if castling.get("Q"):
            c_str += "Q"
        if castling.get("k"):
            c_str += "k"
        if castling.get("q"):
            c_str += "q"
        fen += " " + (c_str if c_str else "-")
    else:
        fen += " -"
    if ep_target:
        fen += " " + ep_target
    else:
        fen += " -"
    return fen


def sq_name(r, c):
    return chr(ord("a") + c) + str(8 - r)


def parse_sq(s):
    return 8 - int(s[1]), ord(s[0]) - ord("a")


def is_enemy(piece, color):
    if piece == ".":
        return False
    return piece.islower() if color == "w" else piece.isupper()


def is_friend(piece, color):
    if piece == ".":
        return False
    return piece.isupper() if color == "w" else piece.islower()


def in_bounds(r, c):
    return 0 <= r < 8 and 0 <= c < 8


def find_king(board, color):
    target = "K" if color == "w" else "k"
    for r in range(8):
        for c in range(8):
            if board[r][c] == target:
                return r, c
    return None


def is_square_attacked(board, r, c, by_color):
    directions = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    for dr, dc in directions:
        nr, nc = r + dr, c + dc
        if in_bounds(nr, nc):
            p = board[nr][nc]
            if is_enemy(p, by_color) and p.lower() == "k":
                return True

    for dr, dc in [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]:
        nr, nc = r + dr, c + dc
        if in_bounds(nr, nc):
            p = board[nr][nc]
            if is_enemy(p, by_color) and p.lower() == "n":
                return True

    for dr, dc in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
        nr, nc = r + dr, c + dc
        if in_bounds(nr, nc):
            p = board[nr][nc]
            if is_enemy(p, by_color) and p.lower() == "p":
                if by_color == "w" and dr == 1:
                    continue
                if by_color == "b" and dr == -1:
                    continue
                return True

    for dr, dc in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
        nr, nc = r + dr, c + dc
        while in_bounds(nr, nc):
            p = board[nr][nc]
            if p != ".":
                if is_enemy(p, by_color) and p.lower() in ("b", "q"):
                    return True
                break
            nr += dr
            nc += dc

    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        nr, nc = r + dr, c + dc
        while in_bounds(nr, nc):
            p = board[nr][nc]
            if p != ".":
                if is_enemy(p, by_color) and p.lower() in ("r", "q"):
                    return True
                break
            nr += dr
            nc += dc

    return False


def is_in_check(board, color):
    pos = find_king(board, color)
    if pos is None:
        return False
    r, c = pos
    return is_square_attacked(board, r, c, "b" if color == "w" else "w")


def generate_pseudo_legal_moves(board, color, ep_target=None, castling=None):
    moves = []
    for r in range(8):
        for c in range(8):
            piece = board[r][c]
            if not is_friend(piece, color):
                continue
            pt = piece.lower()

            if pt == "p":
                direction = -1 if color == "w" else 1
                start_row = 6 if color == "w" else 1
                promo_row = 0 if color == "w" else 7
                nr = r + direction
                if in_bounds(nr, c) and board[nr][c] == ".":
                    if nr == promo_row:
                        for promo in ["q", "r", "b", "n"]:
                            moves.append(sq_name(r, c) + sq_name(nr, c) + promo)
                    else:
                        moves.append(sq_name(r, c) + sq_name(nr, c))
                    if r == start_row:
                        nnr = r + 2 * direction
                        if in_bounds(nnr, c) and board[nnr][c] == ".":
                            moves.append(sq_name(r, c) + sq_name(nnr, c))
                for dc in [-1, 1]:
                    nc = c + dc
                    if not in_bounds(nr, nc):
                        continue
                    target = board[nr][nc]
                    if is_enemy(target, color):
                        if nr == promo_row:
                            for promo in ["q", "r", "b", "n"]:
                                moves.append(sq_name(r, c) + sq_name(nr, nc) + promo)
                        else:
                            moves.append(sq_name(r, c) + sq_name(nr, nc))
                    if ep_target and sq_name(nr, nc) == ep_target:
                        moves.append(sq_name(r, c) + sq_name(nr, nc))

            elif pt == "n":
                for dr, dc in [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]:
                    nr, nc = r + dr, c + dc
                    if in_bounds(nr, nc) and not is_friend(board[nr][nc], color):
                        moves.append(sq_name(r, c) + sq_name(nr, nc))

            elif pt in ("b", "r", "q"):
                dirs = []
                if pt in ("b", "q"):
                    dirs += [(-1, -1), (-1, 1), (1, -1), (1, 1)]
                if pt in ("r", "q"):
                    dirs += [(-1, 0), (1, 0), (0, -1), (0, 1)]
                for dr, dc in dirs:
                    nr, nc = r + dr, c + dc
                    while in_bounds(nr, nc):
                        target = board[nr][nc]
                        if is_friend(target, color):
                            break
                        moves.append(sq_name(r, c) + sq_name(nr, nc))
                        if is_enemy(target, color):
                            break
                        nr += dr
                        nc += dc

            elif pt == "k":
                for dr in [-1, 0, 1]:
                    for dc in [-1, 0, 1]:
                        if dr == 0 and dc == 0:
                            continue
                        nr, nc = r + dr, c + dc
                        if in_bounds(nr, nc) and not is_friend(board[nr][nc], color):
                            moves.append(sq_name(r, c) + sq_name(nr, nc))

                if castling:
                    enemy = "b" if color == "w" else "w"
                    if color == "w" and r == 7 and c == 4:
                        if castling.get("K") and board[7][5] == "." and board[7][6] == ".":
                            if not is_square_attacked(board, 7, 4, enemy) and \
                               not is_square_attacked(board, 7, 5, enemy) and \
                               not is_square_attacked(board, 7, 6, enemy):
                                moves.append("e1g1")
                        if castling.get("Q") and board[7][3] == "." and board[7][2] == "." and board[7][1] == ".":
                            if not is_square_attacked(board, 7, 4, enemy) and \
                               not is_square_attacked(board, 7, 3, enemy) and \
                               not is_square_attacked(board, 7, 2, enemy):
                                moves.append("e1c1")
                    elif color == "b" and r == 0 and c == 4:
                        if castling.get("k") and board[0][5] == "." and board[0][6] == ".":
                            if not is_square_attacked(board, 0, 4, enemy) and \
                               not is_square_attacked(board, 0, 5, enemy) and \
                               not is_square_attacked(board, 0, 6, enemy):
                                moves.append("e8g8")
                        if castling.get("q") and board[0][3] == "." and board[0][2] == "." and board[0][1] == ".":
                            if not is_square_attacked(board, 0, 4, enemy) and \
                               not is_square_attacked(board, 0, 3, enemy) and \
                               not is_square_attacked(board, 0, 2, enemy):
                                moves.append("e8c8")

    return moves


def apply_move(board, uci_move, ep_target=None, castling=None):
    new_board = [row[:] for row in board]
    from_r, from_c = parse_sq(uci_move[0:2])
    to_r, to_c = parse_sq(uci_move[2:4])
    promo = uci_move[4] if len(uci_move) > 4 else None
    piece = new_board[from_r][from_c]
    color = "w" if piece.isupper() else "b"
    new_ep = None
    new_castling = dict(castling) if castling else {"K": True, "Q": True, "k": True, "q": True}

    if piece.lower() == "p" and ep_target and sq_name(to_r, to_c) == ep_target:
        cap_r = from_r
        new_board[cap_r][to_c] = "."

    new_board[to_r][to_c] = piece
    new_board[from_r][from_c] = "."

    if piece.lower() == "p" and abs(to_r - from_r) == 2:
        new_ep = sq_name((from_r + to_r) // 2, from_c)

    if promo:
        new_board[to_r][to_c] = promo.upper() if color == "w" else promo.lower()

    if piece.lower() == "k":
        if castling:
            if color == "w":
                new_castling["K"] = False
                new_castling["Q"] = False
            else:
                new_castling["k"] = False
                new_castling["q"] = False
        if abs(to_c - from_c) == 2:
            if to_c == 6:
                new_board[from_r][5] = new_board[from_r][7]
                new_board[from_r][7] = "."
            elif to_c == 2:
                new_board[from_r][3] = new_board[from_r][0]
                new_board[from_r][0] = "."

    if piece.lower() == "r":
        if from_r == 7 and from_c == 0:
            new_castling["Q"] = False
        elif from_r == 7 and from_c == 7:
            new_castling["K"] = False
        elif from_r == 0 and from_c == 0:
            new_castling["q"] = False
        elif from_r == 0 and from_c == 7:
            new_castling["k"] = False

    if to_r == 7 and to_c == 0:
        new_castling["Q"] = False
    elif to_r == 7 and to_c == 7:
        new_castling["K"] = False
    elif to_r == 0 and to_c == 0:
        new_castling["q"] = False
    elif to_r == 0 and to_c == 7:
        new_castling["k"] = False

    return new_board, new_ep, new_castling


def generate_legal_moves(board, color, ep_target=None, castling=None):
    pseudo = generate_pseudo_legal_moves(board, color, ep_target, castling)
    legal = []
    for uci in pseudo:
        new_board, _, _ = apply_move(board, uci, ep_target, castling)
        if not is_in_check(new_board, color):
            legal.append(uci)
    return legal


class GameState:
    def __init__(self, move_time=3000):
        self.lock = threading.Lock()
        self.move_time = move_time
        self.reset()

    def reset(self):
        self.board = [row[:] for row in INITIAL_BOARD]
        self.move_history = []
        self.ep_target = None
        self.castling = {"K": True, "Q": True, "k": True, "q": True}
        self.player_color = "w"
        self.engine_thinking = False
        self.game_over = False
        self.game_result = ""
        self.last_move = None

    def get_legal_moves(self):
        current = "w" if len(self.move_history) % 2 == 0 else "b"
        return generate_legal_moves(self.board, current, self.ep_target, self.castling)

    def make_move(self, uci_move):
        new_board, new_ep, new_castling = apply_move(
            self.board, uci_move, self.ep_target, self.castling
        )
        self.board = new_board
        self.ep_target = new_ep
        self.castling = new_castling
        self.move_history.append(uci_move)
        self.last_move = uci_move

    def check_game_over(self):
        current = "w" if len(self.move_history) % 2 == 0 else "b"
        legal = generate_legal_moves(
            self.board, current, self.ep_target, self.castling)
        if not legal:
            self.game_over = True
            if is_in_check(self.board, current):
                winner = "白方" if current == "b" else "黑方"
                self.game_result = f"将杀！{winner}获胜！"
            else:
                self.game_result = "和棋（逼和）！"
            return True
        return False

    def to_dict(self):
        current = "w" if len(self.move_history) % 2 == 0 else "b"
        in_check = is_in_check(self.board, current)
        legal = self.get_legal_moves()
        return {
            "board": self.board,
            "moveHistory": self.move_history,
            "playerColor": self.player_color,
            "engineThinking": self.engine_thinking,
            "gameOver": self.game_over,
            "gameResult": self.game_result,
            "currentTurn": current,
            "inCheck": in_check,
            "legalMoves": legal,
            "lastMove": self.last_move,
            "castling": self.castling,
            "moveTime": self.move_time,
        }
