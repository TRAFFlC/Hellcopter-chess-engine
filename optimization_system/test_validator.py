"""
测试验证器模块

负责验证优化方案的有效性，包括：
- 回归测试
- 快棋测试（初步验证）
- 慢棋测试（最终验收）
- Elo计算
- 与Baseline和Gatekeeper对比
"""

import json
import os
import sys
import subprocess
import shutil
import math
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple


class TestResultStatus(Enum):
    PASSED = "通过"
    FAILED = "失败"
    INCONCLUSIVE = "不确定"
    CRASH = "崩溃"
    TIMEOUT = "超时"


@dataclass
class MatchResult:
    wins: int
    losses: int
    draws: int
    total_games: int
    win_rate: float
    elo_diff: float
    ci_low: float
    ci_high: float
    status: TestResultStatus
    details: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wins": self.wins,
            "losses": self.losses,
            "draws": self.draws,
            "total_games": self.total_games,
            "win_rate": self.win_rate,
            "elo_diff": self.elo_diff,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "status": self.status.value,
            "details": self.details,
        }


@dataclass
class ValidationReport:
    report_id: str
    timestamp: str
    solution_id: str
    regression_passed: bool
    quick_test: Optional[MatchResult] = None
    standard_test: Optional[MatchResult] = None
    gatekeeper_results: Dict[str, MatchResult] = field(default_factory=dict)
    baseline_comparison: Optional[MatchResult] = None
    overall_status: TestResultStatus = TestResultStatus.INCONCLUSIVE
    elo_change: float = 0.0
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "timestamp": self.timestamp,
            "solution_id": self.solution_id,
            "regression_passed": self.regression_passed,
            "quick_test": self.quick_test.to_dict() if self.quick_test else None,
            "standard_test": self.standard_test.to_dict() if self.standard_test else None,
            "gatekeeper_results": {k: v.to_dict() for k, v in self.gatekeeper_results.items()},
            "baseline_comparison": self.baseline_comparison.to_dict() if self.baseline_comparison else None,
            "overall_status": self.overall_status.value,
            "elo_change": self.elo_change,
            "notes": self.notes,
        }


