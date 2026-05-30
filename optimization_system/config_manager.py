"""
系统配置管理模块

负责加载、验证和管理优化系统的配置。
所有输出文件放置在 .trae/specs/claude/ 目录。
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from pathlib import Path


DEFAULT_OUTPUT_DIR = os.path.join(".trae", "specs", "claude")


@dataclass
class OptimizationConfig:
    """优化系统主配置"""
    target_elo: float = 9999.0
    max_iterations: int = 999999
    quick_tc: str = "10+0.1"
    standard_tc: str = "96+0.8"
    slow_tc: str = "300+2.0"
    opponent_engines: List[str] = field(default_factory=lambda: ["shallowblue", "tscp181", "apollo"])
    gatekeeper_engines: List[str] = field(default_factory=lambda: ["v1.5.0", "v1.7.0"])
    bug_fix_priority: str = "high"
    perf_opt_priority: str = "medium"
    param_opt_method: str = "spsa"
    test_accept_threshold: float = 0.55
    log_level: str = "INFO"
    auto_apply: bool = True
    output_dir: str = DEFAULT_OUTPUT_DIR
    baseline_version: str = "v1.8.0"
    velvet_engine_path: str = r"e:\world\python\chess\test_engines\Velvet\velvet-v8.1.1-x86_64-avx2.exe"
    analysis_depth: int = 20
    analysis_time_limit: float = 0.5
    max_games_per_match: int = 50
    min_games_for_validation: int = 11
    elo_confidence_threshold: float = 0.95
    regression_test_suite: str = "validation_tests.py"
    opening_book_path: Optional[str] = None
    pause_on_error: bool = False
    max_consecutive_failures: int = 999999
    cleanup_temp_files: bool = True
    temp_file_max_age_hours: int = 24
    target_opponent: str = "apollo"
    target_win_rate: float = 0.65
    enable_eval_opt: bool = True
    enable_search_opt: bool = True
    enable_time_mgmt_opt: bool = True
    enable_tactical_opt: bool = True
    enable_pondering: bool = True
    eval_opt_iterations: int = 5
    search_opt_iterations: int = 5
    time_mgmt_opt_iterations: int = 3
    tactical_opt_iterations: int = 3
    exchange_analysis_depth: int = 25
    piece_safety_analysis: bool = True
    min_score_vs_apollo: float = 0.60

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OptimizationConfig':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ConfigManager:
    """配置管理器"""

    def __init__(self, base_dir: str, config_path: Optional[str] = None):
        self.base_dir = base_dir
        self.config_path = config_path or os.path.join(base_dir, DEFAULT_OUTPUT_DIR, "optimization_config.json")
        self.config = OptimizationConfig()
        self._ensure_output_dir()

    def _ensure_output_dir(self):
        output_dir = os.path.join(self.base_dir, self.config.output_dir)
        os.makedirs(output_dir, exist_ok=True)

    def load_config(self) -> OptimizationConfig:
        if os.path.isfile(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.config = OptimizationConfig.from_dict(data)
                print(f"配置已加载: {self.config_path}")
            except Exception as e:
                print(f"加载配置失败 ({e})，使用默认配置")
        else:
            self.save_config()
        return self.config

    def save_config(self):
        self._ensure_output_dir()
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存配置失败: {e}")

    def get_output_path(self, filename: str) -> str:
        return os.path.join(self.base_dir, self.config.output_dir, filename)

    def update_config(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        self.save_config()
