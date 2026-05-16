import os
import sys
import tempfile
import shutil
import subprocess
import re
from datetime import datetime

base_dir = os.path.dirname(os.path.abspath(__file__))

VERSIONS = ["v1.0.0", "v1.0.1", "v1.1.0", "v1.2.0"]
CHAMPION = "v1.3.0"
ROUNDS = 11
TC = "9+0.1"

def create_temp_uci_adapter(temp_dir, params_json_path, label):
    dest_params = os.path.join(temp_dir, "engine_params.json")
    shutil.copy2(params_json_path, dest_params)
    
    script_path = os.path.join(base_dir, f"_uci_engine_{label}.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write("import os\n")
        f.write("import sys\n\n")
        f.write(f'sys.path.insert(0, r"{base_dir}")\n\n')
        f.write("from uci_engine import UCIEngine\n\n")
        f.write('if __name__ == "__main__":\n')
        f.write("    uci = UCIEngine()\n")
        f.write("    uci.run()\n")
    
    return script_path

def find_cutechess():
    candidates = [
        os.path.join(base_dir, "cutechess-cli.exe"),
        os.path.join(base_dir, "cutechess-cli.EXE"),
        "cutechess-cli",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError("cutechess-cli not found")

def resolve_config(config_ref):
    if os.path.isabs(config_ref) and os.path.exists(config_ref):
        return config_ref
    if config_ref.startswith("v") or config_ref.startswith("V"):
        version = config_ref.lower() if config_ref.startswith("V") else config_ref
        path = os.path.join(base_dir, "configs", f"{version}.json")
        if os.path.exists(path):
            return path
    path = os.path.join(base_dir, "configs", config_ref)
    if os.path.exists(path):
        return path
    raise FileNotFoundError(f"Config not found: {config_ref}")

def run_match(challenger, champion, rounds, tc):
    challenger_path = resolve_config(challenger)
    champion_path = resolve_config(champion)
    
    temp_dir_challenger = tempfile.mkdtemp(prefix="chess_tune_challenger_")
    temp_dir_champion = tempfile.mkdtemp(prefix="chess_tune_champion_")
    
    script_challenger = create_temp_uci_adapter(temp_dir_challenger, challenger_path, "challenger")
    script_champion = create_temp_uci_adapter(temp_dir_champion, champion_path, "champion")
    
    cutechess = find_cutechess()
    python_exe = sys.executable or "python"
    
    cmd = [
        cutechess,
        "-engine", f"name={challenger}", "proto=uci",
        f"cmd={python_exe}", f"arg={script_challenger}", f"dir={temp_dir_challenger}",
        "-engine", f"name={champion}", "proto=uci",
        f"cmd={python_exe}", f"arg={script_champion}", f"dir={temp_dir_champion}",
        "-each", f"tc={tc}",
        "-rounds", str(rounds),
        "-pgnout", os.path.join(base_dir, "tournament_results.pgn"),
        "-repeat"
    ]
    
    print(f"\n{'='*60}")
    print(f"挑战赛: {challenger} vs {champion} (擂主)")
    print(f"{'='*60}")
    
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    wins = losses = draws = 0
    
    for line in process.stdout:
        print(line.rstrip())
        match = re.search(r"Score.*?:\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)", line)
        if match:
            wins = int(match.group(1))
            losses = int(match.group(2))
            draws = int(match.group(3))
    
    process.wait()
    
    shutil.rmtree(temp_dir_challenger, ignore_errors=True)
    shutil.rmtree(temp_dir_champion, ignore_errors=True)
    os.remove(script_challenger)
    os.remove(script_champion)
    
    total = wins + losses + draws
    win_rate = (wins + 0.5 * draws) / total if total > 0 else 0.5
    
    if win_rate == 0:
        elo = -1000
    elif win_rate == 1:
        elo = 1000
    else:
        elo = -400 * (1 / win_rate - 1) / (1 / win_rate + 1) if win_rate < 0.5 else 400 * (win_rate / (1 - win_rate) - 1) / (win_rate / (1 - win_rate) + 1)
    
    return wins, losses, draws, elo, win_rate

def main():
    print("="*60)
    print("Hellcopter 参数版本擂台赛")
    print("="*60)
    print(f"初始擂主: {CHAMPION}")
    print(f"挑战者: {', '.join(VERSIONS)}")
    print(f"每场对弈: {ROUNDS}局, 时间控制: {TC}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    current_champion = CHAMPION
    match_history = []
    
    for challenger in VERSIONS:
        print(f"\n{'#'*60}")
        print(f"当前擂主: {current_champion}")
        print(f"挑战者: {challenger}")
        print(f"{'#'*60}")
        
        wins, losses, draws, elo, win_rate = run_match(challenger, current_champion, ROUNDS, TC)
        
        total = wins + losses + draws
        result = {
            "challenger": challenger,
            "champion": current_champion,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "elo": elo,
            "win_rate": win_rate
        }
        match_history.append(result)
        
        print(f"\n结果: {challenger} vs {current_champion}")
        print(f"  胜-负-和: {wins}-{losses}-{draws}")
        print(f"  胜率: {win_rate*100:.1f}%")
        print(f"  Elo差值: {elo:+.1f}")
        
        if win_rate > 0.55:
            print(f"\n*** {challenger} 击败擂主 {current_champion}，成为新擂主！***")
            current_champion = challenger
        else:
            print(f"\n*** {current_champion} 成功卫冕！***")
    
    print("\n" + "="*60)
    print("擂台赛结束")
    print("="*60)
    print(f"\n最终擂主: {current_champion}")
    print(f"\n比赛历史:")
    print("-"*50)
    for i, r in enumerate(match_history, 1):
        status = "挑战成功" if r["win_rate"] > 0.55 else "卫冕成功"
        print(f"第{i}场: {r['challenger']} vs {r['champion']}")
        print(f"       {r['wins']}-{r['losses']}-{r['draws']} (胜率{r['win_rate']*100:.1f}%) - {status}")
    
    print(f"\n完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    return current_champion

if __name__ == "__main__":
    main()
