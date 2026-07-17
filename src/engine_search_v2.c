/* engine_search.c — 搜索核心：TT、SEE、走法排序、quiescence、negamax（从 engine_core.c 拆分） */
/* v2: 重复检测优化 + TT 命中率统计 (Task #109) */

/* Syzygy tablebase largest cardinality (exported from tbprobe.c via engine_debug.c) */
extern unsigned TB_LARGEST;

/* === TT 命中率统计 (诊断用) === */
long long g_tt_probe_count = 0;
long long g_tt_hit_count = 0;      /* TT 命中且深度足够, 直接返回 */
long long g_tt_move_only_count = 0; /* TT 命中但深度不够, 只用 TT move */
long long g_tt_flag_fail_count = 0; /* TT 命中且深度够但 flag 不满足条件 */
long long g_tt_miss_count = 0;     /* TT 未命中 */
long long g_tt_store_count = 0;    /* TT store 次数 */

/* === SEE 剪枝诊断计数器 === */
long long g_see_capture_total = 0;     /* move loop 中遇到的吃子着法总数 */
long long g_see_eligible = 0;          /* 满足 SEE 剪枝前 6 个条件的吃子着法 */
long long g_see_zero_window = 0;       /* 其中满足零窗口的 */
long long g_see_threshold_met = 0;     /* 其中 SEE 值 < -depth*scale 的 */
long long g_see_bad_capture_count = 0; /* bad capture (SEE<0) 总数 */
long long g_see_bad_capture_sum = 0;   /* bad capture SEE 值总和（用于算平均） */
long long g_see_bad_capture_min = 0;   /* bad capture SEE 最小值（最负） */
/* move scoring 阶段的 see() 诊断 */
long long g_see_scoring_bad_count = 0;  /* see() 返回 < 0 的次数 */
long long g_see_scoring_bad_sum = 0;    /* see() < 0 时返回值总和 */
long long g_see_scoring_bad_min = 0;    /* see() < 0 时最小值 */
/* NMP 诊断 */
long long g_nmp_null_fail = 0;          /* null_score < beta (NMP 搜索未产生 cutoff) */
long long g_nmp_verify_fail = 0;        /* null_score >= beta 但验证搜索失败 */
long long g_nmp_verify_depth = 0;       /* 进入验证搜索的次数 */
void print_tt_stats(void)
{
    if (g_tt_probe_count > 0)
    {
        double hit_rate = 100.0 * g_tt_hit_count / g_tt_probe_count;
        double move_rate = 100.0 * g_tt_move_only_count / g_tt_probe_count;
        double flag_rate = 100.0 * g_tt_flag_fail_count / g_tt_probe_count;
        double miss_rate = 100.0 * g_tt_miss_count / g_tt_probe_count;
        fprintf(stderr, "TT Stats: probes=%lld, stores=%lld, hits=%lld (%.1f%%), move_only=%lld (%.1f%%), flag_fail=%lld (%.1f%%), miss=%lld (%.1f%%)\n",
                g_tt_probe_count, g_tt_store_count,
                g_tt_hit_count, hit_rate,
                g_tt_move_only_count, move_rate,
                g_tt_flag_fail_count, flag_rate,
                g_tt_miss_count, miss_rate);
    }
    fprintf(stderr, "SEE Prune Diag: captures=%lld, eligible=%lld, zero_window=%lld, threshold_met=%lld\n",
            g_see_capture_total, g_see_eligible, g_see_zero_window, g_see_threshold_met);
    fprintf(stderr, "SEE Bad Captures (in zero-window): count=%lld, avg_see=%.1f, min_see=%lld\n",
            g_see_bad_capture_count,
            g_see_bad_capture_count > 0 ? (double)g_see_bad_capture_sum / g_see_bad_capture_count : 0.0,
            g_see_bad_capture_min);
    fprintf(stderr, "SEE Scoring: bad_count=%lld, avg=%.1f, min=%lld\n",
            g_see_scoring_bad_count,
            g_see_scoring_bad_count > 0 ? (double)g_see_scoring_bad_sum / g_see_scoring_bad_count : 0.0,
            g_see_scoring_bad_min);
    fprintf(stderr, "NMP Diag: triggered=%lld, null_fail=%lld, verify_depth=%lld, verify_fail=%lld, cutoffs=%lld\n",
            g_nmp_null_fail + g_nmp_verify_depth + (g_prof_nmp_cutoffs - g_nmp_verify_fail),
            g_nmp_null_fail, g_nmp_verify_depth, g_nmp_verify_fail, g_prof_nmp_cutoffs);
}
void reset_tt_stats(void)
{
    g_tt_probe_count = 0;
    g_tt_hit_count = 0;
    g_tt_move_only_count = 0;
    g_tt_flag_fail_count = 0;
    g_tt_miss_count = 0;
    g_tt_store_count = 0;
    g_see_capture_total = 0;
    g_see_eligible = 0;
    g_see_zero_window = 0;
    g_see_threshold_met = 0;
    g_see_bad_capture_count = 0;
    g_see_bad_capture_sum = 0;
    g_see_bad_capture_min = 0;
    g_see_scoring_bad_count = 0;
    g_see_scoring_bad_sum = 0;
    g_see_scoring_bad_min = 0;
    g_nmp_null_fail = 0;
    g_nmp_verify_fail = 0;
    g_nmp_verify_depth = 0;
}

/* === 重复检测哈希表 (Task #109) ===
 * 原实现: engine_search.c L898-916 对 game_history[512] + search_history[256] 线性扫描
 * 新实现: game_history 用哈希表 O(1) 查询 (懒初始化), search_history 仍线性扫描 (栈式, <30 元素)
 * 性能: 从 ~768 比较/节点 降至 ~30 比较 + 1 哈希查询/节点
 */
#define REP_HASH_BITS 10
#define REP_HASH_SIZE (1 << REP_HASH_BITS)
#define REP_HASH_MASK (REP_HASH_SIZE - 1)
#define REP_HASH_MAX_THREADS 64

typedef struct {
    U64 keys[REP_HASH_SIZE];
    int8_t counts[REP_HASH_SIZE];
    int used;  /* 已使用的槽数 (用于诊断) */
} RepHash;

/* 每线程缓存: 懒初始化, 用 SearchState 指针 + count + 首尾元素校验 */
static struct {
    SearchState *s;
    int game_history_count;
    U64 first_key;   /* game_history[0] 或 0 */
    U64 last_key;    /* game_history[count-1] 或 0 */
    RepHash hash;
    int initialized; /* 是否已初始化过 */
} g_rep_cache[REP_HASH_MAX_THREADS];

/* Thread-local evaluation thread id.  evaluate() is called deep inside the
 * search recursion where SearchState is not always available, so we keep the
 * current thread id in TLS.  This is used by the pawn hash table to restrict
 * writes to the main worker and avoid SMP cache pollution.
 *
 * On Windows we use the native TlsAlloc/TlsGetValue/TlsSetValue API because
 * GCC's __declspec(thread) is ignored and its emulated __thread TLS can hang
 * when accessed from threads created directly via CreateThread. */
#ifdef _WIN32
static DWORD g_eval_tls_index = TLS_OUT_OF_INDEXES;

static void ensure_eval_tls(void)
{
    if (g_eval_tls_index == TLS_OUT_OF_INDEXES)
    {
        DWORD idx = TlsAlloc();
        if (idx == TLS_OUT_OF_INDEXES)
            return;
#ifdef _WIN32
        if (InterlockedCompareExchange((LONG *)&g_eval_tls_index, (LONG)idx, (LONG)TLS_OUT_OF_INDEXES) != (LONG)TLS_OUT_OF_INDEXES)
            TlsFree(idx);
#endif
    }
}

int get_eval_thread_id(void)
{
    ensure_eval_tls();
    return (int)(intptr_t)TlsGetValue(g_eval_tls_index);
}

void set_eval_thread_id(int tid)
{
    ensure_eval_tls();
    TlsSetValue(g_eval_tls_index, (void *)(intptr_t)tid);
}
#else
static __thread int g_eval_thread_id = 0;

int get_eval_thread_id(void)
{
    return g_eval_thread_id;
}

void set_eval_thread_id(int tid)
{
    g_eval_thread_id = tid;
}
#endif

/* FNV-like hash for 64-bit key to 10-bit index */
static inline int rep_hash_idx(U64 key)
{
    /* 使用 key 的高位 (Zobrist hash 高位分布更均匀) */
    return (int)((key >> 54) ^ (key >> 44)) & REP_HASH_MASK;
}

/* 插入/递增 (开放寻址, 有限探测) */
static void rep_hash_insert(RepHash *t, U64 key)
{
    int idx = rep_hash_idx(key);
    int probes = 0;
    while (probes++ < REP_HASH_SIZE)
    {
        if (t->keys[idx] == 0)
        {
            t->keys[idx] = key;
            t->counts[idx] = 1;
            t->used++;
            return;
        }
        if (t->keys[idx] == key)
        {
            if (t->counts[idx] < 127)
                t->counts[idx]++;
            return;
        }
        idx = (idx + 1) & REP_HASH_MASK;
    }
    /* Table full — silently drop this entry (extremely rare) */
}

/* 查询计数 (开放寻址, 有限探测) */
static int rep_hash_count(const RepHash *t, U64 key)
{
    int idx = rep_hash_idx(key);
    int probes = 0;
    while (probes++ < REP_HASH_SIZE)
    {
        if (t->keys[idx] == 0)
            return 0;
        if (t->keys[idx] == key)
            return t->counts[idx];
        idx = (idx + 1) & REP_HASH_MASK;
    }
    return 0; /* Table full, key not found */
}

