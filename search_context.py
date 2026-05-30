"""
搜索上下文缓存与 Ponder 支持

实现跨回合搜索上下文保持、预测应手承接、Ponder 机制
"""
import threading
import time
from typing import Optional, List, Tuple, Dict
from dataclasses import dataclass, field
from enum import Enum

try:
    import chess
except ImportError:
    chess = None


class TTFlag(Enum):
    EXACT = 0
    LOWER = 1
    UPPER = 2


@dataclass
class TTEntry:
    key: int
    depth: int
    score: int
    flag: TTFlag
    move: str
    generation: int


@dataclass
class SearchContext:
    root_fen: str
    best_move: str
    ponder_move: Optional[str]
    score: int
    depth: int
    nodes: int
    pv: List[str]
    candidate_moves: List[Tuple[str, int]]
    timestamp: float


@dataclass
class PersistentTT:
    entries: Dict[int, TTEntry] = field(default_factory=dict)
    generation: int = 0
    max_size: int = 1000000
    
    def store(self, key: int, depth: int, score: int, flag: TTFlag, move: str) -> None:
        if len(self.entries) >= self.max_size:
            self._evict_old()
        
        self.entries[key] = TTEntry(
            key=key,
            depth=depth,
            score=score,
            flag=flag,
            move=move,
            generation=self.generation
        )
    
    def probe(self, key: int) -> Optional[TTEntry]:
        return self.entries.get(key)
    
    def _evict_old(self) -> None:
        old_gen = self.generation - 2
        keys_to_remove = [
            k for k, v in self.entries.items() 
            if v.generation < old_gen
        ]
        for k in keys_to_remove[:len(keys_to_remove) // 2]:
            del self.entries[k]
    
    def new_generation(self) -> None:
        self.generation += 1
    
    def clear(self) -> None:
        self.entries.clear()
        self.generation = 0


class SearchContextCache:
    """搜索上下文缓存管理器"""
    
    def __init__(self, max_tt_size: int = 1000000, max_history: int = 100):
        self.tt = PersistentTT(max_size=max_tt_size)
        self.last_context: Optional[SearchContext] = None
        self.history_table: Dict[Tuple, int] = {}
        self.killer_moves: List[List[Optional[str]]] = [[None, None] for _ in range(64)]
        self._max_history = max_history
        self._expire_time = 30.0
        self._lock = threading.Lock()
    
    def save_context(self, context: SearchContext) -> None:
        """保存搜索上下文"""
        with self._lock:
            self.last_context = context
            self.tt.new_generation()
    
    def get_context(self, fen: str) -> Optional[SearchContext]:
        """获取匹配的上下文"""
        with self._lock:
            if self.last_context is None:
                return None
            
            if time.time() - self.last_context.timestamp > self._expire_time:
                self.last_context = None
                return None
            
            return self.last_context
    
    def can_reuse(self, new_fen: str, last_fen: str) -> bool:
        """判断是否可以复用上下文"""
        with self._lock:
            if self.last_context is None:
                return False
            
            if time.time() - self.last_context.timestamp > self._expire_time:
                return False
            
            return True
    
    def update_after_move(self, played_move: str, 
                          opponent_move: Optional[str] = None) -> None:
        """对手走子后更新上下文"""
        with self._lock:
            if self.last_context is None:
                return
            
            if opponent_move:
                for move, score in self.last_context.candidate_moves:
                    if move == opponent_move:
                        return
            
            self.last_context = None
    
    def get_ponder_move(self) -> Optional[str]:
        """获取预测应手"""
        with self._lock:
            if self.last_context is None:
                return None
            return self.last_context.ponder_move
    
    def add_killer(self, ply: int, move: str) -> None:
        """添加杀手着法"""
        with self._lock:
            if 0 <= ply < 64:
                if self.killer_moves[ply][0] != move:
                    self.killer_moves[ply][1] = self.killer_moves[ply][0]
                    self.killer_moves[ply][0] = move
    
    def get_killers(self, ply: int) -> List[Optional[str]]:
        """获取杀手着法"""
        with self._lock:
            if 0 <= ply < 64:
                return self.killer_moves[ply][:]
            return [None, None]
    
    def add_history(self, move_tuple: Tuple, bonus: int) -> None:
        """添加历史着法"""
        with self._lock:
            self.history_table[move_tuple] = self.history_table.get(move_tuple, 0) + bonus
    
    def get_history(self, move_tuple: Tuple) -> int:
        """获取历史着法分数"""
        with self._lock:
            return self.history_table.get(move_tuple, 0)
    
    def clear_invalid_entries(self) -> None:
        """清理无效条目"""
        with self._lock:
            self.last_context = None
    
    def clear_all(self) -> None:
        """清理所有缓存"""
        with self._lock:
            self.tt.clear()
            self.last_context = None
            self.history_table.clear()
            self.killer_moves = [[None, None] for _ in range(64)]


class PonderState(Enum):
    IDLE = 0
    PONDERING = 1
    HIT = 2
    MISS = 3


class PonderManager:
    """Ponder 管理"""
    
    def __init__(self):
        self._state = PonderState.IDLE
        self._ponder_move: Optional[str] = None
        self._ponder_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._result: Optional[Tuple[str, int]] = None
        self._lock = threading.Lock()
        self._enabled = False
    
    def configure(self, enabled: bool) -> None:
        """配置 Ponder"""
        self._enabled = enabled
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    @property
    def state(self) -> PonderState:
        return self._state
    
    def start_ponder(self, board, ponder_move: str, 
                     search_func, time_limit: float = 1.0) -> None:
        """开始后台思考"""
        if not self._enabled:
            return
        
        with self._lock:
            if self._state == PonderState.PONDERING:
                return
            
            self._ponder_move = ponder_move
            self._stop_event.clear()
            self._state = PonderState.PONDERING
            self._result = None
        
        def ponder_worker():
            try:
                board_copy = board.copy()
                move = chess.Move.from_uci(ponder_move)
                board_copy.push(move)
                
                result = search_func(board_copy, time_limit)
                
                with self._lock:
                    if not self._stop_event.is_set():
                        self._result = result
            except Exception:
                pass
        
        self._ponder_thread = threading.Thread(target=ponder_worker, daemon=True)
        self._ponder_thread.start()
    
    def stop_ponder(self) -> None:
        """停止后台思考"""
        with self._lock:
            self._stop_event.set()
            self._state = PonderState.IDLE
        
        if self._ponder_thread is not None and self._ponder_thread.is_alive():
            self._ponder_thread.join(timeout=0.5)
    
    def ponderhit(self) -> Optional[Tuple[str, int]]:
        """对手走进预测分支，返回结果"""
        with self._lock:
            if self._state != PonderState.PONDERING:
                return None
            
            self._state = PonderState.HIT
            return self._result
    
    def pondermiss(self) -> None:
        """对手偏离预测，丢弃结果"""
        with self._lock:
            self._state = PonderState.MISS
            self._result = None
    
    def is_pondering(self) -> bool:
        """是否正在后台思考"""
        return self._state == PonderState.PONDERING


class TimeManager:
    """时间管理器"""
    
    def __init__(self):
        self._context_cache: Optional[SearchContextCache] = None
        self._complexity_factor = 1.0
        self._endgame_factor = 1.0
    
    def set_context_cache(self, cache: SearchContextCache) -> None:
        """设置上下文缓存"""
        self._context_cache = cache
    
    def compute_time(self, 
                     remaining: float,
                     increment: float,
                     move_number: int,
                     moves_to_go: int = 0,
                     is_repeated_position: bool = False,
                     is_endgame: bool = False,
                     legal_moves_count: int = 30) -> Tuple[float, float]:
        """计算时间预算
        
        Returns:
            (optimal_time, max_time)
        """
        if moves_to_go > 0:
            base_time = remaining / moves_to_go
        else:
            if move_number <= 10:
                estimated_moves = 40 - move_number
                time_fraction = 0.5
            elif move_number <= 20:
                estimated_moves = 30
                time_fraction = 0.8
            elif move_number <= 40:
                estimated_moves = max(15, 50 - move_number)
                time_fraction = 1.0
            else:
                estimated_moves = max(10, 60 - move_number)
                time_fraction = 1.2
            
            base_time = remaining / estimated_moves + increment * 0.85
            base_time *= time_fraction
        
        if is_repeated_position and self._context_cache:
            context = self._context_cache.get_context("")
            if context:
                base_time *= 0.7
        
        complexity_factor = 1.0
        if legal_moves_count > 35:
            complexity_factor = 1.3
        elif legal_moves_count > 25:
            complexity_factor = 1.15
        elif legal_moves_count < 15:
            complexity_factor = 0.85
        
        if is_endgame:
            complexity_factor *= 1.1
        
        optimal = base_time * complexity_factor
        optimal = min(optimal, remaining * 0.5)
        optimal = max(optimal, 0.05)
        
        if increment > 0:
            optimal = max(optimal, increment * 0.9)
        
        max_time = min(remaining * 0.6, optimal * 5)
        
        return optimal, max_time
    
    def get_book_exit_bonus(self, base_time: float, 
                            was_in_book: bool) -> float:
        """获取出书后的额外时间"""
        if was_in_book:
            return base_time * 0.1
        return 0.0


class ContextManager:
    """上下文管理器 - 统一管理搜索上下文、Ponder 和时间"""
    
    def __init__(self, 
                 tt_size: int = 1000000,
                 ponder_enabled: bool = False):
        self.cache = SearchContextCache(max_tt_size=tt_size)
        self.ponder = PonderManager()
        self.time_manager = TimeManager()
        
        self.ponder.configure(ponder_enabled)
        self.time_manager.set_context_cache(self.cache)
    
    def configure(self, 
                  tt_size: int = 1000000,
                  ponder_enabled: bool = False,
                  context_expire_time: float = 30.0) -> None:
        """配置上下文管理器"""
        self.cache = SearchContextCache(max_tt_size=tt_size)
        self.cache._expire_time = context_expire_time
        self.ponder.configure(ponder_enabled)
        self.time_manager.set_context_cache(self.cache)
    
    def new_game(self) -> None:
        """新游戏时重置"""
        self.cache.clear_all()
        self.ponder.stop_ponder()
    
    def after_search(self, 
                     board,
                     best_move: str,
                     ponder_move: Optional[str],
                     score: int,
                     depth: int,
                     nodes: int,
                     pv: List[str],
                     candidate_moves: List[Tuple[str, int]]) -> None:
        """搜索完成后保存上下文"""
        context = SearchContext(
            root_fen=board.fen(),
            best_move=best_move,
            ponder_move=ponder_move,
            score=score,
            depth=depth,
            nodes=nodes,
            pv=pv,
            candidate_moves=candidate_moves,
            timestamp=time.time()
        )
        self.cache.save_context(context)
    
    def before_search(self, board) -> Tuple[bool, Optional[SearchContext]]:
        """搜索前检查是否可以复用上下文"""
        context = self.cache.get_context(board.fen())
        if context:
            return True, context
        return False, None
    
    def after_opponent_move(self, 
                            played_move: str,
                            expected_move: Optional[str]) -> None:
        """对手走子后更新状态"""
        if expected_move and played_move == expected_move:
            result = self.ponder.ponderhit()
            if result:
                return
        
        self.ponder.pondermiss()
        self.cache.update_after_move("", played_move)
