#ifndef ENGINE_CORE_H
#define ENGINE_CORE_H

#include <stddef.h>
#include <stdint.h>

typedef unsigned long long U64;

enum
{
    EMPTY = 0,
    PAWN = 1,
    KNIGHT = 2,
    BISHOP = 3,
    ROOK = 4,
    QUEEN = 5,
    KING = 6
};

enum
{
    WHITE = 0,
    BLACK = 1
};

typedef struct
{
    int from;
    int to;
    int promotion;
    int capture;
    int score;
} Move;

typedef struct
{
    U64 pieces[2][7];
    int side_to_move;
    int castling_rights;
    int en_passant;
    int halfmove_clock;
    int fullmove_number;
    int eval_score;
    int mailbox[64];
    U64 hash;
    int king_sq[2];
    int phase;
    int npm[2];
    int mg_score;  /* 中局增量评估分数 (白方视角) */
    int eg_score;  /* 残局增量评估分数 (白方视角) */
} Board;

typedef struct
{
    int captured_piece;
    int castling_rights;
    int en_passant;
    int halfmove_clock;
    U64 hash;
    int eval_score;
    int phase;
    int king_sq[2];
    int npm[2];
    int mailbox_from;
    int mailbox_to;
    int mailbox_ep;
    int ep_capture_sq;
    int fullmove_number;
    int mg_score;
    int eg_score;
} UndoInfo;

typedef struct
{
    double optimal_time;
    double max_time;
    double remaining;
    double increment;
    int moves_to_go;
    int move_number;
    int prev_best_move_from;
    int prev_best_move_to;
    int prev_best_promotion;
    int stable_count;
    int panic_flag;
    double start_time;
    /* Search instability detection */
    int score_history[4];
    int best_from_history[4];
    int best_to_history[4];
    int best_promo_history[4];
    int history_count;
    int instability_count;
    int is_endgame;
    double endgame_factor;
    double complexity_factor;
    /* Critical position detection (Task 5) */
    double base_optimal_time;
    int critical_position_flag;
    double time_bank;
    int root_eval;
    int aw_fails_last_iter;
    int nodes_last_iter;
} TimeManager;

typedef struct
{
    U64 key;
    int16_t depth;
    int32_t score;   /* int32 to hold MATE_SCORE (900000) without overflow */
    int16_t flag;
    Move best_move;
    uint16_t generation;
} TT_Entry;

typedef struct
{
    TT_Entry entries[4];
} TT_Cluster;

typedef struct
{
    Board board;
    TT_Cluster *tt;
    int tt_cluster_count;
    int tt_generation;
    Move killers[64][2];
    int history[64][64];
    Move countermove[2][64][64];
    Move followup[2][64][64];
    Move move_stack[128];
    Move pv_table[128][64];
    int pv_length[128];
    long long nodes;
    long long node_limit;
    double start_time;
    double time_limit;
    int aborted;
    U64 search_history[256];
    int search_history_count;
    U64 game_history[512];
    int game_history_count;

    int lmr_reductions;
    int lmr_re_searches;
    int lmr_nodes_saved;

    int futility_prunes;
    int futility_nodes_saved;

    int razoring_prunes;
    int razoring_nodes_saved;

    int time_check_mask;
    long long tb_hits;

    int static_eval_stack[128];
    Move se_excluded[128]; /* Singular Extension: excluded move per ply */
    int piece_type_stack[128]; /* Piece type before make_move, for cont_history indexing */

    /* ProbCut statistics */
    int probcut_prunes;
    int probcut_nodes_saved;

    /* SMP tracking (Task 5, 6, 8) */
    int thread_id;
    long long tt_hits;
    long long tt_misses;
    int tt_contention_count;
} SearchState;

/* Heuristic snapshot for ponderhit context preservation (Task 3) */
typedef struct {
    Move killers[64][2];
    int history[64][64];
    Move countermove[2][64][64];
    Move followup[2][64][64];
    int valid;
} HeuristicSnapshot;

void save_heuristic_snapshot(const SearchState *s);
void restore_heuristic_snapshot(SearchState *s);
void set_preserve_heuristics(int flag);

/* SMP statistics (Task 5) */
typedef struct {
    long long tt_hits_per_thread[64];
    long long tt_misses_per_thread[64];
    long long nodes_per_thread[64];
    int depth_per_thread[64];
    int tt_contention_per_thread[64];
    int num_threads;
} SMP_Stats;

SMP_Stats get_smp_stats(void);
void reset_smp_stats(void);

