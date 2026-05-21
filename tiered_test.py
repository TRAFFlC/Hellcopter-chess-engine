#!/usr/bin/env python3
"""
分层测试框架 - 渐进式验证引擎改进

测试层级：
- 快速 (fast): 48s+0.4s, 8轮, 确认小幅提升
- 标准 (standard): 96s+0.8s, 11轮, 主要验证
- 深度 (deep): 300s+2.0s, 21轮, 最终验证
"""

import os
import sys
import json
import argparse
import subprocess
import shutil
import tempfile
import re
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict

BASE_DIR = Path(__file__).parent.resolve()
CONFIGS_DIR = BASE_DIR / "configs"
MATCH_RECORDS_DIR = BASE_DIR / "match_records"
VELVET_ANALYZE_SCRIPT = BASE_DIR / "velvet_analyze.py"

TIERS = {
    "fast": {
        "name": "快速",
        "tc": "48+0.4",
        "rounds": 8,
        "threshold": 0.40,
        "description": "确认小幅提升",
    },
    "standard": {
        "name": "标准",
        "tc": "96+0.8",
        "rounds": 11,
        "threshold": 0.45,
        "description": "主要验证",
    },
    "deep": {
        "name": "深度",
        "tc": "300+2.0",
        "rounds": 21,
        "threshold": 0.50,
        "description": "最终验证",
    },
}

TIER_ORDER = ["quick", "fast", "standard"]

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


@dataclass
class TierResult:
    tier: str
    wins: int = 0
    losses: int = 0
    draws: int = 0
    win_rate: float = 0.0
    passed: bool = False
    message: str = ""
    pgn_path: Optional[str] = None


@dataclass
class TestReport:
    config: str
    opponent: str
    start_time: str = ""
    end_time: str = ""
    full_mode: bool = False
    results: List[TierResult] = field(default_factory=list)
    final_status: str = ""
    final_message: str = ""


def find_cutechess(cli_path: Optional[str] = None) -> Path:
    if cli_path:
        if Path(cli_path).is_file():
            return Path(cli_path)
        raise FileNotFoundError(f"指定的cutechess-cli路径不存在: {cli_path}")
    
    found = shutil.which("cutechess-cli")
    if found:
        return Path(found)
    
    candidates = [
        BASE_DIR / "cutechess-cli.exe",
        BASE_DIR / "cutechess-cli",
        BASE_DIR / "cutechess" / "cutechess-cli.exe",
        BASE_DIR / "cutechess" / "cutechess-cli",
    ]
    
    if sys.platform == "win32":
        program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        candidates.extend([
            Path(program_files) / "cutechess-cli" / "cutechess-cli.exe",
            Path(program_files_x86) / "cutechess-cli" / "cutechess-cli.exe",
        ])
    else:
        candidates.extend([
            Path("/usr/local/bin/cutechess-cli"),
            Path("/usr/bin/cutechess-cli"),
        ])
    
    for c in candidates:
        if c.is_file():
            return c
    
    raise FileNotFoundError(
        "cutechess-cli未找到。\n"
        "  请从 https://github.com/cutechess/cutechess/releases 下载\n"
        "  然后添加到PATH或放置在项目目录中。"
    )


def resolve_config(config_ref: str) -> Path:
    if Path(config_ref).is_absolute() and Path(config_ref).exists():
        return Path(config_ref)
    
    if config_ref.startswith("v") or config_ref.startswith("V"):
        version = config_ref.lower() if config_ref.startswith("V") else config_ref
        path = CONFIGS_DIR / f"{version}.json"
        if path.exists():
            return path
    
    path = CONFIGS_DIR / config_ref
    if path.exists():
        return path
    
    raise FileNotFoundError(f"配置文件不存在: {config_ref}")


def get_opponent_path(opponent_key: str) -> Tuple[Path, str]:
    if opponent_key not in OPPONENTS:
        raise ValueError(f"未知对手: {opponent_key}。可用对手: {', '.join(OPPONENTS.keys())}")
    
    opp = OPPONENTS[opponent_key]
    opp_exe = BASE_DIR / opp["dir"] / opp["exe"]
    
    if not opp_exe.is_file():
        raise FileNotFoundError(f"对手引擎不存在: {opp_exe}")
    
    return opp_exe, opp["proto"]


