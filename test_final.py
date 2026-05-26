import subprocess
import time

def test():
    engine_path = r"E:\world\python\chess\dist\Hellcopter.exe"
    process = subprocess.Popen(
        [engine_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1
    )
    def send(cmd):
        process.stdin.write(cmd + "\n")
        process.stdin.flush()

    send("uci")
    while True:
        line = process.stdout.readline().strip()
        if line == "uciok":
            break

    send("isready")
    while True:
        line = process.stdout.readline().strip()
        if line == "readyok":
            break

    print("=== 中局 movetime 5000 ===")
    send("position fen rnbqkb1r/pp2pppp/3p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6")
    send("go movetime 5000")
    start = time.time()
    while True:
        line = process.stdout.readline().strip()
        if line:
            elapsed = time.time() - start
            print(f"  [{elapsed:.1f}s] {line}")
        if line.startswith("bestmove"):
            break

    print("\n=== 残局 movetime 5000 ===")
    send("position fen 8/8/8/4k3/8/8/3K4/4Q3 w - - 0 1")
    send("go movetime 5000")
    start = time.time()
    while True:
        line = process.stdout.readline().strip()
        if line:
            elapsed = time.time() - start
            print(f"  [{elapsed:.1f}s] {line}")
        if line.startswith("bestmove"):
            break

    print("\n=== 初始局面 wtime 12000 btime 12000 ===")
    send("position startpos")
    send("go wtime 12000 btime 12000 winc 100 binc 100")
    start = time.time()
    while True:
        line = process.stdout.readline().strip()
        if line:
            elapsed = time.time() - start
            print(f"  [{elapsed:.1f}s] {line}")
        if line.startswith("bestmove"):
            break

    send("quit")
    process.wait()

test()