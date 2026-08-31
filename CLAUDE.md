# Hellcopter Chess Engine — 开发与实验流程

## 项目结构

```
src/
  engine_core.c          # 主入口（unity build）
  engine_core.h          # 公开接口
  engine_params.h        # 编译期参数（auto-generated from JSON）
  engine_params_loader.c # 运行时参数加载
  engine_eval.c          # 评估函数
  engine_search_v2.c     # 递归搜索核心
  engine_search_root.c   # 迭代加深 + PV 输出 + Lazy SMP
  uci_main.c             # UCI 协议层
  build_engine.py        # 编译脚本
  fathom/                # Syzygy 残局库
  engine_debug.c         # 诊断工具
web_chess.py             # Web 界面
engine_wrapper.py        # DLL 加载层（Python 侧入口）
engine.py                # UCI 引擎封装
engine_registry.py       # 引擎注册/发现
match_manager.py         # 对弈管理
match_utils.py           # 对弈工具函数（Elo/SPRT/统计）
uci_engine.py            # UCI 协议客户端
book_provider.py         # 开局库支持
sse_hub.py               # SSE 推送
chess_logic.py           # 棋局逻辑
config.py                # 配置加载
run_match.py             # 命令行对弈入口
configs/                 # 参数配置 JSON
dist/                    # 开局库 Goi5.1.bin
EGTB/                    # Syzygy 残局表
test_engines/            # 对手引擎
cutechess-1.3.1-win64/   # 对弈工具
```

## 编译

```powershell
# 编译共享库
python src/build_engine.py

# 编译独立 UCI 可执行文件
python src/build_engine.py exe

# 指定配置
python src/build_engine.py --config v1.9.5

# 强制重编
python src/build_engine.py --force

# 清理
python src/build_engine.py clean
```

编译产物：
- `engine_core.dll` → 根目录（`engine_wrapper.py` 自动加载）
- `dist/Hellcopter.exe` → 复制到根目录供 cutechess 使用

**编译警告：** 基线 tag `baseline-20260715` 的代码缺少 `count_total_material()` 函数定义（仅在 `engine_search_root.c` 被引用但未实现）。编译基线 EXE 时必须先添加该函数。该函数已在当前主分支中。

### 开局库

**UCI 选项：** `OwnBook`（默认 false）、`BookPath`（字符串）、`BookRandomness`（0-100，默认20）

引擎启动时不再自动加载开局库。可通过 UCI `setoption name BookPath value dist/Goi5.1.bin` + `setoption name OwnBook true` 启用。

Goi5.1.bin 存在 `dist/` 下（约 130MB），含 9,292,868 个局面。

## 三层实验流水线

### Tier 0 — 冒烟（每次改动必过）

运行固定回归集，确认改动没有破坏基础正确性：

```powershell
# perft
echo "position startpos\ngo perft 6" | Hellcopter.exe
# 期望: 119,060,324 个节点

# 战术深度可达性
echo "position fen r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq -\ngo depth 12" | Hellcopter.exe

echo "position fen 8/5p2/8/2k3P1/p3P3/2K5/1P6/8 b - - - - -\ngo depth 12" | Hellcopter.exe

# UCI 协议合法性
echo "uci\nucinewgame\nisready\nquit" | Hellcopter.exe | findstr "id name uciok readyok"
```

**通过条件：** 全部通过。一项失败 = 立即回滚，不进入 Tier 1。

### Tier 1 — 消融快筛（blitz，SPRT）

用于搜索消融（第 2 周）：关掉某项功能 vs 基线，测是否显著变弱。
SPRT 方向为"弱侧判断"——检测实验版是否比基线明显更差。

```powershell
cutechess-1.3.1-win64\cutechess-cli.exe `
  -engine name=Baseline proto=uci cmd=Hellcopter.exe option.Threads=1 `
  -engine name=Ablation proto=uci cmd=Hellcopter_mod.exe option.Threads=1 `
  -each tc=10+0.2 -rounds 100 -concurrency 2 `
  -draw movenumber=40 movecount=5 score=20 `
  -resign movecount=3 score=500 `
  -sprt elo0=10 elo1=50 alpha=0.05 beta=0.05 `
  -pgnout results\abl_YYYYMMDD_HHMM.pgn
