import os, glob

egtb_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "EGTB")
rtbw = glob.glob(os.path.join(egtb_dir, "*.rtbw"))

def piece_count_v2(name):
    """正确计算棋子数：K=王 Q=后 R=车 B=象 N=马 P=兵"""
    clean = name.replace('K', '')  # 去掉 K
    # 每个大写字母代表一个棋子
    pieces = sum(1 for c in clean if c.isupper())
    return pieces + 2  # 加上两个 K

# 列出所有文件及其棋子数
for f in sorted(rtbw):
    name = os.path.basename(f).replace('.rtbw', '')
    pc = piece_count_v2(name)
    size_mb = os.path.getsize(f) / (1024*1024)
    if pc >= 5:
        print(f"  {name}: {pc}-man, {size_mb:.2f} MB")

# 统计
from collections import Counter
counts = Counter(piece_count_v2(os.path.basename(f).replace('.rtbw','')) for f in rtbw)
print(f"\n统计: {dict(sorted(counts.items()))}")
