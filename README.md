# Hellcopter Chess Engine

一个用 C 编写的 UCI 国际象棋引擎，Python 作为胶水层。

## 技术方案

### 棋盘表示

**Mailbox 结构** — 8×8 二维数组，配合 `in_bounds()` 边界检查。无位棋盘，所有攻击生成基于模板遍历。

Zobrist 哈希增量更新，每步走子后同步更新 pawn hash、material key、phase 值。

### 搜索引擎

```
search() → PVS + aspiration window
  └─ quiescence() → captures + checks + delta pruning
  └─ null_move() → adaptive R
  └─ razoring() → depth <= 3
  └─ reverse_futility() → improving / non-improving
  └─ futility() → depth <= 8
  └─ LMR → history-based reduction
  └─ SEE → prune losing captures
```

**核心流程:**

1. 根节点走迭代加深（ID），每层调 PVS
2. 使用 aspiration window 缩小搜索窗（初始 50cp）
3. 零窗搜索（零窗口搜索）验证 PV 外走法
4. QS 搜索吃子走法 + 将军着法，delta 剪枝过滤

**剪枝技术:**

| 剪枝 | 条件 | 效果 |
|------|------|------|
| NMP | 非 PV 节点、depth >= 3、eval > beta | R = 3 + depth / 6 |
| Razoring | depth <= 3、eval + margin < alpha | 直接返回 |
| RFP | eval - margin >= beta | 裁剪整层 |
| Futility | depth <= 8、非 PV、非 tactics | 仅搜索吃子 |
| LMR | depth >= 3、move > 3 | base 0.75 + log |
| SEE | QS 中负分吃子 / 非吃子 | >= -80 才搜索 |

**置换表 (TT):**

- 全局 TT，容量动态（默认 ~16M 项）
- Always replace / depth-preferred 混合策略
- 存储: hash, depth, score, flag (EXACT/ALPHA/BETA), best move
- 检测到 hash 冲突时触发校验

**走法排序:**

```
TT move > good captures (MVV-LVA) > countermove > killer(2) > history > bad captures
```

- Killer: 每层 2 个
- History: 基于 (move, 颜色) 的计分表，衰减因子 0.9
- Countermove: 上一步之后的响应着法

### 评估函数

**Tapered eval:** `score = (phase * mg + (24 - phase) * eg) / 24`

**子力 + PST:**

基础子力价值: P=100, N=300, B=320, R=480, Q=900, K=20000

每种子力有独立的 MG/EG 位置价值表（64 格，白方视角镜像翻转给黑方）。

**评估项:**

| 项 | 说明 |
|----|------|
| Material + PST | 基础子力和位置综合 |
| Bishop pair | 双象奖励 50cp |
| Pin detection | 牵制惩罚 25cp |
| Pawn structure | 叠兵、孤兵、通路兵、兵链、落后兵 |
| King safety | 周围格攻击计数 + 兵盾检测 |
| Center control | d4/e4 控制权 + 扩展中心 |
| Mobility | 马/象/车/后各 9 格机动性查表 |
| Threats | 被兵/马攻击惩罚，叉击检测 |
| Outpost | 前哨站奖励（马/象在敌阵） |
| Imbalance | 子力不平衡调整 |
| Mop-up | 优势方王靠近敌王 |
| Opposite bishop | 异色象和棋因子 |

**残局检测:**

- 无双后或单后 + 无车 + <= 1 轻子 → endgame
- 综合 phase 值: 非兵子力权重累加 (N=3, B=3, R=5, Q=9)

### 时间管理

```
optimal = remaining / est_moves + inc * 0.85
```

- 开局前 10 步用 50% 时间预算，中局逐步放宽
- Easy move 检测: 连续 3 层同一走法且得分稳定 → 用 50% 时间
- Panic mode: 子力落后或得分骤降 → 激进分配
- Safety cap: max(inc * 50%, remaining * 25%, 50ms)

### 多线程 (Lazy SMP)

- 主线程搜索，辅线程无锁读取共享 TT
- 深度偏移: 线程 n 的起始深度偏移 (n % 4)
- 各线程独立历史表，不共享

### 残局库 (Syzygy)

- 通过 Fathom 库加载 WDL 表
- 搜索开始时查询 TB，返回确切胜负信息

### 开局库 (Polyglot)

- 支持 .bin 格式，通过 python-chess 读取
- 可配置: book mode (internal/generic/hybrid)、随机度、深度
- 出书后正常思考（无时间削减）

## 编译

```bash
python src/build_engine.py                # 默认编译
python src/build_engine.py --config v1.9.5  # 指定配置
python src/build_engine.py --force        # 强制重编
```

依赖: GCC / MSVC / Clang，自动检测。

## 配置文件

`configs/v1.9.5.json` 定义所有可调参数:

- `piece_values`: 子力基础价值
- `pst`: 12 张位置价值表 (6 种子力 × MG/EG)
- `eval_weights`: 评估权重（象对、兵结构、王安全等）
- `search_params`: 搜索参数（NMP/LMR/RFP 阈值、SEE 等）
- `king_danger`: 王安全 128 格危险表
- `mobility_tables`: 机动性 9 格评分表
- `time_management`: 时间分配参数

通过环境变量 `ENGINE_PARAMS` 可在运行时切换参数文件。

## License

MIT
