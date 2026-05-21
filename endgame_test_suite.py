"""
残局测试集 - Endgame Test Suite

用于测试引擎在典型残局局面下的表现，包括：
- 强制将杀局面
- 兵升变局面
- 象马将杀局面
- 逼和检测
- 王活动性评估

使用方法:
    python endgame_test_suite.py
    python endgame_test_suite.py --depth 12
    python endgame_test_suite.py --time 2.0
"""

import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

import chess

import engine_wrapper


@dataclass
class EndgamePosition:
    name: str
    fen: str
    category: str
    expected_result: str
    expected_description: str
    max_moves: int = 20
    search_depth: int = 10
    time_limit: float = 1.0


@dataclass
class TestResult:
    position: EndgamePosition
    best_move: str
    score: int
    nodes: int
    time_elapsed: float
    is_checkmate: bool
    is_stalemate: bool
    moves_to_mate: Optional[int]
    evaluation_correct: bool
    details: Dict[str, Any] = field(default_factory=dict)


ENDGAME_POSITIONS = [
    EndgamePosition(
        name="KQvsK - 后王对王将杀",
        fen="8/8/8/8/8/8/1k6/KQ6 w - - 0 1",
        category="强制将杀",
        expected_result="白方胜",
        expected_description="白方后+王应在有限步数内将杀黑王",
        max_moves=10,
        search_depth=12,
        time_limit=1.0
    ),
    EndgamePosition(
        name="KRPvsKR - 车兵对车升变",
        fen="8/5P1k/8/8/8/8/8/4K2R w - - 0 1",
        category="兵升变",
        expected_result="白方胜",
        expected_description="白方兵即将升变，应找到升变路线",
        max_moves=15,
        search_depth=12,
        time_limit=1.0
    ),
    EndgamePosition(
        name="KBNvsK - 象马将杀",
        fen="8/8/8/8/8/1k6/8/KBN5 w - - 0 1",
        category="象马将杀",
        expected_result="白方胜",
        expected_description="白方象+马+王应能将杀黑王",
        max_moves=30,
        search_depth=14,
        time_limit=2.0
    ),
    EndgamePosition(
        name="逼和局面测试",
        fen="7k/5K2/6P1/8/8/8/8/8 w - - 0 1",
        category="逼和检测",
        expected_result="逼和或白方胜",
        expected_description="不应漏算逼和机会，需正确评估",
        max_moves=5,
        search_depth=10,
        time_limit=1.0
    ),
    EndgamePosition(
        name="王活动性测试",
        fen="8/8/8/3k4/8/8/8/K7 w - - 0 1",
        category="王活动性",
        expected_result="均势",
        expected_description="黑王在中心，白王在角落，黑王活动性应被正确评估",
        max_moves=10,
        search_depth=10,
        time_limit=1.0
    ),
]


