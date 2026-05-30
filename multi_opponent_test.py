import os
import sys
import argparse
import subprocess
import shutil
import platform
import json
import tempfile
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed


OPPONENTS = {
    "sargon": {
        "dir": "test_engines/sargon 1163",
        "exe": "sargon-engine-static-link.exe",
        "proto": "uci",
        "elo": 1163,
    },
    "rainman": {
        "dir": "test_engines/Rainman 1427",
        "exe": "rainman.exe",
        "proto": "xboard",
        "elo": 1427,
    },
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
    "monarch": {
        "dir": "test_engines/Monarch 2005/Monarch(v1.7)",
        "exe": "Monarch(v1.7).exe",
        "proto": "uci",
        "elo": 2005,
    },
    "absolute_zero": {
        "dir": "test_engines/Absolute Zero 2284",
        "exe": "AbsoluteZero.exe",
        "proto": "uci",
        "elo": 2284,
    },
    "velvet": {
        "dir": "test_engines/Velvet",
        "exe": "velvet-v8.1.1-x86_64-avx2.exe",
        "proto": "uci",
        "elo": 2500,
    },
    "stockfish": {
        "dir": "test_engines/Stockfish/src",
        "exe": "stockfish.exe",
        "proto": "uci",
        "elo": 3200,
    },
}


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
        return None

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


def check_engine_exists(base_dir, opponent_key):
    opp = OPPONENTS[opponent_key]
    opp_exe = os.path.join(base_dir, opp["dir"], opp["exe"])
    return os.path.isfile(opp_exe), opp_exe


