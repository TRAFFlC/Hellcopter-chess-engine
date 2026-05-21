#!/usr/bin/env python3
"""
SPSA (Simultaneous Perturbation Stochastic Approximation) 自动调优框架

SPSA 是一种高效的随机优化算法，特别适合高维参数空间的优化问题。
与传统的梯度下降不同，SPSA 只需要两次函数评估就能估计所有参数的梯度。

核心算法：
- 参数更新: θ(k+1) = θ(k) - a(k) * g(k)
- 梯度估计: g(k) = (L(θ+ckΔ) - L(θ-ckΔ)) / (2*ckΔ)
- 扰动向量: Δ 为随机 ±1 向量

优点：
1. 同时扰动所有参数，评估次数与参数数量无关
2. 对噪声具有鲁棒性，适合对弈测试这种随机性较大的场景
3. 收敛到局部最优解
"""

import argparse
import copy
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import shutil
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Callable


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIGS_DIR = os.path.join(BASE_DIR, "configs")
SPSA_RECORDS_DIR = os.path.join(BASE_DIR, "spsa_records")


SPSA_PARAMS = {
    "search_params.null_move_reduction": {
        "min": 1, "max": 4, "step": 1,
        "desc": "空着裁剪深度减少量",
        "c": 0.5,
    },
    "search_params.null_move_min_depth": {
        "min": 2, "max": 6, "step": 1,
        "desc": "启用空着裁剪的最小深度",
        "c": 0.5,
    },
    "search_params.lmr_min_depth": {
        "min": 2, "max": 6, "step": 1,
        "desc": "启用 LMR 的最小深度",
        "c": 0.5,
    },
    "search_params.lmr_move_threshold": {
        "min": 1, "max": 8, "step": 1,
        "desc": "开始应用 LMR 的移动序号",
        "c": 0.5,
    },
    "search_params.futility_margin_base": {
        "min": 50, "max": 300, "step": 25,
        "desc": "无用裁剪基础边界",
        "c": 50.0,
    },
    "search_params.razoring_margin": {
        "min": 100, "max": 500, "step": 50,
        "desc": "剃刀裁剪边界",
        "c": 100.0,
    },
    "eval_weights.bishop_pair_bonus": {
        "min": 20, "max": 100, "step": 5,
        "desc": "双象奖励",
        "c": 10.0,
    },
    "eval_weights.doubled_pawn_penalty": {
        "min": -30, "max": -3, "step": 3,
        "desc": "叠兵惩罚",
        "c": 5.0,
    },
    "eval_weights.isolated_pawn_penalty": {
        "min": -40, "max": -10, "step": 5,
        "desc": "孤兵惩罚",
        "c": 5.0,
    },
    "eval_weights.open_file_bonus": {
        "min": 5, "max": 30, "step": 5,
        "desc": "开放线奖励",
        "c": 5.0,
    },
    "constants.delta": {
        "min": 100, "max": 400, "step": 50,
        "desc": "Delta 裁剪边界",
        "c": 50.0,
    },
}


def _get_nested(d: Dict, key: str) -> Any:
    keys = key.split(".")
    val = d
    for k in keys:
        if isinstance(val, dict) and k in val:
            val = val[k]
        else:
            return None
    return val


def _set_nested(d: Dict, key: str, value: Any):
    keys = key.split(".")
    obj = d
    for k in keys[:-1]:
        if k not in obj:
            obj[k] = {}
        obj = obj[k]
    obj[keys[-1]] = value


def _clamp(value: float, min_val: float, max_val: float, step: float) -> float:
    clamped = max(min_val, min(max_val, value))
    if step > 0:
        clamped = round(clamped / step) * step
        clamped = max(min_val, min(max_val, clamped))
    return int(clamped) if step == 1 else clamped


