# 国际象棋引擎内核技术提升报告

## ——面向 CCRL Blitz 2+1 规格（96s+0.8s/步）的全面棋力优化方案

---

## 目录

- [0. 引擎现状诊断与评级预估](#0-引擎现状诊断与评级预估)
- [1. 架构层关键瓶颈（Critical Path）](#1-架构层关键瓶颈critical-path)
- [2. 搜索算法深度优化](#2-搜索算法深度优化)
- [3. 评估函数全面重构](#3-评估函数全面重构)
- [4. 走法生成与排序优化](#4-走法生成与排序优化)
- [5. 时间管理策略](#5-时间管理策略)
- [6. 置换表与内存架构](#6-置换表与内存架构)
- [7. 多线程优化](#7-多线程优化)
- [8. 残局知识补充](#8-残局知识补充)
- [9. 参数调优方法论](#9-参数调优方法论)
- [10. 实施路线图与预期收益](#10-实施路线图与预期收益)

---

## 0. 引擎现状诊断与评级预估

### 0.1 架构现状总结

| 模块        | 现状                                         | 评价            |
| ----------- | -------------------------------------------- | --------------- |
| 棋盘表示    | Bitboard + Magic Bitboard                    | ✅ 良好         |
| Make/Unmake | **全板拷贝** (`*b = old`)                    | ❌ 致命瓶颈     |
| Zobrist哈希 | **每步全量重算**                             | ❌ 致命瓶颈     |
| 评估函数    | PST + 基础兵型 + 基础王安全                  | ⚠️ 中等偏弱     |
| 搜索框架    | Negamax + PVS + Aspiration                   | ✅ 框架正确     |
| 剪枝技术    | Null Move + LMR + Futility（Razoring被禁用） | ⚠️ 不完整       |
| 走法排序    | TT + MVV-LVA + Killer + History              | ⚠️ 有实现缺陷   |
| 时间管理    | 固定60%截断                                  | ❌ 极其粗糙     |
| 置换表      | 1M条目（~16MB），基础替换                    | ⚠️ 偏小         |
| 多线程      | Lazy SMP（有数据竞争隐患）                   | ⚠️ 有基础但粗糙 |

### 0.2 预估棋力（当前状态）

基于代码分析，该引擎目前预估在 **CCRL Blitz 1800–2100** 区间。核心原因：

- `make_move` 每次都通过 `piece_on_square` 线性扫描12个bitboard来定位棋子类型——这是 O(12) 的操作
- `unmake_move` 直接全板拷贝（`*b = *old`），导致每步需要拷贝整个 Board 结构体（含12个 U64 + 多个 int，约 130+ 字节）
- `compute_hash` 每次全量重算——遍历所有棋子、所有格子
- 这三个操作在搜索树的**每个节点**都会被调用，直接导致 NPS（Nodes Per Second）比同等引擎低 **3-5倍**

---

## 1. 架构层关键瓶颈（Critical Path）

### 1.1 Mailbox 辅助数组：消除 piece_on_square 瓶颈

**问题**：当前 `piece_on_square()` 遍历所有12个bitboard来定位一个格子上的棋子。这个函数在 `make_move`、`evaluate`、`mvv_lva`、`SEE` 等关键路径中被频繁调用。

**方案**：维护一个 `mailbox[64]` 数组，每个元素编码 `(side, piece_type)` 或编码为 `piece_index`：

```c
// 推荐编码：0=empty, 1-6=white P/N/B/R/Q/K, 7-12=black P/N/B/R/Q/K
static int mailbox[64];

// 在 make_move 中维护：
mailbox[from] = EMPTY;
mailbox[to] = piece_code; // side*6 + piece_type
```

**收益**：`piece_on_square` 从 O(12) 降至 O(1)，预计提升 NPS **15-25%**。

### 1.2 增量 Zobrist 哈希：消除全量重算

**问题**：当前 `compute_hash()` 在 `negamax` 的每个节点都被调用，它遍历所有棋子和格子重新计算哈希。这在深搜索中消耗了大量时间。

**方案**：在 Board 结构体中维护 `U64 hash`，在 `make_move` 中增量更新：

```c
// 移动棋子：先 XOR 掉旧位置，再 XOR 新位置
b->hash ^= zobrist_table[piece_idx(side, pt, from)];
b->hash ^= zobrist_table[piece_idx(side, pt, to)];

// 吃子：XOR 掉被吃棋子
if (m->capture)
    b->hash ^= zobrist_table[piece_idx(opp, cap_pt, to)];

// 王车易位：额外 XOR 车的变化
// 吃过路兵：额外 XOR 被吃兵
// 升变：XOR 掉兵，XOR 升变后的棋子
// 易位权变化：XOR 对应的 zobrist key
// 过路兵变化：XOR 旧/新的过路兵 zobrist key
// 换边：XOR side_to_move key
```

**收益**：哈希计算从 O(32) 降至 O(~5)，预计提升 NPS **20-30%**。

### 1.3 真正的 Unmake：消除全板拷贝

**问题**：当前 `unmake_move` 通过 `*b = *old` 恢复整个棋盘。这意味着每次 make_move 之前都需要保存整个 Board 结构体。

**方案**：实现增量 unmake，配合 UndoInfo 结构：

```c
typedef struct {
    int captured_piece;     // 被吃棋子类型
    int castling_rights;    // 旧的易位权
    int en_passant;         // 旧的过路兵格
    int halfmove_clock;     // 旧的半步计数
    U64 hash;               // 旧的哈希
    int eval_score;         // 旧的评估缓存
} UndoInfo;

void make_move(Board *b, const Move *m, UndoInfo *undo) {
    // 保存状态
    undo->castling_rights = b->castling_rights;
    undo->en_passant = b->en_passant;
    undo->halfmove_clock = b->halfmove_clock;
    undo->hash = b->hash;
    undo->eval_score = b->eval_score;
    // ... 增量更新 ...
}

void unmake_move(Board *b, const Move *m, const UndoInfo *undo) {
    // 反向增量更新
    b->castling_rights = undo->castling_rights;
    b->en_passant = undo->en_passant;
    b->halfmove_clock = undo->halfmove_clock;
    b->hash = undo->hash;
    b->eval_score = undo->eval_score;
    // 反向移动棋子...
}
```

**收益**：

- 消除每步 ~130 字节的 memcpy
- 消除 make_move 前保存整个 Board 的栈开销
- 搜索栈空间大幅减少（从每层 ~200 bytes 降至 ~40 bytes）
- 预计提升 NPS **额外 15-20%**

### 1.4 综合效果预估

以上三项改造是**相互耦合**的，应一起实施。综合预估：

| 指标                | 改造前     | 改造后（预估）   |
| ------------------- | ---------- | ---------------- |
| NPS（中局典型位置） | ~200K-400K | ~800K-1.5M       |
| 搜索深度（2秒内）   | ~8-10 ply  | ~10-13 ply       |
| 预估 Elo 提升       | —          | **+100~150 Elo** |

---

## 2. 搜索算法深度优化

### 2.1 修复并增强 Razoring

**问题**：`should_apply_razoring()` 当前硬编码 `return 0`，完全被禁用。

**方案**：实现分层 Razoring：

```c
static int should_apply_razoring(SearchState *s, int depth, int alpha, int in_check, int ply) {
    if (in_check) return 0;
    if (depth > 3) return 0;  // 仅在浅层使用
    if (ply == 0) return 0;   // 不在根节点使用

    int eval = evaluate(&s->board);
    // 从TT获取的静态评估优先
    int razor_margin = 300 + depth * 200;

    if (eval + razor_margin < alpha) {
        if (depth <= 1) {
            // depth 1: 直接进入 quiescence search
            return 1;
        }
        // depth 2-3: 先做一次 reduced search 验证
        return 2; // 标记需要验证
    }
    return 0;
}
```

**预期收益**：在低深度节点节约 5-10% 搜索量，约 **+15-25 Elo**。

### 2.2 改进 LMR 公式

**问题**：当前 LMR 公式 `1 + log(depth) * log(moveNum) / 2.5` 过于简单，且存在以下问题：

- `move_gives_check()` 在 LMR 判断中被调用，但它做了 `make_move` + `is_check`——极其昂贵
- 没有利用 history score 的细粒度信息
- 残局减 1 的固定规则太粗糙

**方案**：采用 Stockfish 风格的 LMR 表 + 多维调整：

```c
// 预计算 LMR 表
static int lmr_table[64][64]; // [depth][moveNum]

void init_lmr_table() {
    for (int d = 1; d < 64; d++)
        for (int m = 1; m < 64; m++)
            lmr_table[d][m] = (int)(0.75 + log(d) * log(m) / 2.25);
}

// 多维调整
int reduction = lmr_table[min(depth, 63)][min(move_num, 63)];

// 基于 history 的精细调整（核心创新点）
int hist = s->history[moving_piece][to][side_to_move];
reduction -= hist / 4000;  // history 好的走法减少 reduction

// PV 节点减少 reduction
if (is_pv_node) reduction -= 1;

// 被将军时不减少
// 给杀的走法不减少
if (move_gives_check_fast(b, move)) reduction -= 1;

// 非捕获走法且 history 极差时增加 reduction
if (hist < -4000) reduction += 1;

// 确保 reduction 合法
reduction = clamp(reduction, 0, depth - 1);
```

**关键优化**：用预计算的"给杀检测"（基于攻击位图）替代 `make_move + is_check`：

```c
static int move_gives_check_fast(const Board *b, const Move *m) {
    int opp_king_sq = lsb_index(b->pieces[1 - b->side_to_move][KING]);
    int from = m->from, to = m->to;
    int pt = piece_on_square(b, from);

    // 直接给杀：棋子到达攻击到对方王的格子
    switch (pt) {
        case KNIGHT: return (knight_attacks[to] >> opp_king_sq) & 1;
        case BISHOP: // 需要射线检测
        case ROOK:
        case QUEEN: // 射线检测（考虑遮挡变化）
        // ...
    }

    // 发现杀（discovered check）：移走from格后，是否有射线棋子攻击到对方王
    // 检查 from 是否在 opp_king 与己方射线棋子之间的射线上
    return discovered_check_possible(b, from, to, opp_king_sq);
}
```

**预期收益**：LMR 精度提升，约 **+30-50 Elo**。

### 2.3 启用将军延伸（Check Extension）

**问题**：代码中将军延伸被注释掉了。

**方案**：有限制的将军延伸，避免搜索爆炸：

```c
if (in_check && ext_count < 3) {  // 最多延伸3次
    // 只延伸 "危险" 的将军：逃逸走法少于3个
    int escape_count = count_legal_evasions(b);
    if (escape_count <= 2) {
        depth += 1;
        ext_count++;
    }
}
```

更激进的做法——**Single Reply Extension**：当只有唯一合法应杀走法时，强制延伸：

```c
if (in_check) {
    int legal_moves = count_legal_moves_fast(b);
    if (legal_moves == 1) {
        depth += 1;  // 强制延伸，不消耗 ext_count
        ext_count++;
    } else if (legal_moves <= 2 && ext_count < 3) {
        depth += 1;
        ext_count++;
    }
}
```

**预期收益**：在战术关键路径上搜索更深，约 **+20-35 Elo**。

### 2.4 ProbCut（概率剪枝）

**原理**：在 depth >= 5 的节点，如果前一层浅搜索（depth-4）的结果远超 beta，则大概率当前深度搜索也会 beta cutoff。

```c
// 在 null move pruning 之后，走法生成之前
if (depth >= 5 && abs(beta) < MATE_SCORE - 100) {
    int rbeta = min(beta + 200, MATE_SCORE - 100);
    // 只搜索 SEE >= rbeta - static_eval 的捕获走法
    Board saved = *b;
    int probcut_score = -probcut_search(s, depth - 4, -rbeta, -rbeta + 1, ply + 1);
    *b = saved;
    if (probcut_score >= rbeta) {
        return beta;
    }
}
```

**预期收益**：节约 ~5-8% 搜索量，约 **+15-25 Elo**。

### 2.5 Static Exchange Evaluation (SEE) 在主搜索中的应用

**问题**：当前 SEE 仅在 quiescence search 中使用，且实现有bug（occupied 位图在循环中没有正确维护——滑动攻击者被移除后应重新计算射线）。

**方案**：在主搜索的走法排序阶段，对捕获走法进行 SEE 过滤：

```c
// 走法排序时，计算 SEE
if (moves[i].capture) {
    int see_val = see(&s->board, moves[i].from, moves[i].to);
    if (see_val >= 0) {
        moves[i].score = GOOD_CAPTURE_BASE + mvv_lva_score;
    } else {
        moves[i].score = BAD_CAPTURE_BASE + see_val; // 负SEE走法后排
    }
}
```

**修复 SEE bug**：当前代码在移除攻击者后没有更新滑动攻击者的射线。正确做法是在 `occupied` 中清除被移除的攻击者位置后，重新查询射线攻击。

**预期收益**：坏捕获后排可以显著改善走法排序，约 **+20-30 Elo**。

### 2.6 改进 Internal Iterative Deepening (IID)

**问题**：当前 IID 在 TT miss 且 depth >= 4 时触发，但使用 `depth - 2` 做完整 alpha-beta 搜索，开销过大。

**方案**：采用更轻量的 IID 策略：

```c
if (tt_move.from == 0 && tt_move.to == 0 && depth >= 5) {
    // 使用更浅的搜索深度
    int iid_depth = depth / 2;
    negamax(s, iid_depth, alpha, beta, ext_count, ply);
    // 重新查询 TT 获取 best move
    tt_probe(s, key, 0, alpha, beta, &tt_move, ply, NULL);
}
```

更激进的做法是完全移除 IID，改为在走法排序中使用更好的启发式：

```c
// 如果 TT 没有走法，使用静态评估决定第一个走法
// 通过"威胁评估"选择最可能的候选走法
```

**预期收益**：减少 IID 开销约 **+10-15 Elo**。

### 2.7 Singular Extension 与 Multi-Cut

**原理**：如果一个走法明显优于其他所有走法（singular move），应该对它进行搜索延伸。

```c
// 在搜索第一个走法（TT move）之前
if (depth >= 8 && tt_move_valid && tt_score >= beta - 20) {
    int singular_beta = tt_score - 50;
    int singular_depth = depth / 2;

    // 排除 TT move，搜索其余走法
    int singular_score = negamax_excluding(s, singular_depth,
                                           singular_beta - 1, singular_beta,
                                           ply, tt_move);

    if (singular_score < singular_beta) {
        // TT move 是 singular，延伸搜索
        depth += 1;
    } else if (singular_score >= beta) {
        // Multi-Cut: 即使没有 TT move 也能 cutoff
        return beta;
    }
}
```

**预期收益**：在关键位置搜索更深，约 **+20-40 Elo**（这是现代引擎的重要技术）。

### 2.8 Null Move Pruning 改进

**问题**：当前 Null Move 的 reduction 是固定的 `NULL_MOVE_REDUCTION`。

**方案**：采用自适应 reduction：

```c
int R = 3 + depth / 6;  // 基础 reduction 随深度增长

// 根据静态评估与 beta 的差距调整
int eval_margin = (eval - beta) / 200;
R += min(eval_margin, 3);  // 优势越大，reduction 越大

// 残局中更保守
if (is_endgame) R = max(R - 1, 2);

// 上限保护
R = min(R, depth - 1);
```

**预期收益**：更精准的 null move 剪枝，约 **+10-15 Elo**。

### 2.9 Aspiration Window 改进

**问题**：当前 aspiration window 固定为 ±25，窗口失败后直接回退到全窗口。

**方案**：渐进式窗口扩展：

```c
int window = 15;  // 初始窗口
while (true) {
    alpha = best_score - window;
    beta = best_score + window;

    // 搜索...

    if (score <= alpha) {
        // Fail-low: 向下扩展窗口
        window *= 2;
        beta = (alpha + beta) / 2;  // 缩小上界
        alpha = score - window;
    } else if (score >= beta) {
        // Fail-high: 向上扩展窗口
        window *= 2;
        beta = score + window;
    } else {
        break;  // 窗口内命中
    }

    if (window > 500) {
        alpha = -INF; beta = INF;  // 最终回退到全窗口
    }
}
```

**预期收益**：减少窗口失败后的重搜索开销，约 **+10-20 Elo**。

---

## 3. 评估函数全面重构

### 3.1 真正的 Mobility（棋子活动性）

**问题**：当前评估中几乎没有 mobility 计算（仅有bishop的一个粗略版本，只检测兵颜色而非实际可达格子数）。

**方案**：为每种棋子计算可达格子数：

```c
// Knight mobility
U64 knight_mob = knight_attacks[sq] & ~own_pieces & ~enemy_pawn_attacks;
int mob_count = popcount(knight_mob);
score += knight_mobility_table[mob_count];  // 查表，非线性

// Bishop mobility
U64 bishop_mob = sliding_attacks_bishop(sq, occupied) & ~own_pieces;
// 可选：排除被敌方兵攻击的格子
int mob_count = popcount(bishop_mob);
score += bishop_mobility_table[mob_count];

// Rook mobility (半开放线+开放线)
U64 rook_mob = sliding_attacks_rook(sq, occupied) & ~own_pieces;
// 特别关注 rook 在 7th rank 的可达格子
int mob_count = popcount(rook_mob);
score += rook_mobility_table[mob_count];

// Queen mobility (权重更低)
U64 queen_mob = (sliding_attacks_bishop(sq, occupied) |
                 sliding_attacks_rook(sq, occupied)) & ~own_pieces;
int mob_count = popcount(queen_mob);
score += queen_mobility_table[min(mob_count, 27)];
```

**典型 mobility bonus 表（通过 Texel 调优获得）**：

```c
// Knight: 0-8 个可达格
static const int knight_mob_mg[] = {-50, -25, -10, 0, 8, 15, 22, 28, 33};
static const int knight_mob_eg[] = {-40, -20, -5, 5, 12, 18, 25, 30, 35};

// Bishop: 0-13 个可达格
static const int bishop_mob_mg[] = {-40, -20, -8, 0, 8, 14, 20, 25, 29, 33, 36, 38, 39, 40};

// Rook: 0-14 个可达格
static const int rook_mob_mg[] = {-30, -15, -5, 0, 5, 10, 14, 18, 22, 25, 28, 30, 32, 33, 34};
```

**预期收益**：Mobility 是传统评估中最强的单一因子之一，约 **+60-100 Elo**。

### 3.2 King Safety 重新设计

**问题**：当前王安全评估过于简单，仅基于"攻击者到达王附近格子的数量"做线性加权。

**方案**：实现分层王安全模型：

```c
// 1. Pawn Shield（兵盾）
int shield_bonus = 0;
// f2/g2/h2（或 f7/g7/h7）上的兵提供保护
// 兵被推进一步（如 g3）减少保护
// 兵缺失则严重惩罚
for (int f = kf - 1; f <= kf + 1; f++) {
    int closest_pawn_rank = find_closest_pawn_rank(b, side, f);
    if (closest_pawn_rank == -1) {
        shield_bonus -= 30;  // 开放线惩罚
    } else {
        int ideal_rank = (side == WHITE) ? 1 : 6;  // 第二行
        int dist = abs(closest_pawn_rank - ideal_rank);
        shield_bonus -= dist * 10;
    }
}

// 2. King Attackers Count & Weight
int attack_weight = 0;
int attacker_count = 0;
// 每个能攻击到王周围12个格子的敌方棋子都算一个攻击者
U64 king_zone = king_attacks[king_sq] | (1ULL << king_sq) |
                shift_forward(king_attacks[king_sq], side); // 前方扩展

for each enemy piece:
    U64 attacks = get_piece_attacks(b, piece, sq);
    U64 zone_hits = attacks & king_zone;
    int hits = popcount(zone_hits);
    if (hits > 0) {
        attacker_count++;
        attack_weight += piece_attack_weight[pt] * hits;
    }

// 3. 非线性攻击惩罚（关键创新）
// 使用查表：attack_weight -> penalty
// 攻击者越多，惩罚指数增长
static const int king_danger_table[] = {
    0, 0, 5, 15, 30, 55, 90, 140, 200, 280, 380, 500, ...
};
int danger = king_danger_table[min(attack_weight, 63)];

// 4. 虚拟着法惩罚：如果对方有一个"虚拟走法"能直接将杀
U64 weak_squares = king_zone & ~defended_squares;
if (enemy_queen && popcount(weak_squares) >= 2)
    danger += 50;

score -= sign * danger;
```

**预期收益**：显著改善攻击/防守判断，约 **+30-60 Elo**。

### 3.3 兵型评估深化

**当前问题**：

- 叠兵/孤兵惩罚使用硬编码常量，不是 runtime params
- 通路兵评估没有考虑"阻挡"（blockade）因素
- 没有 backward pawn 检测
- 没有 connected passers 的完整实现

**方案**：

```c
// 3.3.1 Backward Pawn（落后兵）检测
// 一个兵是 backward 如果：
// - 它不能被相邻文件的己方兵保护
// - 它前面的格子被敌方兵攻击
// - 它不能安全前进
int is_backward = 1;
if (adjacent_files_have_friendly_pawn_ahead) is_backward = 0;
if (!enemy_pawn_attacks(forward_square)) is_backward = 0;
if (is_backward) score += sign * BACKWARD_PAWN_PENALTY[rank]; // -8 ~ -20

// 3.3.2 通路兵的精细评估
for each passed_pawn:
    int bonus = passed_pawn_base[rank];

    // Blockade 惩罚：如果对方棋子直接阻挡通路兵前进
    int forward_sq = sq + 8 * direction;
    if (piece_on_square(b, forward_sq) != EMPTY && is_enemy(forward_sq))
        bonus = bonus * 2 / 3;  // 被阻挡，降低价值

    // 己方王距离通路兵
    int king_dist = chebyshev_distance(my_king, sq);
    bonus -= king_dist * 3;

    // 对方王距离通路兵
    int opp_king_dist = chebyshev_distance(opp_king, sq);
    bonus += opp_king_dist * 5;

    // 通路兵在开放文件（无己方兵在前面）
    if (!(own_pawns & forward_file_mask))
        bonus += 10;

    // Connected passers（并排通路兵）
    if (adjacent_file_has_passed_pawn)
        bonus += 20;

    // 候选通路兵（Candidate passer）：不是完全通路但有潜力
    // ...

// 3.3.3 Doubled Pawn 区分
// 双兵在开放文件上比在半开放文件上更糟糕
if (files[f] > 1) {
    int is_open = !(enemy_pawns & file_mask);
    int penalty = is_open ? -20 : -10;
    score += sign * penalty * (files[f] - 1);
}

// 3.3.4 Isolated Pawn 区分
// 半开放文件上的孤兵（前面没有敌方兵）更差
if (isolated) {
    int is_half_open = !(enemy_pawns & file_mask);
    int penalty = is_half_open ? -20 : -10;
    score += sign * penalty;
}
```

### 3.4 棋子-格子协同评估

**问题**：当前评估是"逐棋子"独立计算的，缺少棋子之间的协同效应。

**方案**：

```c
// 3.4.1 Rook on Open File 协同
// 两个车在同一开放文件上（"双车叠线"）
if (rooks_on_same_open_file >= 2)
    score += sign * 25;

// 3.4.2 Battery（电池）：后+车或后+象在同一线/对角线上
U64 queen_attacks = get_queen_attacks(b, queen_sq, occupied);
if (queen_attacks & own_rooks) score += sign * 15;
if (queen_attacks & own_bishops) score += sign * 10;

// 3.4.3 Knight Outpost 深化
// 前哨马的价值取决于：
// - 是否有兵保护（已有）
// - 是否在中心（已有）
// - 能否被对方兵驱赶（已有）
// - 该马控制了哪些重要格子
U64 outpost_control = knight_attacks[sq] & center_and_key_squares;
score += sign * popcount(outpost_control) * 5;

// 3.4.4 Bad Bishop 深化
// 不仅看中心兵，看所有己方兵在bishop同色的比例
int total_own_pawns = popcount(own_pawns);
int pawns_on_bishop_color = popcount(own_pawns & same_color_mask);
if (total_own_pawns > 0) {
    int ratio = pawns_on_bishop_color * 100 / total_own_pawns;
    if (ratio > 60) score += sign * (-(ratio - 60));  // 超过60%的兵在同色格
}
```

### 3.5 Space Evaluation（空间评估）

**问题**：完全缺失。

**方案**：

```c
// 计算每方控制的前半区格子数
// 白方：rank 4-7 上被己方控制且不被敌方兵攻击的格子
U64 white_space = 0;
for (int sq = 24; sq < 64; sq++) {  // ranks 3-7
    if (is_controlled_by(b, WHITE, sq) && !is_attacked_by_enemy_pawn(b, BLACK, sq))
        white_space |= (1ULL << sq);
}
int space_bonus = popcount(white_space) * 4;
score += space_bonus;
// 黑方类似...
```

**预期收益**：改善中局局面理解，约 **+10-20 Elo**。

### 3.6 评估缓存（Eval Cache）

**问题**：虽然 `b->eval_score` 字段存在，但由于 `make_move` 是全板拷贝，这个缓存实际上几乎从不被命中（因为每个节点都是新的 Board 副本）。

**方案**：在实现增量 make/unmake 后，评估缓存自然生效。另外增加一个独立的 Eval Hash Table：

```c
typedef struct {
    U64 key;
    int score;
    int phase;
} EvalHashEntry;

static EvalHashEntry eval_hash[1 << 16]; // 64K entries

int evaluate(Board *b) {
    U64 key = b->hash;
    int idx = key & 0xFFFF;
    if (eval_hash[idx].key == key)
        return eval_hash[idx].score;

    int score = evaluate_full(b);
    eval_hash[idx].key = key;
    eval_hash[idx].score = score;
    return score;
}
```

### 3.7 Tempo Bonus（先手奖励）

**问题**：当前没有 tempo bonus。

**方案**：

```c
// 走子方获得小幅先手奖励
int tempo = 10;  // 中局10cp，残局5cp
int tempo_tapered = (tempo * phase + 5 * (24 - phase)) / 24;
if (b->side_to_move == WHITE)
    score += tempo_tapered;
else
    score -= tempo_tapered;
```

**预期收益**：约 **+5-10 Elo**，成本极低。

---

## 4. 走法生成与排序优化

### 4.1 分阶段走法生成（Staged Move Generation）

**问题**：当前在每个节点都一次性生成所有伪合法走法（包括安静的走法），然后排序。但实际上，大多数节点在搜索前几个走法后就会 cutoff。

**方案**：实现分阶段生成：

```c
typedef enum {
    STAGE_TT_MOVE,        // 1. TT 走法
    STAGE_GEN_CAPTURES,   // 2. 生成所有捕获
    STAGE_GOOD_CAPTURES,  // 3. 好捕获（SEE >= 0）
    STAGE_KILLER_1,       // 4. Killer 1
    STAGE_KILLER_2,       // 5. Killer 2
    STAGE_COUNTERMOVE,    // 6. Counter move
    STAGE_GEN_QUIET,      // 7. 生成所有安静走法
    STAGE_QUIET,          // 8. 安静走法（按 history 排序）
    STAGE_BAD_CAPTURES,   // 9. 坏捕获（SEE < 0）
    STAGE_DONE
} MoveGenStage;

typedef struct {
    MoveGenStage stage;
    Move moves[MAX_MOVES];
    int move_count;
    int current;
    Move tt_move;
    Move killer1, killer2;
    Move counter_move;
    Move bad_captures[64];
    int bad_capture_count;
    int bad_capture_current;
} MovePicker;

Move next_move(MovePicker *mp, Board *b, SearchState *s, int depth) {
    switch (mp->stage) {
        case STAGE_TT_MOVE:
            mp->stage = STAGE_GEN_CAPTURES;
            if (mp->tt_move.from != 0 || mp->tt_move.to != 0)
                return mp->tt_move;
            // fall through
        case STAGE_GEN_CAPTURES:
            mp->move_count = generate_captures(b, mp->moves);
            score_captures(mp, b);
            mp->current = 0;
            mp->stage = STAGE_GOOD_CAPTURES;
            // fall through
        case STAGE_GOOD_CAPTURES:
            while (mp->current < mp->move_count) {
                Move best = pick_best(mp->moves, mp->current, mp->move_count);
                mp->current++;
                if (best == mp->tt_move) continue;
                int see_val = see(b, best.from, best.to);
                if (see_val >= 0) return best;
                mp->bad_captures[mp->bad_capture_count++] = best;
            }
            mp->stage = STAGE_KILLER_1;
            // fall through
        // ... 后续阶段
    }
}
```

**收益**：在 70%+ 的节点中，只需要搜索 TT move + 1-2 个捕获就能 cutoff，避免了生成和排序所有走法的开销。约 **+30-50 Elo**。

### 4.2 改进 History Heuristic

**问题**：

- 当前 history 表是 `history[64][64]`（from-to），不区分棋子类型和走子方
- 每层迭代后做 `* 9 / 10` 的衰减，过于粗糙

**方案**：多维 history 表：

```c
// 核心 history：按 (piece_type, to_square, side_to_move) 索引
// 12 种棋子 × 64 格 × 2 方 = 1536 entries
static int history[2][6][64];  // [side][piece_type][to_sq]

// Counter-Move History：按 (prev_piece, prev_to, curr_piece, curr_to) 索引
// 需要 6×64 × 6×64 = 147456 entries
static int counter_move_history[6][64][6][64];

// Follow-Up History：按上上步走法索引
static int followup_history[6][64][6][64];

// 更新时使用 depth^2 作为增量（已有），但添加防溢出机制
void update_history(int side, int piece, int to, int depth, int is_good) {
    int bonus = is_good ? depth * depth : -(depth * depth);
    int *h = &history[side][piece][to];
    // Gravity: 防止 history 值无限增长
    *h += bonus - (*h) * abs(bonus) / 16384;
}
```

**预期收益**：更精准的安静走法排序，约 **+20-35 Elo**。

### 4.3 Counter Move Table 修正

**问题**：当前 countermove 表定义为 `countermove[64][64]`（from-to 索引），每个元素存储一个 `Move`。这意味着表的含义是"当上一步是 from->to 时的应对走法"。但这个设计有两个问题：

1. 不区分走子方和棋子类型
2. 在 negamax 中 ply 的含义交替，countermove 的"上一步"实际上是对方的走法

**方案**：

```c
// 按 (opponent_piece, opponent_to) 索引
// 存储推荐的应对走法
static Move counter_move_table[2][6][64]; // [side][piece][to]

// 在 beta cutoff 时更新
if (!move.capture) {
    Move prev = s->move_stack[ply - 1];
    int prev_piece = piece_on_square(b, prev.from);  // 对方棋子
    counter_move_table[1 - side][prev_piece][prev.to] = move;
}
```

---

## 5. 时间管理策略

### 5.1 当前问题

```c
// 当前代码：
if (elapsed >= time_limit * 0.6 && depth > 1)
    break;
```

这是极其粗糙的时间管理——在时间的 60% 就停止迭代，不考虑：

- 当前深度的完成进度
- 最佳走法的稳定性
- 剩余时间的多少
- 增量时间的影响

### 5.2 完整时间管理方案

基于 CCRL Blitz 2+1 规格（换算后 96s+0.8s/步），设计如下策略：

```c
// ============================================
// 时间分配器（Time Allocator）
// ============================================

typedef struct {
    double base_time;        // 总基础时间（96s）
    double increment;        // 每步增量（0.8s）
    double time_remaining;   // 当前剩余时间
    double optimal_time;     // 本步最优用时
    double max_time;         // 本步最大用时
    int moves_to_go;         // 到下一个时间控制的步数（0=突然死亡）
    int move_number;         // 当前步数
    double start_time;       // 搜索开始时间
} TimeManager;

void init_time_manager(TimeManager *tm, double time_remaining, double increment,
                       int move_number, int moves_to_go) {
    tm->time_remaining = time_remaining;
    tm->increment = increment;
    tm->move_number = move_number;
    tm->moves_to_go = moves_to_go;
    tm->start_time = get_time();

    // 估计剩余步数
    int estimated_moves_left;
    if (moves_to_go > 0) {
        estimated_moves_left = moves_to_go;
    } else {
        // 基于经验公式：平均一盘棋约 80 步
        estimated_moves_left = max(80 - move_number, 20);
        estimated_moves_left = max(estimated_moves_left, 15);
    }

    // 基础时间分配
    double base_alloc = time_remaining / estimated_moves_left + increment;

    // 安全系数：永远保留至少 50ms 的缓冲
    double safety_margin = 0.05;
    base_alloc = min(base_alloc, (time_remaining - safety_margin) / max(estimated_moves_left, 1));

    // 最优用时
    tm->optimal_time = base_alloc;

    // 最大用时（允许在困难位置多花时间）
    tm->max_time = min(base_alloc * 5.0, time_remaining * 0.3);

    // 残局加速：步数多时减少单步用时
    if (move_number > 60) {
        tm->optimal_time *= 0.8;
    }

    // 开局阶段（前10步）：减少用时，因为 book moves 多
    if (move_number <= 10) {
        tm->optimal_time *= 0.7;
    }

    // 极低时间保护
    if (time_remaining < 1.0) {
        tm->optimal_time = min(tm->optimal_time, 0.05);  // 50ms
        tm->max_time = min(tm->max_time, 0.1);
    }
}

// 搜索中动态调整
double get_search_time_limit(TimeManager *tm, int depth, int best_move_stable,
                             int score_stable, double best_move_change) {
    double elapsed = get_time() - tm->start_time;

    // 基础：不超过 optimal_time
    double limit = tm->optimal_time;

    // 最佳走法稳定（连续多层未变）：可以减少用时
    if (best_move_stable >= 3) {
        limit *= 0.6;
    }

    // 最佳走法刚改变：增加用时
    if (best_move_change) {
        limit = min(limit * 2.0, tm->max_time);
    }

    // 分数波动大（局面复杂）：增加用时
    if (!score_stable) {
        limit = min(limit * 1.5, tm->max_time);
    }

    // 分数很高/很低（明显胜/负）：减少用时
    // 通过外部传入 best_score 判断

    // 永远不能超过 max_time
    limit = min(limit, tm->max_time);

    // 永远不能超过剩余时间 - 安全余量
    limit = min(limit, tm->time_remaining - elapsed - 0.05);

    return max(limit, 0.001);  // 至少 1ms
}
```

### 5.3 深度迭代中的时间检查

```c
for (depth = 1; depth <= max_depth; depth++) {
    // 在每个深度开始前检查时间
    double elapsed = get_time() - s.start_time;

    // 如果已经用了 optimal_time 的 50%，且当前深度尚未完成
    // 则可能无法完成当前深度，考虑提前退出
    if (elapsed >= tm.optimal_time * 0.5 && depth > 1) {
        // 估计当前深度完成所需时间
        double prev_depth_time = depth_times[depth - 1];
        double estimated_total = elapsed + prev_depth_time * 0.5;
        if (estimated_total > tm.optimal_time) {
            break;
        }
    }

    // 搜索当前深度...

    // 搜索完成后，更新决策
    double depth_elapsed = get_time() - s.start_time - depth_start_time;
    depth_times[depth] = depth_elapsed;

    // 更新 best_move 稳定性计数
    if (current_best == prev_best) {
        stable_count++;
    } else {
        stable_count = 0;
        best_move_changed = 1;
    }
}
```

**预期收益**：科学的时间管理可以避免在简单局面浪费时间和在复杂局面用时不足，约 **+20-40 Elo**。

---

## 6. 置换表与内存架构

### 6.1 当前问题

- TT 大小固定为 `1 << 20`（1M 条目 × ~16 bytes = ~16MB），偏小
- 替换策略过于简单：同 key 深度优先，不同 key age 优先
- 没有两个 bucket 的设计

### 6.2 双 Bucket TT

```c
typedef struct {
    U64 key;
    Move best_move;
    int16_t score;
    int8_t depth;
    uint8_t flag;        // EXACT=0, LOWER=1, UPPER=2
    uint8_t generation;
    uint8_t age;         // 用于替换
} TT_Entry;

typedef struct {
    TT_Entry entries[2];  // 两个 bucket
} TT_Cluster;

// TT 大小增加到 128MB（8M clusters）
static TT_Cluster *tt;
static int tt_cluster_count = 1 << 23;  // ~8M clusters

// 替换策略：
void tt_store(U64 key, int depth, int score, int flag, Move best_move, int ply) {
    int idx = (int)(key & (tt_cluster_count - 1));
    TT_Cluster *cluster = &tt[idx];

    TT_Entry *replace = NULL;

    // 优先替换空位
    if (cluster->entries[0].key == 0) replace = &cluster->entries[0];
    else if (cluster->entries[1].key == 0) replace = &cluster->entries[1];

    if (!replace) {
        // 两个都有内容：替换较旧的或较浅的
        TT_Entry *e0 = &cluster->entries[0];
        TT_Entry *e1 = &cluster->entries[1];

        // 同 key 优先更新
        if (e0->key == key) replace = e0;
        else if (e1->key == key) replace = e1;

        if (!replace) {
            // 替换条件：generation 更旧 或 (同 generation 但深度更浅)
            int score0 = (current_gen - e0->generation) * 256 - e0->depth;
            int score1 = (current_gen - e1->generation) * 256 - e1->depth;
            replace = (score0 >= score1) ? e0 : e1;
        }
    }

    // 不替换更深的同 key 条目（除非当前更深）
    if (replace->key == key && replace->depth > depth && flag != EXACT)
        return;

    replace->key = key;
    replace->depth = depth;
    replace->score = adjust_mate_score(score, ply);
    replace->flag = flag;
    replace->best_move = best_move;
    replace->generation = current_gen;
}
```

### 6.3 TT 大小自适应

```c
// 根据可用内存调整 TT 大小
// 在 7940H 笔记本上（16GB RAM），分配 128-256MB 给 TT
void init_tt(int hash_mb) {
    int clusters = (hash_mb * 1024 * 1024) / sizeof(TT_Cluster);
    // 取最近的 2 的幂
    int pow2 = 1;
    while (pow2 * 2 <= clusters) pow2 *= 2;
    tt_cluster_count = pow2;
    tt = (TT_Cluster *)calloc(tt_cluster_count, sizeof(TT_Cluster));
}
```

**预期收益**：更大的 TT 意味着更多的 cutoff，约 **+15-30 Elo**（128MB vs 16MB）。

### 6.4 PV (Principal Variation) 提取

```c
// 从 TT 中提取完整 PV 用于 UCI 输出
void extract_pv(Board *b, Move *pv, int *pv_length, int max_depth) {
    *pv_length = 0;
    for (int i = 0; i < max_depth; i++) {
        U64 key = b->hash;
        int idx = (int)(key & (tt_cluster_count - 1));
        TT_Cluster *cluster = &tt[idx];

        Move tt_move = {0};
        for (int j = 0; j < 2; j++) {
            if (cluster->entries[j].key == key) {
                tt_move = cluster->entries[j].best_move;
                break;
            }
        }

        if (tt_move.from == 0 && tt_move.to == 0) break;

        // 验证走法合法性
        if (!is_legal_move(b, &tt_move)) break;

        pv[(*pv_length)++] = tt_move;
        make_move(b, &tt_move);
    }
    // Unmake all moves...
}
```

---

## 7. 多线程优化

### 7.1 当前问题

- Lazy SMP 中所有线程共享同一个 TT，但没有原子操作保护
- 所有线程搜索相同深度
- 没有 Numa 感知
- 7940H 是 8 核（16 线程），但实际物理核为 8 个

### 7.2 改进 Lazy SMP

```c
// 7.2.1 原子化 TT 访问
// 使用 key 的上32位做 lock-free 验证
typedef struct {
    volatile uint32_t key32;   // key 的高32位作为签名
    volatile int16_t score;
    volatile int8_t depth;
    volatile uint8_t flag;
    Move best_move;
    volatile uint8_t generation;
} AtomicTTEntry;

// 写入时先写其他字段，最后写 key32（确保可见性顺序）
void tt_store_atomic(AtomicTTEntry *e, ...) {
    e->score = score;
    e->depth = depth;
    e->flag = flag;
    e->best_move = best_move;
    e->generation = gen;
    __atomic_store_n(&e->key32, key >> 32, __ATOMIC_RELEASE);
}

// 读取时先读 key32
int tt_probe_atomic(AtomicTTEntry *e, U64 key, ...) {
    uint32_t stored_key = __atomic_load_n(&e->key32, __ATOMIC_ACQUIRE);
    if (stored_key != (key >> 32)) return MISS;
    // 读取其他字段...
}
```

### 7.2.2 线程差异化

```c
// 不同线程搜索不同深度
for (int i = 0; i < num_threads; i++) {
    workers[i].depth_offset = i % 2;  // 偶数线程搜 depth，奇数搜 depth+1
    workers[i].start_depth = 1 + (i % 2);  // 交错起始深度
}
```

### 7.2.3 线程数优化

7940H 有 8 个物理核心，推荐：

- **搜索线程数 = 物理核数 = 8**（不使用超线程，避免缓存争用）
- 或 **搜索线程数 = 7**（留一个核给操作系统）

```c
int optimal_threads = min(physical_cores, 8);
// 在 7940H 上，8 线程 SMP 约比单线程提升 +80-120 Elo
```

### 7.2.4 停止信号协调

```c
// 使用 volatile + memory barrier 实现高效的停止信号
static volatile int smp_stop;

void smp_signal_stop() {
    __atomic_store_n(&smp_stop, 1, __ATOMIC_RELEASE);
}

int smp_should_stop() {
    return __atomic_load_n(&smp_stop, __ATOMIC_RELAXED);
}

// 每个线程在节点计数检查时查看停止信号
if ((s->nodes & 1023) == 0) {
    if (smp_should_stop() || elapsed >= time_limit) {
        s->aborted = 1;
        return 0;
    }
}
```

**预期收益**：在 8 核上，优化后的 SMP 约 **+80-120 Elo**（对比单线程）。

---

## 8. 残局知识补充

### 8.1 Bitbase 残局

**问题**：当前完全没有残局知识库。

**方案**：实现关键残局 bitbase（或 tablebase probe）：

```c
// 8.1.1 KPK Bitbase（王兵对王）
// 预计算表：约 2 * 64 * 64 * 24 = ~192KB
// 索引：[side_to_move][wk_sq][bk_sq][pawn_sq_relative]
int probe_kpk(Board *b) {
    // 查找预计算的 bitbase
    // 返回 +WIN / -WIN / DRAW
}

// 8.1.2 KBNK Bitbase（王象马对王）
// 约 2 * 64 * 64 * 64 * 64 = ~32MB（可通过压缩减小）

// 8.1.3 简单残局规则（不需要 bitbase）
int eval_kpk_rules(Board *b, int strong_side) {
    int pawn_sq = get_pawn_square(b, strong_side);
    int wk_sq = get_king_square(b, strong_side);
    int bk_sq = get_king_square(b, 1 - strong_side);

    // Rule 1: 如果对方王能到达兵前面的升变格
    // Rule 2: 如果己方王在兵前面
    // Rule 3: Opposition 判断
    // Rule 4: 关键格（key squares）控制
}
```

### 8.2 残局评估增强

```c
// 8.2.1 Opposite Colored Bishops（异色格象）
// 当双方各有象且在不同颜色格上时，和棋倾向极大
if (phase <= 8) {  // 残局
    int wb_sq = get_bishop_square(b, WHITE);
    int bb_sq = get_bishop_square(b, BLACK);
    if (wb_sq >= 0 && bb_sq >= 0) {
        int wb_color = ((wb_sq / 8) + (wb_sq % 8)) % 2;
        int bb_color = ((bb_sq / 8) + (bb_sq % 8)) % 2;
        if (wb_color != bb_color) {
            // 异色格象：大幅缩小评估（向0拉近）
            score = score * 50 / 100;  // 评估减半
        }
    }
}

// 8.2.2 Rook + Pawn vs Rook 残局知识
if (is_rook_pawn_vs_rook(b)) {
    int pawn_file = file_of(pawn_sq);
    int pawn_rank = rank_of(pawn_sq);
    int defending_king_sq = get_king_square(b, defending_side);

    // Philidor Position: 防守方王在升变行，车在第三行
    // Lucena Position: 进攻方王在兵前面，可以搭桥
    // 这些是赢/和的关键判断
}

// 8.2.3 不可赢残局检测
int is_unwinnable(Board *b, int side) {
    int own_pieces = count_all_pieces(b, side);
    if (own_pieces == 1) return 1;  // 只有王
    if (own_pieces == 2) {
        // 王+马 或 王+象 vs 王：不可赢
        if (b->pieces[side][KNIGHT] || b->pieces[side][BISHOP])
            return 1;
    }
    // 王+双马 vs 王：理论不可强制将杀
    if (own_pieces == 3 && count_bits(b->pieces[side][KNIGHT]) == 2 &&
        count_all_pieces(b, 1-side) == 1)
        return 1;
    return 0;
}
```

### 8.3 Scaling（残局缩放）

```c
// 根据残局类型调整评估分数
int scale_endgame(Board *b, int score) {
    int strong_side = (score > 0) ? WHITE : BLACK;
    int weak_side = 1 - strong_side;

    // OCB 缩放
    if (has_opposite_colored_bishops(b)) {
        int other_pieces = count_non_pawn_non_bishop(b);
        if (other_pieces == 0) {
            // 纯异色格象残局
            int scale = 32;  // 32/128 = 25%
            score = score * scale / 128;
        } else {
            int scale = 64 + other_pieces * 8;
            score = score * min(scale, 128) / 128;
        }
    }

    // 如果优势方没有足够的赢棋材料
    if (is_unwinnable(b, strong_side)) {
        score = 0;
    }

    return score;
}
```

**预期收益**：避免在必和残局中浪费时间，在必赢残局中快速转化优势，约 **+15-25 Elo**。

---

## 9. 参数调优方法论

### 9.1 Texel 调优

**原理**：利用大量真实对局的 QUIET 位置（非战术位置），通过梯度下降优化评估参数，使得评估分数与实际对局结果之间的误差最小化。

```c
// 损失函数：均方误差
// E = sum( (result - sigmoid(eval / K))^2 )
// 其中 result ∈ {0, 0.5, 1}，K 是缩放常数

double texel_loss(double *params, int n_params, Position *positions, int n_pos) {
    double loss = 0;
    for (int i = 0; i < n_pos; i++) {
        double eval = evaluate_with_params(&positions[i], params);
        double predicted = 1.0 / (1.0 + pow(10.0, -eval / 400.0));
        double error = positions[i].result - predicted;
        loss += error * error;
    }
    return loss / n_pos;
}

// 优化：局部搜索（Local Search）或 CMA-ES
void texel_tune(double *params, int n_params, Position *positions, int n_pos) {
    double K = find_optimal_K(positions, n_pos);

    for (int iter = 0; iter < 1000; iter++) {
        for (int p = 0; p < n_params; p++) {
            double best_val = params[p];
            double best_loss = texel_loss(params, n_params, positions, n_pos);

            // 尝试增大和减小
            for (int delta : {-1, 1, -2, 2, -5, 5, -10, 10}) {
                params[p] = best_val + delta;
                double loss = texel_loss(params, n_params, positions, n_pos);
                if (loss < best_loss) {
                    best_loss = loss;
                    best_val = params[p];
                }
            }
            params[p] = best_val;
        }
    }
}
```

**需要调优的参数**（按优先级）：

| 优先级 | 参数类别         | 参数量       | 说明                 |
| ------ | ---------------- | ------------ | -------------------- |
| 1      | Piece Values     | 5            | P/N/B/R/Q 价值       |
| 2      | PST Tables       | 6×64×2 = 768 | 棋子-格子表          |
| 3      | Mobility 权重    | ~30          | 各棋子 mobility 系数 |
| 4      | King Safety 参数 | ~20          | 兵盾/攻击权重        |
| 5      | 兵型参数         | ~15          | 叠兵/孤兵/通路兵     |
| 6      | Tempo            | 1            | 先手奖励             |

**数据需求**：至少 100 万个 QUIET 位置（从引擎自身的 self-play 对局中提取，排除战术位置）。

### 9.2 SPSA 搜索参数调优

对于搜索参数（LMR 公式、Null Move reduction、Futility margin 等），使用 SPSA（Simultaneous Perturbation Stochastic Approximation）：

```c
void spsa_tune(SearchParam *params, int n_params) {
    double a = 0.5;  // 学习率
    double c = 2.0;  // 扰动幅度
    double A = 100;  // 稳定化常数
    double alpha = 0.602;
    double gamma = 0.101;

    for (int k = 1; k <= 10000; k++) {
        double ak = a / pow(k + A, alpha);
        double ck = c / pow(k, gamma);

        // 随机扰动
        double delta[n_params];
        for (int i = 0; i < n_params; i++)
            delta[i] = (rand() % 2 == 0) ? 1 : -1;

        // 两组参数
        SearchParam plus[n_params], minus[n_params];
        for (int i = 0; i < n_params; i++) {
            plus[i] = params[i] + ck * delta[i];
            minus[i] = params[i] - ck * delta[i];
        }

        // 对弈测试
        double elo_plus = play_match(plus, baseline_engine);
        double elo_minus = play_match(minus, baseline_engine);

        // 梯度估计
        double gradient = (elo_plus - elo_minus) / (2 * ck);

        // 更新
        for (int i = 0; i < n_params; i++) {
            params[i] += ak * gradient / delta[i];
        }
    }
}
```

---

## 10. 实施路线图与预期收益

### Phase 1：基础设施改造（预计 +150-200 Elo）

| #   | 任务                        | 预估工作量 | 预期 Elo 提升 |
| --- | --------------------------- | ---------- | ------------- |
| 1.1 | Mailbox 辅助数组            | 2-3天      | +15-25        |
| 1.2 | 增量 Zobrist 哈希           | 3-4天      | +20-30        |
| 1.3 | 真正的 Unmake               | 5-7天      | +15-20        |
| 1.4 | 分阶段走法生成              | 5-7天      | +30-50        |
| 1.5 | TT 扩大到 128MB + 双 bucket | 2-3天      | +15-30        |
| 1.6 | 修复 SEE 实现               | 2天        | +10-15        |

**Phase 1 合计**：约 3-4 周，预估总提升 **+150-200 Elo**

### Phase 2：搜索增强（预计 +120-180 Elo）

| #   | 任务                     | 预估工作量 | 预期 Elo 提升 |
| --- | ------------------------ | ---------- | ------------- |
| 2.1 | 启用并改进 Razoring      | 1-2天      | +15-25        |
| 2.2 | 改进 LMR 公式 + 预计算表 | 3-4天      | +30-50        |
| 2.3 | 将军延伸                 | 1-2天      | +20-35        |
| 2.4 | ProbCut                  | 2-3天      | +15-25        |
| 2.5 | 改进 Null Move           | 1-2天      | +10-15        |
| 2.6 | 改进 Aspiration Window   | 2天        | +10-20        |
| 2.7 | Singular Extension       | 3-5天      | +20-40        |

**Phase 2 合计**：约 2-3 周，预估总提升 **+120-180 Elo**

### Phase 3：评估函数重构（预计 +100-180 Elo）

| #   | 任务               | 预估工作量 | 预期 Elo 提升 |
| --- | ------------------ | ---------- | ------------- |
| 3.1 | 真正的 Mobility    | 3-4天      | +60-100       |
| 3.2 | King Safety 重设计 | 3-4天      | +30-60        |
| 3.3 | 兵型深化           | 2-3天      | +15-25        |
| 3.4 | Tempo Bonus        | 0.5天      | +5-10         |
| 3.5 | 残局 Scaling       | 2天        | +10-15        |
| 3.6 | Eval Cache         | 1天        | +5-10         |

**Phase 3 合计**：约 2-3 周，预估总提升 **+100-180 Elo**

### Phase 4：时间管理与多线程（预计 +50-80 Elo）

| #   | 任务                     | 预估工作量 | 预期 Elo 提升 |
| --- | ------------------------ | ---------- | ------------- |
| 4.1 | 完整时间管理器           | 3-4天      | +20-40        |
| 4.2 | 改进 Lazy SMP + 原子操作 | 3-4天      | +20-30        |
| 4.3 | 线程数优化               | 0.5天      | +5-10         |

**Phase 4 合计**：约 1-2 周，预估总提升 **+50-80 Elo**

### Phase 5：精调与残局（预计 +30-60 Elo）

| #   | 任务        | 预估工作量          | 预期 Elo 提升 |
| --- | ----------- | ------------------- | ------------- |
| 5.1 | Texel 调优  | 5-7天（含数据收集） | +20-40        |
| 5.2 | KPK Bitbase | 2-3天               | +5-10         |
| 5.3 | 残局规则库  | 3-4天               | +10-20        |

**Phase 5 合计**：约 2 周，预估总提升 **+30-60 Elo**

### 总预估

| 指标            | 当前状态  | Phase 1-5 后  |
| --------------- | --------- | ------------- |
| 预估 CCRL Blitz | 1800-2100 | **2400-2800** |
| NPS (典型中局)  | ~300K     | ~1.5-2.5M     |
| 搜索深度 (2s)   | ~9 ply    | ~14-17 ply    |
| TT 命中率       | ~20%      | ~40-50%       |

---

## 附录 A：快速收益清单（Quick Wins）

以下改动可在 **1天内** 完成且效果显著：

1. **Tempo Bonus**：+5-10 Elo，10 行代码
2. **启用 Razoring**：+15-25 Elo，取消 `return 0` + 完善条件
3. **TT 大小从 16MB → 128MB**：+10-20 Elo，改一行常量
4. **Null Move adaptive reduction**：+10-15 Elo，修改 reduction 计算公式
5. **Aspiration Window 渐进扩展**：+10-15 Elo，修改窗口逻辑
6. **搜索线程数设为物理核数（8）**：+10-20 Elo，改配置
7. **时间管理 60% → 基于剩余步数的动态分配**：+15-30 Elo

## 附录 B：关键数据结构改造清单

```c
// 改造后的 Board 结构体（推荐）
typedef struct {
    U64 pieces[2][6];         // bitboards（已有）
    int mailbox[64];           // 新增：快速棋子查询
    U64 hash;                  // 新增：增量 Zobrist 哈希
    U64 pawn_hash;             // 新增：兵哈希（用于 Pawn Hash）
    int side_to_move;          // 已有
    int castling_rights;       // 已有
    int en_passant;            // 已有
    int halfmove_clock;        // 已有
    int fullmove_number;       // 已有
    int eval_score;            // 已有：评估缓存
    int phase;                 // 新增：缓存 phase 值
    int king_sq[2];            // 新增：缓存王位置
    int npm[2];                // 新增：缓存 non-pawn material
} Board;

// UndoInfo 结构体
typedef struct {
    int captured_piece;
    int castling_rights;
    int en_passant;
    int halfmove_clock;
    int fullmove_number;
    U64 hash;
    U64 pawn_hash;
    int eval_score;
    int phase;
    int king_sq[2];
    int npm[2];
} UndoInfo;
```

## 附录 C：7940H 硬件适配建议

| 资源     | 规格              | 引擎利用建议                               |
| -------- | ----------------- | ------------------------------------------ |
| CPU 核心 | 8C/16T, Zen 4     | 搜索线程 ≤ 8（物理核），避免超线程争用     |
| L3 Cache | 16MB              | TT 热数据约 8MB 以内效果最佳               |
| 内存     | DDR5-5600         | TT 分配 128-256MB，pawn hash 32MB          |
| SIMD     | AVX-512           | 如果实现 NNUE，可利用 AVX-512 加速矩阵运算 |
| 单核性能 | ~2500 Single-Core | 搜索优化比多线程优化更有价值               |

---

**总结**：该引擎拥有正确的架构骨架（Magic Bitboard、Negamax/PVS、TT），但在基础性能（make/unmake、hash）和现代搜索技术（分阶段生成、高级剪枝）方面存在显著短板。按照上述路线图实施改造后，预估可从 CCRL 1800-2100 提升至 **2400-2800** 区间。其中 **Phase 1（基础设施改造）** 是绝对优先项，因为所有后续优化都建立在高效的 make/unmake 和增量哈希之上。
