# 提升引擎棋力的完整技术报告

## 1. 总体状况分析

该引擎是一个典型的经典国际象棋引擎，实现了位棋盘、主变例搜索(PVS)、迭代加深、置换表(TT)、空着剪枝、LMR、Futility Pruning、Razoring（但被禁用）、静态交换评估(SEE)以及一套基于手工参数+PSQT的评估函数。搜索框架基本合理，但在**评估精度、移动排序、剪枝公式、时间管理、并行效率、代码工程化**等方面仍有许多可优化空间。在本报告中，我们将针对上述模块逐一提出可落地的改进方案，目标是大幅提升在2+1快棋时限（等效96秒+0.8秒增量）下的实际棋力，并充分利用8核CPU的算力。

## 2. 评估函数升级

当前评估函数完全依赖手工设计的分项，权重未经自动调优，导致整体精度不足。评估是引擎的“眼睛”，提升评估带来的Elo收益通常最稳定。

### 2.1 自动化参数调优 (Texel Tuning)
- **问题**：所有子力价值、PSQT表、兵结构奖惩、王安全项等均凭经验设定。
- **方案**：实施 **Texel调优**。将整个评估函数写成一个线性模型，使用带标签（游戏结果）的大量安静局面作为训练集，通过逻辑回归或线性回归最小化误差。调优目标为模型参数 `θ` 使得 `sigmoid(Eval(pos, θ))` 接近实际结果（1=白胜,0.5=和,0=黑胜）。
- **实施**：已有 JSON 加载机制，可生成带 `parameters` 的 JSON 作为初始参数，用梯度下降（或 ADAM）调优。重点调优对象：
  - `piece_values[1..6]`
  - `mg_pst[6][64]` 和 `eg_pst[6][64]`
  - 全部 `eval_weights`（bishop_pair、doubled_pawn 等）
  - 新增的 mobility 权重等。
- **预期收益**：+100 Elo 以上。

### 2.2 增加棋子灵活性 (Mobility)
- **缺失**：当前完全没有移动力评估。
- **方案**：为每个轻子/重子计算合法移动数或攻击格数，乘以权重（按阶段混合）。伪代码：
  ```c
  int mob = count_bits(get_attacks(b, sq, side) & ~own_pieces);
  score += sign * MobWeight[pt] * mob;
  ```
  其中 MobWeight 依子力变化，例如马 mobility 每格 4cp，象 3cp，车 2cp，后 1cp。可通过 texel 调优。为避免减速，可以只计算当前正评估的一方（即 side to move），或者进行快速近似（用攻击目标格数代替真实移动数）。通常在评估函数中计算所有棋子的 mobility 会明显提高准确性。
- **速度优化**：将 mobility 计算限制在中局阶段（phase > 8），残局阶段王活动更重要，可以省略部分。

### 2.3 兵结构哈希表 (Pawn Hash)
- **问题**：兵结构相关评估（叠兵、孤兵、通路兵、兵链、兵盾等）在每次评估时重新计算，成本高。
- **方案**：实现一个 256K 或 512K 条目的专用哈希表，以兵位棋盘（白兵+黑兵）为键，缓存兵结构打分、通路兵bonus数组、兵盾评分等。兵结构变化不频繁，命中率很高，可让评估快 30%～50%，从而允许更深搜索。
- **额外收益**：可以缓存通路兵的评估和威胁，为后续动态评估提供基础。

### 2.4 引入轻量 NNUE（可选但激进）
- **理由**：现代顶级引擎无一例外使用 NNUE 评估。即使在小网络上（比如 HalfKP 256x2→1），精度也远超手工评估。在 8 核 CPU 上仍可运行，因为 NNUE 使用增量更新非常快。
- **实现建议**：
  - 采用 **HalfKP** 特征（己方王格 + 己方棋子位置，视角对称）。输入层约 4 万个特征。
  - 网络结构：`Input(40960) → L1(256) → L2(32) → L1(32) → Output(1)` 并量化到 int16。
  - 增量更新：在 make/unmake 移动时维护当前活跃特征的差值，仅更新网络的前向计算。
  - 训练数据可从 self-play 生成，使用现有引擎进行对局，以 WDL 结果作为监督信号。
- **预期收益**：+300 Elo 以上（保守估计）。如果实现困难，可先用手工评估 + texel 调优获得大部分收益。

## 3. 搜索算法增强

搜索框架需要多方面的精细化调整，以更有效地分配搜索树资源。

### 3.1 移动排序强化
目前排序仅靠 TT move、MVV-LVA、killer、history、countermove/followup。现代引擎会加入更多启发式：

- **SEE 排序捕获**：不再单纯按 MVV-LVA，而是使用 `SEE(move) >= 0` 的捕获排在前面，`SEE < 0` 的“坏捕获”排在 quiet moves 之后（或靠后）。调整分数：好捕获基础 10^6 + MVV*10，坏捕获 10^5 + MVV*10。实现：
  ```c
  if (move.capture) {
      int see_score = see(b, move.from, move.to);
      if (see_score >= 0)
          move.score = 1000000 + see_score;
      else
          move.score = 200000 + see_score; // 落后安静走法
  }
  ```
