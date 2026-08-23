"""验证 setoption Threads 是否真正生效：对比深度-时间曲线。

原理: 单线程与4线程在同一节点数下耗时不同——若 Threads=1 与 Threads=4
的 nodes/time 曲线一致, 说明选项无效; 若 Threads=1 明显更慢, 说明生效。
"""
import subprocess
import time

EXE = r"E:\world\python\chess\arena\copter\Hellcopter.exe"


def probe(threads: int, movetime_ms: int = 3000):
    p = subprocess.Popen(
        [EXE], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, cwd=r"E:\world\python\chess\arena\copter",
    )

    def send(cmd):
        p.stdin.write(cmd + "\n")
        p.stdin.flush()

    send("uci")
    send(f"setoption name Threads value {threads}")
    send("ucinewgame")
    send("position startpos")
    send(f"go movetime {movetime_ms}")
    time.sleep(movetime_ms / 1000 + 0.5)
    send("quit")
    try:
        out, _ = p.communicate(timeout=5)
    except Exception:
        p.kill()
        out, _ = p.communicate()

    # 取最后一条 info 行（搜索结束时的累计值）
    last_info = ""
    for line in out.splitlines():
        if line.startswith("info depth"):
            last_info = line
    print(f"Threads={threads}: {last_info}")


if __name__ == "__main__":
    for th in (1, 4, 1, 4):
        probe(th)
