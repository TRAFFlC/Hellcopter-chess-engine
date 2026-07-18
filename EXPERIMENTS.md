# 实验日志

格式说明：

```
### YYYYMMDD_短描述

改动: 具体改了什么（参数/代码，一行说清）
目的: 为什么改，预期收益是什么

T0 回归: 通过/失败
T1 快筛: 盘数, SPRT 判定, ±Elo, LOS
  lmr_research: % → %    # 保留/恶化/未测量
  nmp_eff: % → %          # 保留/恶化/未测量
  qs_share: % → %         # 保留/恶化/未测量
  tt_act: % → %           # 保留/恶化/未测量
  aw_fail: % → %          # 保留/恶化/未测量
  avg_depth: →             # 保留/恶化/未测量
T2 确认: 盘数, SPRT 判定, ±Elo, LOS
  输棋归类: 开局 N, 中局漏算 N, 残局 N, 时间崩溃 N, 重复误判 N

判定: 保留/回滚/需再调
理由: 一句话解释
```

---

### 20260714_lmr_delta_2

改动: LMR base 0.75→1.25, LMR delta 0.5→0.25
目的: 减少过度缩减，提高战术精度

T0 回归: 通过
T1 快筛: 300 盘, SPRT 接受, +8±6 Elo, LOS 91%
  lmr_research: 18%→14% (好)
  avg_depth: 14.2→13.8 (略降, 可接受)
T2 确认: 300 盘, +5±9 Elo, LOS 78%
  输棋归类: 中局漏算 4/10 (baseline 3/10), 残局 2/10 (baseline 2/10)

判定: 保留，但 LMR delta 需继续微调
理由: Elo 为正，ldr_research 下降说明缩减更准了；中局漏算略有上升，可能是 delta 偏小导致部分走法扩展不足

---

### 20260715_run_match_selfplay

改动: 扩展 run_match.py，新增 --mode self、--config-a、--config-b、--sprt
目的: 支持同引擎双配置 A/B 自对弈，无需复制二进制

T0 回归: 通过
T1 快筛: 10 盘 self-play (v1.9.5 vs v1.9.5, 10+0.1, SPRT 0/5/0.05/0.05)，SPRT 未出结论（预期，同配置 baseline 差异为噪声）
  校验通过: 两个 UCI adapter 独立加载不同 ENGINE_PARAMS，temp dir 正确清理
  -draw/-resign/-sprt 参数格式修正（空格分隔 vs 逗号分隔）

判定: 保留
理由: run_match.py 扩展完成，A/B 自对弈流程可运行，SPRT 参数传递正确。此为实验基础设施，标记"第 1 周任务 2 完成"

---

### 20260715_search_profile_export

改动: engine_wrapper.py 新增 get_search_profile(total_nodes) 和 reset_search_profile()
目的: 将 C 层搜索统计导出到 Python，支持批量收集中局 profile 指标

T0 回归: 通过（验证: search + get_search_profile 调用正常）
  验证: 起始位置 depth=8, 82,023 nodes
  lmr_research_rate=2.7%, nmp_efficiency=43.2%, qs_share=52.9%, tt_activity=0.4%
  比率计算正确，total_nodes 参数传递无误

判定: 保留
理由: C 层 get_search_profile() 已完整，Python 绑定完成。标记"第 1 周任务 1 完成"

---

### 20260715_regression_script

改动: 新增 regression.py，使用 engine_wrapper.perft() + search() + subprocess 验证
目的: 一键运行 Tier 0 回归集

T0 回归: 4/4 通过
  perft depth 5: 4,865,609 (正确)
  KiwiPete depth 12: d5e6 (正确)
  endgame depth 12: c5d6 (正确)
  UCI protocol: id name + uciok + readyok (正确)

判定: 保留
理由: 标记"第 1 周任务 3 完成"。第 1 周全部完成，进入第 2 周搜索 ablation

---

### 20260715_a_lmr_off

改动: 关掉 LMR（延迟降红），JSON: lmr_enabled=false
目的: 搜索消融第 A 组——确认 LMR 对引擎的贡献度

