# Hellcopter 引擎架构参考文档

> **版本**: v1.7.2 (ENGINE_VERSION 20260511)
> **更新日期**: 2026-05-28
> **目的**: 供 AI 协作者和开发者快速理解项目核心架构、文件职责、技术方案与已知问题

---

## 一、项目架构总览

### 1.1 编译流水线

```
configs/v1.7.2.json  →  build_engine.py  →  engine_params.h  →  engine_core.c + uci_main.c
       (参数源)           (配置→头文件)        (编译时参数)           (C源码)
                                                                         ↓
                                                                    gcc/cl 编译
                                                                         ↓
                                                              engine_core.dll / Hellcopter.exe
```

- **参数流向**: JSON 配置 → build_engine.py 读取 → 生成 engine_params.h → 编译进 C 引擎
- **关键点**: engine_params.h 是自动生成的文件（头部标注 "DO NOT EDIT MANUALLY"），所有参数修改必须通过 JSON 配置完成
- **构建命令**: `python build_engine.py --config v1.7.2` 使用指定配置编译

### 1.2 运行时数据流

```
用户/GUI/UCI平台
       ↓
uci_engine.py (UCI协议解析 + 时间管理 + 开局库)
       ↓
engine_wrapper.py (ctypes 桥接 + 参数传递 + 版本校验)
       ↓
engine_core.dll (C搜索引擎核心)
       ↓
find_best_move_c() / find_best_move_smp()
       ↓
negamax() → quiescence_search() → evaluate()
```

### 1.3 核心性能指标

| 指标 | 当前值 |
|------|--------|
| NPS | ~2,000,000 节点/秒 |
| 搜索深度 | 12秒可达深度 10+ |
| 预估 Elo | ~1600-2300（不同评估来源差异较大） |
| 代码规模 | engine_core.c ~6674 行 |

---

## 二、核心文件索引

### 2.1 engine_core.c — 搜索引擎核心（~6674 行）

这是引擎的唯一 C 源文件，包含所有搜索、评估、走法生成逻辑。

| 功能模块 | 行号范围 | 关键函数/逻辑 |
|----------|----------|---------------|
| Zobrist 哈希初始化 | L421-431 | `init_zobrist()` — 使用 LCG 生成随机数 |
| Magic Bitboard 初始化 | L259-400 | `init_magics()`, `init_knight_attacks()`, `init_king_attacks()` |
| LMR 表初始化 | L120-128 | `init_lmr_table()` — 对数衰减表 |
| Blunder Memory | L151-155 | 线性数组，最多 10000 条 |
| 棋子价值 | L1290-1303 | `get_piece_value()` |
| 走法检测 | L1342-1357 | `move_gives_check()`, `is_killer_move()` |
| LMR 判断与计算 | L1379-1449 | `should_apply_lmr()`, `calculate_reduction()` |
| Futility Pruning | L1452-1515 | `should_apply_futility_pruning()` — 每次调用 evaluate() |
| **Razoring** | **L1517-1521** | `should_apply_razoring()` — **返回硬编码 0（因性能退化主动禁用）** |
| 棋盘操作 | L1539-1735 | `count_bits()`, `lsb_index()`, `board_from_fen()`, `board_to_fen()` |
| 攻击检测 | L1830-1876 | `is_square_attacked()`, `is_check()` |
| 走法生成 | L2286-2306 | `generate_legal_moves()` |
| Make/Unmake Move | L2320-2705 | `make_move()`, `unmake_move()` — 增量更新 hash 和 mailbox |
| 兵评估 | L2721-2900 | `evaluate_pawns()` — 叠兵/孤兵/通路兵/兵盾 |
| **评估函数入口** | **L2906-3884** | `evaluate()` — 21 项评估特征，Tapered Eval |
| **phase_weight 计算** | **L2917** | `phase_weight = phase * 256 / 24` — 0=残局, 256=中局 |
| **机动性评估** | **L3005, 3017, 3030, 3043** | **mg/eg 权重反转 BUG（4 处）** |
| **王安全** | **L3170-3273** | 攻击单位表 + 兵盾惩罚 + **阶段缩放条件反转 BUG（L3267）** |
| **残局王活跃度** | **L3769** | **ENDGAME_PHASE_THRESHOLD 误用 BUG** |
| **先手分** | **L3873** | **mg/eg 权重反转 BUG** |
| 走法排序 | L3933-3952 | `mvv_lva()`, `sort_moves()` — 全量 qsort |
| 置换表 | L3966-4083 | `tt_init()`, `tt_probe()`, `tt_store()` — 4-way cluster |
| SEE | L4085-4310 | `see()` — 完整攻击链模拟 |
| 静止搜索 | L4710-4817 | `quiescence_search()` — SEE + Delta + 将军扩展 |
| **Negamax 搜索** | **L4819-5600** | 主搜索函数 |
| **Check Extension** | **L4882-4888** | **被注释掉（因搜索爆炸）** |
| **Endgame Depth Bonus** | **L4896-4901** | **被注释掉** |
| **Razoring 调用** | **L4922-4954** | 已有完整逻辑，因 should_apply_razoring 返回 0 不执行 |
| **Futility 调用** | **L5127** | 每个走法调用 should_apply_futility_pruning |
| **Followup 更新** | **L5238** | `s->followup[prev_own_move.from][prev_own_move.to]` — 缺少颜色维度 |
| 时间管理 | L5605-5652 | `init_time_manager()` — 计算 optimal_time/max_time |
| **主搜索入口** | **L5658-6137** | `find_best_move_c()` — **L5716 每次搜索 calloc TT** |
| Lazy SMP | L6277-6450 | `smp_worker_search()`, `smp_thread_func()` |

