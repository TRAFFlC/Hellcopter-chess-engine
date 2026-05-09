#include "engine_core.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>

#ifdef _MSC_VER
#include <intrin.h>
#define POPCNT64(x) ((int)__popcnt64(x))
#else
#define POPCNT64(x) ((int)__builtin_popcountll(x))
#endif

#define INF 1000000
#define MATE_SCORE 900000
#define DELTA 900
#define MAX_MOVES 256
#define ENGINE_VERSION 20260511

static const int piece_values[7] = {0, 100, 300, 320, 480, 900, 20000};

static const int mg_pawn[64] = {
    0, 0, 0, 0, 0, 0, 0, 0,
    90, 90, 90, 90, 90, 90, 90, 90,
    50, 50, 60, 80, 80, 60, 50, 50,
    20, 20, 40, 65, 65, 40, 20, 20,
    10, 10, 20, 45, 45, 20, 10, 10,
    5, 0, -5, 10, 10, -5, 0, 5,
    5, 10, 10, 0, 0, 10, 10, 5,
    0, 0, 0, 0, 0, 0, 0, 0};

static const int eg_pawn[64] = {
    0, 0, 0, 0, 0, 0, 0, 0,
    80, 80, 80, 80, 80, 80, 80, 80,
    50, 50, 50, 50, 50, 50, 50, 50,
    30, 30, 30, 30, 30, 30, 30, 30,
    20, 20, 20, 20, 20, 20, 20, 20,
    10, 10, 10, 10, 10, 10, 10, 10,
    0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0};

static const int mg_knight[64] = {
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20, 0, 0, 0, 0, -20, -40,
    -30, 0, 10, 15, 15, 10, 0, -30,
    -30, 5, 15, 30, 30, 15, 5, -30,
    -30, 0, 15, 30, 30, 15, 0, -30,
    -30, 5, 10, 15, 15, 10, 5, -30,
    -40, -20, 0, 5, 5, 0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50};

static const int eg_knight[64] = {
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20, 0, 0, 0, 0, -20, -40,
    -30, 0, 10, 15, 15, 10, 0, -30,
    -30, 0, 15, 25, 25, 15, 0, -30,
    -30, 0, 15, 25, 25, 15, 0, -30,
    -30, 0, 10, 15, 15, 10, 0, -30,
    -40, -20, 0, 0, 0, 0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50};

static const int mg_bishop[64] = {
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -10, 0, 5, 10, 10, 5, 0, -10,
    -10, 5, 5, 10, 10, 5, 5, -10,
    -10, 0, 10, 10, 10, 10, 0, -10,
    -10, 10, 10, 10, 10, 10, 10, -10,
    -10, 5, 0, 0, 0, 0, 5, -10,
    -20, -10, -10, -10, -10, -10, -10, -20};

static const int eg_bishop[64] = {
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -10, 0, 5, 10, 10, 5, 0, -10,
    -10, 0, 10, 10, 10, 10, 0, -10,
    -10, 0, 10, 10, 10, 10, 0, -10,
    -10, 0, 10, 10, 10, 10, 0, -10,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -20, -10, -10, -10, -10, -10, -10, -20};

static const int mg_rook[64] = {
    0, 0, 0, 0, 0, 0, 0, 0,
    5, 10, 10, 10, 10, 10, 10, 5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    0, 0, 0, 5, 5, 0, 0, 0};

static const int eg_rook[64] = {
    0, 0, 0, 0, 0, 0, 0, 0,
    5, 10, 10, 10, 10, 10, 10, 5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    0, 0, 0, 5, 5, 0, 0, 0};

static const int mg_queen[64] = {
    -20, -10, -10, -5, -5, -10, -10, -20,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -10, 0, 5, 5, 5, 5, 0, -10,
    -5, 0, 5, 5, 5, 5, 0, -5,
    0, 0, 5, 5, 5, 5, 0, -5,
    -10, 5, 5, 5, 5, 5, 0, -10,
    -10, 0, 5, 0, 0, 0, 0, -10,
    -20, -10, -10, -5, -5, -10, -10, -20};