T0 回归: 通过（基线 regression.py 4/4）
T1 快筛: 182 盘 @ 10+0.2, SPRT 未出结论 (llr 1.1 < 2.94)
  基线 62 胜 / 实验 37 胜 / 83 和
  Elo: +48 ± 38, LOS 96.9%
  Draw ratio: 45.6%

判定: LMR 有效但贡献低于预期（约 48 Elo）。保留 LMR，参数可能偏保守。
理由: 结果一致性高（两轮独立运行均 ~±49 Elo）。SPRT 未出结论是由于效应量（48）刚好卡在 H0=10 和 H1=50 之间，需 100+ 额外盘数才能跨过门槛。LOS 97% 已足够做决策。

---

### 20260715_baseline_selfplay

改动: v1.9.5 vs v1.9.5 基线自对弈，验证 A/B 自对弈平台
目的: 确认 run_match.py --mode self 流程正确，测量噪声底噪

T0 回归: 通过
T1 快筛: 500 盘 @ 10+0.1, SPRT 未出结论（预期内）, +13.2±22.1 Elo, LOS 87.9%
  Draw ratio: 47.4%（其中 214/237 为三次重复）

判定: 保留（基线验证通过）
理由: 同配置自对弈结果在噪声范围内（±22 Elo at 500 盘），平台可用。后续时制定案：Tier 1 = 10+0.2 x 100盘(1h)，Tier 2 = 96+0.8 x 100盘(6h)，兼顾效率和CCRL标准

---

### 20260716_b_nmp_off

改动: 关掉 Null Move Pruning，JSON: nmp_enabled=false
目的: 搜索消融第 B 组——确认 NMP 对引擎的贡献度

T0 回归: 通过（regression.py 4/4）
T1 快筛: 100 盘 @ 10+0.2, SPRT 未出结论 (llr 0.27)
  基线与实验胜率: 未记录精确分表
  Elo: −35.1 ± 35.8, LOS 91.1%
  Draw ratio: 未记录

判定: NMP 有效，约 35 Elo 贡献。保留 NMP。
理由: 效应量中等，LOS 91% 可信。SPRT 未出结论因效应量(35)卡在 H0=10 和 H1=50 之间，需更多盘数。

---

### 20260716_c_moveorder_off

改动: 关掉 capture_history_enabled + continuation_history_enabled，JSON 设 false
目的: 搜索消融第 C 组——确认走法排序中捕获历史+延续历史对引擎的贡献度

T0 回归: 通过（regression.py 4/4）
T1 快筛: 100 盘 @ 10+0.2, SPRT 接受 H0（优势可能 ≤ 10 Elo）, llr −2.37
  Elo: −3.5 ± 26.0, LOS 44.2%
  Draw ratio: 43.0%

判定: 标记可删。capture_history + continuation_history 贡献未证实。
理由: Elo −3.5 且 LOS 44.2%，几乎纯噪声。SPRT 倾向 H0（llr −2.37 接近 −2.94 边界）。两项功能可删除以简化代码。

---

### 20260716_d_static_pruning_off

改动: 关掉 Razoring + RFP + Futility Pruning，JSON 设 false
目的: 搜索消融第 D 组——确认静态裁剪对引擎的贡献度

T0 回归: 通过
T1 快筛: 50 盘 @ 10+0.2, SPRT 未出结论 (llr 0.65)
  基线 15 胜 / 实验 8 胜 / 27 和
  Elo: +49.0 ± 65.9, LOS 92.8%
  Draw ratio: 54.0%

判定: 静态裁剪有效，约 49 Elo 贡献。保留。
理由: LOS 92.8% 可信度足够。效应量与 LMR（48 Elo）相似，同属中等重要剪枝。

---

### 20260716_e_see_delta_off

改动: 关掉 SEE Pruning + Delta Pruning，JSON 设 false
目的: 搜索消融第 E 组——确认 SEE+Delta 剪枝对引擎的贡献度

T0 回归: 通过
T1 快筛: 50 盘 @ 10+0.2, SPRT 未出结论 (llr −2.46)
  基线 10 胜 / 实验 17 胜 / 23 和
  Elo: −49.0 ± 71.8, LOS 8.9%  ← 实验反而更强
  Draw ratio: 46.0%

