#include "engine_core.h"
#include "engine_params.h"
#include "tbprobe.h"
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

static const int knight_mob_mg[9] = {-38, -19, -8, 0, 6, 11, 17, 21, 25};
static const int knight_mob_eg[9] = {-30, -15, -4, 4, 9, 14, 19, 23, 26};
static const int bishop_mob_mg[14] = {-30, -15, -6, 0, 6, 11, 15, 19, 22, 25, 27, 29, 29, 30};
static const int bishop_mob_eg[14] = {-23, -11, -4, 2, 8, 12, 17, 20, 23, 25, 26, 28, 29, 29};
static const int rook_mob_mg[15] = {-23, -11, -4, 0, 4, 8, 11, 14, 17, 19, 21, 23, 24, 25, 26};
static const int rook_mob_eg[15] = {-19, -9, -2, 2, 6, 10, 14, 17, 20, 22, 23, 25, 26, 27, 28};
static const int queen_mob_mg[28] = {-15, -8, -2, 2, 5, 8, 11, 13, 15, 17, 19, 20, 22, 23, 25, 26, 28, 29, 29, 30, 31, 32, 32, 33, 34, 35, 35, 36};
static const int queen_mob_eg[28] = {-11, -5, -1, 3, 6, 9, 12, 14, 17, 19, 20, 22, 23, 25, 26, 27, 28, 29, 29, 30, 31, 32, 32, 33, 34, 35, 35, 36};

static const int king_danger_table[128] = {
    0, 0, 0, 0, 0, 0, 5, 10, 15, 25, 35, 50, 70, 95, 125, 160,
    200, 245, 295, 350, 410, 475, 545, 620, 700, 785, 875, 970, 1070, 1175, 1285, 1400,
    1520, 1645, 1775, 1910, 2050, 2195, 2345, 2500, 2660, 2825, 2995, 3170, 3350, 3535, 3725, 3920,
    4120, 4325, 4535, 4750, 4970, 5195, 5425, 5660, 5900, 6145, 6395, 6650, 6910, 7175, 7445, 7720,
    8000, 8285, 8575, 8870, 9170, 9475, 9785, 10100, 10420, 10745, 11075, 11410, 11750, 12095, 12445, 12800,
    13160, 13525, 13895, 14270, 14650, 15035, 15425, 15820, 16220, 16625, 17035, 17450, 17870, 18295, 18725, 19160,
    19600, 20045, 20495, 20950, 21410, 21875, 22345, 22820, 23300, 23785, 24275, 24770, 25270, 25775, 26285, 26800,
    27320, 27845, 28375, 28910, 29450, 29995, 30545, 31100, 31660, 32225, 32795, 33370, 33950, 34535, 35125, 35720};

static int lmr_table[64][64];

static void init_lmr_table(void)
{
    int d, m;
    for (d = 1; d < 64; d++)
        for (m = 1; m < 64; m++)
            lmr_table[d][m] = (int)(0.75 + log((double)d) * log((double)m) / 2.25);
}

typedef struct
{
    U64 key;
    int score;
} PawnTTEntry;

#define PAWN_HASH_SIZE (1 << 18)
static PawnTTEntry pawn_hash_table[PAWN_HASH_SIZE];

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
static volatile LONG g_smp_stop_flag_value = 0;

/* Thread-safe stop flag access using InterlockedExchange/ExchangeAdd on Windows */
static void smp_set_stop(int val)
{
#ifdef _WIN32
    InterlockedExchange(&g_smp_stop_flag_value, (LONG)val);
#else
    __atomic_store_n(&g_smp_stop_flag_value, val, __ATOMIC_SEQ_CST);
#endif
}

static int smp_get_stop(void)
{
#ifdef _WIN32
    return (int)InterlockedCompareExchange(&g_smp_stop_flag_value, 0, 0);
#else
    return __atomic_load_n(&g_smp_stop_flag_value, __ATOMIC_SEQ_CST);
#endif
}

static EngineInfoCallback g_info_callback = NULL;

void set_engine_info_callback(EngineInfoCallback cb)
{
    g_info_callback = cb;
}

