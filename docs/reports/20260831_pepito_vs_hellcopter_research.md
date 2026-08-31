# 研究报告：Pepito（Elo≈2500）与 Hellcopter（Elo≈1900-2100）的决定性技术差异

> 报告日期：2026-08-31
> 报告性质：**纯源代码研究与技术对比报告，未复制、未移植任何代码**（符合 GOAL.md 工作纪律第 1、2 条）

---

## ⚠️ 0. 研究来源声明（必读）

**本报告的全部 Pepito 侧结论，均来自对下列 GPL 开源引擎源代码的逐文件研读，不是猜测、不是二手资料：**

- 研究对象：**Pepito v1.59**（目录名 "Pepito 2492" 的分值来自历史等级分表），作者 **Carlos del Cacho**（西班牙），2000-2003 年开发，GPL v2 许可，源码位于 `E:\world\python\chess\test_engines\Pepito 2492\pepisrc\`。
- 逐行研读的文件（含关键行号，全文见正文各节）：
  - `negascou.c`（主搜索 NegaScout / Quiesce / DealPrune）
  - `eval.c`（评估函数、王安全、兵结构、残局驱动、重复检测）
  - `hash.c`（置换表布局与替换策略、TT 着法合法性验证）
  - `sort.c`（分段走法排序）
  - `see.c`（静态子力交换评估，含 X 射线发现）
  - `itera.c`（根搜索、aspiration 窗口、easy move、时间延展、PV 回填 TT）
  - `time.c`（时间分配 AllocTime）
  - `mueve.c`（增量式 make/unmake）
  - `readme.txt`、`changes.txt`（版本历史与作者自述——这是判断其"棋力来源"的重要证据）
- Hellcopter 侧结论来自对本仓库 `src/` 目录（engine_search.c / engine_eval.c / engine_core.c 等）的研读，并含本机实测数据（见 §4）。

**反剽窃与合规声明：**

1. Pepito 是 **GPL v2** 代码。**任何一行代码的直接移植都会使 Hellcopter 整体感染 GPL 许可**。本报告只提取"设计思想 + 数值/条件表达式的事实描述"，用于差异分析；后续若借鉴任何思想，必须按 GOAL.md 第 2 条在 `EXPERIMENTS.md` 对应条目写明 `参考来源: Pepito v1.59（GPL，Carlos del Cacho）+ 本报告路径`。
2. 若未来 Hellcopter 出现与 Pepito 结构高度雷同的代码段（相同宏名、相同魔数表、相同位打包布局），即视为未指明借鉴（剽窃），应当拒绝。
3. 本报告引用的具体数值/行号仅作为**证据记录**，方便日后查证与实验设计，不构成"照抄清单"。

---

## 1. Pepito v1.59 技术档案（源码实证）

### 1.1 总体架构

| 模块 | 实现方式 | 源码位置 |
|---|---|---|
| 棋盘表示 | 64 格 mailbox `Tablero[]` + 12 个全局 bitboard（PeonesB/N、TorresB/N…）+ **旋转位板**（Rotado90/45/315） | `datos.h`、`mueve.c` |
| 滑行攻击 | 旋转位板预计算攻击表（按占用字节索引）：`ATAQUES_TORRE_FIL/COL`、`ATAQUES_ALFIL_45/315` | `initataq.c` |
| make/unmake | 全增量：Zobrist、兵 Zobrist、子力 Material、兵数 NumPeones、子数 Piezas、王位置、易位权、`last_cap`（最后一次不可逆着法序号） | `mueve.c:30-190` |
| 协议 | Xboard + UCI 双协议，MultiPV、kibitz、PGN 记录 | `xboard.c`、`uci.c`、`multipv.c` |
| 开局 | B-tree 书（.ind/.bin 双文件）、书学习、对手书学习 | `book.c`、`btree.c` |
| 残局库 | Nalimov EGTB（探测带缓存，EXACTO 100 ply 深度入 TT） | `probe.c`、`tbdecode.c` |
| 深度粒度 | **分数 ply**：`UNIT_PROF` 为 1 ply，延伸/缩减按 1/10 ply 精度 | `negascou.c:49-53` |

### 1.2 搜索（negascou.c）

- **框架**：fail-soft **NegaScout**（零窗口试探 + 失败即全窗口重搜，`negascou.c:795-808`）。
- **根 aspiration 窗极窄**：`RWINDOW = PEON_VAL/3 ≈ 33cp`（`itera.c:37`），fail-high 时先 `beta=实际+1兵`，连续两次才开无限窗（`itera.c:675-695`）；fail-low 同理（`itera.c:739-756`）。
- **空步剪枝**：`R = 3 ply（深度≤6）/ 4 ply（深度>6）`；将军中、无子方禁用；**≤2 子且零窗口时改用 R=5 的预探测**（`negascou.c:409-443`，即 Dieter 式残局 zugzwang 防护）。空步失败且返回值为"被将杀"时置 `null_threat` 标志。
- **null_threat 机制（本引擎最具特色的zugzwang处理）**：`null_threat` 一位随 TT 条目存储（`LIM_INF_NULL` 类型 + hash 条目第 59 位，`hash.c:27-29`），下次到达同位置时**禁用空步**并触发 `NULL_EXT/2~1 ply` 延伸（`negascou.c:344、746-756`）。
- **剪枝簇**：
  - futility（`negascou.c:479-520`）：d≤1 边际 3 兵、d≤2 边际 6 兵、d≤3 且 `TBalance+后≤alpha` 时**先降 1 ply 再用 6 兵边际**（razor 的一种形态）——用的是**增量维护的材料差 TBalance，不调评估函数**。
  - **DealPrune**（`negascou.c:896-934`，Don Dailey 思想）：前沿节点(d=1)若静态分≥beta，则对**所有**吃子做 SEE，若没有任何吃子能把分数拉回 beta 以下，直接返回 beta。
  - 粗 LMR（`negascou.c:784-787`）：`searched>15` 且局面不亏时 `extension=-2 ply`（即该着法搜索深度-2）。
- **延伸（全部分数 ply，且有预算约束 `can_extend = rply ≥ ply`）**：
  - 将军延伸按**应着数缩放**（`CHECK_NJUG[6]`：1 种应着 +1 ply，2 种 +0.1，5 种 −0.1，`negascou.c:71-72、705`）；
  - recap 延伸（同格连续吃子且被吃子同价值）、兵推延伸（无子方兵到 1/6 行）、null-threat 延伸、castle strike（打易位区的兵吃 +0.1~0.2 ply）。
- **Quiesce**（`negascou.c:1078-1168`）：stand-pat → 吃子按 MVV/LVA 插入排序 → **alpha 剪枝（被吃子值+升变值+pos_eval+1兵<alpha 跳过）+ SEE<0 跳过**（仅当对方材料富余时才做这些剪枝，防残局误剪）。
- **走法排序（分段生成，sort.c:44-161）**：TT 着法 → 吃子 MVV/LVA 选择排序 → **对估值低于 −50 的吃子重算 SEE 再选** → 2 killers → 非吃子一次性 ShellSort（按 history）。**不生成不需要的着法**：吃子阶段截断后直接跳杀手/静着。
- **置换表（hash.c）**：16 字节紧凑条目（24 位着法 + 17 位分数 + 2 位类型 + 16 位深度 + 1 位 null_threat + 老化位，`hash.c:21-38`）；**双槽混合替换**：同 key 保留；否则"旧条目或新深度≥旧深度"→ 旧条目降级到 2 号槽（深度优先 + 永远替换并存，Bruce Moreland Gerbil 方案，`hash.c:115-125`）；**TT 着法严格伪合法验证** `JugadaNoValida()`（含易位路径被攻击检查，`hash.c:191-292`）；杀分按 ply 调整。
- **history**：`depth²` 加权（`negascou.c:854`），每步开始整体右移 8 位衰减（`itera.c:313-317`）。

### 1.3 评估（eval.c）

- 三阶段（开局/中局早/晚/残局）判定 + 阶段相关兵表（`itera.c:238-283` 的 TABLA_MED/FIN）。
- **与易位方向绑定的攻王兵表**：双方异侧易位时兵结构直接换用 `KING_STORM/QUEEN_STORM` 进攻表（`eval.c:460-468`）。
- **兵结构（pawn hash 24B/条目，24 位 key 校验）**：弱兵用"攻/守兵计数比较"判定（非简单相邻判定，`eval.c:538-572`）；孤立兵惩罚随数量递增（`BONUS_AISLADOS[9]`，0,-10,-30,-45…）；**暴露兵对"轮到走的一方"惩罚加倍**（`BONUS_EXPUESTOS_PEPI/OTRO`，即考虑行棋方）。
- **通路兵**：静态价值随**对方非兵子力**缩放（`AUMENTA_PASA[PMaterial]`，对方子越少通路兵越贵）；被挡/未挡两张表；**远距通路兵**（`alejados`）；王支持（`REY_APOYA_PASADO`）。
- **显式兵升变赛跑**（`eval.c:823-939`）：无子方时逐通路兵计算"王能否赶上"（王距/行棋方/助推射线），双方比较 aux/aux2，赢赛跑直接 ±8 兵分（≈一个子）。双通路兵另有"不可阻挡"加分。
- **和棋上限（无 EGTB 时的关键）**：无兵方若非兵子力差≤3 且对方有后→ 分数封顶 TABLAS（`eval.c:438-449`）；KNN vs 无兵 = 和；异色象局分数减半；`MaterialInsuficiente()`。
- **专用残局驱动**：`Final_KBB_K()`、`Final_KBN_K()`（直接返回驱动分）、错误色象+车路兵和棋（`TablasAlfilPeonDeTorreB/N`）。
- **王安全**（`EvalSeguridad` + `eval.c:1047-1119`）：对王圈 8 格逐格统计"敌子数-我守子数"（后参与额外 +4），乘**兵盾强度 defB** 与**阶段表 `DISMINUYE[PMaterial]`**（对方子力越少王安全越重要→0），`/32` 缩放。三种风格 solid/normal/aggressive 即此模块开关（readme.txt:123）。
- **lazy eval（fail-soft 式）**：先算完便宜的兵结构+材料，若 `分数 > beta + MaxPos` 或 `< alpha − MaxPos` 直接返回近似值（`eval.c:1029-1045`）——**阈值跟随搜索窗口**而非固定值；另有独立 eval cache（按全局哈希，`eval.c:1127-1133`）。
- 其它：象对（按兵数缩放）、被困象/被困马（−180/−150）、第 7 行重子（`BONUS_SEPTIMA` 按 1-6 个重子递增到 300）、outpost（马/象）、tropism（攻击子向敌王的距离表）、机动性（仅象/车，`MOV_ALFIL/MOV_TORRE`）、开局中心兵堵塞、先手 +4。
- **重复检测**：`Repeticion()` 只扫 `last_cap`（最后一次吃子/兵动）之后**同侧**历史（`eval.c:1529-1542`）→ 50 步规则同一界标（`negascou.c:579`）。

### 1.4 根与时间管理（itera.c / time.c）

- 根着法先全部**用 Quiesce(-INF,INF) 预打分**并排序（`itera.c:432-443`）→ 支持 easy move（第一名领先 2 兵且非吃子亏分时，用 1/3 时间限额即可停，`negascou.c:221-226`）。
- "改主意"即延时（`time_extend` 位标志：PV 首着变化/fail-high/fail-low 均延长预算，最多 2 次 2/3 限额加时，`negascou.c:227-239`）。
- 每轮迭代结束把整条 PV **回填 TT**（防根置换覆盖，`itera.c:767-782`）；记录逐层节点数估算分支因子 bfactor。
- AllocTime：`inc×time_left/(time_left+inc) + time_left/35`（`time.c:70-77`）。

### 1.5 版本史证据（changes.txt）

2002-07 到 2003-02 之间的条目记录了大量"实锤级"修复：SEE 修了 3 次（"SEE function was broken!?"）、TT 边界存错、**升变+缺残局库**的 crash、吃过路兵时被将军的走法生成 bug、根着法被搜两遍、50 步规则没生效、时间管理、书碰撞导致丢后……**这些就是它的 Elo 来源之一：两年锦标赛环境的持续排错。**

---

## 2. Hellcopter 技术档案（现状，src/ 实证）

- 搜索：negamax + PVS 三段验证（零窗→全窗）；根动态 aspiration（engine_search_root.c:1171-1299）。
- 剪枝全家桶：NMP（自适应 R + 验证搜索 + 六重保护，**PV 节点禁用**）、**ProbCut**、RFP（improving/phase 缩放）、futility、razoring、LMP、history/SEE 剪枝、**完整 LMR 阶梯**、**Singular Extension**（engine_search.c:1252-1570）。
- 走法排序：TT→好吃子（SEE+MVV/LVA）→坏吃子→2 killers→**countermove→followup→history + continuation history + capture history**（engine_search.c:1091-1147），一次生成全量打分。
- TT：4 条目 cluster、深度优先替换 + generation 老化、QS 也探/写 TT、TT prefetch、SE 排除着法守卫（engine_search.c:130-290）。**注意：key 校验只用 key>>32（32 位）+ 索引位；TT 着法未见合法性验证**。
- 评估：增量 mg/eg PST + 锥化（256 相位）、lazy（固定 2000cp 阈值）、机动性表、王危险表（攻击单位→128 项 danger 表，兵盾/开放线惩罚，按攻击子数与相位缩放）、兵 hash（SMP 内存屏障）、KRK/KQKR/KBNK/mop-up 专用残局（engine_eval.c:2086-2317）、Texel/SPSA 调参管线（tuning/）。
- 残局库：Syzygy WDL/DTZ（比赛条件禁用）；开局：Polyglot（禁用）；SMP：Threads 选项。
- 重复检测：**每个节点对整个 game_history + search_history 线性扫描**（engine_search.c:898-916），无 last-irreversible 边界。

---

## 3. 决定性差异分析

### 3.1 先说结论

**Hellcopter 的搜索技术栈比 Pepito 更现代、更全面**（LMR/SE/ProbCut/RFP/LMP/continuation history 都是 2002 年不存在或不成熟的技术）。因此"差 400 分"的原因**不是缺某项技术**，而集中在以下四点，按证据强度排序：

### 3.2 差异一：每节点必要成本（决定同深度下的实际用时）

Pepito 把"每个节点都必须做的事"压缩到极致：

| 每节点成本项 | Pepito | Hellcopter |
|---|---|---|
| 剪枝用的静态分 | 增量 `TBalance`（make 时已维护，零成本） | 调 evaluate()（走完整评估管线或 lazy） |
| 重复检测 | 从 `last_cap` 起同侧扫描（通常 0-20 步） | **全 game_history+search_history 线性扫描**（长局可数百条目） |
| 残局库前置 | 无（EGTB 探测有前置条件且缓存） | depth≥2 每节点 ~10 次 popcount + 大位或运算（TB_LARGEST>0 时） |
| 走法生成 | **分段生成**：吃子阶段截断则不生成静着 | 一次全量生成 + 全量打分（每着 7 层启发式查表） |
| 攻击生成 | 旋转位板查表 | magic 位板（质量同级） |

**实测**（本机，单线程）：Hellcopter startpos 深度 15-20 稳态 **548-616 kNPS**（§4）。Pepito 因沙箱无法编译（gcc 启动被阻断，错误 0xC0000135）未能同机测速——这是本报告最大的未验证项。但其代码结构（增量材料、分段生成、零评估前置剪枝）表明**它的每节点固定开销比 Hellcopter 低**。若 Pepito 同机跑出 0.8-1.2 MNPS，96 秒时制下即多约 1 ply 深度 ≈ 60-80 Elo。

### 3.3 差异二：激进与安全的"经验参数"（每个选择都值 Elo）

这是老引擎真正的护城河，Pepito 的 changes.txt 就是证据。对照几个高风险决策点：

1. **NMP 使用范围**：Pepito 在 PV/非 PV 都用（只留将军/无子/残局特殊处理）；Hellcopter **六重保护里包含"PV 节点禁用"**（engine_search.c:1262-1268）——PV 节点是树的大头，全部禁 NMP 会让 PV 路径显著膨胀。保护是修"误剪杀着"症状的药，代价是树变大。
2. **aspiration**：Pepito ±33cp 极窄窗 + 快速开窗策略是两年调出来的；Hellcopter 用动态窗（按分数稳定性），方向相同但参数年轻。
3. **延伸预算**：Pepito 用 `rply≥ply` 全局预算硬性防延伸爆炸 + 分数 ply 精细缩放（将军延伸按应着数：1 种应着延伸多、6 种反而负）；Hellcopter 用 ext_count<2/3 计数上限——同为防爆，Pepito 的"按应着数缩放"对战术深度更精确。
4. **剪枝的正确性边界**：Pepito 的 SEE/alpha 剪枝带"对方材料富余才剪"守卫（`Material(!Turno)-val>3-4兵`），防残局误剪；Hellcopter 的 LMP/history 剪枝带 `static_eval<2000`、`!is_endgame` 等守卫——同类思想，但 Pepito 的边界是"材料差"这种结构性判据。

### 3.4 差异三：无 EGTB/无书规则下的残局与和棋完备性

M1/M2 比赛规则禁书禁库，这正是 2002 年引擎的主场：

- Pepito：**和棋分数封顶**（无兵+子力差≤3 直接 TABLAS 上限，防"赢不够却送兵"）、KBBK/KBNK 驱动、错误色象和棋、**显式王距赛跑**（无子方通路兵"王赶不上"→+8 兵分）、双通路兵 unstoppable、异色象分数减半、`MaterialInsuficiente`。
- Hellcopter：有 KRK/KQKR/KBNK/mop-up，但**没有和棋封顶/错误色象/赛跑这类"把和棋当和棋"的判定**；而用户最近的 m1_self 对局里出现的**重复局面循环和棋**（2026-08-30 议题）说明和棋侧仍是失血点。残局"会赢"只是一半，"该和就和、不和就赢"是另一半。

### 3.5 差异四：搜索-评估联动的独门细节（Pepito 有、Hellcopter 无，值得研究）

1. **null_threat 经 TT 传播 + LIM_INF_NULL 边界类型 + 触发延伸**：zugzwang 的搜索级闭环（空步失败被将杀 → 存表 → 下次禁空步+延伸），比"验证搜索"更省。
2. **lazy eval 相对 alpha/beta**（`> beta+MaxPos` 才短路）vs Hellcopter 固定 2000cp：前者在叶子层省的评估次数远多于后者，且天然 fail-soft。
3. **eval cache 按位置哈希**（跨分支复用）vs Hellcopter 的单条目 board 级缓存。
4. **DealPrune**：前沿节点"静态分+全吃子 SEE"一次性判定，等价于便宜的整节点 razor。
5. **TT 着法合法性验证**（JugadaNoValida 含易位路径检查）——Hellcopter 的 TT key 只有 32 位校验且未见着法验证，哈希碰撞时可能直接执行非法着法。
6. **根层 Quiesce 预打分全部根着法 + easy move + 改主意延时 + PV 回填 TT**：一整套根管理，减少时间浪费与"最后一层不可信"问题。

### 3.6 差异五（反向）：Hellcopter 领先 Pepito 的部分

诚实起见：Pepito **没有** LMR 阶梯、SE、ProbCut、RFP、LMP、continuation/capture history、countermove、TT-in-QS、SMP、锥化调参评估。**这些是 Hellcopter 未来涨分的本金，不是负担**——问题只在于它们的保护条件/参数尚未被锦标赛数据校准。

---

## 4. 本机实测数据（2026-08-31）

### 4.1 Hellcopter NPS（单线程，startpos）

| 深度 | 节点数 | 用时 ms | kNPS |
|---|---|---|---|
| 10 | 178,670 | 375 | 476 |
| 15 | 8,039,325 | 13,054 | 616 |
| 19 | 73,103,388 | 133,448 | 548 |
| 20 | 161,089,522 | 293,785 | 548 |

- 实测对象：`arena\copter\Hellcopter.exe`（1 线程）与根目录 `Hellcopter.exe`。
- 深度 14→20 节点增长 ×85.5 → **有效分支因子 ≈ 2.07**（含 LMR/TT 的现代水平）。
- 附带发现 1：**`go movetime 8000` 未被遵守**（startpos 一路搜到 depth 20 用了 294 秒）。Arena 正赛走 wtime 不受影响，但说明 movetime 路径存在 bug，建议复核。
- 附带发现 2：从仓库根目录运行 `arena\copter\Hellcopter.exe` 时仍打印 `Auto-loaded Syzygy EGTB from: EGTB (TB_LARGEST=5)`——**复现并证实了 GOAL.md 的警告**：必须从 `arena/copter` 目录内启动。

### 4.2 Pepito 测速：未完成（诚实声明）

沙箱环境无法启动本机 mingw gcc（进程启动失败 0xC0000135，python-subprocess 同样被拦），**Pepito 未能编译，其 kNPS 与同机对局均未测**。凡涉及 Pepito 性能的论断均标注为"代码结构推断"。待办：在正常终端编译后补测（§6 实验 1）。

---

## 5. 对 Hellcopter 的启示（仅方向，动代码前须按 GOAL.md 留痕）

按预期收益/风险排序：

1. **测速对齐**（验证 §3.2 假设）：正常环境编译 Pepito，同位置同时制对比 kNPS/深度。若速度差 ≥1.5×，优先做"每节点成本"清单：重复检测加 last-irreversible 边界、TB 前置成本、分段生成。
2. **和棋/残局判定补全**（验证 §3.4）：无兵+子力差≤3 的 TABLAS 封顶、错误色象、通路兵王距赛跑——这些可在现有 eval 框架内实现，且与 M1 的"长局消耗"输棋画像直接相关。
3. **NMP 的 PV 禁用做 A/B**：这是最大的树膨胀嫌疑项。
4. **TT 着法合法性验证**（Pepito 的 JugadaNoValida 思路，自行实现）+ 考虑 64 位 key 校验。
5. **movetime 修复**（4.1 发现 1）。
6. 中期：分数 ply 延伸、null_threat 闭环、相对窗口 lazy eval——属"借鉴 Pepito 思想"，实施时必须在 EXPERIMENTS.md 标注参考来源。

---

## 6. 后续验证实验清单

| # | 实验 | 通过标准 | 状态 |
|---|---|---|---|
| 1 | 正常终端编译 Pepito + 同机 kNPS 对比 | 得出双方 kNPS 与 96s 可达深度 | 待做（沙箱阻断） |
| 2 | Hellcopter per-node profile（重复扫描/TB 前置/全量打分占比） | 各项占比数据 | 待做 |
| 3 | NMP PV 禁用 A/B（≥300 局或 SPRT） | Elo 变化置信区间 | 待做 |
| 4 | 重复检测改 last-irreversible 边界 A/B | 同上 | 待做 |

---

*本报告由源码研读 + 本机实测生成；引用行号以 2026-08-31 的工作区状态为准。再次声明：未复制 Pepito 任何代码，后续任何借鉴须在 EXPERIMENTS.md 留痕。*
