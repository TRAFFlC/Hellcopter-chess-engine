import sys
import time
import engine_wrapper


TEST_POSITIONS = [
    {
        "name": "初始局面",
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    },
    {
        "name": "意大利开局",
        "fen": "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
    },
    {
        "name": "中局-复杂局面",
        "fen": "r1bq1rk1/pppp1ppp/2n2n2/2b1p3/2B1P3/3P1N2/PPP2PPP/RNBQ1RK1 w - - 0 7",
    },
    {
        "name": "中局-战术局面",
        "fen": "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
    },
    {
        "name": "残局-王兵残局",
        "fen": "8/8/8/8/8/5k1p/5P1P/4K3 w - - 0 1",
    },
    {
        "name": "残局-王车残局",
        "fen": "8/8/8/8/8/5k2/8/4K2R w - - 0 1",
    },
]


def test_reproducibility(fen: str, time_limit: float, iterations: int = 3, use_smp: bool = False):
    results = []
    for i in range(iterations):
        move, score, nodes = engine_wrapper.search_with_score(
            fen, time_limit, 64, use_smp=use_smp
        )
        results.append((move, score, nodes))
    
    first = results[0]
    first_key = (first[0], first[1])
    all_same = all((r[0], r[1]) == first_key for r in results)
    return all_same, results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="引擎可复现性测试")
    parser.add_argument("--quick", action="store_true", help="快速测试模式")
    parser.add_argument("--iterations", type=int, default=5, help="重复次数")
    parser.add_argument("--time", type=float, default=0.5, help="搜索时间(秒)")
    args = parser.parse_args()

    time_limit = 0.2 if args.quick else args.time
    iterations = 3 if args.quick else args.iterations

    print("=" * 60)
    print("引擎可复现性测试")
    print("=" * 60)
    print(f"搜索时间: {time_limit}秒")
    print(f"重复次数: {iterations}")
    print()

    all_passed = True
    for pos in TEST_POSITIONS:
        print(f"测试: {pos['name']}")
        print(f"FEN: {pos['fen']}")
        
        passed, results = test_reproducibility(
            pos['fen'], time_limit, iterations, use_smp=False
        )
        
        if passed:
            print(f"  ✓ 通过 - 所有结果一致")
            print(f"    走法: {results[0][0]}, 分数: {results[0][1]}, 节点: {results[0][2]}")
        else:
            print(f"  ✗ 失败 - 结果不一致!")
            for i, r in enumerate(results):
                print(f"    第{i+1}次: 走法={r[0]}, 分数={r[1]}, 节点={r[2]}")
            all_passed = False
        print()

    print("=" * 60)
    if all_passed:
        print("结果: 全部通过")
    else:
        print("结果: 存在失败")
        sys.exit(1)
    print("=" * 60)


if __name__ == "__main__":
    main()
