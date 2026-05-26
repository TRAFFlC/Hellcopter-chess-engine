import os
import sys
import subprocess
import threading
import json
import queue
import time as time_mod
from flask import Flask, jsonify, request, send_from_directory, Response

app = Flask(__name__, static_folder="web_static", static_url_path="/static")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.join(BASE_DIR, "test_engines", "Chess3Super", "chess3super.exe")
DEFAULT_MOVE_TIME = 3000

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
            p = board[r][c]
            if p == ".":
                empty += 1
            else:
                if empty:
                    row_str += str(empty)
                    empty = 0
                row_str += p
        if empty:
            row_str += str(empty)
        rows.append(row_str)
    fen = "/".join(rows) + " " + side_to_move

    if castling:
        cs = ""
        if castling.get("K"): cs += "K"
        if castling.get("Q"): cs += "Q"
        if castling.get("k"): cs += "k"
        if castling.get("q"): cs += "q"
        fen += " " + (cs if cs else "-")
    else:
        fen += " -"

    if ep_target and isinstance(ep_target, tuple):
        fen += " " + sq_name(ep_target[0], ep_target[1])
    else:
        fen += " -"

    fen += " 0 1"
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
    for dr, dc in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
        nr, nc = r + dr, c + dc
        if in_bounds(nr, nc):
            p = board[nr][nc]
            if is_friend(p, by_color) and p.upper() == "K":
                return True

    for dr, dc in [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]:
        nr, nc = r + dr, c + dc
        if in_bounds(nr, nc):
            p = board[nr][nc]
            if is_friend(p, by_color) and p.upper() == "N":
                return True

    pawn_dr = 1 if by_color == "w" else -1
    for dc in [-1, 1]:
        nr, nc = r + pawn_dr, c + dc
        if in_bounds(nr, nc):
            p = board[nr][nc]
            if is_friend(p, by_color) and p.upper() == "P":
                return True

    for dr, dc in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
        for dist in range(1, 8):
            nr, nc = r + dr * dist, c + dc * dist
            if not in_bounds(nr, nc):
                break
            p = board[nr][nc]
            if p != ".":
                if is_friend(p, by_color) and p.upper() in ("B", "Q"):
                    return True
                break

    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        for dist in range(1, 8):
            nr, nc = r + dr * dist, c + dc * dist
            if not in_bounds(nr, nc):
                break
            p = board[nr][nc]
            if p != ".":
                if is_friend(p, by_color) and p.upper() in ("R", "Q"):
                    return True
                break

    return False


def is_in_check(board, color):
    pos = find_king(board, color)
    if pos is None:
        return True
    kr, kc = pos
    opp = "b" if color == "w" else "w"
    return is_square_attacked(board, kr, kc, opp)


def generate_pseudo_legal_moves(board, color, ep_target=None, castling=None):
    moves = []
    if castling is None:
        castling = {"K": True, "Q": True, "k": True, "q": True}

    for r in range(8):
        for c in range(8):
            piece = board[r][c]
            if not is_friend(piece, color):
                continue
            pt = piece.upper()
            frm = sq_name(r, c)

            if pt == "P":
                direction = -1 if color == "w" else 1
                start_rank = 6 if color == "w" else 1
                promo_rank = 0 if color == "w" else 7

                nr = r + direction
                if in_bounds(nr, c) and board[nr][c] == ".":
                    if nr == promo_rank:
                        for promo in "qrbn":
                            moves.append(frm + sq_name(nr, c) + promo)
                    else:
                        moves.append(frm + sq_name(nr, c))
                    if r == start_rank:
                        nr2 = r + 2 * direction
                        if in_bounds(nr2, c) and board[nr2][c] == ".":
                            moves.append(frm + sq_name(nr2, c))

                for dc in [-1, 1]:
                    nc = c + dc
                    nr = r + direction
                    if not in_bounds(nr, nc):
                        continue
                    target = board[nr][nc]
                    if is_enemy(target, color):
                        if nr == promo_rank:
                            for promo in "qrbn":
                                moves.append(frm + sq_name(nr, nc) + promo)
                        else:
                            moves.append(frm + sq_name(nr, nc))
                    if ep_target and (nr, nc) == ep_target:
                        moves.append(frm + sq_name(nr, nc))

            elif pt == "N":
                for dr, dc in [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]:
                    nr, nc = r + dr, c + dc
                    if in_bounds(nr, nc) and not is_friend(board[nr][nc], color):
                        moves.append(frm + sq_name(nr, nc))

            elif pt == "K":
                for dr, dc in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
                    nr, nc = r + dr, c + dc
                    if in_bounds(nr, nc) and not is_friend(board[nr][nc], color):
                        moves.append(frm + sq_name(nr, nc))

                opp = "b" if color == "w" else "w"
                back_rank = 7 if color == "w" else 0
                if r == back_rank and c == 4:
                    ks_key = "K" if color == "w" else "k"
                    qs_key = "Q" if color == "w" else "q"
                    if castling.get(ks_key) and board[back_rank][5] == "." and board[back_rank][6] == ".":
                        if not is_square_attacked(board, back_rank, 4, opp) and \
                           not is_square_attacked(board, back_rank, 5, opp) and \
                           not is_square_attacked(board, back_rank, 6, opp):
                            moves.append(frm + sq_name(back_rank, 6))
                    if castling.get(qs_key) and board[back_rank][3] == "." and board[back_rank][2] == "." and board[back_rank][1] == ".":
                        if not is_square_attacked(board, back_rank, 4, opp) and \
                           not is_square_attacked(board, back_rank, 3, opp) and \
                           not is_square_attacked(board, back_rank, 2, opp):
                            moves.append(frm + sq_name(back_rank, 2))
            else:
                dirs = []
                if pt in ("B", "Q"):
                    dirs += [(-1, -1), (-1, 1), (1, -1), (1, 1)]
                if pt in ("R", "Q"):
                    dirs += [(-1, 0), (1, 0), (0, -1), (0, 1)]
                for dr, dc in dirs:
                    for dist in range(1, 8):
                        nr, nc = r + dr * dist, c + dc * dist
                        if not in_bounds(nr, nc):
                            break
                        target = board[nr][nc]
                        if is_friend(target, color):
                            break
                        moves.append(frm + sq_name(nr, nc))
                        if is_enemy(target, color):
                            break

    return moves


