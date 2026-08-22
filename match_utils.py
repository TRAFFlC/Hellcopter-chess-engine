"""
比赛和测试工具的公共函数模块

提供统一的工具函数实现，避免代码重复。所有比赛/测试脚本应从此模块导入这些函数。

功能：
- find_cutechess: 查找cutechess-cli可执行文件
- resolve_config: 解析配置文件路径
- check_engine_dll: 检查引擎DLL文件是否存在
- create_temp_uci_adapter: 创建临时UCI适配器脚本
- calc_elo: 计算Elo评分差异
- calc_ci_wilson: 使用Wilson区间计算置信区间
- parse_match_output: 解析比赛输出结果
- print_results: 打印比赛结果
"""

import os
import sys
import shutil
import platform
import tempfile
import json
import math
import re
from typing import Optional, Tuple


def find_cutechess(cli_path: Optional[str] = None,
                   base_dir: Optional[str] = None) -> Optional[str]:
    """
    查找cutechess-cli可执行文件

    Args:
        cli_path: 用户指定的cutechess-cli路径
        base_dir: 项目基础目录（默认为当前脚本所在目录）

    Returns:
        找到的cutechess-cli路径，如果未找到返回None
    """
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    if cli_path:
        if os.path.isfile(cli_path):
            return cli_path
        print(f"Error: specified cutechess-cli path not found: {cli_path}")
        sys.exit(1)

    found = shutil.which("cutechess-cli")
    if found:
        return found

    candidates = [
        os.path.join(base_dir, "cutechess-cli.exe"),
        os.path.join(base_dir, "cutechess-cli"),
        os.path.join(base_dir, "cutechess", "cutechess-cli.exe"),
        os.path.join(base_dir, "cutechess", "cutechess-cli"),
    ]

    if platform.system() == "Windows":
        program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        candidates.extend([
            os.path.join(program_files, "cutechess-cli", "cutechess-cli.exe"),
            os.path.join(program_files_x86, "cutechess-cli", "cutechess-cli.exe"),
        ])
    else:
        candidates.extend([
            os.path.join(base_dir, "cutechess-cli"),
            "/usr/local/bin/cutechess-cli",
            "/usr/bin/cutechess-cli",
        ])

    for c in candidates:
        if os.path.isfile(c):
            return c

    return None


def resolve_config(config_arg: str, base_dir: str) -> Optional[str]:
    """
    解析配置文件路径

    Args:
        config_arg: 配置引用（版本号或文件路径）
        base_dir: 项目基础目录

    Returns:
        解析后的配置文件路径，如果未找到则退出程序
    """
    if os.path.isfile(config_arg):
        return os.path.abspath(config_arg)

    version = config_arg.lstrip("v")
    config_path = os.path.join(base_dir, "configs", f"v{version}.json")
    if os.path.isfile(config_path):
        return config_path

    config_path = os.path.join(base_dir, "configs", f"{config_arg}.json")
    if os.path.isfile(config_path):
        return config_path

    print(f"Error: Config not found: {config_arg}")
    print(f"  Tried: configs/v{version}.json")
    print(f"  Tried: configs/{config_arg}.json")
    sys.exit(1)


def check_engine_dll(base_dir: str) -> str:
    """
    检查引擎DLL文件是否存在

    Args:
        base_dir: 项目基础目录

    Returns:
        DLL文件路径

    Raises:
        SystemExit: 如果DLL文件不存在
    """
    system = platform.system()
    if system == "Windows":
        dll_name = "engine_core.dll"
    elif system == "Darwin":
        dll_name = "engine_core.dylib"
    else:
        dll_name = "engine_core.so"

    dll_path = os.path.join(base_dir, dll_name)
    if not os.path.isfile(dll_path):
        print(f"Error: Engine DLL not found: {dll_path}")
        print("Please run 'python build_engine.py' first to compile the engine.")
        sys.exit(1)
    return dll_path


def create_temp_uci_adapter(temp_dir: str, params_json_path: str,
                            base_dir: str, label: str) -> str:
    """
    创建临时UCI适配器脚本

    Args:
        temp_dir: 临时目录路径
        params_json_path: 参数JSON文件路径
        base_dir: 项目基础目录
        label: 适配器标签（用于生成文件名）

    Returns:
        生成的脚本路径
    """
    dest_params = os.path.join(temp_dir, "engine_params.json")
    shutil.copy2(params_json_path, dest_params)

    script_path = os.path.join(base_dir, f"_uci_engine_{label}.py")
    base_dir_escaped = base_dir.replace("\\", "\\\\")

    with open(script_path, "w", encoding="utf-8") as f:
        f.write("import os\n")
        f.write("import sys\n\n")
        f.write("sys.path.insert(0, r\"" + base_dir_escaped + "\")\n\n")
        f.write("from uci_engine import UCIEngine\n\n")
        f.write("if __name__ == \"__main__\":\n")
        f.write("    uci = UCIEngine()\n")
        f.write("    uci.run()\n")

    return script_path