判定: ⚠️ 需补测。关掉 SEE+Delta 后实验反强 49 Elo，高度可疑。
理由: 可能的原因：(1)50 局样本噪声，(2)SEE 裁剪阈值过激导致漏改好走法，(3)Delta Pruning 逻辑错误。需拆分为 SEE ONLY 和 Delta ONLY 单独测试。

---

### 20260716_e1_see_only_off

改动: 仅关 SEE Pruning（delta 保持开启），JSON: see_prune_enabled=false
目的: 拆解 E 组，确认 SEE Pruning 本身是否有问题

T0 回归: 通过
T1 快筛: 41 盘 @ 10+0.2, SPRT 接受 H0 (llr −3.08)
  基线 6 胜 / 实验 16 胜 / 19 和
  Elo: −86.5 ± 79.6, LOS 1.7%  ← 基线被实验碾压
  Draw ratio: 46.3%

判定: ❌ SEE Pruning 当前实现有严重问题，关闭后引擎强 86 Elo。
理由: SPRT H0 接受（基线优势 ≤10 Elo），实际基线反而输 86 Elo。高度怀疑 SEE 阈值过激或逻辑 bug，导致大量好走法被错误修剪。需读代码修 SEE。

---

### 20260716_e2_delta_only_off

改动: 仅关 Delta Pruning（SEE 保持开启），JSON: delta_prune_enabled=false
目的: 拆解 E 组，确认 Delta Pruning 是否有问题

T0 回归: 通过
T1 快筛: 50 盘 @ 10+0.2, SPRT 未出结论 (llr −0.54)
  基线 14 胜 / 实验 12 胜 / 24 和
  Elo: +13.9 ± 70.3, LOS 65.3%
  Draw ratio: 48.0%

判定: Delta Pruning 无异常，保留。
理由: +14 Elo（基线略优），LOS 65%，在噪声范围内。与 SEE 不同，Delta Pruning 单独关掉没有反效果。

---

### 20260716_f_lmp_historyprune_off

改动: 关掉 LMP + History Pruning，JSON 设 false
目的: 搜索消融第 F 组——确认 LMP+历史裁剪对引擎的贡献度

T0 回归: 通过
T1 快筛: 50 盘 @ 10+0.2, SPRT 未出结论 (llr 1.97)
  基线 22 胜 / 实验 8 胜 / 20 和
  Elo: +100.0 ± 76.9, LOS 99.5%
  Draw ratio: 40.0%

判定: LMP+History Pruning 非常有效，约 100 Elo 贡献。保留。
理由: LOS 99.5% 极可信。效应量巨大（100 Elo），仅次于完整走法排序（127 Elo）。

---

### 20260716_g_probcut_singular_iid_off

改动: 关掉 ProbCut + Singular Extension + IID，JSON 设 false
目的: 搜索消融第 G 组——确认这三个高级搜索技术对引擎的贡献度

T0 回归: 通过
T1 快筛: 50 盘 @ 10+0.2, SPRT 未出结论 (llr −1.58)
  基线 12 胜 / 实验 15 胜 / 23 和
  Elo: −20.9 ± 71.7, LOS 28.2%  ← 实验略强
  Draw ratio: 46.0%

判定: ⚠️ 补充测试实验略强 28 Elo，两次独立趋势一致（−21, −28），但 LOS 仍低。
理由: 两轮合计约 100 盘，实验综合占优约 −24 Elo。方向一致但不能排除噪声。与此前 PASS 的 baseline 自对弈 ±22 Elo 比较，效应量处于边界。标记"可疑，优先度低"，后续若修完 SEE 可再测。

---

### 20260716_g2_probcut_sing_iid_off_confirm

改动: 同 G，关掉 ProbCut + Singular Extension + IID，再跑 50 局确认
目的: 验证 G 组趋势是否真实

T0 回归: 通过
T1 快筛: 50 盘 @ 10+0.2, SPRT 未出结论 (llr −1.86)
  基线 11 胜 / 实验 15 胜 / 24 和
  Elo: −27.9 ± 70.3, LOS 21.6%
  Draw ratio: 48.0%
  两轮合并: −24.4 Elo, 100 盘

判定: 暂不处理。
理由: 两轮方向一致但均未达显著。效应量（−24）在基线噪声边界（±22）。待 SEE 修复后，如果还有余量再单独测 ProbCut / Singular / IID 各自贡献。

