"""生成干净的比赛配置: resolved(v1.9.5) + SEE开关确认 + 线程1。"""
import json
import sys

sys.path.insert(0, r"E:\world\python\chess")
from config import load_and_resolve_config

cfg = load_and_resolve_config(r"E:\world\python\chess\configs\v1.9.5.json")
cfg["parameters"]["threading"] = {"enabled": True, "num_threads": 1}
# see_prune_depth_scale 是编译期宏(loader 不解析), json 中该键无效, 移除避免误导
cfg["parameters"]["search_params"].pop("see_prune_depth_scale", None)

out = r"E:\world\python\chess\arena\copter\engine_params_clean.json"
with open(out, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
print("written:", out)
print("params groups:", list(cfg["parameters"].keys()))
print("threads:", cfg["parameters"]["threading"])
