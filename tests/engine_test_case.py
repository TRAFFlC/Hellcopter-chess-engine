"""
引擎测试基类

封装 C 引擎调用、局面设置、断言方法，供所有测试用例使用。
"""

import unittest
import os
import sys
import time
import chess

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine_wrapper


class EngineTestCase(unittest.TestCase):
    """引擎测试基类"""
    
    @classmethod
    def setUpClass(cls):
        """初始化引擎（整个测试类只初始化一次）"""
        cls.engine_loaded = False
        try:
            # 检查引擎 DLL 是否存在
            dll_path = engine_wrapper._get_dll_path()
            if os.path.exists(dll_path):
                cls.engine_loaded = True
        except Exception as e:
            print(f"警告: 引擎加载失败: {e}")
    
    def setUp(self):
        """每个测试用例前重置状态"""
        self.board = chess.Board()
        self.search_results = []
    
    def tearDown(self):
        """每个测试用例后清理"""
        self.search_results = []
    
    def set_position(self, fen: str):
        """设置棋盘局面"""
        self.board = chess.Board(fen)
    
    def set_starting_position(self):
        """设置起始局面"""
        self.board = chess.Board()
    
    def apply_moves(self, moves: list):
        """应用一系列着法"""
        for move_uci in moves:
            move = chess.Move.from_uci(move_uci)
            if move in self.board.legal_moves:
                self.board.push(move)
            else:
                raise ValueError(f"非法着法: {move_uci} 在局面 {self.board.fen()}")
    
    def search(self, time_limit: float = 1.0, depth: int = 0, 
               wtime: int = 0, btime: int = 0, winc: int = 0, binc: int = 0,
               movestogo: int = 0, movetime: int = 0) -> dict:
        """
        运行搜索
        
        Args:
            time_limit: 时间限制（秒）
            depth: 搜索深度限制
            wtime/btime: 白方/黑方剩余时间（毫秒）
            winc/binc: 白方/黑方增量（毫秒）
            movestogo: 剩余步数
            movetime: 固定每步时间（毫秒）
        
        Returns:
            dict: 包含 best_move, score, depth, nodes, time 等信息
        """
        if not self.engine_loaded:
            self.skipTest("引擎未加载")
        
        fen = self.board.fen().encode('utf-8')
        
        # 设置时间参数
        if movetime > 0:
            time_limit = movetime / 1000.0
        elif wtime > 0 or btime > 0:
            # 根据当前方选择时间
            if self.board.turn == chess.WHITE:
                time_limit = wtime / 1000.0 if wtime > 0 else time_limit
            else:
                time_limit = btime / 1000.0 if btime > 0 else time_limit
        
        # 限制最大时间
        time_limit = min(time_limit, 30.0)
        
        start_time = time.time()
        
        try:
            # 调用引擎搜索
            result = engine_wrapper.find_best_move(
                fen=fen,
                time_limit=time_limit,
                depth=depth if depth > 0 else 0
            )
            
            elapsed = time.time() - start_time
            
            # 解析结果
            search_result = {
                'best_move': result.get('best_move', ''),
                'score': result.get('score', 0),
                'depth': result.get('depth', 0),
                'nodes': result.get('nodes', 0),
                'time': elapsed,
                'pv': result.get('pv', []),
                'nps': result.get('nodes', 0) / elapsed if elapsed > 0 else 0
            }
            
            self.search_results.append(search_result)
            return search_result
            
        except Exception as e:
            self.fail(f"搜索失败: {e}")
    
    def search_with_uci(self, fen: str, time_limit: float = 1.0, 
                        depth: int = 0) -> dict:
        """
        使用 UCI 协议搜索（备用方法）
        """
        self.set_position(fen)
        return self.search(time_limit=time_limit, depth=depth)
    
    def assert_legal_move(self, move_uci: str):
        """断言着法是合法的"""
        move = chess.Move.from_uci(move_uci)
        self.assertIn(move, self.board.legal_moves, 
                     f"着法 {move_uci} 在局面 {self.board.fen()} 中不合法")
    
    def assert_best_move_not_null(self, result: dict):
        """断言最佳着法不为空"""
        self.assertIsNotNone(result.get('best_move'), "最佳着法不应为 None")
        self.assertNotEqual(result.get('best_move'), '', "最佳着法不应为空字符串")
    
    def assert_search_depth(self, result: dict, min_depth: int):
        """断言搜索深度达到最小值"""
        self.assertGreaterEqual(result.get('depth', 0), min_depth,
                               f"搜索深度应 >= {min_depth}")
    
    def assert_search_time(self, result: dict, max_time: float):
        """断言搜索时间不超过限制"""
        self.assertLessEqual(result.get('time', 0), max_time,
                            f"搜索时间应 <= {max_time}s")
    
    def assert_score_in_range(self, result: dict, min_score: int, max_score: int):
        """断言分数在指定范围内"""
        score = result.get('score', 0)
        self.assertGreaterEqual(score, min_score,
                               f"分数 {score} 应 >= {min_score}")
        self.assertLessEqual(score, max_score,
                            f"分数 {score} 应 <= {max_score}")
    
    def assert_eval_symmetry(self, fen: str, tolerance: int = 20):
        """
        断言对称局面的评估值接近 0
        
        Args:
            fen: 局面 FEN
            tolerance: 允许的误差范围（cp）
        """
        result = self.search(fen, time_limit=0.5)
        score = result.get('score', 0)
        self.assertLessEqual(abs(score), tolerance,
                            f"对称局面分数 {score} 应接近 0 (容差 {tolerance}cp)")
    
    def assert_no_crash(self, fen: str, time_limit: float = 1.0):
        """断言搜索不会崩溃"""
        try:
            result = self.search(fen, time_limit=time_limit)
            self.assertIsNotNone(result, "搜索结果不应为 None")
        except Exception as e:
            self.fail(f"搜索崩溃: {e}")
    
    def measure_search_time(self, fen: str, time_limit: float = 1.0) -> float:
        """测量搜索时间"""
        start = time.time()
        self.search(fen, time_limit=time_limit)
        return time.time() - start
    
    def count_legal_moves(self, fen: str) -> int:
        """计算合法着法数量"""
        board = chess.Board(fen)
        return len(list(board.legal_moves))
    
    def is_endgame(self, fen: str) -> bool:
        """判断是否是残局"""
        board = chess.Board(fen)
        # 简单判断：双方都没有皇后，或者总子力价值低
        queens = len(board.pieces(chess.QUEEN, chess.WHITE)) + \
                 len(board.pieces(chess.QUEEN, chess.BLACK))
        return queens == 0
    
    def get_material_balance(self, fen: str) -> int:
        """获取子力平衡（正值表示白方优势）"""
        board = chess.Board(fen)
        values = {
            chess.PAWN: 100,
            chess.KNIGHT: 300,
            chess.BISHOP: 320,
            chess.ROOK: 480,
            chess.QUEEN: 900,
            chess.KING: 0
        }
        
        balance = 0
        for piece_type in values:
            white_count = len(board.pieces(piece_type, chess.WHITE))
            black_count = len(board.pieces(piece_type, chess.BLACK))
            balance += (white_count - black_count) * values[piece_type]
        
        return balance


