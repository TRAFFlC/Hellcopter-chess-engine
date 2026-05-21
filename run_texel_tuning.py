"""
Texel Tuning 完整流程脚本

整合安静局面生成、参数优化和配置输出的完整流程。

使用方法:
    python run_texel_tuning.py --generate 10000 --output tuned_config.json
    python run_texel_tuning.py --positions quiet_positions.json --base-config v1.5.0
    python run_texel_tuning.py --full --num-positions 10000 --iterations 5000
"""

import argparse
import json
import time
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from quiet_positions_generator import QuietPositionGenerator, save_positions, load_positions
from texel_tuner import TexelTuner, TuningConfig, save_tuning_result
from eval_param_manager import EvalParamManager, compare_params, print_param_comparison


def run_full_pipeline(
    num_positions: int = 10000,
    iterations: int = 1000,
    base_config: str = "v1.5.0",
    output_config: Optional[str] = None,
    positions_file: Optional[str] = None,
    K: float = 1.0,
    learning_rate: float = 0.01,
    batch_size: int = 1000,
    optimize_K: bool = False,
    seed: Optional[int] = None,
    quiet: bool = False
) -> Dict[str, Any]:
    """
    运行完整的 Texel Tuning 流程
    
    Args:
        num_positions: 要生成的局面数
        iterations: 优化迭代次数
        base_config: 基础配置版本
        output_config: 输出配置文件路径
        positions_file: 局面数据文件路径（如果已存在则跳过生成）
        K: sigmoid 缩放因子
        learning_rate: 学习率
        batch_size: 批次大小
        optimize_K: 是否优化 K 值
        seed: 随机种子
        quiet: 是否静默模式
    
    Returns:
        包含所有结果的字典
    """
    results = {
        "start_time": datetime.now().isoformat(),
        "config": {
            "num_positions": num_positions,
            "iterations": iterations,
            "base_config": base_config,
            "K": K,
            "learning_rate": learning_rate,
            "batch_size": batch_size,
        }
    }
    
    print("=" * 70)
    print("Texel Tuning 完整流程")
    print("=" * 70)
    print(f"目标局面数: {num_positions}")
    print(f"迭代次数: {iterations}")
    print(f"基础配置: {base_config}")
    print(f"K 值: {K}")
    print(f"学习率: {learning_rate}")
    print()
    
    step = 1
    
    if positions_file and Path(positions_file).exists():
        print(f"[步骤 {step}] 加载已有局面数据...")
        positions = load_positions(positions_file)
        results["positions_loaded"] = len(positions)
    else:
        print(f"[步骤 {step}] 生成安静局面...")
        start_time = time.perf_counter()
        
        generator = QuietPositionGenerator(seed=seed)
        
        def progress_cb(num_pos, num_games):
            if not quiet:
                elapsed = time.perf_counter() - start_time
                rate = num_pos / elapsed if elapsed > 0 else 0
                print(f"\r  已生成 {num_pos} 个局面 ({num_games} 局游戏, "
                      f"{rate:.1f} 局面/秒)", end="", flush=True)
        
        positions = generator.generate_positions_with_results(
            num_positions=num_positions,
            progress_callback=None if quiet else progress_cb
        )
        
        elapsed = time.perf_counter() - start_time
        if not quiet:
            print()
        
        print(f"  生成完成: {len(positions)} 个局面, 耗时 {elapsed:.2f} 秒")
        
        positions_file = positions_file or "quiet_positions.json"
        save_positions(positions, positions_file, {
            "seed": seed,
            "elapsed_seconds": elapsed,
            "statistics": generator.get_statistics()
        })
        
        results["positions_generated"] = len(positions)
        results["positions_file"] = positions_file
        results["generation_time"] = elapsed
    
    step += 1
    print()
    print(f"[步骤 {step}] 运行 Texel Tuning...")
    
    config = TuningConfig(
        K=K,
        learning_rate=learning_rate,
        batch_size=batch_size,
        iterations=iterations,
    )
    
    tuner = TexelTuner(config)
    tuner.set_positions(positions)
    
    if optimize_K:
        print("  优化 K 值...")
        best_K = tuner.optimize_K()
        results["optimized_K"] = best_K
    
    start_time = time.perf_counter()
    tuning_result = tuner.tune()
    elapsed = time.perf_counter() - start_time
    
    print(f"  优化完成: 耗时 {elapsed:.2f} 秒")
    
    results["tuning_time"] = elapsed
    results["initial_error"] = tuning_result.initial_error
    results["final_error"] = tuning_result.final_error
    results["error_reduction"] = (tuning_result.initial_error - tuning_result.final_error) / tuning_result.initial_error * 100
    results["iterations_completed"] = tuning_result.iterations_completed
    results["best_params"] = tuning_result.best_params
    
    tuning_result_file = f"tuning_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    save_tuning_result(tuning_result, tuning_result_file)
    results["tuning_result_file"] = tuning_result_file
    
    step += 1
    print()
    print(f"[步骤 {step}] 生成优化配置...")
    
    param_manager = EvalParamManager()
    
    try:
        original_params = param_manager.extract_params(f"{base_config}.json")
        
        tuned_params = {}
        piece_values = tuning_result.best_params.get("piece_values", {})
        for piece, value in piece_values.items():
            tuned_params[f"piece_{piece}"] = value
        
        eval_weights = tuning_result.best_params.get("eval_weights", {})
        for name, value in eval_weights.items():
            tuned_params[name] = value
        
        pawn_structure = tuning_result.best_params.get("pawn_structure", {})
        for name, value in pawn_structure.items():
            if name in ["doubled_pawn_penalty", "isolated_pawn_penalty"]:
                tuned_params[name] = -value
            else:
                tuned_params[name] = value
        
        comparison = compare_params(original_params, tuned_params)
        print_param_comparison(comparison)
        
    except FileNotFoundError:
        print(f"  警告: 未找到基础配置 {base_config}.json")
    
    if output_config is None:
        output_config = f"v1.6.0.json"
    
    output_path = Path(output_config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    new_config = {
        "version": output_path.stem,
        "base_version": base_config,
        "created_at": datetime.now().isoformat(),
        "description": f"Texel Tuning 优化结果 - {iterations} 次迭代",
        "parameters": {
            "piece_values": tuning_result.best_params.get("piece_values", {}),
            "eval_weights": {
                "bishop_pair_bonus": tuning_result.best_params.get("eval_weights", {}).get("bishop_pair_bonus", 30),
                "doubled_pawn_penalty": -tuning_result.best_params.get("pawn_structure", {}).get("doubled_pawn_penalty", 20),
                "isolated_pawn_penalty": -tuning_result.best_params.get("pawn_structure", {}).get("isolated_pawn_penalty", 15),
            }
        },
        "tuning_metadata": {
            "positions_used": len(positions),
            "iterations": tuning_result.iterations_completed,
            "initial_error": tuning_result.initial_error,
            "final_error": tuning_result.final_error,
            "error_reduction_percent": results["error_reduction"],
        }
    }
    
    with open(output_config, 'w', encoding='utf-8') as f:
        json.dump(new_config, f, indent=2, ensure_ascii=False)
    
    print(f"\n配置已保存到 {output_config}")
    results["output_config"] = output_config
    
    results["end_time"] = datetime.now().isoformat()
    
    print()
    print("=" * 70)
    print("流程完成")
    print("=" * 70)
    print(f"局面数: {len(positions)}")
    print(f"初始误差: {tuning_result.initial_error:.6f}")
    print(f"最终误差: {tuning_result.final_error:.6f}")
    print(f"误差降低: {results['error_reduction']:.2f}%")
    print(f"输出配置: {output_config}")
    print("=" * 70)
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Texel Tuning 完整流程")
    
    parser.add_argument("--full", "-f", action="store_true",
                       help="运行完整流程（生成局面 + 优化 + 输出）")
    parser.add_argument("--generate", "-g", type=int, default=None,
                       help="仅生成安静局面，指定数量")
    parser.add_argument("--tune", "-t", type=str, default=None,
                       help="仅运行优化，指定局面文件")
    
    parser.add_argument("--num-positions", "-n", type=int, default=10000,
                       help="局面数量 (默认: 10000)")
    parser.add_argument("--iterations", "-i", type=int, default=1000,
                       help="迭代次数 (默认: 1000)")
    parser.add_argument("--base-config", "-b", type=str, default="v1.5.0",
                       help="基础配置版本 (默认: v1.5.0)")
    parser.add_argument("--output", "-o", type=str, default=None,
                       help="输出配置文件路径")
    parser.add_argument("--positions-file", "-p", type=str, default=None,
                       help="局面数据文件路径")
    
    parser.add_argument("--K", type=float, default=1.0,
                       help="sigmoid 缩放因子 (默认: 1.0)")
    parser.add_argument("--learning-rate", "-lr", type=float, default=0.01,
                       help="学习率 (默认: 0.01)")
    parser.add_argument("--batch-size", type=int, default=1000,
                       help="批次大小 (默认: 1000)")
    parser.add_argument("--optimize-K", action="store_true",
                       help="优化 K 值")
    
    parser.add_argument("--seed", "-s", type=int, default=None,
                       help="随机种子")
    parser.add_argument("--quiet", "-q", action="store_true",
                       help="静默模式")
    
    args = parser.parse_args()
    
    if args.generate is not None:
        print("=" * 60)
        print("安静局面生成")
        print("=" * 60)
        
        generator = QuietPositionGenerator(seed=args.seed)
        start_time = time.perf_counter()
        
        positions = generator.generate_positions_with_results(
            num_positions=args.generate,
            progress_callback=None if args.quiet else lambda n, g: print(f"\r已生成 {n} 个局面", end="", flush=True)
        )
        
        elapsed = time.perf_counter() - start_time
        if not args.quiet:
            print()
        
        output_file = args.positions_file or "quiet_positions.json"
        save_positions(positions, output_file, {
            "seed": args.seed,
            "elapsed_seconds": elapsed,
            "statistics": generator.get_statistics()
        })
        
        print(f"生成完成: {len(positions)} 个局面, 耗时 {elapsed:.2f} 秒")
        return
    
    if args.tune:
        print("=" * 60)
        print("Texel Tuning 优化")
        print("=" * 60)
        
        config = TuningConfig(
            K=args.K,
            learning_rate=args.learning_rate,
            batch_size=args.batch_size,
            iterations=args.iterations,
        )
        
        tuner = TexelTuner(config)
        tuner.load_positions(args.tune)
        
        if args.optimize_K:
            tuner.optimize_K()
        
        result = tuner.tune()
        
        output_file = args.output or f"tuning_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_tuning_result(result, output_file)
        
        print(f"\n优化完成，结果保存到 {output_file}")
        return
    
    if args.full:
        results = run_full_pipeline(
            num_positions=args.num_positions,
            iterations=args.iterations,
            base_config=args.base_config,
            output_config=args.output,
            positions_file=args.positions_file,
            K=args.K,
            learning_rate=args.learning_rate,
            batch_size=args.batch_size,
            optimize_K=args.optimize_K,
            seed=args.seed,
            quiet=args.quiet
        )
        
        results_file = f"texel_tuning_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"\n完整结果保存到 {results_file}")
        return
    
    parser.print_help()


if __name__ == "__main__":
    main()
