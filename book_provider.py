"""
统一开局库提供者实现

支持 Polyglot .bin 和 JSON 格式的统一接口
"""
import struct
import os
import json
import random
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

try:
    import chess
except ImportError:
    chess = None


class BookMode(Enum):
    OFF = "off"
    INTERNAL = "internal"
    GENERIC = "generic"
    HYBRID = "hybrid"


@dataclass
class BookMove:
    uci: str
    weight: int = 1
    score: int = 0
    learn: int = 0


@dataclass
class BookEntry:
    key: int
    moves: List[BookMove]


POLYGLOT_RANDOMS = None


def _init_polyglot_randoms():
    global POLYGLOT_RANDOMS
    if POLYGLOT_RANDOMS is not None:
        return
    
    POLYGLOT_RANDOMS = []
    rng_state = 0xD9348E5E5A5A5A5A
    
    def next_random():
        nonlocal rng_state
        rng_state ^= (rng_state >> 12) & 0xFFFFFFFFFFFFFFFF
        rng_state ^= (rng_state << 25) & 0xFFFFFFFFFFFFFFFF
        rng_state ^= (rng_state >> 27) & 0xFFFFFFFFFFFFFFFF
        return (rng_state * 0x2545F4914F6CDD1D) & 0xFFFFFFFFFFFFFFFF
    
    for _ in range(1851):
        POLYGLOT_RANDOMS.append(next_random())


def polyglot_hash(board) -> int:
    """计算 Polyglot 哈希"""
    if chess is None:
        raise ImportError("python-chess is required")
    
    _init_polyglot_randoms()
    h = 0
    
    piece_map = {
        chess.PAWN: 0, chess.KNIGHT: 1, chess.BISHOP: 2,
        chess.ROOK: 3, chess.QUEEN: 4, chess.KING: 5
    }
    
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece:
            piece_idx = piece_map[piece.piece_type]
            if piece.color == chess.BLACK:
                piece_idx += 6
            idx = 64 * piece_idx + square
            h ^= POLYGLOT_RANDOMS[idx]
    
    castling = board.castling_rights
    castling_idx = 0
    if castling & chess.BB_H1:
        castling_idx |= 1
    if castling & chess.BB_A1:
        castling_idx |= 2
    if castling & chess.BB_H8:
        castling_idx |= 4
    if castling & chess.BB_A8:
        castling_idx |= 8
    if castling_idx:
        h ^= POLYGLOT_RANDOMS[768 + castling_idx - 1]
    
    if board.ep_square is not None:
        ep_file = chess.square_file(board.ep_square)
        h ^= POLYGLOT_RANDOMS[772 + ep_file]
    
    if board.turn == chess.BLACK:
        h ^= POLYGLOT_RANDOMS[780]
    
    return h


def _decode_polyglot_move(encoded: int) -> str:
    """解码 Polyglot 编码的着法"""
    from_sq = encoded & 0x3F
    to_sq = (encoded >> 6) & 0x3F
    promo_code = (encoded >> 12) & 0x7
    
    from_str = chr(ord('a') + (from_sq & 7)) + chr(ord('1') + (from_sq >> 3))
    to_str = chr(ord('a') + (to_sq & 7)) + chr(ord('1') + (to_sq >> 3))
    
    promo_map = {1: 'n', 2: 'b', 3: 'r', 4: 'q'}
    promo_str = promo_map.get(promo_code, '')
    
    return from_str + to_str + promo_str


class BookProvider(ABC):
    """统一开局库提供者抽象接口"""
    
    @abstractmethod
    def load(self, path: str) -> bool:
        pass
    
    @abstractmethod
    def lookup(self, board) -> Optional[BookEntry]:
        pass
    
    @abstractmethod
    def select_move(self, board, 
                    randomness: float = 0.0,
                    min_score: int = -9999,
                    max_ply: int = 100,
                    current_ply: int = 0) -> Optional[str]:
        pass
    
    @abstractmethod
    def close(self) -> None:
        pass
    
    @property
    @abstractmethod
    def loaded(self) -> bool:
        pass
    
    @property
    @abstractmethod
    def entry_count(self) -> int:
        pass


