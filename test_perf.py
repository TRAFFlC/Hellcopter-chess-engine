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
    def read_until(prefix, timeout=60):
        start = time.time()
        while time.time() - start < timeout:
            line = process.stdout.readline().strip()
            if line:
                print(f"  {line}")
            if line.startswith(prefix):
                return line
        return None

    send("uci")
    read_until("uciok")
    send("isready")
    read_until("readyok")

    print("=== movetime 2000 ===")
    send("position fen rnbqkb1r/pp2pppp/3p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6")
    send("go movetime 2000")
    read_until("bestmove", timeout=5)

    print("\n=== movetime 10000 ===")
    send("position fen rnbqkb1r/pp2pppp/3p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6")
    send("go movetime 10000")
    read_until("bestmove", timeout=15)

    send("quit")
    process.wait()

test()