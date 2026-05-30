#include "engine_core.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <time.h>

#ifdef _WIN32
#include <windows.h>
#include <process.h>
#include <io.h>
#include <fcntl.h>
#else
#include <pthread.h>
#include <unistd.h>
#endif

#define MAX_LINE 4096
#define MAX_FEN 256
#define MAX_MOVES 256
#define MAX_MOVE_STR 8
#define MAX_POS_HISTORY 512

#ifndef ENGINE_VERSION
#define ENGINE_VERSION 20260511
#endif

typedef unsigned short U16;
typedef unsigned int U32;

static U64 g_polyglot_random[1851];
static int g_polyglot_initialized = 0;

static void init_polyglot_random(void)
{
    if (g_polyglot_initialized) return;
    g_polyglot_initialized = 1;

    U64 state = 0xD9348E5E5A5A5A5AULL;
    for (int i = 0; i < 1851; i++) {
        state ^= (state >> 12);
        state ^= (state << 25);
        state ^= (state >> 27);
        g_polyglot_random[i] = state * 0x2545F4914F6CDD1DULL;
    }
}

static U64 polyglot_hash(const Board *b)
{
    init_polyglot_random();
    U64 h = 0;

    static const int piece_map[2][7] = {
        {-1, 0, 1, 2, 3, 4, 5},
        {-1, 6, 7, 8, 9, 10, 11}
    };

    for (int side = 0; side < 2; side++) {
        for (int ptype = PAWN; ptype <= KING; ptype++) {
            U64 bb = b->pieces[side][ptype];
            while (bb) {
                int sq = __builtin_ctzll(bb);
                bb &= bb - 1;
                int idx = piece_map[side][ptype];
                h ^= g_polyglot_random[64 * idx + sq];
            }
        }
    }

    int castling = 0;
    if (b->castling_rights & 1) castling |= 1;
    if (b->castling_rights & 2) castling |= 2;
    if (b->castling_rights & 4) castling |= 4;
    if (b->castling_rights & 8) castling |= 8;
    if (castling) {
        h ^= g_polyglot_random[768 + castling - 1];
    }

    if (b->en_passant >= 0 && b->en_passant < 64) {
        int ep_file = b->en_passant & 7;
        h ^= g_polyglot_random[772 + ep_file];
    }

    if (b->side_to_move == BLACK) {
        h ^= g_polyglot_random[780];
    }

    return h;
}

typedef struct {
    U64 key;
    U16 move;
    U16 weight;
    U32 learn;
} PolyglotEntry;

static PolyglotEntry *g_book_entries = NULL;
static int g_book_count = 0;
static int g_book_capacity = 0;
static int g_own_book = 1;
static char g_book_path[MAX_LINE] = "";
static int g_book_randomness = 20;

static int load_polyglot_book(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) return 0;

    fseek(f, 0, SEEK_END);
    long file_size = ftell(f);
    fseek(f, 0, SEEK_SET);

    if (file_size % 16 != 0) {
        fclose(f);
        return 0;
    }

    g_book_count = (int)(file_size / 16);
    g_book_entries = (PolyglotEntry *)malloc(file_size);
    if (!g_book_entries) {
        fclose(f);
        return 0;
    }

    for (int i = 0; i < g_book_count; i++) {
        g_book_entries[i].key   = ((U64)fgetc(f) << 56) | ((U64)fgetc(f) << 48) |
                                  ((U64)fgetc(f) << 40) | ((U64)fgetc(f) << 32) |
                                  ((U64)fgetc(f) << 24) | ((U64)fgetc(f) << 16) |
                                  ((U64)fgetc(f) << 8)  | (U64)fgetc(f);
        g_book_entries[i].move  = ((U16)fgetc(f) << 8) | (U16)fgetc(f);
        g_book_entries[i].weight= ((U16)fgetc(f) << 8) | (U16)fgetc(f);
        g_book_entries[i].learn = ((U32)fgetc(f) << 24) | ((U32)fgetc(f) << 16) |
                                  ((U32)fgetc(f) << 8) | (U32)fgetc(f);
    }

    fclose(f);
    return g_book_count;
}