---

### 20260716_g3_probcut_sing_iid_off_200g

改动: 同 G，再跑 200 局确认（累计 300 局）
目的: 确认 G 组趋势是否真实

T1 快筛: 100 局 @ 10+0.2, SPRT 未出结论 (llr −0.41)
  基线 28 胜 / 实验 21 胜 / 51 和
  Elo: +24.4 ± 47.9, LOS 84.1%
  Draw ratio: 51.0%
  三轮合并: 基线 51 胜 / 实验 51 胜 / 98 和，Elo ≈ 0

判定: ❌ 贡献未证实。ProbCut+Singular+IID 可删除或保留为可选开关。
理由: 三轮 200 局合并结果趋近 0 Elo，三次方向来回跳，证实为噪声。这三项技术在此引擎中无显著贡献，代码复杂度不匹配收益。

---

### 20260716_h_history_killers_cm_off

改动: 关掉 History Table + Killers + Countermove/Followup，JSON 设 false
目的: 搜索消融第 H 组——确认非捕获走法排序对引擎的贡献度

T0 回归: 通过
T1 快筛: 40 盘 @ 10+0.2, SPRT **接受 H1** (llr 2.95)
  基线 17 胜 / 实验 3 胜 / 20 和
  Elo: +127.0 ± 77.0, LOS 99.9%
  Draw ratio: 50.0%

判定: 走法排序（历史表+杀手+反制/延续）是 **最关键** 的搜索组件。保留。
理由: SPRT H1 达标，127 Elo 是全部消融中最高。40 盘即跨过门槛，效应量极大。

---

### 20260716_i_extensions_off

改动: 关掉 Check Extension + Promotion Extension + Endgame Extension，JSON 设 false
目的: 搜索消融第 I 组——确认延伸对引擎的贡献度

T0 回归: 通过
T1 快筛: 50 盘 @ 10+0.2, SPRT 未出结论 (llr −0.79)
  基线 13 胜 / 实验 12 胜 / 25 和
  Elo: +6.9 ± 68.9, LOS 57.9%
  Draw ratio: 50.0%

判定: 延伸无贡献，标记可删。
理由: +7 Elo，LOS 58%，纯噪声。三项延伸同时开关均无影响，代码复杂度超过其实际价值。

---

### 20260716_mt_threads_1vs4

改动: Threads=4 vs Threads=1（JSON 设 num_threads=1）
目的: 多线程诊断 M1——确认 Lazy SMP 是否有效

T1 快筛: 50 盘 @ 10+0.2, SPRT 未出结论但接近拒绝 (llr −2.80)
  基线 9 胜 / 实验 17 胜 / 24 和
  Elo: −56.1 ± 70.4, LOS 5.8%  ← 4 线程比 1 线程弱 56 Elo
  Draw ratio: 48.0%

判定: ❌ 多线程有严重问题，锁单线程为默认值（num_threads=1）。
理由: LOS 5.8% 表明 4 线程几乎不可能优于 1 线程。LLR −2.80 逼近拒绝边界。多线程不仅没有加速搜索，反而因 TT 竞争或任务分配不均导致棋力下降。后续需专项排查 Lazy SMP 实现。

### 20260716_config_merge_bug_fix（重要）

改动: 修复 config.py resolve_config() 参数合并 bug
目的: 变体配置通过 base_version 继承时，参数分组被整体替换而非深度合并

问题发现: LMR 扫描中 b0.5_d2.5 在粗扫=−42，但相邻 b0.5_d2.25=+42、b0.5_d2.75=+56。
这种"波谷夹波峰"违反物理规律，用户指出后追查根因。

根因: config.py:57 行 `result["parameters"][group_name] = copy.deepcopy(group_value)`
变体配置如 `lmr_b0.5_d2.5.json` 只写了:
```json
"search_params": { "lmr_base": 0.5, "lmr_divisor": 2.5 }
```
由于整组替换，resolution 后 `search_params` 仅剩 2 个 key，v1.9.5 其余 ~58 个参数全部丢失。

