"""M1 对局输棋初步归类：统计 Hellcopter 败局的终止方式与时长分布。"""
import re
import sys

fn = sys.argv[1] if len(sys.argv) > 1 else "arena/m1_calibration.pgn"
txt = open(fn, encoding="utf-8", errors="ignore").read()

stats = {"wins": 0, "losses": 0, "draws": 0}
loss_terms = {}
loss_plies = []

for b in re.split(r"\n\n(?=\[Event )", txt):
    w = re.search(r'\[White "(.*?)"\]', b)
    bl = re.search(r'\[Black "(.*?)"\]', b)
    r = re.search(r'\[Result "(.*?)"\]', b)
    p = re.search(r'\[PlyCount "(\d+)"\]', b)
    if not (w and bl and r):
        continue
    copter_is_white = w.group(1) == "Hellcopter"
    if copter_is_white and w.group(1) and "Hellcopter" not in bl.group(1):
        pass
    res = r.group(1)
    if res == "1/2-1/2":
        stats["draws"] += 1
        continue
    copter_won = (res == "1-0" and copter_is_white) or (res == "0-1" and not copter_is_white)
    if copter_won:
        stats["wins"] += 1
    else:
        stats["losses"] += 1
        term = re.search(r'\[Termination "(.*?)"\]', b)
        t = term.group(1) if term else "?"
        loss_terms[t] = loss_terms.get(t, 0) + 1
        if p:
            loss_plies.append(int(p.group(1)))

w, l, d = stats["wins"], stats["losses"], stats["draws"]
n = w + l + d
print(f"总盘数 {n}: 胜 {w} / 负 {l} / 和 {d} (得分率 {(w + d*0.5)/n:.1%})" if n else "无对局")
print(f"败局终止方式: {loss_terms}")
if loss_plies:
    loss_plies.sort()
    print(f"败局步数: min={loss_plies[0]} 中位={loss_plies[len(loss_plies)//2]} max={loss_plies[-1]}")
    quick = sum(1 for x in loss_plies if x < 60)
    print(f"  60 步内速败: {quick}/{len(loss_plies)}")
