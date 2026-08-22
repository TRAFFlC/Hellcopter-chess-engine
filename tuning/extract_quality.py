"""Extract quality positions from lichess broadcast zst files.
Filters: Standard variant, ELO >= 2200, classical TC (>=45min).
Unknown TC -> require ELO >= 2500.
Stores outcomes in side-to-move perspective.
"""
import os, sys, json, time, re, io, zstandard
import chess.pgn
re._compile  # ensure re loaded

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def is_classical(tc_str):
    if tc_str == '?':
        return None
    tc = tc_str.lower().replace(' ', '')
    nums = [int(n) for n in re.findall(r'\d+', tc)]
    if not nums:
        return False
    base = nums[0]
    if base >= 600:
        return base >= 2700
    return base >= 45

def parse_elo(s):
    try:
        v = int(s)
        return v if v > 0 else 0
    except:
        return 0

def extract(input_path, max_per_game=35, min_ply=8, max_ply=80):
    positions = []
    game_count = 0
    kept = 0
    skipped = {'variant': 0, 'elo': 0, 'tc': 0, 'result': 0, 'short': 0}

    dctx = zstandard.ZstdDecompressor()
    with open(input_path, 'rb') as f:
        raw = f.read()
    reader = dctx.stream_reader(io.BytesIO(raw[12:]))
    data = b''
    while True:
        chunk = reader.read(65536)
        if not chunk:
            break
        data += chunk
    reader.close()
    text = data.decode('utf-8')

    pgn_io = io.StringIO(text)
    t0 = time.time()
    while True:
        try:
            game = chess.pgn.read_game(pgn_io)
        except:
            break
        if game is None:
            break
        game_count += 1
        if game_count % 5000 == 0:
            print(f'  {game_count} games scanned, {len(positions)} kept [{time.time()-t0:.0f}s]')

        h = game.headers
        result = h.get('Result', '*')
        if result not in ('1-0', '0-1', '1/2-1/2'):
            skipped['result'] += 1
            continue

        if h.get('Variant', 'Standard') != 'Standard':
            skipped['variant'] += 1
            continue

        ew, eb = parse_elo(h.get('WhiteElo', '0')), parse_elo(h.get('BlackElo', '0'))
        min_elo = min(ew, eb)
        max_elo = max(ew, eb)
        if min_elo < 2200:
            skipped['elo'] += 1
            continue

        tc_result = is_classical(h.get('TimeControl', '?'))
        if tc_result is None:
            if max_elo < 2500:
                skipped['tc'] += 1
                continue
        elif not tc_result:
            skipped['tc'] += 1
            continue

        if result == '1-0':
            white_outcome = 1.0
        elif result == '0-1':
            white_outcome = 0.0
        else:
            white_outcome = 0.5

        board = game.board()
        taken = 0
        move_count = 0
        for move in game.mainline_moves():
            move_count += 1
            if move_count < min_ply:
                board.push(move)
                continue
            if move_count > max_ply:
                break

            board.push(move)
            # Check enough material
            material = 0
            for sq in chess.SQUARES:
                p = board.piece_at(sq)
                if p and p.piece_type != chess.KING:
                    material += 1
            if material < 2:
                continue

            fen = board.fen()
            stm = fen.split(' ')[1]
            stm_outcome = white_outcome if stm == 'w' else 1.0 - white_outcome
            positions.append((fen, stm_outcome))
            taken += 1
            if taken >= max_per_game:
                break

        kept += 1

    elapsed = time.time() - t0
    print(f'\nDone: {game_count} games, {len(positions)} positions [{elapsed:.0f}s]')
    print(f'  Kept games: {kept}')
    for k, v in skipped.items():
        print(f'  Skipped ({k}): {v}')
    return positions, game_count

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-dir', default='master')
    parser.add_argument('--output', required=True)
    parser.add_argument('--max-per-game', type=int, default=35)
    args = parser.parse_args()

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_dir = os.path.join(base, args.input_dir)

    files = sorted([f for f in os.listdir(src_dir)
                    if f.startswith('lichess_db_broadcast') and f.endswith('.zst')])

    all_positions = []
    total_games = 0
    for fn in files:
        path = os.path.join(src_dir, fn)
        print(f'\n=== {fn} ===')
        pos, ngames = extract(path, args.max_per_game)
        all_positions.extend(pos)
        total_games += ngames

    print(f'\n=== Total: {len(all_positions)} positions from {total_games} games ===')

    data = {
        'source': 'lichess_broadcast_filtered',
        'filter': 'Standard, ELO>=2200, classical TC, STM outcomes',
        'total_games': total_games,
        'total_positions': len(all_positions),
        'positions': [{'fen': p[0], 'result': p[1]} for p in all_positions],
    }
    out_path = os.path.join(base, args.output)
    with open(out_path, 'w') as f:
        json.dump(data, f)
    print(f'Saved to {out_path}')

if __name__ == '__main__':
    main()
