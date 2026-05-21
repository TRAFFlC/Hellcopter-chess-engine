"""
Perft 测试框架 - 验证着法生成的正确性

Perft (performance test) 通过递归计算指定深度下的所有节点数，
来验证着法生成器是否正确处理所有特殊情况：
- 吃过路兵 (en passant)
- 王车易位 (castling)
- 兵升变 (promotion)
- 发现将军时的非法走法过滤
"""

import time
import sys
from engine_wrapper import perft

INITIAL_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

INITIAL_POSITION_PERFT = {
    1: 20,
    2: 400,
    3: 8902,
    4: 197281,
    5: 4865609,
    6: 119060324,
}

TEST_CASES = [
    {
        "name": "初始局面",
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "perft": {
            1: 20,
            2: 400,
            3: 8902,
            4: 197281,
            5: 4865609,
        },
    },
    {
        "name": "Kiwipete (复杂战术局面)",
        "fen": "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        "perft": {
            1: 48,
            2: 2039,
            3: 97862,
            4: 4085603,
            5: 193690690,
        },
    },
    {
        "name": "位置3 (吃过路兵测试)",
        "fen": "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
        "perft": {
            1: 14,
            2: 191,
            3: 2812,
            4: 43238,
            5: 674624,
        },
    },
    {
        "name": "位置4 (王车易位规则)",
        "fen": "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
        "perft": {
            1: 6,
            2: 264,
            3: 9467,
            4: 422333,
            5: 15833292,
        },
    },
    {
        "name": "位置6 (复杂吃子)",
        "fen": "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
        "perft": {
            1: 46,
            2: 2079,
            3: 89890,
            4: 3894594,
            5: 164075551,
        },
    },
    {
        "name": "吃过路兵局面1",
        "fen": "rnbqkbnr/pppp1ppp/8/4pP2/8/8/PPPPP1PP/RNBQKBNR w KQkq e6 0 3",
        "perft": {
            1: 21,
            2: 607,
            3: 13119,
            4: 382294,
            5: 9181920,
        },
    },
    {
        "name": "吃过路兵局面2",
        "fen": "rnbqkbnr/ppp1pppp/8/3pP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3",
        "perft": {
            1: 31,
            2: 807,
            3: 24988,
            4: 666467,
            5: 21279595,
        },
    },
    {
        "name": "王车易位局面",
        "fen": "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
        "perft": {
            1: 26,
            2: 568,
            3: 13744,
            4: 314346,
            5: 7594526,
        },
    },
    {
        "name": "升变局面",
        "fen": "8/P7/8/8/8/8/8/4K2k w - - 0 1",
        "perft": {
            1: 9,
            2: 21,
            3: 252,
            4: 1014,
            5: 15313,
        },
    },
    {
        "name": "双升变局面",
        "fen": "n1n5/PPPk4/8/8/8/8/4Kppp/5N1N b - - 0 1",
        "perft": {
            1: 24,
            2: 496,
            3: 9483,
            4: 182838,
            5: 3605103,
        },
    },
]


def run_single_test(name: str, fen: str, depth: int, expected: int) -> tuple[bool, int, float]:
    """运行单个 perft 测试"""
    start = time.perf_counter()
    result = perft(fen, depth)
    elapsed = time.perf_counter() - start
    passed = result == expected
    return passed, result, elapsed


def run_test_case(case: dict, max_depth: int = None) -> tuple[int, int]:
    """运行一个测试用例的所有深度"""
    name = case["name"]
    fen = case["fen"]
    perft_values = case["perft"]
    
    passed_count = 0
    total_count = 0
    
    print(f"\n{'='*60}")
    print(f"测试: {name}")
    print(f"FEN: {fen}")
    print(f"{'-'*60}")
    
    for depth, expected in perft_values.items():
        if max_depth is not None and depth > max_depth:
            continue
        
        total_count += 1
        passed, result, elapsed = run_single_test(name, fen, depth, expected)
        
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"  深度 {depth}: {result:>15,} (期望: {expected:>15,}) "
              f"[{elapsed:.3f}s] {status}")
        
        if passed:
            passed_count += 1
    
    return passed_count, total_count


def run_all_tests(max_depth: int = None, verbose: bool = True) -> bool:
    """运行所有测试用例"""
    print("=" * 60)
    print("Perft 测试 - 着法生成正确性验证")
    print("=" * 60)
    
    total_passed = 0
    total_tests = 0
    
    for case in TEST_CASES:
        passed, total = run_test_case(case, max_depth)
        total_passed += passed
        total_tests += total
    
    print(f"\n{'='*60}")
    print(f"测试结果: {total_passed}/{total_tests} 通过")
    print("=" * 60)
    
    return total_passed == total_tests


def quick_test():
    """快速测试 - 只测试初始局面深度1-4"""
    print("=" * 60)
    print("快速 Perft 测试 (初始局面深度1-4)")
    print("=" * 60)
    
    all_passed = True
    for depth in range(1, 5):
        expected = INITIAL_POSITION_PERFT[depth]
        passed, result, elapsed = run_single_test(
            "初始局面", INITIAL_FEN, depth, expected
        )
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"深度 {depth}: {result:>12,} (期望: {expected:>12,}) "
              f"[{elapsed:.3f}s] {status}")
        if not passed:
            all_passed = False
    
    return all_passed


def benchmark(depth: int = 5):
    """性能基准测试"""
    print("=" * 60)
    print(f"Perft 性能基准测试 (初始局面深度 {depth})")
    print("=" * 60)
    
    expected = INITIAL_POSITION_PERFT.get(depth, 0)
    
    start = time.perf_counter()
    result = perft(INITIAL_FEN, depth)
    elapsed = time.perf_counter() - start
    
    nps = result / elapsed if elapsed > 0 else 0
    
    print(f"节点数: {result:,}")
    print(f"时间:   {elapsed:.3f}s")
    print(f"速度:   {nps:,.0f} nodes/s")
    
    if expected > 0:
        status = "✓ 正确" if result == expected else "✗ 错误"
        print(f"验证:   {status} (期望: {expected:,})")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Perft 测试框架")
    parser.add_argument("--quick", "-q", action="store_true",
                        help="快速测试 (只测试初始局面深度1-4)")
    parser.add_argument("--benchmark", "-b", type=int, nargs="?", const=5,
                        help="性能基准测试 (默认深度5)")
    parser.add_argument("--depth", "-d", type=int, default=None,
                        help="最大测试深度")
    parser.add_argument("--fen", type=str, default=None,
                        help="自定义FEN测试")
    
    args = parser.parse_args()
    
    try:
        if args.fen:
            print(f"自定义 FEN 测试: {args.fen}")
            print("-" * 40)
            max_d = args.depth or 4
            for d in range(1, max_d + 1):
                start = time.perf_counter()
                result = perft(args.fen, d)
                elapsed = time.perf_counter() - start
                print(f"深度 {d}: {result:,} [{elapsed:.3f}s]")
            return
        
        if args.quick:
            success = quick_test()
            sys.exit(0 if success else 1)
        
        if args.benchmark is not None:
            benchmark(args.benchmark)
            return
        
        success = run_all_tests(max_depth=args.depth)
        sys.exit(0 if success else 1)
        
    except FileNotFoundError as e:
        print(f"错误: {e}")
        print("请先运行 build_engine.py 编译引擎")
        sys.exit(1)
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
