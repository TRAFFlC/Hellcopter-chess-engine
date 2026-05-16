import os
import sys
import json
import copy
import random
import math
import argparse
import subprocess
import tempfile
import datetime

from tune_params import find_cutechess, calc_elo, parse_match_output, check_engine_dll


def extract_param_groups(config):
    groups = {}
    params = config.get("parameters", {})

    for key, val in params.get("piece_values", {}).items():
        groups[f"piece_values.{key}"] = [val] if not isinstance(val, list) else list(val)

    for key, val in params.get("pst", {}).items():
        groups[f"pst.{key}"] = list(val)

    for key, val in params.get("eval_weights", {}).items():
        groups[f"eval_weights.{key}"] = [val] if not isinstance(val, list) else list(val)

    for key, val in params.get("search_params", {}).items():
        if isinstance(val, bool):
            continue
        groups[f"search_params.{key}"] = [val] if not isinstance(val, list) else list(val)

    return groups


def set_param_group(config, group_path, values):
    params = config["parameters"]
    parts = group_path.split(".", 1)
    category = parts[0]
    key = parts[1]
    parent = params[category]

    if isinstance(parent[key], list):
        parent[key] = values
    else:
        parent[key] = values[0]


def mutate_group(values, rate):
    factor = random.uniform(1.0 / rate, rate)
    return [round(v * factor) for v in values]


def create_uci_adapter(script_path, params_json_path, base_dir):
    base_dir_escaped = base_dir.replace("\\", "\\\\")
    params_escaped = params_json_path.replace("\\", "\\\\")

    with open(script_path, "w", encoding="utf-8") as f:
        f.write("import os\n")
        f.write("import sys\n\n")
        f.write(f'os.environ["ENGINE_PARAMS"] = r"{params_escaped}"\n')
        f.write("sys.path.insert(0, r\"" + base_dir_escaped + "\")\n\n")
        f.write("from uci_engine import UCIEngine\n\n")
        f.write('if __name__ == "__main__":\n')
        f.write("    uci = UCIEngine()\n")
        f.write("    uci.run()\n")


def run_match(cutechess, python_exe, script_new, script_best,
              temp_dir_new, temp_dir_best, rounds, tc, base_dir):
    cmd = [
        cutechess,
        "-engine",
        "name=Hellcopter-New",
        "proto=uci",
        f"cmd={python_exe}",
        f"arg={script_new}",
        f"dir={temp_dir_new}",
        "-engine",
        "name=Hellcopter-Best",
        "proto=uci",
        f"cmd={python_exe}",
        f"arg={script_best}",
        f"dir={temp_dir_best}",
        "-each",
        f"tc={tc}",
        "-rounds", str(rounds),
        "-repeat",
        "-pgnout", os.path.join(base_dir, "auto_tune_match.pgn"),
    ]

    print(f"  Command: {' '.join(cmd)}")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    full_output = []
    for line in process.stdout:
        stripped = line.rstrip()
        print(f"    {stripped}", flush=True)
        full_output.append(stripped)

    process.wait()
    output = "\n".join(full_output)

    result = parse_match_output(output)
    if result:
        _, _, wins, losses, draws = result
        return wins, losses, draws
    return None