### 2.2 engine_core.h — 数据结构定义（~199 行）

| 结构体 | 行号 | 说明 |
|--------|------|------|
| `Board` | L37-50 | 棋盘状态：pieces[2][7] bitboard + mailbox[64] + hash + pawn_hash + phase + npm[2] |
| `UndoInfo` | L52-69 | 撤销信息：captured_piece, castling_rights, hash, eval_score 等 |
| `TimeManager` | L71-85 | 时间管理：optimal_time, max_time, stable_count, panic_flag |
| `TT_Entry` | L87-95 | 置换表条目：key, depth, score, flag, best_move, generation |
| `TT_Cluster` | L97-100 | 4-way 置换表簇 |
| `SearchState` | L102-131 | 搜索状态：killers[64][2], history[64][64], **followup[64][64]**（缺颜色维度）, move_stack, 统计信息 |

### 2.3 engine_params.h — 编译时参数（~258 行，自动生成）

| 区段 | 行号范围 | 内容 |
|------|----------|------|
| SECTION 1 | 棋子价值 | PAWN_VALUE=100, KNIGHT_VALUE=320, BISHOP_VALUE=340, ROOK_VALUE=480, QUEEN_VALUE=900 |
| SECTION 2 | PST 表 | 12 个 static const int[64] 数组（mg/eg × 6 种棋子） |
| SECTION 3 | 评估权重 | BISHOP_PAIR_BONUS, DOUBLED_PAWN_PENALTY, passed_pawn_bonus[8] 等 |
| SECTION 4 | 搜索参数 | NULL_MOVE_REDUCTION=2, LMR_ENABLED=1, FUTILITY_MARGIN_BASE=150, RAZORING_MARGIN=300 |
| SECTION 5 | 常量 | MATE_SCORE=900000, DELTA=200, ENDGAME_PHASE_THRESHOLD=1500 |
| SECTION 6 | 多线程 | THREADING_ENABLED=1, NUM_THREADS=4 |

**重要**: 此文件由 build_engine.py 从 JSON 配置自动生成。当前生成自 v1.7.0 配置（PST 全零），v1.7.2 配置包含完整 PST 数据。

### 2.4 build_engine.py — 构建系统（~724 行）

| 功能 | 行号 | 说明 |
|------|------|------|
| 参数头文件生成 | L83-246 | `_generate_params_header()` — JSON → engine_params.h |
| 增量编译判断 | L269-303 | `_needs_rebuild()` — 时间戳比较 |
| 共享库编译 | L306+ | `build()` — 编译为 .dll/.so/.dylib |
| 可执行文件编译 | L496+ | `build_exe()` — 编译为 Hellcopter.exe |
| 编译优化选项 | — | `-O3 -march=native -fomit-frame-pointer -DNDEBUG` |

### 2.5 engine_wrapper.py — Python-C 桥接层（~432 行）

