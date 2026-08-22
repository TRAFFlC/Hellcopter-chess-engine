import os
import sys
import json
import math
import copy
import random
import argparse
import subprocess
import re
import shutil
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_and_resolve_config
from match_utils import find_cutechess


DEFAULT_PARAMS = [
    ("search_params", "lmr_base", 0.75, 0.25, 2.0),
    ("search_params", "lmr_divisor", 2.0, 1.0, 4.0),
    ("search_params", "lmr_min_depth", 3, 1, 6),
    ("search_params", "history_prune_base", 3, 1, 8),
    ("search_params", "lmp_base", 6, 2, 14),
    ("search_params", "nmp_base_reduction", 3, 1, 6),
    ("search_params", "nmp_depth_divisor", 4, 2, 8),
    ("search_params", "futility_margin_base", 150, 50, 400),
    ("search_params", "razoring_margin", 300, 100, 600),
    ("search_params", "rfp_depth_scale", 30, 10, 80),
    ("time_management", "easy_move_stability_count", 3, 1, 8),
    ("time_management", "panic_score_drop_threshold", 100, 30, 300),
    ("time_management", "initial_aspiration_window", 50, 10, 150),
    ("time_management", "normal_aspiration_window", 25, 10, 100),
]


def perturb_config(resolved: dict, params: list, c: float,
                   seed: int = None) -> tuple:
    if seed is not None:
        random.seed(seed)
    cfg_plus = copy.deepcopy(resolved)
    cfg_minus = copy.deepcopy(resolved)
    delta = []
    for group, key, current, low, high in params:
        d = 1 if random.random() < 0.5 else -1
        delta.append(d)
        for cfg, sign in [(cfg_plus, 1), (cfg_minus, -1)]:
            new_val = float(current) + sign * c * d
            new_val = max(float(low), min(float(high), new_val))
            cfg.setdefault("parameters", {}).setdefault(group, {})[key] = round(new_val, 4)
    return cfg_plus, cfg_minus, delta


