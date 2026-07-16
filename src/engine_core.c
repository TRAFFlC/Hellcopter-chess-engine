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
#ifndef LONG
#define LONG long
#endif
#endif

#ifdef _MSC_VER
#include <intrin.h>
#define POPCNT64(x) ((int)__popcnt64(x))
#else
#define POPCNT64(x) ((int)__builtin_popcountll(x))
#endif

#define INF INF_SCORE
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
    int rfp_enabled;
    int nmp_enabled;
    int lmp_enabled;
    int see_prune_enabled;
    int history_prune_enabled;
    int singular_ext_enabled;
    int iid_enabled;
    int probcut_enabled;
    int probcut_min_depth;
    int probcut_margin;
    int probcut_reduction;
    int history_table_enabled;
    int killers_enabled;
    int countermove_followup_enabled;
    int delta_prune_enabled;
    int mate_score;
    int delta;
    int endgame_phase_threshold;
    int endgame_depth_bonus;
    int endgame_nmr_bonus;
    int king_activity_weight;
    int qs_max_depth_mg;
    int qs_max_depth_eg;
    int threading_enabled;
    int num_threads;
    /* Extended eval weights for tuning */
    int pawn_chain_bonus;
    int backward_pawn_penalty;
    int center_pawn_mg_bonus;
    int connected_passer_bonus;
    int rook_on_7th_mg_bonus;
    int rook_on_7th_eg_bonus;
    int castle_short_bonus;
    int castle_long_bonus;
    int tempo_mg;
    int tempo_eg;
    int knight_edge_penalty;
    int knight_initial_block_penalty;
    int isolated_open_file_mul_num;
    int isolated_open_file_mul_den;
    int simplify_threshold;
    int simplify_bonus;
    int mopup_material_threshold;
    int mopup_edge_weight;
    int mopup_proximity_weight;
    int mopup_opposition_weight;
    int opening_knight_not_developed_penalty;
    int opening_bishop_not_developed_penalty;
    int opening_early_queen_base;
    int hanging_queen_penalty;
    int hanging_rook_penalty;
    int hanging_minor_penalty;
    int in_check_penalty;
    int passed_pawn_supported_bonus;
    int passed_pawn_blocked_base;
    int passed_pawn_clear_path_base;
    int passed_pawn_king_dist_base;
    int center_control_piece_bonus;
    int center_control_pawn_bonus;
    int bishop_mobility_bonus;
    int bishop_bad_penalty;
    int pawn_chain_lateral_bonus;
    int center_pawn_pair_bonus;
    int imbalance_mg_base;
    int imbalance_mg_scale;
    int imbalance_eg_scale;
    int no_minor_vs_two_minor_penalty;
    int opposite_bishop_draw_factor_no_pawn;
    int opposite_bishop_draw_factor_pawn;

    /* King Danger parameters */
    int king_danger_cap;
    int knight_attack_base;
    int bishop_attack_base;
    int rook_attack_base;
    int queen_attack_base;
    int knight_attack_per_sq;
    int bishop_attack_per_sq;
    int rook_attack_per_sq;
    int queen_attack_per_sq;
    int pawn_shield_rank2_penalty;
    int pawn_shield_no_pawn_penalty;
    int open_file_king_zone_penalty;
    int semi_open_file_king_zone_penalty;
    int attacker_count_bonus;
    int king_danger_eg_scale_base;
    int king_danger_eg_scale_phase;
    int king_danger_table[128];

    /* Mobility tables */
    int knight_mob_mg[9];
    int knight_mob_eg[9];
    int bishop_mob_mg[14];
    int bishop_mob_eg[14];
    int rook_mob_mg[15];
    int rook_mob_eg[15];
    int queen_mob_mg[28];
    int queen_mob_eg[28];

    /* Queen Centralization */
    int queen_centralization_mg;
    int queen_centralization_eg;

    /* Passed Pawn Detail */
    int passed_pawn_eg_weight;
    int passed_pawn_eg_phase_denom;
    int promo_threat_rank6_base;
    int promo_threat_rank5_base;
    int promo_threat_eg_divisor;
    int passed_pawn_blocked_rank_scale;
    int passed_pawn_blocked_rank_denom;
    int passed_pawn_clear_path_rank_scale;
    int passed_pawn_king_dist_scale;

    /* Center Control Extended */
    int center_control_extended_bonus;
    int center_control_pawn_extended_bonus;

    /* Back Rank Threats */
    int back_rank_mate_penalty;
    int back_rank_triple_penalty;

    /* Knight Outpost */
    int outpost_mg_base;
    int outpost_mg_rank_scale;
    int outpost_eg_base;
    int outpost_eg_rank_scale;

    /* Attacked by Pawn/Knight */
    int queen_attacked_by_pawn_penalty;
    int rook_attacked_by_pawn_penalty;
    int minor_attacked_by_pawn_penalty;
    int queen_attacked_by_pawn_extra;
    int rook_attacked_by_pawn_extra;
    int queen_attacked_by_knight_penalty;
    int rook_attacked_by_knight_penalty;
    int minor_attacked_by_knight_penalty;
    int piece_defended_by_pawn_bonus;

    /* Fork/Threat */
    int knight_fork_queen_rook_penalty;
    int knight_fork_king_penalty;
    int queen_attacked_by_minor_undefended;
    int queen_attacked_by_minor_defended;
    int rook_attacked_by_minor_undefended;
    int rook_attacked_by_minor_defended;
    int minor_attacked_by_minor_undefended;
    int minor_attacked_by_minor_defended;
    int piece_attacked_by_rook_undefended;
    int piece_attacked_by_rook_defended;
    int piece_attacked_by_bishop_undefended;
    int piece_attacked_by_bishop_defended;

    /* Opening Development Extended */
    int opening_early_queen_scale;
    int opening_early_queen_min;
    int opening_undeveloped_penalty_5;
    int opening_undeveloped_penalty_8;
    int opening_king_not_castled_penalty;
    int opening_early_queen_advance_base;
    int opening_early_queen_advance_scale;
    int opening_early_queen_advance_min;
    int opening_early_rook_advance_penalty;
    int opening_center_pawn_control_bonus;
    int opening_no_center_pawn_penalty;

    /* Fifty Move Rule */
    int fifty_move_urgency_divisor;

    /* Mopup Extended */
    int mopup_winning_king_activity_weight;
    int mopup_losing_king_activity_weight;
    int mopup_king_activity_early_phase;
    int mopup_king_activity_early_weight;
    int mopup_generic_edge_scale;
    int mopup_generic_proximity_scale;

    /* Anti-Simplify */
    int anti_simplify_per_piece_scale;
    int anti_simplify_piece_threshold;

    /* Specific Endgames KRK/KQKR/KBNK */
    int krk_rook_cutoff_bonus;
    int krk_rook_far_penalty;
    int kqkr_corner_scale;
    int kqkr_proximity_scale;
    int kqkr_queen_proximity_scale;
    int kqkr_stalemate_avoid_penalty;
    int kqkr_corner_mate_bonus;
    int kbnk_corner_scale;
    int kbnk_proximity_scale;
    int kbnk_correct_corner_bonus;

    /* Extended Mopup */
    int extended_mopup_edge_scale;
    int extended_mopup_proximity_scale;

    /* Opposite Bishop Draw */
    int opposite_bishop_draw_divisor;

    /* Rook 7th Extended */
    int rook_on_7th_double_bonus;
    int rook_on_7th_king_rank8_bonus;
    int rook_on_7th_double_king_rank8_bonus;

    /* Rook Potential */
    int rook_potential_open_file;
    int rook_potential_semi_open;

    /* NMP/LMR runtime-tunable parameters (P1 fix: make config actually used) */
    int nmp_base_reduction;
    int nmp_depth_divisor;
    double lmr_base;
    double lmr_divisor;

    int loaded; /* Flag: 1 if parameters loaded from file, 0 if using defaults */
} RuntimeParams;