class SPSAConfig:
    def __init__(
        self,
        a: float = 100.0,
        A: float = 100.0,
        alpha: float = 1.0,
        c: float = 1.0,
        gamma: float = 0.166,
        target_elo: float = 0.0,
        max_iterations: int = 100,
        games_per_eval: int = 100,
        time_control: str = "10+0.1",
        opponent: str = "tscp181",
    ):
        self.a = a
        self.A = A
        self.alpha = alpha
        self.c = c
        self.gamma = gamma
        self.target_elo = target_elo
        self.max_iterations = max_iterations
        self.games_per_eval = games_per_eval
        self.time_control = time_control
        self.opponent = opponent

    def a_k(self, k: int) -> float:
        return self.a / ((self.A + k) ** self.alpha)

    def c_k(self, k: int, param_c: float) -> float:
        return self.c * param_c / (k ** self.gamma) if k > 0 else self.c * param_c

    def to_dict(self) -> Dict:
        return {
            "a": self.a,
            "A": self.A,
            "alpha": self.alpha,
            "c": self.c,
            "gamma": self.gamma,
            "target_elo": self.target_elo,
            "max_iterations": self.max_iterations,
            "games_per_eval": self.games_per_eval,
            "time_control": self.time_control,
            "opponent": self.opponent,
        }


class SPSAResult:
    def __init__(self):
        self.iterations: List[Dict] = []
        self.best_params: Optional[Dict] = None
        self.best_elo: float = -float("inf")
        self.best_iteration: int = -1
        self.start_time: str = datetime.now().isoformat()
        self.end_time: Optional[str] = None

    def add_iteration(
        self,
        iteration: int,
        params: Dict,
        elo_plus: float,
        elo_minus: float,
        gradient: Dict[str, float],
        perturbation: Dict[str, int],
        c_k: float,
    ):
        avg_elo = (elo_plus + elo_minus) / 2
        self.iterations.append({
            "iteration": iteration,
            "params": copy.deepcopy(params),
            "elo_plus": elo_plus,
            "elo_minus": elo_minus,
            "avg_elo": avg_elo,
            "gradient": gradient,
            "perturbation": perturbation,
            "c_k": c_k,
            "timestamp": datetime.now().isoformat(),
        })
        if avg_elo > self.best_elo:
            self.best_elo = avg_elo
            self.best_params = copy.deepcopy(params)
            self.best_iteration = iteration

    def finalize(self):
        self.end_time = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_iterations": len(self.iterations),
            "best_iteration": self.best_iteration,
            "best_elo": self.best_elo,
            "best_params": self.best_params,
            "iterations": self.iterations,
        }


