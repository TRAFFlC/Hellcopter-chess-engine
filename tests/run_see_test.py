"""
SEE fix A/B test
Baseline (A): SEE pruning OFF
Experiment (B): SEE pruning ON (with fixed thresholds = depth<=3, legal_count>=2, i>=2, scale=300)

Runs 8 parallel cutechess instances x 50 rounds @ 96+0.8
"""
import sys, os, json, subprocess, threading, re, time, math

BASE = r"E:\world\python\chess"
CUTECHESS = os.path.join(BASE, r"cutechess-1.3.1-win64\cutechess-cli.exe")
PYTHON = sys.executable
RESULTS = os.path.join(BASE, "results")
CONFIG_A = os.path.join(BASE, r"configs\see_off.json")
CONFIG_B = os.path.join(BASE, r"configs\see_on.json")

sys.path.insert(0, BASE)
from match_utils import create_temp_uci_adapter_with_env

os.makedirs(RESULTS, exist_ok=True)

print("=== SEE A/B Test ===")
print("Baseline (A):  SEE pruning OFF")
print("Experiment (B): SEE pruning ON (fix applied)")
print("TC: 96+0.8, Rounds: 400 (8 x 50)")

# Create adapters
adapters_a, adapters_b, dirs_a, dirs_b = [], [], [], []
for i in range(8):
    pa, da = create_temp_uci_adapter_with_env(BASE, CONFIG_A, f"see_off_{i}")
    pb, db = create_temp_uci_adapter_with_env(BASE, CONFIG_B, f"see_on_{i}")
    adapters_a.append(pa); dirs_a.append(da)
    adapters_b.append(pb); dirs_b.append(db)

print(f"Created {len(adapters_a)} + {len(adapters_b)} adapters")

results = [None] * 8

def run_instance(i):
    pgn = os.path.join(RESULTS, f"see_test_{i+1:02d}.pgn")
    if os.path.exists(pgn):
        os.remove(pgn)
    flat = [CUTECHESS,
        "-engine",
        "name=Baseline", "proto=uci", f"cmd={PYTHON}", f"arg={adapters_a[i]}", f"dir={os.path.dirname(adapters_a[i])}",
        "-engine",
        "name=Experiment", "proto=uci", f"cmd={PYTHON}", f"arg={adapters_b[i]}", f"dir={os.path.dirname(adapters_b[i])}",
        "-each", "tc=96+0.8",
        "-rounds", "50", "-concurrency", "1",
        "-draw", "movenumber=40", "movecount=5", "score=20",
        "-resign", "movecount=3", "score=500",
        "-pgnout", pgn]
    proc = subprocess.run(flat, capture_output=True, text=True, timeout=7200)
    results[i] = proc.stdout + proc.stderr
    print(f"Instance {i+1} finished")
    return proc.stdout + proc.stderr

threads = []
start = time.time()
for i in range(8):
    t = threading.Thread(target=run_instance, args=(i,))
    t.start()
    threads.append(t)
    time.sleep(0.5)

for i, t in enumerate(threads):
    t.join()
    if results[i]:
        print(f"\n--- Instance {i+1} output (tail) ---")
        lines = results[i].strip().split("\n")
        for line in lines[-5:]:
            print(f"  {line}")

elapsed = time.time() - start
print(f"\nTotal time: {elapsed:.0f}s ({elapsed/60:.1f}m)")

# Aggregate results
b_wins, e_wins, draws = 0, 0, 0
for i in range(8):
    pgn = os.path.join(RESULTS, f"see_test_{i+1:02d}.pgn")
    if not os.path.exists(pgn):
        continue
    with open(pgn, encoding="utf-8", errors="replace") as f:
        content = f.read()
    for m in re.finditer(r'\[Result "([^"]+)"\]', content):
        r = m.group(1)
        if r == "1-0":       b_wins += 1
        elif r == "0-1":     e_wins += 1
        elif r == "1/2-1/2": draws += 1

total = b_wins + e_wins + draws
print(f"\n=== Aggregated Results ===")
print(f"Total: {total}  Baseline(SEE off): {b_wins}  Experiment(SEE on): {e_wins}  Draws: {draws}")
if total > 0:
    bs = b_wins + draws / 2.0
    es = e_wins + draws / 2.0
    print(f"Baseline: {bs}/{total} ({bs/total*100:.1f}%)")
    print(f"Experiment: {es}/{total} ({es/total*100:.1f}%)")
    if bs > 0 and es > 0:
        elo = round(400 * math.log10(es / bs), 1)
        print(f"Elo diff (Experiment vs Baseline): {elo}")
    # LOS (using binomial CDF)
    los = 0.0
    n = total - draws
    try:
        from math import comb
        for k in range(e_wins, n + 1):
            los += comb(n, k) * (0.5 ** n)
    except ImportError:
        los = -1
    print(f"LOS: {los*100:.1f}%")

# Cleanup
for d in set(dirs_a + dirs_b):
    import shutil
    try: shutil.rmtree(d)
    except: pass