def build_command(cutechess, base_dir, opp_exe, opp_proto, opponent_key, args, uci_script=None):
    python_exe = sys.executable or "python"
    if uci_script is None:
        uci_script = os.path.join(base_dir, "uci_engine.py")
    
    engine_name = f"Hellcopter-{args.config}" if args.config else "Hellcopter"

    each_opts = [f"tc={args.tc}"]
    if args.inc and args.inc > 0:
        each_opts.append(f"inc={args.inc}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    config_tag = args.config if args.config else "default"
    match_dir = os.path.join(base_dir, "match_records", f"{timestamp}-hellcopter-{config_tag}-vs-{opponent_key}")
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
        f"name={opponent_key.capitalize()}",
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

    return cmd, pgn_path


def run_single_match(cutechess, base_dir, opponent_key, args, uci_script=None):
    exists, opp_exe = check_engine_exists(base_dir, opponent_key)
    if not exists:
        return opponent_key, None, None, f"Engine not found: {opp_exe}"
    
    opp = OPPONENTS[opponent_key]
    opp_proto = opp["proto"]
    
    cmd, pgn_path = build_command(cutechess, base_dir, opp_exe, opp_proto, opponent_key, args, uci_script)
    
    print(f"\n{'='*60}")
    print(f"Testing vs {opponent_key.upper()} (Elo ~{opp['elo']})")
    print(f"{'='*60}")
    print(f"Command: {' '.join(cmd)}")
    
    try:
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
        
        pattern = re.compile(
            r"Score of\s+(.+?)\s+vs\s+(.+?):\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)"
        )
        
        wins = losses = draws = 0
        for line in output.splitlines():
            m = pattern.search(line)
            if m:
                wins = int(m.group(3))
                losses = int(m.group(4))
                draws = int(m.group(5))
        
        return opponent_key, (wins, losses, draws), pgn_path, None
        
    except Exception as e:
        return opponent_key, None, None, str(e)


def calc_elo(wins, losses, draws):
    import math
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


def save_results(base_dir, results, args, config_path):
    import math
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    config_tag = args.config if args.config else "default"
    
    results_dir = os.path.join(base_dir, "match_records", f"{timestamp}-multi-opponent-{config_tag}")
    os.makedirs(results_dir, exist_ok=True)
    
    summary = {
        "timestamp": timestamp,
        "config": args.config or "default",
        "config_path": config_path,
        "time_control": args.tc,
        "rounds_per_opponent": args.rounds,
        "results": {},
        "summary": {
            "total_games": 0,
            "total_wins": 0,
            "total_losses": 0,
            "total_draws": 0,
            "average_elo_diff": 0,
        }
    }
    
    total_elo_diff = 0
    valid_elo_count = 0
    
    for opp_key, score, pgn_path, error in results:
        opp_info = OPPONENTS.get(opp_key, {})
        
        if error:
            summary["results"][opp_key] = {
                "opponent_elo": opp_info.get("elo", "unknown"),
                "error": error,
                "status": "failed"
            }
        elif score:
            wins, losses, draws = score
            elo_result = calc_elo(wins, losses, draws)
            
            if elo_result:
                total, p, elo_diff = elo_result
                summary["results"][opp_key] = {
                    "opponent_elo": opp_info.get("elo", "unknown"),
                    "wins": wins,
                    "losses": losses,
                    "draws": draws,
                    "total_games": total,
                    "win_rate": round(p, 4),
                    "elo_diff": round(elo_diff, 2) if not math.isinf(elo_diff) else str(elo_diff),
                    "pgn_file": pgn_path,
                    "status": "completed"
                }
                
                summary["summary"]["total_games"] += total
                summary["summary"]["total_wins"] += wins
                summary["summary"]["total_losses"] += losses
                summary["summary"]["total_draws"] += draws
                
                if not math.isinf(elo_diff):
                    total_elo_diff += elo_diff
                    valid_elo_count += 1
            else:
                summary["results"][opp_key] = {
                    "opponent_elo": opp_info.get("elo", "unknown"),
                    "error": "No games played",
                    "status": "failed"
                }
    
    if valid_elo_count > 0:
        summary["summary"]["average_elo_diff"] = round(total_elo_diff / valid_elo_count, 2)
    
    results_file = os.path.join(results_dir, "results.json")
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    return results_file, summary


def print_summary(summary):
    print("\n" + "=" * 70)
    print("MULTI-OPPONENT TEST SUMMARY")
    print("=" * 70)
    print(f"Config: {summary['config']}")
    print(f"Time Control: {summary['time_control']}")
    print(f"Rounds per opponent: {summary['rounds_per_opponent']}")
    print("-" * 70)
    
    print(f"{'Opponent':<15} {'Elo':<8} {'W-D-L':<15} {'Win%':<8} {'Elo Diff':<10}")
    print("-" * 70)
    
    for opp_key, result in summary["results"].items():
        if result["status"] == "completed":
            wdl = f"{result['wins']}-{result['draws']}-{result['losses']}"
            win_pct = f"{result['win_rate']*100:.1f}%"
            elo_diff = result['elo_diff']
            if isinstance(elo_diff, (int, float)):
                elo_str = f"{elo_diff:+.1f}"
            else:
                elo_str = elo_diff
            print(f"{opp_key:<15} {result['opponent_elo']:<8} {wdl:<15} {win_pct:<8} {elo_str:<10}")
        else:
            print(f"{opp_key:<15} {result['opponent_elo']:<8} ERROR: {result.get('error', 'Unknown')}")
    
    print("-" * 70)
    s = summary["summary"]
    print(f"TOTAL: {s['total_games']} games | {s['total_wins']}-{s['total_draws']}-{s['total_losses']}")
    if s['average_elo_diff']:
        print(f"Average Elo difference: {s['average_elo_diff']:+.2f}")
    print("=" * 70)


def main():
    import math
    
    base_dir = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(
        description="Run batch matches: Hellcopter vs multiple opponents"
    )
    parser.add_argument("--config", type=str, default=None,
                        help="Hellcopter config version (e.g. v1.5.0)")
    parser.add_argument("--opponents", type=str, default="sargon,rainman,shallowblue,tscp181,apollo",
                        help="Comma-separated list of opponents")
    parser.add_argument("--rounds", type=int, default=5,
                        help="Number of rounds per opponent")
    parser.add_argument("--tc", type=str, default="10+0.1",
                        help="Time control string (e.g. 60+2, 15/40, 5+2)")
    parser.add_argument("--inc", type=int, default=0,
                        help="Increment in seconds (overrides tc increment)")
    parser.add_argument("--cutechess", type=str, default=None,
                        help="Path to cutechess-cli executable")
    parser.add_argument("--openings", type=str, default=None,
                        help="Opening book file (EPD/PGN)")
    parser.add_argument("--parallel", type=int, default=1,
                        help="Number of parallel matches (default: 1, sequential)")

    args = parser.parse_args()

    opponent_list = [o.strip().lower() for o in args.opponents.split(",")]
    
    invalid_opponents = [o for o in opponent_list if o not in OPPONENTS]
    if invalid_opponents:
        print(f"Error: Unknown opponents: {invalid_opponents}")
        print(f"Available opponents: {list(OPPONENTS.keys())}")
        sys.exit(1)

    cutechess = find_cutechess(args.cutechess, base_dir)
    if cutechess is None:
        print("Error: cutechess-cli not found.")
        print("Download from: https://github.com/cutechess/cutechess/releases")
        sys.exit(1)

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
        print("Please run build_engine.py first.")
        sys.exit(1)

    uci_script = None
    temp_dir = None
    config_path = None
    
    if args.config:
        config_path = resolve_config(base_dir, args.config)
        if config_path is None:
            print(f"Error: Config not found: {args.config}")
            sys.exit(1)
        print(f"Using config: {config_path}")
        uci_script, temp_dir = create_temp_uci_adapter(base_dir, config_path)

    print(f"\nMulti-Opponent Test Configuration:")
    print(f"  Opponents: {opponent_list}")
    print(f"  Rounds per opponent: {args.rounds}")
    print(f"  Time control: {args.tc}")
    print(f"  Parallel matches: {args.parallel}")
    
    results = []
    
    for opponent_key in opponent_list:
        result = run_single_match(cutechess, base_dir, opponent_key, args, uci_script)
        results.append(result)

    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)

    results_file, summary = save_results(base_dir, results, args, config_path)
    
    print_summary(summary)
    print(f"\nResults saved to: {results_file}")


if __name__ == "__main__":
    main()
