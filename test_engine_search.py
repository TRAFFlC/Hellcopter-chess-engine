import subprocess
import time
import sys

def test_engine_search():
    engine_path = r"E:\world\python\chess\dist\Hellcopter.exe"
    
    print("测试 Hellcopter 引擎搜索能力")
    print("=" * 60)
    
    process = subprocess.Popen(
        [engine_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    
    def send_command(cmd):
        process.stdin.write(cmd + "\n")
        process.stdin.flush()
    
    def read_until(prefix, timeout=30):
        start = time.time()
        lines = []
        while time.time() - start < timeout:
            line = process.stdout.readline().strip()
            if line:
                lines.append(line)
                print(f"  引擎: {line}")
            if line.startswith(prefix):
                return line, lines
        return None, lines
    
    send_command("uci")
    read_until("uciok")
    
    send_command("isready")
    read_until("readyok")
    
    print("\n测试1: 初始局面 depth 12")
    print("-" * 40)
    send_command("position startpos")
    send_command("go depth 12")
    bestmove, lines = read_until("bestmove", timeout=30)
    
    print("\n测试2: 中局 depth 12")
    print("-" * 40)
    fen = "rnbqkb1r/pp2pppp/3p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6"
    send_command(f"position fen {fen}")
    send_command("go depth 12")
    bestmove, lines = read_until("bestmove", timeout=30)
    
    print("\n测试3: movetime 5000")
    print("-" * 40)
    send_command("position startpos")
    send_command("go movetime 5000")
    bestmove, lines = read_until("bestmove", timeout=10)
    
    print("\n测试4: wtime/btime 12000+100")
    print("-" * 40)
    send_command("position startpos")
    send_command("go wtime 12000 btime 12000 winc 100 binc 100")
    bestmove, lines = read_until("bestmove", timeout=15)
    
    send_command("quit")
    process.wait()
    
    print("\n" + "=" * 60)
    print("测试完成")

if __name__ == "__main__":
    test_engine_search()