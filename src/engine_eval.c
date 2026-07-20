/* engine_eval.c 鈥?璇勪及鍑芥暟妯″潡锛堜粠 engine_core.c 鎷嗗垎锛?*/
static int count_total_pieces(Board *b)
{
    int count = 0;
    int side, pt;
    for (side = 0; side < 2; side++)
    {
        for (pt = PAWN; pt < KING; pt++)
        {
            count += count_bits(b->pieces[side][pt]);
        }
    }
    return count;
}

static int tb_wdl_simple(Board *b)
{
    int w_pawns = count_bits(b->pieces[WHITE][PAWN]);
    int b_pawns = count_bits(b->pieces[BLACK][PAWN]);
    int w_knights = count_bits(b->pieces[WHITE][KNIGHT]);
    int b_knights = count_bits(b->pieces[BLACK][KNIGHT]);
    int w_bishops = count_bits(b->pieces[WHITE][BISHOP]);
    int b_bishops = count_bits(b->pieces[BLACK][BISHOP]);
    int w_rooks = count_bits(b->pieces[WHITE][ROOK]);
    int b_rooks = count_bits(b->pieces[BLACK][ROOK]);
    int w_queens = count_bits(b->pieces[WHITE][QUEEN]);
    int b_queens = count_bits(b->pieces[BLACK][QUEEN]);

    int w_pieces = w_pawns + w_knights + w_bishops + w_rooks + w_queens;
    int b_pieces = b_pawns + b_knights + b_bishops + b_rooks + b_queens;
    int total = w_pieces + b_pieces;

    if (total > 3)
        return -2;

    if (total == 0)
        return 0;

    if (total == 1)
    {
        if (w_queens == 1 || w_rooks == 1)
            return 1;
        if (b_queens == 1 || b_rooks == 1)
            return -1;
        return 0;
    }

    if (total == 2)
    {
        if (w_pieces == 2)
        {
            if (w_queens == 2 || w_rooks == 2 || (w_queens == 1 && w_rooks == 1))
                return 1;
            if (w_bishops == 2)
                return 1;
        }
        if (b_pieces == 2)
        {
            if (b_queens == 2 || b_rooks == 2 || (b_queens == 1 && b_rooks == 1))
                return -1;
            if (b_bishops == 2)
                return -1;
        }
        return 0;
    }

    if (total == 3)
    {
        if (w_pieces == 3)
        {
            if (w_queens >= 1 || w_rooks >= 2)
                return 1;
        }
        if (b_pieces == 3)
        {
            if (b_queens >= 1 || b_rooks >= 2)
                return -1;
        }
        return 0;
    }

    return -2;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
int
evaluate(Board *b)
{
    if (b->eval_score != EVAL_SCORE_INVALID)
        return b->eval_score;

    g_prof_eval_calls++;
    int score = 0;
    int side, pt;
    int npm_w = b->npm[0], npm_b = b->npm[1];

    int phase = b->phase;

    int phase_weight = (phase * 256 + 12) / 24;  /* +12 for rounding instead of truncation */

    /* Runtime-evaluated parameters: use g_runtime_params when loaded, else compile-time defaults */
    int doubled_pawn_penalty = g_runtime_params.loaded ? g_runtime_params.doubled_pawn_penalty : DOUBLED_PAWN_PENALTY;
    int isolated_pawn_penalty = g_runtime_params.loaded ? g_runtime_params.isolated_pawn_penalty : ISOLATED_PAWN_PENALTY;
    int isolated_open_file_mul_num = g_runtime_params.loaded ? g_runtime_params.isolated_open_file_mul_num : ISOLATED_OPEN_FILE_MUL_NUM;
    int isolated_open_file_mul_den = g_runtime_params.loaded ? g_runtime_params.isolated_open_file_mul_den : ISOLATED_OPEN_FILE_MUL_DEN;
    int backward_pawn_penalty = g_runtime_params.loaded ? g_runtime_params.backward_pawn_penalty : BACKWARD_PAWN_PENALTY;
    int passed_pawn_supported_bonus = g_runtime_params.loaded ? g_runtime_params.passed_pawn_supported_bonus : PASSED_PAWN_SUPPORTED_BONUS;
    int passed_pawn_blocked_base = g_runtime_params.loaded ? g_runtime_params.passed_pawn_blocked_base : PASSED_PAWN_BLOCKED_BASE;
    int passed_pawn_clear_path_base = g_runtime_params.loaded ? g_runtime_params.passed_pawn_clear_path_base : PASSED_PAWN_CLEAR_PATH_BASE;
    int passed_pawn_king_dist_base = g_runtime_params.loaded ? g_runtime_params.passed_pawn_king_dist_base : PASSED_PAWN_KING_DIST_BASE;
    int pawn_chain_bonus = g_runtime_params.loaded ? g_runtime_params.pawn_chain_bonus : PAWN_CHAIN_BONUS;
    int center_pawn_mg_bonus = g_runtime_params.loaded ? g_runtime_params.center_pawn_mg_bonus : CENTER_PAWN_MG_BONUS;
    int connected_passer_bonus = g_runtime_params.loaded ? g_runtime_params.connected_passer_bonus : CONNECTED_PASSER_BONUS;
    int pawn_chain_lateral_bonus = g_runtime_params.loaded ? g_runtime_params.pawn_chain_lateral_bonus : PAWN_CHAIN_LATERAL_BONUS;
    int center_pawn_pair_bonus = g_runtime_params.loaded ? g_runtime_params.center_pawn_pair_bonus : CENTER_PAWN_PAIR_BONUS;
    int bishop_pair_bonus = g_runtime_params.loaded ? g_runtime_params.bishop_pair_bonus : BISHOP_PAIR_BONUS;
    int open_file_bonus = g_runtime_params.loaded ? g_runtime_params.open_file_bonus : OPEN_FILE_BONUS;
    int semi_open_file_bonus = g_runtime_params.loaded ? g_runtime_params.semi_open_file_bonus : SEMI_OPEN_FILE_BONUS;
    int bishop_mobility_bonus = g_runtime_params.loaded ? g_runtime_params.bishop_mobility_bonus : BISHOP_MOBILITY_BONUS;
    int bishop_bad_penalty = g_runtime_params.loaded ? g_runtime_params.bishop_bad_penalty : BISHOP_BAD_PENALTY;
    int rook_on_7th_mg_bonus = g_runtime_params.loaded ? g_runtime_params.rook_on_7th_mg_bonus : ROOK_ON_7TH_MG_BONUS;
    int rook_on_7th_eg_bonus = g_runtime_params.loaded ? g_runtime_params.rook_on_7th_eg_bonus : ROOK_ON_7TH_EG_BONUS;
    int center_control_piece_bonus = g_runtime_params.loaded ? g_runtime_params.center_control_piece_bonus : CENTER_CONTROL_PIECE_BONUS;
    int center_control_pawn_bonus = g_runtime_params.loaded ? g_runtime_params.center_control_pawn_bonus : CENTER_CONTROL_PAWN_BONUS;
    int hanging_queen_penalty = g_runtime_params.loaded ? g_runtime_params.hanging_queen_penalty : HANGING_QUEEN_PENALTY;
    int hanging_rook_penalty = g_runtime_params.loaded ? g_runtime_params.hanging_rook_penalty : HANGING_ROOK_PENALTY;
    int hanging_minor_penalty = g_runtime_params.loaded ? g_runtime_params.hanging_minor_penalty : HANGING_MINOR_PENALTY;
    int in_check_penalty = g_runtime_params.loaded ? g_runtime_params.in_check_penalty : IN_CHECK_PENALTY;
    int knight_edge_penalty = g_runtime_params.loaded ? g_runtime_params.knight_edge_penalty : KNIGHT_EDGE_PENALTY;
    int knight_initial_block_penalty = g_runtime_params.loaded ? g_runtime_params.knight_initial_block_penalty : KNIGHT_INITIAL_BLOCK_PENALTY;
    int imbalance_mg_base = g_runtime_params.loaded ? g_runtime_params.imbalance_mg_base : IMBALANCE_MG_BASE;
    int imbalance_mg_scale = g_runtime_params.loaded ? g_runtime_params.imbalance_mg_scale : IMBALANCE_MG_SCALE;
    int imbalance_eg_scale = g_runtime_params.loaded ? g_runtime_params.imbalance_eg_scale : IMBALANCE_EG_SCALE;
    int no_minor_vs_two_minor_penalty = g_runtime_params.loaded ? g_runtime_params.no_minor_vs_two_minor_penalty : NO_MINOR_VS_TWO_MINOR_PENALTY;
    int mopup_material_threshold = g_runtime_params.loaded ? g_runtime_params.mopup_material_threshold : MOPUP_MATERIAL_THRESHOLD;
    int simplify_threshold = g_runtime_params.loaded ? g_runtime_params.simplify_threshold : SIMPLIFY_THRESHOLD;
    int simplify_bonus = g_runtime_params.loaded ? g_runtime_params.simplify_bonus : SIMPLIFY_BONUS;
    int castle_short_bonus = g_runtime_params.loaded ? g_runtime_params.castle_short_bonus : CASTLE_SHORT_BONUS;
    int castle_long_bonus = g_runtime_params.loaded ? g_runtime_params.castle_long_bonus : CASTLE_LONG_BONUS;
    int tempo_mg = g_runtime_params.loaded ? g_runtime_params.tempo_mg : TEMPO_MG;
    int tempo_eg = g_runtime_params.loaded ? g_runtime_params.tempo_eg : TEMPO_EG;
    int mopup_edge_weight = g_runtime_params.loaded ? g_runtime_params.mopup_edge_weight : MOPUP_EDGE_WEIGHT;
    int mopup_proximity_weight = g_runtime_params.loaded ? g_runtime_params.mopup_proximity_weight : MOPUP_PROXIMITY_WEIGHT;
    int mopup_opposition_weight = g_runtime_params.loaded ? g_runtime_params.mopup_opposition_weight : MOPUP_OPPOSITION_WEIGHT;
    int opposite_bishop_draw_factor_no_pawn = g_runtime_params.loaded ? g_runtime_params.opposite_bishop_draw_factor_no_pawn : OPPOSITE_BISHOP_DRAW_FACTOR_NO_PAWN;
    int opposite_bishop_draw_factor_pawn = g_runtime_params.loaded ? g_runtime_params.opposite_bishop_draw_factor_pawn : OPPOSITE_BISHOP_DRAW_FACTOR_PAWN;
    int eval_passed_pawn_bonus[8];
    if (g_runtime_params.loaded)
    {
        memcpy(eval_passed_pawn_bonus, g_runtime_params.passed_pawn_bonus, sizeof(eval_passed_pawn_bonus));
    }
    else
    {
        memcpy(eval_passed_pawn_bonus, passed_pawn_bonus, sizeof(eval_passed_pawn_bonus));
    }

    /* King Danger parameters */
    int king_danger_cap = g_runtime_params.loaded ? g_runtime_params.king_danger_cap : KING_DANGER_CAP;
    int knight_attack_base = g_runtime_params.loaded ? g_runtime_params.knight_attack_base : KNIGHT_ATTACK_BASE;
    int bishop_attack_base = g_runtime_params.loaded ? g_runtime_params.bishop_attack_base : BISHOP_ATTACK_BASE;
    int rook_attack_base = g_runtime_params.loaded ? g_runtime_params.rook_attack_base : ROOK_ATTACK_BASE;
    int queen_attack_base = g_runtime_params.loaded ? g_runtime_params.queen_attack_base : QUEEN_ATTACK_BASE;
    int knight_attack_per_sq = g_runtime_params.loaded ? g_runtime_params.knight_attack_per_sq : KNIGHT_ATTACK_PER_SQ;
    int bishop_attack_per_sq = g_runtime_params.loaded ? g_runtime_params.bishop_attack_per_sq : BISHOP_ATTACK_PER_SQ;
    int rook_attack_per_sq = g_runtime_params.loaded ? g_runtime_params.rook_attack_per_sq : ROOK_ATTACK_PER_SQ;
    int queen_attack_per_sq = g_runtime_params.loaded ? g_runtime_params.queen_attack_per_sq : QUEEN_ATTACK_PER_SQ;
    int pawn_shield_rank2_penalty = g_runtime_params.loaded ? g_runtime_params.pawn_shield_rank2_penalty : PAWN_SHIELD_RANK2_PENALTY;
    int pawn_shield_no_pawn_penalty = g_runtime_params.loaded ? g_runtime_params.pawn_shield_no_pawn_penalty : PAWN_SHIELD_NO_PAWN_PENALTY;
    int open_file_king_zone_penalty = g_runtime_params.loaded ? g_runtime_params.open_file_king_zone_penalty : OPEN_FILE_KING_ZONE_PENALTY;
    int semi_open_file_king_zone_penalty = g_runtime_params.loaded ? g_runtime_params.semi_open_file_king_zone_penalty : SEMI_OPEN_FILE_KING_ZONE_PENALTY;
    int attacker_count_bonus = g_runtime_params.loaded ? g_runtime_params.attacker_count_bonus : ATTACKER_COUNT_BONUS;
    int king_danger_eg_scale_base = g_runtime_params.loaded ? g_runtime_params.king_danger_eg_scale_base : KING_DANGER_EG_SCALE_BASE;
    int king_danger_eg_scale_phase = g_runtime_params.loaded ? g_runtime_params.king_danger_eg_scale_phase : KING_DANGER_EG_SCALE_PHASE;
    int eval_king_danger_table[128];
    if (g_runtime_params.loaded)
        memcpy(eval_king_danger_table, g_runtime_params.king_danger_table, sizeof(eval_king_danger_table));
    else
        memcpy(eval_king_danger_table, king_danger_table, sizeof(eval_king_danger_table));

    /* Center Control Extended */
    int center_control_extended_bonus = g_runtime_params.loaded ? g_runtime_params.center_control_extended_bonus : CENTER_CONTROL_EXTENDED_BONUS;
    int center_control_pawn_extended_bonus = g_runtime_params.loaded ? g_runtime_params.center_control_pawn_extended_bonus : CENTER_CONTROL_PAWN_EXTENDED_BONUS;

    /* Back Rank Threats */
    int back_rank_mate_penalty = g_runtime_params.loaded ? g_runtime_params.back_rank_mate_penalty : BACK_RANK_MATE_PENALTY;
    int back_rank_triple_penalty = g_runtime_params.loaded ? g_runtime_params.back_rank_triple_penalty : BACK_RANK_TRIPLE_PENALTY;

    /* Knight Outpost */
    int outpost_mg_base = g_runtime_params.loaded ? g_runtime_params.outpost_mg_base : OUTPOST_MG_BASE;
    int outpost_mg_rank_scale = g_runtime_params.loaded ? g_runtime_params.outpost_mg_rank_scale : OUTPOST_MG_RANK_SCALE;
    int outpost_eg_base = g_runtime_params.loaded ? g_runtime_params.outpost_eg_base : OUTPOST_EG_BASE;
    int outpost_eg_rank_scale = g_runtime_params.loaded ? g_runtime_params.outpost_eg_rank_scale : OUTPOST_EG_RANK_SCALE;

    /* Attacked by Pawn/Knight */
    int queen_attacked_by_pawn_penalty = g_runtime_params.loaded ? g_runtime_params.queen_attacked_by_pawn_penalty : QUEEN_ATTACKED_BY_PAWN_PENALTY;
    int rook_attacked_by_pawn_penalty = g_runtime_params.loaded ? g_runtime_params.rook_attacked_by_pawn_penalty : ROOK_ATTACKED_BY_PAWN_PENALTY;
    int minor_attacked_by_pawn_penalty = g_runtime_params.loaded ? g_runtime_params.minor_attacked_by_pawn_penalty : MINOR_ATTACKED_BY_PAWN_PENALTY;
    int queen_attacked_by_pawn_extra = g_runtime_params.loaded ? g_runtime_params.queen_attacked_by_pawn_extra : QUEEN_ATTACKED_BY_PAWN_EXTRA;
    int rook_attacked_by_pawn_extra = g_runtime_params.loaded ? g_runtime_params.rook_attacked_by_pawn_extra : ROOK_ATTACKED_BY_PAWN_EXTRA;
    int queen_attacked_by_knight_penalty = g_runtime_params.loaded ? g_runtime_params.queen_attacked_by_knight_penalty : QUEEN_ATTACKED_BY_KNIGHT_PENALTY;
    int rook_attacked_by_knight_penalty = g_runtime_params.loaded ? g_runtime_params.rook_attacked_by_knight_penalty : ROOK_ATTACKED_BY_KNIGHT_PENALTY;
    int minor_attacked_by_knight_penalty = g_runtime_params.loaded ? g_runtime_params.minor_attacked_by_knight_penalty : MINOR_ATTACKED_BY_KNIGHT_PENALTY;
    int piece_defended_by_pawn_bonus = g_runtime_params.loaded ? g_runtime_params.piece_defended_by_pawn_bonus : PIECE_DEFENDED_BY_PAWN_BONUS;

    /* Fork/Threat */
    int knight_fork_queen_rook_penalty = g_runtime_params.loaded ? g_runtime_params.knight_fork_queen_rook_penalty : KNIGHT_FORK_QUEEN_ROOK_PENALTY;
    int knight_fork_king_penalty = g_runtime_params.loaded ? g_runtime_params.knight_fork_king_penalty : KNIGHT_FORK_KING_PENALTY;
    int queen_attacked_by_minor_undefended = g_runtime_params.loaded ? g_runtime_params.queen_attacked_by_minor_undefended : QUEEN_ATTACKED_BY_MINOR_UNDEFENDED;
    int queen_attacked_by_minor_defended = g_runtime_params.loaded ? g_runtime_params.queen_attacked_by_minor_defended : QUEEN_ATTACKED_BY_MINOR_DEFENDED;
    int rook_attacked_by_minor_undefended = g_runtime_params.loaded ? g_runtime_params.rook_attacked_by_minor_undefended : ROOK_ATTACKED_BY_MINOR_UNDEFENDED;
    int rook_attacked_by_minor_defended = g_runtime_params.loaded ? g_runtime_params.rook_attacked_by_minor_defended : ROOK_ATTACKED_BY_MINOR_DEFENDED;
    int minor_attacked_by_minor_undefended = g_runtime_params.loaded ? g_runtime_params.minor_attacked_by_minor_undefended : MINOR_ATTACKED_BY_MINOR_UNDEFENDED;
    int minor_attacked_by_minor_defended = g_runtime_params.loaded ? g_runtime_params.minor_attacked_by_minor_defended : MINOR_ATTACKED_BY_MINOR_DEFENDED;
    int piece_attacked_by_rook_undefended = g_runtime_params.loaded ? g_runtime_params.piece_attacked_by_rook_undefended : PIECE_ATTACKED_BY_ROOK_UNDEFENDED;
    int piece_attacked_by_rook_defended = g_runtime_params.loaded ? g_runtime_params.piece_attacked_by_rook_defended : PIECE_ATTACKED_BY_ROOK_DEFENDED;
    int piece_attacked_by_bishop_undefended = g_runtime_params.loaded ? g_runtime_params.piece_attacked_by_bishop_undefended : PIECE_ATTACKED_BY_BISHOP_UNDEFENDED;
    int piece_attacked_by_bishop_defended = g_runtime_params.loaded ? g_runtime_params.piece_attacked_by_bishop_defended : PIECE_ATTACKED_BY_BISHOP_DEFENDED;

    /* Opening Development Extended (閫氱敤鍖栵細浠呬繚鐣欏悗/杞﹁繃鏃╁墠鍘嬪師鍒欙紝宸插彂灞?杞诲瓙绂诲紑宸辨柟搴曠嚎) */
    int opening_early_queen_advance_base = g_runtime_params.loaded ? g_runtime_params.opening_early_queen_advance_base : OPENING_EARLY_QUEEN_ADVANCE_BASE;
    int opening_early_queen_advance_scale = g_runtime_params.loaded ? g_runtime_params.opening_early_queen_advance_scale : OPENING_EARLY_QUEEN_ADVANCE_SCALE;
    int opening_early_queen_advance_min = g_runtime_params.loaded ? g_runtime_params.opening_early_queen_advance_min : OPENING_EARLY_QUEEN_ADVANCE_MIN;
    int opening_early_rook_advance_penalty = g_runtime_params.loaded ? g_runtime_params.opening_early_rook_advance_penalty : OPENING_EARLY_ROOK_ADVANCE_PENALTY;

    /* Fifty Move Rule */
    int fifty_move_urgency_divisor = g_runtime_params.loaded ? g_runtime_params.fifty_move_urgency_divisor : FIFTY_MOVE_URGENCY_DIVISOR;

    /* Mopup Extended */
    int mopup_winning_king_activity_weight = g_runtime_params.loaded ? g_runtime_params.mopup_winning_king_activity_weight : MOPUP_WINNING_KING_ACTIVITY_WEIGHT;
    int mopup_losing_king_activity_weight = g_runtime_params.loaded ? g_runtime_params.mopup_losing_king_activity_weight : MOPUP_LOSING_KING_ACTIVITY_WEIGHT;
    int mopup_king_activity_early_phase = g_runtime_params.loaded ? g_runtime_params.mopup_king_activity_early_phase : MOPUP_KING_ACTIVITY_EARLY_PHASE;
    int mopup_king_activity_early_weight = g_runtime_params.loaded ? g_runtime_params.mopup_king_activity_early_weight : MOPUP_KING_ACTIVITY_EARLY_WEIGHT;
    int mopup_generic_edge_scale = g_runtime_params.loaded ? g_runtime_params.mopup_generic_edge_scale : MOPUP_GENERIC_EDGE_SCALE;
    int mopup_generic_proximity_scale = g_runtime_params.loaded ? g_runtime_params.mopup_generic_proximity_scale : MOPUP_GENERIC_PROXIMITY_SCALE;

    /* Anti-Simplify */
    int anti_simplify_per_piece_scale = g_runtime_params.loaded ? g_runtime_params.anti_simplify_per_piece_scale : ANTI_SIMPLIFY_PER_PIECE_SCALE;
    int anti_simplify_piece_threshold = g_runtime_params.loaded ? g_runtime_params.anti_simplify_piece_threshold : ANTI_SIMPLIFY_PIECE_THRESHOLD;

    /* Specific Endgames KRK/KQKR/KBNK */
    int krk_rook_cutoff_bonus = g_runtime_params.loaded ? g_runtime_params.krk_rook_cutoff_bonus : KRK_ROOK_CUTOFF_BONUS;
    int krk_rook_far_penalty = g_runtime_params.loaded ? g_runtime_params.krk_rook_far_penalty : KRK_ROOK_FAR_PENALTY;
    int kqkr_corner_scale = g_runtime_params.loaded ? g_runtime_params.kqkr_corner_scale : KQKR_CORNER_SCALE;
    int kqkr_proximity_scale = g_runtime_params.loaded ? g_runtime_params.kqkr_proximity_scale : KQKR_PROXIMITY_SCALE;
    int kqkr_queen_proximity_scale = g_runtime_params.loaded ? g_runtime_params.kqkr_queen_proximity_scale : KQKR_QUEEN_PROXIMITY_SCALE;
    int kqkr_stalemate_avoid_penalty = g_runtime_params.loaded ? g_runtime_params.kqkr_stalemate_avoid_penalty : KQKR_STALEMATE_AVOID_PENALTY;
    int kqkr_corner_mate_bonus = g_runtime_params.loaded ? g_runtime_params.kqkr_corner_mate_bonus : KQKR_CORNER_MATE_BONUS;
    int kbnk_corner_scale = g_runtime_params.loaded ? g_runtime_params.kbnk_corner_scale : KBNK_CORNER_SCALE;
    int kbnk_proximity_scale = g_runtime_params.loaded ? g_runtime_params.kbnk_proximity_scale : KBNK_PROXIMITY_SCALE;
    int kbnk_correct_corner_bonus = g_runtime_params.loaded ? g_runtime_params.kbnk_correct_corner_bonus : KBNK_CORRECT_CORNER_BONUS;

    /* Extended Mopup */
    int extended_mopup_edge_scale = g_runtime_params.loaded ? g_runtime_params.extended_mopup_edge_scale : EXTENDED_MOPUP_EDGE_SCALE;
    int extended_mopup_proximity_scale = g_runtime_params.loaded ? g_runtime_params.extended_mopup_proximity_scale : EXTENDED_MOPUP_PROXIMITY_SCALE;

    /* Opposite Bishop Draw */
    int opposite_bishop_draw_divisor = g_runtime_params.loaded ? g_runtime_params.opposite_bishop_draw_divisor : OPPOSITE_BISHOP_DRAW_DIVISOR;

    /* Rook 7th Extended */
    int rook_on_7th_double_bonus = g_runtime_params.loaded ? g_runtime_params.rook_on_7th_double_bonus : ROOK_ON_7TH_DOUBLE_BONUS;
    int rook_on_7th_king_rank8_bonus = g_runtime_params.loaded ? g_runtime_params.rook_on_7th_king_rank8_bonus : ROOK_ON_7TH_KING_RANK8_BONUS;
    int rook_on_7th_double_king_rank8_bonus = g_runtime_params.loaded ? g_runtime_params.rook_on_7th_double_king_rank8_bonus : ROOK_ON_7TH_DOUBLE_KING_RANK8_BONUS;

    /* Rook Potential */
    int rook_potential_open_file = g_runtime_params.loaded ? g_runtime_params.rook_potential_open_file : ROOK_POTENTIAL_OPEN_FILE;
    int rook_potential_semi_open = g_runtime_params.loaded ? g_runtime_params.rook_potential_semi_open : ROOK_POTENTIAL_SEMI_OPEN;

    U64 occupied = all_pieces(b);
    U64 bishop_atk[2][MAX_SLIDERS];
    U64 rook_atk[2][MAX_SLIDERS];
    U64 queen_batk[2][MAX_SLIDERS];
    U64 queen_ratk[2][MAX_SLIDERS];
    int bishop_sqs[2][MAX_SLIDERS];
    int rook_sqs[2][MAX_SLIDERS];
    int queen_sqs[2][MAX_SLIDERS];
    int nb[2] = {0}, nr[2] = {0}, nq[2] = {0};

    for (side = 0; side < 2; side++)
    {
        U64 bb = b->pieces[side][BISHOP];
        while (bb)
        {
            int sq = lsb_index(bb);
            bb &= bb - 1;
            bishop_sqs[side][nb[side]] = sq;
            bishop_atk[side][nb[side]] = sliding_attacks_bishop(sq, occupied);
            nb[side]++;
        }
        bb = b->pieces[side][ROOK];
        while (bb)
        {
            int sq = lsb_index(bb);
            bb &= bb - 1;
            rook_sqs[side][nr[side]] = sq;
            rook_atk[side][nr[side]] = sliding_attacks_rook(sq, occupied);
            nr[side]++;
        }
        bb = b->pieces[side][QUEEN];
        while (bb)
        {
            int sq = lsb_index(bb);
            bb &= bb - 1;
            queen_sqs[side][nq[side]] = sq;
            queen_batk[side][nq[side]] = sliding_attacks_bishop(sq, occupied);
            queen_ratk[side][nq[side]] = sliding_attacks_rook(sq, occupied);
            nq[side]++;
        }
    }

    /* Precompute pawn attacks, knight attacks, and piece counts for both sides */
    U64 pawn_attacks[2] = {0, 0};
    U64 knight_attacks_bb[2] = {0, 0};
    int piece_counts[2][7] = {{0}};

    for (int s = 0; s < 2; s++)
    {
        U64 pawns = b->pieces[s][PAWN];
        while (pawns)
        {
            int sq = lsb_index(pawns);
            pawns &= pawns - 1;
            if (s == WHITE)
                pawn_attacks[s] |= shift_north(shift_east(1ULL << sq)) | shift_north(shift_west(1ULL << sq));
            else
                pawn_attacks[s] |= shift_south(shift_east(1ULL << sq)) | shift_south(shift_west(1ULL << sq));
        }
        U64 knights = b->pieces[s][KNIGHT];
        while (knights)
        {
            int sq = lsb_index(knights);
            knights &= knights - 1;
            knight_attacks_bb[s] |= knight_attacks[sq];
        }
        for (int pt2 = PAWN; pt2 <= QUEEN; pt2++)
            piece_counts[s][pt2] = count_bits(b->pieces[s][pt2]);
    }

    /* 鍚堝苟姣忔柟鎵€鏈夋瀛愮殑鏀诲嚮浣嶆澘锛岀敤浜庢浛浠ｆ槀璐电殑 is_square_attacked 璋冪敤 */
    U64 all_attacks[2] = {0, 0};
    for (side = 0; side < 2; side++)
    {
        all_attacks[side] |= pawn_attacks[side];
        all_attacks[side] |= knight_attacks_bb[side];
        all_attacks[side] |= king_attacks[b->king_sq[side]];
        for (int j = 0; j < nb[side]; j++)
            all_attacks[side] |= bishop_atk[side][j];
        for (int j = 0; j < nr[side]; j++)
            all_attacks[side] |= rook_atk[side][j];
        for (int j = 0; j < nq[side]; j++)
            all_attacks[side] |= queen_batk[side][j] | queen_ratk[side][j];
    }

    /* Use incremental PST+material score as base.
     * b->mg_score/b->eg_score are maintained incrementally in make_move/unmake_move
     * using the compile-time PST+material tables. The runtime params tables
     * (g_runtime_params.mg_pst/eg_pst/piece_values) are initialized as copies of
     * these same compile-time defaults, so the incremental score is valid whether
     * or not runtime params are loaded. This avoids an O(n) full recomputation on
     * every evaluate() call. */
    score = (b->mg_score * phase_weight + b->eg_score * (256 - phase_weight)) / 256;
#ifdef DEBUG_INCREMENTAL
    /* Verify incremental score matches full recomputation. Uses the same
     * PST/piece_values tables (runtime if loaded, compile-time otherwise)
     * that make_move/unmake_move use. */
    {
        int full_mg = 0, full_eg = 0;
        int s2, pt2;
        for (s2 = 0; s2 < 2; s2++)
        {
            int sign2 = (s2 == WHITE) ? 1 : -1;
            for (pt2 = PAWN; pt2 <= KING; pt2++)
            {
                U64 bb2 = b->pieces[s2][pt2];
                while (bb2)
                {
                    int sq2 = lsb_index(bb2);
                    bb2 &= bb2 - 1;
                    int psq2 = (s2 == WHITE) ? sq2 : (sq2 ^ 56);
                    full_mg += sign2 * (get_piece_value(pt2) + get_mg_pst(pt2, psq2));
                    full_eg += sign2 * (get_piece_value(pt2) + get_eg_pst(pt2, psq2));
                }
            }
        }
        if (full_mg != b->mg_score || full_eg != b->eg_score)
        {
            fprintf(stderr, "INCREMENTAL MISMATCH: mg incremental=%d full=%d | eg incremental=%d full=%d phase=%d\n",
                    b->mg_score, full_mg, b->eg_score, full_eg, phase);
        }
    }
#endif

    /* Lazy Eval: 褰撳熀纭€鍒嗘暟锛圥ST+material锛夌粷瀵瑰€艰秴杩囬槇鍊兼椂,
     * 璺宠繃鏈哄姩鎬с€佺帇瀹夊叏銆佸▉鑳佺瓑鏄傝吹璁＄畻锛屼粎鍔?tempo 鍚庤繑鍥炪€?
     * 闃堝€?2000cp 绾︾瓑浜庝袱涓溅鐨勪环鍊硷紝鍓╀綑璇勪及椤规€诲拰涓嶅お鍙兘鏀瑰彉缁撴灉銆?*/
    if (score > LAZY_EVAL_THRESHOLD || score < -LAZY_EVAL_THRESHOLD)
    {
        int tempo_lazy = (tempo_mg * phase_weight + tempo_eg * (256 - phase_weight)) / 256;
        if (b->side_to_move == WHITE)
            score += tempo_lazy;
        else
            score -= tempo_lazy;
        b->eval_score = score;
        return score;
    }


    


    for (side = 0; side < 2; side++)
    {
        int sign = (side == WHITE) ? 1 : -1;
        if (piece_counts[side][BISHOP] >= 2)
        {
            score += sign * bishop_pair_bonus;
        }
    }

    for (side = 0; side < 2; side++)
    {
        int sign = (side == WHITE) ? 1 : -1;
        U64 rooks = b->pieces[side][ROOK];
        U64 own_pawns = b->pieces[side][PAWN];
        U64 enemy_pawns = b->pieces[1 - side][PAWN];

        U64 temp_rooks = rooks;
        while (temp_rooks)
        {
            int sq = lsb_index(temp_rooks);
            temp_rooks &= temp_rooks - 1;
            int f = file_of(sq);
            U64 file_mask = 0x0101010101010101ULL << f;
            int own_pawns_on_file = count_bits(own_pawns & file_mask);
            int enemy_pawns_on_file = count_bits(enemy_pawns & file_mask);
            if (own_pawns_on_file == 0 && enemy_pawns_on_file == 0)
            {
                score += sign * open_file_bonus;
            }
            else if (own_pawns_on_file == 0 && enemy_pawns_on_file > 0)
            {
                score += sign * semi_open_file_bonus;
            }
        }

        if (rooks)
        {
            int f;
            for (f = 0; f < 8; f++)
            {
                U64 file_mask = 0x0101010101010101ULL << f;
                if (!(own_pawns & file_mask) && !(enemy_pawns & file_mask))
                {
                    if (!(rooks & file_mask))
                    {
                        score += sign * rook_potential_open_file;
                    }
                }
                else if (!(own_pawns & file_mask) && (enemy_pawns & file_mask))
                {
                    if (!(rooks & file_mask))
                    {
                        score += sign * rook_potential_semi_open;
                    }
                }
            }
        }
    }

    for (side = 0; side < 2; side++)
    {
        int sign = (side == WHITE) ? 1 : -1;
        U64 bishops = b->pieces[side][BISHOP];
        U64 center_pawns = b->pieces[side][PAWN] & 0x0000001818000000ULL;
        while (bishops)
        {
            int sq = lsb_index(bishops);
            bishops &= bishops - 1;
            int sq_color = ((sq / 8) + (sq % 8)) % 2;
            int pawns_on_color = 0;
            U64 cp = center_pawns;
            while (cp)
            {
                int psq = lsb_index(cp);
                cp &= cp - 1;
                int psq_color = ((psq / 8) + (psq % 8)) % 2;
                if (psq_color == sq_color)
                    pawns_on_color++;
            }
            if (pawns_on_color == 0)
                score += sign * bishop_mobility_bonus;
            else if (pawns_on_color >= 2)
                score += sign * bishop_bad_penalty;
        }
    }

    for (side = 0; side < 2; side++)
    {
        int sign = (side == WHITE) ? 1 : -1;
        int opp_r7 = 1 - side;
        U64 rooks = b->pieces[side][ROOK];
        U64 target_rank = (side == WHITE) ? 0x00FF000000000000ULL : 0x000000000000FF00ULL;
        int rooks_on_7th = count_bits(rooks & target_rank);
        if (rooks_on_7th > 0)
        {
            int mg_bonus = rook_on_7th_mg_bonus;
            int eg_bonus = rook_on_7th_eg_bonus;
            int bonus = (mg_bonus * phase + eg_bonus * (24 - phase)) / 24;
            score += sign * bonus * rooks_on_7th;
            if (rooks_on_7th >= 2)
                score += sign * rook_on_7th_double_bonus;
            int opp_king_rank = rank_of(b->king_sq[opp_r7]);
            int king_on_8th = (side == WHITE && opp_king_rank == 7) || (side == BLACK && opp_king_rank == 0);
            if (king_on_8th)
            {
                score += sign * rook_on_7th_king_rank8_bonus;
                if (rooks_on_7th >= 2)
                    score += sign * rook_on_7th_double_king_rank8_bonus;
            }
        }
    }

    if (g_runtime_params.eval_king_safety_enabled)
    {
        for (side = 0; side < 2; side++)
        {
            int opp = 1 - side;
            int king_square = b->king_sq[side];
            int sign = (side == WHITE) ? 1 : -1;

            U64 king_zone = king_attacks[king_square] | (1ULL << king_square);
            if (side == WHITE)
            {
                U64 front = shift_north(king_zone) | shift_north(shift_north(king_zone));
                king_zone |= front;
            }
            else
            {
                U64 front = shift_south(king_zone) | shift_south(shift_south(king_zone));
                king_zone |= front;
            }

            int attack_units = 0;
            int au_pieces = 0;
            int au_shield = 0;
            int au_files = 0;
            int au_attackers = 0;

            U64 opp_knights = b->pieces[opp][KNIGHT];
            while (opp_knights)
            {
                int sq = lsb_index(opp_knights);
                opp_knights &= opp_knights - 1;
                U64 attacks = knight_attacks[sq] & king_zone;
                if (attacks)
                {
                    int add = knight_attack_base + count_bits(attacks) * knight_attack_per_sq;
                    attack_units += add;
                    au_pieces += add;
                }
            }

            {
                int bi;
                for (bi = 0; bi < nb[opp]; bi++)
                {
                    U64 attacks = bishop_atk[opp][bi] & king_zone;
                    if (attacks)
                    {
                        int add = bishop_attack_base + count_bits(attacks) * bishop_attack_per_sq;
                        attack_units += add;
                        au_pieces += add;
                    }
                }
            }

            {
                int ri;
                for (ri = 0; ri < nr[opp]; ri++)
                {
                    U64 attacks = rook_atk[opp][ri] & king_zone;
                    if (attacks)
                    {
                        int add = rook_attack_base + count_bits(attacks) * rook_attack_per_sq;
                        attack_units += add;
                        au_pieces += add;
                    }
                }
            }

            {
                int qi;
                for (qi = 0; qi < nq[opp]; qi++)
                {
                    U64 attacks = (queen_batk[opp][qi] | queen_ratk[opp][qi]) & king_zone;
                    if (attacks)
                    {
                        int add = queen_attack_base + count_bits(attacks) * queen_attack_per_sq;
                        attack_units += add;
                        au_pieces += add;
                    }
                }
            }

            int kf = king_square % 8;
            int kr = king_square / 8;
            U64 own_pawns = b->pieces[side][PAWN];
            for (int f = kf - 1; f <= kf + 1; f++)
            {
                if (f < 0 || f > 7)
                    continue;
                U64 file_mask = file_masks[f];
                if (side == WHITE)
                {
                    if (kr <= 4 && kr + 2 <= 7)
                    {
                        U64 shield1 = file_mask & own_pawns & rank_masks[kr + 1];
                        U64 shield2 = file_mask & own_pawns & rank_masks[kr + 2];
                        if (shield1)
                            attack_units += 0;
                        else if (shield2)
                        {
                            attack_units += pawn_shield_rank2_penalty;
                            au_shield += pawn_shield_rank2_penalty;
                        }
                        else
                        {
                            attack_units += pawn_shield_no_pawn_penalty;
                            au_shield += pawn_shield_no_pawn_penalty;
                        }
                    }
                }
                else
                {
                    if (kr >= 3 && kr - 2 >= 0)
                    {
                        U64 shield1 = file_mask & own_pawns & rank_masks[kr - 1];
                        U64 shield2 = file_mask & own_pawns & rank_masks[kr - 2];
                        if (shield1)
                            attack_units += 0;
                        else if (shield2)
                        {
                            attack_units += pawn_shield_rank2_penalty;
                            au_shield += pawn_shield_rank2_penalty;
                        }
                        else
                        {
                            attack_units += pawn_shield_no_pawn_penalty;
                            au_shield += pawn_shield_no_pawn_penalty;
                        }
                    }
                }
            }

            {
                int open_file_count = 0;
                int semi_open_file_count = 0;
                for (int f = kf - 1; f <= kf + 1; f++)
                {
                    if (f < 0 || f > 7)
                        continue;
                    U64 fmask = file_masks[f];
                    int own_on_file = count_bits(own_pawns & fmask);
                    int enemy_on_file = count_bits(b->pieces[opp][PAWN] & fmask);
                    if (own_on_file == 0 && enemy_on_file == 0)
                        open_file_count++;
                    else if (own_on_file == 0 && enemy_on_file > 0)
                        semi_open_file_count++;
                }
                int add_files = open_file_count * open_file_king_zone_penalty + semi_open_file_count * semi_open_file_king_zone_penalty;
                attack_units += add_files;
                au_files += add_files;
            }

            int attacker_count = 0;
            if (b->pieces[opp][KNIGHT] && (knight_attacks[king_square] & b->pieces[opp][KNIGHT]))
                attacker_count++;
            {
                int bi;
                for (bi = 0; bi < nb[opp]; bi++)
                {
                    if (bishop_atk[opp][bi] & king_zone)
                    {
                        attacker_count++;
                        break;
                    }
                }
            }
            {
                int ri;
                for (ri = 0; ri < nr[opp]; ri++)
                {
                    if (rook_atk[opp][ri] & king_zone)
                    {
                        attacker_count++;
                        break;
                    }
                }
            }
            {
                int qi;
                for (qi = 0; qi < nq[opp]; qi++)
                {
                    if ((queen_batk[opp][qi] | queen_ratk[opp][qi]) & king_zone)
                    {
                        attacker_count++;
                        break;
                    }
                }
            }
            if (attacker_count >= 2)
            {
                int add_attackers = (attacker_count - 1) * attacker_count_bonus;
                attack_units += add_attackers;
                au_attackers += add_attackers;
            }

            int danger_index = (attack_units < 128) ? attack_units : 127;
            int danger = eval_king_danger_table[danger_index];

            if (attacker_count == 0)
                danger = danger / 3;
            else if (attacker_count == 1)
                danger = danger * 2 / 3;

            if (nq[opp] == 0)
                danger = danger * 30 / 100;

            int danger_before_scale = danger;
            danger = danger * (king_danger_eg_scale_base + phase_weight * king_danger_eg_scale_phase / 128) / 100;

            if (danger > king_danger_cap)
                danger = king_danger_cap;

            {
                static int ksafety_diag_enabled = -1;
                if (ksafety_diag_enabled == -1)
                {
                    const char *env = getenv("HELLCOPTER_KSAFETY_DIAG");
                    ksafety_diag_enabled = (env && strcmp(env, "1") == 0) ? 1 : 0;
                }
                if (ksafety_diag_enabled)
                {
                    fprintf(stderr, "[KSAFETY] side=%d king_sq=%d phase=%d attack_units=%d danger_raw=%d danger_scaled=%d cap=%d pieces=%d shield=%d files=%d attackers=%d\n",
                            side, king_square, phase_weight, attack_units, danger_before_scale, danger, king_danger_cap,
                            au_pieces, au_shield, au_files, au_attackers);
                }
            }

            score -= sign * danger;
        }
    }

    for (side = 0; side < 2; side++)
    {
        int sign = (side == WHITE) ? 1 : -1;
        U64 center = (1ULL << 27) | (1ULL << 28) | (1ULL << 35) | (1ULL << 36);
        U64 ext = 0;
        int sq;
        for (sq = 18; sq <= 21; sq++)
            ext |= 1ULL << sq;
        for (sq = 26; sq <= 29; sq++)
            ext |= 1ULL << sq;
        for (sq = 34; sq <= 37; sq++)
            ext |= 1ULL << sq;
        for (sq = 42; sq <= 45; sq++)
            ext |= 1ULL << sq;
        U64 occ = b->pieces[side][PAWN] | b->pieces[side][KNIGHT] | b->pieces[side][BISHOP] |
                  b->pieces[side][ROOK] | b->pieces[side][QUEEN] | b->pieces[side][KING];
        score += sign * (center_control_piece_bonus * count_bits(occ & center));
        score += sign * (center_control_extended_bonus * count_bits(occ & ext & ~center));

        U64 pawns = b->pieces[side][PAWN];
        score += sign * (center_control_pawn_bonus * count_bits(pawns & center));
        score += sign * (center_control_pawn_extended_bonus * count_bits(pawns & (ext & ~center)));
    }

    for (side = 0; side < 2; side++)
    {
        int sign = (side == WHITE) ? 1 : -1;
        int opp = 1 - side;
        int king_sq = -1;
        U64 kbb = b->pieces[side][KING];
        if (kbb)
            king_sq = lsb_index(kbb);
        if (king_sq < 0)
            continue;
        int kr = rank_of(king_sq);

        if ((side == WHITE && kr <= 1) || (side == BLACK && kr >= 6))
        {
            int kf = file_of(king_sq);
            int blocked_files = 0;
            int df;
            for (df = -1; df <= 1; df++)
            {
                int af = kf + df;
                if (af < 0 || af > 7)
                    continue;
                int r;
                int found_pawn = 0;
                for (r = 0; r < 8; r++)
                {
                    int sq2 = r * 8 + af;
                    if (b->pieces[side][PAWN] & (1ULL << sq2))
                    {
                        found_pawn = 1;
                        if ((side == WHITE && r <= 2) || (side == BLACK && r >= 5))
                            blocked_files++;
                        break;
                    }
                }
            }
            if (blocked_files >= 2)
            {
                U64 back_rank = (side == WHITE) ? rank_masks[0] : rank_masks[7];
                U64 second_rank = (side == WHITE) ? rank_masks[1] : rank_masks[6];
                U64 rq_on_back = 0;
                {
                    int ri;
                    for (ri = 0; ri < nr[opp]; ri++)
                    {
                        int rsq = rook_sqs[opp][ri];
                        int rr = rank_of(rsq);
                        if ((side == WHITE && rr == 7) || (side == BLACK && rr == 0))
                        {
                            if (rook_atk[opp][ri] & (back_rank | second_rank))
                                rq_on_back |= (1ULL << rsq);
                        }
                    }
                }
                {
                    int qi;
                    for (qi = 0; qi < nq[opp]; qi++)
                    {
                        int rsq = queen_sqs[opp][qi];
                        int rr = rank_of(rsq);
                        if ((side == WHITE && rr == 7) || (side == BLACK && rr == 0))
                        {
                            if (queen_ratk[opp][qi] & (back_rank | second_rank))
                                rq_on_back |= (1ULL << rsq);
                        }
                    }
                }
                if (rq_on_back)
                {
                    score += sign * (back_rank_mate_penalty);
                    /* Extra penalty when all 3 files are blocked (no escape at all) */
                    if (blocked_files >= 3)
                        score += sign * (back_rank_triple_penalty);
                }
            }
        }
    }

    /* 閫氱敤寮€灞€鍙戝睍鍘熷垯锛氫笉渚濊禆鏍囧噯璧峰鏍硷紝浠呬繚鐣?杞诲瓙鏈彂灞曟椂鍚?杞﹁繃鏃╁墠鍘?銆?
     * 鍑哄瓙銆佷腑蹇冩帶鍒躲€佺帇瀹夊叏鐢辨満鍔ㄦ€ц〃/center_control/king_danger 绛夐€氱敤鐗瑰緛
     * 涓庢悳绱㈠叡鍚屽緱鍑猴紝閬垮厤"鏍囧噯绛旀琛ヤ竵"瀵归潪鏍囧噯灞€闈㈢殑澶辩湡銆?
     * "宸插彂灞?瀹氫箟涓鸿交瀛愮寮€宸辨柟搴曠嚎锛堥€氱敤鍑犱綍锛岄潪 b1/g1/c1/f1 绛夋爣鍑嗘牸锛夈€?*/
    if (b->fullmove_number <= 15)
    {
        for (side = 0; side < 2; side++)
        {
            int sign = (side == WHITE) ? 1 : -1;
            U64 back_rank = (side == WHITE) ? 0x00000000000000FFULL : 0xFF00000000000000ULL;
            U64 minor = b->pieces[side][KNIGHT] | b->pieces[side][BISHOP];
            int developed = count_bits(minor & ~back_rank);

            if (developed < 3)
            {
                U64 queens = b->pieces[side][QUEEN];
                U64 rooks = b->pieces[side][ROOK];
                U64 enemy_half = (side == WHITE) ? 0xFFFFFFFF00000000ULL : 0x00000000FFFFFFFFULL;
                if (queens & enemy_half)
                {
                    int penalty = opening_early_queen_advance_base - developed * opening_early_queen_advance_scale;
                    if (penalty < opening_early_queen_advance_min)
                        penalty = opening_early_queen_advance_min;
                    score += sign * (-penalty);
                }
                if (rooks & enemy_half)
                    score += sign * (opening_early_rook_advance_penalty);
            }
        }
    }

    {
        int w_minors = piece_counts[WHITE][KNIGHT] + piece_counts[WHITE][BISHOP];
        int b_minors = piece_counts[BLACK][KNIGHT] + piece_counts[BLACK][BISHOP];
        int w_pawns = piece_counts[WHITE][PAWN];
        int b_pawns = piece_counts[BLACK][PAWN];

        int minor_diff = w_minors - b_minors;
        int pawn_diff = w_pawns - b_pawns;

        int mg_weight = phase;
        int eg_weight = 24 - phase;

        /* 閲嶅瓙宸紓锛岀敤浜庤ˉ鍋胯交瀛愪笉骞宠　銆?
         * 1 涓澶栬溅鍙姷娑?1 涓交瀛愬姡鍔匡紝1 涓澶栧悗鍙姷娑?2 涓交瀛愬姡鍔裤€?
         * 杩欑鍚堟潗鏂欎环鍊兼瘮锛氳溅(5)鈮堣交瀛?3)*1.67锛屽悗(9)鈮堣交瀛?3)*3銆?*/
        int w_rooks_cnt = piece_counts[WHITE][ROOK];
        int b_rooks_cnt = piece_counts[BLACK][ROOK];
        int w_queens_cnt = piece_counts[WHITE][QUEEN];
        int b_queens_cnt = piece_counts[BLACK][QUEEN];

        if (minor_diff > 0 && pawn_diff < 0)
        {
            /* 鐧芥柟澶氳交瀛愬皯鍏碉細妫€鏌ラ粦鏂规槸鍚︽湁棰濆閲嶅瓙琛ュ伩 */
            int imbalance = minor_diff;
            int heavy_compensation = (b_rooks_cnt - w_rooks_cnt) + (b_queens_cnt - w_queens_cnt) * 2;
            if (heavy_compensation > 0)
                imbalance -= heavy_compensation;
            if (imbalance > 3)
                imbalance = 3;
            if (imbalance < 0)
                imbalance = 0;
            int mg_penalty = imbalance * (imbalance_mg_base + imbalance_mg_scale * imbalance);
            int eg_penalty = imbalance * imbalance_eg_scale;
            int penalty = (mg_penalty * mg_weight + eg_penalty * eg_weight) / 24;
            score += penalty;
        }
        else if (minor_diff < 0 && pawn_diff > 0)
        {
            /* 鐧芥柟灏戣交瀛愬鍏碉細妫€鏌ョ櫧鏂规槸鍚︽湁棰濆閲嶅瓙琛ュ伩 */
            int imbalance = -minor_diff;
            int heavy_compensation = (w_rooks_cnt - b_rooks_cnt) + (w_queens_cnt - b_queens_cnt) * 2;
            if (heavy_compensation > 0)
                imbalance -= heavy_compensation;
            if (imbalance > 3)
                imbalance = 3;
            if (imbalance < 0)
                imbalance = 0;
            int mg_penalty = imbalance * (imbalance_mg_base + imbalance_mg_scale * imbalance);
            int eg_penalty = imbalance * imbalance_eg_scale;
            int penalty = (mg_penalty * mg_weight + eg_penalty * eg_weight) / 24;
            score -= penalty;
        }

        /* no_minor_vs_two_minor: 鑰冭檻閲嶅瓙琛ュ伩銆?
         * 濡傛灉鏃犺交瀛愮殑涓€鏂规湁棰濆閲嶅瓙锛堣溅/鍚庯級锛屾儵缃氬噺鍗婃垨鏇村銆?
         * 2杞?10) > 2杞诲瓙(6)锛屼笉搴旇涓ラ噸鎯╃綒銆?*/
        if (w_minors == 0 && b_minors >= 2)
        {
            int heavy_compensation = (w_rooks_cnt - b_rooks_cnt) + (w_queens_cnt - b_queens_cnt) * 2;
            if (heavy_compensation > 0)
                score -= no_minor_vs_two_minor_penalty / (1 + heavy_compensation);
            else
                score -= no_minor_vs_two_minor_penalty;
        }
        else if (b_minors == 0 && w_minors >= 2)
        {
            int heavy_compensation = (b_rooks_cnt - w_rooks_cnt) + (b_queens_cnt - w_queens_cnt) * 2;
            if (heavy_compensation > 0)
                score += no_minor_vs_two_minor_penalty / (1 + heavy_compensation);
            else
                score += no_minor_vs_two_minor_penalty;
        }
    }

    if (g_runtime_params.eval_endgame_enabled && b->halfmove_clock >= 30)
    {
        int abs_score = (score > 0) ? score : -score;
        if (abs_score > 150)
        {
            int urgency = b->halfmove_clock - 30;
            int penalty = (urgency * urgency) * (abs_score / fifty_move_urgency_divisor);
            if (penalty > abs_score)
                penalty = abs_score;
            if (score > 0)
                score -= penalty;
            else
                score += penalty;
        }
        }

    {
        int white_non_pawn_material = 0;
        int black_non_pawn_material = 0;
        int mop_up_active = 0;
        int mop_up_strong_side = -1;
        for (pt = KNIGHT; pt <= QUEEN; pt++)
        {
            white_non_pawn_material += piece_counts[WHITE][pt] * get_piece_value(pt);
            black_non_pawn_material += piece_counts[BLACK][pt] * get_piece_value(pt);
        }
        int material_balance = white_non_pawn_material - black_non_pawn_material;

        if (material_balance > mopup_material_threshold)
        {
            mop_up_active = 1;
            mop_up_strong_side = WHITE;
        }
        else if (material_balance < -mopup_material_threshold)
        {
            mop_up_active = 1;
            mop_up_strong_side = BLACK;
        }

        if (g_runtime_params.eval_endgame_enabled)
        {
        /* King activity: continuous scaling based on phase (not hard threshold).
         * In middlegame (phase=24): weight=5 (king should stay safe)
         * In endgame (phase=0): weight=25 (king must be active)
         * This replaces the old phase<=6 hard cutoff. */
        {
            for (side = 0; side < 2; side++)
            {
                int sign = (side == WHITE) ? 1 : -1;
                U64 king_bb = b->pieces[side][KING];
                if (king_bb)
                {
                    int king_sq = lsb_index(king_bb);
                    int kf = file_of(king_sq);
                    int kr = rank_of(king_sq);
                    int center_dist = (kf > 3 ? kf - 3 : 3 - kf) + (kr > 3 ? kr - 3 : 3 - kr);
                    int activity_weight;
                    if (mop_up_active && mop_up_strong_side == side)
                        activity_weight = mopup_winning_king_activity_weight;
                    else if (mop_up_active && mop_up_strong_side == (1 - side))
                        activity_weight = mopup_losing_king_activity_weight;
                    else
                        activity_weight = 5 + (24 - phase) * 20 / 24;  /* Continuous 5..25 */
                    int activity_bonus = (6 - center_dist) * activity_weight;
                    score += sign * activity_bonus;

                    /* King proximity to enemy passed pawns: in endgame, king must
                     * intercept enemy passers. Bonus for being close to advanced enemy pawns. */
                    if (phase < 16)
                    {
                        U64 enemy_pawns = b->pieces[1 - side][PAWN];
                        U64 temp_ep = enemy_pawns;
                        while (temp_ep)
                        {
                            int psq = lsb_index(temp_ep);
                            temp_ep &= temp_ep - 1;
                            int pf = file_of(psq), pr = rank_of(psq);
                            int dist = (abs(kr - pr) > abs(kf - pf)) ? abs(kr - pr) : abs(kf - pf);
                            int advance_rank = (side == WHITE) ? pr : (7 - pr);
                            if (advance_rank >= 4)
                            {
                                int urgency = (8 - dist) * advance_rank * (16 - phase) / 8;
                                score += sign * urgency;
                            }
                        }
                    }
                }
            }
        }

        if (material_balance > simplify_threshold)
        {
            int advantage = material_balance - simplify_threshold;
            int bonus = simplify_bonus * advantage / 100;
            if (bonus > simplify_bonus * 3)
                bonus = simplify_bonus * 3;
            score += bonus;
        }
        else if (material_balance < -simplify_threshold)
        {
            int advantage = -material_balance - simplify_threshold;
            int bonus = simplify_bonus * advantage / 100;
            if (bonus > simplify_bonus * 3)
                bonus = simplify_bonus * 3;
            score -= bonus;
        }

        /* Anti-simplification */
        {
            U64 all_pieces = b->pieces[WHITE][PAWN] | b->pieces[WHITE][KNIGHT] |
                             b->pieces[WHITE][BISHOP] | b->pieces[WHITE][ROOK] |
                             b->pieces[WHITE][QUEEN] | b->pieces[WHITE][KING] |
                             b->pieces[BLACK][PAWN] | b->pieces[BLACK][KNIGHT] |
                             b->pieces[BLACK][BISHOP] | b->pieces[BLACK][ROOK] |
                             b->pieces[BLACK][QUEEN] | b->pieces[BLACK][KING];
            int piece_count = count_bits(all_pieces);
            if (material_balance < -100)
            {
                int trailing_bonus = (piece_count - anti_simplify_piece_threshold) * anti_simplify_per_piece_scale;
                if (trailing_bonus > 0)
                    score += trailing_bonus;
            }
            else if (material_balance > 100)
            {
                int trailing_bonus = (piece_count - anti_simplify_piece_threshold) * anti_simplify_per_piece_scale;
                if (trailing_bonus > 0)
                    score -= trailing_bonus;
            }
        }

        if (phase < 16 && (material_balance > 500 || material_balance < -500))
        {
            int w_q = piece_counts[WHITE][QUEEN], b_q = piece_counts[BLACK][QUEEN];
            int w_r = piece_counts[WHITE][ROOK], b_r = piece_counts[BLACK][ROOK];
            int w_b = piece_counts[WHITE][BISHOP], b_b = piece_counts[BLACK][BISHOP];
            int w_n = piece_counts[WHITE][KNIGHT], b_n = piece_counts[BLACK][KNIGHT];
            int w_p = piece_counts[WHITE][PAWN], b_p = piece_counts[BLACK][PAWN];
            int tp = w_p + b_p;
            int is_specific_endgame = 0;
            if (tp == 0 && ((w_q == 1 && w_r == 0 && w_b + w_n == 0 && b_q == 0 && b_r == 0 && b_b + b_n == 0) ||
                            (b_q == 1 && b_r == 0 && b_b + b_n == 0 && w_q == 0 && w_r == 0 && w_b + w_n == 0) ||
                            (w_r == 1 && w_q == 0 && w_b + w_n == 0 && b_q == 0 && b_r == 0 && b_b + b_n == 0) ||
                            (b_r == 1 && b_q == 0 && b_b + b_n == 0 && w_q == 0 && w_r == 0 && w_b + w_n == 0) ||
                            (w_q == 1 && b_r == 1 && w_r == 0 && b_q == 0 && w_b + w_n == 0 && b_b + b_n == 0) ||
                            (b_q == 1 && w_r == 1 && b_r == 0 && w_q == 0 && b_b + b_n == 0 && w_b + w_n == 0) ||
                            (w_b == 1 && w_n == 1 && w_q == 0 && w_r == 0 && b_q == 0 && b_r == 0 && b_b == 0 && b_n == 0) ||
                            (b_b == 1 && b_n == 1 && b_q == 0 && b_r == 0 && w_q == 0 && w_r == 0 && w_b == 0 && w_n == 0)))
                is_specific_endgame = 1;

            if (!is_specific_endgame)
            {
                int strong_side = (material_balance > 0) ? WHITE : BLACK;
                int weak_king_sq = b->king_sq[1 - strong_side];
                int strong_king_sq = b->king_sq[strong_side];

                int weak_file = weak_king_sq % 8;
                int weak_rank = weak_king_sq / 8;
                int edge_dist_f = (weak_file < (7 - weak_file)) ? weak_file : (7 - weak_file);
                int edge_dist_r = (weak_rank < (7 - weak_rank)) ? weak_rank : (7 - weak_rank);
                int edge_dist = (edge_dist_f < edge_dist_r) ? edge_dist_f : edge_dist_r;
                if (edge_dist > 3)
                    edge_dist = 3;
                /* Stronger corner bonus to drive losing king to edge for mate */
                int corner_bonus = (3 - edge_dist) * mopup_generic_edge_scale;

                int strong_file = strong_king_sq % 8;
                int strong_rank = strong_king_sq / 8;
                int file_dist = (weak_file > strong_file) ? (weak_file - strong_file) : (strong_file - weak_file);
                int rank_dist = (weak_rank > strong_rank) ? (weak_rank - strong_rank) : (strong_rank - weak_rank);
                int king_dist = (file_dist > rank_dist) ? file_dist : rank_dist;
                /* Stronger proximity bonus to encourage winning king approach */
                int proximity_bonus = (7 - king_dist) * mopup_generic_proximity_scale;

                int mop_up = corner_bonus + proximity_bonus;
                score += (strong_side == WHITE) ? mop_up : -mop_up;
            }
        }
    }

        // Castling reward: encourage castling by giving bonus when the king has
        // moved to a castled position AND castling rights are no longer available
        // (indicating the king has actually castled, not just walked there).
        // This avoids double-rewarding with PST and prevents rewarding a king
        // that walked to g1/c1 without castling.
        if (phase > 12)
        {
            int white_king_sq = lsb_index(b->pieces[WHITE][KING]);
            int black_king_sq = lsb_index(b->pieces[BLACK][KING]);

            /* White: if king-side castling right is gone and king is on g1,
             * it likely castled kingside. Same for queenside. */
            if (white_king_sq == 6 && !(b->castling_rights & 1))
                score += castle_short_bonus;
            else if (white_king_sq == 2 && !(b->castling_rights & 2))
                score += castle_long_bonus;

            if (black_king_sq == 62 && !(b->castling_rights & 4))
                score -= castle_short_bonus;
            else if (black_king_sq == 58 && !(b->castling_rights & 8))
                score -= castle_long_bonus;
        }

        {
            int tempo = (tempo_mg * phase_weight + tempo_eg * (256 - phase_weight)) / 256;
            if (b->side_to_move == WHITE)
                score += tempo;
            else
                score -= tempo;
        }

        if (g_runtime_params.eval_endgame_enabled)
        {
            int w_pawns = piece_counts[WHITE][PAWN];
            int b_pawns = piece_counts[BLACK][PAWN];
            int w_knights = piece_counts[WHITE][KNIGHT];
            int b_knights = piece_counts[BLACK][KNIGHT];
            int w_bishops = piece_counts[WHITE][BISHOP];
            int b_bishops = piece_counts[BLACK][BISHOP];
            int w_rooks = piece_counts[WHITE][ROOK];
            int b_rooks = piece_counts[BLACK][ROOK];
            int w_queens = piece_counts[WHITE][QUEEN];
            int b_queens = piece_counts[BLACK][QUEEN];
            int total_pawns = w_pawns + b_pawns;

            /* ============================================================
             * Mop-up evaluation for winning endgames
             * ============================================================ */


            int is_kqk_white = (w_queens == 1 && b_queens == 0 && w_rooks == 0 && b_rooks == 0 &&
                                w_bishops + w_knights == 0 && b_bishops + b_knights == 0 && total_pawns == 0);
            int is_kqk_black = (b_queens == 1 && w_queens == 0 && w_rooks == 0 && b_rooks == 0 &&
                                w_bishops + w_knights == 0 && b_bishops + b_knights == 0 && total_pawns == 0);
            int is_krk_white = (w_rooks == 1 && b_rooks == 0 && w_queens == 0 && b_queens == 0 &&
                                w_bishops + w_knights == 0 && b_bishops + b_knights == 0 && total_pawns == 0);
            int is_krk_black = (b_rooks == 1 && w_rooks == 0 && w_queens == 0 && b_queens == 0 &&
                                w_bishops + w_knights == 0 && b_bishops + b_knights == 0 && total_pawns == 0);
            /* KQKR: queen vs rook (winning side must avoid stalemate, push enemy king to edge) */
            int is_kqkr_white = (w_queens == 1 && b_rooks == 1 && w_rooks == 0 && b_queens == 0 &&
                                 w_bishops + w_knights == 0 && b_bishops + b_knights == 0 && total_pawns == 0);
            int is_kqkr_black = (b_queens == 1 && w_rooks == 1 && b_rooks == 0 && w_queens == 0 &&
                                 w_bishops + w_knights == 0 && b_bishops + b_knights == 0 && total_pawns == 0);
            /* KBNK: bishop+knight vs bare king (must drive to corner matching bishop color) */
            int is_kbnk_white = (w_bishops == 1 && w_knights == 1 && b_bishops == 0 && b_knights == 0 &&
                                 w_queens == 0 && b_queens == 0 && w_rooks == 0 && b_rooks == 0 && total_pawns == 0);
            int is_kbnk_black = (b_bishops == 1 && b_knights == 1 && w_bishops == 0 && w_knights == 0 &&
                                 w_queens == 0 && b_queens == 0 && w_rooks == 0 && b_rooks == 0 && total_pawns == 0);

            if (is_kqk_white || is_krk_white)
            {
                /* These endgames are always forced wins. Use a high base score
                 * with steep progress gradient to guide search toward mate. */
                int b_king = b->king_sq[BLACK];
                int w_king = b->king_sq[WHITE];
                int b_kf = file_of(b_king), b_kr = rank_of(b_king);
                int w_kf = file_of(w_king), w_kr = rank_of(w_king);
                int edge_dist_f = (b_kf < (7 - b_kf)) ? b_kf : (7 - b_kf);
                int edge_dist_r = (b_kr < (7 - b_kr)) ? b_kr : (7 - b_kr);
                int edge_dist = (edge_dist_f < edge_dist_r) ? edge_dist_f : edge_dist_r;
                int file_dist = (w_kf > b_kf) ? (w_kf - b_kf) : (b_kf - w_kf);
                int rank_dist = (w_kr > b_kr) ? (w_kr - b_kr) : (b_kr - w_kr);
                int chebyshev = (file_dist > rank_dist) ? file_dist : rank_dist;

                /* Base win score: ~12000 cp = KNOW_WIN */
                int base_win = MATE_SCORE / 8;
                /* Progress: 0-3000 bonus based on confinement */
                int progress = (3 - edge_dist) * 600 + (7 - chebyshev) * 150;
                /* Rook cutoff bonus for KRK */
                int rook_extra = 0;
                if (is_krk_white)
                {
                    int rook_sq = lsb_index(b->pieces[WHITE][ROOK]);
                    int r_f = file_of(rook_sq), r_r = rank_of(rook_sq);
                    if (r_f == b_kf)
                        rook_extra = 400;
                    else if (r_r == b_kr)
                        rook_extra = 250;
                    if (rook_atk[WHITE][0] & (1ULL << b_king))
                        rook_extra += 300;
                }
                /* Near mate bonus: edge + close king, signals mate within few moves */
                int near_mate = 0;
                if (edge_dist == 0 && chebyshev <= 2)
                    near_mate = (MATE_SCORE / 4) - progress;

                score += base_win + progress + rook_extra + near_mate;
            }
            else if (is_kqkr_white)
            {
                /* KQKR: queen vs rook 鈥?winning side pushes enemy king to edge,
                 * keeps our king close, and tries to fork or trap the rook */
                int w_king = b->king_sq[WHITE];
                int b_king = b->king_sq[BLACK];
                int w_kf = file_of(w_king), w_kr = rank_of(w_king);
                int b_kf = file_of(b_king), b_kr = rank_of(b_king);
                int edge_dist_f = (b_kf < (7 - b_kf)) ? b_kf : (7 - b_kf);
                int edge_dist_r = (b_kr < (7 - b_kr)) ? b_kr : (7 - b_kr);
                int edge_dist = (edge_dist_f < edge_dist_r) ? edge_dist_f : edge_dist_r;
                int file_dist = (w_kf > b_kf) ? (w_kf - b_kf) : (b_kf - w_kf);
                int rank_dist = (w_kr > b_kr) ? (w_kr - b_kr) : (b_kr - w_kr);
                int chebyshev = (file_dist > rank_dist) ? file_dist : rank_dist;

                int corner_bonus = (3 - edge_dist) * kqkr_corner_scale;
                int proximity_bonus = (7 - chebyshev) * kqkr_proximity_scale;
                /* Queen close to enemy king increases chance of forks */
                int queen_sq = lsb_index(b->pieces[WHITE][QUEEN]);
                int q_dist_f = (file_of(queen_sq) > b_kf) ? (file_of(queen_sq) - b_kf) : (b_kf - file_of(queen_sq));
                int q_dist_r = (rank_of(queen_sq) > b_kr) ? (rank_of(queen_sq) - b_kr) : (b_kr - rank_of(queen_sq));
                int q_chebyshev = (q_dist_f > q_dist_r) ? q_dist_f : q_dist_r;
                int queen_prox_bonus = (7 - q_chebyshev) * kqkr_queen_proximity_scale;
                /* Avoid stalemate: if enemy king is on edge, keep some distance */
                int stalemate_avoid = 0;
                if (edge_dist == 0 && chebyshev == 1)
                    stalemate_avoid = kqkr_stalemate_avoid_penalty;
                /* Big bonus when enemy king is actually in corner (mate is close) */
                int corner_mate_bonus = 0;
                if (edge_dist == 0)
                    corner_mate_bonus = kqkr_corner_mate_bonus;

                score += corner_bonus + proximity_bonus + queen_prox_bonus + stalemate_avoid + corner_mate_bonus;
            }
            else if (is_kbnk_white)
            {
                /* KBNK: bishop+knight vs bare king
                 * Winning corner must match bishop color.
                 * Square color = (file + rank) % 2. 0 = dark, 1 = light.
                 * Correct corners:
                 *   dark bishop -> a1 (0+0=0) or h8 (7+7=14 even -> 0)
                 *   light bishop -> a8 (0+7=7 odd -> 1) or h1 (7+0=7 odd -> 1)
                 */
                int w_king = b->king_sq[WHITE];
                int b_king = b->king_sq[BLACK];
                int w_kf = file_of(w_king), w_kr = rank_of(w_king);
                int b_kf = file_of(b_king), b_kr = rank_of(b_king);

                int bishop_sq = lsb_index(b->pieces[WHITE][BISHOP]);
                int bishop_color = ((bishop_sq >> 3) ^ (bishop_sq & 7)) & 1;

                /* Target corners based on bishop color */
                int target_corners[2][2] = {
                    {0, 0}, /* dark: a1 */
                    {7, 7}, /* dark: h8 */
                };
                int alt_target_corners[2][2] = {
                    {0, 7}, /* light: a8 */
                    {7, 0}, /* light: h1 */
                };

                int *tc1, *tc2;
                if (bishop_color == 0)
                {
                    tc1 = target_corners[0];
                    tc2 = target_corners[1];
                }
                else
                {
                    tc1 = alt_target_corners[0];
                    tc2 = alt_target_corners[1];
                }

                int dist1 = (b_kf > tc1[0] ? b_kf - tc1[0] : tc1[0] - b_kf) + (b_kr > tc1[1] ? b_kr - tc1[1] : tc1[1] - b_kr);
                int dist2 = (b_kf > tc2[0] ? b_kf - tc2[0] : tc2[0] - b_kf) + (b_kr > tc2[1] ? b_kr - tc2[1] : tc2[1] - b_kr);
                int corner_dist = (dist1 < dist2) ? dist1 : dist2;

                /* Reward pushing enemy king toward correct corner */
                int corner_bonus = (6 - corner_dist) * kbnk_corner_scale;
                /* Keep our king close to enemy king */
                int file_dist = (w_kf > b_kf) ? (w_kf - b_kf) : (b_kf - w_kf);
                int rank_dist = (w_kr > b_kr) ? (w_kr - b_kr) : (b_kr - w_kr);
                int chebyshev = (file_dist > rank_dist) ? file_dist : rank_dist;
                int proximity_bonus = (7 - chebyshev) * kbnk_proximity_scale;
                /* Big bonus when enemy king is actually in correct corner */
                int in_correct_corner = 0;
                if (corner_dist == 0)
                    in_correct_corner = kbnk_correct_corner_bonus;

                score += corner_bonus + proximity_bonus + in_correct_corner;
            }
            else if (is_kqk_black || is_krk_black)
            {
                int w_king = b->king_sq[WHITE];
                int b_king = b->king_sq[BLACK];
                int w_kf = file_of(w_king), w_kr = rank_of(w_king);
                int b_kf = file_of(b_king), b_kr = rank_of(b_king);
                int edge_dist_f = (w_kf < (7 - w_kf)) ? w_kf : (7 - w_kf);
                int edge_dist_r = (w_kr < (7 - w_kr)) ? w_kr : (7 - w_kr);
                int edge_dist = (edge_dist_f < edge_dist_r) ? edge_dist_f : edge_dist_r;
                int file_dist = (w_kf > b_kf) ? (w_kf - b_kf) : (b_kf - w_kf);
                int rank_dist = (w_kr > b_kr) ? (w_kr - b_kr) : (b_kr - w_kr);
                int chebyshev = (file_dist > rank_dist) ? file_dist : rank_dist;
                int manhattan = file_dist + rank_dist;

                int corner_bonus = (3 - edge_dist) * mopup_edge_weight;
                int proximity_bonus = (7 - chebyshev) * mopup_proximity_weight;
                int opposition_bonus = 0;
                if (chebyshev == 2 && manhattan % 2 == 0)
                    opposition_bonus = mopup_opposition_weight;

                int rook_cutoff_bonus = 0;
                if (is_krk_black)
                {
                    int rook_sq = lsb_index(b->pieces[BLACK][ROOK]);
                    int r_f = file_of(rook_sq), r_r = rank_of(rook_sq);
                    if (r_f == w_kf || r_r == w_kr)
                        rook_cutoff_bonus = krk_rook_cutoff_bonus;
                    int r_dist_f = (r_f > w_kf) ? (r_f - w_kf) : (w_kf - r_f);
                    int r_dist_r = (r_r > w_kr) ? (r_r - w_kr) : (w_kr - r_r);
                    if (r_dist_f > 3 && r_dist_r > 3)
                        rook_cutoff_bonus += krk_rook_far_penalty;
                }

                score -= corner_bonus + proximity_bonus + opposition_bonus + rook_cutoff_bonus;
            }
            else if (is_kqkr_black)
            {
                int w_king = b->king_sq[WHITE];
                int b_king = b->king_sq[BLACK];
                int w_kf = file_of(w_king), w_kr = rank_of(w_king);
                int b_kf = file_of(b_king), b_kr = rank_of(b_king);
                int edge_dist_f = (w_kf < (7 - w_kf)) ? w_kf : (7 - w_kf);
                int edge_dist_r = (w_kr < (7 - w_kr)) ? w_kr : (7 - w_kr);
                int edge_dist = (edge_dist_f < edge_dist_r) ? edge_dist_f : edge_dist_r;
                int file_dist = (w_kf > b_kf) ? (w_kf - b_kf) : (b_kf - w_kf);
                int rank_dist = (w_kr > b_kr) ? (w_kr - b_kr) : (b_kr - w_kr);
                int chebyshev = (file_dist > rank_dist) ? file_dist : rank_dist;

                int corner_bonus = (3 - edge_dist) * kqkr_corner_scale;
                int proximity_bonus = (7 - chebyshev) * kqkr_proximity_scale;
                int queen_sq = lsb_index(b->pieces[BLACK][QUEEN]);
                int q_dist_f = (file_of(queen_sq) > w_kf) ? (file_of(queen_sq) - w_kf) : (w_kf - file_of(queen_sq));
                int q_dist_r = (rank_of(queen_sq) > w_kr) ? (rank_of(queen_sq) - w_kr) : (w_kr - rank_of(queen_sq));
                int q_chebyshev = (q_dist_f > q_dist_r) ? q_dist_f : q_dist_r;
                int queen_prox_bonus = (7 - q_chebyshev) * kqkr_queen_proximity_scale;
                int stalemate_avoid = 0;
                if (edge_dist == 0 && chebyshev == 1)
                    stalemate_avoid = kqkr_stalemate_avoid_penalty;
                int corner_mate_bonus = 0;
                if (edge_dist == 0)
                    corner_mate_bonus = kqkr_corner_mate_bonus;

                score -= corner_bonus + proximity_bonus + queen_prox_bonus + stalemate_avoid + corner_mate_bonus;
            }
            else if (is_kbnk_black)
            {
                int w_king = b->king_sq[WHITE];
                int b_king = b->king_sq[BLACK];
                int w_kf = file_of(w_king), w_kr = rank_of(w_king);
                int b_kf = file_of(b_king), b_kr = rank_of(b_king);

                int bishop_sq = lsb_index(b->pieces[BLACK][BISHOP]);
                int bishop_color = ((bishop_sq >> 3) ^ (bishop_sq & 7)) & 1;

                int target_corners[2][2] = {{0, 0}, {7, 7}};
                int alt_target_corners[2][2] = {{0, 7}, {7, 0}};

                int *tc1, *tc2;
                if (bishop_color == 0)
                {
                    tc1 = target_corners[0];
                    tc2 = target_corners[1];
                }
                else
                {
                    tc1 = alt_target_corners[0];
                    tc2 = alt_target_corners[1];
                }

                int dist1 = (w_kf > tc1[0] ? w_kf - tc1[0] : tc1[0] - w_kf) + (w_kr > tc1[1] ? w_kr - tc1[1] : tc1[1] - w_kr);
                int dist2 = (w_kf > tc2[0] ? w_kf - tc2[0] : tc2[0] - w_kf) + (w_kr > tc2[1] ? w_kr - tc2[1] : tc2[1] - w_kr);
                int corner_dist = (dist1 < dist2) ? dist1 : dist2;

                int corner_bonus = (6 - corner_dist) * kbnk_corner_scale;
                int file_dist = (w_kf > b_kf) ? (w_kf - b_kf) : (b_kf - w_kf);
                int rank_dist = (w_kr > b_kr) ? (w_kr - b_kr) : (b_kr - w_kr);
                int chebyshev = (file_dist > rank_dist) ? file_dist : rank_dist;
                int proximity_bonus = (7 - chebyshev) * kbnk_proximity_scale;
                int in_correct_corner = 0;
                if (corner_dist == 0)
                    in_correct_corner = kbnk_correct_corner_bonus;

                score -= corner_bonus + proximity_bonus + in_correct_corner;
            }
            /* Extended mop-up: winning side has Q or R with pawns vs bare king or king+pawns */
            else if (total_pawns > 0 && (w_queens + b_queens + w_rooks + b_rooks) > 0)
            {
                int w_material = w_queens * QUEEN_VALUE + w_rooks * ROOK_VALUE + w_bishops * BISHOP_VALUE + w_knights * KNIGHT_VALUE;
                int b_material = b_queens * QUEEN_VALUE + b_rooks * ROOK_VALUE + b_bishops * BISHOP_VALUE + b_knights * KNIGHT_VALUE;
                int mat_adv = w_material - b_material;

                /* Activate when one side has overwhelming advantage (Q or R vs no Q/R) */
                if (mat_adv > 400 && b_queens == 0 && b_rooks == 0)
                {
                    int w_king = b->king_sq[WHITE];
                    int b_king = b->king_sq[BLACK];
                    int b_kf = file_of(b_king), b_kr = rank_of(b_king);
                    int w_kf = file_of(w_king), w_kr = rank_of(w_king);
                    int edge_dist_f = (b_kf < (7 - b_kf)) ? b_kf : (7 - b_kf);
                    int edge_dist_r = (b_kr < (7 - b_kr)) ? b_kr : (7 - b_kr);
                    int edge_dist = (edge_dist_f < edge_dist_r) ? edge_dist_f : edge_dist_r;
                    int file_dist = (w_kf > b_kf) ? (w_kf - b_kf) : (b_kf - w_kf);
                    int rank_dist = (w_kr > b_kr) ? (w_kr - b_kr) : (b_kr - w_kr);
                    int chebyshev = (file_dist > rank_dist) ? file_dist : rank_dist;
                    int corner_bonus = (3 - edge_dist) * extended_mopup_edge_scale;
                    int proximity_bonus = (7 - chebyshev) * extended_mopup_proximity_scale;
                    score += corner_bonus + proximity_bonus;
                }
                else if (mat_adv < -400 && w_queens == 0 && w_rooks == 0)
                {
                    int w_king = b->king_sq[WHITE];
                    int b_king = b->king_sq[BLACK];
                    int w_kf = file_of(w_king), w_kr = rank_of(w_king);
                    int b_kf = file_of(b_king), b_kr = rank_of(b_king);
                    int edge_dist_f = (w_kf < (7 - w_kf)) ? w_kf : (7 - w_kf);
                    int edge_dist_r = (w_kr < (7 - w_kr)) ? w_kr : (7 - w_kr);
                    int edge_dist = (edge_dist_f < edge_dist_r) ? edge_dist_f : edge_dist_r;
                    int file_dist = (w_kf > b_kf) ? (w_kf - b_kf) : (b_kf - w_kf);
                    int rank_dist = (w_kr > b_kr) ? (w_kr - b_kr) : (b_kr - w_kr);
                    int chebyshev = (file_dist > rank_dist) ? file_dist : rank_dist;
                    int corner_bonus = (3 - edge_dist) * extended_mopup_edge_scale;
                    int proximity_bonus = (7 - chebyshev) * extended_mopup_proximity_scale;
                    score -= corner_bonus + proximity_bonus;
                }
            }
        }

        {
            int w_bishops = piece_counts[WHITE][BISHOP];
            int b_bishops = piece_counts[BLACK][BISHOP];
            int w_knights = piece_counts[WHITE][KNIGHT];
            int b_knights = piece_counts[BLACK][KNIGHT];
            int w_rooks = piece_counts[WHITE][ROOK];
            int b_rooks = piece_counts[BLACK][ROOK];
            int w_queens = piece_counts[WHITE][QUEEN];
            int b_queens = piece_counts[BLACK][QUEEN];
            int w_pawns = piece_counts[WHITE][PAWN];
            int b_pawns = piece_counts[BLACK][PAWN];

            if (w_bishops == 1 && b_bishops == 1 && w_knights == 0 && b_knights == 0 && w_rooks == 0 && b_rooks == 0 && w_queens == 0 && b_queens == 0)
            {
                U64 w_bishop_bb = b->pieces[WHITE][BISHOP];
                U64 b_bishop_bb = b->pieces[BLACK][BISHOP];
                int w_sq = lsb_index(w_bishop_bb);
                int b_sq = lsb_index(b_bishop_bb);
                int w_color = ((w_sq >> 3) ^ (w_sq & 7)) & 1;
                int b_color = ((b_sq >> 3) ^ (b_sq & 7)) & 1;

                if (w_color != b_color)
                {
                    int draw_factor = opposite_bishop_draw_factor_no_pawn;
                    if (w_pawns > 0 || b_pawns > 0)
                        draw_factor = opposite_bishop_draw_factor_pawn;
                    score = score * draw_factor / opposite_bishop_draw_divisor;
                }
            }
        }

        /* Known draw endgame detection (Task 8):
         * Recognize theoretical draw patterns to prevent the engine from
         * falsely evaluating them as winning positions. */
        {
            int w_rooks = piece_counts[WHITE][ROOK];
            int b_rooks = piece_counts[BLACK][ROOK];
            int w_bishops = piece_counts[WHITE][BISHOP];
            int b_bishops = piece_counts[BLACK][BISHOP];
            int w_knights = piece_counts[WHITE][KNIGHT];
            int b_knights = piece_counts[BLACK][KNIGHT];
            int w_queens = piece_counts[WHITE][QUEEN];
            int b_queens = piece_counts[BLACK][QUEEN];
            int w_pawns = piece_counts[WHITE][PAWN];
            int b_pawns = piece_counts[BLACK][PAWN];
            int w_minors = w_bishops + w_knights;
            int b_minors = b_bishops + b_knights;
            int w_majors = w_rooks + w_queens;
            int b_majors = b_rooks + b_queens;

            /* KR vs KB or KN (no pawns, no queens): theoretical draw.
             * The rook cannot force checkmate against a lone minor piece.
             * draw_factor = 4/16 (25% of score) */
            if (w_pawns == 0 && b_pawns == 0 && w_queens == 0 && b_queens == 0)
            {
                if (w_rooks == 1 && w_minors == 0 && b_rooks == 0 && b_majors == 0 && b_minors == 1)
                {
                    /* White has KR, Black has KB or KN: drawish */
                    score = score * 4 / 16;
                }
                else if (b_rooks == 1 && b_minors == 0 && w_rooks == 0 && w_majors == 0 && w_minors == 1)
                {
                    /* Black has KR, White has KB or KN: drawish */
                    score = score * 4 / 16;
                }
            }

            /* KB+P vs KB opposite color (no other pieces): very drawish.
             * The defending bishop can blockade on the opposite color.
             * draw_factor = 2/16 (12.5% of score) */
            if (w_pawns + b_pawns <= 1 && w_queens == 0 && b_queens == 0 &&
                w_rooks == 0 && b_rooks == 0 && w_knights == 0 && b_knights == 0 &&
                w_bishops == 1 && b_bishops == 1)
            {
                /* Check opposite-colored bishops */
                U64 wb_bb = b->pieces[WHITE][BISHOP];
                U64 bb_bb = b->pieces[BLACK][BISHOP];
                if (wb_bb && bb_bb)
                {
                    int wb_sq = lsb_index(wb_bb);
                    int bb_sq = lsb_index(bb_bb);
                    int wb_color = ((wb_sq >> 3) ^ (wb_sq & 7)) & 1;
                    int bb_color = ((bb_sq >> 3) ^ (bb_sq & 7)) & 1;
                    if (wb_color != bb_color)
                    {
                        score = score * 2 / 16;
                    }
                }
            }
        }

        /* Generic opposition evaluation */
        if (g_runtime_params.eval_endgame_enabled && phase < 12)
        {
            U64 wk_bb = b->pieces[WHITE][KING];
            U64 bk_bb = b->pieces[BLACK][KING];
            if (wk_bb && bk_bb)
            {
                int wk_sq = lsb_index(wk_bb);
                int bk_sq = lsb_index(bk_bb);
                int wk_f = wk_sq & 7, wk_r = wk_sq >> 3;
                int bk_f = bk_sq & 7, bk_r = bk_sq >> 3;
                int file_dist = abs(wk_f - bk_f);
                int rank_dist = abs(wk_r - bk_r);
                int opposition_bonus = 0;
                int opposition_side = -1; /* side that HAS the opposition */

                /* Direct opposition: same file or rank, distance 2 */
                if (file_dist == 0 && rank_dist == 2)
                {
                    opposition_bonus = 15 * (12 - phase) / 12;
                    /* Side NOT to move has the opposition */
                    opposition_side = b->side_to_move ^ 1;
                }
                else if (rank_dist == 0 && file_dist == 2)
                {
                    opposition_bonus = 15 * (12 - phase) / 12;
                    opposition_side = b->side_to_move ^ 1;
                }
                /* Distant opposition: same file or rank, distance 4 */
                else if (file_dist == 0 && rank_dist == 4)
                {
                    opposition_bonus = 8 * (12 - phase) / 12;
                    opposition_side = b->side_to_move ^ 1;
                }
                else if (rank_dist == 0 && file_dist == 4)
                {
                    opposition_bonus = 8 * (12 - phase) / 12;
                    opposition_side = b->side_to_move ^ 1;
                }

                if (opposition_bonus > 0 && opposition_side >= 0)
                {
                    /* Positive score favors White */
                    if (opposition_side == WHITE)
                        score += opposition_bonus;
                    else
                        score -= opposition_bonus;
                }
            }
        }

        if (score >= MATE_SCORE)
            score = MATE_SCORE - 1;
        else if (score <= -MATE_SCORE)
            score = -MATE_SCORE + 1;

        b->eval_score = score;
        return score;
    }
}

/* ============================================================================
 * INCREMENTAL EVAL VERIFICATION 鈥?production guard against silent PST drift
 * ============================================================================
 * Recomputes the full static PST+material score from scratch and compares
 * against the incrementally maintained b->mg_score / b->eg_score.
 * Called once per root node (ply==0) in negamax.
 * ============================================================================ */
static void verify_incremental_eval(const Board *b)
{
    int full_mg = 0, full_eg = 0;
    for (int s2 = 0; s2 < 2; s2++)
    {
        int sign2 = (s2 == WHITE) ? 1 : -1;
        for (int pt2 = PAWN; pt2 <= KING; pt2++)
        {
            U64 bb2 = b->pieces[s2][pt2];
            while (bb2)
            {
                int sq2 = lsb_index(bb2);
                bb2 &= bb2 - 1;
                int psq2 = (s2 == WHITE) ? sq2 : (sq2 ^ 56);
                full_mg += sign2 * (get_piece_value(pt2) + get_mg_pst(pt2, psq2));
                full_eg += sign2 * (get_piece_value(pt2) + get_eg_pst(pt2, psq2));
            }
        }
    }
    if (full_mg != b->mg_score || full_eg != b->eg_score)
    {
        fprintf(stderr, "INC EVAL MISMATCH at root: mg inc=%d full=%d | eg inc=%d full=%d\n",
                b->mg_score, full_mg, b->eg_score, full_eg);
    }
}
