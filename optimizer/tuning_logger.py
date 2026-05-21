"""
调优记录系统

记录引擎参数调优的完整历史，支持：
- 详细的调优记录（参数变化、测试结果、Elo变化）
- Git 标签和 commit 关联
- 历史查询（按时间、参数类型）
- 趋势图数据生成
- 报告导出
"""

import json
import os
import subprocess
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum


class TuningStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class ParameterChange:
    param_name: str
    param_path: str
    old_value: Any
    new_value: Any
    category: str

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'ParameterChange':
        return cls(**data)


@dataclass
class EloResult:
    elo_change: float
    confidence_interval: float
    games_played: int
    wins: int
    draws: int
    losses: int

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'EloResult':
        return cls(**data)

    @property
    def is_significant(self) -> bool:
        return abs(self.elo_change) > self.confidence_interval


@dataclass
class GitInfo:
    commit_hash: str
    tag: Optional[str]
    branch: str

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'GitInfo':
        return cls(**data)


@dataclass
class TuningRecord:
    id: str
    timestamp: str
    status: str
    method: str
    description: str
    parameter_changes: List[Dict]
    elo_result: Optional[Dict]
    test_config: Dict
    git_info: Optional[Dict]
    notes: str
    related_records: List[str]

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'TuningRecord':
        return cls(**data)