def apply_move(board, uci, ep_target=None, castling=None):
    if castling is None:
        castling = {"K": True, "Q": True, "k": True, "q": True}
    new_board = [row[:] for row in board]
    new_castling = dict(castling)
    new_ep = None

    from_r, from_c = parse_sq(uci[0:2])
    to_r, to_c = parse_sq(uci[2:4])
    promo = uci[4] if len(uci) > 4 else None

    piece = new_board[from_r][from_c]
    color = "w" if piece.isupper() else "b"
    captured = new_board[to_r][to_c]

    new_board[from_r][from_c] = "."

    if promo:
        new_board[to_r][to_c] = promo.upper(
        ) if color == "w" else promo.lower()
    else:
        new_board[to_r][to_c] = piece

    if piece.upper() == "P" and to_c != from_c and captured == ".":
        if color == "w":
            new_board[to_r + 1][to_c] = "."
        else:
            new_board[to_r - 1][to_c] = "."

    if piece.upper() == "K" and abs(to_c - from_c) == 2:
        if to_c > from_c:
            rook = new_board[from_r][7]
            new_board[from_r][7] = "."
            new_board[from_r][5] = rook
        else:
            rook = new_board[from_r][0]
            new_board[from_r][0] = "."
            new_board[from_r][3] = rook

    if piece.upper() == "P" and abs(to_r - from_r) == 2:
        ep_r = (from_r + to_r) // 2
        new_ep = (ep_r, to_c)

    if piece == "K":
        new_castling["K"] = False
        new_castling["Q"] = False
    elif piece == "k":
        new_castling["k"] = False
        new_castling["q"] = False
    if (from_r, from_c) == (7, 0) or (to_r, to_c) == (7, 0):
        new_castling["Q"] = False
    if (from_r, from_c) == (7, 7) or (to_r, to_c) == (7, 7):
        new_castling["K"] = False
    if (from_r, from_c) == (0, 0) or (to_r, to_c) == (0, 0):
        new_castling["q"] = False
    if (from_r, from_c) == (0, 7) or (to_r, to_c) == (0, 7):
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
    def __init__(self):
        self.lock = threading.Lock()
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
        self.move_time = DEFAULT_MOVE_TIME

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
        if is_in_check(self.board, current):
            pass
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


