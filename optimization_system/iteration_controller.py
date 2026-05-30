"""
迭代控制器模块

管理自动化迭代流程：
- 持续运行优化迭代循环（直到大幅超过apollo）
- 协调性能分析、方案生成、测试验证
- 追踪Elo变化趋势
- 生成迭代总结报告
- 支持四大优化方向：评估函数、搜索剪枝、时间管理、战术优化
"""

import json
import os
import sys
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any

from .config_manager import ConfigManager
from .performance_analyzer import PerformanceAnalyzer
from .solution_generator import SolutionGenerator
from .test_validator import TestValidator
from .elo_tracker import EloTracker
from .bug_detector import BugDetector
from .tool_integrator import ToolIntegrator
from .parameter_optimizer import ParameterOptimizer


class IterationStatus(Enum):
    IDLE = "空闲"
    ANALYZING = "分析中"
    GENERATING = "生成方案中"
    VALIDATING = "验证中"
    APPLYING = "应用优化中"
    FAILED = "失败"
    COMPLETED = "完成"
    STOPPED = "已停止"


@dataclass
class IterationRecord:
    iteration_number: int
    status: IterationStatus
    start_time: str
    end_time: Optional[str] = None
    analysis_report_id: Optional[str] = None
    solution_document_id: Optional[str] = None
    validation_report_id: Optional[str] = None
    elo_change: float = 0.0
    applied: bool = False
    failure_reason: str = ""
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration_number": self.iteration_number,
            "status": self.status.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "analysis_report_id": self.analysis_report_id,
            "solution_document_id": self.solution_document_id,
            "validation_report_id": self.validation_report_id,
            "elo_change": self.elo_change,
            "applied": self.applied,
            "failure_reason": self.failure_reason,
            "notes": self.notes,
        }


@dataclass
class IterationSummary:
    total_iterations: int
    successful_iterations: int
    failed_iterations: int
    total_elo_gain: float
    best_version: str
    start_time: str
    end_time: Optional[str] = None
    iteration_records: List[IterationRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_iterations": self.total_iterations,
            "successful_iterations": self.successful_iterations,
            "failed_iterations": self.failed_iterations,
            "total_elo_gain": self.total_elo_gain,
            "best_version": self.best_version,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "iteration_records": [r.to_dict() for r in self.iteration_records],
        }