def create_temp_uci_adapter(temp_dir: Path, params_json_path: Path, label: str) -> Path:
    dest_params = temp_dir / "engine_params.json"
    shutil.copy2(params_json_path, dest_params)
    
    script_path = BASE_DIR / f"_uci_engine_tiered_{label}.py"
    with open(script_path, "w", encoding="utf-8") as f:
        f.write("import os\n")
        f.write("import sys\n\n")
        f.write(f'sys.path.insert(0, r"{BASE_DIR}")\n\n')
        f.write("from uci_engine import UCIEngine\n\n")
        f.write('if __name__ == "__main__":\n')
        f.write("    uci = UCIEngine()\n")
        f.write("    uci.run()\n")
    
    return script_path


def run_single_tier(
    config_path: Path,
    opponent_exe: Path,
    opponent_proto: str,
    opponent_name: str,
    tier_key: str,
    cutechess_path: Path,
    record_dir: Optional[Path] = None,
) -> Tuple[int, int, int, Optional[Path]]:
    tier = TIERS[tier_key]
    tc = tier["tc"]
    rounds = tier["rounds"]
    
    temp_dir = Path(tempfile.mkdtemp(prefix=f"chess_tiered_{tier_key}_"))
    script_path = create_temp_uci_adapter(temp_dir, config_path, tier_key)
    
    python_exe = sys.executable or "python"
    
    if record_dir:
        pgn_path = record_dir / f"{tier_key}.pgn"
    else:
        pgn_path = temp_dir / "match.pgn"
    
    cmd = [
        str(cutechess_path),
        "-engine",
        "name=Hellcopter",
        "proto=uci",
        f"cmd={python_exe}",
        f"arg={script_path}",
        f"dir={temp_dir}",
        "-engine",
        f"name={opponent_name}",
        f"proto={opponent_proto}",
        f"cmd={opponent_exe}",
        "-each",
        f"tc={tc}",
        "-rounds", str(rounds),
        "-pgnout", str(pgn_path),
        "-repeat",
    ]
    
    print(f"\n{'='*60}")
    print(f"运行 {tier['name']} 测试 ({tier_key})")
    print(f"{'='*60}")
    print(f"时间控制: {tc}")
    print(f"轮数: {rounds}")
    print(f"阈值: {tier['threshold']*100:.0f}%")
    print(f"{'='*60}\n")
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
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
    
    shutil.rmtree(temp_dir, ignore_errors=True)
    if script_path.exists():
        script_path.unlink()
    
    actual_pgn = pgn_path if pgn_path.exists() else None
    
    return wins, losses, draws, actual_pgn


def calculate_win_rate(wins: int, losses: int, draws: int) -> float:
    total = wins + losses + draws
    if total == 0:
        return 0.0
    return (wins + 0.5 * draws) / total


def calculate_elo(win_rate: float) -> float:
    if win_rate <= 0 or win_rate >= 1:
        return 0.0
    from math import log
    return -400 * log((1 - win_rate) / win_rate) / log(10)


def evaluate_tier_result(tier_key: str, win_rate: float) -> Tuple[bool, str]:
    tier = TIERS[tier_key]
    threshold = tier["threshold"]
    
    if win_rate < threshold:
        if tier_key == "quick":
            return False, "修改可能有大问题"
        elif tier_key == "fast":
            return False, "需要进一步验证"
        else:
            return False, "改进不显著"
    else:
        if tier_key == "standard":
            return True, "改进验证成功"
        else:
            return True, f"通过{tier['name']}测试，进入下一层级"


