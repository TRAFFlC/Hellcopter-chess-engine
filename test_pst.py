import ctypes
import os

dll_path = os.path.join(os.path.dirname(__file__), "engine_core.dll")
engine = ctypes.CDLL(dll_path)

engine.evaluate_fen.argtypes = [ctypes.c_char_p]
engine.evaluate_fen.restype = ctypes.c_int

engine.load_params_from_file.argtypes = [ctypes.c_char_p]
engine.load_params_from_file.restype = ctypes.c_int

engine.load_params_from_file(b"engine_params.json")

print("=" * 60)
print("PST 评估测试")
print("=" * 60)

fens = [
    ("初始局面", b"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
    ("1.e4 后", b"rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"),
    ("1.a4 后", b"rnbqkbnr/pppppppp/8/8/P7/8/1PPPPPPP/RNBQKBNR b KQkq a3 0 1"),
    ("1.d4 后", b"rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq d3 0 1"),
    ("1.c4 后", b"rnbqkbnr/pppppppp/8/8/2P5/8/PP1PPPPP/RNBQKBNR b KQkq c3 0 1"),
]

for name, fen in fens:
    score = engine.evaluate_fen(fen)
    print(f"{name}: 评估 = {score}")