class Engine:
    def __init__(self, engine_path, engine_args=None, protocol="auto",
                 init_options=None):
        self.engine_path = engine_path
        self.engine_args = engine_args or []
        self.process = None
        self.lock = threading.Lock()
        self.protocol = protocol
        self.init_options = init_options or {}
        self.xboard_features = {}
        self._line_queue = queue.Queue()
        self._reader_alive = False

    def start(self):
        try:
            cmd = [self.engine_path] + self.engine_args
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            self._start_reader()

            if self.protocol == "auto":
                self._detect_protocol()

            if self.protocol == "xboard":
                self._init_xboard()
            elif self.protocol == "tscp":
                self._init_tscp()
            else:
                self._init_uci()

            for opt_name, opt_value in self.init_options.items():
                if self.protocol == "uci":
                    self.send(f"setoption name {opt_name} value {opt_value}")
                elif opt_name == "UCI_LimitStrength" and opt_value:
                    self.send("setoption name UCI_LimitStrength value true")
                    self.send(f"setoption name UCI_Elo value {opt_value}")

            if self.protocol == "uci":
                self.send("ucinewgame")
                self.send("isready")
                self.wait_for("readyok", timeout=5.0)
            return True
        except Exception as e:
            print(f"引擎启动失败 [{self.engine_path}]: {e}")
            return False

    def _start_reader(self):
        self._reader_alive = True
        def _reader():
            while self._reader_alive and self.process and self.process.poll() is None:
                try:
                    raw = self.process.stdout.readline()
                    if not raw:
                        break
                    self._line_queue.put(raw.decode(errors='replace').strip())
                except Exception:
                    break
            self._reader_alive = False
        t = threading.Thread(target=_reader, daemon=True)
        t.start()

    def _stop_reader(self):
        self._reader_alive = False

    def _detect_protocol(self):
        time_mod.sleep(0.3)
        if self.process and self.process.poll() is not None:
            raise RuntimeError("引擎进程已退出")

        banner = self.readline(timeout=0.5)
        if banner and ("TSCP" in banner or "Simple Chess" in banner
                       or "Kerrigan" in banner):
            self.protocol = "tscp"
            self.tscp_banner = banner
            return

        self.send("uci")
        try:
            line = self.wait_for("uciok", timeout=3.0)
            self.protocol = "uci"
            return
        except Exception:
            pass

        if self.process and self.process.poll() is not None:
            raise RuntimeError("引擎进程已退出")

        self.send("xboard")
        try:
            self.send("protover 2")
            xb_start = time_mod.time()
            while True:
                line = self.readline(timeout=1.0)
                if not line:
                    if time_mod.time() - xb_start > 4.0:
                        raise TimeoutError("XBoard 引擎无回应")
                    time_mod.sleep(0.1)
                    continue
                if "done=1" in line:
                    self.protocol = "xboard"
                    return
                if "feature " in line:
                    self._parse_xboard_feature(line)
                if line.startswith("Error"):
                    raise RuntimeError(f"XBoard 错误: {line}")
        except Exception:
            pass

        if self.process and self.process.poll() is not None:
            raise RuntimeError("引擎进程已退出")

        tscp_try = self.readline(timeout=1.0)
        if tscp_try and ("TSCP" in tscp_try or "Simple Chess" in tscp_try
                         or "Kerrigan" in tscp_try):
            self.protocol = "tscp"
            return
        self.send("xboard")
        tscp_try2 = self.readline(timeout=1.0)
        if tscp_try2 and "Unknown" in tscp_try2:
            self.protocol = "tscp"
            return

        if self.process and self.process.poll() is not None:
            raise RuntimeError("引擎进程已退出")

        raise RuntimeError("无法检测引擎协议")

    def _parse_xboard_feature(self, line):
        line = line.strip()
        if line.endswith("done=1"):
            line = line[:-6].strip()
        parts = line.split()
        for p in parts:
            if "=" in p:
                k, v = p.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"')
                self.xboard_features[k] = v

    def _init_uci(self):
        self.send("isready")
        self.wait_for("readyok", timeout=5.0)

    def _init_xboard(self):
        for line_data in self.xboard_features.copy().items():
            pass
        self.send("accepted done")
        self.send("new")
        self.send("random")
        time_mod.sleep(0.1)

    def _init_tscp(self):
        pass

    def set_option(self, name, value):
        if self.protocol == "uci":
            self.send(f"setoption name {name} value {value}")

    def send(self, cmd):
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.write((cmd + "\n").encode())
                self.process.stdin.flush()
            except Exception:
                pass

    def readline(self, timeout=None):
        if self.process is None or self.process.poll() is not None:
            return ""
        try:
            return self._line_queue.get(timeout=timeout if timeout is not None else 30.0)
        except queue.Empty:
            return ""

    def _read_until(self, prefix, timeout=30.0):
        start = time_mod.time()
        while True:
            remaining = max(0.5, (timeout - (time_mod.time() - start))) if timeout else 5.0
            line = self.readline(timeout=min(remaining, 2.0))
            if line.startswith(prefix):
                return line
            if timeout and (time_mod.time() - start) > timeout:
                return ""
            if not line and self.process and self.process.poll() is not None:
                return ""

    def wait_for(self, token, timeout=None):
        start = time_mod.time()
        while True:
            remaining = timeout
            if timeout is not None:
                remaining = max(0.5, timeout - (time_mod.time() - start))
            line = self.readline(timeout=min(remaining, 2.0) if remaining else 2.0)
            if token in line:
                return line
            if timeout is not None and (time_mod.time() - start) > timeout:
                raise TimeoutError(f"等待 '{token}' 超时 ({timeout}s)")
            if not line and self.process and self.process.poll() is not None:
                raise RuntimeError(f"引擎进程已退出, 等待 '{token}' 失败")

    def get_best_move(self, move_history, move_time_ms):
        with self.lock:
            if self.protocol == "xboard":
                return self._xboard_get_move_fixed(move_time_ms)
            self.send("position startpos moves " + " ".join(move_history))
            self.send(f"go movetime {move_time_ms}")
            line = self._read_until("bestmove", timeout=max(10.0, move_time_ms / 500.0))
            if line.startswith("bestmove"):
                parts = line.split()
                return parts[1] if len(parts) > 1 else ""
            return ""

    def get_best_move_with_time(self, move_history, wtime, btime, winc, binc,
                                board=None, ep_target=None, castling=None):
        with self.lock:
            if self.protocol == "xboard":
                return self._xboard_get_move(move_history, wtime, btime, winc, binc,
                                             board, ep_target, castling)
            if self.protocol == "tscp":
                return self._tscp_get_move(move_history, wtime, btime, winc, binc)
            self.send("position startpos moves " + " ".join(move_history))
            self.send(f"go wtime {wtime} btime {btime} winc {winc} binc {binc}")
            line = self._read_until("bestmove", timeout=30.0)
            if line.startswith("bestmove"):
                parts = line.split()
                return parts[1] if len(parts) > 1 else ""
            return ""

    def _xboard_get_move(self, move_history, wtime, btime, winc, binc,
                         board, ep_target, castling):
        if board:
            fen = board_to_fen(board, "w" if len(move_history) % 2 == 0 else "b",
                               castling, ep_target)
            self.send("setboard " + fen)
        else:
            self.send("force")
            self.send("new")
            for m in move_history:
                self.send(m)
            time_mod.sleep(0.1)

        self.send(f"level 0 {max(1, wtime // 1000)} {winc / 1000.0:.1f}")
        self.send(f"time {wtime // 10}")
        self.send(f"otim {btime // 10}")
        self.send("go")

        line = self._read_until("move ", timeout=30.0)
        if line.startswith("move "):
            parts = line.split()
            return parts[1] if len(parts) > 1 else ""
        return ""

    def _xboard_get_move_fixed(self, move_time_ms):
        self.send(f"st {max(1, move_time_ms // 1000)}")
        self.send("go")
        line = self._read_until("move ", timeout=max(10.0, move_time_ms / 500.0))
        if line.startswith("move "):
            parts = line.split()
            return parts[1] if len(parts) > 1 else ""
        return ""

    def _tscp_get_move(self, move_history, wtime, btime, winc, binc):
        self.send("new")
        time_mod.sleep(0.05)
        for m in move_history:
            self.send(m)
            time_mod.sleep(0.02)
        move_time_sec = max(0.5, min((wtime + btime) / 2000.0, 5.0))
        self.send("sd 8")
        self.send("st {:d}".format(int(move_time_sec)))
        self.send("go")
        start = time_mod.time()
        timeout = move_time_sec + 5.0
        while True:
            remaining = max(0.5, timeout - (time_mod.time() - start))
            line = self.readline(timeout=min(remaining, 1.0))
            if line and len(line) >= 4 and line[0] in "abcdefgh":
                return line.strip().lower()
            if time_mod.time() - start > timeout:
                return ""
            if not line and self.process and self.process.poll() is not None:
                return ""

    def new_game(self):
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                return
            try:
                if self.protocol == "xboard":
                    self.send("new")
                    self.send("random")
                elif self.protocol == "tscp":
                    self.send("new")
                    time_mod.sleep(0.05)
                else:
                    self.send("ucinewgame")
                    self.send("isready")
                    self.wait_for("readyok", timeout=5.0)
            except Exception as e:
                print(f"new_game 失败 [{self.engine_path}]: {e}")

    def quit(self):
        self._reader_alive = False
        try:
            if self.process and self.process.poll() is None:
                if self.protocol == "tscp":
                    self.send("quit")
                else:
                    self.send("quit")
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    self.process.wait(timeout=2)
        except Exception:
            pass


