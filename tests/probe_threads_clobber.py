"""端到端验证: setoption Threads 是否被首次搜索时的参数懒加载覆盖。

场景 A: cwd=仓库根（engine_params.json 存在, threading.num_threads=4）
场景 B: cwd=arena/copter（无 JSON → 编译期默认 NUM_THREADS=4）

每个场景: setoption Threads value 1 后立即 go depth 14,
采样搜索期间进程的 CPU 时间 → 判断实际并行度。
若 ≈100% 单核 = 单线程生效; 若 ≈400% = 覆盖发生(仍是4线程)。
"""
import subprocess
import sys
import time

import psutil

ROOT = r"E:\world\python\chess"
EXE = r"arena\copter\Hellcopter.exe"


def probe(label: str, cwd: str, threads_opt: int):
    p = subprocess.Popen(
        [EXE], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, cwd=cwd,
    )
    proc = psutil.Process(p.pid)

    def send(cmd):
        p.stdin.write(cmd + "\n")
        p.stdin.flush()

    send("uci")
    send(f"setoption name Threads value {threads_opt}")
    send("ucinewgame")
    send("position startpos")
    send("go depth 14")

    t0 = time.time()
    c0 = proc.cpu_times()
    time.sleep(3.0)
    c1 = proc.cpu_times()
    dt = time.time() - t0
    used_cores = ((c1.user - c0.user) + (c1.system - c0.system)) / dt

    send("quit")
    try:
        out, err = p.communicate(timeout=10)
    except Exception:
        p.kill()
        out, err = p.communicate()

    last_info = ""
    for line in out.splitlines():
        if line.startswith("info depth"):
            last_info = line
    threads_msg = [ln for ln in err.splitlines() if "Threads" in ln]
    verdict = "单线程" if used_cores < 1.5 else ("双线程?" if used_cores < 2.5 else f"多线程({used_cores:.1f}核)")
    print(f"[{label}] Threads={threads_opt}: 实际 {used_cores:.2f} 核 → {verdict}")
    print(f"    stderr: {threads_msg or '(无 Threads 消息)'}")
    print(f"    {last_info[:120]}")


if __name__ == "__main__":
    print("=== 场景 A: cwd=根目录(JSON num_threads=4 存在) ===")
    probe("A", ROOT, 1)
    print("=== 场景 B: cwd=arena/copter(无 JSON) ===")
    probe("B", EXE.rsplit("\\", 1)[0], 1)