class PolyglotBookProvider(BookProvider):
    """Polyglot .bin 格式开局库"""
    
    def __init__(self):
        self._entries: List[Tuple[int, int, int, int]] = []
        self._loaded = False
        self._path = ""
    
    def load(self, path: str) -> bool:
        if not os.path.isfile(path):
            return False
        
        try:
            with open(path, 'rb') as f:
                f.seek(0, 2)
                file_size = f.tell()
                f.seek(0, 0)
                
                if file_size % 16 != 0:
                    return False
                
                count = file_size // 16
                self._entries = []
                
                for _ in range(count):
                    key = struct.unpack('>Q', f.read(8))[0]
                    move = struct.unpack('>H', f.read(2))[0]
                    weight = struct.unpack('>H', f.read(2))[0]
                    learn = struct.unpack('>I', f.read(4))[0]
                    self._entries.append((key, move, weight, learn))
                
                self._entries.sort(key=lambda x: x[0])
                self._loaded = True
                self._path = path
                return True
        except Exception:
            return False
    
    def lookup(self, board) -> Optional[BookEntry]:
        if not self._loaded:
            return None
        
        target = polyglot_hash(board)
        
        left, right = 0, len(self._entries) - 1
        found_idx = -1
        
        while left <= right:
            mid = (left + right) // 2
            if self._entries[mid][0] < target:
                left = mid + 1
            elif self._entries[mid][0] > target:
                right = mid - 1
            else:
                found_idx = mid
                break
        
        if found_idx < 0:
            return None
        
        while found_idx > 0 and self._entries[found_idx - 1][0] == target:
            found_idx -= 1
        
        moves = []
        idx = found_idx
        while idx < len(self._entries) and self._entries[idx][0] == target:
            _, move, weight, learn = self._entries[idx]
            uci = _decode_polyglot_move(move)
            moves.append(BookMove(uci=uci, weight=weight, learn=learn))
            idx += 1
        
        return BookEntry(key=target, moves=moves)
    
    def select_move(self, board, 
                    randomness: float = 0.0,
                    min_score: int = -9999,
                    max_ply: int = 100,
                    current_ply: int = 0) -> Optional[str]:
        if not self._loaded:
            return None
        
        if current_ply >= max_ply:
            return None
        
        entry = self.lookup(board)
        if not entry or not entry.moves:
            return None
        
        if randomness <= 0:
            best = max(entry.moves, key=lambda m: m.weight)
            return best.uci
        
        total_weight = sum(m.weight for m in entry.moves)
        if total_weight <= 0:
            return None
        
        r = random.random() * total_weight
        cumulative = 0
        for move in entry.moves:
            cumulative += move.weight
            if r <= cumulative:
                return move.uci
        
        return entry.moves[0].uci
    
    def close(self) -> None:
        self._entries = []
        self._loaded = False
    
    @property
    def loaded(self) -> bool:
        return self._loaded
    
    @property
    def entry_count(self) -> int:
        return len(self._entries)


class JsonBookProvider(BookProvider):
    """JSON 格式开局库 (兼容现有 opening_book.json)"""
    
    def __init__(self):
        self._entries = {}
        self._loaded = False
        self._path = ""
    
    def _get_position_key(self, board) -> str:
        parts = board.fen().split()
        return f"{parts[0]} {parts[1]}"
    
    def load(self, path: str) -> bool:
        if not os.path.isfile(path):
            return False
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._entries = data.get('entries', {})
            self._loaded = True
            self._path = path
            return True
        except Exception:
            return False
    
    def lookup(self, board) -> Optional[BookEntry]:
        if not self._loaded:
            return None
        
        pos_key = self._get_position_key(board)
        entry = self._entries.get(pos_key)
        
        if not entry:
            return None
        
        moves = []
        moves_list = entry.get('moves', [])
        evals = entry.get('hellcopter_eval', {})
        
        for uci in moves_list:
            score = evals.get(uci, 0)
            weight = 1 if uci == entry.get('preferred') else 1
            moves.append(BookMove(uci=uci, weight=weight, score=score))
        
        return BookEntry(key=hash(pos_key), moves=moves)
    
    def select_move(self, board,
                    randomness: float = 0.0,
                    min_score: int = -9999,
                    max_ply: int = 100,
                    current_ply: int = 0) -> Optional[str]:
        if not self._loaded:
            return None
        
        if current_ply >= max_ply:
            return None
        
        entry = self.lookup(board)
        if not entry or not entry.moves:
            return None
        
        filtered = [m for m in entry.moves if m.score >= min_score]
        if not filtered:
            return None
        
        if randomness <= 0:
            best = max(filtered, key=lambda m: m.score)
            return best.uci
        
        total_weight = sum(m.weight for m in filtered)
        if total_weight <= 0:
            return None
        
        r = random.random() * total_weight
        cumulative = 0
        for move in filtered:
            cumulative += move.weight
            if r <= cumulative:
                return move.uci
        
        return filtered[0].uci
    
    def close(self) -> None:
        self._entries = {}
        self._loaded = False
    
    @property
    def loaded(self) -> bool:
        return self._loaded
    
    @property
    def entry_count(self) -> int:
        return len(self._entries)