game = GameState()
engine = Engine(ENGINE_PATH)

VELVET_PATH = os.path.join(BASE_DIR, "test_engines", "Velvet", "velvet-v8.1.1-x86_64-avx2.exe")
STOCKFISH_PATH = os.path.join(BASE_DIR, "test_engines", "Stockfish", "src", "stockfish.exe")
SHALLOWBLUE_PATH = os.path.join(BASE_DIR, "test_engines", "ShallowBlue 1575", "shallowblue.exe")
APOLLO_PATH = os.path.join(BASE_DIR, "test_engines", "Apollo 1663", "apollo.exe")
MONARCH_PATH = os.path.join(BASE_DIR, "test_engines", "Monarch 2005", "Monarch(v1.7)", "Monarch(v1.7).exe")
RAINMAN_PATH = os.path.join(BASE_DIR, "test_engines", "Rainman 1427", "rainman.exe")
SARGON_PATH = os.path.join(BASE_DIR, "test_engines", "sargon 1163", "sargon-engine-static-link.exe")
TSCP_PATH = os.path.join(BASE_DIR, "test_engines", "TSCP 1607", "tscp181.exe")
CHESS3SUPER_PATH = ENGINE_PATH
HELLCOPTER_ADAPTER_DIR = os.path.join(BASE_DIR, "temp_hellcopter_uci")


