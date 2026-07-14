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
