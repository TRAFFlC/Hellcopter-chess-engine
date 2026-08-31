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

判定: 标记可删，但保留。（⚠️ 见下方 20260719_merge_delete_cgi_failed）
理由: Elo −3.5 且 LOS 44.2%，几乎纯噪声。SPRT 倾向 H0（llr −2.37 接近 −2.94 边界）。但因交互效应不能证明合并删除无害（合并删除导致退化），故保留代码。
（注：上游分支另议"标记可删"，本地经验以 20260719 交互效应教训为准，见下）

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

判定: ❌ 贡献未证实，但保留。（⚠️ 见下方 20260719_merge_delete_cgi_failed）
理由: 三轮 200 局合并结果趋近 0 Elo，三次方向来回跳，证实为噪声。但因交互效应不能证明合并删除无害（合并删除导致退化），故保留代码。
（注：上游分支另议"可删除或保留为可选开关"，本地经验以交互效应教训为准）

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

判定: 延伸无贡献，但保留。（⚠️ 见下方 20260719_merge_delete_cgi_failed）
理由: +7 Elo，LOS 58%，纯噪声。但因交互效应不能证明合并删除无害（合并删除导致退化），故保留代码。
（注：上游分支另议"标记可删"，本地经验以交互效应教训为准）

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

### 20260719_merge_delete_cgi_failed

改动: 合並且删除 C（capture_history + continuation_history）、G（ProbCut + Singular Extension + IID）、I（Check/Promo/Endgame Extensions）三个单独消融标记为"可删"的模块
目的: 清理代码中证实无效的冗余模块

结果: **严重退化。** 单独消融中每个模块的贡献 ≈ 0 Elo，但统一删除后棋力显著下降。

分析: 这是**消融交互效应**的典型表现——三个模块单独开关无影响，是因为其他模块的冗余路径补偿了其功能。同时移除后补偿链断裂，整体搜索质量崩塌。

教训:
- ❌ 搜索模块的消融结果 **不能线性叠加**。ABC 各 −3 Elo 不意味着 A+B+C 同时 = −9 Elo
- ❌ "单独关掉不降 Elo → 可删" 这个推论在搜索模块间有冗余补偿时无效
- ✅ 有效的方法是：逐个关掉 → 确认有效 → 逐步构建简化版，每加一个模块验证一次增量
- ✅ 或走另一条路：保留所有模块，只调参数（LMR 网格 / SEE 阈值等），不改结构

判定: 回滚删除，保留 C/G/I 全部模块。
理由: 三个模块一起删 ≈ −50+ Elo 退化，但单独删每个 ≈ 0 Elo。交互效应使单独消融结论不可靠。后续避免批量删除模块，改用参数级调优。

---

### 20260719_baseline_plus_recovery（补录）

改动: Experiment = baseline + count_total_material() 物料感知深度加成（180e615）+ UCI 默认值修复 + mobility 表加载修复（693990b）
目的: 补录 7/19 凌晨未记录的自对弈实验（tests/results/baseline_plus_sprt.pgn）

T0 回归: 通过（当时构建后已验证）
T1 快筛: 191 局 @ 10+0.1, 未用 SPRT 判定, +21.9±12 Elo, LOS 82.7%
  Profile 指标: 未测量（补录数据缺失）
  注: 同批 baseline_plus_confirm.pgn（6 局固定时间/深度）样本过小，无统计意义，不作为依据

判定: 方向积极，但未达晋升门槛（需 ≥300 局且 LOS≥95% 或 SPRT 接受 H1）
理由: +21.9 Elo 超过噪声底噪（±22 @500盘 的 1σ 边界），LOS 82.7% 提示真实正向；需与后续改动合并后重新确认，避免重复消耗对局资源。当前 dist/Hellcopter.exe（7/19 12:03）已包含这些改动，作为事实基线参加对外标定。

---

### 20260823_m1_calibration_vs_monarch

改动: 无代码改动——当前事实基线（dist/Hellcopter.exe, 7/19 构建）首次与 Monarch 2005 v1.7 正式标定
目的: M1 阶段基准测量：确认当前棋力与 2000 分目标的差距（GOAL.md 阶段里程碑）

比赛条件:
- 时制 96+0.8（目标时制）；240 局；并发 4（资源纪律：8 个单线程引擎进程，<1GB 内存，禁满载）
- Hellcopter 从 arena/copter 启动（已验证 stderr: 无 book、无 EGTB 加载）；
  Monarch 从 arena/monarch 启动（其目录无任何 book 文件）