```

**CPU 说明：** UCI 选项 `Threads` 默认已改为 1（`default 1`）。`set_num_threads()` 不再对 `Threads=1` 禁用 threading，引擎始终走 `find_best_move_smp` 路径。`Threads=4` 时引擎会创建 3 个 worker 线程（共 4 搜索线程），在 16 LP 上占 25% CPU。

**判定逻辑：**
- SPRT 接受 H1（损耗 ≥ 50 Elo）→ **该模块重要**，保持或优化
- SPRT 接受 H0（损耗 ≤ 10 Elo）→ **该模块贡献不大**，标记可删
- SPRT 未出结论 → 效应在 10-50 Elo 之间，需升 Tier 2 进一步确认

**注意：** 消融阶段只回答"这个模块有没有用"，不回答"这个改动涨不涨 Elo"。

### Tier 2 — 确认（standard，SPRT）

仅 Tier 1 通过的改动进入此阶段。

```powershell
cutechess-1.3.1-win64\cutechess-cli.exe `
  -engine name=Baseline proto=uci cmd=Hellcopter.exe option.Threads=1 `
  -engine name=Experiment proto=uci cmd=Hellcopter_mod.exe option.Threads=1 `
  -each tc=96+0.8 -rounds 100 -concurrency 2 `
  -draw movenumber=40 movecount=5 score=20 `
  -resign movecount=3 score=500 `
  -sprt elo0=-2 elo1=5 alpha=0.05 beta=0.10 `
  -pgnout results\confirm_YYYYMMDD_HHMM.pgn
```

**通过条件（必须同时满足）：**
- SPRT 接受 H1，或 Elo 估算 ≥ 0 且盘数 ≥ 100
- 输棋类型分布无系统性恶化（与 baseline 对比）
- 固定回归集重新运行全部通过

**一票否决条件：**
- Elo 下限 < -5
- 残局无力类输棋比例上升 > 10%
- 标准时控下时间崩溃率上升 > 3%

## 基线管理

### 基线定义

基线是当前公认"可信任的参考版本"。所有实验的 baseline 引擎由此构建。

### 基线维护方式

- 用 **git tag** 标识基线，不拷贝二进制：`git tag baseline-20260714 <commit>`
- 当前基线 tag 记录在 `configs/BASELINE`（纯文本，写 tag 名）

### 更新时机

当 **同一个改动** 满足以下所有条件时，更新基线：

1. Tier 1 快筛 + Elo（vs 老基线）≥ 5，LOS ≥ 95%
2. Tier 2 确认 + Elo（vs 老基线）≥ 3，LOS ≥ 90%
3. 输棋类型无系统性恶化
4. 固定回归集全部通过

**禁止：** 累计式更新（A 涨 3 Elo, B 涨 4 Elo，合起来不一定是 7）。每个 merge 必须与老基线直接对弈确认。

### 回滚条件

- Tier 0 回归失败 → 立即回滚到上一基线
- 新版本在 Tier 2 确认中 Elo 下限 < -5 （vs 当前基线）→ 回滚
- 连续 3 次实验"中局漏算"比例上升 → 排查模块，必要时回滚到问题出现前的基线

## 迭代日志

所有实验必须记录到 `EXPERIMENTS.md`。

### 格式要求

每条记录包含：

```
### YYYYMMDD_短描述

改动: 一行说清改了什么
目的: 一句话解释为什么改

T0 回归: 通过/失败
T1 快筛: 盘数, SPRT, ±Elo, LOS
  lmr_research: % → %
  ... (相关 Profile 变化)
T2 确认: 盘数, SPRT, ±Elo, LOS
  输棋归类: 各类型计数

判定: 保留/回滚/需再调
理由: 一句话
```

### 粒度控制

- **每轮实验一条**（不是每个 commit 一条）
- 如果一轮实验涉及同一组参数的多次微调（如 LMR base 扫描 5 个值），合并为一条，记录最优值
- 结构实验单独一条，注明改了什么 .c