/* 懒初始化 + 查询 game_history 重复次数
 * 校验: SearchState 指针 + game_history_count + 首尾 key
 * 若校验失败则重建哈希表 (O(game_history_count), 仅在搜索首次调用时发生)
 */
static int game_rep_count_cached(SearchState *s, U64 key)
{
    int tid = s->thread_id;
    if (tid < 0 || tid >= REP_HASH_MAX_THREADS)
        tid = 0;

    int ghc = s->game_history_count;
    U64 fk = (ghc > 0) ? s->game_history[0] : 0;
    U64 lk = (ghc > 0) ? s->game_history[ghc - 1] : 0;

    /* 校验缓存是否有效 */
    if (g_rep_cache[tid].s != s ||
        g_rep_cache[tid].game_history_count != ghc ||
        g_rep_cache[tid].first_key != fk ||
        g_rep_cache[tid].last_key != lk)
    {
        /* 重建哈希表 */
        memset(&g_rep_cache[tid].hash, 0, sizeof(RepHash));
        for (int i = 0; i < ghc; i++)
        {
            rep_hash_insert(&g_rep_cache[tid].hash, s->game_history[i]);
        }
        g_rep_cache[tid].s = s;
        g_rep_cache[tid].game_history_count = ghc;
        g_rep_cache[tid].first_key = fk;
        g_rep_cache[tid].last_key = lk;
        g_rep_cache[tid].initialized = 1;
    }

    int hash_reps = rep_hash_count(&g_rep_cache[tid].hash, key);
    /* 1024 槽哈希表的碰撞概率非零。当哈希表报告 >= 2 时回退到线性
     * 扫描验证，防止伪阳性导致错误的和棋判定。 */
    if (hash_reps >= 2)
    {
        int linear_reps = 0;
        for (int i = 0; i < ghc; i++)
        {
            if (s->game_history[i] == key)
            {
                if (++linear_reps >= 2)
                    break;
            }
        }
        return linear_reps;
    }
    return hash_reps;
}

static int mvv_lva(const Board *b, const Move *m)
{
    /* MVV-LVA: Most Valuable Victim - Least Valuable Attacker */
    int from_piece = piece_on_square(b, m->from);
    return get_piece_value(m->capture) * MVV_LVA_SCALE - get_piece_value(from_piece);
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

static int next_power_of_2(int v)
{
    v--;
    v |= v >> 1;
    v |= v >> 2;
    v |= v >> 4;
    v |= v >> 8;
    v |= v >> 16;
    v++;
    return v;
}

static void pick_next_move(Move *moves, int count, int current_idx)
{
    int best_idx = current_idx;
    int best_score = moves[current_idx].score;
    int i;
    for (i = current_idx + 1; i < count; i++)
    {
        if (moves[i].score > best_score)
        {
            best_score = moves[i].score;
            best_idx = i;
        }
    }
    if (best_idx != current_idx)
    {
        Move tmp = moves[current_idx];
        moves[current_idx] = moves[best_idx];
        moves[best_idx] = tmp;
    }
}

static void tt_init_global(int hash_mb);

static void tt_init(SearchState *s, int hash_mb)
{
    int raw_count = hash_mb * 1024 * 1024 / (int)sizeof(TT_Cluster);
    s->tt_cluster_count = next_power_of_2(raw_count);
    if (s->tt_cluster_count < 16)
        s->tt_cluster_count = 16;
    s->tt = (TT_Cluster *)calloc(s->tt_cluster_count, sizeof(TT_Cluster));
    s->tt_generation = 1;
}

static TT_Cluster *g_tt = NULL;
static int g_tt_cluster_count = 0;
static int g_tt_generation = 1;
static int g_tt_hash_mb = 128;

/* Capture History: tracks success of captures indexed by [attacker_type][to_sq][captured_type] */
int16_t g_capture_history[7][64][7];

/* Continuation History: tracks move success after specific previous moves [prev_piece][prev_to][curr_piece][curr_to] */
int16_t g_cont_history[7][64][7][64];

/* Atomic, clamped update for the globally-shared history tables in SMP mode.
 * Uses a compare-and-swap loop so concurrent updates from multiple workers do
 * not silently overwrite each other.  The value is clamped to
 * +/- HISTORY_SCORE_LIMIT before being stored. */
static void history_atomic_add(int16_t *ptr, int delta)
{
    int16_t old_val, new_val;
    do
    {
        old_val = *ptr;
        new_val = old_val + (int16_t)delta;
        if (new_val > HISTORY_SCORE_LIMIT)
            new_val = HISTORY_SCORE_LIMIT;
        if (new_val < -HISTORY_SCORE_LIMIT)
            new_val = -HISTORY_SCORE_LIMIT;
#ifdef _MSC_VER
    } while (_InterlockedCompareExchange16((volatile short *)ptr, (short)new_val, (short)old_val) != (short)old_val);
#else
    } while (!__atomic_compare_exchange_n(ptr, &old_val, new_val,
                                          0, __ATOMIC_RELAXED, __ATOMIC_RELAXED));
#endif
}

static void tt_init_global(int hash_mb)
{
    if (g_tt && g_tt_hash_mb == hash_mb)
        return;
    if (g_tt)
    {
        free(g_tt);
        g_tt = NULL;
    }
    g_tt_hash_mb = hash_mb;
    int raw_count = hash_mb * 1024 * 1024 / (int)sizeof(TT_Cluster);
    g_tt_cluster_count = next_power_of_2(raw_count);
    if (g_tt_cluster_count < 16)
        g_tt_cluster_count = 16;
    g_tt = (TT_Cluster *)calloc(g_tt_cluster_count, sizeof(TT_Cluster));
    g_tt_generation = 1;
}

void tt_clear_global(void)
{
    if (g_tt && g_tt_cluster_count > 0)
    {
        memset(g_tt, 0, (size_t)g_tt_cluster_count * sizeof(TT_Cluster));
    }
    g_tt_generation = 1;
}

void tt_resize_global(int hash_mb)
{
    if (hash_mb < 1)
        hash_mb = 1;
    if (hash_mb > 65536)
        hash_mb = 65536;
    if (g_tt)
    {
        free(g_tt);
        g_tt = NULL;
    }
    g_tt_hash_mb = hash_mb;
    int raw_count = hash_mb * 1024 * 1024 / (int)sizeof(TT_Cluster);
    g_tt_cluster_count = next_power_of_2(raw_count);
    if (g_tt_cluster_count < 16)
        g_tt_cluster_count = 16;
    g_tt = (TT_Cluster *)calloc(g_tt_cluster_count, sizeof(TT_Cluster));
    g_tt_generation = 1;
}

static int tt_probe(SearchState *s, U64 key, int depth, int alpha, int beta, Move *out_move, int ply, int *out_tt_score, int *out_tt_flag)
{
    /* Singular Extension: skip TT when we have an excluded move at this ply,
     * because the TT entry may depend on the excluded move being the best. */
    if (out_tt_flag)
        *out_tt_flag = -1;
    if (ply < 128 && (s->se_excluded[ply].from != 0 || s->se_excluded[ply].to != 0))
        return INF + 1;

    g_tt_probe_count++;

    int idx = (int)(key & (U64)(s->tt_cluster_count - 1));
    TT_Cluster *cluster = &s->tt[idx];
    int i;
    int found_key = 0;
    for (i = 0; i < 4; i++)
    {
        TT_Entry *e = &cluster->entries[i];
        if (e->key == key)
        {
            found_key = 1;
            *out_move = e->best_move;
            if (e->depth >= depth)
            {
                int score = e->score;
                if (score > MATE_SCORE - 100)
                    score += depth;
                else if (score < -MATE_SCORE + 100)
                    score -= depth;
                if (out_tt_score)
                    *out_tt_score = score;
                if (out_tt_flag)
                    *out_tt_flag = e->flag;
                if (e->flag == 0)
                {
                    s->tt_hits++;
                    g_prof_tt_hits++;
                    g_tt_hit_count++;
                    return score;
                }
                if (e->flag == 1 && score <= alpha)
                {
                    s->tt_hits++;
                    g_tt_hit_count++;
                    return score;
                }
                if (e->flag == 2 && score >= beta)
                {
                    s->tt_hits++;
                    g_tt_hit_count++;
                    return score;
                }
                /* depth 够但 flag 不满足条件 */
                g_tt_flag_fail_count++;
            }
            else
            {
                if (out_tt_score)
                {
                    int score = e->score;
                    if (score > MATE_SCORE - 100)
                        score += depth;
                    else if (score < -MATE_SCORE + 100)
                        score -= depth;
                    *out_tt_score = score;
                }
                if (out_tt_flag)
                    *out_tt_flag = e->flag;
                g_tt_move_only_count++;
            }
            s->tt_misses++;
            return INF + 1;
        }
    }
    for (i = 0; i < 4; i++)
    {
        TT_Entry *e = &cluster->entries[i];
        if (e->key == key && e->depth > 0)
        {
            *out_move = e->best_move;
            break;
        }
    }
    if (!found_key)
    {
        s->tt_misses++;
        g_tt_miss_count++;
    }
    return INF + 1;
}