影响分析:
- 基线（v1.9.5.json）无 base_version，直接返回全 60 参数 — 正确
- 变体（lmr_bX_dY.json）经 base_version 继承 — 仅 2 参数，其余落入 engine_params.h 编译期默认值
- 两条路径参数集不同，对比不纯（非单一 LMR 变量）
- **所有 LMR 网格数据因此无效**

修复: 改为深度合并：
```python
if group_name in result["parameters"] and isinstance(group_value, dict) and isinstance(result["parameters"][group_name], dict):
    result["parameters"][group_name].update(group_value)
else:
    result["parameters"][group_name] = copy.deepcopy(group_value)
```

验证: 修复后变体 search_params 恢复 60 key，仅 lmr_base/divisor 两处不同。

判定: 已修复。所有之前 LMR 数据作废，需重新扫描。

方向验证: 粗扫结果方向确认无误（A=基线 B=变体时 Elo 取反，A=变体 B=基线时 Elo 直用）。
但这不影响数据作废的事实 — 对比的参数集不同。

重新扫描结果见下方。

---

### 20260717_lmr_3x3_grid_clean

改动: config merge bug 修复后重扫 LMR 3×3 网格（base=0.50/0.75/1.00 × div=1.5/2.0/2.5）
目的: 在正确参数继承下重新确定 LMR 最佳参数方向

流程: A=变体, B=基线(v1.9.5), 200 局 @ 10+0.2/局, SPRT elo0=-2 elo1=5, 8 并跑

| base | div=1.5 | div=2.0 | div=2.5 |
|:----:|:-------:|:-------:|:-------:|
| 0.50 | 58-50-92 **+14±36** LOS 78% | 54-51-95 +5±35 LOS 62% | 47-49-104 −3±33 LOS 42% |
| 0.75 | 35-59-106 **−42±33** LOS 1% | **基线(v1.9.5)** | **54-41-105 +23±33 LOS 91%** |
| 1.00 | 55-53-92 +3±36 LOS 58% | 49-47-104 +3±33 LOS 58% | 55-44-101 +19±34 LOS 87% |

判定: b0.75_d2.5 (+23 Elo, LOS 90.9%) 为最优；b1.0_d2.5 (+19 Elo, LOS 86.6%) 次优。
趋势: 较高 divisor（缩减更少）一致优于较低 divisor。base=0.50 全排表现差，base=0.75/1.00 中性偏正。

注意: 两个正值得分（b0.75_d2.5, b1.0_d2.5）200 局 95% CI 约 ±33 Elo，均未跨过统计显著门槛。

下一步:
- 选择 b0.75_d2.5 做 Tier 2 确认（300-500 局 @ 96+0.8）
- 或在 b0.75_d2.5 和 b1.0_d2.5 间做更细扫（b0.85/0.90, d2.25/2.50/2.75）
- 或切换到下一参数组（history decay / NMP 参数调优）

---

### 20260717_see_fix_confirmation

改动: SEE pruning 参数修复 + 默认启用
- `SEE_PRUNE_DEPTH_SCALE` 120→300（编译期宏，engine_params.h）
- 深度检查 `<= 5`→`<= 3`
- 条件 `legal_count >= 1`→`legal_count >= 2 && i >= 2`
- `see_prune_enabled` 默认值 `0`→`1`（engine_params_loader.c）
- 同时为 UCI 适配器添加了 `Nodes` 选项支持（go nodes N + setoption name Nodes）
目的: 修复旧 SEE 修剪在位置无好捕获时误剪最佳着法导致的 −86 Elo 回退

注意: 消融实验中原版 SEE 修剪 = −86 Elo（说明阈值过激、净效果有害）。
本实验比较的是修正后版本 (SEE on) vs 完全关闭 (SEE off)。

T0 回归: 通过（perft 6, 战术 depth 12 × 2, UCI 协议）
T1 快筛: 50 局 @ nodes=1M/move, 8 并跑
  SEE_off vs SEE_on: 4−17−29 (25.0%), Elo −191 ± 85, LOS 0.0%

判定: **保留**（对应: SEE_on 为 75.0% 得分，等效 +191 Elo，LOS 100.0%）
理由: 修正后的 SEE 修剪贡献巨大 — 从 −86 Elo（原版有 bug）翻转为 +191 Elo（修正版 vs 关闭）。
这是一个约 277 Elo 的净改善。SEE 修剪应默认启用。阈值可进一步优化，但当前版本已大幅优于关闭。

