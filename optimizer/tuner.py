import copy
import json
import math
import os
import random
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Callable

from .config_manager import ConfigManager
from .match_runner import MatchRunner, MatchResult


TUNABLE_PARAMS = {
    "piece_values.pawn": {"min": 50, "max": 200, "step": 10},
    "piece_values.knight": {"min": 200, "max": 500, "step": 25},
    "piece_values.bishop": {"min": 200, "max": 500, "step": 25},
    "piece_values.rook": {"min": 300, "max": 700, "step": 25},
    "piece_values.queen": {"min": 600, "max": 1200, "step": 50},
    "eval_weights.bishop_pair_bonus": {"min": 0, "max": 200, "step": 10},
    "eval_weights.doubled_pawn_penalty": {"min": -100, "max": 0, "step": 5},
    "eval_weights.isolated_pawn_penalty": {"min": -100, "max": 0, "step": 5},
    "eval_weights.open_file_bonus": {"min": 0, "max": 100, "step": 5},
    "eval_weights.semi_open_file_bonus": {"min": 0, "max": 100, "step": 5},
    "search_params.null_move_reduction": {"min": 1, "max": 4, "step": 1},
    "search_params.null_move_min_depth": {"min": 1, "max": 10, "step": 1},
    "search_params.lmr_min_depth": {"min": 1, "max": 10, "step": 1},
    "search_params.lmr_move_threshold": {"min": 1, "max": 10, "step": 1},
    "search_params.futility_margin_base": {"min": 50, "max": 500, "step": 25},
    "search_params.razoring_margin": {"min": 100, "max": 1000, "step": 50},
    "constants.delta": {"min": 100, "max": 2000, "step": 50},
}


def _get_nested(d: Dict, key: str) -> Any:
    keys = key.split(".")
    val = d
    for k in keys:
        val = val[k]
    return val


def _set_nested(d: Dict, key: str, value: Any):
    keys = key.split(".")
    obj = d
    for k in keys[:-1]:
        obj = obj[k]
    obj[keys[-1]] = value


class TuningResult:
    def __init__(self, best_params: Dict, best_elo: float,
                 history: List[Dict], method: str):
        self.best_params = best_params
        self.best_elo = best_elo
        self.history = history
        self.method = method

    def to_dict(self) -> Dict:
        return {
            "best_params": self.best_params,
            "best_elo": self.best_elo,
            "history": self.history,
            "method": self.method,
            "timestamp": datetime.now().isoformat()
        }


class GradientDescentTuner:
    def __init__(self, config_manager: ConfigManager, match_runner: MatchRunner,
                 base_version: str = "1.0.0"):
        self.cm = config_manager
        self.mr = match_runner
        self.base_version = base_version
        self.base_config = self.cm.import_config(base_version)

    def _evaluate(self, params: Dict, opponent: str = "pulsar",
                  rounds: int = 11, time_control: str = "9+0.1") -> float:
        version = f"gd_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            self.cm.export_config(version, parameters=params)
            self.cm.switch_version(version)
            result = self.mr.run_match(opponent=opponent, rounds=rounds,
                                       time_control=time_control,
                                       config_version=version)
            return -result.elo_diff
        except Exception as e:
            print(f"Evaluation failed: {e}")
            return -1000.0

    def tune(self, params_to_tune: Optional[List[str]] = None,
             opponent: str = "pulsar", rounds: int = 11,
             time_control: str = "9+0.1", learning_rate: float = 0.3,
             iterations: int = 10, epsilon: float = 0.05) -> TuningResult:
        if params_to_tune is None:
            params_to_tune = list(TUNABLE_PARAMS.keys())

        current_params = copy.deepcopy(self.base_config["parameters"])
        current_elo = self._evaluate(
            current_params, opponent, rounds, time_control)
        history = [{"iteration": 0, "elo": current_elo,
                    "params": copy.deepcopy(current_params)}]

        print(f"Initial Elo: {current_elo:.1f}")

        for it in range(1, iterations + 1):
            gradients = {}
            for param_key in params_to_tune:
                if param_key not in TUNABLE_PARAMS:
                    continue
                spec = TUNABLE_PARAMS[param_key]
                current_val = _get_nested(current_params, param_key)
                delta = max(spec["step"], abs(current_val) * epsilon)
                test_plus = max(spec["min"], min(
                    spec["max"], current_val + delta))
                test_minus = max(spec["min"], min(
                    spec["max"], current_val - delta))

                params_plus = copy.deepcopy(current_params)
                _set_nested(params_plus, param_key, test_plus)
                elo_plus = self._evaluate(
                    params_plus, opponent, rounds, time_control)

                params_minus = copy.deepcopy(current_params)
                _set_nested(params_minus, param_key, test_minus)
                elo_minus = self._evaluate(
                    params_minus, opponent, rounds, time_control)

                gradient = (elo_plus - elo_minus) / (test_plus -
                                                     test_minus) if test_plus != test_minus else 0.0
                gradients[param_key] = gradient

            for param_key, gradient in gradients.items():
                spec = TUNABLE_PARAMS[param_key]
                current_val = _get_nested(current_params, param_key)
                step = learning_rate * gradient * spec["step"]
                new_val = current_val + step
                quantized = round(new_val / spec["step"]) * spec["step"]
                new_val = max(spec["min"], min(spec["max"], quantized))
                _set_nested(current_params, param_key, int(new_val))

            current_elo = self._evaluate(
                current_params, opponent, rounds, time_control)
            print(f"Iteration {it}: Elo = {current_elo:.1f}")
            history.append({
                "iteration": it, "elo": current_elo,
                "params": copy.deepcopy(current_params),
                "gradients": gradients
            })

        best = max(history, key=lambda h: h["elo"])
        result = TuningResult(
            best_params=best["params"],
            best_elo=best["elo"],
            history=history,
            method="gradient_descent"
        )
        self._save_result(result)
        return result

    def _save_result(self, result: TuningResult):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.mr.results_dir, f"tuning_gd_{ts}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)