def create_temp_uci_adapter_with_env(base_dir: str, config_path: str,
                                      label: str = "adapter") -> Tuple[str, str]:
    """
    创建临时UCI适配器（批处理文件方式）

    使用环境变量ENGINE_PARAMS传递配置路径，然后直接运行编译好的UCI引擎可执行文件。

    Args:
        base_dir: 项目基础目录
        config_path: 配置文件路径
        label: 适配器标签（用于生成临时目录前缀）

    Returns:
        (脚本路径, 临时目录路径)
    """
    from config import load_and_resolve_config

    temp_dir = tempfile.mkdtemp(prefix=f"hellcopter_{label}_")
    dest_params = os.path.join(temp_dir, "engine_params.json")

    resolved = load_and_resolve_config(config_path)
    with open(dest_params, "w", encoding="utf-8") as f:
        json.dump(resolved, f, indent=2)

    exe_path = os.path.join(base_dir, "dist", "Hellcopter.exe")

    script_path = os.path.join(temp_dir, "uci_adapter.cmd")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write("@echo off\n")
        f.write(f'set "ENGINE_PARAMS={dest_params}"\n')
        f.write(f'"{exe_path}"\n')

    return script_path, temp_dir


def calc_elo(wins: int, losses: int, draws: int) -> Optional[Tuple[int, float, float]]:
    """
    计算Elo评分差异

    Args:
        wins: 胜局数
        losses: 负局数
        draws: 和局数

    Returns:
        (总局数, 胜率, Elo差异) 或 None（如果没有对局）
    """
    total = wins + losses + draws
    if total == 0:
        return None
    p = (wins + 0.5 * draws) / total
    if p == 0:
        elo_diff = float("-inf")
    elif p == 1:
        elo_diff = float("inf")
    else:
        elo_diff = -400 * math.log10(1 / p - 1)
    return total, p, elo_diff


def calc_ci_wilson(total: int, wins: int, draws: int,
                   confidence: float = 0.95) -> Tuple[Optional[float], Optional[float]]:
    """
    使用Wilson区间计算置信区间

    Args:
        total: 总局数
        wins: 胜局数
        draws: 和局数
        confidence: 置信水平（默认0.95）

    Returns:
        (Elo下限, Elo上限) 或 (None, None)（如果没有对局）
    """
    if total == 0:
        return None, None
    z = 1.96 if confidence == 0.95 else 2.576
    p_hat = (wins + 0.5 * draws) / total
    denominator = 1 + z ** 2 / total
    centre = (p_hat + z ** 2 / (2 * total)) / denominator
    margin = z * math.sqrt((p_hat * (1 - p_hat) + z ** 2 / (4 * total)) / total) / denominator
    p_low = max(0, centre - margin)
    p_high = min(1, centre + margin)

    def p_to_elo(p: float) -> float:
        if p <= 0.0001:
            return -800
        if p >= 0.9999:
            return 800
        return -400 * math.log10(1 / p - 1)

    elo_low = p_to_elo(p_low)
    elo_high = p_to_elo(p_high)
    return elo_low, elo_high


def parse_match_output(output: str) -> Optional[Tuple[str, str, int, int, int]]:
    """
    解析比赛输出结果

    Args:
        output: cutechess-cli的输出文本

    Returns:
        (引擎A名称, 引擎B名称, 胜局, 负局, 和局) 或 None
    """
    pattern = re.compile(
        r"Score of\s+(.+?)\s+vs\s+(.+?):\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)"
    )
    last_match = None
    for line in output.splitlines():
        m = pattern.search(line)
        if m:
            last_match = (
                m.group(1).strip(),
                m.group(2).strip(),
                int(m.group(3)),
                int(m.group(4)),
                int(m.group(5)),
            )
    return last_match


def print_results(name_a: str, name_b: str, wins: int, losses: int, draws: int) -> None:
    """
    打印比赛结果

    Args:
        name_a: 引擎A名称
        name_b: 引擎B名称
        wins: 胜局数
        losses: 负局数
        draws: 和局数
    """
    result = calc_elo(wins, losses, draws)
    if result is None:
        print("No games played.")
        return

    total, p, elo_diff = result
    ci_low, ci_high = calc_ci_wilson(total, wins, draws)

    print()
    print("=" * 60)
    print(f"  {name_a} vs {name_b}")
    print("=" * 60)
    print(f"  Total games : {total}")
    print(f"  Wins (A)    : {wins}")
    print(f"  Losses (A)  : {losses}")
    print(f"  Draws       : {draws}")
    print(f"  Win rate    : {p:.4f} ({p * 100:.2f}%)")
    if math.isinf(elo_diff):
        if elo_diff > 0:
            print("  Elo diff    : +Inf (A dominates)")
        else:
            print("  Elo diff    : -Inf (B dominates)")
    else:
        print(f"  Elo diff    : {elo_diff:+.2f}")
    if ci_low is not None and ci_high is not None:
        print(f"  95% CI      : [{ci_low:+.2f}, {ci_high:+.2f}]")

    if total < 30:
        print("  Note: Very small sample (< 30 games). Results NOT reliable.")
    elif total < 100:
        print("  Note: Small sample (< 100 games). Results may not be reliable.")
    elif total < 500:
        print("  Note: Moderate sample. Consider more games for higher confidence.")
    else:
        print("  Note: Sample size sufficient for reasonable confidence.")
    print("=" * 60)
