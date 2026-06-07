import os, glob
from collections import Counter

egtb_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "EGTB")
rtbw = glob.glob(os.path.join(egtb_dir, "*.rtbw"))
rtbz = glob.glob(os.path.join(egtb_dir, "*.rtbz"))

def piece_count(name):
    clean = name.replace('K', '')
    return sum(1 for c in clean if c.isupper()) + 2

rtbw_names = [os.path.basename(f).replace('.rtbw','') for f in rtbw]
rtbz_names = [os.path.basename(f).replace('.rtbz','') for f in rtbz]

wdl_counts = Counter(piece_count(n) for n in rtbw_names)
dtz_counts = Counter(piece_count(n) for n in rtbz_names)

all_men = sorted(set(list(wdl_counts.keys()) + list(dtz_counts.keys())))
for k in all_men:
    w = wdl_counts.get(k, 0)
    d = dtz_counts.get(k, 0)
    status = "OK" if w == d and w > 0 else "INCOMPLETE" if w > 0 or d > 0 else "MISSING"
    print(f"  {k}-man: WDL={w}, DTZ={d} [{status}]")

# Check file sizes for 6-man and 7-man
print("\n6-man and 7-man file sizes:")
for f in sorted(rtbw + rtbz):
    name = os.path.basename(f)
    pc = piece_count(name.rsplit('.', 1)[0])
    if pc >= 6:
        size_mb = os.path.getsize(f) / (1024*1024)
        print(f"  {name}: {size_mb:.1f} MB")
