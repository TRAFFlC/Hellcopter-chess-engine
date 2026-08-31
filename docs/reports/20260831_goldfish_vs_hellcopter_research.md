# 研究报告：Goldfish（Elo≈2250-2300）与 Hellcopter（Elo≈1900-2100）的决定性技术差异

> 报告日期：2026-08-31
> 报告性质：**纯源代码研究与技术对比报告，未复制、未移植任何代码**（符合 GOAL.md 工作纪律第 1、2 条）
> 前序报告：`docs/reports/20260831_pepito_vs_hellcopter_research.md`（Pepito, Elo≈2500）、`docs/reports/20260831_invictus_vs_hellcopter_research.md`（Invictus, Elo≈3100）——本报告是五引擎阶梯研究的第三块拼图（填补 2250 档），多处与前两份交叉引用

---

## ⚠️ 0. 研究来源声明（必读）

**本报告的全部 Goldfish 侧结论，均来自对该引擎源代码的逐文件研读（核心 `engine/src` 约 2000 行 Rust，已 100% 通读关键模块），不是猜测、不是二手资料：**

- 研究对象：**Goldfish v2.1.1**（工作区 Cargo.toml 实测版本号），作者 **Bendik Samseth**，**MIT 许可**（LICENCE 文件全文核对）。
- 来源仓库：`https://github.com/bsamseth/goldfish`（2026-08-31 克隆，git 工作区为准）。
- 本地路径：`E:\world\python\chess\test_engines\Goldfish 2250\goldfish\`（目录名取用户指定 Elo 档；README 内部排位表显示 v2.1.0=2314 分，该表以 v1.13 的 CCRL 40/40 榜为锚点换算）。
- 逐行研读的文件（引用行号见正文各节）：
  - `engine/src/search/negamax.rs`（136 行：PVS/negamax 主循环——已全文精读）
  - `engine/src/search/cuts.rs`（266 行：PVS 封装、TT 截止、TB 探测、mate distance pruning、delta pruning）
  - `engine/src/search/speculate.rs`（213 行：NMP/futility/razoring/IID——已全文精读）
  - `engine/src/search/quiescence.rs`（139 行：静态搜索全文精读）
  - `engine/src/search/root.rs`、`run.rs`、`helpers.rs`、`stackstate.rs`、`mod.rs`（根循环/迭代加深/着法栈/重复检测）
  - `engine/src/tt.rs`（715 行：置换表全文精读，含测试）
  - `engine/src/evaluate.rs`（301 行：评估全文精读）
  - `engine/src/movelist.rs`（145 行：MVV-LVA/killer/history 排序）
  - `engine/src/opts.rs`、`limits.rs`（UCI 可调参数与时间预算）
  - `README.md`（版本排位表、路线图）、`Cargo.toml`（版本与依赖）、`LICENCE`（MIT）
- Hellcopter 侧结论来自对本仓库 `src/` 的研读（前两份报告已复核关键行号：每节点 evaluate() engine_search.c:1010、重复检测全量扫描 :903-916、NMP PV 禁用 :1267-1268、LMP 守卫 :1484、TT 着法无验证）。

**反剽窃与合规声明：**

1. Goldfish 是 **MIT 许可**（宽松许可，技术上允许借用），但按本项目纪律仍**只提取设计思想与数值事实描述，不移植任何代码**。与 Invictus（GPL v3）的"禁止传染"不同，本报告的合规风险点是"无意识照抄"而非"许可污染"——MIT 照抄不违法，但违反 GOAL.md 第 2 条的借鉴留痕纪律。
2. Goldfish 评估的 PeSTO 表来自 Chess Programming Wiki 的公开成果（evaluate.rs 文件头自注），任何引擎用同一张表都不构成对 Goldfish 的剽窃，但**若 Hellcopter 采用须另行留痕来源为 CPW/PeSTO**。
3. 本报告引用的具体数值/行号仅作**证据记录**，不构成"照抄清单"。

---

## 1. Goldfish v2.1.1 技术档案（源码实证）

### 1.1 总体架构：Rust 工作区 + 外部位板库

| 模块 | 实现方式 | 源码位置 |
|---|---|---|
| 语言/构建 | Rust 工作区（6 个子 crate），`release-lto` 配置全 LTO | `Cargo.toml:1-9` |
| 棋盘/走法生成 | **外部 `chess` crate v3.2.0**（非自研！）+ 自研 `goldchess` 补充层 | `engine/Cargo.toml:14` |
| 走法执行 | **copy-make**（`let mut new_board = *board` 整体复制，非 make/unmake） | `negamax.rs:77` |
| TT | Stockfish 式移植：10 字节条目 × 3 槽簇（32 字节对齐）、generation 老化、eval 存储 | `tt.rs:34-131` |
| 残局库 | Syzygy WDL 搜索内探测 + DTZ 根着法过滤（fathom 的 Rust 移植） | `cuts.rs:134-187`、`helpers.rs:143-160` |
| SMP | 无（Threads=1 固定，`opts.rs:20-21`） | — |
| **开局书/NNUE** | **无** | — |
| 评估 | **PeSTO 原版渐变 PSQT，无任何其他评估项** | `evaluate.rs:1-280` |

**架构首要事实：Goldfish 连走法生成都是外部库，全部自研精力只投在搜索与 TT 上。这是"用成熟库 + 聚焦搜索"路线达到 ~2300 的实证**（对照本项目规则需自研核心，但架构启示有效：位板/走法层不是 Elo 瓶颈，搜索层才是）。

### 1.2 评估（evaluate.rs）——全场最"穷"的 2250 级评估

- **唯一的评估项**：PeSTO 渐变 PSQT（材料值并入表中）+ 行棋方 +1cp（tempo）。
  - 材料值：MG `[82,337,365,477,1025]` / EG `[94,281,297,512,936]`（`evaluate.rs:12-13`）。
  - 相位：马/象=1、车=2、后=4，总 24，`min(24)` 封顶（`evaluate.rs:258-263、269`）。
  - 渐变：`(mg*phase + eg*(24-phase))/24`（`evaluate.rs:271`）。
- **没有**：兵结构、王安全、机动性、通路兵、威胁、通路兵推进、和棋缩放、专用残局驱动（无 KRK/mop-up 等）。
- **计算方式：非增量**。每次 `evaluate()` 扫全部 64 格重算 mg/eg/phase（`evaluate.rs:247-264`），make/unmake 不维护任何评估增量。
- 残局正确性完全外包给 Syzygy TB（探测命中直接返回 WDL 分），无 TB 时残局只有 PSQT 兜底。

**这是五引擎阶梯里评估项最少的引擎，却站稳 2250+ 档。它证明：一张高质量的调参 PSQT 表 + 像样的搜索，就值 2250。**

### 1.3 搜索（negamax.rs + speculate.rs + quiescence.rs，全文精读）

框架：fail-soft negamax + **PVS**（PV 节点后续着法先零窗侦察，`cuts.rs:29-53`）。节点类型用 `const PV: bool` 泛型单态化（编译期分支消除，Rust 特有优势，`negamax.rs:21`）。

**剪枝/延伸清单（完整）：**

- **将军延伸**：+1 深度（`negamax.rs:46-48`）——唯一的延伸。
- **NMP**（`speculate.rs:48-88`）：条件 `eval >= beta`（动态门槛）；守卫：非将军、上一步非空步、beta 非已知结果分、**有非兵子力**（zugzwang 粗防）、空步搜到已知胜分不采纳（`value >= beta && !value.is_known_win()`）；**R=5 固定**（`depth-5`，`speculate.rs:71`）；零窗搜索。
- **Razoring**（`speculate.rs:129-164`）：边际 `323 + 249×d²`（二次曲线！）；`eval + margin < alpha` 时用零窗 qsearch 验证，验证仍低于 alpha 才剪。
- **Futility**（`speculate.rs:96-122`）：深度 ≤5，边际 `17 + 100×(d-1)`，`eval - margin >= beta` 直接返回 beta（节点级，非着法级）。
- **IID**（`speculate.rs:171-193`）：仅 PV 节点、无 TT 着法、深度 ≥5 时先降 2 深度搜一遍取着法。**作者自注"测试显示收益平平，考虑移除"（TODO 注释原文）**。
- **Mate distance pruning**（`cuts.rs:231-244`）：标准实现。
- **静态搜索**（`quiescence.rs`）：stand-pat（被将军时禁用）+ TT eval 借用（`cuts.rs:200-219`，TT 里的 eval 可直接当 stand-pat，且可用 bound 修正）；**full delta pruning**（`cuts.rs:255-266`：stand-pat + 2×后值 - 兵值 ≤ alpha 剪整节点）+ **per-move delta pruning**（边际 12cp，`speculate.rs:206-213`）；被将军时生成全部应对（含静着）；QS 读写 TT（depth=0 条目）。

**没有的东西（对照 Hellcopter 已有）：LMR、aspiration windows、LMP、IIR、SEE、ProbCut、RFP、countermove、singular extension。** 全部在 README 路线图 TODO 里（`README.md:81-85`）。

**走法排序（movelist.rs）：**
- MVV-LVA（10×被吃值 - 攻击子值，升变加 10×(升变-兵) 差值）；
- killer 加 99cp（兵值-1）；
- history 是**计数式**（`update_history_stats` 每次最佳着法 +1，`helpers.rs:162-166`），排序时按本节点最大计数线性归一到 0-10cp 加成（`movelist.rs:64-82`，上限 UCI 可调默认 10）；
- TT 着法 swap 到首位，其余按分数排序（`movelist.rs:112-125`）。

### 1.4 置换表（tt.rs）——五引擎中与 Hellcopter 最可比的"代差"证据

这是本报告对 Hellcopter 最有横向价值的一节。Goldfish 的 TT 是 Stockfish 结构的忠实移植：

- **条目 10 字节紧打包**：key16（16 位）+ depth8（8 位，偏移 -3）+ gen_and_bound8（gen 5 位 + pv 1 位 + bound 2 位）+ move16 + value16 + eval16（`tt.rs:34-44`），`Option<NonMax>` 零成本表示；
- **3 槽簇 32 字节对齐**（CPU 缓存行，`tt.rs:126-131`）；
- **索引用 mul_hi64**（key×len 取高 64 位，均匀分布下等价取模但无除法，`tt.rs:282-287`）；
- **替换策略**（`tt.rs:342-384`）：同 key 或 EXACT 才无条件覆盖；否则 `depth + PV 加成 > 旧 depth - 4` 或**旧条目属于上一代**才覆盖；**保留旧条目的着法**（新数据没着法时不清 move16）；
- **generation 老化**：每次新搜索 `+8`（模 32），相对年龄参与替换决策（`tt.rs:184-187、331-339`）；
- **eval 字段存储**：静态评估随条目存取——QS 的 stand-pat 直接复用 TT eval（`cuts.rs:205-216`）；
- **杀分校正**：存取时按 ply 平移（`tt.rs:448-501`），并带**基于 halfmove_clock 的"50 步规则杀分降级"**（规则 50 剩余步数不足以完成杀 → 降级为普通胜/负分，`tt.rs:473-501`，含完整测试覆盖）；
- **GHI（图历史交互）部分防护**：halfmove_clock ≥90 时禁用 TT 截止（`cuts.rs:121-124`）。

### 1.5 重复检测与时间管理

- **重复检测**（`helpers.rs:112-129`）：halfmove ≥100、子力不足（chess crate 内建）、**搜索内 2 次重复即判和**（`position_count >= 2`，即同一局面在栈内出现 2 次就返回 DRAW——比"3 次"更激进的搜索内判和）。扫描范围限定在"上次不可逆着法之后"的栈区间（有界，非全量），但实现为逐项线性过滤。
- **时间管理**（`limits.rs:67-111`）：**全场最简**。`movetime = (剩余×95% + (mtg-1)×增量) / mtg`，mtg 缺省 40；无软/硬双限、无 PV 稳定性逻辑、无 easy move；`should_stop` 每节点查表（`helpers.rs:17-21`）。开局后单合法着法直接返回不搜索（`run.rs:23-25`）。

### 1.6 工程细节

- PV 输出用 **TT 链式重建**（不做三角 PV 数组，省搜索热路径成本，`helpers.rs:38-62`）；
- 根着法表每轮按上轮分数重排（`root.rs:12-14`）；
- TB 探测的 CursedWin/BlessedLoss 映射为 DRAW±1（保留"宁可信规则 50 保和也不依赖它"的语义，`cuts.rs:152-158`）；
- 根部 DTZ 过滤 + 单合法着法短路（`helpers.rs:143-160`）；
- Rust 泛型单态化 `const PV: bool`（零运行时分支开销）+ `unsafe` TT 写指针（writer 模式限定生命周期）。

---

## 2. Hellcopter 对照档案（沿用前两份报告的复核结论）

- 搜索：negamax + PVS；NMP（PV 禁用）+ 自适应 R + 验证搜索、ProbCut、RFP、futility、razoring、LMP（`static_eval < 2000` 守卫）、**LMR 阶梯、SE、aspiration**；
- 评估：增量 PST + 256 相位渐变、lazy（固定阈值）、王危险表、KRK/KQKR/KBNK/mop-up 专用残局、Texel/SPSA 管线；
- TT：4 条目簇、深度优先 + generation 老化、QS 读写、TT prefetch、**TT 着法无合法性验证**；
- 重复检测：**全量线性扫描 game_history + search_history**；
- 每节点完整 `evaluate()`；
- NPS 实测：548-616 kNPS（startpos 单线程）。

---

## 3. 决定性差异分析

### 3.1 差异一：评估质量不是 2250 档的分水岭（反向修正）

Pepito 报告 §3 曾把"评估项丰富度"列为 2500 档差异之一。**Goldfish 证伪了它在 2250 档的必要性**：纯 PeSTO PSQT（材料+位置、零结构项、零王安全、非增量计算）+ 搜索就到 2250-2300。Hellcopter 的评估项数量（兵结构/王安全/专用残局/lazy/Texel 调参）**全面超过 Goldfish**。

结论：**Hellcopter 与 2250 档的差距不在"评估项多少"，而在下面几节。**这修正了"逐项堆评估特征"的涨分直觉——特征堆叠在 2000-2250 区间的边际收益低于搜索质量与执行成本。

### 3.2 差异二：TT 的"工程代差"是本场最直接的可移植差距

Goldfish TT 与 Hellcopter TT 的功能面（深度优先+老化+QS 读写）名义相近，但工程细节差一整代：

| 维度 | Goldfish（SF 移植） | Hellcopter |
|---|---|---|
| 条目密度 | 10 字节/条目，32 字节 3 槽簇（缓存行对齐） | 较大条目、4 槽簇 |
| 索引 | mul_hi64（无除法/取模） | 哈希取掩码（视实现） |
| **eval 存储** | **有**——QS stand-pat、TT bound 修正复用 | 无 |
| 杀分 50 步降级 | 有（halfmove 剩余 < 杀距 → 降级） | 无 |
| GHI 防护 | halfmove ≥90 禁止 TT 截止 | 无 |
| 替换精细度 | 同 key 保 move、EXACT 特权、depth-4 宽容、PV 加成 | 深度+老化（粗粒度） |

其中 **eval 存储与 GHI/50 步防护是"纯收益"项**——与 Invictus 报告 §3.1 的评估缓存结论形成三代引擎证据链：Pepito（eval cache）→ Goldfish（TT 内嵌 eval 字段）→ Invictus（独立评估哈希表）。**Hellcopter 在"静态分复用"这一层完全空白，是 2000→2250 档最一致的结构性信号。**

### 3.3 差异三：QS 的 stand-pat 成本路径

Goldfish QS 的 stand-pat 优先取 **TT 条目的 eval 字段**（miss 才全量计算，`cuts.rs:205-208`），并用 TT bound 修正该值（`cuts.rs:212-216`）。Hellcopter QS 的 stand-pat 每次走 lazy evaluate()。叠加 QS 节点占比通常 50-80%，这是 3.2 的直接放大器。

### 3.4 差异四：搜索内的和棋纪律

Goldfish 在搜索内**2 次重复即返回 DRAW**（激进缩短循环线），加上 TB 的精确 WDL，其"不恋战"纪律比 Hellcopter（3 次重复 + 全量扫描判定）更硬。对 m1 长局和棋失血画像（GOAL 记忆）是一致方向：**和棋判定越早越便宜，搜索树越不浪费在注定和棋的分支上**。

### 3.5 差异五（反向）：Hellcopter 搜索技术面全面领先

诚实对照：Hellcopter 有 LMR/aspiration/LMP/IIR/SEE/ProbCut/RFP/SE/countermove，Goldfish 一个都没有。**但 Goldfish 高 150-250 分。**这以最强形式重演了 Invictus 报告 §3.4 的结论：**决定棋力的不是技术清单长度，而是每项的执行质量、参数置信度与每节点成本**。Goldfish 把仅有的几件事（PVS、NMP R=5、razoring 二次边际、futility、SF 级 TT、TB）做到高完成度。

### 3.6 需要交叉验证的排除项（诚实声明）

- **Goldfish 的排位表来自其自办对局池**（以 v1.13 CCRL 40/40 锚定），与 Hellcopter 的评测池不同源，±100 分的池间偏差正常，2250 vs 2000-2100 的差距量级应打八折看待；
- Goldfish 在其测试中可用 Syzygy TB（CCRL 惯例允许 3-5 子库），本项目禁库规则下其残局正确性会显著退化（评估无残局驱动）——**禁库规则下 Goldfish 的有效棋力大概率低于其排位**，即它与 Hellcopter 的真实差距可能比表面更小；
- 未编译测速（沙箱 Rust 工具链不可用），NPS 未实测，性能论断均为代码结构推断。

---

## 4. 实测情况（诚实声明）

- **Goldfish 未能编译测速**：沙箱无法运行 cargo（与 Invictus/Pepito 研究时相同的沙箱限制）。kNPS、同机对局均未测。
- 代码体量：`engine/src` 约 2000 行 Rust（不含 fathom/uci/goldchess 库层），核心 6 文件 100% 精读。
- 版本核实：`engine/Cargo.toml` `version = "2.1.1"`；`chess` crate 3.2.0。
- 待办：正常终端 `cargo build --profile release-lto` 后 `go depth 20` 取 kNPS（与前两份报告的实验 1 合并执行）。

---

## 5. 对 Hellcopter 的启示（仅方向，动代码前须按 GOAL.md 留痕）

按预期收益/风险排序（综合三份报告证据强度）：

1. **TT 条目增加 eval 字段**（§3.2/§3.3，三代引擎一致证据）：搜索与 QS 的所有静态分判断（RFP/futility/razoring/NMP 门槛/QS stand-pat）统一复用 TT eval。与 Invictus 报告 §5.1 的评估缓存建议同向，但**改 TT 条目比新建评估哈希表侵入更小**，可与现有结构并存（先加字段、再逐点替换调用）。
2. **杀分 50 步降级 + GHI 防护**（§3.2）：存 TT 前按"规则 50 剩余步数 < 杀距"降级杀分；halfmove ≥90 禁 TT 截止。正确性纯收益，实现 <30 行。
3. **搜索内 2 次重复判和**（§3.4）：配合已有的有界扫描改造（Invictus 报告 §5.2），把"注定和棋"分支的搜索投入提前砍掉。
4. **参数置信度优先于新特征**（§3.1/§3.5）：Goldfish 反例表明 Hellcopter 的特征面已超配——下一步应把现有特征的参数送上严肃的 Texel/SPSA 调参（现有管线用起来），而非新增评估项。
5. **copy-make vs make/unmake 不构成方向性差异**（Goldfish 用 copy-make 也到 2250），但 Rust 泛型单态化提示：**把"是否 PV 节点/是否将军"等高频分支做编译期或查表化**是可借鉴的降本思路（C 语言可用函数克隆/内联宏实现）。
6. **TT 着法合法性验证**（三份报告一致，优先级维持）：本轮 Goldfish 的做法是"move16 解码后交给走法生成器匹配"，实现代价低于 Invictus 的 60 行几何验证。

---

## 6. 后续验证实验清单

| # | 实验 | 通过标准 | 状态 |
|---|---|---|---|
| 1 | 正常终端编译 Goldfish/Rust + 同机 kNPS（与 Pepito/Invictus 实验 1 合并） | 各引擎 kNPS 与 96s 可达深度 | 待做（沙箱阻断） |
| 2 | TT eval 字段 A/B（≥300 局或 SPRT） | Elo 置信区间 | 待做 |
| 3 | 杀分降级 + GHI 防护 A/B（可与 2 合并） | 同上 | 待做 |
| 4 | 搜索内 2 次重复判和 A/B（重点看 m1 和棋时长） | 同上 + 长局统计 | 待做 |
| 5 | 禁库规则下 Goldfish 对 Hellcopter 实测对局（验证 §3.6 差距修正） | 100 局胜率 | 待做 |

---

*本报告由源码研读生成（Goldfish 核心模块通读 + Hellcopter 关键行复核）；引用行号以 2026-08-31 的工作区状态为准。再次声明：未复制 Goldfish 任何代码（MIT），PeSTO 表如采用须另行标注 CPW 来源；后续任何借鉴须在 EXPERIMENTS.md 留痕。*