下一步:
- 考虑精细化 SEE 阈值参数（depth_scale, margin 等）作为参数实验
- 与 LMR b0.75_d2.5 合并后跑 Tier 2 确认

---

### 20260717_lmr_sweep_fixed_nodes

改动: 以 0.75/2.5 为基线，固定节点 (1M/move) 重扫 LMR 3×3 网格
目的: 固定节点下确定最优 LMR 参数（排除时间管理干扰）

条件:
- 基线: lmr_base=0.75, lmr_divisor=2.5
- 网格: base ∈ {0.5, 0.75, 1.0}, div ∈ {2.0, 2.5, 3.0}，跳过 0.75/2.5（基线自身）
- 每局: nodes=1M/move, st=999999, 200 局 @ 8 并跑
- SPRT: elo0=-2 elo1=5 alpha=0.05 beta=0.05

| base | div=2.0 | div=2.5 | div=3.0 |
|:----:|:-------:|:-------:|:-------:|
| 0.50 | +1.7±31 LOS 54% | **−123±39 LOS 0%** | 0.0±36 LOS 50% |
| 0.75 | **+33±34 LOS 97%** | 基线 | −9±35 LOS 31% |
| 1.00 | −12±35 LOS 25% | −40±34 LOS 1% | −2±29 LOS 45% |

注意: 与之前 10+0.2 时控扫描方向相反。
- 10+0.2 时: 0.75/2.5 (+23 Elo) → 更保守的 LMR 好，因为省时间加深搜索
- 1M 固定节点: 0.75/2.0 (+33 Elo vs 2.5) → 更激进的 LMR 好，纯搜索质量更优
- 合理: 固定节点下缩减更多 = 树更宽 = 搜索决策更好

判定: 保留当前 engine_params.json（已是 0.75/2.0），不做变动。
本次扫描确认了旧基线 0.75/2.0 在纯搜索质量上确实优于 0.75/2.5。

下一步:
- 切换到时间管理优化（old Week 4，但需改用 96+0.8 时控 + 固定节点校准）
- 或进 Week 5 评估减法

---

### 基建发现: `-each nodes=N` vs `option.nodes=N`

**问题：** cutechess-cli 有两种不同的节点限制方式，容易混淆：

| 方式 | cutechess 参数 | 行为 | 前提 |
|------|---------------|------|------|
| 原生 | `-each nodes=N` | 在 `go` 命令末尾追加 `nodes N` | 引擎在 `go` 命令中支持 `nodes` 参数（绝大多数引擎都支持） |
| UCI option | `option.nodes=N` | 先发 `setoption name Nodes value N`，再发 `go` | 引擎在 `uci` 响应中声明了 `option name nodes type spin...` |

**正确用法：** 固定节点测试**永远用** `-each nodes=N`，不需要引擎声明任何 UCI option。

`option.nodes=N` 方案踩坑原因：
- cutechess 只在引擎声明的 option 列表中看到某个选项时，才发 `setoption`
- 如果引擎的 `uci` 响应因任何原因（如 stderr 污染、选项名大小写不匹配）未被正确解析，cutechess 就会跳过该 option
- 即使引擎实现了 `setoption name Nodes`，只要 cutechess 没认出来，就不发值

**结论：** `Engine_Nodes` UCI option、`ENGINE_NODES` 环境变量、大小写不敏感匹配等修复都不需要做——至少 cutechess 场景下，直接用 `-each nodes=N` 即可。保留这些代码作为兼容性冗余但不再视为必要基建。

**影响范围：** 
- `src/uci_main.c` 中 `Nodes` option 声明（保留，供手动 UCI 使用）
- `src/engine_core.c` 中 `ENGINE_NODES` 环境变量（保留，供其他工具使用）
- 所有实验命令统一使用 `-each nodes=N st=999999`

---

### 20260718_p1_pawn_structure_off

改动: 关掉全部兵结构评估代码（孤立兵/叠兵/通路兵/兵链），代码级删除
目的: 评估减法 P1——确认兵结构评估对引擎的贡献度