def create_hellcopter_adapter():
    env_params = os.path.join(BASE_DIR, "configs", "v1.7.0.json")
    os.makedirs(HELLCOPTER_ADAPTER_DIR, exist_ok=True)
    adapter_path = os.path.join(HELLCOPTER_ADAPTER_DIR, "hellcopter_uci.py")

    env_params_fwd = env_params.replace("\\", "/")
    base_dir_fwd = BASE_DIR.replace("\\", "/")

    with open(adapter_path, "w", encoding="utf-8") as f:
        f.write("import os\n")
        f.write("import sys\n\n")
        f.write(f'os.environ["ENGINE_PARAMS"] = "{env_params_fwd}"\n')
        f.write(f'sys.path.insert(0, "{base_dir_fwd}")\n\n')
        f.write("from uci_engine import UCIEngine\n\n")
        f.write('if __name__ == "__main__":\n')
        f.write("    uci = UCIEngine()\n")
        f.write("    uci.run()\n")

    return adapter_path


def _make_hellcopter(name):
    ap = create_hellcopter_adapter()
    return Engine(sys.executable, engine_args=[ap], protocol="uci")


ENGINE_REGISTRY = [
    {"id": "chess3super", "name": "Chess3Super",
     "path": CHESS3SUPER_PATH, "args": [], "protocol": "uci", "options": []},
    {"id": "hellcopter", "name": "Hellcopter v1.7.0",
     "path": None, "factory": lambda: _make_hellcopter("Hellcopter v1.7.0"),
     "protocol": "uci", "options": []},
    {"id": "velvet", "name": "Velvet v8.1.1",
     "path": VELVET_PATH, "args": [], "protocol": "uci",
     "options": [{"name": "limitStrength", "label": "限制强度", "type": "check", "default": False},
                 {"name": "UCI_Elo", "label": "Elo 等级", "type": "spin", "default": 2000, "min": 1225, "max": 3000}]},
    {"id": "stockfish", "name": "Stockfish",
     "path": STOCKFISH_PATH, "args": [], "protocol": "uci", "options": []},
    {"id": "shallowblue", "name": "ShallowBlue 1575",
     "path": SHALLOWBLUE_PATH, "args": [], "protocol": "uci", "options": []},
    {"id": "apollo", "name": "Apollo 1663",
     "path": APOLLO_PATH, "args": [], "protocol": "uci", "options": []},
    {"id": "monarch", "name": "Monarch 2005 v1.7",
     "path": MONARCH_PATH, "args": [], "protocol": "uci", "options": []},
    {"id": "sargon", "name": "Sargon 1978 v1.01b",
     "path": SARGON_PATH, "args": [], "protocol": "uci", "options": []},
    {"id": "rainman", "name": "Rainman 1427",
     "path": RAINMAN_PATH, "args": [], "protocol": "xboard", "options": []},
    {"id": "tscp", "name": "TSCP 181",
     "path": TSCP_PATH, "args": [], "protocol": "tscp", "options": []},
]


def _resolve_engine(engine_id, extra_options=None):
    for entry in ENGINE_REGISTRY:
        if entry["id"] == engine_id:
            opts = {}
            for opt in entry.get("options", []):
                if extra_options and opt["name"] in extra_options:
                    val = extra_options[opt["name"]]
                    if opt["type"] == "check":
                        opts[opt["name"]] = val
                    elif opt["name"] == "UCI_Elo":
                        opts[opt["name"]] = val
                    else:
                        opts[opt["name"]] = val

            if "factory" in entry:
                eng = entry["factory"]()
                for k, v in opts.items():
                    if k == "limitStrength" and v:
                        eng.set_option("UCI_LimitStrength", "true")
                    elif k == "UCI_Elo":
                        eng.set_option("UCI_Elo", str(v))
                return eng, entry

            init_opts = {}
            for opt_name, opt_val in opts.items():
                if opt_name == "limitStrength":
                    if opt_val:
                        init_opts["UCI_LimitStrength"] = True
                elif opt_name == "UCI_Elo":
                    init_opts["UCI_Elo"] = int(opt_val) if isinstance(opt_val, (str, int)) else opt_val
                else:
                    init_opts[opt_name] = opt_val
            if init_opts:
                eng = Engine(entry["path"], entry.get("args", []), entry.get("protocol", "auto"), init_opts)
            else:
                eng = Engine(entry["path"], entry.get("args", []), entry.get("protocol", "auto"))
            return eng, entry
    return None, None

match_state = {
    "active": False,
    "board": [row[:] for row in INITIAL_BOARD],
    "move_history": [],
    "last_move": None,
    "engine1_name": "",
    "engine2_name": "",
    "engine1_time": 0,
    "engine2_time": 0,
    "current_side": "w",
    "game_over": False,
    "game_result": "",
    "move_count": 0,
    "time_base": 96000,
    "time_inc": 800,
    "ep_target": None,
    "castling": {"K": True, "Q": True, "k": True, "q": True},
    "score1": 0,
    "score2": 0,
    "games_played": 0,
    "total_games": 2,
    "white_name": "",
    "black_name": "",
}


