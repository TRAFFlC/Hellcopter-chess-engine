"""PGN 对局结果分析：盘数 / 得分率 / Elo 差 / LOS。

用法:
    py tests/analyze_pgn.py file1.pgn [file2.pgn ...]

约定: 一方名称为 "Experiment"（或通过 --name 指定），统计该方得分。
Elo 与 LOS 为逐盘二项近似 (W-L)/sqrt(2N)。
"""
import math
import re
import sys

SCORE = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}


def stats(fn, name="Experiment"):
    txt = open(fn, encoding="utf-8", errors="ignore").read()
    score = n = 0
    tc_set = set()
    for b in re.split(r"\n\n", txt):
        w = re.search(r'\[White "(.*?)"\]', b)
        bl = re.search(r'\[Black "(.*?)"\]', b)
        r = re.search(r'\[Result "(.*?)"\]', b)
        if not (w and bl and r) or r.group(1) not in SCORE:
            continue
        if w.group(1) == name:
            s = SCORE[r.group(1)]
        elif bl.group(1) == name:
            s = 1.0 - SCORE[r.group(1)]
        else:
            continue
        score += s
        n += 1
        tcm = re.search(r'\[TimeControl "(.*?)"\]', b)
        if tcm:
            tc_set.add(tcm.group(1))
    if n == 0:
        print(f"{fn}: 未找到 [{name}] 参与的对局")
        return
    pct = score / n
    elo = -400 * math.log10(1.0 / pct - 1.0) if 0 < pct < 1 else float("inf") * (1 if pct >= 1 else -1)
    wins = round(score)
    losses = n - wins
    los = 0.5 * (1 + math.erf((wins - losses) / math.sqrt(2 * n)))
    ci = 400 / math.log(10) * 1.96 * math.sqrt(pct * (1 - pct) / n)
    print(f"{fn}")
    print(f"  对手视角: {name} | {n} 局 | TC {sorted(tc_set)}")
    print(f"  得分 {score:.1f}/{n} ({pct:.1%}) | Elo {elo:+.1f} ±{ci:.0f} | LOS {los*100:.1f}%")


if __name__ == "__main__":
    name = "Experiment"
    for i, a in enumerate(sys.argv[1:]):
        if a == "--name":
            name = sys.argv[i + 2]
    args = [a for a in sys.argv[1:] if not a.startswith("-") and a != name]
    if not args:
        print(__doc__)
        sys.exit(1)
    for f in args:
        stats(f, name)
