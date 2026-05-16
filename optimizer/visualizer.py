import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


class Visualizer:
    def __init__(self, results_dir: str = "test_results", output_dir: str = "plots"):
        self.results_dir = Path(results_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def _load_results(self) -> List[Dict]:
        results = []
        if not self.results_dir.exists():
            return results
        for f in sorted(self.results_dir.glob("test_*.json")):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    results.append(json.load(fh))
            except (json.JSONDecodeError, KeyError):
                continue
        return results

    def _load_tuning_results(self) -> List[Dict]:
        results = []
        if not self.results_dir.exists():
            return results
        for f in sorted(self.results_dir.glob("tuning_*.json")):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    results.append(json.load(fh))
            except (json.JSONDecodeError, KeyError):
                continue
        return results

    def plot_elo_progression(self, opponent: Optional[str] = None,
                             save_path: Optional[str] = None) -> str:
        if not HAS_MATPLOTLIB:
            return self._text_elo_progression(opponent)

        results = self._load_results()
        if opponent:
            results = [r for r in results if r.get(
                "results", {}).get("opponent") == opponent]

        if not results:
            return "No match results found"

        timestamps = []
        elo_diffs = []
        ci_lows = []
        ci_highs = []
        labels = []

        for r in results:
            res = r.get("results", {})
            ts = r.get("timestamp", "")
            timestamps.append(ts)
            elo_diffs.append(res.get("elo_diff", 0))
            ci_lows.append(res.get("ci_low", 0))
            ci_highs.append(res.get("ci_high", 0))
            labels.append(r.get("config_version", "unknown"))

        fig, ax = plt.subplots(figsize=(12, 6))
        x = range(len(elo_diffs))
        ax.plot(x, elo_diffs, 'b-o', label='Elo difference', markersize=6)
        ax.fill_between(x, ci_lows, ci_highs, alpha=0.2,
                        color='blue', label='95% CI')
        ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
        ax.set_xlabel('Test')
        ax.set_ylabel('Elo difference')
        ax.set_title(f'Elo Progression{" vs " + opponent if opponent else ""}')
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=8)
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()

        if save_path is None:
            save_path = str(
                self.output_dir / f"elo_progression_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        fig.savefig(save_path, dpi=150)
        plt.close(fig)
        return save_path

    def plot_winrate_by_opponent(self, save_path: Optional[str] = None) -> str:
        if not HAS_MATPLOTLIB:
            return self._text_winrate_by_opponent()

        results = self._load_results()
        if not results:
            return "No match results found"

        by_opponent = {}
        for r in results:
            res = r.get("results", {})
            opp = res.get("opponent", "unknown")
            if opp not in by_opponent:
                by_opponent[opp] = {"wins": 0, "losses": 0, "draws": 0}
            by_opponent[opp]["wins"] += res.get("wins", 0)
            by_opponent[opp]["losses"] += res.get("losses", 0)
            by_opponent[opp]["draws"] += res.get("draws", 0)

        opponents = list(by_opponent.keys())
        winrates = []
        for opp in opponents:
            d = by_opponent[opp]
            total = d["wins"] + d["losses"] + d["draws"]
            winrates.append((d["wins"] + d["draws"] * 0.5) /
                            total * 100 if total > 0 else 0)

        fig, ax = plt.subplots(figsize=(10, 6))
        colors = ['#2ecc71' if wr >= 50 else '#e74c3c' for wr in winrates]
        bars = ax.bar(opponents, winrates, color=colors, alpha=0.8)
        ax.axhline(y=50, color='gray', linestyle='--', alpha=0.5)
        ax.set_ylabel('Win Rate (%)')
        ax.set_title('Win Rate by Opponent')
        ax.set_ylim(0, 100)
        for bar, wr in zip(bars, winrates):
            ax.text(bar.get_x() + bar.get_width() / 2., bar.get_height() + 1,
                    f'{wr:.1f}%', ha='center', va='bottom', fontsize=10)
        plt.tight_layout()

        if save_path is None:
            save_path = str(
                self.output_dir / f"winrate_by_opponent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        fig.savefig(save_path, dpi=150)
        plt.close(fig)
        return save_path

    def plot_tuning_history(self, save_path: Optional[str] = None) -> str:
        if not HAS_MATPLOTLIB:
            return self._text_tuning_history()

        tuning_results = self._load_tuning_results()
        if not tuning_results:
            return "No tuning results found"

        latest = tuning_results[-1]
        history = latest.get("history", [])
        method = latest.get("method", "unknown")

        if not history:
            return "Empty tuning history"

        iterations = [h.get("iteration", i) for i, h in enumerate(history)]
        elos = [h.get("elo", 0) for h in history]

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(iterations, elos, 'b-o', markersize=5)
        ax.set_xlabel('Iteration')
        ax.set_ylabel('Elo')
        ax.set_title(f'Tuning Progress ({method})')
        ax.grid(True, alpha=0.3)

        if len(elos) > 0:
            best_idx = elos.index(max(elos))
            ax.annotate(f'Best: {elos[best_idx]:.1f}',
                        xy=(iterations[best_idx], elos[best_idx]),
                        xytext=(10, 10), textcoords='offset points',
                        arrowprops=dict(arrowstyle='->', color='red'),
                        color='red', fontsize=10)

        plt.tight_layout()
        if save_path is None:
            save_path = str(
                self.output_dir / f"tuning_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        fig.savefig(save_path, dpi=150)
        plt.close(fig)
        return save_path

    def generate_summary_report(self, save_path: Optional[str] = None) -> str:
        results = self._load_results()
        tuning_results = self._load_tuning_results()

        lines = []
        lines.append("=" * 60)
        lines.append("HELLCOPTER ENGINE TEST SUMMARY REPORT")
        lines.append(f"Generated: {datetime.now().isoformat()}")
        lines.append("=" * 60)

        lines.append(f"\nTotal match tests: {len(results)}")
        lines.append(f"Total tuning runs: {len(tuning_results)}")

        if results:
            lines.append("\n--- Match Results ---")
            for r in results:
                res = r.get("results", {})
                lines.append(
                    f"  [{r.get('config_version', '?')}] vs {res.get('opponent', '?')}: "
                    f"W{res.get('wins', 0)} L{res.get('losses', 0)} D{res.get('draws', 0)} "
                    f"Elo={res.get('elo_diff', 0):.1f} "
                    f"CI=[{res.get('ci_low', 0):.1f}, {res.get('ci_high', 0):.1f}]"
                )

        if tuning_results:
            lines.append("\n--- Tuning Results ---")
            for tr in tuning_results:
                lines.append(
                    f"  Method: {tr.get('method', '?')}, "
                    f"Best Elo: {tr.get('best_elo', 0):.1f}"
                )

        report = "\n".join(lines)

        if save_path is None:
            save_path = str(
                self.output_dir / f"summary_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        with open(save_path, 'w', encoding='utf-8') as f:
            f.write(report)
        return report

    def _text_elo_progression(self, opponent: Optional[str] = None) -> str:
        results = self._load_results()
        if opponent:
            results = [r for r in results if r.get(
                "results", {}).get("opponent") == opponent]
        lines = ["Elo Progression:"]
        for r in results:
            res = r.get("results", {})
            lines.append(
                f"  [{r.get('config_version', '?')}] vs {res.get('opponent', '?')}: "
                f"Elo={res.get('elo_diff', 0):.1f} "
                f"CI=[{res.get('ci_low', 0):.1f}, {res.get('ci_high', 0):.1f}]"
            )
        return "\n".join(lines)

    def _text_winrate_by_opponent(self) -> str:
        results = self._load_results()
        by_opp = {}
        for r in results:
            res = r.get("results", {})
            opp = res.get("opponent", "unknown")
            if opp not in by_opp:
                by_opp[opp] = {"wins": 0, "losses": 0, "draws": 0}
            by_opp[opp]["wins"] += res.get("wins", 0)
            by_opp[opp]["losses"] += res.get("losses", 0)
            by_opp[opp]["draws"] += res.get("draws", 0)
        lines = ["Win Rate by Opponent:"]
        for opp, d in by_opp.items():
            total = d["wins"] + d["losses"] + d["draws"]
            wr = (d["wins"] + d["draws"] * 0.5) / \
                total * 100 if total > 0 else 0
            lines.append(
                f"  vs {opp}: {wr:.1f}% (W{d['wins']} L{d['losses']} D{d['draws']})")
        return "\n".join(lines)

    def _text_tuning_history(self) -> str:
        tuning_results = self._load_tuning_results()
        if not tuning_results:
            return "No tuning results found"
        latest = tuning_results[-1]
        history = latest.get("history", [])
        lines = [f"Tuning History ({latest.get('method', '?')}):"]
        for h in history:
            lines.append(
                f"  Iter {h.get('iteration', '?')}: Elo={h.get('elo', 0):.1f}")
        return "\n".join(lines)
