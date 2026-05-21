import os
import sys
import argparse
import subprocess
import json
import re
import shutil
import platform
from datetime import datetime


LADDER = ["shallowblue", "tscp181", "apollo"]

OPPONENTS = {
    "shallowblue": {
        "dir": "test_engines/ShallowBlue 1575",
        "exe": "shallowblue.exe",
        "proto": "uci",
        "elo": 1575,
    },
    "tscp181": {
        "dir": "test_engines/TSCP 1607",
        "exe": "tscp181.exe",
        "proto": "xboard",
        "elo": 1607,
    },

    "apollo": {
        "dir": "test_engines/Apollo 1663",
        "exe": "apollo.exe",
        "proto": "uci",
        "elo": 1663,
    },
}

QUICK_ROUNDS = 5
QUICK_TC = "96+0.8"
STANDARD_ROUNDS = 11
STANDARD_TC = "96+0.8"
WIN_RATE_THRESHOLD = 0.55


def find_cutechess(cli_path, base_dir):
    if cli_path:
        if os.path.isfile(cli_path):
            return cli_path
        print(f"Error: specified cutechess-cli path not found: {cli_path}")
        sys.exit(1)

    found = shutil.which("cutechess-cli")
    if found:
        return found

    candidates = [
        os.path.join(base_dir, "cutechess-cli.exe"),
        os.path.join(base_dir, "cutechess-cli"),
        os.path.join(base_dir, "cutechess", "cutechess-cli.exe"),
        os.path.join(base_dir, "cutechess", "cutechess-cli"),
    ]

    if platform.system() == "Windows":
        program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        candidates.extend([
            os.path.join(program_files, "cutechess-cli", "cutechess-cli.exe"),
            os.path.join(program_files_x86, "cutechess-cli", "cutechess-cli.exe"),
        ])
    else:
        candidates.extend([
            os.path.join(base_dir, "cutechess-cli"),
            "/usr/local/bin/cutechess-cli",
            "/usr/bin/cutechess-cli",
        ])

    for c in candidates:
        if os.path.isfile(c):
            return c

    return None


def parse_match_output(output):
    pattern = re.compile(
        r"Score of\s+(.+?)\s+vs\s+(.+?):\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)"
    )
    last_match = None
    for line in output.splitlines():
        m = pattern.search(line)
        if m:
            last_match = (
                m.group(1).strip(),
                m.group(2).strip(),
                int(m.group(3)),
                int(m.group(4)),
                int(m.group(5)),
            )
    return last_match


def parse_invalid_results(output):
    invalid_wins = 0
    invalid_losses = 0
    for line in output.splitlines():
        l = line.lower()
        if "disconnects" in l or "illegal move" in l or "abandoned" in l:
            if "win:" in l and "disconnects" in l:
                pass
            if "loss:" in l and ("disconnects" in l or "illegal move" in l):
                pass
        m = re.search(r'Finished game \d+.*?(\d+-\d+).*?\{(.*?)\}', line)
        if m:
            result = m.group(1)
            reason = m.group(2).lower()
            if "disconnects" in reason or "illegal move" in reason or "abandoned" in reason:
                if result == "1-0":
                    invalid_wins += 1
                elif result == "0-1":
                    invalid_losses += 1
    return invalid_wins, invalid_losses


def bump_version(version_str):
    parts = version_str.split(".")
    if len(parts) != 3:
        return "1.0.0"
    try:
        major = int(parts[0])
        minor = int(parts[1])
        patch = int(parts[2])
    except ValueError:
        return "1.0.0"
    minor += 1
    return f"{major}.{minor}.{patch}"


def save_config(config_data, base_dir, new_version):
    config_data = dict(config_data)
    config_data["version"] = new_version
    config_dir = os.path.join(base_dir, "configs")
    os.makedirs(config_dir, exist_ok=True)
    config_path = os.path.join(config_dir, f"v{new_version}.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)
    return config_path


def save_match_info(match_dir, opponent_key, tc, rounds, wins, losses, draws, pgn_file, invalid_wins=0, invalid_losses=0):
    total = wins + losses + draws
    win_rate = (wins + 0.5 * draws) / total if total > 0 else 0
    hellcopter_score = f"{wins + 0.5 * draws}/{total}"

    info = {
        "match_name": f"Hellcopter vs {opponent_key.capitalize()}",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time_control": tc,
        "rounds": rounds,
        "result": {
            "hellcopter_wins": wins,
            "opponent_wins": losses,
            "draws": draws,
            "hellcopter_score": hellcopter_score,
            "win_rate": round(win_rate, 4),
        },
        "engines": {
            "hellcopter": {
                "name": "Hellcopter",
            },
            "opponent": {
                "name": opponent_key.capitalize(),
                "estimated_elo": OPPONENTS[opponent_key]["elo"],
            },
        },
        "pgn_file": pgn_file,
        "invalid_wins": invalid_wins,
        "invalid_losses": invalid_losses,
    }

    info_path = os.path.join(match_dir, "info.json")
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)


