"""
残局分类器与专用评估模块

实现残局类型识别、专用评估、基础杀棋模板
"""
from enum import Enum
from typing import Optional, Tuple, List
from dataclasses import dataclass

try:
    import chess
except ImportError:
    chess = None


class EndgameClass(Enum):
    NOT_ENDGAME = 0
    BASIC_MATE = 1
    QUEEN_ENDGAME = 2
    ROOK_ENDGAME = 3
    ROOK_PAWN_ENDGAME = 4
    PAWN_ENDGAME = 5
    MINOR_ENDGAME = 6
    COMPLEX_ENDGAME = 7


@dataclass
class EndgameInfo:
    eg_class: EndgameClass
    material_balance: int
    is_simple: bool
    has_passed_pawns: bool
    can_use_tablebase: bool
    tablebase_pieces: int
    dominant_side: Optional[bool]


class EndgameClassifier:
    """残局分类器"""
    
    PIECE_VALUES = {
        chess.PAWN: 1,
        chess.KNIGHT: 3,
        chess.BISHOP: 3,
        chess.ROOK: 5,
        chess.QUEEN: 9,
        chess.KING: 0
    }
    
    def __init__(self):
        self._tablebase_max_pieces = 5
    
    def classify(self, board) -> EndgameInfo:
        """分类残局类型"""
        if chess is None:
            raise ImportError("python-chess is required")
        
        white_pieces = self._count_pieces(board, chess.WHITE)
        black_pieces = self._count_pieces(board, chess.BLACK)
        
        total_pieces = sum(white_pieces.values()) + sum(black_pieces.values())
        
        white_material = self._material_value(white_pieces)
        black_material = self._material_value(black_pieces)
        material_balance = white_material - black_material
        
        has_passed_pawns = self._has_passed_pawns(board)
        
        eg_class = self._determine_class(white_pieces, black_pieces)
        
        is_simple = self._is_simple_endgame(
            white_pieces, black_pieces, total_pieces
        )
        
        can_use_tablebase = total_pieces <= self._tablebase_max_pieces
        
        dominant_side = None
        if material_balance > 2:
            dominant_side = chess.WHITE
        elif material_balance < -2:
            dominant_side = chess.BLACK
        
        return EndgameInfo(
            eg_class=eg_class,
            material_balance=material_balance,
            is_simple=is_simple,
            has_passed_pawns=has_passed_pawns,
            can_use_tablebase=can_use_tablebase,
            tablebase_pieces=total_pieces if can_use_tablebase else 0,
            dominant_side=dominant_side
        )
    
    def _count_pieces(self, board, color) -> dict:
        """统计某方棋子数量"""
        pieces = {}
        for piece_type in [chess.PAWN, chess.KNIGHT, chess.BISHOP, 
                          chess.ROOK, chess.QUEEN, chess.KING]:
            pieces[piece_type] = len(board.pieces(piece_type, color))
        return pieces
    
    def _material_value(self, pieces: dict) -> int:
        """计算子力价值"""
        value = 0
        for piece_type, count in pieces.items():
            value += self.PIECE_VALUES[piece_type] * count
        return value
    
    def _determine_class(self, white_pieces: dict, black_pieces: dict) -> EndgameClass:
        """确定残局类型"""
        w_q = white_pieces[chess.QUEEN]
        b_q = black_pieces[chess.QUEEN]
        w_r = white_pieces[chess.ROOK]
        b_r = black_pieces[chess.ROOK]
        w_p = white_pieces[chess.PAWN]
        b_p = black_pieces[chess.PAWN]
        w_minors = white_pieces[chess.KNIGHT] + white_pieces[chess.BISHOP]
        b_minors = black_pieces[chess.KNIGHT] + black_pieces[chess.BISHOP]
        
        if w_q + b_q + w_r + b_r + w_minors + b_minors == 0:
            return EndgameClass.PAWN_ENDGAME
        
        if w_q == 1 and b_q == 0 and w_r == 0 and b_r == 0 and w_minors == 0 and b_minors == 0:
            return EndgameClass.BASIC_MATE
        if b_q == 1 and w_q == 0 and w_r == 0 and b_r == 0 and w_minors == 0 and b_minors == 0:
            return EndgameClass.BASIC_MATE
        
        if w_r == 1 and b_r == 0 and w_q == 0 and b_q == 0 and w_minors == 0 and b_minors == 0:
            return EndgameClass.BASIC_MATE
        if b_r == 1 and w_r == 0 and w_q == 0 and b_q == 0 and w_minors == 0 and b_minors == 0:
            return EndgameClass.BASIC_MATE
        
        if w_q + b_q == 0 and w_r + b_r == 0:
            return EndgameClass.MINOR_ENDGAME
        
        if w_q + b_q == 0 and w_r + b_r > 0:
            if w_p + b_p == 0:
                return EndgameClass.ROOK_ENDGAME
            return EndgameClass.ROOK_PAWN_ENDGAME
        
        if w_q + b_q > 0 and w_r + b_r == 0 and w_minors <= 1 and b_minors <= 1:
            return EndgameClass.QUEEN_ENDGAME
        
        return EndgameClass.COMPLEX_ENDGAME
    
    def _is_simple_endgame(self, white_pieces: dict, black_pieces: dict, 
                           total_pieces: int) -> bool:
        """判断是否为简单残局"""
        if total_pieces <= 4:
            return True
        
        w_q = white_pieces[chess.QUEEN]
        b_q = black_pieces[chess.QUEEN]
        w_r = white_pieces[chess.ROOK]
        b_r = black_pieces[chess.ROOK]
        
        if w_q + b_q + w_r + b_r <= 1 and total_pieces <= 6:
            return True
        
        return False
    
    def _has_passed_pawns(self, board) -> bool:
        """检测是否有通路兵"""
        for color in [chess.WHITE, chess.BLACK]:
            pawns = board.pieces(chess.PAWN, color)
            for pawn_sq in pawns:
                if self._is_passed_pawn(board, pawn_sq, color):
                    return True
        return False
    
    def _is_passed_pawn(self, board, square, color) -> bool:
        """判断是否为通路兵"""
        file = chess.square_file(square)
        rank = chess.square_rank(square)
        enemy_color = not color
        
        enemy_pawns = board.pieces(chess.PAWN, enemy_color)
        
        if color == chess.WHITE:
            for enemy_sq in enemy_pawns:
                enemy_file = chess.square_file(enemy_sq)
                enemy_rank = chess.square_rank(enemy_sq)
                if abs(enemy_file - file) <= 1 and enemy_rank > rank:
                    return False
        else:
            for enemy_sq in enemy_pawns:
                enemy_file = chess.square_file(enemy_sq)
                enemy_rank = chess.square_rank(enemy_sq)
                if abs(enemy_file - file) <= 1 and enemy_rank < rank:
                    return False
        
        return True


