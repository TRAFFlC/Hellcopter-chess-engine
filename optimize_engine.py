"""
Hellcopter 国际象棋引擎自动化持续优化系统 - 主入口

使用方法:
    python optimize_engine.py [命令] [选项]

命令:
    run         启动持续优化循环（直到大幅超过Apollo）
    analyze     运行性能分析
    tune        运行参数调优
    validate    验证指定配置
    status      查看当前状态
    report      生成优化报告

选项:
    --config    指定配置文件
    --opponent  指定对手引擎 (默认: apollo)
    --rounds    指定对局轮数
    --tc        指定时间控制

示例:
    python optimize_engine.py run
    python optimize_engine.py analyze --opponent apollo
    python optimize_engine.py tune --config v1.5.0
    python optimize_engine.py status
"""

import argparse
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from optimization_system.iteration_controller import IterationController
from optimization_system.config_manager import ConfigManager
from optimization_system.performance_analyzer import PerformanceAnalyzer
from optimization_system.test_validator import TestValidator
from optimization_system.elo_tracker import EloTracker
from optimization_system.bug_detector import BugDetector
from optimization_system.tool_integrator import ToolIntegrator
from optimization_system.parameter_optimizer import ParameterOptimizer


def cmd_run(args):
    """启动持续优化循环"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    controller = IterationController(base_dir)

    if args.config:
        controller.config_manager.update_config(baseline_version=args.config)

    if args.opponent:
        controller.config_manager.update_config(target_opponent=args.opponent)

    print("=" * 60)
    print("Hellcopter 引擎自动化持续优化系统")
    print("=" * 60)
    print(f"目标: 在标准对局中大幅超过 {controller.config.target_opponent}")
    print(f"目标胜率: {controller.config.target_win_rate:.0%}")
    print(f"基准版本: {controller.config.baseline_version}")
    print("=" * 60)
    print("按 Ctrl+C 暂停优化")
    print("=" * 60)

    controller.run_optimization_loop()


def cmd_analyze(args):
    """运行性能分析"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_manager = ConfigManager(base_dir)
    config = config_manager.load_config()

    analyzer = PerformanceAnalyzer(config_manager, config.velvet_engine_path)

    pgn_file = args.pgn if args.pgn else "auto_tune_match.pgn"
    pgn_path = os.path.join(base_dir, pgn_file)

    if not os.path.isfile(pgn_path):
        print(f"PGN文件未找到: {pgn_path}")
        print("先运行对局生成PGN文件...")
        tool = ToolIntegrator(config_manager, base_dir)
        result = tool.run_match(
            opponent=args.opponent or config.opponent_engines[0],
            rounds=args.rounds or 10,
            tc=args.tc or config.quick_tc,
        )
        if not result.success:
            print("对局运行失败")
            return

    try:
        analyzer.start()
        report = analyzer.analyze_pgn(
            pgn_path,
            depth=args.depth or config.analysis_depth,
            time_limit=args.time or config.analysis_time_limit,
        )
        analyzer.save_report(report)

        print("\n" + "=" * 60)
        print("性能分析报告")
        print("=" * 60)
        print(f"总对局数: {report.total_games}")
        print(f"总步数: {report.total_moves}")
        print(f"发现问题: {len(report.issues)}")
        print(f"开局问题: {len(report.opening_issues)}")
        print(f"残局问题: {len(report.endgame_issues)}")

        if report.issues:
            print("\n主要问题:")
            for issue in report.issues[:10]:
                print(f"  - [{issue.severity.value}] {issue.description} (第{issue.move_number}步)")

    except Exception as e:
        print(f"分析失败: {e}")
    finally:
        analyzer.stop()


def cmd_tune(args):
    """运行参数调优"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_manager = ConfigManager(base_dir)
    config = config_manager.load_config()
    optimizer = ParameterOptimizer(config_manager, base_dir)

    base_config = args.config or config.baseline_version
    base_config_path = os.path.join(base_dir, "configs", f"{base_config}.json")

    if not os.path.isfile(base_config_path):
        print(f"配置未找到: {base_config_path}")
        return

    print("=" * 60)
    print("参数调优")
    print("=" * 60)

    if args.type == "eval" or args.type == "all":
        print("\n--- 评估参数优化 ---")
        eval_params = optimizer.get_eval_param_space()
        results = optimizer.optimize_with_spsa(
            eval_params, base_config_path,
            iterations=args.iterations or config.eval_opt_iterations,
            opponent=args.opponent or config.target_opponent,
        )
        print(f"评估参数优化完成: {len(results)} 个参数")

    if args.type == "search" or args.type == "all":
        print("\n--- 搜索参数优化 ---")
        search_params = optimizer.get_search_param_space()
        results = optimizer.optimize_with_spsa(
            search_params, base_config_path,
            iterations=args.iterations or config.search_opt_iterations,
            opponent=args.opponent or config.target_opponent,
        )
        print(f"搜索参数优化完成: {len(results)} 个参数")

    if args.type == "time" or args.type == "all":
        print("\n--- 时间参数优化 ---")
        time_params = optimizer.get_time_mgmt_param_space()
        results = optimizer.grid_search(
            time_params, base_config_path,
            opponent=args.opponent or config.target_opponent,
        )
        print(f"时间参数优化完成: {len(results)} 个参数")

    if args.type == "tactical" or args.type == "all":
        print("\n--- 战术参数优化 ---")
        tactical_params = optimizer.get_tactical_param_space()
        results = optimizer.optimize_with_spsa(
            tactical_params, base_config_path,
            iterations=args.iterations or config.tactical_opt_iterations,
            opponent=args.opponent or config.target_opponent,
        )
        print(f"战术参数优化完成: {len(results)} 个参数")

    optimizer.save_optimization_report()


def cmd_validate(args):
    """验证指定配置"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_manager = ConfigManager(base_dir)
    config = config_manager.load_config()
    validator = TestValidator(config_manager, base_dir)

    candidate_config = args.config
    if not candidate_config:
        print("请指定要验证的配置: --config <配置名>")
        return

    candidate_path = os.path.join(base_dir, "configs", f"{candidate_config}.json")
    if not os.path.isfile(candidate_path):
        print(f"配置未找到: {candidate_path}")
        return

    baseline_config = os.path.join(base_dir, "configs", f"{config.baseline_version}.json")

    from optimization_system.solution_generator import OptimizationSolution, SolutionType, SolutionPriority

    solution = OptimizationSolution(
        solution_id="manual_validation",
        solution_type=SolutionType.PARAM_OPTIMIZATION,
        priority=SolutionPriority.HIGH,
        title="手动验证",
        description="手动触发的验证",
        root_cause="手动验证",
    )

    print("=" * 60)
    print("验证配置")
    print("=" * 60)

    report = validator.validate_solution(solution, candidate_path, baseline_config)
    validator.save_report(report)

    print("\n验证结果:")
    print(f"  总体状态: {report.overall_status.value}")
    print(f"  Elo变化: {report.elo_change:+.1f}")
    if report.quick_test:
        print(f"  快棋测试: {report.quick_test.win_rate:.2%}")
    if report.standard_test:
        print(f"  标准测试: {report.standard_test.win_rate:.2%}")


