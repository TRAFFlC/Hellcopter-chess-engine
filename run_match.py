import os
import sys
import argparse
import subprocess
import shutil
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


OPPONENTS = {
    "monarch": {
        "dir": "test_engines/Monarch 2005/Monarch(v1.7)",
        "exe": "Monarch(v1.7).exe",
        "proto": "uci",
    },
    "apollo": {
        "dir": "test_engines/Apollo 1663",
        "exe": "apollo.exe",
        "proto": "uci",
    },
    "rainman": {
        "dir": "test_engines/Rainman 1427",
        "exe": "rainman.exe",
        "proto": "xboard",
    },
    "shallowblue": {
        "dir": "test_engines/ShallowBlue 1575",
        "exe": "shallowblue.exe",
        "proto": "uci",
    },
    "pulsar": {
        "dir": "test_engines/Pulsar 1651",
        "exe": "pulsar2009-9b.exe",
        "proto": "xboard",
    },
    "tscp181": {
        "dir": "test_engines/TSCP 1607",
        "exe": "tscp181.exe",
        "proto": "xboard",
    },
    "sargon": {
        "dir": "test_engines/sargon 1163",
        "exe": "sargon-engine-static-link.exe",
        "proto": "uci",
    },
    "absolute_zero": {
        "dir": "test_engines/Absolute Zero 2284",
        "exe": "AbsoluteZero.exe",
        "proto": "uci",
    },
}


def check_dependencies(base_dir, cutechess_path, opponent_key):
    system = platform.system()
    if system == "Windows":
        dll_name = "engine_core.dll"
    elif system == "Darwin":
        dll_name = "engine_core.dylib"
    else:
        dll_name = "engine_core.so"

    dll_path = os.path.join(base_dir, dll_name)
    uci_path = os.path.join(base_dir, "uci_engine.py")

    opp = OPPONENTS[opponent_key]
    opp_exe = os.path.join(base_dir, opp["dir"], opp["exe"])

    missing = []

    if not os.path.isfile(dll_path):
        missing.append((dll_name, f"Expected at: {dll_path}"))

    if not os.path.isfile(uci_path):
        missing.append(("uci_engine.py", f"Expected at: {uci_path}"))

    if not os.path.isfile(opp_exe):
        missing.append((opp["exe"], f"Expected at: {opp_exe}"))

    cutechess = find_cutechess(cutechess_path, base_dir)
    if cutechess is None:
        missing.append((
            "cutechess-cli",
            "Not found in PATH or project directory.\n"
            "  Download from: https://github.com/cutechess/cutechess/releases\n"
            "  Then either add to PATH or place cutechess-cli.exe in the project directory."
        ))

    if missing:
        print("Error: missing dependencies:\n")
        for name, detail in missing:
            print(f"  - {name}: {detail}")
        print("\nPlease install missing dependencies and try again.")
        sys.exit(1)

    return cutechess, opp_exe, opp["proto"]


def build_command(cutechess, base_dir, opp_exe, opp_proto, args):
    python_exe = sys.executable or "python"
    uci_script = os.path.join(base_dir, "uci_engine.py")

    each_opts = [f"tc={args.tc}"]
    if args.inc and args.inc > 0:
        each_opts.append(f"inc={args.inc}")

    if args.pgnout:
        pgn_path = os.path.join(base_dir, args.pgnout)
    else:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        match_dir = os.path.join(base_dir, "match_records", f"{timestamp}-hellcopter-{args.opponent}")
        os.makedirs(match_dir, exist_ok=True)
        pgn_path = os.path.join(match_dir, "match.pgn")

    cmd = [
        cutechess,
        "-engine",
        "name=Hellcopter",
        "proto=uci",
        f"cmd={python_exe}",
        f"arg={uci_script}",
        f"dir={base_dir}",
        "-engine",
        f"name={args.opponent.capitalize()}",
        f"proto={opp_proto}",
        f"cmd={opp_exe}",
        "-each",
        ",".join(each_opts),
        "-rounds", str(args.rounds),
        "-pgnout", pgn_path,
    ]

    if args.openings:
        openings_path = os.path.join(base_dir, args.openings) if not os.path.isabs(args.openings) else args.openings
        cmd.extend(["-openings", f"file={openings_path}"])

    return cmd


def run_cutechess(cmd):
    print(f"Running command:\n{' '.join(cmd)}\n")
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
    return process.returncode, "\n".join(full_output)


def run_elo_calc(base_dir, pgn_file, match_output):
    import re

    elo_script = os.path.join(base_dir, "elo_calc.py")
    pgn_path = os.path.join(base_dir, pgn_file) if pgn_file else None

    pattern = re.compile(
        r"Score of\s+(.+?)\s+vs\s+(.+?):\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)"
    )

    wins = losses = draws = 0
    for line in match_output.splitlines():
        m = pattern.search(line)
        if m:
            wins = int(m.group(3))
            losses = int(m.group(4))
            draws = int(m.group(5))

    print("\n" + "=" * 60)
    print("MATCH RESULTS - Elo Calculation")
    print("=" * 60)

    if wins or losses or draws:
        try:
            result = subprocess.run(
                [sys.executable or "python", elo_script, str(wins), str(losses), str(draws)],
                capture_output=True,
                text=True,
                cwd=base_dir,
            )
            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
        except Exception as e:
            print(f"Error running elo_calc.py: {e}")
    elif pgn_path and os.path.isfile(pgn_path):
        try:
            result = subprocess.run(
                [sys.executable or "python", elo_script, "--file", pgn_path],
                capture_output=True,
                text=True,
                cwd=base_dir,
            )
            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
        except Exception as e:
            print(f"Error running elo_calc.py: {e}")
    else:
        print("No score data found in match output and no PGN file available.")


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(
        description="Run cutechess-cli match: Hellcopter vs opponent"
    )
    parser.add_argument("--opponent", type=str, default="monarch",
                        choices=list(OPPONENTS.keys()),
                        help="Opponent engine (monarch, apollo, rainman, shallowblue, pulsar, or tscp181)")
    parser.add_argument("--rounds", type=int, default=20,
                        help="Number of rounds (each round = 2 games with color swap)")
    parser.add_argument("--tc", type=str, default="60+2",
                        help="Time control string (e.g. 60+2, 15/40, 5+2)")
    parser.add_argument("--inc", type=int, default=0,
                        help="Increment in seconds (overrides tc increment)")
    parser.add_argument("--cutechess", type=str, default=None,
                        help="Path to cutechess-cli executable")
    parser.add_argument("--pgnout", type=str, default=None,
                        help="PGN output filename (default: auto-create in match_records/)")
    parser.add_argument("--openings", type=str, default=None,
                        help="Opening book file (EPD/PGN)")

    args = parser.parse_args()

    cutechess, opp_exe, opp_proto = check_dependencies(base_dir, args.cutechess, args.opponent)

    cmd = build_command(cutechess, base_dir, opp_exe, opp_proto, args)

    returncode, output = run_cutechess(cmd)

    if returncode != 0:
        print(f"\ncutechess-cli exited with code {returncode}")

    run_elo_calc(base_dir, args.pgnout, output)


if __name__ == "__main__":
    main()
