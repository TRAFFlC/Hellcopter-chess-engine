import os
import sys
import argparse
import subprocess
import shutil
import tempfile
import json

from match_utils import (
    find_cutechess,
    resolve_config,
    check_engine_dll,
    create_temp_uci_adapter,
    parse_match_output,
    print_results,
)


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