static void free_polyglot_book(void)
{
    if (g_book_entries) {
        free(g_book_entries);
        g_book_entries = NULL;
    }
    g_book_count = 0;
}

static int polyglot_decode_move(U16 encoded, int *from_out, int *to_out, int *promo_out)
{
    *from_out = encoded & 0x3F;
    *to_out = (encoded >> 6) & 0x3F;
    int promo_code = (encoded >> 12) & 0x7;
    *promo_out = 0;
    switch (promo_code) {
        case 1: *promo_out = KNIGHT; break;
        case 2: *promo_out = BISHOP; break;
        case 3: *promo_out = ROOK; break;
        case 4: *promo_out = QUEEN; break;
    }
    return 1;
}

static U64 xorshift64_state = 0;

static U64 xorshift64(void)
{
    if (xorshift64_state == 0)
        xorshift64_state = (U64)time(NULL) ^ ((U64)clock() << 16);
    U64 x = xorshift64_state;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    xorshift64_state = x;
    return x;
}

static int find_book_move(const Board *b, char *out_move)
{
    if (!g_own_book) return 0;
    if (!g_book_entries || g_book_count == 0) return 0;

    U64 target = polyglot_hash(b);

    int left = 0, right = g_book_count - 1;
    int found_idx = -1;
    while (left <= right) {
        int mid = (left + right) / 2;
        if (g_book_entries[mid].key < target) {
            left = mid + 1;
        } else if (g_book_entries[mid].key > target) {
            right = mid - 1;
        } else {
            found_idx = mid;
            break;
        }
    }

    if (found_idx < 0) return 0;

    while (found_idx > 0 && g_book_entries[found_idx - 1].key == target) {
        found_idx--;
    }

    int start_idx = found_idx;
    int match_count = 0;
    int idx = found_idx;
    while (idx < g_book_count && g_book_entries[idx].key == target) {
        match_count++;
        idx++;
    }

    int selected_move = -1;

    if (g_book_randomness > 0 && match_count > 1) {
        int total_weight = 0;
        for (int i = 0; i < match_count; i++) {
            int w = (int)g_book_entries[start_idx + i].weight;
            if (w <= 0) w = 1;
            total_weight += w;
        }
        if (total_weight > 0) {
            int r = (int)(xorshift64() % (U64)total_weight);
            int cumulative = 0;
            for (int i = 0; i < match_count; i++) {
                int w = (int)g_book_entries[start_idx + i].weight;
                if (w <= 0) w = 1;
                cumulative += w;
                if (r < cumulative) {
                    selected_move = g_book_entries[start_idx + i].move;
                    break;
                }
            }
        }
    }

    if (selected_move < 0) {
        int best_weight = 0;
        for (int i = 0; i < match_count; i++) {
            if (g_book_entries[start_idx + i].weight > best_weight) {
                best_weight = g_book_entries[start_idx + i].weight;
                selected_move = g_book_entries[start_idx + i].move;
            }
        }
    }

    if (selected_move < 0) return 0;

    int from, to, promo;
    polyglot_decode_move((U16)selected_move, &from, &to, &promo);

    out_move[0] = 'a' + (from & 7);
    out_move[1] = '1' + (from >> 3);
    out_move[2] = 'a' + (to & 7);
    out_move[3] = '1' + (to >> 3);
    out_move[4] = '\0';

    if (promo) {
        switch (promo) {
            case KNIGHT: out_move[4] = 'n'; break;
            case BISHOP: out_move[4] = 'b'; break;
            case ROOK:   out_move[4] = 'r'; break;
            case QUEEN:  out_move[4] = 'q'; break;
        }
        out_move[5] = '\0';
    }

    return 1;
}

static Board g_board;
static U64 g_position_history[MAX_POS_HISTORY];
static int g_position_history_count = 0;

