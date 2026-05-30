"""
开局退化防护模块

检测开局阶段的异常行为，防止引擎退化
"""
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

try:
    import chess
except ImportError:
    chess = None


class OpeningAnomalyType(Enum):
    EDGE_PAWN_PUSH = "edge_pawn_push"
    EARLY_QUEEN_MOVE = "early_queen_move"
    EARLY_ROOK_MOVE = "early_rook_move"
    POOR_DEVELOPMENT = "poor_development"
    WEAK_CENTER = "weak_center"
    KING_EXPOSURE = "king_exposure"


@dataclass
class OpeningAnomaly:
    anomaly_type: OpeningAnomalyType
    move_number: int
    move: str
    severity: float
    description: str


@dataclass
class OpeningMetrics:
    edge_pawn_pushes: int
    early_queen_moves: int
    early_rook_moves: int
    development_score: float
    center_control_score: float
    king_safety_score: float


class OpeningAnalyzer:
    """开局分析器"""
    
    EDGE_FILES = {0, 7}
    CENTER_SQUARES = {chess.D4, chess.E4, chess.D5, chess.E5} if chess else set()
    EXTENDED_CENTER = {chess.C3, chess.D3, chess.E3, chess.F3,
                       chess.C4, chess.D4, chess.E4, chess.F4,
                       chess.C5, chess.D5, chess.E5, chess.F5,
                       chess.C6, chess.D6, chess.E6, chess.F6} if chess else set()
    
    def __init__(self):
        self._max_move_number = 12
        self._edge_pawn_threshold = 2
        self._early_queen_threshold = 1
        self._early_rook_threshold = 1
        self._development_threshold = 0.6
    
    def analyze_move(self, board, move, move_number: int) -> Optional[OpeningAnomaly]:
        """分析单个着法是否有异常"""
        if chess is None:
            raise ImportError("python-chess is required")
        
        if move_number > self._max_move_number:
            return None
        
        piece = board.piece_at(move.from_square)
        if piece is None:
            return None
        
        if piece.piece_type == chess.PAWN:
            from_file = chess.square_file(move.from_square)
            if from_file in self.EDGE_FILES:
                return OpeningAnomaly(
                    anomaly_type=OpeningAnomalyType.EDGE_PAWN_PUSH,
                    move_number=move_number,
                    move=move.uci(),
                    severity=0.5,
                    description=f"Edge pawn push on move {move_number}"
                )
        
        if piece.piece_type == chess.QUEEN:
            if move_number <= 6:
                return OpeningAnomaly(
                    anomaly_type=OpeningAnomalyType.EARLY_QUEEN_MOVE,
                    move_number=move_number,
                    move=move.uci(),
                    severity=0.8,
                    description=f"Early queen move on move {move_number}"
                )
        
        if piece.piece_type == chess.ROOK:
            if move_number <= 6:
                return OpeningAnomaly(
                    anomaly_type=OpeningAnomalyType.EARLY_ROOK_MOVE,
                    move_number=move_number,
                    move=move.uci(),
                    severity=0.6,
                    description=f"Early rook move on move {move_number}"
                )
        
        return None
    
    def compute_metrics(self, board, move_history: List[str]) -> OpeningMetrics:
        """计算开局指标"""
        if chess is None:
            raise ImportError("python-chess is required")
        
        edge_pawn_pushes = 0
        early_queen_moves = 0
        early_rook_moves = 0
        
        test_board = chess.Board()
        for i, move_uci in enumerate(move_history[:self._max_move_number]):
            try:
                move = chess.Move.from_uci(move_uci)
                anomaly = self.analyze_move(test_board, move, i + 1)
                if anomaly:
                    if anomaly.anomaly_type == OpeningAnomalyType.EDGE_PAWN_PUSH:
                        edge_pawn_pushes += 1
                    elif anomaly.anomaly_type == OpeningAnomalyType.EARLY_QUEEN_MOVE:
                        early_queen_moves += 1
                    elif anomaly.anomaly_type == OpeningAnomalyType.EARLY_ROOK_MOVE:
                        early_rook_moves += 1
                test_board.push(move)
            except ValueError:
                break
        
        development_score = self._compute_development(board)
        center_control_score = self._compute_center_control(board)
        king_safety_score = self._compute_king_safety(board)
        
        return OpeningMetrics(
            edge_pawn_pushes=edge_pawn_pushes,
            early_queen_moves=early_queen_moves,
            early_rook_moves=early_rook_moves,
            development_score=development_score,
            center_control_score=center_control_score,
            king_safety_score=king_safety_score
        )
    
    def _compute_development(self, board) -> float:
        """计算出子完成度"""
        developed_pieces = 0
        total_pieces = 0
        
        for color in [chess.WHITE, chess.BLACK]:
            knights = board.pieces(chess.KNIGHT, color)
            bishops = board.pieces(chess.BISHOP, color)
            
            total_pieces += len(knights) + len(bishops)
            
            for sq in knights:
                if color == chess.WHITE:
                    if chess.square_rank(sq) > 0:
                        developed_pieces += 1
                else:
                    if chess.square_rank(sq) < 7:
                        developed_pieces += 1
            
            for sq in bishops:
                if color == chess.WHITE:
                    if chess.square_rank(sq) > 0:
                        developed_pieces += 1
                else:
                    if chess.square_rank(sq) < 7:
                        developed_pieces += 1
        
        if total_pieces == 0:
            return 1.0
        
        return developed_pieces / total_pieces
    
    def _compute_center_control(self, board) -> float:
        """计算中心控制分数"""
        score = 0.0
        
        for sq in self.CENTER_SQUARES:
            white_attacks = len(board.attackers(chess.WHITE, sq))
            black_attacks = len(board.attackers(chess.BLACK, sq))
            
            if white_attacks > black_attacks:
                score += 0.25
            elif black_attacks > white_attacks:
                score -= 0.25
        
        return (score + 1.0) / 2.0
    
    def _compute_king_safety(self, board) -> float:
        """计算王安全分数"""
        score = 1.0
        
        for color in [chess.WHITE, chess.BLACK]:
            king_sq = board.king(color)
            if king_sq is None:
                continue
            
            if color == chess.WHITE:
                if chess.square_rank(king_sq) == 0:
                    score += 0.1
            else:
                if chess.square_rank(king_sq) == 7:
                    score += 0.1
        
        return min(score, 1.0)


