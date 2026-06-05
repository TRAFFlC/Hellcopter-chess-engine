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
        for (pt = 0; pt < 6; pt++)
        {
            U64 bb = b.pieces[side][pt];
            if (bb)
            {
                printf("  %s: ", pt == 0 ? "Pawn" : pt == 1 ? "Knight"
                                                : pt == 2   ? "Bishop"
                                                : pt == 3   ? "Rook"
                                                : pt == 4   ? "Queen"
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
                for (pt = 0; pt < 6; pt++)
                {
                    if (b.pieces[side][pt] & (1ULL << sq))
                    {
                        static const char white_chars[] = "PNBRQK";
                        static const char black_chars[] = "pnbrqk";
                        c = side == 0 ? white_chars[pt] : black_chars[pt];
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
