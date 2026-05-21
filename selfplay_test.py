#!/usr/bin/env python3
"""
Hellcopter 自对弈测试脚本
让两个不同版本的 Hellcopter 互相对弈
"""

import os
import sys
import subprocess
import tempfile
import shutil
import argparse
from datetime import datetime


def create_uci_adapter(base_dir, config_path, version_name):
    dest_params = config_path
    
    dest_params_fwd = dest_params.replace("\\", "/")
    base_dir_fwd = base_dir.replace("\\", "/")
    
    temp_dir = tempfile.mkdtemp(prefix=f"hellcopter_{version_name}_")
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


def run_selfplay(config1, config2, rounds, tc, base_dir):
    config1_path = os.path.join(base_dir, "configs", f"{config1}.json")
    config2_path = os.path.join(base_dir, "configs", f"{config2}.json")
    
    if not os.path.exists(config1_path):
        print(f"Error: Config not found: {config1_path}")
        return None
    if not os.path.exists(config2_path):
        print(f"Error: Config not found: {config2_path}")
        return None
    
    script1, temp1 = create_uci_adapter(base_dir, config1_path, config1.replace(".", "_"))
    script2, temp2 = create_uci_adapter(base_dir, config2_path, config2.replace(".", "_"))
    
    python_exe = sys.executable
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    match_dir = os.path.join(base_dir, "match_records", f"{timestamp}-selfplay-{config1}-vs-{config2}")
    os.makedirs(match_dir, exist_ok=True)
    pgn_path = os.path.join(match_dir, "match.pgn")
    
    cutechess = shutil.which("cutechess-cli")
    if not cutechess:
        cutechess = os.path.join(base_dir, "cutechess-cli.exe")
    if not os.path.exists(cutechess):
        print("Error: cutechess-cli not found")
        return None
    
    cmd = [
        cutechess,
        "-engine",
        f"name=Hellcopter-{config1}",
        "proto=uci",
        f"cmd={python_exe}",
        f"arg={script1}",
        f"dir={os.path.dirname(script1)}",
        "-engine",
        f"name=Hellcopter-{config2}",
        "proto=uci",
        f"cmd={python_exe}",
        f"arg={script2}",
        f"dir={os.path.dirname(script2)}",
        "-each",
        f"tc={tc}",
        "-rounds", str(rounds),
        "-pgnout", pgn_path,
    ]
    
    print(f"Running self-play: {config1} vs {config2}")
    print(f"Rounds: {rounds}, Time control: {tc}")
    print(f"Command: {' '.join(cmd)}")
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
    
    shutil.rmtree(temp1, ignore_errors=True)
    shutil.rmtree(temp2, ignore_errors=True)
    
    output = "\n".join(full_output)
    
    import re
    pattern = re.compile(r"Score of\s+.+?:\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)")
    last_match = None
    for line in output.splitlines():
        m = pattern.search(line)
        if m:
            last_match = m
    
    if last_match:
        wins = int(last_match.group(1))
        losses = int(last_match.group(2))
        draws = int(last_match.group(3))
        
        total = wins + losses + draws
        if total > 0:
            score = (wins + 0.5 * draws) / total
            if 0 < score < 1:
                elo = -400 * __import__("math").log10((1 - score) / score)
            else:
                elo = 1000.0 if score >= 1 else -1000.0
        else:
            elo = 0.0
        
        print("\n" + "=" * 60)
        print("SELF-PLAY RESULTS")
        print("=" * 60)
        print(f"{config1} vs {config2}")
        print(f"Wins: {wins}, Losses: {losses}, Draws: {draws}")
        print(f"Win rate: {100 * (wins + 0.5 * draws) / total:.1f}%")
        print(f"Elo difference: {elo:+.1f}")
        
        return {
            "config1": config1,
            "config2": config2,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "elo_diff": elo,
            "pgn_path": pgn_path
        }
    
    return None


def main():
    parser = argparse.ArgumentParser(description="Hellcopter self-play test")
    parser.add_argument("--config1", default="v1.7.0", help="First config version")
    parser.add_argument("--config2", default="v1.4.0", help="Second config version")
    parser.add_argument("--rounds", type=int, default=20, help="Number of rounds")
    parser.add_argument("--tc", default="96+0.8", help="Time control")
    
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    result = run_selfplay(args.config1, args.config2, args.rounds, args.tc, base_dir)
    
    if result:
        result_path = os.path.join(base_dir, "tuning_logs", f"selfplay_{args.config1}_vs_{args.config2}.json")
        os.makedirs(os.path.dirname(result_path), exist_ok=True)
        with open(result_path, "w", encoding="utf-8") as f:
            import json
            json.dump(result, f, indent=2)
        print(f"\nResult saved to: {result_path}")


if __name__ == "__main__":
    main()