/* Global runtime parameters - initialized to defaults */
static RuntimeParams g_runtime_params = {0};

/* ============================================================================
 * SEARCH PROFILE — Global performance counters
 * ============================================================================ */
static long long g_prof_eval_calls = 0;
static long long g_prof_qs_calls = 0;
static long long g_prof_make_move_calls = 0;
static long long g_prof_unmake_move_calls = 0;
static long long g_prof_nmp_triggered = 0;
static long long g_prof_nmp_cutoffs = 0;
static long long g_prof_rfp_triggered = 0;
static long long g_prof_lmr_applied = 0;
static long long g_prof_lmr_full_research = 0;
static long long g_prof_futility_pruned = 0;
static long long g_prof_razoring_triggered = 0;
static long long g_prof_lmp_pruned = 0;
static long long g_prof_see_pruned = 0;
static long long g_prof_history_pruned = 0;
static long long g_prof_probcut_triggered = 0;
static long long g_prof_probcut_cutoffs = 0;
static long long g_prof_tt_hits = 0;
static long long g_prof_tt_stores = 0;
static long long g_prof_qs_nodes = 0;

#ifdef _WIN32
__declspec(dllexport)
#endif
SearchProfile get_search_profile(void)
{
    SearchProfile p;
    p.eval_calls = g_prof_eval_calls;
    p.qs_calls = g_prof_qs_calls;
    p.make_move_calls = g_prof_make_move_calls;
    p.unmake_move_calls = g_prof_unmake_move_calls;
    p.nmp_triggered = g_prof_nmp_triggered;
    p.nmp_cutoffs = g_prof_nmp_cutoffs;
    p.rfp_triggered = g_prof_rfp_triggered;
    p.lmr_applied = g_prof_lmr_applied;
    p.lmr_full_research = g_prof_lmr_full_research;
    p.futility_pruned = g_prof_futility_pruned;
    p.razoring_triggered = g_prof_razoring_triggered;
    p.lmp_pruned = g_prof_lmp_pruned;
    p.see_pruned = g_prof_see_pruned;
    p.history_pruned = g_prof_history_pruned;
    p.probcut_triggered = g_prof_probcut_triggered;
    p.probcut_cutoffs = g_prof_probcut_cutoffs;
    p.tt_hits = g_prof_tt_hits;
    p.tt_stores = g_prof_tt_stores;
    p.total_nodes = 0; /* filled by caller from SearchState */
    p.qs_nodes = g_prof_qs_nodes;
    return p;
}

