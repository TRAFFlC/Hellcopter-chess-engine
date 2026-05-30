"""
BUG检测器模块

负责监控引擎运行时异常：
- 非法着法检测
- 引擎崩溃检测
- 评估异常检测
- 搜索超时检测
- BUG严重程度分类
"""

import json
import os
import re
import subprocess
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any


class BugSeverity(Enum):
    FATAL = "致命"
    CRITICAL = "严重"
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


class BugType(Enum):
    ILLEGAL_MOVE = "非法着法"
    ENGINE_CRASH = "引擎崩溃"
    EVAL_ANOMALY = "评估异常"
    SEARCH_TIMEOUT = "搜索超时"
    INVALID_STATE = "非法状态"
    MOVE_GENERATION = "着法生成错误"


@dataclass
class BugReport:
    bug_id: str
    bug_type: BugType
    severity: BugSeverity
    timestamp: str
    description: str
    fen: str = ""
    move: str = ""
    stack_trace: str = ""
    eval_value: Optional[int] = None
    search_depth: int = 0
    time_spent: float = 0.0
    reproduction_steps: List[str] = field(default_factory=list)
    fix_verified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bug_id": self.bug_id,
            "bug_type": self.bug_type.value,
            "severity": self.severity.value,
            "timestamp": self.timestamp,
            "description": self.description,
            "fen": self.fen,
            "move": self.move,
            "stack_trace": self.stack_trace,
            "eval_value": self.eval_value,
            "search_depth": self.search_depth,
            "time_spent": self.time_spent,
            "reproduction_steps": self.reproduction_steps,
            "fix_verified": self.fix_verified,
        }


