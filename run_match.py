import os
import sys
import platform
import argparse
import subprocess
import shutil
import json
import tempfile
import math
import re
from datetime import datetime

from match_utils import find_cutechess, create_temp_uci_adapter_with_env, calc_elo, calc_ci_wilson


def resolve_config(base_dir, config_ref):
    if not config_ref:
        return None
    config_path = os.path.join(base_dir, "configs", f"{config_ref}.json")
    if os.path.isfile(config_path):
        return config_path
    if os.path.isfile(config_ref):
        return config_ref
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


def check_base_deps(base_dir, cutechess_path):
    system = platform.system()
    dll_name = "engine_core.dll" if system == "Windows" else ("engine_core.dylib" if system == "Darwin" else "engine_core.so")
    dll_path = os.path.join(base_dir, dll_name)
    uci_path = os.path.join(base_dir, "uci_engine.py")
    missing = []
    if not os.path.isfile(dll_path):
        missing.append((dll_name, f"Expected at: {dll_path}"))
    if not os.path.isfile(uci_path):
        missing.append(("uci_engine.py", f"Expected at: {uci_path}"))
    cutechess = find_cutechess(cutechess_path, base_dir)
    if cutechess is None:
        missing.append(("cutechess-cli", "Not found in PATH or project directory."))
    return missing, cutechess


def check_dependencies(base_dir, cutechess_path, opponent_key):
    missing, cutechess = check_base_deps(base_dir, cutechess_path)
    opp = OPPONENTS[opponent_key]
    opp_exe = os.path.join(base_dir, opp["dir"], opp["exe"])
    if not os.path.isfile(opp_exe):
        missing.append((opp["exe"], f"Expected at: {opp_exe}"))
    if missing:
        print("Error: missing dependencies:\n")
        for name, detail in missing:
            print(f"  - {name}: {detail}")
        sys.exit(1)
    return cutechess, opp_exe, opp["proto"]


def check_dependencies_self(base_dir, cutechess_path):
    missing, cutechess = check_base_deps(base_dir, cutechess_path)
    if missing:
        print("Error: missing dependencies:\n")
        for name, detail in missing:
            print(f"  - {name}: {detail}")
        sys.exit(1)
    return cutechess


def make_each_opts(args):
    if args.nodes and args.nodes > 0:
        opts = [f"st=999999", f"nodes={args.nodes}"]
    else:
        opts = [f"tc={args.tc}"]
        if args.inc and args.inc > 0:
            opts.append(f"inc={args.inc}")
    return opts


def resolve_pgn_path(base_dir, args, suffix):
    if args.pgnout:
        return os.path.join(base_dir, args.pgnout)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    match_dir = os.path.join(base_dir, "match_records", f"{timestamp}-{suffix}")
    os.makedirs(match_dir, exist_ok=True)
    return os.path.join(match_dir, "match.pgn")


def add_sprt_args(cmd, args):
    if hasattr(args, 'sprt') and args.sprt:
        p = args.sprt
        cmd.extend(["-sprt", f"elo0={p['elo0']}", f"elo1={p['elo1']}", f"alpha={p['alpha']}", f"beta={p['beta']}"])


def add_adjudication(cmd):
    cmd.extend(["-draw", "movenumber=40", "movecount=5", "score=20"])
    cmd.extend(["-resign", "movecount=3", "score=500"])


def build_self_command(cutechess, base_dir, args, uci_script_a, uci_script_b, label_a, label_b):
    python_exe = sys.executable or "python"
    each_opts = make_each_opts(args)
    pgn_path = resolve_pgn_path(base_dir, args, f"self-{label_a}-{label_b}")

    cmd = [
        cutechess,
        "-engine",
        f"name=HellcopterA-{label_a}",
        "proto=uci",
        f"cmd={python_exe}",
        f"arg={uci_script_a}",
        f"dir={os.path.dirname(uci_script_a) if uci_script_a else base_dir}",
        "-engine",
        f"name=HellcopterB-{label_b}",
        "proto=uci",
        f"cmd={python_exe}",
        f"arg={uci_script_b}",
        f"dir={os.path.dirname(uci_script_b) if uci_script_b else base_dir}",
        "-each",
    ] + each_opts + [
        "-rounds", str(args.rounds),
        "-concurrency", str(args.concurrency),
        "-pgnout", pgn_path,
    ]
    add_adjudication(cmd)
    add_sprt_args(cmd, args)
    return cmd


