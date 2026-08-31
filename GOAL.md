# 项目目标与长期约束（每次会话必读的最高约束文档）

> 本文件固化用户的全部长期要求。任何一次会话开始工作前必须先读本文件；
> 本文件与其他文档冲突时，以本文件为准。修改本文件需要说明理由并记录在 git 提交中。

## 一、最终目标（North Star）

在 **96+0.8s 时制**下、**不借助 opening books 和 EGTB** 的前提下，
战胜限制强度为 **Elo 3000 的 Velvet**，且对局结果的 **LOS（优越似然性）≥ 97%**。

## 二、阶段里程碑

| 阶段 | 目标 | 判定标准 |
|------|------|----------|
| M1 | 击败 Monarch 2005（约 2000 Elo） | 96+0.8 时制、无 book/EGTB、LOS ≥ 97%、盘数 ≥ 100 |
| M2 | 击败限制到约 2200 的 Velvet | 同上 |
| M3 | Velvet 限制档位每级递增，直至 3000 | 同上 |

## 三、工作纪律（用户明确要求，永久有效）

0. **资源使用纪律（2026-08-23 用户批评后新增，最高优先级）**：
   - 用户机器：8 核 16 线程 CPU、16GB 内存、8GB 显存。**用户不保证机器空闲**，
     任何时刻可能有其他应用在运行，禁止吃满全部性能。
   - 对局并发上限 **4**（= 8 个单线程引擎进程，约占一半逻辑线程；TT 固定 128MB/进程 →
     引擎内存合计 <1GB）。禁止 16 并发之类的满载配置。
   - 启动任何批量计算前先估算内存/进程/CPU 占用并在 EXPERIMENTS.md 条目中记录预算。
   - 长时间后台任务启动后必须主动检查系统负载反馈（如模型请求超载报错 = 立即降并发）。
   - 显存一律不动（引擎为 CPU 程序）。
1. **允许参考开源引擎**的代码与配置获取灵感，但**照抄照搬永远是下策**，禁止整段移植。
2. **借鉴必须留痕**：从外部项目获取灵感时，必须生成报告写明——借鉴了谁的什么项目、研究了其中哪一部分内容、新旧结果对比分析。报告写入 `EXPERIMENTS.md` 对应条目（格式：`参考来源:` 字段），重大借鉴另存 `docs/reports/`。
3. **遇到瓶颈优先分析→测试→验证**，禁止走捷径（包括但不限于：调低对手真实强度伪装胜利、用 book/EGTB 冒充棋力、挑选有利样本）。
4. **git 版本管理**：只本地提交，禁止推送远程。基线晋升、阶段达成等关键节点必须打 tag。
5. 所有实验记入 `EXPERIMENTS.md`；实验流程规范见 `CLAUDE.md`。
6. 基线晋升门槛（沿用 CLAUDE.md）：T1 Elo 下限>0 且 ≥300 局，或 SPRT 接受 H1；T2 确认通过后才更新 git tag 与 `configs/BASELINE`。

## 四、对手档案

- **Monarch 2005 v1.7**（M1 目标）：
  `test_engines/Monarch 2005/Monarch(v1.7)/Monarch(v1.7).exe`，UCI 协议。
- **Velvet v8.1.1**（M2+ 目标）：
  `test_engines/Velvet/velvet-v8.1.1-x86_64-avx2.exe`，UCI 协议。
  限强机制（已查证：GitHub mhonert/velvet-chess v8.0.0 release notes，2026-08-23）：
  - `setoption name UCI_LimitStrength value true` + `setoption name UCI_Elo value <1225..3000>`
  - M2 起步档：UCI_Elo 2200；此后按 200 一档递增至 3000
  - ⚠️ 对局必须显式设置 `SimulateThinkingTime value false`（否则 Velvet 模拟人类思考白白耗时间，
    影响公平性）与 `Style value Normal`（Risky 风格约 −25 Elo，非目标条件）
  - ⚠️ 官方声明 UCI_Elo 分值与真实 Elo 的映射未严格校准——M2 各档实测结果才是权威标定
- **比赛条件**：不加载 opening book（`dist/Goi5.1.bin` 仅限训练研究）、不加载 Syzygy EGTB；
  用独立 UCI exe 参赛，避免 Python 包装层引入变量。
  ⚠️ 已验证的干净环境：`arena/copter/`（仓库二级目录，EGTB 相对路径扫描落空、exe 同目录无 book）。
  从仓库根目录或一级子目录启动会自动加载 EGTB/book——**禁止**。

## 五、当前状态快照（每轮工作结束时更新此节）

- 快照日期: 2026-08-23（第 3 次更新）
- git HEAD: baseline-plus 分支（见 git log）
- **M1 标定第 1 轮已完成（未达标）**: 240 局 @96+0.8 →
  胜99/负84/和57, Elo +21.7±38.5, LOS 86.6% < 97% 门槛。
  输棋画像健康（速败仅 19%, 长局消耗为主）。PGN=arena/m1_monarch_20260823_2142.pgn
- **进行中→已裁决**: LMR d2.5 Tier1 快筛失败（250局, −33.5±31.4, LOS 1.8%）
  → 不晋升。教训入档：7 月网格结论跑在 scale300 环境上，在当前 scale60 引擎上
  **视为失效**，引用前必须重测
- **M1 统计续磨启动**: 同配置续跑 vs Monarch2005（run_m1.ps1 -rounds 700），
  与第 1 轮 240 局合并统计；预计需累计 ~920 局达 LOS97%，约 1.5~2 天
- **配置基线已固化**: arena/copter/engine_params.json = resolved(v1.9.5)+Threads1
  （tests/make_arena_config.py 生成; 与烘焙宏经节点数逐位验证等价）。
  根 engine_params.json 已同步清洗——此前含 ~40 个来源不明 eval 权重（已存档快照），
  Python 侧历史分析数据可信度存疑，重要结论需用干净配置复测
- [纠错] 前快照"M1 带 4 线程伤上阵"结论错误: 实测比赛条件本就单线程
  （探针: tests/probe_real_match_conditions.py）。setoption Threads 首搜前是空操作。
- [挂起-编译恢复后优先] SEE_PRUNE_DEPTH_SCALE 当前烘焙=60, 20260717 验证修复值=300
  （被头文件再生成覆盖丢失; loader 不解析该键无法运行时注入）。
  修复动作: src/engine_params.h 回 300 + params_loader 增加该键解析 + 重编译 + Tier0/T1
- M2 就绪度: run_m2.ps1 已修复路径/错误处理 bug 并实测同型脚本可跑通;
  Velvet 参数固化未变（UCI_LimitStrength/UCI_Elo/SimulateThinkingTime=false/Style=Normal）
- gcc 编译器在本机无法启动（疑似安全软件拦截，沙箱内无法解决）:
  参数实验不受影响（运行时 JSON）；源码改动全部挂起待编译恢复
- 待办: M1 跑完 → analyze_pgn --name Hellcopter + classify_losses → 登记 EXPERIMENTS.md
  → LOS≥97% 且 Elo≥+50 ⇒ 打 tag M1-achieved + configs/BASELINE 登记
  → `run_m2.ps1 -elo 2200`
