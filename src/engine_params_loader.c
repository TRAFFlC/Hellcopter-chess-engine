/* engine_params_loader.c — JSON 解析器与参数加载（从 engine_core.c 拆分） */
#include <stdio.h>
#include <stdlib.h>
#include <stddef.h>
#include <ctype.h>
#include <string.h>
#include "engine_params.h"
#include "engine_core.h"
/* ============================================================================
 * JSON PARSING HELPERS
 * ============================================================================
 * Simple JSON parser for loading engine parameters from configuration files.
 * Supports basic JSON types: objects, arrays, strings, numbers, booleans.
 */

/* Skip whitespace in JSON string */
static const char *skip_whitespace(const char *json)
{
    while (*json && isspace((unsigned char)*json))
    {
        json++;
    }
    return json;
}

/* Parse a JSON number */
static const char *parse_json_number(const char *json, int *out_value)
{
    char *end;
    long value = strtol(json, &end, 10);
    if (end == json)
    {
        return NULL; /* Parse error */
    }
    *out_value = (int)value;
    return end;
}

/* Parse a JSON number as double (for LMR_BASE/LMR_DIVISOR etc.) */
static const char *parse_json_double(const char *json, double *out_value)
{
    char *end;
    double value = strtod(json, &end);
    if (end == json)
    {
        return NULL; /* Parse error */
    }
    *out_value = value;
    return end;
}

/* Parse a JSON boolean */
static const char *parse_json_boolean(const char *json, int *out_value)
{
    if (strncmp(json, "true", 4) == 0)
    {
        *out_value = 1;
        return json + 4;
    }
    else if (strncmp(json, "false", 5) == 0)
    {
        *out_value = 0;
        return json + 5;
    }
    return NULL; /* Parse error */
}

/* Parse a JSON string (returns pointer to start of string content and length) */
static const char *parse_json_string(const char *json, const char **out_start, int *out_length)
{
    if (*json != '"')
    {
        return NULL;
    }
    json++; /* Skip opening quote */

    const char *start = json;
    int length = 0;

    while (*json && *json != '"')
    {
        if (*json == '\\')
        {
            json++; /* Skip escape character */
            if (*json)
                json++;
        }
        else
        {
            json++;
        }
        length++;
    }

    if (*json != '"')
    {
        return NULL; /* Missing closing quote */
    }

    *out_start = start;
    *out_length = length;
    return json + 1; /* Skip closing quote */
}

/* Find a key in JSON object and return pointer to its value */
static const char *find_json_key(const char *json, const char *key)
{
    json = skip_whitespace(json);

    if (*json != '{')
    {
        return NULL;
    }
    json++;

    while (1)
    {
        json = skip_whitespace(json);

        if (*json == '}')
        {
            return NULL; /* Key not found */
        }

        /* Parse key */
        const char *key_start;
        int key_length;
        json = parse_json_string(json, &key_start, &key_length);
        if (!json)
        {
            return NULL;
        }

        json = skip_whitespace(json);
        if (*json != ':')
        {
            return NULL;
        }
        json++;
        json = skip_whitespace(json);

        /* Check if this is the key we're looking for */
        if (strlen(key) == (size_t)key_length && strncmp(key_start, key, key_length) == 0)
        {
            return json; /* Found it! */
        }

        /* Skip the value */
        int depth = 0;
        int in_string = 0;
        while (*json)
        {
            if (*json == '"' && (json == key_start || *(json - 1) != '\\' || (*(json - 1) == '\\' && *(json - 2) == '\\')))
            {
                in_string = !in_string;
            }
            else if (!in_string)
            {
                if (*json == '{' || *json == '[')
                {
                    depth++;
                }
                else if (*json == '}' || *json == ']')
                {
                    if (depth == 0)
                    {
                        break;
                    }
                    depth--;
                }
                else if (*json == ',' && depth == 0)
                {
                    json++;
                    break;
                }
            }
            json++;
        }
    }
}

/* Parse a JSON array of integers */
static const char *parse_json_int_array(const char *json, int *out_array, int max_count, int *out_count)
{
    json = skip_whitespace(json);

    if (*json != '[')
    {
        return NULL;
    }
    json++;

    int count = 0;
    while (count < max_count)
    {
        json = skip_whitespace(json);

        if (*json == ']')
        {
            *out_count = count;
            return json + 1;
        }

        if (count > 0)
        {
            if (*json != ',')
            {
                return NULL;
            }
            json++;
            json = skip_whitespace(json);
        }

        int value;
        json = parse_json_number(json, &value);
        if (!json)
        {
            return NULL;
        }

        out_array[count++] = value;
    }

    /* Skip remaining elements if array is longer than max_count */
    json = skip_whitespace(json);
    while (*json && *json != ']')
    {
        json++;
    }

    if (*json == ']')
    {
        *out_count = count;
        return json + 1;
    }

    return NULL;
}

/* ============================================================================
 * PARAMETER LOADING FUNCTION
 * ============================================================================ */

/* Initialize runtime params with compile-time defaults from engine_params.h.
 * Called when no config file is available, ensuring the engine always has
 * valid parameters (especially qs_max_depth_mg/eg which must be > 0). */
