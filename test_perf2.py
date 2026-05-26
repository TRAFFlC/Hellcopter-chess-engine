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
    def read_lines(timeout=60):
        import select
        import msvcrt
        import os
        lines = []
        start = time.time()
        while time.time() - start < timeout:
            line = process.stdout.readline().strip()
            if line:
                print(f"  {line}")
                lines.append(line)
                if line.startswith("bestmove"):
                    # read a few more lines
                    for _ in range(5):
                        extra = process.stdout.readline().strip()
                        if extra:
                            print(f"  {extra}")
                            lines.append(extra)
                    return lines
        return lines

    send("uci")
    read_lines()
    send("isready")
    read_lines()

    print("\n=== movetime 2000 ===")
    send("position fen rnbqkb1r/pp2pppp/3p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6")
    send("go movetime 2000")
    read_lines(timeout=5)

    send("quit")
    process.wait()

test()