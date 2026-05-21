#!/usr/bin/env python3
"""
PGN 统计分析工具 - 解析 PGN 文件并生成对弈统计

功能：
1. 解析 PGN 文件中的对局结果
2. 统计 Hellcopter 执白/执黑的胜负情况
3. 统计将杀类型（白方将杀黑方 / 黑方将杀白方）
4. 生成清晰的统计报告

使用方法:
    python pgn_stats.py --pgn match.pgn --engine Hellcopter
"""

import argparse
import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict

import chess
import chess.pgn


@dataclass
class GameStats:
    game_number: int
    white_player: str = ""
    black_player: str = ""
    result: str = "*"
    termination: str = ""
    hellcopter_color: Optional[str] = None
    hellcopter_won: Optional[bool] = None
    is_checkmate: bool = False
    winner_color: Optional[str] = None


@dataclass
class MatchStats:
    total_games: int = 0
    hellcopter_wins: int = 0
    hellcopter_losses: int = 0
    draws: int = 0
    
    white_games_wins: int = 0
    white_games_losses: int = 0
    white_games_draws: int = 0
    
    black_games_wins: int = 0
    black_games_losses: int = 0
    black_games_draws: int = 0
    
    white_checkmates_black: int = 0
    black_checkmates_white: int = 0
    
    games: List[GameStats] = field(default_factory=list)


def parse_pgn_file(pgn_path: Path, engine_name: str = "Hellcopter") -> MatchStats:
    stats = MatchStats()
    game_num = 0
    
    with open(pgn_path, encoding="latin-1") as f:
        while True:
            game = chess.pgn.read_game(f)
            if game is None:
                break
            
            game_num += 1
            game_stats = GameStats(game_number=game_num)
            
            white_player = game.headers.get("White", "")
            black_player = game.headers.get("Black", "")
            result = game.headers.get("Result", "*")
            termination = game.headers.get("Termination", "")
            
            game_stats.white_player = white_player
            game_stats.black_player = black_player
            game_stats.result = result
            game_stats.termination = termination
            
            if engine_name.lower() in white_player.lower():
                game_stats.hellcopter_color = "white"
            elif engine_name.lower() in black_player.lower():
                game_stats.hellcopter_color = "black"
            
            if result == "1-0":
                game_stats.winner_color = "white"
                if game_stats.hellcopter_color == "white":
                    game_stats.hellcopter_won = True
                elif game_stats.hellcopter_color == "black":
                    game_stats.hellcopter_won = False
            elif result == "0-1":
                game_stats.winner_color = "black"
                if game_stats.hellcopter_color == "black":
                    game_stats.hellcopter_won = True
                elif game_stats.hellcopter_color == "white":
                    game_stats.hellcopter_won = False
            elif result == "1/2-1/2":
                game_stats.hellcopter_won = None
            
            if termination.lower() == "normal" or "checkmate" in termination.lower():
                board = game.board()
                node = game
                while node.variations:
                    node = node.variation(0)
                    board.push(node.move)
                
                if board.is_checkmate():
                    game_stats.is_checkmate = True
                    if board.turn == chess.WHITE:
                        game_stats.winner_color = "black"
                    else:
                        game_stats.winner_color = "white"
            
            stats.games.append(game_stats)
            stats.total_games += 1
            
            if game_stats.hellcopter_won is True:
                stats.hellcopter_wins += 1
            elif game_stats.hellcopter_won is False:
                stats.hellcopter_losses += 1
            else:
                stats.draws += 1
            
            if game_stats.hellcopter_color == "white":
                if game_stats.hellcopter_won is True:
                    stats.white_games_wins += 1
                elif game_stats.hellcopter_won is False:
                    stats.white_games_losses += 1
                else:
                    stats.white_games_draws += 1
            elif game_stats.hellcopter_color == "black":
                if game_stats.hellcopter_won is True:
                    stats.black_games_wins += 1
                elif game_stats.hellcopter_won is False:
                    stats.black_games_losses += 1
                else:
                    stats.black_games_draws += 1
            
            if game_stats.is_checkmate:
                if game_stats.winner_color == "white":
                    stats.white_checkmates_black += 1
                elif game_stats.winner_color == "black":
                    stats.black_checkmates_white += 1
    
    return stats


