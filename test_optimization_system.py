"""
自动化持续优化系统测试套件

测试所有核心模块的功能正确性。
"""

import unittest
import os
import sys
import json
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from optimization_system.config_manager import ConfigManager, OptimizationConfig
from optimization_system.performance_analyzer import PerformanceAnalyzer, IssueType, ErrorSeverity
from optimization_system.solution_generator import SolutionGenerator, SolutionType, SolutionPriority
from optimization_system.test_validator import TestValidator, MatchResult, TestResultStatus
from optimization_system.elo_tracker import EloTracker, EloRecord
from optimization_system.bug_detector import BugDetector, BugType, BugSeverity
from optimization_system.parameter_optimizer import ParameterOptimizer, ParameterSpace


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_manager = ConfigManager(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_default_config(self):
        config = self.config_manager.config
        self.assertEqual(config.target_elo, 9999.0)
        self.assertEqual(config.target_opponent, "apollo")
        self.assertTrue(config.auto_apply)

    def test_save_and_load(self):
        self.config_manager.config.target_elo = 2000.0
        self.config_manager.save_config()

        new_manager = ConfigManager(self.temp_dir)
        config = new_manager.load_config()
        self.assertEqual(config.target_elo, 2000.0)

    def test_output_path(self):
        path = self.config_manager.get_output_path("test.json")
        self.assertIn("test.json", path)


class TestPerformanceAnalyzer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_manager = ConfigManager(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_issue_classification(self):
        from optimization_system.performance_analyzer import PerformanceIssue
        issue = PerformanceIssue(
            issue_type=IssueType.FATAL_ERROR,
            severity=ErrorSeverity.CRITICAL,
            description="致命错误",
            fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            move_number=10,
            uci_move="e2e4",
            score_diff=600,
        )
        self.assertEqual(issue.issue_type, IssueType.FATAL_ERROR)
        self.assertEqual(issue.severity, ErrorSeverity.CRITICAL)


class TestSolutionGenerator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_manager = ConfigManager(self.temp_dir)
        self.generator = SolutionGenerator(self.config_manager)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_generate_solutions_empty_report(self):
        from optimization_system.performance_analyzer import AnalysisReport
        report = AnalysisReport(
            report_id="test",
            timestamp="2024-01-01",
            total_games=0,
            total_moves=0,
        )
        doc = self.generator.generate_solutions(report)
        self.assertIsNotNone(doc)
        self.assertGreaterEqual(len(doc.solutions), 4)

    def test_solution_priorities(self):
        from optimization_system.performance_analyzer import AnalysisReport
        report = AnalysisReport(
            report_id="test",
            timestamp="2024-01-01",
            total_games=0,
            total_moves=0,
        )
        doc = self.generator.generate_solutions(report)
        if doc.solutions:
            first = doc.solutions[0]
            self.assertIn(first.priority, [SolutionPriority.CRITICAL, SolutionPriority.HIGH])


class TestEloTracker(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_manager = ConfigManager(self.temp_dir)
        self.tracker = EloTracker(self.config_manager)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_record_match(self):
        self.tracker.record_match_result(
            version="v1.0",
            wins=10, losses=5, draws=3,
            opponent="apollo",
            time_control="96+0.8",
        )
        self.assertEqual(len(self.tracker.records), 1)
        record = self.tracker.records[0]
        self.assertEqual(record.version, "v1.0")
        self.assertEqual(record.opponent, "apollo")

    def test_find_best_version(self):
        self.tracker.record_match_result("v1.0", 5, 10, 0, "apollo", "96+0.8")
        self.tracker.record_match_result("v1.1", 10, 5, 0, "apollo", "96+0.8")
        best = self.tracker.find_best_version()
        self.assertEqual(best, "v1.1")

    def test_is_regression(self):
        self.tracker.record_match_result("v1.0", 10, 5, 0, "apollo", "96+0.8")
        self.tracker.record_match_result("v1.0", 3, 10, 2, "apollo", "96+0.8")
        self.assertTrue(self.tracker.is_regression("v1.0"))


class TestBugDetector(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_manager = ConfigManager(self.temp_dir)
        self.detector = BugDetector(self.config_manager)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_detect_illegal_move(self):
        bug = self.detector.detect_illegal_move(
            fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            move="e2e9",
        )
        self.assertIsNotNone(bug)
        self.assertEqual(bug.bug_type, BugType.ILLEGAL_MOVE)
        self.assertEqual(bug.severity, BugSeverity.FATAL)

    def test_get_unfixed_bugs(self):
        self.detector.detect_illegal_move("fen", "move1")
        self.detector.detect_engine_crash("error", "fen")
        unfixed = self.detector.get_unfixed_bugs()
        self.assertEqual(len(unfixed), 2)

    def test_should_halt(self):
        self.assertFalse(self.detector.should_halt_optimization())
        self.detector.detect_illegal_move("fen", "move1")
        self.assertTrue(self.detector.should_halt_optimization())


class TestParameterOptimizer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_manager = ConfigManager(self.temp_dir)
        self.optimizer = ParameterOptimizer(self.config_manager, self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_get_search_params(self):
        params = self.optimizer.get_search_param_space()
        self.assertGreater(len(params), 0)
        self.assertEqual(params[0].param_type, "search")

    def test_get_eval_params(self):
        params = self.optimizer.get_eval_param_space()
        self.assertGreater(len(params), 0)
        self.assertEqual(params[0].param_type, "eval")

    def test_validate_param(self):
        param = ParameterSpace("test", "search", 0, 100, 50, 1)
        self.assertTrue(self.optimizer.validate_param(param, 50))
        self.assertFalse(self.optimizer.validate_param(param, 150))

    def test_check_convergence_empty(self):
        result = self.optimizer.check_convergence("test_param")
        self.assertFalse(result)


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_full_workflow(self):
        config_manager = ConfigManager(self.temp_dir)
        config = config_manager.load_config()

        tracker = EloTracker(config_manager)
        tracker.record_match_result("v1.0", 10, 5, 3, "apollo", "96+0.8")

        detector = BugDetector(config_manager)
        self.assertFalse(detector.should_halt_optimization())

        generator = SolutionGenerator(config_manager)
        from optimization_system.performance_analyzer import AnalysisReport
        report = AnalysisReport("test", "2024-01-01", 0, 0)
        doc = generator.generate_solutions(report)
        self.assertIsNotNone(doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