def build_command(cutechess, base_dir, opp_exe, opp_proto, args, uci_script=None, openings_path=None):
    python_exe = sys.executable or "python"
    if uci_script is None:
        uci_script = os.path.join(base_dir, "uci_engine.py")

    engine_name = f"Hellcopter-{args.config}" if args.config else "Hellcopter"
    each_opts = make_each_opts(args)

    config_tag = args.config if args.config else "default"
    pgn_path = resolve_pgn_path(base_dir, args, f"hellcopter-{config_tag}-{args.opponent}")

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
    ] + each_opts + [
        "-rounds", str(args.rounds),
        "-concurrency", str(args.concurrency),
        "-pgnout", pgn_path,
    ]

    if openings_path:
        cmd.extend(["-openings", f"file={openings_path}"])
    add_adjudication(cmd)
    add_sprt_args(cmd, args)
    return cmd, pgn_path


def run_cutechess(cmd):
    print(f"Running command:\n{' '.join(cmd)}\n")
    print("=" * 60)
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    full_output = []
    for line in process.stdout:
        stripped = line.rstrip()
        print(stripped, flush=True)
        full_output.append(stripped)
    process.wait()
    return process.returncode, "\n".join(full_output)


def print_match_results(match_output, pgn_path):
    pattern = re.compile(r"Score of\s+(.+?)\s+vs\s+(.+?):\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)")
    wins = losses = draws = 0
    name_a = name_b = ""
    for line in match_output.splitlines():
        m = pattern.search(line)
        if m:
            name_a, name_b = m.group(1).strip(), m.group(2).strip()
            wins, losses, draws = int(m.group(3)), int(m.group(4)), int(m.group(5))
    total = wins + losses + draws
    if total == 0:
        print("No games played.")
        return None
    result = calc_elo(wins, losses, draws)
    ci_low, ci_high = calc_ci_wilson(total, wins, draws)
    print()
    print("=" * 60)
    print(f"  {name_a} vs {name_b}")
    print("=" * 60)
    print(f"  Total games : {total}")
    print(f"  Wins (A)    : {wins}")
    print(f"  Losses (A)  : {losses}")
    print(f"  Draws       : {draws}")
    if result:
        _, p, elo_diff = result
        print(f"  Win rate    : {p:.4f} ({p*100:.2f}%)")
        if not math.isinf(elo_diff):
            print(f"  Elo diff    : {elo_diff:+.2f}")
        else:
            print(f"  Elo diff    : {'+Inf' if elo_diff > 0 else '-Inf'} (dominates)")
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
    if pgn_path:
        print(f"  PGN: {pgn_path}")
        print("=" * 60)
    return {"name_a": name_a, "name_b": name_b, "wins": wins, "losses": losses, "draws": draws, "total": total}


def parse_sprt(sprt_str):
    if not sprt_str:
        return None
    parts = sprt_str.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("SPRT format: elo0,elo1,alpha,beta (e.g. '0,5,0.05,0.05')")
    try:
        return {"elo0": float(parts[0]), "elo1": float(parts[1]), "alpha": float(parts[2]), "beta": float(parts[3])}
    except ValueError:
        raise argparse.ArgumentTypeError("SPRT values must be numbers: elo0,elo1,alpha,beta")


def resolve_time_control(args):
    if args.tc_standard:
        return "96+0.8"
    if args.tc_slow:
        return "300+2.0"
    return args.tc


def resolve_openings(base_dir, openings_arg):
    if not openings_arg:
        default_epd = os.path.join(base_dir, "openings.epd")
        return default_epd if os.path.isfile(default_epd) else None
    if os.path.isabs(openings_arg):
        return openings_arg
    path = os.path.join(base_dir, openings_arg)
    return path if os.path.isfile(path) else openings_arg