def match_board_to_dict():
    ms = match_state
    current = "w" if len(ms["move_history"]) % 2 == 0 else "b"
    return {
        "board": ms["board"],
        "moveHistory": ms["move_history"],
        "lastMove": ms["last_move"],
        "engine1Name": ms["engine1_name"],
        "engine2Name": ms["engine2_name"],
        "whiteName": ms["white_name"],
        "blackName": ms["black_name"],
        "engine1Time": ms["engine1_time"],
        "engine2Time": ms["engine2_time"],
        "currentSide": current,
        "gameOver": ms["game_over"],
        "gameResult": ms["game_result"],
        "moveCount": ms["move_count"],
        "active": ms["active"],
        "score1": ms["score1"],
        "score2": ms["score2"],
        "gamesPlayed": ms["games_played"],
        "totalGames": ms["total_games"],
    }


_sse_listeners = []
_sse_lock = threading.Lock()


def sse_notify():
    data = json.dumps(match_board_to_dict(), ensure_ascii=False)
    with _sse_lock:
        dead = []
        for i, q in enumerate(_sse_listeners):
            try:
                q.put_nowait(data)
            except Exception:
                dead.append(i)
        for i in reversed(dead):
            _sse_listeners.pop(i)


def run_engine_match(engine1_id, engine2_id, engine1_name, engine2_name,
                     time_base, time_inc, total_games, extra_opts=None):
    extra_opts = extra_opts or {}
    e1, entry1 = _resolve_engine(engine1_id, extra_opts.get(engine1_id, {}))
    e2, entry2 = _resolve_engine(engine2_id, extra_opts.get(engine2_id, {}))

    if not e1 or not e2:
        match_state["game_result"] = "引擎配置无效"
        match_state["active"] = False
        sse_notify()
        return

    e1_proto = entry1.get("protocol", "uci")
    e2_proto = entry2.get("protocol", "uci")

    match_state["engine1_name"] = engine1_name
    match_state["engine2_name"] = engine2_name

    try:
        if not e1.start():
            match_state["game_result"] = f"{engine1_name} 启动失败"
            match_state["game_over"] = True
            match_state["active"] = False
            sse_notify()
            return
        if not e2.start():
            match_state["game_result"] = f"{engine2_name} 启动失败"
            match_state["game_over"] = True
            match_state["active"] = False
            sse_notify()
            return

        for game_idx in range(total_games):
            if not match_state["active"]:
                break

            even_game = (game_idx % 2 == 0)
            if even_game:
                white_engine, black_engine = e1, e2
                white_name, black_name = engine1_name, engine2_name
            else:
                white_engine, black_engine = e2, e1
                white_name, black_name = engine2_name, engine1_name

            def add_score(winner_is_white):
                if winner_is_white:
                    if even_game:
                        match_state["score1"] += 1
                    else:
                        match_state["score2"] += 1
                else:
                    if even_game:
                        match_state["score2"] += 1
                    else:
                        match_state["score1"] += 1

            white_engine.new_game()
            black_engine.new_game()

            if (white_engine.process is None or white_engine.process.poll() is not None):
                match_state["game_over"] = True
                match_state["game_result"] = f"{white_name} 引擎进程异常退出"
                add_score(False)
                sse_notify()
                break
            if (black_engine.process is None or black_engine.process.poll() is not None):
                match_state["game_over"] = True
                match_state["game_result"] = f"{black_name} 引擎进程异常退出"
                add_score(True)
                sse_notify()
                break

            match_state["board"] = [row[:] for row in INITIAL_BOARD]
            match_state["move_history"] = []
            match_state["last_move"] = None
            match_state["game_over"] = False
            match_state["game_result"] = f"第{game_idx+1}局: {white_name}(白) vs {black_name}(黑)"
            match_state["move_count"] = 0
            match_state["ep_target"] = None
            match_state["castling"] = {
                "K": True, "Q": True, "k": True, "q": True}
            match_state["engine1_time"] = time_base
            match_state["engine2_time"] = time_base
            match_state["white_name"] = white_name
            match_state["black_name"] = black_name
            sse_notify()

            times = [time_base, time_base]
            repetition_count = {}

            for move_num in range(300):
                if not match_state["active"]:
                    break

                side = move_num % 2
                eng = white_engine if side == 0 else black_engine
                eng_name = white_name if side == 0 else black_name

                wtime = times[0]
                btime = times[1]

                move_start = time_mod.time()

                best_move = eng.get_best_move_with_time(
                    match_state["move_history"], wtime, btime, time_inc, time_inc,
                    match_state["board"], match_state["ep_target"], match_state["castling"]
                )

                elapsed = int((time_mod.time() - move_start) * 1000)

                if not best_move or len(best_move) < 4 or best_move == "0000" or best_move == "(none)":
                    winner_side = 1 - side
                    winner_name = white_name if winner_side == 0 else black_name
                    match_state["game_over"] = True
                    match_state["game_result"] = f"{eng_name} 无合法走法，{winner_name} 获胜！"
                    add_score(winner_side == 0)
                    sse_notify()
                    break

                if best_move[0:2] == best_move[2:4] and best_move != "0000":
                    winner_side = 1 - side
                    winner_name = white_name if winner_side == 0 else black_name
                    match_state["game_over"] = True
                    match_state["game_result"] = f"{eng_name} 返回非法走法 '{best_move}'（起止格相同），{winner_name} 获胜！"
                    add_score(winner_side == 0)
                    sse_notify()
                    break

                times[side] = times[side] - elapsed + time_inc
                if times[side] <= 0:
                    winner_side = 1 - side
                    winner_name = white_name if winner_side == 0 else black_name
                    match_state["game_over"] = True
                    match_state["game_result"] = f"{eng_name} 超时，{winner_name} 获胜！"
                    add_score(winner_side == 0)
                    sse_notify()
                    break

                match_state["move_history"].append(best_move)
                try:
                    new_board, new_ep, new_castling = apply_move(
                        match_state["board"], best_move,
                        match_state["ep_target"], match_state["castling"]
                    )
                    match_state["board"] = new_board
                    match_state["ep_target"] = new_ep
                    match_state["castling"] = new_castling
                except Exception:
                    winner_side = 1 - side
                    winner_name = white_name if winner_side == 0 else black_name
                    match_state["game_over"] = True
                    match_state["game_result"] = f"{eng_name} 返回非法走法 '{best_move}'，{winner_name} 获胜！"
                    add_score(winner_side == 0)
                    sse_notify()
                    break
                match_state["last_move"] = best_move
                match_state["move_count"] = move_num + 1
                match_state["engine1_time"] = times[0]
                match_state["engine2_time"] = times[1]

                pos_key = "".join("".join(row) for row in match_state["board"])
                repetition_count[pos_key] = repetition_count.get(
                    pos_key, 0) + 1
                if repetition_count[pos_key] >= 3:
                    match_state["game_over"] = True
                    match_state["game_result"] = "三次重复，和棋！"
                    match_state["score1"] += 0.5
                    match_state["score2"] += 0.5
                    sse_notify()
                    break

                sse_notify()
                time_mod.sleep(0.1)

            match_state["games_played"] = game_idx + 1
            sse_notify()

    finally:
        e1.quit()
        e2.quit()
        match_state["active"] = False
        sse_notify()


