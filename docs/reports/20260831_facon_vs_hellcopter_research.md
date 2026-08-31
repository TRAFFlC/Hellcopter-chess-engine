# 研究报告：Facon（Elo≈2800）与 Hellcopter（Elo≈1900-2100）的决定性技术差异

> 报告日期：2026-08-31
> 报告性质：**纯源代码研究与技术对比报告，未复制、未移植任何代码**（符合 GOAL.md 工作纪律第 1、2 条）
> 前序报告：`docs/reports/20260831_pepito_vs_hellcopter_research.md`（Pepito, ≈2500）、`docs/reports/20260831_invictus_vs_hellcopter_research.md`（Invictus, ≈3100）、`docs/reports/20260831_goldfish_vs_hellcopter_research.md`（Goldfish, ≈2250）——本报告是五引擎阶梯研究的收尾，§6 给出五引擎总对比与 Elo 分水岭

---

## ⚠️ 0. 研究来源声明（必读）

**本报告的全部 Facon 侧结论，均来自对该引擎源代码的逐文件研读（`src/` 18 文件约 7500 行 C++17，搜索/评估/TT/时间管理核心 100% 精读，评估 2300 行精读结构+关键函数），不是猜测、不是二手资料：**

- 研究对象：**Facon 1.6 "Temple"**（README 版本徽章与 docs/v1.6.md 核对），作者 **Carlos M. Canavessi**（阿根廷），**仓库无 LICENSE 文件（默认保留所有权利）**。
- 来源仓库：`https://github.com/CMCanavessi/facon`（2026-08-31 克隆，git 工作区为准）。
- 本地路径：`E:\world\python\chess\test_engines\Facon 2800\facon\`（2800 取自 README 所载 Ordo Elo ~2800；26 对手×40 局 gauntlet + 对 1.5 万局自战 +222.8）。
- 精读的文件（引用行号见正文各节）：
  - `search.cpp`（~2450 行：negamax 主干 825-1412 全文精读、QS 738-813、go() 1438-1737、SEE 482-604、move_score/sort 637-725、LMR/LMP 表 426-461）
  - `search.h`（524 行：全部搜索参数与各版本演进注释——**这份头文件的版本注释本身就是一部涨分日记**）
  - `eval.cpp`（~2500 行：evaluate() 1883、934 权重数组 374、材料并入 PST 239-243、各特征组结构、trace_evaluate 2050-2436）
  - `eval.h`（评估全部版本演进注释：mopup/王安全/兵结构/渐变 PST/Texel）
  - `tt.cpp`/`tt.h`（401 行：depth-preferred + generation 老化全文精读）
  - `timeman.cpp`（400 行：软/硬双限全文精读）
  - `board.h`（222 行：位板+邮箱双表示、StateInfo 历史栈、增量 Zobrist）
  - `README.md`（版本 Elo 表 1.0→1.6：1220→2800）、`docs/v1.1-v1.6.md`（各版本技术文档）
- Hellcopter 侧结论来自对本仓库 `src/` 的研读（沿用前三份报告复核的行号）。

**反剽窃与合规声明：**

1. **Facon 无 LICENSE 文件——法律默认"保留所有权利"，任何一行代码的直接复制都不被许可**（比 GPL 更严格：GPL 至少授权使用/修改/再分发）。本报告只提取"设计思想 + 数值/条件表达式的事实描述"。
2. Facon 自述使用了 Gediminas Masaitis 的 texel-tuner 框架（README 致谢）——调参方法论本身是公开技术。
3. 本报告引用的具体数值/行号仅作**证据记录**，不构成"照抄清单"。

---

## 1. Facon 1.6 技术档案（源码实证）

### 1.1 总体架构：一年六版、从 1220 到 2800 的完整成长日记

| 模块 | 实现方式 | 源码位置 |
|---|---|---|
| 语言/构建 | C++17 + CMake，静态链接单二进制 | `CMakeLists.txt` |
| 棋盘表示 | 位板（`pieces[7]`+`by_color[2]`）+ 64 格邮箱 `piece_on[64]` 双冗余 | `board.h:69-75` |
| make/unmake | StateInfo 栈（吃子/EP/易位权/50 步/哈希入栈）；**历史栈内嵌 Board（1024 条 ≈17KB，传引用、禁拷贝）** | `board.h:34-51、100-102`、`search.cpp:1187-1197` |
| 走法生成 | 伪合法生成 + make 后攻王检查合法性（避免 17KB 板拷贝） | `search.cpp:793-800、1188-1197` |
| 哈希 | 增量 Zobrist（15×64 + 16 易位 + 8 EP + 行棋方） | `board.h:231-246` |
| **开局书/EGTB/NNUE/SMP** | **全部没有**（单线程，无任何外部资源） | — |
| 评估 | 934 权重 Texel 调参、渐变 PST、8 特征组 | `eval.cpp:374-475` |

**版本 Elo 表（README.md:56-64，gauntlet 方法论注明）——这是本研究最珍贵的史料：**

| 版本 | 代号 | Ordo Elo | 增量 | 主要新增 |
|---|---|---|---|---|
| 1.0 | Oxido | ~1220 | — | 材料 + PST |
| 1.1 | Herrumbre | ~1360 | +140 | 王安全、动态时间管理、killer |
| 1.2 | Rojo Vivo | ~1700 | +340 | **NMP**、PV 三角数组 |
| 1.3 | Yunque | ~1900 | +200 | **LMR、aspiration、history(depth²)**、TM 细化 |
| 1.4 | Hoja | ~2330 | +430 | LMR 表预计算、RFP/futility 常数化、movestogo、TM 修复 |
| 1.5 | Espiga | ~2550 | +220 | **countermove、IIR、razoring、LMP、SEE 分档吃子排序、TT 代老化** |
| 1.6 | Temple | ~2800 | +250 | **全评估 Texel 重调（934 权重）、渐变 PST、shelter/storm、王安全 v2、tempo** |

**三个涨分断层：NMP（+340）、1.4 的搜索工程整固（+430）、Texel 全评估重调（+250）。**最后一项是纯评估参数工作，超过除 NMP 外任何单项搜索技术。

### 1.2 搜索（search.cpp 825-1412 全文精读）

框架：fail-soft negamax。**没有 PVS**——除 LMR 分支零窗外，所有着法全窗搜索（`search.cpp:1261-1275`，LMR 零窗→fail-high 才全窗重搜，主循环非 LMR 着法直接 `-negamax(-beta, -alpha)`）。PV 用三角数组（`search.cpp:1344-1353`）。

**节点级流程（按源码顺序）：**

1. 中止旗标 + 每 2048 节点查钟（negamax 用 nodes、quiescence 用 qnodes，两个计数器分别触发——深战术链里 nodes 冻结，qnodes 保证查钟仍触发，`search.cpp:754、844`）；
2. 5 分钟心跳输出（VVLTC 防呆，`:849-873`）；
3. 重复/50 步判和（ply>0，`:877`）；ply 达 MAX_PLY 返回 evaluate；
4. **将军延伸**（唯一延伸，`:899`——且在 depth==0 判定**之前**，被将军的 depth0 节点升级为 depth1 全搜索，QS 永不见将军局面）；
5. depth==0 进 QS；
6. 生成全量伪合法着法 → TT probe（**TT 着法对着法表逐项比对验证**，对不上弃用，`:937-943`；TT 截止仅 ply>0 且 depth 达标，根节点永不早退，`:951-964`）；
7. 动态判 PV（`beta-alpha>1`，`:978`）；
8. **IIR**：PV 节点、非将军、depth≥4、无 TT 着法 → depth-1（`:996-998`）；
9. **静态评估按需计算**：仅 `!in_check && ply>0 && depth ≤ max(RFP=3, FUT=2)` 时才调 evaluate（`:1007-1010`）——深节点零评估成本；
10. **RFP**：`static_eval - 100×d ≥ beta` 返回（d≤3，`:1022-1026`）；
11. **Razoring**：非 PV、d≤2、`static_eval + 250×d < alpha` → 零窗 qsearch 验证，`q + margin ≤ alpha` 才返回（`:1046-1058`）；
12. **NMP**：`do_null && !in_check && ply>0 && depth≥3 && 有非兵子力`；R=3 固定；零窗 `(-beta, -beta+1)`；空步分 ≥ beta 返回 beta（`:1085-1118`）；
13. 着法排序（TT→好吃子→killer1→killer2→countermove→history→坏吃子，`move_score` :637-690）+ 循环内：
    - **LMP**：非 PV、非将军、d∈[1,6]、合法静着数 ≥ `LMP_TABLE[d]`（{8,12,16,24,36,48}）且当前着法是静着非 killer → 整着跳过（make 之前，`:1173-1183`）；
    - make + 攻王检查合法性；
    - **着法级 futility**：d≤2、合法着法 >1、静着、`static_eval + 150×d ≤ alpha` → unmake 跳过（`:1206-1215`）；
    - **LMR**：`depth≥3 && legal>3 && !in_check && !吃子 && !升变 && !killer`；查表 `max(1, log(d)×log(m)/2.25)`；reduced_depth 下限 1（不降入 QS）；零窗搜，`>alpha` 全窗重搜（`:1240-1271`）；
    - beta 截止时：killer 存储、history `+depth²`（封顶 50000）、countermove `[piece][to] = m`（`:1360-1382`）；
14. TT 存储（杀分 ply 校正，bound 按 fail-high/EXACT/UPPER）。

**没有的东西：SE、ProbCut、PVS 主循环零窗、多线程、TT prefetch。**

### 1.3 静态搜索（search.cpp 738-813）

- stand-pat = **每个 qnode 全量 evaluate()**（无评估缓存、无 TT eval 字段，`:760`）；
- 只搜吃子（被将军局面被 §1.2 第 4 步结构性挡在 QS 外）；
- **SEE 剪枝**：`被吃值 < 攻击子值 && see(m) < 0` 跳过（"以小换大才需要 SEE 确认"，`:783-788`）；
- make/unmake 合法性；abort 旗标逐层传播（保证 unmake 配对、板一致、TT 无污染，`:741、806`）。

**SEE 本体**（`:482-604`）：经典 swap 算法 + `all_attackers_to(sq, occ)` X 射线增量发现；静态子值表与评估解耦。

### 1.4 评估（eval.cpp）——934 权重的 Texel 重调

- **全部权重集中单数组 `eval_weights[934]`**（`:374-475`），mg/eg 成对；材料值**调参后折入 PST**（`PIECE_VALUE` 保持固定，`:239-243`）；
- 特征组（各带 `*_counts()` 位板收集 + 打分两段，保持线性可调）：
  1. 材料+渐变 PST（每子 MG/EG 两表，`:519-576`）；
  2. **兵结构**：孤/叠/落后/连通/通路（通路按相对行 6 档），全 mg/eg 对（`:1449-1678`）；
  3. **活动性**：各子机动性按格数、开放/半开放线、车第 7、象对、马前哨（两档：可扩 10cp/受护 25cp，`eval.h:40-46`）、`:1680-1881`）；
  4. **王安全 v1**：攻击者计数打包（马象车后各 4 位 + 王区攻击 10 位）≥阈值启动，`:625-739`；
  5. **王安全 v2**：朝王的开放/半开放线 + 各子型"安全将军"格数，`:994-1101`；
  6. **tropism**：各子到敌王 Chebyshev 距离分桶打分，`:755-854`；
  7. **shelter/storm**：王前兵盖按行距分桶 + 敌兵推进分桶（这两组 1.6 新增），`:855-992`；
  8. **positional2**：**tempo（+19 Elo，1.6 单项最高！）**、象前哨、通路兵精修（王 escort/拦截/自由通路/受护，整组 +10.6），`:1159-1296`；
  9. **mopup**：无兵且材料差超阈值的清王角+收王距（K+B/K+N vs K 判和守卫，`eval.h:26-29`），`:1322-1430`；
- 渐变：`phase = N/B=1, R=2, Q=4`（总 24），`(mg×p + eg×(24-p))/24`（`:477-481`）；
- **调参配套**：`trace_evaluate()` 输出线性系数分解 + 引擎一致性校验（UCI `trace` 命令）；`eval` 命令输出逐项分解（`:2045-2451`）；
- **1.6 试错记录（README "rejected" 段，对 Hellcopter 极有价值）**：Tarrasch 车置通路兵后 −9、非线性机动性 −12、Kaufman 材料不平衡 ≈0（调参把价值重分配进 PST，自战确认冗余）。

### 1.5 置换表（tt.cpp）

- 条目含 6 位 generation + 2 位 bound 打包、16 位哈希、深度 8 位、move16、value16；
- **替换**：空槽 / 同哈希 / 新深度 ≥ 旧深度 / **旧条目年龄 ≥ 2 代** 四选一即覆盖（`:85-92` 风格的 `replace` 谓词，版本注释 1.4/1.5 两段记载演进：先 depth-preferred，后加 aging 豁免）；
- **probe 命中即刷新 generation**（防仍有效的条目被老化出局）；hashfull 只统计本代条目；
- 大小取 2 的幂，掩码代替取模；杀分 score_to_tt/from_tt 按 ply 平移；
- QS 不读写 TT（与 Hellcopter/Goldfish 不同——较保守的选择）。

### 1.6 时间管理（timeman.cpp，全文精读）——软/硬双限 + 稳定性反馈

- 预算：`base = (剩余-100ms开销)/25(movestogo可覆盖) + 0.75×inc`，×0.90 安全系数，单着上限 2/5 剩余；
- **soft = 0.6×base**（迭代间 soft_stop 检查：达到即不再开新一轮），**hard = 2.0×base**（节点内每 2048 查，提前 100ms 宽限保 bestmove 发出）；
- **延时触发**：迭代间 PV 变化（depth 的二次因子，15 层满额）或**分数跌 ≥30cp** → soft×因子，普通路径封顶 hard；depth≥25 且确需突破时"复杂局面路径"抬 hard（封顶剩余 50%）；
- **提前收**：找到杀线 ×0.05（一次性守卫防 0.05^N 塌缩）、强制着法 ×0.10、**连续 ≥5 轮 PV+分数稳定（d≥10）逐轮 ×0.95**，PV 再变时 `cancel_easy_move` 反向恢复；
- 所有决策打 `info string TM:` 日志（含 h:mm:ss 格式化）——时间管理可观测性工程。

---

## 2. Hellcopter 对照档案（沿用前三份报告复核结论）

- 搜索：negamax + **PVS**（Facon 没有）；NMP（PV 禁用）+ 自适应 R + 验证搜索、ProbCut、RFP、futility、razoring、LMP（`static_eval<2000` 守卫）、LMR 阶梯、**SE**；
- 评估：增量 PST + 256 相位渐变、lazy 固定阈值、王危险表、KRK/KQKR/KBNK/mop-up 专用残局、Texel/SPSA 管线；
- TT：4 条目簇、深度优先 + generation 老化、**QS 读写**、TT prefetch、**TT 着法无验证**；
- 重复检测：全量线性扫描；每节点完整 evaluate()；NPS 548-616 kNPS。

---

## 3. 决定性差异分析

### 3.1 差异一：参数置信度（本研究最一致的结论，Facon 给出了最强证据）

Facon 1.5→1.6 **一行搜索逻辑没加，+250 Elo**——全部来自把 934 个评估权重送上 Texel 调参（含渐变 PST 化、材料折入）。对照其搜索技术演进史：NMP +340 之后，所有单项搜索技术（LMR/countermove/IIR/razoring/LMP/SEE 排序）**没有一项单独超过 +250**。

结合前序报告：Pepito（两年锦标赛校准）、Invictus（488 行 tune.h 完整管线）、Goldfish（PeSTO 公开调参表）——**五台引擎全部依赖高质量参数，无一例外**。Hellcopter 有 Texel/SPSA 管线但按前三份报告的画像，其参数置信度未达到"934 权重全量重调"的强度。**这是 2000→2800 全程最陡峭的一条路，且 Hellcopter 已具备工具，缺的是执行深度。**

### 3.2 差异二：静态评估的按需计算（负成本评估的中间形态）

Facon 在 negamax 里**只在 depth≤3 的剪枝浅层才算 evaluate**（`search.cpp:1007-1010`），深节点评估成本为零；但 QS stand-pat 每 qnode 全量评估（无缓存）。三种静态分获取形态已经集齐：

| 引擎 | negamax 静态分 | QS stand-pat |
|---|---|---|
| Hellcopter | 每节点 lazy evaluate() | 每 qnode evaluate() |
| **Facon（2800）** | **仅浅层计算** | 每 qnode 全量 evaluate() |
| Invictus（3100）/Pepito/Goldfish | 评估缓存/TT eval | 缓存复用 |

Facon 证明**2800 不需要评估缓存**（只要"深节点不算"这一半），3100 档的 Invictus 才需要。这把 Invictus 报告 §5.1 的"评估缓存"优先级结论修正为**两步走**：第一步是"按需计算"（把 evaluate() 调用从每节点收缩到剪枝层，几乎零风险），第二步才是缓存/TT eval 字段（Goldfish 报告 §5.1）。

### 3.3 差异三：TT 着法验证（三台引擎做法一致，Hellcopter 仍缺）

Facon 的做法最轻：**TT 着法对着法生成表逐项 `==` 比对**（`search.cpp:937-943`），对不上弃用——10 行内解决碰撞污染。加上 Pepito（JugadaNoValida）与 Invictus（moveIsValid + 双检），三个档位的对照引擎全部验证 TT 着法，Hellcopter 缺失。Facon 的轻量形态是 Hellcopter 最容易落地的版本。

### 3.4 差异四：LMR 的"先决条件工程"

Facon 的 LMR 有三处先决工程值得注意（`search.h:18-28、search.cpp:901-909、1250-1253`）：
1. `depth==0` 进 QS 的判定从 `<=` 改为 `==`（让 LMR 降 0 深成为合法态，负深度立即暴露 bug 而非被吞掉）；
2. `reduced_depth = max(1, depth-1-R)`——**LMR 永不直接降入 QS**；
3. 1.4 把对数公式预计算成表（纯提速）。
其 LMR 只有基础公式：**没有** improving、历史减免、杀手减免、log 拟合微调——照样 2800。对照 Invictus 的 LMR 加了 4 种修正。**LMR 的下限实现就能吃到主要收益，上限修饰是最后 100 分的事。**Hellcopter 已有 LMR 阶梯，此差异定性为"已达标"。

### 3.5 差异五：时间管理的稳定性反馈（软/硬双限 + easy/mate/复杂局面）

Facon 的 TM 有四个 Hellcopter 没有的反馈环：分数跌延时、easy move 递减（可撤销）、杀线一次性×0.05、复杂局面抬 hard。96 秒时制下（GOAL 比赛规则），**"该想的局面多想、不该想的局面省时间"直接影响平均深度**。这是低风险、可独立 A/B 的整块素材（timeman 是独立模块，动它不动搜索逻辑）。

### 3.6 差异六（反向）：Hellcopter 领先或对等的部分

PVS（Facon 无）、SE、ProbCut、TT prefetch、QS 的 TT 读写、专用残局驱动（KRK/KQKR/KBNK）、评估的增量 PST（Facon 非增量——每个浅层节点全量重算，靠"按需"而非"增量"省钱）、lazy eval。**搜索技术清单 Hellcopter 长于 Facon。**2800 的 Facon 与 3100 的 Invictus 一起构成第二个反例组：**技术清单长度与 Elo 不相关，置信度与执行成本才相关。**

### 3.7 无关项排除

- VVLTC 心跳/currmove 抑制等输出工程：不影响棋力；
- Facon 无 LICENSE：只影响合规方式（连思想借鉴也要留痕，不能"参考实现"）。

---

## 4. 实测情况（诚实声明）

- **Facon 未能编译测速**：沙箱 gcc 启动失败（0xC0000135，与 Pepito/Invictus 研究时相同，第三次复现）。kNPS、同机对局均未测。
- 代码体量：`src/` 18 文件约 7500 行（eval.cpp ~2500、search.cpp ~2450 为大头）；搜索主干、QS、go()、SEE、TT、TM、评估结构 100% 精读，评估部分特征组函数仅读结构与注释。
- 版本核实：README 徽章 `version-1.6 Temple`；docs/ 至 v1.6.md。
- 待办：正常终端 `cmake -B build && cmake --build build` + `bench`（自带 10 位深度 18 基准）取 NPS，并入实验 1。

---

## 5. 对 Hellcopter 的启示（仅方向，动代码前须按 GOAL.md 留痕）

按预期收益/风险排序（综合四份报告）：

1. **全量 Texel 重调现有评估**（§3.1，五引擎最强一致信号）：把 Hellcopter 现有评估项的全部权重（含 PST 的 mg/eg 对）整体送调参管线，而不是逐项手工试。Facon 的 +250 就是这项工作的实测上限量级。配套先建 `trace` 式线性系数分解（Facon 的 trace_evaluate 思想：调参前先证明"评估=权重×特征"恒等式成立）。
2. **静态评估按需计算**（§3.2）：negamax 里 evaluate() 只在剪枝深度阈值内调用（RFP/futility/razoring/NMP/LMP 判断所需的浅层），深节点跳过。改动集中在搜索入口 ~10 行。
3. **TT 着法轻量验证**（§3.3，Facon 形态：对生成表比对）：三引擎一致，本轮给出最便宜实现路径。
4. **TM 软/硬双限 + 稳定性反馈**（§3.5）：独立模块整块替换式 A/B，含分数跌延时与 easy move 递减（可撤销设计）。
5. **aspiration 单侧扩张原则**（§1.2 go()，search.h:49-53 记载的 yo-yo 修复）：fail-low 只降 alpha 不动 beta——若 Hellcopter 现为双侧收缩，此为一行级修复。
6. **评估特征试错的负结果清单直接可抄结论**（§1.4 rejected）：Tarrasch 车置通路兵后、非线性机动性、Kaufman 不平衡三项已在 2800 级引擎上实测为负/零收益——Hellcopter 无需再花 A/B 预算验证这三个方向。

---

## 6. 五引擎阶梯总对比与 Elo 分水岭（本研究收束）

| | Hellcopter | Goldfish 2.1.1 | Pepito 1.59 | Facon 1.6 | Invictus r391 |
|---|---|---|---|---|---|
| Elo | ~2000 | ~2250-2314 | ~2500 | ~2800 | ~3100 |
| 语言 | C | Rust | C | C++17 | C++17 |
| 评估形态 | 增量 PST+lazy+结构项 | PeSTO 纯 PSQT | 增量 PST+结构项 | 934 权重 Texel | 攻击图+材料哈希 |
| 静态分获取 | 每节点 lazy | TT eval 字段 | 评估缓存 | 按需计算 | 评估哈希表 |
| PVS | 有 | 有 | — | **无** | 有 |
| LMR | 有 | **无** | — | 有（基础式） | 有（修饰式） |
| NMP | 有（PV 禁用） | 有（R=5） | 有（**PV 也用**） | 有（PV 动态判） | 有（PV 禁用） |
| SE | 有 | 无 | — | **无** | 有 |
| 和棋完备性 | 专用残局驱动 | TB 外包 | TABLAS 封顶 | mopup+材料守卫 | 材料表判和/缩放 |
| 调参 | Texel/SPSA（未全量） | PeSTO 公开表 | 锦标赛校准 | **934 全量 Texel** | 完整管线 |
| 外部资源 | 禁用 | Syzygy | 无 | 无 | 无 |

**分水岭结论（每档"必要非充分"的主通道）：**

- **2000→2250：TT 工程代差 + 静态分复用 + NMP/基础剪枝的完成度**（Goldfish 无 LMR 也到 2250——LMR 不是这档的门槛；TT eval 字段/缓存是三代引擎一致信号）；
- **2250→2500：参数置信度 + 每节点成本的增量维护**（Pepito 的年代证据：激进参数两年锦标赛喂出来）；
- **2500→2800：LMR 家族 + Texel 全量调参**（Facon：LMR 前提工程 + 934 权重重调；注意 PVS/SE 都不是门槛——Facon 无 PVS、Invictus 无 SE 之外还有 Facon 无 SE）；
- **2800→3100：评估缓存（静态分零成本化）+ 材料级和棋/缩放框架 + 攻击图评估密度**（Invictus 专属形态）。

**对 Hellcopter 的总路线图（按分水岭顺序，而非按引擎逐个学）**：先补 2250 档的 TT/静态分复用（Goldfish 报告 §5.1-2），再做全量 Texel（Facon 报告 §5.1，一步吃 2500→2800 的主通道），最后才是评估缓存与材料哈希框架（Invictus 报告 §5.1/5.3）。**全程没有一项需要新增评估特征或新搜索技术——Hellcopter 的技术面已超配，全部工作都在"参数与执行成本"。**

---

## 7. 后续验证实验清单

| # | 实验 | 通过标准 | 状态 |
|---|---|---|---|
| 1 | 正常终端编译 Facon + `bench` 取 NPS（与 Pepito/Invictus/Goldfish 合并） | NPS 与 96s 可达深度 | 待做（沙箱阻断，第三次复现 0xC0000135） |
| 2 | Hellcopter 全量 Texel 重调（含 trace 恒等式校验先行） | ≥500 局对现版 Elo 置信区间 | 待做 |
| 3 | 静态评估按需计算 A/B | ≥300 局或 SPRT | 待做 |
| 4 | TT 着法轻量验证（Facon 式生成表比对） | 哈希扰动注入零非法执行 | 待做 |
| 5 | TM 软/硬双限 + easy/mate 反馈整块 A/B | 同 3 | 待做 |

---

*本报告由源码研读生成（Facon 核心 100% 精读 + Hellcopter 关键行复核）；引用行号以 2026-08-31 的工作区状态为准。再次声明：Facon 无 LICENSE（保留所有权利），任何代码复制均不被许可；后续任何借鉴须在 EXPERIMENTS.md 留痕。*
