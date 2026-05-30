"""
Texel Tuning 脚本 - 使用 SPSA 算法优化 Hellcopter 引擎评估参数

使用方法:
    python texel_tune.py
    python texel_tune.py --iterations 100 --positions 100
"""

import json
import math
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psutil

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "configs" / "v1.7.2.json"
POSITIONS_FILE = BASE_DIR / "quiet_positions_c.json"
ENGINE_EXE = BASE_DIR / "dist" / "Hellcopter.exe"
BUILD_SCRIPT = BASE_DIR / "build_engine.py"

K_FACTOR = 200.0

SPSA_PARAMS = {
    "bishop_pair_bonus": {"init": 50, "min": 10, "max": 100, "step": 1},
    "doubled_pawn_penalty": {"init": -10, "min": -50, "max": 0, "step": 1},
    "isolated_pawn_penalty": {"init": -20, "min": -60, "max": 0, "step": 1},
    "pawn_chain_bonus": {"init": 15, "min": 0, "max": 50, "step": 1},
    "open_file_bonus": {"init": 15, "min": 0, "max": 50, "step": 1},
    "semi_open_file_bonus": {"init": 10, "min": 0, "max": 40, "step": 1},
    "passed_pawn_bonus_0": {"init": 0, "min": 0, "max": 20, "step": 1},
    "passed_pawn_bonus_1": {"init": 10, "min": 0, "max": 40, "step": 1},
    "passed_pawn_bonus_2": {"init": 20, "min": 5, "max": 60, "step": 1},
    "passed_pawn_bonus_3": {"init": 30, "min": 10, "max": 80, "step": 1},
    "passed_pawn_bonus_4": {"init": 50, "min": 20, "max": 100, "step": 1},
    "passed_pawn_bonus_5": {"init": 80, "min": 30, "max": 150, "step": 1},
    "passed_pawn_bonus_6": {"init": 120, "min": 50, "max": 200, "step": 1},
}


class UCIEngine:
    def __init__(self, exe_path: Path):
        self.exe_path = exe_path
        self.process: Optional[subprocess.Popen] = None

    def start(self):
        if self.process and self.process.poll() is None:
            return
        self.process = subprocess.Popen(
            [str(self.exe_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=str(self.exe_path.parent),
        )
        self._send("uci")
        self._wait_for("uciok")
        self._send("isready")
        self._wait_for("readyok")

    def stop(self):
        if self.process:
            try:
                parent = psutil.Process(self.process.pid)
                children = parent.children(recursive=True)
                for child in children:
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                parent.kill()
            except psutil.NoSuchProcess:
                pass
            except Exception:
                if self.process.poll() is None:
                    self.process.kill()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            self.process = None
        time.sleep(1.0)

    def _send(self, cmd: str):
        if self.process and self.process.stdin:
            self.process.stdin.write(cmd + "\n")
            self.process.stdin.flush()

    def _wait_for(self, keyword: str, timeout: float = 10.0) -> str:
        if not self.process or not self.process.stdout:
            return ""
        start = time.time()
        while time.time() - start < timeout:
            line = self.process.stdout.readline().strip()
            if keyword in line:
                return line
        return ""

    def evaluate(self, fen: str, depth: int = 4) -> Optional[int]:
        if not self.process or self.process.poll() is not None:
            self.start()

        self._send(f"position fen {fen}")
        self._send("isready")
        self._wait_for("readyok")

        self._send(f"go depth {depth}")

        score = None
        start = time.time()
        while time.time() - start < 30.0:
            line = self.process.stdout.readline().strip()
            if not line:
                continue
            if "score cp" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "cp" and i + 1 < len(parts):
                        try:
                            score = int(parts[i + 1])
                        except ValueError:
                            pass
            if line.startswith("bestmove"):
                break

        return score

    def reload_params(self, config_path: Path):
        if not self.process or self.process.poll() is not None:
            self.start()


def sigmoid(x: float) -> float:
    scaled = x / K_FACTOR
    if scaled > 20:
        return 1.0 - 1e-10
    if scaled < -20:
        return 1e-10
    return 1.0 / (1.0 + math.exp(-scaled))


def load_config() -> Dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: Dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_current_params(config: Dict) -> Dict[str, float]:
    eval_weights = config["parameters"]["eval_weights"]
    params = {}
    params["bishop_pair_bonus"] = eval_weights.get("bishop_pair_bonus", 50)
    params["doubled_pawn_penalty"] = eval_weights.get("doubled_pawn_penalty", -10)
    params["isolated_pawn_penalty"] = eval_weights.get("isolated_pawn_penalty", -20)
    params["pawn_chain_bonus"] = eval_weights.get("pawn_chain_bonus", 15)
    params["open_file_bonus"] = eval_weights.get("open_file_bonus", 15)
    params["semi_open_file_bonus"] = eval_weights.get("semi_open_file_bonus", 10)
    ppb = eval_weights.get("passed_pawn_bonus", [0, 10, 20, 30, 50, 80, 120, 0])
    for i in range(7):
        params[f"passed_pawn_bonus_{i}"] = ppb[i] if i < len(ppb) else 0
    return params


def set_params_in_config(config: Dict, params: Dict[str, float]):
    eval_weights = config["parameters"]["eval_weights"]
    eval_weights["bishop_pair_bonus"] = int(params["bishop_pair_bonus"])
    eval_weights["doubled_pawn_penalty"] = int(params["doubled_pawn_penalty"])
    eval_weights["isolated_pawn_penalty"] = int(params["isolated_pawn_penalty"])
    eval_weights["pawn_chain_bonus"] = int(params["pawn_chain_bonus"])
    eval_weights["open_file_bonus"] = int(params["open_file_bonus"])
    eval_weights["semi_open_file_bonus"] = int(params["semi_open_file_bonus"])
    ppb = [0] * 8
    for i in range(7):
        ppb[i] = int(params[f"passed_pawn_bonus_{i}"])
    eval_weights["passed_pawn_bonus"] = ppb


def build_engine() -> bool:
    for proc in psutil.process_iter(['pid', 'name']):
        if 'Hellcopter' in proc.info['name']:
            try:
                proc.kill()
            except psutil.NoSuchProcess:
                pass

    time.sleep(1)

    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "exe", "--force", "--config", "v1.7.2"],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"编译失败:")
        if result.stdout:
            print(result.stdout[-500:])
        if result.stderr:
            print(result.stderr[-500:])
        return False
    return True