- **历史启发改进**：使用 **butterfly history**（连续历史），存储 `history[from][to]`，再增加 **countermove history**，即对于前一移动 `prev`，维护 `cmh[prev_from][prev_to][piece][to]` 类似 Stockfish。在 LMR 缩减系数中利用这些历史值来动态调整 R。
- **Capture history**：记录某个移动捕获高价值目标的成功率，辅助排序。

### 3.2 LMR 公式优化
当前 `reduction = 1 + (int)(log(depth)*log(move_num) / 2.5)` 太粗糙。推荐采用类 Stockfish 的自适应公式：

```c
int r = (int)(0.5 + log(depth) * log(move_num) / 2.0);
// 根据历史和静态评估调整
if (historyValue > 0)
    r = max(r - 1, 0);
if (eval + margin > beta)  // 局面较好，少减
    r = max(r - 1, 0);
if (inCheck) r = max(r - 2, 0);
if (isKiller) r = max(r - 1, 0);
r = min(r, depth - 1); // 不能减到 <=0
```

- 对于深度低时（d <= 3），LMR 基本不起作用，移除阈值即可。
- 将 `log` 改为快速整数近似（预计算表 `log_table[64]`）。

### 3.3 空着剪枝 (Null Move) 动态化
- **问题**：固定 R 值 `NULL_MOVE_REDUCTION` 不灵活。
- **改进**：动态 R = 3 + depth / 4，残局再加 1。基于 `beta` 边界：若 `eval - beta > 200cp`（大优势），可再增加 R。实现：
  ```c
  int R = 3 + depth / 4 + is_endgame;
  if (eval - beta > 200) R++;
  ```
- **验证搜索**：当前当深度较深时进行验证 (`NULL_MOVE_VERIFICATION_DEPTH`)。这很昂贵，可以替换为**条件验证**：只有当 `null_score >= beta` 且 `depth >= 12` 时才在空着剪枝返回前做一次低深度验证（depth - R - 3），如果仍 fail-high 则直接截断。或者完全取消验证，因为 LMR 和 futility 已经可以补偿风险。

### 3.4 启用并校准 Razoring
- **现状**：`should_apply_razoring` 直接返回 0，被禁用。
- **启用**：条件：`depth <= 3`，`eval + razor_margin < alpha`。razor_margin 可以设为 `250 + 100 * depth`。若满足，直接返回 qsearch(alpha, beta)。这能在极浅深度下迅速剪枝。
- **收益**：可减少大量无效节点，尤其在安静局面。

### 3.5 引入后期走法剪枝 (Late Move Pruning, LMP)
- **应用场景**：在非 PV、非将、深度 `d <= 8` 的节点，如果已产生超过阈值数量的安静走法，则不再搜索剩余安静走法。阈值公式：`(2 + d * d) * 2`。
- 实现：在移动循环中，当 `i >= lmp_limit` 且移动不是捕获/升变/将军时，直接跳过。可安全剪枝。

### 3.6 置换表 (TT) 优化
- **持久化**：**不要在每次搜索中分配/释放 TT**。应在引擎启动时分配大块内存（如 128MB），并在整个对局过程中复用。搜索开始前递增 `generation` 来老化数据，而不是清零。这样可以保留深层信息。
- **替换策略**：采用双桶（每索引存两个条目），优先替换深度更浅或generation更老的条目。伪代码：
  ```c
  if (bucket1.key == key) use it; else if (bucket2.key == key) use it;
  else replace the one with smaller depth * 8 + generation_age.
  ```
- **无锁设计**：并行搜索时，对 TT 写入可以考虑不对齐数据造成的撕裂，但必须确保引擎不崩溃。使用 `_mm_pause()` 等无锁技巧，或使用 128 位原子操作（如果编译器支持）来原子写入 key+score+depth 等关键字段。当前 Lazy SMP 容忍一定程度的损坏，但可能引发搜索不稳定，建议至少使用 `atomic_compare_exchange` 或 `volatile` 控制。

### 3.7 静态交换评估 (SEE) 与剪枝
- **QS 剪枝强化**：当前对捕获使用 SEE < 0 剪枝，很好。可进一步，在安静局面且非将军时，对 **SEE < 0** 的捕获直接跳过，不必排序。还可对 **SEE 很低** 的捕获降低 LMR 缩减速。
- **SEE 利用**：移动排序已建议用 SEE 区分好/坏捕获。

## 4. 时间管理策略

现用的 `elapsed >= time_limit * 0.6` 过于简陋，导致时间利用低效。

### 4.1 动态时间分配
- **思想**：为每一步分配理想时间 `opt_time`，基于剩余时间、阶段平均剩余步数（通常 40 步）和增量。
  ```c
  int moves_left = 40; // 可动态估计，如 max(10, 50 - moveNumber)
  double base_time = remaining_time / moves_left + increment;
  double max_time = base_time * 2.5;
  double opt_time = base_time * 0.8;
  ```
