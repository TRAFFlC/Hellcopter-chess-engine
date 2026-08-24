"""生成实验用平面配置: resolve(任意版本/变体) + 强制单线程。

用法:
  python tests/make_experiment_config.py --config lmr_d2.5 --out temp_exp/lmr_d25.json
  python tests/make_experiment_config.py --config v1.9.5 --out temp_exp/base.json

为什么强制线程: configs/*.json 原始文件仍含 threading.num_threads=4,
而 ENGINE_PARAMS 环境变量路径会在启动时加载该值 → 独立 exe 走 SMP。
7/16 消融已证多线程 −56 Elo 且违反资源纪律(GOAL.md 第0条), 实验一律单线程。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import load_and_resolve_config

parser = argparse.ArgumentParser()
parser.add_argument("--config", required=True, help="configs/ 下名称或绝对路径")
parser.add_argument("--out", required=True)
parser.add_argument("--threads", type=int, default=1)
args = parser.parse_args()

path = args.config
if not os.path.isabs(path):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "configs", f"{path}.json")

cfg = load_and_resolve_config(path)
cfg["parameters"]["threading"] = {"enabled": True, "num_threads": args.threads}
# see_prune_depth_scale 为编译期宏(loader 不解析), 移除死键避免误导
cfg["parameters"].get("search_params", {}).pop("see_prune_depth_scale", None)

os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
with open(args.out, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)

sp = cfg["parameters"].get("search_params", {})
print(f"written: {args.out}")
print(f"  lmr_divisor={sp.get('lmr_divisor')} threads={args.threads} params={len(cfg['parameters'])} groups")
