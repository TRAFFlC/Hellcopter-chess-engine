# 对弈测试规则与记录

## 目录结构

```
chess/
├── match_rules/           # 对弈规则定义
│   └── standard_rule.json # 标准对弈规则
├── match_records/         # 对弈记录存储
│   └── 20260514_120000-hellcopter-shallowblue/
│       ├── match_info.json    # 对弈配置信息
│       ├── result.json        # 对弈结果
│       ├── pgn/
│       │   └── match.pgn      # 对弈记录PGN
│       └── logs/
│           └── cutechess_output.txt  # cutechess输出日志
└── match_manager.py       # 对弈管理脚本
```

## 标准对弈规则

| 参数         | 值               | 说明                          |
| ------------ | ---------------- | ----------------------------- |
| **时制**     | 96秒 + 0.8秒增量 | 每方基础时间96秒，每步加0.8秒 |
| **轮数**     | 11轮             | 交换先后手，确保公平          |
| **胜率阈值** | 55%              | 超过此阈值视为击败对手        |

## 参考引擎阶梯 (按Blitz等级分排序)

| 阶梯   | 引擎          | Blitz Elo | 可执行文件                                     |
| ------ | ------------- | --------- | ---------------------------------------------- |
| Tier 1 | Sargon        | 1163      | `sargon 1163/sargon-engine-static-link.exe`    |
| Tier 1 | Rainman       | 1427      | `Rainman 1427/rainman.exe`                     |
| Tier 2 | ShallowBlue   | 1575      | `ShallowBlue 1575/shallowblue.exe`             |
| Tier 2 | TSCP 181      | 1607      | `TSCP 1607/tscp181.exe`                        |
| Tier 3 | Apollo        | 1663      | `Apollo 1663/apollo.exe`                       |
| Tier 4 | Monarch       | 2005      | `Monarch 2005/Monarch(v1.7)/Monarch(v1.7).exe` |
| Tier 5 | Absolute Zero | 2284      | `Absolute Zero 2284/AbsoluteZero.exe`          |

### Velvet (难度可调节)

Velvet引擎可通过UCI参数调节Elo (1225-3000)：

```
setoption name UCI_LimitStrength value true
setoption name UCI_Elo value 1500
```

### Stockfish (NPS基准)

Stockfish仅作为NPS基准测试，非挑战目标。

基准数据 (单线程, depth=18, hash=128MB):

- **NPS**: 2,406,495 (~2.4M)
- **总时间**: 11,976 ms
- **搜索节点**: 28,820,188

## 使用方法

```bash
# 使用标准规则进行对弈（自动记录）
python match_manager.py --engine-a v1.3.0 --engine-b shallowblue

# 自定义参数
python match_manager.py --engine-a v1.3.0 --engine-b apollo --rounds 21 --tc 60+0.5

# 不记录对弈过程
python match_manager.py --engine-a v1.3.0 --engine-b shallowblue --no-record

# 使用其他规则文件
python match_manager.py --engine-a v1.3.0 --engine-b apollo --rule custom_rule.json
```

## 对弈记录命名规则

格式: `{时间}-{引擎A}-{引擎B}`

示例: `20260514_120000-hellcopter-shallowblue`

- 时间: YYYYMMDD_HHMMSS
- 引擎A: 通常为hellcopter（测试方）
- 引擎B: 参考引擎
