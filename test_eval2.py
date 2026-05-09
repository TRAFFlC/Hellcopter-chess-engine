import ctypes
import chess
import engine_wrapper

engine_wrapper.reload_library()
lib = ctypes.CDLL('engine_core.dll', winmode=0)

lib.debug_root_moves.argtypes = [ctypes.c_char_p, ctypes.c_int, 
    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), 
    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
lib.debug_root_moves.restype = None

lib.evaluate_fen.argtypes = [ctypes.c_char_p]
lib.evaluate_fen.restype = ctypes.c_int

# After Nxd4, white root moves
fen_nxd4 = b'1r3k1r/ppp2ppp/1b1qpn2/3pNb2/3n1P2/2P3P1/PP1NP1BP/R1B1QRK1 w - - 0 12'

out_scores = (ctypes.c_int * 64)()
out_from = (ctypes.c_int * 64)()
out_to = (ctypes.c_int * 64)()
out_count = ctypes.c_int(0)

lib.debug_root_moves(fen_nxd4, 5, out_scores, out_from, out_to, ctypes.byref(out_count))

sq_to_str = lambda sq: chr(ord('a') + (sq & 7)) + chr(ord('1') + (sq >> 3))
moves_data = []
for i in range(min(out_count.value, 64)):
    frm = sq_to_str(out_from[i])
    to = sq_to_str(out_to[i])
    moves_data.append((out_scores[i], frm, to))

moves_data.sort(key=lambda x: -x[0])
print('After Nxd4, white root moves (depth 5):')
for score, frm, to in moves_data[:10]:
    print(f'  {frm}{to}: {score}')

# Static evals of key positions
print()
print('Static evals:')
print(f'  After Nxd4: {lib.evaluate_fen(fen_nxd4)}')

fen_nxf7 = b'1r3k1r/ppp2Npp/1b1qpn2/3p1b2/3n1P2/2P3P1/PP1NP1BP/R1B1QRK1 b - - 0 12'
print(f'  After Nxf7: {lib.evaluate_fen(fen_nxf7)}')

# Full tactical sequence
board = chess.Board('1r3k1r/ppp2ppp/1bnqpn2/3pNb2/3P1P2/2P3P1/PP1NP1BP/R1B1QRK1 b - - 6 11')
board.push(chess.Move.from_uci('c6d4'))
board.push(chess.Move.from_uci('e5f7'))
board.push(chess.Move.from_uci('d4c2'))
board.push(chess.Move.from_uci('g1h1'))
board.push(chess.Move.from_uci('c2e1'))
board.push(chess.Move.from_uci('f7d6'))
fen_final = board.fen().encode()
print(f'  After Nxd4 Nxf7 Nc2+ Kh1 Nxe1 Nxd6: {lib.evaluate_fen(fen_final)}')
print(f'    FEN: {board.fen()}')

# After Nxe5 fxe5
board2 = chess.Board('1r3k1r/ppp2ppp/1bnqpn2/3pNb2/3P1P2/2P3P1/PP1NP1BP/R1B1QRK1 b - - 6 11')
board2.push(chess.Move.from_uci('c6e5'))
board2.push(chess.Move.from_uci('f4e5'))
fen_nxe5_fxe5 = board2.fen().encode()
print(f'  After Nxe5 fxe5: {lib.evaluate_fen(fen_nxe5_fxe5)}')
print(f'    FEN: {board2.fen()}')

# What about Nxd4 cxd4 Bxd4+ ?
board3 = chess.Board('1r3k1r/ppp2ppp/1bnqpn2/3pNb2/3P1P2/2P3P1/PP1NP1BP/R1B1QRK1 b - - 6 11')
board3.push(chess.Move.from_uci('c6d4'))
board3.push(chess.Move.from_uci('c3d4'))
board3.push(chess.Move.from_uci('b6d4'))
fen_bxd4 = board3.fen().encode()
print(f'  After Nxd4 cxd4 Bxd4+: {lib.evaluate_fen(fen_bxd4)}')
print(f'    FEN: {board3.fen()}')
