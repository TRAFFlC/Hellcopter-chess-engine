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