def config_label(config_path):
    """Extract a short label from a config path (e.g. 'v1.9.5' from 'configs\\v1.9.5.json')."""
    base = os.path.splitext(os.path.basename(config_path))[0]
    return base.replace("v", "").replace(".", "")


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(description="Run cutechess-cli match")
    parser.add_argument("--mode", type=str, default="external", choices=["external", "self"],
                        help="external: Hellcopter vs opponent (default). self: Hellcopter A vs Hellcopter B")
    parser.add_argument("--opponent", type=str, default="monarch", choices=list(OPPONENTS.keys()),
                        help="Opponent engine (external mode)")
    parser.add_argument("--config-a", type=str, default=None,
                        help="Config for Hellcopter A (self-play mode)")
    parser.add_argument("--config-b", type=str, default=None,
                        help="Config for Hellcopter B (self-play mode)")
    parser.add_argument("--rounds", type=int, default=20,
                        help="Number of rounds (each round = 2 games with color swap)")
    parser.add_argument("--tc", type=str, default="96+0.8",
                        help="Time control string (e.g. 96+0.8, 60+2)")
    parser.add_argument("--tc-standard", action="store_true", help="Use standard time control: 96+0.8s")
    parser.add_argument("--tc-slow", action="store_true", help="Use slow time control: 300+2.0s")
    parser.add_argument("--nodes", type=int, default=0, help="Node limit per move (0 = disabled, fixed-node testing)")
    parser.add_argument("--concurrency", type=int, default=1, help="Number of concurrent games")
    parser.add_argument("--inc", type=int, default=0, help="Increment in seconds (overrides tc increment)")
    parser.add_argument("--cutechess", type=str, default=None, help="Path to cutechess-cli executable")
    parser.add_argument("--pgnout", type=str, default=None, help="PGN output filename")
    parser.add_argument("--openings", type=str, default=None, help="Opening book file (EPD/PGN)")
    parser.add_argument("--config", type=str, default=None, help="Hellcopter config version (external mode)")
    parser.add_argument("--sprt", type=parse_sprt, default=None,
                        help="SPRT test: elo0,elo1,alpha,beta (e.g. '0,5,0.05,0.05')")

    args = parser.parse_args()
    if args.tc_standard and args.tc_slow:
        print("Error: --tc-standard and --tc-slow are mutually exclusive")
        sys.exit(1)
    args.tc = resolve_time_control(args)

    if args.mode == "self":
        if not args.config_a or not args.config_b:
            print("Error: --config-a and --config-b are required in --mode self")
            sys.exit(1)
        cutechess = check_dependencies_self(base_dir, args.cutechess)
        config_a_path = resolve_config(base_dir, args.config_a)
        config_b_path = resolve_config(base_dir, args.config_b)
        if not config_a_path:
            print(f"Error: Config A not found: {args.config_a}"); sys.exit(1)
        if not config_b_path:
            print(f"Error: Config B not found: {args.config_b}"); sys.exit(1)
        label_a = config_label(config_a_path)
        label_b = config_label(config_b_path)
        print(f"Self-play: A={config_a_path} (label={label_a}) vs B={config_b_path} (label={label_b})")
        uci_script_a, temp_dir_a = create_temp_uci_adapter_with_env(base_dir, config_a_path, label="self_a")
        uci_script_b, temp_dir_b = create_temp_uci_adapter_with_env(base_dir, config_b_path, label="self_b")
        cmd = build_self_command(cutechess, base_dir, args, uci_script_a, uci_script_b, label_a, label_b)
        returncode, output = run_cutechess(cmd)
        shutil.rmtree(temp_dir_a, ignore_errors=True)
        shutil.rmtree(temp_dir_b, ignore_errors=True)
        print_match_results(output, None)
    else:
        cutechess, opp_exe, opp_proto = check_dependencies(base_dir, args.cutechess, args.opponent)
        uci_script = None
        temp_dir = None
        if args.config:
            config_path = resolve_config(base_dir, args.config)
            if config_path is None:
                print(f"Error: Config not found: {args.config}")
                sys.exit(1)
            print(f"Using config: {config_path}")
            uci_script, temp_dir = create_temp_uci_adapter_with_env(base_dir, config_path)
        openings_path = resolve_openings(base_dir, args.openings)
        if openings_path:
            print(f"Using openings: {openings_path}")
        cmd, pgn_path = build_command(cutechess, base_dir, opp_exe, opp_proto, args, uci_script, openings_path)
        returncode, output = run_cutechess(cmd)
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
        print_match_results(output, pgn_path)

    if returncode != 0:
        print(f"\ncutechess-cli exited with code {returncode}")
        sys.exit(returncode)


if __name__ == "__main__":
    main()