static void init_runtime_params_defaults(void)
{
    g_runtime_params.piece_values[0] = 0;
    g_runtime_params.piece_values[1] = PAWN_VALUE;
    g_runtime_params.piece_values[2] = KNIGHT_VALUE;
    g_runtime_params.piece_values[3] = BISHOP_VALUE;
    g_runtime_params.piece_values[4] = ROOK_VALUE;
    g_runtime_params.piece_values[5] = QUEEN_VALUE;
    g_runtime_params.piece_values[6] = KING_VALUE;

    memcpy(g_runtime_params.mg_pst[0], mg_pawn, 64 * sizeof(int));
    memcpy(g_runtime_params.eg_pst[0], eg_pawn, 64 * sizeof(int));
    memcpy(g_runtime_params.mg_pst[1], mg_knight, 64 * sizeof(int));
    memcpy(g_runtime_params.eg_pst[1], eg_knight, 64 * sizeof(int));
    memcpy(g_runtime_params.mg_pst[2], mg_bishop, 64 * sizeof(int));
    memcpy(g_runtime_params.eg_pst[2], eg_bishop, 64 * sizeof(int));
    memcpy(g_runtime_params.mg_pst[3], mg_rook, 64 * sizeof(int));
    memcpy(g_runtime_params.eg_pst[3], eg_rook, 64 * sizeof(int));
    memcpy(g_runtime_params.mg_pst[4], mg_queen, 64 * sizeof(int));
    memcpy(g_runtime_params.eg_pst[4], eg_queen, 64 * sizeof(int));
    memcpy(g_runtime_params.mg_pst[5], mg_king, 64 * sizeof(int));
    memcpy(g_runtime_params.eg_pst[5], eg_king, 64 * sizeof(int));

    g_runtime_params.bishop_pair_bonus = BISHOP_PAIR_BONUS;
    g_runtime_params.doubled_pawn_penalty = DOUBLED_PAWN_PENALTY;
    g_runtime_params.isolated_pawn_penalty = ISOLATED_PAWN_PENALTY;
    memcpy(g_runtime_params.passed_pawn_bonus, passed_pawn_bonus, 8 * sizeof(int));
    g_runtime_params.open_file_bonus = OPEN_FILE_BONUS;
    g_runtime_params.semi_open_file_bonus = SEMI_OPEN_FILE_BONUS;
    g_runtime_params.null_move_reduction = NULL_MOVE_REDUCTION;
    g_runtime_params.null_move_min_depth = NULL_MOVE_MIN_DEPTH;
    g_runtime_params.lmr_enabled = LMR_ENABLED;
    g_runtime_params.lmr_min_depth = LMR_MIN_DEPTH;
    g_runtime_params.lmr_move_threshold = LMR_MOVE_THRESHOLD;
    g_runtime_params.futility_enabled = FUTILITY_ENABLED;
    g_runtime_params.futility_margin_base = FUTILITY_MARGIN_BASE;
    g_runtime_params.razoring_enabled = RAZORING_ENABLED;
    g_runtime_params.razoring_margin = RAZORING_MARGIN;
    g_runtime_params.rfp_enabled = 1;
    g_runtime_params.nmp_enabled = 1;
    g_runtime_params.lmp_enabled = 1;
    g_runtime_params.see_prune_enabled = 1;
    g_runtime_params.history_prune_enabled = 1;
    g_runtime_params.singular_ext_enabled = 1;
    g_runtime_params.iid_enabled = 1;
    g_runtime_params.probcut_enabled = 1;   /* PROBCUT_ENABLED */
    g_runtime_params.probcut_min_depth = 5;  /* PROBCUT_MIN_DEPTH */
    g_runtime_params.probcut_margin = 200;   /* PROBCUT_MARGIN */
    g_runtime_params.probcut_reduction = 4;  /* PROBCUT_REDUCTION */
    g_runtime_params.history_table_enabled = 1;
    g_runtime_params.killers_enabled = 1;
    g_runtime_params.countermove_followup_enabled = 1;
    g_runtime_params.delta_prune_enabled = 1;
    g_runtime_params.eval_king_safety_enabled = 1;
    g_runtime_params.eval_endgame_enabled = 0;
    g_runtime_params.mate_score = MATE_SCORE;
    g_runtime_params.delta = DELTA;
    g_runtime_params.endgame_phase_threshold = ENDGAME_PHASE_THRESHOLD;
    g_runtime_params.endgame_depth_bonus = ENDGAME_DEPTH_BONUS;
    g_runtime_params.endgame_nmr_bonus = ENDGAME_NMR_BONUS;
    g_runtime_params.king_activity_weight = KING_ACTIVITY_WEIGHT;
    g_runtime_params.qs_max_depth_mg = QS_MAX_DEPTH_MG;
    g_runtime_params.qs_max_depth_eg = QS_MAX_DEPTH_EG;
    g_runtime_params.threading_enabled = THREADING_ENABLED;
    g_runtime_params.num_threads = NUM_THREADS;

    /* Extended eval weights */
    g_runtime_params.pawn_chain_bonus = PAWN_CHAIN_BONUS;
    g_runtime_params.backward_pawn_penalty = BACKWARD_PAWN_PENALTY;
    g_runtime_params.center_pawn_mg_bonus = CENTER_PAWN_MG_BONUS;
    g_runtime_params.connected_passer_bonus = CONNECTED_PASSER_BONUS;
    g_runtime_params.rook_on_7th_mg_bonus = ROOK_ON_7TH_MG_BONUS;
    g_runtime_params.rook_on_7th_eg_bonus = ROOK_ON_7TH_EG_BONUS;
    g_runtime_params.castle_short_bonus = CASTLE_SHORT_BONUS;
    g_runtime_params.castle_long_bonus = CASTLE_LONG_BONUS;
    g_runtime_params.tempo_mg = TEMPO_MG;
    g_runtime_params.tempo_eg = TEMPO_EG;
    g_runtime_params.knight_edge_penalty = KNIGHT_EDGE_PENALTY;
    g_runtime_params.knight_initial_block_penalty = KNIGHT_INITIAL_BLOCK_PENALTY;
    g_runtime_params.isolated_open_file_mul_num = ISOLATED_OPEN_FILE_MUL_NUM;
    g_runtime_params.isolated_open_file_mul_den = ISOLATED_OPEN_FILE_MUL_DEN;
    g_runtime_params.simplify_threshold = SIMPLIFY_THRESHOLD;
    g_runtime_params.simplify_bonus = SIMPLIFY_BONUS;
    g_runtime_params.mopup_material_threshold = MOPUP_MATERIAL_THRESHOLD;
    g_runtime_params.mopup_edge_weight = MOPUP_EDGE_WEIGHT;
    g_runtime_params.mopup_proximity_weight = MOPUP_PROXIMITY_WEIGHT;
    g_runtime_params.mopup_opposition_weight = MOPUP_OPPOSITION_WEIGHT;
    g_runtime_params.opening_knight_not_developed_penalty = OPENING_KNIGHT_NOT_DEVELOPED_PENALTY;
    g_runtime_params.opening_bishop_not_developed_penalty = OPENING_BISHOP_NOT_DEVELOPED_PENALTY;
    g_runtime_params.opening_early_queen_base = OPENING_EARLY_QUEEN_BASE;
    g_runtime_params.hanging_queen_penalty = HANGING_QUEEN_PENALTY;
    g_runtime_params.hanging_rook_penalty = HANGING_ROOK_PENALTY;
    g_runtime_params.hanging_minor_penalty = HANGING_MINOR_PENALTY;
    g_runtime_params.in_check_penalty = IN_CHECK_PENALTY;
    g_runtime_params.passed_pawn_supported_bonus = PASSED_PAWN_SUPPORTED_BONUS;
    g_runtime_params.passed_pawn_blocked_base = PASSED_PAWN_BLOCKED_BASE;
    g_runtime_params.passed_pawn_clear_path_base = PASSED_PAWN_CLEAR_PATH_BASE;
    g_runtime_params.passed_pawn_king_dist_base = PASSED_PAWN_KING_DIST_BASE;
    g_runtime_params.center_control_piece_bonus = CENTER_CONTROL_PIECE_BONUS;
    g_runtime_params.center_control_pawn_bonus = CENTER_CONTROL_PAWN_BONUS;
    g_runtime_params.bishop_mobility_bonus = BISHOP_MOBILITY_BONUS;
    g_runtime_params.bishop_bad_penalty = BISHOP_BAD_PENALTY;
    g_runtime_params.pawn_chain_lateral_bonus = PAWN_CHAIN_LATERAL_BONUS;
    g_runtime_params.center_pawn_pair_bonus = CENTER_PAWN_PAIR_BONUS;
    g_runtime_params.imbalance_mg_base = IMBALANCE_MG_BASE;
    g_runtime_params.imbalance_mg_scale = IMBALANCE_MG_SCALE;
    g_runtime_params.imbalance_eg_scale = IMBALANCE_EG_SCALE;
    g_runtime_params.no_minor_vs_two_minor_penalty = NO_MINOR_VS_TWO_MINOR_PENALTY;
    g_runtime_params.opposite_bishop_draw_factor_no_pawn = OPPOSITE_BISHOP_DRAW_FACTOR_NO_PAWN;
    g_runtime_params.opposite_bishop_draw_factor_pawn = OPPOSITE_BISHOP_DRAW_FACTOR_PAWN;

    /* King Danger parameters */
    g_runtime_params.king_danger_cap = KING_DANGER_CAP;
    g_runtime_params.knight_attack_base = KNIGHT_ATTACK_BASE;
    g_runtime_params.bishop_attack_base = BISHOP_ATTACK_BASE;
    g_runtime_params.rook_attack_base = ROOK_ATTACK_BASE;
    g_runtime_params.queen_attack_base = QUEEN_ATTACK_BASE;
    g_runtime_params.knight_attack_per_sq = KNIGHT_ATTACK_PER_SQ;
    g_runtime_params.bishop_attack_per_sq = BISHOP_ATTACK_PER_SQ;
    g_runtime_params.rook_attack_per_sq = ROOK_ATTACK_PER_SQ;
    g_runtime_params.queen_attack_per_sq = QUEEN_ATTACK_PER_SQ;
    g_runtime_params.pawn_shield_rank2_penalty = PAWN_SHIELD_RANK2_PENALTY;
    g_runtime_params.pawn_shield_no_pawn_penalty = PAWN_SHIELD_NO_PAWN_PENALTY;
    g_runtime_params.open_file_king_zone_penalty = OPEN_FILE_KING_ZONE_PENALTY;
    g_runtime_params.semi_open_file_king_zone_penalty = SEMI_OPEN_FILE_KING_ZONE_PENALTY;
    g_runtime_params.attacker_count_bonus = ATTACKER_COUNT_BONUS;
    g_runtime_params.king_danger_eg_scale_base = KING_DANGER_EG_SCALE_BASE;
    g_runtime_params.king_danger_eg_scale_phase = KING_DANGER_EG_SCALE_PHASE;
    memcpy(g_runtime_params.king_danger_table, king_danger_table, 128 * sizeof(int));

    /* Mobility tables */
    memcpy(g_runtime_params.knight_mob_mg, knight_mob_mg, 9 * sizeof(int));
    memcpy(g_runtime_params.knight_mob_eg, knight_mob_eg, 9 * sizeof(int));
    memcpy(g_runtime_params.bishop_mob_mg, bishop_mob_mg, 14 * sizeof(int));
    memcpy(g_runtime_params.bishop_mob_eg, bishop_mob_eg, 14 * sizeof(int));
    memcpy(g_runtime_params.rook_mob_mg, rook_mob_mg, 15 * sizeof(int));
    memcpy(g_runtime_params.rook_mob_eg, rook_mob_eg, 15 * sizeof(int));
    memcpy(g_runtime_params.queen_mob_mg, queen_mob_mg, 28 * sizeof(int));
    memcpy(g_runtime_params.queen_mob_eg, queen_mob_eg, 28 * sizeof(int));

    /* Queen Centralization */
    g_runtime_params.queen_centralization_mg = QUEEN_CENTRALIZATION_MG;
    g_runtime_params.queen_centralization_eg = QUEEN_CENTRALIZATION_EG;

    /* Passed Pawn Detail */
    g_runtime_params.passed_pawn_eg_weight = PASSED_PAWN_EG_WEIGHT;
    g_runtime_params.passed_pawn_eg_phase_denom = PASSED_PAWN_EG_PHASE_DENOM;
    g_runtime_params.promo_threat_rank6_base = PROMO_THREAT_RANK6_BASE;
    g_runtime_params.promo_threat_rank5_base = PROMO_THREAT_RANK5_BASE;
    g_runtime_params.promo_threat_eg_divisor = PROMO_THREAT_EG_DIVISOR;
    g_runtime_params.passed_pawn_blocked_rank_scale = PASSED_PAWN_BLOCKED_RANK_SCALE;
    g_runtime_params.passed_pawn_blocked_rank_denom = PASSED_PAWN_BLOCKED_RANK_DENOM;
    g_runtime_params.passed_pawn_clear_path_rank_scale = PASSED_PAWN_CLEAR_PATH_RANK_SCALE;
    g_runtime_params.passed_pawn_king_dist_scale = PASSED_PAWN_KING_DIST_SCALE;

    /* Center Control Extended */
    g_runtime_params.center_control_extended_bonus = CENTER_CONTROL_EXTENDED_BONUS;
    g_runtime_params.center_control_pawn_extended_bonus = CENTER_CONTROL_PAWN_EXTENDED_BONUS;

    /* Back Rank Threats */
    g_runtime_params.back_rank_mate_penalty = BACK_RANK_MATE_PENALTY;
    g_runtime_params.back_rank_triple_penalty = BACK_RANK_TRIPLE_PENALTY;

    /* Knight Outpost */
    g_runtime_params.outpost_mg_base = OUTPOST_MG_BASE;
    g_runtime_params.outpost_mg_rank_scale = OUTPOST_MG_RANK_SCALE;
    g_runtime_params.outpost_eg_base = OUTPOST_EG_BASE;
    g_runtime_params.outpost_eg_rank_scale = OUTPOST_EG_RANK_SCALE;

    /* Attacked by Pawn/Knight */
    g_runtime_params.queen_attacked_by_pawn_penalty = QUEEN_ATTACKED_BY_PAWN_PENALTY;
    g_runtime_params.rook_attacked_by_pawn_penalty = ROOK_ATTACKED_BY_PAWN_PENALTY;
    g_runtime_params.minor_attacked_by_pawn_penalty = MINOR_ATTACKED_BY_PAWN_PENALTY;
    g_runtime_params.queen_attacked_by_pawn_extra = QUEEN_ATTACKED_BY_PAWN_EXTRA;
    g_runtime_params.rook_attacked_by_pawn_extra = ROOK_ATTACKED_BY_PAWN_EXTRA;
    g_runtime_params.queen_attacked_by_knight_penalty = QUEEN_ATTACKED_BY_KNIGHT_PENALTY;
    g_runtime_params.rook_attacked_by_knight_penalty = ROOK_ATTACKED_BY_KNIGHT_PENALTY;
    g_runtime_params.minor_attacked_by_knight_penalty = MINOR_ATTACKED_BY_KNIGHT_PENALTY;
    g_runtime_params.piece_defended_by_pawn_bonus = PIECE_DEFENDED_BY_PAWN_BONUS;

    /* Fork/Threat */
    g_runtime_params.knight_fork_queen_rook_penalty = KNIGHT_FORK_QUEEN_ROOK_PENALTY;
    g_runtime_params.knight_fork_king_penalty = KNIGHT_FORK_KING_PENALTY;
    g_runtime_params.queen_attacked_by_minor_undefended = QUEEN_ATTACKED_BY_MINOR_UNDEFENDED;
    g_runtime_params.queen_attacked_by_minor_defended = QUEEN_ATTACKED_BY_MINOR_DEFENDED;
    g_runtime_params.rook_attacked_by_minor_undefended = ROOK_ATTACKED_BY_MINOR_UNDEFENDED;
    g_runtime_params.rook_attacked_by_minor_defended = ROOK_ATTACKED_BY_MINOR_DEFENDED;
    g_runtime_params.minor_attacked_by_minor_undefended = MINOR_ATTACKED_BY_MINOR_UNDEFENDED;
    g_runtime_params.minor_attacked_by_minor_defended = MINOR_ATTACKED_BY_MINOR_DEFENDED;
    g_runtime_params.piece_attacked_by_rook_undefended = PIECE_ATTACKED_BY_ROOK_UNDEFENDED;
    g_runtime_params.piece_attacked_by_rook_defended = PIECE_ATTACKED_BY_ROOK_DEFENDED;
    g_runtime_params.piece_attacked_by_bishop_undefended = PIECE_ATTACKED_BY_BISHOP_UNDEFENDED;
    g_runtime_params.piece_attacked_by_bishop_defended = PIECE_ATTACKED_BY_BISHOP_DEFENDED;

    /* Opening Development Extended */
    g_runtime_params.opening_early_queen_scale = OPENING_EARLY_QUEEN_SCALE;
    g_runtime_params.opening_early_queen_min = OPENING_EARLY_QUEEN_MIN;
    g_runtime_params.opening_undeveloped_penalty_5 = OPENING_UNDEVELOPED_PENALTY_5;
    g_runtime_params.opening_undeveloped_penalty_8 = OPENING_UNDEVELOPED_PENALTY_8;
    g_runtime_params.opening_king_not_castled_penalty = OPENING_KING_NOT_CASTLED_PENALTY;
    g_runtime_params.opening_early_queen_advance_base = OPENING_EARLY_QUEEN_ADVANCE_BASE;
    g_runtime_params.opening_early_queen_advance_scale = OPENING_EARLY_QUEEN_ADVANCE_SCALE;
    g_runtime_params.opening_early_queen_advance_min = OPENING_EARLY_QUEEN_ADVANCE_MIN;
    g_runtime_params.opening_early_rook_advance_penalty = OPENING_EARLY_ROOK_ADVANCE_PENALTY;
    g_runtime_params.opening_center_pawn_control_bonus = OPENING_CENTER_PAWN_CONTROL_BONUS;
    g_runtime_params.opening_no_center_pawn_penalty = OPENING_NO_CENTER_PAWN_PENALTY;

    /* Fifty Move Rule */
    g_runtime_params.fifty_move_urgency_divisor = FIFTY_MOVE_URGENCY_DIVISOR;

    /* Mopup Extended */
    g_runtime_params.mopup_winning_king_activity_weight = MOPUP_WINNING_KING_ACTIVITY_WEIGHT;
    g_runtime_params.mopup_losing_king_activity_weight = MOPUP_LOSING_KING_ACTIVITY_WEIGHT;
    g_runtime_params.mopup_king_activity_early_phase = MOPUP_KING_ACTIVITY_EARLY_PHASE;
    g_runtime_params.mopup_king_activity_early_weight = MOPUP_KING_ACTIVITY_EARLY_WEIGHT;
    g_runtime_params.mopup_generic_edge_scale = MOPUP_GENERIC_EDGE_SCALE;
    g_runtime_params.mopup_generic_proximity_scale = MOPUP_GENERIC_PROXIMITY_SCALE;

    /* Anti-Simplify */
    g_runtime_params.anti_simplify_per_piece_scale = ANTI_SIMPLIFY_PER_PIECE_SCALE;
    g_runtime_params.anti_simplify_piece_threshold = ANTI_SIMPLIFY_PIECE_THRESHOLD;

    /* Specific Endgames KRK/KQKR/KBNK */
    g_runtime_params.krk_rook_cutoff_bonus = KRK_ROOK_CUTOFF_BONUS;
    g_runtime_params.krk_rook_far_penalty = KRK_ROOK_FAR_PENALTY;
    g_runtime_params.kqkr_corner_scale = KQKR_CORNER_SCALE;
    g_runtime_params.kqkr_proximity_scale = KQKR_PROXIMITY_SCALE;
    g_runtime_params.kqkr_queen_proximity_scale = KQKR_QUEEN_PROXIMITY_SCALE;
    g_runtime_params.kqkr_stalemate_avoid_penalty = KQKR_STALEMATE_AVOID_PENALTY;
    g_runtime_params.kqkr_corner_mate_bonus = KQKR_CORNER_MATE_BONUS;
    g_runtime_params.kbnk_corner_scale = KBNK_CORNER_SCALE;
    g_runtime_params.kbnk_proximity_scale = KBNK_PROXIMITY_SCALE;
    g_runtime_params.kbnk_correct_corner_bonus = KBNK_CORRECT_CORNER_BONUS;

    /* Extended Mopup */
    g_runtime_params.extended_mopup_edge_scale = EXTENDED_MOPUP_EDGE_SCALE;
    g_runtime_params.extended_mopup_proximity_scale = EXTENDED_MOPUP_PROXIMITY_SCALE;

    /* Opposite Bishop Draw */
    g_runtime_params.opposite_bishop_draw_divisor = OPPOSITE_BISHOP_DRAW_DIVISOR;

    /* Rook 7th Extended */
    g_runtime_params.rook_on_7th_double_bonus = ROOK_ON_7TH_DOUBLE_BONUS;
    g_runtime_params.rook_on_7th_king_rank8_bonus = ROOK_ON_7TH_KING_RANK8_BONUS;
    g_runtime_params.rook_on_7th_double_king_rank8_bonus = ROOK_ON_7TH_DOUBLE_KING_RANK8_BONUS;

    /* Rook Potential */
    g_runtime_params.rook_potential_open_file = ROOK_POTENTIAL_OPEN_FILE;
    g_runtime_params.rook_potential_semi_open = ROOK_POTENTIAL_SEMI_OPEN;

    /* NMP/LMR runtime-tunable parameters (P1 fix: make config actually used) */
    g_runtime_params.nmp_base_reduction = NMP_BASE_REDUCTION;
    g_runtime_params.nmp_depth_divisor = NMP_DEPTH_DIVISOR;
    g_runtime_params.lmr_base = LMR_BASE;
    g_runtime_params.lmr_divisor = LMR_DIVISOR;

    /* Regenerate lmr_table with the (default) runtime params */
    regenerate_lmr_table();

    g_runtime_params.loaded = 1; /* Defaults initialized, safe to use */
}

