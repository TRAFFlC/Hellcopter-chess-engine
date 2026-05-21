"""
循环赛锦标赛
自动收集 v1.4.0、v1.5.0 和所有候选版本进行两两循环赛
赛制: 11 rounds, 96+0.8s, 胜1分 平0.5分 负0分
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
from itertools import combinations

BASE_DIR = Path(__file__).parent.resolve()

BASE_VERSIONS = ["v1.4.0", "v1.5.0"]
ROUNDS = 11
TC = "96+0.8"


def collect_versions():
    configs_dir = BASE_DIR / "configs"
    versions = list(BASE_VERSIONS)

    candidate_nums = []
    for f in os.listdir(configs_dir):
        if f.startswith("candidate_") and f.endswith(".json"):
            try:
                num = int(f[10:-5])
                candidate_nums.append(num)
            except ValueError:
                pass

    for num in sorted(candidate_nums):
        versions.append(f"candidate_{num}")

    return versions


def create_temp_uci_adapter(temp_dir: Path, config_ref: str, label: str) -> Path:
    from config import load_and_resolve_config

    config_path = resolve_config_file(config_ref)
    resolved = load_and_resolve_config(str(config_path))

    dest_params = temp_dir / "engine_params.json"
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


def resolve_config_file(config_ref: str) -> Path:
    path = BASE_DIR / "configs" / f"{config_ref}.json"
    if path.exists():
        return path
    raise FileNotFoundError(f"Config not found: {config_ref}")


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


def run_match(engine_a: str, engine_b: str, rounds: int, tc: str):
    temp_dir_a = Path(tempfile.mkdtemp(prefix="chess_tournament_a_"))
    temp_dir_b = Path(tempfile.mkdtemp(prefix="chess_tournament_b_"))

    script_a = create_temp_uci_adapter(temp_dir_a, engine_a, "a")
    script_b = create_temp_uci_adapter(temp_dir_b, engine_b, "b")

    cutechess = find_cutechess()
    python_exe = sys.executable or "python"

    pgn_file = BASE_DIR / "tournament_temp.pgn"

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

    print(f"\n对局: {engine_a} vs {engine_b}")
    print("-" * 40)

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    wins = losses = draws = 0

    for line in process.stdout:
        print(line.rstrip())
        match = re.search(r"Score.*?:\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)", line)
        if match:
            wins = int(match.group(1))
            losses = int(match.group(2))
            draws = int(match.group(3))

    process.wait()

    shutil.rmtree(temp_dir_a, ignore_errors=True)
    shutil.rmtree(temp_dir_b, ignore_errors=True)
    try:
        os.remove(script_a)
        os.remove(script_b)
    except:
        pass

    return wins, losses, draws


def main():
    versions = collect_versions()

    print("=" * 60)
    print("Hellcopter 参数版本循环赛锦标赛")
    print("=" * 60)
    print(f"参赛版本: {', '.join(versions)}")
    print(f"版本数量: {len(versions)}")
    print(f"赛制: 两两循环赛")
    print(f"每场对弈: {ROUNDS} rounds")
    print(f"时间控制: {TC}")
    print(f"积分规则: 胜1分 平0.5分 负0分")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    scores = {v: 0.0 for v in versions}
    match_results = []

    matchups = list(combinations(versions, 2))
    total_matches = len(matchups)

    print(f"\n总对局数: {total_matches} 场")

    for i, (engine_a, engine_b) in enumerate(matchups, 1):
        print(f"\n[{i}/{total_matches}] ", end="")

        wins, losses, draws = run_match(engine_a, engine_b, ROUNDS, TC)

        score_a = wins + 0.5 * draws
        score_b = losses + 0.5 * draws

        scores[engine_a] += score_a
        scores[engine_b] += score_b

        match_results.append({
            "engine_a": engine_a,
            "engine_b": engine_b,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "score_a": score_a,
            "score_b": score_b
        })

        print(f"\n结果: {engine_a} {wins}-{draws}-{losses} {engine_b}")
        print(f"积分: {engine_a} +{score_a}, {engine_b} +{score_b}")

    print("\n" + "=" * 60)
    print("锦标赛结束")
    print("=" * 60)

    ranking = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    print("\n最终积分排行榜:")
    print("-" * 50)
    print(f"{'排名':<6}{'版本':<18}{'积分':<10}")
    print("-" * 50)

    for rank, (version, score) in enumerate(ranking, 1):
        print(f"{rank:<6}{version:<18}{score:<10.1f}")

    print("-" * 50)

    print(f"\n详细对局记录:")
    print("-" * 50)
    for m in match_results:
        print(f"{m['engine_a']} vs {m['engine_b']}: {m['wins']}-{m['draws']}-{m['losses']} "
              f"(积分: {m['score_a']:.1f} vs {m['score_b']:.1f})")

    results_file = BASE_DIR / "tournament_results.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump({
            "versions": versions,
            "rounds": ROUNDS,
            "time_control": TC,
            "scores": dict(scores),
            "ranking": ranking,
            "match_results": match_results,
            "end_time": datetime.now().isoformat()
        }, f, indent=2, ensure_ascii=False)

    print(f"\n结果已保存到: {results_file}")
    print(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
