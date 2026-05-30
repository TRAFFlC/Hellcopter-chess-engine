"""
方案生成器模块

根据性能分析报告生成优化方案，包括：
- BUG修复方案
- 参数优化方案
- 搜索算法优化方案
- 评估函数优化方案
- 时间管理优化方案
- 战术优化方案（子力交换、棋子安全）
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any

from .performance_analyzer import AnalysisReport, IssueType, ErrorSeverity, PerformanceIssue


class SolutionType(Enum):
    BUG_FIX = "BUG修复"
    PARAM_OPTIMIZATION = "参数优化"
    SEARCH_ALGORITHM = "搜索算法优化"
    EVAL_FUNCTION = "评估函数优化"
    OPENING_BOOK = "开局库优化"
    ENDGAME_TABLE = "残局库优化"
    TIME_MANAGEMENT = "时间管理优化"
    TACTICAL = "战术优化"
    PONDERING = "后台思考优化"


class SolutionPriority(Enum):
    CRITICAL = "紧急"
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


@dataclass
class OptimizationSolution:
    solution_id: str
    solution_type: SolutionType
    priority: SolutionPriority
    title: str
    description: str
    root_cause: str
    implementation_steps: List[str] = field(default_factory=list)
    expected_benefit: str = ""
    risk_level: str = "低"
    estimated_effort: str = ""
    affected_modules: List[str] = field(default_factory=list)
    test_plan: List[str] = field(default_factory=list)
    rollback_plan: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "solution_id": self.solution_id,
            "solution_type": self.solution_type.value,
            "priority": self.priority.value,
            "title": self.title,
            "description": self.description,
            "root_cause": self.root_cause,
            "implementation_steps": self.implementation_steps,
            "expected_benefit": self.expected_benefit,
            "risk_level": self.risk_level,
            "estimated_effort": self.estimated_effort,
            "affected_modules": self.affected_modules,
            "test_plan": self.test_plan,
            "rollback_plan": self.rollback_plan,
        }


@dataclass
class SolutionDocument:
    document_id: str
    timestamp: str
    based_on_report: str
    solutions: List[OptimizationSolution] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "timestamp": self.timestamp,
            "based_on_report": self.based_on_report,
            "solutions": [s.to_dict() for s in self.solutions],
            "summary": self.summary,
        }


class SolutionGenerator:
    """方案生成器"""

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.config = config_manager.config
        self.solutions: List[OptimizationSolution] = []

    def generate_solutions(self, report: AnalysisReport) -> SolutionDocument:
        """根据分析报告生成优化方案"""
        self.solutions = []

        for issue in report.issues:
            solution = self._create_solution_for_issue(issue)
            if solution:
                self.solutions.append(solution)

        for issue in report.opening_issues:
            solution = self._create_opening_solution(issue)
            if solution and not any(s.solution_id == solution.solution_id for s in self.solutions):
                self.solutions.append(solution)

        for issue in report.endgame_issues:
            solution = self._create_endgame_solution(issue)
            if solution and not any(s.solution_id == solution.solution_id for s in self.solutions):
                self.solutions.append(solution)

        if self.config.enable_eval_opt:
            eval_solution = self._create_eval_optimization_solution()
            if eval_solution:
                self.solutions.append(eval_solution)

        if self.config.enable_search_opt:
            search_solution = self._create_search_pruning_solution()
            if search_solution:
                self.solutions.append(search_solution)

        if self.config.enable_time_mgmt_opt:
            time_solution = self._create_time_management_solution()
            if time_solution:
                self.solutions.append(time_solution)

        if self.config.enable_tactical_opt:
            tactical_solution = self._create_tactical_solution()
            if tactical_solution:
                self.solutions.append(tactical_solution)

        if self.config.enable_pondering:
            ponder_solution = self._create_pondering_solution()
            if ponder_solution:
                self.solutions.append(ponder_solution)

        self.solutions.sort(key=lambda s: (
            0 if s.priority == SolutionPriority.CRITICAL else
            1 if s.priority == SolutionPriority.HIGH else
            2 if s.priority == SolutionPriority.MEDIUM else 3
        ))

        doc_id = f"solutions_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        return SolutionDocument(
            document_id=doc_id,
            timestamp=datetime.now().isoformat(),
            based_on_report=report.report_id,
            solutions=self.solutions,
            summary=self._generate_summary(),
        )

    def _create_solution_for_issue(self, issue: PerformanceIssue) -> Optional[OptimizationSolution]:
        """为单个问题创建解决方案"""
        if issue.issue_type == IssueType.FATAL_ERROR:
            return self._create_bug_fix_solution(issue)
        elif issue.issue_type == IssueType.PERFORMANCE_ISSUE:
            return self._create_param_opt_solution(issue)
        elif issue.issue_type == IssueType.SEARCH_ISSUE:
            return self._create_search_opt_solution(issue)
        return None

    def _create_bug_fix_solution(self, issue: PerformanceIssue) -> OptimizationSolution:
        """创建BUG修复方案"""
        solution_id = f"bugfix_{issue.fen.replace(' ', '_')[:20]}_{issue.move_number}"

        if "漏杀" in issue.description:
            return OptimizationSolution(
                solution_id=solution_id,
                solution_type=SolutionType.BUG_FIX,
                priority=SolutionPriority.CRITICAL,
                title="修复将杀检测BUG",
                description=f"在局面 {issue.fen[:50]}... 中漏杀",
                root_cause="搜索深度不足或将杀检测逻辑缺陷",
                implementation_steps=[
                    "检查 search_with_score 函数中的将杀检测逻辑",
                    "增加 quiescence search 中的将杀检查",
                    "验证 mate distance pruning 实现",
                    "添加针对该局面的回归测试",
                ],
                expected_benefit="消除漏杀，提升对局胜率5-10%",
                risk_level="中",
                estimated_effort="2-4小时",
                affected_modules=["engine_wrapper.py", "engine_core.c"],
                test_plan=[
                    "运行 validation_tests.py",
                    "使用 FEN 局面进行手动验证",
                    "运行 100 局快棋测试",
                ],
                rollback_plan="回退到上一版本配置",
            )
        else:
            return OptimizationSolution(
                solution_id=solution_id,
                solution_type=SolutionType.BUG_FIX,
                priority=SolutionPriority.CRITICAL if issue.severity == ErrorSeverity.CRITICAL else SolutionPriority.HIGH,
                title="修复评估函数致命错误",
                description=f"评估偏差 {issue.score_diff} 分",
                root_cause="评估函数计算错误或溢出",
                implementation_steps=[
                    "检查 evaluate 函数中的边界条件",
                    "验证 piece value 和 PST 表",
                    "检查是否有整数溢出",
                    "添加断言检查评估值范围",
                ],
                expected_benefit="消除重大失误，提升稳定性",
                risk_level="低",
                estimated_effort="1-2小时",
                affected_modules=["engine_core.c", "eval_param_manager.py"],
                test_plan=[
                    "运行 test_positions.py",
                    "对比 Velvet 评估值",
                    "运行 50 局快棋测试",
                ],
                rollback_plan="回退到上一版本配置",
            )

    def _create_param_opt_solution(self, issue: PerformanceIssue) -> OptimizationSolution:
        """创建参数优化方案"""
        solution_id = f"paramopt_{issue.fen.replace(' ', '_')[:20]}_{issue.move_number}"

        if issue.velvet_depth > 0 and issue.velvet_depth >= 20:
            return OptimizationSolution(
                solution_id=solution_id,
                solution_type=SolutionType.PARAM_OPTIMIZATION,
                priority=SolutionPriority.HIGH,
                title="优化搜索参数提升深度",
                description=f"Velvet搜索深度{issue.velvet_depth}，Hellcopter可能深度不足",
                root_cause="搜索剪枝过于激进或时间分配不合理",
                implementation_steps=[
                    "调整 futility_margin_base 参数",
                    "优化 razoring_margin 阈值",
                    "检查 LMR 条件是否过于激进",
                    "优化时间分配策略",
                ],
                expected_benefit="搜索深度提升2-5层，Elo提升20-50",
                risk_level="中",
                estimated_effort="3-6小时",
                affected_modules=["engine_core.c", "spsa_tuner.py"],
                test_plan=[
                    "运行 SPSA 调优",
                    "对比搜索深度分布",
                    "运行 200 局快棋测试",
                ],
                rollback_plan="恢复原始搜索参数",
            )
        else:
            return OptimizationSolution(
                solution_id=solution_id,
                solution_type=SolutionType.PARAM_OPTIMIZATION,
                priority=SolutionPriority.MEDIUM,
                title="调整评估权重",
                description=f"分数损失 {issue.score_diff} 分",
                root_cause="评估权重不平衡",
                implementation_steps=[
                    "使用 Texel Tuning 优化评估参数",
                    "调整相关 piece values",
                    "优化 PST 表权重",
                    "验证改进效果",
                ],
                expected_benefit="减少失误，Elo提升10-30",
                risk_level="低",
                estimated_effort="4-8小时",
                affected_modules=["eval_param_manager.py", "texel_tuner.py"],
                test_plan=[
                    "运行 Texel Tuning",
                    "对比评估值准确性",
                    "运行 100 局快棋测试",
                ],
                rollback_plan="恢复原始评估参数",
            )

    def _create_search_opt_solution(self, issue: PerformanceIssue) -> OptimizationSolution:
        """创建搜索算法优化方案"""
        solution_id = f"searchopt_{issue.fen.replace(' ', '_')[:20]}_{issue.move_number}"
        return OptimizationSolution(
            solution_id=solution_id,
            solution_type=SolutionType.SEARCH_ALGORITHM,
            priority=SolutionPriority.HIGH,
            title="优化搜索算法",
            description="搜索深度差异超过10层",
            root_cause="搜索剪枝策略或着法排序问题",
            implementation_steps=[
                "优化着法排序（MVV-LVA + Killer + History）",
                "调整 Null Move Pruning 条件",
                "优化 LMR 表格",
                "改进 Iterative Deepening",
            ],
            expected_benefit="搜索效率提升，Elo提升30-80",
            risk_level="高",
            estimated_effort="8-16小时",
            affected_modules=["engine_core.c", "search_context.py"],
            test_plan=[
                "运行 perft 测试验证正确性",
                "对比节点数减少比例",
                "运行 500 局快棋测试",
            ],
            rollback_plan="回退到上一版本引擎核心",
        )

    def _create_opening_solution(self, issue: PerformanceIssue) -> OptimizationSolution:
        """创建开局优化方案"""
        return OptimizationSolution(
            solution_id=f"opening_{issue.fen.replace(' ', '_')[:20]}",
            solution_type=SolutionType.OPENING_BOOK,
            priority=SolutionPriority.MEDIUM,
            title="优化开局库配置",
            description="开局阶段出现异常行为",
            root_cause="开局库配置不当或覆盖不足",
            implementation_steps=[
                "检查 opening_book.json 覆盖范围",
                "增加常见开局变例",
                "调整 BookRandomness 参数",
                "验证开局库质量",
            ],
            expected_benefit="开局胜率提升5-15%",
            risk_level="低",
            estimated_effort="2-4小时",
            affected_modules=["opening_book.py", "book_provider.py"],
            test_plan=[
                "运行 test_opening.py",
                "统计开局阶段胜率",
                "运行 100 局完整对局",
            ],
            rollback_plan="恢复原始开局库",
        )

    def _create_endgame_solution(self, issue: PerformanceIssue) -> OptimizationSolution:
        """创建残局优化方案"""
        return OptimizationSolution(
            solution_id=f"endgame_{issue.fen.replace(' ', '_')[:20]}",
            solution_type=SolutionType.ENDGAME_TABLE,
            priority=SolutionPriority.HIGH,
            title="优化残局评估和转化",
            description="残局阶段转化失败",
            root_cause="残局评估函数不准确或缺少残局库",
            implementation_steps=[
                "实现基本残局库（KQvK, KRvK等）",
                "优化 passer pawn 评估",
                "改进王活性评估",
                "添加残局特定启发式",
            ],
            expected_benefit="残局胜率提升10-20%",
            risk_level="中",
            estimated_effort="6-12小时",
            affected_modules=["endgame.py", "engine_core.c"],
            test_plan=[
                "运行 endgame_test_suite.py",
                "验证基本残局必胜",
                "运行 200 局残局测试",
            ],
            rollback_plan="禁用残局优化",
        )

    def _create_eval_optimization_solution(self) -> Optional[OptimizationSolution]:
        """创建评估函数迭代优化方案"""
        if not self.config.enable_eval_opt:
            return None
        return OptimizationSolution(
            solution_id="eval_opt_iter",
            solution_type=SolutionType.EVAL_FUNCTION,
            priority=SolutionPriority.HIGH,
            title="迭代优化评估函数参数",
            description="使用Texel Tuning和SPSA持续优化评估参数",
            root_cause="评估函数参数可能未达最优",
            implementation_steps=[
                f"运行Texel Tuning ({self.config.eval_opt_iterations}轮)",
                "扩展新的评估参数（如兵形、王安全等）",
                "使用SPSA微调关键参数",
                "验证评估值与Velvet的一致性",
                "添加新的评估特征（如通路兵潜力、弱格等）",
            ],
            expected_benefit="Elo提升20-60",
            risk_level="低",
            estimated_effort="6-12小时",
            affected_modules=["eval_param_manager.py", "texel_tuner.py", "spsa_tuner.py"],
            test_plan=[
                "运行Texel Tuning验证",
                "对比评估值分布",
                "运行200局快棋测试",
                "运行标准对局测试",
            ],
            rollback_plan="恢复原始评估参数",
        )

    def _create_search_pruning_solution(self) -> Optional[OptimizationSolution]:
        """创建搜索剪枝算法检测和优化方案"""
        if not self.config.enable_search_opt:
            return None
        return OptimizationSolution(
            solution_id="search_pruning_opt",
            solution_type=SolutionType.SEARCH_ALGORITHM,
            priority=SolutionPriority.HIGH,
            title="检测并优化搜索剪枝算法效果",
            description="验证现有剪枝算法是否正常工作并达到预期效果",
            root_cause="剪枝算法可能未发挥应有作用",
            implementation_steps=[
                "测量各剪枝算法的触发频率（NMP、LMR、Futility、Razoring等）",
                "对比启用/禁用各剪枝的Elo变化",
                "分析剪枝导致的漏判局面",
                "调整剪枝阈值使其更激进或更保守",
                "优化着法排序以提高剪枝效率",
                "检查双重扩展和 singular extension 实现",
            ],
            expected_benefit="搜索效率提升15-30%，Elo提升30-80",
            risk_level="高",
            estimated_effort="10-20小时",
            affected_modules=["engine_core.c", "search_context.py", "spsa_tuner.py"],
            test_plan=[
                "统计各剪枝算法触发率",
                "运行ablation study（逐一禁用测试）",
                "运行500局快棋测试",
                "运行标准对局测试",
            ],
            rollback_plan="恢复原始搜索参数",
        )

    def _create_time_management_solution(self) -> Optional[OptimizationSolution]:
        """创建时间管理优化方案"""
        if not self.config.enable_time_mgmt_opt:
            return None
        return OptimizationSolution(
            solution_id="time_mgmt_opt",
            solution_type=SolutionType.TIME_MANAGEMENT,
            priority=SolutionPriority.HIGH,
            title="优化时间分配策略",
            description="让引擎在不同局面下更好地利用时间",
            root_cause="固定时间分配无法适应复杂局面",
            implementation_steps=[
                "实现基于局面复杂度的动态时间分配",
                "在关键局面（如战术局面、时间紧张时）增加思考时间",
                "优化开局和残局的时间使用策略",
                "实现基于对手时间的自适应策略",
                "添加时间恐慌模式处理",
            ],
            expected_benefit="复杂局面决策质量提升，Elo提升15-40",
            risk_level="中",
            estimated_effort="6-12小时",
            affected_modules=["engine_core.c", "uci_engine.py"],
            test_plan=[
                "统计各阶段时间使用分布",
                "测试复杂局面的决策质量",
                "运行200局标准时制测试",
                "测试时间恐慌处理",
            ],
            rollback_plan="恢复固定时间分配",
        )

    def _create_tactical_solution(self) -> Optional[OptimizationSolution]:
        """创建战术优化方案（子力交换、棋子安全）"""
        if not self.config.enable_tactical_opt:
            return None
        return OptimizationSolution(
            solution_id="tactical_opt",
            solution_type=SolutionType.TACTICAL,
            priority=SolutionPriority.HIGH,
            title="优化子力交换计算和棋子安全",
            description="提升复杂交换计算能力，避免棋子走到易受攻击位置",
            root_cause="SEE计算深度不足，棋子安全评估不准确",
            implementation_steps=[
                f"增加SEE计算深度至{self.config.exchange_analysis_depth}层",
                "优化复杂交换序列的搜索",
                "实现棋子安全评估（被攻击、保护不足）",
                "添加陷阱检测（避免走入被串击、叉击等）",
                "优化牵制和击双的检测",
                "改进通路兵和弱格的评估",
            ],
            expected_benefit="战术失误减少50%，Elo提升30-70",
            risk_level="中",
            estimated_effort="8-16小时",
            affected_modules=["engine_core.c", "eval_param_manager.py"],
            test_plan=[
                "运行战术测试集",
                "统计交换决策准确率",
                "运行300局快棋测试",
                "运行标准对局测试",
            ],
            rollback_plan="恢复原始战术评估",
        )

    def _create_pondering_solution(self) -> Optional[OptimizationSolution]:
        """创建后台思考（Pondering）优化方案"""
        if not self.config.enable_pondering:
            return None
        return OptimizationSolution(
            solution_id="pondering_opt",
            solution_type=SolutionType.PONDERING,
            priority=SolutionPriority.MEDIUM,
            title="实现后台思考（Pondering）",
            description="在对手思考时持续分析，利用已有分析进行进一步搜索",
            root_cause="未利用对手思考时间",
            implementation_steps=[
                "实现ponderhit处理逻辑",
                "在对手思考时继续搜索预期着法",
                "优化ponder命中时的搜索复用",
                "实现ponder失败时的快速切换",
                "添加ponder统计和效率监控",
            ],
            expected_benefit="有效思考时间增加30-50%，Elo提升10-30",
            risk_level="中",
            estimated_effort="4-8小时",
            affected_modules=["uci_engine.py", "engine_core.c"],
            test_plan=[
                "统计ponder命中率",
                "测试ponder复用效率",
                "运行200局标准时制测试",
                "验证ponder不影响正常搜索",
            ],
            rollback_plan="禁用pondering",
        )

    def _generate_summary(self) -> Dict[str, Any]:
        bug_fixes = sum(1 for s in self.solutions if s.solution_type == SolutionType.BUG_FIX)
        param_opts = sum(1 for s in self.solutions if s.solution_type == SolutionType.PARAM_OPTIMIZATION)
        search_opts = sum(1 for s in self.solutions if s.solution_type == SolutionType.SEARCH_ALGORITHM)
        eval_opts = sum(1 for s in self.solutions if s.solution_type == SolutionType.EVAL_FUNCTION)
        opening_opts = sum(1 for s in self.solutions if s.solution_type == SolutionType.OPENING_BOOK)
        endgame_opts = sum(1 for s in self.solutions if s.solution_type == SolutionType.ENDGAME_TABLE)
        time_opts = sum(1 for s in self.solutions if s.solution_type == SolutionType.TIME_MANAGEMENT)
        tactical_opts = sum(1 for s in self.solutions if s.solution_type == SolutionType.TACTICAL)
        ponder_opts = sum(1 for s in self.solutions if s.solution_type == SolutionType.PONDERING)

        critical = sum(1 for s in self.solutions if s.priority == SolutionPriority.CRITICAL)
        high = sum(1 for s in self.solutions if s.priority == SolutionPriority.HIGH)
        medium = sum(1 for s in self.solutions if s.priority == SolutionPriority.MEDIUM)
        low = sum(1 for s in self.solutions if s.priority == SolutionPriority.LOW)

        return {
            "total_solutions": len(self.solutions),
            "by_type": {
                "bug_fixes": bug_fixes,
                "param_optimizations": param_opts,
                "search_optimizations": search_opts,
                "eval_optimizations": eval_opts,
                "opening_optimizations": opening_opts,
                "endgame_optimizations": endgame_opts,
                "time_management": time_opts,
                "tactical": tactical_opts,
                "pondering": ponder_opts,
            },
            "by_priority": {
                "critical": critical,
                "high": high,
                "medium": medium,
                "low": low,
            },
            "estimated_total_effort": self._estimate_total_effort(),
        }

    def _estimate_total_effort(self) -> str:
        total_hours = 0
        for solution in self.solutions:
            effort = solution.estimated_effort
            if "小时" in effort:
                try:
                    parts = effort.replace("小时", "").split("-")
                    if len(parts) == 2:
                        total_hours += (float(parts[0]) + float(parts[1])) / 2
                    else:
                        total_hours += float(parts[0])
                except:
                    pass
        return f"约 {total_hours:.0f} 小时"

    def save_document(self, document: SolutionDocument, output_path: Optional[str] = None):
        if output_path is None:
            output_path = self.config_manager.get_output_path(
                f"solution_document_{document.document_id}.json"
            )
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(document.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"方案文档已保存: {output_path}")