static const int eg_queen[64] = {
    -20, -10, -10, -5, -5, -10, -10, -20,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -10, 0, 5, 5, 5, 5, 0, -10,
    -5, 0, 5, 5, 5, 5, 0, -5,
    0, 0, 5, 5, 5, 5, 0, -5,
    -10, 5, 5, 5, 5, 5, 0, -10,
    -10, 0, 5, 0, 0, 0, 0, -10,
    -20, -10, -10, -5, -5, -10, -10, -20};

static const int mg_king[64] = {
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -20, -30, -30, -40, -40, -30, -30, -20,
    -10, -20, -20, -20, -20, -20, -20, -10,
    20, 20, 0, 0, 0, 0, 20, 20,
    20, 30, 10, 0, 0, 10, 30, 20};

static const int eg_king[64] = {
    -50, -40, -30, -20, -20, -30, -40, -50,
    -30, -20, -10, 0, 0, -10, -20, -30,
    -30, -10, 20, 30, 30, 20, -10, -30,
    -30, -10, 30, 40, 40, 30, -10, -30,
    -30, -10, 30, 40, 40, 30, -10, -30,
    -30, -10, 20, 30, 30, 20, -10, -30,
    -30, -30, 0, 0, 0, 0, -30, -30,
    -50, -30, -30, -30, -30, -30, -30, -50};

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
static void init_zobrist(void);

static int rank_of(int sq) { return sq >> 3; }
static int file_of(int sq) { return sq & 7; }

static U64 shift_north(U64 b) { return b << 8; }
static U64 shift_south(U64 b) { return b >> 8; }
static U64 shift_east(U64 b) { return (b << 1) & ~file_masks[0]; }
static U64 shift_west(U64 b) { return (b >> 1) & ~file_masks[7]; }

static U64 sliding_attacks_rook(int sq, U64 occupied)
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

static U64 sliding_attacks_bishop(int sq, U64 occupied)
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

static int piece_on_square(const Board *b, int sq)
{
    U64 bb = 1ULL << sq;
    int side, pt;
    for (side = 0; side < 2; side++)
    {
        for (pt = PAWN; pt <= KING; pt++)
        {
            if (b->pieces[side][pt] & bb)
                return pt;
        }
    }
    return EMPTY;
}

static int side_on_square(const Board *b, int sq)
{
    U64 bb = 1ULL << sq;
    int pt;
    for (pt = PAWN; pt <= KING; pt++)
    {
        if (b->pieces[WHITE][pt] & bb)
            return WHITE;
        if (b->pieces[BLACK][pt] & bb)
            return BLACK;
    }
    return -1;
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
    make_move(&s.board, &m);
    if (is_check(&s.board, old.side_to_move))
    {
        free(s.tt);
        return -INF - 1;
    }
    int score = -negamax(&s, max_depth - 1, -INF, INF, 0, 1);
    s.board = old;
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
    Move pseudo[MAX_MOVES];
    int n = generate_pseudo_legal_moves(b, pseudo);
    int count = 0;
    int i;
    for (i = 0; i < n; i++)
    {
        Board copy = *b;
        make_move(&copy, &pseudo[i]);
        if (!is_check(&copy, b->side_to_move))
        {
            moves[count++] = pseudo[i];
        }
    }
    return count;
}

