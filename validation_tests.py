"""
验收测试脚本

用于验证引擎各项功能是否正常工作
"""
import os
import sys
import io
import time
import json
from typing import List, Tuple, Dict, Optional

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

try:
    import chess
except ImportError:
    chess = None

try:
    import book_provider
    import endgame
    import search_context
    import opening_health
except ImportError:
    pass


class ValidationTest:
    """验收测试基类"""
    
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.message = ""
    
    def run(self) -> bool:
        raise NotImplementedError
    
    def report(self) -> str:
        status = "✅ PASS" if self.passed else "❌ FAIL"
        return f"{status} [{self.name}] {self.message}"


class BookProviderTest(ValidationTest):
    """开局库测试"""
    
    def __init__(self):
        super().__init__("Book Provider")
    
    def run(self) -> bool:
        if chess is None:
            self.message = "python-chess not installed"
            return False
        
        manager = book_provider.BookManager()
        
        base_path = os.path.dirname(os.path.abspath(__file__))
        book_path = os.path.join(base_path, "dist", "book.bin")
        
        if not os.path.exists(book_path):
            self.message = f"Book file not found: {book_path}"
            self.passed = False
            return False
        
        success = manager.configure(
            mode="internal",
            own_book=True,
            book_path=book_path
        )
        
        if not success:
            self.message = "Failed to load book"
            self.passed = False
            return False
        
        board = chess.Board()
        move = manager.get_book_move(board, 0)
        
        if move:
            self.message = f"Book loaded, entry count: {manager.entry_count}, test move: {move}"
            self.passed = True
        else:
            self.message = f"Book loaded but no move found for starting position"
            self.passed = True
        
        return self.passed


class EndgameClassifierTest(ValidationTest):
    """残局分类器测试"""
    
    def __init__(self):
        super().__init__("Endgame Classifier")
    
    def run(self) -> bool:
        if chess is None:
            self.message = "python-chess not installed"
            return False
        
        classifier = endgame.EndgameClassifier()
        
        board = chess.Board("8/8/8/8/8/8/1k6/1K1Q4 w - - 0 1")
        info = classifier.classify(board)
        
        if info.eg_class == endgame.EndgameClass.BASIC_MATE:
            self.message = f"KQvK correctly classified as BASIC_MATE"
            self.passed = True
        else:
            self.message = f"KQvK misclassified as {info.eg_class}"
            self.passed = False
        
        return self.passed


class BasicMateTest(ValidationTest):
    """基础杀棋测试"""
    
    def __init__(self):
        super().__init__("Basic Mate Templates")
    
    def run(self) -> bool:
        if chess is None:
            self.message = "python-chess not installed"
            return False
        
        mate = endgame.BasicMateTemplates()
        
        board = chess.Board("8/8/8/8/8/8/1k6/1K1Q4 w - - 0 1")
        mate_move = mate.can_mate_directly(board)
        
        if mate_move:
            self.message = f"Mate in 1 found: {mate_move}"
            self.passed = True
        else:
            board = chess.Board("8/8/8/8/8/8/k7/1K1R4 w - - 0 1")
            guide_move = mate.get_mate_guide_move(board)
            if guide_move:
                self.message = f"Mate guide move found: {guide_move}"
                self.passed = True
            else:
                self.message = "No mate move found"
                self.passed = False
        
        return self.passed


class SearchContextTest(ValidationTest):
    """搜索上下文测试"""
    
    def __init__(self):
        super().__init__("Search Context Cache")
    
    def run(self) -> bool:
        cache = search_context.SearchContextCache(max_tt_size=1000)
        
        context = search_context.SearchContext(
            root_fen="test",
            best_move="e2e4",
            ponder_move="e7e5",
            score=30,
            depth=10,
            nodes=1000,
            pv=["e2e4", "e7e5"],
            candidate_moves=[("e7e5", 30), ("c7c5", 25)],
            timestamp=time.time()
        )
        
        cache.save_context(context)
        retrieved = cache.get_context("test")
        
        if retrieved and retrieved.best_move == "e2e4":
            self.message = "Context save/retrieve works correctly"
            self.passed = True
        else:
            self.message = "Context save/retrieve failed"
            self.passed = False
        
        return self.passed


class OpeningHealthTest(ValidationTest):
    """开局健康检查测试"""
    
    def __init__(self):
        super().__init__("Opening Health Check")
    
    def run(self) -> bool:
        if chess is None:
            self.message = "python-chess not installed"
            return False
        
        checker = opening_health.OpeningHealthChecker()
        
        board = chess.Board()
        moves = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"]
        
        result = checker.check_position(board, moves)
        
        if result["status"] in ["healthy", "warning"]:
            self.message = f"Opening health: {result['health_score']:.1f}, status: {result['status']}"
            self.passed = True
        else:
            self.message = f"Opening health check failed: {result}"
            self.passed = False
        
        return self.passed


class TimeManagerTest(ValidationTest):
    """时间管理测试"""
    
    def __init__(self):
        super().__init__("Time Manager")
    
    def run(self) -> bool:
        tm = search_context.TimeManager()
        
        optimal, max_time = tm.compute_time(
            remaining=60.0,
            increment=1.0,
            move_number=10,
            legal_moves_count=30
        )
        
        if optimal > 0 and max_time >= optimal:
            self.message = f"Time allocation: optimal={optimal:.2f}s, max={max_time:.2f}s"
            self.passed = True
        else:
            self.message = f"Invalid time allocation: optimal={optimal}, max={max_time}"
            self.passed = False
        
        return self.passed


class ValidationSuite:
    """验收测试套件"""
    
    def __init__(self):
        self.tests: List[ValidationTest] = []
        self.results: List[Tuple[str, bool, str]] = []
    
    def add_test(self, test: ValidationTest) -> None:
        self.tests.append(test)
    
    def run_all(self) -> Dict:
        """运行所有测试"""
        print("\n" + "=" * 60)
        print("Hellcopter 引擎验收测试")
        print("=" * 60 + "\n")
        
        passed = 0
        failed = 0
        
        for test in self.tests:
            try:
                test.run()
                print(test.report())
                
                if test.passed:
                    passed += 1
                else:
                    failed += 1
                
                self.results.append((test.name, test.passed, test.message))
            except Exception as e:
                failed += 1
                print(f"❌ FAIL [{test.name}] Exception: {e}")
                self.results.append((test.name, False, str(e)))
        
        print("\n" + "=" * 60)
        print(f"测试结果: {passed} passed, {failed} failed")
        print("=" * 60 + "\n")
        
        return {
            "total": len(self.tests),
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / len(self.tests) if self.tests else 0.0
        }
    
    def save_report(self, path: str) -> None:
        """保存测试报告"""
        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "results": [
                {"name": name, "passed": passed, "message": msg}
                for name, passed, msg in self.results
            ]
        }
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)


def main():
    """运行验收测试"""
    suite = ValidationSuite()
    
    suite.add_test(BookProviderTest())
    suite.add_test(EndgameClassifierTest())
    suite.add_test(BasicMateTest())
    suite.add_test(SearchContextTest())
    suite.add_test(OpeningHealthTest())
    suite.add_test(TimeManagerTest())
    
    results = suite.run_all()
    
    report_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "validation_report.json"
    )
    suite.save_report(report_path)
    print(f"报告已保存到: {report_path}")
    
    return 0 if results["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
