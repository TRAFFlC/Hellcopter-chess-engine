import ctypes
import os
import sys
import platform
import logging
import threading

EXPECTED_ENGINE_VERSION = 20260511


class Move(ctypes.Structure):
    _fields_ = [
        ("from_sq", ctypes.c_int),
        ("to_sq", ctypes.c_int),
        ("promotion", ctypes.c_int),
        ("capture", ctypes.c_int),
        ("score", ctypes.c_int),
    ]


class LMR_Stats(ctypes.Structure):
    _fields_ = [
        ("reductions", ctypes.c_int),
        ("re_searches", ctypes.c_int),
        ("nodes_saved", ctypes.c_int),
    ]


class Pruning_Stats(ctypes.Structure):
    _fields_ = [
        ("prunes", ctypes.c_int),
        ("nodes_saved", ctypes.c_int),
    ]


class SearchProfile(ctypes.Structure):
    _fields_ = [
        ("eval_calls", ctypes.c_longlong),
        ("qs_calls", ctypes.c_longlong),
        ("make_move_calls", ctypes.c_longlong),
        ("unmake_move_calls", ctypes.c_longlong),
        ("nmp_triggered", ctypes.c_longlong),
        ("nmp_cutoffs", ctypes.c_longlong),
        ("rfp_triggered", ctypes.c_longlong),
        ("lmr_applied", ctypes.c_longlong),
        ("lmr_full_research", ctypes.c_longlong),
        ("futility_pruned", ctypes.c_longlong),
        ("razoring_triggered", ctypes.c_longlong),
        ("lmp_pruned", ctypes.c_longlong),
        ("see_pruned", ctypes.c_longlong),
        ("history_pruned", ctypes.c_longlong),
        ("probcut_triggered", ctypes.c_longlong),
        ("probcut_cutoffs", ctypes.c_longlong),
        ("tt_hits", ctypes.c_longlong),
        ("tt_stores", ctypes.c_longlong),
        ("total_nodes", ctypes.c_longlong),
        ("qs_nodes", ctypes.c_longlong),
    ]


def _sq_to_algebraic(sq: int) -> str:
    file = sq & 7
    rank = sq >> 3
    return chr(ord("a") + file) + chr(ord("1") + rank)


def _move_to_uci(move: Move) -> str:
    uci = _sq_to_algebraic(move.from_sq) + _sq_to_algebraic(move.to_sq)
    if move.promotion:
        promo_map = {2: "n", 3: "b", 4: "r", 5: "q"}
        uci += promo_map.get(move.promotion, "")
    return uci


def _get_base_path() -> str:
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def _get_dll_path() -> str:
    env_path = os.environ.get("HELLCOPTER_DLL_PATH")
    if env_path:
        return env_path
    base = _get_base_path()
    system = platform.system()
    if system == "Windows":
        dll_name = "engine_core.dll"
    elif system == "Linux":
        dll_name = "engine_core.so"
    elif system == "Darwin":
        dll_name = "engine_core.dylib"
    else:
        dll_name = "engine_core.so"
    return os.path.join(base, dll_name)


