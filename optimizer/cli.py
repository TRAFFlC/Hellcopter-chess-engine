import argparse
import json
import os
import sys
from datetime import datetime
from typing import Optional

from .config_manager import ConfigManager
from .match_runner import MatchRunner
from .tuner import GradientDescentTuner, GridSearchTuner, TUNABLE_PARAMS
from .visualizer import Visualizer


def cmd_config(args):
    cm = ConfigManager(config_dir=args.config_dir)
    if args.action == "export":
        version = args.version
        params = None
        if args.from_file:
            with open(args.from_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            params = data.get("parameters", data)
        path = cm.export_config(
            version, description=args.desc or "", parameters=params)
        print(f"Config v{version} exported to {path}")
    elif args.action == "import":
        config = cm.import_config(args.version)
        print(json.dumps(config, indent=2, ensure_ascii=False))
    elif args.action == "list":
        versions = cm.list_versions()
        for v in versions:
            print(f"  v{v['version']}: {v['description']} ({v['created_at']})")
    elif args.action == "switch":
        cm.switch_version(args.version)
        print(f"Switched to v{args.version}. Rebuild engine to apply.")
    elif args.action == "compare":
        diff = cm.compare_versions(args.version, args.version2)
        if diff["added"]:
            print("Added:", json.dumps(diff["added"], indent=2))
        if diff["removed"]:
            print("Removed:", json.dumps(diff["removed"], indent=2))
        if diff["modified"]:
            print("Modified:")
            for k, v in diff["modified"].items():
                print(f"  {k}: {v['old']} -> {v['new']}")
        if not diff["added"] and not diff["removed"] and not diff["modified"]:
            print("No differences found.")
    elif args.action == "delete":
        cm.delete_version(args.version)
        print(f"Deleted v{args.version}")


def cmd_match(args):
    mr = MatchRunner(base_dir=args.base_dir, results_dir=args.results_dir)
    result = mr.run_match(
        opponent=args.opponent,
        rounds=args.rounds,
        time_control=args.tc,
        config_version=args.config_version or ""
    )
    print(f"\nResult: W{result.wins} L{result.losses} D{result.draws}")
    print(
        f"Elo diff: {result.elo_diff:.1f} CI=[{result.ci_low:.1f}, {result.ci_high:.1f}]")


def cmd_benchmark(args):
    mr = MatchRunner(base_dir=args.base_dir, results_dir=args.results_dir)
    result = mr.run_benchmark(
        config_version=args.config_version or "",
        depth=args.depth
    )
    print(f"Avg NPS: {result['avg_nps']:.0f}")
    print(
        f"Total: {result['total_nodes']} nodes in {result['total_time']:.3f}s")


def cmd_tune(args):
    cm = ConfigManager(config_dir=args.config_dir)
    mr = MatchRunner(base_dir=args.base_dir, results_dir=args.results_dir)

    params_to_tune = args.params.split(",") if args.params else None

    if args.method == "gradient":
        tuner = GradientDescentTuner(cm, mr, base_version=args.base_version)
        result = tuner.tune(
            params_to_tune=params_to_tune,
            opponent=args.opponent,
            rounds=args.rounds,
            time_control=args.tc,
            learning_rate=args.learning_rate,
            iterations=args.iterations
        )
    elif args.method == "grid":
        tuner = GridSearchTuner(cm, mr, base_version=args.base_version)
        result = tuner.tune(
            params_to_tune=params_to_tune,
            opponent=args.opponent,
            rounds=args.rounds,
            time_control=args.tc
        )
    else:
        print(f"Unknown method: {args.method}")
        return

    print(f"\nBest Elo: {result.best_elo:.1f}")
    print(f"Best params saved to tuning result file.")


def cmd_visualize(args):
    viz = Visualizer(results_dir=args.results_dir, output_dir=args.output_dir)
    if args.type == "elo":
        path = viz.plot_elo_progression(opponent=args.opponent)
        print(f"Elo progression plot: {path}")
    elif args.type == "winrate":
        path = viz.plot_winrate_by_opponent()
        print(f"Win rate plot: {path}")
    elif args.type == "tuning":
        path = viz.plot_tuning_history()
        print(f"Tuning history plot: {path}")
    elif args.type == "summary":
        report = viz.generate_summary_report()
        print(report)


def cmd_list_params(args):
    print("Tunable parameters:")
    for key, spec in TUNABLE_PARAMS.items():
        print(
            f"  {key}: min={spec['min']}, max={spec['max']}, step={spec['step']}")


def main():
    parser = argparse.ArgumentParser(
        prog="hellcopter",
        description="Hellcopter Chess Engine Optimization CLI"
    )
    subparsers = parser.add_subparsers(
        dest="command", help="Available commands")

    # config
    cfg = subparsers.add_parser("config", help="Manage engine configurations")
    cfg.add_argument("action", choices=[
                     "export", "import", "list", "switch", "compare", "delete"])
    cfg.add_argument("--version", required=True)
    cfg.add_argument("--version2", help="Second version for compare")
    cfg.add_argument("--desc", help="Description for export")
    cfg.add_argument("--from-file", help="Import parameters from JSON file")
    cfg.add_argument("--config-dir", default="configs")

    # match
    match = subparsers.add_parser("match", help="Run match against opponent")
    match.add_argument("--opponent", default="pulsar",
                       choices=["monarch", "apollo", "rainman", "shallowblue", "pulsar", "tscp181"])
    match.add_argument("--rounds", type=int, default=51)
    match.add_argument("--tc", default="9+0.1")
    match.add_argument("--config-version", default="")
    match.add_argument("--base-dir", default=".")
    match.add_argument("--results-dir", default="test_results")

    # benchmark
    bench = subparsers.add_parser(
        "benchmark", help="Run performance benchmark")
    bench.add_argument("--depth", type=int, default=10)
    bench.add_argument("--config-version", default="")
    bench.add_argument("--base-dir", default=".")
    bench.add_argument("--results-dir", default="test_results")

    # tune
    tune = subparsers.add_parser("tune", help="Tune engine parameters")
    tune.add_argument(
        "--method", choices=["gradient", "grid"], default="gradient")
    tune.add_argument("--base-version", default="1.0.0")
    tune.add_argument("--opponent", default="pulsar")
    tune.add_argument("--rounds", type=int, default=11)
    tune.add_argument("--tc", default="9+0.1")
    tune.add_argument("--params", help="Comma-separated param keys to tune")
    tune.add_argument("--iterations", type=int, default=10)
    tune.add_argument("--learning-rate", type=float, default=0.3)
    tune.add_argument("--config-dir", default="configs")
    tune.add_argument("--base-dir", default=".")
    tune.add_argument("--results-dir", default="test_results")

    # visualize
    viz = subparsers.add_parser("visualize", help="Generate visualizations")
    viz.add_argument("--type", choices=["elo", "winrate", "tuning", "summary"],
                     default="summary")
    viz.add_argument("--opponent", default=None)
    viz.add_argument("--results-dir", default="test_results")
    viz.add_argument("--output-dir", default="plots")

    # list-params
    subparsers.add_parser("list-params", help="List tunable parameters")

    args = parser.parse_args()

    if args.command == "config":
        cmd_config(args)
    elif args.command == "match":
        cmd_match(args)
    elif args.command == "benchmark":
        cmd_benchmark(args)
    elif args.command == "tune":
        cmd_tune(args)
    elif args.command == "visualize":
        cmd_visualize(args)
    elif args.command == "list-params":
        cmd_list_params(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