static int g_go_params_wtime;
static int g_go_params_btime;
static int g_go_params_winc;
static int g_go_params_binc;
static int g_go_params_depth;
static int g_go_params_movetime;
static int g_go_infinite;

static char g_exe_dir[MAX_LINE];

static void get_exe_dir(void)
{
    g_exe_dir[0] = '\0';
#ifdef _WIN32
    GetModuleFileNameA(NULL, g_exe_dir, MAX_LINE);
    char *last_sep = strrchr(g_exe_dir, '\\');
    if (!last_sep) last_sep = strrchr(g_exe_dir, '/');
    if (last_sep) *last_sep = '\0';
#else
    ssize_t len = readlink("/proc/self/exe", g_exe_dir, MAX_LINE - 1);
    if (len > 0) {
        g_exe_dir[len] = '\0';
        char *last_sep = strrchr(g_exe_dir, '/');
        if (last_sep) *last_sep = '\0';
    }
#endif
}

static char *strip(char *s)
{
    while (*s && isspace((unsigned char)*s)) s++;
    char *end = s + strlen(s) - 1;
    while (end > s && isspace((unsigned char)*end)) *end-- = '\0';
    return s;
}

static int sq_to_str(int sq, char *out)
{
    out[0] = 'a' + (sq & 7);
    out[1] = '1' + (sq >> 3);
    out[2] = '\0';
    return 2;
}

static void move_to_uci(const Move *m, char *out)
{
    char from[4], to[4];
    sq_to_str(m->from, from);
    sq_to_str(m->to, to);
    sprintf(out, "%s%s", from, to);
    if (m->promotion) {
        char *p = out + 4;
        switch (m->promotion) {
            case KNIGHT: *p++ = 'n'; break;
            case BISHOP: *p++ = 'b'; break;
            case ROOK:   *p++ = 'r'; break;
            case QUEEN:  *p++ = 'q'; break;
        }
        *p = '\0';
    }
}

static int uci_to_sq(const char *s)
{
    if (strlen(s) < 2) return -1;
    int f = s[0] - 'a';
    int r = s[1] - '1';
    if (f < 0 || f > 7 || r < 0 || r > 7) return -1;
    return r * 8 + f;
}

static int str_to_promotion(char c)
{
    switch (c) {
        case 'n': return KNIGHT;
        case 'b': return BISHOP;
        case 'r': return ROOK;
        case 'q': return QUEEN;
    }
    return 0;
}

static void load_opening_book(void)
{
    free_polyglot_book();

    if (g_book_path[0] != '\0') {
        int count = load_polyglot_book(g_book_path);
        if (count > 0) {
            fprintf(stderr, "Loaded opening book from %s: %d positions\n", g_book_path, count);
            return;
        }
        fprintf(stderr, "Failed to load book from BookPath: %s\n", g_book_path);
    }

    char path[MAX_LINE];
    const char *book_names[] = {"Goi5.1.bin", "book.bin"};
    int count = 0;
    for (int i = 0; i < 2 && count <= 0; i++) {
        sprintf(path, "%s\\%s", g_exe_dir, book_names[i]);
        count = load_polyglot_book(path);
        if (count <= 0) {
            sprintf(path, "%s/%s", g_exe_dir, book_names[i]);
            count = load_polyglot_book(path);
        }
        if (count > 0) {
            fprintf(stderr, "Loaded opening book (%s): %d positions\n", book_names[i], count);
        }
    }
}