class TuningLogger:
    def __init__(self, log_dir: str = "tuning_logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.log_file = self.log_dir / "tuning_log.json"
        self._ensure_log_file()

    def _ensure_log_file(self):
        if not self.log_file.exists():
            initial_data = {
                "version": "1.0",
                "created_at": datetime.now().isoformat(),
                "records": [],
                "metadata": {
                    "total_tunings": 0,
                    "successful_tunings": 0,
                    "total_elo_gain": 0.0
                }
            }
            self._save_log(initial_data)

    def _load_log(self) -> Dict:
        with open(self.log_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _save_log(self, data: Dict):
        with open(self.log_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _generate_id(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    def _get_git_info(self) -> Optional[GitInfo]:
        try:
            commit_hash = subprocess.check_output(
                ['git', 'rev-parse', 'HEAD'],
                stderr=subprocess.DEVNULL,
                cwd=os.getcwd()
            ).decode().strip()

            try:
                tag = subprocess.check_output(
                    ['git', 'describe', '--tags', '--exact-match'],
                    stderr=subprocess.DEVNULL,
                    cwd=os.getcwd()
                ).decode().strip()
            except subprocess.CalledProcessError:
                tag = None

            branch = subprocess.check_output(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                stderr=subprocess.DEVNULL,
                cwd=os.getcwd()
            ).decode().strip()

            return GitInfo(commit_hash=commit_hash, tag=tag, branch=branch)
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

    def create_git_tag(self, tag_name: str, message: str = "") -> bool:
        try:
            cmd = ['git', 'tag', '-a', tag_name, '-m', message or f"Tuning: {tag_name}"]
            subprocess.check_call(cmd, cwd=os.getcwd())
            return True
        except subprocess.CalledProcessError:
            return False

    def record_tuning(
        self,
        parameter_changes: List[ParameterChange],
        method: str,
        description: str = "",
        elo_result: Optional[EloResult] = None,
        test_config: Optional[Dict] = None,
        notes: str = "",
        create_tag: bool = False,
        status: str = TuningStatus.COMPLETED.value
    ) -> str:
        record_id = self._generate_id()
        git_info = self._get_git_info()

        if create_tag and elo_result and elo_result.is_significant and elo_result.elo_change > 0:
            tag_name = f"tune_{record_id}"
            if self.create_git_tag(tag_name, description):
                git_info = self._get_git_info()

        default_test_config = {
            "opponents": [],
            "time_control": "",
            "games_per_opponent": 0,
            "total_games": 0
        }

        record = TuningRecord(
            id=record_id,
            timestamp=datetime.now().isoformat(),
            status=status,
            method=method,
            description=description,
            parameter_changes=[pc.to_dict() for pc in parameter_changes],
            elo_result=elo_result.to_dict() if elo_result else None,
            test_config=test_config or default_test_config,
            git_info=git_info.to_dict() if git_info else None,
            notes=notes,
            related_records=[]
        )

        log_data = self._load_log()
        log_data["records"].append(record.to_dict())

        log_data["metadata"]["total_tunings"] += 1
        if status == TuningStatus.COMPLETED.value and elo_result:
            log_data["metadata"]["successful_tunings"] += 1
            if elo_result.elo_change > 0:
                log_data["metadata"]["total_elo_gain"] += elo_result.elo_change

        self._save_log(log_data)

        return record_id

    def update_record(
        self,
        record_id: str,
        status: Optional[str] = None,
        elo_result: Optional[EloResult] = None,
        notes: Optional[str] = None
    ) -> bool:
        log_data = self._load_log()

        for record in log_data["records"]:
            if record["id"] == record_id:
                if status:
                    record["status"] = status
                if elo_result:
                    record["elo_result"] = elo_result.to_dict()
                if notes:
                    record["notes"] = notes
                self._save_log(log_data)
                return True

        return False

    def link_records(self, record_id1: str, record_id2: str) -> bool:
        log_data = self._load_log()

        found1 = found2 = False
        for record in log_data["records"]:
            if record["id"] == record_id1:
                if record_id2 not in record["related_records"]:
                    record["related_records"].append(record_id2)
                found1 = True
            if record["id"] == record_id2:
                if record_id1 not in record["related_records"]:
                    record["related_records"].append(record_id1)
                found2 = True

        if found1 and found2:
            self._save_log(log_data)
            return True
        return False

    def query_by_time_range(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[TuningRecord]:
        log_data = self._load_log()
        results = []

        for record_data in log_data["records"]:
            record_time = datetime.fromisoformat(record_data["timestamp"])

            if start_time and record_time < start_time:
                continue
            if end_time and record_time > end_time:
                continue

            results.append(TuningRecord.from_dict(record_data))

        return results

    def query_by_param_type(self, category: str) -> List[TuningRecord]:
        log_data = self._load_log()
        results = []

        for record_data in log_data["records"]:
            for change in record_data["parameter_changes"]:
                if change.get("category") == category:
                    results.append(TuningRecord.from_dict(record_data))
                    break

        return results

    def query_by_method(self, method: str) -> List[TuningRecord]:
        log_data = self._load_log()
        results = []

        for record_data in log_data["records"]:
            if record_data["method"] == method:
                results.append(TuningRecord.from_dict(record_data))

        return results

    def query_by_status(self, status: str) -> List[TuningRecord]:
        log_data = self._load_log()
        results = []

        for record_data in log_data["records"]:
            if record_data["status"] == status:
                results.append(TuningRecord.from_dict(record_data))

        return results

    def query_by_param_name(self, param_name: str) -> List[TuningRecord]:
        log_data = self._load_log()
        results = []

        for record_data in log_data["records"]:
            for change in record_data["parameter_changes"]:
                if change.get("param_name") == param_name:
                    results.append(TuningRecord.from_dict(record_data))
                    break

        return results

    def get_record(self, record_id: str) -> Optional[TuningRecord]:
        log_data = self._load_log()

        for record_data in log_data["records"]:
            if record_data["id"] == record_id:
                return TuningRecord.from_dict(record_data)

        return None

    def get_all_records(self) -> List[TuningRecord]:
        log_data = self._load_log()
        return [TuningRecord.from_dict(r) for r in log_data["records"]]

    def generate_trend_data(
        self,
        param_name: Optional[str] = None,
        time_range_days: Optional[int] = None
    ) -> Dict[str, Any]:
        log_data = self._load_log()

        if time_range_days:
            start_time = datetime.now() - timedelta(days=time_range_days)
            records = self.query_by_time_range(start_time=start_time)
        else:
            records = [TuningRecord.from_dict(r) for r in log_data["records"]]

        trend_data = {
            "timestamps": [],
            "elo_values": [],
            "elo_lower": [],
            "elo_upper": [],
            "param_values": {},
            "cumulative_elo": 0.0,
            "cumulative_elo_series": []
        }

        for record in sorted(records, key=lambda r: r.timestamp):
            if record.elo_result:
                elo = record.elo_result["elo_change"]
                ci = record.elo_result["confidence_interval"]

                trend_data["timestamps"].append(record.timestamp)
                trend_data["elo_values"].append(elo)
                trend_data["elo_lower"].append(elo - ci)
                trend_data["elo_upper"].append(elo + ci)

                if elo > 0:
                    trend_data["cumulative_elo"] += elo
                trend_data["cumulative_elo_series"].append(trend_data["cumulative_elo"])

            if param_name:
                for change in record.parameter_changes:
                    if change["param_name"] == param_name:
                        if param_name not in trend_data["param_values"]:
                            trend_data["param_values"][param_name] = []
                        trend_data["param_values"][param_name].append({
                            "timestamp": record.timestamp,
                            "value": change["new_value"]
                        })

        return trend_data

    def generate_param_evolution_data(self) -> Dict[str, List[Dict]]:
        log_data = self._load_log()
        param_evolution = {}

        for record_data in log_data["records"]:
            record = TuningRecord.from_dict(record_data)

            for change in record.parameter_changes:
                param_name = change["param_name"]
                if param_name not in param_evolution:
                    param_evolution[param_name] = []

                param_evolution[param_name].append({
                    "timestamp": record.timestamp,
                    "old_value": change["old_value"],
                    "new_value": change["new_value"],
                    "record_id": record.id,
                    "method": record.method
                })

        return param_evolution

    def export_report(
        self,
        output_path: str,
        format: str = "json",
        time_range_days: Optional[int] = None,
        include_trends: bool = True
    ) -> str:
        log_data = self._load_log()

        if time_range_days:
            start_time = datetime.now() - timedelta(days=time_range_days)
            records = self.query_by_time_range(start_time=start_time)
        else:
            records = [TuningRecord.from_dict(r) for r in log_data["records"]]

        report = {
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_records": len(records),
                "successful_tunings": sum(1 for r in records if r.status == TuningStatus.COMPLETED.value),
                "failed_tunings": sum(1 for r in records if r.status == TuningStatus.FAILED.value),
                "total_elo_gain": sum(
                    r.elo_result["elo_change"]
                    for r in records
                    if r.elo_result and r.elo_result["elo_change"] > 0
                ),
                "methods_used": list(set(r.method for r in records))
            },
            "records": [r.to_dict() for r in records]
        }

        if include_trends:
            report["trends"] = self.generate_trend_data(time_range_days=time_range_days)
            report["param_evolution"] = self.generate_param_evolution_data()

        output_file = Path(output_path)

        if format == "json":
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
        elif format == "markdown":
            md_content = self._generate_markdown_report(report)
            with open(output_file.with_suffix('.md'), 'w', encoding='utf-8') as f:
                f.write(md_content)

        return str(output_file)

    def _generate_markdown_report(self, report: Dict) -> str:
        lines = []
        lines.append(f"# 调优报告")
        lines.append(f"\n生成时间: {report['generated_at']}\n")

        summary = report["summary"]
        lines.append("## 概要统计\n")
        lines.append(f"- 总调优次数: {summary['total_records']}")
        lines.append(f"- 成功调优: {summary['successful_tunings']}")
        lines.append(f"- 失败调优: {summary['failed_tunings']}")
        lines.append(f"- 累计 Elo 提升: {summary['total_elo_gain']:.1f}")
        lines.append(f"- 使用方法: {', '.join(summary['methods_used'])}\n")

        lines.append("## 调优记录\n")
        for record in report["records"]:
            lines.append(f"### {record['id']}\n")
            lines.append(f"- 时间: {record['timestamp']}")
            lines.append(f"- 状态: {record['status']}")
            lines.append(f"- 方法: {record['method']}")
            lines.append(f"- 描述: {record['description']}\n")

            if record['parameter_changes']:
                lines.append("**参数变更:**\n")
                for change in record['parameter_changes']:
                    lines.append(f"- {change['param_name']}: {change['old_value']} → {change['new_value']}")
                lines.append("")

            if record['elo_result']:
                elo = record['elo_result']
                lines.append(f"**Elo 结果:** {elo['elo_change']:.1f} ± {elo['confidence_interval']:.1f}")
                lines.append(f"- 对局数: {elo['games_played']}")
                lines.append(f"- 胜/和/负: {elo['wins']}/{elo['draws']}/{elo['losses']}\n")

            if record['git_info']:
                lines.append(f"**Git 信息:**")
                lines.append(f"- Commit: `{record['git_info']['commit_hash'][:8]}`")
                if record['git_info']['tag']:
                    lines.append(f"- Tag: `{record['git_info']['tag']}`")
                lines.append("")

        return "\n".join(lines)

    def get_statistics(self) -> Dict[str, Any]:
        log_data = self._load_log()
        records = [TuningRecord.from_dict(r) for r in log_data["records"]]

        stats = {
            "total_tunings": len(records),
            "by_status": {},
            "by_method": {},
            "by_category": {},
            "elo_stats": {
                "total_gain": 0.0,
                "total_loss": 0.0,
                "best_gain": 0.0,
                "worst_loss": 0.0,
                "average_change": 0.0
            },
            "most_tuned_params": {}
        }

        elo_changes = []

        for record in records:
            stats["by_status"][record.status] = stats["by_status"].get(record.status, 0) + 1
            stats["by_method"][record.method] = stats["by_method"].get(record.method, 0) + 1

            for change in record.parameter_changes:
                category = change.get("category", "unknown")
                stats["by_category"][category] = stats["by_category"].get(category, 0) + 1

                param_name = change["param_name"]
                stats["most_tuned_params"][param_name] = stats["most_tuned_params"].get(param_name, 0) + 1

            if record.elo_result:
                elo_change = record.elo_result["elo_change"]
                elo_changes.append(elo_change)

                if elo_change > 0:
                    stats["elo_stats"]["total_gain"] += elo_change
                    if elo_change > stats["elo_stats"]["best_gain"]:
                        stats["elo_stats"]["best_gain"] = elo_change
                else:
                    stats["elo_stats"]["total_loss"] += abs(elo_change)
                    if elo_change < stats["elo_stats"]["worst_loss"]:
                        stats["elo_stats"]["worst_loss"] = elo_change

        if elo_changes:
            stats["elo_stats"]["average_change"] = sum(elo_changes) / len(elo_changes)

        stats["most_tuned_params"] = dict(
            sorted(stats["most_tuned_params"].items(), key=lambda x: x[1], reverse=True)[:10]
        )

        return stats

    def rollback_record(self, record_id: str, reason: str = "") -> bool:
        log_data = self._load_log()

        for record in log_data["records"]:
            if record["id"] == record_id:
                record["status"] = TuningStatus.ROLLED_BACK.value
                if reason:
                    record["notes"] = f"{record.get('notes', '')}\n回滚原因: {reason}".strip()
                self._save_log(log_data)
                return True

        return False

    def delete_record(self, record_id: str) -> bool:
        log_data = self._load_log()

        original_count = len(log_data["records"])
        log_data["records"] = [r for r in log_data["records"] if r["id"] != record_id]

        if len(log_data["records"]) < original_count:
            log_data["metadata"]["total_tunings"] = len(log_data["records"])
            self._save_log(log_data)
            return True

        return False


def create_parameter_change(
    param_name: str,
    param_path: str,
    old_value: Any,
    new_value: Any,
    category: str = "unknown"
) -> ParameterChange:
    return ParameterChange(
        param_name=param_name,
        param_path=param_path,
        old_value=old_value,
        new_value=new_value,
        category=category
    )


def create_elo_result(
    elo_change: float,
    confidence_interval: float,
    games_played: int,
    wins: int,
    draws: int,
    losses: int
) -> EloResult:
    return EloResult(
        elo_change=elo_change,
        confidence_interval=confidence_interval,
        games_played=games_played,
        wins=wins,
        draws=draws,
        losses=losses
    )
