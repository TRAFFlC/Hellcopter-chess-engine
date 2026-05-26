"""
NPS 性能基准测试 - 诊断 Hellcopter v1.7.0 的 NPS 性能问题

测试不同线程数下的 NPS（每秒节点数），并与理论值对比。

使用方法:
    python nps_benchmark.py                    # 运行完整测试
    python nps_benchmark.py --threads 1,2,4    # 指定测试的线程数
    python nps_benchmark.py --quick            # 快速测试
"""

import ctypes
import os
import sys
import time
import json
import argparse
import tempfile
import shutil
from pathlib import Path

INITIAL_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

TEST_POSITIONS = [
    ("初始局面", INITIAL_FEN),
    ("中局", "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"),
    ("残局", "8/8/8/8/8/5k2/8/4k2r w - - 0 1"),
    ("复杂战术", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"),
]


class Move(ctypes.Structure):
    _fields_ = [
        ("from_sq", ctypes.c_int),
        ("to_sq", ctypes.c_int),
        ("promotion", ctypes.c_int),
        ("capture", ctypes.c_int),
        ("score", ctypes.c_int),
    ]


def get_dll_path() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, "engine_core.dll")


def load_engine(dll_path: str):
    engine = ctypes.CDLL(dll_path, winmode=0)
    
    engine.find_best_move_c.argtypes = [
        ctypes.c_char_p, ctypes.c_double, ctypes.c_double, ctypes.c_double,
        ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint64),
        ctypes.c_int
    ]
    engine.find_best_move_c.restype = Move
    
    engine.find_best_move_smp.argtypes = [
        ctypes.c_char_p, ctypes.c_double, ctypes.c_double, ctypes.c_double,
        ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint64),
        ctypes.c_int
    ]
    engine.find_best_move_smp.restype = Move
    
    engine.load_params_from_file.argtypes = [ctypes.c_char_p]
    engine.load_params_from_file.restype = ctypes.c_int
    
    return engine


def create_temp_config(base_config_path: str, num_threads: int, output_path: str):
    with open(base_config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    if "parameters" not in config:
        config["parameters"] = {}
    if "threading" not in config["parameters"]:
        config["parameters"]["threading"] = {}
    
    config["parameters"]["threading"]["enabled"] = True
    config["parameters"]["threading"]["num_threads"] = num_threads
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)


def run_single_test(engine, fen: str, time_limit: float, use_smp: bool = False) -> tuple[int, float]:
    nodes = ctypes.c_int()
    game_history = (ctypes.c_uint64 * 256)()
    
    start = time.perf_counter()
    if use_smp:
        move = engine.find_best_move_smp(
            fen.encode('utf-8'),
            ctypes.c_double(time_limit),
            ctypes.c_double(0.0),
            ctypes.c_double(0.0),
            ctypes.c_int(0),
            ctypes.c_int(0),
            ctypes.c_int(100),
            ctypes.byref(nodes),
            game_history,
            ctypes.c_int(0)
        )
    else:
        move = engine.find_best_move_c(
            fen.encode('utf-8'),
            ctypes.c_double(time_limit),
            ctypes.c_double(0.0),
            ctypes.c_double(0.0),
            ctypes.c_int(0),
            ctypes.c_int(0),
            ctypes.c_int(100),
            ctypes.byref(nodes),
            game_history,
            ctypes.c_int(0)
        )
    elapsed = time.perf_counter() - start
    
    return nodes.value, elapsed


def benchmark_nps(engine, num_threads: int, time_limit: float = 5.0, 
                  use_smp: bool = True, warmup: bool = True) -> dict:
    results = {}
    
    if warmup:
        run_single_test(engine, INITIAL_FEN, 1.0, use_smp)
    
    for name, fen in TEST_POSITIONS:
        total_nodes = 0
        total_time = 0.0
        
        for _ in range(3):
            nodes, elapsed = run_single_test(engine, fen, time_limit, use_smp)
            total_nodes += nodes
            total_time += elapsed
        
        avg_nodes = total_nodes // 3
        avg_time = total_time / 3
        nps = int(avg_nodes / avg_time) if avg_time > 0 else 0
        
        results[name] = {
            "nodes": avg_nodes,
            "time": avg_time,
            "nps": nps
        }
    
    return results