@app.route("/")
def index():
    return send_from_directory("web_static", "index.html")


@app.route("/api/state", methods=["GET"])
def get_state():
    with game.lock:
        return jsonify(game.to_dict())


@app.route("/api/move", methods=["POST"])
def make_move():
    data = request.json
    uci_move = data.get("move", "")

    with game.lock:
        if game.engine_thinking or game.game_over:
            return jsonify({"error": "无法走棋"}), 400

        current = "w" if len(game.move_history) % 2 == 0 else "b"
        if current != game.player_color:
            return jsonify({"error": "不是你的回合"}), 400

        legal = game.get_legal_moves()
        if uci_move not in legal:
            return jsonify({"error": "非法走法"}), 400

        game.make_move(uci_move)
        game.check_game_over()

        if game.game_over:
            return jsonify(game.to_dict())

        game.engine_thinking = True
        move_time = game.move_time

    def engine_think():
        best = engine.get_best_move(game.move_history, move_time)
        with game.lock:
            game.engine_thinking = False
            if best:
                game.make_move(best)
                game.check_game_over()

    t = threading.Thread(target=engine_think, daemon=True)
    t.start()

    with game.lock:
        return jsonify(game.to_dict())


@app.route("/api/new_game", methods=["POST"])
def new_game():
    data = request.json or {}
    player_color = data.get("playerColor", "w")
    move_time = data.get("moveTime", DEFAULT_MOVE_TIME)

    with game.lock:
        game.reset()
        game.player_color = player_color
        game.move_time = move_time

    engine.new_game()

    if player_color == "b":
        with game.lock:
            game.engine_thinking = True

        def engine_first():
            best = engine.get_best_move([], move_time)
            with game.lock:
                game.engine_thinking = False
                if best:
                    game.make_move(best)
                    game.check_game_over()

        t = threading.Thread(target=engine_first, daemon=True)
        t.start()

    with game.lock:
        return jsonify(game.to_dict())


@app.route("/api/undo", methods=["POST"])
def undo_move():
    with game.lock:
        if game.engine_thinking or game.game_over:
            return jsonify({"error": "无法悔棋"}), 400
        if len(game.move_history) < 2:
            return jsonify({"error": "没有可以悔棋的步"}), 400

        game.move_history.pop()
        game.move_history.pop()
        game.board = [row[:] for row in INITIAL_BOARD]
        game.ep_target = None
        game.castling = {"K": True, "Q": True, "k": True, "q": True}
        game.last_move = None
        for m in game.move_history:
            new_board, new_ep, new_castling = apply_move(
                game.board, m, game.ep_target, game.castling
            )
            game.board = new_board
            game.ep_target = new_ep
            game.castling = new_castling
        game.check_game_over()

        return jsonify(game.to_dict())