#ifdef _WIN32
__declspec(dllexport)
#endif
int
load_params_from_file(const char *filename)
{
    FILE *file = fopen(filename, "r");
    if (!file)
    {
        fprintf(stderr, "Error: Cannot open config file: %s\n", filename);
        return 0;
    }

    /* Read entire file into memory */
    fseek(file, 0, SEEK_END);
    long file_size = ftell(file);
    fseek(file, 0, SEEK_SET);

    if (file_size <= 0 || file_size > 10 * 1024 * 1024)
    { /* Max 10MB */
        fprintf(stderr, "Error: Invalid file size: %ld\n", file_size);
        fclose(file);
        return 0;
    }

    char *json = (char *)malloc(file_size + 1);
    if (!json)
    {
        fprintf(stderr, "Error: Memory allocation failed\n");
        fclose(file);
        return 0;
    }

    size_t bytes_read = fread(json, 1, file_size, file);
    json[bytes_read] = '\0';
    fclose(file);

    /* Parse JSON and load parameters */
    const char *params_obj = find_json_key(json, "parameters");
    if (!params_obj)
    {
        fprintf(stderr, "Error: 'parameters' key not found in config file\n");
        free(json);
        return 0;
    }

    /* Initialize runtime params with defaults from engine_params.h */
    init_runtime_params_defaults();

    /* Parse piece_values */
    const char *piece_values_obj = find_json_key(params_obj, "piece_values");
    if (piece_values_obj)
    {
        const char *val;
        int value;

        if ((val = find_json_key(piece_values_obj, "pawn")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.piece_values[1] = value;
            }
        }
        if ((val = find_json_key(piece_values_obj, "knight")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.piece_values[2] = value;
            }
        }
        if ((val = find_json_key(piece_values_obj, "bishop")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.piece_values[3] = value;
            }
        }
        if ((val = find_json_key(piece_values_obj, "rook")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.piece_values[4] = value;
            }
        }
        if ((val = find_json_key(piece_values_obj, "queen")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.piece_values[5] = value;
            }
        }
        if ((val = find_json_key(piece_values_obj, "king")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.piece_values[6] = value;
            }
        }
    }

    /* Parse PST tables */
    const char *pst_obj = find_json_key(params_obj, "pst");
    if (pst_obj)
    {
        const char *table;
        int count;

        if ((table = find_json_key(pst_obj, "mg_pawn")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.mg_pst[0], 64, &count);
        }
        if ((table = find_json_key(pst_obj, "eg_pawn")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.eg_pst[0], 64, &count);
        }
        if ((table = find_json_key(pst_obj, "mg_knight")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.mg_pst[1], 64, &count);
        }
        if ((table = find_json_key(pst_obj, "eg_knight")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.eg_pst[1], 64, &count);
        }
        if ((table = find_json_key(pst_obj, "mg_bishop")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.mg_pst[2], 64, &count);
        }
        if ((table = find_json_key(pst_obj, "eg_bishop")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.eg_pst[2], 64, &count);
        }
        if ((table = find_json_key(pst_obj, "mg_rook")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.mg_pst[3], 64, &count);
        }
        if ((table = find_json_key(pst_obj, "eg_rook")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.eg_pst[3], 64, &count);
        }
        if ((table = find_json_key(pst_obj, "mg_queen")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.mg_pst[4], 64, &count);
        }
        if ((table = find_json_key(pst_obj, "eg_queen")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.eg_pst[4], 64, &count);
        }
        if ((table = find_json_key(pst_obj, "mg_king")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.mg_pst[5], 64, &count);
        }
        if ((table = find_json_key(pst_obj, "eg_king")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.eg_pst[5], 64, &count);
        }
    }

    /* Parse eval_weights */
    const char *eval_weights_obj = find_json_key(params_obj, "eval_weights");
    if (eval_weights_obj)
    {
        const char *val;
        int value, count;

        if ((val = find_json_key(eval_weights_obj, "bishop_pair_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.bishop_pair_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "doubled_pawn_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.doubled_pawn_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "isolated_pawn_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.isolated_pawn_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "passed_pawn_bonus")) != NULL)
        {
            parse_json_int_array(val, g_runtime_params.passed_pawn_bonus, 8, &count);
        }
        if ((val = find_json_key(eval_weights_obj, "open_file_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.open_file_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "semi_open_file_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.semi_open_file_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "pawn_chain_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.pawn_chain_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "backward_pawn_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.backward_pawn_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "center_pawn_mg_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.center_pawn_mg_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "connected_passer_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.connected_passer_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "rook_7th_mg_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.rook_on_7th_mg_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "rook_7th_eg_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.rook_on_7th_eg_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "castle_short_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.castle_short_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "castle_long_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.castle_long_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "tempo_mg")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.tempo_mg = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "tempo_eg")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.tempo_eg = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "knight_edge_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.knight_edge_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "knight_initial_block_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.knight_initial_block_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "isolated_open_file_multiplier_num")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.isolated_open_file_mul_num = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "isolated_open_file_multiplier_den")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.isolated_open_file_mul_den = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "simplify_threshold")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.simplify_threshold = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "simplify_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.simplify_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "mopup_material_threshold")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.mopup_material_threshold = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "mopup_edge_weight")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.mopup_edge_weight = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "mopup_proximity_weight")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.mopup_proximity_weight = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "mopup_opposition_weight")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.mopup_opposition_weight = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "opening_knight_not_developed_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.opening_knight_not_developed_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "opening_bishop_not_developed_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.opening_bishop_not_developed_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "opening_early_queen_base")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.opening_early_queen_base = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "hanging_queen_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.hanging_queen_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "hanging_rook_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.hanging_rook_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "hanging_minor_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.hanging_minor_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "in_check_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.in_check_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "passed_pawn_supported_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.passed_pawn_supported_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "passed_pawn_blocked_base")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.passed_pawn_blocked_base = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "passed_pawn_clear_path_base")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.passed_pawn_clear_path_base = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "passed_pawn_king_dist_base")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.passed_pawn_king_dist_base = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "center_control_piece_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.center_control_piece_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "center_control_pawn_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.center_control_pawn_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "bishop_mobility_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.bishop_mobility_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "bishop_bad_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.bishop_bad_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "pawn_chain_lateral_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.pawn_chain_lateral_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "center_pawn_pair_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.center_pawn_pair_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "imbalance_mg_base")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.imbalance_mg_base = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "imbalance_mg_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.imbalance_mg_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "imbalance_eg_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.imbalance_eg_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "no_minor_vs_two_minor_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.no_minor_vs_two_minor_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "opposite_bishop_draw_factor_no_pawn")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.opposite_bishop_draw_factor_no_pawn = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "opposite_bishop_draw_factor_pawn")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.opposite_bishop_draw_factor_pawn = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "passed_pawn_eg_weight")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.passed_pawn_eg_weight = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "passed_pawn_eg_phase_denom")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.passed_pawn_eg_phase_denom = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "promo_threat_rank6_base")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.promo_threat_rank6_base = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "promo_threat_rank5_base")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.promo_threat_rank5_base = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "promo_threat_eg_divisor")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.promo_threat_eg_divisor = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "passed_pawn_blocked_rank_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.passed_pawn_blocked_rank_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "passed_pawn_blocked_rank_denom")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.passed_pawn_blocked_rank_denom = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "passed_pawn_clear_path_rank_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.passed_pawn_clear_path_rank_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "passed_pawn_king_dist_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.passed_pawn_king_dist_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "center_control_extended_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.center_control_extended_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "center_control_pawn_extended_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.center_control_pawn_extended_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "back_rank_mate_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.back_rank_mate_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "back_rank_triple_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.back_rank_triple_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "outpost_mg_base")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.outpost_mg_base = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "outpost_mg_rank_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.outpost_mg_rank_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "outpost_eg_base")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.outpost_eg_base = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "outpost_eg_rank_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.outpost_eg_rank_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "queen_attacked_by_pawn_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.queen_attacked_by_pawn_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "rook_attacked_by_pawn_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.rook_attacked_by_pawn_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "minor_attacked_by_pawn_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.minor_attacked_by_pawn_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "queen_attacked_by_pawn_extra")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.queen_attacked_by_pawn_extra = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "rook_attacked_by_pawn_extra")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.rook_attacked_by_pawn_extra = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "queen_attacked_by_knight_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.queen_attacked_by_knight_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "rook_attacked_by_knight_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.rook_attacked_by_knight_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "minor_attacked_by_knight_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.minor_attacked_by_knight_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "piece_defended_by_pawn_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.piece_defended_by_pawn_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "knight_fork_queen_rook_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.knight_fork_queen_rook_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "knight_fork_king_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.knight_fork_king_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "queen_attacked_by_minor_undefended")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.queen_attacked_by_minor_undefended = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "queen_attacked_by_minor_defended")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.queen_attacked_by_minor_defended = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "rook_attacked_by_minor_undefended")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.rook_attacked_by_minor_undefended = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "rook_attacked_by_minor_defended")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.rook_attacked_by_minor_defended = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "minor_attacked_by_minor_undefended")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.minor_attacked_by_minor_undefended = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "minor_attacked_by_minor_defended")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.minor_attacked_by_minor_defended = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "piece_attacked_by_rook_undefended")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.piece_attacked_by_rook_undefended = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "piece_attacked_by_rook_defended")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.piece_attacked_by_rook_defended = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "piece_attacked_by_bishop_undefended")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.piece_attacked_by_bishop_undefended = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "piece_attacked_by_bishop_defended")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.piece_attacked_by_bishop_defended = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "opening_early_queen_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.opening_early_queen_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "opening_early_queen_min")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.opening_early_queen_min = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "opening_undeveloped_penalty_5")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.opening_undeveloped_penalty_5 = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "opening_undeveloped_penalty_8")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.opening_undeveloped_penalty_8 = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "opening_king_not_castled_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.opening_king_not_castled_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "opening_early_queen_advance_base")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.opening_early_queen_advance_base = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "opening_early_queen_advance_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.opening_early_queen_advance_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "opening_early_queen_advance_min")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.opening_early_queen_advance_min = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "opening_early_rook_advance_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.opening_early_rook_advance_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "opening_center_pawn_control_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.opening_center_pawn_control_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "opening_no_center_pawn_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.opening_no_center_pawn_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "fifty_move_urgency_divisor")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.fifty_move_urgency_divisor = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "mopup_winning_king_activity_weight")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.mopup_winning_king_activity_weight = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "mopup_losing_king_activity_weight")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.mopup_losing_king_activity_weight = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "mopup_king_activity_early_phase_threshold")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.mopup_king_activity_early_phase = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "mopup_king_activity_early_weight")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.mopup_king_activity_early_weight = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "mopup_generic_edge_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.mopup_generic_edge_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "mopup_generic_proximity_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.mopup_generic_proximity_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "anti_simplify_per_piece_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.anti_simplify_per_piece_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "anti_simplify_piece_threshold")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.anti_simplify_piece_threshold = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "krk_rook_cutoff_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.krk_rook_cutoff_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "krk_rook_far_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.krk_rook_far_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "kqkr_corner_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.kqkr_corner_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "kqkr_proximity_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.kqkr_proximity_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "kqkr_queen_proximity_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.kqkr_queen_proximity_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "kqkr_stalemate_avoid_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.kqkr_stalemate_avoid_penalty = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "kqkr_corner_mate_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.kqkr_corner_mate_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "kbnk_corner_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.kbnk_corner_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "kbnk_proximity_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.kbnk_proximity_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "kbnk_correct_corner_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.kbnk_correct_corner_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "extended_mopup_edge_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.extended_mopup_edge_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "extended_mopup_proximity_scale")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.extended_mopup_proximity_scale = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "opposite_bishop_draw_divisor")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.opposite_bishop_draw_divisor = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "rook_7th_double_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.rook_on_7th_double_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "rook_7th_king_rank8_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.rook_on_7th_king_rank8_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "rook_7th_double_king_rank8_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.rook_on_7th_double_king_rank8_bonus = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "rook_potential_open_file")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.rook_potential_open_file = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "rook_potential_semi_open")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.rook_potential_semi_open = value;
            }
        }
    }

    /* Parse king_danger */
    const char *king_danger_obj = find_json_key(params_obj, "king_danger");
    if (king_danger_obj)
    {
        const char *val;
        int value, count;

        if ((val = find_json_key(king_danger_obj, "king_danger_cap")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.king_danger_cap = value;
            }
        }
        if ((val = find_json_key(king_danger_obj, "knight_attack_base")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.knight_attack_base = value;
            }
        }
        if ((val = find_json_key(king_danger_obj, "bishop_attack_base")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.bishop_attack_base = value;
            }
        }
        if ((val = find_json_key(king_danger_obj, "rook_attack_base")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.rook_attack_base = value;
            }
        }
        if ((val = find_json_key(king_danger_obj, "queen_attack_base")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.queen_attack_base = value;
            }
        }
        if ((val = find_json_key(king_danger_obj, "knight_attack_per_sq")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.knight_attack_per_sq = value;
            }
        }
        if ((val = find_json_key(king_danger_obj, "bishop_attack_per_sq")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.bishop_attack_per_sq = value;
            }
        }
        if ((val = find_json_key(king_danger_obj, "rook_attack_per_sq")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.rook_attack_per_sq = value;
            }
        }
        if ((val = find_json_key(king_danger_obj, "queen_attack_per_sq")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.queen_attack_per_sq = value;
            }
        }
        if ((val = find_json_key(king_danger_obj, "pawn_shield_rank2_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.pawn_shield_rank2_penalty = value;
            }
        }
        if ((val = find_json_key(king_danger_obj, "pawn_shield_no_pawn_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.pawn_shield_no_pawn_penalty = value;
            }
        }
        if ((val = find_json_key(king_danger_obj, "open_file_king_zone_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.open_file_king_zone_penalty = value;
            }
        }
        if ((val = find_json_key(king_danger_obj, "semi_open_file_king_zone_penalty")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.semi_open_file_king_zone_penalty = value;
            }
        }
        if ((val = find_json_key(king_danger_obj, "attacker_count_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.attacker_count_bonus = value;
            }
        }
        if ((val = find_json_key(king_danger_obj, "king_danger_eg_scale_base")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.king_danger_eg_scale_base = value;
            }
        }
        if ((val = find_json_key(king_danger_obj, "king_danger_eg_scale_phase")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.king_danger_eg_scale_phase = value;
            }
        }
        if ((val = find_json_key(king_danger_obj, "king_danger_table")) != NULL)
        {
            parse_json_int_array(val, g_runtime_params.king_danger_table, 128, &count);
        }
    }

    /* Parse mobility_tables */
    const char *mobility_obj = find_json_key(params_obj, "mobilityTables");
    if (mobility_obj)
    {
        const char *table;
        int count;

        if ((table = find_json_key(mobility_obj, "knight_mob_mg")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.knight_mob_mg, 9, &count);
        }
        if ((table = find_json_key(mobility_obj, "knight_mob_eg")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.knight_mob_eg, 9, &count);
        }
        if ((table = find_json_key(mobility_obj, "bishop_mob_mg")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.bishop_mob_mg, 14, &count);
        }
        if ((table = find_json_key(mobility_obj, "bishop_mob_eg")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.bishop_mob_eg, 14, &count);
        }
        if ((table = find_json_key(mobility_obj, "rook_mob_mg")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.rook_mob_mg, 15, &count);
        }
        if ((table = find_json_key(mobility_obj, "rook_mob_eg")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.rook_mob_eg, 15, &count);
        }
        if ((table = find_json_key(mobility_obj, "queen_mob_mg")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.queen_mob_mg, 28, &count);
        }
        if ((table = find_json_key(mobility_obj, "queen_mob_eg")) != NULL)
        {
            parse_json_int_array(table, g_runtime_params.queen_mob_eg, 28, &count);
        }
    }

    /* Parse queen centralization params from eval_weights */
    if (eval_weights_obj)
    {
        const char *val;
        int value;
        if ((val = find_json_key(eval_weights_obj, "queen_centralization_mg")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.queen_centralization_mg = value;
            }
        }
        if ((val = find_json_key(eval_weights_obj, "queen_centralization_eg")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.queen_centralization_eg = value;
            }
        }
    }

    /* Parse search_params */
    const char *search_params_obj = find_json_key(params_obj, "search_params");
    if (search_params_obj)
    {
        const char *val;
        int value;

        if ((val = find_json_key(search_params_obj, "null_move_reduction")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.null_move_reduction = value;
            }
        }
        if ((val = find_json_key(search_params_obj, "null_move_min_depth")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.null_move_min_depth = value;
            }
        }
        if ((val = find_json_key(search_params_obj, "lmr_enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
            {
                g_runtime_params.lmr_enabled = value;
            }
        }
        if ((val = find_json_key(search_params_obj, "lmr_min_depth")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.lmr_min_depth = value;
            }
        }
        if ((val = find_json_key(search_params_obj, "lmr_move_threshold")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.lmr_move_threshold = value;
            }
        }
        if ((val = find_json_key(search_params_obj, "futility_enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
            {
                g_runtime_params.futility_enabled = value;
            }
        }
        if ((val = find_json_key(search_params_obj, "futility_margin_base")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.futility_margin_base = value;
            }
        }
        if ((val = find_json_key(search_params_obj, "razoring_enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
            {
                g_runtime_params.razoring_enabled = value;
            }
        }
        if ((val = find_json_key(search_params_obj, "razoring_margin")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.razoring_margin = value;
            }
        }
        if ((val = find_json_key(search_params_obj, "rfp_enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
                g_runtime_params.rfp_enabled = value;
        }
        if ((val = find_json_key(search_params_obj, "nmp_enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
                g_runtime_params.nmp_enabled = value;
        }
        if ((val = find_json_key(search_params_obj, "nmp_base_reduction")) != NULL)
        {
            if (parse_json_number(val, &value))
                g_runtime_params.nmp_base_reduction = value;
        }
        if ((val = find_json_key(search_params_obj, "nmp_depth_divisor")) != NULL)
        {
            if (parse_json_number(val, &value))
                g_runtime_params.nmp_depth_divisor = value;
        }
        if ((val = find_json_key(search_params_obj, "lmr_base")) != NULL)
        {
            double dval;
            if (parse_json_double(val, &dval))
                g_runtime_params.lmr_base = dval;
        }
        if ((val = find_json_key(search_params_obj, "lmr_divisor")) != NULL)
        {
            double dval;
            if (parse_json_double(val, &dval))
                g_runtime_params.lmr_divisor = dval;
        }
        if ((val = find_json_key(search_params_obj, "lmp_enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
                g_runtime_params.lmp_enabled = value;
        }
        if ((val = find_json_key(search_params_obj, "see_prune_enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
                g_runtime_params.see_prune_enabled = value;
        }
        if ((val = find_json_key(search_params_obj, "eval_king_safety_enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
                g_runtime_params.eval_king_safety_enabled = value;
        }
        if ((val = find_json_key(search_params_obj, "eval_endgame_enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
                g_runtime_params.eval_endgame_enabled = value;
        }
        if ((val = find_json_key(search_params_obj, "history_prune_enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
                g_runtime_params.history_prune_enabled = value;
        }
        if ((val = find_json_key(search_params_obj, "singular_ext_enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
                g_runtime_params.singular_ext_enabled = value;
        }
        if ((val = find_json_key(search_params_obj, "iid_enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
                g_runtime_params.iid_enabled = value;
        }
        if ((val = find_json_key(search_params_obj, "probcut_enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
                g_runtime_params.probcut_enabled = value;
        }
        if ((val = find_json_key(search_params_obj, "probcut_min_depth")) != NULL)
        {
            if (parse_json_number(val, &value))
                g_runtime_params.probcut_min_depth = value;
        }
        if ((val = find_json_key(search_params_obj, "probcut_margin")) != NULL)
        {
            if (parse_json_number(val, &value))
                g_runtime_params.probcut_margin = value;
        }
        if ((val = find_json_key(search_params_obj, "probcut_reduction")) != NULL)
        {
            if (parse_json_number(val, &value))
                g_runtime_params.probcut_reduction = value;
        }
        if ((val = find_json_key(search_params_obj, "history_table_enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
                g_runtime_params.history_table_enabled = value;
        }
        if ((val = find_json_key(search_params_obj, "killers_enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
                g_runtime_params.killers_enabled = value;
        }
        if ((val = find_json_key(search_params_obj, "countermove_followup_enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
                g_runtime_params.countermove_followup_enabled = value;
        }
        if ((val = find_json_key(search_params_obj, "delta_prune_enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
                g_runtime_params.delta_prune_enabled = value;
        }
        if ((val = find_json_key(search_params_obj, "qs_max_depth_mg")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.qs_max_depth_mg = value;
            }
        }
        if ((val = find_json_key(search_params_obj, "qs_max_depth_eg")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.qs_max_depth_eg = value;
            }
        }
    }

    /* Parse constants */
    const char *constants_obj = find_json_key(params_obj, "constants");
    if (constants_obj)
    {
        const char *val;
        int value;

        if ((val = find_json_key(constants_obj, "mate_score")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.mate_score = value;
            }
        }
        if ((val = find_json_key(constants_obj, "delta")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.delta = value;
            }
        }
        if ((val = find_json_key(constants_obj, "endgame_phase_threshold")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.endgame_phase_threshold = value;
            }
        }
        if ((val = find_json_key(constants_obj, "endgame_depth_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.endgame_depth_bonus = value;
            }
        }
        if ((val = find_json_key(constants_obj, "endgame_nmr_bonus")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.endgame_nmr_bonus = value;
            }
        }
        if ((val = find_json_key(constants_obj, "king_activity_weight")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.king_activity_weight = value;
            }
        }
    }

    /* Parse threading */
    const char *threading_obj = find_json_key(params_obj, "threading");
    if (threading_obj)
    {
        const char *val;
        int value;

        if ((val = find_json_key(threading_obj, "enabled")) != NULL)
        {
            if (parse_json_boolean(val, &value))
            {
                g_runtime_params.threading_enabled = value;
            }
        }
        if ((val = find_json_key(threading_obj, "num_threads")) != NULL)
        {
            if (parse_json_number(val, &value))
            {
                g_runtime_params.num_threads = value;
            }
        }
    }

    /* ========================================================================
     * PARAMETER VALIDATION
     * ========================================================================
     * Validate all loaded parameters to ensure they are within reasonable
     * ranges. This prevents invalid configurations from causing engine
     * malfunction or undefined behavior.
     */

    int validation_errors = 0;
    int validation_warnings = 0;

    /* Validate piece values - must be positive and in reasonable ranges */
    if (g_runtime_params.piece_values[1] <= 0 || g_runtime_params.piece_values[1] > 200)
    {
        fprintf(stderr, "ERROR: Invalid pawn value: %d (expected 50-200)\n",
                g_runtime_params.piece_values[1]);
        validation_errors++;
    }
    if (g_runtime_params.piece_values[2] <= 0 || g_runtime_params.piece_values[2] > 500)
    {
        fprintf(stderr, "ERROR: Invalid knight value: %d (expected 200-500)\n",
                g_runtime_params.piece_values[2]);
        validation_errors++;
    }
    if (g_runtime_params.piece_values[3] <= 0 || g_runtime_params.piece_values[3] > 500)
    {
        fprintf(stderr, "ERROR: Invalid bishop value: %d (expected 200-500)\n",
                g_runtime_params.piece_values[3]);
        validation_errors++;
    }
    if (g_runtime_params.piece_values[4] <= 0 || g_runtime_params.piece_values[4] > 800)
    {
        fprintf(stderr, "ERROR: Invalid rook value: %d (expected 300-800)\n",
                g_runtime_params.piece_values[4]);
        validation_errors++;
    }
    if (g_runtime_params.piece_values[5] <= 0 || g_runtime_params.piece_values[5] > 1500)
    {
        fprintf(stderr, "ERROR: Invalid queen value: %d (expected 700-1500)\n",
                g_runtime_params.piece_values[5]);
        validation_errors++;
    }
    if (g_runtime_params.piece_values[6] <= 0 || g_runtime_params.piece_values[6] > 100000)
    {
        fprintf(stderr, "ERROR: Invalid king value: %d (expected 10000-100000)\n",
                g_runtime_params.piece_values[6]);
        validation_errors++;
    }

    /* Validate piece value relationships */
    if (g_runtime_params.piece_values[2] < g_runtime_params.piece_values[1])
    {
        fprintf(stderr, "WARNING: Knight value (%d) is less than pawn value (%d)\n",
                g_runtime_params.piece_values[2], g_runtime_params.piece_values[1]);
        validation_warnings++;
    }
    if (g_runtime_params.piece_values[3] < g_runtime_params.piece_values[1])
    {
        fprintf(stderr, "WARNING: Bishop value (%d) is less than pawn value (%d)\n",
                g_runtime_params.piece_values[3], g_runtime_params.piece_values[1]);
        validation_warnings++;
    }
    if (g_runtime_params.piece_values[4] < g_runtime_params.piece_values[2])
    {
        fprintf(stderr, "WARNING: Rook value (%d) is less than knight value (%d)\n",
                g_runtime_params.piece_values[4], g_runtime_params.piece_values[2]);
        validation_warnings++;
    }
    if (g_runtime_params.piece_values[5] < g_runtime_params.piece_values[4])
    {
        fprintf(stderr, "WARNING: Queen value (%d) is less than rook value (%d)\n",
                g_runtime_params.piece_values[5], g_runtime_params.piece_values[4]);
        validation_warnings++;
    }

    /* Validate PST tables - values should be within reasonable bounds */
    int piece_idx, sq;
    for (piece_idx = 0; piece_idx < 6; piece_idx++)
    {
        for (sq = 0; sq < 64; sq++)
        {
            if (g_runtime_params.mg_pst[piece_idx][sq] < -500 ||
                g_runtime_params.mg_pst[piece_idx][sq] > 500)
            {
                fprintf(stderr, "WARNING: PST value out of range for piece %d square %d: mg=%d\n",
                        piece_idx, sq, g_runtime_params.mg_pst[piece_idx][sq]);
                validation_warnings++;
            }
            if (g_runtime_params.eg_pst[piece_idx][sq] < -500 ||
                g_runtime_params.eg_pst[piece_idx][sq] > 500)
            {
                fprintf(stderr, "WARNING: PST value out of range for piece %d square %d: eg=%d\n",
                        piece_idx, sq, g_runtime_params.eg_pst[piece_idx][sq]);
                validation_warnings++;
            }
        }
    }

    /* Validate evaluation weights */
    if (g_runtime_params.bishop_pair_bonus < 0 || g_runtime_params.bishop_pair_bonus > 200)
    {
        fprintf(stderr, "WARNING: Bishop pair bonus out of range: %d (expected 0-200)\n",
                g_runtime_params.bishop_pair_bonus);
        validation_warnings++;
    }
    if (g_runtime_params.doubled_pawn_penalty > 0 || g_runtime_params.doubled_pawn_penalty < -100)
    {
        fprintf(stderr, "WARNING: Doubled pawn penalty out of range: %d (expected -100 to 0)\n",
                g_runtime_params.doubled_pawn_penalty);
        validation_warnings++;
    }
    if (g_runtime_params.isolated_pawn_penalty > 0 || g_runtime_params.isolated_pawn_penalty < -100)
    {
        fprintf(stderr, "WARNING: Isolated pawn penalty out of range: %d (expected -100 to 0)\n",
                g_runtime_params.isolated_pawn_penalty);
        validation_warnings++;
    }
    if (g_runtime_params.open_file_bonus < 0 || g_runtime_params.open_file_bonus > 100)
    {
        fprintf(stderr, "WARNING: Open file bonus out of range: %d (expected 0-100)\n",
                g_runtime_params.open_file_bonus);
        validation_warnings++;
    }
    if (g_runtime_params.semi_open_file_bonus < 0 || g_runtime_params.semi_open_file_bonus > 100)
    {
        fprintf(stderr, "WARNING: Semi-open file bonus out of range: %d (expected 0-100)\n",
                g_runtime_params.semi_open_file_bonus);
        validation_warnings++;
    }

    /* Validate passed pawn bonuses */
    int rank;
    for (rank = 0; rank < 8; rank++)
    {
        if (g_runtime_params.passed_pawn_bonus[rank] < 0 ||
            g_runtime_params.passed_pawn_bonus[rank] > 300)
        {
            fprintf(stderr, "WARNING: Passed pawn bonus for rank %d out of range: %d (expected 0-300)\n",
                    rank, g_runtime_params.passed_pawn_bonus[rank]);
            validation_warnings++;
        }
    }

    /* Validate search parameters */
    if (g_runtime_params.null_move_reduction < 1 || g_runtime_params.null_move_reduction > 5)
    {
        fprintf(stderr, "ERROR: Null move reduction out of range: %d (expected 1-5)\n",
                g_runtime_params.null_move_reduction);
        validation_errors++;
    }
    if (g_runtime_params.null_move_min_depth < 1 || g_runtime_params.null_move_min_depth > 10)
    {
        fprintf(stderr, "ERROR: Null move min depth out of range: %d (expected 1-10)\n",
                g_runtime_params.null_move_min_depth);
        validation_errors++;
    }
    if (g_runtime_params.lmr_enabled != 0 && g_runtime_params.lmr_enabled != 1)
    {
        fprintf(stderr, "ERROR: LMR enabled must be 0 or 1, got: %d\n",
                g_runtime_params.lmr_enabled);
        validation_errors++;
    }
    if (g_runtime_params.lmr_min_depth < 1 || g_runtime_params.lmr_min_depth > 10)
    {
        fprintf(stderr, "ERROR: LMR min depth out of range: %d (expected 1-10)\n",
                g_runtime_params.lmr_min_depth);
        validation_errors++;
    }
    if (g_runtime_params.lmr_move_threshold < 1 || g_runtime_params.lmr_move_threshold > 10)
    {
        fprintf(stderr, "ERROR: LMR move threshold out of range: %d (expected 1-10)\n",
                g_runtime_params.lmr_move_threshold);
        validation_errors++;
    }
    if (g_runtime_params.futility_enabled != 0 && g_runtime_params.futility_enabled != 1)
    {
        fprintf(stderr, "ERROR: Futility enabled must be 0 or 1, got: %d\n",
                g_runtime_params.futility_enabled);
        validation_errors++;
    }
    if (g_runtime_params.futility_margin_base < 50 || g_runtime_params.futility_margin_base > 500)
    {
        fprintf(stderr, "ERROR: Futility margin base out of range: %d (expected 50-500)\n",
                g_runtime_params.futility_margin_base);
        validation_errors++;
    }
    if (g_runtime_params.razoring_enabled != 0 && g_runtime_params.razoring_enabled != 1)
    {
        fprintf(stderr, "ERROR: Razoring enabled must be 0 or 1, got: %d\n",
                g_runtime_params.razoring_enabled);
        validation_errors++;
    }
    if (g_runtime_params.razoring_margin < 100 || g_runtime_params.razoring_margin > 1000)
    {
        fprintf(stderr, "ERROR: Razoring margin out of range: %d (expected 100-1000)\n",
                g_runtime_params.razoring_margin);
        validation_errors++;
    }

    /* Validate constants */
    if (g_runtime_params.mate_score < 100000 || g_runtime_params.mate_score > 10000000)
    {
        fprintf(stderr, "ERROR: Mate score out of range: %d (expected 100000-10000000)\n",
                g_runtime_params.mate_score);
        validation_errors++;
    }
    if (g_runtime_params.delta < 100 || g_runtime_params.delta > 2000)
    {
        fprintf(stderr, "ERROR: Delta out of range: %d (expected 100-2000)\n",
                g_runtime_params.delta);
        validation_errors++;
    }

    /* Validate threading parameters */
    if (g_runtime_params.threading_enabled != 0 && g_runtime_params.threading_enabled != 1)
    {
        fprintf(stderr, "ERROR: Threading enabled must be 0 or 1, got: %d\n",
                g_runtime_params.threading_enabled);
        validation_errors++;
    }
    if (g_runtime_params.num_threads < 1 || g_runtime_params.num_threads > 64)
    {
        fprintf(stderr, "ERROR: Number of threads out of range: %d (expected 1-64)\n",
                g_runtime_params.num_threads);
        validation_errors++;
    }

    /* Report validation results */
    if (validation_errors > 0)
    {
        fprintf(stderr, "\n=== PARAMETER VALIDATION FAILED ===\n");
        fprintf(stderr, "Found %d error(s) and %d warning(s)\n",
                validation_errors, validation_warnings);
        fprintf(stderr, "Configuration file rejected: %s\n", filename);
        free(json);
        return 0;
    }

    if (validation_warnings > 0)
    {
        printf("\n=== PARAMETER VALIDATION WARNINGS ===\n");
        printf("Found %d warning(s) - parameters loaded but may not be optimal\n",
               validation_warnings);
    }

    /* Regenerate lmr_table with the loaded runtime params (P1 fix) */
    regenerate_lmr_table();

    g_runtime_params.loaded = 1;
    free(json);

    fprintf(stderr, "\n=== PARAMETERS LOADED SUCCESSFULLY ===\n");
    fprintf(stderr, "Configuration file: %s\n", filename);
    fprintf(stderr, "Piece values: P=%d N=%d B=%d R=%d Q=%d K=%d\n",
            g_runtime_params.piece_values[1],
            g_runtime_params.piece_values[2],
            g_runtime_params.piece_values[3],
            g_runtime_params.piece_values[4],
            g_runtime_params.piece_values[5],
            g_runtime_params.piece_values[6]);
    fprintf(stderr, "Search params: LMR=%s Futility=%s Razoring=%s\n",
            g_runtime_params.lmr_enabled ? "enabled" : "disabled",
            g_runtime_params.futility_enabled ? "enabled" : "disabled",
            g_runtime_params.razoring_enabled ? "enabled" : "disabled");
    fprintf(stderr, "Threading: %s (%d threads)\n",
            g_runtime_params.threading_enabled ? "enabled" : "disabled",
            g_runtime_params.num_threads);
    fprintf(stderr, "Validation: %d error(s), %d warning(s)\n",
            validation_errors, validation_warnings);

    return 1;
}

/* Reload parameters from file - for tuning use.
 * Returns 1 on success, 0 on failure. */
#ifdef _WIN32
__declspec(dllexport)
#endif
int
reload_params(const char *filename)
{
    return load_params_from_file(filename);
}

/* Set a search param toggle by name. Returns 1 on success, 0 on unknown name. */
#ifdef _WIN32
__declspec(dllexport)
#endif
int
set_search_param(const char *name, int value)
{
    if (!name) return 0;
    if (strcmp(name, "rfp_enabled") == 0) { g_runtime_params.rfp_enabled = value; return 1; }
    if (strcmp(name, "nmp_enabled") == 0) { g_runtime_params.nmp_enabled = value; return 1; }
    if (strcmp(name, "lmr_enabled") == 0) { g_runtime_params.lmr_enabled = value; return 1; }
    if (strcmp(name, "futility_enabled") == 0) { g_runtime_params.futility_enabled = value; return 1; }
    if (strcmp(name, "razoring_enabled") == 0) { g_runtime_params.razoring_enabled = value; return 1; }
    if (strcmp(name, "lmp_enabled") == 0) { g_runtime_params.lmp_enabled = value; return 1; }
    if (strcmp(name, "see_prune_enabled") == 0) { g_runtime_params.see_prune_enabled = value; return 1; }
    if (strcmp(name, "history_prune_enabled") == 0) { g_runtime_params.history_prune_enabled = value; return 1; }
    if (strcmp(name, "singular_ext_enabled") == 0) { g_runtime_params.singular_ext_enabled = value; return 1; }
    if (strcmp(name, "iid_enabled") == 0) { g_runtime_params.iid_enabled = value; return 1; }
    if (strcmp(name, "probcut_enabled") == 0) { g_runtime_params.probcut_enabled = value; return 1; }
    if (strcmp(name, "probcut_min_depth") == 0) { g_runtime_params.probcut_min_depth = value; return 1; }
    if (strcmp(name, "probcut_margin") == 0) { g_runtime_params.probcut_margin = value; return 1; }
    if (strcmp(name, "probcut_reduction") == 0) { g_runtime_params.probcut_reduction = value; return 1; }
    if (strcmp(name, "history_table_enabled") == 0) { g_runtime_params.history_table_enabled = value; return 1; }
    if (strcmp(name, "killers_enabled") == 0) { g_runtime_params.killers_enabled = value; return 1; }
    if (strcmp(name, "countermove_followup_enabled") == 0) { g_runtime_params.countermove_followup_enabled = value; return 1; }
    if (strcmp(name, "delta_prune_enabled") == 0) { g_runtime_params.delta_prune_enabled = value; return 1; }
    if (strcmp(name, "eval_king_safety_enabled") == 0) { g_runtime_params.eval_king_safety_enabled = value; return 1; }
    if (strcmp(name, "eval_endgame_enabled") == 0) { g_runtime_params.eval_endgame_enabled = value; return 1; }
    return 0;
}

/* Get current value of a search param toggle. Returns -1 on unknown name. */
#ifdef _WIN32
__declspec(dllexport)
#endif
int
get_search_param(const char *name)
{
    if (!name) return -1;
    if (strcmp(name, "rfp_enabled") == 0) return g_runtime_params.rfp_enabled;
    if (strcmp(name, "nmp_enabled") == 0) return g_runtime_params.nmp_enabled;
    if (strcmp(name, "lmr_enabled") == 0) return g_runtime_params.lmr_enabled;
    if (strcmp(name, "futility_enabled") == 0) return g_runtime_params.futility_enabled;
    if (strcmp(name, "razoring_enabled") == 0) return g_runtime_params.razoring_enabled;
    if (strcmp(name, "lmp_enabled") == 0) return g_runtime_params.lmp_enabled;
    if (strcmp(name, "see_prune_enabled") == 0) return g_runtime_params.see_prune_enabled;
    if (strcmp(name, "history_prune_enabled") == 0) return g_runtime_params.history_prune_enabled;
    if (strcmp(name, "singular_ext_enabled") == 0) return g_runtime_params.singular_ext_enabled;
    if (strcmp(name, "iid_enabled") == 0) return g_runtime_params.iid_enabled;
    if (strcmp(name, "probcut_enabled") == 0) return g_runtime_params.probcut_enabled;
    if (strcmp(name, "probcut_min_depth") == 0) return g_runtime_params.probcut_min_depth;
    if (strcmp(name, "probcut_margin") == 0) return g_runtime_params.probcut_margin;
    if (strcmp(name, "probcut_reduction") == 0) return g_runtime_params.probcut_reduction;
    if (strcmp(name, "history_table_enabled") == 0) return g_runtime_params.history_table_enabled;
    if (strcmp(name, "killers_enabled") == 0) return g_runtime_params.killers_enabled;
    if (strcmp(name, "countermove_followup_enabled") == 0) return g_runtime_params.countermove_followup_enabled;
    if (strcmp(name, "delta_prune_enabled") == 0) return g_runtime_params.delta_prune_enabled;
    if (strcmp(name, "eval_king_safety_enabled") == 0) return g_runtime_params.eval_king_safety_enabled;
    if (strcmp(name, "eval_endgame_enabled") == 0) return g_runtime_params.eval_endgame_enabled;
    return -1;
}