void board_from_fen(Board *b, const char *fen);
void board_to_fen(const Board *b, char *fen, size_t fen_size);
int generate_legal_moves(Board *b, Move *moves);
void make_move(Board *b, const Move *m, UndoInfo *undo);
void unmake_move(Board *b, const Move *m, const UndoInfo *undo);
int is_check(const Board *b, int side);
int is_game_over(Board *b);
int evaluate(Board *b);
int quiescence_search(SearchState *s, int alpha, int beta, int ply, int qs_depth);
int negamax(SearchState *s, int depth, int alpha, int beta, int ext_count, int ply);
Move find_best_move_c(const char *fen, double time_limit, double time_left, double increment, int moves_to_go, int move_number, int max_depth, long long node_limit, int *out_nodes,
                 U64 *game_history, int game_history_count);
Move find_best_move_smp(const char *fen, double time_limit, double time_left, double increment, int moves_to_go, int move_number, int max_depth, long long node_limit, int *out_nodes,
                 U64 *game_history, int game_history_count);
U64 compute_hash_from_fen(const char *fen);
int popcount(U64 x);
U64 get_attacks(const Board *b, int sq, int side);

/* Parameter loading function */
int load_params_from_file(const char *filename);

/* Thread count setter for UCI Threads option */
void set_num_threads(int n);
int get_threading_enabled(void);

/* LMR statistics structure */
typedef struct
{
    int reductions;  // Number of times LMR was applied
    int re_searches; // Number of times re-search was needed
    int nodes_saved; // Estimated nodes saved by LMR
} LMR_Stats;

/* Get LMR statistics from last search */
LMR_Stats get_lmr_stats(void);

/* Futility Pruning statistics structure */
typedef struct
{
    int prunes;      // Number of times Futility Pruning was applied
    int nodes_saved; // Estimated nodes saved by Futility Pruning
} Pruning_Stats;

/* Get Futility Pruning statistics from last search */
Pruning_Stats get_pruning_stats(void);

/* Razoring statistics structure */
typedef struct
{
    int prunes;      // Number of times Razoring was applied
    int nodes_saved; // Estimated nodes saved by Razoring
} Razoring_Stats;

/* Get Razoring statistics from last search */
Razoring_Stats get_razoring_stats(void);

/* Get last search info (0=depth, 1=nodes, 2=score) */
int get_last_search_info(int what);

/* Perft function for move generation testing */
U64 perft(const char *fen, int depth);

/* Global abort flag for stopping search externally */
void set_engine_abort(int flag);
int get_engine_abort(void);

/* Info callback for iterative deepening output */
typedef void (*EngineInfoCallback)(int depth, int score, int nodes, int time_ms, const char *pv_str);
void set_engine_info_callback(EngineInfoCallback cb);

/* Global TT management */
void tt_clear_global(void);
void tt_resize_global(int hash_mb);
void set_preserve_tt_generation(int flag);

/* Extract ponder move from TT after search completes */
int extract_ponder_move(const Board *b, Move best_move, Move *ponder_move);

/* Bug Hunter: board consistency check (make/unmake + incremental state) */
int board_consistency_check(const char *fen);

/* Bug Hunter: perft divide (per-move perft counts) */
int perft_divide(const char *fen, int depth, int *out_from, int *out_to,
                 int *out_promo, U64 *out_count, U64 *out_total);

/* Bug Hunter: SEE value for a move */
int see_test(const char *fen, int from_sq, int to_sq);

/* Bug Hunter: eval consistency stress test */
int eval_consistency_stress(const char *fen, int cycles);

/* Pruning toggle control for ablation testing */
int set_search_param(const char *name, int value);
int get_search_param(const char *name);
int reload_params(const char *filename);

/* ============================================================================
 * SEARCH PROFILE — Performance instrumentation for profiling
 * ============================================================================ */
typedef struct {
    long long eval_calls;        /* evaluate() invocations */
    long long qs_calls;          /* quiescence_search() invocations */
    long long make_move_calls;   /* make_move() invocations */
    long long unmake_move_calls; /* unmake_move() invocations */
    long long nmp_triggered;     /* Null Move Pruning applied */
    long long nmp_cutoffs;       /* NMP resulted in beta cutoff */
    long long rfp_triggered;     /* Reverse Futility Pruning applied */
    long long lmr_applied;       /* LMR reductions applied */
    long long lmr_full_research; /* LMR re-searches at full depth */
    long long futility_pruned;   /* Futility pruned moves */
    long long razoring_triggered;/* Razoring applied */
    long long lmp_pruned;        /* Late Move Pruning pruned moves */
    long long see_pruned;        /* SEE-based capture pruning */
    long long history_pruned;    /* History-based pruning */
    long long probcut_triggered; /* ProbCut applied */
    long long probcut_cutoffs;   /* ProbCut resulted in beta cutoff */
    long long tt_hits;           /* Transposition table hits */
    long long tt_stores;         /* TT entries stored */
    long long total_nodes;       /* Total nodes searched */
    long long qs_nodes;          /* Nodes in quiescence search */
} SearchProfile;

SearchProfile get_search_profile(void);
void reset_search_profile(void);

/* Regenerate lmr_table after runtime params are loaded (P1 fix) */
void regenerate_lmr_table(void);

#endif