@app.route("/match")
def match_page():
    return send_from_directory("web_static", "match.html")


@app.route("/api/match/state", methods=["GET"])
def get_match_state():
    return jsonify(match_board_to_dict())


@app.route("/api/match/stream", methods=["GET"])
def match_stream():
    def generate():
        q = queue.Queue(maxsize=64)
        with _sse_lock:
            _sse_listeners.append(q)
        try:
            yield f"data: {json.dumps(match_board_to_dict(), ensure_ascii=False)}\n\n"
            while True:
                try:
                    data = q.get(timeout=30)
                    yield f"data: {data}\n\n"
                except queue.Empty:
                    yield f": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                try:
                    _sse_listeners.remove(q)
                except ValueError:
                    pass

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/engines", methods=["GET"])
def get_engines():
    result = []
    for entry in ENGINE_REGISTRY:
        result.append({
            "id": entry["id"],
            "name": entry["name"],
            "protocol": entry["protocol"],
            "options": entry.get("options", []),
        })
    return jsonify(result)


@app.route("/api/match/start", methods=["POST"])
def start_match():
    data = request.json or {}
    time_base = data.get("timeBase", 96000)
    time_inc = data.get("timeInc", 800)
    total_games = data.get("totalGames", 5)
    engine1_id = data.get("engine1Id", "chess3super")
    engine2_id = data.get("engine2Id", "hellcopter")
    velvet_elo = data.get("velvetElo", 2000)
    engine1_opts = data.get("engine1Options", {})
    engine2_opts = data.get("engine2Options", {})

    if match_state["active"]:
        return jsonify({"error": "对弈正在进行中"}), 400

    extra_opts = {}

    if engine1_id == "velvet":
        limit_e1 = data.get("velvetLimitStrength1", False)
        elo_e1 = data.get("velvetElo1", 2000)
        if limit_e1:
            extra_opts["velvet"] = {"limitStrength": True, "UCI_Elo": int(elo_e1)}
    if engine2_id == "velvet":
        limit_e2 = data.get("velvetLimitStrength2", False)
        elo_e2 = data.get("velvetElo2", 2000)
        if limit_e2:
            extra_opts["velvet"] = extra_opts.get("velvet", {})
            extra_opts["velvet"]["limitStrength"] = True
            extra_opts["velvet"]["UCI_Elo"] = int(elo_e2)

    for eid, opts in engine1_opts.items():
        if opts:
            extra_opts[eid] = extra_opts.get(eid, {})
            extra_opts[eid].update(opts)
    for eid, opts in engine2_opts.items():
        if opts:
            extra_opts[eid] = extra_opts.get(eid, {})
            extra_opts[eid].update(opts)

    e1_name = next((e["name"] for e in ENGINE_REGISTRY if e["id"] == engine1_id), engine1_id)
    e2_name = next((e["name"] for e in ENGINE_REGISTRY if e["id"] == engine2_id), engine2_id)

    match_state["active"] = True
    match_state["game_over"] = False
    match_state["game_result"] = "正在启动..."
    match_state["score1"] = 0
    match_state["score2"] = 0
    match_state["games_played"] = 0
    match_state["total_games"] = total_games
    match_state["time_base"] = time_base
    match_state["time_inc"] = time_inc

    t = threading.Thread(target=run_engine_match, args=(
        engine1_id, engine2_id, e1_name, e2_name,
        time_base, time_inc, total_games, extra_opts
    ), daemon=True)
    t.start()

    return jsonify(match_board_to_dict())


@app.route("/api/match/stop", methods=["POST"])
def stop_match():
    match_state["active"] = False
    return jsonify(match_board_to_dict())


if __name__ == "__main__":
    if not engine.start():
        print("警告: Chess3Super 引擎无法启动，人机对弈模式不可用")
        print("引擎对弈模式仍可正常使用")
    else:
        print("Chess3Super 引擎已就绪")

    os.makedirs("web_static", exist_ok=True)

    print("=" * 52)
    print("   Chess Arena - 引擎对弈竞技场")
    print("   人机对弈: http://localhost:5000")
    print("   引擎对弈: http://localhost:5000/match")
    print("-" * 52)
    print("   已注册引擎:")
    for entry in ENGINE_REGISTRY:
        p = entry["protocol"]
        proto_tag = "UCI" if p == "uci" else "XBoard" if p == "xboard" else "TSCP" if p == "tscp" else p.upper()
        print(f"     [{proto_tag:>6}] {entry['name']}")
    print("=" * 52)

    try:
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
    finally:
        engine.quit()
