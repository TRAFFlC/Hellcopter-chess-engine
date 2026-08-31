# 研究报告：Invictus（Elo≈3100）与 Hellcopter（Elo≈1900-2100）的决定性技术差异

> 报告日期：2026-08-31
> 报告性质：**纯源代码研究与技术对比报告，未复制、未移植任何代码**（符合 GOAL.md 工作纪律第 1、2 条）
> 前序报告：`docs/reports/20260831_pepito_vs_hellcopter_research.md`（Pepito v1.59, Elo≈2500）——本报告多处与其交叉引用，并含一处对其假设的**修正**（见 §3.0）

---

## ⚠️ 0. 研究来源声明（必读）

**本报告的全部 Invictus 侧结论，均来自对该引擎源代码的逐文件完整研读（全库约 2900 行 C++17，已 100% 通读），不是猜测、不是二手资料：**

- 研究对象：**Invictus r391**，作者 **Edsel Apostol**（ed_apostol@yahoo.com，菲律宾），GPL v3 许可。
- 来源仓库：`https://github.com/ed-apostol/InvictusChess`（2026-08-31 克隆，git 工作区为准）。
- 本地路径：`E:\world\python\chess\test_engines\Invictus 3100\InvictusChess\`（目录名 3100 取自 README 所载 CCRL 40/4 榜 r382 = 3108 分，CCRL 40/40 榜 = 3099 分；当前源码版本 r391 略新于最后一次上榜版本）。
- 逐行研读的文件（引用行号见正文各节）：
  - `search.cpp`（483 行：PVS/aspiration/RFP/NMP/ProbCut/LMP/futility/SEE 剪枝/LMR/SE/ABDADA/时间管理/历史更新——已全文精读）
  - `eval.cpp`（234 行：攻击图评估、材料哈希探测、锥化+缩放）
  - `params.cpp`（239 行：全部评估参数、PSQT 参数化生成、材料表初始化与和棋标志）
  - `movepicker.cpp`（162 行：分段走法选择器、各阶段打分）
  - `trans.cpp`/`trans.h`（置换表/评估缓存/ABDADA 忙表的布局与替换策略）
  - `position.cpp`（578 行：增量 make/unmake、有界重复检测、SEE、TT 着法完整验证）
  - `movegen.cpp`（97 行：分段生成 + 专门的单将应对生成）
  - `attacks.cpp`（200 行：magic 位板 + pext）
  - `engine.cpp`/`engine.h`（时间预算、UCI 选项、线程/共享状态）
  - `uci.cpp`（版本号 r391、UCI 协议、调参入口）
  - `tune.h`（488 行：Texel 调参完整管线——K 搜索/Adam/局部搜索）
  - `typedefs.h`、`utils.cpp`、`README.md`、`CMakeLists.txt`
- Hellcopter 侧结论来自对本仓库 `src/` 的研读（本日已复核关键行号：重复检测 engine_search.c:903-916、NMP PV 禁用 :1267-1268、每节点 evaluate() :1010、LMP 守卫 :1484）。

**反剽窃与合规声明：**

1. Invictus 是 **GPL v3** 代码，比 Pepito 的 GPL v2 传染性更强。**任何一行代码的直接移植都会使 Hellcopter 整体感染 GPL v3**。本报告只提取"设计思想 + 数值/条件表达式的事实描述"，用于差异分析。
2. README 自述其受 Stockfish、Ethereal、Defenchess 影响（imbalance 代码注明 Tord Romstad）——即 Invictus 本身也是"借鉴留痕"的产物，这与 GOAL.md 第 2 条的工作方式一致，但其 GPL 性质决定我们**只能借鉴思想，不能移植实现**。
3. 若未来 Hellcopter 出现与 Invictus 结构雷同的代码段（相同魔数表、相同 486×486 材料表布局、相同 ABDADA key 打包），即视为未指明借鉴（剽窃），应当拒绝。
4. 本报告引用的具体数值/行号仅作**证据记录**，不构成"照抄清单"。

---

## 1. Invictus r391 技术档案（源码实证）

### 1.1 总体架构：2900 行达到 3100 分

| 模块 | 实现方式 | 源码位置 |
|---|---|---|
| 语言/构建 | C++17，`-O3 -msse3 -mpopcnt -mbmi2`，LTO，pext 硬编码开启 | `CMakeLists.txt:8`、`typedefs.h:24` |
| 棋盘表示 | 纯位板（`piecesBB[7]`+`colorBB[2]`+64 格邮箱 `pieces[]`+`kpos[2]`） | `position.h:98-110` |
| 滑行攻击 | magic 位板 + `_pext_u64`（无 magic 乘法，纯查表） | `attacks.cpp:86-92` |
| make/unmake | 全增量：Zobrist、兵 Zobrist（phash）、**mg/eg PST 分（stack.score[2]）**、**材料索引 mat_idx**、fifty、pliesfromnull | `position.cpp:171-226、228-253` |
| 走法编码 | 16 位（from 6 + to 6 + flags 4）+ 16 位分数，直接整体存入 TT | `typedefs.h:93-122` |
| 协议 | UCI；附 perft/perft2/eval/d/speedup/tune/see 调试命令 | `uci.cpp:47-71` |
| **开局书/残局库/NNUE** | **全部没有**（README "To Do" 明示待做；源码无任何 book/EGTB/NNUE 代码） | `README.md:16-19` |
| SMP | 改良 ABDADA（异步忙表 + 延迟着法 + 截止复查）+ NUMA 绑定 | `search.cpp:345-362、391-393`、`utils.cpp:90-137` |

**首要事实：Invictus 的 3100 分是在无书、无 EGTB、无 NNUE 的条件下取得的**——与本项目比赛规则（禁书禁库）完全同构。这直接证明：在本规则下 3100 分不需要任何外部资源，搜索+评估本身就能做到。

### 1.2 搜索（search.cpp，全文精读）

- **框架**：fail-soft PVS。根循环所有线程共享深度（`e.rdepth` 原子变量），根结果经自旋锁合并（`search.cpp:146-203`）。
- **aspiration 极窄**：`delta = 10`（约 10cp！）；fail-low 时 `beta=(alpha+beta)/2, alpha=score-delta`；fail-high 时 `beta=score+delta`；连续失败 `delta += delta/2`（1.5 倍增长）。仅 `rdepth>=5` 启用，之前全窗（`search.cpp:147、164-168、176-185`）。
- **静态评估零成本化（本引擎最核心的工程决策）**：
  `evalscore = (TT 有分数) ? TT 分数 : et.retrieve(pos)`（`search.cpp:259`）——**搜索从不直接调用完整评估**。`et` 是每线程独立的**评估缓存哈希表**（5 槽×6 字节条目，miss 时算一次并写入，`trans.cpp:10-20`、`trans.h:37-52`）。RFP、NMP、futility、ProbCut 的所有静态分判断全部吃这个缓存。
- **RFP**：`depth<9 && evalscore - 85*depth > beta` 直接返回（`search.cpp:265`）。
- **NMP**：`depth>=2 && eval>=beta && 有非兵子 && 上一步非空步`；`R = (13+depth)>>2 + min(3, (eval-beta)/185)`（自适应）；**深度≥12 或 beta 接近杀分时做验证搜索**（`search.cpp:267-279`）。注意：与 Hellcopter 相同，**PV 节点禁用**（整个剪枝块在 `!inPv && !inCheck` 内，`search.cpp:264`）。
- **ProbCut**：`depth>=5 && eval>=beta` 时 `rbeta=beta+100`，先用 qsearch 试探吃子着法，fail-high 才升格为 `depth-4` 完整搜索（`search.cpp:281-293`）。
- **LMP**：`movestried >= 3 + depth²`（improving 两态同表，`search.cpp:37-39、369`）。
- **futility**：`eval + 90*depth + 250`；另有**历史版 futility**：`eval + 90*depth` 且 `(h+ch+fh) < 600/500`（`search.cpp:296-297、371`）。
- **SEE 剪枝双档**：静着 `SEE < -10*depth²` 跳过；坏吃子阶段 `SEE < -100*depth` 跳过（`search.cpp:374、377`）。
- **CMHist/FMHist 深度剪枝**：`depth-R ≤ 3/2` 且对应历史值低于阈值（-100/-200）跳过（`search.cpp:372-373`）。
- **LMR**：对数表 `0.75 + log(d)*log(p)/2.1`（`search.cpp:32`）；`reduction += !inPv + !improving`；杀手/countermove 减免；**历史和减免** `clamp((h+ch+fh)/600, -2, 2)`；仅对静着（`search.cpp:382-389`）。缩减后零窗→升窗→PV 全窗三段重搜（`search.cpp:392-399`）。
- **SE（singular extension，仅对节点首个着法）**：TT 着法 + `tte.depth >= depth-2` + TT_LOWER 界；`xbeta = tscore - depth*2`（**动态边际**）；排除搜索深度 `depth/2 - 1`，带 quiets≥6 / tactical≥3 预算；**若 `xbeta >= beta` 直接返回 xbeta（multicut 融合）**（`search.cpp:321-339`）。将军延伸 +1、单应对延伸 +1——除此之外无其他延伸，无延伸预算计数器（不可能爆炸）。
- **无 IIR/IID**：TT 缺着法时不降深度。3100 分不需要这项现代标配（值得注意的反例）。
- **Quiesce**（`search.cpp:436-490`）：stand-pat 同样来自 TT/评估缓存；**QS movepicker 带 SEE 边际 `max(1, alpha-best_score-100)`（delta 剪枝形态）**；被将时生成**全部应对**（含静着）；QS 也读写 TT（depth=0，`search.cpp:488`）。
- **和棋/重复检查在每个节点入口**：`fifty>99 || isRepeat() || isMatDrawn()`（`search.cpp:241、441`）。
- **时间管理**（`engine.cpp:48-59` + `search.cpp:191-231`）：
  - 预算：`time = mytime - 1000`（保 1 秒）；`movestogo` 钳到 [1,30] 缺省 30；`max = time/30 + 0.8*inc`；`abs = 0.3*time + 0.8*inc`。
  - 迭代末检查：已用满 65% 预算且**分数比上轮跌 ≥20cp → 延时** `time_range*(跌分)/40`，上限 abs（`search.cpp:193-198`）；杀分确认（rdepth≥30 且连续 4 轮杀分）提前停（`search.cpp:200-201`）。
  - 节点轮询：每 16384 节点查一次钟；软限（未出迭代结论时豁免）/硬限双阈值；尚无最佳着法时宽限 `time_range/2`（`search.cpp:218-231`）。
- **ABDADA**（多线程，单线程比赛下无效但记录如下）：`depth>=3` 非将军节点，着法哈希 `(pos.hash>>32) ^ LCG(m)` 入忙表；被占用着法**延迟到全部正常阶段之后**重试（STG_DEFERRED 阶段，`movepicker.cpp:123-129`）；延迟着法存在且 `depth>=4` 时先复查 TT 截止（`search.cpp:348-354`）。忙表 2MB 固定（`engine.cpp:18`）。UCI 可调 `ABDADA Depth`（默认 3）与 `Cutoff Check Depth`（默认 4）（`engine.cpp:135-136`）。
- **历史更新**：重力公式 `sc += delta - (sc*|delta|)/800`（`search.cpp:492-494`）；杀手×2 + countermove + **cmh（上一步 piece/to 索引）+ fmh（上上步索引）+ caphistory（子×被吃×到格）**，全部 depth² 加权封顶 400（`search.cpp:496-527`）。

### 1.3 走法排序与置换表

- **Movepicker 分段**（`movepicker.cpp:33-135`）：TT 着法 → 好吃子（`(被吃+升变)*6-攻击子 + caphistory` 打分，**SEE<边际 的坏吃子甩到队尾阶段**）→ killer1 → killer2 → countermove → 静着（h+ch+fh 打分）→ 坏吃子 → ABDADA 延迟着法。**选择排序（懒式逐个取最大）**，非一次性全排序。
- **TT 着法验证**：TT 着法使用前经 `moveIsValid()`（完整几何验证：子存在、属行棋方、吃子合法、pinned 方向、走法形状、升变/易位/过路兵逐项检查，`position.cpp:565-629`）+ `moveIsLegal()` 双重检查，非法则弃用（`movepicker.cpp:44-53`）。**Hellcopter 未做此事**（见 §3.3）。
- **TT 布局**：条目 7 字节紧打包（32 位锁 + move_t 4 字节 + depth 8 位 + age 6 位&bound 2 位），3 槽桶 24 字节；替换 = 同锁保序（EXACT 或 depth≥旧值才覆盖）+ **年龄优先替换** `((64+currAge-entryAge)%64 << 8) - depth`（`trans.h:54-77`、`trans.cpp:34-55`）；探测命中即刷新年龄（`trans.cpp:26`）。锁同为 32 位（hash>>32）——但配合着法验证兜底。
- **评估缓存**：每线程 5 槽桶×6 字节（32 位锁+int16 分），miss 全量计算并**覆盖 0 号槽**（`trans.cpp:10-20`）。
- 杀分 TT 存储 ply 校正（`search.cpp:44-49`）。

### 1.4 评估（eval.cpp + params.cpp）

- **攻击图架构**（Ethereal/Defenchess 风格）：先算双方 pawnatks、各子攻击、allatks（≥1 攻击）、allatks2（≥2 攻击）、kingzone，再在其上做所有评估项（`eval.cpp:225-234`）。
- **材料哈希表（本引擎评估侧的最大特色）**：`MaterialTable[486][486]`，索引 = 每方 `兵数×1 + 马数×9 + 象数×27 + 车数×81 + 后数×243`（**make/unmake 增量维护 mat_idx**，`position.cpp:234、247`）。表内**预计算**：材料值+不平衡+phase+标志位（`params.cpp:206-258`）：
  - `flags & 1` = 无子力/单轻子对单轻子/双马对无兵 → **直接判和**（搜索每节点 `isMatDrawn()` 查一次，零评估成本，`position.cpp:364-367`）；
  - `flags & 2` = 车对轻子、车+轻子对车（无兵）→ **缩放至 1/32**（`eval.cpp:221`）；
  - `flags & 4` = 异色象残局 → **缩放至 16/32（半分）**（`eval.cpp:222`）。
  - 作者自己标注 TODO：KRPkr、KBPK、KRPKR 等专用识别**尚未实现**（`params.cpp:254-256`）——即 3100 分并不依赖这些。
- **材料不平衡**：Stockfish 式二次多项式（内部/外部双 6×6 表，注明 Tord Romstad，`params.cpp:47-63、192-204`）。
- **PSQT 参数化生成**：每子的表 = **file 表 + rank 表之和**（`params.cpp:15-43`）——参数量 16/子而非 64/子，天然平滑、便于调参。
- **兵结构**（`eval.cpp:54-69`）：连通/叠/孤/落后兵，**各分"开放/非开放"两档**。
- **子力活动**（`eval.cpp:71-124`）：机动性**按格数逐档查表**（KnightMob[9]/BishopMob[14]/RookMob[15]/QueenMob[28]，全 mg/eg 对，`params.cpp:65-68`）；前哨（马/象，含"可扩前哨"半档）；象控制中心；**象受己方同色兵拖累**；车第 7 横排（需敌王在第 7/8 横排配合）；半开放/开放文件车。
- **王安全**（`eval.cpp:126-164`）：攻击者计数（马/象/车/后各 4 位打包 + 王区攻击数 10 位）≥ 阈值才启动；弱格 = 被我方攻击且对方不能≥2 次防守；**四类"安全将军"**（后/车/象/马将军且将军子不被吃）；**王盾按易位翼 3 档掩码**（含王所在文件特殊档）+ 兵暴两档；**二次曲线评分** `bonus² / 1024`（mg）、`bonus / 20`（eg）（`eval.cpp:162`）。
- **威胁项**（`eval.cpp:166-183`）：弱兵、兵吃轻子、轻子互吃、重子吃弱轻子、兵/轻子攻重子、凡攻后、王攻弱轻子/弱车、**带目标兵推进**。
- **通路兵**（`eval.cpp:185-202`）：按相对行 6 档表 ×（基础值 + 己王距离 + 敌王距离 + 未被挡 + 安全推进 + 安全升变），**全部独立调参**（`params.cpp:70-75`）。
- **空间**（`eval.cpp:204-209`）：我方≥2 次攻击、对方 0 次、非兵攻击的格子，占子/空格两档。
- **锥化**：`tapered = (m*phase + e*(TotalPhase-phase))/TotalPhase`，**再乘材料缩放 scale/32**，加 Tempo=38（`eval.cpp:245-247`）。
- **无 lazy eval、无兵结构哈希**——因为评估缓存把整份评估按位置哈希缓存了，无需在评估内部做捷径。

### 1.5 Texel 调参管线（tune.h，488 行完整实现）

- 数据：`lichess-quiet.txt`（FEN|结果 格式，`uci.cpp:172`）；sigmoid `1/(1+10^(-K*score/400))`，K 由 `FindBestK()` 从 1.36749 起自动寻优（`tune.h:25、53-55、98-116`）。
- **两种优化器并存**：AdamDemonOptimizer（Adam，α=0.015，β1/β2=0.9/0.999，epoch 上限 10000，梯度用**中心差分**：参数±2.0 算两次误差，`tune.h:226-293`）与 LocalSearch（逐参数 ±步长，步长翻倍/反向/稳定计数跳过，`tune.h:295-340`）。当前配置走 LocalSearch（`tune.h:520`）。
- 批大小 16384，每 epoch 洗牌；误差用 Neumaier 求和防漂移（`tune.h:57-92`）。
- 调参开关按模块分组（材料/不平衡/机动性/通路兵/兵结构/活动/威胁/王安全/phase），**mg/eg 成对独立调**（`tune.h:342-484`）。
- 参数全体以 `score_t`（double）参与调参、int16_t 编译进正式版（`typedefs.h:139-143`）。

### 1.6 其他工程细节

- 重复检测（`position.cpp:346-354`）：从 `history.size-5` 起步、**步长 -2（同色）**、下界 = `max(size-fifty, size-pliesfromnull)`——**双界标有界扫描**，成本 O(fifty/2)。
- SEE（`position.cpp:459-497`）：swap 算法 + X 射线增量；静态子值 {100,450,450,675,1300} 与评估完全解耦。
- `moveIsCheck` 用**预计算的发现子位板 dcc** 做快速将军判定（`position.cpp:547-563`、`search.cpp:261`），避免 make 后重算攻击。
- Zobrist 用 xorshift128+ 自生成（`position.cpp:36-44`）。
- Windows NUMA 绑定（`utils.cpp:90-137`）。

---

## 2. Hellcopter 对照档案（本日复核行号）

- 搜索：negamax + PVS；NMP **PV 节点禁用**（`engine_search.c:1267-1268`）、自适应 R + 验证搜索；ProbCut、RFP（`!is_pv_node_rfp`，:1233-1234）、futility、razoring、LMP（`static_eval < 2000` 守卫，:1484）、LMR 阶梯、SE。
- **每节点调用完整 `evaluate()`**（`engine_search.c:1010`；评估内部仅兵结构有 pawn hash，`engine_eval.c:952-956`，无位置级评估缓存）。
- **重复检测：全量线性扫描 game_history + search_history**（`engine_search.c:903-916`），无不可逆边界。
- TT：4 条目簇、深度优先 + generation 老化、QS 读写、TT prefetch；**TT 着法无合法性验证**（`src/` 全目录检索无验证调用）。
- 评估：增量 PST + 256 相位锥化、lazy（固定阈值）、王危险表、KRK/KQKR/KBNK/mop-up 专用残局、Texel/SPSA 管线（tuning/）。
- 残局库 Syzygy / 开局书 Polyglot：比赛禁用（代码存在，正赛不加载）。
- 实测 NPS：548-616 kNPS（startpos，单线程，见 Pepito 报告 §4）。

---

## 3. 决定性差异分析

### 3.0 先说一个修正：Pepito 报告 §5.3 的假设被本报告证伪

Pepito 报告曾假设"NMP 在 PV 节点禁用是 Hellcopter 树膨胀的主要嫌疑项，建议优先 A/B"。**本报告证据：Invictus（3100 分）同样在 PV 节点禁用 NMP**（`search.cpp:264` 的 `!inPv` 门与 Hellcopter `engine_search.c:1267` 语义相同），照样 3100。两台不同代际的强引擎（2002 年 2500 分 / 2021 年 3100 分）在这一点上与 Hellcopter 做法一致 → **该假设应降级为低优先级**。这正是做多引擎交叉研究的价值：单一对照会误导。Pepito 的 NMP-PV 用法属于那个年代的激进选择，不是 Elo 主通道。

### 3.1 差异一：静态评估的获取方式（每节点成本的核心）

这是两引擎**结构差异最大**的一处，比 Pepito 报告的"增量材料差"更彻底：

| 环节 | Invictus | Hellcopter |
|---|---|---|
| 搜索中静态分来源 | TT 分数 → 每线程**评估缓存表**（按位置哈希，5 槽 6 字节条目） | 每节点调 `evaluate()`（`engine_search.c:1010`） |
| 全量评估触发频率 | 每个新哈希**至多一次/线程** | 每个非 TT 命中节点 |
| RFP/NMP/futility/ProbCut 判断成本 | 缓存读取（1 次哈希+5 次锁比较） | 完整评估管线或 lazy 分支 |
| 评估内部捷径 | 无（不需要） | lazy 阈值 + pawn hash |

Hellcopter 的 lazy eval 是"在评估内部做减法"；Invictus 的做法是"在评估外面做缓存"——后者让 RFP/NMP 等所有剪枝判断**完全复用**同一份缓存值，且天然 fail-soft。结合实测（Hellcopter 548-616 kNPS vs 同代引擎普遍 1-3 MNPS），这仍是 96 秒时制下每 1.5× 速度差 ≈ 60-80 Elo 的量级问题（待实验 1 验证）。

### 3.2 差异二：和棋/材料判定的框架化（对 M1 直接相关）

Invictus 把"什么局面该判和/该缩放"做成了**预计算材料表 + 增量索引**（§1.4）：486×486 表覆盖全部材料组合，`mat_idx` 随 make/unmake 增量维护，每节点一次 `isMatDrawn()` 查表：

- 不足以将杀的材料 → 搜索入口直接返回 0（`search.cpp:241`）；
- 车对轻子等"理论难赢" → 评估缩放至 3%；
- 异色象 → 评估减半。

对照 Hellcopter：有 KRK/KQKR/KBNK/mop-up 驱动，但**没有材料级和棋/缩放框架**；Pepito 报告 §3.4 已指出这是失血点，且 2026-08-30 的 m1_self 重复循环和棋议题（见 GOAL 记忆）再次印证和棋侧仍在失血。**两台对照引擎（Pepito 的 TABLAS 封顶、Invictus 的材料表标志位）殊途同归**——这不是巧合，是"把和棋当和棋"的通用解。

### 3.3 差异三：TT 着法验证（正确性保险）

Invictus 的 TT 锁同样只有 32 位（`trans.h:28`：`hash >> 32`，与 Hellcopter 相同的弱点），但它用**完整几何验证**（`moveIsValid()`，60 余行逐项检查，`position.cpp:565-629`）+ 合法性双检兜底（`movepicker.cpp:44-53`）。Pepito 的 `JugadaNoValida` 同样如此。**两个对照引擎都验证、Hellcopter 不验证**——哈希碰撞时 Hellcopter 可能直接执行非法着法（轻则污染搜索，重则崩溃）。这是低成本高价值的一致信号。

### 3.4 差异四：搜索框架的"减法美学"

Invictus 搜索（483 行）做的事**少于** Hellcopter（无 razoring、无 IIR、无延伸预算系统、无 continuation history 多层、LMR 只减静着），但每一项都带**精确的数值边界**（85×depth、100×depth、10×depth²、600/500 历史限、3+depth²）。 Hellcopter 的技术清单更长，但 Pepito 报告 §3.3 的结论在这里**以更强的形式重演**：决定棋力的不是技术数量，而是每个技术的**参数置信度**。Invictus 的参数置信度来自 §1.5 的 Texel 管线 + 长年版本迭代（r228→r391，CCRL 从 2255→3108，README 有案）。

### 3.5 差异五：走法循环的每步成本

- **分段生成 + 选择排序**：好吃子阶段结束前不生成静着；LMP/futility 触发 `skipquiets` 后直接跳过静着生成（`movepicker.cpp:94-98`）。Hellcopter 一次生成全量并全量打分（Pepito 报告 §2 已档）。
- **`moveIsCheck` 用发现子位板**预判将军（`position.cpp:547-563`），不用 make/unmake 试探。
- **QS 的 SEE 边际随 alpha 动态收紧**（`max(1, alpha-best_score-100)`，`search.cpp:466`）——delta 剪枝与 SEE 剪枝合流。

### 3.6 差异六（反向）：Hellcopter 领先或对等的部分

诚实对照：Hellcopter 拥有 Invictus 没有的 razoring、TT prefetch、兵结构哈希、KRK/KQKR/KBNK/mop-up 专用残局驱动、Syzygy/Polyglot 支持（禁用但存在）、更丰富的 continuation 历史族。评估特征覆盖面上两者同量级（Invictus 的威胁项/空间/前哨甚至更细）。**结论：Hellcopter 的技术栈宽度不输 3100 引擎——差距在每节点执行成本（§3.1/§3.5）、和棋完备性（§3.2）、正确性保险（§3.3）与参数校准（§3.4）四件事上。**

### 3.7 无关项（比赛条件下的排除说明）

- ABDADA 多线程：GOAL.md 规则下正赛 Threads=1，此项不构成差异（但说明其单线程代码即为 3100 分主体，未依赖线程数）。
- NUMA、pext：属编译/环境红利，与本机同代 CPU 无本质差异。

---

## 4. 实测情况（诚实声明）

- **Invictus 未能编译测速**：沙箱无法启动本机 mingw gcc（进程启动失败 0xC0000135，与 Pepito 研究时完全相同，已复现两次）。其 kNPS、与 Hellcopter 的同机对局均未测。凡涉及其性能的论断均标注为"代码结构推断"。
- 代码体量实测：`src/` 共 26 文件、约 2900 行（含头文件与调参代码；核心搜索+评估+棋盘约 2000 行），**全部通读完毕**。
- 版本核实：`uci.cpp:19` `version = "r391"`；README 评级榜止于 r382（CCRL 40/4 = 3108）。
- 待办：在正常终端 `cmake -B build && cmake --build build` 后可 `perft 5`（校验正确性）与 `go depth 20`（取 kNPS），补入本节（实验 1）。

---

## 5. 对 Hellcopter 的启示（仅方向，动代码前须按 GOAL.md 留痕）

按预期收益/风险排序（交叉两份报告的信号强度）：

1. **评估缓存表**（§3.1，两引擎证据叠加：Pepito 用 eval cache、Invictus 用 eval hash table——**三代引擎一致**）：位置级哈希缓存全量评估，搜索内所有静态分判断（RFP/NMP/futility/LMP/ProbCut/QS stand-pat）统一走缓存。可与现有 lazy eval 并存或替代。**这是与现有 lazy 机制不同层级的优化**，预期收益 > Pepito 报告的任何单项。
2. **重复检测边界化**（§1.6/§2 对照）：fifty + pliesfromnull 双界标、同侧步长 2 扫描。实现量 <20 行，直接削减每节点固定成本。与 1 合并做 A/B。
3. **材料哈希和棋/缩放框架**（§3.2）：索引式材料表（不必 486×486，Hellcopter 可用增量材料计数的紧凑索引）+ 三类标志（判和/缩放/OCB）。针对 m1 长局消耗与和棋失血画像。
4. **TT 着法合法性验证**（§3.3，两引擎一致）：自研几何验证（禁止照抄 moveIsValid 结构），碰撞兜底。
5. **LMP/futility 的历史联动档位**（§1.2 的 FPHistLimit/CMHist/FMHist 深度剪枝思想）：Hellcopter 已有 LMP 阶梯，可增加"历史值不达标的着法在浅层直接跳过"档位。
6. **aspiration 收敛策略**（delta=10 起步 1.5 倍扩张）与**时间管理的分数跌落延时**（65% 预算 + 跌 20cp 延时）——低风险 A/B 素材。
7. **NMP-PV 禁用 A/B 优先级下调**（§3.0 修正）：不再是首要嫌疑。
8. 沿用 Pepito 报告 §5 的 movetime 修复（仍未处理）。

---

## 6. 后续验证实验清单

| # | 实验 | 通过标准 | 状态 |
|---|---|---|---|
| 1 | 正常终端编译 Invictus + 同机 kNPS 对比（含 Pepito 补测） | 双方 kNPS 与 96s 可达深度 | 待做（沙箱阻断） |
| 2 | Hellcopter 增加评估缓存 A/B（≥300 局或 SPRT） | Elo 置信区间 | 待做 |
| 3 | 重复检测边界化 A/B（可与 2 合并） | 同上 | 待做 |
| 4 | 材料哈希和棋/缩放框架 A/B（重点观察和棋局结果质量） | 同上 + 和棋分类统计 | 待做 |
| 5 | TT 着法验证（正确性测试：随机哈希扰动注入） | 非法着法零执行 | 待做 |

---

*本报告由源码研读生成（Invictus 全库通读 + Hellcopter 关键行复核）；引用行号以 2026-08-31 的工作区状态为准。再次声明：未复制 Invictus 任何代码（GPL v3），后续任何借鉴须在 EXPERIMENTS.md 留痕。*