### 避免的问题

| 陷阱 | 后果 | 对策 |
|------|------|------|
| 不记日志 | 下次改同参数不知之前结果 | 每轮必记 |
| 只记 Elo 不记 Profile | 不知为什么涨跌 | 至少记 3 个 Profile 指标 |
| 只记成功不记失败 | 不能排除重复踩坑 | 回滚的也保留 |

## A/B 自对弈方案

**当前状态：** 已完成。`run_match.py --mode self --config-a/--config-b` 已实现。

```powershell
run_match.py --mode self --config-a configs\v1.9.5.json --config-b configs\experiment.json --rounds 500 --tc 10+0.1 --sprt
```

实现方式：通过临时 UCI adapter 进程，每个 instance 绑不同 `ENGINE_PARAMS` 环境变量指向对应 JSON，无需复制二进制。

## Search Profile 指标

**当前状态：** 已实现。`engine_wrapper.get_search_profile(total_nodes)` 返回全部 20 个原始计数器 + 5 个导出指标。`option name nodes` 已加入 UCI 选项列表。

### 核心指标

| 指标 | 公式 | 信息 | 方向信号 |
|------|------|------|----------|
| lmr_research_rate | lmr_full_research / lmr_applied | LMR 过度缩减率 | ↓ 好（缩减准确） |
| nmp_efficiency | nmp_cutoffs / nmp_triggered | Null move 裁剪有效率 | ↑ 好 |
| qs_share | qs_nodes / total_nodes | QS 节点占比 | 太高中局战术弱 |
| tt_activity | tt_hits / (tt_hits + tt_stores) | TT 命中率 | ↑ 好 |
| aw_fail_rate | aw_fails / (aw_hits + aw_fails) | Aspiration 失败率 | ↓ 好 |
| avg_depth | total_nodes 分布反推 | 平均搜索深度 | ↑ 好（但需配合 qs_share） |

### 实验记录模板

每次改动必须记录：

```
实验编号: 20260714_lmr_delta_2
改动: LMR base 0.75 → 1.25, LMR delta 0.5 → 0.25
T0 回归: 通过
T1 快筛: 300 盘, SPRT 接受, +8±6 Elo, LOS 91%
  lmr_research: 18% → 14% (好)
  avg_depth: 14.2 → 13.8 (略降, 可接受)
T2 确认: 300 盘, +5±9 Elo, LOS 78%
  输棋归类: 中局漏算 4/10 (baseline 3/10), 残局 2/10 (baseline 2/10)
判定: 保留，但 LMR delta 需继续微调
```

## 输棋归类

### 五类标准

| 类型 | 特征 | 怀疑模块 |
|------|------|----------|
| 开局劣势 | 10 步内 eval < -100 | 开局库覆盖 / PST 校准 / time mgmt |
| 中局漏算 | 子力被吃 / 将杀漏看 | QS depth / SEE / futility / LMR 过度 |
| 残局无力 | 优势未能转化 | 残局缩放 / mop-up / king activity / passed pawn |
| 时间崩溃 | 超时或最后几步速降 | easy move 阈值 / panic mode / aspiration fail |
| 重复误判 | 优势局面主动三次重复 | contempt / 重复检测逻辑 |

### 归类规则

- 每场确认实验输棋提取前 5-10 步关键局面
- 按局面的 phase（opening / middlegame / endgame）和 material 分类
- 记录哪个模块最可能是根因
- 如果同一类型占比连续 3 次实验上升，该模块列为优先优化目标

## 参数实验规则

### 参数实验（改 JSON 即可）

允许改动的范围（每次只选一组）：

- LMR: base / delta / limit / history_div
- History: decay / max_bonus / threshold
- King safety: attack_weight / pawn_shield / open_file
- Time management: easy_move_threshold / panic_threshold / phase_factor
- Evaluation weight: bishop_pair / doubled_pawn / isolated_pawn / passed_pawn

**禁止：** 一次同时改两组不相关参数。

### 结构实验（改 .c）

允许改动的范围：

- 新增 / 删除剪枝条件
- 修改走法排序逻辑
- 调整评估函数结构