class EndgameEvaluator:
    """残局专用评估"""
    
    def __init__(self):
        self.classifier = EndgameClassifier()
    
    def evaluate(self, board, eg_info: Optional[EndgameInfo] = None) -> int:
        """残局评估"""
        if chess is None:
            raise ImportError("python-chess is required")
        
        if eg_info is None:
            eg_info = self.classifier.classify(board)
        
        if eg_info.eg_class == EndgameClass.NOT_ENDGAME:
            return 0
        
        score = 0
        
        score += self._king_activity(board, eg_info)
        score += self._push_king(board, eg_info)
        score += self._passed_pawn_push(board, eg_info)
        score += self._simplification(board, eg_info)
        
        return score
    
    def _king_activity(self, board, eg_info: EndgameInfo) -> int:
        """王活跃化评估"""
        score = 0
        
        for color in [chess.WHITE, chess.BLACK]:
            king_sq = board.king(color)
            if king_sq is None:
                continue
            
            center_dist = self._center_distance(king_sq)
            
            if eg_info.dominant_side == color:
                activity = (7 - center_dist) * 5
            else:
                activity = center_dist * 3
            
            if color == chess.WHITE:
                score += activity
            else:
                score -= activity
        
        return score
    
    def _push_king(self, board, eg_info: EndgameInfo) -> int:
        """逼王到边角评估"""
        if eg_info.eg_class != EndgameClass.BASIC_MATE:
            return 0
        
        score = 0
        
        enemy_color = not eg_info.dominant_side if eg_info.dominant_side else chess.BLACK
        enemy_king_sq = board.king(enemy_color)
        
        if enemy_king_sq is not None:
            file = chess.square_file(enemy_king_sq)
            rank = chess.square_rank(enemy_king_sq)
            corners = [(0, 0), (0, 7), (7, 0), (7, 7)]
            corner_dist = min(abs(file - cf) + abs(rank - cr) for cf, cr in corners)
            if eg_info.dominant_side == chess.WHITE:
                score += corner_dist * 10
            else:
                score -= corner_dist * 10
        
        return score
    
    def _passed_pawn_push(self, board, eg_info: EndgameInfo) -> int:
        """通路兵推进评估"""
        if not eg_info.has_passed_pawns:
            return 0
        
        score = 0
        
        for color in [chess.WHITE, chess.BLACK]:
            pawns = board.pieces(chess.PAWN, color)
            for pawn_sq in pawns:
                if self.classifier._is_passed_pawn(board, pawn_sq, color):
                    rank = chess.square_rank(pawn_sq)
                    
                    if color == chess.WHITE:
                        push_score = rank * rank * 3
                        score += push_score
                    else:
                        push_score = (7 - rank) * (7 - rank) * 3
                        score -= push_score
        
        return score
    
    def _simplification(self, board, eg_info: EndgameInfo) -> int:
        """简化奖励"""
        if eg_info.dominant_side is None:
            return 0
        
        score = 0
        
        dominant_material = self._total_material(board, eg_info.dominant_side)
        enemy_color = not eg_info.dominant_side
        enemy_material = self._total_material(board, enemy_color)
        
        if dominant_material > enemy_material + 3:
            simplification_bonus = (dominant_material - enemy_material) * 2
            if eg_info.dominant_side == chess.WHITE:
                score += simplification_bonus
            else:
                score -= simplification_bonus
        
        return score
    
    def _center_distance(self, square) -> int:
        """计算到中心的距离"""
        file = chess.square_file(square)
        rank = chess.square_rank(square)
        center_file = 3.5
        center_rank = 3.5
        return int(abs(file - center_file) + abs(rank - center_rank))
    
    def _corner_distance(self, square) -> int:
        """计算到最近角落的距离"""
        file = chess.square_file(square)
        rank = chess.square_rank(square)
        
        corners = [(0, 0), (0, 7), (7, 0), (7, 7)]
        min_dist = 100
        
        for cf, cr in corners:
            dist = abs(file - cf) + abs(rank - cr)
            min_dist = min(min_dist, dist)
        
        return min_dist
    
    def _total_material(self, board, color) -> int:
        """计算总子力"""
        values = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
                  chess.ROOK: 5, chess.QUEEN: 9}
        total = 0
        for piece_type, value in values.items():
            total += len(board.pieces(piece_type, color)) * value
        return total


