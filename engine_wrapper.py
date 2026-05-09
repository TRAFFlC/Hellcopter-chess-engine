import ctypes
import os
import sys
import platform
import logging

EXPECTED_ENGINE_VERSION = 20260511


class Move(ctypes.Structure):
    _fields_ = [
        ("from_sq", ctypes.c_int),
        ("to_sq", ctypes.c_int),
        ("promotion", ctypes.c_int),
        ("capture", ctypes.c_int),
        ("score", ctypes.c_int),
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


def _get_dll_path() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    system = platform.system()
    if system == "Windows":
        dll_name = "engine_core.dll"
    elif system == "Linux":
        dll_name = "engine_core.so"
    elif system == "Darwin":
        dll_name = "engine_core.dylib"
    else:
        dll_name = "engine_core.so"
    return os.path.join(script_dir, dll_name)


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
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.c_int,
    ]
    lib.find_best_move_c.restype = Move

    lib.compute_hash_from_fen.argtypes = [ctypes.c_char_p]
    lib.compute_hash_from_fen.restype = ctypes.c_uint64

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


def _ensure_loaded():
    global _lib
    if _lib is None:
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
           position_history: list | None = None) -> tuple[str, int]:
    _ensure_loaded()
    nodes = ctypes.c_int(0)

    hist_array = None
    hist_count = 0
    if position_history:
        hist_count = len(position_history)
        hist_array = (ctypes.c_uint64 * hist_count)(*position_history)

    move = _lib.find_best_move_c(
        fen.encode("utf-8"),
        ctypes.c_double(time_limit),
        ctypes.c_int(max_depth),
        ctypes.byref(nodes),
        hist_array,
        ctypes.c_int(hist_count),
    )
    uci = _move_to_uci(move)
    return uci, nodes.value


def is_loaded() -> bool:
    return _lib is not None


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
