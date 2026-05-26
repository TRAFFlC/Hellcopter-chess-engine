#include "engine_core.h"
#include "engine_params.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>
#include <ctype.h>
#include <assert.h>

#ifdef _WIN32
#include <windows.h>
#else
#include <pthread.h>
#include <stdatomic.h>
#endif

#ifdef _MSC_VER
#include <intrin.h>
#define POPCNT64(x) ((int)__popcnt64(x))
#else
#define POPCNT64(x) ((int)__builtin_popcountll(x))
#endif

#define INF 1000000
#define EVAL_SCORE_INVALID 9999999
/* MATE_SCORE and DELTA now defined in engine_params.h */
#define MAX_MOVES 256
#define ENGINE_VERSION 20260511

/* ============================================================================
 * RUNTIME PARAMETER STRUCTURE
 * ============================================================================
 * This structure holds runtime-loaded parameters that can override the
 * compile-time defaults from engine_params.h
 */
typedef struct
{
    int piece_values[7]; /* 0=empty, 1=pawn, 2=knight, 3=bishop, 4=rook, 5=queen, 6=king */
    int mg_pst[6][64];   /* Middlegame PST for pawn, knight, bishop, rook, queen, king */
    int eg_pst[6][64];   /* Endgame PST for pawn, knight, bishop, rook, queen, king */
    int bishop_pair_bonus;
    int doubled_pawn_penalty;
    int isolated_pawn_penalty;
    int passed_pawn_bonus[8];
    int open_file_bonus;
    int semi_open_file_bonus;
    int null_move_reduction;
    int null_move_min_depth;
    int lmr_enabled;
    int lmr_min_depth;
    int lmr_move_threshold;
    int futility_enabled;
    int futility_margin_base;
    int razoring_enabled;
    int razoring_margin;
    int mate_score;
    int delta;
    int threading_enabled;
    int num_threads;
    int loaded; /* Flag: 1 if parameters loaded from file, 0 if using defaults */
} RuntimeParams;

/* Global runtime parameters - initialized to defaults */
static RuntimeParams g_runtime_params = {0};

/* Piece values array - using values from engine_params.h or runtime params */
static const int piece_values[7] = {0, PAWN_VALUE, KNIGHT_VALUE, BISHOP_VALUE, ROOK_VALUE, QUEEN_VALUE, KING_VALUE};

/* PST tables are now defined in engine_params.h */
/* Pointer arrays to access PST tables */
static const int *mg_pst[7] = {NULL, mg_pawn, mg_knight, mg_bishop, mg_rook, mg_queen, mg_king};
static const int *eg_pst[7] = {NULL, eg_pawn, eg_knight, eg_bishop, eg_rook, eg_queen, eg_king};

static const U64 file_masks[8] = {
    0x0101010101010101ULL,
    0x0202020202020202ULL,
    0x0404040404040404ULL,
    0x0808080808080808ULL,
    0x1010101010101010ULL,
    0x2020202020202020ULL,
    0x4040404040404040ULL,
    0x8080808080808080ULL};

static const U64 rank_masks[8] = {
    0x00000000000000FFULL,
    0x000000000000FF00ULL,
    0x0000000000FF0000ULL,
    0x00000000FF000000ULL,
    0x000000FF00000000ULL,
    0x0000FF0000000000ULL,
    0x00FF000000000000ULL,
    0xFF00000000000000ULL};

static U64 knight_attacks[64];
static U64 king_attacks[64];
static U64 zobrist_table[12 * 64 + 1 + 4 + 64];
static int zobrist_initialized = 0;
static int attacks_initialized = 0;

#define MAX_BLUNDER_ENTRIES 10000

typedef struct
{
    U64 zobrist_key;
    int bad_from;
    int bad_to;
    int good_from;
    int good_to;
} BlunderEntry;

static BlunderEntry g_blunder_memory[MAX_BLUNDER_ENTRIES];
static int g_blunder_count = 0;
static int g_blunder_memory_loaded = 0;

volatile int g_engine_abort_flag = 0;

static EngineInfoCallback g_info_callback = NULL;

void set_engine_info_callback(EngineInfoCallback cb)
{
    g_info_callback = cb;
}

static void init_zobrist(void);
static U64 compute_hash(const Board *b);

static int rank_of(int sq) { return sq >> 3; }
static int file_of(int sq) { return sq & 7; }

static U64 shift_north(U64 b) { return b << 8; }
static U64 shift_south(U64 b) { return b >> 8; }
static U64 shift_east(U64 b) { return (b << 1) & ~file_masks[0]; }
static U64 shift_west(U64 b) { return (b >> 1) & ~file_masks[7]; }

static U64 slow_rook_attacks(int sq, U64 occupied)
{
    U64 attacks = 0;
    int r = rank_of(sq), f = file_of(sq);
    int i;
    for (i = f + 1; i < 8; i++)
    {
        U64 bb = 1ULL << (r * 8 + i);
        attacks |= bb;
        if (occupied & bb)
            break;
    }
    for (i = f - 1; i >= 0; i--)
    {
        U64 bb = 1ULL << (r * 8 + i);
        attacks |= bb;
        if (occupied & bb)
            break;
    }
    for (i = r + 1; i < 8; i++)
    {
        U64 bb = 1ULL << (i * 8 + f);
        attacks |= bb;
        if (occupied & bb)
            break;
    }
    for (i = r - 1; i >= 0; i--)
    {
        U64 bb = 1ULL << (i * 8 + f);
        attacks |= bb;
        if (occupied & bb)
            break;
    }
    return attacks;
}

static U64 slow_bishop_attacks(int sq, U64 occupied)
{
    U64 attacks = 0;
    int r = rank_of(sq), f = file_of(sq);
    int i, j;
    for (i = r + 1, j = f + 1; i < 8 && j < 8; i++, j++)
    {
        U64 bb = 1ULL << (i * 8 + j);
        attacks |= bb;
        if (occupied & bb)
            break;
    }
    for (i = r + 1, j = f - 1; i < 8 && j >= 0; i++, j--)
    {
        U64 bb = 1ULL << (i * 8 + j);
        attacks |= bb;
        if (occupied & bb)
            break;
    }
    for (i = r - 1, j = f + 1; i >= 0 && j < 8; i--, j++)
    {
        U64 bb = 1ULL << (i * 8 + j);
        attacks |= bb;
        if (occupied & bb)
            break;
    }
    for (i = r - 1, j = f - 1; i >= 0 && j >= 0; i--, j--)
    {
        U64 bb = 1ULL << (i * 8 + j);
        attacks |= bb;
        if (occupied & bb)
            break;
    }
    return attacks;
}

typedef struct
{
    U64 mask;
    U64 magic;
    int shift;
    U64 *attacks;
} MagicEntry;

static MagicEntry rook_magics[64];
static MagicEntry bishop_magics[64];
static U64 rook_attack_table[102400];
static U64 bishop_attack_table[5248];
static int magics_initialized = 0;

static U64 magic_prng_state;

static U64 magic_prng_next(void)
{
    magic_prng_state ^= magic_prng_state >> 12;
    magic_prng_state ^= magic_prng_state << 25;
    magic_prng_state ^= magic_prng_state >> 27;
    return magic_prng_state * 2685821657736338717ULL;
}

static U64 magic_prng_sparse(void)
{
    return magic_prng_next() & magic_prng_next() & magic_prng_next();
}

static void init_magics(MagicEntry magics[], U64 table[], int is_rook)
{
    U64 occupancy[4096];
    U64 reference[4096];
    int epoch[4096];
    U64 seeds[8] = {8977ULL, 44560ULL, 54343ULL, 38998ULL,
                    5731ULL, 95205ULL, 104912ULL, 17020ULL};
    int cnt = 0;
    int size = 0;
    int sq, i;
    unsigned idx;
    U64 b, edges, attacks;

    memset(epoch, 0, sizeof(epoch));

    for (sq = 0; sq < 64; sq++)
    {
        edges = ((rank_masks[0] | rank_masks[7]) & ~rank_masks[rank_of(sq)]) |
                ((file_masks[0] | file_masks[7]) & ~file_masks[file_of(sq)]);
        attacks = is_rook ? slow_rook_attacks(sq, 0) : slow_bishop_attacks(sq, 0);

        magics[sq].mask = attacks & ~edges;
        magics[sq].shift = 64 - POPCNT64(magics[sq].mask);
        magics[sq].attacks = sq == 0 ? table : magics[sq - 1].attacks + size;
        size = 0;

        b = 0;
        do
        {
            occupancy[size] = b;
            reference[size] = is_rook ? slow_rook_attacks(sq, b) : slow_bishop_attacks(sq, b);
            size++;
            b = (b - magics[sq].mask) & magics[sq].mask;
        } while (b);

        magic_prng_state = seeds[rank_of(sq)];

        for (i = 0; i < size;)
        {
            for (magics[sq].magic = 0;
                 POPCNT64((magics[sq].magic * magics[sq].mask) >> 56) < 6;)
                magics[sq].magic = magic_prng_sparse();

            for (++cnt, i = 0; i < size; ++i)
            {
                idx = (unsigned)(((occupancy[i] & magics[sq].mask) * magics[sq].magic) >> magics[sq].shift);
                if (epoch[idx] < cnt)
                {
                    epoch[idx] = cnt;
                    magics[sq].attacks[idx] = reference[i];
                }
                else if (magics[sq].attacks[idx] != reference[i])
                {
                    break;
                }
            }
        }
    }
}

static U64 sliding_attacks_rook(int sq, U64 occupied)
{
    MagicEntry *m = &rook_magics[sq];
    unsigned idx = (unsigned)(((occupied & m->mask) * m->magic) >> m->shift);
    return m->attacks[idx];
}

static U64 sliding_attacks_bishop(int sq, U64 occupied)
{
    MagicEntry *m = &bishop_magics[sq];
    unsigned idx = (unsigned)(((occupied & m->mask) * m->magic) >> m->shift);
    return m->attacks[idx];
}

static void init_knight_attacks(void)
{
    int sq;
    for (sq = 0; sq < 64; sq++)
    {
        int r = rank_of(sq), f = file_of(sq);
        U64 bb = 0;
        if (r + 2 < 8 && f + 1 < 8)
            bb |= 1ULL << ((r + 2) * 8 + f + 1);
        if (r + 2 < 8 && f - 1 >= 0)
            bb |= 1ULL << ((r + 2) * 8 + f - 1);
        if (r - 2 >= 0 && f + 1 < 8)
            bb |= 1ULL << ((r - 2) * 8 + f + 1);
        if (r - 2 >= 0 && f - 1 >= 0)
            bb |= 1ULL << ((r - 2) * 8 + f - 1);
        if (r + 1 < 8 && f + 2 < 8)
            bb |= 1ULL << ((r + 1) * 8 + f + 2);
        if (r + 1 < 8 && f - 2 >= 0)
            bb |= 1ULL << ((r + 1) * 8 + f - 2);
        if (r - 1 >= 0 && f + 2 < 8)
            bb |= 1ULL << ((r - 1) * 8 + f + 2);
        if (r - 1 >= 0 && f - 2 >= 0)
            bb |= 1ULL << ((r - 1) * 8 + f - 2);
        knight_attacks[sq] = bb;
    }
}

static void init_king_attacks(void)
{
    int sq;
    for (sq = 0; sq < 64; sq++)
    {
        int r = rank_of(sq), f = file_of(sq);
        U64 bb = 0;
        int dr, df;
        for (dr = -1; dr <= 1; dr++)
        {
            for (df = -1; df <= 1; df++)
            {
                if (dr == 0 && df == 0)
                    continue;
                int nr = r + dr, nf = f + df;
                if (nr >= 0 && nr < 8 && nf >= 0 && nf < 8)
                    bb |= 1ULL << (nr * 8 + nf);
            }
        }
        king_attacks[sq] = bb;
    }
}

static void ensure_engine_tables_initialized(void)
{
    if (!attacks_initialized)
    {
        init_knight_attacks();
        init_king_attacks();
        attacks_initialized = 1;
    }
    if (!magics_initialized)
    {
        init_magics(rook_magics, rook_attack_table, 1);
        init_magics(bishop_magics, bishop_attack_table, 0);
        magics_initialized = 1;
    }
    if (!zobrist_initialized)
    {
        init_zobrist();
    }
}

static void init_zobrist(void)
{
    unsigned long long seed = 0x123456789ABCDEF0ULL;
    int i;
    for (i = 0; i < 12 * 64 + 1 + 4 + 64; i++)
    {
        seed = seed * 1103515245 + 12345;
        zobrist_table[i] = seed;
    }
    zobrist_initialized = 1;
}

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
 * ============================================================================
 */

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

/* Helper function to get piece value (uses runtime params if loaded) */
static int get_piece_value(int piece_type)
{
    if (g_runtime_params.loaded && piece_type >= 0 && piece_type < 7)
    {
        return g_runtime_params.piece_values[piece_type];
    }
    return piece_values[piece_type];
}

static double get_time(void)
{
    clock_t c = clock();
    return (double)c / (double)CLOCKS_PER_SEC;
}

int popcount(U64 x)
{
    return POPCNT64(x);
}

static U64 all_pieces(const Board *b)
{
    return b->pieces[WHITE][PAWN] | b->pieces[WHITE][KNIGHT] | b->pieces[WHITE][BISHOP] |
           b->pieces[WHITE][ROOK] | b->pieces[WHITE][QUEEN] | b->pieces[WHITE][KING] |
           b->pieces[BLACK][PAWN] | b->pieces[BLACK][KNIGHT] | b->pieces[BLACK][BISHOP] |
           b->pieces[BLACK][ROOK] | b->pieces[BLACK][QUEEN] | b->pieces[BLACK][KING];
}

static U64 side_pieces(const Board *b, int side)
{
    return b->pieces[side][PAWN] | b->pieces[side][KNIGHT] | b->pieces[side][BISHOP] |
           b->pieces[side][ROOK] | b->pieces[side][QUEEN] | b->pieces[side][KING];
}

static int has_non_pawn_material(const Board *b, int side)
{
    return (b->pieces[side][KNIGHT] | b->pieces[side][BISHOP] |
            b->pieces[side][ROOK] | b->pieces[side][QUEEN]) != 0;
}

/* ============================================================================
 * LMR (Late Move Reduction) Helper Functions
 * ============================================================================
 */

/**
 * Check if a move gives check to the opponent
 *
 * @param b The board position
 * @param move The move to check
 * @return 1 if the move gives check, 0 otherwise
 */
static int move_gives_check(const Board *b, const Move *move)
{
    UndoInfo undo;
    Board copy = *b;
    make_move(&copy, move, &undo);
    return is_check(&copy, b->side_to_move);
}

/**
 * Check if a move is a killer move
 *
 * @param s The search state
 * @param move The move to check
 * @param depth The current search depth
 * @return 1 if the move is a killer move, 0 otherwise
 */
static int is_killer_move(const SearchState *s, const Move *move, int depth)
{
    if (depth >= 64)
        return 0;

    int i;
    for (i = 0; i < 2; i++)
    {
        if (s->killers[depth][i].from == move->from &&
            s->killers[depth][i].to == move->to)
        {
            return 1;
        }
    }
    return 0;
}

static int mvv_lva(const Board *b, const Move *m);
static int move_gives_check(const Board *b, const Move *move);

static int should_apply_lmr(const SearchState *s, const Move *move, int depth,
                            int move_num, int in_check, int is_endgame)
{
    if (!g_runtime_params.lmr_enabled)
        return 0;

    if (depth < g_runtime_params.lmr_min_depth)
        return 0;

    int threshold = g_runtime_params.lmr_move_threshold;
    if (is_endgame)
        threshold += 1;
    if (move_num < threshold)
        return 0;

    if (in_check)
        return 0;

    if (move->capture)
        return 0;

    if (move->promotion)
        return 0;

    if (move_gives_check(&s->board, move))
        return 0;

    if (is_killer_move(s, move, depth))
        return 0;

    return 1;
}

