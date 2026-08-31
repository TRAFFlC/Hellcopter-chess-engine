import subprocess
import sys
import time

ENGINE = r".\dist\Hellcopter.exe"

# Each test case: (name, fen, min_depth, min_score_abs, max_nodes)
# min_score_abs: at min_depth, |score| must be >= this (indicating forced win recognition)
TEST_CASES = [
    (
        "KRK edge",
        "4k3/8/8/8/8/8/4K3/7R w - - 0 1",
        8, 100000, 500000,
    ),
    (
        "KQK center",
        "8/8/8/2k5/8/8/K7/6R1 w - - 0 1",
        7, 100000, 500000,
    ),
    (
        "KBNK correct corner",
        "8/8/8/4k3/8/8/1K6/1N2B3 w - - 0 1",
        10, 1, 2000000,
    ),
    (
        "KQKR scattered",
        "8/8/3k4/8/8/r7/6K1/5Q2 w - - 0 1",
        10, 1, 2000000,
    ),
    (
        "KPK convert",
        "8/4k3/8/8/8/4K3/4P3/8 w - - 0 1",
        6, 100, 300000,
    ),
    (
        "KRKB drawnish",
        "5k2/8/8/8/3b4/8/4K3/7R w - - 0 1",
        6, 50, 300000,
    ),
]

def test_convergence(exe_path, test_cases, syzygy_path="dist/syzygy"):
    results = []
    for name, fen, min_depth, min_score_abs, max_nodes in test_cases:
        print(f"\n  [{name}] {fen}")
        uci_commands = (
            f"uci\n"
            f"setoption name SyzygyPath value {syzygy_path}\n"
            f"ucinewgame\n"
            f"isready\n"
            f"position fen {fen}\n"
            f"go depth {min_depth}\n"
            f"quit\n"
        )
        start = time.time()
        proc = subprocess.run(
            [exe_path],
            input=uci_commands,
            capture_output=True,
            text=True,
            timeout=120,
        )
        elapsed = time.time() - start
        output = proc.stdout

        # Parse last line before quit — "bestmove XXX"
        # Find all "info depth N score ..." lines
        lines = output.splitlines()
        bestmove = None
        depth_reached = 0
        final_score = None
        final_nodes = 0
        final_pv = ""

        for line in lines:
            if line.startswith("bestmove"):
                bestmove = line.strip()
            if line.startswith("info depth"):
                parts = line.split()
                try:
                    idx = parts.index("depth")
                    d = int(parts[idx + 1])
                    if d > depth_reached:
                        depth_reached = d
                except (ValueError, IndexError):
                    pass
                try:
                    idx = parts.index("score")
                    score_str = parts[idx + 1]
                    if score_str == "mate":
                        score_val = 900000  # mate is always good
                    else:
                        score_val = int(parts[idx + 2])
                    if d >= min_depth and (final_score is None or d >= depth_reached):
                        final_score = score_val
                except (ValueError, IndexError):
                    pass
                try:
                    idx = parts.index("nodes")
                    n = int(parts[idx + 1])
                    final_nodes = n
                except (ValueError, IndexError):
                    pass
                try:
                    idx = parts.index("pv")
                    final_pv = " ".join(parts[idx + 1:])
                except (ValueError, IndexError):
                    pass

        passed = False
        if final_score is not None:
            score_abs = abs(final_score)
            if score_abs >= min_score_abs and depth_reached >= min_depth:
                passed = True
            # mate = auto pass
            if "mate" in str(final_score):
                passed = True

        results.append({
            "name": name,
            "fen": fen,
            "passed": passed,
            "depth": depth_reached,
            "best_score": final_score,
            "nodes": final_nodes,
            "pv": final_pv,
            "time": f"{elapsed:.1f}s",
        })

        status = "PASS" if passed else "FAIL"
        print(f"    depth={depth_reached} score={final_score} nodes={final_nodes} pv={final_pv[:50]} [{status}] [{elapsed:.1f}s]")

    print("\n=== Summary ===")
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    print(f"  {passed}/{total} passed")
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"  [{status}] {r['name']:20s} depth={r['depth']:2d} score={str(r['best_score']):>8s}")
    return passed == total


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", default=ENGINE)
    parser.add_argument("--syzygy", default="dist/syzygy")
    args = parser.parse_args()

    ok = test_convergence(args.exe, TEST_CASES, args.syzygy)
    sys.exit(0 if ok else 1)