def run_match(cutechess, base_dir, config_path, opponent_key, rounds, tc):
    python_exe = sys.executable or "python"
    uci_script = os.path.join(base_dir, "uci_engine.py")

    opp = OPPONENTS[opponent_key]
    opp_exe = os.path.join(base_dir, opp["dir"], opp["exe"])
    opp_dir = os.path.join(base_dir, opp["dir"])

    match_dir = os.path.join(base_dir, "match_records", f"hellcopter_vs_{opponent_key}")
    os.makedirs(match_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tc_safe = tc.replace("+", "p")
    pgn_filename = f"match_{timestamp}_{tc_safe}.pgn"
    pgn_path = os.path.join(match_dir, pgn_filename)

    env = os.environ.copy()
    env["ENGINE_PARAMS"] = os.path.abspath(config_path)

    cmd = [
        cutechess,
        "-engine",
        "name=Hellcopter",
        "proto=uci",
        f"cmd={python_exe}",
        f"arg={uci_script}",
        f"dir={base_dir}",
        "-engine",
        f"name={opponent_key.capitalize()}",
        f"proto={opp['proto']}",
        f"cmd={opp_exe}",
        f"dir={opp_dir}",
        "-each",
        f"tc={tc}",
        "-rounds", str(rounds),
        "-repeat",
        "-pgnout", pgn_path,
    ]

    print(f"\nRunning: {' '.join(cmd)}\n")
    print("=" * 60)

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )

    full_output = []
    for line in process.stdout:
        stripped = line.rstrip()
        print(stripped, flush=True)
        full_output.append(stripped)

    process.wait()
    output = "\n".join(full_output)

    if process.returncode != 0:
        print(f"\ncutechess-cli exited with code {process.returncode}")

    result = parse_match_output(output)
    if result:
        _, _, wins, losses, draws = result
    else:
        print("Failed to parse match results from cutechess-cli output!")
        wins, losses, draws = 0, 0, 0

    invalid_wins, invalid_losses = parse_invalid_results(output)
    if invalid_wins > 0 or invalid_losses > 0:
        print(f"\nWARNING: Invalid results detected - {invalid_wins} invalid wins (disconnect/illegal), {invalid_losses} invalid losses")
        wins = max(0, wins - invalid_wins)
        losses = max(0, losses - invalid_losses)
        print(f"  Adjusted result: {wins}W - {losses}L - {draws}D")

    save_match_info(match_dir, opponent_key, tc, rounds, wins, losses, draws, pgn_filename, invalid_wins, invalid_losses)

    return wins, losses, draws, invalid_wins, invalid_losses


