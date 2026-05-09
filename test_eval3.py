import ctypes
import chess
import engine_wrapper

engine_wrapper.reload_library()
lib = ctypes.CDLL('engine_core.dll', winmode=0)

lib.debug_root_moves.argtypes = [ctypes.c_char_p, ctypes.c_int, 
    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), 
    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
lib.debug_root_moves.restype = None

lib.eval_move_score.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_double, ctypes.c_int]
lib.eval_move_score.restype = ctypes.c_int

lib.evaluate_fen.argtypes = [ctypes.c_char_p]
lib.evaluate_fen.restype = ctypes.c_int

fen = b'1r3k1r/ppp2ppp/1bnqpn2/3pNb2/3P1P2/2P3P1/PP1NP1BP/R1B1QRK1 b - - 6 11'
fen_str = '1r3k1r/ppp2ppp/1bnqpn2/3pNb2/3P1P2/2P3P1/PP1NP1BP/R1B1QRK1 b - - 6 11'

sq = lambda f, r: f + r * 8
c6 = sq(2, 5)
e5 = sq(4, 4)
d4 = sq(3, 3)

print('=== eval_move_score comparison ===')
for depth in [4, 5, 6, 7, 8]:
    s_nxe5 = lib.eval_move_score(fen, c6, e5, 30.0, depth)
    s_nxd4 = lib.eval_move_score(fen, c6, d4, 30.0, depth)
    diff = s_nxe5 - s_nxd4
    better = 'Nxe5' if diff > 0 else 'Nxd4'
    print(f'Depth {depth}: Nxe5={s_nxe5}, Nxd4={s_nxd4}, diff={diff:+d} ({better} better)')

print()
print('=== Full search (2s time limit) ===')
board = chess.Board(fen_str)
for i in range(5):
    uci, nodes = engine_wrapper.search(fen_str, time_limit=2.0, max_depth=10)
    move = chess.Move.from_uci(uci)
    san = board.san(move)
    print(f'  Run {i+1}: {uci} ({san}), nodes={nodes}')

print()
print('=== Root moves at depth 6 ===')
out_scores = (ctypes.c_int * 64)()
out_from = (ctypes.c_int * 64)()
out_to = (ctypes.c_int * 64)()
out_count = ctypes.c_int(0)

lib.debug_root_moves(fen, 6, out_scores, out_from, out_to, ctypes.byref(out_count))

sq_to_str = lambda sq: chr(ord('a') + (sq & 7)) + chr(ord('1') + (sq >> 3))
moves_data = []
for i in range(min(out_count.value, 64)):
    frm = sq_to_str(out_from[i])
    to = sq_to_str(out_to[i])
    moves_data.append((out_scores[i], frm, to))

moves_data.sort(key=lambda x: -x[0])
for score, frm, to in moves_data[:15]:
    print(f'  {frm}{to}: {score}')

# Key position static evals
print()
print('=== Key position static evals ===')
fen_nxd4 = b'1r3k1r/ppp2ppp/1b1qpn2/3pNb2/3n1P2/2P3P1/PP1NP1BP/R1B1QRK1 w - - 0 12'
fen_nxe5 = b'1r3k1r/ppp2ppp/1b1qpn2/3pnb2/3P1P2/2P3P1/PP1NP1BP/R1B1QRK1 w - - 0 12'
fen_nxf7 = b'1r3k1r/ppp2Npp/1b1qpn2/3p1b2/3n1P2/2P3P1/PP1NP1BP/R1B1QRK1 b - - 0 12'
fen_cxd4_bxd4 = b'1r3k1r/ppp2ppp/3qpn2/3pNb2/3b1P2/6P1/PP1NP1BP/R1B1QRK1 w - - 0 13'
fen_nxe5_fxe5 = b'1r3k1r/ppp2ppp/1b1qpn2/3pPb2/3P4/2P3P1/PP1NP1BP/R1B1QRK1 b - - 0 12'

print(f'After Nxd4: {lib.evaluate_fen(fen_nxd4)}')
print(f'After Nxe5: {lib.evaluate_fen(fen_nxe5)}')
print(f'After Nxf7: {lib.evaluate_fen(fen_nxf7)}')
print(f'After cxd4 Bxd4+: {lib.evaluate_fen(fen_cxd4_bxd4)}')
print(f'After Nxe5 fxe5: {lib.evaluate_fen(fen_nxe5_fxe5)}')
