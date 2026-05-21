#!/usr/bin/env python3
"""
迭代对弈分析脚本 - 运行对弈并自动分析败着

功能：
1. 运行 Hellcopter 与对手的对弈
2. 如果有失败对局，自动调用 Velvet 分析败着
3. 生成分析报告保存到 match_records 目录
4. 输出改进建议
"""

import os
import sys
import argparse
import subprocess
import re
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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


def find_cutechess(cli_path, base_dir):
    import shutil
    import platform
    
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


def check_dependencies(base_dir, cutechess_path, opponent_key):
    import platform
    
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


def find_velvet_engine(base_dir):
    velvet_dir = os.path.join(base_dir, "test_engines", "Velvet")
    if os.path.isdir(velvet_dir):
        for f in os.listdir(velvet_dir):
            if f.startswith("velvet") and (f.endswith(".exe") or not f.endswith(".txt")):
                return os.path.join(velvet_dir, f)
    return None


@dataclass
class MatchResult:
    wins: int = 0
    losses: int = 0
    draws: int = 0
    total: int = 0
    pgn_path: str = ""
    match_dir: str = ""
    output: str = ""


def parse_match_result(output: str) -> tuple:
    pattern = re.compile(
        r"Score of\s+(.+?)\s+vs\s+(.+?):\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)"
    )
    
    for line in output.splitlines():
        m = pattern.search(line)
        if m:
            wins = int(m.group(3))
            losses = int(m.group(4))
            draws = int(m.group(5))
            return wins, losses, draws
    return 0, 0, 0


def build_command(cutechess, base_dir, opp_exe, opp_proto, args, pgn_path):
    python_exe = sys.executable or "python"
    uci_script = os.path.join(base_dir, "uci_engine.py")

    each_opts = [f"tc={args.tc}"]
    if args.inc and args.inc > 0:
        each_opts.append(f"inc={args.inc}")

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