void make_move(Board *b, const Move *m)
{
    int side = b->side_to_move;
    int opp = 1 - side;
    U64 from_bb = 1ULL << m->from;
    U64 to_bb = 1ULL << m->to;
    int pt = piece_on_square(b, m->from);
    if (pt == EMPTY)
        return;

    b->pieces[side][pt] &= ~from_bb;
    b->pieces[side][pt] |= to_bb;

    if (m->capture)
    {
        int cap_pt = m->capture;
        b->pieces[opp][cap_pt] &= ~to_bb;
    }

    if (m->promotion)
    {
        b->pieces[side][PAWN] &= ~to_bb;
        b->pieces[side][m->promotion] |= to_bb;
    }

    if (pt == KING)
    {
        if (side == WHITE)
        {
            if (m->from == 4 && m->to == 6)
            {
                b->pieces[WHITE][ROOK] &= ~(1ULL << 7);
                b->pieces[WHITE][ROOK] |= (1ULL << 5);
            }
            else if (m->from == 4 && m->to == 2)
            {
                b->pieces[WHITE][ROOK] &= ~(1ULL << 0);
                b->pieces[WHITE][ROOK] |= (1ULL << 3);
            }
            b->castling_rights &= ~3;
        }
        else
        {
            if (m->from == 60 && m->to == 62)
            {
                b->pieces[BLACK][ROOK] &= ~(1ULL << 63);
                b->pieces[BLACK][ROOK] |= (1ULL << 61);
            }
            else if (m->from == 60 && m->to == 58)
            {
                b->pieces[BLACK][ROOK] &= ~(1ULL << 56);
                b->pieces[BLACK][ROOK] |= (1ULL << 59);
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

    int old_ep = b->en_passant;

    if (pt == PAWN && abs(m->to - m->from) == 16)
    {
        b->en_passant = (m->from + m->to) / 2;
    }
    else
    {
        b->en_passant = -1;
    }

    if (pt == PAWN && old_ep >= 0 && m->to == old_ep && (abs(m->to - m->from) == 7 || abs(m->to - m->from) == 9))
    {
        int ep_cap_sq = (side == WHITE) ? (m->to - 8) : (m->to + 8);
        if (ep_cap_sq >= 0 && ep_cap_sq < 64)
        {
            b->pieces[opp][PAWN] &= ~(1ULL << ep_cap_sq);
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

    b->side_to_move = opp;
}

void unmake_move(Board *b, const Move *m, const Board *old)
{
    *b = *old;
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
int
evaluate(const Board *b)
{
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
                int mg = mg_pst[pt][psq];
                int eg = eg_pst[pt][psq];
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
                score += sign * (-35 * (files[f] - 1));
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
                score += sign * (-25);

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
                int bonus = (side == WHITE) ? (40 + 15 * r) : (40 + 15 * (7 - r));
                score += sign * bonus;
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
                score += sign * 10;
        }
    }

    for (side = 0; side < 2; side++)
    {
        int sign = (side == WHITE) ? 1 : -1;
        if (count_bits(b->pieces[side][BISHOP]) >= 2)
        {
            score += sign * 55;
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
                score += sign * 30;
            }
            else if (own_pawns_on_file == 0 && enemy_pawns_on_file > 0)
            {
                score += sign * 15;
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
                        score += sign * 8;
                    }
                }
                else if (!(own_pawns & file_mask) && (enemy_pawns & file_mask))
                {
                    if (!(own_rooks & file_mask))
                    {
                        score += sign * 4;
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
                score += sign * 15;
            else if (pawns_on_color >= 2)
                score += sign * (-15);
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
            score += sign * (30 + (enemy_king_on_8th ? 20 : 0)) * rooks_on_7th;
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
        score += sign * (-5 * attack_weight);

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
                score += sign * 45;

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

        score += sign * (-30 * count_bits(attacked_by_pawn));
        score += sign * (-25 * count_bits(attacked_by_knight));
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

    return score;
}

int is_game_over(const Board *b)
{
    Move moves[MAX_MOVES];
    int n = generate_legal_moves(b, moves);
    return n == 0;
}

U64 compute_hash(const Board *b)
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
    static const int mvv[7] = {0, 100, 300, 320, 480, 900, 20000};
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

static int tt_probe(SearchState *s, U64 key, int depth, int alpha, int beta, Move *out_move, int ply)
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
        if (e->flag == 0)
            return score;
        if (e->flag == 1 && score <= alpha)
            return score;
        if (e->flag == 2 && score >= beta)
            return score;
    }
    return INF + 1;
}

static void tt_store(SearchState *s, U64 key, int depth, int score, int flag, Move best_move, int ply)
{
    int idx = (int)(key % s->tt_size);
    TT_Entry *e = &s->tt[idx];
    if (e->key == 0 || e->depth <= depth)
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
    }
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

int quiescence_search(SearchState *s, int alpha, int beta, int ply)
{
    if (s->aborted)
        return 0;
    s->nodes++;

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
        Board copy = s->board;
        make_move(&s->board, &moves[i]);
        if (!is_check(&s->board, copy.side_to_move))
        {
            legal_count++;
            int score = -quiescence_search(s, -beta, -alpha, next_ply);
            if (score > alpha)
            {
                alpha = score;
                if (alpha >= beta)
                {
                    s->board = copy;
                    return beta;
                }
            }
        }
        s->board = copy;
    }

    if (in_check && legal_count == 0)
    {
        return -MATE_SCORE + ply;
    }

    return alpha;
}

int negamax(SearchState *s, int depth, int alpha, int beta, int ext_count, int ply)
{
    if (s->aborted)
        return 0;
    s->nodes++;
    if ((s->nodes & 511) == 0)
    {
        double elapsed = get_time() - s->start_time;
        if (elapsed >= s->time_limit)
        {
            s->aborted = 1;
            return 0;
        }
    }

    U64 key = compute_hash(&s->board);
    Move tt_move = {0};
    int tt_val = tt_probe(s, key, depth, alpha, beta, &tt_move, ply);
    if (tt_val != INF + 1)
        return tt_val;

    {
        int rep_i;
        int game_reps = 0;
        for (rep_i = 0; rep_i < s->search_history_count; rep_i++)
        {
            if (s->search_history[rep_i] == key)
                return 0;
        }
        for (rep_i = 0; rep_i < s->game_history_count; rep_i++)
        {
            if (s->game_history[rep_i] == key)
                game_reps++;
        }
        if (game_reps >= 2)
            return 0;
    }

    int saved_history_count = s->search_history_count;

    if (s->search_history_count < 256)
    {
        s->search_history[s->search_history_count] = key;
        s->search_history_count++;
    }

    int in_check = is_check(&s->board, s->board.side_to_move);
    if (in_check && ext_count < 4)
    {
        depth++;
        ext_count++;
    }

    if (depth <= 0)
    {
        s->search_history_count = saved_history_count;
        return quiescence_search(s, alpha, beta, ply);
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
            if (moves[i].score == 0)
            {
                moves[i].score = s->history[moves[i].from][moves[i].to];
            }
        }
    }
    sort_moves(moves, n);

    int best_score = -INF;
    Move best_move = {0};
    int flag = 1;

    if (depth >= 4 && !in_check && beta < INF - 1000 && has_non_pawn_material(b, b->side_to_move))
    {
        Board saved = *b;
        b->side_to_move = 1 - b->side_to_move;
        b->en_passant = -1;
        int null_score = -negamax(s, depth - 3, -beta, -beta + 1, 0, ply + 1);
        *b = saved;
        if (s->aborted)
        {
            s->search_history_count = saved_history_count;
            return 0;
        }
        if (null_score >= beta)
        {
            if (depth >= 6)
            {
                int saved_for_verify = s->search_history_count;
                s->search_history_count = saved_history_count;
                int verify_score = negamax(s, depth - 5, alpha, beta, ext_count, ply);
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
        Board old = *b;
        make_move(b, &moves[i]);
        if (is_check(b, old.side_to_move))
        {
            *b = old;
            continue;
        }
        legal_count++;

        int score;
        if (i == 0)
        {
            score = -negamax(s, depth - 1, -beta, -alpha, ext_count, ply + 1);
        }
        else
        {
            score = -negamax(s, depth - 1, -alpha - 1, -alpha, ext_count, ply + 1);
            if (score > alpha && score < beta)
            {
                score = -negamax(s, depth - 1, -beta, -alpha, ext_count, ply + 1);
            }
        }
        *b = old;

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
        Board copy = b;
        make_move(&b, &moves[i]);
        if (!is_check(&b, b.side_to_move ^ 1))
            legal++;
        b = copy;
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
debug_root_moves(const char *fen, int depth, int *out_scores, int *out_from, int *out_to, int *out_count)
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
    s.search_history_count = 0;
    s.game_history_count = 0;

    Board *b = &s.board;
    Move root_moves[MAX_MOVES];
    int n_moves = generate_pseudo_legal_moves(b, root_moves);
    int legal_moves_count = 0;
    int i;
    for (i = 0; i < n_moves; i++)
    {
        Board copy = *b;
        make_move(b, &root_moves[i]);
        if (!is_check(b, b->side_to_move ^ 1))
        {
            root_moves[legal_moves_count++] = root_moves[i];
        }
        *b = copy;
    }

    int count = 0;
    for (i = 0; i < legal_moves_count && count < 64; i++)
    {
        Board old = *b;
        make_move(b, &root_moves[i]);
        int score = -negamax(&s, depth - 1, -INF, INF, 0, 1);
        *b = old;
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
    s.search_history_count = 0;
    s.game_history_count = 0;

    Board *b = &s.board;
    Move root_moves[MAX_MOVES];
    int n_moves = generate_pseudo_legal_moves(b, root_moves);
    int legal_moves_count = 0;
    int i;
    for (i = 0; i < n_moves; i++)
    {
        Board copy = *b;
        make_move(b, &root_moves[i]);
        if (!is_check(b, b->side_to_move ^ 1))
        {
            root_moves[legal_moves_count++] = root_moves[i];
        }
        *b = copy;
    }

    int depth;
    for (depth = 1; depth <= max_depth; depth++)
    {
        int alpha = -INF, beta = INF;
        for (i = 0; i < legal_moves_count; i++)
        {
            Board old = *b;
            make_move(b, &root_moves[i]);
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
            *b = old;
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
    ensure_engine_tables_initialized();

    SearchState s;
    memset(&s, 0, sizeof(SearchState));
    board_from_fen(&s.board, fen);
    s.start_time = get_time();
    s.time_limit = time_limit;
    s.aborted = 0;
    s.nodes = 0;
    s.tt_size = 1 << 20;
    s.tt = (TT_Entry *)calloc(s.tt_size, sizeof(TT_Entry));
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

    Move best_move = {0};
    int best_score = -INF;
    int depth;

    Board *b = &s.board;
    Move root_moves[MAX_MOVES];
    int n_moves = generate_pseudo_legal_moves(b, root_moves);
    int legal_moves_count = 0;
    int i;
    for (i = 0; i < n_moves; i++)
    {
        Board copy = *b;
        make_move(b, &root_moves[i]);
        if (!is_check(b, b->side_to_move ^ 1))
        {
            root_moves[legal_moves_count++] = root_moves[i];
        }
        *b = copy;
    }

    if (legal_moves_count == 0)
    {
        if (out_nodes)
            *out_nodes = 0;
        free(s.tt);
        return best_move;
    }

    for (depth = 1; depth <= max_depth; depth++)
    {
        if (depth >= 5)
        {
            double elapsed = get_time() - s.start_time;
            if (elapsed >= time_limit * 0.8)
            {
                break;
            }
        }

        int nodes_before = s.nodes;

        Move current_best = {0};
        int current_score = -INF;
        int alpha = -INF, beta = INF;

        for (i = 0; i < legal_moves_count; i++)
        {
            Board old = *b;
            make_move(b, &root_moves[i]);
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
            *b = old;

            if (s.aborted)
                break;

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

        if (!s.aborted && current_score > -INF)
        {
            best_move = current_best;
            best_score = current_score;
            g_last_search_depth = depth;
            g_last_search_nodes = s.nodes;
            g_last_best_score = current_score;
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
        }

        if (s.aborted)
            break;
    }

    if (out_nodes)
        *out_nodes = s.nodes;
    free(s.tt);
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
