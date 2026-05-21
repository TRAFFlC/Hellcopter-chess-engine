#!/usr/bin/env python3
"""
搜索参数手动调优框架

功能：
1. 读取当前搜索参数
2. 支持调整 LMR 参数（div, min_depth）
3. 支持调整 Null Move R 值
4. 支持调整 Futility margin
5. 实现参数测试流程（短对弈测试）
6. 根据诊断报告建议调整残局阶段参数
7. 记录调参历史和结果
"""

import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
import shutil
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIGS_DIR = os.path.join(BASE_DIR, "configs")
TUNING_RECORDS_DIR = os.path.join(BASE_DIR, "tuning_records")


DEFAULT_SEARCH_PARAMS = {
    "null_move_reduction": 2,
    "null_move_min_depth": 3,
    "lmr_enabled": True,
    "lmr_min_depth": 3,
    "lmr_move_threshold": 2,
    "futility_enabled": True,
    "futility_margin_base": 100,
    "razoring_enabled": True,
    "razoring_margin": 250
}

PARAM_RANGES = {
    "null_move_reduction": {"min": 1, "max": 4, "step": 1, "desc": "空着裁剪深度减少量"},
    "null_move_min_depth": {"min": 2, "max": 6, "step": 1, "desc": "启用空着裁剪的最小深度"},
    "lmr_min_depth": {"min": 2, "max": 6, "step": 1, "desc": "启用LMR的最小深度"},
    "lmr_move_threshold": {"min": 1, "max": 8, "step": 1, "desc": "开始应用LMR的移动序号"},
    "futility_margin_base": {"min": 50, "max": 300, "step": 25, "desc": "无用裁剪基础边界"},
    "razoring_margin": {"min": 100, "max": 500, "step": 50, "desc": "剃刀裁剪边界"},
}

ENDGAME_TUNING_SUGGESTIONS = {
    "lmr_reduction": {
        "current": "reduction = 1 + (int)(log_depth * log_move_num / 2.5)",
        "suggestion": "残局阶段减少 LMR 削减量: if (is_endgame && reduction > 0) reduction -= 1",
        "status": "已实现",
        "impact": "残局阶段减少过度削减，提高搜索精度"
    },
    "futility_margin": {
        "current": "margin = futility_margin_base + depth * 50",
        "suggestion": "残局阶段放宽剪枝阈值: margin *= 1.5 或 margin *= 2",
        "status": "待实现",
        "impact": "残局阶段减少误剪枝，避免丢失关键着法"
    },
    "null_move": {
        "current": "nmr = NULL_MOVE_REDUCTION (默认2)",
        "suggestion": "残局阶段增加空着裁剪R值: nmr += 1 或禁用空着裁剪",
        "status": "已实现",
        "impact": "残局阶段减少空着裁剪的激进程度，避免zugzwang问题"
    },
    "razoring": {
        "current": "razor_margin = razoring_margin + (depth - 1) * 150",
        "suggestion": "残局阶段放宽剃刀裁剪阈值: razor_margin *= 1.5",
        "status": "已实现",
        "impact": "残局阶段减少误裁剪"
    }
}


