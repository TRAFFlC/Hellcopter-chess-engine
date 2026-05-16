import os
import sys
import argparse
import subprocess
import shutil
import tempfile
import re
import json
import math
import platform


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


def resolve_config(config_arg, base_dir):
    if os.path.isfile(config_arg):
        return os.path.abspath(config_arg)

    version = config_arg.lstrip("v")
    config_path = os.path.join(base_dir, "configs", f"v{version}.json")
    if os.path.isfile(config_path):
        return config_path

    config_path = os.path.join(base_dir, "configs", f"{config_arg}.json")
    if os.path.isfile(config_path):
        return config_path

    print(f"Error: Config not found: {config_arg}")
    print(f"  Tried: configs/v{version}.json")
    print(f"  Tried: configs/{config_arg}.json")
    sys.exit(1)


def check_engine_dll(base_dir):
    system = platform.system()
    if system == "Windows":
        dll_name = "engine_core.dll"
    elif system == "Darwin":
        dll_name = "engine_core.dylib"
    else:
        dll_name = "engine_core.so"

    dll_path = os.path.join(base_dir, dll_name)
    if not os.path.isfile(dll_path):
        print(f"Error: Engine DLL not found: {dll_path}")
        print("Please run 'python build_engine.py' first to compile the engine.")
        sys.exit(1)
    return dll_path


def create_temp_uci_adapter(temp_dir, params_json_path, base_dir, label):
    dest_params = os.path.join(temp_dir, "engine_params.json")
    shutil.copy2(params_json_path, dest_params)

    script_path = os.path.join(base_dir, f"_uci_engine_{label}.py")
    base_dir_escaped = base_dir.replace("\\", "\\\\")

    with open(script_path, "w", encoding="utf-8") as f:
        f.write("import os\n")
        f.write("import sys\n\n")
        f.write("sys.path.insert(0, r\"" + base_dir_escaped + "\")\n\n")
        f.write("from uci_engine import UCIEngine\n\n")
        f.write("if __name__ == \"__main__\":\n")
        f.write("    uci = UCIEngine()\n")
        f.write("    uci.run()\n")

    return script_path


def calc_elo(wins, losses, draws):
    total = wins + losses + draws
    if total == 0:
        return None
    p = (wins + 0.5 * draws) / total
    if p == 0:
        elo_diff = float("-inf")
    elif p == 1:
        elo_diff = float("inf")
    else:
        elo_diff = -400 * math.log10(1 / p - 1)
    return total, p, elo_diff


def calc_ci_wilson(total, wins, draws, confidence=0.95):
    if total == 0:
        return None, None
    z = 1.96 if confidence == 0.95 else 2.576
    p_hat = (wins + 0.5 * draws) / total
    denominator = 1 + z ** 2 / total
    centre = (p_hat + z ** 2 / (2 * total)) / denominator
    margin = z * math.sqrt((p_hat * (1 - p_hat) + z ** 2 / (4 * total)) / total) / denominator
    p_low = max(0, centre - margin)
    p_high = min(1, centre + margin)

    def p_to_elo(p):
        if p <= 0.0001:
            return -800
        if p >= 0.9999:
            return 800
        return -400 * math.log10(1 / p - 1)

    elo_low = p_to_elo(p_low)
    elo_high = p_to_elo(p_high)
    return elo_low, elo_high


def parse_match_output(output):
    pattern = re.compile(
        r"Score of\s+(.+?)\s+vs\s+(.+?):\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)"
    )
    for line in output.splitlines():
        m = pattern.search(line)
        if m:
            return m.group(1).strip(), m.group(2).strip(), int(m.group(3)), int(m.group(4)), int(m.group(5))
    return None