def _load_library():
    dll_path = _get_dll_path()
    if not os.path.exists(dll_path):
        raise FileNotFoundError(
            f"引擎共享库未找到: {dll_path}\n"
            f"请先运行 build_engine.py 编译 C 引擎。"
        )

    system = platform.system()
    if system == "Windows":
        lib = ctypes.CDLL(dll_path, winmode=0)
    else:
        lib = ctypes.CDLL(dll_path)

    lib.find_best_move_c.argtypes = [
        ctypes.c_char_p,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.c_int,
    ]
    lib.find_best_move_c.restype = Move

    lib.find_best_move_smp.argtypes = [
        ctypes.c_char_p,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.c_int,
    ]
    lib.find_best_move_smp.restype = Move

    lib.compute_hash_from_fen.argtypes = [ctypes.c_char_p]
    lib.compute_hash_from_fen.restype = ctypes.c_uint64

    lib.get_lmr_stats.argtypes = []
    lib.get_lmr_stats.restype = LMR_Stats

    lib.get_pruning_stats.argtypes = []
    lib.get_pruning_stats.restype = Pruning_Stats

    lib.evaluate_fen.argtypes = [ctypes.c_char_p]
    lib.evaluate_fen.restype = ctypes.c_int

    lib.debug_root_moves.argtypes = [
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]
    lib.debug_root_moves.restype = None

    lib.debug_print_board.argtypes = [ctypes.c_char_p]
    lib.debug_print_board.restype = None

    lib.perft.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.perft.restype = ctypes.c_uint64

    lib.add_blunder_entry.argtypes = [
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    lib.add_blunder_entry.restype = None

    lib.clear_blunder_memory.argtypes = []
    lib.clear_blunder_memory.restype = None

    lib.load_blunder_memory.argtypes = [
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_int,
    ]
    lib.load_blunder_memory.restype = None

    lib.set_engine_abort.argtypes = [ctypes.c_int]
    lib.set_engine_abort.restype = None

    lib.get_last_search_info.argtypes = [ctypes.c_int]
    lib.get_last_search_info.restype = ctypes.c_int

    lib.board_consistency_check.argtypes = [ctypes.c_char_p]
    lib.board_consistency_check.restype = ctypes.c_int

    lib.perft_divide.argtypes = [
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_uint64),
    ]
    lib.perft_divide.restype = ctypes.c_int

    lib.see_test.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
    lib.see_test.restype = ctypes.c_int

    lib.eval_consistency_stress.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.eval_consistency_stress.restype = ctypes.c_int

    lib.set_search_param.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.set_search_param.restype = ctypes.c_int

    lib.get_search_param.argtypes = [ctypes.c_char_p]
    lib.get_search_param.restype = ctypes.c_int

    lib.reload_params.argtypes = [ctypes.c_char_p]
    lib.reload_params.restype = ctypes.c_int

    lib.clear_global_tt.argtypes = []
    lib.clear_global_tt.restype = None

    lib.get_search_profile.argtypes = []
    lib.get_search_profile.restype = SearchProfile

    lib.reset_search_profile.argtypes = []
    lib.reset_search_profile.restype = None

    try:
        lib.init_syzygy_c.argtypes = [ctypes.c_char_p]
        lib.init_syzygy_c.restype = ctypes.c_int
    except AttributeError:
        pass

    try:
        lib.get_engine_version.argtypes = []
        lib.get_engine_version.restype = ctypes.c_int
        ver = lib.get_engine_version()
        if ver != EXPECTED_ENGINE_VERSION:
            logging.warning(
                f"引擎版本不匹配! 期望={EXPECTED_ENGINE_VERSION}, 实际={ver}. "
                f"请重新编译引擎!"
            )
    except AttributeError:
        logging.warning("引擎缺少版本检查函数，可能是旧版本DLL，请重新编译!")

    return lib


_lib = None
_load_lock = threading.Lock()


def _ensure_loaded():
    global _lib
    if _lib is None:
        with _load_lock:
            if _lib is None:  # double-check
                _lib = _load_library()


def get_version() -> int:
    _ensure_loaded()
    try:
        return _lib.get_engine_version()
    except AttributeError:
        return 0


def compute_hash(fen: str) -> int:
    _ensure_loaded()
    return _lib.compute_hash_from_fen(fen.encode("utf-8"))


def search(fen: str, time_limit: float, max_depth: int,
           position_history: list | None = None, use_smp: bool = False,
           time_left: float = 0.0, increment: float = 0.0,
           moves_to_go: int = 0, move_number: int = 0) -> tuple[str, int]:
    _ensure_loaded()
    nodes = ctypes.c_int(0)

    hist_array = None
    hist_count = 0
    if position_history:
        hist_count = len(position_history)
        hist_array = (ctypes.c_uint64 * hist_count)(*position_history)

    search_func = _lib.find_best_move_smp if use_smp else _lib.find_best_move_c
    move = search_func(
        fen.encode("utf-8"),
        ctypes.c_double(time_limit),
        ctypes.c_double(time_left),
        ctypes.c_double(increment),
        ctypes.c_int(moves_to_go),
        ctypes.c_int(move_number),
        ctypes.c_int(max_depth),
        ctypes.byref(nodes),
        hist_array,
        ctypes.c_int(hist_count),
    )
    uci = _move_to_uci(move)
    return uci, nodes.value