class SearchParamTuner:
    def __init__(self, base_config: str = "v1.5.0"):
        self.base_config = base_config
        self.config_path = os.path.join(CONFIGS_DIR, f"{base_config}.json")
        self.current_config = self._load_config()
        self.tuning_history: List[Dict] = []
        self._ensure_records_dir()

    def _ensure_records_dir(self):
        os.makedirs(TUNING_RECORDS_DIR, exist_ok=True)

    def _load_config(self) -> Dict:
        if os.path.isfile(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"parameters": {"search_params": copy.deepcopy(DEFAULT_SEARCH_PARAMS)}}

    def _save_config(self, config: Dict, version: str) -> str:
        config_path = os.path.join(CONFIGS_DIR, f"{version}.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return config_path

    def get_search_params(self) -> Dict:
        return self.current_config.get("parameters", {}).get("search_params", DEFAULT_SEARCH_PARAMS)

    def display_current_params(self):
        params = self.get_search_params()
        print("\n" + "=" * 60)
        print("当前搜索参数")
        print("=" * 60)
        print(f"配置版本: {self.base_config}")
        print("-" * 40)
        
        for key, value in params.items():
            if key in PARAM_RANGES:
                range_info = PARAM_RANGES[key]
                print(f"  {key}: {value}")
                print(f"    范围: [{range_info['min']}, {range_info['max']}], 步长: {range_info['step']}")
                print(f"    说明: {range_info['desc']}")
            else:
                print(f"  {key}: {value}")
        print()

    def display_endgame_suggestions(self):
        print("\n" + "=" * 60)
        print("残局阶段参数调整建议")
        print("=" * 60)
        
        for param, info in ENDGAME_TUNING_SUGGESTIONS.items():
            status_icon = "✓" if info["status"] == "已实现" else "○"
            print(f"\n[{status_icon}] {param}")
            print(f"  当前实现: {info['current']}")
            print(f"  建议调整: {info['suggestion']}")
            print(f"  状态: {info['status']}")
            print(f"  影响: {info['impact']}")
        print()

    def set_param(self, param_name: str, value: Any) -> bool:
        if "parameters" not in self.current_config:
            self.current_config["parameters"] = {}
        if "search_params" not in self.current_config["parameters"]:
            self.current_config["parameters"]["search_params"] = copy.deepcopy(DEFAULT_SEARCH_PARAMS)
        
        if param_name not in DEFAULT_SEARCH_PARAMS:
            print(f"错误: 未知参数 '{param_name}'")
            print(f"可用参数: {list(DEFAULT_SEARCH_PARAMS.keys())}")
            return False
        
        if param_name in PARAM_RANGES:
            range_info = PARAM_RANGES[param_name]
            if not (range_info["min"] <= value <= range_info["max"]):
                print(f"警告: 值 {value} 超出建议范围 [{range_info['min']}, {range_info['max']}]")
        
        old_value = self.current_config["parameters"]["search_params"].get(param_name)
        self.current_config["parameters"]["search_params"][param_name] = value
        
        print(f"参数已更新: {param_name}: {old_value} -> {value}")
        return True

    def generate_test_values(self, param_name: str) -> List[Any]:
        if param_name not in PARAM_RANGES:
            return [self.get_search_params().get(param_name)]
        
        range_info = PARAM_RANGES[param_name]
        values = []
        v = range_info["min"]
        while v <= range_info["max"]:
            values.append(v)
            v += range_info["step"]
        return values

    def run_match_test(self, config: Dict, opponent: str = "shallowblue", 
                       rounds: int = 10, time_control: str = "10+0.1") -> Dict:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        test_version = f"tune_test_{timestamp}"
        
        test_config = copy.deepcopy(config)
        test_config["version"] = test_version
        test_config["description"] = f"Search parameter tuning test - {timestamp}"
        
        config_path = self._save_config(test_config, test_version)
        
        print(f"\n运行测试: {test_version}")
        print(f"对手: {opponent}, 回合: {rounds}, 时间控制: {time_control}")
        
        try:
            result = subprocess.run(
                [sys.executable, os.path.join(BASE_DIR, "run_match.py"),
                 "--opponent", opponent,
                 "--rounds", str(rounds),
                 "--tc", time_control,
                 "--config", test_version],
                capture_output=True,
                text=True,
                cwd=BASE_DIR,
                timeout=600
            )
            
            output = result.stdout + result.stderr
            wins, losses, draws = self._parse_match_result(output)
            
            if wins + losses + draws > 0:
                total = wins + losses + draws
                win_rate = (wins + 0.5 * draws) / total
                elo_diff = self._calculate_elo(wins, losses, draws)
            else:
                win_rate = 0.5
                elo_diff = 0.0
                wins = losses = draws = 0
            
            return {
                "version": test_version,
                "opponent": opponent,
                "rounds": rounds,
                "time_control": time_control,
                "wins": wins,
                "losses": losses,
                "draws": draws,
                "win_rate": win_rate,
                "elo_diff": elo_diff,
                "success": True
            }
            
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "测试超时"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _parse_match_result(self, output: str) -> Tuple[int, int, int]:
        import re
        pattern = re.compile(r"Score of\s+.+?:\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)")
        for line in output.splitlines():
            m = pattern.search(line)
            if m:
                return int(m.group(1)), int(m.group(2)), int(m.group(3))
        return 0, 0, 0

    def _calculate_elo(self, wins: int, losses: int, draws: int) -> float:
        total = wins + losses + draws
        if total == 0:
            return 0.0
        score = (wins + 0.5 * draws) / total
        if score <= 0 or score >= 1:
            return 0.0
        import math
        return -400 * math.log10((1 - score) / score)

    def tune_single_param(self, param_name: str, opponent: str = "shallowblue",
                          rounds: int = 10, time_control: str = "10+0.1") -> Dict:
        print(f"\n{'='*60}")
        print(f"单参数调优: {param_name}")
        print(f"{'='*60}")
        
        if param_name not in PARAM_RANGES:
            print(f"错误: 参数 '{param_name}' 不支持调优")
            return {"success": False, "error": "参数不支持调优"}
        
        test_values = self.generate_test_values(param_name)
        current_value = self.get_search_params().get(param_name)
        
        print(f"当前值: {current_value}")
        print(f"测试值: {test_values}")
        
        results = []
        baseline_config = copy.deepcopy(self.current_config)
        
        for value in test_values:
            test_config = copy.deepcopy(baseline_config)
            test_config["parameters"]["search_params"][param_name] = value
            
            print(f"\n测试 {param_name} = {value}")
            result = self.run_match_test(test_config, opponent, rounds, time_control)
            
            if result["success"]:
                results.append({
                    "param_name": param_name,
                    "value": value,
                    "wins": result["wins"],
                    "losses": result["losses"],
                    "draws": result["draws"],
                    "win_rate": result["win_rate"],
                    "elo_diff": result["elo_diff"]
                })
                print(f"  结果: {result['wins']}W-{result['losses']}L-{result['draws']}D")
                print(f"  胜率: {result['win_rate']:.2%}, Elo差: {result['elo_diff']:+.1f}")
            else:
                print(f"  测试失败: {result.get('error', '未知错误')}")
        
        if results:
            best = max(results, key=lambda r: r["win_rate"])
            print(f"\n最佳结果: {param_name} = {best['value']}")
            print(f"  胜率: {best['win_rate']:.2%}, Elo差: {best['elo_diff']:+.1f}")
            
            self._save_tuning_record({
                "type": "single_param",
                "param_name": param_name,
                "baseline_value": current_value,
                "best_value": best["value"],
                "all_results": results,
                "timestamp": datetime.now().isoformat()
            })
            
            return {
                "success": True,
                "best_value": best["value"],
                "best_win_rate": best["win_rate"],
                "best_elo": best["elo_diff"],
                "all_results": results
            }
        
        return {"success": False, "error": "无有效测试结果"}

    def tune_endgame_params(self, opponent: str = "shallowblue", rounds: int = 10,
                           time_control: str = "10+0.1") -> Dict:
        print(f"\n{'='*60}")
        print("残局阶段参数调优")
        print(f"{'='*60}")
        
        self.display_endgame_suggestions()
        
        endgame_params = {
            "null_move_reduction": [2, 3],
            "lmr_min_depth": [3, 4, 5],
            "futility_margin_base": [100, 150, 200],
        }
        
        all_results = {}
        baseline_config = copy.deepcopy(self.current_config)
        
        for param_name, test_values in endgame_params.items():
            print(f"\n调优参数: {param_name}")
            param_results = []
            
            for value in test_values:
                test_config = copy.deepcopy(baseline_config)
                test_config["parameters"]["search_params"][param_name] = value
                
                print(f"  测试 {param_name} = {value}...", end=" ", flush=True)
                result = self.run_match_test(test_config, opponent, rounds, time_control)
                
                if result["success"]:
                    param_results.append({
                        "value": value,
                        "win_rate": result["win_rate"],
                        "elo_diff": result["elo_diff"],
                        "wins": result["wins"],
                        "losses": result["losses"],
                        "draws": result["draws"]
                    })
                    print(f"{result['win_rate']:.2%} ({result['elo_diff']:+.1f} Elo)")
                else:
                    print("失败")
            
            if param_results:
                best = max(param_results, key=lambda r: r["win_rate"])
                all_results[param_name] = {
                    "best_value": best["value"],
                    "best_win_rate": best["win_rate"],
                    "all_results": param_results
                }
                print(f"  最佳: {param_name} = {best['value']} (胜率 {best['win_rate']:.2%})")
        
        self._save_tuning_record({
            "type": "endgame_params",
            "results": all_results,
            "timestamp": datetime.now().isoformat()
        })
        
        return {"success": True, "results": all_results}

    def compare_configs(self, config_versions: List[str], opponent: str = "shallowblue",
                       rounds: int = 10, time_control: str = "10+0.1") -> Dict:
        print(f"\n{'='*60}")
        print("配置对比测试")
        print(f"{'='*60}")
        
        results = []
        
        for version in config_versions:
            config_path = os.path.join(CONFIGS_DIR, f"{version}.json")
            if not os.path.isfile(config_path):
                print(f"警告: 配置 {version} 不存在，跳过")
                continue
            
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            
            print(f"\n测试配置: {version}")
            result = self.run_match_test(config, opponent, rounds, time_control)
            
            if result["success"]:
                results.append({
                    "version": version,
                    "wins": result["wins"],
                    "losses": result["losses"],
                    "draws": result["draws"],
                    "win_rate": result["win_rate"],
                    "elo_diff": result["elo_diff"]
                })
                print(f"  结果: {result['wins']}W-{result['losses']}L-{result['draws']}D")
                print(f"  胜率: {result['win_rate']:.2%}, Elo差: {result['elo_diff']:+.1f}")
        
        if results:
            print(f"\n{'='*60}")
            print("对比结果汇总")
            print(f"{'='*60}")
            print(f"{'配置':<15} {'胜率':>10} {'Elo差':>10} {'战绩':>15}")
            print("-" * 50)
            for r in sorted(results, key=lambda x: x["win_rate"], reverse=True):
                record = f"{r['wins']}W-{r['losses']}L-{r['draws']}D"
                print(f"{r['version']:<15} {r['win_rate']:>10.2%} {r['elo_diff']:>+10.1f} {record:>15}")
        
        return {"success": True, "results": results}

    def _save_tuning_record(self, record: Dict):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        record_type = record.get("type", "unknown")
        filename = f"tuning_{record_type}_{timestamp}.json"
        filepath = os.path.join(TUNING_RECORDS_DIR, filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        
        print(f"\n调优记录已保存: {filename}")

    def show_tuning_history(self, limit: int = 10):
        print(f"\n{'='*60}")
        print("调优历史记录")
        print(f"{'='*60}")
        
        if not os.path.isdir(TUNING_RECORDS_DIR):
            print("暂无调优记录")
            return
        
        records = []
        for filename in os.listdir(TUNING_RECORDS_DIR):
            if filename.endswith(".json"):
                filepath = os.path.join(TUNING_RECORDS_DIR, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        record = json.load(f)
                    records.append((filename, record))
                except:
                    pass
        
        records.sort(key=lambda x: x[1].get("timestamp", ""), reverse=True)
        
        if not records:
            print("暂无调优记录")
            return
        
        for filename, record in records[:limit]:
            print(f"\n文件: {filename}")
            print(f"类型: {record.get('type', 'unknown')}")
            print(f"时间: {record.get('timestamp', 'unknown')}")
            
            if record["type"] == "single_param":
                print(f"参数: {record.get('param_name')}")
                print(f"基线值: {record.get('baseline_value')}")
                print(f"最佳值: {record.get('best_value')}")
            elif record["type"] == "endgame_params":
                for param, result in record.get("results", {}).items():
                    print(f"  {param}: 最佳值={result.get('best_value')}, 胜率={result.get('best_win_rate', 0):.2%}")

    def export_optimized_config(self, version: str, description: str = "") -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_version = version or f"v_tuned_{timestamp}"
        
        new_config = copy.deepcopy(self.current_config)
        new_config["version"] = new_version
        new_config["base_version"] = self.base_config
        new_config["created_at"] = datetime.now().isoformat()
        new_config["description"] = description or f"手动调优配置 - 基于 {self.base_config}"
        
        config_path = self._save_config(new_config, new_version)
        print(f"\n配置已导出: {config_path}")
        print(f"版本: {new_version}")
        
        return config_path


def interactive_mode(tuner: SearchParamTuner):
    print("\n" + "=" * 60)
    print("搜索参数调优 - 交互模式")
    print("=" * 60)
    
    while True:
        print("\n可用命令:")
        print("  1. show        - 显示当前参数")
        print("  2. suggest     - 显示残局调优建议")
        print("  3. set <参数> <值> - 设置参数值")
        print("  4. tune <参数> - 单参数调优")
        print("  5. endgame     - 残局参数调优")
        print("  6. compare <v1> <v2> ... - 对比多个配置")
        print("  7. history     - 查看调优历史")
        print("  8. export <版本> - 导出当前配置")
        print("  9. quit        - 退出")
        
        try:
            cmd = input("\n> ").strip().split()
        except EOFError:
            break
        
        if not cmd:
            continue
        
        action = cmd[0].lower()
        
        if action == "show":
            tuner.display_current_params()
        
        elif action == "suggest":
            tuner.display_endgame_suggestions()
        
        elif action == "set" and len(cmd) >= 3:
            param_name = cmd[1]
            try:
                value = int(cmd[2]) if cmd[2].isdigit() else cmd[2].lower() == "true"
                tuner.set_param(param_name, value)
            except ValueError:
                print(f"错误: 无效的值 '{cmd[2]}'")
        
        elif action == "tune" and len(cmd) >= 2:
            param_name = cmd[1]
            rounds = int(cmd[2]) if len(cmd) >= 3 else 10
            tuner.tune_single_param(param_name, rounds=rounds)
        
        elif action == "endgame":
            rounds = int(cmd[1]) if len(cmd) >= 2 else 10
            tuner.tune_endgame_params(rounds=rounds)
        
        elif action == "compare" and len(cmd) >= 2:
            versions = cmd[1:]
            tuner.compare_configs(versions)
        
        elif action == "history":
            tuner.show_tuning_history()
        
        elif action == "export":
            version = cmd[1] if len(cmd) >= 2 else None
            tuner.export_optimized_config(version)
        
        elif action in ("quit", "exit", "q"):
            print("再见!")
            break
        
        else:
            print(f"未知命令: {action}")


def main():
    parser = argparse.ArgumentParser(
        description="搜索参数手动调优工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python search_tuner.py show                    # 显示当前参数
  python search_tuner.py tune lmr_min_depth      # 调优 LMR 最小深度
  python search_tuner.py endgame                 # 残局参数调优
  python search_tuner.py compare v1.4.0 v1.5.0   # 对比两个配置
  python search_tuner.py interactive             # 进入交互模式
        """
    )
    
    parser.add_argument("action", nargs="?", default="show",
                       help="操作: show, suggest, tune, endgame, compare, history, export, interactive")
    parser.add_argument("--config", default="v1.5.0", help="基础配置版本")
    parser.add_argument("--param", help="要调优的参数名")
    parser.add_argument("--value", help="参数值")
    parser.add_argument("--opponent", default="shallowblue", help="测试对手")
    parser.add_argument("--rounds", type=int, default=10, help="测试回合数")
    parser.add_argument("--tc", default="10+0.1", help="时间控制")
    parser.add_argument("--versions", nargs="+", help="要对比的配置版本")
    
    args = parser.parse_args()
    
    tuner = SearchParamTuner(base_config=args.config)
    
    if args.action == "show":
        tuner.display_current_params()
    
    elif args.action == "suggest":
        tuner.display_endgame_suggestions()
    
    elif args.action == "tune":
        if args.param:
            tuner.tune_single_param(args.param, opponent=args.opponent,
                                   rounds=args.rounds, time_control=args.tc)
        else:
            print("错误: 请指定要调优的参数 (--param)")
    
    elif args.action == "endgame":
        tuner.tune_endgame_params(opponent=args.opponent, rounds=args.rounds,
                                 time_control=args.tc)
    
    elif args.action == "compare":
        if args.versions:
            tuner.compare_configs(args.versions, opponent=args.opponent,
                                 rounds=args.rounds, time_control=args.tc)
        else:
            print("错误: 请指定要对比的配置版本 (--versions)")
    
    elif args.action == "history":
        tuner.show_tuning_history()
    
    elif args.action == "export":
        tuner.export_optimized_config(args.value or "")
    
    elif args.action == "interactive":
        interactive_mode(tuner)
    
    elif args.action == "set":
        if args.param and args.value:
            try:
                value = int(args.value) if args.value.isdigit() else args.value.lower() == "true"
                tuner.set_param(args.param, value)
            except ValueError:
                print(f"错误: 无效的值 '{args.value}'")
        else:
            print("错误: 请指定参数名 (--param) 和值 (--value)")
    
    else:
        print(f"未知操作: {args.action}")
        parser.print_help()


if __name__ == "__main__":
    main()
