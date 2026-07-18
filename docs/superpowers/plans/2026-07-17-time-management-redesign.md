# 时间管理系统重构实现计划

> **面向 AI 代理的工作者：** 必需子技能：subagent-driven-development（推荐）或 executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 重写时间管理系统，解决"平均分配时间"的根本缺陷，改用阶段感知分配 + 增强关键局面检测 + 扩容时间银行。

**架构：** 只修改 `engine_search_root.c` 中的 `init_time_manager()` 和根搜索循环中的时间调整逻辑。所有时间管理参数均为编译期定义（`engine_params.h`），JSON 不加载时间参数。不修改其他文件。

**技术栈：** C99, unity build, MSVC/Clang

**测试方法：** `src/build_engine.py` 编译 → `depth_test.py` 验证单步耗时 → UCI 对弈观察时间分配

---

### 任务 1：阶段感知分配（替换 estimated_moves）

**文件：**
- 修改：`src/engine_search_root.c:161-243`（init_time_manager 函数）
- 修改：`src/engine_search_root.c:2188-2223`（SMP 路径的重复公式）
- 修改：`src/engine_params.h:508-542`（替换 EST_MOVES 常量，添加新常量）

- [ ] **步骤 1：在 engine_params.h 中添加新常量，保留旧常量备用**

在 `EST_MOVES_BY_MATERIAL` 和 `EST_MOVES_MATERIAL_THRESHOLDS` 之后添加：

```c
/* 阶段感知时间分配常量（最终取代 EST_MOVES_BY_MATERIAL） */
#define PHASE_OPENING_MOVES_REMAINING 20   /* 开局：预留 20 步的份量 */
#define PHASE_MIDGAME_MOVES_REMAINING 12   /* 中局：每步拿 1/12 剩余时间 */
#define PHASE_ENDGAME_MOVES_REMAINING 20   /* 残局：保守 */
#define PHASE_OPENING_MAX_MOVE 12          /* move_number <= 12 为开局 */
#define PHASE_MIDGAME_MAX_MOVE 30          /* move_number <= 30 为中局 */
#define PHASE_BASE_MAX_TIME_FRACTION_NUM 1 /* max_time = time_left * 1/3 */
#define PHASE_BASE_MAX_TIME_FRACTION_DEN 3
```

- [ ] **步骤 2：重写 init_time_manager() 中的 estimated_moves 逻辑**

用阶段感知分配替换原有的 EST_MOVES_BY_MATERIAL 表查询。在 `engine_search_root.c:198-217` 处替换：

```c
/* 阶段感知分配：根据 move_number 选择所在阶段，各阶段有独立预估步数 */
int estimated_moves;
if (moves_to_go > 0)
{
    estimated_moves = moves_to_go;
}
else if (move_number <= PHASE_OPENING_MAX_MOVE)
{
    /* 开局：预留足够步数 */
    estimated_moves = PHASE_OPENING_MOVES_REMAINING;
}
else if (move_number <= PHASE_MIDGAME_MAX_MOVE)
{
    /* 中局：关键阶段，每步获得更多时间 */
    estimated_moves = PHASE_MIDGAME_MOVES_REMAINING;
}
else
{
    /* 残局：保守剩余步数 */
    estimated_moves = PHASE_ENDGAME_MOVES_REMAINING;
}

tm->optimal_time = time_left / estimated_moves + inc * OPTIMAL_TIME_INC_FRACTION_NUM / OPTIMAL_TIME_INC_FRACTION_DEN;
tm->max_time = time_left * PHASE_BASE_MAX_TIME_FRACTION_NUM / PHASE_BASE_MAX_TIME_FRACTION_DEN;
if (tm->max_time > tm->optimal_time * MAX_TIME_OPTIMAL_MULTIPLIER)
    tm->max_time = tm->optimal_time * MAX_TIME_OPTIMAL_MULTIPLIER;
```

保留 extreme pressure 处理逻辑（time_left < 1.0 时的保护）和 MIN_OPTIMAL_TIME_MS 下限。

- [ ] **步骤 3：移除 per-iteration safety_cap 二次限缩**

