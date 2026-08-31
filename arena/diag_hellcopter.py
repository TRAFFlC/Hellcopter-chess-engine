"""
Hellcopter 96+0.8 真实行为诊断（一次性运行后保留供分析）

- 接管 Hellcopter 的 stdout + stderr（engine_comm 默认吞掉 stderr）
- 逐手记录：发出去的 UCI 命令、引擎 info 行、bestmove、wall-clock
- 把 stderr 落到 hellcopter.stderr.log（关键！C 端 assert/crash 都会在这里）
- 把 JSON 摘要落到 hellcopter.diag.json
- 跑 N 局（默认 2 局），每局后停
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime

ROOT = r"e:\world\python\chess"
sys.path.insert(0, ROOT)
import chess  # noqa: E402

UCI = os.path.join(ROOT, "uci_engine.py")
PARAMS = os.path.join(ROOT, "engine_params.json")
LOG_DIR = os.path.join(ROOT, "arena", "diag_logs")
os.makedirs(LOG_DIR, exist_ok=True)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
stderr_log_path = os.path.join(LOG_DIR, f"hellcopter_{ts}.stderr.log")
diag_path = os.path.join(LOG_DIR, f"hellcopter_{ts}.diag.json")

print(f"[diag] stderr log: {stderr_log_path}")
print(f"[diag] diag json : {diag_path}")

# 启动 Hellcopter，stderr 重定向到文件（关键！）
print("[diag] starting Hellcopter...")
env = os.environ.copy()
env["ENGINE_PARAMS"] = PARAMS
t0 = time.perf_counter()
proc = subprocess.Popen(
    [sys.executable, UCI],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=open(stderr_log_path, "wb"),
    bufsize=0,
    env=env,
    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
)
print(f"[diag] startup: {time.perf_counter()-t0:.2f}s, pid={proc.pid}")

# 启动 reader 线程
line_q: "queue.Queue[str]" = queue.Queue()
reader_alive = True


def _reader():
    import ctypes
    import msvcrt
    fd = proc.stdout.fileno()
    handle = msvcrt.get_osfhandle(fd) if sys.platform == "win32" else None
    buf = b""
    while reader_alive:
        try:
            if sys.platform == "win32" and handle is not None:
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
                        line_q.put(line.decode("utf-8", errors="replace").rstrip("\r"))
                else:
                    time.sleep(0.01)
            else:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line_q.put(line.decode("utf-8", errors="replace").rstrip("\r"))
        except OSError:
            break
        except Exception:
            break


threading.Thread(target=_reader, daemon=True).start()


def send(cmd: str):
    proc.stdin.write((cmd + "\n").encode())
    proc.stdin.flush()


def readline(timeout=1.0):
    try:
        return line_q.get(timeout=timeout)
    except queue.Empty:
        return None


def wait_for(token, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = readline(timeout=0.5)
        if line and token in line:
            return line
    return None


# 初始 UCI 握手
send("uci")
wait_for("uciok", timeout=10)
send("isready")
wait_for("readyok", timeout=15)

# 锁死选项
for name, val in [("Threads", "1"), ("Ponder", "false"),
                  ("OwnBook", "false"), ("BookPath", ""),
                  ("SyzygyPath", "")]:
    send(f"setoption name {name} value {val}")
send("isready")
wait_for("readyok", timeout=10)
print("[diag] Hellcopter ready")

# 跑 2 局
summary = {"games": [], "stderr_log": stderr_log_path}

N_GAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 2
TC_BASE_MS = 96 * 1000
TC_INC_MS = 800

for game_no in range(1, N_GAMES + 1):
    is_white = (game_no % 2 == 1)
    print(f"\n=== Game {game_no}, Hellcopter plays "
          f"{'White' if is_white else 'Black'} ===")
    # 新局
    send("stop")
    time.sleep(0.2)
    while not line_q.empty():
        try:
            line_q.get_nowait()
        except queue.Empty:
            break
    send("ucinewgame")
    send("isready")
    wait_for("readyok", timeout=15)

    board = chess.Board()
    moves: list[str] = []
    h_clk = m_clk = TC_BASE_MS
    game_diag = {"game": game_no, "plies": [], "outcome": None, "elapsed_s": 0.0}
    g_t0 = time.perf_counter()

    plies = 0
    while not board.is_game_over(claim_draw=True) and plies < 300:
        is_white_turn = board.turn == chess.WHITE
        h_to_move = (is_white_turn == is_white)

        # 清空 info 行（保留 bestmove/readyok 暂存，下面会处理）
        drained = 0
        while not line_q.empty():
            try:
                stale = line_q.get_nowait()
                drained += 1
            except queue.Empty:
                break
        if drained:
            print(f"  [drain {drained}]")

        wtime = h_clk if h_to_move == is_white else m_clk
        btime = m_clk if h_to_move == is_white else h_clk

        # 发送 position + go
        pos_cmd = "position startpos moves " + " ".join(moves)
        go_cmd = f"go wtime {wtime} btime {btime} winc {TC_INC_MS} binc {TC_INC_MS}"
        send(pos_cmd)
        send(go_cmd)
        t0 = time.perf_counter()

        # 等待 bestmove
        bestmove = None
        info_lines = []
        deadline = time.time() + 60
        last_info_t = time.time()
        while time.time() < deadline:
            line = readline(timeout=1.0)
            if line is None:
                continue
            if line.startswith("info "):
                info_lines.append(line[:160])
                last_info_t = time.time()
                continue
            if line.startswith("bestmove"):
                parts = line.split()
                bestmove = parts[1] if len(parts) >= 2 else None
                break
            if "readyok" in line:
                # 残留 readyok，忽略
                continue
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        if bestmove is None or bestmove == "0000":
            print(f"  [NO MOVE after {elapsed_ms}ms]")
            game_diag["outcome"] = "no-move"
            game_diag["plies"].append({
                "ply": plies + 1,
                "mover": "HELL" if h_to_move else "MON",
                "elapsed_ms": elapsed_ms,
                "wtime": wtime, "btime": btime,
                "info_last": info_lines[-1] if info_lines else None,
                "bestmove": bestmove,
            })
            break

        legal = chess.Move.from_uci(bestmove) in board.legal_moves
        print(f"  ply {plies+1:2d}  HELL={h_to_move}  "
              f"elapsed={elapsed_ms/1000:.2f}s  "
              f"move={bestmove}  legal={legal}  clk_before={h_clk if h_to_move else m_clk}")
        game_diag["plies"].append({
            "ply": plies + 1,
            "mover": "HELL" if h_to_move else "MON",
            "elapsed_ms": elapsed_ms,
            "wtime": wtime, "btime": btime,
            "info_count": len(info_lines),
            "info_last": info_lines[-1] if info_lines else None,
            "bestmove": bestmove,
            "legal": legal,
        })

        # 走子
        board.push(chess.Move.from_uci(bestmove))
        moves.append(bestmove)
        plies += 1
        if h_to_move:
            h_clk = max(0, h_clk - elapsed_ms + TC_INC_MS)
        else:
            m_clk = max(0, m_clk - elapsed_ms + TC_INC_MS)

    if game_diag["outcome"] is None:
        outcome = board.outcome(claim_draw=True)
        game_diag["outcome"] = outcome.result() if outcome else "1/2-1/2"
    game_diag["elapsed_s"] = time.perf_counter() - g_t0
    game_diag["final_h_clk"] = h_clk
    game_diag["final_m_clk"] = m_clk
    print(f"  [Game {game_no} outcome: {game_diag['outcome']} "
          f"in {game_diag['elapsed_s']:.1f}s]")
    summary["games"].append(game_diag)

# 落盘
with open(diag_path, "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)

# 引擎退出
try:
    send("quit")
except Exception:
    pass
time.sleep(0.3)
try:
    if proc.poll() is None:
        proc.terminate()
except Exception:
    pass
reader_alive = False

print(f"\n[diag] DONE")
print(f"  summary : {diag_path}")
print(f"  stderr  : {stderr_log_path}")
print(f"  (查看 stderr 文件看 HELL 是否抛了 C 端 assert)")