def evaluate_fen(fen: str) -> int:
    _ensure_loaded()
    return _lib.evaluate_fen(fen.encode("utf-8"))


def search_with_score(fen: str, time_limit: float, max_depth: int,
                      position_history: list | None = None,
                      use_smp: bool = False,
                      time_left: float = 0.0, increment: float = 0.0,
                      moves_to_go: int = 0, move_number: int = 0) -> tuple[str, int, int]:
    _ensure_loaded()
    nodes = ctypes.c_int(0)

    hist_array = None
    hist_count = 0
    if position_history:
        hist_count = len(position_history)
        hist_array = (ctypes.c_uint64 * hist_count)(*position_history)

    search_func = _lib.find_best_move_smp if use_smp else _lib.find_best_move_c
    move = search_func(
        fen.encode("utf-8"),
        ctypes.c_double(time_limit),
        ctypes.c_double(time_left),
        ctypes.c_double(increment),
        ctypes.c_int(moves_to_go),
        ctypes.c_int(move_number),
        ctypes.c_int(max_depth),
        ctypes.byref(nodes),
        hist_array,
        ctypes.c_int(hist_count),
    )
    uci = _move_to_uci(move)
    return uci, move.score, nodes.value


def init() -> bool:
    try:
        _ensure_loaded()
        return True
    except Exception as e:
        logging.error(f"引擎初始化失败: {e}")
        return False


def is_loaded() -> bool:
    return _lib is not None


def debug_root_moves(fen: str, depth: int = 1) -> list:
    _ensure_loaded()
    scores = (ctypes.c_int * 64)()
    from_sqs = (ctypes.c_int * 64)()
    to_sqs = (ctypes.c_int * 64)()
    count = ctypes.c_int()
    
    _lib.debug_root_moves(
        fen.encode("utf-8"),
        ctypes.c_int(depth),
        scores,
        from_sqs,
        to_sqs,
        ctypes.byref(count),
    )
    
    result = []
    for i in range(count.value):
        from_sq = from_sqs[i]
        to_sq = to_sqs[i]
        from_str = _sq_to_algebraic(from_sq)
        to_str = _sq_to_algebraic(to_sq)
        result.append({
            "move": f"{from_str}{to_str}",
            "score": scores[i],
        })
    return result


def debug_print_board(fen: str) -> None:
    _ensure_loaded()
    _lib.debug_print_board(fen.encode("utf-8"))


def reload_library():
    global _lib
    if _lib is not None and platform.system() == "Windows":
        try:
            handle = getattr(_lib, '_handle', None)
            if handle:
                kernel32 = ctypes.windll.kernel32
                kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
                kernel32.FreeLibrary.restype = ctypes.c_int
                kernel32.FreeLibrary(handle)
        except Exception:
            pass
    _lib = None
    _ensure_loaded()
    ver = get_version()
    logging.info(f"引擎DLL已重载, 版本={ver}")


def get_lmr_stats() -> dict:
    """Get LMR statistics from the last search."""
    _ensure_loaded()
    stats = _lib.get_lmr_stats()
    return {
        'reductions': stats.reductions,
        're_searches': stats.re_searches,
        'nodes_saved': stats.nodes_saved,
    }


def get_last_search_info(what: int) -> int:
    """Get last search info.
    
    what: 0 = depth, 1 = nodes, 2 = score, 100+ = per-depth nodes
    """
    _ensure_loaded()
    return _lib.get_last_search_info(what)


def get_pruning_stats() -> dict:
    """Get Futility Pruning statistics from last search."""
    _ensure_loaded()
    stats = _lib.get_pruning_stats()
    return {
        'prunes': stats.prunes,
        'nodes_saved': stats.nodes_saved,
    }


def get_engine_version() -> int:
    """Get the engine version number."""
    _ensure_loaded()
    return _lib.get_engine_version()