class OpeningRegressionTester:
    """开局回归测试器"""
    
    def __init__(self):
        self.analyzer = OpeningAnalyzer()
        self._baseline_metrics: Dict[str, OpeningMetrics] = {}
        self._test_results: List[Tuple[str, bool, str]] = []
    
    def set_baseline(self, name: str, metrics: OpeningMetrics) -> None:
        """设置基线指标"""
        self._baseline_metrics[name] = metrics
    
    def test_game(self, 
                  name: str,
                  board,
                  move_history: List[str],
                  strict: bool = False) -> Tuple[bool, List[OpeningAnomaly]]:
        """测试一局棋的开局行为"""
        metrics = self.analyzer.compute_metrics(board, move_history)
        anomalies = []
        passed = True
        
        if metrics.edge_pawn_pushes > self.analyzer._edge_pawn_threshold:
            anomalies.append(OpeningAnomaly(
                anomaly_type=OpeningAnomalyType.EDGE_PAWN_PUSH,
                move_number=0,
                move="",
                severity=metrics.edge_pawn_pushes / 10.0,
                description=f"Too many edge pawn pushes: {metrics.edge_pawn_pushes}"
            ))
            if strict:
                passed = False
        
        if metrics.early_queen_moves > self.analyzer._early_queen_threshold:
            anomalies.append(OpeningAnomaly(
                anomaly_type=OpeningAnomalyType.EARLY_QUEEN_MOVE,
                move_number=0,
                move="",
                severity=metrics.early_queen_moves / 5.0,
                description=f"Too many early queen moves: {metrics.early_queen_moves}"
            ))
            if strict:
                passed = False
        
        if metrics.early_rook_moves > self.analyzer._early_rook_threshold:
            anomalies.append(OpeningAnomaly(
                anomaly_type=OpeningAnomalyType.EARLY_ROOK_MOVE,
                move_number=0,
                move="",
                severity=metrics.early_rook_moves / 5.0,
                description=f"Too many early rook moves: {metrics.early_rook_moves}"
            ))
            if strict:
                passed = False
        
        if metrics.development_score < self.analyzer._development_threshold:
            anomalies.append(OpeningAnomaly(
                anomaly_type=OpeningAnomalyType.POOR_DEVELOPMENT,
                move_number=0,
                move="",
                severity=1.0 - metrics.development_score,
                description=f"Poor development score: {metrics.development_score:.2f}"
            ))
        
        baseline = self._baseline_metrics.get(name)
        if baseline:
            if metrics.edge_pawn_pushes > baseline.edge_pawn_pushes + 1:
                passed = False
        
        self._test_results.append((name, passed, 
            f"edge_pawn={metrics.edge_pawn_pushes}, "
            f"early_q={metrics.early_queen_moves}, "
            f"early_r={metrics.early_rook_moves}, "
            f"dev={metrics.development_score:.2f}"))
        
        return passed, anomalies
    
    def get_summary(self) -> Dict:
        """获取测试摘要"""
        total = len(self._test_results)
        passed = sum(1 for _, p, _ in self._test_results if p)
        
        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": passed / total if total > 0 else 0.0
        }


class OpeningHealthChecker:
    """开局健康检查器"""
    
    def __init__(self):
        self.analyzer = OpeningAnalyzer()
        self.tester = OpeningRegressionTester()
    
    def check_position(self, board, move_history: List[str]) -> Dict:
        """检查当前局面的开局健康度"""
        metrics = self.analyzer.compute_metrics(board, move_history)
        
        health_score = 100.0
        
        health_score -= metrics.edge_pawn_pushes * 10
        health_score -= metrics.early_queen_moves * 15
        health_score -= metrics.early_rook_moves * 8
        health_score += metrics.development_score * 20
        health_score += metrics.center_control_score * 10
        
        health_score = max(0, min(100, health_score))
        
        return {
            "health_score": health_score,
            "metrics": {
                "edge_pawn_pushes": metrics.edge_pawn_pushes,
                "early_queen_moves": metrics.early_queen_moves,
                "early_rook_moves": metrics.early_rook_moves,
                "development_score": round(metrics.development_score, 2),
                "center_control_score": round(metrics.center_control_score, 2),
                "king_safety_score": round(metrics.king_safety_score, 2)
            },
            "status": "healthy" if health_score >= 70 else "warning" if health_score >= 50 else "unhealthy"
        }
    
    def should_block_release(self, test_games: List[Tuple[str, any, List[str]]]) -> Tuple[bool, str]:
        """检查是否应该阻断发布"""
        all_passed = True
        anomalies_found = []
        
        for name, board, moves in test_games:
            passed, anomalies = self.tester.test_game(name, board, moves, strict=True)
            if not passed:
                all_passed = False
                anomalies_found.extend([a.description for a in anomalies])
        
        if all_passed:
            return False, "All opening regression tests passed"
        
        return True, f"Opening regression failures: {'; '.join(anomalies_found)}"