static int calculate_reduction(SearchState *s, const Move *move, int depth, int move_num, int is_endgame)
{
    if (depth < 1 || move_num < 1)
        return 0;

    if (move_num < g_runtime_params.lmr_move_threshold)
        return 0;

    double log_depth = log((double)depth);
    double log_move_num = log((double)move_num);
    int reduction = 1 + (int)(log_depth * log_move_num / 2.5);

    if (move->capture)
    {
        int see_score = mvv_lva(&s->board, move) - 100;
        if (see_score >= 0)
            reduction = reduction > 1 ? reduction - 1 : 0;
    }

    if (move->promotion)
        reduction = reduction > 1 ? reduction - 1 : 0;

    if (move_gives_check(&s->board, move))
        reduction = reduction > 1 ? reduction - 1 : 0;

    int history_value = s->history[move->from][move->to];
    if (history_value > 500)
        reduction = reduction > 1 ? reduction - 1 : 0;

    if (is_endgame)
        reduction = (reduction > 1) ? reduction - 1 : 0;

    if (reduction >= depth)
        reduction = depth - 1;

    if (reduction < 0)
        reduction = 0;

    return reduction;
}

/**
 * Determine if Futility Pruning should be applied to a move
 *
 * Futility Pruning is a forward pruning technique that skips moves in shallow
 * positions when the static evaluation is far below alpha. The idea is that if
 * the current position is so bad that even with a generous margin, we can't
 * reach alpha, then searching this move is futile.
 *
 * This function checks all the conditions that must be met for Futility Pruning
 * to be safely applied:
 *
 * 1. Futility Pruning must be enabled in configuration
 * 2. Depth must be shallow (typically <= 3 plies)
 * 3. Not in a PV node (move_num > 0, first move is always searched)
 * 4. Not in check (tactical position)
 * 5. Static evaluation + margin <= alpha (position is hopeless)
 * 6. Move is not tactical (not a capture, check, or promotion)
 *
 * @param s The search state
 * @param move The move to check
 * @param depth The current search depth
 * @param move_num The move number (0-indexed, 0 is the first move)
 * @param in_check Whether the current side is in check
 * @param alpha The current alpha bound
 * @return 1 if Futility Pruning should be applied (skip this move), 0 otherwise
 */
static int should_apply_futility_pruning(SearchState *s, const Move *move,
                                         int depth, int move_num, int in_check,
                                         int alpha, int is_endgame)
{
    if (!g_runtime_params.futility_enabled)
        return 0;

    if (depth > 5 || depth <= 0)
        return 0;

    if (move_num == 0)
        return 0;

    if (in_check)
        return 0;

    if (move->capture)
        return 0;

    if (move->promotion)
        return 0;

    if (move_gives_check(&s->board, move))
        return 0;

    int margin = g_runtime_params.futility_margin_base * depth;
    if (is_endgame)
        margin = margin * 3 / 2;

    int eval = evaluate(&s->board);

    if (eval + margin <= alpha)
    {
        return 1;
    }

    return 0;
}

/**
 * Determine if Razoring should be applied at the current node
 *
 * Razoring is a pruning technique that reduces the search depth when the static
 * evaluation is far below alpha at low depths. The idea is that if the position
 * is so bad that even with a generous margin, we can't reach alpha, then we can
 * reduce the search depth or return the evaluation directly.
 *
 * This function checks all the conditions that must be met for Razoring to be
 * safely applied:
 *
 * 1. Razoring must be enabled in configuration
 * 2. Depth must be very shallow (typically <= 3 plies)
 * 3. Not in a PV node (move_num > 0, first move is always searched)
 * 4. Not in check (tactical position)
 * 5. Static evaluation + razor_margin < alpha (position is very bad)
 *
 * Unlike Futility Pruning which skips individual moves, Razoring is applied
 * at the node level before move generation or early in the search.
 *
 * @param s The search state
 * @param depth The current search depth
 * @param alpha The current alpha bound
 * @param in_check Whether the current side is in check
 * @return 1 if Razoring should be applied, 0 otherwise
 */
static int should_apply_razoring(SearchState *s, int depth, int alpha,
                                 int in_check)
{
    return 0;
}

static int piece_on_square(const Board *b, int sq)
{
    int code = b->mailbox[sq];
    if (code == 0)
        return EMPTY;
    return ((code - 1) % 6) + 1;
}

static int side_on_square(const Board *b, int sq)
{
    int code = b->mailbox[sq];
    if (code == 0)
        return -1;
    return (code - 1) / 6;
}

static int count_bits(U64 bb)
{
    return POPCNT64(bb);
}

static int lsb_index(U64 bb)
{
    return __builtin_ctzll(bb);
}

#ifdef _WIN32
__declspec(dllexport)
#endif
void
board_from_fen(Board *b, const char *fen)
{
    memset(b, 0, sizeof(Board));
    b->en_passant = -1;
    b->castling_rights = 0;
    b->halfmove_clock = 0;
    b->fullmove_number = 1;
    b->eval_score = EVAL_SCORE_INVALID;

    const char *p = fen;
    int rank = 7, file = 0;
    while (*p && *p != ' ')
    {
        char c = *p++;
        if (c >= '1' && c <= '8')
        {
            file += c - '0';
        }
        else if (c == '/')
        {
            rank--;
            file = 0;
        }
        else
        {
            int side = (c >= 'a' && c <= 'z') ? BLACK : WHITE;
            int pt = EMPTY;
            switch (c)
            {
            case 'P':
            case 'p':
                pt = PAWN;
                break;
            case 'N':
            case 'n':
                pt = KNIGHT;
                break;
            case 'B':
            case 'b':
                pt = BISHOP;
                break;
            case 'R':
            case 'r':
                pt = ROOK;
                break;
            case 'Q':
            case 'q':
                pt = QUEEN;
                break;
            case 'K':
            case 'k':
                pt = KING;
                break;
            }
            if (pt != EMPTY)
            {
                int sq = rank * 8 + file;
                b->pieces[side][pt] |= 1ULL << sq;
            }
            file++;
        }
    }
    while (*p == ' ')
        p++;
    if (*p == 'w')
        b->side_to_move = WHITE;
    else if (*p == 'b')
        b->side_to_move = BLACK;
    p++;
    while (*p == ' ')
        p++;
    while (*p && *p != ' ')
    {
        switch (*p++)
        {
        case 'K':
            b->castling_rights |= 1;
            break;
        case 'Q':
            b->castling_rights |= 2;
            break;
        case 'k':
            b->castling_rights |= 4;
            break;
        case 'q':
            b->castling_rights |= 8;
            break;
        }
    }
    while (*p == ' ')
        p++;
    if (*p >= 'a' && *p <= 'h')
    {
        int f = *p++ - 'a';
        int r = *p++ - '1';
        b->en_passant = r * 8 + f;
    }
    else
    {
        b->en_passant = -1;
    }
    while (*p == ' ')
        p++;
    b->halfmove_clock = atoi(p);
    while (*p && *p != ' ')
        p++;
    while (*p == ' ')
        p++;
    b->fullmove_number = atoi(p);

    {
        int sq;
        for (sq = 0; sq < 64; sq++)
            b->mailbox[sq] = 0;
        for (sq = 0; sq < 64; sq++)
        {
            int side, pt;
            for (side = 0; side < 2; side++)
            {
                for (pt = PAWN; pt <= KING; pt++)
                {
                    if (b->pieces[side][pt] & (1ULL << sq))
                    {
                        b->mailbox[sq] = side * 6 + pt;
                        break;
                    }
                }
            }
        }
    }

    {
        U64 bb;
        bb = b->pieces[WHITE][KING];
        b->king_sq[WHITE] = bb ? lsb_index(bb) : 0;
        bb = b->pieces[BLACK][KING];
        b->king_sq[BLACK] = bb ? lsb_index(bb) : 0;
    }

    b->hash = compute_hash(b);

    {
        U64 h = 0;
        int side;
        for (side = 0; side < 2; side++)
        {
            U64 bb = b->pieces[side][PAWN];
            while (bb)
            {
                int sq = lsb_index(bb);
                bb &= bb - 1;
                h ^= zobrist_table[((side * 6 + 0) * 64 + sq)];
            }
        }
        b->pawn_hash = h;
    }

    {
        int npm_w = 0, npm_b = 0;
        int pt;
        for (pt = KNIGHT; pt <= QUEEN; pt++)
        {
            int c = count_bits(b->pieces[WHITE][pt]);
            npm_w += c * (pt == KNIGHT ? 3 : pt == BISHOP ? 3
                                         : pt == ROOK     ? 5
                                                          : 9);
            c = count_bits(b->pieces[BLACK][pt]);
            npm_b += c * (pt == KNIGHT ? 3 : pt == BISHOP ? 3
                                         : pt == ROOK     ? 5
                                                          : 9);
        }
        b->npm[WHITE] = npm_w;
        b->npm[BLACK] = npm_b;
        int phase = npm_w + npm_b;
        if (phase > 31)
            phase = 31;
        phase = phase * 24 / 31;
        if (phase > 24)
            phase = 24;
        b->phase = phase;
    }
}

void board_to_fen(const Board *b, char *fen, size_t fen_size)
{
    char buf[128];
    int pos = 0;
    int rank, file;
    for (rank = 7; rank >= 0; rank--)
    {
        int empty = 0;
        for (file = 0; file < 8; file++)
        {
            int sq = rank * 8 + file;
            int pt = piece_on_square(b, sq);
            if (pt == EMPTY)
            {
                empty++;
            }
            else
            {
                if (empty > 0)
                {
                    buf[pos++] = '0' + empty;
                    empty = 0;
                }
                int side = side_on_square(b, sq);
                char c = ' ';
                switch (pt)
                {
                case PAWN:
                    c = 'P';
                    break;
                case KNIGHT:
                    c = 'N';
                    break;
                case BISHOP:
                    c = 'B';
                    break;
                case ROOK:
                    c = 'R';
                    break;
                case QUEEN:
                    c = 'Q';
                    break;
                case KING:
                    c = 'K';
                    break;
                }
                if (side == BLACK)
                    c += 32;
                buf[pos++] = c;
            }
        }
        if (empty > 0)
            buf[pos++] = '0' + empty;
        if (rank > 0)
            buf[pos++] = '/';
    }
    buf[pos++] = ' ';
    buf[pos++] = (b->side_to_move == WHITE) ? 'w' : 'b';
    buf[pos++] = ' ';
    int cr = b->castling_rights;
    if (cr == 0)
    {
        buf[pos++] = '-';
    }
    else
    {
        if (cr & 1)
            buf[pos++] = 'K';
        if (cr & 2)
            buf[pos++] = 'Q';
        if (cr & 4)
            buf[pos++] = 'k';
        if (cr & 8)
            buf[pos++] = 'q';
    }
    buf[pos++] = ' ';
    if (b->en_passant >= 0)
    {
        int f = file_of(b->en_passant);
        int r = rank_of(b->en_passant);
        buf[pos++] = 'a' + f;
        buf[pos++] = '1' + r;
    }
    else
    {
        buf[pos++] = '-';
    }
    buf[pos++] = ' ';
    pos += sprintf(buf + pos, "%d %d", b->halfmove_clock, b->fullmove_number);
    buf[pos] = '\0';
    strncpy(fen, buf, fen_size - 1);
    fen[fen_size - 1] = '\0';
}

static int is_square_attacked(const Board *b, int sq, int by_side)
{
    if (knight_attacks[sq] & b->pieces[by_side][KNIGHT])
        return 1;
    if (king_attacks[sq] & b->pieces[by_side][KING])
        return 1;

    U64 occupied = all_pieces(b);
    U64 bishops_queens = b->pieces[by_side][BISHOP] | b->pieces[by_side][QUEEN];
    U64 rooks_queens = b->pieces[by_side][ROOK] | b->pieces[by_side][QUEEN];

    if (sliding_attacks_bishop(sq, occupied) & bishops_queens)
        return 1;
    if (sliding_attacks_rook(sq, occupied) & rooks_queens)
        return 1;

    if (by_side == WHITE)
    {
        if ((sq - 7) >= 0 && (sq % 8) != 7 && (b->pieces[WHITE][PAWN] & (1ULL << (sq - 7))))
            return 1;
        if ((sq - 9) >= 0 && (sq % 8) != 0 && (b->pieces[WHITE][PAWN] & (1ULL << (sq - 9))))
            return 1;
    }
    else
    {
        if ((sq + 7) < 64 && (sq % 8) != 0 && (b->pieces[BLACK][PAWN] & (1ULL << (sq + 7))))
            return 1;
        if ((sq + 9) < 64 && (sq % 8) != 7 && (b->pieces[BLACK][PAWN] & (1ULL << (sq + 9))))
            return 1;
    }

    return 0;
}

int is_check(const Board *b, int side)
{
    int king_sq = -1;
    U64 kbb = b->pieces[side][KING];
    while (kbb)
    {
        king_sq = __builtin_ctzll(kbb);
        kbb &= kbb - 1;
    }
    if (king_sq < 0)
        return 0;
    return is_square_attacked(b, king_sq, 1 - side);
}

static int g_last_search_depth = 0;
static int g_last_search_nodes = 0;
static int g_depth_nodes[64] = {0};
static int g_last_best_score = 0;

/* LMR statistics from last search */
static int g_last_lmr_reductions = 0;
static int g_last_lmr_re_searches = 0;
static int g_last_lmr_nodes_saved = 0;

/* Futility Pruning statistics from last search */
static int g_last_futility_prunes = 0;
static int g_last_futility_nodes_saved = 0;

/* Razoring statistics from last search */
static int g_last_razoring_prunes = 0;
static int g_last_razoring_nodes_saved = 0;

/* ============================================================================
 * TINY PERTURBATION MECHANISM
 * ============================================================================
 * When multiple moves have similar evaluations, introduce small perturbation
 * to allow the engine to make different choices, adding variety to play.
 */
static U64 g_perturb_rng_state = 0;
static int g_perturb_threshold = 0;    /* Score difference threshold in centipawns - 0 means only exact same scores */
static int g_perturb_probability = 30; /* Probability to choose second best (0-100) */
static int g_perturb_enabled = 0;      /* Enable/disable perturbation - DISABLED for tuning */

static U64 perturb_xorshift64(void)
{
    U64 x = g_perturb_rng_state;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    return g_perturb_rng_state = x;
}

static void perturb_rng_seed(void)
{
    if (g_perturb_rng_state == 0)
    {
        g_perturb_rng_state = (U64)time(NULL) ^ 0x123456789ABCDEFULL;
        g_perturb_rng_state ^= (U64)clock();
    }
}

static int perturb_rand_int(int max)
{
    if (max <= 0)
        return 0;
    return (int)(perturb_xorshift64() % (U64)max);
}