def run_velvet_analysis(pgn_path: Path, output_dir: Path) -> Optional[Path]:
    if not VELVET_ANALYZE_SCRIPT.exists():
        print(f"\n警告: velvet_analyze.py 不存在，跳过失败分析")
        return None
    
    analysis_output = output_dir / "velvet_analysis.json"
    
    print(f"\n{'='*60}")
    print("运行 Velvet 分析失败对局...")
    print(f"{'='*60}\n")
    
    cmd = [
        sys.executable or "python",
        str(VELVET_ANALYZE_SCRIPT),
        "--pgn", str(pgn_path),
        "--output", str(analysis_output),
        "--depth", "18",
        "--time", "0.3",
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.stdout:
            print(result.stdout)
        if result.returncode == 0 and analysis_output.exists():
            return analysis_output
    except subprocess.TimeoutExpired:
        print("Velvet 分析超时")
    except Exception as e:
        print(f"Velvet 分析失败: {e}")
    
    return None


def print_tier_result(result: TierResult):
    tier = TIERS[result.tier]
    total = result.wins + result.losses + result.draws
    elo = calculate_elo(result.win_rate)
    
    status_icon = "✓" if result.passed else "✗"
    status_color = "通过" if result.passed else "失败"
    
    print(f"\n{'='*60}")
    print(f"{tier['name']} 测试结果")
    print(f"{'='*60}")
    print(f"胜-负-和: {result.wins}-{result.losses}-{result.draws} (共{total}局)")
    print(f"胜率: {result.win_rate*100:.1f}%")
    print(f"Elo差值: {elo:+.1f}")
    print(f"状态: {status_icon} {status_color}")
    print(f"信息: {result.message}")
    print(f"{'='*60}")


def print_final_report(report: TestReport):
    print(f"\n{'#'*60}")
    print("分层测试汇总报告")
    print(f"{'#'*60}")
    print(f"配置版本: {report.config}")
    print(f"对手引擎: {report.opponent}")
    print(f"测试模式: {'完整流程' if report.full_mode else '单层级'}")
    print(f"开始时间: {report.start_time}")
    print(f"结束时间: {report.end_time}")
    print(f"\n{'-'*50}")
    print("各层级结果:")
    print(f"{'-'*50}")
    
    for result in report.results:
        tier = TIERS[result.tier]
        status = "✓ 通过" if result.passed else "✗ 失败"
        print(f"\n{tier['name']} ({result.tier}):")
        print(f"  胜-负-和: {result.wins}-{result.losses}-{result.draws}")
        print(f"  胜率: {result.win_rate*100:.1f}% (阈值: {tier['threshold']*100:.0f}%)")
        print(f"  状态: {status}")
        print(f"  信息: {result.message}")
    
    print(f"\n{'-'*50}")
    print(f"最终状态: {report.final_status}")
    print(f"结论: {report.final_message}")
    print(f"{'#'*60}")


def save_report_json(report: TestReport, output_path: Path):
    data = {
        "config": report.config,
        "opponent": report.opponent,
        "start_time": report.start_time,
        "end_time": report.end_time,
        "full_mode": report.full_mode,
        "results": [
            {
                "tier": r.tier,
                "tier_name": TIERS[r.tier]["name"],
                "wins": r.wins,
                "losses": r.losses,
                "draws": r.draws,
                "win_rate": r.win_rate,
                "threshold": TIERS[r.tier]["threshold"],
                "passed": r.passed,
                "message": r.message,
                "pgn_path": str(r.pgn_path) if r.pgn_path else None,
            }
            for r in report.results
        ],
        "final_status": report.final_status,
        "final_message": report.final_message,
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"\n报告已保存到: {output_path}")


def run_tiered_test(
    config: str,
    opponent: str,
    tier: Optional[str] = None,
    full: bool = False,
    cutechess_path: Optional[str] = None,
) -> TestReport:
    config_path = resolve_config(config)
    opponent_exe, opponent_proto = get_opponent_path(opponent)
    cutechess = find_cutechess(cutechess_path)
    
    report = TestReport(
        config=config,
        opponent=opponent,
        start_time=datetime.now().isoformat(),
        full_mode=full,
    )
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    record_dir = MATCH_RECORDS_DIR / f"{timestamp}-tiered-{config}-{opponent}"
    record_dir.mkdir(parents=True, exist_ok=True)
    
    if full:
        tiers_to_run = TIER_ORDER
    else:
        tiers_to_run = [tier] if tier else ["standard"]
    
    failed_pgn = None
    
    for tier_key in tiers_to_run:
        wins, losses, draws, pgn_path = run_single_tier(
            config_path,
            opponent_exe,
            opponent_proto,
            opponent,
            tier_key,
            cutechess,
            record_dir,
        )
        
        win_rate = calculate_win_rate(wins, losses, draws)
        passed, message = evaluate_tier_result(tier_key, win_rate)
        
        result = TierResult(
            tier=tier_key,
            wins=wins,
            losses=losses,
            draws=draws,
            win_rate=win_rate,
            passed=passed,
            message=message,
            pgn_path=str(pgn_path) if pgn_path else None,
        )
        
        report.results.append(result)
        print_tier_result(result)
        
        if not passed:
            failed_pgn = pgn_path
            report.final_status = "失败"
            report.final_message = message
            break
    else:
        report.final_status = "成功"
        report.final_message = "所有测试层级通过"
    
    report.end_time = datetime.now().isoformat()
    
    if failed_pgn and failed_pgn.exists():
        velvet_output = run_velvet_analysis(failed_pgn, record_dir)
        if velvet_output:
            print(f"\nVelvet 分析报告: {velvet_output}")
    
    report_json_path = record_dir / "tiered_report.json"
    save_report_json(report, report_json_path)
    
    print_final_report(report)
    
    return report


def main():
    parser = argparse.ArgumentParser(
        description="分层测试框架 - 渐进式验证引擎改进",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
测试层级:
  quick    最快测试 (12s+0.1s, 5轮) - 淘汰明显错误
  fast     快速测试 (36s+0.3s, 11轮) - 确认小幅提升
  standard 标准测试 (96s+0.8s, 21轮) - 最终验证

示例:
  # 运行最快测试
  python tiered_test.py --tier quick --opponent tscp181

  # 运行完整测试流程
  python tiered_test.py --full --opponent tscp181

  # 指定配置版本
  python tiered_test.py --tier standard --config v1.4.2 --opponent monarch
        """
    )
    
    parser.add_argument(
        "--tier",
        choices=["quick", "fast", "standard"],
        help="测试层级 (quick/fast/standard)"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="运行完整测试流程 (quick -> fast -> standard)"
    )
    parser.add_argument(
        "--opponent",
        required=True,
        choices=list(OPPONENTS.keys()),
        help="对手引擎"
    )
    parser.add_argument(
        "--config",
        default="v1.4.2",
        help="配置版本 (如 v1.4.2，默认使用最新版本)"
    )
    parser.add_argument(
        "--cutechess",
        help="cutechess-cli 可执行文件路径"
    )
    
    args = parser.parse_args()
    
    if not args.tier and not args.full:
        args.tier = "standard"
        print("未指定测试层级，默认使用 standard 层级")
    
    print(f"\n{'#'*60}")
    print("分层测试框架")
    print(f"{'#'*60}")
    print(f"配置版本: {args.config}")
    print(f"对手引擎: {args.opponent}")
    if args.full:
        print(f"测试模式: 完整流程 (quick -> fast -> standard)")
    else:
        tier = TIERS[args.tier]
        print(f"测试模式: 单层级 ({tier['name']})")
    print(f"{'#'*60}")
    
    try:
        report = run_tiered_test(
            config=args.config,
            opponent=args.opponent,
            tier=args.tier,
            full=args.full,
            cutechess_path=args.cutechess,
        )
        
        if report.final_status == "成功":
            sys.exit(0)
        else:
            sys.exit(1)
            
    except FileNotFoundError as e:
        print(f"\n错误: {e}")
        sys.exit(2)
    except ValueError as e:
        print(f"\n错误: {e}")
        sys.exit(2)
    except Exception as e:
        print(f"\n未预期的错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(3)


if __name__ == "__main__":
    main()
