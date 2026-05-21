"""
随机自战测试脚本 - 验证引擎断言检查

该脚本通过运行多局随机自战来测试引擎的断言检查：
1. 编译引擎（启用断言，不使用 NDEBUG）
2. 运行多局随机自战
3. 检查是否有断言失败
4. 输出测试结果

使用方法:
    python random_selfplay_test.py              # 运行默认10局测试
    python random_selfplay_test.py --games 50   # 运行50局测试
    python random_selfplay_test.py --depth 8    # 使用深度8搜索
    python random_selfplay_test.py --rebuild    # 强制重新编译
"""

import os
import sys
import subprocess
import argparse
import random
import time
import platform
from pathlib import Path

INITIAL_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def build_with_asserts(force: bool = False) -> bool:
    """
    编译引擎，启用断言检查（不定义 NDEBUG）
    
    Args:
        force: 是否强制重新编译
        
    Returns:
        True 表示编译成功
    """
    system = platform.system()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    src_file = os.path.join(script_dir, "engine_core.c")
    
    if system == "Windows":
        output_file = os.path.join(script_dir, "engine_core.dll")
        compiler = "gcc" if _find_compiler() == "gcc" else "cl"
        
        if compiler == "gcc":
            cmd = [
                "gcc", "-shared",
                "-g",
                "-o", output_file,
                src_file,
                "-lm",
            ]
        else:
            obj_file = os.path.join(script_dir, "engine_core.obj")
            cmd = [
                "cl", "/LD",
                "/Zi",
                f"/Fe{output_file}",
                f"/Fo{obj_file}",
                src_file,
            ]
    elif system == "Linux":
        output_file = os.path.join(script_dir, "engine_core.so")
        compiler = _find_compiler()
        cmd = [
            compiler, "-shared", "-fPIC",
            "-g",
            "-o", output_file,
            src_file,
            "-lm",
        ]
    elif system == "Darwin":
        output_file = os.path.join(script_dir, "engine_core.dylib")
        compiler = _find_compiler()
        cmd = [
            compiler, "-dynamiclib",
            "-g",
            "-o", output_file,
            src_file,
        ]
    else:
        print(f"不支持的操作系统: {system}")
        return False
    
    print(f"\n{'='*60}")
    print(f"编译引擎（启用断言检查）")
    print(f"平台: {system}")
    print(f"编译器: {compiler}")
    print(f"命令: {' '.join(cmd)}")
    print(f"{'='*60}\n")
    
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=script_dir)
    
    if result.returncode != 0:
        print("编译失败！")
        if result.stdout:
            print("stdout:\n" + result.stdout)
        if result.stderr:
            print("stderr:\n" + result.stderr)
        return False
    
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    
    if os.path.exists(output_file):
        print(f"编译成功: {output_file}")
        return True
    else:
        print("编译命令返回成功，但输出文件未生成")
        return False


def _find_compiler() -> str:
    """查找可用的 C 编译器"""
    import shutil
    if shutil.which("gcc"):
        return "gcc"
    if shutil.which("clang"):
        return "clang"
    if shutil.which("cl"):
        return "cl"
    return None


def run_random_game(engine, game_num: int, max_depth: int, time_limit: float) -> dict:
    """
    运行一局随机自战
    
    Args:
        engine: 引擎模块
        game_num: 游戏编号
        max_depth: 最大搜索深度
        time_limit: 时间限制
        
    Returns:
        游戏结果字典
    """
    import chess
    
    board = chess.Board()
    moves = []
    nodes_total = 0
    start_time = time.perf_counter()
    
    position_history = []
    
    while not board.is_game_over():
        try:
            fen = board.fen()
            hash_val = engine.compute_hash(fen)
            position_history.append(hash_val)
            
            uci_move, nodes = engine.search(
                fen,
                time_limit=time_limit,
                max_depth=max_depth,
                position_history=position_history,
                use_smp=False
            )
            
            move = chess.Move.from_uci(uci_move)
            if move not in board.legal_moves:
                return {
                    "game_num": game_num,
                    "status": "illegal_move",
                    "moves": len(moves),
                    "nodes": nodes_total,
                    "time": time.perf_counter() - start_time,
                    "error": f"非法走法: {uci_move}",
                }
            
            board.push(move)
            moves.append(uci_move)
            nodes_total += nodes
            
            if len(moves) > 500:
                return {
                    "game_num": game_num,
                    "status": "max_moves",
                    "moves": len(moves),
                    "nodes": nodes_total,
                    "time": time.perf_counter() - start_time,
                    "result": "draw",
                }
                
        except AssertionError as e:
            return {
                "game_num": game_num,
                "status": "assertion_failed",
                "moves": len(moves),
                "nodes": nodes_total,
                "time": time.perf_counter() - start_time,
                "error": str(e),
            }
        except Exception as e:
            return {
                "game_num": game_num,
                "status": "error",
                "moves": len(moves),
                "nodes": nodes_total,
                "time": time.perf_counter() - start_time,
                "error": str(e),
            }
    
    result = board.result()
    return {
        "game_num": game_num,
        "status": "completed",
        "moves": len(moves),
        "nodes": nodes_total,
        "time": time.perf_counter() - start_time,
        "result": result,
    }