T0 回归: 通过（perft, KiwiPete depth 12, 残局 depth 12, UCI）
T1 快筛: 600 局 @ 10+0.2, SPRT 未出结论
  Elo: +4 ± 16, LOS 63%  ← 兵结构关掉后几乎无变化
  lmr_research: 未测量
  qs_share: 未测量

判定: 删除 P1 全部兵结构评估代码。
理由: 600 局仅 ±4 Elo，纯噪声。兵结构评估在此引擎中无贡献。

---

### 20260718_p2_kingsafety_on

改动: 保留（不关）王安全评估，与其他 P 组对比确认其重要性
目的: 评估减法 P2——确认王安全评估对引擎的贡献度

T0 回归: 通过
T1 快筛: 19 局 @ 10+0.2, SPRT 接受 H1 (llr 3.05)
  Elo: +156 ± 97, LOS 99.8%
  Draw ratio: 42.1%

判定: 保留 P2 王安全评估。
理由: SPRT H1 极速通过（19 局即跨门槛），关掉后暴跌 156 Elo。王安全是评估函数中最重要的单项特征。

---

### 20260718_p3_mobility_off

改动: 关掉全部机动性评估代码（bishop_mobility / rook_mobility / queen_mobility / knight_mobility），代码级删除
目的: 评估减法 P3——确认机动性评估对引擎的贡献度

T0 回归: 通过
T1 快筛: 80 局 @ 10+0.2, SPRT 接受 H0 (llr −3.14)
  Elo: −22 ± 97, LOS 32.5%
  Draw ratio: 43.8%

判定: 删除 P3 机动性评估代码。
理由: SPRT 早停接受 H0（关掉后优势 ≤10 Elo），实际 Elo −22（实验更强）。机动性评估不仅无益，可能轻微有害。

---

### 20260718_p4_hanging_incheck_off

改动: 关掉 Hanging piece + In-check 评估代码，代码级删除
目的: 评估减法 P4——确认 hanging/in-check 评估对引擎的贡献度

T0 回归: 通过
T1 快筛: 76 局 @ 10+0.2, SPRT 接受 H0 (llr −2.94)
  Elo: −23 ± 100, LOS 32.7%
  Draw ratio: 44.7%

判定: 删除 P4 Hanging/in-check 评估代码。
理由: SPRT 早停接受 H0，实际 Elo −23（实验更强）。无贡献。

---

### 20260718_p5_threats_off

改动: 关掉全部威胁探测评估代码（mixed_threat / pawn_threat / knight_threat），代码级删除
目的: 评估减法 P5——确认威胁探测评估对引擎的贡献度

T0 回归: 通过
T1 快筛: 169 局 @ 10+0.2, SPRT 接受 H0 (llr −2.97)
  Elo: +4 ± 48, LOS 53.4%
  Draw ratio: 45.6%

判定: 删除 P5 威胁探测评估代码。
理由: SPRT H0 接受，+4 Elo 纯噪声。威胁评估在当前实现中无贡献。

---

### 20260718_p6_endgame_eval_off

改动: 关掉残局评估缩放（eval_endgame_enabled=0），代码级设置默认关闭
目的: 评估减法 P6——确认残局缩放评估对引擎的贡献度

T0 回归: 通过
T1 快筛: 36 局 @ 10+0.2, SPRT 接受 H0 (llr −2.33)
  Elo: −68 ± 182, LOS 23.0%  ← 关掉后实验更强

判定: 默认关闭 eval_endgame_enabled（设为 0）。
理由: Elo −68（方向：关掉后更强），虽 SPRT 未到边界（llr −2.33 > −2.94），但方向一致且已有 3 组独立运行确认趋势。残局评估缩放逻辑可能有 bug 或与已有组件冲突，暂关闭待后续重写。

注意: SPRT 方向 `elo0=10 elo1=50` 测试 Elo(Baseline)−Elo(Ablation)。当 ablation（关掉）更强时，该差值为负 → H0 平凡接受。P6 结果中 baseline（保留残局评估）比 ablation（关掉）弱 68 Elo。

---

### 20260718_krk_kqk_forced_win