def perft(fen: str, depth: int) -> int:
    """Calculate perft value for a position at given depth.
    
    Perft (performance test) counts the number of leaf nodes at a given depth,
    used to verify move generation correctness.
    
    Args:
        fen: FEN string of the position
        depth: Search depth (0 = 1 node, 1 = number of legal moves, etc.)
    
    Returns:
        Number of leaf nodes at the given depth
    """
    _ensure_loaded()
    return _lib.perft(fen.encode("utf-8"), ctypes.c_int(depth))


def board_consistency_check(fen: str) -> int:
    """Run make/unmake consistency check on all legal moves of a position.

    Checks hash, pawn_hash, phase, npm, king_sq, mailbox, PST+material
    after each make_move, and verifies full restoration after unmake_move.

    Args:
        fen: FEN string of the position to test

    Returns:
        Number of errors found (0 = all clean)
    """
    _ensure_loaded()
    return _lib.board_consistency_check(fen.encode("utf-8"))


def perft_divide(fen: str, depth: int) -> list:
    """Get per-move perft counts for isolating move generation bugs.

    Args:
        fen: FEN string of the position
        depth: Search depth

    Returns:
        List of dicts: [{'from': int, 'to': int, 'promo': int, 'count': int}, ...]
        Plus 'total' key in the last element or returned separately.
    """
    _ensure_loaded()
    FROM = (ctypes.c_int * 256)()
    TO = (ctypes.c_int * 256)()
    PROMO = (ctypes.c_int * 256)()
    COUNT = (ctypes.c_uint64 * 256)()
    TOTAL = ctypes.c_uint64(0)

    n = _lib.perft_divide(
        fen.encode("utf-8"),
        ctypes.c_int(depth),
        FROM, TO, PROMO, COUNT,
        ctypes.byref(TOTAL),
    )

    result = []
    for i in range(n):
        result.append({
            'from': FROM[i],
            'to': TO[i],
            'promo': PROMO[i],
            'count': COUNT[i],
        })
    return result, TOTAL.value


def see_test(fen: str, from_sq: int, to_sq: int) -> int:
    """Compute SEE (Static Exchange Evaluation) for a move.

    Args:
        fen: FEN string
        from_sq: source square (0-63)
        to_sq: destination square (0-63)

    Returns:
        SEE score in centipawns
    """
    _ensure_loaded()
    return _lib.see_test(fen.encode("utf-8"), from_sq, to_sq)


def eval_consistency_stress(fen: str, cycles: int = 100) -> int:
    """Stress test: repeated make/unmake on all legal moves.

    Runs `cycles` iterations of make+unmake on every legal move,
    checking that mg_score, eg_score, hash, pawn_hash, phase, and npm
    are perfectly restored each time.

    Args:
        fen: FEN string
        cycles: number of make/unmake cycles

    Returns:
        Number of errors found (0 = all clean)
    """
    _ensure_loaded()
    return _lib.eval_consistency_stress(fen.encode("utf-8"), cycles)


def set_search_param(name: str, value: int) -> bool:
    """Set a search parameter toggle (for ablation testing).

    Args:
        name: parameter name (e.g. 'rfp_enabled', 'nmp_enabled', etc.)
        value: 0 to disable, 1 to enable

    Returns:
        True if the parameter was found and set
    """
    _ensure_loaded()
    return bool(_lib.set_search_param(name.encode("utf-8"), value))


def get_search_param(name: str) -> int:
    """Get current value of a search parameter toggle.

    Args:
        name: parameter name

    Returns:
        Parameter value, or -1 if unknown
    """
    _ensure_loaded()
    return _lib.get_search_param(name.encode("utf-8"))


def reload_params(path: str) -> bool:
    """Reload engine parameters from a JSON file.

    Args:
        path: path to the JSON config file

    Returns:
        True if successful
    """
    _ensure_loaded()
    return bool(_lib.reload_params(path.encode("utf-8")))


