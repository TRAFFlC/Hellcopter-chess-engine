"""
引擎优化迭代系统

该包提供了国际象棋引擎的参数配置管理、优化和测试功能。
"""

__version__ = "1.0.0"

from .config_manager import ConfigManager
from .match_runner import MatchRunner, MatchResult
from .tuner import BaseTuner, GradientDescentTuner, GridSearchTuner, TUNABLE_PARAMS
from .visualizer import Visualizer
from .build_engine import EngineBuilder
from .tuning_logger import (
    TuningLogger,
    TuningStatus,
    ParameterChange,
    EloResult,
    GitInfo,
    TuningRecord,
    create_parameter_change,
    create_elo_result
)

__all__ = [
    'ConfigManager',
    'MatchRunner',
    'MatchResult',
    'BaseTuner',
    'GradientDescentTuner',
    'GridSearchTuner',
    'TUNABLE_PARAMS',
    'Visualizer',
    'EngineBuilder',
    'TuningLogger',
    'TuningStatus',
    'ParameterChange',
    'EloResult',
    'GitInfo',
    'TuningRecord',
    'create_parameter_change',
    'create_elo_result',
]