class GridSearchTuner:
    def __init__(self, config_manager: ConfigManager, match_runner: MatchRunner,
                 base_version: str = "1.0.0"):
        self.cm = config_manager
        self.mr = match_runner
        self.base_version = base_version
        self.base_config = self.cm.import_config(base_version)

    def _evaluate(self, params: Dict, opponent: str = "pulsar",
                  rounds: int = 11, time_control: str = "9+0.1") -> float:
        version = f"gs_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            self.cm.export_config(version, parameters=params)
            self.cm.switch_version(version)
            result = self.mr.run_match(opponent=opponent, rounds=rounds,
                                       time_control=time_control,
                                       config_version=version)
            return -result.elo_diff
        except Exception as e:
            print(f"Evaluation failed: {e}")
            return -1000.0

    def tune(self, params_to_tune: Optional[List[str]] = None,
             opponent: str = "pulsar", rounds: int = 11,
             time_control: str = "9+0.1") -> TuningResult:
        if params_to_tune is None:
            params_to_tune = list(TUNABLE_PARAMS.keys())

        grid_values = {}
        for key in params_to_tune:
            if key not in TUNABLE_PARAMS:
                continue
            spec = TUNABLE_PARAMS[key]
            values = list(range(spec["min"], spec["max"] + 1, spec["step"]))
            grid_values[key] = values

        best_elo = -float('inf')
        best_params = copy.deepcopy(self.base_config["parameters"])
        history = []

        total_combos = 1
        for v in grid_values.values():
            total_combos *= len(v)
        print(
            f"Grid search: {total_combos} combinations across {len(grid_values)} params")

        combo_count = 0
        for param_key in grid_values:
            for value in grid_values[param_key]:
                combo_count += 1
                test_params = copy.deepcopy(self.base_config["parameters"])
                _set_nested(test_params, param_key, value)
                elo = self._evaluate(test_params, opponent,
                                     rounds, time_control)
                print(
                    f"[{combo_count}/{total_combos}] {param_key}={value}: Elo={elo:.1f}")

                history.append({
                    "param_key": param_key, "value": value,
                    "elo": elo, "iteration": combo_count
                })

                if elo > best_elo:
                    best_elo = elo
                    best_params = copy.deepcopy(test_params)

        result = TuningResult(
            best_params=best_params,
            best_elo=best_elo,
            history=history,
            method="grid_search"
        )
        self._save_result(result)
        return result

    def _save_result(self, result: TuningResult):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.mr.results_dir, f"tuning_gs_{ts}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