在 `engine_search_root.c:1319-1329`，删除 safety_cap 计算和使用逻辑（约 11 行）。让迭代内 time_limit 只受 max_time 约束，不再有第二次限缩。

```c
/* 移除 — 单一上限 max_time 已在 init_time_manager 中保障，不再二次限缩 */
```

- [ ] **步骤 4：同步更新 SMP 路径中的时间公式**

在 `engine_search_root.c:2190-2217`，做同样替换。

- [ ] **步骤 5：编译验证**

```powershell
python src/build_engine.py --force
```

期望：编译通过，无 warning。

- [ ] **步骤 6：运行深度测试**

```powershell
python E:\world\python\chess\depth_test.py
```

期望：引擎正常搜索，无 crash。

- [ ] **步骤 7：提交**

```powershell
git add src/engine_search_root.c src/engine_params.h
git commit -m "time: 阶段感知分配 + 移除 safety_cap 二次限缩"
```

---

### 任务 2：增强关键局面检测

**文件：**
- 修改：`src/engine_search_root.c:105-159`（compute_criticality_score）
- 修改：`src/engine_search_root.c:1331-1379`（criticality 使用逻辑）

- [ ] **步骤 1：新增三个检测信号**

```c
static int compute_criticality_score(const TimeManager *tm, int current_score, int prev_score,
                                     int best_move_changed, int aw_fails_this_iter,
                                     long long nodes_this_iter, int legal_moves_count)
{
    int score = 0;

    /* Signal 1: Best move instability (weight 25) */
    if (best_move_changed)
        score += 25;
    else if (tm->instability_count >= 2)
        score += 12;

    /* Signal 2: Aspiration window failures (weight 20) */
    if (aw_fails_this_iter >= 3)
        score += 20;
    else if (aw_fails_this_iter >= 1)
        score += 8 + aw_fails_this_iter * 4;

    /* Signal 3: Node explosion (weight 15) */
    if (tm->nodes_last_iter > 0)
    {
        long long ratio = nodes_this_iter / (tm->nodes_last_iter + 1);
        if (ratio >= 5)
            score += 15;
        else if (ratio >= 3)
            score += 10;
        else if (ratio >= 2)
            score += 5;
    }

    /* Signal 4: Top 2 moves close (weight 10) */
    if (prev_score > -MATE_SCORE + 1000)
    {
        int top2_gap = abs(current_score - prev_score);
        if (top2_gap < 10)
            score += 10;
        else if (top2_gap < 25)
            score += 5;
    }

    /* Signal 5: Static eval vs search score divergence (weight 10) */
    {
        int divergence = abs(tm->root_eval - current_score);
        if (divergence > 150)
            score += 10;
        else if (divergence > 80)
            score += 5;
    }

    /* Signal 6: 合法走法 ≤ 3 → 强制局面（weight 20） */
    if (legal_moves_count >= 1 && legal_moves_count <= 3)
        score += 20;
    else if (legal_moves_count <= 5)
        score += 8;

    /* Signal 7: 中局相位 +10（weight 10） */
    if (!tm->is_endgame)
        score += 10;

    /* Signal 8: 战术密度 — 走法列表中吃子/将军比例（weight 15）
     * 通过 nodes_this_iter 与 legal_moves_count 的比值估算战术复杂性 */
    if (legal_moves_count > 0)
    {
        long long nodes_per_move = nodes_this_iter / legal_moves_count;
        if (nodes_per_move > 5000)
            score += 15;
        else if (nodes_per_move > 2000)
            score += 8;
    }

    if (score > 100)
        score = 100;
    return score;
}
```

- [ ] **步骤 2：调整 criticality 使用阈值**

```c
/* 关键局面（score >= 55）：使用 max_time + 银行取款 */
if (crit >= 55)
{
    double crit_limit = tm.max_time;
    double withdraw = tm.time_bank * 0.5;
    if (withdraw > 2.0)  /* 取款上限从 0.5s 升到 2.0s */
        withdraw = 2.0;
    crit_limit += withdraw;
    if (time_limit < crit_limit)
        time_limit = crit_limit;
    tm.critical_position_flag = 1;
    tm.time_bank -= withdraw;
    if (tm.time_bank < 0)
        tm.time_bank = 0;
}
/* 较复杂（score >= 25）：使用 optimal * 2.5 */
else if (crit >= 25)
{
    double mod_limit = tm.base_optimal_time * 2.5;
    if (time_limit < mod_limit)
        time_limit = mod_limit;
    tm.critical_position_flag = 0;
}
```

