import chess

fen = '1r3k1r/ppp2ppp/1bnqpn2/3pNb2/3P1P2/2P3P1/PP1NP1BP/R1B1QRK1 b - - 6 11'

def count_material(b):
    white_mat = 0
    black_mat = 0
    for sq in chess.SQUARES:
        p = b.piece_at(sq)
        if p:
            val = {1:100, 2:300, 3:320, 4:480, 5:900, 6:20000}[p.piece_type]
            if p.color == chess.WHITE:
                white_mat += val
            else:
                black_mat += val
    return white_mat, black_mat

board0 = chess.Board(fen)
w0, b0 = count_material(board0)
print(f'Original: White={w0}, Black={b0}, Diff={b0-w0}')

# Line 1: Nxd4 Nxf7 Nc2+ Kh1 Nxe1 Nxd6
board = chess.Board(fen)
board.push(chess.Move.from_uci('c6d4'))
board.push(chess.Move.from_uci('e5f7'))
board.push(chess.Move.from_uci('d4c2'))
board.push(chess.Move.from_uci('g1h1'))
board.push(chess.Move.from_uci('c2e1'))
nxd6 = chess.Move.from_uci('f7d6')
print(f'Nxd6 legal: {nxd6 in board.legal_moves}')
if nxd6 in board.legal_moves:
    board.push(nxd6)
w, b = count_material(board)
print(f'Nxd4 Nxf7 Nc2+ Kh1 Nxe1 Nxd6: White={w}, Black={b}, Diff={b-w}')
print(f'  FEN: {board.fen()}')

# Line 2: Nxe5 fxe5
board2 = chess.Board(fen)
board2.push(chess.Move.from_uci('c6e5'))
board2.push(chess.Move.from_uci('f4e5'))
w2, b2 = count_material(board2)
print(f'\nNxe5 fxe5: White={w2}, Black={b2}, Diff={b2-w2}')
print(f'  FEN: {board2.fen()}')

# Line 3: Nxd4 cxd4 Bxd4+
board3 = chess.Board(fen)
board3.push(chess.Move.from_uci('c6d4'))
board3.push(chess.Move.from_uci('c3d4'))
board3.push(chess.Move.from_uci('b6d4'))
print(f'\nNxd4 cxd4 Bxd4+ check: {board3.is_check()}')
w3, b3 = count_material(board3)
print(f'Nxd4 cxd4 Bxd4+: White={w3}, Black={b3}, Diff={b3-w3}')
print(f'  White responses:')
for move in board3.legal_moves:
    print(f'    {move.uci()} ({board3.san(move)})')

# Line 4: Nxd4 Nxf7 Nc2+ - what if white plays differently?
board4 = chess.Board(fen)
board4.push(chess.Move.from_uci('c6d4'))
board4.push(chess.Move.from_uci('e5f7'))
board4.push(chess.Move.from_uci('d4c2'))
print(f'\nAfter Nc2+ check, white responses:')
for move in board4.legal_moves:
    print(f'  {move.uci()} ({board4.san(move)})')

# What about Nxe5 and white doesn't play fxe5?
board5 = chess.Board(fen)
board5.push(chess.Move.from_uci('c6e5'))
print(f'\nAfter Nxe5, white responses (top):')
moves = list(board5.legal_moves)
for move in moves[:20]:
    print(f'  {move.uci()} ({board5.san(move)})')

# Check: after Nxd4, what is white's BEST response according to Stockfish-level analysis?
# Nxf7 forks Qd6 and Rh8, but Nc2+ is discovered check
# The key question: is Nxf7 actually good for white?
print('\n=== Critical analysis ===')
print('After Nxd4 Nxf7:')
print('  White knight on f7 attacks: d6(Q), d8, e5, g5, h6, h8(R)')
print('  Black can play Nc2+ (discovered check from Bb6)')
print('  After Nc2+ Kh1 Nxe1 Nxd6: queens traded, material roughly equal')
print()
print('After Nxe5 fxe5:')
print('  Knights traded, black positionally better (open f-file, e5 pawn target)')
print('  Material: equal (knight for knight)')