class BasicMateTemplates:
    """基础杀棋模板"""
    
    def __init__(self):
        self.classifier = EndgameClassifier()
    
    def can_mate_directly(self, board) -> Optional[str]:
        """检查是否可以直接将杀"""
        if chess is None:
            raise ImportError("python-chess is required")
        
        eg_info = self.classifier.classify(board)
        
        if eg_info.eg_class != EndgameClass.BASIC_MATE:
            return None
        
        for move in board.legal_moves:
            board.push(move)
            if board.is_checkmate():
                board.pop()
                return move.uci()
            board.pop()
        
        return None
    
    def get_mate_distance(self, board) -> Optional[int]:
        """获取将杀距离 (简化版)"""
        mate_move = self.can_mate_directly(board)
        if mate_move:
            return 1
        
        eg_info = self.classifier.classify(board)
        if eg_info.eg_class != EndgameClass.BASIC_MATE:
            return None
        
        return 3
    
    def get_mate_guide_move(self, board) -> Optional[str]:
        """获取杀棋引导着法"""
        if chess is None:
            raise ImportError("python-chess is required")
        
        eg_info = self.classifier.classify(board)
        
        if eg_info.eg_class != EndgameClass.BASIC_MATE:
            return None
        
        mate_move = self.can_mate_directly(board)
        if mate_move:
            return mate_move
        
        return self._find_push_king_move(board)
    
    def _find_push_king_move(self, board) -> Optional[str]:
        """找到逼王的着法"""
        enemy_king_sq = board.king(not board.turn)
        if enemy_king_sq is None:
            return None
        
        best_move = None
        best_score = -1000
        
        for move in board.legal_moves:
            board.push(move)
            new_enemy_king = board.king(not board.turn)
            if new_enemy_king:
                nf = chess.square_file(new_enemy_king)
                nr = chess.square_rank(new_enemy_king)
                corners = [(0, 0), (0, 7), (7, 0), (7, 7)]
                new_corner_dist = min(abs(nf - cf) + abs(nr - cr) for cf, cr in corners)
                if new_corner_dist > best_score:
                    best_score = new_corner_dist
                    best_move = move.uci()
            board.pop()
        
        return best_move


class EndgameManager:
    """残局管理器"""
    
    def __init__(self):
        self.classifier = EndgameClassifier()
        self.evaluator = EndgameEvaluator()
        self.mate_templates = BasicMateTemplates()
        self._depth_bonus = 2
        self._enabled = True
    
    def configure(self, enabled: bool = True, depth_bonus: int = 2) -> None:
        """配置残局模块"""
        self._enabled = enabled
        self._depth_bonus = depth_bonus
    
    def get_endgame_evaluation(self, board) -> int:
        """获取残局评估"""
        if not self._enabled:
            return 0
        
        eg_info = self.classifier.classify(board)
        return self.evaluator.evaluate(board, eg_info)
    
    def get_endgame_depth_bonus(self, board) -> int:
        """获取残局深度奖励"""
        if not self._enabled:
            return 0
        
        eg_info = self.classifier.classify(board)
        
        if eg_info.is_simple:
            return self._depth_bonus
        
        return 0
    
    def try_mate_move(self, board) -> Optional[str]:
        """尝试获取杀棋着法"""
        if not self._enabled:
            return None
        
        return self.mate_templates.can_mate_directly(board)
    
    def get_info(self, board) -> Optional[EndgameInfo]:
        """获取残局信息"""
        if not self._enabled:
            return None
        
        return self.classifier.classify(board)