def run_tests(num_games: int, max_depth: int, time_limit: float, rebuild: bool) -> bool:
    """
    运行所有测试
    
    Args:
        num_games: 游戏数量
        max_depth: 最大搜索深度
        time_limit: 时间限制
        rebuild: 是否强制重新编译
        
    Returns:
        True 表示所有测试通过
    """
    print("=" * 60)
    print("引擎自检断言测试 - 随机自战")
    print("=" * 60)
    
    if rebuild or not _check_engine_exists():
        if not build_with_asserts(force=rebuild):
            print("编译失败，无法运行测试")
            return False
    
    try:
        import engine_wrapper as engine
        engine.reload_library()
    except Exception as e:
        print(f"加载引擎失败: {e}")
        return False
    
    try:
        import chess
    except ImportError:
        print("请安装 python-chess: pip install chess")
        return False
    
    print(f"\n测试配置:")
    print(f"  游戏数量: {num_games}")
    print(f"  搜索深度: {max_depth}")
    print(f"  时间限制: {time_limit}s")
    print()
    
    results = []
    passed = 0
    failed = 0
    
    for i in range(1, num_games + 1):
        print(f"运行游戏 {i}/{num_games}...", end=" ", flush=True)
        result = run_random_game(engine, i, max_depth, time_limit)
        results.append(result)
        
        if result["status"] == "completed":
            passed += 1
            print(f"完成 ({result['result']}) - {result['moves']} 步, {result['nodes']} 节点, {result['time']:.2f}s")
        elif result["status"] == "assertion_failed":
            failed += 1
            print(f"断言失败! {result.get('error', '')}")
        else:
            failed += 1
            print(f"失败 ({result['status']}): {result.get('error', '未知错误')}")
    
    print()
    print("=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    print(f"总游戏数: {num_games}")
    print(f"完成: {passed}")
    print(f"失败: {failed}")
    
    if failed > 0:
        print("\n失败详情:")
        for r in results:
            if r["status"] != "completed":
                print(f"  游戏 {r['game_num']}: {r['status']} - {r.get('error', '未知')}")
    
    print("=" * 60)
    
    return failed == 0


def _check_engine_exists() -> bool:
    """检查引擎是否已编译"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    system = platform.system()
    
    if system == "Windows":
        dll_name = "engine_core.dll"
    elif system == "Linux":
        dll_name = "engine_core.so"
    elif system == "Darwin":
        dll_name = "engine_core.dylib"
    else:
        dll_name = "engine_core.so"
    
    return os.path.exists(os.path.join(script_dir, dll_name))


def quick_assertion_test():
    """
    快速断言测试 - 测试几个已知会触发搜索的位置
    """
    print("=" * 60)
    print("快速断言测试")
    print("=" * 60)
    
    if not build_with_asserts(force=True):
        print("编译失败")
        return False
    
    try:
        import engine_wrapper as engine
        engine.reload_library()
    except Exception as e:
        print(f"加载引擎失败: {e}")
        return False
    
    test_positions = [
        ("初始局面", INITIAL_FEN),
        ("意大利开局", "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 2 3"),
        ("西西里防御", "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"),
        ("复杂战术", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"),
        ("残局", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"),
    ]
    
    all_passed = True
    for name, fen in test_positions:
        print(f"\n测试: {name}")
        print(f"FEN: {fen}")
        try:
            move, score, nodes = engine.search_with_score(fen, time_limit=0.5, max_depth=6)
            print(f"  走法: {move}, 分数: {score}, 节点: {nodes}")
            print(f"  ✓ 通过")
        except AssertionError as e:
            print(f"  ✗ 断言失败: {e}")
            all_passed = False
        except Exception as e:
            print(f"  ✗ 错误: {e}")
            all_passed = False
    
    print()
    print("=" * 60)
    print(f"结果: {'全部通过' if all_passed else '有失败'}")
    print("=" * 60)
    
    return all_passed


def main():
    parser = argparse.ArgumentParser(description="引擎自检断言测试")
    parser.add_argument("--games", "-g", type=int, default=10,
                        help="游戏数量 (默认: 10)")
    parser.add_argument("--depth", "-d", type=int, default=6,
                        help="搜索深度 (默认: 6)")
    parser.add_argument("--time", "-t", type=float, default=0.1,
                        help="每步时间限制 (默认: 0.1s)")
    parser.add_argument("--rebuild", "-r", action="store_true",
                        help="强制重新编译")
    parser.add_argument("--quick", "-q", action="store_true",
                        help="快速测试模式")
    
    args = parser.parse_args()
    
    if args.quick:
        success = quick_assertion_test()
    else:
        success = run_tests(
            num_games=args.games,
            max_depth=args.depth,
            time_limit=args.time,
            rebuild=args.rebuild
        )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