**前置条件：** 必须先过 Tier 0 回归集，再进 Tier 1 快筛。

**特殊规则：** 结构实验通过后，需要将对应参数提炼到 JSON 供后续参数实验使用，避免每次改结构都重新编译。

### 减法 ablation

关掉模块对比 baseline 是最快的定位手段：

```
实验 A: eval_king_safety = OFF
实验 B: eval_pawn_structure = OFF
实验 C: LMR = OFF
实验 D: history_pruning = OFF
```

如果关掉某项 Elo 不降（±3 以内），该项贡献未证实，应删除或重写。

## Texel 调参修复

**紧急程度：高。** 当前 `v1.9.5.json` 的 `tuning_metadata.error_reduction_percent = 0` 表明调参流程已失效。

修复路径：

1. **确认损失函数** — 当前用 MSE 还是 cross-entropy？如果是 MSE，确认梯度是否正确
2. **确认训练数据** — 数据是否足够多样？自对弈数据容易过拟合，需要混入外部大师对局
3. **确认可调参数范围** — 不要一次调太多。先从 bishop_pair 单参数验证流程收敛
4. **先做单参数验证** — 只调 bishop_pair，看调参能否收敛到合理值（经验值 40-60）
5. **再扩大范围** — 确认流程稳定后，逐步增加参数量

**预期 checkpoint：** 参数调优后，在快筛中至少观察到 +3 Elo 改善（否则说明数据或目标函数有问题）。

## 代码规范

- 关键路径的**不变量**、**剪枝前提**、**恢复状态逻辑**必须有注释。例如：`make_move` 后棋盘状态假设、TT 条目何时有效、NMP 恢复条件
- C 语言：C99 标准，unity build
- 搜索参数一致性：`engine_params.h`（编译期）与 `engine_params.json`（运行时）保持同步
- 参数实验只改 `engine_params.json` 或 `evolvable_params.json`
- 结构实验改 `.c`，但通过后必须将参数提炼到 JSON 供后续使用

## 实验隔离制度

1. **一次只改一组相关参数** — 违反此条，改动的归因能力归零
2. **数据驱动** — 不靠直觉判断，靠 Elo + Profile + 输棋归类
3. **先减法后加法** — 删除无效代码比添加新代码更重要。关掉某项不降 Elo → 删
4. **快筛慢确认** — 快筛 SPRT 淘汰噪音，确认 SPRT 验证真实收益
5. **归因优先** — 没有分类能力的改动不提交
6. **不信任直觉** — 每次改动必记三样：Elo、Profile、失败类型

## 优先级路线图

### 第 1 周：实验工具补全（已完成）
1. ✅ **SearchProfile Python 导出** — `engine_wrapper.get_search_profile(total_nodes)` 已实现
2. ✅ **A/B 自对弈** — `run_match.py --mode self --config-a/--config-b` 已实现
3. ✅ **固定回归脚本** — `regression.py` 一键验证 perft + 战术 + UCI

### 第 2 周（当前）：搜索 ablation

搜索技术全清单（共 26+ 项）：
- 框架: 迭代加深、PVS、Aspiration Windows
- 缩减: LMR、IIR
- 延伸: Check Ext、Singular Ext、Promotion Ext、Endgame Ext
- 裁剪: NMP、Razoring、RFP、Futility、SEE Pruning、History Pruning、LMP、ProbCut、Delta Pruning
- 辅助: IID、TT、SEE、QS、Syzygy TB
- 走法排序: MVV-LVA、Killers、Countermove/Followup、History/Cont/Capture History
- 评估: 20+ 组件
- 时间管理: Easy/Hard/Panic/Time Bank
- 多线程: Lazy SMP

#### 消融策略

**不逐一测 26 项**。按功能聚合为 8 组，每组独立开关，按敏感度排序执行：

