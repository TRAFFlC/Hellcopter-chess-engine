"""深度对比: resolve(configs/v1.9.5.json) vs 根目录 engine_params.json。"""
import copy
import json
import sys

sys.path.insert(0, r"E:\world\python\chess")
from config import load_and_resolve_config

a = load_and_resolve_config(r"E:\world\python\chess\configs\v1.9.5.json")
with open(r"E:\world\python\chess\engine_params.json", encoding="utf-8") as f:
    b = json.load(f)


def flat(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flat(v, key))
        else:
            out[key] = v
    return out


fa, fb = flat(a.get("parameters", {})), flat(b.get("parameters", {}))
all_keys = sorted(set(fa) | set(fb))
diffs = []
for k in all_keys:
    va, vb = fa.get(k, "<缺失>"), fb.get(k, "<缺失>")
    if va != vb:
        diffs.append((k, va, vb))

print(f"v1.9.5 resolved 参数数: {len(fa)}, engine_params.json 参数数: {len(fb)}")
print(f"差异键数: {len(diffs)}")
for k, va, vb in diffs[:40]:
    print(f"  {k}: v1.9.5={va} | root_json={vb}")