| 功能 | 行号 | 说明 |
|------|------|------|
| 数据结构映射 | L10-32 | Move, LMR_Stats, Pruning_Stats ctypes 结构体 |
| 库加载与版本校验 | L69+ | `_load_library()` — 期望版本 20260511 |
| 搜索接口 | L198-276 | `search()`, `search_with_score()`, `evaluate_fen()` |
| 热重载 | L311+ | `reload_library()` — Windows FreeLibrary + 重新加载 |
| 错着记忆 | — | `add_blunder_entry()`, `load_blunder_memory_from_file()` |

### 2.6 uci_engine.py — UCI 协议适配器（~317 行）

| 功能 | 行号 | 说明 |
|------|------|------|
| 开局库 | L12-42 | BookManager — 从 dist/book.bin (Polyglot) 加载 |
| UCI 命令处理 | L45+ | uci/isready/ucinewgame/position/go/stop/quit |
| 时间管理 | L175-222 | `_compute_time()` — 按阶段分配搜索时间 |
| 异步搜索 | L224+ | `_search_worker()` — 独立线程调用引擎 |

### 2.7 config.py — 配置解析（~63 行）

- `resolve_config()`: 递归解析 base_version 继承链
- `load_and_resolve_config()`: 加载并解析完整配置

### 2.8 configs/ — 参数配置文件族

| 版本 | 关键变化 |
|------|---------|
| v1.7.0 | PST 全零（占位），基础参数 |
| v1.7.2 | **完整 PST 数据**，endgame_depth_bonus=3，castle_short/long_bonus |

配置继承机制：子版本通过 `base_version` 字段继承父版本参数，仅覆盖差异项。

### 2.9 测试与调优工具

| 文件 | 用途 |
|------|------|
| perft_test.py | 走法生成正确性验证 |
| reproducibility_test.py | 搜索可复现性验证 |
| run_match.py | 引擎对弈测试 |
| random_selfplay_test.py | 随机自对弈测试 |
| multi_opponent_test.py | 多对手测试 |
| nps_benchmark.py | NPS 基准测试 |
| spsa_tuner.py | SPSA 参数调优 |
| run_texel_tuning.py | Texel Tuning 调优 |
| velvet_analyze.py | Velvet 对局分析 |
| auto_ladder.py / auto_tune.py | 自动天梯/调优 |

---

## 三、搜索技术方案

### 3.1 搜索框架

```
find_best_move_c()
  └── 迭代加深循环 (depth = 1, 2, 3, ...)
        └── Aspiration Window (初始 ±25, 逐步加倍)
              └── negamax(depth, alpha, beta)
                    ├── TT 探测 (tt_probe)
                    ├── IID (无 TT 着法时 depth-2 搜索)
                    ├── Null Move Pruning (R=2+depth/6)
                    ├── Razoring (已禁用 — should_apply_razoring 返回 0)
                    ├── 走法生成 + 排序
                    ├── PVS (首走法全窗口, 后续零窗口)
                    │     ├── LMR (对数衰减 + 多条件调整)
                    │     ├── Futility Pruning (depth<=5, 非将军/捕获/升变)
                    │     └── 递归 negamax(depth-1)
                    └── TT 存储 (tt_store)
```

### 3.2 剪枝技术状态

| 技术 | 状态 | 位置 | 说明 |
|------|------|------|------|
| Null Move Pruning | ✅ 启用 | L5060-5123 | R=2+depth/6，含验证搜索 |
| LMR | ✅ 启用 | L1379-1449 | 对数表 + PV/将军/捕获/历史调整 |
| Futility Pruning | ✅ 启用 | L1452-1515, L5127 | depth<=5, margin=base*depth |
| RFP | ✅ 启用 | negamax 中 | Reverse Futility, depth<=8 |
| Delta Pruning | ✅ 启用 | quiescence_search | stand_pat + DELTA < alpha |
| SEE 裁剪 | ✅ 启用 | quiescence_search | 负分捕获跳过 |
| **Razoring** | **🟡 主动禁用** | **L1517-1521** | **因评估函数 BUG 导致性能退化而禁用。退化根因：评估系统性错误使 Razoring 剪枝决策不可靠 + is_endgame 永远为真导致 margin 过大。修复评估 BUG 后应重新测试** |
| **Check Extension** | **🟡 被注释** | **L4882-4888** | **因搜索爆炸被注释，非 BUG** |
| **Endgame Depth Bonus** | **🟡 被注释** | **L4896-4901** | 被注释，可通过配置 ENDGAME_DEPTH_BONUS 控制 |
| LMP | ❌ 未实现 | — | Late Move Pruning |

### 3.3 走法排序