def bump_version(version_str):
    parts = version_str.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(description="Auto-tune via random walk")
    parser.add_argument("--base-config", default="configs/v1.3.0.json",
                        help="Base config file path (default: configs/v1.3.0.json)")
    parser.add_argument("--iterations", type=int, default=20,
                        help="Number of tuning iterations (default: 20)")
    parser.add_argument("--rounds", type=int, default=10,
                        help="Games per match (default: 10)")
    parser.add_argument("--tc", default="12+0.1",
                        help="Time control (default: 12+0.1)")
    parser.add_argument("--output", default=None,
                        help="Output config file path (default: auto-generated version)")

    args = parser.parse_args()

    config_path = args.base_config
    if not os.path.isabs(config_path):
        config_path = os.path.join(base_dir, config_path)

    with open(config_path, "r", encoding="utf-8") as f:
        base_config = json.load(f)

    groups = extract_param_groups(base_config)
    group_names = list(groups.keys())

    print("=" * 60)
    print("  Auto-Tune Random Walk")
    print("=" * 60)
    print(f"  Base config : {config_path}")
    print(f"  Iterations  : {args.iterations}")
    print(f"  Rounds/match: {args.rounds}")
    print(f"  TC          : {args.tc}")
    print(f"  Param groups: {len(group_names)}")
    for name in group_names:
        print(f"    {name} ({len(groups[name])} values)")
    print("=" * 60)

    check_engine_dll(base_dir)

    cutechess = find_cutechess(None, base_dir)
    if cutechess is None:
        print("Error: cutechess-cli not found in PATH or project directory.")
        sys.exit(1)

    best_config = copy.deepcopy(base_config)
    best_groups = {name: list(vals) for name, vals in groups.items()}
    mutation_rates = {}
    for name in group_names:
        if name.startswith("piece_values"):
            mutation_rates[name] = 1.05
        elif name.startswith("pst"):
            mutation_rates[name] = 1.4
        elif name.startswith("eval_weights"):
            mutation_rates[name] = 1.15
        elif name.startswith("search_params"):
            mutation_rates[name] = 1.1
        else:
            mutation_rates[name] = 1.2

    history = []
    improvements = 0
    python_exe = sys.executable or "python"

    for iteration in range(1, args.iterations + 1):
        print(f"\n{'=' * 60}")
        print(f"  Iteration {iteration}/{args.iterations}")
        print(f"{'=' * 60}")

        selected = random.choice(group_names)
        rate = mutation_rates[selected]
        old_values = best_groups[selected]

        new_values = mutate_group(old_values, rate)

        if new_values == old_values:
            print(f"  Group: {selected} (rate={rate:.3f}) - No change after mutation, skipping")
            history.append({
                "iteration": iteration,
                "group": selected,
                "mutation_rate": round(rate, 4),
                "accepted": False,
                "reason": "no_change",
            })
            continue

        print(f"  Group: {selected} (rate={rate:.3f})")
        if len(old_values) == 1:
            print(f"    Old: {old_values[0]} -> New: {new_values[0]}")
        else:
            changed = sum(1 for a, b in zip(old_values, new_values) if a != b)
            print(f"    Changed {changed}/{len(old_values)} values")

        new_config = copy.deepcopy(best_config)
        set_param_group(new_config, selected, new_values)

        temp_dir_best = tempfile.mkdtemp(prefix="chess_tune_best_")
        temp_dir_new = tempfile.mkdtemp(prefix="chess_tune_new_")

        best_json = os.path.join(temp_dir_best, "temp_best.json")
        new_json = os.path.join(temp_dir_new, "temp_new.json")

        with open(best_json, "w", encoding="utf-8") as f:
            json.dump(best_config, f, indent=2)
        with open(new_json, "w", encoding="utf-8") as f:
            json.dump(new_config, f, indent=2)

        script_best = os.path.join(base_dir, "_uci_engine_best.py")
        script_new = os.path.join(base_dir, "_uci_engine_new.py")

        create_uci_adapter(script_best, best_json, base_dir)
        create_uci_adapter(script_new, new_json, base_dir)

        result = run_match(
            cutechess, python_exe, script_new, script_best,
            temp_dir_new, temp_dir_best, args.rounds, args.tc, base_dir,
        )

        if result is None:
            print("  Failed to parse match results")
            history.append({
                "iteration": iteration,
                "group": selected,
                "mutation_rate": round(rate, 4),
                "accepted": False,
                "reason": "parse_failed",
            })
            continue

        wins, losses, draws = result
        total = wins + losses + draws
        win_rate = (wins + 0.5 * draws) / total if total > 0 else 0

        elo_result = calc_elo(wins, losses, draws)

        print(f"  Result: {wins}W {losses}L {draws}D (win rate: {win_rate:.2%})")
        if elo_result:
            _, _, elo_diff = elo_result
            if not math.isinf(elo_diff):
                print(f"  Elo diff: {elo_diff:+.1f}")

        temperature = max(0.1, 1.0 - iteration / args.iterations)
        if win_rate > 0.5:
            accepted = True
        else:
            accept_prob = math.exp((win_rate - 0.5) / temperature)
            accepted = random.random() < accept_prob
        if accepted:
            print(f"  >>> ACCEPTED - New params adopted!")
            best_config = new_config
            best_groups[selected] = new_values
            improvements += 1
            mutation_rates[selected] = min(2.0, mutation_rates[selected] * 1.05)
        else:
            print(f"  >>> REJECTED - Best params remain")
            mutation_rates[selected] = max(1.05, mutation_rates[selected] / 1.05)

        history.append({
            "iteration": iteration,
            "group": selected,
            "mutation_rate": round(rate, 4),
            "new_mutation_rate": round(mutation_rates[selected], 4),
            "old_values": old_values if len(old_values) <= 8 else f"[{len(old_values)} values]",
            "new_values": new_values if len(new_values) <= 8 else f"[{len(new_values)} values]",
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "win_rate": round(win_rate, 4),
            "accepted": accepted,
        })

    history_path = os.path.join(base_dir, "tune_history.json")
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    print(f"\nTune history saved to: {history_path}")

    if args.output:
        output_path = args.output
    else:
        old_version = base_config.get("version", "1.0.0")
        new_version = bump_version(old_version)
        best_config["version"] = new_version
        output_path = os.path.join(base_dir, "configs", f"v{new_version}.json")

    best_config["created_at"] = datetime.datetime.now().isoformat()
    best_config["description"] = f"Auto-tuned from v{base_config.get('version', '?')}"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(best_config, f, indent=2, ensure_ascii=False)

    print(f"Best config saved to: {output_path}")
    print(f"\n{'=' * 60}")
    print(f"  Summary")
    print(f"{'=' * 60}")
    print(f"  Total iterations : {args.iterations}")
    print(f"  Improvements     : {improvements}")
    print(f"  Acceptance rate  : {improvements / args.iterations:.1%}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