static void tt_store(SearchState *s, U64 key, int depth, int score, int flag, Move best_move, int ply)
{
    g_prof_tt_stores++;
    g_tt_store_count++;
    /* All SMP workers now write into the shared TT, so that the global
     * tt_generation counter (incremented by all workers each iteration)
     * stays consistent with the entries stored.  Lazy SMP tolerates the
     * occasional data race — the benefit of shared knowledge outweighs it. */
    /* Singular Extension: don't store TT when we have an excluded move at this ply,
     * to avoid polluting TT with results from an incomplete search. */
    if (ply < 128 && (s->se_excluded[ply].from != 0 || s->se_excluded[ply].to != 0))
        return;

    int idx = (int)(key & (U64)(s->tt_cluster_count - 1));
    TT_Cluster *cluster = &s->tt[idx];
    int i;
    /* Check for existing entry with same key */
    for (i = 0; i < 4; i++)
    {
        TT_Entry *e = &cluster->entries[i];
        if (e->key == key)
        {
            if (depth >= e->depth)
            {
                int adj_score = score;
                if (adj_score > MATE_SCORE - 100)
                    adj_score -= depth;
                else if (adj_score < -MATE_SCORE + 100)
                    adj_score += depth;
                e->key = key;
                e->depth = (int16_t)depth;
                e->score = adj_score;
                e->flag = (int16_t)flag;
                e->best_move = best_move;
                e->generation = (uint16_t)(s->tt_generation);
            }
            else
            {
                /* Depth insufficient to overwrite, but refresh generation
                 * so the entry is not evicted as stale by a shallower
                 * replacement candidate in a future iteration. */
                assert(e->best_move.from < 64 && e->best_move.to < 64
                       && "Stored TT best_move has invalid square range");
                e->generation = (uint16_t)(s->tt_generation);
            }
            return;
        }
    }
    /* Depth-preferred replacement for different keys. Within a cluster we
     * prefer to overwrite:
     *   1. an empty slot (key == 0), or
     *   2. the entry with the smallest stored depth, and
     *   3. if depths are tied, the oldest generation.
     * This raises TT hit rate because shallow entries are cheaper to recompute
     * than deep ones, and matches the modern depth-preferred strategy used by
     * strong engines. The same-key path above already protects deep entries
     * from being overwritten by shallower ones. */
    int replace_idx = 0;
    int worst_score = 0x7FFFFFFF;
    for (i = 0; i < 4; i++)
    {
        TT_Entry *e = &cluster->entries[i];
        int score;
        if (e->key == 0)
        {
            score = -0x7FFFFFFF - 1; /* empty slot is the best victim */
        }
        else
        {
            int gen_diff = (uint16_t)(s->tt_generation - e->generation);
            score = (int)e->depth * 256 - gen_diff;
        }
        if (score < worst_score)
        {
            worst_score = score;
            replace_idx = i;
        }
    }
    /* Track TT contention: if we're replacing an entry from current generation,
     * it means multiple threads are competing for the same cluster slot. */
    {
        TT_Entry *victim = &cluster->entries[replace_idx];
        if ((int)victim->generation == (int)(s->tt_generation & 0xFFFF) && victim->key != 0)
            s->tt_contention_count++;
    }
    {
        TT_Entry *e = &cluster->entries[replace_idx];
        int adj_score = score;
        if (adj_score > MATE_SCORE - 100)
            adj_score -= depth;
        else if (adj_score < -MATE_SCORE + 100)
            adj_score += depth;
        e->key = key;
        e->depth = (int16_t)depth;
        e->score = adj_score;
        e->flag = (int16_t)flag;
        e->best_move = best_move;
        e->generation = (uint16_t)(s->tt_generation);
    }
}

static int see_piece_value(int piece)
{
    switch (piece)
    {
    case PAWN:
        return get_piece_value(PAWN);
    case KNIGHT:
        return get_piece_value(KNIGHT);
    case BISHOP:
        return get_piece_value(BISHOP);
    case ROOK:
        return get_piece_value(ROOK);
    case QUEEN:
        return get_piece_value(QUEEN);
    case KING:
        return SEE_KING_VALUE;
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

    /* For en passant captures, remove the captured pawn from occupied.
     * The captured pawn is on a different square than the target square:
     * for white capturing en passant, the captured pawn is at to-8;
     * for black, at to+8. */
    if (b->en_passant == to && piece_on_square(b, to) == 0)
    {
        if (b->side_to_move == WHITE)
            occupied &= ~(1ULL << (to - 8));
        else
            occupied &= ~(1ULL << (to + 8));
    }

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

        /* Remove the attacker from its original square (X-ray effect).
         * Do NOT update current_sq — all subsequent captures happen at the
         * original target square 'to'. The piece moves to 'to' conceptually
         * but occupied already has a piece at 'to', so we only need to clear
         * the attacker's origin to reveal sliding attackers behind it. */
        occupied &= ~(1ULL << next_attacker_sq);

        gain[gain_count++] = next_value;

        if (next_piece == KING)
        {
            /* Check if the target square is attacked by any opponent piece.
             * If so, the king cannot safely capture — abort the exchange
             * and discard the king's gain. */
            U64 opp_bq = b->pieces[1 - stm][BISHOP] | b->pieces[1 - stm][QUEEN];
            U64 opp_rq = b->pieces[1 - stm][ROOK] | b->pieces[1 - stm][QUEEN];
            U64 opp_n = b->pieces[1 - stm][KNIGHT];
            U64 opp_p = b->pieces[1 - stm][PAWN];
            int stm_king_sq = current_sq;

            if ((sliding_attacks_bishop(stm_king_sq, occupied) & opp_bq) ||
                (sliding_attacks_rook(stm_king_sq, occupied) & opp_rq) ||
                (knight_attacks[stm_king_sq] & opp_n) ||
                /* Pawn attacks on stm_king_sq: opponent pawns on the two
                 * diagonally-adjacent squares that attack the target. */
                ((((1 - stm) == WHITE)
                  ? (((1ULL << stm_king_sq) >> 7) & ~0x0101010101010101ULL)
                    | (((1ULL << stm_king_sq) >> 9) & ~0x8080808080808080ULL)
                  : (((1ULL << stm_king_sq) << 7) & ~0x8080808080808080ULL)
                    | (((1ULL << stm_king_sq) << 9) & ~0x0101010101010101ULL)) & opp_p))
            {
                gain_count--;
                break;
            }

            /* 国王安全吃子，对手无法回吃国王。
             * 直接返回净收益。
             * 注意: 与标准路径一致，gain[0] 不截断 —
             * 吃子方已经走了，无法撤回。 */
            int g = gain_count - 1;
            while (g > 0)
            {
                gain[g - 1] = gain[g - 1] - gain[g];
                if (g > 1 && gain[g - 1] < 0)
                    gain[g - 1] = 0;
                g--;
            }
            return gain[0];
        }

        /* current_sq stays as 'to' — all captures happen at the target square */
        stm = 1 - stm;
        piece = next_piece;

        if (gain_count >= 30)
            break;
    }

    /* SEE 反向计算: 从交换序列末尾向前推导每方的最优净收益。
     * 关键: 只有"可以选择不参与"的一方才截断负数为 0 (stand pat)。
     * 吃子方(第一步)已经走了, 无法撤回, 所以 gain[0] 不截断 —
     * 这样 see() 能正确返回负数, 使 SEE 剪枝可以工作。
     * 修复前: 所有 gain[i] 都截断, see() 永远 >= 0, SEE 剪枝从未触发。 */
    while (gain_count > 1)
    {
        gain_count--;
        gain[gain_count - 1] = gain[gain_count - 1] - gain[gain_count];
        if (gain_count > 1 && gain[gain_count - 1] < 0)
            gain[gain_count - 1] = 0;
    }

    return gain[0];
}