当前排序优先级：TT move > SEE(捕获) > Killer > Countermove > Followup > History

| 排序技术 | 位置 | 说明 |
|----------|------|------|
| TT move | negamax 入口 | 最高优先级 |
| MVV-LVA | L3933-3940 | 捕获走法排序 |
| Killer Moves | L1359-1374 | 每深度 2 个，**未去重** |
| Countermove | L5006 | `s->countermove[side][from][to]` |
| Followup | L5006 | `s->followup[from][to]` — **缺颜色维度 BUG** |
| History | L5238 附近 | 64×64 表，**无 History Malus** |

### 3.4 置换表

- 结构：4-way cluster（每簇 4 个 TT_Entry）
- 大小：128MB（每次搜索 calloc/free）
- 替换策略：深度优先 + generation 老化
- **已知问题**: 每次搜索重新分配，无法跨搜索保留深层信息

### 3.5 Lazy SMP

- 架构：多 worker 共享 TT，主线程决定结果
- 线程数：4（可配置）
- **限制**: 所有线程使用完全相同的参数搜索，无深度交错或参数差异化

---

## 四、评估函数技术方案

### 4.1 架构

```
evaluate(Board *b)
  ├── 缓存检查 (b->eval_score != EVAL_SCORE_INVALID)
  ├── phase_weight = phase * 256 / 24  (0=残局, 256=中局)
  ├── PST 评估 (mg_pst + eg_pst 渐变)
  ├── 兵评估 (evaluate_pawns — Pawn Hash 缓存)
  │     ├── 叠兵 / 孤兵 / 通路兵 / 连通路兵
  │     ├── 通路兵升变威胁 / 支持 / 阻挡
  │     └── 兵盾评估
  ├── 机动性评估 (马/象/车/后)
  ├── 棋子关系评估
  │     ├── 悬垂子惩罚 / 被少子攻击
  │     ├── 马前哨 / 叉子检测
  │     └── 双象奖励
  ├── 王安全评估
  │     ├── 攻击单位表 (128 项)
  │     ├── 兵盾惩罚
  │     └── 阶段衰减
  ├── 开局启发 (前 15 回合)
  ├── 残局启发
  │     ├── 王活跃化 / 逼王墙角
  │     └── 简化奖励
  ├── 中心控制 / 车开放线 / 7 线车 / 易位奖励
  └── 先手分 (tempo)
```

### 4.2 Tapered Eval 渐变机制

所有评估项使用中局/残局两套权重，通过 `phase_weight` 线性插值：

```c
// 正确公式（当前部分位置存在反转 BUG）
score = (mg_value * phase_weight + eg_value * (256 - phase_weight)) / 256;
```

- `phase_weight = phase * 256 / 24`
- `phase` 范围 0-24（0=纯残局, 24=纯中局）
- `phase_weight` 范围 0-256

### 4.3 评估特征清单（21 项）

| 特征 | 位置 | 说明 |
|------|------|------|
| PST | engine_params.h | 6 种棋子 × mg/eg，当前编译版本全零 |
| 兵结构 | L2721-2900 | 叠兵/孤兵/通路兵/连通路兵/兵盾 |
| 机动性 | L2990-3050 | 马/象/车/后按攻击格数计分 |
| 悬垂子 | L3363-3377 | 被攻击且未防守的棋子惩罚 |
| 被少子攻击 | — | 被低价值棋子攻击的高价值棋子惩罚 |
| 马前哨 | — | 马在中心有兵保护的位置 |
| 叉子检测 | — | 同时攻击两个高价值目标 |
| 双象奖励 | — | BISHOP_PAIR_BONUS=50 |
| 王安全 | L3170-3273 | 攻击单位表 + 兵盾 + 阶段衰减 |
| 中心控制 | — | 中心格占据奖励 |
| 车开放线/半开放线 | — | ROOK_ON_7TH_BONUS=30 |
| 开局启发 | — | 前 15 回合惩罚未出动子力、鼓励易位 |
| 残局王活跃化 | L3769-3786 | 王靠近中心奖励 |
| 逼王墙角 | L3815-3839 | 将对方王逼向角落 |
| 简化奖励 | — | SIMPLIFICATION_THRESHOLD=200 |
| 先手分 | L3871-3878 | tempo_mg / tempo_eg |
| 易位奖励 | — | castle_short_bonus / castle_long_bonus |

---

## 五、参数配置系统

### 5.1 配置加载链路