def run_velvet_analyze(base_dir, pgn_path, output_path, velvet_path, depth=20, time_limit=0.5):
    velvet_script = os.path.join(base_dir, "velvet_analyze.py")
    
    if not os.path.isfile(velvet_script):
        print(f"错误: velvet_analyze.py 不存在: {velvet_script}")
        return None
    
    cmd = [
        sys.executable or "python",
        velvet_script,
        "--pgn", pgn_path,
        "--output", output_path,
        "--depth", str(depth),
        "--time", str(time_limit),
        "--engine", velvet_path,
    ]
    
    print(f"\n{'=' * 60}")
    print("调用 Velvet 分析败着...")
    print(f"{'=' * 60}")
    print(f"PGN文件: {pgn_path}")
    print(f"分析深度: {depth}")
    print(f"每步时间: {time_limit}秒")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=base_dir,
        )
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        
        if os.path.isfile(output_path):
            with open(output_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None
    except Exception as e:
        print(f"分析失败: {e}")
        return None


def generate_improvement_suggestions(analysis_data):
    if not analysis_data:
        return []
    
    suggestions = []
    
    total_blunders = sum(len(game.get("blunders", [])) for game in analysis_data)
    missed_mates = sum(
        1 for game in analysis_data 
        for b in game.get("blunders", []) 
        if b.get("error_type") == "漏杀"
    )
    big_blunders = sum(
        1 for game in analysis_data 
        for b in game.get("blunders", []) 
        if b.get("error_type") == "重大失误"
    )
    mistakes = sum(
        1 for game in analysis_data 
        for b in game.get("blunders", []) 
        if b.get("error_type") == "失误"
    )
    
    if missed_mates > 0:
        suggestions.append({
            "priority": "最高",
            "category": "搜索问题",
            "issue": f"发现 {missed_mates} 次漏杀",
            "suggestion": "检查杀棋搜索逻辑，可能需要增加搜索深度或改进静态交换评估",
            "details": []
        })
    
    if big_blunders > 0:
        suggestions.append({
            "priority": "高",
            "category": "评估/搜索问题",
            "issue": f"发现 {big_blunders} 次重大失误(>300分)",
            "suggestion": "检查评估函数和搜索剪枝逻辑，重大失误通常意味着评估偏差或剪枝错误",
            "details": []
        })
    
    if mistakes > 0:
        suggestions.append({
            "priority": "中",
            "category": "搜索深度问题",
            "issue": f"发现 {mistakes} 次失误(100-300分)",
            "suggestion": "考虑增加搜索深度或改进移动排序以减少剪枝错误",
            "details": []
        })
    
    move_issues = {}
    for game in analysis_data:
        for blunder in game.get("blunders", []):
            uci_move = blunder.get("uci_move", "")
            san_move = blunder.get("san_move", "")
            vel_best = blunder.get("velvet_best_move", "")
            score_diff = blunder.get("score_diff", 0)
            
            if vel_best and uci_move != vel_best:
                key = f"{san_move} -> 应走 {vel_best}"
                if key not in move_issues:
                    move_issues[key] = {
                        "count": 0,
                        "total_loss": 0,
                        "positions": []
                    }
                move_issues[key]["count"] += 1
                move_issues[key]["total_loss"] += abs(score_diff)
                move_issues[key]["positions"].append(blunder.get("fen_before", ""))
    
    for move_issue, data in sorted(move_issues.items(), key=lambda x: -x[1]["total_loss"]):
        if data["count"] >= 2:
            suggestions.append({
                "priority": "高",
                "category": "重复错误",
                "issue": f"重复错误: {move_issue} (出现{data['count']}次)",
                "suggestion": f"累计损失 {data['total_loss']} 分，需要重点修复此类型的着法选择",
                "details": data["positions"][:3]
            })
    
    return suggestions


def print_suggestions(suggestions):
    if not suggestions:
        print("\n未发现需要改进的问题，表现良好！")
        return
    
    print("\n" + "=" * 60)
    print("改进建议")
    print("=" * 60)
    
    priority_order = {"最高": 0, "高": 1, "中": 2, "低": 3}
    sorted_suggestions = sorted(suggestions, key=lambda x: priority_order.get(x["priority"], 99))
    
    for i, sug in enumerate(sorted_suggestions, 1):
        print(f"\n{i}. 【{sug['priority']}优先级】{sug['category']}")
        print(f"   问题: {sug['issue']}")
        print(f"   建议: {sug['suggestion']}")
        if sug.get("details"):
            print(f"   示例局面:")
            for j, detail in enumerate(sug["details"][:2], 1):
                print(f"     {j}. {detail[:60]}...")


def run_elo_calc(base_dir, wins, losses, draws):
    elo_script = os.path.join(base_dir, "elo_calc.py")
    
    print("\n" + "=" * 60)
    print("MATCH RESULTS - Elo Calculation")
    print("=" * 60)
    
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


def run_match_with_analysis(base_dir, args):
    cutechess, opp_exe, opp_proto = check_dependencies(base_dir, args.cutechess, args.opponent)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    match_dir = os.path.join(base_dir, "match_records", f"{timestamp}-hellcopter-{args.opponent}")
    os.makedirs(match_dir, exist_ok=True)
    pgn_path = os.path.join(match_dir, "match.pgn")
    
    cmd = build_command(cutechess, base_dir, opp_exe, opp_proto, args, pgn_path)
    
    returncode, output = run_cutechess(cmd)
    
    if returncode != 0:
        print(f"\ncutechess-cli exited with code {returncode}")
    
    wins, losses, draws = parse_match_result(output)
    total = wins + losses + draws
    
    print(f"\n对弈结果: {wins}胜 - {losses}负 - {draws}平 (共{total}局)")
    
    run_elo_calc(base_dir, wins, losses, draws)
    
    analysis_data = None
    suggestions = []
    
    if losses > 0 and os.path.isfile(pgn_path):
        velvet_path = args.velvet_engine or find_velvet_engine(base_dir)
        
        if velvet_path and os.path.isfile(velvet_path):
            analysis_path = os.path.join(match_dir, "analysis.json")
            analysis_data = run_velvet_analyze(
                base_dir,
                pgn_path,
                analysis_path,
                velvet_path,
                depth=args.analyze_depth,
                time_limit=args.analyze_time
            )
            
            if analysis_data:
                suggestions = generate_improvement_suggestions(analysis_data)
                print_suggestions(suggestions)
                
                suggestions_path = os.path.join(match_dir, "suggestions.json")
                with open(suggestions_path, "w", encoding="utf-8") as f:
                    json.dump(suggestions, f, ensure_ascii=False, indent=2)
                print(f"\n改进建议已保存到: {suggestions_path}")
        else:
            print("\n警告: 未找到Velvet引擎，跳过败着分析")
            print(f"请将Velvet引擎放置到 {os.path.join(base_dir, 'test_engines', 'Velvet')} 目录")
    
    summary = {
        "timestamp": timestamp,
        "opponent": args.opponent,
        "rounds": args.rounds,
        "time_control": args.tc,
        "results": {
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "total": total
        },
        "pgn_file": pgn_path,
        "analysis_file": os.path.join(match_dir, "analysis.json") if analysis_data else None,
        "suggestions_count": len(suggestions)
    }
    
    summary_path = os.path.join(match_dir, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    print(f"\n对弈摘要已保存到: {summary_path}")
    
    return {
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "total": total,
        "pgn_path": pgn_path,
        "match_dir": match_dir,
        "analysis": analysis_data,
        "suggestions": suggestions
    }


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    parser = argparse.ArgumentParser(
        description="迭代对弈分析: 运行对弈并自动分析败着"
    )
    parser.add_argument("--opponent", type=str, default="tscp181",
                        choices=list(OPPONENTS.keys()),
                        help="对手引擎 (monarch, apollo, rainman, shallowblue, tscp181, sargon, absolute_zero)")
    parser.add_argument("--rounds", type=int, default=5,
                        help="对弈轮数 (每轮=2局，交换先后手)")
    parser.add_argument("--tc", type=str, default="96+0.8",
                        help="时间控制 (如 60+2, 15/40, 5+2)")
    parser.add_argument("--inc", type=int, default=0,
                        help="时间增量(秒)，覆盖tc中的增量")
    parser.add_argument("--cutechess", type=str, default=None,
                        help="cutechess-cli 可执行文件路径")
    parser.add_argument("--openings", type=str, default=None,
                        help="开局库文件 (EPD/PGN)")
    parser.add_argument("--velvet-engine", type=str, default=None,
                        help="Velvet引擎路径 (默认自动查找)")
    parser.add_argument("--analyze-depth", type=int, default=20,
                        help="败着分析深度 (默认20)")
    parser.add_argument("--analyze-time", type=float, default=0.5,
                        help="每步分析时间(秒) (默认0.5)")
    
    args = parser.parse_args()
    
    result = run_match_with_analysis(base_dir, args)
    
    print("\n" + "=" * 60)
    print("对弈完成")
    print("=" * 60)
    print(f"结果目录: {result['match_dir']}")
    print(f"PGN文件: {result['pgn_path']}")
    if result.get('analysis'):
        print(f"分析报告: {os.path.join(result['match_dir'], 'analysis.json')}")
    print(f"战绩: {result['wins']}胜 - {result['losses']}负 - {result['draws']}平")


if __name__ == "__main__":
    main()
