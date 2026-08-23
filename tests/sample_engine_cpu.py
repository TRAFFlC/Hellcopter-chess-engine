"""采样运行中引擎进程的 CPU 占用（占单核百分比），判断实际并行度。"""
import time

import psutil


def sample(interval=2.0):
    procs = {}
    for p in psutil.process_iter(["name"]):
        try:
            n = (p.info["name"] or "").lower()
            if n.startswith(("hellcopter", "monarch")):
                procs[p.pid] = p
        except Exception:
            pass
    if not procs:
        print("未找到引擎进程")
        return
    t0 = time.time()
    snap = {pid: p.cpu_times() for pid, p in procs.items()}
    time.sleep(interval)
    dt = time.time() - t0
    ncpu = psutil.cpu_count(logical=True)
    print(f"逻辑核数 {ncpu}, 采样间隔 {dt:.1f}s")
    for pid, p in sorted(procs.items()):
        try:
            c = p.cpu_times()
            d = (c.user - snap[pid].user) + (c.system - snap[pid].system)
            pct = d / dt * 100
            name = p.name()
            mark = "≈单线程" if pct < 150 else ("双线程?" if pct < 250 else "⚠多线程")
            print(f"  PID {pid} [{name}]: {pct:.0f}% 单核 → {mark}")
        except Exception as e:
            print(f"  PID {pid}: 采样失败 {e}")


if __name__ == "__main__":
    sample()