class IterationController:
    """迭代控制器"""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.config_manager = ConfigManager(base_dir)
        self.config = self.config_manager.load_config()

        self.analyzer = PerformanceAnalyzer(self.config_manager, self.config.velvet_engine_path)
        self.solution_generator = SolutionGenerator(self.config_manager)
        self.validator = TestValidator(self.config_manager, base_dir)
        self.elo_tracker = EloTracker(self.config_manager)
        self.bug_detector = BugDetector(self.config_manager)
        self.tool_integrator = ToolIntegrator(self.config_manager, base_dir)
        self.param_optimizer = ParameterOptimizer(self.config_manager, base_dir)

        self.iteration_count = 0
        self.consecutive_failures = 0
        self.stop_requested = False
        self.current_status = IterationStatus.IDLE
        self.iteration_records: List[IterationRecord] = []
        self.summary_file = self.config_manager.get_output_path("iteration_summary.json")
        self.log_file = self.config_manager.get_output_path("iteration_log.txt")

        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, sig, frame):
        print("\n\n收到停止信号，正在完成当前迭代...")
        self.stop_requested = True

    def _log(self, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}\n"
        print(log_line, end="")
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_line)

    def _check_apollo_target(self) -> bool:
        """检查是否大幅超过apollo"""
        apollo_records = [r for r in self.elo_tracker.records if r.opponent.lower() == "apollo"]
        if not apollo_records:
            return False

        latest = apollo_records[-1]
        win_rate = (latest.wins + 0.5 * latest.draws) / (latest.wins + latest.losses + latest.draws) if (latest.wins + latest.losses + latest.draws) > 0 else 0

        self._log(f"当前对Apollo胜率: {win_rate:.2%} (目标: {self.config.target_win_rate:.2%})")
        return win_rate >= self.config.target_win_rate

    def run_optimization_loop(self):
        """运行优化迭代循环（直到大幅超过apollo）"""
        self._log("=" * 60)
        self._log("Hellcopter 自动化持续优化系统启动")
        self._log("=" * 60)
        self._log(f"目标: 在标准对局中大幅超过 Apollo (胜率 >= {self.config.target_win_rate:.0%})")
        self._log(f"基准版本: {self.config.baseline_version}")
        self._log("=" * 60)

        while not self.stop_requested:
            if self._check_apollo_target():
                self._log("=" * 60)
                self._log("目标达成！已在标准对局中大幅超过Apollo")
                self._log("=" * 60)
                break

            self.iteration_count += 1
            self._log(f"\n--- 开始第 {self.iteration_count} 次迭代 ---")

            record = self._run_single_iteration()
            self.iteration_records.append(record)
            self._save_summary()

            if record.status == IterationStatus.COMPLETED and record.applied:
                self.consecutive_failures = 0
                self._log(f"迭代 {self.iteration_count} 成功，Elo变化: {record.elo_change:+.1f}")
            else:
                self.consecutive_failures += 1
                self._log(f"迭代 {self.iteration_count} 失败: {record.failure_reason}")

            if self.bug_detector.should_halt_optimization():
                self._log("检测到致命BUG，停止优化")
                break

            time.sleep(5)

        self._generate_final_summary()
        self._log("\n优化循环结束")

    def _run_single_iteration(self) -> IterationRecord:
        """运行单次迭代"""
        record = IterationRecord(
            iteration_number=self.iteration_count,
            status=IterationStatus.ANALYZING,
            start_time=datetime.now().isoformat(),
        )

        try:
            self.current_status = IterationStatus.ANALYZING
            analysis_report = self._run_analysis()
            if not analysis_report:
                record.status = IterationStatus.FAILED
                record.failure_reason = "性能分析失败"
                record.end_time = datetime.now().isoformat()
                return record

            record.analysis_report_id = analysis_report.report_id

            self.current_status = IterationStatus.GENERATING
            solution_doc = self._generate_solutions(analysis_report)
            if not solution_doc or not solution_doc.solutions:
                record.status = IterationStatus.FAILED
                record.failure_reason = "没有生成优化方案"
                record.end_time = datetime.now().isoformat()
                return record

            record.solution_document_id = solution_doc.document_id

            best_solution = solution_doc.solutions[0]
            self._log(f"选择方案: {best_solution.title} (优先级: {best_solution.priority.value})")

            candidate_config = self._create_candidate_config(best_solution)
            if not candidate_config:
                record.status = IterationStatus.FAILED
                record.failure_reason = "创建候选配置失败"
                record.end_time = datetime.now().isoformat()
                return record

            if best_solution.solution_type.value == "参数优化":
                self._apply_param_optimization(best_solution, candidate_config)

            self.current_status = IterationStatus.VALIDATING
            baseline_config = os.path.join(self.base_dir, "configs", f"{self.config.baseline_version}.json")
            validation_report = self.validator.validate_solution(
                best_solution, candidate_config, baseline_config
            )

            record.validation_report_id = validation_report.report_id
            record.elo_change = validation_report.elo_change

            if validation_report.overall_status.value == "通过":
                self.current_status = IterationStatus.APPLYING
                if self.config.auto_apply:
                    applied = self._apply_optimization(candidate_config, validation_report)
                    record.applied = applied
                else:
                    self._log("自动应用已禁用，请手动确认应用优化")
                    record.applied = False
                    record.notes.append("等待手动确认")

                record.status = IterationStatus.COMPLETED
                self.elo_tracker.record_match_result(
                    version=f"iter_{self.iteration_count}",
                    wins=validation_report.standard_test.wins if validation_report.standard_test else 0,
                    losses=validation_report.standard_test.losses if validation_report.standard_test else 0,
                    draws=validation_report.standard_test.draws if validation_report.standard_test else 0,
                    opponent=self.config.opponent_engines[0] if self.config.opponent_engines else "unknown",
                    time_control=self.config.standard_tc,
                    notes=f"Iteration {self.iteration_count}",
                )
            else:
                record.status = IterationStatus.FAILED
                record.failure_reason = f"验证未通过: {validation_report.overall_status.value}"
                self._cleanup_candidate_config(candidate_config)

        except Exception as e:
            record.status = IterationStatus.FAILED
            record.failure_reason = f"异常: {str(e)}"
            import traceback
            record.notes.append(traceback.format_exc())

        record.end_time = datetime.now().isoformat()
        self.current_status = IterationStatus.IDLE
        return record

    def _run_analysis(self):
        """运行性能分析"""
        self._log("运行性能分析...")

        pgn_files = self._find_recent_pgn_files()
        if not pgn_files:
            self._log("未找到PGN文件，运行对局生成数据...")
            match_result = self.tool_integrator.run_match(
                opponent=self.config.opponent_engines[0] if self.config.opponent_engines else "tscp181",
                rounds=10,
                tc=self.config.quick_tc,
            )
            if not match_result.success:
                self._log("对局运行失败")
                return None
            pgn_files = self._find_recent_pgn_files()

        if not pgn_files:
            self._log("无法获取PGN文件进行分析")
            return None

        try:
            self.analyzer.start()
            report = self.analyzer.analyze_pgn(
                pgn_files[0],
                depth=self.config.analysis_depth,
                time_limit=self.config.analysis_time_limit,
            )
            self.analyzer.save_report(report)
            self._log(f"分析完成，发现 {len(report.issues)} 个问题")
            return report
        except Exception as e:
            self._log(f"分析失败: {e}")
            return None
        finally:
            self.analyzer.stop()

    def _generate_solutions(self, analysis_report):
        """生成优化方案"""
        self._log("生成优化方案...")
        try:
            doc = self.solution_generator.generate_solutions(analysis_report)
            self.solution_generator.save_document(doc)
            self._log(f"生成 {len(doc.solutions)} 个方案")
            return doc
        except Exception as e:
            self._log(f"方案生成失败: {e}")
            return None

    def _create_candidate_config(self, solution) -> Optional[str]:
        """创建候选配置"""
        self._log("创建候选配置...")

        base_config_path = os.path.join(self.base_dir, "configs", f"{self.config.baseline_version}.json")
        if not os.path.isfile(base_config_path):
            self._log(f"基准配置未找到: {base_config_path}")
            return None

        try:
            with open(base_config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)

            config_data["version"] = f"candidate_iter_{self.iteration_count}"
            config_data["base_version"] = self.config.baseline_version
            config_data["created_at"] = datetime.now().isoformat()
            config_data["optimization_note"] = solution.title

            self._apply_solution_to_config(config_data, solution)

            candidate_path = os.path.join(
                self.base_dir, "configs",
                f"candidate_iter_{self.iteration_count}.json"
            )
            with open(candidate_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)

            self._log(f"候选配置已保存: {candidate_path}")
            return candidate_path
        except Exception as e:
            self._log(f"创建候选配置失败: {e}")
            return None

    def _apply_solution_to_config(self, config_data: dict, solution):
        """根据方案类型修改候选配置参数"""
        import random

        if "parameters" not in config_data:
            config_data["parameters"] = {}

        params = config_data["parameters"]

        if solution.solution_type.value == "评估函数优化":
            self._perturb_eval_params(params)
        elif solution.solution_type.value == "搜索算法优化":
            self._perturb_search_params(params)
        elif solution.solution_type.value == "时间管理优化":
            self._perturb_time_params(params)
        elif solution.solution_type.value == "战术优化":
            self._perturb_tactical_params(params)
        elif solution.solution_type.value == "参数优化":
            self._perturb_eval_params(params)
            self._perturb_search_params(params)

    def _perturb_eval_params(self, params: dict):
        """微调评估参数"""
        import random

        if "eval_weights" not in params:
            params["eval_weights"] = {}

        ew = params["eval_weights"]
        perturbations = {
            "bishop_pair_bonus": (30, 70),
            "doubled_pawn_penalty": (-20, -5),
            "isolated_pawn_penalty": (-30, -10),
            "pawn_chain_bonus": (5, 25),
            "open_file_bonus": (5, 25),
            "semi_open_file_bonus": (5, 20),
            "king_activity_weight": (5, 20),
            "simplify_threshold": (150, 300),
            "simplify_bonus": (10, 25),
            "castle_short_bonus": (20, 50),
            "castle_long_bonus": (10, 30),
        }

        for key, (lo, hi) in perturbations.items():
            current = ew.get(key, (lo + hi) // 2 if isinstance(lo, int) else (lo + hi) / 2)
            delta = (hi - lo) * 0.1
            new_val = current + random.uniform(-delta, delta)
            if isinstance(current, int):
                new_val = int(round(new_val))
            ew[key] = new_val

        if "piece_values" in params:
            pv = params["piece_values"]
            for piece in ["pawn", "knight", "bishop", "rook", "queen"]:
                if piece in pv:
                    val = pv[piece]
                    delta = max(1, int(val * 0.02))
                    pv[piece] = val + random.randint(-delta, delta)

        self._log(f"  评估参数已微调")

    def _perturb_search_params(self, params: dict):
        """微调搜索参数"""
        import random

        if "search_params" not in params:
            params["search_params"] = {}

        sp = params["search_params"]
        perturbations = {
            "null_move_reduction": (2, 4),
            "null_move_min_depth": (2, 4),
            "futility_margin_base": (100, 200),
            "razoring_margin": (200, 400),
            "lmr_min_depth": (2, 4),
            "lmr_move_threshold": (1, 4),
        }

        for key, (lo, hi) in perturbations.items():
            current = sp.get(key, (lo + hi) // 2)
            delta = max(1, int((hi - lo) * 0.1))
            if isinstance(current, int):
                sp[key] = current + random.randint(-delta, delta)
            else:
                sp[key] = current + random.uniform(-delta, delta)

        if "constants" not in params:
            params["constants"] = {}
        ct = params["constants"]
        if "delta" in ct:
            ct["delta"] = ct["delta"] + random.randint(-20, 20)

        self._log(f"  搜索参数已微调")

    def _perturb_time_params(self, params: dict):
        """微调时间管理参数"""
        import random

        if "time_management" not in params:
            params["time_management"] = {}

        tm = params["time_management"]
        tm["base_factor"] = tm.get("base_factor", 0.04) + random.uniform(-0.005, 0.005)
        tm["increment_factor"] = tm.get("increment_factor", 0.7) + random.uniform(-0.05, 0.05)
        tm["complexity_factor"] = tm.get("complexity_factor", 1.0) + random.uniform(-0.1, 0.1)

        self._log(f"  时间管理参数已微调")

    def _perturb_tactical_params(self, params: dict):
        """微调战术参数"""
        import random

        if "tactical" not in params:
            params["tactical"] = {}

        tp = params["tactical"]
        tp["see_depth"] = tp.get("see_depth", 12) + random.randint(-2, 2)
        tp["hanging_piece_penalty"] = tp.get("hanging_piece_penalty", 100) + random.randint(-20, 20)
        tp["threat_bonus"] = tp.get("threat_bonus", 100) + random.randint(-20, 20)

        self._log(f"  战术参数已微调")

    def _apply_param_optimization(self, solution, candidate_config: str):
        """应用参数优化"""
        self._log("应用参数优化...")

        if "评估" in solution.title:
            eval_params = self.param_optimizer.get_eval_param_space()
            results = self.param_optimizer.optimize_with_spsa(
                eval_params, candidate_config,
                iterations=self.config.eval_opt_iterations,
                opponent=self.config.target_opponent,
            )
            self._log(f"评估参数优化完成: {len(results)} 个参数")

        elif "搜索" in solution.title:
            search_params = self.param_optimizer.get_search_param_space()
            results = self.param_optimizer.optimize_with_spsa(
                search_params, candidate_config,
                iterations=self.config.search_opt_iterations,
                opponent=self.config.target_opponent,
            )
            self._log(f"搜索参数优化完成: {len(results)} 个参数")

        elif "时间" in solution.title:
            time_params = self.param_optimizer.get_time_mgmt_param_space()
            results = self.param_optimizer.grid_search(
                time_params, candidate_config,
                opponent=self.config.target_opponent,
            )
            self._log(f"时间参数优化完成: {len(results)} 个参数")

        elif "战术" in solution.title:
            tactical_params = self.param_optimizer.get_tactical_param_space()
            results = self.param_optimizer.optimize_with_spsa(
                tactical_params, candidate_config,
                iterations=self.config.tactical_opt_iterations,
                opponent=self.config.target_opponent,
            )
            self._log(f"战术参数优化完成: {len(results)} 个参数")

    def _apply_optimization(self, candidate_config: str, validation_report) -> bool:
        """应用优化"""
        self._log("应用优化...")
        try:
            new_version = f"v1.{self.iteration_count + 5}.0"
            new_path = os.path.join(self.base_dir, "configs", f"{new_version}.json")

            with open(candidate_config, 'r', encoding='utf-8') as f:
                config_data = json.load(f)

            config_data["version"] = new_version
            config_data["validated"] = True
            config_data["elo_change"] = validation_report.elo_change

            with open(new_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)

            self.config.baseline_version = new_version
            self.config_manager.save_config()

            self._log(f"优化已应用，新版本: {new_version}")
            return True
        except Exception as e:
            self._log(f"应用优化失败: {e}")
            return False

    def _cleanup_candidate_config(self, candidate_config: str):
        """清理候选配置"""
        try:
            if os.path.isfile(candidate_config):
                os.remove(candidate_config)
                self._log(f"已清理候选配置: {candidate_config}")
        except Exception as e:
            self._log(f"清理候选配置失败: {e}")

    def _find_recent_pgn_files(self) -> List[str]:
        """查找最近的PGN文件"""
        pgn_files = []
        match_records_dir = os.path.join(self.base_dir, "match_records")
        if os.path.isdir(match_records_dir):
            for root, dirs, files in os.walk(match_records_dir):
                for file in files:
                    if file.endswith(".pgn"):
                        pgn_files.append(os.path.join(root, file))

        auto_tune_pgn = os.path.join(self.base_dir, "auto_tune_match.pgn")
        if os.path.isfile(auto_tune_pgn):
            pgn_files.append(auto_tune_pgn)

        pgn_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        return pgn_files

    def _save_summary(self):
        """保存迭代摘要"""
        summary = {
            "current_iteration": self.iteration_count,
            "status": self.current_status.value,
            "consecutive_failures": self.consecutive_failures,
            "records": [r.to_dict() for r in self.iteration_records],
        }
        try:
            with open(self.summary_file, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self._log(f"保存摘要失败: {e}")

    def _generate_final_summary(self):
        """生成最终总结"""
        successful = sum(1 for r in self.iteration_records if r.status == IterationStatus.COMPLETED)
        failed = sum(1 for r in self.iteration_records if r.status == IterationStatus.FAILED)
        total_elo = sum(r.elo_change for r in self.iteration_records if r.applied)

        best = self.elo_tracker.find_best_version() or self.config.baseline_version

        summary = IterationSummary(
            total_iterations=self.iteration_count,
            successful_iterations=successful,
            failed_iterations=failed,
            total_elo_gain=total_elo,
            best_version=best,
            start_time=self.iteration_records[0].start_time if self.iteration_records else datetime.now().isoformat(),
            end_time=datetime.now().isoformat(),
            iteration_records=self.iteration_records,
        )

        output_path = self.config_manager.get_output_path("final_summary.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(summary.to_dict(), f, indent=2, ensure_ascii=False)

        self._log("\n" + "=" * 60)
        self._log("优化迭代总结")
        self._log("=" * 60)
        self._log(f"总迭代次数: {self.iteration_count}")
        self._log(f"成功: {successful}")
        self._log(f"失败: {failed}")
        self._log(f"总Elo提升: {total_elo:+.1f}")
        self._log(f"最佳版本: {best}")
        self._log("=" * 60)

    def pause(self):
        """暂停优化"""
        self.stop_requested = True
        self._log("优化已暂停")

    def resume(self):
        """恢复优化"""
        self.stop_requested = False
        self._log("优化已恢复")
        self.run_optimization_loop()

    def get_status(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "current_iteration": self.iteration_count,
            "status": self.current_status.value,
            "consecutive_failures": self.consecutive_failures,
            "stop_requested": self.stop_requested,
            "baseline_version": self.config.baseline_version,
        }