def cmd_status(args):
    """查看当前状态"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_manager = ConfigManager(base_dir)
    config = config_manager.load_config()
    elo_tracker = EloTracker(config_manager)

    print("=" * 60)
    print("系统状态")
    print("=" * 60)
    print(f"基准版本: {config.baseline_version}")
    print(f"目标对手: {config.target_opponent}")
    print(f"目标胜率: {config.target_win_rate:.0%}")
    print(f"自动应用: {'是' if config.auto_apply else '否'}")

    print("\nElo追踪:")
    report = elo_tracker.generate_elo_report()
    print(f"  总版本数: {report.get('total_versions', 0)}")
    print(f"  最佳版本: {report.get('best_version', 'N/A')}")
    print(f"  最佳Elo: {report.get('best_elo', 'N/A')}")

    if elo_tracker.records:
        latest = elo_tracker.records[-1]
        print(f"\n最新记录:")
        print(f"  版本: {latest.version}")
        print(f"  对手: {latest.opponent}")
        print(f"  Elo: {latest.elo:+.1f}")
        print(f"  对局: {latest.wins}-{latest.losses}-{latest.draws}")


def cmd_report(args):
    """生成优化报告"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_manager = ConfigManager(base_dir)

    elo_tracker = EloTracker(config_manager)
    elo_tracker.save_elo_report()

    bug_detector = BugDetector(config_manager)
    bug_detector.save_bug_report()

    optimizer = ParameterOptimizer(config_manager, base_dir)
    optimizer.save_optimization_report()

    print("报告已生成:")
    print(f"  - {config_manager.get_output_path('elo_report.json')}")
    print(f"  - {config_manager.get_output_path('bug_report.json')}")
    print(f"  - {config_manager.get_output_path('param_optimization_report.json')}")


def main():
    parser = argparse.ArgumentParser(
        description="Hellcopter 引擎自动化持续优化系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python optimize_engine.py run
  python optimize_engine.py analyze --opponent apollo
  python optimize_engine.py tune --type all
  python optimize_engine.py validate --config candidate_iter_1
  python optimize_engine.py status
  python optimize_engine.py report
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    run_parser = subparsers.add_parser("run", help="启动持续优化循环")
    run_parser.add_argument("--config", help="基准配置")
    run_parser.add_argument("--opponent", default="apollo", help="目标对手")

    analyze_parser = subparsers.add_parser("analyze", help="运行性能分析")
    analyze_parser.add_argument("--pgn", help="PGN文件路径")
    analyze_parser.add_argument("--opponent", default="apollo", help="对手引擎")
    analyze_parser.add_argument("--rounds", type=int, default=10, help="对局轮数")
    analyze_parser.add_argument("--tc", default="10+0.1", help="时间控制")
    analyze_parser.add_argument("--depth", type=int, help="分析深度")
    analyze_parser.add_argument("--time", type=float, help="分析时间限制")

    tune_parser = subparsers.add_parser("tune", help="运行参数调优")
    tune_parser.add_argument("--config", help="基准配置")
    tune_parser.add_argument("--type", default="all",
                             choices=["eval", "search", "time", "tactical", "all"],
                             help="调优类型")
    tune_parser.add_argument("--opponent", default="apollo", help="对手引擎")
    tune_parser.add_argument("--iterations", type=int, help="迭代次数")

    validate_parser = subparsers.add_parser("validate", help="验证指定配置")
    validate_parser.add_argument("--config", required=True, help="要验证的配置")

    subparsers.add_parser("status", help="查看当前状态")
    subparsers.add_parser("report", help="生成优化报告")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "run": cmd_run,
        "analyze": cmd_analyze,
        "tune": cmd_tune,
        "validate": cmd_validate,
        "status": cmd_status,
        "report": cmd_report,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