class MatchEvaluator:
    def __init__(self, base_dir: str = BASE_DIR):
        self.base_dir = base_dir
        self.configs_dir = os.path.join(base_dir, "configs")
        os.makedirs(self.configs_dir, exist_ok=True)

    def evaluate(
        self,
        params: Dict,
        opponent: str = "shallowblue",
        rounds: int = 50,
        time_control: str = "10+0.1",
        base_version: str = "v1.5.0",
    ) -> Tuple[float, int, int, int]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        test_version = f"spsa_{timestamp}"

        config = self._create_config(params, test_version, base_version)
        config_path = os.path.join(self.configs_dir, f"{test_version}.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    os.path.join(self.base_dir, "run_match.py"),
                    "--opponent", opponent,
                    "--rounds", str(rounds),
                    "--tc", time_control,
                    "--config", test_version,
                ],
                capture_output=True,
                text=True,
                cwd=self.base_dir,
                timeout=3600,
            )
            output = result.stdout + result.stderr
            wins, losses, draws = self._parse_match_result(output)
            total = wins + losses + draws
            if total > 0:
                score = (wins + 0.5 * draws) / total
                if 0 < score < 1:
                    elo = -400 * math.log10((1 - score) / score)
                else:
                    elo = 1000.0 if score >= 1 else -1000.0
            else:
                elo = 0.0
            return elo, wins, losses, draws
        except subprocess.TimeoutExpired:
            print("  [警告] 测试超时")
            return 0.0, 0, 0, 0
        except Exception as e:
            print(f"  [错误] 测试失败: {e}")
            return 0.0, 0, 0, 0
        finally:
            if os.path.exists(config_path):
                os.remove(config_path)

    def _create_config(self, params: Dict, version: str, base_version: str) -> Dict:
        base_path = os.path.join(self.configs_dir, f"{base_version}.json")
        if os.path.exists(base_path):
            with open(base_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        else:
            config = {"version": base_version, "parameters": {}}

        config["version"] = version
        config["base_version"] = base_version
        config["created_at"] = datetime.now().isoformat()
        config["description"] = f"SPSA tuning test - {version}"

        if "parameters" not in config:
            config["parameters"] = {}

        for key, value in params.items():
            _set_nested(config["parameters"], key, value)

        return config

    def _parse_match_result(self, output: str) -> Tuple[int, int, int]:
        import re
        pattern = re.compile(r"Score of\s+.+?:\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)")
        last_match = None
        for line in output.splitlines():
            m = pattern.search(line)
            if m:
                last_match = m
        if last_match:
            return int(last_match.group(1)), int(last_match.group(2)), int(last_match.group(3))
        print("  [警告] 无法解析对弈结果，输出片段:")
        for line in output.splitlines()[-10:]:
            print(f"    {line[:100]}")
        return 0, 0, 0


class SPSATuner:
    def __init__(
        self,
        base_version: str = "v1.5.0",
        spsa_config: Optional[SPSAConfig] = None,
        params_to_tune: Optional[List[str]] = None,
    ):
        self.base_version = base_version
        self.spsa_config = spsa_config or SPSAConfig()
        self.params_to_tune = params_to_tune or list(SPSA_PARAMS.keys())
        self.evaluator = MatchEvaluator()
        self.result = SPSAResult()
        self._ensure_records_dir()

        self.base_config = self._load_base_config()
        self.current_params = self._extract_params(self.base_config)

    def _ensure_records_dir(self):
        os.makedirs(SPSA_RECORDS_DIR, exist_ok=True)

    def _load_base_config(self) -> Dict:
        config_path = os.path.join(CONFIGS_DIR, f"{self.base_version}.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"parameters": {}}

    def _extract_params(self, config: Dict) -> Dict[str, Any]:
        params = {}
        param_groups = config.get("parameters", {})
        for key in self.params_to_tune:
            value = _get_nested(param_groups, key)
            if value is not None:
                params[key] = value
            else:
                spec = SPSA_PARAMS.get(key, {})
                default_val = (spec["min"] + spec["max"]) // 2
                params[key] = default_val
        return params

    def _generate_perturbation(self) -> Dict[str, int]:
        return {key: random.choice([-1, 1]) for key in self.params_to_tune}

    def _apply_perturbation(
        self,
        params: Dict[str, Any],
        perturbation: Dict[str, int],
        c_k: float,
        sign: int,
    ) -> Dict[str, Any]:
        perturbed = copy.deepcopy(params)
        for key in self.params_to_tune:
            if key not in perturbed:
                continue
            spec = SPSA_PARAMS.get(key, {})
            param_c = spec.get("c", 1.0)
            delta = sign * perturbation[key] * c_k * param_c
            new_val = perturbed[key] + delta
            new_val = _clamp(new_val, spec["min"], spec["max"], spec["step"])
            perturbed[key] = new_val
        return perturbed

    def _estimate_gradient(
        self,
        elo_plus: float,
        elo_minus: float,
        perturbation: Dict[str, int],
        c_k: float,
    ) -> Dict[str, float]:
        gradient = {}
        for key in self.params_to_tune:
            spec = SPSA_PARAMS.get(key, {})
            param_c = spec.get("c", 1.0)
            delta = c_k * param_c
            if delta > 0:
                g = (elo_plus - elo_minus) / (2 * delta * perturbation[key])
            else:
                g = 0.0
            gradient[key] = g
        return gradient

    def _update_params(
        self,
        params: Dict[str, Any],
        gradient: Dict[str, float],
        a_k: float,
    ) -> Dict[str, Any]:
        updated = copy.deepcopy(params)
        for key in self.params_to_tune:
            if key not in gradient:
                continue
            spec = SPSA_PARAMS.get(key, {})
            step = a_k * gradient[key]
            new_val = updated[key] - step
            new_val = _clamp(new_val, spec["min"], spec["max"], spec["step"])
            updated[key] = new_val
        return updated

    def tune(self, verbose: bool = True) -> SPSAResult:
        if verbose:
            self._print_header()

        for k in range(1, self.spsa_config.max_iterations + 1):
            a_k = self.spsa_config.a_k(k)
            c_k = self.spsa_config.c_k(k, 1.0)

            perturbation = self._generate_perturbation()

            params_plus = self._apply_perturbation(
                self.current_params, perturbation, c_k, +1
            )
            params_minus = self._apply_perturbation(
                self.current_params, perturbation, c_k, -1
            )

            if verbose:
                print(f"\n{'='*60}")
                print(f"迭代 {k}/{self.spsa_config.max_iterations}")
                print(f"  a(k) = {a_k:.4f}, c(k) = {c_k:.4f}")
                print(f"  扰动向量: {list(perturbation.values())[:5]}...")

            if verbose:
                print(f"\n  评估 θ + c(k)Δ...")
            elo_plus, w_p, l_p, d_p = self.evaluator.evaluate(
                params_plus,
                opponent=self.spsa_config.opponent,
                rounds=self.spsa_config.games_per_eval,
                time_control=self.spsa_config.time_control,
                base_version=self.base_version,
            )
            if verbose:
                print(f"    结果: {w_p}W-{l_p}L-{d_p}D, Elo = {elo_plus:+.1f}")

            if verbose:
                print(f"\n  评估 θ - c(k)Δ...")
            elo_minus, w_m, l_m, d_m = self.evaluator.evaluate(
                params_minus,
                opponent=self.spsa_config.opponent,
                rounds=self.spsa_config.games_per_eval,
                time_control=self.spsa_config.time_control,
                base_version=self.base_version,
            )
            if verbose:
                print(f"    结果: {w_m}W-{l_m}L-{d_m}D, Elo = {elo_minus:+.1f}")

            gradient = self._estimate_gradient(elo_plus, elo_minus, perturbation, c_k)

            self.result.add_iteration(
                iteration=k,
                params=copy.deepcopy(self.current_params),
                elo_plus=elo_plus,
                elo_minus=elo_minus,
                gradient=gradient,
                perturbation=perturbation,
                c_k=c_k,
            )

            self.current_params = self._update_params(
                self.current_params, gradient, a_k
            )

            if verbose:
                print(f"\n  梯度估计: {list(gradient.values())[:3]}...")
                print(f"  当前参数: {list(self.current_params.values())[:3]}...")
                print(f"  平均 Elo: {(elo_plus + elo_minus) / 2:+.1f}")

            if self.spsa_config.target_elo > 0:
                avg_elo = (elo_plus + elo_minus) / 2
                if avg_elo >= self.spsa_config.target_elo:
                    if verbose:
                        print(f"\n  达到目标 Elo: {avg_elo:.1f} >= {self.spsa_config.target_elo}")
                    break

            self._save_checkpoint(k)

        self.result.finalize()
        self._save_result()

        if verbose:
            self._print_summary()

        return self.result

    def _print_header(self):
        print("\n" + "=" * 60)
        print("SPSA 自动调优")
        print("=" * 60)
        print(f"基础配置: {self.base_version}")
        print(f"调优参数: {len(self.params_to_tune)} 个")
        print(f"最大迭代: {self.spsa_config.max_iterations}")
        print(f"每次评估对局: {self.spsa_config.games_per_eval}")
        print(f"时间控制: {self.spsa_config.time_control}")
        print(f"对手引擎: {self.spsa_config.opponent}")
        print("-" * 60)
        print("\n初始参数:")
        for key, value in self.current_params.items():
            spec = SPSA_PARAMS.get(key, {})
            desc = spec.get("desc", "")
            print(f"  {key}: {value} ({desc})")

    def _print_summary(self):
        print("\n" + "=" * 60)
        print("SPSA 调优完成")
        print("=" * 60)
        print(f"总迭代次数: {len(self.result.iterations)}")
        print(f"最佳迭代: {self.result.best_iteration}")
        print(f"最佳 Elo: {self.result.best_elo:+.1f}")
        print("\n最佳参数:")
        if self.result.best_params:
            for key, value in self.result.best_params.items():
                spec = SPSA_PARAMS.get(key, {})
                desc = spec.get("desc", "")
                print(f"  {key}: {value} ({desc})")

    def _save_checkpoint(self, iteration: int):
        checkpoint = {
            "iteration": iteration,
            "current_params": self.current_params,
            "result": self.result.to_dict(),
            "spsa_config": self.spsa_config.to_dict(),
            "timestamp": datetime.now().isoformat(),
        }
        path = os.path.join(SPSA_RECORDS_DIR, "checkpoint.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, indent=2, ensure_ascii=False)

    def _save_result(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"spsa_result_{timestamp}.json"
        path = os.path.join(SPSA_RECORDS_DIR, filename)

        result_data = self.result.to_dict()
        result_data["spsa_config"] = self.spsa_config.to_dict()
        result_data["base_version"] = self.base_version
        result_data["params_to_tune"] = self.params_to_tune

        with open(path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, indent=2, ensure_ascii=False)

        print(f"\n结果已保存: {filename}")

    def export_best_config(self, version: Optional[str] = None) -> str:
        if not self.result.best_params:
            print("错误: 没有找到最佳参数")
            return ""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_version = version or f"v_spsa_{timestamp}"

        config = copy.deepcopy(self.base_config)
        config["version"] = new_version
        config["base_version"] = self.base_version
        config["created_at"] = datetime.now().isoformat()
        config["description"] = f"SPSA auto-tuned config - Elo: {self.result.best_elo:+.1f}"

        if "parameters" not in config:
            config["parameters"] = {}

        for key, value in self.result.best_params.items():
            _set_nested(config["parameters"], key, value)

        config_path = os.path.join(CONFIGS_DIR, f"{new_version}.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        print(f"\n最佳配置已导出: {config_path}")
        return config_path

    def load_checkpoint(self, path: Optional[str] = None) -> bool:
        if path is None:
            path = os.path.join(SPSA_RECORDS_DIR, "checkpoint.json")
        if not os.path.exists(path):
            print(f"检查点文件不存在: {path}")
            return False

        with open(path, "r", encoding="utf-8") as f:
            checkpoint = json.load(f)

        self.current_params = checkpoint["current_params"]

        print(f"已加载检查点: 迭代 {checkpoint['iteration']}")
        return True


def visualize_history(result_path: str):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("需要安装 matplotlib: pip install matplotlib")
        return

    with open(result_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    iterations = data["iterations"]
    if not iterations:
        print("没有迭代数据")
        return

    x = [it["iteration"] for it in iterations]
    y_avg = [it["avg_elo"] for it in iterations]
    y_plus = [it["elo_plus"] for it in iterations]
    y_minus = [it["elo_minus"] for it in iterations]

    fig, axes = plt.subplots(2, 1, figsize=(10, 8))

    axes[0].plot(x, y_avg, "b-", label="平均 Elo", linewidth=2)
    axes[0].plot(x, y_plus, "g--", label="Elo (+)", alpha=0.5)
    axes[0].plot(x, y_minus, "r--", label="Elo (-)", alpha=0.5)
    axes[0].axhline(y=0, color="k", linestyle=":", alpha=0.3)
    axes[0].set_xlabel("迭代次数")
    axes[0].set_ylabel("Elo 差")
    axes[0].set_title("SPSA 调优进度")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    params_to_tune = data.get("params_to_tune", [])
    if params_to_tune and iterations:
        param_history = {key: [] for key in params_to_tune}
        for it in iterations:
            params = it.get("params", {})
            for key in params_to_tune:
                param_history[key].append(params.get(key, 0))

        for key, values in param_history.items():
            short_key = key.split(".")[-1]
            axes[1].plot(x[: len(values)], values, marker=".", label=short_key)

        axes[1].set_xlabel("迭代次数")
        axes[1].set_ylabel("参数值")
        axes[1].set_title("参数变化轨迹")
        axes[1].legend(loc="best", fontsize=8)
        axes[1].grid(True, alpha=0.3)

    plt.tight_layout()

    output_path = result_path.replace(".json", "_plot.png")
    plt.savefig(output_path, dpi=150)
    print(f"图表已保存: {output_path}")
    plt.show()


def list_results():
    if not os.path.exists(SPSA_RECORDS_DIR):
        print("暂无调优记录")
        return

    results = []
    for filename in os.listdir(SPSA_RECORDS_DIR):
        if filename.startswith("spsa_result_") and filename.endswith(".json"):
            path = os.path.join(SPSA_RECORDS_DIR, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                results.append({
                    "filename": filename,
                    "iterations": len(data.get("iterations", [])),
                    "best_elo": data.get("best_elo", 0),
                    "best_iteration": data.get("best_iteration", 0),
                    "timestamp": data.get("start_time", ""),
                })
            except:
                pass

    results.sort(key=lambda x: x["timestamp"], reverse=True)

    print("\n" + "=" * 60)
    print("SPSA 调优历史记录")
    print("=" * 60)
    print(f"{'文件名':<30} {'迭代':>6} {'最佳Elo':>10} {'最佳迭代':>8}")
    print("-" * 60)
    for r in results:
        print(f"{r['filename']:<30} {r['iterations']:>6} {r['best_elo']:>+10.1f} {r['best_iteration']:>8}")


def main():
    parser = argparse.ArgumentParser(
        description="SPSA 自动调优工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python spsa_tuner.py run                              # 使用默认配置运行 SPSA
  python spsa_tuner.py run --iterations 50              # 运行 50 次迭代
  python spsa_tuner.py run --games 200 --tc "20+0.2"    # 每次评估 200 局，时间控制 20+0.2
  python spsa_tuner.py run --params lmr_min_depth null_move_reduction  # 只调优指定参数
  python spsa_tuner.py list                             # 列出历史记录
  python spsa_tuner.py visualize spsa_result_xxx.json   # 可视化调优结果
  python spsa_tuner.py export spsa_result_xxx.json      # 导出最佳配置
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="命令")

    run_parser = subparsers.add_parser("run", help="运行 SPSA 调优")
    run_parser.add_argument("--config", default="v1.5.0", help="基础配置版本")
    run_parser.add_argument("--iterations", type=int, default=50, help="最大迭代次数")
    run_parser.add_argument("--games", type=int, default=100, help="每次评估的对局数")
    run_parser.add_argument("--tc", default="10+0.1", help="时间控制")
    run_parser.add_argument("--opponent", default="tscp181", help="对手引擎")
    run_parser.add_argument("--params", nargs="+", help="要调优的参数")
    run_parser.add_argument("--a", type=float, default=100.0, help="SPSA 参数 a")
    run_parser.add_argument("--A", type=float, default=100.0, help="SPSA 参数 A")
    run_parser.add_argument("--c", type=float, default=1.0, help="SPSA 参数 c")
    run_parser.add_argument("--target-elo", type=float, default=0.0, help="目标 Elo")
    run_parser.add_argument("--resume", action="store_true", help="从检查点恢复")

    list_parser = subparsers.add_parser("list", help="列出历史记录")

    viz_parser = subparsers.add_parser("visualize", help="可视化调优结果")
    viz_parser.add_argument("result_file", help="结果文件路径")

    export_parser = subparsers.add_parser("export", help="导出最佳配置")
    export_parser.add_argument("result_file", help="结果文件路径")
    export_parser.add_argument("--version", help="新配置版本号")

    args = parser.parse_args()

    if args.command == "run":
        spsa_config = SPSAConfig(
            a=args.a,
            A=args.A,
            c=args.c,
            max_iterations=args.iterations,
            games_per_eval=args.games,
            time_control=args.tc,
            opponent=args.opponent,
            target_elo=args.target_elo,
        )

        params_to_tune = args.params if args.params else None

        tuner = SPSATuner(
            base_version=args.config,
            spsa_config=spsa_config,
            params_to_tune=params_to_tune,
        )

        if args.resume:
            tuner.load_checkpoint()

        result = tuner.tune()

        if result.best_params:
            tuner.export_best_config()

    elif args.command == "list":
        list_results()

    elif args.command == "visualize":
        result_path = args.result_file
        if not os.path.isabs(result_path):
            result_path = os.path.join(SPSA_RECORDS_DIR, result_path)
        visualize_history(result_path)

    elif args.command == "export":
        result_path = args.result_file
        if not os.path.isabs(result_path):
            result_path = os.path.join(SPSA_RECORDS_DIR, result_path)

        with open(result_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        tuner = SPSATuner(base_version=data.get("base_version", "v1.5.0"))
        tuner.result.best_params = data.get("best_params")
        tuner.result.best_elo = data.get("best_elo", 0)
        tuner.export_best_config(args.version)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
