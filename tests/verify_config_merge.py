"""验证 config.resolve_config 深度合并：变体继承基线全部参数且仅覆盖显式项。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import load_and_resolve_config

base = load_and_resolve_config("configs/v1.9.5.json")
variant = load_and_resolve_config("configs/lmr_d2.5.json")

base_keys = set(base["parameters"]["search_params"])
var_keys = set(variant["parameters"]["search_params"])

missing = base_keys - var_keys
extra = var_keys - base_keys
diff = {k for k in (base_keys & var_keys)
        if base["parameters"]["search_params"][k] != variant["parameters"]["search_params"][k]}

print(f"基线 search_params: {len(base_keys)} 项")
print(f"变体 search_params: {len(var_keys)} 项")
if missing:
    print(f"缺失参数（合并失败）: {sorted(missing)}")
    sys.exit(1)
if extra:
    print(f"多出参数（异常）: {sorted(extra)}")
    sys.exit(1)
print(f"与基线不同的参数: {sorted(diff)}")
expected = {"lmr_divisor"}
if diff != expected:
    print(f"预期只有 {sorted(expected)} 不同，实际: {sorted(diff)}")
    sys.exit(1)
print("PASS: 深度合并正确，变体完整继承基线且仅覆盖 lmr_divisor")