| 序号 | 组 | 开关方式 | 预期 | 优先级 |
|------|-----|----------|------|--------|
| A | **LMR**（含 IIR） | JSON: lmr_enabled=false | 暴跌（核心） | ★★★ P0 |
| B | **NMP**（空步裁剪） | JSON: null_move_min_depth=99 | 大跌 | ★★★ P0 |
| C | **走法排序**（历史表/杀手/反制/延续/捕获） | JSON 逐个关 | 中跌 | ★★☆ P1 |
| D | **静态裁剪**（Razoring+RFP+Futility） | JSON 逐个关 | 小~中跌 | ★★☆ P1 |
| E | **SEE Pruning + Delta Pruning** | 需改 C 加开关 | 小跌 | ★☆☆ P2 |
| F | **LMP + History Pruning** | JSON 参数调极值 | 小跌 | ★☆☆ P2 |
| G | **ProbCut + Singular Ext** | 需改 C 加开关 | 微小 | ★☆☆ P2 |
| H | **延伸**（检查/唯一/升变/残局） | 需改 C 加开关 | 微小 | ★☆☆ P3 |

**每项流程**：T0 回归 → T1 快筛 100 盘 @ 10+0.2 SPRT → 记录 Profile → 判定
**最终确认（第 7 周合并）**：Tier 2 100 盘 @ 96+0.8 SPRT

**总预计耗时**：A+B=1 晚，C=1 晚，D+E=1 晚，F+G+H=1 晚 → 约 4 晚

**产出**：敏感度排序表，标明"哪个关了 Elo 不降 ← 删掉"

✅ **已完成**：全部 10 组消融实验（A-I）+ 多线程诊断，记录在 EXPERIMENTS.md。
消融结论：
- 核心贡献（关掉即暴跌）：走法排序（127 Elo）> LMP+History Pruning（100 Elo）> SEE 有 bug（86 Elo）> 静态裁剪（49 Elo）> LMR（48 Elo）> NMP（35 Elo）
- 无贡献（标记可删）：capture/continuation history、G 组（ProbCut+Singular+IID）、延伸
- 多线程：Threads=4 比 Threads=1 弱 56 Elo，锁单线程
- SEE 修复：see_prune_enabled 默认设为 false，发现阈值过激

### 第 2.5 周：多线程诊断 ✅

已确认 Threads=4 弱于 Threads=1（−56 Elo），锁单线程。待第 7 周专项排查。

### 第 3 周：LMR 参数调优
config merge bug 修复后重扫 3×3 网格完成。
最优: b0.75_d2.5（+23 Elo, LOS 91%）, b1.0_d2.5（+19 Elo, LOS 87%）。
确认 v1.9.5.json 的 lmr_divisor 已是 2.5，与基线一致 → 无需 LMR 改动。

### 第 4 周（跳过）：时间管理
优先级后调，先做评估减法。

### 第 5 周：评估减法（已完成）
P1 兵结构（关掉+4±16 → 已删代码）
P2 王安全（H1 接受 +156 Elo → 保留）
P3 机动性（关掉−22±97 → 已删）
P4 Hanging/in-check（关掉−23±100 → 已删）
P5 威胁探测（关掉+4±48 → 已删）
P6 残局评估（关掉−68±182 → 默认关闭 eval_endgame_enabled=0）

### 第 6 周：残局专项
EGTB 自动加载（3-5 子 Syzygy RTB 文件在 `EGTB/`），CCRL 显式允许。
KRK/KQK 强制胜势评估增强（base_win + 进度梯度）。
易走步残局标志位修复（tm->is_endgame 根据 npm 正确设置）。
残局收束测试 6/6 通过。

### 第 7 周（当前）：合并确认
前 5-6 周有效改动合并为标准时控确认：
- 保留：P2 王安全 + SEE 修正 + LMR b0.75_d2.0
- 删除：P3 机动性 / P4 Hanging / P5 威胁 / P6 残局评估 / capture+cont history / G 组扩展 / 延伸
- 修复：KRK/KQK 评估增强 / 残局标志位 / SEE 阈值 / 开局库默认关闭
- 排除：多线程（锁 Threads=1）
- 基线 v1.9.5 vs 实验（当前代码），SPRT(-2,5,0.05,0.10)，96+0.8

### 第 8 周：分析 + 规划
整理"最常见输棋模式排行榜"，决定下一轮主攻方向。