- [ ] **步骤 3：编译验证**

```powershell
python src/build_engine.py --force
```

期望：编译通过。

- [ ] **步骤 4：回归测试**

```powershell
python E:\world\python\chess\regression.py
```

期望：perft + 战术 + UCI 全部通过。

- [ ] **步骤 5：提交**

```powershell
git add src/engine_search_root.c
git commit -m "time: 增强关键局面检测（强制局面/中局权重/战术密度）"
```

---

### 任务 3：时间银行扩容

**文件：**
- 修改：`src/engine_search_root.c:1362-1373`（存款逻辑）
- 修改：`src/engine_search_root.c:1341-1352`（取款逻辑）

- [ ] **步骤 1：扩容存款上限和取款上限**

存款部分（`engine_search_root.c:1362-1373`）：
```c
/* Simple position: save time to bank */
double simple_limit = tm.base_optimal_time * 0.85;
double saved = time_limit - simple_limit;
if (saved > 0.05)
{
    tm.time_bank += saved * 0.7;  /* 存款比例 50% → 70% */
    if (tm.time_bank > tm.base_optimal_time * 8.0)  /* 上限 ×3 → ×8 */
        tm.time_bank = tm.base_optimal_time * 8.0;
    time_limit = simple_limit;
}
```

取款部分已在任务2步骤2中修改。

- [ ] **步骤 2：编译并运行回归**

```powershell
python src/build_engine.py --force; python E:\world\python\chess\regression.py
```

- [ ] **步骤 3：提交**

```powershell
git add src/engine_search_root.c
git commit -m "time: 时间银行扩容（存款上限×8, 取款上限2s, 存款比例70%）"
```

---

### 任务 4：简化 Easy Move 逻辑

**文件：**
- 修改：`src/engine_search_root.c:1234-1253`（easy move）

- [ ] **步骤 1：修改 easy move 条件**

```c
/* Easy move: stable for 4+ iterations, score change < 10cp
 * 不再提前终止搜索，只设置为不增加时间预算（normal multiplier 1.0x） */
{
    int easy_condition = 0;
    if (tm.stable_count >= 4 && abs(current_score - prev_score) < 10)
        easy_condition = 1;

    if (easy_condition && max_depth <= 0)
    {
        /* Easy: don't boost time, stay at base_optimal * 1.0
         * (instead of the normal 1.1x or higher) */
        time_limit = tm.base_optimal_time;
        /* Still apply safety cap for protection */
        s->time_limit = time_limit;
    }
}
```

- [ ] **步骤 2：编译验证**

```powershell
python src/build_engine.py --force
```

- [ ] **步骤 3：提交**

```powershell
git add src/engine_search_root.c
git commit -m "time: easy move 改为不增压（不再提前终止），稳定要求 3→4"
```

---

### 任务 5：Tier 0 回归验证

**文件：** 无代码修改

- [ ] **步骤 1：运行回归测试**

```powershell
python E:\world\python\chess\regression.py
```

期望：全部通过。

- [ ] **步骤 2：运行深度测试对比**

```powershell
python E:\world\python\chess\depth_test.py
```

期望：单步耗时合理增加。

- [ ] **步骤 3：运行 A/B 自对弈快速验证**

```powershell
python run_match.py --mode self --config-a configs\v1.9.5.json --config-b configs\v1.9.5.json --rounds 50 --tc 10+0.2 --concurrency 2
```

期望：自对弈不出错，时间分配合理，不超时。

---

## 执行选项

计划已完成并保存到 `docs/superpowers/plans/2026-07-17-time-management-redesign.md`。两种执行方式：

**1. 子代理驱动（推荐）** - 每个任务调度一个新的子代理，任务间进行审查，快速迭代

**2. 内联执行** - 在当前会话中使用 executing-plans 逐任务实现，批量执行并设有检查点