int quiescence_search(SearchState *s, int alpha, int beta, int ply, int qs_depth)
{
    assert(alpha < beta && "Alpha must be less than beta in quiescence_search");

    set_eval_thread_id(s->thread_id);

    if (s->aborted)
        return 0;
    g_prof_qs_calls++;
    g_prof_qs_nodes++;
    s->nodes++;
    if ((s->nodes & s->time_check_mask) == 0)
    {
        double elapsed = get_time() - s->start_time;
        if (elapsed >= s->time_limit || g_engine_abort_flag ||
            (s->node_limit > 0 && s->nodes >= s->node_limit))
        {
            s->aborted = 1;
            return 0;
        }
    }

    int is_endgame_qs = 0;
    {
        int npm = s->board.npm[0] + s->board.npm[1];
        if (npm <= g_runtime_params.endgame_phase_threshold)
            is_endgame_qs = 1;
    }
    int qs_max_depth = is_endgame_qs ? g_runtime_params.qs_max_depth_eg : g_runtime_params.qs_max_depth_mg;
    if (qs_depth >= qs_max_depth)
    {
        int in_check_at_limit = is_check(&s->board, s->board.side_to_move);
        if (in_check_at_limit)
        {
            Move moves[MAX_MOVES];
            int n = generate_legal_moves(&s->board, moves);
            if (n == 0)
            {
                return -MATE_SCORE + ply;
            }
        }

        int eval = evaluate(&s->board);
        if (s->board.side_to_move == BLACK)
            eval = -eval;
        return eval;
    }

    int in_check = is_check(&s->board, s->board.side_to_move);
    int next_ply = ply + 1;
    int initial_alpha_qs = alpha; /* Save initial alpha for correct TT flag */

    /* TT probe in quiescence search */
    U64 pos_key = s->board.hash;
    Move tt_move = {0};
    int tt_score_raw = 0;
    int tt_hit = tt_probe(s, pos_key, 0, alpha, beta, &tt_move, ply, &tt_score_raw, NULL);
    if (tt_hit <= INF)
    {
        return tt_hit;
    }

    /* Syzygy TB probe in quiescence search (Task 4.1a).
     * Only at QS entry (qs_depth == 0) to avoid repeated probes in recursive QS.
     * Provides exact WDL scores for endgame positions, replacing heuristic eval. */
    if (TB_LARGEST > 0 && qs_depth == 0)
    {
        U64 qs_all_white = s->board.pieces[WHITE][PAWN] | s->board.pieces[WHITE][KNIGHT] |
                           s->board.pieces[WHITE][BISHOP] | s->board.pieces[WHITE][ROOK] |
                           s->board.pieces[WHITE][QUEEN] | s->board.pieces[WHITE][KING];
        U64 qs_all_black = s->board.pieces[BLACK][PAWN] | s->board.pieces[BLACK][KNIGHT] |
                           s->board.pieces[BLACK][BISHOP] | s->board.pieces[BLACK][ROOK] |
                           s->board.pieces[BLACK][QUEEN] | s->board.pieces[BLACK][KING];
        int qs_total = count_bits(qs_all_white) + count_bits(qs_all_black);
        int qs_w_bishops = count_bits(s->board.pieces[WHITE][BISHOP]);
        int qs_b_bishops = count_bits(s->board.pieces[BLACK][BISHOP]);
        int qs_w_knights = count_bits(s->board.pieces[WHITE][KNIGHT]);
        int qs_b_knights = count_bits(s->board.pieces[BLACK][KNIGHT]);
        int qs_total_pawns = count_bits(s->board.pieces[WHITE][PAWN] | s->board.pieces[BLACK][PAWN]);
        int qs_is_kbnk = (qs_w_bishops + qs_b_bishops == 1 && qs_w_knights + qs_b_knights == 1 && qs_total_pawns == 0);
        if (qs_total <= (int)TB_LARGEST && qs_total >= 3 && s->board.castling_rights == 0 && !qs_is_kbnk)
        {
            unsigned qs_ep = 0;
            if (s->board.en_passant >= 0 && s->board.en_passant < 64)
                qs_ep = (unsigned)s->board.en_passant + 1;
            unsigned qs_wdl = tb_probe_wdl(
                qs_all_white, qs_all_black,
                s->board.pieces[WHITE][KING] | s->board.pieces[BLACK][KING],
                s->board.pieces[WHITE][QUEEN] | s->board.pieces[BLACK][QUEEN],
                s->board.pieces[WHITE][ROOK] | s->board.pieces[BLACK][ROOK],
                s->board.pieces[WHITE][BISHOP] | s->board.pieces[BLACK][BISHOP],
                s->board.pieces[WHITE][KNIGHT] | s->board.pieces[BLACK][KNIGHT],
                s->board.pieces[WHITE][PAWN] | s->board.pieces[BLACK][PAWN],
                0, 0, qs_ep,
                s->board.side_to_move == WHITE);
            if (qs_wdl != TB_RESULT_FAILED)
            {
                int qs_tb_score;
                if (qs_wdl == TB_WIN)
                    qs_tb_score = MATE_SCORE - 200 - ply;
                else if (qs_wdl == TB_CURSED_WIN)
                    qs_tb_score = MATE_SCORE - 2000 - ply;
                else if (qs_wdl == TB_DRAW)
                    qs_tb_score = 0;
                else if (qs_wdl == TB_BLESSED_LOSS)
                    qs_tb_score = -(MATE_SCORE - 2000) + ply;
                else
                    qs_tb_score = -(MATE_SCORE - 200) + ply;
                s->tb_hits++;
                /* TB result is exact — store in TT with EXACT flag and return */
                {
                    Move zero_move = {0};
                    tt_store(s, pos_key, 0, qs_tb_score, 0, zero_move, ply);
                }
                return qs_tb_score;
            }
        }
    }

    int stand_pat_val = 0;
    if (!in_check)
    {
        int stand_pat = evaluate(&s->board);
        if (s->board.side_to_move == BLACK)
            stand_pat = -stand_pat;
        if (stand_pat >= beta)
            return beta;
        if (alpha < stand_pat)
            alpha = stand_pat;
        /* Queen_VALUE check first: if even the most valuable capture (queen)
         * cannot lift the score to alpha, no capture matters.  This is the
         * conservative safety net and must execute before the more aggressive
         * delta pruning, so that positions where a queen capture is still
         * relevant are not incorrectly pruned.  Uses get_piece_value() so
         * runtime-loaded piece values are respected. */
        if (stand_pat + get_piece_value(QUEEN) + get_piece_value(QUEEN) - get_piece_value(PAWN) < alpha)
            return alpha;
        {
            int delta_margin = get_piece_value(QUEEN);
            int my_npm = s->board.npm[s->board.side_to_move];
            int opp_npm = s->board.npm[s->board.side_to_move ^ 1];
            if (my_npm < opp_npm - 100)
                delta_margin = delta_margin * 3 / 2;
            if (stand_pat + delta_margin < alpha)
                return alpha;
        }
        if (ply >= 60)
            return alpha;
        stand_pat_val = stand_pat;
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
        /* 在浅层 QS 中加入安静将军着法，提升战术视野 */
        if (qs_depth < QS_CHECK_MAX_DEPTH)
        {
            n = generate_checking_moves(&s->board, moves, n);
        }
    }
    int i;
    for (i = 0; i < n; i++)
    {
        moves[i].score = mvv_lva(&s->board, &moves[i]);
        /* 安静将军着法给固定分数，低于吃子但高于普通安静走法 */
        if (!moves[i].capture && !moves[i].promotion && moves[i].score == 0)
            moves[i].score = QS_CHECK_SCORE;
        /* Give TT move the highest priority for better move ordering */
        if (tt_move.from != 0 && moves[i].from == tt_move.from && moves[i].to == tt_move.to && moves[i].promotion == tt_move.promotion)
        {
            moves[i].score = QS_TT_MOVE_SCORE;
        }
    }

    int legal_count = 0;
    Move best_qs_move = {0};
    for (i = 0; i < n; i++)
    {
        pick_next_move(moves, n, i);
        if (!in_check && moves[i].capture && !moves[i].promotion)
        {
            /* SEE 只读 Board 不修改，直接传指针避免 436 字节拷贝 */
            int see_score = see(&s->board, moves[i].from, moves[i].to);
            if (see_score < 0)
                continue;
        }

        if (!in_check && moves[i].capture)
        {
            int captured_value = get_piece_value(moves[i].capture);
            if (moves[i].promotion)
                captured_value += get_piece_value(moves[i].promotion) - get_piece_value(PAWN);
            if (stand_pat_val + captured_value + QS_DELTA_MARGIN < alpha)
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
                best_qs_move = moves[i];
                if (alpha >= beta)
                {
                    unmake_move(&s->board, &moves[i], &undo);
                    tt_store(s, pos_key, 0, beta, 2, best_qs_move, ply);
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

    /* Store QS result in TT.
     * Flag: EXACT (0) if alpha was raised above initial alpha,
     * UPPERBOUND (1) if no move/capture improved on the initial alpha. */
    {
        int flag = (alpha > initial_alpha_qs) ? 0 : 1;
        tt_store(s, pos_key, 0, alpha, flag, best_qs_move, ply);
    }

    return alpha;
}

int negamax(SearchState *s, int depth, int alpha, int beta, int ext_count, int ply)
{
    assert(alpha < beta && "Alpha must be less than beta in negamax");

    set_eval_thread_id(s->thread_id);

    if (ply == 0)
    {
        verify_incremental_eval(&s->board);
        /* Verify hash consistency between compute_hash() and incremental
         * maintenance.  Any discrepancy corrupts TT probes and repetition
         * detection permanently. */
        U64 computed_hash = compute_hash(&s->board);
        assert(computed_hash == s->board.hash && "Hash mismatch at root - TT corruption risk");
    }

    if (s->aborted)
        return 0;
    s->nodes++;
    if (ply >= 100)
    {
        return quiescence_search(s, alpha, beta, ply, 0);
    }
    if ((s->nodes & s->time_check_mask) == 0)
    {
        double elapsed = get_time() - s->start_time;
        if (elapsed >= s->time_limit || g_engine_abort_flag ||
            (s->node_limit > 0 && s->nodes >= s->node_limit))
        {
            s->aborted = 1;
            return 0;
        }
    }

    U64 key = s->board.hash;
    Move tt_move = {0};
    int tt_score = -INF;
    int tt_flag = -1;
    int tt_val = tt_probe(s, key, depth, alpha, beta, &tt_move, ply, &tt_score, &tt_flag);
    if (tt_val != INF + 1)
        return tt_val;

    if (TB_LARGEST > 0 && depth >= 2)
    {
        U64 all_white = s->board.pieces[WHITE][PAWN] | s->board.pieces[WHITE][KNIGHT] |
                        s->board.pieces[WHITE][BISHOP] | s->board.pieces[WHITE][ROOK] |
                        s->board.pieces[WHITE][QUEEN] | s->board.pieces[WHITE][KING];
        U64 all_black = s->board.pieces[BLACK][PAWN] | s->board.pieces[BLACK][KNIGHT] |
                        s->board.pieces[BLACK][BISHOP] | s->board.pieces[BLACK][ROOK] |
                        s->board.pieces[BLACK][QUEEN] | s->board.pieces[BLACK][KING];
        int total_pieces = count_bits(all_white) + count_bits(all_black);
        int w_bishops = count_bits(s->board.pieces[WHITE][BISHOP]);
        int b_bishops = count_bits(s->board.pieces[BLACK][BISHOP]);
        int w_knights = count_bits(s->board.pieces[WHITE][KNIGHT]);
        int b_knights = count_bits(s->board.pieces[BLACK][KNIGHT]);
        int total_pawns = count_bits(s->board.pieces[WHITE][PAWN] | s->board.pieces[BLACK][PAWN]);
        int is_kbnk = (w_bishops + b_bishops == 1 && w_knights + b_knights == 1 && total_pawns == 0);
        if (total_pieces <= (int)TB_LARGEST && total_pieces >= 3 && s->board.castling_rights == 0 && !is_kbnk)
        {
            unsigned ep_sq = 0;
            if (s->board.en_passant >= 0 && s->board.en_passant < 64)
                ep_sq = (unsigned)s->board.en_passant + 1;
            unsigned wdl = tb_probe_wdl(
                all_white,
                all_black,
                s->board.pieces[WHITE][KING] | s->board.pieces[BLACK][KING],
                s->board.pieces[WHITE][QUEEN] | s->board.pieces[BLACK][QUEEN],
                s->board.pieces[WHITE][ROOK] | s->board.pieces[BLACK][ROOK],
                s->board.pieces[WHITE][BISHOP] | s->board.pieces[BLACK][BISHOP],
                s->board.pieces[WHITE][KNIGHT] | s->board.pieces[BLACK][KNIGHT],
                s->board.pieces[WHITE][PAWN] | s->board.pieces[BLACK][PAWN],
                0, /* rule50: pass 0 to WDL probe (Fathom rejects non-zero values) */
                0,
                ep_sq,
                s->board.side_to_move == WHITE);
            if (wdl != TB_RESULT_FAILED)
            {
                /* Sanity check: if tablebase claims DRAW but material imbalance
                 * is huge (e.g. Q vs R, BN vs bare K), the TB file may be corrupt.
                 * Ignore corrupt TB results and fall back to search + eval. */
                if (wdl == TB_DRAW)
                {
                    int w_mat = count_bits(s->board.pieces[WHITE][QUEEN]) * get_piece_value(QUEEN) +
                                count_bits(s->board.pieces[WHITE][ROOK]) * get_piece_value(ROOK) +
                                count_bits(s->board.pieces[WHITE][BISHOP]) * get_piece_value(BISHOP) +
                                count_bits(s->board.pieces[WHITE][KNIGHT]) * get_piece_value(KNIGHT);
                    int b_mat = count_bits(s->board.pieces[BLACK][QUEEN]) * get_piece_value(QUEEN) +
                                count_bits(s->board.pieces[BLACK][ROOK]) * get_piece_value(ROOK) +
                                count_bits(s->board.pieces[BLACK][BISHOP]) * get_piece_value(BISHOP) +
                                count_bits(s->board.pieces[BLACK][KNIGHT]) * get_piece_value(KNIGHT);
                    int mat_diff = w_mat - b_mat;
                    if (s->board.side_to_move == BLACK)
                        mat_diff = -mat_diff;
                    /* If side to move has >400 advantage, TB DRAW is suspicious */
                    if (mat_diff > 400)
                        goto tb_done;
                }

                int tb_score;
                /* DTZ optimization (Task 4.1b): use 2*ply multiplier for
                 * TB_WIN/TB_LOSS to create a steeper gradient that more
                 * strongly prefers faster wins and slower losses.
                 * Root search already uses DTZ-based scoring (100000-2*dtz).
                 * The 2*ply multiplier in negamax ensures intermediate
                 * TB-probed nodes also favor shorter paths to the win. */
                if (wdl == TB_WIN)
                    tb_score = MATE_SCORE - 200 - 2 * ply;
                else if (wdl == TB_CURSED_WIN)
                    tb_score = MATE_SCORE - 2000 - ply;
                else if (wdl == TB_DRAW)
                    tb_score = 0;
                else if (wdl == TB_BLESSED_LOSS)
                    tb_score = -(MATE_SCORE - 2000) + ply;
                else
                    tb_score = -(MATE_SCORE - 200) + 2 * ply;
                s->tb_hits++;
                if (tb_score >= beta)
                    return beta;
                if (tb_score > alpha)
                    alpha = tb_score;
            }
        tb_done:;
        }
    }

    {
        int rep_i;
        int total_reps = 0;
        int game_reps = 0;
        int search_reps = 0;
        /* Task #109: game_history 用哈希表 O(1) 查询替代线性扫描 */
        game_reps = game_rep_count_cached(s, key);
        /* search_history 是栈式 (深度通常 <30), 线性扫描成本可接受 */
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

    s->pv_length[ply] = 0;

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
    if (in_check && ext_count < 2)
    {
        depth++;
        ext_count++;
    }

    int is_endgame = 0;
    int is_simple_endgame = 0;
    int is_one_sided_major_endgame = 0; /* one side has Q/R, other has none */
    {
        int npm = s->board.npm[0] + s->board.npm[1];
        if (npm <= g_runtime_params.endgame_phase_threshold)
            is_endgame = 1;
        if (npm <= 3)
            is_simple_endgame = 1;
        /* Detect one-sided major piece endgames (e.g. Q+R vs K+P) even when
         * npm > 3. These are "simple" in the sense that pruning should be
         * conservative to avoid missing forced mates. */
        if (is_endgame)
        {
            int w_majors = count_bits(s->board.pieces[WHITE][QUEEN]) + count_bits(s->board.pieces[WHITE][ROOK]);
            int b_majors = count_bits(s->board.pieces[BLACK][QUEEN]) + count_bits(s->board.pieces[BLACK][ROOK]);
            if ((w_majors > 0 && b_majors == 0) || (b_majors > 0 && w_majors == 0))
            {
                is_one_sided_major_endgame = 1;
                if (!is_simple_endgame)
                    is_simple_endgame = 2;
            }
        }
        if (is_simple_endgame)
        {
            int w_pawns = count_bits(s->board.pieces[WHITE][PAWN]);
            int b_pawns = count_bits(s->board.pieces[BLACK][PAWN]);
            int w_knights = count_bits(s->board.pieces[WHITE][KNIGHT]);
            int b_knights = count_bits(s->board.pieces[BLACK][KNIGHT]);
            int w_bishops = count_bits(s->board.pieces[WHITE][BISHOP]);
            int b_bishops = count_bits(s->board.pieces[BLACK][BISHOP]);
            int w_rooks = count_bits(s->board.pieces[WHITE][ROOK]);
            int b_rooks = count_bits(s->board.pieces[BLACK][ROOK]);
            int w_queens = count_bits(s->board.pieces[WHITE][QUEEN]);
            int b_queens = count_bits(s->board.pieces[BLACK][QUEEN]);
            int w_majors = w_rooks + w_queens;
            int b_majors = b_rooks + b_queens;
            int w_minors = w_knights + w_bishops;
            int b_minors = b_knights + b_bishops;
            if (w_majors == 0 && b_majors == 0 && w_pawns == 0 && b_pawns == 0)
                is_simple_endgame = 2;
            else if (w_majors + b_majors <= 1 && w_pawns + b_pawns <= 2)
                is_simple_endgame = 2;
            (void)w_minors;
            (void)b_minors;
        }
    }

    /* Endgame checkmate extension: in clearly winning endgames (e.g. KQ+P vs K),
     * extend search depth to help find checkmate paths more efficiently.
     * Only apply when one side has Q or R and the other has no Q/R at all. */
    if (is_endgame && ext_count < 3)
    {
        int w_mat = s->board.npm[0];
        int b_mat = s->board.npm[1];
        int w_has_major = (count_bits(s->board.pieces[WHITE][QUEEN]) + count_bits(s->board.pieces[WHITE][ROOK])) > 0;
        int b_has_major = (count_bits(s->board.pieces[BLACK][QUEEN]) + count_bits(s->board.pieces[BLACK][ROOK])) > 0;
        if (w_has_major && !b_has_major && w_mat - b_mat > 400)
        {
            depth++;
            ext_count++;
        }
        else if (b_has_major && !w_has_major && b_mat - w_mat > 400)
        {
            depth++;
            ext_count++;
        }
    }

    int static_eval = evaluate(&s->board);
    if (s->board.side_to_move == BLACK)
        static_eval = -static_eval;

    int improving = 0;
    if (ply >= 2)
    {
        int prev_eval = s->static_eval_stack[ply - 2];
        if (prev_eval != EVAL_SCORE_INVALID)
            improving = (static_eval > prev_eval);
    }
    s->static_eval_stack[ply] = static_eval;

    /* Internal Iterative Deepening (IID):
     * If we don't have a TT move and this is a PV node,
     * do a reduced search to find a good move first.
     * Use isolated ext_count to avoid consuming main search extension budget.
     */
    if (g_runtime_params.iid_enabled && tt_move.from == 0 && tt_move.to == 0 && depth >= 4 && (beta - alpha > 1))
    {
        int iid_ext = 0;
        int iid_score = negamax(s, depth - 2, alpha, beta, iid_ext, ply);
        if (!s->aborted)
        {
            tt_probe(s, key, depth - 2, alpha, beta, &tt_move, ply, NULL, NULL);
        }
    }

    /* IIR: Reduce depth when no TT move available (non-PV nodes only) */
    if (tt_move.from == 0 && tt_move.to == 0 && depth >= 4 && (beta - alpha <= 1))
    {
        depth -= 1;
    }

    if (depth <= 0)
    {
        s->search_history_count = saved_history_count;
        return quiescence_search(s, alpha, beta, ply, 0);
    }

    /* Razoring: If the static evaluation is far below alpha at shallow depths,
     * we can reduce the search depth or return the evaluation directly.
     * This is applied before move generation to save time.
     * Disabled in clearly winning positions to avoid missing forced mates.
     */
    if (g_runtime_params.razoring_enabled && should_apply_razoring(s, depth, alpha, in_check) && (beta - alpha == 1) && !is_simple_endgame && static_eval < 2000)
    {
        g_prof_razoring_triggered++;
        int razor_margin = g_runtime_params.razoring_margin + (depth - 1) * 100;

        if (static_eval + razor_margin < alpha)
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
    int move_see_vals[MAX_MOVES]; /* Pure SEE values for SEE pruning (Task #110) */
    int n = generate_pseudo_legal_moves(b, moves);

    int legal_count = 0;
    int i;

    for (i = 0; i < n; i++)
    {
        move_see_vals[i] = 0; /* default for non-captures */
        if (moves[i].from == tt_move.from && moves[i].to == tt_move.to && moves[i].promotion == tt_move.promotion)
        {
            moves[i].score = TT_MOVE_SCORE;
        }
        else if (moves[i].capture)
        {
            int see_val = see(b, moves[i].from, moves[i].to);
            move_see_vals[i] = see_val; /* Store pure SEE for pruning (Task #110) */
            /* 诊断: 统计 see() 返回值分布 */
            if (see_val < 0)
            {
                g_see_scoring_bad_count++;
                g_see_scoring_bad_sum += see_val;
                if (see_val < g_see_scoring_bad_min || g_see_scoring_bad_count == 1)
                    g_see_scoring_bad_min = see_val;
            }
            if (see_val >= 0)
            {
                moves[i].score = GOOD_CAPTURE_BASE + see_val * MVV_LVA_SCALE + mvv_lva(b, &moves[i]);
            }
            else
            {
                moves[i].score = BAD_CAPTURE_BASE + see_val;
            }
            /* Capture History: refine capture ordering based on past success */
            if (g_runtime_params.capture_history_enabled)
            {
                int ch_attacker = piece_on_square(b, moves[i].from);
                int ch_captured = moves[i].capture;
                if (ch_attacker > 0 && ch_attacker <= 6 && ch_captured > 0 && ch_captured <= 6)
                    moves[i].score += g_capture_history[ch_attacker][moves[i].to][ch_captured];
            }
        }
        else
        {
            int k1, k2;
            if (ply < 64)
            {
                for (k1 = 0; k1 < 2; k1++)
                {
                    if (s->killers[ply][k1].from == moves[i].from && s->killers[ply][k1].to == moves[i].to)
                    {
                        moves[i].score = KILLER_BASE_SCORE - k1 * KILLER_STEP;
                        break;
                    }
                }
            }
            if (moves[i].score == 0 && ply >= 1)
            {
                Move prev_move_cm = s->move_stack[ply - 1];
                int prev_side = 1 - s->board.side_to_move;
                Move *cm = &s->countermove[prev_side][prev_move_cm.from][prev_move_cm.to];
                if (cm->from == moves[i].from && cm->to == moves[i].to)
                {
                    moves[i].score = COUNTERMOVE_SCORE;
                }
            }
            if (moves[i].score == 0 && ply >= 3)
            {
                Move *fu = &s->followup[s->board.side_to_move][moves[i].from][moves[i].to];
                if (fu->from == moves[i].from && fu->to == moves[i].to)
                {
                    moves[i].score = FOLLOWUP_SCORE;
                }
            }
            if (moves[i].score == 0)
            {
                moves[i].score = s->history[moves[i].from][moves[i].to];
            }
            /* Continuation History: refine quiet move ordering with previous-move context */
            if (g_runtime_params.continuation_history_enabled && ply >= 1)
            {
                int ch_prev_pt = s->piece_type_stack[ply - 1];
                int ch_curr_pt = piece_on_square(b, moves[i].from);
                if (ch_prev_pt > 0 && ch_prev_pt <= 6 && ch_curr_pt > 0 && ch_curr_pt <= 6)
                    moves[i].score += g_cont_history[ch_prev_pt][s->move_stack[ply - 1].to][ch_curr_pt][moves[i].to];
            }
            /* Promotion bonus: always prioritize promotions regardless of game phase.
             * A promotion is one of the most critical moves in any position and must
             * be searched early to avoid missing mates or tactical wins. */
            if (moves[i].promotion)
                moves[i].score += PROMOTION_SCORE;
            if (is_endgame)
            {
                /* Check bonus removed from scoring phase — move_gives_check()
                 * does full make/unmake which is too expensive per-move.
                 * Checks will still be found during search naturally. */
                if (!moves[i].capture && !moves[i].promotion)
                {
                    int from_piece = piece_on_square(&s->board, moves[i].from);
                    if (from_piece == PAWN)
                    {
                        int from_rank = moves[i].from / 8;
                        int to_rank = moves[i].to / 8;
                        int side = s->board.side_to_move;
                        int adv_rank = (side == WHITE) ? to_rank : (7 - to_rank);
                        if (adv_rank >= 5)
                        {
                            int from_file = moves[i].from % 8;
                            int is_passed = 1;
                            int df;
                            for (df = -1; df <= 1; df++)
                            {
                                int af = from_file + df;
                                if (af < 0 || af > 7)
                                    continue;
                                U64 enemy_pawns = s->board.pieces[1 - side][PAWN];
                                U64 mask = file_masks[af];
                                if (side == WHITE)
                                    mask &= ~((1ULL << (moves[i].from + 1)) - 1);
                                else
                                    mask &= ((1ULL << moves[i].from) - 1);
                                if (enemy_pawns & mask)
                                {
                                    is_passed = 0;
                                    break;
                                }
                            }
                            if (is_passed)
                            {
                                int push_bonus = adv_rank * ENDGAME_PASSER_ADVANCE_SCALE;
                                moves[i].score += push_bonus;
                            }
                        }
                    }
                }
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
                        moves[i].score += BLUNDER_PENALTY;
                    }
                    if (moves[i].from == g_blunder_memory[bi].good_from && moves[i].to == g_blunder_memory[bi].good_to)
                    {
                        moves[i].score += BLUNDER_BONUS;
                    }
                }
            }
        }
    }

    int best_score = -MATE_SCORE;
    Move best_move = {0};
    int flag = 1;

    {
        int is_pv_node_rfp = (beta - alpha > 1);
        if (g_runtime_params.rfp_enabled && !in_check && !is_pv_node_rfp && depth >= 2 && depth <= 8 && abs(beta) < MATE_SCORE - 100 && !is_simple_endgame && !(is_endgame && static_eval > 2000))
        {
            g_prof_rfp_triggered++;
            int margin_rfp = depth * depth * RFP_DEPTH_SQ_SCALE + depth * RFP_DEPTH_SCALE;
            if (margin_rfp > RFP_CAP)
                margin_rfp = RFP_CAP;
            if (improving)
                margin_rfp = margin_rfp * RFP_IMPROVING_NUM / RFP_IMPROVING_DEN;
            if (b->phase < 10)
                margin_rfp = margin_rfp * RFP_LOW_PHASE_NUM / RFP_LOW_PHASE_DEN;
            if (static_eval - margin_rfp >= beta)
            {
                s->search_history_count = saved_history_count;
                return static_eval - margin_rfp;
            }
        }
    }

    /* Null Move Pruning:
     * Guard 1: abs(beta) < MATE_SCORE - 100 prevents NMP near mate scores.
     *   The old check (beta < INF - 1000) was useless because MATE_SCORE (900000)
     *   is far below INF (1000000), so NMP would still fire at mate scores.
     * Guard 2: abs(static_eval) < MATE_SCORE - 500 prevents NMP when the position
     *   is already evaluated as "nearly mated" — pruning here risks false positives
     *   (missing the opponent's defense) or false negatives (missing our own mate).
     * Guard 3: In won positions (eval > 2000), reduce NMP depth to be more careful.
     * Guard 4: In clearly winning positions (static_eval > 2000), reduce NMP
     *   reduction to avoid pruning away mating continuations.
     * Guard 5: Skip NMP in PV nodes. PV nodes need precise scores for correct
     *   move selection. NMP returns truncated beta, which can cause the PV move
     *   to be incorrectly replaced when the verification search is falsely
     *   confirmed by RFP (which can return values far above the zero-window beta).
     */
    int is_pv_node_nmp = (beta - alpha > 1);
    if (g_runtime_params.nmp_enabled && depth >= NULL_MOVE_MIN_DEPTH && !in_check && !is_pv_node_nmp && abs(beta) < MATE_SCORE - 100 && abs(static_eval) < MATE_SCORE - 500 && has_non_pawn_material(b, b->side_to_move) && !is_simple_endgame && !is_one_sided_major_endgame)
    {
        g_prof_nmp_triggered++;
        /* Guard 6: Disable NMP in pure pawn endgames.
         * Zugzwang is extremely common in pawn endgames — a null move
         * gives an unrealistically optimistic result because being forced
         * to move is often a disadvantage. */
        {
            int total_minors_majors = count_bits(b->pieces[WHITE][KNIGHT] | b->pieces[WHITE][BISHOP] |
                b->pieces[WHITE][ROOK] | b->pieces[WHITE][QUEEN] |
                b->pieces[BLACK][KNIGHT] | b->pieces[BLACK][BISHOP] |
                b->pieces[BLACK][ROOK] | b->pieces[BLACK][QUEEN]);
            if (total_minors_majors == 0)
                goto skip_nmp;
        }
        int saved_side = b->side_to_move;
        int saved_ep = b->en_passant;
        U64 saved_hash = b->hash;
        U64 saved_pawn_hash = b->pawn_hash;
        int saved_eval_score = b->eval_score;
        int saved_mg = b->mg_score;
        int saved_eg = b->eg_score;
        int saved_halfmove = b->halfmove_clock;
        if (saved_ep >= 0 && saved_ep < 64)
            b->hash ^= zobrist_table[12 * 64 + 1 + 4 + saved_ep];
        b->hash ^= zobrist_table[12 * 64];
        b->side_to_move = 1 - b->side_to_move;
        b->en_passant = -1;
        b->eval_score = EVAL_SCORE_INVALID;
        int R = g_runtime_params.nmp_base_reduction + depth / g_runtime_params.nmp_depth_divisor;
        if (static_eval - beta > NMP_HIGH_EVAL_THRESHOLD)
            R += NMP_HIGH_EVAL_EXTRA_REDUCTION;
        /* In won positions, be more conservative with NMP to avoid
         * pruning away the opponent's defenses (false positive mates)
         * or our own mating continuations (false negative mates). */
        if (abs(static_eval) > NMP_BIG_ADV_THRESHOLD)
            R = (R + NMP_BIG_ADV_REDUCTION >= 1) ? R + NMP_BIG_ADV_REDUCTION : 1;
        else if (abs(static_eval) > NMP_MED_ADV_THRESHOLD)
            R = (R + NMP_MED_ADV_REDUCTION >= 1) ? R + NMP_MED_ADV_REDUCTION : 1;
        if (b->phase < NMP_LOW_PHASE_THRESHOLD)
            R = (R + NMP_LOW_PHASE_REDUCTION >= 1) ? R + NMP_LOW_PHASE_REDUCTION : 1;
        if (is_endgame)
            R = (R > 2) ? R - g_runtime_params.endgame_nmr_bonus : 1;
        /* In endgames with passed pawns, NMP is particularly dangerous because
         * a null move ignores pawn advancement, which can be the most critical
         * factor. Reduce NMP aggression further to avoid missing promotion
         * threats or defense against them. */
        if (is_endgame && b->phase < 10)
        {
            /* Quick check: if either side has pawns in the endgame, they might
             * be passed. Be more conservative with NMP reduction. */
            if (count_bits(b->pieces[WHITE][PAWN] | b->pieces[BLACK][PAWN]) > 0)
            {
                R = (R > 2) ? R - 1 : 1;
            }
        }
        if (R >= depth)
            R = depth - 1;
        if (R < 1)
            R = 1;
        int null_score = -negamax(s, depth - (R + 1), -beta, -beta + 1, 0, ply + 1);
        b->side_to_move = saved_side;
        b->en_passant = saved_ep;
        b->hash = saved_hash;
        b->pawn_hash = saved_pawn_hash;
        b->eval_score = saved_eval_score;
        b->mg_score = saved_mg;
        b->eg_score = saved_eg;
        b->halfmove_clock = saved_halfmove;
        /* Restore search history: keep current position key, clear any keys
         * added by the null-move sub-search (which would otherwise pollute
         * the verification search's repetition detection). */
        s->search_history_count = saved_history_count + 1;
        if (s->aborted)
        {
            s->search_history_count = saved_history_count;
            return 0;
        }
        if (null_score >= beta)
        {
            if (depth >= NULL_MOVE_VERIFICATION_DEPTH)
            {
                g_nmp_verify_depth++;
                /* Keep the current position in the repetition history for
                 * the verification search. Previously this was resetting
                 * to saved_history_count which removed the current position,
                 * potentially allowing the verify search to miss repetitions. */
                int verify_reduction = NULL_MOVE_VERIFICATION_REDUCTION;
                /* In endgames, use deeper verification to catch zugzwang */
                if (is_endgame && b->phase < 8)
                    verify_reduction = NULL_MOVE_VERIFICATION_REDUCTION + 2;
                /* Save PV and static eval before verification search.
                 * The verification runs at the same ply and would overwrite
                 * static_eval_stack[ply] and pv_table[ply], corrupting the
                 * improving flag and PV collection for the main search. */
                Move saved_pv_nmp[64];
                int saved_pv_len_nmp = s->pv_length[ply];
                int saved_static_eval_nmp = s->static_eval_stack[ply];
                memcpy(saved_pv_nmp, s->pv_table[ply], 64 * sizeof(Move));
                int verify_score = negamax(s, depth - verify_reduction, beta - 1, beta, ext_count, ply);
                /* Restore state after verification search */
                s->pv_length[ply] = saved_pv_len_nmp;
                memcpy(s->pv_table[ply], saved_pv_nmp, 64 * sizeof(Move));
                s->static_eval_stack[ply] = saved_static_eval_nmp;
                if (s->aborted)
                {
                    s->search_history_count = saved_history_count;
                    return 0;
                }
                if (verify_score >= beta)
                {
                    g_prof_nmp_cutoffs++;
                    s->search_history_count = saved_history_count;
                    return beta;
                }
                g_nmp_verify_fail++;
            }
            else
            {
                g_prof_nmp_cutoffs++;
                s->search_history_count = saved_history_count;
                return beta;
            }
        }
        else
        {
            g_nmp_null_fail++;
        }
    }
    skip_nmp:;

    /* ProbCut: shallow capture search with elevated beta to detect likely cutoffs */
    if (g_runtime_params.probcut_enabled
        && depth >= g_runtime_params.probcut_min_depth
        && !in_check
        && abs(beta) < MATE_SCORE - 100
        && (beta - alpha <= 1))
    {
        g_prof_probcut_triggered++;
        int probcut_beta = beta + g_runtime_params.probcut_margin;
        int probcut_depth = depth - g_runtime_params.probcut_reduction;
        if (probcut_depth < 1) probcut_depth = 1;

        int pc_i;
        for (pc_i = 0; pc_i < n; pc_i++)
        {
            if (!moves[pc_i].capture)
                continue;
            /* Skip captures with negative SEE */
            int pc_see = see(b, moves[pc_i].from, moves[pc_i].to);
            if (pc_see < 0)
                continue;

            UndoInfo pc_undo;
            make_move(b, &moves[pc_i], &pc_undo);
            if (is_check(b, 1 - b->side_to_move))
            {
                unmake_move(b, &moves[pc_i], &pc_undo);
                continue;
            }
            int pc_score = -negamax(s, probcut_depth, -probcut_beta, -probcut_beta + 1, ext_count, ply + 1);
            unmake_move(b, &moves[pc_i], &pc_undo);
            if (s->aborted)
            {
                s->search_history_count = saved_history_count;
                return 0;
            }
            if (pc_score >= probcut_beta)
            {
                s->probcut_prunes++;
                g_prof_probcut_cutoffs++;
                s->probcut_nodes_saved += (long long)(1 << probcut_depth); /* estimate */
                s->search_history_count = saved_history_count;
                return beta;
            }
        }
    }

    int is_pv_node = (beta - alpha > 1);
    for (i = 0; i < n; i++)
    {
        pick_next_move(moves, n, i);

        /* Singular Extension: skip the excluded move */
        if (ply < 128 && (s->se_excluded[ply].from != 0 || s->se_excluded[ply].to != 0) &&
            moves[i].from == s->se_excluded[ply].from && moves[i].to == s->se_excluded[ply].to)
            continue;

        if (should_apply_futility_pruning(s, &moves[i], depth, i, in_check, alpha, is_endgame, static_eval, ply, improving))
        {
            int estimated_nodes_saved = (1 << depth) - 1;
            s->futility_prunes++;
            g_prof_futility_pruned++;
            s->futility_nodes_saved += estimated_nodes_saved;
            continue;
        }

        if (g_runtime_params.see_prune_enabled && !in_check && moves[i].capture && !moves[i].promotion && depth <= 3 &&
            legal_count >= 2 && i >= 2 && (beta - alpha <= 1))
        {
            /* Task #110: Use pure SEE value stored during scoring phase.
             * Previously used (score - BAD_CAPTURE_BASE) which included
             * capture_history adjustment, causing false SEE pruning when
             * capture_history was strongly negative. */
            int cached_see = move_see_vals[i];
            g_see_zero_window++;
            if (cached_see < 0)
            {
                g_see_bad_capture_count++;
                g_see_bad_capture_sum += cached_see;
                if (cached_see < g_see_bad_capture_min || g_see_bad_capture_count == 1)
                    g_see_bad_capture_min = cached_see;
            }
            if (cached_see < -depth * SEE_PRUNE_DEPTH_SCALE)
            {
                g_see_threshold_met++;
                g_prof_see_pruned++;
                continue;
            }
        }
        /* 诊断: 统计吃子着法总数和满足前 6 个条件的数量 */
        if (moves[i].capture && !moves[i].promotion && depth <= 8 && !in_check)
        {
            g_see_capture_total++;
            if (legal_count >= 1)
                g_see_eligible++;
        }

        if (g_runtime_params.history_prune_enabled && !in_check && !moves[i].capture && !moves[i].promotion &&
            depth <= 3 && legal_count > HISTORY_PRUNE_BASE + depth * depth &&
            (beta - alpha <= 1) &&
            s->history[moves[i].from][moves[i].to] < 0 &&
            !is_endgame)
        {
            g_prof_history_pruned++;
            continue;
        }

        if (ply < 128)
            s->piece_type_stack[ply] = piece_on_square(b, moves[i].from);

        UndoInfo undo;
        make_move(b, &moves[i], &undo);
        if (is_check(b, 1 - b->side_to_move))
        {
            unmake_move(b, &moves[i], &undo);
            continue;
        }
        legal_count++;

        /* TT Prefetch: 预取子节点的 TT 槽，减少递归调用时的 cache miss */
        {
            int tt_idx = (int)(b->hash & (U64)(s->tt_cluster_count - 1));
            __builtin_prefetch(&s->tt[tt_idx], 0, 1);
        }

        /* Late Move Pruning: prune quiet moves that are unlikely to improve alpha
         * Uses legal_count (actual legal moves searched) instead of loop index
         * to avoid pruning important moves when many pseudo-legal moves are illegal */
        if (g_runtime_params.lmp_enabled && !in_check && !is_pv_node && depth <= 5 && legal_count >= LMP_BASE + depth * depth && !moves[i].capture && !moves[i].promotion && static_eval < 2000)
        {
            g_prof_lmp_pruned++;
            unmake_move(b, &moves[i], &undo);
            continue;
        }

        /* Promotion extension: extend search by 1 ply when a pawn promotes.
         * This ensures critical promotion lines (often leading to mates) are
         * searched deeply enough to be correctly evaluated. */
        int promo_ext = (moves[i].promotion && ext_count < 3) ? 1 : 0;

        if (ply < 128)
            s->move_stack[ply] = moves[i];

        int score;
        if (i == 0)
        {
            int se_depth = promo_ext;
            if (g_runtime_params.singular_ext_enabled && depth >= 8 && moves[i].from == tt_move.from && moves[i].to == tt_move.to && tt_score > -MATE_SCORE + 100 && tt_score < MATE_SCORE - 100)
            {
                /* Singular Extension: verify that the TT move is singular by
                 * searching the position with the TT move excluded at reduced depth.
                 * If all alternatives score below (tt_score - 2*depth), the TT
                 * move is singular and deserves an extension. */
                int se_beta = tt_score - SE_BETA_DEPTH_SCALE * depth;
                if (se_beta < -MATE_SCORE + 100)
                    se_beta = -MATE_SCORE + 100;
                int se_depth_limit = depth / 2;

                /* Save PV table before SE search to avoid corruption.
                 * The SE search runs at the same ply and would overwrite
                 * pv_table[ply], pv_length[ply], and static_eval_stack[ply].
                 * Always save the full 64-entry array so the restore correctly
                 * clears any entries written by the SE search. */
                Move saved_pv[64];
                int saved_pv_len = s->pv_length[ply];
                int saved_static_eval = s->static_eval_stack[ply];
                memcpy(saved_pv, s->pv_table[ply], 64 * sizeof(Move));

                s->se_excluded[ply] = tt_move;
                int se_score = negamax(s, se_depth_limit, se_beta - 1, se_beta, ext_count, ply);
                s->se_excluded[ply] = (Move){0};

                /* Restore state after SE search */
                s->pv_length[ply] = saved_pv_len;
                memcpy(s->pv_table[ply], saved_pv, 64 * sizeof(Move));
                s->static_eval_stack[ply] = saved_static_eval;

                if (se_score < se_beta)
                    se_depth = 1;
            }
            score = -negamax(s, depth - 1 + se_depth, -beta, -alpha, ext_count + promo_ext, ply + 1);
        }
        else
        {
            int is_pv_node = (beta - alpha > 1);
            int apply_lmr = should_apply_lmr(s, &moves[i], depth, i, in_check, is_endgame, ply, move_see_vals[i]);

            if (apply_lmr)
            {
                int reduction = calculate_reduction(s, &moves[i], depth, i, is_pv_node, in_check, static_eval, ply, move_see_vals[i]);

                int estimated_nodes_saved = (1 << reduction) - 1;

                score = -negamax(s, depth - 1 + promo_ext - reduction, -alpha - 1, -alpha, ext_count + promo_ext, ply + 1);

                s->lmr_reductions++;
                g_prof_lmr_applied++;
                s->lmr_nodes_saved += estimated_nodes_saved;

                if (score > alpha)
                {
                    score = -negamax(s, depth - 1 + promo_ext, -alpha - 1, -alpha, ext_count + promo_ext, ply + 1);
                    s->lmr_re_searches++;
                    g_prof_lmr_full_research++;

                    if (score > alpha && score < beta)
                    {
                        score = -negamax(s, depth - 1 + promo_ext, -beta, -alpha, ext_count + promo_ext, ply + 1);
                    }
                }
            }
            else
            {
                score = -negamax(s, depth - 1 + promo_ext, -alpha - 1, -alpha, ext_count + promo_ext, ply + 1);

                if (score > alpha && score < beta)
                {
                    score = -negamax(s, depth - 1 + promo_ext, -beta, -alpha, ext_count + promo_ext, ply + 1);
                }
            }
        }
        unmake_move(b, &moves[i], &undo);

        if (s->aborted)
        {
            s->search_history_count = saved_history_count;
            return 0;
        }

        if (!moves[i].capture && !moves[i].promotion && score <= alpha)
        {
            s->history[moves[i].from][moves[i].to] -= depth * depth;
            if (s->history[moves[i].from][moves[i].to] < -HISTORY_SCORE_LIMIT)
                s->history[moves[i].from][moves[i].to] = -HISTORY_SCORE_LIMIT;
            /* Continuation History fail-low penalty */
            if (g_runtime_params.continuation_history_enabled && ply >= 1)
            {
                int fl_prev_pt = s->piece_type_stack[ply - 1];
                int fl_curr_pt = s->piece_type_stack[ply];
                if (fl_prev_pt > 0 && fl_prev_pt <= 6 && fl_curr_pt > 0 && fl_curr_pt <= 6)
                {
                    int16_t *ce = &g_cont_history[fl_prev_pt][s->move_stack[ply - 1].to][fl_curr_pt][moves[i].to];
                    history_atomic_add(ce, -depth * depth);
                }
            }
        }

        /* Capture History fail-low penalty */
        if (g_runtime_params.capture_history_enabled && moves[i].capture && !moves[i].promotion && score <= alpha)
        {
            int fl_att = s->piece_type_stack[ply];
            int fl_cap = moves[i].capture;
            if (fl_att > 0 && fl_att <= 6 && fl_cap > 0 && fl_cap <= 6)
            {
                int16_t *che = &g_capture_history[fl_att][moves[i].to][fl_cap];
                history_atomic_add(che, -depth * depth);
            }
        }

        if (score > best_score)
        {
            best_score = score;
            best_move = moves[i];
            if (score > alpha)
            {
                alpha = score;
                flag = 0;
                s->pv_table[ply][0] = moves[i];
                memcpy(&s->pv_table[ply][1], s->pv_table[ply + 1], s->pv_length[ply + 1] * sizeof(Move));
                s->pv_length[ply] = s->pv_length[ply + 1] + 1;
                if (alpha >= beta)
                {
                    flag = 2;
                    if (!moves[i].capture && ply < 128)
                    {
                        if (moves[i].from != s->killers[ply][0].from || moves[i].to != s->killers[ply][0].to)
                        {
                            /* Only shift if the new move is also different from killer[1],
                             * otherwise we'd duplicate killer[1] into killer[0]. */
                            if (moves[i].from != s->killers[ply][1].from || moves[i].to != s->killers[ply][1].to)
                            {
                                s->killers[ply][1] = s->killers[ply][0];
                                s->killers[ply][0] = moves[i];
                            }
                        }
                        s->history[moves[i].from][moves[i].to] += depth * depth;
                        if (s->history[moves[i].from][moves[i].to] > HISTORY_SCORE_LIMIT)
                            s->history[moves[i].from][moves[i].to] = HISTORY_SCORE_LIMIT;
                        /* Continuation History beta cutoff bonus */
                        if (g_runtime_params.continuation_history_enabled && ply >= 1)
                        {
                            int bc_prev_pt = s->piece_type_stack[ply - 1];
                            int bc_curr_pt = s->piece_type_stack[ply];
                            if (bc_prev_pt > 0 && bc_prev_pt <= 6 && bc_curr_pt > 0 && bc_curr_pt <= 6)
                            {
                                int16_t *bce = &g_cont_history[bc_prev_pt][s->move_stack[ply - 1].to][bc_curr_pt][moves[i].to];
                                history_atomic_add(bce, depth * depth);
                            }
                        }
                    }
                    /* Capture History beta cutoff bonus */
                    if (g_runtime_params.capture_history_enabled && moves[i].capture && ply < 128)
                    {
                        int bc_att = s->piece_type_stack[ply];
                        int bc_cap = moves[i].capture;
                        if (bc_att > 0 && bc_att <= 6 && bc_cap > 0 && bc_cap <= 6)
                        {
                            int16_t *bche = &g_capture_history[bc_att][moves[i].to][bc_cap];
                            history_atomic_add(bche, depth * depth);
                        }
                    }
                    if (ply >= 1)
                    {
                        Move prev_move = s->move_stack[ply - 1];
                        int prev_side = 1 - b->side_to_move;
                        s->countermove[prev_side][prev_move.from][prev_move.to] = moves[i];
                    }
                    if (ply >= 2)
                    {
                        Move prev_own_move = s->move_stack[ply - 2];
                        s->followup[b->side_to_move][prev_own_move.from][prev_own_move.to] = moves[i];
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