```
configs/v1.7.2.json
       ↓ (build_engine.py 读取)
_generate_params_header()
       ↓ (生成)
engine_params.h (#define + static const 数组)
       ↓ (编译进)
engine_core.c / engine_core.dll
```

### 5.2 运行时参数加载

引擎还支持运行时从文件加载参数（`load_params_from_file()`），加载的参数存储在 `g_runtime_params` 结构体中，可覆盖编译时默认值。

### 5.3 PST 全零的真实原因

**这不是 BUG，是配置加载机制的设计结果**：

1. `engine_params.h` 由 `build_engine.py` 从 JSON 配置自动生成
2. 当前 `engine_params.h` 是从 **v1.7.0** 配置生成的，该版本 PST 值设为零（占位）
3. **v1.7.2** 配置已包含完整的 PST 数据（经典 PeSTO 风格值）
4. 执行 `python build_engine.py --config v1.7.2` 即可将 PST 编译进引擎
5. 也可以通过运行时 `load_params_from_file()` 加载包含 PST 的配置

**结论**: 不需要在代码中硬编码 PST 默认值，配置系统已正确支持 PST 数据加载。

### 5.4 配置继承机制

配置文件支持 `base_version` 字段实现继承：

```json
{
  "version": "v1.7.2",
  "base_version": "v1.7.0",
  "parameters": {
    "pst": { ... },          // 仅覆盖 PST
    "search_params": {       // 仅覆盖搜索参数
      "endgame_depth_bonus": 3
    }
  }
}
```

`config.py` 的 `resolve_config()` 会递归解析继承链，子版本仅覆盖差异参数。

---

## 六、已知问题与设计意图

### 🔴 确认 BUG（需修复）

| 编号 | BUG | 位置 | 影响 |
|------|-----|------|------|
| B1 | 机动性 mg/eg 权重反转 | L3005, 3017, 3030, 3043 | 中局用残局机动性分，残局用中局分 |
| B2 | 先手分 mg/eg 权重反转 | L3873 | 中局用残局先手分，残局用中局分 |
| B3 | 王安全阶段缩放条件反转 | L3267 | 中局王危险被缩减 80%，残局反而不缩减 |
| B4 | ENDGAME_PHASE_THRESHOLD 误用 | L3769 | phase(0-24) 与阈值 1500 比较，残局王活跃度永远生效 |
| B5 | 通路兵升变格被攻击符号错误 | L2849, 2851 | 黑方通路兵升变格被攻击时反而加分 |
| B6 | Followup 缺少颜色维度 | engine_core.h L111 | 黑白方 followup 数据互相覆盖 |

### 🟡 设计选择（需验证后修改）

| 编号 | 现象 | 位置 | 真实原因 |
|------|------|------|---------|
| D1 | **Razoring 返回 0** | L1517-1521 | **因评估函数 BUG 导致性能退化而禁用**。退化根因：(1) 机动性/先手分 mg/eg 权重反转使静态评估系统性偏差，Razoring 依赖 eval+margin<alpha 判断不可靠；(2) ENDGAME_PHASE_THRESHOLD 误用使 is_endgame 永远为真，razor_margin 被放大 1.5 倍过于激进；(3) PST 全零缺乏位置感。**修复评估 BUG 后应重新测试** |
| D2 | **Check Extension 被注释** | L4882-4888 | **因搜索爆炸被注释**。ext_count 上限 4 过大，需降至 2 后重新测试 |
| D3 | **PST 全零** | engine_params.h | **配置加载机制**。v1.7.0 配置 PST 为零占位，v1.7.2 已有完整数据 |
| D4 | **Endgame Depth Bonus 被注释** | L4896-4901 | 被注释掉，可通过配置 ENDGAME_DEPTH_BONUS 控制（v1.7.2 配置值为 3） |

### 🟢 优化机会（可选改进）

| 编号 | 机会 | 位置 | 预期收益 |
|------|------|------|---------|
| O1 | TT 持久化 | L5716 | 消除每次 calloc 128MB 开销，保留跨搜索深层信息 |
| O2 | static_eval 缓存 | L1452, negamax | RFP/Futility/Null Move 共享评估值，减少 90%+ evaluate 调用 |
| O3 | Pick-Next 延迟排序 | L3949-3952 | 替代全量 qsort，beta 截断后无需排序剩余走法 |
| O4 | Blunder Memory 哈希化 | L151 | 线性扫描 10000 条 → 哈希表 O(1) |
| O5 | 重复检测优化 | L4847-4865 | 限制扫描范围为 halfmove_clock |
| O6 | History Malus | negamax | 安静走法未截断时减少 history 值 |
| O7 | Killer 去重 | killer 更新处 | 避免与 killer[0] 重复存储 |
| O8 | Lazy SMP 线程多样性 | L6277 | 辅助线程参数差异化 |
| O9 | 高精度计时器 | L1299-1303 | Windows clock() 精度 15.6ms → QueryPerformanceCounter |
| O10 | Zobrist 哈希改进 | L421-431 | LCG → Xorshift64/SplitMix64 |