static void init_zobrist(void);
static U64 compute_hash(const Board *b);
static void tt_init(SearchState *s, int hash_mb);

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
        init_lmr_table();
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
#ifdef _WIN32
    static LARGE_INTEGER freq = {0};
    static int freq_init = 0;
    if (!freq_init)
    {
        QueryPerformanceFrequency(&freq);
        freq_init = 1;
    }
    LARGE_INTEGER counter;
    QueryPerformanceCounter(&counter);
    return (double)counter.QuadPart / (double)freq.QuadPart;
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
#endif
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
static int move_gives_check(Board *b, const Move *move)
{
    UndoInfo undo;
    make_move(b, move, &undo);
    int result = is_check(b, b->side_to_move);
    unmake_move(b, move, &undo);
    return result;
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
static int move_gives_check(Board *b, const Move *move);

static int should_apply_lmr(const SearchState *s, const Move *move, int depth,
                            int move_num, int in_check, int is_endgame)
{
    if (!g_runtime_params.lmr_enabled)
        return 0;

    if (depth < g_runtime_params.lmr_min_depth)
        return 0;

    if (move_num < g_runtime_params.lmr_move_threshold)
        return 0;

    return 1;
}

/* Check if the current position is clearly winning for the side to move.
 * Used to reduce pruning aggression in winning positions. */
static int is_clearly_winning(const Board *b, int static_eval)
{
    /* If we're winning by more than a queen, we're clearly winning */
    if (static_eval > 2000)
        return 1;
    return 0;
}

static int calculate_reduction(SearchState *s, const Move *move, int depth, int move_num, int is_pv_node, int in_check)
{
    if (depth < 1 || move_num < 1)
        return 0;

    int reduction = lmr_table[depth < 63 ? depth : 63][move_num < 63 ? move_num : 63];

    if (is_pv_node)
        reduction -= 1;
    if (in_check)
        reduction -= 1;
    if (move_num <= 3)
        reduction -= 1;
    if (move->capture && move->capture >= 0)
    {
        reduction -= 1;
        {
            int my_npm = s->board.npm[s->board.side_to_move];
            int opp_npm = s->board.npm[s->board.side_to_move ^ 1];
            if (my_npm < opp_npm - 100)
                reduction -= 1;
        }
    }
    if (move->promotion)
        reduction -= 1;

    {
        int npm = s->board.npm[0] + s->board.npm[1];
        if (npm <= ENDGAME_PHASE_THRESHOLD)
        {
            reduction -= 1;
            if (move->promotion)
                reduction -= 1;
        }
    }

    /* In clearly winning positions, reduce LMR to avoid missing forced mates */
    {
        int static_eval = evaluate(&s->board);
        if (s->board.side_to_move == BLACK)
            static_eval = -static_eval;
        if (is_clearly_winning(&s->board, static_eval))
            reduction = (reduction > 1) ? reduction - 1 : 0;
    }

    int hist_val = s->history[move->from][move->to];
    if (hist_val > 500)
        reduction -= 1;
    if (hist_val < -500)
        reduction += 1;

    if (reduction < 0)
        reduction = 0;
    if (reduction >= depth)
        reduction = depth - 1;

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
                                         int alpha, int is_endgame, int static_eval)
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

    /* Disable futility pruning in clearly winning positions to avoid
     * missing forced mates. When we're winning by a large margin,
     * even "futile" moves might be part of a mating sequence. */
    if (static_eval > 2000)
        return 0;

    int margin = g_runtime_params.futility_margin_base * depth;
    if (is_endgame)
        margin = margin * 2 / 3;

    if (static_eval + margin <= alpha)
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
    if (depth > 3)
        return 0;
    if (in_check)
        return 0;
    return 1;
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
                if (sq >= 0 && sq < 64)
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
        if (*p >= '1' && *p <= '8')
        {
            int r = *p++ - '1';
            b->en_passant = r * 8 + f;
        }
        else
        {
            b->en_passant = -1;
        }
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

/* Aspiration Window statistics from last search */
static int g_last_aw_hits = 0;
static int g_last_aw_fails = 0;

/* ============================================================================
 * TINY PERTURBATION MECHANISM
 * ============================================================================
 * When multiple moves have similar evaluations, introduce small perturbation
 * to allow the engine to make different choices, adding variety to play.
 */
static U64 g_perturb_rng_state = 0;
static int g_perturb_threshold = 0;
static int g_perturb_probability = 10;
static int g_perturb_enabled = 0;

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
    tt_init(&s, 16);

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

#define MAX_SLIDERS 16

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

int generate_legal_moves(Board *b, Move *moves)
{
    ensure_engine_tables_initialized();
    Move pseudo[MAX_MOVES];
    int n = generate_pseudo_legal_moves(b, pseudo);
    int count = 0;
    int i;
    int moving_side = b->side_to_move;
    for (i = 0; i < n; i++)
    {
        UndoInfo undo;
        make_move(b, &pseudo[i], &undo);
        if (!is_check(b, moving_side))
        {
            moves[count++] = pseudo[i];
        }
        unmake_move(b, &pseudo[i], &undo);
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

int is_game_over(Board *b)
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

/* === 拆分模块（unity build） === */
#include "engine_params_loader.c"
#include "engine_eval.c"
#include "engine_search.c"
#include "engine_search_root.c"
#include "engine_debug.c"