def print_results(name_a, name_b, wins, losses, draws):
    result = calc_elo(wins, losses, draws)
    if result is None:
        print("No games played.")
        return

    total, p, elo_diff = result
    ci_low, ci_high = calc_ci_wilson(total, wins, draws)

    print()
    print("=" * 60)
    print(f"  {name_a} vs {name_b}")
    print("=" * 60)
    print(f"  Total games : {total}")
    print(f"  Wins (A)    : {wins}")
    print(f"  Losses (A)  : {losses}")
    print(f"  Draws       : {draws}")
    print(f"  Win rate    : {p:.4f} ({p * 100:.2f}%)")
    if math.isinf(elo_diff):
        if elo_diff > 0:
            print("  Elo diff    : +Inf (A dominates)")
        else:
            print("  Elo diff    : -Inf (B dominates)")
    else:
        print(f"  Elo diff    : {elo_diff:+.2f}")
    if ci_low is not None and ci_high is not None:
        print(f"  95% CI      : [{ci_low:+.2f}, {ci_high:+.2f}]")

    if total < 30:
        print("  Note: Very small sample (< 30 games). Results NOT reliable.")
    elif total < 100:
        print("  Note: Small sample (< 100 games). Results may not be reliable.")
    elif total < 500:
        print("  Note: Moderate sample. Consider more games for higher confidence.")
    else:
        print("  Note: Sample size sufficient for reasonable confidence.")
    print("=" * 60)


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(
        description="Self-play parameter tuning tool for Hellcopter chess engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tune_params.py --config-a v1.0.0 --config-b v1.3.0
  python tune_params.py --config-a configs/v1.0.0.json --config-b configs/v1.3.0.json
  python tune_params.py --config-a v1.0.0 --config-b v1.3.0 --rounds 201 --tc 5+0.1
        """
    )
    parser.add_argument("--config-a", required=True,
                        help="Config A: version (e.g. v1.0.0) or JSON file path")
    parser.add_argument("--config-b", required=True,
                        help="Config B: version (e.g. v1.3.0) or JSON file path")
    parser.add_argument("--rounds", type=int, default=101,
                        help="Number of rounds (default: 101)")
    parser.add_argument("--tc", type=str, default="9+0.1",
                        help='Time control string (default: "9+0.1")')
    parser.add_argument("--cutechess", type=str, default=None,
                        help="Path to cutechess-cli executable")
    parser.add_argument("--openings", type=str, default=None,
                        help="Opening book file (EPD/PGN)")
    parser.add_argument("--pgnout", type=str, default="tune_results.pgn",
                        help="PGN output filename (default: tune_results.pgn)")
    parser.add_argument("--no-repeat", action="store_true",
                        help="Disable color-swap repeat (each round plays both sides by default)")

    args = parser.parse_args()

    config_a_path = resolve_config(args.config_a, base_dir)
    config_b_path = resolve_config(args.config_b, base_dir)

    with open(config_a_path, "r", encoding="utf-8") as f:
        config_a = json.load(f)
    with open(config_b_path, "r", encoding="utf-8") as f:
        config_b = json.load(f)

    name_a = f"Hellcopter-{config_a.get('version', 'A')}"
    name_b = f"Hellcopter-{config_b.get('version', 'B')}"

    print("=" * 60)
    print("  Self-Play Parameter Tuning")
    print("=" * 60)
    print(f"  Config A: {name_a}")
    desc_a = config_a.get("description", "")
    if desc_a:
        print(f"           {desc_a}")
    print(f"           {config_a_path}")
    print(f"  Config B: {name_b}")
    desc_b = config_b.get("description", "")
    if desc_b:
        print(f"           {desc_b}")
    print(f"           {config_b_path}")
    print(f"  Rounds  : {args.rounds}")
    print(f"  TC      : {args.tc}")
    print("=" * 60)

    check_engine_dll(base_dir)

    temp_dir_a = tempfile.mkdtemp(prefix="chess_tune_a_")
    temp_dir_b = tempfile.mkdtemp(prefix="chess_tune_b_")
    script_a = None
    script_b = None

    try:
        script_a = create_temp_uci_adapter(temp_dir_a, config_a_path, base_dir, "a")
        script_b = create_temp_uci_adapter(temp_dir_b, config_b_path, base_dir, "b")

        cutechess = find_cutechess(args.cutechess, base_dir)
        if cutechess is None:
            print("Error: cutechess-cli not found in PATH or project directory.")
            print("  Download from: https://github.com/cutechess/cutechess/releases")
            sys.exit(1)

        python_exe = sys.executable or "python"

        cmd = [
            cutechess,
            "-engine",
            f"name={name_a}",
            "proto=uci",
            f"cmd={python_exe}",
            f"arg={script_a}",
            f"dir={temp_dir_a}",
            "-engine",
            f"name={name_b}",
            "proto=uci",
            f"cmd={python_exe}",
            f"arg={script_b}",
            f"dir={temp_dir_b}",
            "-each",
            f"tc={args.tc}",
            "-rounds", str(args.rounds),
            "-pgnout", os.path.join(base_dir, args.pgnout),
        ]

        if not args.no_repeat:
            cmd.append("-repeat")

        if args.openings:
            openings_path = args.openings if os.path.isabs(args.openings) else os.path.join(base_dir, args.openings)
            cmd.extend(["-openings", f"file={openings_path}"])

        print(f"\nRunning command:\n{' '.join(cmd)}\n")
        print("=" * 60)

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
            print(stripped, flush=True)
            full_output.append(stripped)

        process.wait()
        output = "\n".join(full_output)

        if process.returncode != 0:
            print(f"\ncutechess-cli exited with code {process.returncode}")

        result = parse_match_output(output)
        if result:
            _, _, wins, losses, draws = result
            print_results(name_a, name_b, wins, losses, draws)
        else:
            print("\nFailed to parse match results from cutechess-cli output.")
            pgn_path = os.path.join(base_dir, args.pgnout)
            if os.path.isfile(pgn_path):
                print(f"PGN file saved at: {pgn_path}")
                print("You can analyze it manually or with elo_calc.py --file")

    finally:
        for script in (script_a, script_b):
            if script and os.path.exists(script):
                try:
                    os.remove(script)
                except OSError:
                    pass
        for temp_dir in (temp_dir_a, temp_dir_b):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except OSError:
                pass


if __name__ == "__main__":
    main()
