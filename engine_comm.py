import os
import sys
import subprocess
import threading
import queue
import time


class Engine:
    def __init__(self, engine_path, engine_args=None, protocol="auto",
                 init_options=None, init_env=None):
        self.engine_path = engine_path
        self.engine_args = engine_args or []
        self.process = None
        self.lock = threading.Lock()
        self.protocol = protocol
        self.init_options = init_options or {}
        self.init_env = init_env
        self.xboard_features = {}
        self._line_queue = queue.Queue()
        self._reader_alive = False
        self._pondering = False
        self._ponder_move = None
        self._searching = False
        self.syzygy_path = None

    def start(self):
        tag = os.path.basename(self.engine_path)
        print(f"[ENGINE-DBG] {tag} start: path={self.engine_path}, protocol={self.protocol}")
        try:
            cmd = [self.engine_path] + self.engine_args
            env = self.init_env if self.init_env else None
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                env=env,
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

        if self.process and self.process.poll() is not None:
            print(f"[ENGINE] {self.engine_path} died immediately after start, exit code: {self.process.returncode}")
            return False

        if self.syzygy_path and self.protocol == "uci":
            self.set_option("SyzygyPath", self.syzygy_path)
            self.send("isready")
            self._read_until("readyok", timeout=5)

        return True

    def _start_reader(self):
        self._reader_alive = True

        def reader():
            import ctypes
            import msvcrt
            fd = self.process.stdout.fileno()
            # Get Windows HANDLE from file descriptor
            handle = msvcrt.get_osfhandle(fd) if sys.platform == "win32" else None
            buf = b""
            while self._reader_alive:
                try:
                    if sys.platform == "win32" and handle is not None:
                        # Use PeekNamedPipe to check available bytes without blocking
                        avail = ctypes.c_ulong(0)
                        ok = ctypes.windll.kernel32.PeekNamedPipe(
                            handle, None, 0, None,
                            ctypes.byref(avail), None
                        )
                        if ok and avail.value > 0:
                            chunk = os.read(fd, min(avail.value, 4096))
                            if not chunk:
                                break
                            buf += chunk
                            while b"\n" in buf:
                                line, buf = buf.split(b"\n", 1)
                                decoded = line.decode("utf-8", errors="replace").rstrip("\r")
                                if decoded:
                                    self._line_queue.put(decoded)
                        else:
                            # No data available, sleep briefly to yield GIL
                            time.sleep(0.01)
                    else:
                        # Non-Windows: use os.read which properly releases GIL
                        chunk = os.read(fd, 4096)
                        if not chunk:
                            break
                        buf += chunk
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            decoded = line.decode("utf-8", errors="replace").rstrip("\r")
                            if decoded:
                                self._line_queue.put(decoded)
                except OSError:
                    break
                except Exception:
                    break
            # Flush remaining buffer
            if buf:
                decoded = buf.decode("utf-8", errors="replace").rstrip("\r")
                if decoded:
                    self._line_queue.put(decoded)

        t = threading.Thread(target=reader, daemon=True)
        t.start()

    def _stop_reader(self):
        self._reader_alive = False

    def _detect_protocol(self):
        self.process.stdin.write(b"uci\n")
        self.process.stdin.flush()

        time.sleep(0.3)

        lines = []
        while not self._line_queue.empty():
            try:
                lines.append(self._line_queue.get_nowait())
            except queue.Empty:
                break

        for line in lines:
            if "uciok" in line or "id name" in line or "option name" in line:
                self.protocol = "uci"
                while True:
                    try:
                        self._line_queue.get_nowait()
                    except queue.Empty:
                        break
                return

        self.process.stdin.write(b"xboard\n")
        self.process.stdin.flush()
        time.sleep(0.3)

        while not self._line_queue.empty():
            try:
                lines.append(self._line_queue.get_nowait())
            except queue.Empty:
                break

        for line in lines:
            if line.startswith("feature"):
                self._parse_xboard_feature(line)
                self.protocol = "xboard"
                while True:
                    try:
                        self._line_queue.get_nowait()
                    except queue.Empty:
                        break
                return

        for line in lines:
            if "Illegal" in line or "Error" in line or "move" in line:
                self.protocol = "tscp"
                while True:
                    try:
                        self._line_queue.get_nowait()
                    except queue.Empty:
                        break
                return

        self.protocol = "tscp"
        while True:
            try:
                self._line_queue.get_nowait()
            except queue.Empty:
                break

    def _parse_xboard_feature(self, line):
        parts = line.split()
        for part in parts[1:]:
            if "=" in part:
                key, value = part.split("=", 1)
                self.xboard_features[key] = value.strip('"')

    def _init_uci(self):
        tag = os.path.basename(self.engine_path)
        print(f"[ENGINE-DBG] {tag} _init_uci: send uci")
        self.process.stdin.write(b"uci\n")
        self.process.stdin.flush()
        lines = self._read_until("uciok", timeout=5)
        print(f"[ENGINE-DBG] {tag} _init_uci: uciok received, extra_lines={len(lines)-1 if lines else 0}")

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
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.readline(timeout=1.0)
            if line is not None and token in line:
                return line
        return None

    def _parse_bestmove(self, line):
        if not line or not line.startswith("bestmove"):
            return None, None
        parts = line.split()
        if len(parts) < 2:
            return None, None
        best_move = parts[1]
        ponder_move = None
        if len(parts) >= 4 and parts[2] == "ponder":
            ponder_move = parts[3]
        return best_move, ponder_move

    def get_best_move(self, move_history, move_time):
        if self.protocol == "uci":
            # 只刷新 info 行，保留 bestmove/readyok 等关键行
            temp = []
            while not self._line_queue.empty():
                try:
                    line = self._line_queue.get_nowait()
                    if line.startswith("bestmove") or line.startswith("readyok"):
                        temp.append(line)
                    # 丢弃 info 等无关行
                except queue.Empty:
                    break
            for line in temp:
                self._line_queue.put(line)

            self.send("position startpos moves " + " ".join(move_history))
            self.send(f"go movetime {move_time}")
            self._searching = True
            while True:
                line = self.readline(timeout=30)
                if line is None:
                    self._searching = False
                    return None
                if line.startswith("bestmove"):
                    best, ponder = self._parse_bestmove(line)
                    self._searching = False
                    return best
        elif self.protocol == "xboard":
            return self._xboard_get_move(move_time)
        elif self.protocol == "tscp":
            return self._tscp_get_move(move_history)
        return None

    def is_alive(self):
        if self.process is None:
            return False
        return self.process.poll() is None

    def get_best_move_with_time(self, move_history, wtime, btime, winc, binc,
                                board=None, ep_target=None, castling=None):
        self._pondering = False
        self._ponder_move = None
        tag = os.path.basename(self.engine_path)
        if self.protocol == "uci":
            # 清空队列中的残留行，但记录丢弃了什么
            drained = 0
            while not self._line_queue.empty():
                try:
                    stale = self._line_queue.get_nowait()
                    drained += 1
                    if stale.startswith("bestmove"):
                        print(f"[ENGINE-DBG] {tag} get_best_move_with_time: DRAINING STALE bestmove: {stale[:80]}")
                except: break
            if drained:
                print(f"[ENGINE-DBG] {tag} get_best_move_with_time: drained {drained} stale lines before go")
            # 短暂等待确保 reader 线程处理完残留数据
            time.sleep(0.02)
            # 二次清空
            while not self._line_queue.empty():
                try:
                    stale = self._line_queue.get_nowait()
                    if stale.startswith("bestmove"):
                        print(f"[ENGINE-DBG] {tag} get_best_move_with_time: DRAINING STALE bestmove (2nd): {stale[:80]}")
                except: break
            alive_before = self.is_alive()
            pos_cmd = "position startpos moves " + " ".join(move_history)
            go_cmd = f"go wtime {wtime} btime {btime} winc {winc} binc {binc}"
            print(f"[ENGINE-DBG] {tag} alive={alive_before} send: {pos_cmd}")
            self.send(pos_cmd)
            print(f"[ENGINE-DBG] {tag} send: {go_cmd}")
            self.send(go_cmd)
            self._searching = True
            deadline = time.time() + 60
            loop_count = 0
            while True:
                loop_count += 1
                alive = self.is_alive()
                if not alive:
                    rc = self.process.returncode if self.process else "?"
                    print(f"[ENGINE-DBG] {tag} DIED at loop {loop_count}, exit={rc}")
                    self._searching = False
                    return None
                line = self.readline(timeout=3)
                if line is not None:
                    print(f"[ENGINE-DBG] {tag} recv: {line[:80]}")
                    if line.startswith("bestmove"):
                        best, ponder = self._parse_bestmove(line)
                        self._ponder_move = ponder
                        self._searching = False
                        return best
                if time.time() >= deadline:
                    print(f"[ENGINE-DBG] {tag} TIMEOUT at loop {loop_count}, alive={alive}")
                    self._searching = False
                    return None
        elif self.protocol == "xboard":
            return self._xboard_get_move_fixed(wtime, btime, winc, binc)
        elif self.protocol == "tscp":
            return self._tscp_get_move(move_history)
        print(f"[ENGINE-DBG] {tag} FALLTHROUGH protocol={self.protocol}")
        return None

    def start_ponder(self, move_history, wtime, btime, winc, binc, ponder_move=None):
        if self.protocol != "uci":
            return
        self._pondering = True
        pos_cmd = "position startpos moves " + " ".join(move_history)
        # UCI ponder: 必须将 ponder 着法加入 position，这样引擎搜索的是
        # 对手走了 ponder 着法后的局面，ponderhit 时返回的是我方最佳着法
        if ponder_move:
            pos_cmd += " " + ponder_move
        self.send(pos_cmd)
        self.send(f"go ponder wtime {wtime} btime {btime} winc {winc} binc {binc}")

    def send_ponderhit(self):
        if self.protocol != "uci":
            return
        self._pondering = False
        self.send("ponderhit")

    def stop_ponder(self):
        if self.protocol != "uci":
            return
        tag = os.path.basename(self.engine_path)
        self.send("stop")
        # 消费引擎返回的 bestmove 响应，避免残留行污染后续搜索
        # 超时设为6秒，匹配C版wait_for_search_thread的3秒+余量
        deadline = time.time() + 6
        bestmove_consumed = False
        while time.time() < deadline:
            line = self.readline(timeout=1.0)
            if line is not None:
                print(f"[ENGINE-DBG] {tag} stop_ponder recv: {line[:80]}")
                if line.startswith("bestmove"):
                    bestmove_consumed = True
                    break
            else:
                print(f"[ENGINE-DBG] {tag} stop_ponder: no data, waiting...")
        if not bestmove_consumed:
            print(f"[ENGINE-DBG] {tag} stop_ponder: WARNING - no bestmove received within 6s")
        # 额外清空队列中可能残留的行（防止竞态条件）
        time.sleep(0.05)
        drained = 0
        while not self._line_queue.empty():
            try:
                stale = self._line_queue.get_nowait()
                drained += 1
                print(f"[ENGINE-DBG] {tag} stop_ponder drain: {stale[:80]}")
            except queue.Empty:
                break
        if drained:
            print(f"[ENGINE-DBG] {tag} stop_ponder: drained {drained} stale lines")
        self._pondering = False
        self._ponder_move = None

    def wait_for_bestmove_ponder(self, timeout=60):
        if self.protocol != "uci":
            return None, None
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.is_alive():
                self._pondering = False
                return None, None
            line = self.readline(timeout=min(3.0, deadline - time.time() + 0.1))
            if line is None:
                continue
            if line.startswith("bestmove"):
                best, ponder = self._parse_bestmove(line)
                self._pondering = False
                return best, ponder
        self._pondering = False
        return None, None

    def is_pondering(self):
        return self._pondering

    def get_ponder_move(self):
        return self._ponder_move

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
        tag = os.path.basename(self.engine_path)
        self._pondering = False
        self._ponder_move = None
        if self.protocol == "uci":
            t0 = time.time()
            # 只在引擎正在搜索时才发送 stop 并等待 bestmove
            if self._searching:
                print(f"[ENGINE-DBG] {tag} new_game: searching, sending stop")
                self.send("stop")
                deadline = time.time() + 2
                while time.time() < deadline:
                    line = self.readline(timeout=0.5)
                    if line is not None and line.startswith("bestmove"):
                        break
                self._searching = False
                print(f"[ENGINE-DBG] {tag} new_game: stop done, {time.time()-t0:.3f}s")
            # 刷新残留输出
            while not self._line_queue.empty():
                try:
                    self._line_queue.get_nowait()
                except queue.Empty:
                    break
            print(f"[ENGINE-DBG] {tag} new_game: queue flushed, {time.time()-t0:.3f}s")
            self.send("ucinewgame")
            self.send("isready")
            print(f"[ENGINE-DBG] {tag} new_game: sent ucinewgame+isready, {time.time()-t0:.3f}s")
            lines = self._read_until("readyok", timeout=5)
            print(f"[ENGINE-DBG] {tag} new_game: readyok received, total={time.time()-t0:.3f}s, extra_lines={len(lines)-1 if lines else 0}")
            while not self._line_queue.empty():
                try: self._line_queue.get_nowait()
                except: break
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