- **实施**：搜索开始前设定 `s.max_time = get_time() + opt_time`。在迭代加深循环中，每完成一个深度，检查是否超过 `opt_time`，若超过且最佳移动稳定，可以提前退出。若搜索超过 `max_time`，强制停止。

### 4.2 简单移动检测 (Easy Move)
- 当某步移动的评估比次优移动高出一定阈值（如 150cp），且深度达到一定（如 depth >= 6），则立即停止搜索并返回该步。可节省大量时间用于复杂局面。

### 4.3 节点时间管理
- 除了时间，可监测节点数。若在 `opt_time` 用完前节点数已超过预期（如 100M），并且最佳移动与上一深度一致，可提前退出。

## 5. 并行搜索 (Lazy SMP) 提升

当前 Lazy SMP 实现基础，改进潜力大。

### 5.1 线程多样性
- **不同深度搜索**：辅助线程从不同的起始深度或不同的 depth step 开始搜索，例如主线程从 depth=1 正常迭代，辅助线程 1 从 depth=2 开始，辅助线程 2 从 depth=3 等，增加异构性。
- **参数扰动**：给每个线程稍有不同的 LMR/Futility 参数（如增加 0~2 的 reduction），使树形各异，更易发现更好的移动。

### 5.2 共享哈希表的无锁处理
- 尽量减少竞争：使用 multiple buckets，每个线程写入时使用 `__atomic_compare_exchange` 只更新一个桶，避免使用全局锁。
- 或者接受少量错误，但务必保证 `key` 和 `score` 写入的原子性：将 TT entry 的前 8 字节改为 key，后 8 字节为 score+depth+flag 组合，使用 64 位原子写入，这样至少不会读出完全不相关条目。

### 5.3 提前终止
- 当主线程搜索完 best_move 并且时间用尽，立即通知所有辅助线程停止（已有的 `g_smp_stop_flag` 可以），然后主线程不等它们完成就返回。当前代码是在主线程结束后才等待辅助线程，这会浪费时间。可以改为等待有限时间，或者直接 detach 辅助线程（POSIX），Windows 可用 `TerminateThread`（不推荐），最好只是设置标志并快速 join，或使用非阻塞的循环检查。

## 6. 代码性能优化

### 6.1 魔法位棋盘
- 当前滑动攻击可能使用了 `sliding_attacks_bishop/rook`，推测是基于 `while` 循环的射线计算，速度较慢。实现标准魔法位棋盘，预计算攻击表（总计约 100KB），能让移动生成和攻击计算提速 3-5 倍。

### 6.2 预计算与查找表
- 检查 `knight_attacks` 和 `king_attacks` 是否已有，确保持久化。为 `file_masks`, `rank_masks` 提供数组。
- 评估函数中的 `phase` 映射表可预计算到数组 `phase_to_weight[32]`。

### 6.3 减少重复计算
- 在 `evaluate()` 内，`count_bits` 等多次调用。如果引入兵哈希，可省去重复兵结构计算。对于王安全评估，也建议缓存盾牌评分。

### 6.4 编译器优化与内存布局
- 确保 `Board` 结构体对齐到 64 字节，使用 `__attribute__((aligned(64)))`，位棋盘数组为 `U64`。
- 将常用的 `pieces[side][piece]` 访问放在结构体开头。
- 开启 `-O3 -march=native`，利用 `POPCNT` 等指令。

## 7. 调优与测试流程

### 7.1 本地测试框架
- 使用 **fastchess** 或 **cutechess-cli** 进行自动对局测试，配合时间控制 `2+1`。
- 构建 Elo 计算系统，利用 SPRT 判断补丁有效性。

### 7.2 参数调优
- **SPSA** 可用于同时调整数十个搜索参数（LMR 公式常数、FP margin、NMR 等），大约需要几万局。
- 对于评估权重，首选 Texel tuning。

### 7.3 渐进式引入
1. 工程优化（魔法位棋盘、持久TT、兵哈希） → 获得速度与深度。
2. 搜索参数调优（LMR、NMP、LMP） → 约 +50 Elo。
3. 评估调优（Texel） → +100 Elo。
4. 更多评估特征（mobility、安全增强） → +30-50 Elo。
5. 时间管理优化 → 实际对局胜率 +20-30 Elo。
6. 并行搜索改进 → 利用多核心再加 30-50 Elo。

## 8. 结语

该引擎具备良好的基础，通过上述一系列深度优化，在相同硬件和时限下，棋力预期可提升 300~500 Elo。最关键的三步是：**实现魔法位棋盘与持久化 TT**（立即提速）、**texel 调优评估参数**（大幅提高准确性）、**重写时间管理**（提高实战胜率）。如果进一步集成轻量 NNUE，将进入顶级业余引擎行列。所有建议均基于该引擎的代码结构，具备高度可行性。