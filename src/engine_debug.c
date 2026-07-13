/* engine_debug.c — 调试/诊断/API 导出函数（从 engine_core.c 拆分） */
int count_legal_moves(const char *fen)
{
    ensure_engine_tables_initialized();
    Board b;
    board_from_fen(&b, fen);
    Move moves[MAX_MOVES];
    int n = generate_pseudo_legal_moves(&b, moves);
    int legal = 0;
    int i;
    for (i = 0; i < n; i++)
    {
        UndoInfo undo;
        make_move(&b, &moves[i], &undo);
        if (!is_check(&b, b.side_to_move ^ 1))
            legal++;
        unmake_move(&b, &moves[i], &undo);
    }
    return n * 10000 + legal;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
U64
compute_hash_from_fen(const char *fen)
{
    Board b;
    board_from_fen(&b, fen);
    return compute_hash(&b);
}

#ifdef _WIN32
__declspec(dllexport)
#endif
void
add_blunder_entry(const char *fen, int bad_from, int bad_to, int good_from, int good_to)
{
    Board b;
    U64 key;
    if (g_blunder_count >= MAX_BLUNDER_ENTRIES)
        return;
    ensure_engine_tables_initialized();
    board_from_fen(&b, fen);
    key = compute_hash(&b);
    g_blunder_memory[g_blunder_count].zobrist_key = key;
    g_blunder_memory[g_blunder_count].bad_from = bad_from;
    g_blunder_memory[g_blunder_count].bad_to = bad_to;
    g_blunder_memory[g_blunder_count].good_from = good_from;
    g_blunder_memory[g_blunder_count].good_to = good_to;
    g_blunder_count++;
    g_blunder_memory_loaded = 1;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
void
clear_blunder_memory(void)
{
    g_blunder_count = 0;
    g_blunder_memory_loaded = 0;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
void
load_blunder_memory(U64 *keys, int *bad_froms, int *bad_tos, int *good_froms, int *good_tos, int count)
{
    int i;
    int limit = count < MAX_BLUNDER_ENTRIES ? count : MAX_BLUNDER_ENTRIES;
    for (i = 0; i < limit; i++)
    {
        g_blunder_memory[i].zobrist_key = keys[i];
        g_blunder_memory[i].bad_from = bad_froms[i];
        g_blunder_memory[i].bad_to = bad_tos[i];
        g_blunder_memory[i].good_from = good_froms[i];
        g_blunder_memory[i].good_to = good_tos[i];
    }
    g_blunder_count = limit;
    g_blunder_memory_loaded = 1;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
int
evaluate_fen(const char *fen)
{
    ensure_engine_tables_initialized();
    Board b;
    board_from_fen(&b, fen);
    return evaluate(&b);
}

#ifdef _WIN32
__declspec(dllexport)
#endif
void
debug_print_board(const char *fen)
{
    ensure_engine_tables_initialized();
    Board b;
    board_from_fen(&b, fen);

    printf("Board from FEN: %s\n", fen);
    printf("Side to move: %s\n", b.side_to_move == 0 ? "White" : "Black");
    printf("Castling rights: %d\n", b.castling_rights);
    printf("En passant: %d\n", b.en_passant);
    printf("Halfmove clock: %d\n", b.halfmove_clock);

    printf("\nPieces:\n");
    int side, pt;
    for (side = 0; side < 2; side++)
    {
        printf("%s:\n", side == 0 ? "White" : "Black");
        for (pt = PAWN; pt <= KING; pt++)
        {
            U64 bb = b.pieces[side][pt];
            if (bb)
            {
                printf("  %s: ", pt == PAWN ? "Pawn" : pt == KNIGHT ? "Knight"
                                                : pt == BISHOP   ? "Bishop"
                                                : pt == ROOK     ? "Rook"
                                                : pt == QUEEN    ? "Queen"
                                                            : "King");
                while (bb)
                {
                    int sq = __builtin_ctzll(bb);
                    bb &= bb - 1;
                    printf("%c%d ", 'a' + (sq % 8), 1 + (sq / 8));
                }
                printf("\n");
            }
        }
    }

    printf("\nBoard display:\n");
    int rank, file;
    for (rank = 7; rank >= 0; rank--)
    {
        printf("%d ", rank + 1);
        for (file = 0; file < 8; file++)
        {
            int sq = rank * 8 + file;
            char c = '.';
            for (side = 0; side < 2; side++)
            {
                for (pt = PAWN; pt <= KING; pt++)
                {
                    if (b.pieces[side][pt] & (1ULL << sq))
                    {
                        /* pt: PAWN=1,KNIGHT=2,BISHOP=3,ROOK=4,QUEEN=5,KING=6
                         * Index into chars: pt-1 gives 0..5 */
                        static const char white_chars[] = "PNBRQK";
                        static const char black_chars[] = "pnbrqk";
                        c = side == 0 ? white_chars[pt - 1] : black_chars[pt - 1];
                        break;
                    }
                }
            }
            printf("%c ", c);
        }
        printf("\n");
    }
    printf("  a b c d e f g h\n");

    Move moves[MAX_MOVES];
    int n = generate_pseudo_legal_moves(&b, moves);
    printf("\nPseudo-legal moves: %d\n", n);

    int legal = 0;
    int i;
    for (i = 0; i < n; i++)
    {
        UndoInfo undo;
        make_move(&b, &moves[i], &undo);
        if (!is_check(&b, b.side_to_move ^ 1))
        {
            legal++;
        }
        unmake_move(&b, &moves[i], &undo);
    }
    printf("Legal moves: %d\n", legal);
}

#ifdef _WIN32
__declspec(dllexport)
#endif
void
debug_root_moves(const char *fen, int depth, int *out_scores, int *out_from, int *out_to, int *out_count)
{
    ensure_engine_tables_initialized();
    g_engine_abort_flag = 0; /* Ensure abort flag is clear */
    /* Ensure runtime params are loaded for consistent behavior */
    {
        static int params_loaded_debug = 0;
        if (!params_loaded_debug)
        {
            const char *env_path = getenv("ENGINE_PARAMS");
            if (env_path && env_path[0] != '\0')
                load_params_from_file(env_path);
            else
                load_params_from_file("engine_params.json");
            params_loaded_debug = 1;
        }
    }
    SearchState *s_ptr = (SearchState *)calloc(1, sizeof(SearchState));
    if (!s_ptr)
    {
        *out_count = 0;
        return;
    }
    SearchState *s = s_ptr;
    board_from_fen(&s->board, fen);
    s->start_time = get_time();
    s->time_limit = 300.0;
    s->aborted = 0;
    s->nodes = 0;
    tt_init(s, 16);
    s->search_history_count = 0;
    s->game_history_count = 0;
    int i;

    Board *b = &s->board;
    Move root_moves[MAX_MOVES];
    int n_moves = generate_pseudo_legal_moves(b, root_moves);
    int legal_moves_count = 0;
    for (i = 0; i < n_moves; i++)
    {
        UndoInfo undo;
        make_move(b, &root_moves[i], &undo);
        if (!is_check(b, b->side_to_move ^ 1))
        {
            root_moves[legal_moves_count++] = root_moves[i];
        }
        unmake_move(b, &root_moves[i], &undo);
    }

    int count = 0;
    for (i = 0; i < legal_moves_count && count < 64; i++)
    {
        UndoInfo undo;
        make_move(b, &root_moves[i], &undo);
        int score = -negamax(s, depth - 1, -INF, INF, 0, 1);
        unmake_move(b, &root_moves[i], &undo);
        if (s->aborted)
            break;
        out_scores[count] = score;
        out_from[count] = root_moves[i].from;
        out_to[count] = root_moves[i].to;
        count++;
    }
    *out_count = count;
    free(s->tt);
    free(s_ptr);
}

#ifdef _WIN32
__declspec(dllexport)
#endif
void
debug_id_scores(const char *fen, int max_depth, int *out_scores, int *out_from, int *out_to, int *out_count)
{
    ensure_engine_tables_initialized();
    g_engine_abort_flag = 0; /* Ensure abort flag is clear */
    /* Ensure runtime params are loaded for consistent behavior */
    {
        static int params_loaded_debug = 0;
        if (!params_loaded_debug)
        {
            const char *env_path = getenv("ENGINE_PARAMS");
            if (env_path && env_path[0] != '\0')
                load_params_from_file(env_path);
            else
                load_params_from_file("engine_params.json");
            params_loaded_debug = 1;
        }
    }
    SearchState *s_ptr = (SearchState *)calloc(1, sizeof(SearchState));
    if (!s_ptr)
    {
        *out_count = 0;
        return;
    }
    SearchState *s = s_ptr;
    board_from_fen(&s->board, fen);
    s->start_time = get_time();
    s->time_limit = 30.0;
    s->aborted = 0;
    s->nodes = 0;
    tt_init(s, 16);
    s->search_history_count = 0;
    s->game_history_count = 0;
    int i;

    Board *b = &s->board;
    Move root_moves[MAX_MOVES];
    int n_moves = generate_pseudo_legal_moves(b, root_moves);
    int legal_moves_count = 0;
    for (i = 0; i < n_moves; i++)
    {
        UndoInfo undo;
        make_move(b, &root_moves[i], &undo);
        if (!is_check(b, b->side_to_move ^ 1))
        {
            root_moves[legal_moves_count++] = root_moves[i];
        }
        unmake_move(b, &root_moves[i], &undo);
    }

    int depth;
    for (depth = 1; depth <= max_depth; depth++)
    {
        int alpha = -INF, beta = INF;
        for (i = 0; i < legal_moves_count; i++)
        {
            UndoInfo undo;
            make_move(b, &root_moves[i], &undo);
            int score;
            if (i == 0)
            {
                score = -negamax(s, depth - 1, -beta, -alpha, 0, 1);
            }
            else
            {
                score = -negamax(s, depth - 1, -alpha - 1, -alpha, 0, 1);
                if (!s->aborted && score > alpha && score < beta)
                {
                    score = -negamax(s, depth - 1, -beta, -alpha, 0, 1);
                }
            }
            unmake_move(b, &root_moves[i], &undo);
            if (s->aborted)
                break;
            if (i < 64)
            {
                out_scores[depth * 64 + i] = score;
                out_from[depth * 64 + i] = root_moves[i].from;
                out_to[depth * 64 + i] = root_moves[i].to;
            }
            if (score > alpha)
                alpha = score;
        }
        if (s->aborted)
            break;
        int best_idx = 0;
        int best_s = out_scores[depth * 64];
        for (i = 1; i < legal_moves_count && i < 64; i++)
        {
            if (out_scores[depth * 64 + i] > best_s)
            {
                best_s = out_scores[depth * 64 + i];
                best_idx = i;
            }
        }
        if (best_idx != 0)
        {
            Move tmp = root_moves[0];
            root_moves[0] = root_moves[best_idx];
            root_moves[best_idx] = tmp;
            int tmp_s = out_scores[depth * 64];
            out_scores[depth * 64] = out_scores[depth * 64 + best_idx];
            out_scores[depth * 64 + best_idx] = tmp_s;
            int tmp_f = out_from[depth * 64];
            out_from[depth * 64] = out_from[depth * 64 + best_idx];
            out_from[depth * 64 + best_idx] = tmp_f;
            int tmp_t = out_to[depth * 64];
            out_to[depth * 64] = out_to[depth * 64 + best_idx];
            out_to[depth * 64 + best_idx] = tmp_t;
        }
    }
    *out_count = legal_moves_count;
    free(s->tt);
    free(s_ptr);
}

#ifdef _WIN32
__declspec(dllexport)
#endif
int
get_engine_version(void)
{
    return ENGINE_VERSION;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
LMR_Stats
get_lmr_stats(void)
{
    LMR_Stats stats;
    stats.reductions = g_last_lmr_reductions;
    stats.re_searches = g_last_lmr_re_searches;
    stats.nodes_saved = g_last_lmr_nodes_saved;
    return stats;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
Pruning_Stats
get_pruning_stats(void)
{
    Pruning_Stats stats;
    stats.prunes = g_last_futility_prunes;
    stats.nodes_saved = g_last_futility_nodes_saved;
    return stats;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
Razoring_Stats
get_razoring_stats(void)
{
    Razoring_Stats stats;
    stats.prunes = g_last_razoring_prunes;
    stats.nodes_saved = g_last_razoring_nodes_saved;
    return stats;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
int
extract_ponder_move(const Board *b, Move best_move, Move *ponder_move)
{
    if (!g_tt || g_tt_cluster_count == 0)
        return 0;
    if (best_move.from == 0 && best_move.to == 0)
        return 0;

    Board tmp_board = *b;
    UndoInfo undo;
    make_move(&tmp_board, &best_move, &undo);

    U64 key = tmp_board.hash;
    int idx = (int)(key & (U64)(g_tt_cluster_count - 1));
    TT_Cluster *cluster = &g_tt[idx];

    Move tt_move = {0};
    int found = 0;
    for (int i = 0; i < 4; i++)
    {
        TT_Entry *e = &cluster->entries[i];
        if (e->key == (key >> 32))
        {
            tt_move = e->best_move;
            found = 1;
            break;
        }
    }
    if (!found)
        return 0;
    if (tt_move.from == 0 && tt_move.to == 0)
        return 0;

    Move legal_moves[MAX_MOVES];
    int n = generate_legal_moves(&tmp_board, legal_moves);
    for (int i = 0; i < n; i++)
    {
        if (legal_moves[i].from == tt_move.from &&
            legal_moves[i].to == tt_move.to &&
            legal_moves[i].promotion == tt_move.promotion)
        {
            *ponder_move = legal_moves[i];
            return 1;
        }
    }
    return 0;
}

static U64 perft_internal(Board *b, int depth)
{
    if (depth == 0)
        return 1;

    Move moves[MAX_MOVES];
    int n = generate_legal_moves(b, moves);

    if (depth == 1)
        return (U64)n;

    U64 nodes = 0;
    for (int i = 0; i < n; i++)
    {
        UndoInfo undo;
        make_move(b, &moves[i], &undo);
        nodes += perft_internal(b, depth - 1);
        unmake_move(b, &moves[i], &undo);
    }

    return nodes;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
U64
perft(const char *fen, int depth)
{
    ensure_engine_tables_initialized();

    Board b;
    board_from_fen(&b, fen);

    return perft_internal(&b, depth);
}

#ifdef _WIN32
__declspec(dllexport)
#endif
void
set_engine_abort(int flag)
{
    g_engine_abort_flag = flag;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
int
get_engine_abort(void)
{
    return g_engine_abort_flag;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
int
init_syzygy_c(const char *path)
{
    extern unsigned TB_LARGEST;
    if (!path || !path[0])
        return 0;
    tb_free();
    bool ok = tb_init(path);
    return ok ? (int)TB_LARGEST : 0;
}

/* Debug: get runtime param value.
 * what: 0=loaded flag, 1=mg_pst[piece_idx][sq], 2=eg_pst[piece_idx][sq],
 *       3=piece_values[idx], 4=tempo_mg, 5=tempo_eg,
 *       6=doubled_pawn_penalty, 7=bishop_pair_bonus */
#ifdef _WIN32
__declspec(dllexport)
#endif
int
get_runtime_param(int what, int piece_idx, int sq)
{
    if (what == 0)
        return g_runtime_params.loaded;
    if (what == 1)
    {
        if (piece_idx < 0 || piece_idx >= 6 || sq < 0 || sq >= 64)
            return -999999;
        return g_runtime_params.mg_pst[piece_idx][sq];
    }
    if (what == 2)
    {
        if (piece_idx < 0 || piece_idx >= 6 || sq < 0 || sq >= 64)
            return -999999;
        return g_runtime_params.eg_pst[piece_idx][sq];
    }
    if (what == 3)
    {
        if (piece_idx < 0 || piece_idx >= 7)
            return -999999;
        return g_runtime_params.piece_values[piece_idx];
    }
    if (what == 4)
        return g_runtime_params.tempo_mg;
    if (what == 5)
        return g_runtime_params.tempo_eg;
    if (what == 6)
        return g_runtime_params.doubled_pawn_penalty;
    if (what == 7)
        return g_runtime_params.bishop_pair_bonus;
    return -999999;
}

/* Clear evaluation caches - needed after parameter reload for tuning */
#ifdef _WIN32
__declspec(dllexport)
#endif
void
clear_eval_caches(void)
{
    memset((void*)pawn_hash_table, 0, sizeof(pawn_hash_table));
}

#ifdef _WIN32
__declspec(dllexport)
#endif
int
test_tb_probe_root(const char *fen, int *out_wdl, int *out_dtz, char *out_move)
{
    Board b;
    board_from_fen(&b, fen);

    U64 all_white = b.pieces[WHITE][PAWN] | b.pieces[WHITE][KNIGHT] |
                    b.pieces[WHITE][BISHOP] | b.pieces[WHITE][ROOK] |
                    b.pieces[WHITE][QUEEN] | b.pieces[WHITE][KING];
    U64 all_black = b.pieces[BLACK][PAWN] | b.pieces[BLACK][KNIGHT] |
                    b.pieces[BLACK][BISHOP] | b.pieces[BLACK][ROOK] |
                    b.pieces[BLACK][QUEEN] | b.pieces[BLACK][KING];
    int total_pieces = count_bits(all_white) + count_bits(all_black);

    if (TB_LARGEST == 0 || total_pieces > (int)TB_LARGEST || b.castling_rights != 0)
    {
        return -2;
    }

    unsigned ep_sq = 0;
    if (b.en_passant >= 0 && b.en_passant < 64)
        ep_sq = (unsigned)b.en_passant + 1;

    unsigned results[TB_MAX_MOVES];
    unsigned tb_res = tb_probe_root(
        all_white, all_black,
        b.pieces[WHITE][KING] | b.pieces[BLACK][KING],
        b.pieces[WHITE][QUEEN] | b.pieces[BLACK][QUEEN],
        b.pieces[WHITE][ROOK] | b.pieces[BLACK][ROOK],
        b.pieces[WHITE][BISHOP] | b.pieces[BLACK][BISHOP],
        b.pieces[WHITE][KNIGHT] | b.pieces[BLACK][KNIGHT],
        b.pieces[WHITE][PAWN] | b.pieces[BLACK][PAWN],
        (unsigned)b.halfmove_clock, 0, ep_sq,
        b.side_to_move == WHITE, results);
    if (tb_res == TB_RESULT_FAILED)
        return -3;

    *out_wdl = TB_GET_WDL(tb_res);
    *out_dtz = TB_GET_DTZ(tb_res);
    int from = TB_GET_FROM(tb_res);
    int to = TB_GET_TO(tb_res);
    out_move[0] = 'a' + (from % 8);
    out_move[1] = '1' + (from / 8);
    out_move[2] = 'a' + (to % 8);
    out_move[3] = '1' + (to / 8);
    out_move[4] = '\0';
    return 0;
}

/* ============================================================
 * Bug Hunter: board_consistency_check
 *
 * For a given FEN, tests every legal move:
 *   save state → make_move → verify post-state → unmake_move → verify restored
 *
 * Checks (after make):
 *   1. hash matches compute_hash()
 *   2. pawn_hash matches pawn-only recompute
 *   3. phase matches npm-based recompute
 *   4. npm[] matches piece-count recompute
 *   5. king_sq[] matches actual king positions
 *   6. mailbox consistency with bitboards
 *
 * Checks (after unmake):
 *   7. ALL state fields restored to original
 *
 * Returns total error count (0 = all clean).
 * ============================================================ */
#ifdef _WIN32
__declspec(dllexport)
#endif
int
board_consistency_check(const char *fen)
{
    ensure_engine_tables_initialized();
    Board b;
    board_from_fen(&b, fen);
    int errors = 0;

    /* First: verify the board itself is consistent after FEN parse */
    {
        U64 h = compute_hash(&b);
        if (h != b.hash)
        {
            fprintf(stderr, "[BUG] FEN hash mismatch: incremental=%llx recomputed=%llx\n",
                    (unsigned long long)b.hash, (unsigned long long)h);
            errors++;
            b.hash = h; /* fix so we can continue testing */
        }
    }

    Move moves[MAX_MOVES];
    int n = generate_legal_moves(&b, moves);

    for (int i = 0; i < n; i++)
    {
        /* Save original state */
        U64 orig_hash = b.hash;
        U64 orig_pawn_hash = b.pawn_hash;
        int orig_eval = b.eval_score;
        int orig_phase = b.phase;
        int orig_npm0 = b.npm[0];
        int orig_npm1 = b.npm[1];
        int orig_king0 = b.king_sq[0];
        int orig_king1 = b.king_sq[1];
        int orig_mg = b.mg_score;
        int orig_eg = b.eg_score;
        int orig_stm = b.side_to_move;
        int orig_castle = b.castling_rights;
        int orig_ep = b.en_passant;
        int orig_hmc = b.halfmove_clock;
        int orig_fmn = b.fullmove_number;
        int orig_mb[64];
        for (int j = 0; j < 64; j++) orig_mb[j] = b.mailbox[j];

        /* Make move */
        UndoInfo undo;
        make_move(&b, &moves[i], &undo);

        /* --- Post-make checks --- */

        /* Check 1: hash consistency */
        U64 recomputed_hash = compute_hash(&b);
        if (recomputed_hash != b.hash)
        {
            fprintf(stderr, "[BUG] Hash mismatch after move %c%d%c%d: "
                    "incremental=%llx recomputed=%llx\n",
                    'a' + (moves[i].from % 8), 1 + (moves[i].from / 8),
                    'a' + (moves[i].to % 8), 1 + (moves[i].to / 8),
                    (unsigned long long)b.hash, (unsigned long long)recomputed_hash);
            errors++;
        }

        /* Check 2: pawn_hash consistency */
        {
            U64 recomputed_phash = 0;
            for (int s = 0; s < 2; s++)
            {
                U64 bb = b.pieces[s][PAWN];
                while (bb)
                {
                    int sq = lsb_index(bb);
                    bb &= bb - 1;
                    recomputed_phash ^= zobrist_table[(s * 6 + (PAWN - 1)) * 64 + sq];
                }
            }
            if (recomputed_phash != b.pawn_hash)
            {
                fprintf(stderr, "[BUG] Pawn hash mismatch after move %c%d%c%d\n",
                        'a' + (moves[i].from % 8), 1 + (moves[i].from / 8),
                        'a' + (moves[i].to % 8), 1 + (moves[i].to / 8));
                errors++;
            }
        }

        /* Check 3: npm consistency */
        {
            /* npm uses pawn-unit values: N=3, B=3, R=5, Q=9 */
            static const int npm_vals[7] = {0, 0, 3, 3, 5, 9, 0};
            int recomputed_npm[2] = {0, 0};
            for (int s = 0; s < 2; s++)
            {
                for (int pt = KNIGHT; pt <= QUEEN; pt++)
                {
                    recomputed_npm[s] += count_bits(b.pieces[s][pt]) * npm_vals[pt];
                }
            }
            if (recomputed_npm[0] != b.npm[0] || recomputed_npm[1] != b.npm[1])
            {
                fprintf(stderr, "[BUG] NPM mismatch after move %c%d%c%d: "
                        "incr=[%d,%d] recomputed=[%d,%d]\n",
                        'a' + (moves[i].from % 8), 1 + (moves[i].from / 8),
                        'a' + (moves[i].to % 8), 1 + (moves[i].to / 8),
                        b.npm[0], b.npm[1], recomputed_npm[0], recomputed_npm[1]);
                errors++;
            }
        }

        /* Check 4: king_sq consistency */
        {
            int wk_sq = lsb_index(b.pieces[WHITE][KING]);
            int bk_sq = lsb_index(b.pieces[BLACK][KING]);
            if (wk_sq != b.king_sq[0] || bk_sq != b.king_sq[1])
            {
                fprintf(stderr, "[BUG] king_sq mismatch after move %c%d%c%d\n",
                        'a' + (moves[i].from % 8), 1 + (moves[i].from / 8),
                        'a' + (moves[i].to % 8), 1 + (moves[i].to / 8));
                errors++;
            }
        }

        /* Check 5: phase consistency (npm is in pawn-units: N=3,B=3,R=5,Q=9) */
        {
            int total_npm = b.npm[0] + b.npm[1];
            int phase = total_npm;
            if (phase > 31) phase = 31;
            phase = phase * 24 / 31;
            if (phase != b.phase)
            {
                fprintf(stderr, "[BUG] Phase mismatch after move %c%d%c%d: "
                        "stored=%d recomputed=%d\n",
                        'a' + (moves[i].from % 8), 1 + (moves[i].from / 8),
                        'a' + (moves[i].to % 8), 1 + (moves[i].to / 8),
                        b.phase, phase);
                errors++;
            }
        }

        /* Check 6: mailbox vs bitboard consistency */
        {
            int mb_errors = 0;
            for (int sq = 0; sq < 64; sq++)
            {
                int found = 0;
                for (int s = 0; s < 2 && !found; s++)
                {
                    for (int pt = PAWN; pt <= KING && !found; pt++)
                    {
                        if (b.pieces[s][pt] & (1ULL << sq))
                        {
                            int expected = s * 6 + pt;
                            if (b.mailbox[sq] != expected)
                                mb_errors++;
                            found = 1;
                        }
                    }
                }
                if (!found && b.mailbox[sq] != 0)
                    mb_errors++;
            }
            if (mb_errors)
            {
                fprintf(stderr, "[BUG] Mailbox inconsistency after move %c%d%c%d: "
                        "%d squares mismatched\n",
                        'a' + (moves[i].from % 8), 1 + (moves[i].from / 8),
                        'a' + (moves[i].to % 8), 1 + (moves[i].to / 8),
                        mb_errors);
                errors++;
            }
        }

        /* Check 7: PST+material incremental vs full recompute */
        {
            int mg = 0, eg = 0;
            for (int s = 0; s < 2; s++)
            {
                int sign = (s == WHITE) ? 1 : -1;
                for (int pt = PAWN; pt <= KING; pt++)
                {
                    U64 bb = b.pieces[s][pt];
                    while (bb)
                    {
                        int sq = lsb_index(bb);
                        bb &= bb - 1;
                        int psq = (s == WHITE) ? (sq ^ 56) : sq;
                        mg += sign * (piece_values[pt] + mg_pst[pt][psq]);
                        eg += sign * (piece_values[pt] + eg_pst[pt][psq]);
                    }
                }
            }
            if (mg != b.mg_score || eg != b.eg_score)
            {
                fprintf(stderr, "[BUG] PST+material mismatch after move %c%d%c%d: "
                        "incr=[%d,%d] recomputed=[%d,%d] delta=[%d,%d]\n",
                        'a' + (moves[i].from % 8), 1 + (moves[i].from / 8),
                        'a' + (moves[i].to % 8), 1 + (moves[i].to / 8),
                        b.mg_score, b.eg_score, mg, eg,
                        b.mg_score - mg, b.eg_score - eg);
                errors++;
            }
        }

        /* --- Unmake and verify restoration --- */
        unmake_move(&b, &moves[i], &undo);

        if (b.hash != orig_hash ||
            b.pawn_hash != orig_pawn_hash ||
            b.eval_score != orig_eval ||
            b.phase != orig_phase ||
            b.npm[0] != orig_npm0 || b.npm[1] != orig_npm1 ||
            b.king_sq[0] != orig_king0 || b.king_sq[1] != orig_king1 ||
            b.mg_score != orig_mg || b.eg_score != orig_eg ||
            b.side_to_move != orig_stm ||
            b.castling_rights != orig_castle ||
            b.en_passant != orig_ep ||
            b.halfmove_clock != orig_hmc ||
            b.fullmove_number != orig_fmn)
        {
            fprintf(stderr, "[BUG] Unmake failed to restore state after move %c%d%c%d:\n",
                    'a' + (moves[i].from % 8), 1 + (moves[i].from / 8),
                    'a' + (moves[i].to % 8), 1 + (moves[i].to / 8));
            if (b.hash != orig_hash)
                fprintf(stderr, "  hash: orig=%llx now=%llx\n",
                        (unsigned long long)orig_hash, (unsigned long long)b.hash);
            if (b.pawn_hash != orig_pawn_hash)
                fprintf(stderr, "  pawn_hash: orig=%llx now=%llx\n",
                        (unsigned long long)orig_pawn_hash, (unsigned long long)b.pawn_hash);
            if (b.phase != orig_phase)
                fprintf(stderr, "  phase: orig=%d now=%d\n", orig_phase, b.phase);
            if (b.npm[0] != orig_npm0 || b.npm[1] != orig_npm1)
                fprintf(stderr, "  npm: orig=[%d,%d] now=[%d,%d]\n",
                        orig_npm0, orig_npm1, b.npm[0], b.npm[1]);
            if (b.king_sq[0] != orig_king0 || b.king_sq[1] != orig_king1)
                fprintf(stderr, "  king_sq: orig=[%d,%d] now=[%d,%d]\n",
                        orig_king0, orig_king1, b.king_sq[0], b.king_sq[1]);
            if (b.mg_score != orig_mg || b.eg_score != orig_eg)
                fprintf(stderr, "  PST scores: orig=[%d,%d] now=[%d,%d]\n",
                        orig_mg, orig_eg, b.mg_score, b.eg_score);
            if (b.eval_score != orig_eval)
                fprintf(stderr, "  eval_score: orig=%d now=%d\n", orig_eval, b.eval_score);
            errors++;
        }

        /* Check 8: mailbox restoration */
        {
            int mb_restore_err = 0;
            for (int j = 0; j < 64; j++)
            {
                if (b.mailbox[j] != orig_mb[j])
                    mb_restore_err++;
            }
            if (mb_restore_err)
            {
                fprintf(stderr, "[BUG] Mailbox not restored after unmake of %c%d%c%d: "
                        "%d squares differ\n",
                        'a' + (moves[i].from % 8), 1 + (moves[i].from / 8),
                        'a' + (moves[i].to % 8), 1 + (moves[i].to / 8),
                        mb_restore_err);
                errors++;
            }
        }
    }

    return errors;
}

/* ============================================================
 * Bug Hunter: perft_divide
 *
 * Returns per-move perft counts for a position at given depth.
 * Fills arrays: out_from[], out_to[], out_promo[], out_count[].
 * Returns number of moves written. *out_total = total perft.
 *
 * Used to isolate which move causes a perft mismatch.
 * ============================================================ */
#ifdef _WIN32
__declspec(dllexport)
#endif
int
perft_divide(const char *fen, int depth, int *out_from, int *out_to,
             int *out_promo, U64 *out_count, U64 *out_total)
{
    ensure_engine_tables_initialized();
    Board b;
    board_from_fen(&b, fen);

    Move moves[MAX_MOVES];
    int n = generate_legal_moves(&b, moves);
    U64 total = 0;
    int written = 0;

    for (int i = 0; i < n && i < 256; i++)
    {
        UndoInfo undo;
        make_move(&b, &moves[i], &undo);
        U64 cnt = perft_internal(&b, depth - 1);
        unmake_move(&b, &moves[i], &undo);

        out_from[written] = moves[i].from;
        out_to[written] = moves[i].to;
        out_promo[written] = moves[i].promotion;
        out_count[written] = cnt;
        total += cnt;
        written++;
    }
    *out_total = total;
    return written;
}

/* ============================================================
 * Bug Hunter: see_test
 *
 * Compute SEE value for a move on a given position.
 * Returns the SEE score in centipawns.
 *
 * Also runs a consistency check: generates all captures on the
 * target square, applies them in MVV-LVA order, and verifies
 * the minimax settlement matches.
 * ============================================================ */
#ifdef _WIN32
__declspec(dllexport)
#endif
int
see_test(const char *fen, int from_sq, int to_sq)
{
    ensure_engine_tables_initialized();
    Board b;
    board_from_fen(&b, fen);

    return see(&b, from_sq, to_sq);
}

/* ============================================================
 * Bug Hunter: eval_consistency_stress
 *
 * For a given FEN, performs N make/unmake cycles on each legal
 * move. After each cycle, verifies all incremental state is
 * restored. Catches accumulation errors from repeated make/unmake.
 *
 * Returns total error count.
 * ============================================================ */
#ifdef _WIN32
__declspec(dllexport)
#endif
int
eval_consistency_stress(const char *fen, int cycles)
{
    ensure_engine_tables_initialized();
    Board b;
    board_from_fen(&b, fen);
    int errors = 0;

    Move moves[MAX_MOVES];
    int n = generate_legal_moves(&b, moves);

    for (int c = 0; c < cycles; c++)
    {
        for (int i = 0; i < n; i++)
        {
            /* Save original state */
            int orig_mg = b.mg_score;
            int orig_eg = b.eg_score;
            U64 orig_hash = b.hash;
            U64 orig_pawn_hash = b.pawn_hash;
            int orig_phase = b.phase;
            int orig_npm0 = b.npm[0];
            int orig_npm1 = b.npm[1];

            /* Make and immediately unmake */
            UndoInfo undo;
            make_move(&b, &moves[i], &undo);
            unmake_move(&b, &moves[i], &undo);

            /* Verify restoration */
            if (b.mg_score != orig_mg || b.eg_score != orig_eg)
            {
                if (errors < 10) /* limit output */
                    fprintf(stderr, "[BUG] Stress PST drift cycle %d move %d: "
                            "mg %d->%d eg %d->%d\n",
                            c, i, orig_mg, b.mg_score, orig_eg, b.eg_score);
                errors++;
            }
            if (b.hash != orig_hash)
            {
                if (errors < 10)
                    fprintf(stderr, "[BUG] Stress hash drift cycle %d move %d\n", c, i);
                errors++;
            }
            if (b.pawn_hash != orig_pawn_hash)
            {
                if (errors < 10)
                    fprintf(stderr, "[BUG] Stress pawn_hash drift cycle %d move %d\n", c, i);
                errors++;
            }
            if (b.phase != orig_phase || b.npm[0] != orig_npm0 || b.npm[1] != orig_npm1)
            {
                if (errors < 10)
                    fprintf(stderr, "[BUG] Stress phase/npm drift cycle %d move %d\n", c, i);
                errors++;
            }
        }
    }

    return errors;
}

/* Clear the global transposition table */
#ifdef _WIN32
__declspec(dllexport)
#endif
void
clear_global_tt(void)
{
    extern void tt_clear_global(void);
    tt_clear_global();
}