class CombinedBookProvider(BookProvider):
    """组合多本书 (hybrid 模式)"""
    
    def __init__(self, primary: BookProvider, secondary: Optional[BookProvider] = None):
        self._primary = primary
        self._secondary = secondary
        self._loaded = False
    
    def load(self, path: str) -> bool:
        return False
    
    def load_combined(self, primary_path: str, secondary_path: Optional[str] = None) -> bool:
        success = self._primary.load(primary_path)
        
        if secondary_path and self._secondary:
            self._secondary.load(secondary_path)
        
        self._loaded = success
        return success
    
    def lookup(self, board) -> Optional[BookEntry]:
        entry = self._primary.lookup(board)
        if entry:
            return entry
        
        if self._secondary:
            return self._secondary.lookup(board)
        
        return None
    
    def select_move(self, board,
                    randomness: float = 0.0,
                    min_score: int = -9999,
                    max_ply: int = 100,
                    current_ply: int = 0) -> Optional[str]:
        move = self._primary.select_move(board, randomness, min_score, max_ply, current_ply)
        if move:
            return move
        
        if self._secondary:
            return self._secondary.select_move(board, randomness, min_score, max_ply, current_ply)
        
        return None
    
    def close(self) -> None:
        self._primary.close()
        if self._secondary:
            self._secondary.close()
        self._loaded = False
    
    @property
    def loaded(self) -> bool:
        return self._loaded
    
    @property
    def entry_count(self) -> int:
        count = self._primary.entry_count
        if self._secondary:
            count += self._secondary.entry_count
        return count


class BookManager:
    """开局库管理器
    
    CCRL 规则：比赛时不允许自带 book，必须使用外部通用书
    - 比赛模式：BookMode.GENERIC，使用外部书如 draw.ctg, 5moves.ctg
    - 日常模式：BookMode.INTERNAL 或 HYBRID，可使用引擎自有书
    """
    
    def __init__(self):
        self._provider: Optional[BookProvider] = None
        self._mode = BookMode.INTERNAL
        self._own_book = True
        self._max_ply = 20
        self._randomness = 0.0
        self._min_score = -9999
        self._exit_bonus_time = 0.1
        self._book_exit_position = None
        self._tournament_mode = False
    
    def set_tournament_mode(self, enabled: bool) -> None:
        """设置比赛模式
        
        CCRL 规则：比赛模式下强制使用外部通用书，禁用引擎私有书优势
        """
        self._tournament_mode = enabled
        if enabled and self._mode != BookMode.GENERIC:
            self._mode = BookMode.GENERIC
    
    def configure(self,
                  mode: str = "internal",
                  own_book: bool = True,
                  book_path: str = "",
                  max_ply: int = 20,
                  randomness: float = 0.0,
                  min_score: int = -9999,
                  exit_bonus_time: float = 0.1,
                  tournament_mode: bool = False) -> bool:
        """配置开局库
        
        Args:
            mode: 书模式 (off/internal/generic/hybrid)
            own_book: 是否使用自有书 (比赛模式下会被强制禁用)
            book_path: 开局库路径
            max_ply: 最大书步数
            randomness: 随机度 [0, 1]
            min_score: 最低分数阈值
            exit_bonus_time: 出书后额外时间比例
            tournament_mode: 比赛模式 (强制使用外部通用书)
        """
        self._tournament_mode = tournament_mode
        
        if tournament_mode:
            self._mode = BookMode.GENERIC
            self._own_book = False
        else:
            self._mode = BookMode(mode)
            self._own_book = own_book
        
        self._max_ply = max_ply
        self._randomness = randomness
        self._min_score = min_score
        self._exit_bonus_time = exit_bonus_time
        
        if self._mode == BookMode.OFF:
            if self._provider:
                self._provider.close()
            self._provider = None
            return True
        
        base_path = os.path.dirname(os.path.abspath(__file__))
        
        if self._mode == BookMode.INTERNAL:
            if self._tournament_mode:
                return False
            path = book_path or os.path.join(base_path, "dist", "book.bin")
            self._provider = PolyglotBookProvider()
            return self._provider.load(path)
        
        elif self._mode == BookMode.GENERIC:
            path = book_path
            if not path:
                return False
            self._provider = PolyglotBookProvider()
            return self._provider.load(path)
        
        elif self._mode == BookMode.HYBRID:
            if self._tournament_mode:
                return False
            internal_path = os.path.join(base_path, "dist", "book.bin")
            generic_path = book_path
            
            primary = PolyglotBookProvider()
            secondary = PolyglotBookProvider() if generic_path else None
            
            self._provider = CombinedBookProvider(primary, secondary)
            return self._provider.load_combined(internal_path, generic_path)
        
        return False
    
    def get_book_move(self, board, current_ply: int = 0) -> Optional[str]:
        """获取开局库着法"""
        if self._mode == BookMode.OFF:
            return None
        
        if not self._provider or not self._provider.loaded:
            return None
        
        if current_ply >= self._max_ply:
            return None
        
        move = self._provider.select_move(
            board,
            randomness=self._randomness,
            min_score=self._min_score,
            max_ply=self._max_ply,
            current_ply=current_ply
        )
        
        if move is None and self._book_exit_position is None:
            self._book_exit_position = board.fen()
        
        return move
    
    def get_exit_bonus_time(self, base_time: float) -> float:
        """获取出书后的额外时间"""
        if self._book_exit_position is None:
            return 0.0
        
        bonus = base_time * self._exit_bonus_time
        self._book_exit_position = None
        return bonus
    
    @property
    def mode(self) -> BookMode:
        return self._mode
    
    @property
    def loaded(self) -> bool:
        return self._provider is not None and self._provider.loaded
    
    @property
    def entry_count(self) -> int:
        if self._provider:
            return self._provider.entry_count
        return 0
