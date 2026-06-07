#!/usr/bin/env python3
"""
测试运行器

支持分类运行、超时控制、结果汇总。
"""

import unittest
import sys
import os
import time
import json
from datetime import datetime

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestResult:
    """测试结果封装"""
    
    def __init__(self):
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.errors = 0
        self.skipped = 0
        self.failures = []
        self.errors_list = []
        self.start_time = None
        self.end_time = None
    
    @property
    def duration(self) -> float:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return 0.0
    
    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total * 100
    
    def to_dict(self) -> dict:
        return {
            'total': self.total,
            'passed': self.passed,
            'failed': self.failed,
            'errors': self.errors,
            'skipped': self.skipped,
            'success_rate': round(self.success_rate, 2),
            'duration': round(self.duration, 2),
            'failures': self.failures,
            'errors': self.errors_list
        }


class CustomTestResult(unittest.TestResult):
    """自定义测试结果收集器"""
    
    def __init__(self):
        super().__init__()
        self.result = TestResult()
        self.start_time = None
    
    def startTest(self, test):
        super().startTest(test)
        self.result.total += 1
        if self.start_time is None:
            self.start_time = time.time()
    
    def addSuccess(self, test):
        super().addSuccess(test)
        self.result.passed += 1
    
    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.result.failed += 1
        self.result.failures.append({
            'test': str(test),
            'error': err[1]
        })
    
    def addError(self, test, err):
        super().addError(test, err)
        self.result.errors += 1
        self.result.errors_list.append({
            'test': str(test),
            'error': err[1]
        })
    
    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.result.skipped += 1


class TestRunner:
    """测试运行器"""
    
    def __init__(self, timeout: int = 300):
        """
        Args:
            timeout: 单个测试的超时时间（秒）
        """
        self.timeout = timeout
        self.results = {}
    
    def discover_tests(self, pattern: str = 'test_*.py') -> unittest.TestSuite:
        """发现测试用例"""
        loader = unittest.TestLoader()
        start_dir = os.path.dirname(os.path.abspath(__file__))
        suite = loader.discover(start_dir, pattern=pattern, top_level_dir=os.path.dirname(start_dir))
        return suite
    
    def run_suite(self, suite: unittest.TestSuite, name: str = 'all') -> TestResult:
        """运行测试套件"""
        print(f"\n{'='*60}")
        print(f"运行测试: {name}")
        print(f"{'='*60}")
        
        result = CustomTestResult()
        result.result.start_time = time.time()
        
        suite.run(result)
        
        result.result.end_time = time.time()
        self.results[name] = result.result
        
        return result.result
    
    def run_category(self, category: str) -> TestResult:
        """运行特定类别的测试"""
        category_map = {
            'search': 'test_search.py',
            'pruning': 'test_pruning.py',
            'eval': 'test_eval.py',
            'time': 'test_time_mgmt.py',
            'all': 'test_*.py'
        }
        
        pattern = category_map.get(category, f'test_{category}.py')
        suite = self.discover_tests(pattern)
        return self.run_suite(suite, category)
    
    def run_all(self) -> dict:
        """运行所有测试"""
        suite = self.discover_tests()
        result = self.run_suite(suite, 'all')
        return result.to_dict()
    
    def print_summary(self):
        """打印测试结果摘要"""
        print(f"\n{'='*60}")
        print("测试结果摘要")
        print(f"{'='*60}")
        
        total_passed = 0
        total_failed = 0
        total_errors = 0
        total_skipped = 0
        total_duration = 0.0
        
        for name, result in self.results.items():
            print(f"\n{name}:")
            print(f"  总数: {result.total}")
            print(f"  通过: {result.passed}")
            print(f"  失败: {result.failed}")
            print(f"  错误: {result.errors}")
            print(f"  跳过: {result.skipped}")
            print(f"  成功率: {result.success_rate:.1f}%")
            print(f"  耗时: {result.duration:.2f}s")
            
            total_passed += result.passed
            total_failed += result.failed
            total_errors += result.errors
            total_skipped += result.skipped
            total_duration += result.duration
        
        print(f"\n总计:")
        print(f"  通过: {total_passed}")
        print(f"  失败: {total_failed}")
        print(f"  错误: {total_errors}")
        print(f"  跳过: {total_skipped}")
        print(f"  总耗时: {total_duration:.2f}s")
        
        if total_failed > 0 or total_errors > 0:
            print(f"\n失败的测试:")
            for name, result in self.results.items():
                for failure in result.failures:
                    print(f"  [{name}] {failure['test']}")
                    print(f"    {failure['error']}")
                
                for error in result.errors_list:
                    print(f"  [{name}] {error['test']}")
                    print(f"    {error['error']}")
    
    def save_report(self, output_file: str = 'test_report.json'):
        """保存测试报告"""
        report = {
            'timestamp': datetime.now().isoformat(),
            'results': {name: result.to_dict() for name, result in self.results.items()}
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"\n测试报告已保存到: {output_file}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='引擎测试运行器')
    parser.add_argument('--category', '-c', default='all',
                       choices=['all', 'search', 'pruning', 'eval', 'time'],
                       help='测试类别')
    parser.add_argument('--timeout', '-t', type=int, default=300,
                       help='单个测试超时时间（秒）')
    parser.add_argument('--report', '-r', default='test_report.json',
                       help='测试报告输出文件')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='详细输出')
    
    args = parser.parse_args()
    
    runner = TestRunner(timeout=args.timeout)
    
    if args.category == 'all':
        result = runner.run_all()
    else:
        result = runner.run_category(args.category)
    
    runner.print_summary()
    runner.save_report(args.report)
    
    # 返回退出码
    if result['failed'] > 0 or result['errors'] > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
