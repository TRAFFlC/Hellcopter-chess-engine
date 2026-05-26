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

static int find_book_move(const Board *b, char *out_move)
{
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

    int best_weight = 0;
    int best_move = -1;
    int idx = found_idx;
    while (idx < g_book_count && g_book_entries[idx].key == target) {
        if (g_book_entries[idx].weight > best_weight) {
            best_weight = g_book_entries[idx].weight;
            best_move = g_book_entries[idx].move;
        }
        idx++;
    }

    if (best_move < 0) return 0;

    int from, to, promo;
    polyglot_decode_move((U16)best_move, &from, &to, &promo);

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
    char path[MAX_LINE];

    sprintf(path, "%s\\book.bin", g_exe_dir);
    int count = load_polyglot_book(path);
    if (count <= 0) {
        sprintf(path, "%s/book.bin", g_exe_dir);
        count = load_polyglot_book(path);
    }
    if (count > 0) {
        fprintf(stderr, "Loaded opening book: %d positions\n", count);
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
    printf("uciok\n");
    fflush(stdout);
}

static void cmd_isready(void)
{
    printf("readyok\n");
    fflush(stdout);
}

static void cmd_ucinewgame(void)
{
    set_engine_abort(1);
    g_position_history_count = 0;
    board_from_fen(&g_board,
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
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
        } else if (strcmp(cmd, "ucinewgame") == 0) {
            cmd_ucinewgame();
        } else if (strncmp(cmd, "position", 8) == 0) {
            cmd_position(cmd + 8);
        } else if (strncmp(cmd, "go", 2) == 0) {
            if (cmd[2] == ' ' || cmd[2] == '\0')
                cmd_go(cmd + 2);
        } else if (strcmp(cmd, "stop") == 0) {
            cmd_stop();
        } else if (strcmp(cmd, "quit") == 0) {
            set_engine_abort(1);
            break;
        }
    }

    return 0;
}