def write_config(cfg: dict, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(cfg, f)


def create_uci_adapter(adapter_path: str, engine_params_path: str, base_dir: str):
    ep_path = engine_params_path.replace("\\", "/")
    bd_path = base_dir.replace("\\", "/")
    with open(adapter_path, "w") as f:
        f.write("import os, sys\n")
        f.write(f'os.environ["ENGINE_PARAMS"] = "{ep_path}"\n')
        f.write(f'sys.path.insert(0, "{bd_path}")\n')
        f.write("from uci_engine import UCIEngine\n")
        f.write("uci = UCIEngine()\n")
        f.write("uci.run()\n")


def run_match(cutechess: str, adapter_a: str, adapter_b: str,
              label_a: str, label_b: str, base_dir: str,
              tc: str, rounds: int, concurrency: int = 4) -> Optional[dict]:
    python_exe = sys.executable or "python"
    cmd = [
        cutechess,
        "-engine", f"name=A-{label_a}", "proto=uci",
        f"cmd={python_exe}", f"arg={adapter_a}", f"dir={base_dir}",
        "-engine", f"name=B-{label_b}", "proto=uci",
        f"cmd={python_exe}", f"arg={adapter_b}", f"dir={base_dir}",
        "-each", f"tc={tc}",
        "-rounds", str(rounds),
        "-concurrency", str(concurrency),
        "-draw", "movenumber=40", "movecount=5", "score=20",
        "-resign", "movecount=3", "score=500",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          cwd=base_dir, timeout=7200)
    output = proc.stdout + proc.stderr
    m = re.search(
        r"Score of\s+(.+?)\s+vs\s+(.+?):\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)",
        output
    )
    if m:
        return {
            "wins_a": int(m.group(3)), "wins_b": int(m.group(4)),
            "draws": int(m.group(5)),
            "total": int(m.group(3)) + int(m.group(4)) + int(m.group(5)),
        }
    print("Warning: could not parse match result")
    print(output[-800:])
    return None


def gradient_from_scores(score_plus: float, score_minus: float,
                         c: float, delta: list) -> list:
    return [(score_plus - score_minus) / (2 * c * d) for d in delta]


def main():
    parser = argparse.ArgumentParser(description="SPSA Tuning for Hellcopter")
    parser.add_argument("--config", default=None, help="Base config")
    parser.add_argument("--tc", default="10+0.1", help="Time control")
    parser.add_argument("--rounds", type=int, default=200)
    parser.add_argument("--iters", type=int, default=50)
    parser.add_argument("--c", type=float, default=0.1, help="Perturbation size")
    parser.add_argument("--a", type=float, default=0.5, help="Init learning rate")
    parser.add_argument("--A", type=float, default=10, help="Stabilization const")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--alpha", type=float, default=0.602,
                        help="Gain decay exponent")
    parser.add_argument("--gamma", type=float, default=0.101,
                        help="Perturbation decay exponent")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cutechess = find_cutechess(None, base_dir)
    if not cutechess:
        print("cutechess-cli not found")
        sys.exit(1)

    config_path = args.config or os.path.join(base_dir, "engine_params.json")
    resolved = load_and_resolve_config(config_path)
    params = DEFAULT_PARAMS
    n_params = len(params)
    x = [p[2] for p in params]

    tmp_root = os.path.join(base_dir, ".__spsa_tmp__")
    os.makedirs(tmp_root, exist_ok=True)

    print(f"SPSA: {n_params} params, {args.iters} iters, tc={args.tc}, {args.rounds}rnd/iter")
    print()

    for it in range(1, args.iters + 1):
        ak = args.a / (it + args.A) ** args.alpha
        ck = args.c / (it + args.A) ** args.gamma

        cfg_plus, cfg_minus, delta = perturb_config(resolved, params, ck, seed=it * 37)

        dir_plus = os.path.join(tmp_root, "plus")
        dir_minus = os.path.join(tmp_root, "minus")
        os.makedirs(dir_plus, exist_ok=True)
        os.makedirs(dir_minus, exist_ok=True)

        ep_plus = os.path.join(dir_plus, "engine_params.json")
        ep_minus = os.path.join(dir_minus, "engine_params.json")
        ad_plus = os.path.join(dir_plus, "adapter.py")
        ad_minus = os.path.join(dir_minus, "adapter.py")

        write_config(cfg_plus, ep_plus)
        write_config(cfg_minus, ep_minus)
        create_uci_adapter(ad_plus, ep_plus, base_dir)
        create_uci_adapter(ad_minus, ep_minus, base_dir)

        result = run_match(cutechess, ad_plus, ad_minus,
                           f"P{it}", f"M{it}", base_dir,
                           args.tc, args.rounds, args.concurrency)

        shutil.rmtree(dir_plus, ignore_errors=True)
        shutil.rmtree(dir_minus, ignore_errors=True)

        if result is None or result["total"] == 0:
            print(f"  iter {it:3d}: match failed, skip")
            continue

        score_plus = (result["wins_a"] + 0.5 * result["draws"]) / result["total"]
        score_minus = (result["wins_b"] + 0.5 * result["draws"]) / result["total"]
        grad = gradient_from_scores(score_plus, score_minus, ck, delta)
        grad_norm = math.sqrt(sum(g * g for g in grad))

        for i in range(n_params):
            x[i] += ak * grad[i]
            _, _, low, high = params[i]
            x[i] = max(low, min(high, x[i]))
            resolved["parameters"][params[i][0]][params[i][1]] = round(x[i], 4)

        key_preview = "  ".join(
            f"{params[i][1]}={x[i]:.3f}" for i in range(min(3, n_params)))
        print(f"  {it:3d}: +{score_plus:.3f} -{score_minus:.3f}  |g|={grad_norm:.4f}  {key_preview}")

        if grad_norm < 0.001:
            print("  Converged.")
            break

    print("\nFinal parameters:")
    for i, (group, key, _, low, high) in enumerate(params):
        print(f"  {group}.{key}: {x[i]:.4f}  [{low}, {high}]")

    out_path = os.path.join(base_dir, "spsa_result.json")
    with open(out_path, "w") as f:
        json.dump(resolved, f, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
