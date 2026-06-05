/* engine_eval.c — 评估函数模块（从 engine_core.c 拆分） */
static int count_total_material(Board *b)
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

static int evaluate_pawns(Board *b, int phase)
{
    int score = 0;
    int side;
    for (side = 0; side < 2; side++)
    {
        int sign = (side == WHITE) ? 1 : -1;
        U64 pawns = b->pieces[side][PAWN];
        int files[8] = {0};
        int passed_files[8] = {0};
        U64 temp = pawns;
        while (temp)
        {
            int sq = lsb_index(temp);
            temp &= temp - 1;
            files[file_of(sq)]++;
        }
        int f;
        for (f = 0; f < 8; f++)
        {
            if (files[f] > 1)
            {
                int extra = files[f] - 1;
                score += sign * (DOUBLED_PAWN_PENALTY * extra * (extra + 1) / 2);
            }
        }
        temp = pawns;
        while (temp)
        {
            int sq = lsb_index(temp);
            temp &= temp - 1;
            int f = file_of(sq);
            int isolated = 1;
            if (f > 0 && files[f - 1] > 0)
                isolated = 0;
            if (f < 7 && files[f + 1] > 0)
                isolated = 0;
            if (isolated)
            {
                int penalty = ISOLATED_PAWN_PENALTY;
                U64 file_bb = file_masks[f];
                U64 opp_pawns = b->pieces[1 - side][PAWN];
                if (!(opp_pawns & file_bb))
                    penalty = penalty * 3 / 2;
                score += sign * penalty;
            }

            int r_pawn = rank_of(sq);
            int backward = 0;
            if (!isolated)
            {
                int own_pawns_behind = 0;
                if (side == WHITE && r_pawn > 0)
                {
                    if (f > 0)
                    {
                        U64 adj_mask = file_masks[f - 1] & ((1ULL << (r_pawn * 8)) - 1);
                        if (pawns & adj_mask)
                            own_pawns_behind = 1;
                    }
                    if (f < 7)
                    {
                        U64 adj_mask = file_masks[f + 1] & ((1ULL << (r_pawn * 8)) - 1);
                        if (pawns & adj_mask)
                            own_pawns_behind = 1;
                    }
                }
                else if (side == BLACK && r_pawn < 7)
                {
                    if (f > 0)
                    {
                        U64 adj_mask = file_masks[f - 1] & ~((1ULL << ((r_pawn + 1) * 8)) - 1);
                        if (pawns & adj_mask)
                            own_pawns_behind = 1;
                    }
                    if (f < 7)
                    {
                        U64 adj_mask = file_masks[f + 1] & ~((1ULL << ((r_pawn + 1) * 8)) - 1);
                        if (pawns & adj_mask)
                            own_pawns_behind = 1;
                    }
                }
                if (!own_pawns_behind)
                {
                    int adv_sq = (side == WHITE) ? sq + 8 : sq - 8;
                    if (adv_sq >= 0 && adv_sq < 64)
                    {
                        U64 opp_pawn_attacks_adv = 0;
                        U64 opp_p = b->pieces[1 - side][PAWN];
                        while (opp_p)
                        {
                            int opsq = lsb_index(opp_p);
                            opp_p &= opp_p - 1;
                            if (1 - side == WHITE)
                                opp_pawn_attacks_adv |= shift_north(shift_east(1ULL << opsq)) | shift_north(shift_west(1ULL << opsq));
                            else
                                opp_pawn_attacks_adv |= shift_south(shift_east(1ULL << opsq)) | shift_south(shift_west(1ULL << opsq));
                        }
                        if ((opp_pawn_attacks_adv >> adv_sq) & 1)
                            backward = 1;
                    }
                }
            }
            if (backward)
                score += sign * (-15);

            int r = rank_of(sq);
            int passed = 1;
            int df;
            for (df = -1; df <= 1; df++)
            {
                int af = f + df;
                if (af < 0 || af > 7)
                    continue;
                U64 enemy_pawns = b->pieces[1 - side][PAWN];
                U64 mask = file_masks[af];
                if (side == WHITE)
                {
                    mask &= ~((1ULL << (sq + 1)) - 1);
                }
                else
                {
                    mask &= ((1ULL << sq) - 1);
                }
                if (enemy_pawns & mask)
                {
                    passed = 0;
                    break;
                }
            }
            if (passed)
            {
                int bonus_rank = (side == WHITE) ? r : (7 - r);
                int bonus = passed_pawn_bonus[bonus_rank];
                int eg_phase = 24 - phase;
                int mg_phase = phase;
                int eg_multiplier = eg_phase * 100 / 24;
                int total_bonus = (bonus * mg_phase + bonus * eg_phase * 2) / 24;
                int promotion_threat = 0;
                int promo_sq;
                int promo_sq_attacked;
                score += sign * total_bonus;
                /* Promotion threat bonus: bigger bonus for pawns close to promotion.
                 * Rank 6 (one step away): 200 base + endgame multiplier
                 * Rank 5 (two steps away): 80 base + endgame multiplier */
                if (bonus_rank >= 5)
                {
                    promotion_threat = (bonus_rank == 6) ? 200 : 80;
                    promotion_threat += promotion_threat * eg_multiplier / 150;
                    score += sign * promotion_threat;
                }

                {
                    int supported = 0;
                    if (f > 0 && (pawns & (1ULL << sq)))
                    {
                        U64 adj_file = file_masks[f - 1];
                        U64 support_pawns = pawns & adj_file;
                        if (side == WHITE)
                            support_pawns &= ~((1ULL << sq) - 1);
                        else
                            support_pawns &= ~((1ULL << (sq + 1)) - 1);
                        if (support_pawns)
                            supported = 1;
                    }
                    if (!supported && f < 7)
                    {
                        U64 adj_file = file_masks[f + 1];
                        U64 support_pawns = pawns & adj_file;
                        if (side == WHITE)
                            support_pawns &= ~((1ULL << sq) - 1);
                        else
                            support_pawns &= ~((1ULL << (sq + 1)) - 1);
                        if (support_pawns)
                            supported = 1;
                    }
                    if (supported)
                        score += sign * 15;
                }

                {
                    int blocked_sq = (side == WHITE) ? sq + 8 : sq - 8;
                    if (blocked_sq >= 0 && blocked_sq < 64)
                    {
                        U64 blockers = b->pieces[1 - side][KNIGHT] | b->pieces[1 - side][BISHOP] |
                                       b->pieces[1 - side][ROOK] | b->pieces[1 - side][QUEEN] |
                                       b->pieces[1 - side][KING];
                        if (blockers & (1ULL << blocked_sq))
                        {
                            score += sign * (-10 - 5 * bonus_rank / 3);
                        }
                    }
                }

                if (side == WHITE)
                    promo_sq = 56 + f;
                else
                    promo_sq = f;
                promo_sq_attacked = is_square_attacked(b, promo_sq, 1 - side);
                if (promo_sq_attacked)
                {
                    score -= sign * total_bonus / 2;
                    if (bonus_rank >= 5)
                        score -= sign * promotion_threat / 2;
                }

                {
                    int path_clear = 1;
                    int pr;
                    for (pr = (side == WHITE) ? r - 1 : r + 1;
                         (side == WHITE) ? pr >= 0 : pr <= 7;
                         pr += (side == WHITE) ? -1 : 1)
                    {
                        int psq = pr * 8 + f;
                        if (b->pieces[1 - side][KNIGHT] & (1ULL << psq))
                        {
                            path_clear = 0;
                            break;
                        }
                        if (b->pieces[1 - side][BISHOP] & (1ULL << psq))
                        {
                            path_clear = 0;
                            break;
                        }
                        if (b->pieces[1 - side][ROOK] & (1ULL << psq))
                        {
                            path_clear = 0;
                            break;
                        }
                        if (b->pieces[1 - side][QUEEN] & (1ULL << psq))
                        {
                            path_clear = 0;
                            break;
                        }
                    }
                    if (path_clear && bonus_rank >= 4)
                        score += sign * (15 + bonus_rank * 8);
                }

                {
                    int king_sq = b->king_sq[side];
                    int kr = rank_of(king_sq), kc = file_of(king_sq);
                    int pawn_dist = abs(kr - r);
                    int promo_dist = (side == WHITE) ? (6 - r) : (r - 1);
                    if (pawn_dist <= 1 && promo_dist >= 2)
                        score += sign * (15 + (6 - promo_dist) * 5);
                }

                passed_files[f] = 1;
            }

            int chain = 0;
            if (side == WHITE)
            {
                if (r > 0)
                {
                    if (f > 0 && (pawns & (1ULL << ((r - 1) * 8 + f - 1))))
                        chain = 1;
                    if (f < 7 && (pawns & (1ULL << ((r - 1) * 8 + f + 1))))
                        chain = 1;
                }
            }
            else
            {
                if (r < 7)
                {
                    if (f > 0 && (pawns & (1ULL << ((r + 1) * 8 + f - 1))))
                        chain = 1;
                    if (f < 7 && (pawns & (1ULL << ((r + 1) * 8 + f + 1))))
                        chain = 1;
                }
            }
            if (chain)
                score += sign * PAWN_CHAIN_BONUS;

            if (phase >= 20)
            {
                if (side == WHITE && (sq == 27 || sq == 28))
                    score += sign * 20;
                else if (side == BLACK && (sq == 35 || sq == 36))
                    score += sign * 20;
            }
        }
        {
            int cf;
            for (cf = 0; cf < 7; cf++)
            {
                if (passed_files[cf] && passed_files[cf + 1])
                {
                    score += sign * 30;
                }
            }
        }
        {
            int rank_pawns[8][8] = {{0}};
            U64 tmp = pawns;
            while (tmp)
            {
                int sq2 = lsb_index(tmp);
                tmp &= tmp - 1;
                rank_pawns[rank_of(sq2)][file_of(sq2)] = 1;
            }
            int rr;
            for (rr = 2; rr <= 5; rr++)
            {
                int ff;
                for (ff = 2; ff <= 5; ff++)
                {
                    if (rank_pawns[rr][ff] && rank_pawns[rr][ff + 1])
                    {
                        score += sign * 15;
                    }
                }
            }
            if (side == WHITE && rank_pawns[3][3] && rank_pawns[3][4])
                score += sign * 20;
            else if (side == BLACK && rank_pawns[4][3] && rank_pawns[4][4])
                score += sign * 20;
        }
    }
    return score;
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

    int score = 0;
    int side, pt;
    int npm_w = b->npm[0], npm_b = b->npm[1];

    int phase = b->phase;

    int phase_weight = phase * 256 / 24;

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

    for (side = 0; side < 2; side++)
    {
        int sign = (side == WHITE) ? 1 : -1;
        for (pt = PAWN; pt <= KING; pt++)
        {
            U64 bb = b->pieces[side][pt];
            while (bb)
            {
                int sq = lsb_index(bb);
                bb &= bb - 1;
                int psq = (side == WHITE) ? (sq ^ 56) : sq;
                int mg, eg;
                if (g_runtime_params.loaded)
                {
                    mg = g_runtime_params.mg_pst[pt - 1][psq];
                    eg = g_runtime_params.eg_pst[pt - 1][psq];
                }
                else
                {
                    mg = mg_pst[pt][psq];
                    eg = eg_pst[pt][psq];
                }
                int tapered = (mg * phase + eg * (24 - phase)) / 24;
                score += sign * (piece_values[pt] + tapered);
            }
        }
    }

    {
        for (side = 0; side < 2; side++)
        {
            int sign = (side == WHITE) ? 1 : -1;
            U64 own_pieces = side_pieces(b, side);

            U64 knights = b->pieces[side][KNIGHT];
            while (knights)
            {
                int sq = lsb_index(knights);
                knights &= knights - 1;
                int mob = popcount(knight_attacks[sq] & ~own_pieces);
                if (mob > 8)
                    mob = 8;
                int mg_score = knight_mob_mg[mob];
                int eg_score = knight_mob_eg[mob];
                score += sign * ((mg_score * phase_weight + eg_score * (256 - phase_weight)) / 256);
            }

            {
                int bi;
                for (bi = 0; bi < nb[side]; bi++)
                {
                    int mob = popcount(bishop_atk[side][bi] & ~own_pieces);
                    if (mob > 13)
                        mob = 13;
                    int mg_score = bishop_mob_mg[mob];
                    int eg_score = bishop_mob_eg[mob];
                    score += sign * ((mg_score * phase_weight + eg_score * (256 - phase_weight)) / 256);
                }
            }

            {
                int ri;
                for (ri = 0; ri < nr[side]; ri++)
                {
                    int mob = popcount(rook_atk[side][ri] & ~own_pieces);
                    if (mob > 14)
                        mob = 14;
                    int mg_score = rook_mob_mg[mob];
                    int eg_score = rook_mob_eg[mob];
                    score += sign * ((mg_score * phase_weight + eg_score * (256 - phase_weight)) / 256);
                }
            }

            {
                int qi;
                for (qi = 0; qi < nq[side]; qi++)
                {
                    int mob = popcount((queen_batk[side][qi] | queen_ratk[side][qi]) & ~own_pieces);
                    if (mob > 27)
                        mob = 27;
                    int mg_score = queen_mob_mg[mob];
                    int eg_score = queen_mob_eg[mob];
                    score += sign * ((mg_score * phase_weight + eg_score * (256 - phase_weight)) / 256);
                }
            }
        }
    }

    {
        int pawn_score;
        U64 pawn_key = b->pawn_hash;
        int pawn_idx = (int)(pawn_key & (PAWN_HASH_SIZE - 1));
        if (pawn_hash_table[pawn_idx].key == pawn_key)
        {
            pawn_score = pawn_hash_table[pawn_idx].score;
        }
        else
        {
            pawn_score = evaluate_pawns(b, phase);
            pawn_hash_table[pawn_idx].key = pawn_key;
            pawn_hash_table[pawn_idx].score = pawn_score;
        }
        score += pawn_score;
    }

    for (side = 0; side < 2; side++)
    {
        int sign = (side == WHITE) ? 1 : -1;
        if (count_bits(b->pieces[side][BISHOP]) >= 2)
        {
            score += sign * BISHOP_PAIR_BONUS;
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
                score += sign * OPEN_FILE_BONUS;
            }
            else if (own_pawns_on_file == 0 && enemy_pawns_on_file > 0)
            {
                score += sign * SEMI_OPEN_FILE_BONUS;
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
                        score += sign * ROOK_POTENTIAL_OPEN_FILE;
                    }
                }
                else if (!(own_pawns & file_mask) && (enemy_pawns & file_mask))
                {
                    if (!(rooks & file_mask))
                    {
                        score += sign * ROOK_POTENTIAL_SEMI_OPEN;
                    }
                }
            }
        }
    }

    for (side = 0; side < 2; side++)
    {
        int sign = (side == WHITE) ? 1 : -1;
        U64 bishops = b->pieces[side][BISHOP];
        U64 center_pawns = b->pieces[side][PAWN] & (0x1818181818181818ULL);
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
                score += sign * BISHOP_MOBILITY_BONUS;
            else if (pawns_on_color >= 2)
                score += sign * BISHOP_BAD_PENALTY;
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
            int mg_bonus = 20;
            int eg_bonus = 30;
            int bonus = (mg_bonus * phase + eg_bonus * (24 - phase)) / 24;
            score += sign * bonus * rooks_on_7th;
            if (rooks_on_7th >= 2)
                score += sign * 20;
            int opp_king_rank = rank_of(b->king_sq[opp_r7]);
            int king_on_8th = (side == WHITE && opp_king_rank == 7) || (side == BLACK && opp_king_rank == 0);
            if (king_on_8th)
            {
                score += sign * 25;
                if (rooks_on_7th >= 2)
                    score += sign * 15;
            }
        }
    }

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

        U64 opp_knights = b->pieces[opp][KNIGHT];
        while (opp_knights)
        {
            int sq = lsb_index(opp_knights);
            opp_knights &= opp_knights - 1;
            U64 attacks = knight_attacks[sq] & king_zone;
            if (attacks)
            {
                attack_units += 2 + count_bits(attacks);
            }
        }

        {
            int bi;
            for (bi = 0; bi < nb[opp]; bi++)
            {
                U64 attacks = bishop_atk[opp][bi] & king_zone;
                if (attacks)
                {
                    attack_units += 2 + count_bits(attacks);
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
                    attack_units += 3 + count_bits(attacks) * 2;
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
                    attack_units += 5 + count_bits(attacks) * 2;
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
            U64 shield_pawns;
            if (side == WHITE)
            {
                U64 rank2_pawns = file_mask & own_pawns & rank_masks[1];
                U64 rank3_pawns = file_mask & own_pawns & rank_masks[2];
                if (rank2_pawns)
                    attack_units += 0;
                else if (rank3_pawns)
                    attack_units += 4;
                else
                    attack_units += 10;
            }
            else
            {
                U64 rank7_pawns = file_mask & own_pawns & rank_masks[6];
                U64 rank6_pawns = file_mask & own_pawns & rank_masks[5];
                if (rank7_pawns)
                    attack_units += 0;
                else if (rank6_pawns)
                    attack_units += 4;
                else
                    attack_units += 10;
            }
        }

        {
            U64 king_file_mask = file_masks[kf];
            U64 adj_file_mask = 0;
            if (kf > 0)
                adj_file_mask |= file_masks[kf - 1];
            if (kf < 7)
                adj_file_mask |= file_masks[kf + 1];
            U64 own_pawns_on_king_files = own_pawns & (king_file_mask | adj_file_mask);
            U64 enemy_pawns_on_king_files = b->pieces[opp][PAWN] & (king_file_mask | adj_file_mask);
            U64 open_files = (king_file_mask | adj_file_mask) & ~own_pawns_on_king_files & ~enemy_pawns_on_king_files;
            U64 semi_open_files = (king_file_mask | adj_file_mask) & ~own_pawns_on_king_files & enemy_pawns_on_king_files;
            attack_units += count_bits(open_files) * 6;
            attack_units += count_bits(semi_open_files) * 3;
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
        if (nq[opp] > 0)
            attacker_count++;
        if (attacker_count >= 2)
            attack_units += (attacker_count - 1) * 6;

        int danger_index = (attack_units < 128) ? attack_units : 127;
        int danger = king_danger_table[danger_index];

        if (danger > 4000)
            danger = 4000;

        if (phase_weight <= 128)
        {
            danger = danger * (40 + phase_weight * 40 / 128) / 100;
        }

        score -= sign * danger;
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
        score += sign * (8 * count_bits(occ & center));
        score += sign * (3 * count_bits(occ & ext & ~center));

        U64 pawns = b->pieces[side][PAWN];
        score += sign * (20 * count_bits(pawns & center));
        score += sign * (6 * count_bits(pawns & (ext & ~center)));
    }

    for (side = 0; side < 2; side++)
    {
        int opp = 1 - side;
        int sign = (side == WHITE) ? 1 : -1;
        U64 own_pieces_bb = 0;
        for (pt = KNIGHT; pt <= QUEEN; pt++)
            own_pieces_bb |= b->pieces[side][pt];

        U64 enemy_attacks = 0;
        U64 opp_pawns = b->pieces[opp][PAWN];
        while (opp_pawns)
        {
            int sq = lsb_index(opp_pawns);
            opp_pawns &= opp_pawns - 1;
            if (opp == WHITE)
            {
                enemy_attacks |= shift_north(shift_east(1ULL << sq)) | shift_north(shift_west(1ULL << sq));
            }
            else
            {
                enemy_attacks |= shift_south(shift_east(1ULL << sq)) | shift_south(shift_west(1ULL << sq));
            }
        }
        U64 opp_knights = b->pieces[opp][KNIGHT];
        while (opp_knights)
        {
            int sq = lsb_index(opp_knights);
            opp_knights &= opp_knights - 1;
            enemy_attacks |= knight_attacks[sq];
        }
        {
            int bi;
            for (bi = 0; bi < nb[opp]; bi++)
                enemy_attacks |= bishop_atk[opp][bi];
        }
        {
            int ri;
            for (ri = 0; ri < nr[opp]; ri++)
                enemy_attacks |= rook_atk[opp][ri];
        }
        {
            int qi;
            for (qi = 0; qi < nq[opp]; qi++)
                enemy_attacks |= queen_batk[opp][qi] | queen_ratk[opp][qi];
        }
        enemy_attacks |= king_attacks[b->king_sq[opp]];

        U64 own_defended = 0;
        U64 own_pawns = b->pieces[side][PAWN];
        while (own_pawns)
        {
            int sq = lsb_index(own_pawns);
            own_pawns &= own_pawns - 1;
            if (side == WHITE)
            {
                own_defended |= shift_north(shift_east(1ULL << sq)) | shift_north(shift_west(1ULL << sq));
            }
            else
            {
                own_defended |= shift_south(shift_east(1ULL << sq)) | shift_south(shift_west(1ULL << sq));
            }
        }
        own_defended |= king_attacks[b->king_sq[side]];

        U64 hanging = own_pieces_bb & enemy_attacks & ~own_defended;
        while (hanging)
        {
            int sq = lsb_index(hanging);
            hanging &= hanging - 1;
            int pt2 = piece_on_square(b, sq);
            int penalty = 0;
            if (pt2 == QUEEN)
                penalty = 45;
            else if (pt2 == ROOK)
                penalty = 30;
            else if (pt2 == BISHOP || pt2 == KNIGHT)
                penalty = 23;
            score -= sign * penalty;
        }
    }

    if (is_check(b, b->side_to_move))
    {
        if (b->side_to_move == WHITE)
            score -= 25;
        else
            score += 25;
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
            int blocked = 1;
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
                            blocked = 1;
                        else
                            blocked = 0;
                        break;
                    }
                }
                if (!found_pawn)
                {
                    /* No pawn on this file - king can escape, not blocked */
                    blocked = 0;
                }
                if (!blocked)
                    break;
            }
            if (blocked)
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
                    score += sign * (-50);
                }
            }
        }
    }

    for (side = 0; side < 2; side++)
    {
        int sign = (side == WHITE) ? 1 : -1;
        int opp = 1 - side;
        U64 enemy_pawns = b->pieces[opp][PAWN];
        U64 friendly_pawns = b->pieces[side][PAWN];

        U64 enemy_pawn_attacks = 0;
        {
            U64 temp = enemy_pawns;
            while (temp)
            {
                int sq = lsb_index(temp);
                temp &= temp - 1;
                if (opp == WHITE)
                {
                    if (file_of(sq) > 0 && sq + 7 < 64)
                        enemy_pawn_attacks |= 1ULL << (sq + 7);
                    if (file_of(sq) < 7 && sq + 9 < 64)
                        enemy_pawn_attacks |= 1ULL << (sq + 9);
                }
                else
                {
                    if (file_of(sq) > 0 && sq - 9 >= 0)
                        enemy_pawn_attacks |= 1ULL << (sq - 9);
                    if (file_of(sq) < 7 && sq - 7 >= 0)
                        enemy_pawn_attacks |= 1ULL << (sq - 7);
                }
            }
        }

        U64 own_pawn_defense = 0;
        {
            U64 temp = friendly_pawns;
            while (temp)
            {
                int sq = lsb_index(temp);
                temp &= temp - 1;
                if (side == WHITE)
                {
                    if (file_of(sq) > 0 && sq + 7 < 64)
                        own_pawn_defense |= 1ULL << (sq + 7);
                    if (file_of(sq) < 7 && sq + 9 < 64)
                        own_pawn_defense |= 1ULL << (sq + 9);
                }
                else
                {
                    if (file_of(sq) > 0 && sq - 9 >= 0)
                        own_pawn_defense |= 1ULL << (sq - 9);
                    if (file_of(sq) < 7 && sq - 7 >= 0)
                        own_pawn_defense |= 1ULL << (sq - 7);
                }
            }
        }

        U64 enemy_knight_attacks = 0;
        {
            U64 temp = b->pieces[opp][KNIGHT];
            while (temp)
            {
                int sq = lsb_index(temp);
                temp &= temp - 1;
                enemy_knight_attacks |= knight_attacks[sq];
            }
        }

        U64 knights = b->pieces[side][KNIGHT];
        while (knights)
        {
            int sq = lsb_index(knights);
            knights &= knights - 1;
            int r = rank_of(sq);
            int f = file_of(sq);

            int can_be_attacked_by_pawn = (enemy_pawn_attacks >> sq) & 1;
            int defended_by_pawn = (own_pawn_defense >> sq) & 1;

            if (f == 0 || f == 7)
            {
                if (r >= 2 && r <= 5)
                    score += sign * (-30);
            }

            if (phase >= 16)
            {
                if (side == WHITE)
                {
                    if (sq == 18 && (b->pieces[WHITE][PAWN] & (1ULL << 10)))
                        score += sign * (-25);
                    if (sq == 21 && (b->pieces[WHITE][PAWN] & (1ULL << 13)))
                        score += sign * (-25);
                }
                else
                {
                    if (sq == 42 && (b->pieces[BLACK][PAWN] & (1ULL << 50)))
                        score += sign * (-25);
                    if (sq == 45 && (b->pieces[BLACK][PAWN] & (1ULL << 53)))
                        score += sign * (-25);
                }
            }
        }

        U64 knights_for_outpost = b->pieces[side][KNIGHT];
        while (knights_for_outpost)
        {
            int sq = lsb_index(knights_for_outpost);
            knights_for_outpost &= knights_for_outpost - 1;
            int r = rank_of(sq);
            int can_be_attacked_by_pawn_out = (enemy_pawn_attacks >> sq) & 1;
            int defended_by_pawn_out = (own_pawn_defense >> sq) & 1;
            if (!can_be_attacked_by_pawn_out && defended_by_pawn_out)
            {
                int outpost_mg = 0, outpost_eg = 0;
                if (side == WHITE && r >= 3 && r <= 5)
                {
                    outpost_mg = 15 + (r - 3) * 5;
                    outpost_eg = 10 + (r - 3) * 3;
                }
                else if (side == BLACK && r >= 2 && r <= 4)
                {
                    outpost_mg = 15 + (4 - r) * 5;
                    outpost_eg = 10 + (4 - r) * 3;
                }
                if (outpost_mg > 0)
                {
                    int outpost_bonus = (outpost_mg * phase + outpost_eg * (24 - phase)) / 24;
                    score += sign * outpost_bonus;
                }
            }
        }

        U64 bishops_bb = b->pieces[side][BISHOP];
        while (bishops_bb)
        {
            int sq = lsb_index(bishops_bb);
            bishops_bb &= bishops_bb - 1;
            int r = rank_of(sq);
            int f = file_of(sq);

            int can_be_attacked_by_pawn_b = (enemy_pawn_attacks >> sq) & 1;
            int defended_by_pawn_b = (own_pawn_defense >> sq) & 1;
        }

        U64 own_minor_major = b->pieces[side][KNIGHT] | b->pieces[side][BISHOP] |
                              b->pieces[side][ROOK] | b->pieces[side][QUEEN];
        U64 attacked_by_pawn = own_minor_major & enemy_pawn_attacks;
        U64 attacked_by_knight = own_minor_major & enemy_knight_attacks & ~enemy_pawn_attacks;
        U64 defended_by_own_pawn = own_minor_major & own_pawn_defense;

        U64 queens_attacked_by_pawn = attacked_by_pawn & b->pieces[side][QUEEN];
        U64 rooks_attacked_by_pawn = attacked_by_pawn & b->pieces[side][ROOK];
        U64 minors_attacked_by_pawn = attacked_by_pawn & ~(queens_attacked_by_pawn | rooks_attacked_by_pawn);
        score += sign * (-25 * count_bits(queens_attacked_by_pawn));
        score += sign * (-20 * count_bits(rooks_attacked_by_pawn));
        score += sign * (-15 * count_bits(minors_attacked_by_pawn));
        score += sign * (-5 * count_bits(queens_attacked_by_pawn));
        score += sign * (-3 * count_bits(rooks_attacked_by_pawn));

        U64 queens_attacked_by_knight = attacked_by_knight & b->pieces[side][QUEEN];
        U64 rooks_attacked_by_knight = attacked_by_knight & b->pieces[side][ROOK];
        U64 minors_attacked_by_knight = attacked_by_knight & ~(queens_attacked_by_knight | rooks_attacked_by_knight);
        score += sign * (-20 * count_bits(queens_attacked_by_knight));
        score += sign * (-15 * count_bits(rooks_attacked_by_knight));
        score += sign * (-13 * count_bits(minors_attacked_by_knight));

        score += sign * (10 * count_bits(defended_by_own_pawn));

        U64 enemy_knights_bb = b->pieces[opp][KNIGHT];
        while (enemy_knights_bb)
        {
            int ksq = lsb_index(enemy_knights_bb);
            enemy_knights_bb &= enemy_knights_bb - 1;
            U64 k_attacks = knight_attacks[ksq];
            U64 forked_valuable = k_attacks & (b->pieces[side][QUEEN] | b->pieces[side][ROOK]);
            int fork_count = count_bits(forked_valuable);
            if (fork_count >= 2)
                score += sign * (-75);
            U64 forked_with_king = k_attacks & b->pieces[side][KING];
            if (forked_with_king && count_bits(forked_valuable) >= 1)
                score += sign * (-60);
        }

        U64 queens = b->pieces[side][QUEEN];
        while (queens)
        {
            int sq = lsb_index(queens);
            queens &= queens - 1;
            int attacked_by_lesser = 0;
            if (b->pieces[opp][KNIGHT] && (knight_attacks[sq] & b->pieces[opp][KNIGHT]))
                attacked_by_lesser = 1;
            if (!attacked_by_lesser)
            {
                int bi;
                for (bi = 0; bi < nb[opp]; bi++)
                {
                    if (bishop_atk[opp][bi] & (1ULL << sq))
                    {
                        attacked_by_lesser = 1;
                        break;
                    }
                }
            }
            if (!attacked_by_lesser)
            {
                int ri;
                for (ri = 0; ri < nr[opp]; ri++)
                {
                    if (rook_atk[opp][ri] & (1ULL << sq))
                    {
                        attacked_by_lesser = 1;
                        break;
                    }
                }
            }
            if (attacked_by_lesser)
            {
                if (!defended_by_own_pawn || !(own_pawn_defense & (1ULL << sq)))
                    score += sign * (-75);
                else
                    score += sign * (-30);
            }
        }

        U64 rooks = b->pieces[side][ROOK];
        while (rooks)
        {
            int sq = lsb_index(rooks);
            rooks &= rooks - 1;
            int rook_attacked_by_lesser = 0;
            if (b->pieces[opp][KNIGHT] && (knight_attacks[sq] & b->pieces[opp][KNIGHT]))
                rook_attacked_by_lesser = 1;
            if (!rook_attacked_by_lesser)
            {
                int bi;
                for (bi = 0; bi < nb[opp]; bi++)
                {
                    if (bishop_atk[opp][bi] & (1ULL << sq))
                    {
                        rook_attacked_by_lesser = 1;
                        break;
                    }
                }
            }
            if (rook_attacked_by_lesser)
            {
                if (!defended_by_own_pawn || !(own_pawn_defense & (1ULL << sq)))
                    score += sign * (-40);
                else
                    score += sign * (-15);
            }
        }
    }

    if (b->fullmove_number <= 15)
    {
        for (side = 0; side < 2; side++)
        {
            int sign = (side == WHITE) ? 1 : -1;
            if (b->pieces[side][KNIGHT] & (1ULL << (side == WHITE ? 1 : 57)))
                score += sign * (-20);
            if (b->pieces[side][KNIGHT] & (1ULL << (side == WHITE ? 6 : 62)))
                score += sign * (-20);
            if (b->pieces[side][BISHOP] & (1ULL << (side == WHITE ? 2 : 58)))
                score += sign * (-20);
            if (b->pieces[side][BISHOP] & (1ULL << (side == WHITE ? 5 : 61)))
                score += sign * (-20);
            {
                U64 queen_pos = b->pieces[side][QUEEN];
                U64 start_sq = (1ULL << (side == WHITE ? 3 : 59));
                U64 minor = b->pieces[side][KNIGHT] | b->pieces[side][BISHOP];
                int dev = 0;
                U64 t = minor;
                while (t)
                {
                    int sq = lsb_index(t);
                    t &= t - 1;
                    if (side == WHITE && (sq < 8 || sq == 9 || sq == 14))
                        continue;
                    if (side == BLACK && (sq >= 56 || sq == 49 || sq == 54))
                        continue;
                    dev++;
                }
                if (!(queen_pos & start_sq) && dev < 3)
                {
                    int penalty = 40 - dev * 10;
                    if (penalty < 10)
                        penalty = 10;
                    score += sign * (-penalty);
                }
            }

            U64 minor = b->pieces[side][KNIGHT] | b->pieces[side][BISHOP];
            int developed = 0;
            U64 temp = minor;
            while (temp)
            {
                int sq = lsb_index(temp);
                temp &= temp - 1;
                if (side == WHITE && (sq < 8 || sq == 9 || sq == 14))
                    continue;
                if (side == BLACK && (sq >= 56 || sq == 49 || sq == 54))
                    continue;
                developed++;
            }
            if (developed < 2 && b->fullmove_number >= 5)
                score += sign * (-30);
            if (developed < 3 && b->fullmove_number >= 8)
                score += sign * (-20);

            int king_sq = -1;
            U64 kbb = b->pieces[side][KING];
            if (kbb)
                king_sq = lsb_index(kbb);
            if (king_sq >= 0)
            {
                if (side == WHITE && king_sq == 4 && b->fullmove_number >= 6)
                    score += sign * (-25);
                if (side == BLACK && king_sq == 60 && b->fullmove_number >= 6)
                    score += sign * (-25);
            }
            {
                U64 queens = b->pieces[side][QUEEN];
                U64 rooks = b->pieces[side][ROOK];
                U64 minor = b->pieces[side][KNIGHT] | b->pieces[side][BISHOP];
                int developed = 0;
                U64 temp = minor;
                while (temp)
                {
                    int sq = lsb_index(temp);
                    temp &= temp - 1;
                    if (side == WHITE && (sq < 8 || sq == 9 || sq == 14))
                        continue;
                    if (side == BLACK && (sq >= 56 || sq == 49 || sq == 54))
                        continue;
                    developed++;
                }
                if (developed < 3)
                {
                    U64 enemy_half = (side == WHITE) ? 0xFFFFFFFF00000000ULL : 0x00000000FFFFFFFFULL;
                    if (queens & enemy_half)
                    {
                        int penalty = 50 - developed * 10;
                        if (penalty < 20)
                            penalty = 20;
                        score += sign * (-penalty);
                    }
                    if (rooks & enemy_half)
                        score += sign * (-15);
                }
            }
            {
                U64 own_center;
                if (side == WHITE)
                    own_center = b->pieces[WHITE][PAWN] & ((1ULL << 27) | (1ULL << 28));
                else
                    own_center = b->pieces[BLACK][PAWN] & ((1ULL << 35) | (1ULL << 36));
                if (own_center)
                    score += sign * (10 * count_bits(own_center));
                else
                    score += sign * (-35);
            }
        }
    }

    {
        int w_minors = count_bits(b->pieces[WHITE][KNIGHT]) + count_bits(b->pieces[WHITE][BISHOP]);
        int b_minors = count_bits(b->pieces[BLACK][KNIGHT]) + count_bits(b->pieces[BLACK][BISHOP]);
        int w_pawns = count_bits(b->pieces[WHITE][PAWN]);
        int b_pawns = count_bits(b->pieces[BLACK][PAWN]);

        int minor_diff = w_minors - b_minors;
        int pawn_diff = w_pawns - b_pawns;

        int mg_weight = phase;
        int eg_weight = 24 - phase;

        if (minor_diff > 0 && pawn_diff < 0)
        {
            int imbalance = minor_diff;
            if (imbalance > 3)
                imbalance = 3;
            int mg_penalty = imbalance * (50 + 15 * imbalance);
            int eg_penalty = imbalance * 20;
            int penalty = (mg_penalty * mg_weight + eg_penalty * eg_weight) / 24;
            score += penalty;
        }
        else if (minor_diff < 0 && pawn_diff > 0)
        {
            int imbalance = -minor_diff;
            if (imbalance > 3)
                imbalance = 3;
            int mg_penalty = imbalance * (50 + 15 * imbalance);
            int eg_penalty = imbalance * 20;
            int penalty = (mg_penalty * mg_weight + eg_penalty * eg_weight) / 24;
            score -= penalty;
        }

        if (w_minors == 0 && b_minors >= 2)
            score -= 80;
        else if (b_minors == 0 && w_minors >= 2)
            score += 80;
    }

    if (b->halfmove_clock >= 40)
    {
        int abs_score = (score > 0) ? score : -score;
        if (abs_score > 300)
        {
            int penalty = (b->halfmove_clock - 40) * (abs_score / 100);
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
            white_non_pawn_material += count_bits(b->pieces[WHITE][pt]) * piece_values[pt];
            black_non_pawn_material += count_bits(b->pieces[BLACK][pt]) * piece_values[pt];
        }
        int material_balance = white_non_pawn_material - black_non_pawn_material;

        if (material_balance > 500)
        {
            mop_up_active = 1;
            mop_up_strong_side = WHITE;
        }
        else if (material_balance < -500)
        {
            mop_up_active = 1;
            mop_up_strong_side = BLACK;
        }

        if (phase <= 6)
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
                        activity_weight = 15;
                    else if (mop_up_active && mop_up_strong_side == (1 - side))
                        activity_weight = 3;
                    else
                        activity_weight = (phase < 8) ? 25 : g_runtime_params.king_activity_weight;
                    int activity_bonus = (6 - center_dist) * activity_weight;
                    score += sign * activity_bonus;
                }
            }
        }

        if (material_balance > SIMPLIFY_THRESHOLD)
        {
            int advantage = material_balance - SIMPLIFY_THRESHOLD;
            int bonus = SIMPLIFY_BONUS * advantage / 100;
            if (bonus > SIMPLIFY_BONUS * 3)
                bonus = SIMPLIFY_BONUS * 3;
            score += bonus;
        }
        else if (material_balance < -SIMPLIFY_THRESHOLD)
        {
            int advantage = -material_balance - SIMPLIFY_THRESHOLD;
            int bonus = SIMPLIFY_BONUS * advantage / 100;
            if (bonus > SIMPLIFY_BONUS * 3)
                bonus = SIMPLIFY_BONUS * 3;
            score -= bonus;
        }

        /* Anti-simplification: when behind in material, discourage exchanges.
         * The trailing side gets a small bonus for each piece on the board,
         * making it less likely to trade pieces unnecessarily.
         * This encourages the losing side to keep pieces and create complications. */
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
                int trailing_bonus = (piece_count - 6) * 2; /* ~2cp per extra piece */
                if (trailing_bonus > 0)
                    score += trailing_bonus; /* Favors the losing side (white is losing, help white keep pieces) */
            }
            else if (material_balance > 100)
            {
                int trailing_bonus = (piece_count - 6) * 2;
                if (trailing_bonus > 0)
                    score -= trailing_bonus; /* Favors the losing side (black is losing, help black keep pieces) */
            }
        }

        if (phase < 16 && (material_balance > 500 || material_balance < -500))
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
            int corner_bonus = (3 - edge_dist) * 80;

            int strong_file = strong_king_sq % 8;
            int strong_rank = strong_king_sq / 8;
            int file_dist = (weak_file > strong_file) ? (weak_file - strong_file) : (strong_file - weak_file);
            int rank_dist = (weak_rank > strong_rank) ? (weak_rank - strong_rank) : (strong_rank - weak_rank);
            int king_dist = (file_dist > rank_dist) ? file_dist : rank_dist;
            /* Stronger proximity bonus to encourage winning king approach */
            int proximity_bonus = (7 - king_dist) * 50;

            int mop_up = corner_bonus + proximity_bonus;
            score += (strong_side == WHITE) ? mop_up : -mop_up;
        }
    }

    // 王车易位奖励 - 鼓励王车易位，特别是短易位
    // 只在开局和中局阶段给予奖励（phase > 12 表示非残局）
    if (phase > 12)
    {
        int white_king_sq = lsb_index(b->pieces[WHITE][KING]);
        int black_king_sq = lsb_index(b->pieces[BLACK][KING]);

        // 白方易位奖励
        if (white_king_sq == 6) // g1 - 短易位
        {
            score += 30;
        }
        else if (white_king_sq == 2) // c1 - 长易位
        {
            score += 15;
        }

        // 黑方易位奖励
        if (black_king_sq == 62) // g8 - 短易位
        {
            score -= 30;
        }
        else if (black_king_sq == 58) // c8 - 长易位
        {
            score -= 15;
        }
    }

    {
        int tempo_mg = 15;
        int tempo_eg = 8;
        int tempo = (tempo_mg * phase_weight + tempo_eg * (256 - phase_weight)) / 256;
        if (b->side_to_move == WHITE)
            score += tempo;
        else
            score -= tempo;
    }

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
        int total_pawns = w_pawns + b_pawns;

        /* ============================================================
         * Mop-up evaluation for winning endgames
         * ============================================================ */

        /* Helper: calculate mop-up score for king vs king (strong king pushes weak king to edge) */
        #define MOPUP_KING_EDGE_WEIGHT  120
        #define MOPUP_KING_PROX_WEIGHT  60
        #define MOPUP_OPPOSITION_WEIGHT 80

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
            int manhattan = file_dist + rank_dist;

            /* Push enemy king to edge/corner */
            int corner_bonus = (3 - edge_dist) * MOPUP_KING_EDGE_WEIGHT;
            /* Keep our king close to enemy king */
            int proximity_bonus = (7 - chebyshev) * MOPUP_KING_PROX_WEIGHT;
            /* Opposition bonus: kings face each other with one square gap */
            int opposition_bonus = 0;
            if (chebyshev == 2 && manhattan % 2 == 0)
                opposition_bonus = MOPUP_OPPOSITION_WEIGHT;

            /* KRK-specific: encourage rook to cut off enemy king */
            int rook_cutoff_bonus = 0;
            if (is_krk_white)
            {
                int rook_sq = lsb_index(b->pieces[WHITE][ROOK]);
                int r_f = file_of(rook_sq), r_r = rank_of(rook_sq);
                /* Rook on same rank/file as enemy king cuts off escape */
                if (r_f == b_kf || r_r == b_kr)
                    rook_cutoff_bonus = 60;
                /* Rook far from enemy king is bad (should stay close to control) */
                int r_dist_f = (r_f > b_kf) ? (r_f - b_kf) : (b_kf - r_f);
                int r_dist_r = (r_r > b_kr) ? (r_r - b_kr) : (b_kr - r_r);
                if (r_dist_f > 3 && r_dist_r > 3)
                    rook_cutoff_bonus -= 40;
            }

            score += corner_bonus + proximity_bonus + opposition_bonus + rook_cutoff_bonus;
        }
        else if (is_kqkr_white)
        {
            /* KQKR: queen vs rook — winning side pushes enemy king to edge,
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

            int corner_bonus = (3 - edge_dist) * 150;
            int proximity_bonus = (7 - chebyshev) * 80;
            /* Queen close to enemy king increases chance of forks */
            int queen_sq = lsb_index(b->pieces[WHITE][QUEEN]);
            int q_dist_f = (file_of(queen_sq) > b_kf) ? (file_of(queen_sq) - b_kf) : (b_kf - file_of(queen_sq));
            int q_dist_r = (rank_of(queen_sq) > b_kr) ? (rank_of(queen_sq) - b_kr) : (b_kr - rank_of(queen_sq));
            int q_chebyshev = (q_dist_f > q_dist_r) ? q_dist_f : q_dist_r;
            int queen_prox_bonus = (7 - q_chebyshev) * 50;
            /* Avoid stalemate: if enemy king is on edge, keep some distance */
            int stalemate_avoid = 0;
            if (edge_dist == 0 && chebyshev == 1)
                stalemate_avoid = -100;
            /* Big bonus when enemy king is actually in corner (mate is close) */
            int corner_mate_bonus = 0;
            if (edge_dist == 0)
                corner_mate_bonus = 200;

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
                {0, 0},   /* dark: a1 */
                {7, 7},   /* dark: h8 */
            };
            int alt_target_corners[2][2] = {
                {0, 7},   /* light: a8 */
                {7, 0},   /* light: h1 */
            };

            int *tc1, *tc2;
            if (bishop_color == 0) {
                tc1 = target_corners[0]; tc2 = target_corners[1];
            } else {
                tc1 = alt_target_corners[0]; tc2 = alt_target_corners[1];
            }

            int dist1 = (b_kf > tc1[0] ? b_kf - tc1[0] : tc1[0] - b_kf)
                      + (b_kr > tc1[1] ? b_kr - tc1[1] : tc1[1] - b_kr);
            int dist2 = (b_kf > tc2[0] ? b_kf - tc2[0] : tc2[0] - b_kf)
                      + (b_kr > tc2[1] ? b_kr - tc2[1] : tc2[1] - b_kr);
            int corner_dist = (dist1 < dist2) ? dist1 : dist2;

            /* Reward pushing enemy king toward correct corner */
            int corner_bonus = (6 - corner_dist) * 100;
            /* Keep our king close to enemy king */
            int file_dist = (w_kf > b_kf) ? (w_kf - b_kf) : (b_kf - w_kf);
            int rank_dist = (w_kr > b_kr) ? (w_kr - b_kr) : (b_kr - w_kr);
            int chebyshev = (file_dist > rank_dist) ? file_dist : rank_dist;
            int proximity_bonus = (7 - chebyshev) * 60;
            /* Big bonus when enemy king is actually in correct corner */
            int in_correct_corner = 0;
            if (corner_dist == 0)
                in_correct_corner = 300;

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

            int corner_bonus = (3 - edge_dist) * MOPUP_KING_EDGE_WEIGHT;
            int proximity_bonus = (7 - chebyshev) * MOPUP_KING_PROX_WEIGHT;
            int opposition_bonus = 0;
            if (chebyshev == 2 && manhattan % 2 == 0)
                opposition_bonus = MOPUP_OPPOSITION_WEIGHT;

            int rook_cutoff_bonus = 0;
            if (is_krk_black)
            {
                int rook_sq = lsb_index(b->pieces[BLACK][ROOK]);
                int r_f = file_of(rook_sq), r_r = rank_of(rook_sq);
                if (r_f == w_kf || r_r == w_kr)
                    rook_cutoff_bonus = 60;
                int r_dist_f = (r_f > w_kf) ? (r_f - w_kf) : (w_kf - r_f);
                int r_dist_r = (r_r > w_kr) ? (r_r - w_kr) : (w_kr - r_r);
                if (r_dist_f > 3 && r_dist_r > 3)
                    rook_cutoff_bonus -= 40;
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

            int corner_bonus = (3 - edge_dist) * 150;
            int proximity_bonus = (7 - chebyshev) * 80;
            int queen_sq = lsb_index(b->pieces[BLACK][QUEEN]);
            int q_dist_f = (file_of(queen_sq) > w_kf) ? (file_of(queen_sq) - w_kf) : (w_kf - file_of(queen_sq));
            int q_dist_r = (rank_of(queen_sq) > w_kr) ? (rank_of(queen_sq) - w_kr) : (w_kr - rank_of(queen_sq));
            int q_chebyshev = (q_dist_f > q_dist_r) ? q_dist_f : q_dist_r;
            int queen_prox_bonus = (7 - q_chebyshev) * 50;
            int stalemate_avoid = 0;
            if (edge_dist == 0 && chebyshev == 1)
                stalemate_avoid = -100;
            int corner_mate_bonus = 0;
            if (edge_dist == 0)
                corner_mate_bonus = 200;

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

            int target_corners[2][2] = { {0, 0}, {7, 7} };
            int alt_target_corners[2][2] = { {0, 7}, {7, 0} };

            int *tc1, *tc2;
            if (bishop_color == 0) {
                tc1 = target_corners[0]; tc2 = target_corners[1];
            } else {
                tc1 = alt_target_corners[0]; tc2 = alt_target_corners[1];
            }

            int dist1 = (w_kf > tc1[0] ? w_kf - tc1[0] : tc1[0] - w_kf)
                      + (w_kr > tc1[1] ? w_kr - tc1[1] : tc1[1] - w_kr);
            int dist2 = (w_kf > tc2[0] ? w_kf - tc2[0] : tc2[0] - w_kf)
                      + (w_kr > tc2[1] ? w_kr - tc2[1] : tc2[1] - w_kr);
            int corner_dist = (dist1 < dist2) ? dist1 : dist2;

            int corner_bonus = (6 - corner_dist) * 100;
            int file_dist = (w_kf > b_kf) ? (w_kf - b_kf) : (b_kf - w_kf);
            int rank_dist = (w_kr > b_kr) ? (w_kr - b_kr) : (b_kr - w_kr);
            int chebyshev = (file_dist > rank_dist) ? file_dist : rank_dist;
            int proximity_bonus = (7 - chebyshev) * 60;
            int in_correct_corner = 0;
            if (corner_dist == 0)
                in_correct_corner = 300;

            score -= corner_bonus + proximity_bonus + in_correct_corner;
        }
        /* Extended mop-up: winning side has Q or R with pawns vs bare king or king+pawns */
        else if (total_pawns > 0 && (w_queens + b_queens + w_rooks + b_rooks) > 0)
        {
            int w_material = w_queens * 900 + w_rooks * 480 + w_bishops * 340 + w_knights * 320;
            int b_material = b_queens * 900 + b_rooks * 480 + b_bishops * 340 + b_knights * 320;
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
                int corner_bonus = (3 - edge_dist) * 80;
                int proximity_bonus = (7 - chebyshev) * 40;
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
                int corner_bonus = (3 - edge_dist) * 80;
                int proximity_bonus = (7 - chebyshev) * 40;
                score -= corner_bonus + proximity_bonus;
            }
        }
    }

    {
        int w_bishops = count_bits(b->pieces[WHITE][BISHOP]);
        int b_bishops = count_bits(b->pieces[BLACK][BISHOP]);
        int w_knights = count_bits(b->pieces[WHITE][KNIGHT]);
        int b_knights = count_bits(b->pieces[BLACK][KNIGHT]);
        int w_rooks = count_bits(b->pieces[WHITE][ROOK]);
        int b_rooks = count_bits(b->pieces[BLACK][ROOK]);
        int w_queens = count_bits(b->pieces[WHITE][QUEEN]);
        int b_queens = count_bits(b->pieces[BLACK][QUEEN]);
        int w_pawns = count_bits(b->pieces[WHITE][PAWN]);
        int b_pawns = count_bits(b->pieces[BLACK][PAWN]);

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
                int draw_factor = 8;
                if (w_pawns > 0 || b_pawns > 0)
                    draw_factor = 12;
                score = score * draw_factor / 16;
            }
        }
    }

    assert(score > -MATE_SCORE && score < MATE_SCORE && "Evaluation score out of valid range");

    b->eval_score = score;
    return score;
}