/* engine_search_root.c — 根搜索入口：时间管理、迭代加深、Lazy SMP（从 engine_core.c 拆分） */

/* Syzygy tablebase largest cardinality (exported from tbprobe.c via engine_debug.c) */
extern unsigned TB_LARGEST;

/* Ponder TT preservation flag: when set, find_best_move_c skips the TT generation increment
 * so that TT entries from the ponder search are retained for the ponderhit search. */
static volatile int g_preserve_tt_generation = 0;

#ifdef _WIN32
__declspec(dllexport)
#endif
void
set_preserve_tt_generation(int flag)
{
    g_preserve_tt_generation = flag;
}

/* Atomic increment of the global TT generation counter.  Each SMP worker calls
 * this once at the start of every iterative-deepening iteration so that all
 * TT writes share a single monotonic aging timeline, matching the single-
 * threaded search behaviour where s->tt_generation is advanced per iteration. */
static int smp_inc_tt_generation(void)
{
#ifdef _WIN32
    return (int)InterlockedIncrement((LONG *)&g_tt_generation);
#else
    return __atomic_add_fetch(&g_tt_generation, 1, __ATOMIC_SEQ_CST);
#endif
}

extern void set_eval_thread_id(int tid);

/* ============================================================================
 * HEURISTIC SNAPSHOT — Ponderhit context preservation (Task 4.2a)
 * ============================================================================ */
static HeuristicSnapshot g_heuristic_snapshot = {.valid = 0};
static volatile int g_preserve_heuristics = 0;

