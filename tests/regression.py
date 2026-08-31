"""Tier 0 固定回归测试 — 每次改动后必须通过后再上对弈。"""

import subprocess
import sys
import os

from engine_wrapper import perft as engine_perft
from engine_wrapper import search, reset_search_profile, init


def test_perft() -> bool:
    d = 5
    expected = {4: 197281, 5: 4865609, 6: 119060324}
    print(f"  [perft] startpos, depth {d} (expected {expected[d]:,})...", end=" ")
    result = engine_perft("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", d)
    if result == expected[d]:
        print(f"PASS ({result:,})")
        return True
    print(f"FAIL (got {result:,})")
    return False


def test_tactical_depth(fen: str, depth: int, label: str) -> bool:
    print(f"  [tactical] {label} depth {depth}...", end=" ")
    reset_search_profile()
    move, nodes = search(fen, time_limit=30.0, max_depth=depth)
    if move:
        print(f"PASS ({move}, {nodes:,} nodes)")
        return True
    print("FAIL (no move)")
    return False


def test_uci_protocol() -> bool:
    print("  [uci] protocol handshake...", end=" ")
    p = subprocess.run(
        "Hellcopter.exe",
        input="uci\nucinewgame\nisready\nquit\n",
        capture_output=True, text=True, timeout=10,
    )
    out = p.stdout + p.stderr
    has_id = "id name" in out
    has_uciok = "uciok" in out
    has_readyok = "readyok" in out
    if has_id and has_uciok and has_readyok:
        print("PASS")
        return True
    print(f"FAIL (missing id/uciok/readyok)")
    return False


def main():
    if not os.path.isfile("Hellcopter.exe"):
        print("Error: Hellcopter.exe not found.")
        sys.exit(1)

    if not init():
        print("Error: engine DLL init failed.")
        sys.exit(1)

    print(f"\n=== Tier 0 Regression Suite ===")
    print(f"Engine: Hellcopter.exe ({os.path.getsize('Hellcopter.exe')} bytes)\n")

    tests = [
        ("Perft startpos depth 5", test_perft),
        ("Tactical KiwiPete depth 12",
         lambda: test_tactical_depth(
             "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq -",
             12, "KiwiPete")),
        ("Tactical endgame depth 12",
         lambda: test_tactical_depth(
             "8/5p2/8/2k3P1/p3P3/2K5/1P6/8 b - - - -",
             12, "endgame")),
        ("UCI protocol", test_uci_protocol),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            ok = fn()
        except Exception as e:
            print(f"  {name}: EXCEPTION {e}")
            ok = False
        if ok:
            passed += 1
        else:
            failed += 1

    print(f"\n=== Results: {passed}/{len(tests)} passed, {failed} failed ===")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
