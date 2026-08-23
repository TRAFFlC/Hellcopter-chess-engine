"""等价性验证: 放入 engine_params.json 后 vs 烘焙默认值(无 json)。

固定深度 14 起始局面搜索是确定性的: 参数相同 → 节点数完全相同。
无 json 基准: nodes=1880013 score cp 51 (dist exe @ arena/copter)
"""
import subprocess
import time

import psutil

EXE = r"E:\world\python\chess\arena\copter\Hellcopter.exe"
CWD = r"E:\world\python\chess\arena\copter"

p = subprocess.Popen([EXE], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, cwd=CWD)
proc = psutil.Process(p.pid)


def send(c):
    p.stdin.write(c + "\n")
    p.stdin.flush()


send("uci")
send("ucinewgame")
send("position startpos")
send("go depth 14")
t0 = time.time()
c0 = proc.cpu_times()
time.sleep(3.0)
c1 = proc.cpu_times()
cores = ((c1.user - c0.user) + (c1.system - c0.system)) / (time.time() - t0)
send("quit")
out, err = p.communicate(timeout=10)
info = [l for l in out.splitlines() if l.startswith("info depth")][-1]
print(f"CPU {cores:.2f} 核")
print("stderr 关键行:", [l for l in err.splitlines()
      if "config" in l.lower() or "LOADED" in l or "Threading" in l.lower()])
print(info[:110])
