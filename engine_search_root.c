/* engine_search_root.c — 根搜索入口：时间管理、迭代加深、Lazy SMP（从 engine_core.c 拆分） */

/* Syzygy tablebase largest cardinality (exported from tbprobe.c via engine_debug.c) */
extern unsigned TB_LARGEST;

static void init_time_manager(TimeManager *tm, double time_left, double inc, int moves_to_go, int move_number, double start_time)
{
    tm->remaining = time_left;
    tm->increment = inc;
    tm->moves_to_go = moves_to_go;
    tm->move_number = move_number;
    tm->start_time = start_time;
    tm->easy_move_count = 0;
    tm->prev_best_move_from = -1;
    tm->prev_best_move_to = -1;
    tm->prev_best_promotion = 0;
    tm->stable_count = 0;
    tm->panic_flag = 0;

    /* Initialize instability detection */
    tm->history_count = 0;
    tm->instability_count = 0;
    for (int i = 0; i < 4; i++)
    {
        tm->score_history[i] = 0;
        tm->best_from_history[i] = -1;
        tm->best_to_history[i] = -1;
        tm->best_promo_history[i] = 0;
    }

    /* Initialize complexity and endgame factors */
    tm->complexity_factor = 1.0;
    tm->endgame_factor = 1.0;
    tm->is_endgame = 0;

    int estimated_moves = 25;
    if (moves_to_go > 0)
    {
        estimated_moves = moves_to_go + 5;
    }
    else
    {
        /* More nuanced move estimation based on game phase */
        if (move_number < 10)
            estimated_moves = 35 - move_number;
        else if (move_number < 20)
            estimated_moves = 25;
        else if (move_number < 30)
            estimated_moves = 22;
        else if (move_number < 40)
            estimated_moves = 18;
        else if (move_number < 60)
            estimated_moves = 15;
        else
            estimated_moves = 12;
    }

    tm->optimal_time = time_left / estimated_moves + inc * 0.85;
    if (tm->optimal_time > time_left * 0.6 + inc * 0.5)
        tm->optimal_time = time_left * 0.6 + inc * 0.5;

    tm->max_time = time_left * 0.6 + inc * 0.5;
    if (tm->max_time < tm->optimal_time * 3)
        tm->max_time = tm->optimal_time * 3;
    if (tm->max_time > time_left + inc * 0.9 - 0.05)
        tm->max_time = time_left + inc * 0.9 - 0.05;

    if (inc > 0 && time_left < inc * 5)
    {
        double inc_based_optimal = inc * 0.85;
        double inc_based_max = inc * 0.95;
        if (tm->optimal_time < inc_based_optimal)
            tm->optimal_time = inc_based_optimal;
        if (tm->max_time < inc_based_max)
            tm->max_time = inc_based_max;
    }

    /* Opening time discount - save time for later */
    if (move_number <= 10)
        tm->optimal_time *= 0.85;
    else if (move_number <= 20)
        tm->optimal_time *= 0.95;

    /* Extreme time pressure mode: remaining < 1 second
     * In this mode, we need to be very careful not to timeout.
     * Strategy: use minimal time, rely on increment if available.
     */
    if (time_left < 1.0)
    {
        /* Use at most half of remaining time or increment */
        double extreme_time = time_left * 0.4;
        if (inc > 0)
            extreme_time = inc * 0.8; /* Rely on increment */

        if (tm->optimal_time > extreme_time)
            tm->optimal_time = extreme_time;
        if (tm->max_time > time_left * 0.8)
            tm->max_time = time_left * 0.8;

        /* Ensure we leave some buffer to avoid timeout */
        if (tm->max_time > time_left - 0.05)
            tm->max_time = time_left - 0.05;
    }

    if (tm->optimal_time < 0.01)
        tm->optimal_time = 0.01;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
Move
find_best_move_c(const char *fen, double time_limit, double time_left, double increment, int moves_to_go, int move_number, int max_depth, int *out_nodes,
                 U64 *game_history, int game_history_count)
{
    static int params_loaded = 0;
    ensure_engine_tables_initialized();
    if (!params_loaded)
    {
        const char *env_path = getenv("ENGINE_PARAMS");
        if (env_path && env_path[0] != '\0')
        {
            load_params_from_file(env_path);
        }
        else
        {
            load_params_from_file("engine_params.json");
        }
        params_loaded = 1;
    }

    SearchState *s_ptr = (SearchState *)calloc(1, sizeof(SearchState));
    if (!s_ptr)
    {
        Move zero_move = {0, 0, 0, 0, 0};
        return zero_move;
    }
    SearchState *s = s_ptr;  /* Use pointer throughout */
    board_from_fen(&s->board, fen);
    s->start_time = get_time();
    s->aborted = 0;
    s->nodes = 0;
    g_engine_abort_flag = 0; /* Ensure abort flag is clear before starting search */
    {
        int si;
        for (si = 0; si < 128; si++)
            s->static_eval_stack[si] = EVAL_SCORE_INVALID;
    }

    TimeManager tm;
    init_time_manager(&tm, time_left > 0 ? time_left : time_limit, increment, moves_to_go, move_number, s->start_time);
    if (time_left <= 0)
    {
        tm.optimal_time = time_limit;
        tm.max_time = time_limit;
        tm.remaining = time_limit;
    }
    s->time_limit = tm.max_time;
    s->time_check_mask = 511;
    if (tm.optimal_time < 2.0)
        s->time_check_mask = 127;
    else if (tm.optimal_time < 5.0)
        s->time_check_mask = 255;
    tt_init_global(128);
    tt_clear_global();
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
        U64 root_key = s->board.hash;
        if (s->search_history_count < 256)
        {
            s->search_history[s->search_history_count] = root_key;
            s->search_history_count++;
        }
    }

    Move best_move = {0};
    int best_score = -INF;
    int prev_score = -INF;
    int depth;
    int i;
    int root_scores[MAX_MOVES];
    int scores_valid = 0;
    int early_terminate = 0;
    for (i = 0; i < MAX_MOVES; i++)
        root_scores[i] = -INF;

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
        if (out_nodes)
            *out_nodes = 1;
        Move single_move = root_moves[0];
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
            static const int victim_values[] = {0, 100, 300, 320, 500, 900, 0};
            static const int attacker_values[] = {0, 10, 30, 30, 50, 90, 0};
            int attacker = piece_on_square(b, m->from);
            priority += 10000 + victim_values[m->capture] - attacker_values[attacker];
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
                if (root_eval > 50)
                    priority -= 200000; /* Winning: avoid repetition */
                else if (root_eval < -50)
                    priority += 200000; /* Losing: seek repetition */
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
        int tt_root_val = tt_probe(s, s->board.hash, 1, -INF, INF, &tt_root_move, 0, NULL);
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
                    int w_mat = count_bits(s->board.pieces[WHITE][QUEEN]) * 900 +
                                count_bits(s->board.pieces[WHITE][ROOK]) * 480 +
                                count_bits(s->board.pieces[WHITE][BISHOP]) * 340 +
                                count_bits(s->board.pieces[WHITE][KNIGHT]) * 320;
                    int b_mat = count_bits(s->board.pieces[BLACK][QUEEN]) * 900 +
                                count_bits(s->board.pieces[BLACK][ROOK]) * 480 +
                                count_bits(s->board.pieces[BLACK][BISHOP]) * 340 +
                                count_bits(s->board.pieces[BLACK][KNIGHT]) * 320;
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
        root_tb_done:
            ;
        }
    }

    int material = count_total_material(&s->board);
    int depth_bonus = 0;
    if (material <= 4)
        depth_bonus = 4;
    else if (material <= 6)
        depth_bonus = 3;
    else if (material <= 10)
        depth_bonus = 2;
    else if (material <= 14)
        depth_bonus = 1;

    /* When max_depth=0 (no limit), use a very high default.
     * The depth_bonus is only meaningful when max_depth > 0. */
    int effective_max_depth;
    if (max_depth <= 0)
        effective_max_depth = 100; /* Unlimited - let time control the search */
    else
        effective_max_depth = max_depth + depth_bonus;

    /* Complexity and endgame detection for time management */
    {
        int legal_count = generate_legal_moves(&s->board, s->move_stack);
        int phase = s->board.phase;

        /* Endgame detection */
        if (phase <= 6)
        {
            tm.is_endgame = 1;
            tm.endgame_factor = 1.15; /* More time in endgame - positions are critical */
        }
        else if (phase <= 10)
        {
            tm.is_endgame = 1;
            tm.endgame_factor = 1.1;
        }

        /* Complexity factor based on legal moves count */
        if (legal_count > 35)
        {
            tm.complexity_factor = 1.3; /* Very complex position */
        }
        else if (legal_count > 28)
        {
            tm.complexity_factor = 1.15; /* Complex position */
        }
        else if (legal_count < 10)
        {
            tm.complexity_factor = 0.8; /* Simple position, few legal moves */
        }
        else if (legal_count < 15)
        {
            tm.complexity_factor = 0.9; /* Relatively simple */
        }

        /* Check if in check - add more time */
        if (is_check(&s->board, s->board.side_to_move))
        {
            tm.complexity_factor *= 1.2;
        }
    }

    int window = 50;
    int aw_hits = 0;
    int aw_fails = 0;

    /* Extreme time pressure: limit max depth to avoid timeout */
    int extreme_time_mode = (tm.remaining < 1.0 && tm.remaining > 0);
    if (extreme_time_mode)
    {
        /* In extreme time pressure, limit depth to 6-8 */
        int extreme_depth = 6;
        if (tm.increment > 0.1)
            extreme_depth = 8; /* With increment, we can search deeper */
        if (effective_max_depth > extreme_depth)
            effective_max_depth = extreme_depth;
    }

    for (depth = 1; depth <= effective_max_depth; depth++)
    {
        double elapsed = get_time() - tm.start_time;
        if (elapsed >= tm.optimal_time * 0.85 && depth > 1)
        {
            break;
        }

        int nodes_before = s->nodes;

        Move current_best = {0};
        int current_score = -INF;
        int alpha, beta;

        if (depth <= 1)
        {
            alpha = -INF;
            beta = INF;

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
            if (abs(best_score) > MATE_SCORE - 100 || abs(best_score) > 1500)
            {
                alpha = -INF;
                beta = INF;
            }
            else
            {
                alpha = best_score - window;
                beta = best_score + window;
            }

            while (1)
            {
                if (alpha < -INF)
                    alpha = -INF;
                if (beta > INF)
                    beta = INF;

                current_score = -INF;
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
                    window += window / 2 + 10;
                    alpha = best_score - window;
                    if (alpha < -INF)
                        alpha = -INF;
                    /* Don't widen beta on fail-low */
                }
                else if (current_score >= beta)
                {
                    aw_fails++;
                    /* Fail-high: raise beta with asymmetric growth */
                    window += window / 2 + 10;
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

                /* If window gets too large, fall back to full window */
                if (window > 500)
                {
                    alpha = -INF;
                    beta = INF;
                    break;
                }
            }
        }

        if (!s->aborted && current_score > -INF)
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
                int pi;
                for (pi = 0; pi < pv_len && pi < 32; pi++)
                {
                    Move *pm = &s->pv_table[0][pi];
                    if (pm->from == 0 && pm->to == 0 && pi > 0)
                        break;
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
                        s->history[hi][hj] = s->history[hi][hj] * 9 / 10;
                    }
                }
            }
            /* In clearly winning positions, keep full window to avoid
             * missing forced mates due to narrow aspiration. */
            if (abs(best_score) > 1500)
                window = 500; /* effectively full window after first iteration */
            else
                window = 25;
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

            /* Early termination: stable best move with improving score */
            if (tm.stable_count >= 3 && current_score >= prev_score - 10)
            {
                double em_elapsed = get_time() - tm.start_time;
                if (em_elapsed >= tm.optimal_time * 0.3)
                {
                    early_terminate = 1;
                }
            }

            if (tm.stable_count >= 5 && current_score >= prev_score - 20)
            {
                double em_elapsed = get_time() - tm.start_time;
                if (em_elapsed >= tm.optimal_time * 0.2)
                {
                    early_terminate = 1;
                }
            }

            /* Improved panic mode: detect score volatility */
            {
                int score_drop = prev_score - current_score;
                if (score_drop >= 25 && depth >= 4)
                {
                    tm.panic_flag = 1;
                }
                /* Recover from panic when score stabilizes or improves */
                if (tm.panic_flag && current_score >= prev_score + 15)
                {
                    tm.panic_flag = 0;
                }
            }

            /* Dynamic time limit adjustment based on search state */
            {
                double base_limit = tm.optimal_time * 1.5;
                double final_limit;

                if (tm.panic_flag)
                {
                    /* Panic: give more time to find a good move */
                    base_limit = tm.optimal_time * 3.0;
                }
                else if (tm.instability_count >= 3 && depth >= 6)
                {
                    /* Unstable search: best move keeps changing, need more time */
                    base_limit = tm.optimal_time * 2.5;
                    tm.instability_count = 0; /* Reset after adjustment */
                }
                else if (current_score > 500 && depth >= 6)
                {
                    /* Winning position: can afford to spend less time */
                    base_limit = tm.optimal_time * 1.2;
                }
                else if (tm.is_endgame)
                {
                    /* Endgame: slightly less time as positions are more concrete */
                    base_limit = tm.optimal_time * tm.endgame_factor;
                }

                /* Apply complexity factor */
                base_limit *= tm.complexity_factor;

                /* Clamp to max_time */
                final_limit = (base_limit < tm.max_time) ? base_limit : tm.max_time;
                s->time_limit = final_limit;
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
        const char *env_path = getenv("ENGINE_PARAMS");
        if (env_path && env_path[0] != '\0')
        {
            load_params_from_file(env_path);
        }
        else
        {
            load_params_from_file("engine_params.json");
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
        alpha = -INF;
        beta = INF;
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
 * ============================================================================
 */

typedef struct
{
    Board board;
    TT_Cluster *shared_tt;
    int tt_cluster_count;
    double start_time;
    double time_limit;
    double time_limit_max;
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
    s->board = w->board;
    s->start_time = w->start_time;
    s->time_limit = w->time_limit;
    s->aborted = 0;
    s->nodes = 0;
    s->tt = w->shared_tt;
    s->tt_cluster_count = w->tt_cluster_count;
    s->tt_generation = g_tt_generation;
    s->search_history_count = 0;
    s->game_history_count = w->game_history_count;
    if (w->game_history_count > 0)
    {
        int limit = w->game_history_count < 512 ? w->game_history_count : 512;
        memcpy(s->game_history, w->game_history, sizeof(U64) * limit);
        s->game_history_count = limit;
    }

    {
        U64 root_key = s->board.hash;
        if (s->search_history_count < 256)
        {
            s->search_history[s->search_history_count] = root_key;
            s->search_history_count++;
        }
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

    int start_depth = 1 + (w->thread_id % 4);
    int depth_step = 1;
    int smp_max_depth = w->max_depth;
    if (smp_max_depth <= 0)
        smp_max_depth = 100; /* Unlimited - let time control the search */

    Move best_move = root_moves[0];
    int best_score = -INF;
    w->best_move = best_move;
    w->best_score = best_score;

    for (int depth = start_depth; depth <= smp_max_depth; depth += depth_step)
    {
        if (smp_get_stop())
            break;
        if (depth >= 5)
        {
            double elapsed = get_time() - s->start_time;
            if (elapsed >= w->time_limit * 0.7)
                break;
        }

        int nodes_before = s->nodes;
        Move current_best = {0};
        int current_score = -INF;
        int alpha = -INF, beta = INF;

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

            if (score > current_score)
            {
                current_score = score;
                current_best = root_moves[i];
                if (score > alpha)
                    alpha = score;
            }
        }

        if (!s->aborted && !smp_get_stop() && current_score > -INF)
        {
            best_move = current_best;
            best_move.score = current_score;
            best_score = current_score;
            w->completed_depth = depth;
            w->nodes = s->nodes;
            w->best_move = best_move;
            w->best_score = best_score;

            for (int j = 0; j < legal_count; j++)
            {
                if (root_moves[j].from == current_best.from &&
                    root_moves[j].to == current_best.to &&
                    root_moves[j].promotion == current_best.promotion)
                {
                    Move tmp = root_moves[0];
                    root_moves[0] = root_moves[j];
                    root_moves[j] = tmp;
                    break;
                }
            }
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
                   int *out_nodes, U64 *game_history, int game_history_count)
{
    static int params_loaded_smp = 0;
    ensure_engine_tables_initialized();
    if (!params_loaded_smp)
    {
        const char *env_path = getenv("ENGINE_PARAMS");
        if (env_path && env_path[0] != '\0')
        {
            load_params_from_file(env_path);
        }
        else
        {
            load_params_from_file("engine_params.json");
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
        return find_best_move_c(fen, time_limit, time_left, increment, moves_to_go, move_number, max_depth, out_nodes,
                                game_history, game_history_count);
    }

    int tt_cluster_count_smp;
    tt_init_global(128);
    tt_clear_global();
    TT_Cluster *shared_tt = g_tt;
    tt_cluster_count_smp = g_tt_cluster_count;

    LazySMPWorker *workers = (LazySMPWorker *)calloc(num_threads, sizeof(LazySMPWorker));
    if (!workers)
    {
        return find_best_move_c(fen, time_limit, time_left, increment, moves_to_go, move_number, max_depth, out_nodes,
                                game_history, game_history_count);
    }

    smp_set_stop(0);
    double start_time = get_time();

    TimeManager tm_smp;
    double smp_optimal;
    double smp_max;
    if (time_left > 0)
    {
        smp_optimal = time_limit;
        smp_max = time_left * 0.4;
        if (smp_max < smp_optimal * 3)
            smp_max = smp_optimal * 3;
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
        workers[i].max_depth = max_depth;
        workers[i].thread_id = i;
        workers[i].num_threads = num_threads;
        workers[i].completed_depth = 0;
        workers[i].best_score = -INF;
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

    for (int i = 1; i < num_threads; i++)
    {
        total_nodes += workers[i].nodes;
        if (workers[i].completed_depth > best_depth ||
            (workers[i].completed_depth == best_depth && workers[i].best_score > best_score))
        {
            best_move = workers[i].best_move;
            best_depth = workers[i].completed_depth;
            best_score = workers[i].best_score;
        }
    }

    if (out_nodes)
        *out_nodes = total_nodes;

    g_last_search_depth = best_depth;
    g_last_search_nodes = total_nodes;
    g_last_best_score = best_score;

    free(workers);
    return best_move;
}
