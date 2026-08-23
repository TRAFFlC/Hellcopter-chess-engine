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

- 快照日期: 2026-08-23
- git HEAD: f433b4e 之后（含 180e615 material-depth bonus、693990b UCI/mobility 修复）
- 最近补录实验: 20260719_baseline_plus_recovery —— 自对弈 191 局 +21.9±12 Elo, LOS 82.7%（未达晋升门槛，方向积极）
- M1 进度: 未开始正式标定（下一步：Hellcopter vs Monarch 2005 @ 96+0.8）
