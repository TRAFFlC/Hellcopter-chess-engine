import subprocess
import time

process = subprocess.Popen(
    [r"E:\world\python\chess\dist\Hellcopter.exe"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, bufsize=1
)

def send(cmd):
    process.stdin.write(cmd + "\n")
    process.stdin.flush()

send("uci")
time.sleep(0.5)
send("position fen rnbqkb1r/pp2pppp/3p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6")
time.sleep(0.1)
send("go movetime 2000")
time.sleep(3)
send("quit")
time.sleep(0.5)

stdout, stderr = process.communicate(timeout=5)

print("=== STDOUT ===")
for line in stdout.strip().split('\n'):
    print(f"  {line}")

print("\n=== STDERR ===")
for line in stderr.strip().split('\n'):
    if 'PLY_NODES' in line or 'PARAMETERS' in line or 'Piece values' in line:
        print(f"  {line}")