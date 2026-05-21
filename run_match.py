import os
import sys
import argparse
import subprocess
import shutil
import platform
import json
import tempfile
from datetime import datetime


def resolve_config(base_dir, config_ref):
    if not config_ref:
        return None
    
    config_path = os.path.join(base_dir, "configs", f"{config_ref}.json")
    if os.path.isfile(config_path):
        return config_path
    
    if os.path.isfile(config_ref):
        return config_ref
    
    return None


def create_temp_uci_adapter(base_dir, config_path):
    from config import load_and_resolve_config
    
    temp_dir = tempfile.mkdtemp(prefix="hellcopter_match_")
    dest_params = os.path.join(temp_dir, "engine_params.json")
    
    resolved = load_and_resolve_config(config_path)
    with open(dest_params, "w", encoding="utf-8") as f:
        json.dump(resolved, f, indent=2)
    
    dest_params_fwd = dest_params.replace("\\", "/")
    base_dir_fwd = base_dir.replace("\\", "/")
    
    script_path = os.path.join(temp_dir, "uci_adapter.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write("import os\n")
        f.write("import sys\n\n")
        f.write(f'os.environ["ENGINE_PARAMS"] = "{dest_params_fwd}"\n')
        f.write(f'sys.path.insert(0, "{base_dir_fwd}")\n\n')
        f.write("from uci_engine import UCIEngine\n\n")
        f.write('if __name__ == "__main__":\n')
        f.write("    uci = UCIEngine()\n")
        f.write("    uci.run()\n")
    
    return script_path, temp_dir


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


def build_command(cutechess, base_dir, opp_exe, opp_proto, args, uci_script=None, openings_path=None):
    python_exe = sys.executable or "python"
    if uci_script is None:
        uci_script = os.path.join(base_dir, "uci_engine.py")
    
    engine_name = f"Hellcopter-{args.config}" if args.config else "Hellcopter"

    each_opts = [f"tc={args.tc}"]
    if args.inc and args.inc > 0:
        each_opts.append(f"inc={args.inc}")

    if args.pgnout:
        pgn_path = os.path.join(base_dir, args.pgnout)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        config_tag = args.config if args.config else "default"
        match_dir = os.path.join(base_dir, "match_records", f"{timestamp}-hellcopter-{config_tag}-{args.opponent}")
        os.makedirs(match_dir, exist_ok=True)
        pgn_path = os.path.join(match_dir, "match.pgn")

    cmd = [
        cutechess,
        "-engine",
        f"name={engine_name}",
        "proto=uci",
        f"cmd={python_exe}",
        f"arg={uci_script}",
        f"dir={os.path.dirname(uci_script) if uci_script else base_dir}",
        "-engine",
        f"name={args.opponent.capitalize()}",
        f"proto={opp_proto}",
        f"cmd={opp_exe}",
        "-each",
        ",".join(each_opts),
        "-rounds", str(args.rounds),
        "-pgnout", pgn_path,
    ]

    if openings_path:
        cmd.extend(["-openings", f"file={openings_path}"])

    if hasattr(args, 'sprt') and args.sprt:
        sprt_params = args.sprt
        sprt_str = f"elo0={sprt_params['elo0']},elo1={sprt_params['elo1']},alpha={sprt_params['alpha']},beta={sprt_params['beta']}"
        cmd.extend(["-sprt", sprt_str])

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


def parse_sprt(sprt_str):
    if not sprt_str:
        return None
    parts = sprt_str.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "SPRT format: elo0,elo1,alpha,beta (e.g. '0,5,0.05,0.05')"
        )
    try:
        return {
            "elo0": float(parts[0]),
            "elo1": float(parts[1]),
            "alpha": float(parts[2]),
            "beta": float(parts[3]),
        }
    except ValueError:
        raise argparse.ArgumentTypeError(
            "SPRT values must be numbers: elo0,elo1,alpha,beta"
        )


def resolve_time_control(args):
    if args.tc_standard:
        return "96+0.8"
    if args.tc_slow:
        return "300+2.0"
    return args.tc


def resolve_openings(base_dir, openings_arg):
    if not openings_arg:
        default_epd = os.path.join(base_dir, "openings.epd")
        if os.path.isfile(default_epd):
            return default_epd
        return None
    
    if os.path.isabs(openings_arg):
        return openings_arg
    
    path = os.path.join(base_dir, openings_arg)
    if os.path.isfile(path):
        return path
    
    return openings_arg


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(
        description="Run cutechess-cli match: Hellcopter vs opponent"
    )
    parser.add_argument("--opponent", type=str, default="monarch",
                        choices=list(OPPONENTS.keys()),
                        help="Opponent engine (monarch, apollo, rainman, shallowblue, tscp181, sargon, or absolute_zero)")
    parser.add_argument("--rounds", type=int, default=20,
                        help="Number of rounds (each round = 2 games with color swap)")
    parser.add_argument("--tc", type=str, default="96+0.8",
                        help="Time control string (e.g. 96+0.8, 60+2, 15/40)")
    parser.add_argument("--tc-standard", action="store_true",
                        help="Use standard time control: 96+0.8s")
    parser.add_argument("--tc-slow", action="store_true",
                        help="Use slow time control: 300+2.0s")
    parser.add_argument("--inc", type=int, default=0,
                        help="Increment in seconds (overrides tc increment)")
    parser.add_argument("--cutechess", type=str, default=None,
                        help="Path to cutechess-cli executable")
    parser.add_argument("--pgnout", type=str, default=None,
                        help="PGN output filename (default: auto-create in match_records/)")
    parser.add_argument("--openings", type=str, default=None,
                        help="Opening book file (EPD/PGN). Default: openings.epd if exists")
    parser.add_argument("--config", type=str, default=None,
                        help="Hellcopter config version (e.g. v1.5.0)")
    parser.add_argument("--sprt", type=parse_sprt, default=None,
                        help="SPRT test: elo0,elo1,alpha,beta (e.g. '0,5,0.05,0.05')")

    args = parser.parse_args()
    
    if args.tc_standard and args.tc_slow:
        print("Error: --tc-standard and --tc-slow are mutually exclusive")
        sys.exit(1)
    
    args.tc = resolve_time_control(args)

    cutechess, opp_exe, opp_proto = check_dependencies(base_dir, args.cutechess, args.opponent)

    uci_script = None
    temp_dir = None
    
    if args.config:
        config_path = resolve_config(base_dir, args.config)
        if config_path is None:
            print(f"Error: Config not found: {args.config}")
            sys.exit(1)
        print(f"Using config: {config_path}")
        uci_script, temp_dir = create_temp_uci_adapter(base_dir, config_path)

    openings_path = resolve_openings(base_dir, args.openings)
    if openings_path:
        print(f"Using openings: {openings_path}")

    cmd = build_command(cutechess, base_dir, opp_exe, opp_proto, args, uci_script, openings_path)

    returncode, output = run_cutechess(cmd)

    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)

    if returncode != 0:
        print(f"\ncutechess-cli exited with code {returncode}")

    run_elo_calc(base_dir, args.pgnout, output)


if __name__ == "__main__":
    main()