def print_stats(stats: MatchStats, engine_name: str = "Hellcopter"):
    print("\n" + "=" * 60)
    print(f"对弈统计报告 - {engine_name}")
    print("=" * 60)
    
    print(f"\n总对局数: {stats.total_games}")
    print(f"胜-负-和: {stats.hellcopter_wins}-{stats.hellcopter_losses}-{stats.draws}")
    
    if stats.total_games > 0:
        win_rate = (stats.hellcopter_wins + 0.5 * stats.draws) / stats.total_games
        print(f"胜率: {win_rate:.2%}")
    
    print(f"\n{'='*60}")
    print("按执色统计")
    print(f"{'='*60}")
    
    print(f"\n执白对局:")
    white_total = stats.white_games_wins + stats.white_games_losses + stats.white_games_draws
    print(f"  胜-负-和: {stats.white_games_wins}-{stats.white_games_losses}-{stats.white_games_draws}")
    print(f"  总计: {white_total} 局")
    
    print(f"\n执黑对局:")
    black_total = stats.black_games_wins + stats.black_games_losses + stats.black_games_draws
    print(f"  胜-负-和: {stats.black_games_wins}-{stats.black_games_losses}-{stats.black_games_draws}")
    print(f"  总计: {black_total} 局")
    
    print(f"\n{'='*60}")
    print("将杀统计")
    print(f"{'='*60}")
    
    print(f"\n白方将杀黑方: {stats.white_checkmates_black} 次")
    print(f"  (白方获胜，黑方被将杀)")
    
    print(f"\n黑方将杀白方: {stats.black_checkmates_white} 次")
    print(f"  (黑方获胜，白方被将杀)")
    
    print(f"\n{'='*60}")
    print("详细对局列表")
    print(f"{'='*60}")
    
    for game in stats.games:
        result_str = ""
        if game.hellcopter_won is True:
            result_str = "胜"
        elif game.hellcopter_won is False:
            result_str = "负"
        else:
            result_str = "和"
        
        checkmate_str = " [将杀]" if game.is_checkmate else ""
        
        print(f"\n对局 {game.game_number}:")
        print(f"  白方: {game.white_player}")
        print(f"  黑方: {game.black_player}")
        print(f"  结果: {game.result} ({result_str}){checkmate_str}")
        print(f"  {engine_name}执: {game.hellcopter_color or '未知'}")


def save_stats_json(stats: MatchStats, output_path: str, engine_name: str = "Hellcopter"):
    total = stats.total_games
    win_rate = (stats.hellcopter_wins + 0.5 * stats.draws) / total if total > 0 else 0
    
    data = {
        "summary": {
            "total_games": total,
            "wins": stats.hellcopter_wins,
            "losses": stats.hellcopter_losses,
            "draws": stats.draws,
            "win_rate": round(win_rate, 4),
            "win_rate_percent": f"{win_rate:.2%}"
        },
        "by_color": {
            "white_games": {
                "wins": stats.white_games_wins,
                "losses": stats.white_games_losses,
                "draws": stats.white_games_draws,
                "total": stats.white_games_wins + stats.white_games_losses + stats.white_games_draws
            },
            "black_games": {
                "wins": stats.black_games_wins,
                "losses": stats.black_games_losses,
                "draws": stats.black_games_draws,
                "total": stats.black_games_wins + stats.black_games_losses + stats.black_games_draws
            }
        },
        "checkmate_stats": {
            "white_checkmates_black": stats.white_checkmates_black,
            "black_checkmates_white": stats.black_checkmates_white,
            "description": {
                "white_checkmates_black": "白方将杀黑方（白方获胜，黑方被将杀）",
                "black_checkmates_white": "黑方将杀白方（黑方获胜，白方被将杀）"
            }
        },
        "games": [
            {
                "game_number": g.game_number,
                "white_player": g.white_player,
                "black_player": g.black_player,
                "result": g.result,
                "hellcopter_color": g.hellcopter_color,
                "hellcopter_won": g.hellcopter_won,
                "is_checkmate": g.is_checkmate,
                "winner_color": g.winner_color
            }
            for g in stats.games
        ]
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"\n统计结果已保存到: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="PGN 统计分析工具 - 解析 PGN 文件并生成对弈统计"
    )
    parser.add_argument(
        "--pgn",
        required=True,
        help="PGN 文件路径"
    )
    parser.add_argument(
        "--engine",
        default="Hellcopter",
        help="引擎名称（默认 Hellcopter）"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出 JSON 文件路径（默认不保存）"
    )
    
    args = parser.parse_args()
    
    pgn_path = Path(args.pgn)
    if not pgn_path.exists():
        print(f"错误: PGN 文件不存在: {pgn_path}")
        return
    
    print(f"解析 PGN 文件: {pgn_path}")
    stats = parse_pgn_file(pgn_path, args.engine)
    
    print_stats(stats, args.engine)
    
    if args.output:
        save_stats_json(stats, args.output, args.engine)


if __name__ == "__main__":
    main()