#ifdef _WIN32
__declspec(dllexport)
#endif
int
get_last_search_info(int what)
{
    if (what == 0)
        return g_last_search_depth;
    if (what == 1)
        return g_last_search_nodes;
    if (what == 2)
        return g_last_best_score;
    if (what >= 100 && what < 164)
        return g_depth_nodes[what - 100];
    return 0;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
int
eval_move_score(const char *fen, int from_sq, int to_sq, double time_limit, int max_depth)
{
    ensure_engine_tables_initialized();
    SearchState s;
    board_from_fen(&s.board, fen);
    s.nodes = 0;
    s.start_time = get_time();
    s.time_limit = time_limit;
    s.aborted = 0;
    s.search_history_count = 0;
    s.game_history_count = 0;
    memset(s.killers, 0, sizeof(s.killers));
    memset(s.history, 0, sizeof(s.history));
    s.tt_size = 1 << 20;
    s.tt = (TT_Entry *)calloc(s.tt_size, sizeof(TT_Entry));
    s.tt_generation = 1;

    Board old = s.board;
    int side = s.board.side_to_move;
    int opp = 1 - side;
    U64 to_bb = 1ULL << to_sq;
    int cap = 0;
    if (s.board.pieces[opp][PAWN] & to_bb)
        cap = PAWN;
    else if (s.board.pieces[opp][KNIGHT] & to_bb)
        cap = KNIGHT;
    else if (s.board.pieces[opp][BISHOP] & to_bb)
        cap = BISHOP;
    else if (s.board.pieces[opp][ROOK] & to_bb)
        cap = ROOK;
    else if (s.board.pieces[opp][QUEEN] & to_bb)
        cap = QUEEN;
    else if (s.board.pieces[opp][KING] & to_bb)
        cap = KING;
    int from_pt = piece_on_square(&s.board, from_sq);
    int promotion = 0;
    if (from_pt == PAWN)
    {
        if ((side == WHITE && rank_of(to_sq) == 7) || (side == BLACK && rank_of(to_sq) == 0))
            promotion = QUEEN;
    }
    Move m = {from_sq, to_sq, promotion, cap, 0};
    UndoInfo undo;
    make_move(&s.board, &m, &undo);
    if (is_check(&s.board, side))
    {
        unmake_move(&s.board, &m, &undo);
        free(s.tt);
        return -INF - 1;
    }
    int score = -negamax(&s, max_depth - 1, -INF, INF, 0, 1);
    unmake_move(&s.board, &m, &undo);
    free(s.tt);
    return score;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
int
generate_pseudo_legal_moves(const Board *b, Move *moves)
{
    int count = 0;
    int side = b->side_to_move;
    int opp = 1 - side;
    U64 own = side_pieces(b, side);
    U64 enemy = side_pieces(b, opp);
    U64 occupied = own | enemy;
    U64 empty = ~occupied;

    U64 pawns = b->pieces[side][PAWN];
    while (pawns)
    {
        int sq = __builtin_ctzll(pawns);
        pawns &= pawns - 1;
        int r = rank_of(sq), f = file_of(sq);
        if (side == WHITE)
        {
            int to = sq + 8;
            if (to < 64 && !(occupied & (1ULL << to)))
            {
                if (rank_of(to) == 7)
                {
                    int prom;
                    for (prom = QUEEN; prom >= KNIGHT; prom--)
                    {
                        if (prom == KING)
                            continue;
                        moves[count++] = (Move){sq, to, prom, 0, 0};
                    }
                }
                else
                {
                    moves[count++] = (Move){sq, to, 0, 0, 0};
                }
                if (r == 1)
                {
                    int to2 = sq + 16;
                    if (!(occupied & (1ULL << to2)))
                    {
                        moves[count++] = (Move){sq, to2, 0, 0, 0};
                    }
                }
            }
            if (f > 0)
            {
                int to = sq + 7;
                if ((enemy & (1ULL << to)) || (b->en_passant == to))
                {
                    int cap = (b->en_passant == to) ? PAWN : piece_on_square(b, to);
                    if (rank_of(to) == 7)
                    {
                        int prom;
                        for (prom = QUEEN; prom >= KNIGHT; prom--)
                        {
                            if (prom == KING)
                                continue;
                            moves[count++] = (Move){sq, to, prom, cap, 0};
                        }
                    }
                    else
                    {
                        moves[count++] = (Move){sq, to, 0, cap, 0};
                    }
                }
            }
            if (f < 7)
            {
                int to = sq + 9;
                if ((enemy & (1ULL << to)) || (b->en_passant == to))
                {
                    int cap = (b->en_passant == to) ? PAWN : piece_on_square(b, to);
                    if (rank_of(to) == 7)
                    {
                        int prom;
                        for (prom = QUEEN; prom >= KNIGHT; prom--)
                        {
                            if (prom == KING)
                                continue;
                            moves[count++] = (Move){sq, to, prom, cap, 0};
                        }
                    }
                    else
                    {
                        moves[count++] = (Move){sq, to, 0, cap, 0};
                    }
                }
            }
        }
        else
        {
            int to = sq - 8;
            if (to >= 0 && !(occupied & (1ULL << to)))
            {
                if (rank_of(to) == 0)
                {
                    int prom;
                    for (prom = QUEEN; prom >= KNIGHT; prom--)
                    {
                        if (prom == KING)
                            continue;
                        moves[count++] = (Move){sq, to, prom, 0, 0};
                    }
                }
                else
                {
                    moves[count++] = (Move){sq, to, 0, 0, 0};
                }
                if (r == 6)
                {
                    int to2 = sq - 16;
                    if (!(occupied & (1ULL << to2)))
                    {
                        moves[count++] = (Move){sq, to2, 0, 0, 0};
                    }
                }
            }
            if (f > 0)
            {
                int to = sq - 9;
                if ((enemy & (1ULL << to)) || (b->en_passant == to))
                {
                    int cap = (b->en_passant == to) ? PAWN : piece_on_square(b, to);
                    if (rank_of(to) == 0)
                    {
                        int prom;
                        for (prom = QUEEN; prom >= KNIGHT; prom--)
                        {
                            if (prom == KING)
                                continue;
                            moves[count++] = (Move){sq, to, prom, cap, 0};
                        }
                    }
                    else
                    {
                        moves[count++] = (Move){sq, to, 0, cap, 0};
                    }
                }
            }
            if (f < 7)
            {
                int to = sq - 7;
                if ((enemy & (1ULL << to)) || (b->en_passant == to))
                {
                    int cap = (b->en_passant == to) ? PAWN : piece_on_square(b, to);
                    if (rank_of(to) == 0)
                    {
                        int prom;
                        for (prom = QUEEN; prom >= KNIGHT; prom--)
                        {
                            if (prom == KING)
                                continue;
                            moves[count++] = (Move){sq, to, prom, cap, 0};
                        }
                    }
                    else
                    {
                        moves[count++] = (Move){sq, to, 0, cap, 0};
                    }
                }
            }
        }
    }

    U64 knights = b->pieces[side][KNIGHT];
    while (knights)
    {
        int sq = __builtin_ctzll(knights);
        knights &= knights - 1;
        U64 att = knight_attacks[sq] & ~own;
        while (att)
        {
            int to = __builtin_ctzll(att);
            att &= att - 1;
            int cap = (enemy & (1ULL << to)) ? piece_on_square(b, to) : 0;
            moves[count++] = (Move){sq, to, 0, cap, 0};
        }
    }

    U64 bishops = b->pieces[side][BISHOP];
    while (bishops)
    {
        int sq = __builtin_ctzll(bishops);
        bishops &= bishops - 1;
        U64 att = sliding_attacks_bishop(sq, occupied) & ~own;
        while (att)
        {
            int to = __builtin_ctzll(att);
            att &= att - 1;
            int cap = (enemy & (1ULL << to)) ? piece_on_square(b, to) : 0;
            moves[count++] = (Move){sq, to, 0, cap, 0};
        }
    }

    U64 rooks = b->pieces[side][ROOK];
    while (rooks)
    {
        int sq = __builtin_ctzll(rooks);
        rooks &= rooks - 1;
        U64 att = sliding_attacks_rook(sq, occupied) & ~own;
        while (att)
        {
            int to = __builtin_ctzll(att);
            att &= att - 1;
            int cap = (enemy & (1ULL << to)) ? piece_on_square(b, to) : 0;
            moves[count++] = (Move){sq, to, 0, cap, 0};
        }
    }

    U64 queens = b->pieces[side][QUEEN];
    while (queens)
    {
        int sq = __builtin_ctzll(queens);
        queens &= queens - 1;
        U64 att = (sliding_attacks_bishop(sq, occupied) | sliding_attacks_rook(sq, occupied)) & ~own;
        while (att)
        {
            int to = __builtin_ctzll(att);
            att &= att - 1;
            int cap = (enemy & (1ULL << to)) ? piece_on_square(b, to) : 0;
            moves[count++] = (Move){sq, to, 0, cap, 0};
        }
    }

    int king_sq = -1;
    U64 kbb = b->pieces[side][KING];
    while (kbb)
    {
        king_sq = __builtin_ctzll(kbb);
        kbb &= kbb - 1;
    }
    if (king_sq >= 0)
    {
        U64 att = king_attacks[king_sq] & ~own;
        while (att)
        {
            int to = __builtin_ctzll(att);
            att &= att - 1;
            int cap = (enemy & (1ULL << to)) ? piece_on_square(b, to) : 0;
            moves[count++] = (Move){king_sq, to, 0, cap, 0};
        }

        if (side == WHITE)
        {
            if ((b->castling_rights & 1) && !(occupied & ((1ULL << 5) | (1ULL << 6))))
            {
                if (!is_square_attacked(b, 4, BLACK) && !is_square_attacked(b, 5, BLACK))
                    moves[count++] = (Move){4, 6, 0, 0, 0};
            }
            if ((b->castling_rights & 2) && !(occupied & ((1ULL << 1) | (1ULL << 2) | (1ULL << 3))))
            {
                if (!is_square_attacked(b, 4, BLACK) && !is_square_attacked(b, 3, BLACK))
                    moves[count++] = (Move){4, 2, 0, 0, 0};
            }
        }
        else
        {
            if ((b->castling_rights & 4) && !(occupied & ((1ULL << 61) | (1ULL << 62))))
            {
                if (!is_square_attacked(b, 60, WHITE) && !is_square_attacked(b, 61, WHITE))
                    moves[count++] = (Move){60, 62, 0, 0, 0};
            }
            if ((b->castling_rights & 8) && !(occupied & ((1ULL << 57) | (1ULL << 58) | (1ULL << 59))))
            {
                if (!is_square_attacked(b, 60, WHITE) && !is_square_attacked(b, 59, WHITE))
                    moves[count++] = (Move){60, 58, 0, 0, 0};
            }
        }
    }

    return count;
}

int generate_legal_moves(const Board *b, Move *moves)
{
    ensure_engine_tables_initialized();
    Move pseudo[MAX_MOVES];
    int n = generate_pseudo_legal_moves(b, pseudo);
    int count = 0;
    int i;
    for (i = 0; i < n; i++)
    {
        UndoInfo undo;
        Board copy = *b;
        make_move(&copy, &pseudo[i], &undo);
        if (!is_check(&copy, b->side_to_move))
        {
            moves[count++] = pseudo[i];
        }
    }
    return count;
}

static int npm_piece_value(int pt)
{
    if (pt == KNIGHT)
        return 3;
    if (pt == BISHOP)
        return 3;
    if (pt == ROOK)
        return 5;
    if (pt == QUEEN)
        return 9;
    return 0;
}

void make_move(Board *b, const Move *m, UndoInfo *undo)
{
    int side = b->side_to_move;
    int opp = 1 - side;
    U64 from_bb = 1ULL << m->from;
    U64 to_bb = 1ULL << m->to;
    int pt = piece_on_square(b, m->from);
    if (pt == EMPTY)
        return;

    undo->castling_rights = b->castling_rights;
    undo->en_passant = b->en_passant;
    undo->halfmove_clock = b->halfmove_clock;
    undo->fullmove_number = b->fullmove_number;
    undo->hash = b->hash;
    undo->pawn_hash = b->pawn_hash;
    undo->eval_score = b->eval_score;
    undo->phase = b->phase;
    undo->king_sq[0] = b->king_sq[0];
    undo->king_sq[1] = b->king_sq[1];
    undo->npm[0] = b->npm[0];
    undo->npm[1] = b->npm[1];
    undo->mailbox_from = b->mailbox[m->from];
    undo->mailbox_to = b->mailbox[m->to];
    undo->mailbox_ep = 0;
    undo->ep_capture_sq = -1;
    undo->captured_piece = 0;

    int old_castling = b->castling_rights;
    int old_ep = b->en_passant;

    b->hash ^= zobrist_table[12 * 64];

    if (old_ep >= 0 && old_ep < 64)
    {
        int castling_base = 12 * 64 + 1;
        b->hash ^= zobrist_table[castling_base + 4 + old_ep];
    }

    b->pieces[side][pt] &= ~from_bb;
    b->pieces[side][pt] |= to_bb;
    b->mailbox[m->from] = 0;
    b->mailbox[m->to] = side * 6 + pt;

    b->hash ^= zobrist_table[((side * 6 + (pt - 1)) * 64 + m->from)];
    b->hash ^= zobrist_table[((side * 6 + (pt - 1)) * 64 + m->to)];

    if (pt == PAWN)
    {
        b->pawn_hash ^= zobrist_table[((side * 6 + 0) * 64 + m->from)];
        b->pawn_hash ^= zobrist_table[((side * 6 + 0) * 64 + m->to)];
    }

    if (m->capture)
    {
        int cap_pt = m->capture;
        b->pieces[opp][cap_pt] &= ~to_bb;
        undo->captured_piece = cap_pt;

        b->hash ^= zobrist_table[((opp * 6 + (cap_pt - 1)) * 64 + m->to)];

        if (cap_pt == PAWN)
        {
            b->pawn_hash ^= zobrist_table[((opp * 6 + 0) * 64 + m->to)];
        }
        else
        {
            b->npm[opp] -= npm_piece_value(cap_pt);
        }
    }

    if (m->promotion)
    {
        b->pieces[side][PAWN] &= ~to_bb;
        b->pieces[side][m->promotion] |= to_bb;
        b->mailbox[m->to] = side * 6 + m->promotion;

        b->hash ^= zobrist_table[((side * 6 + 0) * 64 + m->to)];
        b->hash ^= zobrist_table[((side * 6 + (m->promotion - 1)) * 64 + m->to)];

        b->pawn_hash ^= zobrist_table[((side * 6 + 0) * 64 + m->to)];

        b->npm[side] += npm_piece_value(m->promotion);
    }

    if (pt == KING)
    {
        b->king_sq[side] = m->to;

        if (side == WHITE)
        {
            if (m->from == 4 && m->to == 6)
            {
                b->pieces[WHITE][ROOK] &= ~(1ULL << 7);
                b->pieces[WHITE][ROOK] |= (1ULL << 5);
                b->mailbox[7] = 0;
                b->mailbox[5] = WHITE * 6 + ROOK;
                b->hash ^= zobrist_table[((0 * 6 + 3) * 64 + 7)];
                b->hash ^= zobrist_table[((0 * 6 + 3) * 64 + 5)];
            }
            else if (m->from == 4 && m->to == 2)
            {
                b->pieces[WHITE][ROOK] &= ~(1ULL << 0);
                b->pieces[WHITE][ROOK] |= (1ULL << 3);
                b->mailbox[0] = 0;
                b->mailbox[3] = WHITE * 6 + ROOK;
                b->hash ^= zobrist_table[((0 * 6 + 3) * 64 + 0)];
                b->hash ^= zobrist_table[((0 * 6 + 3) * 64 + 3)];
            }
            b->castling_rights &= ~3;
        }
        else
        {
            if (m->from == 60 && m->to == 62)
            {
                b->pieces[BLACK][ROOK] &= ~(1ULL << 63);
                b->pieces[BLACK][ROOK] |= (1ULL << 61);
                b->mailbox[63] = 0;
                b->mailbox[61] = BLACK * 6 + ROOK;
                b->hash ^= zobrist_table[((1 * 6 + 3) * 64 + 63)];
                b->hash ^= zobrist_table[((1 * 6 + 3) * 64 + 61)];
            }
            else if (m->from == 60 && m->to == 58)
            {
                b->pieces[BLACK][ROOK] &= ~(1ULL << 56);
                b->pieces[BLACK][ROOK] |= (1ULL << 59);
                b->mailbox[56] = 0;
                b->mailbox[59] = BLACK * 6 + ROOK;
                b->hash ^= zobrist_table[((1 * 6 + 3) * 64 + 56)];
                b->hash ^= zobrist_table[((1 * 6 + 3) * 64 + 59)];
            }
            b->castling_rights &= ~12;
        }
    }

    if (pt == ROOK)
    {
        if (side == WHITE)
        {
            if (m->from == 0)
                b->castling_rights &= ~2;
            else if (m->from == 7)
                b->castling_rights &= ~1;
        }
        else
        {
            if (m->from == 56)
                b->castling_rights &= ~8;
            else if (m->from == 63)
                b->castling_rights &= ~4;
        }
    }

    if (m->capture == ROOK)
    {
        if (opp == WHITE)
        {
            if (m->to == 0)
                b->castling_rights &= ~2;
            else if (m->to == 7)
                b->castling_rights &= ~1;
        }
        else
        {
            if (m->to == 56)
                b->castling_rights &= ~8;
            else if (m->to == 63)
                b->castling_rights &= ~4;
        }
    }

    if (b->castling_rights != old_castling)
    {
        int castling_base = 12 * 64 + 1;
        int cr;
        for (cr = 0; cr < 4; cr++)
        {
            if ((old_castling ^ b->castling_rights) & (1 << cr))
                b->hash ^= zobrist_table[castling_base + cr];
        }
    }

    if (pt == PAWN && abs(m->to - m->from) == 16)
    {
        b->en_passant = (m->from + m->to) / 2;
    }
    else
    {
        b->en_passant = -1;
    }

    if (b->en_passant >= 0 && b->en_passant < 64)
    {
        int castling_base = 12 * 64 + 1;
        b->hash ^= zobrist_table[castling_base + 4 + b->en_passant];
    }

    if (pt == PAWN && old_ep >= 0 && m->to == old_ep && (abs(m->to - m->from) == 7 || abs(m->to - m->from) == 9))
    {
        int ep_cap_sq = (side == WHITE) ? (m->to - 8) : (m->to + 8);
        if (ep_cap_sq >= 0 && ep_cap_sq < 64)
        {
            b->pieces[opp][PAWN] &= ~(1ULL << ep_cap_sq);
            undo->mailbox_ep = b->mailbox[ep_cap_sq];
            undo->ep_capture_sq = ep_cap_sq;
            b->mailbox[ep_cap_sq] = 0;

            b->hash ^= zobrist_table[((opp * 6 + 0) * 64 + ep_cap_sq)];
            b->pawn_hash ^= zobrist_table[((opp * 6 + 0) * 64 + ep_cap_sq)];
        }
    }

    if (pt == PAWN || m->capture)
    {
        b->halfmove_clock = 0;
    }
    else
    {
        b->halfmove_clock++;
    }

    if (side == BLACK)
    {
        b->fullmove_number++;
    }

    {
        int phase_raw = b->npm[0] + b->npm[1];
        if (phase_raw > 31)
            phase_raw = 31;
        b->phase = phase_raw * 24 / 31;
        if (b->phase > 24)
            b->phase = 24;
    }

    b->side_to_move = opp;
    b->eval_score = EVAL_SCORE_INVALID;
}

void unmake_move(Board *b, const Move *m, const UndoInfo *undo)
{
    int side = 1 - b->side_to_move;
    int opp = 1 - side;
    U64 from_bb = 1ULL << m->from;
    U64 to_bb = 1ULL << m->to;

    int moved_code = undo->mailbox_from;
    int moved_pt = ((moved_code - 1) % 6) + 1;

    if (m->promotion)
    {
        b->pieces[side][m->promotion] &= ~to_bb;
        b->pieces[side][PAWN] |= from_bb;
    }
    else
    {
        b->pieces[side][moved_pt] &= ~to_bb;
        b->pieces[side][moved_pt] |= from_bb;
    }

    if (m->capture && undo->ep_capture_sq < 0)
    {
        b->pieces[opp][m->capture] |= to_bb;
    }

    if (undo->ep_capture_sq >= 0)
    {
        b->pieces[opp][PAWN] |= (1ULL << undo->ep_capture_sq);
    }

    if (moved_pt == KING)
    {
        if (side == WHITE)
        {
            if (m->from == 4 && m->to == 6)
            {
                b->pieces[WHITE][ROOK] &= ~(1ULL << 5);
                b->pieces[WHITE][ROOK] |= (1ULL << 7);
            }
            else if (m->from == 4 && m->to == 2)
            {
                b->pieces[WHITE][ROOK] &= ~(1ULL << 3);
                b->pieces[WHITE][ROOK] |= (1ULL << 0);
            }
        }
        else
        {
            if (m->from == 60 && m->to == 62)
            {
                b->pieces[BLACK][ROOK] &= ~(1ULL << 61);
                b->pieces[BLACK][ROOK] |= (1ULL << 63);
            }
            else if (m->from == 60 && m->to == 58)
            {
                b->pieces[BLACK][ROOK] &= ~(1ULL << 59);
                b->pieces[BLACK][ROOK] |= (1ULL << 56);
            }
        }
    }

    b->castling_rights = undo->castling_rights;
    b->en_passant = undo->en_passant;
    b->halfmove_clock = undo->halfmove_clock;
    b->fullmove_number = undo->fullmove_number;
    b->hash = undo->hash;
    b->pawn_hash = undo->pawn_hash;
    b->eval_score = undo->eval_score;
    b->phase = undo->phase;
    b->king_sq[0] = undo->king_sq[0];
    b->king_sq[1] = undo->king_sq[1];
    b->npm[0] = undo->npm[0];
    b->npm[1] = undo->npm[1];
    b->side_to_move = side;

    b->mailbox[m->from] = undo->mailbox_from;
    b->mailbox[m->to] = undo->mailbox_to;

    if (undo->ep_capture_sq >= 0)
    {
        b->mailbox[undo->ep_capture_sq] = undo->mailbox_ep;
    }

    if (moved_pt == KING)
    {
        if (side == WHITE)
        {
            if (m->from == 4 && m->to == 6)
            {
                b->mailbox[5] = 0;
                b->mailbox[7] = WHITE * 6 + ROOK;
            }
            else if (m->from == 4 && m->to == 2)
            {
                b->mailbox[3] = 0;
                b->mailbox[0] = WHITE * 6 + ROOK;
            }
        }
        else
        {
            if (m->from == 60 && m->to == 62)
            {
                b->mailbox[61] = 0;
                b->mailbox[63] = BLACK * 6 + ROOK;
            }
            else if (m->from == 60 && m->to == 58)
            {
                b->mailbox[59] = 0;
                b->mailbox[56] = BLACK * 6 + ROOK;
            }
        }
    }
}

U64 get_attacks(const Board *b, int sq, int side)
{
    int pt = piece_on_square(b, sq);
    if (pt == EMPTY)
        return 0;
    U64 occupied = all_pieces(b);
    switch (pt)
    {
    case PAWN:
    {
        U64 bb = 1ULL << sq;
        if (side == WHITE)
        {
            return (shift_north(shift_east(bb)) | shift_north(shift_west(bb)));
        }
        else
        {
            return (shift_south(shift_east(bb)) | shift_south(shift_west(bb)));
        }
    }
    case KNIGHT:
        return knight_attacks[sq];
    case BISHOP:
        return sliding_attacks_bishop(sq, occupied);
    case ROOK:
        return sliding_attacks_rook(sq, occupied);
    case QUEEN:
        return sliding_attacks_bishop(sq, occupied) | sliding_attacks_rook(sq, occupied);
    case KING:
        return king_attacks[sq];
    }
    return 0;
}

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
    int npm_w = 0, npm_b = 0;

    for (side = 0; side < 2; side++)
    {
        for (pt = KNIGHT; pt <= QUEEN; pt++)
        {
            int c = count_bits(b->pieces[side][pt]);
            if (side == WHITE)
                npm_w += c * (pt == KNIGHT ? 3 : pt == BISHOP ? 3
                                             : pt == ROOK     ? 5
                                                              : 9);
            else
                npm_b += c * (pt == KNIGHT ? 3 : pt == BISHOP ? 3
                                             : pt == ROOK     ? 5
                                                              : 9);
        }
    }

    int phase = (npm_w + npm_b);
    if (phase > 31)
        phase = 31;
    phase = phase * 24 / 31;
    if (phase > 24)
        phase = 24;

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
                int psq = (side == WHITE) ? sq : (sq ^ 56);
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
                score += sign * (DOUBLED_PAWN_PENALTY * (files[f] - 1));
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
                score += sign * ISOLATED_PAWN_PENALTY;

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
                int eg_scale = (24 - phase) / 6;
                int eg_bonus;
                int promotion_threat = 0;
                int promo_sq;
                int promo_sq_attacked;
                if (eg_scale > 3)
                    eg_scale = 3;
                eg_bonus = bonus * eg_scale / 6;
                score += sign * (bonus + eg_bonus);
                if (bonus_rank >= 5)
                {
                    promotion_threat = (bonus_rank == 6) ? 150 : 50;
                    score += sign * promotion_threat;
                }
                if (side == WHITE)
                    promo_sq = 56 + f;
                else
                    promo_sq = f;
                promo_sq_attacked = is_square_attacked(b, promo_sq, 1 - side);
                if (promo_sq_attacked)
                {
                    score -= sign * (bonus + eg_bonus) / 2;
                    if (bonus_rank >= 5)
                        score -= sign * promotion_threat / 2;
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
                    score += sign * 10;
                else if (side == BLACK && (sq == 35 || sq == 36))
                    score += sign * 10;
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
        while (rooks)
        {
            int sq = lsb_index(rooks);
            rooks &= rooks - 1;
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

        U64 own_rooks = b->pieces[side][ROOK];
        if (own_rooks)
        {
            int f;
            for (f = 0; f < 8; f++)
            {
                U64 file_mask = 0x0101010101010101ULL << f;
                if (!(own_pawns & file_mask) && !(enemy_pawns & file_mask))
                {
                    if (!(own_rooks & file_mask))
                    {
                        score += sign * ROOK_POTENTIAL_OPEN_FILE;
                    }
                }
                else if (!(own_pawns & file_mask) && (enemy_pawns & file_mask))
                {
                    if (!(own_rooks & file_mask))
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
        U64 rooks = b->pieces[side][ROOK];
        U64 target_rank = (side == WHITE) ? 0x00FF000000000000ULL : 0x000000000000FF00ULL;
        int rooks_on_7th = count_bits(rooks & target_rank);
        if (rooks_on_7th > 0)
        {
            U64 enemy_king = b->pieces[1 - side][KING];
            int ek_sq = -1;
            if (enemy_king)
                ek_sq = lsb_index(enemy_king);
            int ek_rank = (ek_sq >= 0) ? ek_sq / 8 : -1;
            int enemy_king_on_8th = (side == WHITE) ? (ek_rank == 7) : (ek_rank == 0);
            score += sign * (ROOK_ON_7TH_BONUS + (enemy_king_on_8th ? ROOK_ON_7TH_WITH_KING : 0)) * rooks_on_7th;
        }
    }

    for (side = 0; side < 2; side++)
    {
        int sign = (side == WHITE) ? 1 : -1;
        int king_sq = -1;
        U64 kbb = b->pieces[side][KING];
        if (kbb)
            king_sq = lsb_index(kbb);
        if (king_sq < 0)
            continue;
        U64 around = king_attacks[king_sq];
        around |= (1ULL << king_sq);
        int attack_weight = 0;
        int sq;
        for (sq = 0; sq < 64; sq++)
        {
            if (around & (1ULL << sq))
            {
                int opp = 1 - side;
                U64 enemy_queens = b->pieces[opp][QUEEN];
                U64 enemy_rooks = b->pieces[opp][ROOK];
                U64 enemy_bishops = b->pieces[opp][BISHOP];
                U64 enemy_knights = b->pieces[opp][KNIGHT];
                U64 enemy_pawns = b->pieces[opp][PAWN];
                U64 enemy_king_bb = b->pieces[opp][KING];
                U64 occ = side_pieces(b, 0) | side_pieces(b, 1);

                if (enemy_queens && (sliding_attacks_rook(sq, occ) & enemy_queens))
                    attack_weight += 4;
                if (enemy_queens && (sliding_attacks_bishop(sq, occ) & enemy_queens))
                    attack_weight += 4;
                if (enemy_rooks && (sliding_attacks_rook(sq, occ) & enemy_rooks))
                    attack_weight += 3;
                if (enemy_bishops && (sliding_attacks_bishop(sq, occ) & enemy_bishops))
                    attack_weight += 2;
                if (enemy_knights && (knight_attacks[sq] & enemy_knights))
                    attack_weight += 1;
                if (enemy_pawns)
                {
                    if (opp == WHITE)
                    {
                        if (sq >= 9 && (sq % 8) > 0 && (enemy_pawns & (1ULL << (sq - 9))))
                            attack_weight += 1;
                        if (sq >= 7 && (sq % 8) < 7 && (enemy_pawns & (1ULL << (sq - 7))))
                            attack_weight += 1;
                    }
                    else
                    {
                        if (sq <= 54 && (sq % 8) > 0 && (enemy_pawns & (1ULL << (sq + 7))))
                            attack_weight += 1;
                        if (sq <= 56 && (sq % 8) < 7 && (enemy_pawns & (1ULL << (sq + 9))))
                            attack_weight += 1;
                    }
                }
                if (enemy_king_bb && (king_attacks[sq] & enemy_king_bb))
                    attack_weight += 1;
            }
        }
        score += sign * (-5 * attack_weight * (phase < 8 ? 3 : 10) / 10);

        {
            int defenders = 0;
            U64 around_king = king_attacks[king_sq] | (1ULL << king_sq);
            U64 own_pieces = side_pieces(b, side);
            U64 own_defenders = around_king & own_pieces;
            defenders = count_bits(own_defenders);

            U64 enemy_heavy = b->pieces[1 - side][QUEEN] | b->pieces[1 - side][ROOK];
            if (enemy_heavy && defenders < 3)
            {
                int exposure_penalty = (3 - defenders) * 30;
                if (phase >= 8)
                {
                    score += sign * (-exposure_penalty);
                }
            }
        }

        int kf = file_of(king_sq);
        int f;
        for (f = kf - 1; f <= kf + 1; f++)
        {
            if (f < 0 || f > 7)
                continue;
            U64 file_mask = 0x0101010101010101ULL << f;
            U64 own_pawns_on_file = b->pieces[side][PAWN] & file_mask;
            U64 enemy_pawns_on_file = b->pieces[1 - side][PAWN] & file_mask;
            if (own_pawns_on_file == 0 && enemy_pawns_on_file == 0)
            {
                U64 enemy_rq = (b->pieces[1 - side][ROOK] | b->pieces[1 - side][QUEEN]) & file_mask;
                if (enemy_rq)
                {
                    score += sign * (-25);
                }
            }
        }

        int shield_bonus = 0;
        int kr = rank_of(king_sq);
        if (side == WHITE && kr <= 1)
        {
            int shield_count = 0;
            U64 wp = b->pieces[WHITE][PAWN];
            int df;
            for (df = -1; df <= 1; df++)
            {
                int af = kf + df;
                if (af < 0 || af > 7)
                    continue;
                int r;
                for (r = 2; r <= 3; r++)
                {
                    int sq2 = r * 8 + af;
                    if (wp & (1ULL << sq2))
                    {
                        shield_count++;
                        break;
                    }
                }
            }
            if (shield_count >= 3)
                shield_bonus = 30;
            else if (shield_count >= 2)
                shield_bonus = 15;
            else if (shield_count == 1)
                shield_bonus = -10;
            else
                shield_bonus = -30;
        }
        else if (side == BLACK && kr >= 6)
        {
            int shield_count = 0;
            U64 bp = b->pieces[BLACK][PAWN];
            int df;
            for (df = -1; df <= 1; df++)
            {
                int af = kf + df;
                if (af < 0 || af > 7)
                    continue;
                int r;
                for (r = 4; r <= 5; r++)
                {
                    int sq2 = r * 8 + af;
                    if (bp & (1ULL << sq2))
                    {
                        shield_count++;
                        break;
                    }
                }
            }
            if (shield_count >= 3)
                shield_bonus = 30;
            else if (shield_count >= 2)
                shield_bonus = 15;
            else if (shield_count == 1)
                shield_bonus = -10;
            else
                shield_bonus = -30;
        }
        score += sign * shield_bonus;
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
                for (r = 0; r < 8; r++)
                {
                    int sq2 = r * 8 + af;
                    if (b->pieces[side][PAWN] & (1ULL << sq2))
                    {
                        if ((side == WHITE && r <= 2) || (side == BLACK && r >= 5))
                            blocked = 1;
                        else
                            blocked = 0;
                        break;
                    }
                }
                if (!blocked)
                    break;
            }
            if (blocked)
            {
                U64 enemy_rq = b->pieces[opp][ROOK] | b->pieces[opp][QUEEN];
                U64 back_rank = (side == WHITE) ? rank_masks[0] : rank_masks[7];
                U64 second_rank = (side == WHITE) ? rank_masks[1] : rank_masks[6];
                U64 occ = all_pieces(b);
                U64 rq_on_back = 0;
                U64 temp = enemy_rq;
                while (temp)
                {
                    int rsq = lsb_index(temp);
                    temp &= temp - 1;
                    int rr = rank_of(rsq);
                    if ((side == WHITE && rr == 7) || (side == BLACK && rr == 0))
                    {
                        U64 attacks = sliding_attacks_rook(rsq, occ);
                        if (attacks & (back_rank | second_rank))
                            rq_on_back |= (1ULL << rsq);
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

            int is_outpost = 0;
            if ((r >= 3 && r <= 5) && (f >= 2 && f <= 5))
            {
                if (defended_by_pawn && !can_be_attacked_by_pawn)
                    is_outpost = 1;
            }

            if (is_outpost)
                score += sign * 45; /* TODO: Add KNIGHT_OUTPOST_BONUS to engine_params.h */

            if (f == 0 || f == 7)
            {
                if (r >= 2 && r <= 5)
                    score += sign * (-30);
            }
        }

        U64 own_minor_major = b->pieces[side][KNIGHT] | b->pieces[side][BISHOP] |
                              b->pieces[side][ROOK] | b->pieces[side][QUEEN];
        U64 attacked_by_pawn = own_minor_major & enemy_pawn_attacks;
        U64 attacked_by_knight = own_minor_major & enemy_knight_attacks & ~enemy_pawn_attacks;
        U64 defended_by_own_pawn = own_minor_major & own_pawn_defense;

        U64 queens_attacked_by_pawn = attacked_by_pawn & b->pieces[side][QUEEN];
        U64 rooks_attacked_by_pawn = attacked_by_pawn & b->pieces[side][ROOK];
        U64 minors_attacked_by_pawn = attacked_by_pawn & ~(queens_attacked_by_pawn | rooks_attacked_by_pawn);
        score += sign * (-50 * count_bits(queens_attacked_by_pawn));
        score += sign * (-40 * count_bits(rooks_attacked_by_pawn));
        score += sign * (-30 * count_bits(minors_attacked_by_pawn));
        score += sign * (-10 * count_bits(queens_attacked_by_pawn));
        score += sign * (-5 * count_bits(rooks_attacked_by_pawn));

        U64 queens_attacked_by_knight = attacked_by_knight & b->pieces[side][QUEEN];
        U64 rooks_attacked_by_knight = attacked_by_knight & b->pieces[side][ROOK];
        U64 minors_attacked_by_knight = attacked_by_knight & ~(queens_attacked_by_knight | rooks_attacked_by_knight);
        score += sign * (-40 * count_bits(queens_attacked_by_knight));
        score += sign * (-30 * count_bits(rooks_attacked_by_knight));
        score += sign * (-25 * count_bits(minors_attacked_by_knight));

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
                score += sign * (-150);
            U64 forked_with_king = k_attacks & b->pieces[side][KING];
            if (forked_with_king && count_bits(forked_valuable) >= 1)
                score += sign * (-120);
        }

        U64 queens = b->pieces[side][QUEEN];
        while (queens)
        {
            int sq = lsb_index(queens);
            queens &= queens - 1;
            int attacked_by_lesser = 0;
            U64 occ = all_pieces(b);
            if (b->pieces[opp][KNIGHT] && (knight_attacks[sq] & b->pieces[opp][KNIGHT]))
                attacked_by_lesser = 1;
            if (b->pieces[opp][BISHOP] && (sliding_attacks_bishop(sq, occ) & b->pieces[opp][BISHOP]))
                attacked_by_lesser = 1;
            if (b->pieces[opp][ROOK] && (sliding_attacks_rook(sq, occ) & b->pieces[opp][ROOK]))
                attacked_by_lesser = 1;
            if (attacked_by_lesser)
            {
                if (!defended_by_own_pawn || !(own_pawn_defense & (1ULL << sq)))
                    score += sign * (-150);
                else
                    score += sign * (-60);
            }
        }

        U64 rooks = b->pieces[side][ROOK];
        while (rooks)
        {
            int sq = lsb_index(rooks);
            rooks &= rooks - 1;
            int rook_attacked_by_lesser = 0;
            U64 occ = all_pieces(b);
            if (b->pieces[opp][KNIGHT] && (knight_attacks[sq] & b->pieces[opp][KNIGHT]))
                rook_attacked_by_lesser = 1;
            if (b->pieces[opp][BISHOP] && (sliding_attacks_bishop(sq, occ) & b->pieces[opp][BISHOP]))
                rook_attacked_by_lesser = 1;
            if (rook_attacked_by_lesser)
            {
                if (!defended_by_own_pawn || !(own_pawn_defense & (1ULL << sq)))
                    score += sign * (-80);
                else
                    score += sign * (-30);
            }
        }
    }

    if (b->fullmove_number <= 15)
    {
        for (side = 0; side < 2; side++)
        {
            int sign = (side == WHITE) ? 1 : -1;
            if (b->pieces[side][KNIGHT] & (1ULL << (side == WHITE ? 1 : 57)))
                score += sign * (-35);
            if (b->pieces[side][KNIGHT] & (1ULL << (side == WHITE ? 6 : 62)))
                score += sign * (-35);
            if (b->pieces[side][BISHOP] & (1ULL << (side == WHITE ? 2 : 58)))
                score += sign * (-35);
            if (b->pieces[side][BISHOP] & (1ULL << (side == WHITE ? 5 : 61)))
                score += sign * (-35);
            if (b->pieces[side][QUEEN] & (1ULL << (side == WHITE ? 3 : 59)))
                score += sign * (-20);

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

    if (phase <= ENDGAME_PHASE_THRESHOLD)
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
                int activity_weight = (phase < 8) ? 25 : KING_ACTIVITY_WEIGHT;
                int activity_bonus = (6 - center_dist) * activity_weight;
                score += sign * activity_bonus;
            }
        }
    }

    /* Simplification bonus: encourage side with material advantage to exchange pieces */
    {
        int white_non_pawn_material = 0;
        int black_non_pawn_material = 0;
        for (pt = KNIGHT; pt <= QUEEN; pt++)
        {
            white_non_pawn_material += count_bits(b->pieces[WHITE][pt]) * piece_values[pt];
            black_non_pawn_material += count_bits(b->pieces[BLACK][pt]) * piece_values[pt];
        }
        int material_balance = white_non_pawn_material - black_non_pawn_material;
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
        int stm = b->side_to_move;
        int my_king_sq = -1;
        U64 my_king_bb = b->pieces[stm][KING];
        if (my_king_bb)
            my_king_sq = lsb_index(my_king_bb);

        if (my_king_sq >= 0 && is_check(b, stm))
        {
            Move escape_moves[MAX_MOVES];
            int n_escape = generate_pseudo_legal_moves(b, escape_moves);
            int legal_escape = 0;
            int ei;
            for (ei = 0; ei < n_escape; ei++)
            {
                UndoInfo undo;
                Board copy = *b;
                make_move(&copy, &escape_moves[ei], &undo);
                if (!is_check(&copy, stm))
                    legal_escape++;
            }
            if (legal_escape == 0)
            {
                score = (stm == WHITE) ? -MATE_SCORE + 100 : MATE_SCORE - 100;
            }
            else if (legal_escape <= 2)
            {
                int penalty = 200 - legal_escape * 50;
                score += (stm == WHITE) ? -penalty : penalty;
            }
        }
    }

    assert(score > -MATE_SCORE && score < MATE_SCORE && "Evaluation score out of valid range");

    b->eval_score = score;
    return score;
}

int is_game_over(const Board *b)
{
    Move moves[MAX_MOVES];
    int n = generate_legal_moves(b, moves);
    return n == 0;
}

static U64 compute_hash(const Board *b)
{
    if (!zobrist_initialized)
        init_zobrist();
    U64 h = 0;
    int side, pt, sq;
    for (side = 0; side < 2; side++)
    {
        for (pt = PAWN; pt <= KING; pt++)
        {
            U64 bb = b->pieces[side][pt];
            while (bb)
            {
                sq = lsb_index(bb);
                bb &= bb - 1;
                int idx = ((side * 6 + (pt - 1)) * 64 + sq);
                h ^= zobrist_table[idx];
            }
        }
    }
    if (b->side_to_move == BLACK)
    {
        h ^= zobrist_table[12 * 64];
    }
    int castling_base = 12 * 64 + 1;
    if (b->castling_rights & 1)
        h ^= zobrist_table[castling_base];
    if (b->castling_rights & 2)
        h ^= zobrist_table[castling_base + 1];
    if (b->castling_rights & 4)
        h ^= zobrist_table[castling_base + 2];
    if (b->castling_rights & 8)
        h ^= zobrist_table[castling_base + 3];
    if (b->en_passant >= 0 && b->en_passant < 64)
    {
        h ^= zobrist_table[castling_base + 4 + b->en_passant];
    }
    return h;
}

static int mvv_lva(const Board *b, const Move *m)
{
    /* MVV-LVA: Most Valuable Victim - Least Valuable Attacker */
    /* Using piece values from engine_params.h */
    static const int mvv[7] = {0, PAWN_VALUE, KNIGHT_VALUE, BISHOP_VALUE, ROOK_VALUE, QUEEN_VALUE, KING_VALUE};
    int from_piece = piece_on_square(b, m->from);
    return mvv[m->capture] * 10 - piece_values[from_piece];
}

static int compare_moves_desc(const void *a, const void *b)
{
    const Move *ma = (const Move *)a;
    const Move *mb = (const Move *)b;
    return mb->score - ma->score;
}

static void sort_moves(Move *moves, int n)
{
    qsort(moves, n, sizeof(Move), compare_moves_desc);
}

static int tt_probe(SearchState *s, U64 key, int depth, int alpha, int beta, Move *out_move, int ply, int *out_tt_score)
{
    int idx = (int)(key % s->tt_size);
    TT_Entry *e = &s->tt[idx];
    if (e->key == key && e->depth >= depth)
    {
        *out_move = e->best_move;
        int score = e->score;
        if (score > MATE_SCORE - 100)
            score -= ply;
        else if (score < -MATE_SCORE + 100)
            score += ply;
        if (out_tt_score)
            *out_tt_score = score;
        if (e->flag == 0)
            return score;
        if (e->flag == 1 && score <= alpha)
            return score;
        if (e->flag == 2 && score >= beta)
            return score;
    }
    else if (e->key != 0)
    {
        *out_move = e->best_move;
        if (e->key == key && out_tt_score)
        {
            int score = e->score;
            if (score > MATE_SCORE - 100)
                score -= ply;
            else if (score < -MATE_SCORE + 100)
                score += ply;
            *out_tt_score = score;
        }
    }
    return INF + 1;
}

static void tt_store(SearchState *s, U64 key, int depth, int score, int flag, Move best_move, int ply)
{
    int idx = (int)(key % s->tt_size);
    TT_Entry *e = &s->tt[idx];
    int should_replace = 0;
    if (e->key == 0)
    {
        should_replace = 1;
    }
    else if (e->key == key)
    {
        if (depth >= e->depth)
            should_replace = 1;
    }
    else
    {
        int age_diff = s->tt_generation - e->generation;
        if (age_diff > 0 || depth > e->depth)
            should_replace = 1;
    }
    if (should_replace)
    {
        int adj_score = score;
        if (adj_score > MATE_SCORE - 100)
            adj_score += ply;
        else if (adj_score < -MATE_SCORE + 100)
            adj_score -= ply;
        e->key = key;
        e->depth = depth;
        e->score = adj_score;
        e->flag = flag;
        e->best_move = best_move;
        e->generation = s->tt_generation;
    }
}

static int see_piece_value(int piece)
{
    switch (piece)
    {
    case PAWN:
        return PAWN_VALUE;
    case KNIGHT:
        return KNIGHT_VALUE;
    case BISHOP:
        return BISHOP_VALUE;
    case ROOK:
        return ROOK_VALUE;
    case QUEEN:
        return QUEEN_VALUE;
    case KING:
        return 10000;
    default:
        return 0;
    }
}

static U64 see_attackers(const Board *b, int sq, int side, U64 occupied)
{
    U64 attackers = 0;
    U64 pawns = b->pieces[side][PAWN];
    U64 knights = b->pieces[side][KNIGHT];
    U64 bishops = b->pieces[side][BISHOP];
    U64 rooks = b->pieces[side][ROOK];
    U64 queens = b->pieces[side][QUEEN];
    U64 kings = b->pieces[side][KING];

    if (side == WHITE)
    {
        if (sq >= 8)
        {
            if (file_of(sq) > 0 && (pawns & (1ULL << (sq - 9))))
                attackers |= (1ULL << (sq - 9));
            if (file_of(sq) < 7 && (pawns & (1ULL << (sq - 7))))
                attackers |= (1ULL << (sq - 7));
        }
    }
    else
    {
        if (sq < 56)
        {
            if (file_of(sq) > 0 && (pawns & (1ULL << (sq + 7))))
                attackers |= (1ULL << (sq + 7));
            if (file_of(sq) < 7 && (pawns & (1ULL << (sq + 9))))
                attackers |= (1ULL << (sq + 9));
        }
    }

    attackers |= knights & knight_attacks[sq];
    attackers |= kings & king_attacks[sq];

    U64 diag_attackers = bishops | queens;
    U64 straight_attackers = rooks | queens;
    attackers |= diag_attackers & sliding_attacks_bishop(sq, occupied);
    attackers |= straight_attackers & sliding_attacks_rook(sq, occupied);

    return attackers;
}

static int see_smallest_attacker(const Board *b, int sq, int side, U64 occupied, int *attacker_sq)
{
    U64 pawns = b->pieces[side][PAWN] & occupied;
    U64 knights = b->pieces[side][KNIGHT] & occupied;
    U64 bishops = b->pieces[side][BISHOP] & occupied;
    U64 rooks = b->pieces[side][ROOK] & occupied;
    U64 queens = b->pieces[side][QUEEN] & occupied;
    U64 kings = b->pieces[side][KING] & occupied;

    if (side == WHITE)
    {
        if (sq >= 8)
        {
            if (file_of(sq) > 0 && (pawns & (1ULL << (sq - 9))))
            {
                *attacker_sq = sq - 9;
                return PAWN;
            }
            if (file_of(sq) < 7 && (pawns & (1ULL << (sq - 7))))
            {
                *attacker_sq = sq - 7;
                return PAWN;
            }
        }
    }
    else
    {
        if (sq < 56)
        {
            if (file_of(sq) > 0 && (pawns & (1ULL << (sq + 7))))
            {
                *attacker_sq = sq + 7;
                return PAWN;
            }
            if (file_of(sq) < 7 && (pawns & (1ULL << (sq + 9))))
            {
                *attacker_sq = sq + 9;
                return PAWN;
            }
        }
    }

    U64 knight_attackers = knights & knight_attacks[sq];
    if (knight_attackers)
    {
        *attacker_sq = lsb_index(knight_attackers);
        return KNIGHT;
    }

    U64 diag_attackers = (bishops | queens) & sliding_attacks_bishop(sq, occupied);
    if (diag_attackers)
    {
        U64 bishop_attackers = bishops & diag_attackers;
        if (bishop_attackers)
        {
            *attacker_sq = lsb_index(bishop_attackers);
            return BISHOP;
        }
        U64 queen_diag = queens & diag_attackers;
        if (queen_diag)
        {
            *attacker_sq = lsb_index(queen_diag);
            return QUEEN;
        }
    }

    U64 straight_attackers = (rooks | queens) & sliding_attacks_rook(sq, occupied);
    if (straight_attackers)
    {
        U64 rook_attackers = rooks & straight_attackers;
        if (rook_attackers)
        {
            *attacker_sq = lsb_index(rook_attackers);
            return ROOK;
        }
        U64 queen_straight = queens & straight_attackers;
        if (queen_straight)
        {
            *attacker_sq = lsb_index(queen_straight);
            return QUEEN;
        }
    }

    U64 king_attackers = kings & king_attacks[sq];
    if (king_attackers)
    {
        *attacker_sq = lsb_index(king_attackers);
        return KING;
    }

    return 0;
}

static int see(Board *b, int from, int to)
{
    int captured = piece_on_square(b, to);
    if (captured == 0 && b->en_passant == to)
        captured = PAWN;

    if (captured == 0)
        return 0;

    int capture_value = see_piece_value(captured);

    int attacker_piece = piece_on_square(b, from);
    int attacker_value = see_piece_value(attacker_piece);

    U64 occupied = 0;
    int side, pt;
    for (side = 0; side < 2; side++)
    {
        for (pt = PAWN; pt <= KING; pt++)
        {
            occupied |= b->pieces[side][pt];
        }
    }

    occupied &= ~(1ULL << from);
    occupied |= (1ULL << to);

    int gain[32];
    int gain_count = 0;
    gain[gain_count++] = capture_value;

    int current_sq = to;
    int stm = 1 - b->side_to_move;
    int piece = attacker_piece;

    while (1)
    {
        int next_attacker_sq;
        int next_piece = see_smallest_attacker(b, current_sq, stm, occupied, &next_attacker_sq);

        if (next_piece == 0)
            break;

        int next_value = see_piece_value(next_piece);

        occupied &= ~(1ULL << next_attacker_sq);

        gain[gain_count++] = next_value;

        if (next_piece == KING)
            break;

        current_sq = next_attacker_sq;
        stm = 1 - stm;
        piece = next_piece;

        if (gain_count >= 30)
            break;
    }

    while (gain_count > 1)
    {
        gain_count--;
        gain[gain_count - 1] = gain[gain_count - 1] - gain[gain_count];
        if (gain[gain_count - 1] < 0)
            gain[gain_count - 1] = 0;
    }

    return gain[0];
}

static int qsearch_generate_moves(const Board *b, Move *moves)
{
    int count = 0;
    int side = b->side_to_move;
    int opp = 1 - side;
    U64 own = side_pieces(b, side);
    U64 enemy = side_pieces(b, opp);
    U64 occupied = own | enemy;

    U64 pawns = b->pieces[side][PAWN];
    while (pawns)
    {
        int sq = lsb_index(pawns);
        pawns &= pawns - 1;
        int r = rank_of(sq), f = file_of(sq);
        if (side == WHITE)
        {
            if (r == 6)
            {
                if (!(occupied & (1ULL << (sq + 8))))
                {
                    int prom;
                    for (prom = QUEEN; prom >= KNIGHT; prom--)
                    {
                        if (prom == KING)
                            continue;
                        moves[count++] = (Move){sq, sq + 8, prom, 0, 0};
                    }
                }
                if (f > 0 && (enemy & (1ULL << (sq + 7))))
                {
                    int cap = piece_on_square(b, sq + 7);
                    int prom;
                    for (prom = QUEEN; prom >= KNIGHT; prom--)
                    {
                        if (prom == KING)
                            continue;
                        moves[count++] = (Move){sq, sq + 7, prom, cap, 0};
                    }
                }
                if (f < 7 && (enemy & (1ULL << (sq + 9))))
                {
                    int cap = piece_on_square(b, sq + 9);
                    int prom;
                    for (prom = QUEEN; prom >= KNIGHT; prom--)
                    {
                        if (prom == KING)
                            continue;
                        moves[count++] = (Move){sq, sq + 9, prom, cap, 0};
                    }
                }
            }
            else
            {
                if (f > 0 && (enemy & (1ULL << (sq + 7))))
                {
                    int cap = piece_on_square(b, sq + 7);
                    moves[count++] = (Move){sq, sq + 7, 0, cap, 0};
                }
                if (f < 7 && (enemy & (1ULL << (sq + 9))))
                {
                    int cap = piece_on_square(b, sq + 9);
                    moves[count++] = (Move){sq, sq + 9, 0, cap, 0};
                }
            }
            if (b->en_passant >= 0)
            {
                if (f > 0 && (sq + 7) == b->en_passant)
                    moves[count++] = (Move){sq, sq + 7, 0, PAWN, 0};
                if (f < 7 && (sq + 9) == b->en_passant)
                    moves[count++] = (Move){sq, sq + 9, 0, PAWN, 0};
            }
        }
        else
        {
            if (r == 1)
            {
                if (!(occupied & (1ULL << (sq - 8))))
                {
                    int prom;
                    for (prom = QUEEN; prom >= KNIGHT; prom--)
                    {
                        if (prom == KING)
                            continue;
                        moves[count++] = (Move){sq, sq - 8, prom, 0, 0};
                    }
                }
                if (f > 0 && (enemy & (1ULL << (sq - 9))))
                {
                    int cap = piece_on_square(b, sq - 9);
                    int prom;
                    for (prom = QUEEN; prom >= KNIGHT; prom--)
                    {
                        if (prom == KING)
                            continue;
                        moves[count++] = (Move){sq, sq - 9, prom, cap, 0};
                    }
                }
                if (f < 7 && (enemy & (1ULL << (sq - 7))))
                {
                    int cap = piece_on_square(b, sq - 7);
                    int prom;
                    for (prom = QUEEN; prom >= KNIGHT; prom--)
                    {
                        if (prom == KING)
                            continue;
                        moves[count++] = (Move){sq, sq - 7, prom, cap, 0};
                    }
                }
            }
            else
            {
                if (f > 0 && (enemy & (1ULL << (sq - 9))))
                {
                    int cap = piece_on_square(b, sq - 9);
                    moves[count++] = (Move){sq, sq - 9, 0, cap, 0};
                }
                if (f < 7 && (enemy & (1ULL << (sq - 7))))
                {
                    int cap = piece_on_square(b, sq - 7);
                    moves[count++] = (Move){sq, sq - 7, 0, cap, 0};
                }
            }
            if (b->en_passant >= 0)
            {
                if (f > 0 && (sq - 9) == b->en_passant)
                    moves[count++] = (Move){sq, sq - 9, 0, PAWN, 0};
                if (f < 7 && (sq - 7) == b->en_passant)
                    moves[count++] = (Move){sq, sq - 7, 0, PAWN, 0};
            }
        }
    }

    U64 knights = b->pieces[side][KNIGHT];
    while (knights)
    {
        int sq = lsb_index(knights);
        knights &= knights - 1;
        U64 att = knight_attacks[sq] & enemy;
        while (att)
        {
            int to = lsb_index(att);
            att &= att - 1;
            int cap = piece_on_square(b, to);
            moves[count++] = (Move){sq, to, 0, cap, 0};
        }
    }

    U64 bishops = b->pieces[side][BISHOP];
    while (bishops)
    {
        int sq = lsb_index(bishops);
        bishops &= bishops - 1;
        U64 att = sliding_attacks_bishop(sq, occupied) & enemy;
        while (att)
        {
            int to = lsb_index(att);
            att &= att - 1;
            int cap = piece_on_square(b, to);
            moves[count++] = (Move){sq, to, 0, cap, 0};
        }
    }

    U64 rooks = b->pieces[side][ROOK];
    while (rooks)
    {
        int sq = lsb_index(rooks);
        rooks &= rooks - 1;
        U64 att = sliding_attacks_rook(sq, occupied) & enemy;
        while (att)
        {
            int to = lsb_index(att);
            att &= att - 1;
            int cap = piece_on_square(b, to);
            moves[count++] = (Move){sq, to, 0, cap, 0};
        }
    }

    U64 queens = b->pieces[side][QUEEN];
    while (queens)
    {
        int sq = lsb_index(queens);
        queens &= queens - 1;
        U64 att = (sliding_attacks_bishop(sq, occupied) | sliding_attacks_rook(sq, occupied)) & enemy;
        while (att)
        {
            int to = lsb_index(att);
            att &= att - 1;
            int cap = piece_on_square(b, to);
            moves[count++] = (Move){sq, to, 0, cap, 0};
        }
    }

    int king_sq = -1;
    U64 kbb = b->pieces[side][KING];
    if (kbb)
        king_sq = lsb_index(kbb);
    if (king_sq >= 0)
    {
        U64 att = king_attacks[king_sq] & enemy;
        while (att)
        {
            int to = lsb_index(att);
            att &= att - 1;
            int cap = piece_on_square(b, to);
            moves[count++] = (Move){king_sq, to, 0, cap, 0};
        }
    }

    return count;
}

static int generate_checking_moves(const Board *b, Move *moves, int start_count)
{
    int count = start_count;
    int side = b->side_to_move;
    int opp = 1 - side;
    U64 own = side_pieces(b, side);
    U64 enemy = side_pieces(b, opp);
    U64 occupied = own | enemy;

    int opp_king_sq = -1;
    U64 opp_king = b->pieces[opp][KING];
    if (opp_king)
        opp_king_sq = lsb_index(opp_king);
    if (opp_king_sq < 0)
        return count;

    U64 queen_check_squares = (sliding_attacks_rook(opp_king_sq, occupied) |
                               sliding_attacks_bishop(opp_king_sq, occupied));
    U64 rook_check_squares = sliding_attacks_rook(opp_king_sq, occupied);
    U64 bishop_check_squares = sliding_attacks_bishop(opp_king_sq, occupied);
    U64 knight_check_squares = knight_attacks[opp_king_sq];

    U64 queens = b->pieces[side][QUEEN];
    while (queens)
    {
        int sq = lsb_index(queens);
        queens &= queens - 1;
        U64 all_att = sliding_attacks_bishop(sq, occupied) | sliding_attacks_rook(sq, occupied);
        U64 non_cap = all_att & ~enemy & ~own & queen_check_squares;
        while (non_cap)
        {
            int to = lsb_index(non_cap);
            non_cap &= non_cap - 1;
            moves[count++] = (Move){sq, to, 0, 0, 0};
        }
    }

    U64 rooks = b->pieces[side][ROOK];
    while (rooks)
    {
        int sq = lsb_index(rooks);
        rooks &= rooks - 1;
        U64 all_att = sliding_attacks_rook(sq, occupied);
        U64 non_cap = all_att & ~enemy & ~own & rook_check_squares;
        while (non_cap)
        {
            int to = lsb_index(non_cap);
            non_cap &= non_cap - 1;
            moves[count++] = (Move){sq, to, 0, 0, 0};
        }
    }

    U64 bishops = b->pieces[side][BISHOP];
    while (bishops)
    {
        int sq = lsb_index(bishops);
        bishops &= bishops - 1;
        U64 all_att = sliding_attacks_bishop(sq, occupied);
        U64 non_cap = all_att & ~enemy & ~own & bishop_check_squares;
        while (non_cap)
        {
            int to = lsb_index(non_cap);
            non_cap &= non_cap - 1;
            moves[count++] = (Move){sq, to, 0, 0, 0};
        }
    }

    U64 knights = b->pieces[side][KNIGHT];
    while (knights)
    {
        int sq = lsb_index(knights);
        knights &= knights - 1;
        U64 all_att = knight_attacks[sq];
        U64 non_cap = all_att & ~enemy & ~own & knight_check_squares;
        while (non_cap)
        {
            int to = lsb_index(non_cap);
            non_cap &= non_cap - 1;
            moves[count++] = (Move){sq, to, 0, 0, 0};
        }
    }

    {
        U64 pawns = b->pieces[side][PAWN];
        U64 opp_king_bb = (U64)1 << opp_king_sq;
        while (pawns)
        {
            int sq = lsb_index(pawns);
            pawns &= pawns - 1;
            int r = rank_of(sq), f = file_of(sq);
            if (side == WHITE)
            {
                if (r == 6)
                {
                    int to = sq + 8;
                    if (!(occupied & (1ULL << to)))
                    {
                        U64 queen_att = sliding_attacks_bishop(to, (occupied & ~(1ULL << sq)) | (1ULL << to)) |
                                        sliding_attacks_rook(to, (occupied & ~(1ULL << sq)) | (1ULL << to));
                        U64 rook_att = sliding_attacks_rook(to, (occupied & ~(1ULL << sq)) | (1ULL << to));
                        U64 bishop_att = sliding_attacks_bishop(to, (occupied & ~(1ULL << sq)) | (1ULL << to));
                        U64 knight_att = knight_attacks[to];
                        if (queen_att & opp_king_bb)
                            moves[count++] = (Move){sq, to, QUEEN, 0, 0};
                        if (rook_att & opp_king_bb)
                            moves[count++] = (Move){sq, to, ROOK, 0, 0};
                        if (bishop_att & opp_king_bb)
                            moves[count++] = (Move){sq, to, BISHOP, 0, 0};
                        if (knight_att & opp_king_bb)
                            moves[count++] = (Move){sq, to, KNIGHT, 0, 0};
                    }
                }
                else
                {
                    int to1 = sq + 8;
                    if (!(occupied & (1ULL << to1)))
                    {
                        if (f > 0 && ((to1 - 1) == opp_king_sq))
                            moves[count++] = (Move){sq, to1, 0, 0, 0};
                        else if (f < 7 && ((to1 + 1) == opp_king_sq))
                            moves[count++] = (Move){sq, to1, 0, 0, 0};
                        if (r == 1)
                        {
                            int to2 = sq + 16;
                            if (!(occupied & (1ULL << to2)))
                            {
                                if (f > 0 && ((to2 - 1) == opp_king_sq))
                                    moves[count++] = (Move){sq, to2, 0, 0, 0};
                                else if (f < 7 && ((to2 + 1) == opp_king_sq))
                                    moves[count++] = (Move){sq, to2, 0, 0, 0};
                            }
                        }
                    }
                }
            }
            else
            {
                if (r == 1)
                {
                    int to = sq - 8;
                    if (!(occupied & (1ULL << to)))
                    {
                        U64 queen_att = sliding_attacks_bishop(to, (occupied & ~(1ULL << sq)) | (1ULL << to)) |
                                        sliding_attacks_rook(to, (occupied & ~(1ULL << sq)) | (1ULL << to));
                        U64 rook_att = sliding_attacks_rook(to, (occupied & ~(1ULL << sq)) | (1ULL << to));
                        U64 bishop_att = sliding_attacks_bishop(to, (occupied & ~(1ULL << sq)) | (1ULL << to));
                        U64 knight_att = knight_attacks[to];
                        if (queen_att & opp_king_bb)
                            moves[count++] = (Move){sq, to, QUEEN, 0, 0};
                        if (rook_att & opp_king_bb)
                            moves[count++] = (Move){sq, to, ROOK, 0, 0};
                        if (bishop_att & opp_king_bb)
                            moves[count++] = (Move){sq, to, BISHOP, 0, 0};
                        if (knight_att & opp_king_bb)
                            moves[count++] = (Move){sq, to, KNIGHT, 0, 0};
                    }
                }
                else
                {
                    int to1 = sq - 8;
                    if (!(occupied & (1ULL << to1)))
                    {
                        if (f > 0 && ((to1 - 1) == opp_king_sq))
                            moves[count++] = (Move){sq, to1, 0, 0, 0};
                        else if (f < 7 && ((to1 + 1) == opp_king_sq))
                            moves[count++] = (Move){sq, to1, 0, 0, 0};
                        if (r == 6)
                        {
                            int to2 = sq - 16;
                            if (!(occupied & (1ULL << to2)))
                            {
                                if (f > 0 && ((to2 - 1) == opp_king_sq))
                                    moves[count++] = (Move){sq, to2, 0, 0, 0};
                                else if (f < 7 && ((to2 + 1) == opp_king_sq))
                                    moves[count++] = (Move){sq, to2, 0, 0, 0};
                            }
                        }
                    }
                }
            }
        }
    }

    return count;
}

int quiescence_search(SearchState *s, int alpha, int beta, int ply, int qs_depth)
{
    assert(alpha < beta && "Alpha must be less than beta in quiescence_search");

    if (s->aborted)
        return 0;
    s->nodes++;

    int is_endgame_qs = 0;
    {
        int npm = 0;
        int pt;
        for (pt = KNIGHT; pt <= QUEEN; pt++)
        {
            npm += count_bits(s->board.pieces[WHITE][pt]) * (pt == KNIGHT ? 3 : pt == BISHOP ? 3
                                                                            : pt == ROOK     ? 5
                                                                                             : 9);
            npm += count_bits(s->board.pieces[BLACK][pt]) * (pt == KNIGHT ? 3 : pt == BISHOP ? 3
                                                                            : pt == ROOK     ? 5
                                                                                             : 9);
        }
        if (npm <= ENDGAME_PHASE_THRESHOLD)
            is_endgame_qs = 1;
    }
    int qs_max_depth = is_endgame_qs ? QS_MAX_DEPTH_EG : QS_MAX_DEPTH_MG;
    if (qs_depth >= qs_max_depth)
    {
        int eval = evaluate(&s->board);
        if (s->board.side_to_move == BLACK)
            eval = -eval;
        return eval;
    }

    int in_check = is_check(&s->board, s->board.side_to_move);
    int next_ply = ply + 1;

    if (!in_check)
    {
        int stand_pat = evaluate(&s->board);
        if (s->board.side_to_move == BLACK)
            stand_pat = -stand_pat;
        if (stand_pat >= beta)
            return beta;
        if (alpha < stand_pat)
            alpha = stand_pat;
        if (stand_pat + DELTA < alpha)
            return alpha;
        if (stand_pat + QUEEN_VALUE < alpha)
            return alpha;
        if (ply >= 60)
            return alpha;
    }

    Move moves[MAX_MOVES];
    int n;
    if (in_check)
    {
        n = generate_pseudo_legal_moves(&s->board, moves);
    }
    else
    {
        n = qsearch_generate_moves(&s->board, moves);
    }
    int i;
    for (i = 0; i < n; i++)
    {
        moves[i].score = mvv_lva(&s->board, &moves[i]);
    }
    sort_moves(moves, n);

    int legal_count = 0;
    for (i = 0; i < n; i++)
    {
        if (!in_check && moves[i].capture && !moves[i].promotion)
        {
            Board temp_board = s->board;
            int see_score = see(&temp_board, moves[i].from, moves[i].to);
            if (see_score < 0)
                continue;
        }

        UndoInfo undo;
        make_move(&s->board, &moves[i], &undo);
        if (!is_check(&s->board, 1 - s->board.side_to_move))
        {
            legal_count++;
            int score = -quiescence_search(s, -beta, -alpha, next_ply, qs_depth + 1);
            if (score > alpha)
            {
                alpha = score;
                if (alpha >= beta)
                {
                    unmake_move(&s->board, &moves[i], &undo);
                    return beta;
                }
            }
        }
        unmake_move(&s->board, &moves[i], &undo);
    }

    if (in_check && legal_count == 0)
    {
        return -MATE_SCORE + ply;
    }

    return alpha;
}

int negamax(SearchState *s, int depth, int alpha, int beta, int ext_count, int ply)
{
    assert(alpha < beta && "Alpha must be less than beta in negamax");

    if (s->aborted)
        return 0;
    s->nodes++;
    if (ply >= 100)
    {
        return quiescence_search(s, alpha, beta, ply, 0);
    }
    if ((s->nodes & 511) == 0)
    {
        double elapsed = get_time() - s->start_time;
        if (elapsed >= s->time_limit || g_engine_abort_flag)
        {
            s->aborted = 1;
            return 0;
        }
    }

    U64 key = s->board.hash;
    Move tt_move = {0};
    int tt_score = -INF;
    int tt_val = tt_probe(s, key, depth, alpha, beta, &tt_move, ply, &tt_score);
    if (tt_val != INF + 1)
        return tt_val;

    {
        int rep_i;
        int total_reps = 0;
        int game_reps = 0;
        int search_reps = 0;
        for (rep_i = 0; rep_i < s->game_history_count; rep_i++)
        {
            if (s->game_history[rep_i] == key)
                game_reps++;
        }
        for (rep_i = 0; rep_i < s->search_history_count; rep_i++)
        {
            if (s->search_history[rep_i] == key)
                search_reps++;
        }
        total_reps = game_reps + search_reps;
        if (total_reps >= 2)
            return 0;
    }

    int saved_history_count = s->search_history_count;

    if (s->search_history_count < 256)
    {
        s->search_history[s->search_history_count] = key;
        s->search_history_count++;
    }

    if (s->board.halfmove_clock >= 100)
    {
        s->search_history_count = saved_history_count;
        return 0;
    }

    int in_check = is_check(&s->board, s->board.side_to_move);
    /*
    if (in_check && ext_count < 4)
    {
        depth++;
        ext_count++;
    }
    */

    int is_endgame = 0;
    {
        int npm_w = 0, npm_b = 0;
        int pt;
        for (pt = KNIGHT; pt <= QUEEN; pt++)
        {
            int c = count_bits(s->board.pieces[WHITE][pt]);
            npm_w += c * (pt == KNIGHT ? 3 : pt == BISHOP ? 3
                                         : pt == ROOK     ? 5
                                                          : 9);
            c = count_bits(s->board.pieces[BLACK][pt]);
            npm_b += c * (pt == KNIGHT ? 3 : pt == BISHOP ? 3
                                         : pt == ROOK     ? 5
                                                          : 9);
        }
        int phase = npm_w + npm_b;
        if (phase <= ENDGAME_PHASE_THRESHOLD)
            is_endgame = 1;
    }
    /*
    if (is_endgame && depth >= 2 && depth < 8)
    {
        depth += ENDGAME_DEPTH_BONUS;
    }
    */

    if (tt_move.from == 0 && tt_move.to == 0 && depth >= 4 && alpha > -INF + 1000 && beta < INF - 1000)
    {
        int iid_score = negamax(s, depth - 2, alpha, beta, ext_count, ply);
        if (!s->aborted)
        {
            tt_probe(s, key, depth - 2, alpha, beta, &tt_move, ply, NULL);
        }
    }

    if (depth <= 0)
    {
        s->search_history_count = saved_history_count;
        return quiescence_search(s, alpha, beta, ply, 0);
    }

    /* Razoring: If the static evaluation is far below alpha at shallow depths,
     * we can reduce the search depth or return the evaluation directly.
     * This is applied before move generation to save time.
     */
    if (should_apply_razoring(s, depth, alpha, in_check))
    {
        /* Get static evaluation */
        int eval = evaluate(&s->board);

        /* Calculate razor margin */
        int razor_margin = g_runtime_params.razoring_margin + (depth - 1) * 150;
        if (is_endgame)
            razor_margin = razor_margin * 3 / 2;

        /* If eval + margin is still below alpha, do a quiescence search
         * to verify the position is really bad */
        if (eval + razor_margin < alpha)
        {
            /* Do a quiescence search to verify */
            int q_score = quiescence_search(s, alpha, beta, ply, 0);

            /* If quiescence search confirms the position is bad, return it */
            if (q_score < alpha)
            {
                /* Estimate nodes saved by Razoring
                 * This is a rough estimate based on typical search tree size at this depth */
                int estimated_nodes_saved = (1 << depth) - 1; /* 2^depth - 1 */

                /* Update Razoring statistics */
                s->razoring_prunes++;
                s->razoring_nodes_saved += estimated_nodes_saved;

                s->search_history_count = saved_history_count;
                return q_score;
            }
        }
    }

    Board *b = &s->board;
    Move moves[MAX_MOVES];
    int n = generate_pseudo_legal_moves(b, moves);
    int legal_count = 0;
    int i;

    for (i = 0; i < n; i++)
    {
        if (moves[i].from == tt_move.from && moves[i].to == tt_move.to && moves[i].promotion == tt_move.promotion)
        {
            moves[i].score = 1000000;
        }
        else if (moves[i].capture)
        {
            moves[i].score = mvv_lva(b, &moves[i]) + 50000;
        }
        else
        {
            int k1, k2;
            if (depth < 64)
            {
                for (k1 = 0; k1 < 2; k1++)
                {
                    if (s->killers[depth][k1].from == moves[i].from && s->killers[depth][k1].to == moves[i].to)
                    {
                        moves[i].score = 40000 - k1 * 1000;
                        break;
                    }
                }
            }
            if (moves[i].score == 0 && ply >= 2)
            {
                Move *cm = &s->countermove[moves[i].from][moves[i].to];
                if (cm->from == moves[i].from && cm->to == moves[i].to)
                {
                    moves[i].score = 30000;
                }
            }
            if (moves[i].score == 0 && ply >= 3)
            {
                Move *fu = &s->followup[moves[i].from][moves[i].to];
                if (fu->from == moves[i].from && fu->to == moves[i].to)
                {
                    moves[i].score = 25000;
                }
            }
            if (moves[i].score == 0)
            {
                moves[i].score = s->history[moves[i].from][moves[i].to];
            }
        }
        if (g_blunder_memory_loaded)
        {
            int bi;
            for (bi = 0; bi < g_blunder_count; bi++)
            {
                if (g_blunder_memory[bi].zobrist_key == key)
                {
                    if (moves[i].from == g_blunder_memory[bi].bad_from && moves[i].to == g_blunder_memory[bi].bad_to)
                    {
                        moves[i].score -= 5000;
                    }
                    if (moves[i].from == g_blunder_memory[bi].good_from && moves[i].to == g_blunder_memory[bi].good_to)
                    {
                        moves[i].score += 5000;
                    }
                }
            }
        }
    }
    sort_moves(moves, n);

    int best_score = -INF;
    Move best_move = {0};
    int flag = 1;

    if (depth >= NULL_MOVE_MIN_DEPTH && !in_check && beta < INF - 1000 && has_non_pawn_material(b, b->side_to_move))
    {
        Board saved = *b;
        b->side_to_move = 1 - b->side_to_move;
        b->en_passant = -1;
        int nmr = NULL_MOVE_REDUCTION;
        if (is_endgame)
            nmr += ENDGAME_NMR_BONUS;
        int null_score = -negamax(s, depth - (nmr + 1), -beta, -beta + 1, 0, ply + 1);
        *b = saved;
        if (s->aborted)
        {
            s->search_history_count = saved_history_count;
            return 0;
        }
        if (null_score >= beta)
        {
            if (depth >= NULL_MOVE_VERIFICATION_DEPTH)
            {
                int saved_for_verify = s->search_history_count;
                s->search_history_count = saved_history_count;
                int verify_score = negamax(s, depth - NULL_MOVE_VERIFICATION_REDUCTION, alpha, beta, ext_count, ply);
                s->search_history_count = saved_for_verify;
                if (s->aborted)
                {
                    s->search_history_count = saved_history_count;
                    return 0;
                }
                if (verify_score >= beta)
                {
                    s->search_history_count = saved_history_count;
                    return beta;
                }
            }
            else
            {
                s->search_history_count = saved_history_count;
                return beta;
            }
        }
    }

    for (i = 0; i < n; i++)
    {
        if (should_apply_futility_pruning(s, &moves[i], depth, i, in_check, alpha, is_endgame))
        {
            int estimated_nodes_saved = (1 << depth) - 1;
            s->futility_prunes++;
            s->futility_nodes_saved += estimated_nodes_saved;
            continue;
        }

        UndoInfo undo;
        make_move(b, &moves[i], &undo);
        if (is_check(b, 1 - b->side_to_move))
        {
            unmake_move(b, &moves[i], &undo);
            continue;
        }
        legal_count++;

        if (ply < 128)
            s->move_stack[ply] = moves[i];

        int score;
        if (i == 0)
        {
            int se_depth = depth - 1;
            if (depth >= 8 && tt_score >= beta + 30 &&
                moves[i].from == tt_move.from && moves[i].to == tt_move.to)
            {
                se_depth = depth;
            }
            score = -negamax(s, se_depth, -beta, -alpha, ext_count, ply + 1);
        }
        else
        {
            int apply_lmr = should_apply_lmr(s, &moves[i], depth, i, in_check, is_endgame);

            if (apply_lmr)
            {
                int reduction = calculate_reduction(s, &moves[i], depth, i, is_endgame);

                int estimated_nodes_saved = (1 << reduction) - 1;

                score = -negamax(s, depth - 1 - reduction, -alpha - 1, -alpha, ext_count, ply + 1);

                s->lmr_reductions++;
                s->lmr_nodes_saved += estimated_nodes_saved;

                if (score > alpha)
                {
                    score = -negamax(s, depth - 1, -alpha - 1, -alpha, ext_count, ply + 1);
                    s->lmr_re_searches++;

                    if (score > alpha && score < beta)
                    {
                        score = -negamax(s, depth - 1, -beta, -alpha, ext_count, ply + 1);
                    }
                }
            }
            else
            {
                score = -negamax(s, depth - 1, -alpha - 1, -alpha, ext_count, ply + 1);

                if (score > alpha && score < beta)
                {
                    score = -negamax(s, depth - 1, -beta, -alpha, ext_count, ply + 1);
                }
            }
        }
        unmake_move(b, &moves[i], &undo);

        if (s->aborted)
        {
            s->search_history_count = saved_history_count;
            return 0;
        }

        if (score > best_score)
        {
            best_score = score;
            best_move = moves[i];
            if (score > alpha)
            {
                alpha = score;
                flag = 0;
                if (alpha >= beta)
                {
                    flag = 2;
                    if (!moves[i].capture && depth < 64)
                    {
                        s->killers[depth][1] = s->killers[depth][0];
                        s->killers[depth][0] = moves[i];
                        s->history[moves[i].from][moves[i].to] += depth * depth;
                    }
                    if (ply >= 1)
                    {
                        Move prev_move = s->move_stack[ply - 1];
                        s->countermove[prev_move.from][prev_move.to] = moves[i];
                    }
                    if (ply >= 2)
                    {
                        Move prev_own_move = s->move_stack[ply - 2];
                        s->followup[prev_own_move.from][prev_own_move.to] = moves[i];
                    }
                    tt_store(s, key, depth, beta, flag, best_move, ply);
                    s->search_history_count = saved_history_count;
                    return beta;
                }
            }
        }
    }

    if (legal_count == 0)
    {
        s->search_history_count = saved_history_count;
        if (in_check)
        {
            return -MATE_SCORE + ply;
        }
        else
        {
            return 0;
        }
    }

    tt_store(s, key, depth, alpha, flag, best_move, ply);
    s->search_history_count = saved_history_count;
    return alpha;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
int
count_legal_moves(const char *fen)
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
    SearchState s;
    memset(&s, 0, sizeof(SearchState));
    board_from_fen(&s.board, fen);
    s.start_time = get_time();
    s.time_limit = 300.0;
    s.aborted = 0;
    s.nodes = 0;
    s.tt_size = 1 << 20;
    s.tt = (TT_Entry *)calloc(s.tt_size, sizeof(TT_Entry));
    s.tt_generation = 1;
    s.search_history_count = 0;
    s.game_history_count = 0;
    int i;

    Board *b = &s.board;
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
        int score = -negamax(&s, depth - 1, -INF, INF, 0, 1);
        unmake_move(b, &root_moves[i], &undo);
        if (s.aborted)
            break;
        out_scores[count] = score;
        out_from[count] = root_moves[i].from;
        out_to[count] = root_moves[i].to;
        count++;
    }
    *out_count = count;
    free(s.tt);
}

#ifdef _WIN32
__declspec(dllexport)
#endif
void
debug_id_scores(const char *fen, int max_depth, int *out_scores, int *out_from, int *out_to, int *out_count)
{
    ensure_engine_tables_initialized();
    SearchState s;
    memset(&s, 0, sizeof(SearchState));
    board_from_fen(&s.board, fen);
    s.start_time = get_time();
    s.time_limit = 30.0;
    s.aborted = 0;
    s.nodes = 0;
    s.tt_size = 1 << 20;
    s.tt = (TT_Entry *)calloc(s.tt_size, sizeof(TT_Entry));
    s.tt_generation = 1;
    s.search_history_count = 0;
    s.game_history_count = 0;
    int i;

    Board *b = &s.board;
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
                score = -negamax(&s, depth - 1, -beta, -alpha, 0, 1);
            }
            else
            {
                score = -negamax(&s, depth - 1, -alpha - 1, -alpha, 0, 1);
                if (!s.aborted && score > alpha && score < beta)
                {
                    score = -negamax(&s, depth - 1, -beta, -alpha, 0, 1);
                }
            }
            unmake_move(b, &root_moves[i], &undo);
            if (s.aborted)
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
        if (s.aborted)
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
    free(s.tt);
}

#ifdef _WIN32
__declspec(dllexport)
#endif
Move
find_best_move_c(const char *fen, double time_limit, int max_depth, int *out_nodes,
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

    SearchState s;
    memset(&s, 0, sizeof(SearchState));
    board_from_fen(&s.board, fen);
    s.start_time = get_time();
    s.time_limit = time_limit;
    s.aborted = 0;
    s.nodes = 0;
    s.tt_size = 1 << 20;
    s.tt = (TT_Entry *)calloc(s.tt_size, sizeof(TT_Entry));
    s.tt_generation = 1;
    s.search_history_count = 0;
    s.game_history_count = 0;
    if (game_history && game_history_count > 0)
    {
        int gh_i;
        int gh_limit = game_history_count < 512 ? game_history_count : 512;
        for (gh_i = 0; gh_i < gh_limit; gh_i++)
        {
            s.game_history[gh_i] = game_history[gh_i];
        }
        s.game_history_count = gh_limit;
    }

    {
        U64 root_key = s.board.hash;
        if (s.search_history_count < 256)
        {
            s.search_history[s.search_history_count] = root_key;
            s.search_history_count++;
        }
    }

    Move best_move = {0};
    int best_score = -INF;
    int depth;
    int i;
    int aspiration_alpha = -INF, aspiration_beta = INF;

    int root_scores[MAX_MOVES];
    int scores_valid = 0;
    for (i = 0; i < MAX_MOVES; i++)
        root_scores[i] = -INF;

    if (g_perturb_enabled)
        perturb_rng_seed();

    Board *b = &s.board;
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
        U64 root_key = s.board.hash;
        int root_reps = 0;
        int rep_i;
        for (rep_i = 0; rep_i < s.game_history_count; rep_i++)
        {
            if (s.game_history[rep_i] == root_key)
                root_reps++;
        }
        if (root_reps >= 3)
        {
            if (out_nodes)
                *out_nodes = 0;
            free(s.tt);
            return best_move; // Return null move, let cutechess handle the draw
        }
    }

    if (legal_moves_count == 0)
    {
        if (out_nodes)
            *out_nodes = 0;
        free(s.tt);
        return best_move;
    }

    // Root move ordering: sort moves for better search efficiency
    // Prioritize: captures > promotions > center moves > others
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

    int material = count_total_material(&s.board);
    int depth_bonus = 0;
    if (material <= 4)
        depth_bonus = 2;
    else if (material <= 6)
        depth_bonus = 1;
    int effective_max_depth = max_depth + depth_bonus;

    for (depth = 1; depth <= effective_max_depth; depth++)
    {
        double elapsed = get_time() - s.start_time;
        if (elapsed >= time_limit * 0.6 && depth > 1)
        {
            break;
        }

        int nodes_before = s.nodes;

        Move current_best = {0};
        int current_score = -INF;
        int alpha, beta;
        Move empty_move = {0};

        if (depth == 1)
        {
            alpha = -INF;
            beta = INF;
        }
        else
        {
            alpha = aspiration_alpha;
            beta = aspiration_beta;
        }

        for (i = 0; i < legal_moves_count; i++)
        {
            UndoInfo undo;
            make_move(b, &root_moves[i], &undo);
            int score;
            if (i == 0)
            {
                score = -negamax(&s, depth - 1, -beta, -alpha, 0, 1);
            }
            else
            {
                score = -negamax(&s, depth - 1, -alpha - 1, -alpha, 0, 1);
                if (!s.aborted && score > alpha && score < beta)
                {
                    score = -negamax(&s, depth - 1, -beta, -alpha, 0, 1);
                }
            }
            unmake_move(b, &root_moves[i], &undo);

            if (s.aborted)
                break;

            root_scores[i] = score;

            if (score > current_score)
            {
                current_score = score;
                current_best = root_moves[i];
                if (score > alpha)
                {
                    alpha = score;
                }
            }
        }

        if (!s.aborted && depth >= 2 && (current_score <= aspiration_alpha || current_score >= aspiration_beta))
        {
            alpha = -INF;
            beta = INF;
            current_score = -INF;
            current_best = empty_move;
            for (i = 0; i < legal_moves_count; i++)
            {
                UndoInfo undo2;
                make_move(b, &root_moves[i], &undo2);
                int score;
                if (i == 0)
                {
                    score = -negamax(&s, depth - 1, -beta, -alpha, 0, 1);
                }
                else
                {
                    score = -negamax(&s, depth - 1, -alpha - 1, -alpha, 0, 1);
                    if (!s.aborted && score > alpha && score < beta)
                    {
                        score = -negamax(&s, depth - 1, -beta, -alpha, 0, 1);
                    }
                }
                unmake_move(b, &root_moves[i], &undo2);
                if (s.aborted)
                    break;
                root_scores[i] = score;
                if (score > current_score)
                {
                    current_score = score;
                    current_best = root_moves[i];
                    if (score > alpha)
                    {
                        alpha = score;
                    }
                }
            }
        }

        if (!s.aborted && current_score > -INF)
        {
            best_move = current_best;
            best_move.score = current_score;
            best_score = current_score;
            scores_valid = 1;
            g_last_search_depth = depth;
            g_last_search_nodes = s.nodes;
            g_last_best_score = current_score;

            g_last_lmr_reductions = s.lmr_reductions;
            g_last_lmr_re_searches = s.lmr_re_searches;
            g_last_lmr_nodes_saved = s.lmr_nodes_saved;

            g_last_futility_prunes = s.futility_prunes;
            g_last_futility_nodes_saved = s.futility_nodes_saved;

            g_last_razoring_prunes = s.razoring_prunes;
            g_last_razoring_nodes_saved = s.razoring_nodes_saved;
            if (depth < 64)
                g_depth_nodes[depth] = s.nodes - nodes_before;
            {
                int j;
                for (j = 0; j < legal_moves_count; j++)
                {
                    if (root_moves[j].from == current_best.from && root_moves[j].to == current_best.to && root_moves[j].promotion == current_best.promotion)
                    {
                        Move tmp = root_moves[0];
                        root_moves[0] = root_moves[j];
                        root_moves[j] = tmp;
                        break;
                    }
                }
            }

            if (g_info_callback)
            {
                double elapsed = get_time() - s.start_time;
                int time_ms = (int)(elapsed * 1000);
                char pv_buf[256];
                int pv_pos = 0;
                pv_pos += sprintf(pv_buf + pv_pos, "%c%c%c%c",
                                  'a' + (current_best.from & 7), '1' + (current_best.from >> 3),
                                  'a' + (current_best.to & 7), '1' + (current_best.to >> 3));
                if (current_best.promotion)
                {
                    char pc = 'q';
                    switch (current_best.promotion)
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
                pv_buf[pv_pos] = '\0';
                g_info_callback(depth, current_score, s.nodes, time_ms, pv_buf);
            }

            {
                int hi, hj;
                for (hi = 0; hi < 64; hi++)
                {
                    for (hj = 0; hj < 64; hj++)
                    {
                        s.history[hi][hj] = s.history[hi][hj] * 9 / 10;
                    }
                }
            }
            aspiration_alpha = current_score - 25;
            aspiration_beta = current_score + 25;
            s.tt_generation++;
        }

        if (s.aborted)
            break;
    }

    // Random move selection: among all moves with score within threshold, pick randomly
    if (scores_valid && g_perturb_enabled && legal_moves_count > 1)
    {
        int candidate_count = 0;
        int candidate_indices[MAX_MOVES];
        int min_acceptable_score = best_score - g_perturb_threshold;

        for (i = 0; i < legal_moves_count; i++)
        {
            if (root_scores[i] >= min_acceptable_score)
            {
                candidate_indices[candidate_count++] = i;
            }
        }

        if (candidate_count > 1)
        {
            int chosen_idx = perturb_rand_int(candidate_count);
            int move_idx = candidate_indices[chosen_idx];
            best_move = root_moves[move_idx];
            best_move.score = root_scores[move_idx];
        }
    }

    if (out_nodes)
        *out_nodes = s.nodes;
    free(s.tt);
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

    SearchState s;
    memset(&s, 0, sizeof(SearchState));
    board_from_fen(&s.board, fen);
    s.start_time = get_time();
    s.time_limit = time_limit;
    s.aborted = 0;
    s.nodes = 0;
    s.tt_size = 1 << 20;
    s.tt = (TT_Entry *)calloc(s.tt_size, sizeof(TT_Entry));
    s.tt_generation = 1;
    s.search_history_count = 0;
    s.game_history_count = 0;

    Board *b = &s.board;
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
                score = -negamax(&s, depth - 1, -beta, -alpha, 0, 1);
            else
            {
                score = -negamax(&s, depth - 1, -alpha - 1, -alpha, 0, 1);
                if (!s.aborted && score > alpha && score < beta)
                    score = -negamax(&s, depth - 1, -beta, -alpha, 0, 1);
            }
            unmake_move(b, &root_moves[i], &undo);
            if (s.aborted)
                break;
            if (i < 256)
                root_moves[i].score = score;
            if (score > alpha)
                alpha = score;
        }
        if (s.aborted)
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
    free(s.tt);
}

/* ============================================================================
 * LAZY SMP MULTI-THREADED SEARCH
 * ============================================================================
 */

typedef struct
{
    Board board;
    TT_Entry *shared_tt;
    int tt_size;
    double start_time;
    double time_limit;
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

static volatile int g_smp_stop_flag;

static void smp_worker_search(LazySMPWorker *w)
{
    SearchState s;
    memset(&s, 0, sizeof(SearchState));
    s.board = w->board;
    s.start_time = w->start_time;
    s.time_limit = w->time_limit;
    s.aborted = 0;
    s.nodes = 0;
    s.tt = w->shared_tt;
    s.tt_size = w->tt_size;
    s.tt_generation = 1;
    s.search_history_count = 0;
    s.game_history_count = w->game_history_count;
    if (w->game_history_count > 0)
    {
        int limit = w->game_history_count < 512 ? w->game_history_count : 512;
        memcpy(s.game_history, w->game_history, sizeof(U64) * limit);
        s.game_history_count = limit;
    }

    {
        U64 root_key = s.board.hash;
        if (s.search_history_count < 256)
        {
            s.search_history[s.search_history_count] = root_key;
            s.search_history_count++;
        }
    }

    Board *b = &s.board;
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
        return;
    }

    int start_depth = 1;
    int depth_step = 1;

    Move best_move = root_moves[0];
    int best_score = -INF;

    for (int depth = start_depth; depth <= w->max_depth; depth += depth_step)
    {
        if (g_smp_stop_flag)
            break;
        if (depth >= 5)
        {
            double elapsed = get_time() - s.start_time;
            if (elapsed >= w->time_limit * 0.7)
                break;
        }

        int nodes_before = s.nodes;
        Move current_best = {0};
        int current_score = -INF;
        int alpha = -INF, beta = INF;

        for (i = 0; i < legal_count; i++)
        {
            if (g_smp_stop_flag)
                break;
            UndoInfo undo;
            make_move(b, &root_moves[i], &undo);
            int score;
            if (i == 0)
            {
                score = -negamax(&s, depth - 1, -beta, -alpha, 0, 1);
            }
            else
            {
                score = -negamax(&s, depth - 1, -alpha - 1, -alpha, 0, 1);
                if (!s.aborted && !g_smp_stop_flag && score > alpha && score < beta)
                {
                    score = -negamax(&s, depth - 1, -beta, -alpha, 0, 1);
                }
            }
            unmake_move(b, &root_moves[i], &undo);

            if (s.aborted || g_smp_stop_flag)
                break;

            if (score > current_score)
            {
                current_score = score;
                current_best = root_moves[i];
                if (score > alpha)
                    alpha = score;
            }
        }

        if (!s.aborted && !g_smp_stop_flag && current_score > -INF)
        {
            best_move = current_best;
            best_move.score = current_score;
            best_score = current_score;
            w->completed_depth = depth;
            w->nodes = s.nodes;
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

        if (s.aborted || g_smp_stop_flag)
            break;
    }
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
find_best_move_smp(const char *fen, double time_limit, int max_depth,
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
        return find_best_move_c(fen, time_limit, max_depth, out_nodes,
                                game_history, game_history_count);
    }

    int tt_size = 1 << 20;
    TT_Entry *shared_tt = (TT_Entry *)calloc(tt_size, sizeof(TT_Entry));
    if (!shared_tt)
    {
        return find_best_move_c(fen, time_limit, max_depth, out_nodes,
                                game_history, game_history_count);
    }

    LazySMPWorker *workers = (LazySMPWorker *)calloc(num_threads, sizeof(LazySMPWorker));
    if (!workers)
    {
        free(shared_tt);
        return find_best_move_c(fen, time_limit, max_depth, out_nodes,
                                game_history, game_history_count);
    }

    g_smp_stop_flag = 0;
    double start_time = get_time();

    for (int i = 0; i < num_threads; i++)
    {
        board_from_fen(&workers[i].board, fen);
        workers[i].shared_tt = shared_tt;
        workers[i].tt_size = tt_size;
        workers[i].start_time = start_time;
        workers[i].time_limit = time_limit;
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
            int limit = game_history_count < 512 ? game_history_count : 512;
            memcpy(workers[i].game_history, game_history, sizeof(U64) * limit);
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
        workers[i].thread_handle = CreateThread(NULL, 0, smp_thread_func,
                                                &workers[i], 0, NULL);
#else
        pthread_create(&workers[i].thread_handle, NULL, smp_thread_func, &workers[i]);
#endif
    }

    smp_worker_search(&workers[0]);

    g_smp_stop_flag = 1;

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

    free(shared_tt);
    free(workers);
    return best_move;
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

void set_engine_abort(int flag)
{
    g_engine_abort_flag = flag;
}

int get_engine_abort(void)
{
    return g_engine_abort_flag;
}