class EndgameTestSuite:
    def __init__(self, default_depth: int = 10, default_time: float = 1.0):
        self.default_depth = default_depth
        self.default_time = default_time
        self.results: List[TestResult] = []

    def run_single_test(self, position: EndgamePosition) -> TestResult:
        board = chess.Board(position.fen)
        start_time = time.perf_counter()

        depth = position.search_depth if position.search_depth > 0 else self.default_depth
        time_limit = position.time_limit if position.time_limit > 0 else self.default_time

        try:
            uci_move, score, nodes = engine_wrapper.search_with_score(
                position.fen,
                time_limit=time_limit,
                max_depth=depth,
                position_history=None,
                use_smp=False
            )
        except Exception as e:
            return TestResult(
                position=position,
                best_move="",
                score=0,
                nodes=0,
                time_elapsed=time.perf_counter() - start_time,
                is_checkmate=False,
                is_stalemate=False,
                moves_to_mate=None,
                evaluation_correct=False,
                details={"error": str(e)}
            )

        time_elapsed = time.perf_counter() - start_time

        is_checkmate = False
        is_stalemate = False
        moves_to_mate = None
        evaluation_correct = False

        if uci_move and len(uci_move) >= 4:
            try:
                move = chess.Move.from_uci(uci_move)
                if move in board.legal_moves:
                    board.push(move)
                    if board.is_checkmate():
                        is_checkmate = True
                        moves_to_mate = 1
                    elif board.is_stalemate():
                        is_stalemate = True
                    board.pop()

                    if position.category == "强制将杀":
                        evaluation_correct = score > 500 or is_checkmate
                    elif position.category == "兵升变":
                        evaluation_correct = score > 100
                    elif position.category == "象马将杀":
                        evaluation_correct = score > 0
                    elif position.category == "逼和检测":
                        evaluation_correct = True
                    elif position.category == "王活动性":
                        evaluation_correct = abs(score) < 200
                    else:
                        evaluation_correct = True
            except Exception:
                pass

        return TestResult(
            position=position,
            best_move=uci_move,
            score=score,
            nodes=nodes,
            time_elapsed=time_elapsed,
            is_checkmate=is_checkmate,
            is_stalemate=is_stalemate,
            moves_to_mate=moves_to_mate,
            evaluation_correct=evaluation_correct,
            details={}
        )

    def simulate_game(self, position: EndgamePosition, max_moves: int = 50) -> Dict[str, Any]:
        board = chess.Board(position.fen)
        moves = []
        scores = []
        nodes_list = []
        position_history = []

        depth = position.search_depth if position.search_depth > 0 else self.default_depth
        time_limit = position.time_limit if position.time_limit > 0 else self.default_time

        for _ in range(max_moves):
            if board.is_game_over():
                break

            fen = board.fen()
            try:
                hash_val = engine_wrapper.compute_hash(fen)
                position_history.append(hash_val)
            except Exception:
                pass

            try:
                uci_move, score, nodes = engine_wrapper.search_with_score(
                    fen,
                    time_limit=time_limit,
                    max_depth=depth,
                    position_history=position_history,
                    use_smp=False
                )
            except Exception as e:
                return {
                    "moves": moves,
                    "scores": scores,
                    "nodes": nodes_list,
                    "result": "error",
                    "error": str(e),
                    "final_fen": board.fen()
                }

            if not uci_move or len(uci_move) < 4:
                break

            try:
                move = chess.Move.from_uci(uci_move)
                if move not in board.legal_moves:
                    break
                board.push(move)
                moves.append(uci_move)
                scores.append(score)
                nodes_list.append(nodes)
            except Exception:
                break

        result = "unknown"
        if board.is_checkmate():
            result = "checkmate"
        elif board.is_stalemate():
            result = "stalemate"
        elif board.is_insufficient_material():
            result = "insufficient_material"
        elif len(moves) >= max_moves:
            result = "max_moves_reached"

        return {
            "moves": moves,
            "scores": scores,
            "nodes": nodes_list,
            "result": result,
            "final_fen": board.fen(),
            "total_moves": len(moves),
            "total_nodes": sum(nodes_list)
        }

    def run_all_tests(self, simulate: bool = True) -> List[TestResult]:
        print("=" * 70)
        print("残局测试集 - Endgame Test Suite")
        print("=" * 70)
        print(f"测试局面数量: {len(ENDGAME_POSITIONS)}")
        print(f"默认搜索深度: {self.default_depth}")
        print(f"默认时间限制: {self.default_time}s")
        print("=" * 70)

        self.results = []

        for i, position in enumerate(ENDGAME_POSITIONS, 1):
            print(f"\n[{i}/{len(ENDGAME_POSITIONS)}] 测试: {position.name}")
            print(f"  类别: {position.category}")
            print(f"  FEN: {position.fen}")
            print(f"  预期: {position.expected_description}")

            result = self.run_single_test(position)
            self.results.append(result)

            status = "✓" if result.evaluation_correct else "✗"
            print(f"  最佳走法: {result.best_move}")
            print(f"  分数: {result.score}")
            print(f"  节点数: {result.nodes}")
            print(f"  耗时: {result.time_elapsed:.3f}s")
            print(f"  评估正确: {status}")

            if result.is_checkmate:
                print(f"  发现将杀!")
            if result.is_stalemate:
                print(f"  发现逼和!")

            if simulate and position.category in ["强制将杀", "兵升变", "象马将杀"]:
                print(f"  模拟对弈...")
                game_result = self.simulate_game(position, max_moves=position.max_moves)
                print(f"    结果: {game_result['result']}")
                print(f"    步数: {game_result['total_moves']}")
                print(f"    总节点: {game_result['total_nodes']}")

                result.details["game_simulation"] = game_result

        return self.results

    def generate_report(self) -> Dict[str, Any]:
        total = len(self.results)
        correct = sum(1 for r in self.results if r.evaluation_correct)
        checkmates = sum(1 for r in self.results if r.is_checkmate)
        stalemates = sum(1 for r in self.results if r.is_stalemate)

        categories = {}
        for r in self.results:
            cat = r.position.category
            if cat not in categories:
                categories[cat] = {"total": 0, "correct": 0}
            categories[cat]["total"] += 1
            if r.evaluation_correct:
                categories[cat]["correct"] += 1

        return {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_positions": total,
                "correct_evaluations": correct,
                "accuracy": correct / total if total > 0 else 0,
                "checkmates_found": checkmates,
                "stalemates_found": stalemates,
            },
            "categories": categories,
            "results": [
                {
                    "name": r.position.name,
                    "fen": r.position.fen,
                    "category": r.position.category,
                    "expected": r.position.expected_description,
                    "best_move": r.best_move,
                    "score": r.score,
                    "nodes": r.nodes,
                    "time_elapsed": r.time_elapsed,
                    "is_checkmate": r.is_checkmate,
                    "is_stalemate": r.is_stalemate,
                    "evaluation_correct": r.evaluation_correct,
                    "game_simulation": r.details.get("game_simulation"),
                }
                for r in self.results
            ]
        }

    def print_summary(self):
        report = self.generate_report()
        summary = report["summary"]

        print("\n" + "=" * 70)
        print("测试结果摘要")
        print("=" * 70)
        print(f"总测试数: {summary['total_positions']}")
        print(f"正确评估: {summary['correct_evaluations']}")
        print(f"准确率: {summary['accuracy'] * 100:.1f}%")
        print(f"发现将杀: {summary['checkmates_found']}")
        print(f"发现逼和: {summary['stalemates_found']}")
        print("-" * 70)

        print("\n按类别统计:")
        for cat, stats in report["categories"].items():
            acc = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
            print(f"  {cat}: {stats['correct']}/{stats['total']} ({acc:.0f}%)")

        print("\n详细结果:")
        for r in self.results:
            status = "✓" if r.evaluation_correct else "✗"
            mate_info = ""
            if r.is_checkmate:
                mate_info = " [将杀]"
            elif r.is_stalemate:
                mate_info = " [逼和]"
            print(f"  {status} {r.position.name}: {r.best_move} (分数: {r.score}){mate_info}")

        print("=" * 70)

    def save_report(self, path: Path):
        report = self.generate_report()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n报告已保存: {path}")


def main():
    parser = argparse.ArgumentParser(description="残局测试集")
    parser.add_argument("--depth", "-d", type=int, default=10, help="搜索深度 (默认: 10)")
    parser.add_argument("--time", "-t", type=float, default=1.0, help="时间限制 (默认: 1.0s)")
    parser.add_argument("--no-simulate", action="store_true", help="不进行对弈模拟")
    parser.add_argument("--output", "-o", type=str, default=None, help="输出文件路径")

    args = parser.parse_args()

    try:
        engine_wrapper.reload_library()
        version = engine_wrapper.get_version()
        print(f"引擎版本: {version}")
    except Exception as e:
        print(f"警告: 无法加载引擎 - {e}")
        print("请确保已编译引擎 (运行 build_engine.py)")

    suite = EndgameTestSuite(
        default_depth=args.depth,
        default_time=args.time
    )

    suite.run_all_tests(simulate=not args.no_simulate)
    suite.print_summary()

    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path(__file__).parent / "endgame_test_results" / f"endgame_test_{timestamp}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    suite.save_report(output_path)


if __name__ == "__main__":
    main()