class BugDetector:
    """BUG检测器"""

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.bugs: List[BugReport] = []
        self.bug_counter = 0
        self.bugs_file = config_manager.get_output_path("bug_reports.json")
        self._load_existing_bugs()

    def _load_existing_bugs(self):
        if os.path.isfile(self.bugs_file):
            try:
                with open(self.bugs_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for bug_data in data.get("bugs", []):
                    self.bugs.append(BugReport(**bug_data))
                self.bug_counter = len(self.bugs)
            except Exception as e:
                print(f"加载BUG记录失败: {e}")

    def save_bugs(self):
        data = {
            "total_bugs": len(self.bugs),
            "unfixed_bugs": sum(1 for b in self.bugs if not b.fix_verified),
            "bugs": [b.to_dict() for b in self.bugs],
        }
        try:
            with open(self.bugs_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存BUG记录失败: {e}")

    def detect_illegal_move(self, fen: str, move: str, reason: str = ""):
        """检测非法着法"""
        self.bug_counter += 1
        bug = BugReport(
            bug_id=f"BUG_{self.bug_counter:04d}",
            bug_type=BugType.ILLEGAL_MOVE,
            severity=BugSeverity.FATAL,
            timestamp=datetime.now().isoformat(),
            description=f"非法着法: {move}" + (f" ({reason})" if reason else ""),
            fen=fen,
            move=move,
            reproduction_steps=[
                f"设置局面: {fen}",
                f"尝试着法: {move}",
            ],
        )
        self.bugs.append(bug)
        self.save_bugs()
        print(f"[BUG] 检测到非法着法: {move} in {fen[:50]}...")
        return bug

    def detect_engine_crash(self, error_output: str, fen: str = ""):
        """检测引擎崩溃"""
        self.bug_counter += 1
        bug = BugReport(
            bug_id=f"BUG_{self.bug_counter:04d}",
            bug_type=BugType.ENGINE_CRASH,
            severity=BugSeverity.FATAL,
            timestamp=datetime.now().isoformat(),
            description="引擎崩溃",
            fen=fen,
            stack_trace=error_output[:2000],
            reproduction_steps=[f"设置局面: {fen}"] if fen else [],
        )
        self.bugs.append(bug)
        self.save_bugs()
        print(f"[BUG] 检测到引擎崩溃")
        return bug

    def detect_eval_anomaly(self, fen: str, eval_value: int, expected_range: tuple = (-30000, 30000)):
        """检测评估异常"""
        if expected_range[0] <= eval_value <= expected_range[1]:
            return None

        self.bug_counter += 1
        severity = BugSeverity.CRITICAL if abs(eval_value) > 50000 else BugSeverity.HIGH
        bug = BugReport(
            bug_id=f"BUG_{self.bug_counter:04d}",
            bug_type=BugType.EVAL_ANOMALY,
            severity=severity,
            timestamp=datetime.now().isoformat(),
            description=f"评估值异常: {eval_value} (期望范围: {expected_range})",
            fen=fen,
            eval_value=eval_value,
            reproduction_steps=[f"评估局面: {fen}"],
        )
        self.bugs.append(bug)
        self.save_bugs()
        print(f"[BUG] 检测到评估异常: {eval_value}")
        return bug

    def detect_search_timeout(self, fen: str, time_limit: float, actual_time: float, depth: int = 0):
        """检测搜索超时"""
        if actual_time <= time_limit * 1.5:
            return None

        self.bug_counter += 1
        bug = BugReport(
            bug_id=f"BUG_{self.bug_counter:04d}",
            bug_type=BugType.SEARCH_TIMEOUT,
            severity=BugSeverity.HIGH,
            timestamp=datetime.now().isoformat(),
            description=f"搜索超时: 限制{time_limit:.2f}s, 实际{actual_time:.2f}s",
            fen=fen,
            search_depth=depth,
            time_spent=actual_time,
            reproduction_steps=[
                f"设置局面: {fen}",
                f"搜索时间限制: {time_limit}s",
            ],
        )
        self.bugs.append(bug)
        self.save_bugs()
        print(f"[BUG] 检测到搜索超时: {actual_time:.2f}s > {time_limit:.2f}s")
        return bug

    def detect_invalid_state(self, fen: str, reason: str):
        """检测非法状态"""
        self.bug_counter += 1
        bug = BugReport(
            bug_id=f"BUG_{self.bug_counter:04d}",
            bug_type=BugType.INVALID_STATE,
            severity=BugSeverity.CRITICAL,
            timestamp=datetime.now().isoformat(),
            description=f"非法状态: {reason}",
            fen=fen,
            reproduction_steps=[f"设置局面: {fen}"],
        )
        self.bugs.append(bug)
        self.save_bugs()
        print(f"[BUG] 检测到非法状态: {reason}")
        return bug

    def get_unfixed_bugs(self) -> List[BugReport]:
        """获取未修复的BUG"""
        return [b for b in self.bugs if not b.fix_verified]

    def get_fatal_bugs(self) -> List[BugReport]:
        """获取致命BUG"""
        return [b for b in self.bugs if b.severity == BugSeverity.FATAL and not b.fix_verified]

    def mark_bug_fixed(self, bug_id: str, verified: bool = True):
        """标记BUG已修复"""
        for bug in self.bugs:
            if bug.bug_id == bug_id:
                bug.fix_verified = verified
                self.save_bugs()
                print(f"BUG {bug_id} 已标记为{'已验证修复' if verified else '未修复'}")
                return True
        return False

    def generate_bug_report(self) -> Dict[str, Any]:
        """生成BUG报告"""
        unfixed = self.get_unfixed_bugs()
        fatal = self.get_fatal_bugs()

        by_type = {}
        for bug in unfixed:
            t = bug.bug_type.value
            by_type[t] = by_type.get(t, 0) + 1

        by_severity = {}
        for bug in unfixed:
            s = bug.severity.value
            by_severity[s] = by_severity.get(s, 0) + 1

        return {
            "total_bugs": len(self.bugs),
            "unfixed_bugs": len(unfixed),
            "fatal_bugs": len(fatal),
            "by_type": by_type,
            "by_severity": by_severity,
            "recent_bugs": [b.to_dict() for b in self.bugs[-10:]],
        }

    def save_bug_report(self, output_path: Optional[str] = None):
        if output_path is None:
            output_path = self.config_manager.get_output_path("bug_report.json")
        report = self.generate_bug_report()
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"BUG报告已保存: {output_path}")

    def should_halt_optimization(self) -> bool:
        """判断是否应该停止优化（存在致命BUG）"""
        return len(self.get_fatal_bugs()) > 0