#ifdef _WIN32
__declspec(dllexport)
#endif
void reset_search_profile(void)
{
    g_prof_eval_calls = 0;
    g_prof_qs_calls = 0;
    g_prof_make_move_calls = 0;
    g_prof_unmake_move_calls = 0;
    g_prof_nmp_triggered = 0;
    g_prof_nmp_cutoffs = 0;
    g_prof_rfp_triggered = 0;
    g_prof_lmr_applied = 0;
    g_prof_lmr_full_research = 0;
    g_prof_futility_pruned = 0;
    g_prof_razoring_triggered = 0;
    g_prof_lmp_pruned = 0;
    g_prof_see_pruned = 0;
    g_prof_history_pruned = 0;
    g_prof_probcut_triggered = 0;
    g_prof_probcut_cutoffs = 0;
    g_prof_tt_hits = 0;
    g_prof_tt_stores = 0;
    g_prof_qs_nodes = 0;
}

void set_num_threads(int n)
{
    if (n < 1)
        n = 1;
    if (n > 64)
        n = 64;
    g_runtime_params.num_threads = n;
    g_runtime_params.threading_enabled = (n > 1) ? 1 : 0;
}

int get_threading_enabled(void)
{
    return g_runtime_params.threading_enabled;
}

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

/* Mobility tables now defined in engine_params.h */

/* king_danger_table now defined in engine_params.h */

static int lmr_table[128][64];

static void init_lmr_table(void)
{
    int d, m;
    /* Fall back to compile-time constants when runtime params are not yet
     * loaded (g_runtime_params is zero-initialized). This prevents division
     * by zero when ensure_engine_tables_initialized() runs before
     * init_runtime_params_defaults()/load_params_from_file(). */
    double base = (g_runtime_params.lmr_divisor != 0.0) ? g_runtime_params.lmr_base : LMR_BASE;
    double divisor = (g_runtime_params.lmr_divisor != 0.0) ? g_runtime_params.lmr_divisor : LMR_DIVISOR;
    for (d = 1; d < 128; d++)
        for (m = 1; m < 64; m++)
            lmr_table[d][m] = (int)(base + log((double)d) * log((double)m) / divisor);
}

/* Public interface to regenerate lmr_table after runtime params are loaded */
void regenerate_lmr_table(void)
{
    init_lmr_table();
}

typedef struct
{
    U64 key;
    int score;
} PawnTTEntry;

#define PAWN_HASH_SIZE (1 << PAWN_HASH_SIZE_EXP)
static PawnTTEntry volatile pawn_hash_table[PAWN_HASH_SIZE];

