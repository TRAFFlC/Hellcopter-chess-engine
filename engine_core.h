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
    U64 pawn_hash;
    int king_sq[2];
    int phase;
    int npm[2];
} Board;

typedef struct
{
    int captured_piece;
    int castling_rights;
    int en_passant;
    int halfmove_clock;
    U64 hash;
    U64 pawn_hash;
    int eval_score;
    int phase;
    int king_sq[2];
    int npm[2];
    int mailbox_from;
    int mailbox_to;
    int mailbox_ep;
    int ep_capture_sq;
    int fullmove_number;
} UndoInfo;

typedef struct
{
    double optimal_time;
    double max_time;
    double remaining;
    double increment;
    int moves_to_go;
    int move_number;
    int easy_move_count;
    int prev_best_move_from;
    int prev_best_move_to;
    int stable_count;
    int panic_flag;
    double start_time;
} TimeManager;

typedef struct
{
    U64 key;
    int16_t depth;
    int16_t score;
    int16_t flag;
    Move best_move;
    uint8_t generation;
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
    int nodes;
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
} SearchState;

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
Move find_best_move_c(const char *fen, double time_limit, double time_left, double increment, int moves_to_go, int move_number, int max_depth, int *out_nodes,
                      U64 *game_history, int game_history_count);
Move find_best_move_smp(const char *fen, double time_limit, double time_left, double increment, int moves_to_go, int move_number, int max_depth, int *out_nodes,
                        U64 *game_history, int game_history_count);
U64 compute_hash_from_fen(const char *fen);
int popcount(U64 x);
U64 get_attacks(const Board *b, int sq, int side);

/* Parameter loading function */
int load_params_from_file(const char *filename);

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

#endif
