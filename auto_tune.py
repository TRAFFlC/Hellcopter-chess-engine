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
import signal
import shutil

from tune_params import find_cutechess, calc_elo, parse_match_output, check_engine_dll


PIECE_VALUE_MUTATION_RATE = 1.15
PST_MUTATION_RATE = 1.5
EVAL_WEIGHTS_MUTATION_RATE = 1.5
SEARCH_PARAMS_MUTATION_RATE = 1.3

SEARCH_PARAMS_MUTABLE = {"futility_margin_base", "razoring_margin"}

ACCEPTANCE_THRESHOLD = 0.55
DEFAULT_ROUNDS = 11
DEFAULT_TC = "96+0.8"

GATEKEEPERS = ["v1.4.0", "v1.5.0"]


def extract_param_groups(config):
    groups = {}
    params = config.get("parameters", {})

    for key, val in params.get("piece_values", {}).items():
        if key == "pawn":
            continue
        groups[f"piece_values.{key}"] = [val] if not isinstance(val, list) else list(val)

    for key, val in params.get("pst", {}).items():
        groups[f"pst.{key}"] = list(val)

    for key, val in params.get("eval_weights", {}).items():
        groups[f"eval_weights.{key}"] = [val] if not isinstance(val, list) else list(val)

    for key, val in params.get("search_params", {}).items():
        if isinstance(val, bool):
            continue
        if key not in SEARCH_PARAMS_MUTABLE:
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


def get_mutation_rate(group_name):
    if group_name.startswith("piece_values"):
        return PIECE_VALUE_MUTATION_RATE
    elif group_name.startswith("pst"):
        return PST_MUTATION_RATE
    elif group_name.startswith("eval_weights"):
        return EVAL_WEIGHTS_MUTATION_RATE
    elif group_name.startswith("search_params"):
        return SEARCH_PARAMS_MUTATION_RATE
    else:
        return 1.3


def create_uci_adapter(script_path, params_json_path, base_dir):
    params_fwd = params_json_path.replace("\\", "/")
    base_dir_fwd = base_dir.replace("\\", "/")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write("import os\n")
        f.write("import sys\n")
        f.write("import traceback\n\n")
        f.write(f'os.environ["ENGINE_PARAMS"] = "{params_fwd}"\n')
        f.write(f'sys.path.insert(0, "{base_dir_fwd}")\n\n')
        f.write("try:\n")
        f.write("    from uci_engine import UCIEngine\n")
        f.write("    uci = UCIEngine()\n")
        f.write("    uci.run()\n")
        f.write("except Exception:\n")
        f.write("    traceback.print_exc(file=sys.stderr)\n")
        f.write("    sys.stderr.flush()\n")


def run_match(cutechess, python_exe, script_new, script_best,
              temp_dir_new, temp_dir_best, rounds, tc, base_dir,
              name_new="Hellcopter-New", name_best="Hellcopter-Best"):
    cmd = [
        cutechess,
        "-engine",
        f"name={name_new}",
        "proto=uci",
        f"cmd={python_exe}",
        f"arg={script_new}",
        f"dir={temp_dir_new}",
        "-engine",
        f"name={name_best}",
        "proto=uci",
        f"cmd={python_exe}",
        f"arg={script_best}",
        f"dir={temp_dir_best}",
        "-each",
        f"tc={tc}",
        "-rounds", str(rounds),
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
        total = wins + losses + draws
        if total < rounds:
            print(f"  WARNING: Match incomplete! {total}/{rounds} games played (engine crash?)")
            return wins, losses, draws, False
        return wins, losses, draws, True
    return None, None, None, False


def load_gatekeeper_config(version, base_dir):
    config_path = os.path.join(base_dir, "configs", f"{version}.json")
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"Gatekeeper config not found: {config_path}")
    from config import load_and_resolve_config
    return load_and_resolve_config(config_path)


