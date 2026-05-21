"""
对弈测试管理器
支持标准规则对弈、过程记录、结果归档
"""
import os
import sys
import json
import subprocess
import shutil
import tempfile
import re
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
MATCH_RULES_DIR = BASE_DIR / "match_rules"
MATCH_RECORDS_DIR = BASE_DIR / "match_records"
STANDARD_RULE_FILE = MATCH_RULES_DIR / "standard_rule.json"


def load_standard_rule():
    if not STANDARD_RULE_FILE.exists():
        raise FileNotFoundError(f"标准规则文件不存在: {STANDARD_RULE_FILE}")
    with open(STANDARD_RULE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def create_match_folder(engine_a: str, engine_b: str, record_enabled: bool = True) -> Path:
    if not record_enabled:
        return None
    
    MATCH_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"{timestamp}-{engine_a}-{engine_b}"
    folder_path = MATCH_RECORDS_DIR / folder_name
    
    folder_path.mkdir(parents=True, exist_ok=True)
    
    (folder_path / "pgn").mkdir(exist_ok=True)
    (folder_path / "logs").mkdir(exist_ok=True)
    
    return folder_path


def create_temp_uci_adapter(temp_dir: Path, params_json_path: Path, label: str) -> Path:
    dest_params = temp_dir / "engine_params.json"
    from config import load_and_resolve_config
    resolved = load_and_resolve_config(str(params_json_path))
    with open(dest_params, "w", encoding="utf-8") as f:
        json.dump(resolved, f, indent=2)

    dest_params_fwd = str(dest_params).replace("\\", "/")
    base_dir_fwd = str(BASE_DIR).replace("\\", "/")
    script_path = BASE_DIR / f"_uci_engine_{label}.py"
    with open(script_path, "w", encoding="utf-8") as f:
        f.write("import os\n")
        f.write("import sys\n\n")
        f.write(f'os.environ["ENGINE_PARAMS"] = "{dest_params_fwd}"\n')
        f.write(f'sys.path.insert(0, "{base_dir_fwd}")\n\n')
        f.write("from uci_engine import UCIEngine\n\n")
        f.write('if __name__ == "__main__":\n')
        f.write("    uci = UCIEngine()\n")
        f.write("    uci.run()\n")
    
    return script_path


def find_cutechess() -> Path:
    candidates = [
        BASE_DIR / "cutechess-cli.exe",
        BASE_DIR / "cutechess-cli.EXE",
        Path("cutechess-cli"),
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("cutechess-cli not found")


def resolve_config(config_ref: str) -> Path:
    if Path(config_ref).is_absolute() and Path(config_ref).exists():
        return Path(config_ref)
    
    if config_ref.startswith("v") or config_ref.startswith("V"):
        version = config_ref.lower() if config_ref.startswith("V") else config_ref
        path = BASE_DIR / "configs" / f"{version}.json"
        if path.exists():
            return path
    
    path = BASE_DIR / "configs" / config_ref
    if path.exists():
        return path
    
    raise FileNotFoundError(f"Config not found: {config_ref}")


def run_match(
    engine_a: str,
    engine_b: str,
    rounds: int = None,
    tc: str = None,
    record_enabled: bool = True,
    rule_file: str = None
):
    if rule_file:
        rule_path = MATCH_RULES_DIR / rule_file if not Path(rule_file).is_absolute() else Path(rule_file)
        with open(rule_path, "r", encoding="utf-8") as f:
            rule = json.load(f)
        rounds = rounds or rule["rounds"]
        tc = tc or rule["time_control"]["tc_string"]
    else:
        rule = load_standard_rule()
        rounds = rounds or rule["rounds"]
        tc = tc or rule["time_control"]["tc_string"]
    
    config_a_path = resolve_config(engine_a)
    config_b_path = resolve_config(engine_b)
    
    record_folder = create_match_folder(engine_a, engine_b, record_enabled)
    
    temp_dir_a = Path(tempfile.mkdtemp(prefix="chess_match_a_"))
    temp_dir_b = Path(tempfile.mkdtemp(prefix="chess_match_b_"))
    
    script_a = create_temp_uci_adapter(temp_dir_a, config_a_path, "a")
    script_b = create_temp_uci_adapter(temp_dir_b, config_b_path, "b")
    
    cutechess = find_cutechess()
    python_exe = sys.executable or "python"
    
    pgn_file = record_folder / "pgn" / "match.pgn" if record_folder else BASE_DIR / "temp_match.pgn"
    
    cmd = [
        str(cutechess),
        "-engine", f"name={engine_a}", "proto=uci",
        f"cmd={python_exe}", f"arg={script_a}", f"dir={temp_dir_a}",
        "-engine", f"name={engine_b}", "proto=uci",
        f"cmd={python_exe}", f"arg={script_b}", f"dir={temp_dir_b}",
        "-each", f"tc={tc}",
        "-rounds", str(rounds),
        "-pgnout", str(pgn_file),
        "-repeat"
    ]
    
    print("=" * 60)
    print("对弈测试")
    print("=" * 60)
    print(f"引擎 A: {engine_a}")
    print(f"引擎 B: {engine_b}")
    print(f"轮数: {rounds}")
    print(f"时制: {tc}")
    print(f"记录目录: {record_folder if record_folder else '不记录'}")
    print("=" * 60)
    
    if record_folder:
        match_info = {
            "engine_a": engine_a,
            "engine_b": engine_b,
            "rounds": rounds,
            "time_control": tc,
            "start_time": datetime.now().isoformat(),
            "command": " ".join(cmd)
        }
        with open(record_folder / "match_info.json", "w", encoding="utf-8") as f:
            json.dump(match_info, f, indent=2, ensure_ascii=False)
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    
    wins = losses = draws = 0
    all_output = []
    
    for line in process.stdout:
        print(line.rstrip())
        all_output.append(line)
        match = re.search(r"Score.*?:\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)", line)
        if match:
            wins = int(match.group(1))
            losses = int(match.group(2))
            draws = int(match.group(3))
    
    process.wait()
    
    if record_folder:
        with open(record_folder / "logs" / "cutechess_output.txt", "w", encoding="utf-8") as f:
            f.writelines(all_output)
        
        total = wins + losses + draws
        win_rate = (wins + 0.5 * draws) / total if total > 0 else 0.5
        
        if win_rate == 0:
            elo = -1000
        elif win_rate == 1:
            elo = 1000
        else:
            from math import log
            elo = -400 * log((1 - win_rate) / win_rate) / log(10)
        
        result = {
            "engine_a": engine_a,
            "engine_b": engine_b,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "total": total,
            "win_rate": win_rate,
            "elo_diff": round(elo, 1),
            "end_time": datetime.now().isoformat()
        }
        with open(record_folder / "result.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        print(f"\n结果已保存到: {record_folder}")
    
    shutil.rmtree(temp_dir_a, ignore_errors=True)
    shutil.rmtree(temp_dir_b, ignore_errors=True)
    os.remove(script_a)
    os.remove(script_b)
    
    return wins, losses, draws


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="对弈测试管理器")
    parser.add_argument("--engine-a", required=True, help="引擎A配置 (如 v1.3.0)")
    parser.add_argument("--engine-b", required=True, help="引擎B配置 (如 shallowblue)")
    parser.add_argument("--rounds", type=int, help="对弈轮数 (默认使用标准规则)")
    parser.add_argument("--tc", help="时间控制 (如 96+0.8, 默认使用标准规则)")
    parser.add_argument("--no-record", action="store_true", help="不记录对弈过程")
    parser.add_argument("--rule", help="使用指定的规则文件")
    
    args = parser.parse_args()
    
    run_match(
        engine_a=args.engine_a,
        engine_b=args.engine_b,
        rounds=args.rounds,
        tc=args.tc,
        record_enabled=not args.no_record,
        rule_file=args.rule
    )


if __name__ == "__main__":
    main()
