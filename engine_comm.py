import os
import sys
import subprocess
import threading
import queue


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
        except Exception as e:
            print(f"Engine start error: {e}")
            return False

        self._start_reader()

        if self.protocol == "auto":
            self._detect_protocol()

        if self.protocol == "uci":
            self._init_uci()
        elif self.protocol == "xboard":
            self._init_xboard()
        elif self.protocol == "tscp":
            self._init_tscp()

        return True

    def _start_reader(self):
        self._reader_alive = True

        def reader():
            while self._reader_alive:
                try:
                    line = self.process.stdout.readline()
                    if not line:
                        break
                    line = line.decode("utf-8", errors="replace").rstrip()
                    self._line_queue.put(line)
                except Exception:
                    break

        t = threading.Thread(target=reader, daemon=True)
        t.start()

    def _stop_reader(self):
        self._reader_alive = False

    def _detect_protocol(self):
        self.process.stdin.write(b"xboard\n")
        self.process.stdin.flush()

        import time
        time.sleep(0.3)

        lines = []
        while not self._line_queue.empty():
            try:
                lines.append(self._line_queue.get_nowait())
            except queue.Empty:
                break

        for line in lines:
            if line.startswith("feature"):
                self._parse_xboard_feature(line)
                self.protocol = "xboard"
                self._line_queue.queue.clear()
                return

        self.process.stdin.write(b"uci\n")
        self.process.stdin.flush()
        time.sleep(0.3)

        while not self._line_queue.empty():
            try:
                lines.append(self._line_queue.get_nowait())
            except queue.Empty:
                break

        for line in lines:
            if "uciok" in line or "id name" in line or "option name" in line:
                self.protocol = "uci"
                self._line_queue.queue.clear()
                return

        for line in lines:
            if "Illegal" in line or "Error" in line or "move" in line:
                self.protocol = "tscp"
                self._line_queue.queue.clear()
                return

        self.protocol = "tscp"
        self._line_queue.queue.clear()

    def _parse_xboard_feature(self, line):
        parts = line.split()
        for part in parts[1:]:
            if "=" in part:
                key, value = part.split("=", 1)
                self.xboard_features[key] = value.strip('"')

    def _init_uci(self):
        self.process.stdin.write(b"uci\n")
        self.process.stdin.flush()
        self._read_until("uciok", timeout=5)

    def _init_xboard(self):
        self.process.stdin.write(b"xboard\n")
        self.process.stdin.flush()
        self.process.stdin.write(b"protover 2\n")
        self.process.stdin.flush()
        self._read_until("done=1", timeout=5)

    def _init_tscp(self):
        pass

    def set_option(self, name, value):
        if self.protocol == "uci":
            cmd = f"setoption name {name} value {value}\n"
            self.process.stdin.write(cmd.encode())
            self.process.stdin.flush()

    def send(self, cmd):
        self.process.stdin.write((cmd + "\n").encode())
        self.process.stdin.flush()

    def readline(self, timeout=5.0):
        try:
            return self._line_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _read_until(self, token, timeout=5):
        import time
        deadline = time.time() + timeout
        lines = []
        while time.time() < deadline:
            line = self.readline(timeout=0.5)
            if line is not None:
                lines.append(line)
                if token in line:
                    return lines
        return lines

    def wait_for(self, token, timeout=60):
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.readline(timeout=1.0)
            if line is not None and token in line:
                return line
        return None

    def get_best_move(self, move_history, move_time):
        if self.protocol == "uci":
            self.send("position startpos moves " + " ".join(move_history))
            self.send(f"go movetime {move_time}")
            while True:
                line = self.readline(timeout=30)
                if line is None:
                    return None
                if line.startswith("bestmove"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return parts[1]
                    return None
        elif self.protocol == "xboard":
            return self._xboard_get_move(move_time)
        elif self.protocol == "tscp":
            return self._tscp_get_move(move_history)
        return None

    def get_best_move_with_time(self, move_history, wtime, btime, winc, binc,
                                board=None, ep_target=None, castling=None):
        if self.protocol == "uci":
            self.send("position startpos moves " + " ".join(move_history))
            self.send(f"go wtime {wtime} btime {btime} winc {winc} binc {binc}")
            while True:
                line = self.readline(timeout=120)
                if line is None:
                    return None
                if line.startswith("bestmove"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return parts[1]
                    return None
        elif self.protocol == "xboard":
            return self._xboard_get_move_fixed(wtime, btime, winc, binc)
        elif self.protocol == "tscp":
            return self._tscp_get_move(move_history)
        return None

    def _xboard_get_move(self, move_time):
        self.send(f"go {move_time // 10}")
        while True:
            line = self.readline(timeout=30)
            if line is None:
                return None
            if line.startswith("move "):
                return line.split()[1]

    def _xboard_get_move_fixed(self, wtime, btime, winc, binc):
        self.send(f"time {wtime // 10}")
        self.send(f"otim {btime // 10}")
        self.send("go")
        while True:
            line = self.readline(timeout=120)
            if line is None:
                return None
            if line.startswith("move "):
                return line.split()[1]

    def _tscp_get_move(self, move_history):
        from chess_logic import board_to_fen, apply_move, INITIAL_BOARD
        board = [row[:] for row in INITIAL_BOARD]
        ep_target = None
        castling = {"K": True, "Q": True, "k": True, "q": True}
        for move in move_history:
            board, ep_target, castling = apply_move(board, move, ep_target, castling)
        side = "w" if len(move_history) % 2 == 0 else "b"
        fen = board_to_fen(board, side, castling, ep_target)
        self.send(f"fen {fen}")
        while True:
            line = self.readline(timeout=30)
            if line is None:
                return None
            stripped = line.strip()
            if len(stripped) == 4 and stripped[0] in "abcdefgh" and stripped[2] in "abcdefgh":
                return stripped

    def new_game(self):
        if self.protocol == "uci":
            self.send("ucinewgame")
            self.send("isready")
            self._read_until("readyok", timeout=5)
        elif self.protocol == "xboard":
            self.send("new")

    def quit(self):
        try:
            if self.process and self.process.poll() is None:
                if self.protocol == "uci":
                    self.send("quit")
                elif self.protocol == "xboard":
                    self.send("quit")
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                self._stop_reader()
        except Exception:
            pass
