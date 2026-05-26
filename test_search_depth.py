import ctypes
import os
import time

dll_path = os.path.join(os.path.dirname(__file__), "engine_core.dll")
engine = ctypes.CDLL(dll_path)

class Move(ctypes.Structure):
    _fields_ = [
        ("from_sq", ctypes.c_int),
        ("to_sq", ctypes.c_int),
        ("promotion", ctypes.c_int),
        ("capture", ctypes.c_int),
        ("score", ctypes.c_int),
    ]

engine.find_best_move_c.argtypes = [
    ctypes.c_char_p, ctypes.c_double, ctypes.c_double, ctypes.c_double,
    ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint64),
    ctypes.c_int
]
engine.find_best_move_c.restype = Move

engine.load_params_from_file.argtypes = [ctypes.c_char_p]
engine.load_params_from_file.restype = ctypes.c_int

engine.load_params_from_file(b"engine_params.json")

print("=" * 60)
print("搜索深度测试")
print("=" * 60)

test_positions = [
    ("初始局面", b"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
    ("中局", b"r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"),
    ("残局", b"8/8/8/8/8/5k2/8/4k2r w - - 0 1"),
    ("杀棋测试 (Qxf7#)", b"r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"),
]

sq_names = 'a1b1c1d1e1f1g1h1a2b2c2d2e2f2g2h2a3b3c3d3e3f3g3h3a4b4c4d4e4f4g4h4a5b5c5d5e5f5g5h5a6b6c6d6e6f6g6h6a7b7c7d7e7f7g7h7a8b8c8d8e8f8g8h8'

def sq_to_name(sq):
    return sq_names[sq*2:sq*2+2]

for name, fen in test_positions:
    nodes = ctypes.c_int()
    game_history = (ctypes.c_uint64 * 256)()
    
    start = time.perf_counter()
    move = engine.find_best_move_c(fen, 5.0, 0.0, 0.0, 0, 0, 100, ctypes.byref(nodes), game_history, 0)
    elapsed = time.perf_counter() - start
    
    move_str = sq_to_name(move.from_sq) + sq_to_name(move.to_sq)
    nps = nodes.value / elapsed if elapsed > 0 else 0
    
    print(f"\n{name}:")
    print(f"  着法: {move_str}, 分数: {move.score}")
    print(f"  节点数: {nodes.value:,}, NPS: {nps:,.0f}")
    print(f"  时间: {elapsed:.2f}s")
