import ctypes
import os

dll_path = os.path.join(os.path.dirname(__file__), "engine_core.dll")
engine = ctypes.CDLL(dll_path)

engine.find_best_move_c.argtypes = [
    ctypes.c_char_p, ctypes.c_double, ctypes.c_int,
    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)
]
engine.find_best_move_c.restype = None

engine.load_params_from_file.argtypes = [ctypes.c_char_p]
engine.load_params_from_file.restype = ctypes.c_int

engine.load_params_from_file(b"engine_params.json")

print("=" * 60)
print("搜索测试 (深度 1)")
print("=" * 60)

fen = b"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

from_sq = ctypes.c_int()
to_sq = ctypes.c_int()
score = ctypes.c_int()
nodes = ctypes.c_int()

engine.find_best_move_c(fen, 0.1, 1, ctypes.byref(score), ctypes.byref(from_sq), ctypes.byref(to_sq), ctypes.byref(nodes))

sq_names = 'a1b1c1d1e1f1g1h1a2b2c2d2e2f2g2h2a3b3c3d3e3f3g3h3a4b4c4d4e4f4g4h4a5b5c5d5e5f5g5h5a6b6c6d6e6f6g6h6a7b7c7d7e7f7g7h7a8b8c8d8e8f8g8h8'

def sq_to_name(sq):
    return sq_names[sq*2:sq*2+2]

print(f"最佳着法: {sq_to_name(from_sq.value)}{sq_to_name(to_sq.value)}")
print(f"分数: {score.value}")
print(f"节点数: {nodes.value}")