class SearchTestCase(EngineTestCase):
    """搜索算法测试基类"""
    
    def assert_aspiration_window_stable(self, fen: str, time_limit: float = 2.0):
        """断言 aspiration window 搜索稳定"""
        result = self.search(fen, time_limit=time_limit)
        # 检查是否有有效的 PV
        self.assert_best_move_not_null(result)
        self.assert_search_depth(result, 1)


class PruningTestCase(EngineTestCase):
    """剪枝算法测试基类"""
    
    def count_nodes(self, fen: str, time_limit: float = 1.0) -> int:
        """统计搜索节点数"""
        result = self.search(fen, time_limit=time_limit)
        return result.get('nodes', 0)
    
    def assert_node_count_reduction(self, fen: str, 
                                   baseline_nodes: int, 
                                   min_reduction_pct: float = 5.0):
        """断言节点数减少"""
        current_nodes = self.count_nodes(fen)
        if baseline_nodes > 0:
            reduction_pct = (baseline_nodes - current_nodes) / baseline_nodes * 100
            self.assertGreaterEqual(reduction_pct, min_reduction_pct,
                                   f"节点数减少 {reduction_pct:.1f}% 应 >= {min_reduction_pct}%")


class EvaluationTestCase(EngineTestCase):
    """评估函数测试基类"""
    
    def get_eval(self, fen: str, time_limit: float = 0.5) -> int:
        """获取评估值"""
        result = self.search(fen, time_limit=time_limit)
        return result.get('score', 0)
    
    def assert_eval_positive(self, fen: str, min_score: int = 0):
        """断言评估值为正"""
        eval_score = self.get_eval(fen)
        self.assertGreater(eval_score, min_score,
                          f"评估值 {eval_score} 应 > {min_score}")
    
    def assert_eval_negative(self, fen: str, max_score: int = 0):
        """断言评估值为负"""
        eval_score = self.get_eval(fen)
        self.assertLess(eval_score, max_score,
                       f"评估值 {eval_score} 应 < {max_score}")


class TimeManagementTestCase(EngineTestCase):
    """时间管理测试基类"""
    
    def search_with_time_pressure(self, fen: str, 
                                  time_ms: int, 
                                  increment_ms: int = 0) -> dict:
        """在时间压力下搜索"""
        return self.search(fen, time_limit=time_ms/1000.0)
    
    def assert_time_usage_efficient(self, fen: str, 
                                   allocated_time: float,
                                   max_usage_ratio: float = 0.3):
        """
        断言时间使用高效（简单局面不应使用太多时间）
        """
        result = self.search(fen, time_limit=allocated_time)
        usage_ratio = result.get('time', 0) / allocated_time
        self.assertLessEqual(usage_ratio, max_usage_ratio,
                            f"时间使用比例 {usage_ratio:.2f} 应 <= {max_usage_ratio}")
    
    def assert_no_timeout(self, fen: str, time_ms: int):
        """断言不会超时"""
        start = time.time()
        result = self.search(fen, time_limit=time_ms/1000.0)
        elapsed = time.time() - start
        self.assertLess(elapsed, time_ms/1000.0 + 0.1,
                       f"搜索时间 {elapsed:.2f}s 应 < {time_ms/1000.0 + 0.1}s")


if __name__ == '__main__':
    unittest.main()
