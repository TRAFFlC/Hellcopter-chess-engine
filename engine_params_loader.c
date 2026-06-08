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
            if (*json == '"' && (json == key_start || *(json - 1) != '\\'))
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
    g_runtime_params.piece_values[0] = 0;
    g_runtime_params.piece_values[1] = PAWN_VALUE;
    g_runtime_params.piece_values[2] = KNIGHT_VALUE;
    g_runtime_params.piece_values[3] = BISHOP_VALUE;
    g_runtime_params.piece_values[4] = ROOK_VALUE;
    g_runtime_params.piece_values[5] = QUEEN_VALUE;
    g_runtime_params.piece_values[6] = KING_VALUE;

    /* Copy PST defaults */
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