import ctypes
import chess
import engine_wrapper

engine_wrapper.reload_library()
lib = ctypes.CDLL('engine_core.dll', winmode=0)
lib.evaluate_fen.argtypes = [ctypes.c_char_p]
lib.evaluate_fen.restype = ctypes.c_int

board = chess.Board('1r3k1r/ppp2ppp/1bnqpn2/3pNb2/3P1P2/2P3P1/PP1NP1BP/R1B1QRK1 b - - 6 11')
board.push(chess.Move.from_uci('c6d4'))
board.push(chess.Move.from_uci('c3d4'))
board.push(chess.Move.from_uci('b6d4'))

print(f'After Nxd4 cxd4 Bxd4+ eval: {lib.evaluate_fen(board.fen().encode())}')
print(f'Is check: {board.is_check()}')
print()

print("White's responses to Bxd4+:")
for move in board.legal_moves:
    san = board.san(move)
    board.push(move)
    ev = lib.evaluate_fen(board.fen().encode())
    print(f'  {move.uci()} ({san}) eval={ev}')
    board.pop()

print()
print('=== After Nxe5 fxe5 ===')
board2 = chess.Board('1r3k1r/ppp2ppp/1bnqpn2/3pNb2/3P1P2/2P3P1/PP1NP1BP/R1B1QRK1 b - - 6 11')
board2.push(chess.Move.from_uci('c6e5'))
board2.push(chess.Move.from_uci('f4e5'))
print(f'Static eval: {lib.evaluate_fen(board2.fen().encode())}')

uci, nodes = engine_wrapper.search(board2.fen(), time_limit=2.0, max_depth=10)
move = chess.Move.from_uci(uci)
print(f'Black best: {uci} ({board2.san(move)}), nodes={nodes}')

print()
print('=== After Nxd4 cxd4 Bxd4+ Kh1 ===')
board3 = chess.Board('1r3k1r/ppp2ppp/1bnqpn2/3pNb2/3P1P2/2P3P1/PP1NP1BP/R1B1QRK1 b - - 6 11')
board3.push(chess.Move.from_uci('c6d4'))
board3.push(chess.Move.from_uci('c3d4'))
board3.push(chess.Move.from_uci('b6d4'))
board3.push(chess.Move.from_uci('g1h1'))
print(f'Static eval: {lib.evaluate_fen(board3.fen().encode())}')

uci2, nodes2 = engine_wrapper.search(board3.fen(), time_limit=2.0, max_depth=10)
move2 = chess.Move.from_uci(uci2)
print(f'Black best: {uci2} ({board3.san(move2)}), nodes={nodes2}')
