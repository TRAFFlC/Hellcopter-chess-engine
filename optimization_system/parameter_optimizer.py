"""
参数优化器模块

负责智能优化引擎参数：
- 搜索参数优化（SPSA方法）
- 评估参数优化（Texel Tuning方法）
- 离散参数优化（网格搜索）
- 参数合法性验证
- 参数历史记录
"""

import json
import os
import sys
import subprocess
import math
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple


@dataclass
class ParameterSpace:
    name: str
    param_type: str
    min_value: float
    max_value: float
    current_value: float
    step_size: float = 1.0
    discrete_values: Optional[List[float]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "param_type": self.param_type,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "current_value": self.current_value,
            "step_size": self.step_size,
            "discrete_values": self.discrete_values,
        }


@dataclass
class OptimizationResult:
    param_name: str
    old_value: float
    new_value: float
    improvement: float
    games_played: int
    confidence: float
    converged: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "param_name": self.param_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "improvement": self.improvement,
            "games_played": self.games_played,
            "confidence": self.confidence,
            "converged": self.converged,
        }


class ParameterOptimizer:
    """参数优化器"""

    def __init__(self, config_manager, base_dir: str):
        self.config_manager = config_manager
        self.config = config_manager.config
        self.base_dir = base_dir
        self.python_exe = sys.executable or "python"
        self.history: List[OptimizationResult] = []
        self.history_file = config_manager.get_output_path("param_opt_history.json")
        self._load_history()

    def _load_history(self):
        if os.path.isfile(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for item in data.get("history", []):
                    self.history.append(OptimizationResult(**item))
            except Exception as e:
                print(f"加载参数优化历史失败: {e}")

    def save_history(self):
        data = {
            "total_optimizations": len(self.history),
            "history": [h.to_dict() for h in self.history],
        }
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存参数优化历史失败: {e}")

    def get_search_param_space(self) -> List[ParameterSpace]:
        """获取搜索参数空间"""
        return [
            ParameterSpace("futility_margin_base", "search", 50, 150, 100, 10),
            ParameterSpace("futility_margin_mult", "search", 10, 40, 25, 2),
            ParameterSpace("razoring_margin", "search", 200, 500, 350, 25),
            ParameterSpace("nmp_reduction", "search", 2, 5, 3, 0.5),
            ParameterSpace("lmr_base", "search", 0.5, 1.5, 1.0, 0.1),
            ParameterSpace("lmr_divisor", "search", 1.5, 3.0, 2.0, 0.1),
            ParameterSpace("aspiration_window", "search", 15, 50, 30, 5),
            ParameterSpace("delta_pruning_margin", "search", 100, 300, 200, 20),
            ParameterSpace("see_threshold", "search", 50, 150, 100, 10),
            ParameterSpace("history_prune_threshold", "search", -1000, -100, -500, 50),
        ]

    def get_eval_param_space(self) -> List[ParameterSpace]:
        """获取评估参数空间"""
        return [
            ParameterSpace("piece_value_pawn", "eval", 80, 120, 100, 5),
            ParameterSpace("piece_value_knight", "eval", 300, 400, 320, 10),
            ParameterSpace("piece_value_bishop", "eval", 300, 400, 330, 10),
            ParameterSpace("piece_value_rook", "eval", 450, 600, 500, 15),
            ParameterSpace("piece_value_queen", "eval", 850, 1100, 900, 25),
            ParameterSpace("bishop_pair_bonus", "eval", 20, 60, 30, 5),
            ParameterSpace("passed_pawn_bonus", "eval", 10, 50, 20, 5),
            ParameterSpace("king_safety_weight", "eval", 0.5, 2.0, 1.0, 0.1),
            ParameterSpace("mobility_weight", "eval", 0.5, 2.0, 1.0, 0.1),
            ParameterSpace("space_weight", "eval", 0.1, 1.0, 0.5, 0.1),
        ]

    def get_time_mgmt_param_space(self) -> List[ParameterSpace]:
        """获取时间管理参数空间"""
        return [
            ParameterSpace("time_base_factor", "time", 0.02, 0.08, 0.04, 0.005),
            ParameterSpace("time_increment_factor", "time", 0.5, 1.0, 0.7, 0.05),
            ParameterSpace("time_complexity_factor", "time", 0.5, 2.0, 1.0, 0.1),
            ParameterSpace("time_bookend_factor", "time", 0.5, 1.5, 1.0, 0.1),
            ParameterSpace("ponder_enabled", "time", 0, 1, 1, 1),
        ]

    def get_tactical_param_space(self) -> List[ParameterSpace]:
        """获取战术参数空间（子力交换、棋子安全）"""
        return [
            ParameterSpace("exchange_depth", "tactical", 20, 30, 25, 1),
            ParameterSpace("see_depth", "tactical", 8, 16, 12, 1),
            ParameterSpace("tactical_threat_bonus", "tactical", 50, 200, 100, 10),
            ParameterSpace("hanging_piece_penalty", "tactical", 50, 200, 100, 10),
            ParameterSpace("fork_bonus", "tactical", 100, 300, 200, 20),
            ParameterSpace("pin_bonus", "tactical", 50, 150, 100, 10),
            ParameterSpace("skewer_bonus", "tactical", 50, 150, 100, 10),
            ParameterSpace("discovered_attack_bonus", "tactical", 50, 150, 100, 10),
        ]

    def optimize_with_spsa(self, param_space: List[ParameterSpace],
                           base_config: str, iterations: int = 50,
                           games_per_iteration: int = 20,
                           opponent: str = "tscp181", tc: str = "10+0.1") -> List[OptimizationResult]:
        """使用SPSA优化参数"""
        print(f"\n开始SPSA参数优化: {len(param_space)} 个参数, {iterations} 次迭代")

        results = []
        spsa_script = os.path.join(self.base_dir, "spsa_tuner.py")

        if not os.path.isfile(spsa_script):
            print(f"SPSA调优脚本未找到: {spsa_script}")
            return results

        for param in param_space:
            print(f"\n优化参数: {param.name} (当前值: {param.current_value})")

            try:
                result = subprocess.run(
                    [
                        self.python_exe, spsa_script, "run",
                        "--config", os.path.splitext(os.path.basename(base_config))[0],
                        "--iterations", str(iterations),
                        "--games", str(games_per_iteration),
                        "--tc", tc,
                        "--opponent", opponent,
                        "--params", param.name,
                    ],
                    capture_output=True,
                    text=True,
                    cwd=self.base_dir,
                    timeout=7200,
                )

                if result.returncode == 0:
                    new_value = self._parse_spsa_result(result.stdout, param.name)
                    if new_value is not None:
                        opt_result = OptimizationResult(
                            param_name=param.name,
                            old_value=param.current_value,
                            new_value=new_value,
                            improvement=0.0,
                            games_played=iterations * games_per_iteration,
                            confidence=0.8,
                        )
                        results.append(opt_result)
                        self.history.append(opt_result)
                        print(f"  {param.name}: {param.current_value} -> {new_value}")
                else:
                    print(f"  SPSA优化失败: {result.stderr[:200]}")

            except Exception as e:
                print(f"  优化异常: {e}")

        self.save_history()
        return results

    def optimize_with_texel(self, positions_file: str,
                            output_file: str = "texel_result.json",
                            iterations: int = 1000,
                            learning_rate: float = 0.01) -> List[OptimizationResult]:
        """使用Texel Tuning优化评估参数"""
        print(f"\n开始Texel Tuning优化")

        results = []
        texel_script = os.path.join(self.base_dir, "texel_tuner.py")

        if not os.path.isfile(texel_script):
            print(f"Texel调优脚本未找到: {texel_script}")
            return results

        try:
            result = subprocess.run(
                [
                    self.python_exe, texel_script,
                    "--positions", positions_file,
                    "--output", output_file,
                    "--iterations", str(iterations),
                    "--learning-rate", str(learning_rate),
                ],
                capture_output=True,
                text=True,
                cwd=self.base_dir,
                timeout=3600,
            )

            if result.returncode == 0:
                print("Texel Tuning完成")
                if os.path.isfile(output_file):
                    with open(output_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    for param_name, new_value in data.get("optimized_params", {}).items():
                        opt_result = OptimizationResult(
                            param_name=param_name,
                            old_value=data.get("original_params", {}).get(param_name, 0),
                            new_value=new_value,
                            improvement=data.get("error_reduction", 0),
                            games_played=iterations,
                            confidence=0.9,
                        )
                        results.append(opt_result)
                        self.history.append(opt_result)
            else:
                print(f"Texel Tuning失败: {result.stderr[:200]}")

        except Exception as e:
            print(f"Texel Tuning异常: {e}")

        self.save_history()
        return results

    def grid_search(self, param_space: List[ParameterSpace],
                    base_config: str, games_per_point: int = 10,
                    opponent: str = "tscp181", tc: str = "10+0.1") -> List[OptimizationResult]:
        """网格搜索离散参数"""
        print(f"\n开始网格搜索: {len(param_space)} 个参数")

        results = []

        for param in param_space:
            if not param.discrete_values:
                param.discrete_values = self._generate_grid_points(param)

            best_value = param.current_value
            best_score = 0.5

            for value in param.discrete_values:
                print(f"  测试 {param.name} = {value}")
                score = self._test_param_value(param, value, base_config,
                                                games_per_point, opponent, tc)
                if score > best_score:
                    best_score = score
                    best_value = value

            if best_value != param.current_value:
                opt_result = OptimizationResult(
                    param_name=param.name,
                    old_value=param.current_value,
                    new_value=best_value,
                    improvement=best_score - 0.5,
                    games_played=len(param.discrete_values) * games_per_point,
                    confidence=min(0.99, 0.5 + best_score - 0.5),
                )
                results.append(opt_result)
                self.history.append(opt_result)
                print(f"  {param.name}: {param.current_value} -> {best_value} (胜率: {best_score:.2%})")

        self.save_history()
        return results

    def _generate_grid_points(self, param: ParameterSpace) -> List[float]:
        """生成网格搜索点"""
        points = []
        current = param.min_value
        while current <= param.max_value:
            points.append(current)
            current += param.step_size
        return points

    def _test_param_value(self, param: ParameterSpace, value: float,
                          base_config: str, games: int,
                          opponent: str, tc: str) -> float:
        """测试单个参数值"""
        try:
            with open(base_config, 'r', encoding='utf-8') as f:
                config_data = json.load(f)

            config_data[param.name] = value
            test_config = os.path.join(self.base_dir, "configs", f"test_{param.name}.json")
            with open(test_config, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2)

            run_match_script = os.path.join(self.base_dir, "run_match.py")
            result = subprocess.run(
                [
                    self.python_exe, run_match_script,
                    "--opponent", opponent,
                    "--rounds", str(games),
                    "--tc", tc,
                    "--config", f"test_{param.name}",
                ],
                capture_output=True,
                text=True,
                cwd=self.base_dir,
                timeout=1800,
            )

            wins, losses, draws = self._parse_match_output(result.stdout + result.stderr)
            total = wins + losses + draws
            if total == 0:
                return 0.5
            return (wins + 0.5 * draws) / total

        except Exception as e:
            print(f"  测试失败: {e}")
            return 0.5

    def _parse_match_output(self, output: str) -> Tuple[int, int, int]:
        """解析对局输出"""
        import re
        pattern = re.compile(r"Score of\s+.+?\s+vs\s+.+?:\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)")
        for line in output.splitlines():
            m = pattern.search(line)
            if m:
                return int(m.group(1)), int(m.group(2)), int(m.group(3))
        return 0, 0, 0

    def _parse_spsa_result(self, output: str, param_name: str) -> Optional[float]:
        """解析SPSA结果"""
        import re
        pattern = re.compile(rf"{param_name}\s*[:=]\s*([\d.]+)")
        for line in output.splitlines():
            m = pattern.search(line)
            if m:
                return float(m.group(1))
        return None

    def validate_param(self, param: ParameterSpace, value: float) -> bool:
        """验证参数合法性"""
        if param.discrete_values:
            return value in param.discrete_values
        return param.min_value <= value <= param.max_value

    def check_convergence(self, param_name: str, window_size: int = 5) -> bool:
        """检查参数是否收敛"""
        param_history = [h for h in self.history if h.param_name == param_name]
        if len(param_history) < window_size * 2:
            return False

        recent = param_history[-window_size:]
        older = param_history[-window_size * 2:-window_size]

        recent_avg = sum(h.new_value for h in recent) / len(recent)
        older_avg = sum(h.new_value for h in older) / len(older)

        return abs(recent_avg - older_avg) < 0.01 * abs(older_avg)

    def get_param_interactions(self) -> Dict[str, List[str]]:
        """识别参数之间的相互影响"""
        interactions = {}
        param_names = list(set(h.param_name for h in self.history))

        for i, p1 in enumerate(param_names):
            interactions[p1] = []
            for p2 in param_names[i + 1:]:
                if self._check_param_correlation(p1, p2):
                    interactions[p1].append(p2)

        return interactions

    def _check_param_correlation(self, p1: str, p2: str, threshold: float = 0.5) -> bool:
        """检查两个参数是否相关"""
        h1 = [h for h in self.history if h.param_name == p1]
        h2 = [h for h in self.history if h.param_name == p2]

        if len(h1) < 3 or len(h2) < 3:
            return False

        improvements_1 = [h.improvement for h in h1[-5:]]
        improvements_2 = [h.improvement for h in h2[-5:]]

        if len(improvements_1) != len(improvements_2):
            return False

        mean_1 = sum(improvements_1) / len(improvements_1)
        mean_2 = sum(improvements_2) / len(improvements_2)

        numerator = sum((a - mean_1) * (b - mean_2) for a, b in zip(improvements_1, improvements_2))
        denom_1 = math.sqrt(sum((a - mean_1) ** 2 for a in improvements_1))
        denom_2 = math.sqrt(sum((b - mean_2) ** 2 for b in improvements_2))

        if denom_1 == 0 or denom_2 == 0:
            return False

        correlation = numerator / (denom_1 * denom_2)
        return abs(correlation) > threshold

    def generate_optimization_report(self) -> Dict[str, Any]:
        """生成优化报告"""
        if not self.history:
            return {"error": "没有优化历史"}

        param_stats = {}
        for h in self.history:
            if h.param_name not in param_stats:
                param_stats[h.param_name] = {
                    "optimizations": 0,
                    "total_improvement": 0,
                    "best_value": h.new_value,
                    "current_value": h.new_value,
                }
            param_stats[h.param_name]["optimizations"] += 1
            param_stats[h.param_name]["total_improvement"] += h.improvement
            param_stats[h.param_name]["current_value"] = h.new_value

        return {
            "total_optimizations": len(self.history),
            "unique_params": len(param_stats),
            "param_stats": param_stats,
            "interactions": self.get_param_interactions(),
        }

    def save_optimization_report(self, output_path: Optional[str] = None):
        if output_path is None:
            output_path = self.config_manager.get_output_path("param_optimization_report.json")
        report = self.generate_optimization_report()
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"参数优化报告已保存: {output_path}")
