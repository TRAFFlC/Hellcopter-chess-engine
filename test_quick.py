import subprocess
import time

def quick_test():
    engine_path = r"E:\world\python\chess\dist\Hellcopter.exe"
    
    process = subprocess.Popen(
        [engine_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
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
    
    print("\n=== 中局搜索 (movetime 5000) ===")
    send("position fen rnbqkb1r/pp2pppp/3p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6")
    send("go movetime 5000")
    read_until("bestmove", timeout=10)
    
    print("\n=== 残局搜索 (movetime 5000) ===")
    send("position fen 8/8/8/4k3/8/8/3K4/4Q3 w - - 0 1")
    send("go movetime 5000")
    read_until("bestmove", timeout=10)
    
    print("\n=== 初始局面 (wtime 12000 btime 12000) ===")
    send("position startpos")
    send("go wtime 12000 btime 12000 winc 100 binc 100")
    read_until("bestmove", timeout=15)
    
    send("quit")
    process.wait()

quick_test()