- 开局: arena/openings.epd（30 条主流变例随机抽取，双方同开局各执黑白一次，公平且多样；
  该 EPD 由 tests/gen_openings_epd.py 生成，来源为公开开局树知识，非任何引擎私有库）
- 裁决: -draw movenumber=40 movecount=8 score=20 -resign movecount=4 score=600

资源事故记录: 首次启动误用并发 16 导致系统 CPU 满载（用户机器同时跑有其他应用，
触发模型服务商过载告警），已被用户批评。已终止并作废该批 9 局数据。
教训固化至 GOAL.md 第三节第 0 条（并发上限 4，启动前记录资源预算）。

T0 回归: 通过（arena/copter 环境验证 + UCI 握手）
T1/T2: 进行中（96+0.8 长时制，预计数小时，结果出来后补录 Elo/LOS 与输棋归类）

判定: 待定
理由: 等待对局完成。

参考来源: 无外部借鉴。openings.epd 为自写生成器（标准开局树常识）。



---

### 20260823_config_archaeology_and_M1_restart

改动: 无引擎代码改动。基础设施考古+修复日——清洗根 engine_params.json 为规范 resolved(v1.9.5)+Threads1；
arena/copter 放显式同名配置；新增 run_m1.ps1 并修复两脚本路径/错误处理；两段旧 M1 数据存档 reference-only。
目的: M1 标定必须测"已知且可复现的配置"，消除三套配置来源漂移。

实测发现（全部有探针脚本佐证，tests/probe_*.py）:
1. [关键] 独立 exe 比赛条件（无 ENGINE_PARAMS env、cwd 无 json）: 引擎单线程
   （uci go 分发在读 g_runtime 时 BSS 尚未初始化 → find_best_move_c 直达，
   find_best_move_smp 内部的懒加载从未发生）、无 book/EGTB、参数=烘焙编译期默认。
   烘焙默认经探针证实 ≡ resolved(v1.9.5)：固定深度 14 节点数逐位一致（1,880,013, cp51, d2d4）。
2. [纠错] 昨会话两个结论被推翻:
   - "M1 引擎跑 4 线程 Lazy SMP 带伤上阵" —— 错。实测单线程（CPU 采样 ~1 核）。
     16 线程饱和的真因未定（Monarch 自身多线程? 把 OS 线程数当计算线程的观测误差?）。
   - "setoption Threads=1 可切单线程（源码确认）" —— 半错。选项注册且 set_num_threads 生效，
     但 go 分发先于参数懒加载读取 threading_enabled，故该选项在首搜前是空操作。
     幸而比赛条件本就单线程，无实害。
3. [重大隐患已除] 根 engine_params.json 含 ~40 个来源不明 eval_weights（≠v1.9.3/v1.9.5/
   texel_tuned 抽查全不匹配），曾使 depth14 搜索树膨胀 4x（7.51M vs 1.88M 节点）、换最佳走法。
   该文件是 DLL/web/regression 的活跃配置 ⇒ 此前 Python 侧分析全部基于污染权重！
   已清洗为规范配置，原文件快照: tuning/root_json_mystery_weights_snapshot.json
4. [挂起] SEE_PRUNE_DEPTH_SCALE 三处三个值: v1.9.5.json=60（生成宏同）/
   旧 root_json=120（死键——loader 根本不解析该参数）/ EXPERIMENTS 20260717 验证修复值=300
   （手改宏，后被重新生成覆盖丢失）。当前 dist exe 烘焙=60+新代码条件（legal≥2&&i≥2 等）。
   无法运行时注入、无法重编译（gcc 受阻）⇒ M1 实测的是未验证组合 scale60+新条件。
   编译恢复后: 头文件回 300 + params_loader 增加 see_prune_depth_scale 解析（防再丢）。
5. run_m1/run_m2.ps1 三 bug 修复: cwd 未固定（相对路径失效）、openings.epd 相对路径错误、
   $ErrorActionPreference=Stop 使 stderr 警告（如 Monarch 无 Threads 选项）杀死整场比赛。

T0 回归: 通过（清洗后根配置 regression.py 4/4）
资源验证: 9 进程（1 cutechess + 4×2 引擎）, 全部单线程, 合计 ~5 核/16, 内存 <1GB

