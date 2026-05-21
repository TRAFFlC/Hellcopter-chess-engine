"""
配置管理模块

该模块负责引擎参数配置的导出、导入、版本管理和切换功能。
支持将引擎参数导出为 JSON 格式，并从 JSON 加载配置。
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path


class ConfigManager:
    """
    引擎配置管理器

    负责管理引擎参数配置的导出、导入、版本控制和切换。
    配置文件以 JSON 格式存储在 configs/ 目录下。
    """

    def __init__(self, config_dir: str = "configs"):
        """
        初始化配置管理器

        Args:
            config_dir: 配置文件存储目录，默认为 "configs"
        """
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(exist_ok=True)

    def export_config(
        self,
        version: str,
        description: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        导出引擎配置为 JSON 文件

        Args:
            version: 版本号，如 "1.0.0"
            description: 配置描述
            parameters: 引擎参数字典，如果为 None 则从引擎提取当前参数
            metadata: 元数据，包含性能基准等信息

        Returns:
            配置文件路径

        Raises:
            ValueError: 如果版本号格式不正确或已存在
        """
        # 验证版本号格式
        if not self._validate_version(version):
            raise ValueError(f"Invalid version format: {version}")

        # 检查版本是否已存在
        config_path = self._get_config_path(version)
        if config_path.exists():
            raise ValueError(f"Version {version} already exists")

        # 如果未提供参数，从引擎提取
        if parameters is None:
            parameters = self._extract_current_parameters()

        # 构建配置对象
        config = {
            "version": version,
            "created_at": datetime.now().isoformat(),
            "description": description,
            "metadata": metadata or {},
            "parameters": parameters
        }

        # 保存配置文件
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        return str(config_path)

    def import_config(self, version: str) -> Dict[str, Any]:
        config_path = self._get_config_path(version)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        if "base_version" in config:
            from config import resolve_config
            config = resolve_config(config)

        self._validate_config(config)

        return config

    def list_versions(self) -> List[Dict[str, Any]]:
        """
        列出所有可用的配置版本

        Returns:
            版本信息列表，每个元素包含 version, created_at, description
        """
        versions = []

        for config_file in self.config_dir.glob("v*.json"):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    versions.append({
                        "version": config.get("version", "unknown"),
                        "created_at": config.get("created_at", ""),
                        "description": config.get("description", "")
                    })
            except (json.JSONDecodeError, KeyError):
                continue

        # 按创建时间排序
        versions.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return versions

    def switch_version(self, version: str) -> None:
        """
        切换到指定版本的配置

        该方法会加载指定版本的配置并生成 C 头文件，
        然后需要重新编译引擎以应用新配置。

        Args:
            version: 目标版本号

        Raises:
            FileNotFoundError: 如果配置文件不存在
        """
        config = self.import_config(version)
        self._generate_c_header(config["parameters"])
        self._export_runtime_json(config["parameters"])

    def compare_versions(self, version1: str, version2: str) -> Dict[str, Any]:
        """
        对比两个版本的配置差异

        Args:
            version1: 第一个版本号
            version2: 第二个版本号

        Returns:
            差异字典，包含 added, removed, modified 三个键
        """
        config1 = self.import_config(version1)
        config2 = self.import_config(version2)

        params1 = config1["parameters"]
        params2 = config2["parameters"]

        diff = {
            "added": {},
            "removed": {},
            "modified": {}
        }

        # 递归比较参数
        self._compare_dicts(params1, params2, diff, "")

        return diff

    def delete_version(self, version: str) -> None:
        """
        删除指定版本的配置

        Args:
            version: 要删除的版本号

        Raises:
            FileNotFoundError: 如果配置文件不存在
        """
        config_path = self._get_config_path(version)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        config_path.unlink()

    def _extract_current_parameters(self) -> Dict[str, Any]:
        """
        从 engine_core.c 提取当前参数

        该方法解析 engine_core.c 文件，提取所有可配置参数。

        Returns:
            参数字典
        """
        # 读取 engine_core.c 文件
        engine_core_path = Path("engine_core.c")
        if not engine_core_path.exists():
            # 如果文件不存在，返回默认值
            return self._get_default_parameters()

        try:
            with open(engine_core_path, 'r', encoding='utf-8') as f:
                source_code = f.read()
        except Exception as e:
            print(f"Warning: Failed to read engine_core.c: {e}")
            return self._get_default_parameters()

        # 提取参数
        parameters = {
            "piece_values": self._extract_piece_values(source_code),
            "pst": {
                "mg_pawn": self._extract_pst_from_source("mg_pawn", source_code),
                "eg_pawn": self._extract_pst_from_source("eg_pawn", source_code),
                "mg_knight": self._extract_pst_from_source("mg_knight", source_code),
                "eg_knight": self._extract_pst_from_source("eg_knight", source_code),
                "mg_bishop": self._extract_pst_from_source("mg_bishop", source_code),
                "eg_bishop": self._extract_pst_from_source("eg_bishop", source_code),
                "mg_rook": self._extract_pst_from_source("mg_rook", source_code),
                "eg_rook": self._extract_pst_from_source("eg_rook", source_code),
                "mg_queen": self._extract_pst_from_source("mg_queen", source_code),
                "eg_queen": self._extract_pst_from_source("eg_queen", source_code),
                "mg_king": self._extract_pst_from_source("mg_king", source_code),
                "eg_king": self._extract_pst_from_source("eg_king", source_code)
            },
            "eval_weights": {
                "bishop_pair_bonus": 50,
                "doubled_pawn_penalty": -10,
                "isolated_pawn_penalty": -20,
                "passed_pawn_bonus": [0, 10, 20, 30, 50, 80, 120, 0],
                "open_file_bonus": 15,
                "semi_open_file_bonus": 10
            },
            "search_params": {
                "null_move_reduction": 2,
                "null_move_min_depth": 3,
                "lmr_enabled": False,
                "lmr_min_depth": 3,
                "lmr_move_threshold": 2,
                "futility_enabled": False,
                "futility_margin_base": 150,
                "razoring_enabled": False,
                "razoring_margin": 300
            },
            "constants": self._extract_constants(source_code),
            "threading": {
                "enabled": False,
                "num_threads": 1
            }
        }

        return parameters

    def _extract_piece_values(self, source_code: str) -> Dict[str, int]:
        """
        从源代码中提取棋子价值数组

        Args:
            source_code: engine_core.c 的源代码

        Returns:
            棋子价值字典
        """
        import re

        # 查找 piece_values 数组定义
        # 格式: static const int piece_values[7] = {0, 100, 300, 320, 480, 900, 20000};
        pattern = r'static\s+const\s+int\s+piece_values\s*\[\s*\d+\s*\]\s*=\s*\{([^}]+)\}'
        match = re.search(pattern, source_code)

        if match:
            values_str = match.group(1)
            # 提取所有数字
            values = [int(x.strip())
                      for x in values_str.split(',') if x.strip()]

            # piece_values[7] = {0, pawn, knight, bishop, rook, queen, king}
            if len(values) >= 7:
                return {
                    "pawn": values[1],
                    "knight": values[2],
                    "bishop": values[3],
                    "rook": values[4],
                    "queen": values[5],
                    "king": values[6]
                }

        # 如果提取失败，返回默认值
        return {
            "pawn": 100,
            "knight": 300,
            "bishop": 320,
            "rook": 480,
            "queen": 900,
            "king": 20000
        }

    def _extract_constants(self, source_code: str) -> Dict[str, int]:
        """
        从源代码中提取常量（MATE_SCORE 和 DELTA）

        Args:
            source_code: engine_core.c 的源代码

        Returns:
            常量字典
        """
        import re

        constants = {
            "mate_score": 900000,
            "delta": 900
        }

        # 提取 MATE_SCORE
        mate_pattern = r'#define\s+MATE_SCORE\s+(\d+)'
        mate_match = re.search(mate_pattern, source_code)
        if mate_match:
            constants["mate_score"] = int(mate_match.group(1))

        # 提取 DELTA
        delta_pattern = r'#define\s+DELTA\s+(\d+)'
        delta_match = re.search(delta_pattern, source_code)
        if delta_match:
            constants["delta"] = int(delta_match.group(1))

        return constants

    def _get_default_parameters(self) -> Dict[str, Any]:
        """
        获取默认参数（当无法从源文件提取时使用）

        Returns:
            默认参数字典
        """
        return {
            "piece_values": {
                "pawn": 100,
                "knight": 300,
                "bishop": 320,
                "rook": 480,
                "queen": 900,
                "king": 20000
            },
            "pst": {
                "mg_pawn": self._get_default_pst("mg_pawn"),
                "eg_pawn": self._get_default_pst("eg_pawn"),
                "mg_knight": self._get_default_pst("mg_knight"),
                "eg_knight": self._get_default_pst("eg_knight"),
                "mg_bishop": self._get_default_pst("mg_bishop"),
                "eg_bishop": self._get_default_pst("eg_bishop"),
                "mg_rook": self._get_default_pst("mg_rook"),
                "eg_rook": self._get_default_pst("eg_rook"),
                "mg_queen": self._get_default_pst("mg_queen"),
                "eg_queen": self._get_default_pst("eg_queen"),
                "mg_king": self._get_default_pst("mg_king"),
                "eg_king": self._get_default_pst("eg_king")
            },
            "eval_weights": {
                "bishop_pair_bonus": 50,
                "doubled_pawn_penalty": -10,
                "isolated_pawn_penalty": -20,
                "passed_pawn_bonus": [0, 10, 20, 30, 50, 80, 120, 0],
                "open_file_bonus": 15,
                "semi_open_file_bonus": 10
            },
            "search_params": {
                "null_move_reduction": 2,
                "null_move_min_depth": 3,
                "lmr_enabled": False,
                "lmr_min_depth": 3,
                "lmr_move_threshold": 2,
                "futility_enabled": False,
                "futility_margin_base": 150,
                "razoring_enabled": False,
                "razoring_margin": 300
            },
            "constants": {
                "mate_score": 900000,
                "delta": 900
            },
            "threading": {
                "enabled": False,
                "num_threads": 1
            }
        }

    def _extract_pst_from_source(self, table_name: str, source_code: str) -> List[int]:
        """
        从 engine_core.c 源文件中提取位置价值表

        Args:
            table_name: 表名，如 "mg_pawn"
            source_code: engine_core.c 的源代码

        Returns:
            64 个整数的列表
        """
        import re

        # 查找 PST 数组定义
        # 格式: static const int mg_pawn[64] = { ... };
        pattern = rf'static\s+const\s+int\s+{table_name}\s*\[\s*64\s*\]\s*=\s*\{{([^}}]+)\}}'
        match = re.search(pattern, source_code, re.DOTALL)

        if match:
            values_str = match.group(1)
            # 提取所有数字（包括负数）
            numbers = re.findall(r'-?\d+', values_str)
            values = [int(x) for x in numbers]

            # 确保有 64 个值
            if len(values) == 64:
                return values
            else:
                print(
                    f"Warning: {table_name} has {len(values)} values, expected 64")

        # 如果提取失败，返回默认值
        return self._get_default_pst(table_name)

    def _get_default_pst(self, table_name: str) -> List[int]:
        """
        获取默认的 PST 值

        Args:
            table_name: 表名

        Returns:
            64 个整数的列表
        """
        default_psts = {
            "mg_pawn": [
                0, 0, 0, 0, 0, 0, 0, 0,
                90, 90, 90, 90, 90, 90, 90, 90,
                50, 50, 60, 80, 80, 60, 50, 50,
                20, 20, 40, 65, 65, 40, 20, 20,
                10, 10, 20, 45, 45, 20, 10, 10,
                5, 0, -5, 10, 10, -5, 0, 5,
                5, 10, 10, 0, 0, 10, 10, 5,
                0, 0, 0, 0, 0, 0, 0, 0
            ],
            "eg_pawn": [
                0, 0, 0, 0, 0, 0, 0, 0,
                80, 80, 80, 80, 80, 80, 80, 80,
                50, 50, 50, 50, 50, 50, 50, 50,
                30, 30, 30, 30, 30, 30, 30, 30,
                20, 20, 20, 20, 20, 20, 20, 20,
                10, 10, 10, 10, 10, 10, 10, 10,
                0, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0, 0, 0, 0, 0, 0
            ],
            "mg_knight": [
                -50, -40, -30, -30, -30, -30, -40, -50,
                -40, -20, 0, 0, 0, 0, -20, -40,
                -30, 0, 10, 15, 15, 10, 0, -30,
                -30, 5, 15, 30, 30, 15, 5, -30,
                -30, 0, 15, 30, 30, 15, 0, -30,
                -30, 5, 10, 15, 15, 10, 5, -30,
                -40, -20, 0, 5, 5, 0, -20, -40,
                -50, -40, -30, -30, -30, -30, -40, -50
            ],
            "eg_knight": [
                -50, -40, -30, -30, -30, -30, -40, -50,
                -40, -20, 0, 0, 0, 0, -20, -40,
                -30, 0, 10, 15, 15, 10, 0, -30,
                -30, 0, 15, 25, 25, 15, 0, -30,
                -30, 0, 15, 25, 25, 15, 0, -30,
                -30, 0, 10, 15, 15, 10, 0, -30,
                -40, -20, 0, 0, 0, 0, -20, -40,
                -50, -40, -30, -30, -30, -30, -40, -50
            ],
            "mg_bishop": [
                -20, -10, -10, -10, -10, -10, -10, -20,
                -10, 0, 0, 0, 0, 0, 0, -10,
                -10, 0, 5, 10, 10, 5, 0, -10,
                -10, 5, 5, 10, 10, 5, 5, -10,
                -10, 0, 10, 10, 10, 10, 0, -10,
                -10, 10, 10, 10, 10, 10, 10, -10,
                -10, 5, 0, 0, 0, 0, 5, -10,
                -20, -10, -10, -10, -10, -10, -10, -20
            ],
            "eg_bishop": [
                -20, -10, -10, -10, -10, -10, -10, -20,
                -10, 0, 0, 0, 0, 0, 0, -10,
                -10, 0, 5, 10, 10, 5, 0, -10,
                -10, 0, 10, 10, 10, 10, 0, -10,
                -10, 0, 10, 10, 10, 10, 0, -10,
                -10, 0, 10, 10, 10, 10, 0, -10,
                -10, 0, 0, 0, 0, 0, 0, -10,
                -20, -10, -10, -10, -10, -10, -10, -20
            ],
            "mg_rook": [
                0, 0, 0, 0, 0, 0, 0, 0,
                5, 10, 10, 10, 10, 10, 10, 5,
                -5, 0, 0, 0, 0, 0, 0, -5,
                -5, 0, 0, 0, 0, 0, 0, -5,
                -5, 0, 0, 0, 0, 0, 0, -5,
                -5, 0, 0, 0, 0, 0, 0, -5,
                -5, 0, 0, 0, 0, 0, 0, -5,
                0, 0, 0, 5, 5, 0, 0, 0
            ],
            "eg_rook": [
                0, 0, 0, 0, 0, 0, 0, 0,
                5, 10, 10, 10, 10, 10, 10, 5,
                -5, 0, 0, 0, 0, 0, 0, -5,
                -5, 0, 0, 0, 0, 0, 0, -5,
                -5, 0, 0, 0, 0, 0, 0, -5,
                -5, 0, 0, 0, 0, 0, 0, -5,
                -5, 0, 0, 0, 0, 0, 0, -5,
                0, 0, 0, 5, 5, 0, 0, 0
            ],
            "mg_queen": [
                -20, -10, -10, -5, -5, -10, -10, -20,
                -10, 0, 0, 0, 0, 0, 0, -10,
                -10, 0, 5, 5, 5, 5, 0, -10,
                -5, 0, 5, 5, 5, 5, 0, -5,
                0, 0, 5, 5, 5, 5, 0, -5,
                -10, 5, 5, 5, 5, 5, 0, -10,
                -10, 0, 5, 0, 0, 0, 0, -10,
                -20, -10, -10, -5, -5, -10, -10, -20
            ],
            "eg_queen": [
                -20, -10, -10, -5, -5, -10, -10, -20,
                -10, 0, 0, 0, 0, 0, 0, -10,
                -10, 0, 5, 5, 5, 5, 0, -10,
                -5, 0, 5, 5, 5, 5, 0, -5,
                0, 0, 5, 5, 5, 5, 0, -5,
                -10, 5, 5, 5, 5, 5, 0, -10,
                -10, 0, 5, 0, 0, 0, 0, -10,
                -20, -10, -10, -5, -5, -10, -10, -20
            ],
            "mg_king": [
                -30, -40, -40, -50, -50, -40, -40, -30,
                -30, -40, -40, -50, -50, -40, -40, -30,
                -30, -40, -40, -50, -50, -40, -40, -30,
                -30, -40, -40, -50, -50, -40, -40, -30,
                -20, -30, -30, -40, -40, -30, -30, -20,
                -10, -20, -20, -20, -20, -20, -20, -10,
                20, 20, 0, 0, 0, 0, 20, 20,
                20, 30, 10, 0, 0, 10, 30, 20
            ],
            "eg_king": [
                -50, -40, -30, -20, -20, -30, -40, -50,
                -30, -20, -10, 0, 0, -10, -20, -30,
                -30, -10, 20, 30, 30, 20, -10, -30,
                -30, -10, 30, 40, 40, 30, -10, -30,
                -30, -10, 30, 40, 40, 30, -10, -30,
                -30, -10, 20, 30, 30, 20, -10, -30,
                -30, -30, 0, 0, 0, 0, -30, -30,
                -50, -30, -30, -30, -30, -30, -30, -50
            ]
        }

        return default_psts.get(table_name, [0] * 64)

    def _generate_c_header(self, parameters: Dict[str, Any]) -> None:
        """
        从配置参数生成 C 头文件

        该方法将配置参数转换为 C 语言头文件格式，
        供引擎编译时使用。

        Args:
            parameters: 参数字典
        """
        header_path = Path("engine_params.h")

        with open(header_path, 'w', encoding='utf-8') as f:
            f.write("/* Auto-generated engine parameters */\n")
            f.write("/* DO NOT EDIT MANUALLY */\n\n")
            f.write("#ifndef ENGINE_PARAMS_H\n")
            f.write("#define ENGINE_PARAMS_H\n\n")

            # 棋子价值
            piece_values = parameters.get("piece_values", {})
            f.write("/* Piece values */\n")
            f.write(f"#define PAWN_VALUE {piece_values.get('pawn', 100)}\n")
            f.write(
                f"#define KNIGHT_VALUE {piece_values.get('knight', 300)}\n")
            f.write(
                f"#define BISHOP_VALUE {piece_values.get('bishop', 320)}\n")
            f.write(f"#define ROOK_VALUE {piece_values.get('rook', 480)}\n")
            f.write(f"#define QUEEN_VALUE {piece_values.get('queen', 900)}\n")
            f.write(
                f"#define KING_VALUE {piece_values.get('king', 20000)}\n\n")

            # PST 表
            pst = parameters.get("pst", {})
            for table_name, values in pst.items():
                f.write(f"/* {table_name} */\n")
                f.write(f"static const int {table_name}[64] = {{\n")
                for i in range(0, 64, 8):
                    row = ", ".join(str(v) for v in values[i:i+8])
                    f.write(f"    {row},\n")
                f.write("};\n\n")

            # 评估权重
            eval_weights = parameters.get("eval_weights", {})
            f.write("/* Evaluation weights */\n")
            f.write(
                f"#define BISHOP_PAIR_BONUS {eval_weights.get('bishop_pair_bonus', 50)}\n")
            f.write(
                f"#define DOUBLED_PAWN_PENALTY {eval_weights.get('doubled_pawn_penalty', -10)}\n")
            f.write(
                f"#define ISOLATED_PAWN_PENALTY {eval_weights.get('isolated_pawn_penalty', -20)}\n")
            f.write(
                f"#define PAWN_CHAIN_BONUS {eval_weights.get('pawn_chain_bonus', 10)}\n\n")

            ppb = eval_weights.get('passed_pawn_bonus', [
                                   0, 10, 20, 30, 50, 80, 120, 0])
            f.write("static const int passed_pawn_bonus[8] = {\n")
            f.write("    " + ", ".join(str(v) for v in ppb) + "\n")
            f.write("};\n\n")

            f.write(
                f"#define OPEN_FILE_BONUS {eval_weights.get('open_file_bonus', 15)}\n")
            f.write(
                f"#define SEMI_OPEN_FILE_BONUS {eval_weights.get('semi_open_file_bonus', 10)}\n")
            f.write(
                f"#define ROOK_POTENTIAL_OPEN_FILE {eval_weights.get('rook_potential_open_file', 8)}\n")
            f.write(
                f"#define ROOK_POTENTIAL_SEMI_OPEN {eval_weights.get('rook_potential_semi_open', 4)}\n")
            f.write(
                f"#define ROOK_ON_7TH_BONUS {eval_weights.get('rook_on_7th_bonus', 30)}\n")
            f.write(
                f"#define ROOK_ON_7TH_WITH_KING {eval_weights.get('rook_on_7th_with_king', 20)}\n")
            f.write(
                f"#define BISHOP_MOBILITY_BONUS {eval_weights.get('bishop_mobility_bonus', 15)}\n")
            f.write(
                f"#define BISHOP_BAD_PENALTY {eval_weights.get('bishop_bad_penalty', -15)}\n\n")

            # 搜索参数
            search_params = parameters.get("search_params", {})
            f.write("/* Search parameters */\n")
            f.write(
                f"#define NULL_MOVE_REDUCTION {search_params.get('null_move_reduction', 2)}\n")
            f.write(
                f"#define NULL_MOVE_MIN_DEPTH {search_params.get('null_move_min_depth', 3)}\n")
            f.write(
                f"#define NULL_MOVE_VERIFICATION_DEPTH {search_params.get('null_move_verification_depth', 6)}\n")
            f.write(
                f"#define NULL_MOVE_VERIFICATION_REDUCTION {search_params.get('null_move_verification_reduction', 5)}\n")
            f.write(
                f"#define LMR_ENABLED {1 if search_params.get('lmr_enabled', False) else 0}\n")
            f.write(
                f"#define LMR_MIN_DEPTH {search_params.get('lmr_min_depth', 3)}\n")
            f.write(
                f"#define LMR_MOVE_THRESHOLD {search_params.get('lmr_move_threshold', 2)}\n")
            f.write(
                f"#define FUTILITY_ENABLED {1 if search_params.get('futility_enabled', False) else 0}\n")
            f.write(
                f"#define FUTILITY_MARGIN_BASE {search_params.get('futility_margin_base', 150)}\n")
            f.write(
                f"#define RAZORING_ENABLED {1 if search_params.get('razoring_enabled', False) else 0}\n")
            f.write(
                f"#define RAZORING_MARGIN {search_params.get('razoring_margin', 300)}\n\n")

            # 常量
            constants = parameters.get("constants", {})
            f.write("/* Constants */\n")
            f.write(
                f"#define MATE_SCORE {constants.get('mate_score', 900000)}\n")
            f.write(f"#define DELTA {constants.get('delta', 900)}\n\n")

            # 多线程
            threading = parameters.get("threading", {})
            f.write("/* Threading */\n")
            f.write(
                f"#define THREADING_ENABLED {1 if threading.get('enabled', False) else 0}\n")
            f.write(
                f"#define NUM_THREADS {threading.get('num_threads', 1)}\n\n")

            f.write("#endif /* ENGINE_PARAMS_H */\n")

    def _export_runtime_json(self, parameters: Dict[str, Any]) -> None:
        runtime = {"parameters": parameters}
        json_path = Path("engine_params.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(runtime, f, indent=2, ensure_ascii=False)

    def _validate_version(self, version: str) -> bool:
        """
        验证版本号格式

        Args:
            version: 版本号字符串

        Returns:
            是否有效
        """
        # 简单验证：版本号应该是 x.y.z 格式
        parts = version.split('.')
        if len(parts) != 3:
            return False

        try:
            for part in parts:
                int(part)
            return True
        except ValueError:
            return False

    def _validate_config(self, config: Dict[str, Any]) -> None:
        """
        验证配置文件格式

        该方法执行完整的 JSON schema 验证，包括：
        - 必需字段检查
        - 参数类型验证
        - 参数范围验证
        - 数据完整性检查

        Args:
            config: 配置字典

        Raises:
            ValueError: 如果配置格式不正确，包含详细的错误信息
        """
        errors = []

        # 1. 验证顶层必需字段
        required_top_keys = ["version", "created_at", "parameters"]
        for key in required_top_keys:
            if key not in config:
                errors.append(f"Missing required top-level field: '{key}'")

        # 如果缺少关键字段，立即返回
        if errors:
            raise ValueError(
                "Config validation failed:\n  - " + "\n  - ".join(errors))

        # 2. 验证版本号格式
        version = config.get("version", "")
        if not self._validate_version(version):
            errors.append(
                f"Invalid version format: '{version}' (expected format: x.y.z)")

        # 3. 验证 created_at 格式
        created_at = config.get("created_at", "")
        if not self._validate_timestamp(created_at):
            errors.append(
                f"Invalid timestamp format: '{created_at}' (expected ISO 8601 format)")

        # 4. 验证参数结构
        params = config["parameters"]
        required_param_keys = [
            "piece_values", "pst", "eval_weights", "search_params", "constants", "threading"]
        for key in required_param_keys:
            if key not in params:
                errors.append(
                    f"Missing required parameter section: 'parameters.{key}'")

        # 如果缺少参数部分，无法继续验证
        if errors:
            raise ValueError(
                "Config validation failed:\n  - " + "\n  - ".join(errors))

        # 5. 验证棋子价值
        piece_values_errors = self._validate_piece_values(
            params.get("piece_values", {}))
        errors.extend(piece_values_errors)

        # 6. 验证位置价值表 (PST)
        pst_errors = self._validate_pst(params.get("pst", {}))
        errors.extend(pst_errors)

        # 7. 验证评估权重
        eval_weights_errors = self._validate_eval_weights(
            params.get("eval_weights", {}))
        errors.extend(eval_weights_errors)

        # 8. 验证搜索参数
        search_params_errors = self._validate_search_params(
            params.get("search_params", {}))
        errors.extend(search_params_errors)

        # 9. 验证常量
        constants_errors = self._validate_constants(
            params.get("constants", {}))
        errors.extend(constants_errors)

        # 10. 验证多线程配置
        threading_errors = self._validate_threading(
            params.get("threading", {}))
        errors.extend(threading_errors)

        # 如果有任何错误，抛出异常
        if errors:
            raise ValueError(
                "Config validation failed:\n  - " + "\n  - ".join(errors))

    def _validate_timestamp(self, timestamp: str) -> bool:
        """
        验证时间戳格式（ISO 8601）

        Args:
            timestamp: 时间戳字符串

        Returns:
            是否有效
        """
        try:
            datetime.fromisoformat(timestamp)
            return True
        except (ValueError, TypeError):
            return False

    def _validate_piece_values(self, piece_values: Dict[str, Any]) -> List[str]:
        """
        验证棋子价值

        Args:
            piece_values: 棋子价值字典

        Returns:
            错误信息列表
        """
        errors = []
        required_pieces = ["pawn", "knight", "bishop", "rook", "queen", "king"]

        # 检查必需的棋子
        for piece in required_pieces:
            if piece not in piece_values:
                errors.append(
                    f"Missing piece value: 'parameters.piece_values.{piece}'")
                continue

            value = piece_values[piece]

            # 检查类型
            if not isinstance(value, int):
                errors.append(
                    f"Invalid type for 'parameters.piece_values.{piece}': expected int, got {type(value).__name__}")
                continue

            # 检查范围
            if piece == "pawn":
                if not (50 <= value <= 200):
                    errors.append(
                        f"Value out of range for 'parameters.piece_values.{piece}': {value} (expected 50-200)")
            elif piece == "knight":
                if not (200 <= value <= 500):
                    errors.append(
                        f"Value out of range for 'parameters.piece_values.{piece}': {value} (expected 200-500)")
            elif piece == "bishop":
                if not (200 <= value <= 500):
                    errors.append(
                        f"Value out of range for 'parameters.piece_values.{piece}': {value} (expected 200-500)")
            elif piece == "rook":
                if not (300 <= value <= 700):
                    errors.append(
                        f"Value out of range for 'parameters.piece_values.{piece}': {value} (expected 300-700)")
            elif piece == "queen":
                if not (600 <= value <= 1200):
                    errors.append(
                        f"Value out of range for 'parameters.piece_values.{piece}': {value} (expected 600-1200)")
            elif piece == "king":
                if not (10000 <= value <= 50000):
                    errors.append(
                        f"Value out of range for 'parameters.piece_values.{piece}': {value} (expected 10000-50000)")

        return errors

    def _validate_pst(self, pst: Dict[str, Any]) -> List[str]:
        """
        验证位置价值表

        Args:
            pst: PST 字典

        Returns:
            错误信息列表
        """
        errors = []
        required_tables = [
            "mg_pawn", "eg_pawn",
            "mg_knight", "eg_knight",
            "mg_bishop", "eg_bishop",
            "mg_rook", "eg_rook",
            "mg_queen", "eg_queen",
            "mg_king", "eg_king"
        ]

        for table_name in required_tables:
            if table_name not in pst:
                errors.append(
                    f"Missing PST table: 'parameters.pst.{table_name}'")
                continue

            table = pst[table_name]

            # 检查类型
            if not isinstance(table, list):
                errors.append(
                    f"Invalid type for 'parameters.pst.{table_name}': expected list, got {type(table).__name__}")
                continue

            # 检查长度
            if len(table) != 64:
                errors.append(
                    f"Invalid length for 'parameters.pst.{table_name}': expected 64 elements, got {len(table)}")
                continue

            # 检查每个元素的类型
            for i, value in enumerate(table):
                if not isinstance(value, int):
                    errors.append(
                        f"Invalid type for 'parameters.pst.{table_name}[{i}]': expected int, got {type(value).__name__}")
                    break  # 只报告第一个类型错误

            # 检查值的范围（PST 值通常在 -200 到 200 之间）
            for i, value in enumerate(table):
                if isinstance(value, int) and not (-500 <= value <= 500):
                    errors.append(
                        f"Value out of range for 'parameters.pst.{table_name}[{i}]': {value} (expected -500 to 500)")
                    break  # 只报告第一个范围错误

        return errors

    def _validate_eval_weights(self, eval_weights: Dict[str, Any]) -> List[str]:
        """
        验证评估权重

        Args:
            eval_weights: 评估权重字典

        Returns:
            错误信息列表
        """
        errors = []

        # 验证 bishop_pair_bonus
        if "bishop_pair_bonus" not in eval_weights:
            errors.append(
                "Missing field: 'parameters.eval_weights.bishop_pair_bonus'")
        elif not isinstance(eval_weights["bishop_pair_bonus"], int):
            errors.append(
                f"Invalid type for 'parameters.eval_weights.bishop_pair_bonus': expected int, got {type(eval_weights['bishop_pair_bonus']).__name__}")
        elif not (0 <= eval_weights["bishop_pair_bonus"] <= 200):
            errors.append(
                f"Value out of range for 'parameters.eval_weights.bishop_pair_bonus': {eval_weights['bishop_pair_bonus']} (expected 0-200)")

        # 验证 doubled_pawn_penalty
        if "doubled_pawn_penalty" not in eval_weights:
            errors.append(
                "Missing field: 'parameters.eval_weights.doubled_pawn_penalty'")
        elif not isinstance(eval_weights["doubled_pawn_penalty"], int):
            errors.append(
                f"Invalid type for 'parameters.eval_weights.doubled_pawn_penalty': expected int, got {type(eval_weights['doubled_pawn_penalty']).__name__}")
        elif not (-100 <= eval_weights["doubled_pawn_penalty"] <= 0):
            errors.append(
                f"Value out of range for 'parameters.eval_weights.doubled_pawn_penalty': {eval_weights['doubled_pawn_penalty']} (expected -100 to 0)")

        # 验证 isolated_pawn_penalty
        if "isolated_pawn_penalty" not in eval_weights:
            errors.append(
                "Missing field: 'parameters.eval_weights.isolated_pawn_penalty'")
        elif not isinstance(eval_weights["isolated_pawn_penalty"], int):
            errors.append(
                f"Invalid type for 'parameters.eval_weights.isolated_pawn_penalty': expected int, got {type(eval_weights['isolated_pawn_penalty']).__name__}")
        elif not (-100 <= eval_weights["isolated_pawn_penalty"] <= 0):
            errors.append(
                f"Value out of range for 'parameters.eval_weights.isolated_pawn_penalty': {eval_weights['isolated_pawn_penalty']} (expected -100 to 0)")

        # 验证 passed_pawn_bonus
        if "passed_pawn_bonus" not in eval_weights:
            errors.append(
                "Missing field: 'parameters.eval_weights.passed_pawn_bonus'")
        elif not isinstance(eval_weights["passed_pawn_bonus"], list):
            errors.append(
                f"Invalid type for 'parameters.eval_weights.passed_pawn_bonus': expected list, got {type(eval_weights['passed_pawn_bonus']).__name__}")
        elif len(eval_weights["passed_pawn_bonus"]) != 8:
            errors.append(
                f"Invalid length for 'parameters.eval_weights.passed_pawn_bonus': expected 8 elements, got {len(eval_weights['passed_pawn_bonus'])}")
        else:
            for i, value in enumerate(eval_weights["passed_pawn_bonus"]):
                if not isinstance(value, int):
                    errors.append(
                        f"Invalid type for 'parameters.eval_weights.passed_pawn_bonus[{i}]': expected int, got {type(value).__name__}")
                    break
                if not (0 <= value <= 200):
                    errors.append(
                        f"Value out of range for 'parameters.eval_weights.passed_pawn_bonus[{i}]': {value} (expected 0-200)")
                    break

        # 验证 open_file_bonus
        if "open_file_bonus" not in eval_weights:
            errors.append(
                "Missing field: 'parameters.eval_weights.open_file_bonus'")
        elif not isinstance(eval_weights["open_file_bonus"], int):
            errors.append(
                f"Invalid type for 'parameters.eval_weights.open_file_bonus': expected int, got {type(eval_weights['open_file_bonus']).__name__}")
        elif not (0 <= eval_weights["open_file_bonus"] <= 100):
            errors.append(
                f"Value out of range for 'parameters.eval_weights.open_file_bonus': {eval_weights['open_file_bonus']} (expected 0-100)")

        # 验证 semi_open_file_bonus
        if "semi_open_file_bonus" not in eval_weights:
            errors.append(
                "Missing field: 'parameters.eval_weights.semi_open_file_bonus'")
        elif not isinstance(eval_weights["semi_open_file_bonus"], int):
            errors.append(
                f"Invalid type for 'parameters.eval_weights.semi_open_file_bonus': expected int, got {type(eval_weights['semi_open_file_bonus']).__name__}")
        elif not (0 <= eval_weights["semi_open_file_bonus"] <= 100):
            errors.append(
                f"Value out of range for 'parameters.eval_weights.semi_open_file_bonus': {eval_weights['semi_open_file_bonus']} (expected 0-100)")

        return errors

    def _validate_search_params(self, search_params: Dict[str, Any]) -> List[str]:
        """
        验证搜索参数

        Args:
            search_params: 搜索参数字典

        Returns:
            错误信息列表
        """
        errors = []

        # 验证 null_move_reduction
        if "null_move_reduction" not in search_params:
            errors.append(
                "Missing field: 'parameters.search_params.null_move_reduction'")
        elif not isinstance(search_params["null_move_reduction"], int):
            errors.append(
                f"Invalid type for 'parameters.search_params.null_move_reduction': expected int, got {type(search_params['null_move_reduction']).__name__}")
        elif not (1 <= search_params["null_move_reduction"] <= 4):
            errors.append(
                f"Value out of range for 'parameters.search_params.null_move_reduction': {search_params['null_move_reduction']} (expected 1-4)")

        # 验证 null_move_min_depth
        if "null_move_min_depth" not in search_params:
            errors.append(
                "Missing field: 'parameters.search_params.null_move_min_depth'")
        elif not isinstance(search_params["null_move_min_depth"], int):
            errors.append(
                f"Invalid type for 'parameters.search_params.null_move_min_depth': expected int, got {type(search_params['null_move_min_depth']).__name__}")
        elif not (1 <= search_params["null_move_min_depth"] <= 10):
            errors.append(
                f"Value out of range for 'parameters.search_params.null_move_min_depth': {search_params['null_move_min_depth']} (expected 1-10)")

        # 验证 LMR 参数
        if "lmr_enabled" not in search_params:
            errors.append(
                "Missing field: 'parameters.search_params.lmr_enabled'")
        elif not isinstance(search_params["lmr_enabled"], bool):
            errors.append(
                f"Invalid type for 'parameters.search_params.lmr_enabled': expected bool, got {type(search_params['lmr_enabled']).__name__}")

        if "lmr_min_depth" not in search_params:
            errors.append(
                "Missing field: 'parameters.search_params.lmr_min_depth'")
        elif not isinstance(search_params["lmr_min_depth"], int):
            errors.append(
                f"Invalid type for 'parameters.search_params.lmr_min_depth': expected int, got {type(search_params['lmr_min_depth']).__name__}")
        elif not (1 <= search_params["lmr_min_depth"] <= 10):
            errors.append(
                f"Value out of range for 'parameters.search_params.lmr_min_depth': {search_params['lmr_min_depth']} (expected 1-10)")

        if "lmr_move_threshold" not in search_params:
            errors.append(
                "Missing field: 'parameters.search_params.lmr_move_threshold'")
        elif not isinstance(search_params["lmr_move_threshold"], int):
            errors.append(
                f"Invalid type for 'parameters.search_params.lmr_move_threshold': expected int, got {type(search_params['lmr_move_threshold']).__name__}")
        elif not (1 <= search_params["lmr_move_threshold"] <= 10):
            errors.append(
                f"Value out of range for 'parameters.search_params.lmr_move_threshold': {search_params['lmr_move_threshold']} (expected 1-10)")

        # 验证 Futility Pruning 参数
        if "futility_enabled" not in search_params:
            errors.append(
                "Missing field: 'parameters.search_params.futility_enabled'")
        elif not isinstance(search_params["futility_enabled"], bool):
            errors.append(
                f"Invalid type for 'parameters.search_params.futility_enabled': expected bool, got {type(search_params['futility_enabled']).__name__}")

        if "futility_margin_base" not in search_params:
            errors.append(
                "Missing field: 'parameters.search_params.futility_margin_base'")
        elif not isinstance(search_params["futility_margin_base"], int):
            errors.append(
                f"Invalid type for 'parameters.search_params.futility_margin_base': expected int, got {type(search_params['futility_margin_base']).__name__}")
        elif not (50 <= search_params["futility_margin_base"] <= 500):
            errors.append(
                f"Value out of range for 'parameters.search_params.futility_margin_base': {search_params['futility_margin_base']} (expected 50-500)")

        # 验证 Razoring 参数
        if "razoring_enabled" not in search_params:
            errors.append(
                "Missing field: 'parameters.search_params.razoring_enabled'")
        elif not isinstance(search_params["razoring_enabled"], bool):
            errors.append(
                f"Invalid type for 'parameters.search_params.razoring_enabled': expected bool, got {type(search_params['razoring_enabled']).__name__}")

        if "razoring_margin" not in search_params:
            errors.append(
                "Missing field: 'parameters.search_params.razoring_margin'")
        elif not isinstance(search_params["razoring_margin"], int):
            errors.append(
                f"Invalid type for 'parameters.search_params.razoring_margin': expected int, got {type(search_params['razoring_margin']).__name__}")
        elif not (100 <= search_params["razoring_margin"] <= 1000):
            errors.append(
                f"Value out of range for 'parameters.search_params.razoring_margin': {search_params['razoring_margin']} (expected 100-1000)")

        return errors

    def _validate_constants(self, constants: Dict[str, Any]) -> List[str]:
        """
        验证常量

        Args:
            constants: 常量字典

        Returns:
            错误信息列表
        """
        errors = []

        # 验证 mate_score
        if "mate_score" not in constants:
            errors.append("Missing field: 'parameters.constants.mate_score'")
        elif not isinstance(constants["mate_score"], int):
            errors.append(
                f"Invalid type for 'parameters.constants.mate_score': expected int, got {type(constants['mate_score']).__name__}")
        elif not (100000 <= constants["mate_score"] <= 10000000):
            errors.append(
                f"Value out of range for 'parameters.constants.mate_score': {constants['mate_score']} (expected 100000-10000000)")

        # 验证 delta
        if "delta" not in constants:
            errors.append("Missing field: 'parameters.constants.delta'")
        elif not isinstance(constants["delta"], int):
            errors.append(
                f"Invalid type for 'parameters.constants.delta': expected int, got {type(constants['delta']).__name__}")
        elif not (100 <= constants["delta"] <= 2000):
            errors.append(
                f"Value out of range for 'parameters.constants.delta': {constants['delta']} (expected 100-2000)")

        return errors

    def _validate_threading(self, threading: Dict[str, Any]) -> List[str]:
        """
        验证多线程配置

        Args:
            threading: 多线程配置字典

        Returns:
            错误信息列表
        """
        errors = []

        # 验证 enabled
        if "enabled" not in threading:
            errors.append("Missing field: 'parameters.threading.enabled'")
        elif not isinstance(threading["enabled"], bool):
            errors.append(
                f"Invalid type for 'parameters.threading.enabled': expected bool, got {type(threading['enabled']).__name__}")

        # 验证 num_threads
        if "num_threads" not in threading:
            errors.append("Missing field: 'parameters.threading.num_threads'")
        elif not isinstance(threading["num_threads"], int):
            errors.append(
                f"Invalid type for 'parameters.threading.num_threads': expected int, got {type(threading['num_threads']).__name__}")
        elif not (1 <= threading["num_threads"] <= 64):
            errors.append(
                f"Value out of range for 'parameters.threading.num_threads': {threading['num_threads']} (expected 1-64)")

        return errors

    def _get_config_path(self, version: str) -> Path:
        """
        获取配置文件路径

        Args:
            version: 版本号

        Returns:
            配置文件路径
        """
        return self.config_dir / f"v{version}.json"

    def _compare_dicts(
        self,
        dict1: Dict[str, Any],
        dict2: Dict[str, Any],
        diff: Dict[str, Any],
        prefix: str
    ) -> None:
        """
        递归比较两个字典的差异

        Args:
            dict1: 第一个字典
            dict2: 第二个字典
            diff: 差异结果字典
            prefix: 键前缀
        """
        # 检查 dict2 中新增的键
        for key in dict2:
            full_key = f"{prefix}.{key}" if prefix else key
            if key not in dict1:
                diff["added"][full_key] = dict2[key]
            elif isinstance(dict1[key], dict) and isinstance(dict2[key], dict):
                self._compare_dicts(dict1[key], dict2[key], diff, full_key)
            elif dict1[key] != dict2[key]:
                diff["modified"][full_key] = {
                    "old": dict1[key],
                    "new": dict2[key]
                }

        # 检查 dict1 中删除的键
        for key in dict1:
            full_key = f"{prefix}.{key}" if prefix else key
            if key not in dict2:
                diff["removed"][full_key] = dict1[key]