def write_temp_config(config, temp_dir, filename="engine_params.json"):
    clean_config = {"parameters": config.get("parameters", {})}
    json_path = os.path.join(temp_dir, filename)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(clean_config, f, indent=2)
    return json_path


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(description="Auto-tune with dual gatekeeper validation")
    parser.add_argument("--base-config", default="configs/v1.5.0.json",
                        help="Base config file path (default: configs/v1.5.0.json)")
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS,
                        help=f"Games per match (default: {DEFAULT_ROUNDS})")
    parser.add_argument("--tc", default=DEFAULT_TC,
                        help=f"Time control (default: {DEFAULT_TC})")
    parser.add_argument("--accept-threshold", type=float, default=ACCEPTANCE_THRESHOLD,
                        help=f"Win rate threshold (default: {ACCEPTANCE_THRESHOLD})")

    args = parser.parse_args()

    config_path = args.base_config
    if not os.path.isabs(config_path):
        config_path = os.path.join(base_dir, config_path)

    from config import load_and_resolve_config
    base_config = load_and_resolve_config(config_path)

    groups = extract_param_groups(base_config)
    group_names = list(groups.keys())

    gatekeeper_configs = {}
    for gk in GATEKEEPERS:
        gatekeeper_configs[gk] = load_gatekeeper_config(gk, base_dir)

    print("=" * 60)
    print("  Auto-Tune Dual Gatekeeper Mode")
    print("=" * 60)
    print(f"  Base config       : {config_path}")
    print(f"  Gatekeepers       : {', '.join(GATEKEEPERS)}")
    print(f"  Accept threshold  : {args.accept_threshold:.0%} (vs EACH gatekeeper)")
    print(f"  Rounds/match      : {args.rounds}")
    print(f"  TC                : {args.tc}")
    print(f"  Param groups      : {len(group_names)} (all mutated each iteration)")
    print(f"  Mode              : Continuous (Ctrl+C to stop)")
    print("")
    print("  Mutation rates:")
    print(f"    piece_values    : {PIECE_VALUE_MUTATION_RATE:.2f}x")
    print(f"    pst             : {PST_MUTATION_RATE:.2f}x")
    print(f"    eval_weights    : {EVAL_WEIGHTS_MUTATION_RATE:.2f}x")
    print(f"    search_params   : {SEARCH_PARAMS_MUTATION_RATE:.2f}x")
    print("=" * 60)

    check_engine_dll(base_dir)

    cutechess = find_cutechess(None, base_dir)
    if cutechess is None:
        print("Error: cutechess-cli not found.")
        sys.exit(1)

    best_config = copy.deepcopy(base_config)
    best_groups = {name: list(vals) for name, vals in groups.items()}

    candidates = []
    history = []

    configs_dir = os.path.join(base_dir, "configs")
    existing_candidates = []
    for f in os.listdir(configs_dir):
        if f.startswith("candidate_") and f.endswith(".json"):
            try:
                num = int(f[10:-5])
                existing_candidates.append(num)
            except ValueError:
                pass
    candidate_counter = max(existing_candidates) if existing_candidates else 0
    print(f"  Starting candidate numbering from: {candidate_counter + 1}")

    python_exe = sys.executable or "python"
    iteration = 0

    stop_requested = False

    def signal_handler(sig, frame):
        nonlocal stop_requested
        print(f"\n\n  Ctrl+C received! Finishing current iteration and saving...")
        stop_requested = True

    signal.signal(signal.SIGINT, signal_handler)

    while not stop_requested:
        iteration += 1
        print(f"\n{'=' * 60}")
        print(f"  Iteration {iteration}")
        print(f"{'=' * 60}")

        print(f"  Mutating all {len(group_names)} groups:")

        mutations = []
        new_config = copy.deepcopy(best_config)
        new_groups = copy.deepcopy(best_groups)

        for group_name in group_names:
            rate = get_mutation_rate(group_name)
            old_values = best_groups[group_name]
            new_values = mutate_group(old_values, rate)

            if new_values == old_values:
                for _ in range(5):
                    new_values = mutate_group(old_values, rate * 1.1)
                    if new_values != old_values:
                        break

            if new_values != old_values:
                if len(old_values) == 1:
                    change_pct = abs(new_values[0] - old_values[0]) / old_values[0] * 100
                    print(f"    {group_name}: {old_values[0]} -> {new_values[0]} ({change_pct:+.1f}%)")
                else:
                    changed = sum(1 for a, b in zip(old_values, new_values) if a != b)
                    print(f"    {group_name}: {changed}/{len(old_values)} values changed")

                set_param_group(new_config, group_name, new_values)
                new_groups[group_name] = new_values
                mutations.append({
                    "group": group_name,
                    "rate": rate,
                    "old": old_values if len(old_values) <= 4 else f"[{len(old_values)}]",
                    "new": new_values if len(new_values) <= 4 else f"[{len(new_values)}]",
                })

        if not mutations:
            print("  No valid mutations, skipping")
            continue

        accepted = True
        gatekeeper_results = {}

        for gk_name in GATEKEEPERS:
            if stop_requested:
                accepted = False
                break

            print(f"\n  --- Gatekeeper: {gk_name} ---")

            temp_dir_new = tempfile.mkdtemp(prefix="chess_tune_new_")
            temp_dir_gk = tempfile.mkdtemp(prefix=f"chess_tune_gk_")

            new_json = write_temp_config(new_config, temp_dir_new)
            gk_json = write_temp_config(gatekeeper_configs[gk_name], temp_dir_gk)

            script_new = os.path.join(base_dir, "_uci_engine_new.py")
            script_gk = os.path.join(base_dir, "_uci_engine_gk.py")

            create_uci_adapter(script_new, new_json, base_dir)
            create_uci_adapter(script_gk, gk_json, base_dir)

            wins, losses, draws, complete = run_match(
                cutechess, python_exe, script_new, script_gk,
                temp_dir_new, temp_dir_gk, args.rounds, args.tc, base_dir,
                name_new=f"New-Iter{iteration}",
                name_best=f"GK-{gk_name}",
            )

            shutil.rmtree(temp_dir_new, ignore_errors=True)
            shutil.rmtree(temp_dir_gk, ignore_errors=True)

            if wins is None:
                print(f"  >>> INVALID - Failed to parse match results vs {gk_name}")
                accepted = False
                gatekeeper_results[gk_name] = {"status": "parse_failed"}
                break

            if not complete:
                print(f"  >>> INVALID - Match incomplete vs {gk_name} (engine crash)")
                accepted = False
                gatekeeper_results[gk_name] = {"status": "incomplete"}
                break

            total = wins + losses + draws
            win_rate = (wins + 0.5 * draws) / total if total > 0 else 0

            elo_result = calc_elo(wins, losses, draws)
            elo_str = ""
            if elo_result:
                _, _, elo_diff = elo_result
                if not math.isinf(elo_diff):
                    elo_str = f", Elo: {elo_diff:+.1f}"

            print(f"  Result vs {gk_name}: {wins}W {losses}L {draws}D (win rate: {win_rate:.2%}{elo_str})")

            gatekeeper_results[gk_name] = {
                "wins": wins,
                "losses": losses,
                "draws": draws,
                "win_rate": round(win_rate, 4),
            }

            if win_rate < args.accept_threshold:
                print(f"  >>> REJECTED by {gk_name} (win rate {win_rate:.2%} < {args.accept_threshold:.0%})")
                accepted = False
                break
            else:
                print(f"  >>> PASSED {gk_name} (win rate {win_rate:.2%} >= {args.accept_threshold:.0%})")

        if accepted and not stop_requested:
            print(f"\n  >>> CANDIDATE ACCEPTED! Passed all gatekeepers!")
            best_config = new_config
            best_groups = new_groups

            candidate_counter += 1
            candidate_config = copy.deepcopy(new_config)
            candidate_config["version"] = f"candidate_{candidate_counter}"
            candidate_config["created_at"] = datetime.datetime.now().isoformat()
            candidate_config["gatekeeper_results"] = gatekeeper_results
            candidate_config["iteration"] = iteration

            candidates.append({
                "version": f"candidate_{candidate_counter}",
                "iteration": iteration,
                "gatekeeper_results": gatekeeper_results,
            })

            candidate_path = os.path.join(base_dir, "configs", f"candidate_{candidate_counter}.json")
            with open(candidate_path, "w", encoding="utf-8") as f:
                json.dump(candidate_config, f, indent=2, ensure_ascii=False)
            print(f"  Candidate saved to: {candidate_path}")

        history.append({
            "iteration": iteration,
            "accepted": accepted,
            "gatekeeper_results": gatekeeper_results,
        })

        print(f"\n  Summary:")
        print(f"    Iterations   : {iteration}")
        print(f"    Candidates   : {len(candidates)}")
        if candidates:
            for c in candidates:
                gk_str = " | ".join(
                    f"{k}: {v['win_rate']:.2%}" for k, v in c["gatekeeper_results"].items()
                    if "win_rate" in v
                )
                print(f"      {c['version']} (iter {c['iteration']}): {gk_str}")

    history_path = os.path.join(base_dir, "tune_history.json")
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    print(f"\n  Tune history saved to: {history_path}")

    print(f"\n{'=' * 60}")
    print(f"  Auto-Tune Stopped")
    print(f"{'=' * 60}")
    print(f"  Total iterations : {iteration}")
    print(f"  Candidates found : {len(candidates)}")
    if candidates:
        print(f"\n  Candidate details:")
        for c in candidates:
            gk_str = " | ".join(
                f"{k}: {v['win_rate']:.2%}" for k, v in c["gatekeeper_results"].items()
                if "win_rate" in v
            )
            print(f"    {c['version']} (iter {c['iteration']}): {gk_str}")
    print(f"  Candidates saved to: configs/candidate_*.json")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