def calculate_error(positions: List[Dict], engine: UCIEngine) -> float:
    total_error = 0.0
    count = 0
    for pos in positions:
        result = pos["result"]
        if result == "1-0":
            result_val = 1.0
        elif result == "0-1":
            result_val = 0.0
        else:
            result_val = 0.5

        score = engine.evaluate(pos["fen"])
        if score is None:
            continue

        predicted = sigmoid(score)
        error = (predicted - result_val) ** 2
        total_error += error
        count += 1

    return total_error / count if count > 0 else float("inf")


def run_spsa(
    positions: List[Dict],
    num_iterations: int = 50,
    a: float = 10.0,
    c: float = 5.0,
    A: float = 100,
    alpha: float = 0.602,
    gamma: float = 0.101,
):
    config = load_config()
    current_params = get_current_params(config)

    engine = UCIEngine(ENGINE_EXE)
    engine.start()

    print("\n计算基准误差...")
    baseline_error = calculate_error(positions, engine)
    print(f"基准 MSE: {baseline_error:.6f}")

    best_params = current_params.copy()
    best_error = baseline_error
    error_history = [baseline_error]

    print(f"\n开始 SPSA 优化，共 {num_iterations} 次迭代...")
    print(f"参数数量: {len(current_params)}")

    for iteration in range(1, num_iterations + 1):
        ak = a / (iteration + A) ** alpha
        ck = c / iteration ** gamma

        delta = {}
        for param_name in current_params:
            delta[param_name] = 1 if random.random() > 0.5 else -1

        params_plus = {}
        params_minus = {}
        for param_name, value in best_params.items():
            param_info = SPSA_PARAMS[param_name]
            step = ck * delta[param_name] * param_info["step"]
            params_plus[param_name] = max(
                param_info["min"], min(param_info["max"], value + step)
            )
            params_minus[param_name] = max(
                param_info["min"], min(param_info["max"], value - step)
            )

        engine.stop()
        set_params_in_config(config, params_plus)
        save_config(config)
        if not build_engine():
            print(f"迭代 {iteration}: 编译失败，跳过")
            continue
        engine.start()
        error_plus = calculate_error(positions, engine)

        engine.stop()
        set_params_in_config(config, params_minus)
        save_config(config)
        if not build_engine():
            print(f"迭代 {iteration}: 编译失败，跳过")
            continue
        engine.start()
        error_minus = calculate_error(positions, engine)

        gradient = {}
        for param_name in current_params:
            gradient[param_name] = (error_plus - error_minus) / (
                2 * ck * delta[param_name] * SPSA_PARAMS[param_name]["step"]
            )

        new_params = {}
        for param_name, value in best_params.items():
            param_info = SPSA_PARAMS[param_name]
            new_value = value - ak * gradient[param_name]
            new_params[param_name] = max(
                param_info["min"], min(param_info["max"], new_value)
            )

        set_params_in_config(config, new_params)
        save_config(config)
        if not build_engine():
            print(f"迭代 {iteration}: 编译失败，跳过")
            continue
        engine.stop()
        engine.start()
        new_error = calculate_error(positions, engine)

        if new_error < best_error:
            best_error = new_error
            best_params = new_params.copy()
            improvement = "✓ 改善"
        else:
            improvement = "✗ 无改善"

        error_history.append(new_error)

        if iteration % 10 == 0 or iteration == 1:
            print(
                f"迭代 {iteration:4d}: 误差={new_error:.6f}, "
                f"最佳={best_error:.6f}, ak={ak:.4f}, ck={ck:.4f} {improvement}"
            )

    set_params_in_config(config, best_params)
    save_config(config)
    build_engine()

    engine.stop()

    print("\n" + "=" * 60)
    print("优化完成")
    print("=" * 60)
    print(f"初始误差: {baseline_error:.6f}")
    print(f"最终误差: {best_error:.6f}")
    print(f"误差改善: {baseline_error - best_error:.6f} ({(baseline_error - best_error) / baseline_error * 100:.2f}%)")
    print(f"\n优化后的参数:")
    for param_name, value in sorted(best_params.items()):
        print(f"  {param_name}: {value:.1f}")

    return best_params, best_error, baseline_error


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Texel Tuning - SPSA 优化")
    parser.add_argument("--iterations", type=int, default=50, help="迭代次数 (默认: 50)")
    parser.add_argument("--positions", type=int, default=0, help="使用的局面数量 (0=全部)")
    parser.add_argument("--a", type=float, default=10.0, help="SPSA a 参数")
    parser.add_argument("--c", type=float, default=5.0, help="SPSA c 参数")
    parser.add_argument("--A", type=float, default=100, help="SPSA A 参数")
    parser.add_argument("--alpha", type=float, default=0.602, help="SPSA alpha 参数")
    parser.add_argument("--gamma", type=float, default=0.101, help="SPSA gamma 参数")
    args = parser.parse_args()

    print("=" * 60)
    print("Texel Tuning - SPSA 优化 Hellcopter 引擎评估参数")
    print("=" * 60)

    print(f"\n加载局面数据: {POSITIONS_FILE}")
    with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
        all_positions = json.load(f)
    print(f"总局面数: {len(all_positions)}")

    if args.positions > 0 and args.positions < len(all_positions):
        positions = random.sample(all_positions, args.positions)
        print(f"采样局面数: {args.positions}")
    else:
        positions = all_positions
        print(f"使用全部局面: {len(positions)}")

    print(f"\nSPSA 参数:")
    print(f"  迭代次数: {args.iterations}")
    print(f"  a={args.a}, c={args.c}, A={args.A}")
    print(f"  alpha={args.alpha}, gamma={args.gamma}")

    print(f"\n待优化参数:")
    config = load_config()
    current_params = get_current_params(config)
    for name, value in sorted(current_params.items()):
        info = SPSA_PARAMS[name]
        print(f"  {name}: {value} (范围: [{info['min']}, {info['max']}])")

    best_params, best_error, baseline_error = run_spsa(
        positions,
        num_iterations=args.iterations,
        a=args.a,
        c=args.c,
        A=args.A,
        alpha=args.alpha,
        gamma=args.gamma,
    )

    result_file = BASE_DIR / "tuning_result_spsa.json"
    result = {
        "algorithm": "SPSA",
        "iterations": args.iterations,
        "positions_used": len(positions),
        "baseline_error": baseline_error,
        "final_error": best_error,
        "improvement": baseline_error - best_error,
        "improvement_percent": (baseline_error - best_error) / baseline_error * 100,
        "optimized_params": {k: round(v, 1) for k, v in best_params.items()},
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存到: {result_file}")


if __name__ == "__main__":
    main()