---

## 七、短期迭代共识路线图

基于 DeepSeek / GLM / Kimi / Qwen 四份优化方案的交叉验证总结。

### 7.1 共识项（四方案一致认同）

| 优先级 | 内容 | 预估 Elo | 风险 |
|--------|------|----------|------|
| **P0** | 评估函数 BUG 修复（B1-B6） | +80~150 | 低（BUG 修复） |
| **P1** | static_eval 缓存 | +15~25 | 低 |
| **P1** | Check Extension 重新启用（ext_count≤2） | +5~10 | 中低 |
| **P2** | TT 持久化 | +20~40 | 低 |
| **P2** | 重复检测优化 | +5~10 | 低 |
| **P3** | 走法排序优化（pick-next + history malus + killer 去重） | +15~30 | 中 |
| **P4** | Lazy SMP 线程多样性 | +15~30 | 低 |

### 7.2 分歧项（需测试验证）

| 内容 | 分歧 | 验证建议 |
|------|------|---------|
| Razoring 重新启用 | 退化根因已定位为评估 BUG（mg/eg 反转 + is_endgame 误用 + PST 全零），修复评估后应重新测试 | 迭代1完成后实现 should_apply_razoring 有效逻辑，SPRT 测试验证；若仍退化调整 margin |
| PST 填充方式 | GLM 建议硬编码经典值；实际配置系统已支持 | 使用 v1.7.2 配置编译即可，无需硬编码 |
| LMP 添加 | 仅 DeepSeek 提及 | 单独 SPRT 测试验证 |
| 评估函数增量更新 | 仅 Kimi 提及 | 实现复杂度高，列为中长期 |
| SEE 缓存 | 仅 Qwen 提及 | 需评估内存开销和命中率 |

### 7.3 推荐迭代顺序

```
迭代1: 评估函数 BUG 修复（B1-B6）     ← 最高优先级，低风险高收益
迭代2: 搜索性能优化（static_eval 缓存 + Check Extension）
迭代3: TT 持久化 + 检测优化
迭代4: 走法排序优化
迭代5: Lazy SMP 增强
```

每个迭代完成后：
1. 运行 `perft_test.py` 确保走法生成正确
2. 快棋自对弈 100 局确保无崩溃
3. 与前一版本快棋 50 局确认不退化
4. 打 git tag 标记版本

---

## 八、关键代码位置速查

| 功能 | 文件 | 行号 |
|------|------|------|
| evaluate() 入口 | engine_core.c | 2906 |
| phase_weight 计算 | engine_core.c | 2917 |
| 机动性权重反转 BUG | engine_core.c | 3005, 3017, 3030, 3043 |
| 王安全阶段缩放反转 BUG | engine_core.c | 3267 |
| ENDGAME_PHASE_THRESHOLD 误用 | engine_core.c | 3769 |
| 先手分权重反转 BUG | engine_core.c | 3873 |
| 通路兵符号错误 BUG | engine_core.c | 2849, 2851 |
| should_apply_razoring | engine_core.c | 1517 |
| should_apply_futility_pruning | engine_core.c | 1452 |
| Check Extension（注释） | engine_core.c | 4882-4888 |
| Endgame Depth Bonus（注释） | engine_core.c | 4896-4901 |
| negamax() | engine_core.c | 4819 |
| quiescence_search() | engine_core.c | 4710 |
| find_best_move_c() | engine_core.c | 5658 |
| TT 初始化（每次 calloc） | engine_core.c | 5716 |
| Followup 更新 | engine_core.c | 5238 |
| Followup 定义 | engine_core.h | 111 |
| Lazy SMP worker | engine_core.c | 6277 |
| PST 定义 | engine_params.h | 33-163 |
| 搜索参数 | engine_params.h | 196-212 |
| 配置生成 | build_engine.py | 83-246 |
