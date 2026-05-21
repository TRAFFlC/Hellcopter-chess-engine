# Hellcopter Chess Engine

一个用C和Python编写的国际象棋引擎，支持UCI协议。

## 特性

- **搜索引擎**: Negamax + PVS + Alpha-Beta剪枝
- **静止搜索**: 吃子/将军着法延伸
- **剪枝技术**: 空着裁剪(NMP)、LMR、Futility Pruning、Razoring
- **置换表**: Zobrist哈希 + 深度优先替换
- **评估函数**: Tapered Eval、兵结构、王安全、子力位置表(PST)
- **多线程**: Lazy SMP并行搜索

## 性能

- NPS: ~2,000,000 节点/秒
- 搜索深度: 12秒可达深度10+
- 预估Elo: 1600

## 快速开始

### 环境要求

- Python 3.10+
- GCC/MSVC/Clang 编译器

### 安装

```bash
pip install -r requirements.txt
python build_engine.py
```

### 运行GUI

```bash
python main.py
```

### 作为UCI引擎

```bash
python uci_engine.py
```

## 项目结构

```
├── engine_core.c      # C搜索引擎核心
├── engine_core.h      # C引擎头文件
├── engine_wrapper.py  # Python-C接口
├── build_engine.py    # 编译脚本
├── uci_engine.py      # UCI协议适配器
├── main.py            # GUI主程序
├── gui.py             # Tkinter界面
├── config.py          # 配置管理
├── configs/           # 引擎配置文件
└── optimizer/         # 参数优化模块
```

## 配置

配置文件位于 `configs/` 目录，当前最新版本为 `v1.4.2.json`。

关键参数:
- `lmr_enabled`: LMR剪枝开关
- `futility_enabled`: Futility剪枝开关
- `razoring_enabled`: Razoring剪枝开关
- `delta`: 静态搜索Delta剪枝阈值

## API使用

```python
import engine_wrapper as ew

# 搜索最佳走法
move, score, nodes = ew.search_with_score(
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    time_limit=2.0,
    max_depth=100
)
print(f"最佳走法: {move}, 分数: {score}")
```

## License

MIT