/* MAX_BLUNDER_ENTRIES now defined in engine_params.h */

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
    /* SplitMix64 PRNG — much higher quality than LCG, eliminates correlation */
    U64 z = 0x9E3779B97F4A7C15ULL; /* golden ratio hash constant */
    int i;
    for (i = 0; i < 12 * 64 + 1 + 4 + 64; i++)
    {
        z += 0x9E3779B97F4A7C15ULL;
        U64 x = z;
        x ^= x >> 30;
        x *= 0xBF58476D1CE4E5B9ULL;
        x ^= x >> 27;
        x *= 0x94D049BB133111EBULL;
        x ^= x >> 31;
        zobrist_table[i] = x;
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

/* PST accessor: returns runtime PST value if loaded, else compile-time default.
 * Mirrors get_piece_value() for consistency. */
static int get_mg_pst(int piece_type, int sq)
{
    if (g_runtime_params.loaded && piece_type > 0 && piece_type < 7)
        return g_runtime_params.mg_pst[piece_type - 1][sq];
    return mg_pst[piece_type][sq];
}

static int get_eg_pst(int piece_type, int sq)
{
    if (g_runtime_params.loaded && piece_type > 0 && piece_type < 7)
        return g_runtime_params.eg_pst[piece_type - 1][sq];
    return eg_pst[piece_type][sq];
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

static int piece_on_square(const Board *b, int sq);

/**
 * Check if a move gives check to the opponent
 *
 * @param b The board position
 * @param move The move to check
 * @return 1 if the move gives check, 0 otherwise
 */
static int move_gives_check(Board *b, const Move *move)
{
    int stm = b->side_to_move;
    int opp = 1 - stm;
    int opp_king_sq = b->king_sq[opp];
    int from = move->from;
    int to = move->to;
    int piece = piece_on_square(b, from);

    U64 occupied = all_pieces(b);
    U64 from_bb = 1ULL << from;
    U64 to_bb = 1ULL << to;

    /* 1. 直接将军：走法后棋子是否攻击对方王 */
    U64 new_occupied = (occupied & ~from_bb) | to_bb;
    int check_piece = move->promotion ? move->promotion : piece;
    U64 opp_king_bb = 1ULL << opp_king_sq;

    switch (check_piece)
    {
        case KNIGHT:
            if (knight_attacks[to] & opp_king_bb)
                return 1;
            break;
        case KING:
            /* 王本身不会将军对方王（正规局面中王不相邻） */
            break;
        case PAWN:
        {
            U64 pawn_atk = 0;
            if (stm == WHITE)
            {
                if ((to + 7) < 64 && (to % 8) != 7)
                    pawn_atk |= (1ULL << (to + 7));
                if ((to + 9) < 64 && (to % 8) != 0)
                    pawn_atk |= (1ULL << (to + 9));
            }
            else
            {
                if ((to - 7) >= 0 && (to % 8) != 0)
                    pawn_atk |= (1ULL << (to - 7));
                if ((to - 9) >= 0 && (to % 8) != 7)
                    pawn_atk |= (1ULL << (to - 9));
            }
            if (pawn_atk & opp_king_bb)
                return 1;
            break;
        }
        case BISHOP:
            if (sliding_attacks_bishop(to, new_occupied) & opp_king_bb)
                return 1;
            break;
        case ROOK:
            if (sliding_attacks_rook(to, new_occupied) & opp_king_bb)
                return 1;
            break;
        case QUEEN:
            if ((sliding_attacks_bishop(to, new_occupied) |
                 sliding_attacks_rook(to, new_occupied)) & opp_king_bb)
                return 1;
            break;
    }

    /* 2. 间接将军（discovered check）：移除 from 格后是否打开了对对方王的射线 */
    U64 occ_no_from = occupied & ~from_bb;

    /* Castling: the rook also moves; adjust occ_no_from to reflect its departure */
    if (piece == KING && (to - from == 2 || from - to == 2))
    {
        int rook_from = (to > from) ? from + 3 : from - 4;
        int rook_to   = (to > from) ? from + 1 : from - 1;
        U64 rook_from_bb = 1ULL << rook_from;
        U64 rook_to_bb   = 1ULL << rook_to;
        new_occupied = (new_occupied & ~rook_from_bb) | rook_to_bb;
        occ_no_from &= ~rook_from_bb;
        if (sliding_attacks_rook(rook_to, new_occupied) & opp_king_bb)
            return 1;
    }

    /* en passant 时被吃的兵不在 from/to 格，需要额外移除 */
    if (move->capture == PAWN && b->en_passant == to)
    {
        int ep_capture_sq = (stm == WHITE) ? to - 8 : to + 8;
        occ_no_from &= ~(1ULL << ep_capture_sq);
        new_occupied &= ~(1ULL << ep_capture_sq);
    }

    U64 bishops_queens = b->pieces[stm][BISHOP] | b->pieces[stm][QUEEN];
    if (sliding_attacks_bishop(opp_king_sq, occ_no_from) & bishops_queens & ~from_bb)
        return 1;

    U64 rooks_queens = b->pieces[stm][ROOK] | b->pieces[stm][QUEEN];
    if (sliding_attacks_rook(opp_king_sq, occ_no_from) & rooks_queens & ~from_bb)
        return 1;

    return 0;
}

/**
 * Check if a move is a killer move
 *
 * @param s The search state
 * @param move The move to check
 * @param depth The current search depth
 * @return 1 if the move is a killer move, 0 otherwise
 */
static int is_killer_move(const SearchState *s, const Move *move, int ply)
{
    if (ply >= 64)
        return 0;

    int i;
    for (i = 0; i < 2; i++)
    {
        if (s->killers[ply][i].from == move->from &&
            s->killers[ply][i].to == move->to)
        {
            return 1;
        }
    }
    return 0;
}

static int mvv_lva(const Board *b, const Move *m);
static int move_gives_check(Board *b, const Move *move);

static int should_apply_lmr(const SearchState *s, const Move *move, int depth,
                            int move_num, int in_check, int is_endgame, int ply,
                            int see_val)
{
    if (!g_runtime_params.lmr_enabled)
        return 0;

    /* 将军逃脱中不应用 LMR：合法走法通常很少，每步都是关键，
     * 削减可能漏掉唯一的安全解。 */
    if (in_check)
        return 0;

    if (depth < g_runtime_params.lmr_min_depth)
        return 0;

    if (move_num < g_runtime_params.lmr_move_threshold)
        return 0;

    /* Exclude good captures (SEE >= 0) from LMR.
     * Use the cached SEE value directly — relying on score >= GOOD_CAPTURE_BASE
     * is fragile because capture_history can push good captures below the
     * threshold. */
    if (move->capture && see_val >= 0)
        return 0;

    /* Exclude promotions from LMR — they are always critical. */
    if (move->promotion)
        return 0;

    return 1;
}

/* Check if the current position is clearly winning for the side to move.
 * Used to reduce pruning aggression in winning positions. */
static int is_clearly_winning(const Board *b, int static_eval)
{
    /* If we're winning by more than a queen, we're clearly winning */
    if (static_eval > CLEARLY_WINNING_THRESHOLD)
        return 1;
    return 0;
}

static int calculate_reduction(SearchState *s, const Move *move, int depth, int move_num, int is_pv_node, int in_check, int static_eval, int ply, int see_val)
{
    if (depth < 1 || move_num < 1)
        return 0;
    int reduction = lmr_table[depth < 127 ? depth : 127][move_num < 63 ? move_num : 63];

    if (is_pv_node)
        reduction -= 1;
    if (in_check)
        reduction -= 1;
    if (move_num <= 3)
        reduction -= 1;
    /* Use cached SEE value to identify good captures — relying on
     * score >= GOOD_CAPTURE_BASE is fragile because capture_history
     * can push good captures below the threshold. */
    if (move->capture && see_val >= 0)
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
        if (npm <= g_runtime_params.endgame_phase_threshold)
        {
            reduction -= 1;
            if (move->promotion)
                reduction -= 1;
        }
    }

    /* Task 11: Endgame LMR conservative — pawn endgames and close kings. */
    {
        /* Pawn endgame: only pawns on board (no minors/majors).
         * Every move is critical in pawn endgames. */
        U64 minors_majors = s->board.pieces[WHITE][KNIGHT] | s->board.pieces[WHITE][BISHOP] |
                            s->board.pieces[WHITE][ROOK] | s->board.pieces[WHITE][QUEEN] |
                            s->board.pieces[BLACK][KNIGHT] | s->board.pieces[BLACK][BISHOP] |
                            s->board.pieces[BLACK][ROOK] | s->board.pieces[BLACK][QUEEN];
        if (!minors_majors)
            reduction -= 1;

        /* Close kings: when both kings are near each other (Chebyshev dist <= 3),
         * tactical opportunities are high — be conservative with reductions. */
        if (s->board.king_sq[WHITE] >= 0 && s->board.king_sq[BLACK] >= 0)
        {
            int wk_f = s->board.king_sq[WHITE] & 7, wk_r = s->board.king_sq[WHITE] >> 3;
            int bk_f = s->board.king_sq[BLACK] & 7, bk_r = s->board.king_sq[BLACK] >> 3;
            int king_dist = abs(wk_f - bk_f);
            int king_dist_r = abs(wk_r - bk_r);
            if (king_dist_r > king_dist) king_dist = king_dist_r;
            if (king_dist <= 3)
                reduction -= 1;
        }
    }

    /* In clearly winning positions, reduce LMR to avoid missing forced mates.
     * Uses the pre-computed static_eval passed from negamax instead of
     * calling evaluate() again, saving significant computation in the hot path. */
    if (is_clearly_winning(&s->board, static_eval))
        reduction = (reduction > 1) ? reduction - 1 : 0;

    int hist_val = s->history[move->from][move->to];
    if (hist_val > LMR_HISTORY_THRESHOLD)
        reduction -= 1;
    if (hist_val < -LMR_HISTORY_THRESHOLD)
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
                                         int alpha, int is_endgame, int static_eval, int ply,
                                         int improving)
{
    if (!g_runtime_params.futility_enabled)
        return 0;

    /* 深度门槛扩展到 4：depth 4 使用更紧的 margin（按 depth 3 计算），
     * 在保留战术可靠性的同时增加中局/残局的剪枝收益。
     * depth 5+ 仍禁用，避免漏掉深层战术。 */
    if (depth > 4 || depth <= 0)
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
    if (static_eval > FUTILITY_WINNING_THRESHOLD)
        return 0;

    /* depth 4 首次启用 futility，使用 depth 3 的紧 margin 以降低漏算风险 */
    int effective_depth = (depth == 4) ? 3 : depth;
    int margin = g_runtime_params.futility_margin_base * effective_depth;
    /* 非 improving 局面（对手有强威胁）时增大 margin，更保守剪枝 */
    if (!improving)
        margin = margin * 4 / 3;
    if (is_endgame)
        margin = margin * FUTILITY_EG_MARGIN_NUM / FUTILITY_EG_MARGIN_DEN;

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
    /* Guard against undefined behavior: __builtin_ctzll(0) is UB per C standard.
     * Return 64 (invalid square) for empty bitboard, which is safer than
     * unpredictable compiler-optimized behavior. */
    if (bb == 0)
        return 64;
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

    /* Initialize incremental PST+material scores */
    {
        int mg = 0, eg = 0;
        int s, pt2;
        for (s = 0; s < 2; s++)
        {
            int sign = (s == WHITE) ? 1 : -1;
            for (pt2 = PAWN; pt2 <= KING; pt2++)
            {
                U64 bb = b->pieces[s][pt2];
                while (bb)
                {
                    int sq = lsb_index(bb);
                    bb &= bb - 1;
                    int psq = (s == WHITE) ? sq : (sq ^ 56);
                    mg += sign * (get_piece_value(pt2) + get_mg_pst(pt2, psq));
                    eg += sign * (get_piece_value(pt2) + get_eg_pst(pt2, psq));
                }
            }
        }
        b->mg_score = mg;
        b->eg_score = eg;
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
    int ksq = b->king_sq[side];
    if (ksq < 0 || ksq > 63)
        return 0;
    return is_square_attacked(b, ksq, 1 - side);
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
    SearchState *s = (SearchState *)calloc(1, sizeof(SearchState));
    if (!s)
        return -INF - 1;
    board_from_fen(&s->board, fen);
    s->nodes = 0;
    s->start_time = get_time();
    s->time_limit = time_limit;
    s->aborted = 0;
    s->search_history_count = 0;
    s->game_history_count = 0;
    memset(s->killers, 0, sizeof(s->killers));
    memset(s->history, 0, sizeof(s->history));
    tt_init(s, 16);

    Board old = s->board;
    int side = s->board.side_to_move;
    int opp = 1 - side;
    U64 to_bb = 1ULL << to_sq;
    int cap = 0;
    if (s->board.pieces[opp][PAWN] & to_bb)
        cap = PAWN;
    else if (s->board.pieces[opp][KNIGHT] & to_bb)
        cap = KNIGHT;
    else if (s->board.pieces[opp][BISHOP] & to_bb)
        cap = BISHOP;
    else if (s->board.pieces[opp][ROOK] & to_bb)
        cap = ROOK;
    else if (s->board.pieces[opp][QUEEN] & to_bb)
        cap = QUEEN;
    else if (s->board.pieces[opp][KING] & to_bb)
        cap = KING;
    int from_pt = piece_on_square(&s->board, from_sq);
    int promotion = 0;
    if (from_pt == PAWN)
    {
        if ((side == WHITE && rank_of(to_sq) == 7) || (side == BLACK && rank_of(to_sq) == 0))
            promotion = QUEEN;
    }
    Move m = {from_sq, to_sq, promotion, cap, 0};
    UndoInfo undo;
    make_move(&s->board, &m, &undo);
    if (is_check(&s->board, side))
    {
        unmake_move(&s->board, &m, &undo);
        free(s->tt);
        free(s);
        return -INF - 1;
    }
    int score = -negamax(s, max_depth - 1, -INF, INF, 0, 1);
    unmake_move(&s->board, &m, &undo);
    free(s->tt);
    free(s);
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
                if (to < 64 && ((enemy & (1ULL << to)) || (b->en_passant == to)))
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
                if (to < 64 && ((enemy & (1ULL << to)) || (b->en_passant == to)))
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
                if (to >= 0 && ((enemy & (1ULL << to)) || (b->en_passant == to)))
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
                if (to >= 0 && ((enemy & (1ULL << to)) || (b->en_passant == to)))
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
				if (!is_square_attacked(b, 4, BLACK) && !is_square_attacked(b, 5, BLACK) && !is_square_attacked(b, 6, BLACK))
					moves[count++] = (Move){4, 6, 0, 0, 0};
			}
			if ((b->castling_rights & 2) && !(occupied & ((1ULL << 1) | (1ULL << 2) | (1ULL << 3))))
			{
				if (!is_square_attacked(b, 4, BLACK) && !is_square_attacked(b, 3, BLACK) && !is_square_attacked(b, 2, BLACK))
					moves[count++] = (Move){4, 2, 0, 0, 0};
			}
        }
        else
        {
			if ((b->castling_rights & 4) && !(occupied & ((1ULL << 61) | (1ULL << 62))))
			{
				if (!is_square_attacked(b, 60, WHITE) && !is_square_attacked(b, 61, WHITE) && !is_square_attacked(b, 62, WHITE))
					moves[count++] = (Move){60, 62, 0, 0, 0};
			}
			if ((b->castling_rights & 8) && !(occupied & ((1ULL << 57) | (1ULL << 58) | (1ULL << 59))))
			{
				if (!is_square_attacked(b, 60, WHITE) && !is_square_attacked(b, 59, WHITE) && !is_square_attacked(b, 58, WHITE))
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
    g_prof_make_move_calls++;
    int side = b->side_to_move;
    int opp = 1 - side;
    U64 from_bb = 1ULL << m->from;
    U64 to_bb = 1ULL << m->to;
    int pt = piece_on_square(b, m->from);
    if (pt == EMPTY)
    {
        /* Mark undo as skipped so unmake_move knows not to modify the board.
         * We still switch side_to_move to keep the call balanced. */
        assert(0 && "make_move: pt==EMPTY indicates move generation bug");
        undo->castling_rights = -1; /* Sentinel: make_move was skipped */
        b->side_to_move = opp;
        b->eval_score = EVAL_SCORE_INVALID;
        return;
    }

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
    undo->mg_score = b->mg_score;
    undo->eg_score = b->eg_score;

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

    /* Detect en passant capture early so we skip the regular capture handler */
    int is_ep_capture = (pt == PAWN && old_ep >= 0 && m->to == old_ep &&
                         (abs(m->to - m->from) == 7 || abs(m->to - m->from) == 9));

    if (m->capture && !is_ep_capture)
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

    /* Incremental PST+material score update */
    {
        int sign = (side == WHITE) ? 1 : -1;
        int psq_from = (side == WHITE) ? m->from : (m->from ^ 56);
        int psq_to = (side == WHITE) ? m->to : (m->to ^ 56);

        /* 1. Moving piece from->to: PST change only (material unchanged for non-promotion) */
        b->mg_score += sign * (get_mg_pst(pt, psq_to) - get_mg_pst(pt, psq_from));
        b->eg_score += sign * (get_eg_pst(pt, psq_to) - get_eg_pst(pt, psq_from));

        /* 2. Capture: remove captured piece's material+PST */
        if (m->capture)
        {
            if (undo->ep_capture_sq >= 0)
            {
                /* En passant: captured pawn is at ep_cap_sq, not at m->to */
                int ep_sq = undo->ep_capture_sq;
                int sign_opp = (opp == WHITE) ? 1 : -1;
                int psq_ep = (opp == WHITE) ? ep_sq : (ep_sq ^ 56);
                b->mg_score -= sign_opp * (get_piece_value(PAWN) + get_mg_pst(PAWN, psq_ep));
                b->eg_score -= sign_opp * (get_piece_value(PAWN) + get_eg_pst(PAWN, psq_ep));
            }
            else
            {
                /* Regular capture: remove captured piece at m->to */
                int cap_pt = m->capture;
                int sign_opp = (opp == WHITE) ? 1 : -1;
                int psq_cap = (opp == WHITE) ? m->to : (m->to ^ 56);
                b->mg_score -= sign_opp * (get_piece_value(cap_pt) + get_mg_pst(cap_pt, psq_cap));
                b->eg_score -= sign_opp * (get_piece_value(cap_pt) + get_eg_pst(cap_pt, psq_cap));
            }
        }

        /* 3. Promotion: replace pawn with promoted piece at m->to */
        if (m->promotion)
        {
            int promo = m->promotion;
            b->mg_score += sign * ((get_piece_value(promo) + get_mg_pst(promo, psq_to)) - (get_piece_value(PAWN) + get_mg_pst(PAWN, psq_to)));
            b->eg_score += sign * ((get_piece_value(promo) + get_eg_pst(promo, psq_to)) - (get_piece_value(PAWN) + get_eg_pst(PAWN, psq_to)));
        }

        /* 4. Castling: move rook */
        if (pt == KING)
        {
            if (side == WHITE)
            {
                if (m->from == 4 && m->to == 6)
                {
                    /* White kingside: rook h1(7) -> f1(5) */
                    b->mg_score += get_mg_pst(ROOK, 5) - get_mg_pst(ROOK, 7);
                    b->eg_score += get_eg_pst(ROOK, 5) - get_eg_pst(ROOK, 7);
                }
                else if (m->from == 4 && m->to == 2)
                {
                    /* White queenside: rook a1(0) -> d1(3) */
                    b->mg_score += get_mg_pst(ROOK, 3) - get_mg_pst(ROOK, 0);
                    b->eg_score += get_eg_pst(ROOK, 3) - get_eg_pst(ROOK, 0);
                }
            }
            else
            {
                if (m->from == 60 && m->to == 62)
                {
                    /* Black kingside: rook h8(63) -> f8(61) */
                    b->mg_score -= get_mg_pst(ROOK, 61 ^ 56) - get_mg_pst(ROOK, 63 ^ 56);
                    b->eg_score -= get_eg_pst(ROOK, 61 ^ 56) - get_eg_pst(ROOK, 63 ^ 56);
                }
                else if (m->from == 60 && m->to == 58)
                {
                    /* Black queenside: rook a8(56) -> d8(59) */
                    b->mg_score -= get_mg_pst(ROOK, 59 ^ 56) - get_mg_pst(ROOK, 56 ^ 56);
                    b->eg_score -= get_eg_pst(ROOK, 59 ^ 56) - get_eg_pst(ROOK, 56 ^ 56);
                }
            }
        }
    }
}

void unmake_move(Board *b, const Move *m, const UndoInfo *undo)
{
    g_prof_unmake_move_calls++;
    /* If make_move was skipped (piece_on_square returned EMPTY),
     * just restore side_to_move and return without modifying the board. */
    if (undo->castling_rights == -1)
    {
        b->side_to_move = 1 - b->side_to_move;
        return;
    }

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
    b->mg_score = undo->mg_score;
    b->eg_score = undo->eg_score;
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
#include "engine_search_v2.c"  /* Task #109/#110: SEE bug 修复 + SEE 剪枝 bug 修复 + TT 诊断 */
#include "engine_search_root.c"  /* 回滚到原版（TT 大小 1GB 测试无效果） */
#include "engine_debug.c"