static double compute_time(int wtime, int btime, int winc, int binc, int movetime)
{
    if (movetime > 0) return movetime / 1000.0;

    int remaining_ms, inc_ms;
    if (g_board.side_to_move == WHITE) {
        remaining_ms = wtime;
        inc_ms = winc;
    } else {
        remaining_ms = btime;
        inc_ms = binc;
    }
    if (remaining_ms <= 0) return 2.0;

    double remaining = remaining_ms / 1000.0;
    double inc = inc_ms / 1000.0;
    int move_num = g_board.fullmove_number;

    int estimated_moves_left;
    double time_fraction;
    if (move_num <= 10) {
        estimated_moves_left = 40 - move_num;
        time_fraction = 0.5;
    } else if (move_num <= 20) {
        estimated_moves_left = 30;
        time_fraction = 0.8;
    } else if (move_num <= 40) {
        estimated_moves_left = 50 - move_num;
        if (estimated_moves_left < 15) estimated_moves_left = 15;
        time_fraction = 1.0;
    } else {
        estimated_moves_left = 60 - move_num;
        if (estimated_moves_left < 10) estimated_moves_left = 10;
        time_fraction = 1.2;
    }

    double time_limit = remaining / estimated_moves_left + inc * 0.85;
    if (time_limit > remaining * 0.5) time_limit = remaining * 0.5;
    time_limit *= time_fraction;

    if (inc > 0 && time_limit < inc * 0.9) time_limit = inc * 0.9;
    if (remaining < inc * 3 && inc > 0 && time_limit > inc * 0.95)
        time_limit = inc * 0.95;

    if (time_limit < 0.05) time_limit = 0.05;
    return time_limit;
}

static void uci_info_callback(int depth, int score, int nodes, int time_ms, const char *pv_str)
{
    if (depth < 0) {
        printf("%s\n", pv_str);
    } else if (abs(score) >= 30000) {
        int mate_in = (32767 - abs(score) + 1) / 2;
        if (score < 0) mate_in = -mate_in;
        printf("info depth %d score mate %d nodes %d time %d pv %s\n",
               depth, mate_in, nodes, time_ms, pv_str);
    } else {
        printf("info depth %d score cp %d nodes %d time %d pv %s\n",
               depth, score, nodes, time_ms, pv_str);
    }
    fflush(stdout);
}

static void run_search(double time_limit, int max_depth)
{
    set_engine_abort(0);

    char fen[MAX_FEN];
    board_to_fen(&g_board, fen, MAX_FEN);

    double time_left = 0.0;
    double increment = 0.0;
    int moves_to_go = 0;
    int move_number = g_board.fullmove_number;

    if (g_go_params_movetime <= 0) {
        int remaining_ms, inc_ms;
        if (g_board.side_to_move == WHITE) {
            remaining_ms = g_go_params_wtime;
            inc_ms = g_go_params_winc;
        } else {
            remaining_ms = g_go_params_btime;
            inc_ms = g_go_params_binc;
        }
        if (remaining_ms > 0) {
            time_left = remaining_ms / 1000.0;
            increment = inc_ms / 1000.0;
        }
    }

    clock_t start = clock();
    int nodes = 0;
    Move result = find_best_move_c(
        fen, time_limit, time_left, increment, moves_to_go, move_number, max_depth, &nodes,
        g_position_history_count > 0 ? g_position_history : NULL,
        g_position_history_count
    );
    clock_t end = clock();
    int time_ms = (int)((double)(end - start) / CLOCKS_PER_SEC * 1000);

    if (result.from == 0 && result.to == 0) {
        printf("bestmove 0000\n");
        fflush(stdout);
        return;
    }

    int depth = get_last_search_info(0);
    int score = result.score;

    char uci_move[MAX_MOVE_STR];
    move_to_uci(&result, uci_move);

    if (depth > 0) {
        if (abs(score) >= 30000) {
            int mate_in = (32767 - abs(score) + 1) / 2;
            if (score < 0) mate_in = -mate_in;
            printf("info depth %d score mate %d nodes %d time %d pv %s\n",
                   depth, mate_in, nodes, time_ms, uci_move);
        } else {
            printf("info depth %d score cp %d nodes %d time %d pv %s\n",
                   depth, score, nodes, time_ms, uci_move);
        }
    }
    printf("bestmove %s\n", uci_move);
    fflush(stdout);
}