class TestValidator:
    """测试验证器"""

    def __init__(self, config_manager, base_dir: str):
        self.config = config_manager.config
        self.config_manager = config_manager
        self.base_dir = base_dir
        self.python_exe = sys.executable or "python"

    def validate_solution(self, solution, candidate_config_path: str,
                          baseline_config_path: Optional[str] = None) -> ValidationReport:
        """验证优化方案"""
        report_id = f"validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        notes = []

        print(f"\n{'='*60}")
        print(f"开始验证方案: {solution.solution_id}")
        print(f"{'='*60}")

        regression_passed = self._run_regression_tests()
        if not regression_passed:
            notes.append("回归测试未通过")
            if self.config.pause_on_error:
                print("警告: 回归测试失败，继续快棋测试...")

        quick_result = self._run_quick_test(candidate_config_path)
        if quick_result.status == TestResultStatus.FAILED:
            notes.append(f"快棋测试未通过: 胜率 {quick_result.win_rate:.2%}")
            return ValidationReport(
                report_id=report_id,
                timestamp=datetime.now().isoformat(),
                solution_id=solution.solution_id,
                regression_passed=regression_passed,
                quick_test=quick_result,
                overall_status=TestResultStatus.FAILED,
                notes=notes,
            )

        standard_result = self._run_standard_test(candidate_config_path)
        gatekeeper_results = self._run_gatekeeper_tests(candidate_config_path)

        baseline_comparison = None
        if baseline_config_path and os.path.isfile(baseline_config_path):
            baseline_comparison = self._run_baseline_comparison(
                candidate_config_path, baseline_config_path
            )

        overall_status = self._determine_overall_status(
            quick_result, standard_result, gatekeeper_results, baseline_comparison
        )

        elo_change = self._calculate_elo_change(standard_result, baseline_comparison)

        if overall_status == TestResultStatus.PASSED:
            notes.append(f"方案通过验证，Elo变化: {elo_change:+.1f}")
        else:
            notes.append(f"方案未通过验证")

        return ValidationReport(
            report_id=report_id,
            timestamp=datetime.now().isoformat(),
            solution_id=solution.solution_id,
            regression_passed=regression_passed,
            quick_test=quick_result,
            standard_test=standard_result,
            gatekeeper_results=gatekeeper_results,
            baseline_comparison=baseline_comparison,
            overall_status=overall_status,
            elo_change=elo_change,
            notes=notes,
        )

    def _run_regression_tests(self) -> bool:
        """运行回归测试套件"""
        print("\n--- 运行回归测试 ---")
        test_suite = self.config.regression_test_suite
        test_path = os.path.join(self.base_dir, test_suite)

        if not os.path.isfile(test_path):
            print(f"回归测试文件未找到: {test_path}，跳过")
            return True

        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            result = subprocess.run(
                [self.python_exe, test_path],
                capture_output=True,
                text=True,
                cwd=self.base_dir,
                timeout=300,
                encoding='utf-8',
                errors='replace',
                env=env,
            )
            passed = result.returncode == 0
            if passed:
                print("回归测试通过")
            else:
                print(f"回归测试失败（不阻止后续验证）")
                if result.stdout:
                    print(f"  stdout: {result.stdout[-300:]}")
                if result.stderr:
                    print(f"  stderr: {result.stderr[-300:]}")
            return passed
        except subprocess.TimeoutExpired:
            print("回归测试超时（不阻止后续验证）")
            return False
        except Exception as e:
            print(f"回归测试运行失败: {e}（不阻止后续验证）")
            return False

    def _run_quick_test(self, config_path: str) -> MatchResult:
        """运行快棋测试"""
        print(f"\n--- 快棋测试: {self.config.quick_tc} ---")
        return self._run_match(
            config_path,
            opponent=self.config.opponent_engines[0] if self.config.opponent_engines else "tscp181",
            rounds=max(5, self.config.min_games_for_validation // 2),
            tc=self.config.quick_tc,
        )

    def _run_standard_test(self, config_path: str) -> MatchResult:
        """运行标准测试"""
        print(f"\n--- 标准测试: {self.config.standard_tc} ---")
        return self._run_match(
            config_path,
            opponent=self.config.opponent_engines[0] if self.config.opponent_engines else "tscp181",
            rounds=self.config.min_games_for_validation,
            tc=self.config.standard_tc,
        )

    def _run_gatekeeper_tests(self, config_path: str) -> Dict[str, MatchResult]:
        """运行守门员测试"""
        results = {}
        for gk in self.config.gatekeeper_engines:
            print(f"\n--- Gatekeeper测试: {gk} ---")
            gk_config = os.path.join(self.base_dir, "configs", f"{gk}.json")
            if not os.path.isfile(gk_config):
                print(f"Gatekeeper配置未找到: {gk_config}")
                continue

            result = self._run_match_vs_config(
                config_path, gk_config,
                name_a="Candidate", name_b=f"GK-{gk}",
                rounds=self.config.min_games_for_validation,
                tc=self.config.standard_tc,
            )
            results[gk] = result
        return results

    def _run_baseline_comparison(self, candidate_path: str, baseline_path: str) -> MatchResult:
        """与基准版本对比"""
        print(f"\n--- Baseline对比测试 ---")
        return self._run_match_vs_config(
            candidate_path, baseline_path,
            name_a="Candidate", name_b="Baseline",
            rounds=self.config.min_games_for_validation,
            tc=self.config.standard_tc,
        )

    def _run_match(self, config_path: str, opponent: str, rounds: int, tc: str) -> MatchResult:
        """运行对局测试"""
        run_match_script = os.path.join(self.base_dir, "run_match.py")
        if not os.path.isfile(run_match_script):
            return MatchResult(
                wins=0, losses=0, draws=0, total_games=0,
                win_rate=0, elo_diff=0, ci_low=0, ci_high=0,
                status=TestResultStatus.CRASH,
                details="run_match.py not found",
            )

        try:
            config_name = os.path.splitext(os.path.basename(config_path))[0]
            result = subprocess.run(
                [
                    self.python_exe, run_match_script,
                    "--opponent", opponent,
                    "--rounds", str(rounds),
                    "--tc", tc,
                    "--config", config_name,
                ],
                capture_output=True,
                text=True,
                cwd=self.base_dir,
                timeout=7200,
                encoding='utf-8',
                errors='replace',
            )

            combined = result.stdout + result.stderr
            wins, losses, draws = self._parse_match_output(combined)
            total = wins + losses + draws

            if total == 0:
                return MatchResult(
                    wins=0, losses=0, draws=0, total_games=0,
                    win_rate=0, elo_diff=0, ci_low=0, ci_high=0,
                    status=TestResultStatus.CRASH,
                    details=f"No games completed. Output tail: {combined[-500:] if combined else 'empty'}",
                )

            win_rate = (wins + 0.5 * draws) / total
            elo_diff = self._calc_elo_diff(wins, losses, draws)
            ci_low, ci_high = self._calc_ci(wins, losses, draws)

            status = TestResultStatus.PASSED if win_rate >= self.config.test_accept_threshold else TestResultStatus.FAILED

            return MatchResult(
                wins=wins, losses=losses, draws=draws, total_games=total,
                win_rate=win_rate, elo_diff=elo_diff,
                ci_low=ci_low, ci_high=ci_high,
                status=status,
                details=f"Win rate: {win_rate:.2%}",
            )

        except subprocess.TimeoutExpired:
            return MatchResult(
                wins=0, losses=0, draws=0, total_games=0,
                win_rate=0, elo_diff=0, ci_low=0, ci_high=0,
                status=TestResultStatus.TIMEOUT,
                details="Match timeout",
            )
        except Exception as e:
            return MatchResult(
                wins=0, losses=0, draws=0, total_games=0,
                win_rate=0, elo_diff=0, ci_low=0, ci_high=0,
                status=TestResultStatus.CRASH,
                details=str(e),
            )

    def _run_match_vs_config(self, config_a: str, config_b: str,
                             name_a: str, name_b: str,
                             rounds: int, tc: str) -> MatchResult:
        """两个配置对弈"""
        tune_script = os.path.join(self.base_dir, "tune_params.py")
        if not os.path.isfile(tune_script):
            return MatchResult(
                wins=0, losses=0, draws=0, total_games=0,
                win_rate=0, elo_diff=0, ci_low=0, ci_high=0,
                status=TestResultStatus.CRASH,
                details="tune_params.py not found",
            )

        try:
            result = subprocess.run(
                [
                    self.python_exe, tune_script,
                    "--config-a", config_a,
                    "--config-b", config_b,
                    "--rounds", str(rounds),
                    "--tc", tc,
                ],
                capture_output=True,
                text=True,
                cwd=self.base_dir,
                timeout=3600,
            )

            wins, losses, draws = self._parse_match_output(result.stdout + result.stderr)
            total = wins + losses + draws

            if total == 0:
                return MatchResult(
                    wins=0, losses=0, draws=0, total_games=0,
                    win_rate=0, elo_diff=0, ci_low=0, ci_high=0,
                    status=TestResultStatus.CRASH,
                    details="No games completed",
                )

            win_rate = (wins + 0.5 * draws) / total
            elo_diff = self._calc_elo_diff(wins, losses, draws)
            ci_low, ci_high = self._calc_ci(wins, losses, draws)

            status = TestResultStatus.PASSED if win_rate >= self.config.test_accept_threshold else TestResultStatus.FAILED

            return MatchResult(
                wins=wins, losses=losses, draws=draws, total_games=total,
                win_rate=win_rate, elo_diff=elo_diff,
                ci_low=ci_low, ci_high=ci_high,
                status=status,
                details=f"{name_a} vs {name_b}: {win_rate:.2%}",
            )

        except Exception as e:
            return MatchResult(
                wins=0, losses=0, draws=0, total_games=0,
                win_rate=0, elo_diff=0, ci_low=0, ci_high=0,
                status=TestResultStatus.CRASH,
                details=str(e),
            )

    def _parse_match_output(self, output: str) -> Tuple[int, int, int]:
        """解析对局输出"""
        import re
        pattern = re.compile(
            r"Score of\s+.+?\s+vs\s+.+?:\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)"
        )
        for line in output.splitlines():
            m = pattern.search(line)
            if m:
                return int(m.group(1)), int(m.group(2)), int(m.group(3))
        return 0, 0, 0

    def _calc_elo_diff(self, wins: int, losses: int, draws: int) -> float:
        """计算Elo差"""
        total = wins + losses + draws
        if total == 0:
            return 0.0
        p = (wins + 0.5 * draws) / total
        if p <= 0:
            return -1000.0
        if p >= 1:
            return 1000.0
        return -400 * math.log10(1 / p - 1)

    def _calc_ci(self, wins: int, losses: int, draws: int, confidence: float = 0.95) -> Tuple[float, float]:
        """计算置信区间"""
        total = wins + losses + draws
        if total == 0:
            return 0.0, 0.0
        z = 1.96 if confidence == 0.95 else 2.576
        p_hat = (wins + 0.5 * draws) / total
        denominator = 1 + z ** 2 / total
        centre = (p_hat + z ** 2 / (2 * total)) / denominator
        margin = z * math.sqrt((p_hat * (1 - p_hat) + z ** 2 / (4 * total)) / total) / denominator
        p_low = max(0, centre - margin)
        p_high = min(1, centre + margin)

        def p_to_elo(p):
            if p <= 0.0001:
                return -800
            if p >= 0.9999:
                return 800
            return -400 * math.log10(1 / p - 1)

        return p_to_elo(p_low), p_to_elo(p_high)

    def _determine_overall_status(self, quick: MatchResult, standard: MatchResult,
                                  gatekeepers: Dict[str, MatchResult],
                                  baseline: Optional[MatchResult]) -> TestResultStatus:
        """确定总体状态"""
        if quick.status == TestResultStatus.FAILED:
            return TestResultStatus.FAILED

        if standard.status == TestResultStatus.FAILED:
            return TestResultStatus.FAILED

        for gk_result in gatekeepers.values():
            if gk_result.status == TestResultStatus.FAILED:
                return TestResultStatus.FAILED

        if baseline and baseline.elo_diff < -50:
            return TestResultStatus.FAILED

        if standard.win_rate >= self.config.test_accept_threshold:
            return TestResultStatus.PASSED

        return TestResultStatus.INCONCLUSIVE

    def _calculate_elo_change(self, standard: MatchResult, baseline: Optional[MatchResult]) -> float:
        """计算Elo变化"""
        if baseline:
            return standard.elo_diff - baseline.elo_diff
        return standard.elo_diff

    def save_report(self, report: ValidationReport, output_path: Optional[str] = None):
        if output_path is None:
            output_path = self.config_manager.get_output_path(
                f"validation_report_{report.report_id}.json"
            )
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"验证报告已保存: {output_path}")