def main():
    parser = argparse.ArgumentParser(description="NPS 性能基准测试")
    parser.add_argument("--threads", "-t", type=str, default="1,2,4",
                       help="测试的线程数，逗号分隔 (默认: 1,2,4)")
    parser.add_argument("--time", type=float, default=5.0,
                       help="每次搜索的时间限制 (秒, 默认: 5.0)")
    parser.add_argument("--quick", "-q", action="store_true",
                       help="快速测试模式 (1秒)")
    parser.add_argument("--config", type=str, default="configs/v1.7.0.json",
                       help="基础配置文件路径")
    
    args = parser.parse_args()
    
    if args.quick:
        args.time = 1.0
    
    thread_counts = [int(t.strip()) for t in args.threads.split(",")]
    
    dll_path = get_dll_path()
    if not os.path.exists(dll_path):
        print(f"错误: 引擎 DLL 未找到: {dll_path}")
        print("请先运行 build_engine.py 编译引擎")
        sys.exit(1)
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_config_path = os.path.join(script_dir, args.config)
    if not os.path.exists(base_config_path):
        print(f"错误: 配置文件未找到: {base_config_path}")
        sys.exit(1)
    
    print("=" * 70)
    print("Hellcopter NPS 性能基准测试")
    print("=" * 70)
    print(f"配置文件: {args.config}")
    print(f"测试线程数: {thread_counts}")
    print(f"每次搜索时间: {args.time}秒")
    print("=" * 70)
    
    all_results = {}
    
    for num_threads in thread_counts:
        print(f"\n{'─' * 70}")
        print(f"测试 {num_threads} 线程")
        print(f"{'─' * 70}")
        
        temp_config = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        temp_config_path = temp_config.name
        temp_config.close()
        
        try:
            create_temp_config(base_config_path, num_threads, temp_config_path)
            
            engine = load_engine(dll_path)
            result = engine.load_params_from_file(temp_config_path.encode('utf-8'))
            
            use_smp = num_threads > 1
            results = benchmark_nps(engine, num_threads, args.time, use_smp)
            
            all_results[num_threads] = results
            
            for name, data in results.items():
                print(f"  {name}:")
                print(f"    节点数: {data['nodes']:,}")
                print(f"    时间:   {data['time']:.2f}s")
                print(f"    NPS:    {data['nps']:,}")
            
            avg_nps = sum(r['nps'] for r in results.values()) // len(results)
            print(f"\n  平均 NPS: {avg_nps:,}")
            
            del engine
            
        finally:
            if os.path.exists(temp_config_path):
                os.remove(temp_config_path)
    
    print("\n" + "=" * 70)
    print("性能分析报告")
    print("=" * 70)
    
    baseline_nps = None
    for num_threads in thread_counts:
        if num_threads == 1:
            results = all_results[num_threads]
            baseline_nps = sum(r['nps'] for r in results.values()) // len(results)
            break
    
    if baseline_nps is None:
        baseline_nps = all_results[thread_counts[0]]
        baseline_nps = sum(r['nps'] for r in baseline_nps.values()) // len(baseline_nps)
    
    print(f"\n{'线程数':<8} {'平均 NPS':>15} {'扩展效率':>12} {'理论 NPS':>15} {'效率比':>10}")
    print("─" * 70)
    
    theoretical_nps_4t = baseline_nps * 4 * 0.75
    
    for num_threads in thread_counts:
        results = all_results[num_threads]
        avg_nps = sum(r['nps'] for r in results.values()) // len(results)
        
        if num_threads == 1:
            efficiency = 1.0
            theoretical_nps = baseline_nps
        else:
            efficiency = avg_nps / baseline_nps
            theoretical_nps = baseline_nps * num_threads * 0.75
        
        efficiency_ratio = avg_nps / theoretical_nps if theoretical_nps > 0 else 0
        
        print(f"{num_threads:<8} {avg_nps:>15,} {efficiency:>12.2f}x {theoretical_nps:>15,} {efficiency_ratio:>10.1%}")
    
    print("\n" + "=" * 70)
    print("诊断结论")
    print("=" * 70)
    
    if 4 in all_results:
        results_4t = all_results[4]
        avg_nps_4t = sum(r['nps'] for r in results_4t.values()) // len(results_4t)
        
        theoretical_4t = baseline_nps * 4 * 0.75
        actual_efficiency = avg_nps_4t / baseline_nps
        
        print(f"\n单线程基准 NPS: {baseline_nps:,}")
        print(f"4线程实际 NPS:  {avg_nps_4t:,}")
        print(f"4线程理论 NPS:  {int(theoretical_4t):,} (假设75%并行效率)")
        print(f"实际扩展效率:   {actual_efficiency:.2f}x")
        
        if avg_nps_4t < theoretical_4t * 0.8:
            print("\n⚠️  性能警告:")
            print(f"   4线程 NPS 低于理论值的80%")
            print(f"   可能存在以下瓶颈:")
            print(f"   - 线程同步开销过大")
            print(f"   - 共享数据结构竞争")
            print(f"   - 主线程等待时间过长")
            print(f"   - 搜索树分割不均衡")
        elif avg_nps_4t < theoretical_4t:
            print("\n✓ 性能正常:")
            print(f"   多线程扩展效率在预期范围内")
        else:
            print("\n✓ 性能优秀:")
            print(f"   多线程扩展效率超出预期")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