#ifdef _WIN32
static unsigned __stdcall search_thread_func(void *arg)
{
    double *time_limit_ptr = (double *)arg;
    run_search(*time_limit_ptr, g_go_params_depth);
    return 0;
}
#else
static void *search_thread_func(void *arg)
{
    double *time_limit_ptr = (double *)arg;
    run_search(*time_limit_ptr, g_go_params_depth);
    return NULL;
}
#endif

static void cmd_uci(void)
{
    printf("id name Hellcopter\n");
    printf("id author Trafflc\n");
    printf("option name OwnBook type check default true\n");
    printf("option name BookPath type string default \n");
    printf("option name BookRandomness type spin default 20 min 0 max 100\n");
    printf("option name SyzygyPath type string default dist\\syzygy\n");
    printf("uciok\n");
    fflush(stdout);
}

static void cmd_isready(void)
{
    printf("readyok\n");
    fflush(stdout);
}

static void cmd_setoption(const char *args)
{
    const char *p = args;
    while (*p == ' ') p++;
    if (strncmp(p, "name", 4) != 0) return;
    p += 4;
    while (*p == ' ') p++;

    if (strncmp(p, "OwnBook", 7) == 0 && (p[7] == ' ' || p[7] == '\0')) {
        p += 7;
        while (*p == ' ') p++;
        if (strncmp(p, "value", 5) != 0) return;
        p += 5;
        while (*p == ' ') p++;
        g_own_book = (strncmp(p, "true", 4) == 0) ? 1 : 0;
    } else if (strncmp(p, "BookPath", 8) == 0 && (p[8] == ' ' || p[8] == '\0')) {
        p += 8;
        while (*p == ' ') p++;
        if (strncmp(p, "value", 5) != 0) return;
        p += 5;
        while (*p == ' ') p++;
        strncpy(g_book_path, p, MAX_LINE - 1);
        g_book_path[MAX_LINE - 1] = '\0';
        int len = (int)strlen(g_book_path);
        while (len > 0 && (g_book_path[len - 1] == '\n' || g_book_path[len - 1] == '\r'))
            g_book_path[--len] = '\0';
        load_opening_book();
    } else if (strncmp(p, "BookRandomness", 14) == 0 && (p[14] == ' ' || p[14] == '\0')) {
        p += 14;
        while (*p == ' ') p++;
        if (strncmp(p, "value", 5) != 0) return;
        p += 5;
        while (*p == ' ') p++;
        g_book_randomness = atoi(p);
        if (g_book_randomness < 0) g_book_randomness = 0;
        if (g_book_randomness > 100) g_book_randomness = 100;
    } else if (strncmp(p, "SyzygyPath", 10) == 0 && (p[10] == ' ' || p[10] == '\0')) {
        p += 10;
        while (*p == ' ') p++;
        if (strncmp(p, "value", 5) != 0) return;
        p += 5;
        while (*p == ' ') p++;
        fprintf(stderr, "SyzygyPath set to: %s (built-in tablebase rules active)\n", p);
    }
}