判定: 保留
理由: M1 于 2026-08-23 以显式配置重启（240 局 @96+0.8, 并发 4, PGN=arena/m1_monarch_*.pgn）。
旧数据 75 局(saturated 段)与 43 局(aborted 段)移入 tests/results/*_reference.pgn 仅作参考不对齐统计。

---

### 20260824_M1_monarch_calibration_r1

改动: 无引擎代码改动。M1 标定第 1 轮: arena 显式配置(resolved v1.9.5, 单线程,
SEE scale=60 烘焙值) vs Monarch2005 v1.7
目的: 测量当前引擎相对 M1 门槛对手的真实差距

T0 回归: 通过（赛前 regression.py 4/4）
结果: 240 局 @ 96+0.8 并发 4, 胜 99 / 负 84 / 和 57, 得分率 53.1%
  Elo +21.7 ±38.5 (95%CI 含 0), LOS 86.6%, 和棋率 23.8%（异常低, 对局极具决定性）
  终止方式: 绝大多数为 resign/adjudication 裁决
输棋归类: 84 负中 ≤60 步速败仅 16 局 (19%), 中位败局长度 83 步
  → 无战术崩溃/时间崩溃模式, 败局集中于长局消耗战（残局/位置性劣势）

判定: ⚠️ 未达 M1 门槛（LOS ≥ 97%）, 方向为正但证据不足
下一步: 真实优势若 ≈ +22 Elo, 凑到 LOS97% 需累计约 800+ 局, 纯统计磨盘不经济。
改为先强化引擎再标定——启动 LMR d2.5 变体(divisor 2.0→2.5, 20260717 网格最优
+23±33 从未确认) 的 Tier1 SPRT 自对弈确认(0,5,.05,.05 @10+0.2 并发4);
无论胜负均以最终配置重跑 Monarch 标定（避免同一标定跑两遍）。

附注: 双方引擎持续输出 "Illegal PV move" 警告（PV 提取的外观缺陷, 对局不受影响）,
列入低优先待查。

---

### 20260824_lmr_d25_confirm_failed

改动: 无代码改动。Tier1 快筛确认 lmr_divisor 2.0→2.5（configs/lmr_d2.5.json,
20260717 网格最优点 +23±33 的首次正式确认）
目的: 验证网格最优参数是否真实, 若真则强化引擎后再重跑 M1 标定

T0 回归: 通过（实验配置经 make_experiment_config.py 强制单线程）
T1 快筛: 250 局 @ 10+0.2 并发4, SPRT 未正式越界(llr -0.71)但数据已决定性
  实验方(A=d2.5): 胜54 / 负78 / 和118, 得分率 45.2%
  Elo -33.5 ±31.4, LOS 1.8%
  和棋率 47.2%

判定: ❌ 回滚（不晋升 d2.5）
理由: 点估计 -33.5 且 LOS 1.8%, 与先验 +23 方向相反。无任何晋升可能。

分析（重要）: 先验来自 7/17 网格扫描, 当时跑在 SEE_PRUNE_DEPTH_SCALE=300 的
手修版 exe 上; 本次跑在 scale=60 重编译版上。同 TC 同参数、不同剪枝环境,
效应方向翻转 —— LMR 效应依赖周边剪枝组合, 单参数历史结论不可跨构建环境复用。
与 20260719_merge_delete_cgi_failed 的教训同族：搜索参数存在环境耦合。
推论: 所有 7 月网格/消融结论在 scale60 引擎上视为失效, 如需引用必须重测。

---

### 20260831_pepito_source_research

改动: 无代码改动。逐文件研读外部引擎 Pepito v1.59 源码（negascou.c/eval.c/hash.c/
sort.c/see.c/itera.c/time.c/mueve.c/readme.txt/changes.txt），产出对比研究报告
目的: 定位 Hellcopter（~1900-2100）与 2500 级引擎的决定性差异，为后续涨分方向提供证据

参考来源: Pepito v1.59（GPL v2, 作者 Carlos del Cacho, 2000-2003, 西班牙）,
路径 test_engines/Pepito 2492/pepisrc/。
完整报告: docs/reports/20260831_pepito_vs_hellcopter_research.md
（报告 §0 含反剽窃声明：仅提取设计思想与事实描述，未复制任何代码；
后续任何借鉴须在本文件对应条目标注参考来源）

核心结论:
1. 差异不在技术栈新旧（Hellcopter 的 LMR/SE/ProbCut/RFP 更现代），而在四点：
   每节点必要成本（增量材料/分段生成/last_cap 重复检测 vs 全量扫描）、
   两年锦标赛校准的激进参数（NMP 在 PV 也用）、
   禁书禁库规则下的和棋/残局完备性（TABLAS 封顶/王距赛跑/错误色象）、
   搜索-评估联动细节（null_threat 经 TT 传播、相对窗口 lazy eval）
2. 实测 Hellcopter startpos 548-616 kNPS（单线程）；Pepito 沙箱无法编译未测速
   （正常终端待补，见报告 §6 实验 1）
3. 附带发现: go movetime 8000 未被遵守（搜到 depth 20 用 294s）——待复核

判定: 研究完成（报告已存档）
理由: 用户要求的源码研究 + 反剽窃声明已落实；后续涨分方向见报告 §5，
动代码前须按 GOAL.md 第 1/2 条逐项留痕

---

### 20260831_invictus_source_research

改动: 无代码改动。拉取 InvictusChess 仓库至 test_engines/Invictus 3100/，
逐文件研读 Invictus r391 源码（search.cpp/eval.cpp/params.cpp/movepicker.cpp/
trans.cpp/position.cpp/movegen.cpp/attacks.cpp/engine.cpp/uci.cpp/tune.h 等全库
26 文件约 2900 行，100% 通读），产出对比研究报告
目的: 定位 Hellcopter（~1900-2100）与 3100 级引擎的决定性差异，交叉验证
Pepito 报告结论，为后续涨分方向提供二代引擎证据

参考来源: Invictus r391（GPL v3, 作者 Edsel Apostol, 2021, 菲律宾）,
来源 https://github.com/ed-apostol/InvictusChess（2026-08-31 克隆）,
本地路径 test_engines/Invictus 3100/InvictusChess/（3100 取自 README 所载
CCRL 40/4 榜 r382=3108）。
完整报告: docs/reports/20260831_invictus_vs_hellcopter_research.md
（报告 §0 含反剽窃声明：GPL v3 传染性强于 Pepito 的 GPL v2，任何一行代码
直接移植都会感染整个项目——只提取设计思想与数值事实描述；
后续任何借鉴须在本文件对应条目标注参考来源）

核心结论:
1. 修正 Pepito 报告假设: NMP-PV 禁用不是主要失分点（Invictus 3100 同样
   PV 禁用，两台对照引擎做法一致 → 该嫌疑降级）
2. 真正差距四件事: 每节点执行成本（评估缓存表 vs 每节点全量 evaluate()）、
   和棋/材料判定框架化（486×486 预计算表+增量索引）、TT 着法完整验证
   （Hellcopter 缺失）、参数置信度（Texel 调参管线）
3. 技术栈宽度 Hellcopter 不输 3100 引擎——减法美学+精确数值边界 > 技术数量
4. 首要事实: Invictus 3100 分在无书/无 EGTB/无 NNUE 条件下取得（与本项目
   禁书禁库规则同构，证明该规则下纯搜索+评估可达 3100）
5. 实测受限: 沙箱 gcc 启动失败（0xC0000135，与 Pepito 研究时相同），
   Invictus kNPS 未测，性能论断均为代码结构推断

判定: 研究完成（报告已存档）
理由: 用户要求的拉取+研究+报告已落实；两份对照报告（Pepito 2500 / 
Invictus 3100）已形成交叉证据链，后续涨分方向见报告 §5，
动代码前须按 GOAL.md 第 1/2 条逐项留痕

---

### 20260831_goldfish_source_research

改动: 无代码改动。拉取 goldfish 仓库至 test_engines/Goldfish 2250/，
精读 Goldfish v2.1.1 源码（engine/src 约 2000 行 Rust：negamax/cuts/
speculate/quiescence/tt/evaluate/movelist/opts/limits 等核心 100% 通读），
产出对比研究报告
目的: 填补五引擎 Elo 阶梯的 2250 档，定位 Hellcopter（~1900-2100）与
2250 级引擎的决定性差异（用户指定：自研方向长期瓶颈，先学习）

参考来源: Goldfish v2.1.1（MIT License, 作者 Bendik Samseth）,
来源 https://github.com/bsamseth/goldfish（2026-08-31 克隆）,
本地路径 test_engines/Goldfish 2250/goldfish/（README 内部排位表
v2.1.0=2314, 以 v1.13 CCRL 40/40 为锚; 评估用 CPW 公开 PeSTO 表）。
完整报告: docs/reports/20260831_goldfish_vs_hellcopter_research.md
（报告 §0 含反剽窃声明: MIT 宽松许可无传染风险, 但仍只提取设计思想
与数值事实描述, 不移植代码; PeSTO 表如采用须另行标注 CPW 来源）

核心结论:
1. 反向修正: 评估项数量不是 2250 档门槛——Goldfish 纯 PeSTO PSQT
   （零兵结构/零王安全/非增量）+ PVS/NMP/razoring/futility 即到 2250+;
   Hellcopter 评估特征面已全面超过 Goldfish
2. 真正差异是 TT 工程代差: SF 式 10 字节条目+32B 3 槽簇+mul_hi64 索引
   +eval 字段存储+杀分 50 步降级+GHI（halfmove≥90 禁截止）——静态分
   复用是三代引擎（Pepito/Goldfish/Invictus）一致信号, Hellcopter 空白
3. LMR/aspiration 不是 2250 档门槛（Goldfish 无此两项）; Hellcopter
   搜索技术清单全面长于 Goldfish 却低 150-250 分——技术数量≠棋力,
   与 Invictus 报告 §3.4 结论互证
4. 诚实修正: Goldfish 测试池可用 Syzygy（本项目禁库）, 禁库规则下其
   有效棋力大概率低于排位, 两池不同源 ±100 分偏差正常
5. 实测受限: 沙箱 cargo 不可用, kNPS 未测（并入实验 1）

判定: 研究完成（报告已存档）
理由: 用户要求的拉取+研究+报告已落实; 五引擎阶梯已补 2250 档,
后续涨分方向见报告 §5, 动代码前须按 GOAL.md 第 1/2 条逐项留痕

---

### 20260831_facon_source_research

改动: 无代码改动。拉取 facon 仓库至 test_engines/Facon 2800/，精读
Facon 1.6 "Temple" 源码（src/ 18 文件约 7500 行 C++17: search.cpp 主干
/QS/go()/SEE/TT/TM 100% 精读, eval.cpp 结构+关键函数+934 权重体系精读）,
产出对比研究报告并收束五引擎阶梯总对比（报告 §6）
目的: 填补 2800 档并形成 Hellcopter→Goldfish→Pepito→Facon→Invictus
完整 Elo 阶梯证据链, 定位各档分水岭（用户指定: 先学习再动手）

参考来源: Facon 1.6 Temple（**无 LICENSE 文件, 默认保留所有权利,
比 GPL 更严: 任何代码复制均不被许可**）, 作者 Carlos M. Canavessi,
来源 https://github.com/CMCanavessi/facon（2026-08-31 克隆）,
本地路径 test_engines/Facon 2800/facon/（README Ordo Elo ~2800,
gauntlet 26 对手×40 局; 版本表 1.0→1.6 = 1220→2800）。
完整报告: docs/reports/20260831_facon_vs_hellcopter_research.md
（报告 §0 含反剽窃声明; §6 为五引擎阶梯总表与分水岭结论）

核心结论:
1. 最强参数证据: 1.5→1.6 零搜索改动 +250 Elo, 全部来自 934 权重
   Texel 全量重调（tempo 单项 +19）; 对照其演进史 NMP +340 之后无任何
   单项搜索技术超过 +250——参数置信度是 2500→2800 主通道
2. 静态分获取三形态集齐: Hellcopter 每节点 lazy / Facon 仅剪枝浅层
   计算（深节点零评估成本, 2800 不需要评估缓存）/ Invictus 缓存（3100
   才需要）——修正 Invictus 报告为两步走: 先"按需计算"再"缓存"
3. TT 着法轻量验证形态: 对生成着法表逐项比对（~10 行）, 与 Pepito/
   Invictus 三引擎一致, Hellcopter 仍缺; Facon 形态最易落地
4. 反例组: Facon 无 PVS、无 SE、无 ProbCut 照样 2800——与 Invictus
   报告互证技术清单长度与 Elo 不相关
5. 负结果清单可直接采信: Tarrasch 车置通路兵后（−9）、非线性机动性
   （−12）、Kaufman 材料不平衡（≈0）已在 2800 级实测, Hellcopter
   无需再花 A/B 预算验证这三个方向
6. 五引擎分水岭: 2000→2250 TT 工程代差+静态分复用; 2250→2500 参数
   置信度+增量成本; 2500→2800 LMR 家族+全量 Texel; 2800→3100 评估
   缓存+材料级和棋/缩放框架。全程无一项需要新增评估特征或新搜索技术
7. 实测受限: 沙箱 gcc 第三次复现 0xC0000135, Facon kNPS 未测
   （自带 bench 10 位深度 18, 并入实验 1）

判定: 研究完成（报告已存档）
理由: 用户要求的拉取+研究+两份报告（Goldfish+Facon）已落实; 五引擎
阶梯证据链闭合, 总路线图见 Facon 报告 §6（按分水岭顺序: TT/静态分
复用 → 全量 Texel → 评估缓存/材料哈希框架）, 动代码前须按 GOAL.md
第 1/2 条逐项留痕

---

### 20260831_reckless_chess324_research

改动: 无代码改动。拉取 Reckless 仓库至 test_engines/Reckless 3700/，
精读 v0.10.0-dev 源码（核心约 80 文件: board/parser/movegen/makemove/
castling/moves/uci/nnue 全家族/evaluation 100% 精读），并外部文献核证
chess324 变体定义，产出变体兼容专题研究报告
目的: 用户指定专题——顶级引擎（3700+）如何支持 chess324, 是单独优化
还是评估与 PST 解耦（用户目标: 更全面的变体兼容引擎, 不做与
Hellcopter 的全面对比）

参考来源: Reckless v0.10.0-dev（**AGPL v3, 含第 13 条网络条款, 传染性
强于 GPL: 任何代码复制均不被许可**）, 作者 codedeliveryservice,
来源 https://github.com/codedeliveryservice/Reckless（2026-08-31 克隆,
HEAD 91b56c2; README v0.9.0: SPCC 3833 / CCRL 3767）。chess324 定义:
Larry Kaufman 2022-08 TalkChess（王车标准位/双象异色/每方 18 排列/
18×18=324/易位规则完全标准）; SPCC AntiDraw 2.0 开局集含 Chess324
64x（Stefan Pohl, TalkChess 2022-09）——Reckless 实战评级的测试池
成分。完整报告: docs/reports/20260831_reckless_chess324_research.md

核心结论:
1. 前提修正: Reckless 代码库零 chess324 专门代码（全库检索 324|960|
   variant 仅命中 UCI_Chess960 选项与 960 perft 测试）; chess324 本身
   因王车归位而"任何引擎都能下"（易位零改动, 只需 FEN 解析健壮）
2. 三层解耦架构（非单独优化的实证）: 易位几何逐局面参数化
   （castling_path/threat/rooks 从 FEN 动态预计算, 标准棋只是"王 e1
   车 h1"特例, parser.rs:68-116）; I/O 双格式宽容（Shredder-FEN 与
   KQkq 都接受, 收着法走"生成集比对"验证, UCI_Chess960 仅控输出
   格式）; 评估特征零开局先验（NNUE 王桶条件化 PSQ + 攻击关系威胁
   特征 + 位置无关校正）
3. PST 解耦的本质: 位置价值 = (子, 格, 王位置桶, 视角) 的函数而非
   绝对坐标函数——"马 f3 好多少"以"王在哪"为条件（psq.rs:204-211,
   10 王桶: 第 1-2 行精细 16 桶/第 3 行 1 桶/第 4-8 行压缩 1 桶 =
   王在宫/离宫/残局三态建模）; 威胁特征 66864 维为"攻击者×被攻击者
   ×攻击格×被攻击格"六元组, 天然位置无关
4. 诚实边界: NNUE 网络为嵌入式二进制, 训练数据是否含 FRC 增强不可
   从源码判断; chess324 实战可用有 SPCC 评级佐证, 但退化幅度未实测
   （未编译, 沙箱限制延续）
5. 对 Hellcopter 启示: 兵结构/机动性/王安全特征本就位置无关（存量
   资产）, 唯一先验污染源是 PST; 最低成本解耦 = PST 加王位置桶维度
   （[piece][sq] → [piece][sq][king_bucket], 用现有 Texel 管线调参,
   王翼桶天然吸收现主表, 不需变体训练数据）; AGPL 代码严禁复制,
   思想层面（王桶条件化/动态易位几何）落地须留痕

判定: 研究完成（报告已存档）
理由: 用户指定的拉取+chess324 专题研究+报告已落实; 结论为"三层架构
性解耦而非单独优化", 后续若动 Hellcopter PST/易位代码须按 GOAL.md
第 1/2 条逐项留痕（AGPL 合规红线已写入报告 §0）

---

## 上游分支独有条目（合并自 origin/main，2026-08-31 手动对齐）

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
