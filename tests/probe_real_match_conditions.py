"""模拟真实 M1 比赛条件(cutechess 不发 Threads 选项): 测引擎实际并行度。

矩阵: {arena构建, 根目录构建} x cwd=arena/copter, 均不发 setoption。
"""
import subprocess
import time

import psutil

ROOT = r"E:\world\python\chess"
COPTER_DIR = ROOT + r"\arena\copter"


def probe(label: str, exe_path: str):
    p = subprocess.Popen(
        [exe_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, cwd=COPTER_DIR,
    )
    proc = psutil.Process(p.pid)

    def send(cmd):
        p.stdin.write(cmd + "\n")
        p.stdin.flush()

    send("uci")
    send("ucinewgame")
    send("position startpos")
    send("go depth 14")

    t0 = time.time()
    c0 = proc.cpu_times()
    peak_cores = 0.0
    while time.time() - t0 < 12:
        time.sleep(1.0)
        c1 = proc.cpu_times()
        dt = time.time() - t0
        avg = ((c1.user - c0.user) + (c1.system - c0.system)) / dt
        peak_cores = max(peak_cores, avg)
        if p.poll() is not None:
            break

    send("quit")
    try:
        out, err = p.communicate(timeout=5)
    except Exception:
        p.kill()
        out, err = p.communicate()

    last_info = ""
    for line in out.splitlines():
        if line.startswith("info depth"):
            last_info = line
    verdict = "单线程" if peak_cores < 1.5 else ("~双线程" if peak_cores < 2.5 else f"⚠多线程({peak_cores:.1f}核)")
    print(f"[{label}] 峰值平均 {peak_cores:.2f} 核 → {verdict}")
    print(f"    {last_info[:110]}")
    if err.strip():
        print(f"    stderr: {err.strip().splitlines()[:3]}")


if __name__ == "__main__":
    probe("arena构建(=dist), 无setoption", COPTER_DIR + r"\Hellcopter.exe")
    probe("根目录构建, 无setoption", ROOT + r"\Hellcopter.exe")