static void cmd_ucinewgame(void)
{
    set_engine_abort(1);
    g_position_history_count = 0;
    board_from_fen(&g_board,
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
    tt_clear_global();
    set_engine_abort(0);
}

static void cmd_position(const char *args)
{
    const char *p = args;

    while (*p == ' ') p++;

    if (strncmp(p, "startpos", 8) == 0) {
        board_from_fen(&g_board,
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
        p += 8;
    } else if (strncmp(p, "fen", 3) == 0) {
        p += 3;
        while (*p == ' ') p++;
        char fen_buf[MAX_FEN];
        int fen_parts = 0;
        const char *fen_start = p;
        while (*p && fen_parts < 6) {
            if (*p == ' ') {
                fen_parts++;
                while (*(p + 1) == ' ') p++;
            }
            p++;
        }
        int fen_len = (int)(p - fen_start);
        if (fen_len >= MAX_FEN) fen_len = MAX_FEN - 1;
        memcpy(fen_buf, fen_start, fen_len);
        fen_buf[fen_len] = '\0';

        int need_defaults = 0;
        const char *sp = fen_buf;
        int part = 0;
        while (*sp) { if (*sp == ' ') part++; sp++; }
        if (part < 2) { strcat(fen_buf, " w KQkq - 0 1"); }
        else if (part < 3) { strcat(fen_buf, " KQkq - 0 1"); }
        else if (part < 4) { strcat(fen_buf, " - 0 1"); }
        else if (part < 5) { strcat(fen_buf, " 0 1"); }
        else if (part < 6) { strcat(fen_buf, " 1"); }

        board_from_fen(&g_board, fen_buf);
    } else {
        return;
    }

    g_position_history_count = 0;
    g_position_history[0] = g_board.hash;
    g_position_history_count = 1;

    while (*p == ' ') p++;
    if (strncmp(p, "moves", 5) == 0) {
        p += 5;
        while (*p == ' ') p++;
        while (*p) {
            char move_str[16];
            int i = 0;
            while (*p && *p != ' ' && i < 15) {
                move_str[i++] = *p++;
            }
            move_str[i] = '\0';
            while (*p == ' ') p++;

            if (strlen(move_str) < 4) continue;

            int from = uci_to_sq(move_str);
            int to = uci_to_sq(move_str + 2);
            if (from < 0 || to < 0) continue;

            int promotion = 0;
            if (strlen(move_str) > 4)
                promotion = str_to_promotion(move_str[4]);

            Move legal_moves[MAX_MOVES];
            UndoInfo undo;
            int n = generate_legal_moves(&g_board, legal_moves);
            int found = 0;
            int mi;
            for (mi = 0; mi < n; mi++) {
                if (legal_moves[mi].from == from &&
                    legal_moves[mi].to == to &&
                    legal_moves[mi].promotion == promotion) {
                    make_move(&g_board, &legal_moves[mi], &undo);
                    found = 1;
                    break;
                }
            }

            if (found && g_position_history_count < MAX_POS_HISTORY) {
                g_position_history[g_position_history_count++] = g_board.hash;
            }
        }
    }
}

static void cmd_go(const char *args)
{
    set_engine_abort(1);

    g_go_params_wtime = 0;
    g_go_params_btime = 0;
    g_go_params_winc = 0;
    g_go_params_binc = 0;
    g_go_params_depth = 100;
    g_go_params_movetime = 0;
    g_go_infinite = 0;

    const char *p = args;
    while (*p) {
        while (*p == ' ') p++;
        if (strncmp(p, "wtime", 5) == 0) {
            g_go_params_wtime = atoi(p + 5);
        } else if (strncmp(p, "btime", 5) == 0) {
            g_go_params_btime = atoi(p + 5);
        } else if (strncmp(p, "winc", 4) == 0) {
            g_go_params_winc = atoi(p + 4);
        } else if (strncmp(p, "binc", 4) == 0) {
            g_go_params_binc = atoi(p + 4);
        } else if (strncmp(p, "depth", 5) == 0) {
            g_go_params_depth = atoi(p + 5);
        } else if (strncmp(p, "movetime", 8) == 0) {
            g_go_params_movetime = atoi(p + 8);
        } else if (strncmp(p, "infinite", 8) == 0) {
            g_go_infinite = 1;
        }
        while (*p && *p != ' ') p++;
    }

    char book_move[MAX_MOVE_STR];
    if (find_book_move(&g_board, book_move)) {
        printf("info depth 0 score cp 0 nodes 0 time 0 pv %s\n", book_move);
        printf("bestmove %s\n", book_move);
        fflush(stdout);
        return;
    }

    double time_limit;
    if (g_go_infinite) {
        time_limit = 1e9;
    } else if (g_go_params_wtime == 0 && g_go_params_btime == 0 && g_go_params_movetime == 0) {
        time_limit = 30.0;
    } else {
        time_limit = compute_time(
            g_go_params_wtime, g_go_params_btime,
            g_go_params_winc, g_go_params_binc,
            g_go_params_movetime
        );
    }

    set_engine_abort(0);

    double *tl_ptr = (double *)malloc(sizeof(double));
    *tl_ptr = time_limit;

#ifdef _WIN32
    HANDLE h = (HANDLE)_beginthreadex(NULL, 0, search_thread_func, tl_ptr, 0, NULL);
    if (h) {
        WaitForSingleObject(h, INFINITE);
        CloseHandle(h);
    } else {
        run_search(time_limit, g_go_params_depth);
    }
#else
    pthread_t tid;
    if (pthread_create(&tid, NULL, search_thread_func, tl_ptr) == 0) {
        pthread_join(tid, NULL);
    } else {
        run_search(time_limit, g_go_params_depth);
    }
#endif
    free(tl_ptr);
}

static void cmd_stop(void)
{
    set_engine_abort(1);
}

static void cmd_bench(void)
{
    static const char *bench_fens[] = {
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
        "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
        "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
        "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
        "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
        "8/P7/8/8/8/8/8/4K2k w - - 0 1",
        "n1n5/PPPk4/8/8/8/8/4Kppp/5N1N b - - 0 1",
        "rnbqkbnr/pppp1ppp/8/4pP2/8/8/PPPPP1PP/RNBQKBNR w KQkq e6 0 3",
        "r1bqkb1r/pppppppp/2n2n2/8/3PP3/2N5/PPP2PPP/R1BQKBNR b KQkq d3 0 3",
        "r1bq1rk1/ppp2ppp/2n2n2/3pp3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 6",
    };
    int num_fens = sizeof(bench_fens) / sizeof(bench_fens[0]);
    int bench_depth = 10;
    long long total_nodes = 0;
    clock_t start = clock();

    for (int i = 0; i < num_fens; i++) {
        int nodes = 0;
        find_best_move_c(bench_fens[i], 100000.0, 0, 0, 0, 0, bench_depth, &nodes, NULL, 0);
        total_nodes += nodes;
        fprintf(stdout, "Position %2d/%2d: nodes=%d\n", i + 1, num_fens, nodes);
    }

    double elapsed = (double)(clock() - start) / CLOCKS_PER_SEC;
    long long nps = (long long)(total_nodes / (elapsed > 0.001 ? elapsed : 0.001));
    fprintf(stdout, "Bench: %lld nodes in %.2fs (%lld nps)\n", total_nodes, elapsed, nps);
}

int main(void)
{
#ifdef _WIN32
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stdin, NULL, _IONBF, 0);
#endif

    get_exe_dir();
    load_opening_book();
    set_engine_info_callback(uci_info_callback);

    board_from_fen(&g_board,
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");

    char line[MAX_LINE];

    while (fgets(line, MAX_LINE, stdin)) {
        char *cmd = strip(line);
        if (strlen(cmd) == 0) continue;

        if (strcmp(cmd, "uci") == 0) {
            cmd_uci();
        } else if (strcmp(cmd, "isready") == 0) {
            cmd_isready();
        } else if (strncmp(cmd, "setoption", 9) == 0) {
            cmd_setoption(cmd + 9);
        } else if (strcmp(cmd, "ucinewgame") == 0) {
            cmd_ucinewgame();
        } else if (strncmp(cmd, "position", 8) == 0) {
            cmd_position(cmd + 8);
        } else if (strncmp(cmd, "go", 2) == 0) {
            if (cmd[2] == ' ' || cmd[2] == '\0')
                cmd_go(cmd + 2);
        } else if (strcmp(cmd, "stop") == 0) {
            cmd_stop();
        } else if (strcmp(cmd, "bench") == 0) {
            cmd_bench();
        } else if (strcmp(cmd, "quit") == 0) {
            set_engine_abort(1);
            break;
        }
    }

    return 0;
}