#ifdef _WIN32
__declspec(dllexport)
#endif
void
set_preserve_heuristics(int flag)
{
    g_preserve_heuristics = flag;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
void
save_heuristic_snapshot(const SearchState *s)
{
    if (!g_preserve_heuristics)
        return;
    memcpy(g_heuristic_snapshot.killers, s->killers, sizeof(s->killers));
    memcpy(g_heuristic_snapshot.history, s->history, sizeof(s->history));
    memcpy(g_heuristic_snapshot.countermove, s->countermove, sizeof(s->countermove));
    memcpy(g_heuristic_snapshot.followup, s->followup, sizeof(s->followup));
    g_heuristic_snapshot.valid = 1;
    g_preserve_heuristics = 0;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
void
restore_heuristic_snapshot(SearchState *s)
{
    if (!g_heuristic_snapshot.valid)
        return;
    memcpy(s->killers, g_heuristic_snapshot.killers, sizeof(s->killers));
    memcpy(s->history, g_heuristic_snapshot.history, sizeof(s->history));
    memcpy(s->countermove, g_heuristic_snapshot.countermove, sizeof(s->countermove));
    memcpy(s->followup, g_heuristic_snapshot.followup, sizeof(s->followup));
    g_heuristic_snapshot.valid = 0; /* One-time use */
}

/* ============================================================================
 * SMP STATISTICS (Task 6.1)
 * ============================================================================ */
static SMP_Stats g_smp_stats;

#ifdef _WIN32
__declspec(dllexport)
#endif
SMP_Stats
get_smp_stats(void)
{
    return g_smp_stats;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
void
reset_smp_stats(void)
{
    memset(&g_smp_stats, 0, sizeof(g_smp_stats));
}

/* Critical position detection: compute a 0-100 score based on 8 signals.
 * Higher score = more critical position = deserves more search time. */
static int compute_criticality_score(const TimeManager *tm, int current_score, int prev_score,
                                     int best_move_changed, int aw_fails_this_iter,
                                     long long nodes_this_iter, int legal_moves_count)
{
    int score = 0;

    /* Signal 1: Best move instability (weight 25) */
    if (best_move_changed)
        score += 25;
    else if (tm->instability_count >= 2)
        score += 12;

    /* Signal 2: Aspiration window failures (weight 20) */
    if (aw_fails_this_iter >= 3)
        score += 20;
    else if (aw_fails_this_iter >= 1)
        score += 8 + aw_fails_this_iter * 4;

    /* Signal 3: Node explosion (weight 15) */
    if (tm->nodes_last_iter > 0)
    {
        long long ratio = nodes_this_iter / (tm->nodes_last_iter + 1);
        if (ratio >= 5)
            score += 15;
        else if (ratio >= 3)
            score += 10;
        else if (ratio >= 2)
            score += 5;
    }

    /* Signal 4: Top 2 moves close (weight 10) */
    if (prev_score > -MATE_SCORE + 1000)
    {
        int top2_gap = abs(current_score - prev_score);
        if (top2_gap < 10)
            score += 10;
        else if (top2_gap < 25)
            score += 5;
    }

    /* Signal 5: Static eval vs search score divergence (weight 10) */
    {
        int divergence = abs(tm->root_eval - current_score);
        if (divergence > 150)
            score += 10;
        else if (divergence > 80)
            score += 5;
    }

    /* Signal 6: 合法走法 ≤ 3 → 强制局面（weight 20） */
    if (legal_moves_count >= 1 && legal_moves_count <= 3)
        score += 20;
    else if (legal_moves_count <= 5)
        score += 8;

    /* Signal 7: 中局相位 +10（weight 10） */
    if (!tm->is_endgame)
        score += 10;

    /* Signal 8: 战术密度 — 每个走法的平均节点数（weight 15） */
    if (legal_moves_count > 0)
    {
        long long nodes_per_move = nodes_this_iter / legal_moves_count;
        if (nodes_per_move > 5000)
            score += 15;
        else if (nodes_per_move > 2000)
            score += 8;
    }

    if (score > 100)
        score = 100;
    return score;
}

static void init_time_manager(TimeManager *tm, double time_left, double inc, int moves_to_go, int move_number, double start_time)
{
    tm->remaining = time_left;
    tm->increment = inc;
    tm->moves_to_go = moves_to_go;
    tm->move_number = move_number;
    tm->start_time = start_time;
    tm->prev_best_move_from = -1;
    tm->prev_best_move_to = -1;
    tm->prev_best_promotion = 0;
    tm->stable_count = 0;
    tm->panic_flag = 0;

    /* Initialize instability detection */
    tm->history_count = 0;
    tm->instability_count = 0;
    tm->is_endgame = 0;
    tm->endgame_factor = 1.0;
    tm->complexity_factor = 1.0;

    /* Critical position detection (Task 5) */
    tm->critical_position_flag = 0;
    tm->time_bank = 0.0;
    tm->root_eval = 0;
    tm->aw_fails_last_iter = 0;
    tm->nodes_last_iter = 0;

    for (int i = 0; i < 4; i++)
    {
        tm->score_history[i] = 0;
        tm->best_from_history[i] = -1;
        tm->best_to_history[i] = -1;
        tm->best_promo_history[i] = 0;
    }

    /* 阶段感知分配：根据 move_number 选择所在阶段，各阶段有独立预估步数 */
    int estimated_moves;
    if (moves_to_go > 0)
    {
        estimated_moves = moves_to_go;
    }
    else if (move_number <= PHASE_OPENING_MAX_MOVE)
    {
        /* 开局：预留足够步数 */
        estimated_moves = PHASE_OPENING_MOVES_REMAINING;
    }
    else if (move_number <= PHASE_MIDGAME_MAX_MOVE)
    {
        /* 中局：关键阶段，每步获得更多时间 */
        estimated_moves = PHASE_MIDGAME_MOVES_REMAINING;
    }
    else
    {
        /* 残局：保守剩余步数 */
        estimated_moves = PHASE_ENDGAME_MOVES_REMAINING;
    }

    /* Core time allocation formula:
     * optimum = time_left / estimated_moves + increment fraction
     * maximum = min(time_left × fraction, optimum × multiplier) */
    tm->optimal_time = time_left / estimated_moves + inc * OPTIMAL_TIME_INC_FRACTION_NUM / OPTIMAL_TIME_INC_FRACTION_DEN;
    tm->max_time = time_left * PHASE_BASE_MAX_TIME_FRACTION_NUM / PHASE_BASE_MAX_TIME_FRACTION_DEN;
    if (tm->max_time > tm->optimal_time * MAX_TIME_OPTIMAL_MULTIPLIER)
        tm->max_time = tm->optimal_time * MAX_TIME_OPTIMAL_MULTIPLIER;

    /* Extreme time pressure: remaining < 1 second */
    if (time_left < 1.0)
    {
        double extreme_time = time_left * EXTREME_PRESSURE_FRACTION_NUM / EXTREME_PRESSURE_FRACTION_DEN;
        if (inc > 0)
            extreme_time = inc * EXTREME_PRESSURE_INC_FRACTION_NUM / EXTREME_PRESSURE_INC_FRACTION_DEN;
        if (tm->optimal_time > extreme_time)
            tm->optimal_time = extreme_time;
        if (tm->max_time > time_left * 0.8)
            tm->max_time = time_left * 0.8;
        if (tm->max_time > time_left - (double)EXTREME_PRESSURE_SAFETY_MARGIN / 1000.0)
            tm->max_time = time_left - (double)EXTREME_PRESSURE_SAFETY_MARGIN / 1000.0;
    }

    if (tm->optimal_time < (double)MIN_OPTIMAL_TIME_MS / 1000.0)
        tm->optimal_time = (double)MIN_OPTIMAL_TIME_MS / 1000.0;
}
static int count_total_material(Board *b)
{
    static const int piece_vals[] = {0, PAWN_VALUE, KNIGHT_VALUE, BISHOP_VALUE, ROOK_VALUE, QUEEN_VALUE, 0};
    int total = 0;
    int side, pt;
    for (side = 0; side < 2; side++)
        for (pt = PAWN; pt <= QUEEN; pt++)
            total += count_bits(b->pieces[side][pt]) * piece_vals[pt];
    return total;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
Move
find_best_move_c(const char *fen, double time_limit, double time_left, double increment, int moves_to_go, int move_number, int max_depth, long long node_limit, int *out_nodes,
                 U64 *game_history, int game_history_count)
{
    static int params_loaded = 0;
    ensure_engine_tables_initialized();
    if (!params_loaded)
    {
        int loaded_ok = 0;
        const char *env_path = getenv("ENGINE_PARAMS");
        if (env_path && env_path[0] != '\0')
        {
            loaded_ok = load_params_from_file(env_path);
        }
        if (!loaded_ok)
        {
            loaded_ok = load_params_from_file("engine_params.json");
        }
        if (!loaded_ok)
        {
            init_runtime_params_defaults();
            fprintf(stderr, "Using default params: qs_mg=%d qs_eg=%d endgame_thresh=%d pst_mg_pawn_0=%d pst_eg_pawn_0=%d\n",
                    g_runtime_params.qs_max_depth_mg, g_runtime_params.qs_max_depth_eg,
                    g_runtime_params.endgame_phase_threshold,
                    g_runtime_params.mg_pst[0][0], g_runtime_params.eg_pst[0][0]);
        }
        params_loaded = 1;
    }

    SearchState *s_ptr = (SearchState *)calloc(1, sizeof(SearchState));
    if (!s_ptr)
    {
        Move zero_move = {0, 0, 0, 0, 0};
        return zero_move;
    }
    SearchState *s = s_ptr; /* Use pointer throughout */
    board_from_fen(&s->board, fen);
    s->start_time = get_time();
    s->aborted = 0;
    s->nodes = 0;
    s->node_limit = node_limit;
    s->thread_id = 0;        /* Main thread */
    extern void set_eval_thread_id(int tid);
    set_eval_thread_id(0);
    g_engine_abort_flag = 0; /* Ensure abort flag is clear before starting search */
    {
        int si;
        for (si = 0; si < 128; si++)
            s->static_eval_stack[si] = EVAL_SCORE_INVALID;
    }
    /* Restore heuristics from previous ponder search (if ponderhit path) */
    restore_heuristic_snapshot(s);

    TimeManager tm;
    init_time_manager(&tm, time_left > 0 ? time_left : time_limit, increment, moves_to_go, move_number, s->start_time);
    if (time_left <= 0)
    {
        /* When time_left is not provided, fall back to time_limit.
         * If both are zero (e.g., 'go depth N' mode), set a minimum
         * time budget to ensure at least one depth-1 search completes.
         * When max_depth is explicitly set, use a very large time limit
         * so the search is controlled by depth, not time. */
        double fallback = time_limit > 0 ? time_limit : 0.1;
        if (max_depth > 0)
            fallback = 3600.0; /* 1 hour - depth-limited search should not time out */
        tm.optimal_time = fallback;
        tm.max_time = fallback;
        tm.remaining = fallback;
    }
    s->time_limit = tm.max_time;
    s->time_check_mask = TIME_CHECK_MASK_NORMAL;
    if (tm.optimal_time < 2.0)
        s->time_check_mask = TIME_CHECK_MASK_LOW;
    else if (tm.optimal_time < 5.0)
        s->time_check_mask = TIME_CHECK_MASK_VERY_LOW;
    tt_init_global(128);
    if (g_preserve_tt_generation)
    {
        /* Ponderhit path: keep TT entries from ponder search, just sync generation */
        g_preserve_tt_generation = 0;
    }
    else
    {
        g_tt_generation++; /* 替换 tt_clear_global()，递增世代让旧条目自然老化 */
    }
    s->tt = g_tt;
    s->tt_cluster_count = g_tt_cluster_count;
    s->tt_generation = g_tt_generation;
    s->search_history_count = 0;
    s->game_history_count = 0;
    if (game_history && game_history_count > 0)
    {
        int gh_i;
        int gh_start = game_history_count > 512 ? game_history_count - 512 : 0;
        int gh_limit = game_history_count > 512 ? 512 : game_history_count;
        for (gh_i = 0; gh_i < gh_limit; gh_i++)
        {
            s->game_history[gh_i] = game_history[gh_start + gh_i];
        }
        s->game_history_count = gh_limit;
    }

    {
        /* Fix: Do NOT add root key to search_history. The root position
         * is already included in game_history (passed from Python wrapper).
         * Adding it here causes double-counting in repetition detection,
         * leading to false draw detection (total_reps >= 2 when only 2
         * occurrences exist, not the required 3 for threefold repetition). */
    }

    Move best_move = {0};
    int best_score = -MATE_SCORE;
    int prev_score = -MATE_SCORE;
    int depth;
    int i;
    int root_scores[MAX_MOVES];
    int scores_valid = 0;
    int early_terminate = 0;
    (void)early_terminate;
    for (i = 0; i < MAX_MOVES; i++)
        root_scores[i] = -MATE_SCORE;

    if (g_perturb_enabled)
        perturb_rng_seed();

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

    {
        U64 root_key = s->board.hash;
        int root_reps = 0;
        int rep_i;
        for (rep_i = 0; rep_i < s->game_history_count; rep_i++)
        {
            if (s->game_history[rep_i] == root_key)
                root_reps++;
        }
        if (root_reps >= 3 && legal_moves_count > 0)
        {
            /* Threefold repetition detected - return a legal move to avoid 0000 */
            if (out_nodes)
                *out_nodes = 0;
            Move rep_move = root_moves[0];
            free(s_ptr);
            return rep_move;
        }
    }

    if (legal_moves_count == 0)
    {
        if (out_nodes)
            *out_nodes = 0;
        free(s_ptr);
        return best_move;
    }

    if (legal_moves_count == 1)
    {
        /* Even with a single legal move, we must search to get the correct score.
         * Previously this returned immediately with score 0, which produced
         * incorrect evaluations (e.g., reporting +0.00 in forced-mate positions). */
        Move single_move = root_moves[0];
        UndoInfo undo;
        make_move(b, &single_move, &undo);
        int single_score = -negamax(s, 0, -MATE_SCORE, MATE_SCORE, 0, 1);
        unmake_move(b, &single_move, &undo);
        if (out_nodes)
            *out_nodes = s->nodes;
        single_move.score = single_score;
        g_last_best_score = single_score;
        g_last_search_depth = 1;
        free(s_ptr);
        return single_move;
    }

    // Root move ordering: sort moves for better search efficiency
    // Prioritize: captures > promotions > center moves > others
    // Conditional repetition handling:
    //   - Winning (eval > threshold): AVOID repetition (penalize repeating moves)
    //   - Losing  (eval < threshold): SEEK repetition (bonus repeating moves)
    //   - Equal: no adjustment
    int root_reps = 0;
    int root_eval = evaluate(b);
    if (b->side_to_move == BLACK)
        root_eval = -root_eval;
    tm.root_eval = root_eval;
    {
        U64 root_key = s->board.hash;
        for (int ri = 0; ri < s->game_history_count; ri++)
        {
            if (s->game_history[ri] == root_key)
                root_reps++;
        }
    }
    int move_priorities[MAX_MOVES];
    for (i = 0; i < legal_moves_count; i++)
    {
        Move *m = &root_moves[i];
        int priority = 0;

        // Captures get high priority (MVV-LVA: Most Valuable Victim - Least Valuable Attacker)
        if (m->capture)
        {
            int attacker = piece_on_square(b, m->from);
            priority += 10000 + ROOT_CAPTURE_VALUE[m->capture] - ROOT_ATTACKER_VALUE[attacker];
        }

        // Promotions
        if (m->promotion)
            priority += 5000;

        // Center squares (d4, e4, d5, e5 = index 27,28,35,36)
        int to_r = rank_of(m->to), to_f = file_of(m->to);
        if ((to_f >= 2 && to_f <= 5) && (to_r >= 2 && to_r <= 5))
            priority += 100;

        // Repetition adjustment based on evaluation:
        //   Winning (eval > 50): penalize repeating moves to avoid draw
        //   Losing  (eval < -50): bonus repeating moves to seek draw
        if (root_reps >= 1)
        {
            UndoInfo rep_undo;
            make_move(b, m, &rep_undo);
            U64 child_key = b->hash;
            int child_reps = 0;
            for (int ri = 0; ri < s->game_history_count; ri++)
            {
                if (s->game_history[ri] == child_key)
                    child_reps++;
            }
            unmake_move(b, m, &rep_undo);
            if (child_reps >= 1)
            {
                if (root_eval > REPETITION_EVAL_THRESHOLD)
                    priority -= REPETITION_SCORE; /* Winning: avoid repetition */
                else if (root_eval < -REPETITION_EVAL_THRESHOLD)
                    priority += REPETITION_SCORE; /* Losing: seek repetition */
            }
        }

        // Just to make sure order is deterministic
        priority += 63 - m->to;

        move_priorities[i] = priority;
    }

    // Simple selection sort by priority descending
    for (i = 0; i < legal_moves_count - 1; i++)
    {
        int best_idx = i;
        for (int j = i + 1; j < legal_moves_count; j++)
        {
            if (move_priorities[j] > move_priorities[best_idx])
                best_idx = j;
        }
        if (best_idx != i)
        {
            Move tmp = root_moves[i];
            root_moves[i] = root_moves[best_idx];
            root_moves[best_idx] = tmp;
            int tmp_p = move_priorities[i];
            move_priorities[i] = move_priorities[best_idx];
            move_priorities[best_idx] = tmp_p;
        }
    }

    {
        Move tt_root_move = {0};
        int tt_root_val = tt_probe(s, s->board.hash, 1, -MATE_SCORE, MATE_SCORE, &tt_root_move, 0, NULL, NULL);
        if (tt_root_move.from != 0 || tt_root_move.to != 0)
        {
            int tt_idx = -1;
            for (i = 0; i < legal_moves_count; i++)
            {
                if (root_moves[i].from == tt_root_move.from &&
                    root_moves[i].to == tt_root_move.to &&
                    root_moves[i].promotion == tt_root_move.promotion)
                {
                    tt_idx = i;
                    break;
                }
            }
            if (tt_idx > 0)
            {
                Move tmp = root_moves[0];
                root_moves[0] = root_moves[tt_idx];
                root_moves[tt_idx] = tmp;
            }
        }
    }

    if (TB_LARGEST > 0)
    {
        U64 all_white = s->board.pieces[WHITE][PAWN] | s->board.pieces[WHITE][KNIGHT] |
                        s->board.pieces[WHITE][BISHOP] | s->board.pieces[WHITE][ROOK] |
                        s->board.pieces[WHITE][QUEEN] | s->board.pieces[WHITE][KING];
        U64 all_black = s->board.pieces[BLACK][PAWN] | s->board.pieces[BLACK][KNIGHT] |
                        s->board.pieces[BLACK][BISHOP] | s->board.pieces[BLACK][ROOK] |
                        s->board.pieces[BLACK][QUEEN] | s->board.pieces[BLACK][KING];
        int total_pieces = count_bits(all_white) + count_bits(all_black);
        int w_bishops = count_bits(s->board.pieces[WHITE][BISHOP]);
        int b_bishops = count_bits(s->board.pieces[BLACK][BISHOP]);
        int w_knights = count_bits(s->board.pieces[WHITE][KNIGHT]);
        int b_knights = count_bits(s->board.pieces[BLACK][KNIGHT]);
        int root_total_pawns = count_bits(s->board.pieces[WHITE][PAWN] | s->board.pieces[BLACK][PAWN]);
        int is_kbnk = (w_bishops + b_bishops == 1 && w_knights + b_knights == 1 && root_total_pawns == 0);
        if (total_pieces <= (int)TB_LARGEST && total_pieces >= 3 && s->board.castling_rights == 0 && !is_kbnk)
        {
            unsigned ep_sq = 0;
            if (s->board.en_passant >= 0 && s->board.en_passant < 64)
                ep_sq = (unsigned)s->board.en_passant + 1;
            unsigned results[TB_MAX_MOVES];
            unsigned tb_res = tb_probe_root(
                all_white,
                all_black,
                s->board.pieces[WHITE][KING] | s->board.pieces[BLACK][KING],
                s->board.pieces[WHITE][QUEEN] | s->board.pieces[BLACK][QUEEN],
                s->board.pieces[WHITE][ROOK] | s->board.pieces[BLACK][ROOK],
                s->board.pieces[WHITE][BISHOP] | s->board.pieces[BLACK][BISHOP],
                s->board.pieces[WHITE][KNIGHT] | s->board.pieces[BLACK][KNIGHT],
                s->board.pieces[WHITE][PAWN] | s->board.pieces[BLACK][PAWN],
                (unsigned)s->board.halfmove_clock,
                0,
                ep_sq,
                s->board.side_to_move == WHITE,
                results);
            if (tb_res != TB_RESULT_FAILED)
            {
                int wdl = TB_GET_WDL(tb_res);

                /* Sanity check: if tablebase claims DRAW but material imbalance
                 * is huge, the TB file may be corrupt. Ignore and fall back to search. */
                if (wdl == TB_DRAW)
                {
                    int w_mat = count_bits(s->board.pieces[WHITE][QUEEN]) * QUEEN_VALUE +
                                count_bits(s->board.pieces[WHITE][ROOK]) * ROOK_VALUE +
                                count_bits(s->board.pieces[WHITE][BISHOP]) * BISHOP_VALUE +
                                count_bits(s->board.pieces[WHITE][KNIGHT]) * KNIGHT_VALUE;
                    int b_mat = count_bits(s->board.pieces[BLACK][QUEEN]) * QUEEN_VALUE +
                                count_bits(s->board.pieces[BLACK][ROOK]) * ROOK_VALUE +
                                count_bits(s->board.pieces[BLACK][BISHOP]) * BISHOP_VALUE +
                                count_bits(s->board.pieces[BLACK][KNIGHT]) * KNIGHT_VALUE;
                    int mat_diff = w_mat - b_mat;
                    if (s->board.side_to_move == BLACK)
                        mat_diff = -mat_diff;
                    if (mat_diff > 400)
                        goto root_tb_done;
                }

                int from_sq = TB_GET_FROM(tb_res);
                int to_sq = TB_GET_TO(tb_res);
                int promotes = TB_GET_PROMOTES(tb_res);
                int dtz = TB_GET_DTZ(tb_res);
                int tb_score;
                if (wdl == TB_WIN)
                    tb_score = 100000 - 2 * dtz;
                else if (wdl == TB_CURSED_WIN)
                    tb_score = 90000 - 2 * dtz;
                else if (wdl == TB_DRAW)
                    tb_score = 0;
                else if (wdl == TB_BLESSED_LOSS)
                    tb_score = -(90000) + 2 * dtz;
                else
                    tb_score = -(100000) + 2 * dtz;
                Move tb_move = {0};
                tb_move.from = from_sq;
                tb_move.to = to_sq;
                tb_move.score = tb_score;
                if (promotes == TB_PROMOTES_QUEEN)
                    tb_move.promotion = QUEEN;
                else if (promotes == TB_PROMOTES_ROOK)
                    tb_move.promotion = ROOK;
                else if (promotes == TB_PROMOTES_BISHOP)
                    tb_move.promotion = BISHOP;
                else if (promotes == TB_PROMOTES_KNIGHT)
                    tb_move.promotion = KNIGHT;
                if (!s->aborted)
                {
                    char move_str[6] = {0};
                    move_str[0] = 'a' + (from_sq % 8);
                    move_str[1] = '1' + (from_sq / 8);
                    move_str[2] = 'a' + (to_sq % 8);
                    move_str[3] = '1' + (to_sq / 8);
                    if (tb_move.promotion)
                    {
                        static const char promo_chars[] = "xnbrqk";
                        move_str[4] = promo_chars[tb_move.promotion];
                    }
                    if (g_info_callback)
                    {
                        g_info_callback(100, tb_score, 0, 0, move_str);
                    }
                    s->tb_hits = 1;
                    if (out_nodes)
                        *out_nodes = 0;
                    free(s_ptr);
                    return tb_move;
                }
            }
        root_tb_done:;
        }
    }

    int material = count_total_material(&s->board);
    int depth_bonus = 0;
    if (material <= MATERIAL_DEPTH_THRESHOLDS[0])
        depth_bonus = MATERIAL_DEPTH_BONUS[0];
    else if (material <= MATERIAL_DEPTH_THRESHOLDS[1])
        depth_bonus = MATERIAL_DEPTH_BONUS[1];
    else if (material <= MATERIAL_DEPTH_THRESHOLDS[2])
        depth_bonus = MATERIAL_DEPTH_BONUS[2];
    else if (material <= MATERIAL_DEPTH_THRESHOLDS[3])
        depth_bonus = MATERIAL_DEPTH_BONUS[3];

    /* When max_depth=0 (no limit), use a very high default.
     * The depth_bonus is only meaningful when max_depth > 0. */
    int effective_max_depth;
    if (max_depth <= 0)
        effective_max_depth = 100; /* Unlimited - let time control the search */
    else
        effective_max_depth = max_depth + depth_bonus;

    /* Search pre-adjustments: compute legal_count and phase for downstream use,
     * and apply time adjustments based on position characteristics. */
    {
        int legal_count = generate_legal_moves(&s->board, s->move_stack);
        int phase = s->board.phase;

        /* When in check: increase time — forced moves may still require
         * deep search to find the only correct response. */
        if (is_check(&s->board, s->board.side_to_move))
        {
            tm.optimal_time *= (double)IN_CHECK_TIME_REDUCTION_NUM / IN_CHECK_TIME_REDUCTION_DEN;
        }

        /* Endgame time bonus: with fewer pieces, each move is more critical.
         * Phase ranges from 0 (endgame) to 24 (opening). */
        if (phase < 6)
        {
            tm.optimal_time *= 1.2;
        }
        else if (phase < 10)
        {
            tm.optimal_time *= 1.1;
        }

        /* Opening time reduction: in the opening, moves are less critical
         * and positions are well-studied. Save time for middlegame/endgame
         * where deeper search matters more. */
        if (move_number > 0 && move_number <= 10)
        {
            tm.optimal_time *= 0.7;
        }
        else if (move_number > 10 && move_number <= 15)
        {
            tm.optimal_time *= 0.85;
        }

        /* Complexity bonus: positions with many legal moves deserve more time.
         * This helps the engine find the best move in complex positions. */
        if (legal_count >= 35)
        {
            tm.optimal_time *= 1.15;
        }
        else if (legal_count >= 25)
        {
            tm.optimal_time *= 1.08;
        }

        /* Endgame passed pawn criticality bonus: in endgames with passed pawns,
         * each move is extremely critical — a single wrong move can allow or
         * prevent promotion. These positions require deeper search to correctly
         * evaluate pawn promotion sequences. This is conservative: only applies
         * when phase < 10 and there are passed pawns on the board. */
        if (phase < 10)
        {
            /* Quick passed pawn detection: check if any pawn has no enemy pawns
             * ahead on adjacent files. This is a simplified check for time
             * management purposes — not as thorough as the eval's detection. */
            int has_passed_pawn = 0;
            U64 wp = s->board.pieces[WHITE][PAWN];
            U64 bp = s->board.pieces[BLACK][PAWN];
            /* Check White passed pawns */
            while (wp && !has_passed_pawn)
            {
                int sq = lsb_index(wp);
                wp &= wp - 1;
                int f = sq % 8;
                int r = sq / 8;
                U64 ahead_mask = 0;
                int af;
                for (af = (f > 0 ? f - 1 : 0); af <= (f < 7 ? f + 1 : 7); af++)
                {
                    int ar;
                    for (ar = r + 1; ar <= 7; ar++)
                        ahead_mask |= (1ULL << (ar * 8 + af));
                }
                if (!(bp & ahead_mask))
                    has_passed_pawn = 1;
            }
            /* Check Black passed pawns */
            while (bp && !has_passed_pawn)
            {
                int sq = lsb_index(bp);
                bp &= bp - 1;
                int f = sq % 8;
                int r = sq / 8;
                U64 ahead_mask = 0;
                int af;
                for (af = (f > 0 ? f - 1 : 0); af <= (f < 7 ? f + 1 : 7); af++)
                {
                    int ar;
                    for (ar = r - 1; ar >= 0; ar--)
                        ahead_mask |= (1ULL << (ar * 8 + af));
                }
                if (!(wp & ahead_mask))
                    has_passed_pawn = 1;
            }
            if (has_passed_pawn)
            {
                /* Deeper phase (fewer pieces) = more critical passed pawns */
                if (phase < 6)
                    tm.optimal_time *= 1.15;
                else
                    tm.optimal_time *= 1.08;
            }
        }

        /* EGTB guard: if Syzygy tablebases cover this position (piece count ≤ TB_LARGEST),
         * skip any endgame time bonus. Currently no endgame bonus is applied,
         * but this check ensures future additions respect EGTB coverage. */
        if (TB_LARGEST > 0)
        {
            U64 all_w = s->board.pieces[WHITE][PAWN] | s->board.pieces[WHITE][KNIGHT] |
                        s->board.pieces[WHITE][BISHOP] | s->board.pieces[WHITE][ROOK] |
                        s->board.pieces[WHITE][QUEEN] | s->board.pieces[WHITE][KING];
            U64 all_b = s->board.pieces[BLACK][PAWN] | s->board.pieces[BLACK][KNIGHT] |
                        s->board.pieces[BLACK][BISHOP] | s->board.pieces[BLACK][ROOK] |
                        s->board.pieces[BLACK][QUEEN] | s->board.pieces[BLACK][KING];
            int total_pc = count_bits(all_w) + count_bits(all_b);
            if (total_pc <= (int)TB_LARGEST)
            {
                /* No endgame time bonus when EGTB covers this position */
            }
        }
    }

    /* Capture base_optimal_time AFTER pre-adjustments (opening/endgame/complexity) */
    tm.base_optimal_time = tm.optimal_time;

    int window = INITIAL_ASPIRATION_WINDOW;
    int aw_hits = 0;
    int aw_fails = 0;
    double prev_iter_elapsed = 0.0;

    for (depth = 1; depth <= effective_max_depth; depth++)
    {
        double elapsed = get_time() - tm.start_time;
        /* When max_depth is explicitly set (depth-limited mode), don't cut
         * search short based on time. The user wants a full depth-N search. */
        if (max_depth <= 0 && depth > 1)
        {
            /* 预测下一次迭代耗时（通常 1.5-2 倍增长）
             * 如果已用时间超过 optimal_time，但预测下一次迭代仍可在
             * max_time 内完成，则继续搜索以获得更深的搜索结果。
             * 这在短时制下尤为重要，避免过早停止迭代加深。 */
            double predicted_next = prev_iter_elapsed * 1.8;
            if (elapsed >= tm.optimal_time * 0.85 &&
                elapsed + predicted_next >= tm.max_time)
            {
                break;
            }
        }

        int nodes_before = s->nodes;
        int aw_fails_before = aw_fails;

        Move current_best = {0};
        int current_score = -MATE_SCORE;
        int alpha, beta;

        if (depth <= 1)
        {
            alpha = -MATE_SCORE;
            beta = MATE_SCORE;

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

                root_scores[i] = score;
                root_moves[i].score = score;

                if (score > current_score)
                {
                    current_score = score;
                    current_best = root_moves[i];
                    if (score > alpha)
                    {
                        alpha = score;
                        s->pv_table[0][0] = root_moves[i];
                        memcpy(&s->pv_table[0][1], s->pv_table[1], s->pv_length[1] * sizeof(Move));
                        s->pv_length[0] = s->pv_length[1] + 1;
                    }
                }
            }
        }
        else
        {
            /* When the previous best score indicates a winning position or mate,
             * use a full window to avoid missing forced mates. A narrow aspiration
             * window can cause the search to lose mates because:
             * 1. Fail-high re-searches are expensive and may time out
             * 2. TT entries from narrow-window searches can pollute later searches
             * 3. The score jump from "winning" to "mate" can be very large */
            if (abs(best_score) > MATE_SCORE - 100)
            {
                alpha = -MATE_SCORE;
                beta = MATE_SCORE;
            }
            else
            {
                alpha = best_score - window;
                beta = best_score + window;
            }
            while (1)
            {
                if (alpha < -MATE_SCORE)
                    alpha = -MATE_SCORE;
                if (beta > MATE_SCORE)
                    beta = MATE_SCORE;

                current_score = -MATE_SCORE;
                current_best = (Move){0};

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

                    root_scores[i] = score;
                    root_moves[i].score = score;

                    if (score > current_score)
                    {
                        current_score = score;
                        current_best = root_moves[i];
                        if (score > alpha)
                        {
                            alpha = score;
                            s->pv_table[0][0] = root_moves[i];
                            memcpy(&s->pv_table[0][1], s->pv_table[1], s->pv_length[1] * sizeof(Move));
                            s->pv_length[0] = s->pv_length[1] + 1;
                        }
                    }
                }

                if (s->aborted)
                    break;

                if (current_score <= alpha)
                {
                    aw_fails++;
                    /* Fail-low: lower alpha with asymmetric growth */
                    window += window / 2 + ASPIRATION_WINDOW_GROWTH_BASE;
                    alpha = best_score - window;
                    if (alpha < -INF)
                        alpha = -INF;
                    /* Don't widen beta on fail-low */
                }
                else if (current_score >= beta)
                {
                    aw_fails++;
                    /* Fail-high: raise beta with asymmetric growth */
                    window += window / 2 + ASPIRATION_WINDOW_GROWTH_BASE;
                    beta = best_score + window;
                    if (beta > INF)
                        beta = INF;
                    /* Don't widen alpha on fail-high */
                }
                else
                {
                    aw_hits++;
                    break;
                }

                /* If window gets too large, fall back to full window
                 * and re-search to get a reliable score. */
                if (window > ASPIRATION_FULL_WINDOW_THRESHOLD)
                {
                    alpha = -MATE_SCORE;
                    beta = MATE_SCORE;

                    current_score = -MATE_SCORE;
                    current_best = (Move){0};

                    for (i = 0; i < legal_moves_count; i++)
                    {
                        UndoInfo undo;
                        make_move(b, &root_moves[i], &undo);
                        int score;
                        if (i == 0)
                        {
                            score = -negamax(s, depth - 1, -MATE_SCORE, MATE_SCORE, 0, 1);
                        }
                        else
                        {
                            score = -negamax(s, depth - 1, -MATE_SCORE, -alpha, 0, 1);
                            if (!s->aborted && score > alpha)
                            {
                                score = -negamax(s, depth - 1, -MATE_SCORE, -alpha, 0, 1);
                            }
                        }
                        unmake_move(b, &root_moves[i], &undo);

                        if (s->aborted)
                            break;

                        root_scores[i] = score;
                        root_moves[i].score = score;

                        if (score > current_score)
                        {
                            current_score = score;
                            current_best = root_moves[i];
                            if (score > alpha)
                            {
                                alpha = score;
                                s->pv_table[0][0] = root_moves[i];
                                memcpy(&s->pv_table[0][1], s->pv_table[1], s->pv_length[1] * sizeof(Move));
                                s->pv_length[0] = s->pv_length[1] + 1;
                            }
                        }
                    }
                    break;
                }
            }
        }

#ifdef DEBUG
        if (depth >= 6)
        {
            fprintf(stderr, "[ST depth %d] best_score=%d current_score=%d legal=%d\n",
                    depth, best_score, current_score, legal_moves_count);
            fflush(stderr);
            for (int dbg_i = 0; dbg_i < legal_moves_count; dbg_i++)
            {
                fprintf(stderr, "  %c%c%c%c score=%d\n",
                        'a' + (root_moves[dbg_i].from & 7), '1' + (root_moves[dbg_i].from >> 3),
                        'a' + (root_moves[dbg_i].to & 7), '1' + (root_moves[dbg_i].to >> 3),
                        root_moves[dbg_i].score);
                fflush(stderr);
            }
        }
#endif

        if (!s->aborted && current_score > -MATE_SCORE)
        {
            best_move = current_best;
            best_move.score = current_score;
            best_score = current_score;
            scores_valid = 1;
            g_last_search_depth = depth;
            g_last_search_nodes = s->nodes;
            g_last_best_score = current_score;

            g_last_lmr_reductions = s->lmr_reductions;
            g_last_lmr_re_searches = s->lmr_re_searches;
            g_last_lmr_nodes_saved = s->lmr_nodes_saved;

            g_last_futility_prunes = s->futility_prunes;
            g_last_futility_nodes_saved = s->futility_nodes_saved;

            g_last_razoring_prunes = s->razoring_prunes;
            g_last_razoring_nodes_saved = s->razoring_nodes_saved;
            g_last_aw_hits = aw_hits;
            g_last_aw_fails = aw_fails;
            if (depth < 64)
                g_depth_nodes[depth] = s->nodes - nodes_before;
            {
                int j;
                for (j = 0; j < legal_moves_count; j++)
                {
                    if (root_moves[j].from == current_best.from && root_moves[j].to == current_best.to && root_moves[j].promotion == current_best.promotion)
                    {
                        root_moves[j].score = current_score + 1000000;
                    }
                }
                for (j = 1; j < legal_moves_count; j++)
                {
                    int k;
                    for (k = j; k > 0; k--)
                    {
                        if (root_moves[k].score > root_moves[k - 1].score)
                        {
                            Move tmp = root_moves[k];
                            root_moves[k] = root_moves[k - 1];
                            root_moves[k - 1] = tmp;
                        }
                        else
                            break;
                    }
                }
            }

            if (g_info_callback)
            {
                double elapsed2 = get_time() - s->start_time;
                int time_ms = (int)(elapsed2 * 1000);
                char pv_buf[1024];
                int pv_pos = 0;
                int pv_len = s->pv_length[0];
                if (pv_len <= 0)
                    pv_len = 1;
                Board replay_board = s->board;
                int pi;
                for (pi = 0; pi < pv_len && pi < 32; pi++)
                {
                    Move *pm = &s->pv_table[0][pi];
                    if (pm->from == 0 && pm->to == 0 && pi > 0)
                        break;
                    Move legal_moves[256];
                    int n_legal = generate_pseudo_legal_moves(&replay_board, legal_moves);
                    int found = 0;
                    int j;
                    for (j = 0; j < n_legal; j++)
                    {
                        if (legal_moves[j].from == pm->from && legal_moves[j].to == pm->to && legal_moves[j].promotion == pm->promotion)
                        {
                            found = 1;
                            break;
                        }
                    }
                    if (!found)
                    {
                        fprintf(stderr, "PV_REPLAY: illegal move %c%c%c%c at depth %d pv[%d], truncating\n",
                                'a' + (pm->from & 7), '1' + (pm->from >> 3),
                                'a' + (pm->to & 7), '1' + (pm->to >> 3), depth, pi);
                        break;
                    }
                    UndoInfo replay_undo;
                    make_move(&replay_board, pm, &replay_undo);
                    if (is_check(&replay_board, replay_board.side_to_move ^ 1))
                    {
                        fprintf(stderr, "PV_REPLAY: move %c%c%c%c leaves king in check at depth %d pv[%d], truncating\n",
                                'a' + (pm->from & 7), '1' + (pm->from >> 3),
                                'a' + (pm->to & 7), '1' + (pm->to >> 3), depth, pi);
                        break;
                    }
                    if (pv_pos > 0)
                        pv_pos += sprintf(pv_buf + pv_pos, " ");
                    pv_pos += sprintf(pv_buf + pv_pos, "%c%c%c%c",
                                      'a' + (pm->from & 7), '1' + (pm->from >> 3),
                                      'a' + (pm->to & 7), '1' + (pm->to >> 3));
                    if (pm->promotion)
                    {
                        char pc = 'q';
                        switch (pm->promotion)
                        {
                        case KNIGHT:
                            pc = 'n';
                            break;
                        case BISHOP:
                            pc = 'b';
                            break;
                        case ROOK:
                            pc = 'r';
                            break;
                        }
                        pv_pos += sprintf(pv_buf + pv_pos, "%c", pc);
                    }
                }
                pv_buf[pv_pos] = '\0';
                g_info_callback(depth, current_score, s->nodes, time_ms, pv_buf);
            }

            {
                int hi, hj;
                for (hi = 0; hi < 64; hi++)
                {
                    for (hj = 0; hj < 64; hj++)
                    {
                        s->history[hi][hj] = s->history[hi][hj] * HISTORY_DECAY_NUM / HISTORY_DECAY_DEN;
                    }
                }
            }
            /* In clearly winning positions, keep full window to avoid
             * missing forced mates due to narrow aspiration. */
            if (abs(best_score) > MATE_SCORE - 100)
                window = ASPIRATION_FULL_WINDOW_THRESHOLD; /* effectively full window after first iteration */
            else
                window = NORMAL_ASPIRATION_WINDOW;
            s->tt_generation++;

            /* Stability check - now includes promotion field */
            if (current_best.from == tm.prev_best_move_from &&
                current_best.to == tm.prev_best_move_to &&
                current_best.promotion == tm.prev_best_promotion)
            {
                tm.stable_count++;
            }
            else
            {
                tm.stable_count = 0;
            }
            tm.prev_best_move_from = current_best.from;
            tm.prev_best_move_to = current_best.to;
            tm.prev_best_promotion = current_best.promotion;

            /* Update search instability detection history */
            {
                int hidx = tm.history_count % 4;
                tm.score_history[hidx] = current_score;
                tm.best_from_history[hidx] = current_best.from;
                tm.best_to_history[hidx] = current_best.to;
                tm.best_promo_history[hidx] = current_best.promotion;
                tm.history_count++;

                /* Count instability: how many times best move changed in last 4 iterations */
                if (tm.history_count >= 2)
                {
                    int prev_hidx = (tm.history_count - 2) % 4;
                    if (tm.best_from_history[prev_hidx] != current_best.from ||
                        tm.best_to_history[prev_hidx] != current_best.to ||
                        tm.best_promo_history[prev_hidx] != current_best.promotion)
                    {
                        tm.instability_count++;
                    }
                }
            }

            /* Easy move: stable for 4+ iterations with score change < 10cp.
             * 不再提前终止搜索，改为稍后在时间调整中应用 easy 系数。 */
            {
                int easy_condition = 0;
                if (tm.stable_count >= 4 && abs(current_score - prev_score) < 10)
                    easy_condition = 1;

                if (easy_condition && max_depth <= 0)
                {
                    /* Set flag — 后续时间调整段将使用此标志设置 time_limit = base_optimal */
                    tm.critical_position_flag = 2;  /* 2 = easy mode */
                }
            }

            /* Stability-driven dynamic time adjustment with score volatility awareness */
            {
                int score_drop = prev_score - current_score;
                int best_move_changed = (tm.stable_count == 0 && tm.history_count > 0);
                double time_limit;

                /* Score volatility: measure how much the score fluctuated across
                 * recent iterations. High volatility indicates a complex position
                 * where deeper search is needed to find the correct evaluation.
                 * Lowered threshold from 50 to 30cp to catch more complex positions.
                 * Increased cap from 1.5 to 1.8 to give more time for volatile positions. */
                double volatility_bonus = 1.0;
                if (tm.history_count >= 2)
                {
                    int h1 = (tm.history_count - 1) % 4;
                    int h2 = (tm.history_count - 2) % 4;
                    int score_change = abs(tm.score_history[h1] - tm.score_history[h2]);
                    if (score_change >= 30)
                    {
                        /* Score swing between iterations — position is complex.
                         * Increase time budget to allow deeper search.
                         * Scale: 30cp -> 1.15x, 60cp -> 1.30x, 100cp -> 1.50x, 160cp -> 1.80x */
                        volatility_bonus = 1.0 + score_change / 200.0;
                        if (volatility_bonus > 1.8)
                            volatility_bonus = 1.8;
                    }
                    else if (score_change <= 8 && tm.stable_count >= 3)
                    {
                        /* Score very stable and best move unchanged for 3+ iterations —
                         * position is simple. Reduce time budget since deeper search
                         * unlikely to change result. Tightened from stable_count >= 2. */
                        volatility_bonus = 0.85;
                    }
                }

                /* Panic: score drop ≥ PANIC_SCORE_DROP_THRESHOLD → use maximum time */
                if (score_drop >= PANIC_SCORE_DROP_THRESHOLD)
                {
                    time_limit = tm.max_time;
                    tm.panic_flag = 1;
                }
                /* Hard move: best_move changed or score drop ≥ HARD_MOVE_SCORE_DROP_THRESHOLD */
                else if (best_move_changed || score_drop >= HARD_MOVE_SCORE_DROP_THRESHOLD)
                {
                    time_limit = tm.optimal_time * HARD_MOVE_TIME_MULTIPLIER_NUM / HARD_MOVE_TIME_MULTIPLIER_DEN;
                    tm.panic_flag = 0;
                }
                /* Moderate difficulty: best move changed but score is stable or only
                 * slightly dropped (20-49cp). This catches positions where the engine
                 * is reconsidering its evaluation — a sign the position is complex
                 * and needs deeper search, but not as urgent as a hard move.
                 * Give 1.3x optimal time to allow deeper analysis. */
                else if (best_move_changed == 0 && tm.instability_count >= 2 && score_drop >= 20)
                {
                    time_limit = tm.optimal_time * 13.0 / 10.0;
                    tm.panic_flag = 0;
                }
                /* Normal: slightly above optimal, adjusted by volatility */
                else
                {
                    time_limit = tm.optimal_time * NORMAL_TIME_MULTIPLIER_NUM / NORMAL_TIME_MULTIPLIER_DEN * volatility_bonus;
                    tm.panic_flag = 0;
                }

                /* 移除 — 单一上限 max_time 已在 init_time_manager 中保障，不再二次限缩 */

                /* Apply easy mode: cap time_limit at base_optimal (no boost) */
                if (tm.critical_position_flag == 2)
                {
                    if (time_limit > tm.base_optimal_time)
                        time_limit = tm.base_optimal_time;
                    tm.critical_position_flag = 0;
                }

                /* Critical position detection + time bank (Task 5) */
                if (depth >= 3 && max_depth <= 0)
                {
                    int aw_fails_this_iter = aw_fails - aw_fails_before;
                    long long nodes_this_iter = s->nodes - nodes_before;
                    int crit = compute_criticality_score(&tm, current_score, prev_score,
                        best_move_changed, aw_fails_this_iter, nodes_this_iter, legal_moves_count);

                    if (crit >= 55)
                    {
                        /* Critical position: use max_time + withdraw from bank */
                        double crit_limit = tm.max_time;
                        double withdraw = tm.time_bank * 0.5;
                        if (withdraw > 2.0)
                            withdraw = 2.0;
                        crit_limit += withdraw;
                        if (time_limit < crit_limit)
                            time_limit = crit_limit;
                        tm.critical_position_flag = 1;
                        tm.time_bank -= withdraw;
                        if (tm.time_bank < 0)
                            tm.time_bank = 0;
                    }
                    else if (crit >= 25)
                    {
                        /* Moderate: 1.5x base optimal */
                        double mod_limit = tm.base_optimal_time * 1.5;
                        if (time_limit < mod_limit)
                            time_limit = mod_limit;
                        tm.critical_position_flag = 0;
                    }
                    else if (crit <= 12 && tm.stable_count >= 3)
                    {
                        /* Simple position: save time to bank */
                        double simple_limit = tm.base_optimal_time * 0.7;
                        double saved = time_limit - simple_limit;
                        if (saved > 0.05)
                        {
                            tm.time_bank += saved * 0.7;
                            if (tm.time_bank > tm.base_optimal_time * 8.0)
                                tm.time_bank = tm.base_optimal_time * 8.0;
                            time_limit = simple_limit;
                        }
                        tm.critical_position_flag = 0;
                    }
                    else
                    {
                        tm.critical_position_flag = 0;
                    }

                    /* 移除 — safety_cap 已不再使用 */
                }

                s->time_limit = time_limit;
            }

            /* Store iteration data for next iteration's criticality computation */
            tm.nodes_last_iter = s->nodes - nodes_before;
            tm.aw_fails_last_iter = aw_fails - aw_fails_before;

            /* 记录本次迭代耗时，用于下一次迭代的时间预测 */
            {
                double iter_end = get_time() - tm.start_time;
                prev_iter_elapsed = iter_end - elapsed;
            }

            prev_score = current_score;
        }

        if (s->aborted || early_terminate)
            break;
    }

    if (scores_valid && g_perturb_enabled && legal_moves_count > 1)
    {
        int candidate_count = 0;
        int candidate_indices[MAX_MOVES];
        int candidate_weights[MAX_MOVES];
        int total_weight = 0;
        int min_acceptable_score = best_score - g_perturb_threshold;

        for (i = 0; i < legal_moves_count; i++)
        {
            if (root_scores[i] >= min_acceptable_score)
            {
                int diff = best_score - root_scores[i];
                int weight = g_perturb_threshold + 1 - diff;
                if (weight < 1)
                    weight = 1;
                candidate_indices[candidate_count] = i;
                candidate_weights[candidate_count] = weight;
                total_weight += weight;
                candidate_count++;
            }
        }

        if (candidate_count > 1)
        {
            int roll = perturb_rand_int(total_weight);
            int cumulative = 0;
            int chosen_idx = 0;
            for (i = 0; i < candidate_count; i++)
            {
                cumulative += candidate_weights[i];
                if (roll < cumulative)
                {
                    chosen_idx = i;
                    break;
                }
            }
            best_move = root_moves[candidate_indices[chosen_idx]];
            best_move.score = root_scores[candidate_indices[chosen_idx]];
        }
    }

    if (!scores_valid && legal_moves_count > 0)
    {
        best_move = root_moves[0];
        best_move.score = 0;
    }

    if (out_nodes)
        *out_nodes = s->nodes;
    g_tt_generation = s->tt_generation;
    /* Save heuristics for potential ponderhit reuse */
    save_heuristic_snapshot(s);
    free(s_ptr);
    return best_move;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
void
get_root_move_scores(const char *fen, double time_limit, int max_depth,
                     int *out_scores, int *out_from, int *out_to, int *out_count)
{
    ensure_engine_tables_initialized();

    static int params_loaded_scores = 0;
    if (!params_loaded_scores)
    {
        int loaded_ok = 0;
        const char *env_path = getenv("ENGINE_PARAMS");
        if (env_path && env_path[0] != '\0')
        {
            loaded_ok = load_params_from_file(env_path);
        }
        if (!loaded_ok)
        {
            loaded_ok = load_params_from_file("engine_params.json");
        }
        if (!loaded_ok)
        {
            init_runtime_params_defaults();
        }
        params_loaded_scores = 1;
    }

    SearchState *s_ptr = (SearchState *)calloc(1, sizeof(SearchState));
    if (!s_ptr)
        return;
    SearchState *s = s_ptr;
    board_from_fen(&s->board, fen);
    s->start_time = get_time();
    s->time_limit = time_limit;
    s->aborted = 0;
    s->nodes = 0;
    tt_init(s, 16);
    s->search_history_count = 0;
    s->game_history_count = 0;

    Board *b = &s->board;
    Move root_moves[MAX_MOVES];
    int n_moves = generate_pseudo_legal_moves(b, root_moves);
    int legal_moves_count = 0;
    int i;
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
    int alpha, beta;
    for (depth = 1; depth <= max_depth; depth++)
    {
        alpha = -MATE_SCORE;
        beta = MATE_SCORE;
        for (i = 0; i < legal_moves_count; i++)
        {
            UndoInfo undo;
            make_move(b, &root_moves[i], &undo);
            int score;
            if (i == 0)
                score = -negamax(s, depth - 1, -beta, -alpha, 0, 1);
            else
            {
                score = -negamax(s, depth - 1, -alpha - 1, -alpha, 0, 1);
                if (!s->aborted && score > alpha && score < beta)
                    score = -negamax(s, depth - 1, -beta, -alpha, 0, 1);
            }
            unmake_move(b, &root_moves[i], &undo);
            if (s->aborted)
                break;
            if (i < 256)
                root_moves[i].score = score;
            if (score > alpha)
                alpha = score;
        }
        if (s->aborted)
            break;
        {
            int best_idx = 0;
            for (i = 1; i < legal_moves_count; i++)
                if (root_moves[i].score > root_moves[best_idx].score)
                    best_idx = i;
            if (best_idx != 0)
            {
                Move tmp = root_moves[0];
                root_moves[0] = root_moves[best_idx];
                root_moves[best_idx] = tmp;
            }
        }
    }

    int count = 0;
    for (i = 0; i < legal_moves_count && count < 256; i++)
    {
        out_scores[count] = root_moves[i].score;
        out_from[count] = root_moves[i].from;
        out_to[count] = root_moves[i].to;
        count++;
    }
    *out_count = count;
    free(s->tt);
    free(s_ptr);
}

/* ============================================================================
 * LAZY SMP MULTI-THREADED SEARCH
 * ============================================================================ */

/* Lazy SMP globals.
 *
 * Strategy: Each thread independently does iterative deepening on all
 * root moves. Thread diversity comes from:
 * 1. Different start_depth (1 + thread_id % 4)
 * 2. Fisher-Yates shuffle of root moves for helpers
 * 3. Shared TT naturally causes divergence as search progresses
 *
 * This is the simplest and most robust Lazy SMP approach. Dynamic work
 * distribution and shared alpha were tested but showed no improvement
 * over this simple approach for typical chess positions. */

typedef struct
{
    Board board;
    TT_Cluster *shared_tt;
    int tt_cluster_count;
    double start_time;
    double time_limit;
    double time_limit_max;
    long long node_limit;
    int max_depth;
    int thread_id;
    int num_threads;
    U64 game_history[512];
    int game_history_count;
    Move best_move;
    int best_score;
    int completed_depth;
    int nodes;
    int aborted;
#ifdef _WIN32
    HANDLE thread_handle;
#else
    pthread_t thread_handle;
#endif
} LazySMPWorker;

static void smp_worker_search(LazySMPWorker *w)
{
    SearchState *s_ptr = (SearchState *)calloc(1, sizeof(SearchState));
    if (!s_ptr)
    {
        w->completed_depth = 0;
        w->nodes = 0;
        return;
    }
    SearchState *s = s_ptr;
    {
        int si;
        for (si = 0; si < 128; si++)
            s->static_eval_stack[si] = EVAL_SCORE_INVALID;
    }
    s->board = w->board;
    s->start_time = w->start_time;
    s->time_limit = w->time_limit;
    s->node_limit = w->node_limit;
    s->aborted = 0;
    s->nodes = 0;
    s->thread_id = w->thread_id;
    set_eval_thread_id(w->thread_id);

    s->tt_cluster_count = w->tt_cluster_count;
    s->tt = w->shared_tt;
    /* Per-worker generation seed.  Each worker advances its own s->tt_generation
     * once per completed root iteration, matching the single-threaded loop in
     * find_best_move_c.  This keeps the TT aging timeline monotonic within each
     * worker without forcing a globally-shared counter that can make one
     * worker's fresh but shallow entries look older than another worker's. */
    s->tt_generation = g_tt_generation;
    s->search_history_count = 0;
    s->game_history_count = w->game_history_count;
    if (w->game_history_count > 0)
    {
        int limit = w->game_history_count < 512 ? w->game_history_count : 512;
        memcpy(s->game_history, w->game_history, sizeof(U64) * limit);
        s->game_history_count = limit;
    }
    /* Worker 0 (main thread) restores heuristics from ponder search */
    if (w->thread_id == 0)
        restore_heuristic_snapshot(s);

    {
        /* Fix: Do NOT add root key to search_history (same as main thread fix).
         * Root position is already in game_history. */
    }

    Board *b = &s->board;
    Move root_moves[MAX_MOVES];
    int n_moves = generate_pseudo_legal_moves(b, root_moves);
    int legal_count = 0;
    int i;
    for (i = 0; i < n_moves; i++)
    {
        UndoInfo undo;
        make_move(b, &root_moves[i], &undo);
        if (!is_check(b, b->side_to_move ^ 1))
            root_moves[legal_count++] = root_moves[i];
        unmake_move(b, &root_moves[i], &undo);
    }

    if (legal_count == 0)
    {
        w->completed_depth = 0;
        w->nodes = 0;
        free(s_ptr);
        return;
    }

    /* Root move ordering: same logic as find_best_move_c so worker 0 (and
     * helpers) start from the same move order as the single-threaded search.
     * Divergent ordering interacts with aspiration windows, LMR, and pruning
     * heuristics, producing different results at the same depth. */
    {
        int root_reps = 0;
        int root_eval = evaluate(b);
        if (b->side_to_move == BLACK)
            root_eval = -root_eval;
        {
            U64 root_key = s->board.hash;
            for (int ri = 0; ri < s->game_history_count; ri++)
            {
                if (s->game_history[ri] == root_key)
                    root_reps++;
            }
        }
        int move_priorities[MAX_MOVES];
        for (i = 0; i < legal_count; i++)
        {
            Move *m = &root_moves[i];
            int priority = 0;

            if (m->capture)
            {
                int attacker = piece_on_square(b, m->from);
                priority += 10000 + ROOT_CAPTURE_VALUE[m->capture] - ROOT_ATTACKER_VALUE[attacker];
            }

            if (m->promotion)
                priority += 5000;

            int to_r = rank_of(m->to), to_f = file_of(m->to);
            if ((to_f >= 2 && to_f <= 5) && (to_r >= 2 && to_r <= 5))
                priority += 100;

            if (root_reps >= 1)
            {
                UndoInfo rep_undo;
                make_move(b, m, &rep_undo);
                U64 child_key = b->hash;
                int child_reps = 0;
                for (int ri = 0; ri < s->game_history_count; ri++)
                {
                    if (s->game_history[ri] == child_key)
                        child_reps++;
                }
                unmake_move(b, m, &rep_undo);
                if (child_reps >= 1)
                {
                    if (root_eval > REPETITION_EVAL_THRESHOLD)
                        priority -= REPETITION_SCORE;
                    else if (root_eval < -REPETITION_EVAL_THRESHOLD)
                        priority += REPETITION_SCORE;
                }
            }

            priority += 63 - m->to;
            move_priorities[i] = priority;
        }

        for (i = 0; i < legal_count - 1; i++)
        {
            int best_idx = i;
            for (int j = i + 1; j < legal_count; j++)
            {
                if (move_priorities[j] > move_priorities[best_idx])
                    best_idx = j;
            }
            if (best_idx != i)
            {
                Move tmp = root_moves[i];
                root_moves[i] = root_moves[best_idx];
                root_moves[best_idx] = tmp;
                int tmp_p = move_priorities[i];
                move_priorities[i] = move_priorities[best_idx];
                move_priorities[best_idx] = tmp_p;
            }
        }

        {
            Move tt_root_move = {0};
            int tt_root_val = tt_probe(s, s->board.hash, 1, -MATE_SCORE, MATE_SCORE, &tt_root_move, 0, NULL, NULL);
            (void)tt_root_val;
            if (tt_root_move.from != 0 || tt_root_move.to != 0)
            {
                int tt_idx = -1;
                for (i = 0; i < legal_count; i++)
                {
                    if (root_moves[i].from == tt_root_move.from &&
                        root_moves[i].to == tt_root_move.to &&
                        root_moves[i].promotion == tt_root_move.promotion)
                    {
                        tt_idx = i;
                        break;
                    }
                }
                if (tt_idx > 0)
                {
                    Move tmp = root_moves[0];
                    root_moves[0] = root_moves[tt_idx];
                    root_moves[tt_idx] = tmp;
                }
            }
        }
    }

    /* Simple Lazy SMP: each thread independently searches all root moves.
     * Diversity now comes only from the shared TT and parallel node expansion.
     * All workers use the same start depth and root move order as the main
     * thread to maximise single-vs-multi consistency. */
    int start_depth = 1;
    int depth_step = 1;
    int smp_max_depth = w->max_depth;
    if (smp_max_depth <= 0)
        smp_max_depth = 100;
    else
    {
        /* Fix: apply the same depth_bonus as single-threaded search.
         * Without this, `go depth N` searches to N+depth_bonus in
         * single-thread mode but only N in SMP mode, causing SMP to
         * miss mates found by single-thread at deeper plies. */
        int material = count_total_material(&s->board);
        int depth_bonus = 0;
        if (material <= MATERIAL_DEPTH_THRESHOLDS[0])
            depth_bonus = MATERIAL_DEPTH_BONUS[0];
        else if (material <= MATERIAL_DEPTH_THRESHOLDS[1])
            depth_bonus = MATERIAL_DEPTH_BONUS[1];
        else if (material <= MATERIAL_DEPTH_THRESHOLDS[2])
            depth_bonus = MATERIAL_DEPTH_BONUS[2];
        else if (material <= MATERIAL_DEPTH_THRESHOLDS[3])
            depth_bonus = MATERIAL_DEPTH_BONUS[3];
        smp_max_depth += depth_bonus;
    }

    Move best_move = root_moves[0];
    int best_score = -MATE_SCORE;
    w->best_move = best_move;
    w->best_score = best_score;

    int window = INITIAL_ASPIRATION_WINDOW;

    for (int depth = start_depth; depth <= smp_max_depth; depth += depth_step)
    {
        /* Advance the shared TT generation atomically at the start of every
         * worker iteration.  This guarantees that all workers see a single
         * monotonic aging timeline, preventing a helper thread's fresh deep
         * entries from being overwritten by another helper's stale shallow
         * entries (or vice-versa) during replacement. */
        s->tt_generation = smp_inc_tt_generation();

        if (smp_get_stop())
            break;
        if (depth >= 5)
        {
            double elapsed = get_time() - s->start_time;
            if (elapsed >= w->time_limit * SMP_TIME_CHECK_FRACTION_NUM / SMP_TIME_CHECK_FRACTION_DEN)
                break;
        }

        int nodes_before = s->nodes;
        Move current_best = {0};
        int current_score = -MATE_SCORE;
        int alpha, beta;

        if (depth <= 1)
        {
            alpha = -MATE_SCORE;
            beta = MATE_SCORE;

            for (i = 0; i < legal_count; i++)
            {
                if (smp_get_stop())
                    break;
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
                    if (!s->aborted && !smp_get_stop() && score > alpha && score < beta)
                    {
                        score = -negamax(s, depth - 1, -beta, -alpha, 0, 1);
                    }
                }
                unmake_move(b, &root_moves[i], &undo);

                if (s->aborted || smp_get_stop())
                    break;

                root_moves[i].score = score;

                if (score > current_score)
                {
                    current_score = score;
                    current_best = root_moves[i];
                    if (score > alpha)
                        alpha = score;
                }
            }
        }
        else
        {
            /* When the previous best score indicates a winning position or mate,
             * use a full window to avoid missing forced mates. A narrow aspiration
             * window can cause the search to lose mates because:
             * 1. Fail-high re-searches are expensive and may time out
             * 2. TT entries from narrow-window searches can pollute later searches
             * 3. The score jump from "winning" to "mate" can be very large */
            if (abs(best_score) > MATE_SCORE - 100)
            {
                alpha = -MATE_SCORE;
                beta = MATE_SCORE;
            }
            else
            {
                alpha = best_score - window;
                beta = best_score + window;
            }
            while (1)
            {
                if (alpha < -MATE_SCORE)
                    alpha = -MATE_SCORE;
                if (beta > MATE_SCORE)
                    beta = MATE_SCORE;

                current_score = -MATE_SCORE;
                current_best = root_moves[0];

                for (i = 0; i < legal_count; i++)
                {
                    if (smp_get_stop())
                        break;
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
                        if (!s->aborted && !smp_get_stop() && score > alpha && score < beta)
                        {
                            score = -negamax(s, depth - 1, -beta, -alpha, 0, 1);
                        }
                    }
                    unmake_move(b, &root_moves[i], &undo);

                    if (s->aborted || smp_get_stop())
                        break;

                    root_moves[i].score = score;

                    if (score > current_score)
                    {
                        current_score = score;
                        current_best = root_moves[i];
                        if (score > alpha)
                            alpha = score;
                    }
                }

                if (s->aborted || smp_get_stop())
                    break;

                if (current_score <= alpha)
                {
                    window += window / 2 + ASPIRATION_WINDOW_GROWTH_BASE;
                    alpha = best_score - window;
                    if (alpha < -INF)
                        alpha = -INF;
                }
                else if (current_score >= beta)
                {
                    window += window / 2 + ASPIRATION_WINDOW_GROWTH_BASE;
                    beta = best_score + window;
                    if (beta > INF)
                        beta = INF;
                }
                else
                {
                    break;
                }

                /* If window gets too large, fall back to a full-window search
                 * so we do not return a score polluted by a narrow window. */
                if (window > ASPIRATION_FULL_WINDOW_THRESHOLD)
                {
                    alpha = -MATE_SCORE;
                    beta = MATE_SCORE;

                    current_score = -MATE_SCORE;
                    current_best = root_moves[0];
                    for (i = 0; i < legal_count; i++)
                    {
                        if (smp_get_stop())
                            break;
                        UndoInfo undo;
                        make_move(b, &root_moves[i], &undo);
                        int score;
                        if (i == 0)
                        {
                            score = -negamax(s, depth - 1, -MATE_SCORE, MATE_SCORE, 0, 1);
                        }
                        else
                        {
                            score = -negamax(s, depth - 1, -MATE_SCORE, -alpha, 0, 1);
                            if (!s->aborted && !smp_get_stop() && score > alpha)
                            {
                                score = -negamax(s, depth - 1, -MATE_SCORE, -alpha, 0, 1);
                            }
                        }
                        unmake_move(b, &root_moves[i], &undo);

                        if (s->aborted || smp_get_stop())
                            break;

                        if (score > current_score)
                        {
                            current_score = score;
                            current_best = root_moves[i];
                            if (score > alpha)
                                alpha = score;
                        }
                    }
                    break;
                }
            }
        }

        if (depth >= 6)
        {
            fprintf(stderr, "[SMP depth %d] best_score=%d current_score=%d legal=%d\n",
                    depth, best_score, current_score, legal_count);
            fflush(stderr);
            for (int dbg_i = 0; dbg_i < legal_count; dbg_i++)
            {
                fprintf(stderr, "  %c%c%c%c score=%d\n",
                        'a' + (root_moves[dbg_i].from & 7), '1' + (root_moves[dbg_i].from >> 3),
                        'a' + (root_moves[dbg_i].to & 7), '1' + (root_moves[dbg_i].to >> 3),
                        root_moves[dbg_i].score);
                fflush(stderr);
            }
        }

        if (!s->aborted && !smp_get_stop() && current_score > -MATE_SCORE)
        {
            best_move = current_best;
            best_move.score = current_score;
            best_score = current_score;
            w->completed_depth = depth;
            w->nodes = s->nodes;
            w->best_move = best_move;
            w->best_score = best_score;

            /* Update root move scores and sort by score descending, matching
             * the single-threaded iterative-deepening loop.  Keeping the same
             * move order is critical for reproducible results at the same depth. */
            {
                int j;
                for (j = 0; j < legal_count; j++)
                {
                    if (root_moves[j].from == current_best.from &&
                        root_moves[j].to == current_best.to &&
                        root_moves[j].promotion == current_best.promotion)
                    {
                        root_moves[j].score = current_score + 1000000;
                    }
                }
                for (j = 1; j < legal_count; j++)
                {
                    int k;
                    for (k = j; k > 0; k--)
                    {
                        if (root_moves[k].score > root_moves[k - 1].score)
                        {
                            Move tmp = root_moves[k];
                            root_moves[k] = root_moves[k - 1];
                            root_moves[k - 1] = tmp;
                        }
                        else
                            break;
                    }
                }
            }

            /* Age the local quiet history table, matching the single-threaded
             * iterative-deepening loop.  Without this the history scores grow
             * without bound and move ordering diverges from single-thread. */
            {
                int hi, hj;
                for (hi = 0; hi < 64; hi++)
                {
                    for (hj = 0; hj < 64; hj++)
                    {
                        s->history[hi][hj] = s->history[hi][hj] * HISTORY_DECAY_NUM / HISTORY_DECAY_DEN;
                    }
                }
            }

            /* Match single-threaded aspiration window sizing: tighten the
             * window after a successful iteration, and keep it wide when a
             * forced mate is already known. */
            if (abs(best_score) > MATE_SCORE - 100)
                window = ASPIRATION_FULL_WINDOW_THRESHOLD;
            else
                window = NORMAL_ASPIRATION_WINDOW;
        }

        if (s->aborted || smp_get_stop())
            break;
    }
    free(s_ptr);
}

#ifdef _WIN32
static DWORD WINAPI smp_thread_func(LPVOID arg)
{
    LazySMPWorker *w = (LazySMPWorker *)arg;
    smp_worker_search(w);
    return 0;
}
#else
static void *smp_thread_func(void *arg)
{
    LazySMPWorker *w = (LazySMPWorker *)arg;
    smp_worker_search(w);
    return NULL;
}
#endif

#ifdef _WIN32
__declspec(dllexport)
#endif
Move
find_best_move_smp(const char *fen, double time_limit, double time_left, double increment, int moves_to_go, int move_number, int max_depth,
                   long long node_limit, int *out_nodes, U64 *game_history, int game_history_count)
{
    static int params_loaded_smp = 0;
    ensure_engine_tables_initialized();
    if (!params_loaded_smp)
    {
        int loaded_ok = 0;
        const char *env_path = getenv("ENGINE_PARAMS");
        if (env_path && env_path[0] != '\0')
        {
            loaded_ok = load_params_from_file(env_path);
        }
        if (!loaded_ok)
        {
            loaded_ok = load_params_from_file("engine_params.json");
        }
        if (!loaded_ok)
        {
            init_runtime_params_defaults();
        }
        params_loaded_smp = 1;
    }

    int num_threads = g_runtime_params.threading_enabled ? g_runtime_params.num_threads : 1;
    if (num_threads < 1)
        num_threads = 1;
    if (num_threads > 64)
        num_threads = 64;

    if (num_threads == 1)
    {
        return find_best_move_c(fen, time_limit, time_left, increment, moves_to_go, move_number, max_depth, node_limit, out_nodes,
                                game_history, game_history_count);
    }

    int tt_cluster_count_smp;
    tt_init_global(128);
    /* Ponderhit path: keep TT entries from ponder search.  In normal searches
     * advance the global generation once at search start (checking the
     * single-threaded path); individual workers then advance it per iteration via
     * smp_inc_tt_generation(). */
    if (g_preserve_tt_generation)
        g_preserve_tt_generation = 0;
    else
        g_tt_generation++;
    TT_Cluster *shared_tt = g_tt;
    tt_cluster_count_smp = g_tt_cluster_count;

    LazySMPWorker *workers = (LazySMPWorker *)calloc(num_threads, sizeof(LazySMPWorker));
    if (!workers)
    {
        return find_best_move_c(fen, time_limit, time_left, increment, moves_to_go, move_number, max_depth, node_limit, out_nodes,
                                game_history, game_history_count);
    }

    smp_set_stop(0);
    double start_time = get_time();

    TimeManager tm_smp;
    double smp_optimal;
    double smp_max;
    if (time_left > 0)
    {
        /* Use the same formula as init_time_manager for consistency */
        int estimated_moves;
        if (moves_to_go > 0)
            estimated_moves = moves_to_go;
        else if (move_number <= PHASE_OPENING_MAX_MOVE)
            estimated_moves = PHASE_OPENING_MOVES_REMAINING;
        else if (move_number <= PHASE_MIDGAME_MAX_MOVE)
            estimated_moves = PHASE_MIDGAME_MOVES_REMAINING;
        else
            estimated_moves = PHASE_ENDGAME_MOVES_REMAINING;

        smp_optimal = time_left / estimated_moves + increment * OPTIMAL_TIME_INC_FRACTION_NUM / OPTIMAL_TIME_INC_FRACTION_DEN;
        smp_max = time_left * PHASE_BASE_MAX_TIME_FRACTION_NUM / PHASE_BASE_MAX_TIME_FRACTION_DEN;
        if (smp_max > smp_optimal * MAX_TIME_OPTIMAL_MULTIPLIER)
            smp_max = smp_optimal * MAX_TIME_OPTIMAL_MULTIPLIER;
        if (smp_max > time_left - 0.1)
            smp_max = time_left - 0.1;
    }
    else
    {
        smp_optimal = time_limit;
        smp_max = time_limit;
    }

    for (int i = 0; i < num_threads; i++)
    {
        board_from_fen(&workers[i].board, fen);
        workers[i].shared_tt = shared_tt;
        workers[i].tt_cluster_count = tt_cluster_count_smp;
        workers[i].start_time = start_time;
        workers[i].time_limit = smp_optimal;
        workers[i].time_limit_max = smp_max;
        workers[i].node_limit = node_limit;
        workers[i].max_depth = max_depth;
        workers[i].thread_id = i;
        workers[i].num_threads = num_threads;
        workers[i].completed_depth = 0;
        workers[i].best_score = -MATE_SCORE;
        workers[i].nodes = 0;
        workers[i].aborted = 0;
        memset(&workers[i].best_move, 0, sizeof(Move));

        if (game_history && game_history_count > 0)
        {
            int gh_start = game_history_count > 512 ? game_history_count - 512 : 0;
            int limit = game_history_count > 512 ? 512 : game_history_count;
            memcpy(workers[i].game_history, game_history + gh_start, sizeof(U64) * limit);
            workers[i].game_history_count = limit;
        }
        else
        {
            workers[i].game_history_count = 0;
        }
    }

    for (int i = 1; i < num_threads; i++)
    {
#ifdef _WIN32
        workers[i].thread_handle = CreateThread(NULL, 4 * 1024 * 1024, smp_thread_func,
                                                &workers[i], 0, NULL);
        if (workers[i].thread_handle == NULL)
        {
            fprintf(stderr, "Warning: CreateThread failed for worker %d\n", i);
            num_threads = i; /* Use fewer threads */
            break;
        }
#else
        pthread_attr_t smp_attr;
        pthread_attr_init(&smp_attr);
        pthread_attr_setstacksize(&smp_attr, 4 * 1024 * 1024);
        int ret = pthread_create(&workers[i].thread_handle, &smp_attr, smp_thread_func, &workers[i]);
        pthread_attr_destroy(&smp_attr);
        if (ret != 0)
        {
            fprintf(stderr, "Warning: pthread_create failed for worker %d (error=%d)\n", i, ret);
            num_threads = i;
            break;
        }
#endif
    }

    smp_worker_search(&workers[0]);

    smp_set_stop(1);

    for (int i = 1; i < num_threads; i++)
    {
#ifdef _WIN32
        WaitForSingleObject(workers[i].thread_handle, INFINITE);
        CloseHandle(workers[i].thread_handle);
#else
        pthread_join(workers[i].thread_handle, NULL);
#endif
    }

    Move best_move = workers[0].best_move;
    int best_depth = workers[0].completed_depth;
    int best_score = workers[0].best_score;
    int total_nodes = workers[0].nodes;

    /* Task 6.1: Save per-thread SMP statistics */
    reset_smp_stats();
    g_smp_stats.num_threads = num_threads;
    for (int i = 0; i < num_threads; i++)
    {
        g_smp_stats.nodes_per_thread[i] = workers[i].nodes;
        g_smp_stats.depth_per_thread[i] = workers[i].completed_depth;
        fprintf(stderr, "  [SMP] Thread %d: %lld nodes, depth %d\n",
                i, (long long)workers[i].nodes, workers[i].completed_depth);
    }

    /* Task 6.2.3: Weighted voting mechanism for SMP result merging.
     * All workers that reached best_depth or best_depth-1 participate.
     * Vote weight = completed_depth. This favors consensus among workers
     * while still giving more weight to deeper searches. */
    for (int i = 1; i < num_threads; i++)
    {
        total_nodes += workers[i].nodes;
        if (workers[i].completed_depth > best_depth)
            best_depth = workers[i].completed_depth;
    }

    /* Build vote table */
    typedef struct
    {
        int from, to, promo;
        int total_weight;
        int best_score;
        int max_depth;
    } MoveVote;
    MoveVote votes[MAX_MOVES];
    int vote_count = 0;

    for (int i = 0; i < num_threads; i++)
    {
        if (workers[i].completed_depth < best_depth - 1)
            continue;
        int weight = workers[i].completed_depth > 0 ? workers[i].completed_depth : 1;
        int found = 0;
        for (int v = 0; v < vote_count; v++)
        {
            if (votes[v].from == workers[i].best_move.from &&
                votes[v].to == workers[i].best_move.to &&
                votes[v].promo == workers[i].best_move.promotion)
            {
                votes[v].total_weight += weight;
                if (workers[i].best_score > votes[v].best_score)
                    votes[v].best_score = workers[i].best_score;
                if (workers[i].completed_depth > votes[v].max_depth)
                    votes[v].max_depth = workers[i].completed_depth;
                found = 1;
                break;
            }
        }
        if (!found && vote_count < MAX_MOVES)
        {
            votes[vote_count].from = workers[i].best_move.from;
            votes[vote_count].to = workers[i].best_move.to;
            votes[vote_count].promo = workers[i].best_move.promotion;
            votes[vote_count].total_weight = weight;
            votes[vote_count].best_score = workers[i].best_score;
            votes[vote_count].max_depth = workers[i].completed_depth;
            vote_count++;
        }
    }

    /* Select move with highest total vote weight, but keep the main thread
     * (worker 0) authoritative when it kept pace with the deepest helper.
     * This prevents a single helper with a shuffled move order from overriding
     * the canonical iterative-deepening result and improves single-vs-multi
     * consistency on tactical positions. */
    if (vote_count > 0)
    {
        int best_weight = -1;
        int best_vote_idx = 0;
        for (int v = 0; v < vote_count; v++)
        {
            if (votes[v].total_weight > best_weight)
            {
                best_weight = votes[v].total_weight;
                best_vote_idx = v;
            }
        }

        /* Prefer worker 0 only when it actually reached the deepest iteration
         * completed by any worker.  If worker 0 is still behind (e.g. because
         * helpers started with a depth offset and finished an extra ply), trust
         * the deeper helper instead of falling back to a shallower result. */
        if (workers[0].completed_depth >= best_depth && workers[0].completed_depth > 0)
        {
            best_move = workers[0].best_move;
            best_depth = workers[0].completed_depth;
            best_score = workers[0].best_score;
        }
        else
        {
            /* Find the worker with the deepest search for the winning move. */
            for (int i = 0; i < num_threads; i++)
            {
                if (workers[i].best_move.from == votes[best_vote_idx].from &&
                    workers[i].best_move.to == votes[best_vote_idx].to &&
                    workers[i].best_move.promotion == votes[best_vote_idx].promo)
                {
                    if (workers[i].completed_depth > best_depth ||
                        (workers[i].completed_depth == best_depth && workers[i].best_score > best_score))
                    {
                        best_move = workers[i].best_move;
                        best_depth = workers[i].completed_depth;
                        best_score = workers[i].best_score;
                    }
                }
            }
        }
    }

    if (out_nodes)
        *out_nodes = total_nodes;

    g_last_search_depth = best_depth;
    g_last_search_nodes = total_nodes;
    g_last_best_score = best_score;

    /* The global TT generation has already been advanced by each worker's
     * smp_inc_tt_generation() calls, so no additional end-of-search bump is
     * needed.  The next search will increment it once more at start. */

    free(workers);
    return best_move;
}