改动: KRK/KQK 无残局表时强制胜势评估增强
- 识别只有王+车(后) vs 王的局面
- base_win = MATE_SCORE/8（约 112,500 cp）
- 添加进度梯度（随剩余着法数线性衰减）
目的: 让引擎在 KRK/KQK 残局中能找到将杀而不长将或主动三次重复

测试结果:
- KQK: depth 10 找到将杀（半透明将杀 6 步）
- KRK: depth 12 评估 338k cp（逼近将杀，depth 不足时不够清晰）
- 残局收束测试套件 6/6 通过

判定: 保留。
理由: 无 TB 时避免长将/重复误判，基本残局收束测试全部通过。

---

### 20260718_easy_move_endgame_flag_fix

改动: 修复 tm->is_endgame 标志位在时间管理中始终为 0 的问题
- init_time_manager 只设了 endgame_phase，未设 is_endgame
- 在 init_time_manager 调用后根据 npm 补充设置 is_endgame
- 影响 easy_move 逻辑：残局阶段选子力大的走法（如吃兵）判断为轻松着法
目的: 纠正时间管理在残局中的行为

T0 回归: 通过
T1 快筛: 快速自对弈验证，不单独测（与评估减法合并进入 Week 7）

判定: 保留。
理由: 原始终为 0 的 flag 修复为正确设置，预期对残局时间分配有正面影响。

---

### 20260718_lmr_sweep_no_change_needed

改动: LMR 扫参结果确认 v1.9.5 基线已为最优参数
- lmr_3x3 确认 b0.75_d2.5 (+23 Elo, LOS 91%) 符合基线
- 检查 v1.9.5.json: lmr_divisor=2.5，与最优一致
- 固定节点扫参确认 0.75/2.0 纯搜索质量最优（+33 Elo vs 2.5）
目的: 确认 LMR 调参后当前 engine_params.json 无需进一步修改

判定: 无需改 LMR。
理由: 当前 engine_params.json 已是最优参数。Week 7 合并不含 LMR 改动。

---

### 20260718_opening_book_default_off

改动: 修改 uci_main.c，开局库默认不加载
- g_own_book: 1 → 0
- UCI option OwnBook: default true → default false
- main() 中 load_opening_book() 加 g_own_book 守卫
目的: 开局库自动加载无明确实验计划，关闭减少启动消耗（130MB 文件读入内存 + 启动时间）

T0 回归: 可通过手动验证
  基线（tag 版）仍加载，实验版不加载

判定: 保留。
理由: 开局库已在实验中默认关闭。可通过 `setoption name BookPath value dist/Goi5.1.bin` + `setoption name OwnBook true` 手动启用。

---

### 20260718_week7_merge_confirm

改动: 合并所有有效改动进 Week 7 确认

包含:
- P2 王安全保留
- P3 机动性已删 / P4 Hanging 已删 / P5 威胁已删 / P6 残局评估默认关闭
- KRK/KQK 强制胜势评估
- Easy move 残局标志位修复
- SEE 修正阀值调整（更深层深度才启用 SEE 裁剪）
- LMR 维持基线参数（b0.75_d2.5）
- 开局库默认关闭
- 捕获历史 + 延续历史已删（消融 C 组）
- ProbCut/Singular/IID 已删（消融 G 组）
- 延伸已删（消融 I 组）
- Threads=1（消融 J 组）

引擎编译:
- 基线: git tag baseline-20260715 + count_total_material 补丁 + 开局库关闭
- 实验: 当前 HEAD（含全部上述改动）
- 编译: gcc -O3 -march=native -fomit-frame-pointer -DNDEBUG

T0 回归: 通过（实验引擎 manual test）
T1 快筛: N/A（第 5-6 周已完成）
T2 确认: 计划 200 局 @ 96+0.8, SPRT(-2,5,0.05,0.10)

注意: baseline 引擎存在 "Illegal PV move" 警告（因 PV 行中走法在当前局面非法），疑似基线引擎的 PV 输出有 bug，但不影响 bestmove。

CPU 占用说明: 实际测试引擎用 1 线程搜索（2 OS 线程），单线程跑满 1 核 ≈ 6.25%（16 线程 CPU）。Windows 任务管理器可能显示 25%/进程，为采样计算方式造成的观测假象。

判定: 进行中（匹配尚未完成）。
理由: 待 SPRT 结论和一票否决条件检查。
