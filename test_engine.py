import subprocess
import time
import sys

def test_engine():
    engine_path = r"E:\world\python\chess\dist\Hellcopter.exe"
    
    print("测试 Hellcopter 引擎性能...")
    print("=" * 50)
    
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
    
    def read_until(prefix, timeout=10):
        start = time.time()
        while time.time() - start < timeout:
            line = process.stdout.readline().strip()
            if line:
                print(f"引擎输出: {line}")
            if line.startswith(prefix):
                return line
        return None
    
    send_command("uci")
    uciok = read_until("uciok")
    if not uciok:
        print("错误: 引擎未响应uci命令")
        return
    
    send_command("isready")
    readyok = read_until("readyok")
    if not readyok:
        print("错误: 引擎未就绪")
        return
    
    print("\n测试1: 初始局面深度搜索")
    print("-" * 30)
    send_command("position startpos")
    send_command("go depth 10")
    bestmove = read_until("bestmove", timeout=30)
    if bestmove:
        print(f"引擎选择: {bestmove}")
    else:
        print("错误: 搜索超时或无响应")
    
    print("\n测试2: 中局局面搜索")
    print("-" * 30)
    send_command("position startpos moves e2e4 e7e5 g1f3 b8c6 f1b5 a7a6")
    send_command("go depth 10")
    bestmove = read_until("bestmove", timeout=30)
    if bestmove:
        print(f"引擎选择: {bestmove}")
    else:
        print("错误: 搜索超时或无响应")
    
    print("\n测试3: 时间控制测试 (5秒)")
    print("-" * 30)
    send_command("position startpos")
    send_command("go movetime 5000")
    start_time = time.time()
    bestmove = read_until("bestmove", timeout=10)
    elapsed = time.time() - start_time
    if bestmove:
        print(f"引擎选择: {bestmove}")
        print(f"实际用时: {elapsed:.2f}秒")
        if elapsed > 6:
            print("警告: 引擎超时使用!")
    else:
        print("错误: 搜索超时或无响应")
    
    print("\n测试4: 快速对弈测试 (1秒/步)")
    print("-" * 30)
    send_command("ucinewgame")
    send_command("isready")
    read_until("readyok")
    
    board_cmds = ["position startpos"]
    moves = []
    
    for i in range(10):
        cmd = f"position startpos moves {' '.join(moves)}" if moves else "position startpos"
        send_command(cmd)
        send_command("go movetime 1000")
        
        bestmove_line = read_until("bestmove", timeout=5)
        if bestmove_line:
            move = bestmove_line.split()[1]
            if move == "0000":
                print(f"第{i+1}步: 引擎无法找到走法")
                break
            moves.append(move)
            print(f"第{i+1}步: {move}")
        else:
            print(f"第{i+1}步: 超时")
            break
    
    print(f"\n对弈记录: {' '.join(moves)}")
    
    send_command("quit")
    process.wait()
    
    print("\n" + "=" * 50)
    print("测试完成")

if __name__ == "__main__":
    test_engine()