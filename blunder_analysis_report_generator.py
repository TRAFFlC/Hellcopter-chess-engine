#!/usr/bin/env python3
"""
败着分析报告生成器 - 分析Hellcopter的对局败着并生成改进建议
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

def analyze_blunders(analysis_path):
    with open(analysis_path, encoding="utf-8") as f:
        games = json.load(f)
    
    stats = {
        "total_games": len(games),
        "big_blunders": [],
        "mistakes": [],
        "inaccuracies": [],
        "hellcopter_blunders": [],
    }
    
    for game in games:
        game_num = game.get("game_number", 0)
        hellcopter_color = game.get("hellcopter_color", "")
        opponent = game.get("opponent", "")
        result = game.get("result", "")
        
        for move in game.get("moves", []):
            if not move.get("is_hellcopter_move", False):
                continue
            
            error_type = move.get("error_type")
            if not error_type:
                continue
            
            blunder_info = {
                "game_num": game_num,
                "move_num": move.get("move_number", 0),
                "san_move": move.get("san_move", ""),
                "uci_move": move.get("uci_move", ""),
                "fen_before": move.get("fen_before", ""),
                "score_diff": move.get("score_diff", 0),
                "velvet_best_move": move.get("velvet_best_move", ""),
                "velvet_score": move.get("velvet_score", 0),
                "hellcopter_color": hellcopter_color,
                "opponent": opponent,
                "result": result,
            }
            
            if error_type == "重大失误":
                stats["big_blunders"].append(blunder_info)
            elif error_type == "失误":
                stats["mistakes"].append(blunder_info)
            elif error_type == "不准确":
                stats["inaccuracies"].append(blunder_info)
            
            stats["hellcopter_blunders"].append(blunder_info)
    
    return stats

def analyze_all_matches(match_records_dir):
    all_stats = {
        "total_games": 0,
        "big_blunders": [],
        "mistakes": [],
        "inaccuracies": [],
        "hellcopter_blunders": [],
        "by_opponent": defaultdict(lambda: {"games": 0, "big_blunders": 0, "mistakes": 0, "inaccuracies": 0}),
    }
    
    match_records_path = Path(match_records_dir)
    
    for analysis_file in match_records_path.glob("**/velvet_analysis.json"):
        try:
            stats = analyze_blunders(analysis_file)
            all_stats["total_games"] += stats["total_games"]
            all_stats["big_blunders"].extend(stats["big_blunders"])
            all_stats["mistakes"].extend(stats["mistakes"])
            all_stats["inaccuracies"].extend(stats["inaccuracies"])
            all_stats["hellcopter_blunders"].extend(stats["hellcopter_blunders"])
            
            for blunder in stats["hellcopter_blunders"]:
                opp = blunder.get("opponent", "unknown")
                all_stats["by_opponent"][opp]["games"] = stats["total_games"]
                if blunder.get("score_diff", 0) >= 300 or blunder.get("score_diff", 0) <= -300:
                    all_stats["by_opponent"][opp]["big_blunders"] += 1
                elif abs(blunder.get("score_diff", 0)) >= 100:
                    all_stats["by_opponent"][opp]["mistakes"] += 1
                elif abs(blunder.get("score_diff", 0)) >= 50:
                    all_stats["by_opponent"][opp]["inaccuracies"] += 1
        except Exception as e:
            print(f"Error analyzing {analysis_file}: {e}", file=sys.stderr)
    
    return all_stats

def generate_report(stats):
    report = []
    report.append("=" * 80)
    report.append("Hellcopter 败着分析报告")
    report.append("=" * 80)
    report.append("")
    
    report.append("## 总体统计")
    report.append(f"- 分析对局总数: {stats['total_games']}")
    report.append(f"- 重大失误 (>=300分): {len(stats['big_blunders'])}")
    report.append(f"- 失误 (100-300分): {len(stats['mistakes'])}")
    report.append(f"- 不准确 (50-100分): {len(stats['inaccuracies'])}")
    report.append(f"- Hellcopter败着总数: {len(stats['hellcopter_blunders'])}")
    report.append("")
    
    report.append("## 按对手统计")
    for opp, data in sorted(stats["by_opponent"].items(), key=lambda x: x[1]["big_blunders"], reverse=True):
        if data["big_blunders"] > 0 or data["mistakes"] > 0:
            report.append(f"- {opp}: 重大失误={data['big_blunders']}, 失误={data['mistakes']}, 不准确={data['inaccuracies']}")
    report.append("")
    
    report.append("## 分差最大的20个败着")
    sorted_blunders = sorted(stats["hellcopter_blunders"], key=lambda x: abs(x.get("score_diff", 0)), reverse=True)[:20]
    for i, blunder in enumerate(sorted_blunders, 1):
        report.append(f"\n{i}. 第{blunder['game_num']}局 第{blunder['move_num']}着 {blunder['san_move']}")
        report.append(f"   对手: {blunder['opponent']}, Hellcopter执: {blunder['hellcopter_color']}")
        report.append(f"   分数损失: {blunder['score_diff']}分 ({blunder['score_diff']/100:.1f}个兵)")
        report.append(f"   Velvet推荐: {blunder['velvet_best_move']}")
        report.append(f"   FEN: {blunder['fen_before']}")
    report.append("")
    
    report.append("## 败着模式分析")
    
    big_blunder_count = len(stats['big_blunders'])
    mistake_count = len(stats['mistakes'])
    inaccuracy_count = len(stats['inaccuracies'])
    total = big_blunder_count + mistake_count + inaccuracy_count
    
    if total > 0:
        report.append(f"- 重大失误占比: {big_blunder_count/total*100:.1f}%")
        report.append(f"- 失误占比: {mistake_count/total*100:.1f}%")
        report.append(f"- 不准确占比: {inaccuracy_count/total*100:.1f}%")
    report.append("")
    
    report.append("## 改进建议")
    report.append("")
    
    if big_blunder_count > 0:
        report.append("### 高优先级（重大失误）")
        report.append("1. 加强战术搜索深度，避免漏算关键变化")
        report.append("2. 改进静态评估函数，减少评估误差")
        report.append("3. 添加战术检测模块，识别潜在威胁")
        report.append("")
    
    if mistake_count > 0:
        report.append("### 中优先级（失误）")
        report.append("1. 优化搜索剪枝策略，避免剪掉重要变化")
        report.append("2. 改进位置评估，特别是王安全和兵结构")
        report.append("3. 增加中局到残局的过渡评估")
        report.append("")
    
    if inaccuracy_count > 0:
        report.append("### 低优先级（不准确）")
        report.append("1. 微调评估参数")
        report.append("2. 改进着法排序，提高搜索效率")
        report.append("")
    
    return "\n".join(report)

def main():
    match_records_dir = Path(__file__).parent / "match_records"
    stats = analyze_all_matches(match_records_dir)
    report = generate_report(stats)
    print(report)
    
    output_path = Path(__file__).parent / "blunder_analysis_report.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n报告已保存到: {output_path}")

if __name__ == "__main__":
    main()
