"""
Elo追踪器模块

负责记录和分析引擎Elo水平变化：
- 记录每个版本的Elo评分
- 计算Elo变化的统计显著性
- 生成Elo变化趋势图
- 识别关键优化和退化
"""

import json
import os
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path


@dataclass
class EloRecord:
    version: str
    timestamp: str
    elo: float
    ci_low: float
    ci_high: float
    wins: int
    losses: int
    draws: int
    opponent: str
    time_control: str
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "elo": self.elo,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "wins": self.wins,
            "losses": self.losses,
            "draws": self.draws,
            "opponent": self.opponent,
            "time_control": self.time_control,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EloRecord':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class VersionElo:
    version: str
    records: List[EloRecord] = field(default_factory=list)
    average_elo: float = 0.0
    best_elo: float = -float('inf')
    worst_elo: float = float('inf')

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "records": [r.to_dict() for r in self.records],
            "average_elo": self.average_elo,
            "best_elo": self.best_elo,
            "worst_elo": self.worst_elo,
        }


class EloTracker:
    """Elo追踪器"""

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.records: List[EloRecord] = []
        self.version_elos: Dict[str, VersionElo] = {}
        self.baseline_elo: float = 1500.0
        self.history_file = config_manager.get_output_path("elo_history.json")
        self._load_history()

    def _load_history(self):
        if os.path.isfile(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for record_data in data.get("records", []):
                    record = EloRecord.from_dict(record_data)
                    self.add_record(record)
                self.baseline_elo = data.get("baseline_elo", 1500.0)
            except Exception as e:
                print(f"加载Elo历史失败: {e}")

    def save_history(self):
        data = {
            "baseline_elo": self.baseline_elo,
            "records": [r.to_dict() for r in self.records],
            "version_summary": {v: ve.to_dict() for v, ve in self.version_elos.items()},
        }
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存Elo历史失败: {e}")

    def add_record(self, record: EloRecord):
        self.records.append(record)

        if record.version not in self.version_elos:
            self.version_elos[record.version] = VersionElo(version=record.version)

        ve = self.version_elos[record.version]
        ve.records.append(record)
        ve.best_elo = max(ve.best_elo, record.elo)
        ve.worst_elo = min(ve.worst_elo, record.elo)
        ve.average_elo = sum(r.elo for r in ve.records) / len(ve.records)

        self.save_history()

    def record_match_result(self, version: str, wins: int, losses: int, draws: int,
                           opponent: str, time_control: str, notes: str = ""):
        """记录对局结果并计算Elo"""
        total = wins + losses + draws
        if total == 0:
            return

        p = (wins + 0.5 * draws) / total
        elo_diff = self._calc_elo_diff(wins, losses, draws)
        ci_low, ci_high = self._calc_ci(wins, losses, draws)

        record = EloRecord(
            version=version,
            timestamp=datetime.now().isoformat(),
            elo=elo_diff,
            ci_low=ci_low,
            ci_high=ci_high,
            wins=wins,
            losses=losses,
            draws=draws,
            opponent=opponent,
            time_control=time_control,
            notes=notes,
        )
        self.add_record(record)

    def get_version_elo(self, version: str) -> Optional[VersionElo]:
        return self.version_elos.get(version)

    def get_elo_trend(self, version: str, last_n: int = 5) -> List[float]:
        """获取最近N个Elo记录"""
        ve = self.version_elos.get(version)
        if not ve:
            return []
        return [r.elo for r in ve.records[-last_n:]]

    def calculate_elo_change(self, from_version: str, to_version: str) -> Optional[float]:
        """计算两个版本间的Elo变化"""
        from_ve = self.version_elos.get(from_version)
        to_ve = self.version_elos.get(to_version)
        if not from_ve or not to_ve:
            return None
        return to_ve.average_elo - from_ve.average_elo

    def is_significant_improvement(self, version: str, threshold: float = 10.0) -> bool:
        """判断是否有显著进步"""
        ve = self.version_elos.get(version)
        if not ve or len(ve.records) < 3:
            return False

        recent = [r.elo for r in ve.records[-3:]]
        older = [r.elo for r in ve.records[:-3]]

        if not older:
            return False

        recent_avg = sum(recent) / len(recent)
        older_avg = sum(older) / len(older)

        return recent_avg - older_avg > threshold

    def is_regression(self, version: str, threshold: float = -20.0) -> bool:
        """判断是否退化"""
        ve = self.version_elos.get(version)
        if not ve or len(ve.records) < 2:
            return False

        recent = [r.elo for r in ve.records[-2:]]
        recent_avg = sum(recent) / len(recent)

        return recent_avg < threshold

    def find_best_version(self) -> Optional[str]:
        """找到最佳版本"""
        if not self.version_elos:
            return None
        return max(self.version_elos.keys(),
                   key=lambda v: self.version_elos[v].average_elo)

    def find_regression_versions(self) -> List[str]:
        """找到退化的版本"""
        regressions = []
        for version, ve in self.version_elos.items():
            if self.is_regression(version):
                regressions.append(version)
        return regressions

    def generate_elo_report(self) -> Dict[str, Any]:
        """生成Elo分析报告"""
        if not self.version_elos:
            return {"error": "没有Elo记录"}

        versions = sorted(self.version_elos.keys())
        best_version = self.find_best_version()
        regressions = self.find_regression_versions()

        version_data = []
        for v in versions:
            ve = self.version_elos[v]
            version_data.append({
                "version": v,
                "average_elo": round(ve.average_elo, 1),
                "best_elo": round(ve.best_elo, 1),
                "worst_elo": round(ve.worst_elo, 1),
                "total_games": sum(r.wins + r.losses + r.draws for r in ve.records),
                "record_count": len(ve.records),
            })

        return {
            "total_versions": len(versions),
            "total_records": len(self.records),
            "best_version": best_version,
            "best_elo": round(self.version_elos[best_version].average_elo, 1) if best_version else None,
            "regressions": regressions,
            "version_data": version_data,
            "baseline_elo": self.baseline_elo,
        }

    def save_elo_report(self, output_path: Optional[str] = None):
        if output_path is None:
            output_path = self.config_manager.get_output_path("elo_report.json")
        report = self.generate_elo_report()
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"Elo报告已保存: {output_path}")

    def _calc_elo_diff(self, wins: int, losses: int, draws: int) -> float:
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