def get_search_profile(total_nodes: int | None = None) -> dict:
    """Get search profile counters from the last search.
    
    Args:
        total_nodes: total nodes searched (from search() return). If None,
                     uses the struct's total_nodes field (may be 0).
    
    Returns dict with raw counters and derived metrics:
    - lmr_research_rate: lmr_full_research / lmr_applied (lower = better)
    - nmp_efficiency: nmp_cutoffs / nmp_triggered (higher = better)
    - qs_share: qs_nodes / total_nodes (high = weak in tactics)
    - tt_activity: tt_hits / (tt_hits + tt_stores) (higher = better)
    """
    _ensure_loaded()
    p = _lib.get_search_profile()
    total = total_nodes if total_nodes is not None else (p.total_nodes if p.total_nodes > 0 else 1)
    return {
        "eval_calls": p.eval_calls,
        "qs_calls": p.qs_calls,
        "make_move_calls": p.make_move_calls,
        "unmake_move_calls": p.unmake_move_calls,
        "nmp_triggered": p.nmp_triggered,
        "nmp_cutoffs": p.nmp_cutoffs,
        "rfp_triggered": p.rfp_triggered,
        "lmr_applied": p.lmr_applied,
        "lmr_full_research": p.lmr_full_research,
        "futility_pruned": p.futility_pruned,
        "razoring_triggered": p.razoring_triggered,
        "lmp_pruned": p.lmp_pruned,
        "see_pruned": p.see_pruned,
        "history_pruned": p.history_pruned,
        "probcut_triggered": p.probcut_triggered,
        "probcut_cutoffs": p.probcut_cutoffs,
        "tt_hits": p.tt_hits,
        "tt_stores": p.tt_stores,
        "total_nodes": total,
        "qs_nodes": p.qs_nodes,
        "lmr_research_rate": p.lmr_full_research / max(p.lmr_applied, 1),
        "nmp_efficiency": p.nmp_cutoffs / max(p.nmp_triggered, 1),
        "qs_share": p.qs_nodes / total,
        "tt_activity": p.tt_hits / max(p.tt_hits + p.tt_stores, 1),
    }


def reset_search_profile():
    """Reset all search profile counters to zero."""
    _ensure_loaded()
    _lib.reset_search_profile()


def tt_clear_global():
    """Clear the global transposition table."""
    _ensure_loaded()
    _lib.clear_global_tt()


def _algebraic_to_sq(sq_str: str) -> int:
    file = ord(sq_str[0]) - ord("a")
    rank = int(sq_str[1]) - 1
    return rank * 8 + file


def add_blunder_entry(fen: str, bad_from: int, bad_to: int,
                      good_from: int, good_to: int) -> None:
    _ensure_loaded()
    _lib.add_blunder_entry(
        fen.encode("utf-8"),
        ctypes.c_int(bad_from),
        ctypes.c_int(bad_to),
        ctypes.c_int(good_from),
        ctypes.c_int(good_to),
    )


def clear_blunder_memory() -> None:
    _ensure_loaded()
    _lib.clear_blunder_memory()


def set_engine_abort(flag: int = 1) -> None:
    _ensure_loaded()
    _lib.set_engine_abort(flag)


def init_syzygy(path: str) -> int:
    _ensure_loaded()
    try:
        result = _lib.init_syzygy_c(path.encode("utf-8"))
        return result
    except (AttributeError, OSError):
        return 0


def load_blunder_memory_from_file(blunder_memory_path: str) -> None:
    import json
    _ensure_loaded()
    with open(blunder_memory_path, "r") as f:
        data = json.load(f)
    _lib.clear_blunder_memory()
    for entry in data.get("entries", []):
        fen = entry["fen"]
        bad_move = entry["bad_move"]
        good_move = entry["good_move"]
        bad_from = _algebraic_to_sq(bad_move[:2])
        bad_to = _algebraic_to_sq(bad_move[2:4])
        good_from = _algebraic_to_sq(good_move[:2])
        good_to = _algebraic_to_sq(good_move[2:4])
        _lib.add_blunder_entry(
            fen.encode("utf-8"),
            ctypes.c_int(bad_from),
            ctypes.c_int(bad_to),
            ctypes.c_int(good_from),
            ctypes.c_int(good_to),
        )


if __name__ == "__main__":
    try:
        uci_move, nodes = search(
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            time_limit=1.0,
            max_depth=6,
        )
        print(f"最佳走法: {uci_move}, 节点数: {nodes}")
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