def call_auto_tune(base_dir, config_path):
    auto_tune_script = os.path.join(base_dir, "auto_tune.py")
    if not os.path.isfile(auto_tune_script):
        print(f"Error: auto_tune.py not found at {auto_tune_script}")
        return False

    print(f"\nCalling auto_tune.py --base-config {config_path}")
    print("=" * 60)
    try:
        result = subprocess.run(
            [sys.executable or "python", auto_tune_script, "--base-config", config_path],
            cwd=base_dir,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Error running auto_tune.py: {e}")
        return False


def print_result_summary(opponent_key, test_type, wins, losses, draws):
    total = wins + losses + draws
    win_rate = (wins + 0.5 * draws) / total if total > 0 else 0
    print(f"\n{test_type} Result vs {opponent_key.capitalize()}: "
          f"{wins}W - {losses}L - {draws}D  "
          f"(Win rate: {win_rate:.2%}, Score: {wins + 0.5 * draws}/{total})")


def check_quick_pass(wins, losses, draws):
    return losses == 0 and wins >= 2


def check_standard_pass(wins, losses, draws):
    total = wins + losses + draws
    if total == 0:
        return False
    win_rate = (wins + 0.5 * draws) / total
    return win_rate >= WIN_RATE_THRESHOLD


def challenge_opponent(cutechess, base_dir, config_path, config_data, opponent_key,
                       current_version, skip_quick):
    opp = OPPONENTS[opponent_key]
    opp_elo = opp["elo"]

    print(f"\n{'=' * 60}")
    print(f"  Challenge: {opponent_key.capitalize()} (ELO ~{opp_elo})")
    print(f"  Current version: v{current_version}")
    print(f"{'=' * 60}")

    if not skip_quick:
        print(f"\n--- Quick Test: {QUICK_ROUNDS} rounds, {QUICK_TC} ---")
        wins, losses, draws, inv_w, inv_l = run_match(
            cutechess, base_dir, config_path, opponent_key, QUICK_ROUNDS, QUICK_TC
        )
        if inv_w + inv_l > 0:
            print(f"WARNING: {inv_w + inv_l} invalid results in quick test ({inv_w} invalid wins, {inv_l} invalid losses)")
        print_result_summary(opponent_key, "Quick Test", wins, losses, draws)

        if check_quick_pass(wins, losses, draws):
            print(f">>> Quick test PASSED against {opponent_key.capitalize()}!")
            new_version = bump_version(current_version)
            saved_path = save_config(config_data, base_dir, new_version)
            print(f"    Version: v{current_version} -> v{new_version}")
            print(f"    Config saved: {saved_path}")
            return True, new_version, saved_path, config_data

    print(f"\n--- Standard Test: {STANDARD_ROUNDS} rounds, {STANDARD_TC} ---")
    wins, losses, draws, inv_w, inv_l = run_match(
        cutechess, base_dir, config_path, opponent_key, STANDARD_ROUNDS, STANDARD_TC
    )
    if inv_w + inv_l > 0:
        print(f"WARNING: {inv_w + inv_l} invalid results in standard test ({inv_w} invalid wins, {inv_l} invalid losses)")
    print_result_summary(opponent_key, "Standard Test", wins, losses, draws)

    if check_standard_pass(wins, losses, draws):
        print(f">>> Standard test PASSED against {opponent_key.capitalize()}!")
        new_version = bump_version(current_version)
        saved_path = save_config(config_data, base_dir, new_version)
        print(f"    Version: v{current_version} -> v{new_version}")
        print(f"    Config saved: {saved_path}")
        return True, new_version, saved_path, config_data

    print(f">>> Standard test FAILED against {opponent_key.capitalize()}")
    return False, current_version, config_path, config_data


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(
        description="Auto ladder test for Hellcopter chess engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python auto_ladder.py
  python auto_ladder.py --start-from shallowblue
  python auto_ladder.py --config configs/v1.3.0.json
  python auto_ladder.py --skip-quick
        """,
    )
    parser.add_argument("--start-from", type=str, default="shallowblue",
                        choices=LADDER,
                        help="Start from which opponent (default: shallowblue)")
    parser.add_argument("--config", type=str, default="configs/v1.3.0.json",
                        help="Current config file (default: configs/v1.3.0.json)")
    parser.add_argument("--skip-quick", action="store_true",
                        help="Skip quick test, go straight to standard test")
    parser.add_argument("--cutechess", type=str, default=None,
                        help="Path to cutechess-cli executable")

    args = parser.parse_args()

    cutechess = find_cutechess(args.cutechess, base_dir)
    if cutechess is None:
        print("Error: cutechess-cli not found in PATH or project directory.")
        print("  Download from: https://github.com/cutechess/cutechess/releases")
        sys.exit(1)

    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(base_dir, config_path)
    if not os.path.isfile(config_path):
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)

    current_version = config_data.get("version", "1.0.0")

    start_idx = LADDER.index(args.start_from) if args.start_from in LADDER else 0

    print("=" * 60)
    print("  Hellcopter Auto Ladder Test")
    print("=" * 60)
    print(f"  Version : v{current_version}")
    print(f"  Config  : {config_path}")
    print(f"  Ladder  : {' -> '.join(LADDER)}")
    print(f"  Start   : {LADDER[start_idx].capitalize()}")
    print(f"  Quick   : {QUICK_ROUNDS} rounds, {QUICK_TC}"
          f"{' (skipped)' if args.skip_quick else ''}")
    print(f"  Standard: {STANDARD_ROUNDS} rounds, {STANDARD_TC}")
    print("=" * 60)

    defeated_list = []
    stopped = False

    for i in range(start_idx, len(LADDER)):
        opponent = LADDER[i]

        passed, new_version, new_config_path, config_data = challenge_opponent(
            cutechess, base_dir, config_path, config_data, opponent,
            current_version, args.skip_quick,
        )

        if passed:
            defeated_list.append(opponent)
            current_version = new_version
            config_path = new_config_path
            continue

        print(f"\n>>> Calling auto_tune.py for optimization...")
        tune_ok = call_auto_tune(base_dir, config_path)
        if not tune_ok:
            print(f">>> auto_tune.py failed or not found. Stopping ladder.")
            stopped = True
            break

        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        current_version = config_data.get("version", current_version)

        print(f"\n{'=' * 60}")
        print(f"  Re-challenge: {opponent.capitalize()} (after tuning)")
        print(f"  Version: v{current_version}")
        print(f"{'=' * 60}")

        passed, new_version, new_config_path, config_data = challenge_opponent(
            cutechess, base_dir, config_path, config_data, opponent,
            current_version, args.skip_quick,
        )

        if passed:
            defeated_list.append(opponent)
            current_version = new_version
            config_path = new_config_path
            continue

        print(f"\n>>> Defeated by {opponent.capitalize()} after tuning. Ladder stopped.")
        stopped = True
        break

    print(f"\n{'=' * 60}")
    print("  Ladder Test Summary")
    print("=" * 60)
    print(f"  Final version: v{current_version}")
    print(f"  Config: {config_path}")
    if defeated_list:
        print(f"  Defeated opponents:")
        for opp in defeated_list:
            elo = OPPONENTS[opp]["elo"]
            print(f"    - {opp.capitalize()} (ELO ~{elo})")
    else:
        print(f"  No opponents defeated.")
    if stopped:
        next_opp = LADDER[start_idx + len(defeated_list)]
        print(f"  Stopped at: {next_opp.capitalize()} (ELO ~{OPPONENTS[next_opp]['elo']})")
    elif not stopped and len(defeated_list) == len(LADDER) - start_idx:
        print(f"  All opponents defeated!")
    print("=" * 60)


if __name__ == "__main__":
    main()
