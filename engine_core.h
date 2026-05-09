#ifndef ENGINE_CORE_H
#define ENGINE_CORE_H

#include <stddef.h>

typedef unsigned long long U64;

enum {
    EMPTY = 0,
    PAWN = 1,
    KNIGHT = 2,
    BISHOP = 3,
    ROOK = 4,
    QUEEN = 5,
    KING = 6
};

enum {
    WHITE = 0,
    BLACK = 1
};

typedef struct {
    int from;
    int to;
    int promotion;
    int capture;
    int score;
} Move;

typedef struct {
    U64 pieces[2][7];
    int side_to_move;
    int castling_rights;
    int en_passant;
    int halfmove_clock;
    int fullmove_number;
} Board;

typedef struct {
    U64 key;
    int depth;
    int score;
    int flag;
    Move best_move;
} TT_Entry;

typedef struct {
    Board board;
    TT_Entry* tt;
    int tt_size;
    Move killers[64][2];
    int history[64][64];
    int nodes;
    double start_time;
    double time_limit;
    int aborted;
    U64 search_history[256];
    int search_history_count;
    U64 game_history[512];
    int game_history_count;
} SearchState;

void board_from_fen(Board* b, const char* fen);
void board_to_fen(const Board* b, char* fen, size_t fen_size);
int generate_legal_moves(const Board* b, Move* moves);
void make_move(Board* b, const Move* m);
void unmake_move(Board* b, const Move* m, const Board* old);
int is_check(const Board* b, int side);
int is_game_over(const Board* b);
int evaluate(const Board* b);
int quiescence_search(SearchState* s, int alpha, int beta, int ply);
int negamax(SearchState* s, int depth, int alpha, int beta, int ext_count, int ply);
Move find_best_move_c(const char* fen, double time_limit, int max_depth, int* out_nodes,
                       U64* game_history, int game_history_count);
U64 compute_hash(const Board* b);
U64 compute_hash_from_fen(const char* fen);
int popcount(U64 x);
U64 get_attacks(const Board* b, int sq, int side);

#endif
