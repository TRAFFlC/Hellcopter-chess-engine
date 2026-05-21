"""
评估参数管理器 - 用于 Texel Tuning

提供评估参数的提取、注入和转换功能：
1. 从引擎配置文件提取可调优参数
2. 将优化后的参数注入回配置文件
3. 参数格式转换和验证

使用方法:
    from eval_param_manager import EvalParamManager
    
    manager = EvalParamManager()
    params = manager.extract_params("configs/v1.5.0.json")
    manager.inject_params(params, "configs/v1.6.0.json")
"""

import json
import copy
import chess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field


@dataclass
class ParamDefinition:
    name: str
    path: str
    value_type: str
    min_val: float
    max_val: float
    default: Any
    description: str = ""


PARAM_DEFINITIONS = {
    "piece_pawn": ParamDefinition(
        name="piece_pawn", path="parameters.piece_values.pawn",
        value_type="int", min_val=80, max_val=120, default=100,
        description="兵的子力价值"
    ),
    "piece_knight": ParamDefinition(
        name="piece_knight", path="parameters.piece_values.knight",
        value_type="int", min_val=280, max_val=400, default=320,
        description="马的子力价值"
    ),
    "piece_bishop": ParamDefinition(
        name="piece_bishop", path="parameters.piece_values.bishop",
        value_type="int", min_val=280, max_val=400, default=340,
        description="象的子力价值"
    ),
    "piece_rook": ParamDefinition(
        name="piece_rook", path="parameters.piece_values.rook",
        value_type="int", min_val=400, max_val=600, default=500,
        description="车的子力价值"
    ),
    "piece_queen": ParamDefinition(
        name="piece_queen", path="parameters.piece_values.queen",
        value_type="int", min_val=800, max_val=1000, default=900,
        description="后的子力价值"
    ),
    "bishop_pair_bonus": ParamDefinition(
        name="bishop_pair_bonus", path="parameters.eval_weights.bishop_pair_bonus",
        value_type="int", min_val=0, max_val=100, default=30,
        description="双象奖励"
    ),
    "doubled_pawn_penalty": ParamDefinition(
        name="doubled_pawn_penalty", path="parameters.eval_weights.doubled_pawn_penalty",
        value_type="int", min_val=-50, max_val=0, default=-20,
        description="叠兵惩罚"
    ),
    "isolated_pawn_penalty": ParamDefinition(
        name="isolated_pawn_penalty", path="parameters.eval_weights.isolated_pawn_penalty",
        value_type="int", min_val=-50, max_val=0, default=-15,
        description="孤兵惩罚"
    ),
    "open_file_bonus": ParamDefinition(
        name="open_file_bonus", path="parameters.eval_weights.open_file_bonus",
        value_type="int", min_val=0, max_val=50, default=20,
        description="开放线奖励"
    ),
    "semi_open_file_bonus": ParamDefinition(
        name="semi_open_file_bonus", path="parameters.eval_weights.semi_open_file_bonus",
        value_type="int", min_val=0, max_val=30, default=12,
        description="半开放线奖励"
    ),
}


class EvalParamManager:
    def __init__(self, config_dir: Optional[str] = None):
        self.config_dir = Path(config_dir) if config_dir else Path("configs")
        self.param_definitions = PARAM_DEFINITIONS.copy()
        
    def load_config(self, config_path: str) -> Dict:
        path = Path(config_path)
        if not path.is_absolute():
            path = self.config_dir / path
        
        with open(path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        return self._resolve_config(config)
    
    def _resolve_config(self, config: Dict) -> Dict:
        if "base_version" not in config:
            return copy.deepcopy(config)
        
        base_version = config["base_version"]
        base_path = self.config_dir / f"{base_version}.json"
        if not base_path.exists():
            base_path = self.config_dir / f"v{base_version}.json"
        
        if not base_path.exists():
            raise FileNotFoundError(f"基础配置未找到: {base_version}")
        
        with open(base_path, 'r', encoding='utf-8') as f:
            base_config = json.load(f)
        
        resolved_base = self._resolve_config(base_config)
        
        result = copy.deepcopy(resolved_base)
        result["version"] = config.get("version", result.get("version"))
        result["created_at"] = config.get("created_at", result.get("created_at"))
        result["description"] = config.get("description", result.get("description"))
        
        if "parameters" in config:
            if "parameters" not in result:
                result["parameters"] = {}
            for group_name, group_value in config["parameters"].items():
                result["parameters"][group_name] = copy.deepcopy(group_value)
        
        return result
    
    def save_config(self, config: Dict, output_path: str):
        path = Path(output_path)
        if not path.is_absolute():
            path = self.config_dir / path
        
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        print(f"配置已保存到 {path}")
    
    def extract_params(self, config_path: str) -> Dict[str, Any]:
        config = self.load_config(config_path)
        params = {}
        
        for name, defn in self.param_definitions.items():
            value = self._get_nested(config, defn.path)
            if value is not None:
                params[name] = value
            else:
                params[name] = defn.default
        
        params["_pst"] = self._extract_pst(config)
        
        return params
    
    def _extract_pst(self, config: Dict) -> Dict:
        pst = {}
        params = config.get("parameters", {})
        pst_config = params.get("pst", {})
        
        for piece in ["pawn", "knight", "bishop", "rook", "queen", "king"]:
            for phase in ["mg", "eg"]:
                key = f"{phase}_{piece}"
                if key in pst_config:
                    pst[key] = pst_config[key]
        
        return pst
    
    def inject_params(self, params: Dict[str, Any], 
                     base_config_path: str,
                     output_path: str,
                     version: Optional[str] = None,
                     description: Optional[str] = None) -> str:
        base_config = self.load_config(base_config_path)
        
        if "parameters" not in base_config:
            base_config["parameters"] = {}
        
        for name, value in params.items():
            if name.startswith("_"):
                continue
            
            if name not in self.param_definitions:
                continue
            
            defn = self.param_definitions[name]
            
            clamped = max(defn.min_val, min(defn.max_val, value))
            if defn.value_type == "int":
                clamped = int(round(clamped))
            
            self._set_nested(base_config, defn.path, clamped)
        
        if "_pst" in params:
            self._inject_pst(base_config, params["_pst"])
        
        if version:
            base_config["version"] = version
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_config["version"] = f"texel_tuned_{ts}"
        
        base_config["created_at"] = datetime.now().isoformat()
        base_config["description"] = description or "Texel Tuning 优化结果"
        
        self.save_config(base_config, output_path)
        return output_path
    
    def _inject_pst(self, config: Dict, pst: Dict):
        if "parameters" not in config:
            config["parameters"] = {}
        if "pst" not in config["parameters"]:
            config["parameters"]["pst"] = {}
        
        for key, value in pst.items():
            config["parameters"]["pst"][key] = value
    
    def _get_nested(self, d: Dict, path: str) -> Any:
        keys = path.split(".")
        val = d
        for key in keys:
            if not isinstance(val, dict) or key not in val:
                return None
            val = val[key]
        return val
    
    def _set_nested(self, d: Dict, path: str, value: Any):
        keys = path.split(".")
        obj = d
        for key in keys[:-1]:
            if key not in obj:
                obj[key] = {}
            obj = obj[key]
        obj[keys[-1]] = value
    
    def get_param_bounds(self) -> Dict[str, Tuple[float, float]]:
        bounds = {}
        for name, defn in self.param_definitions.items():
            bounds[name] = (defn.min_val, defn.max_val)
        return bounds
    
    def validate_params(self, params: Dict[str, Any]) -> Dict[str, List[str]]:
        errors = {}
        
        for name, value in params.items():
            if name.startswith("_"):
                continue
            
            if name not in self.param_definitions:
                continue
            
            defn = self.param_definitions[name]
            issues = []
            
            if value < defn.min_val:
                issues.append(f"值 {value} 小于最小值 {defn.min_val}")
            if value > defn.max_val:
                issues.append(f"值 {value} 大于最大值 {defn.max_val}")
            
            if defn.value_type == "int" and not isinstance(value, int):
                if not isinstance(value, float) or not value.is_integer():
                    issues.append(f"值 {value} 不是整数")
            
            if issues:
                errors[name] = issues
        
        return errors
    
    def create_tuning_config(self, 
                            base_version: str,
                            params_to_tune: Optional[List[str]] = None) -> Dict:
        config = {
            "version": f"tuning_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "base_version": base_version,
            "created_at": datetime.now().isoformat(),
            "description": "Texel Tuning 临时配置",
            "parameters": {}
        }
        
        return config
    
    def params_to_texel_format(self, params: Dict[str, Any]) -> Dict:
        texel_params = {
            "piece_values": {},
            "eval_weights": {},
            "pawn_structure": {}
        }
        
        for name, value in params.items():
            if name.startswith("piece_"):
                piece = name[6:]
                texel_params["piece_values"][piece] = value
            elif name in ["bishop_pair_bonus"]:
                texel_params["eval_weights"][name] = value
            elif name in ["doubled_pawn_penalty", "isolated_pawn_penalty"]:
                texel_params["pawn_structure"][name] = abs(value)
            elif name in ["open_file_bonus", "semi_open_file_bonus"]:
                texel_params["eval_weights"][name] = value
        
        return texel_params
    
    def params_from_texel_format(self, texel_params: Dict) -> Dict[str, Any]:
        params = {}
        
        piece_values = texel_params.get("piece_values", {})
        for piece, value in piece_values.items():
            params[f"piece_{piece}"] = value
        
        eval_weights = texel_params.get("eval_weights", {})
        for name, value in eval_weights.items():
            params[name] = value
        
        pawn_structure = texel_params.get("pawn_structure", {})
        for name, value in pawn_structure.items():
            if name in ["doubled_pawn_penalty", "isolated_pawn_penalty"]:
                params[name] = -abs(value)
            else:
                params[name] = value
        
        return params


def compare_params(params1: Dict, params2: Dict) -> Dict[str, Tuple[Any, Any, float]]:
    comparison = {}
    
    all_keys = set(params1.keys()) | set(params2.keys())
    
    for key in all_keys:
        if key.startswith("_"):
            continue
        
        val1 = params1.get(key)
        val2 = params2.get(key)
        
        if val1 is not None and val2 is not None:
            if isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
                diff = val2 - val1
                comparison[key] = (val1, val2, diff)
            else:
                comparison[key] = (val1, val2, 0)
    
    return comparison


def print_param_comparison(comparison: Dict[str, Tuple[Any, Any, float]]):
    print("\n参数对比:")
    print("-" * 60)
    print(f"{'参数名':<25} {'原值':>10} {'新值':>10} {'变化':>10}")
    print("-" * 60)
    
    for name, (old, new, diff) in sorted(comparison.items()):
        if isinstance(diff, (int, float)) and diff != 0:
            print(f"{name:<25} {old:>10} {new:>10} {diff:>+10}")
    
    print("-" * 60)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="评估参数管理器")
    parser.add_argument("--extract", "-e", type=str, help="从配置文件提取参数")
    parser.add_argument("--compare", "-c", nargs=2, metavar=("CONFIG1", "CONFIG2"),
                       help="比较两个配置文件的参数")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有可调优参数")
    
    args = parser.parse_args()
    
    manager = EvalParamManager()
    
    if args.list:
        print("\n可调优参数列表:")
        print("-" * 70)
        print(f"{'名称':<25} {'类型':<8} {'范围':<20} {'默认值':<10}")
        print("-" * 70)
        for name, defn in PARAM_DEFINITIONS.items():
            range_str = f"[{defn.min_val}, {defn.max_val}]"
            print(f"{name:<25} {defn.value_type:<8} {range_str:<20} {defn.default:<10}")
        print("-" * 70)
    
    if args.extract:
        params = manager.extract_params(args.extract)
        print(f"\n从 {args.extract} 提取的参数:")
        print("-" * 40)
        for name, value in params.items():
            if not name.startswith("_"):
                print(f"  {name}: {value}")
    
    if args.compare:
        params1 = manager.extract_params(args.compare[0])
        params2 = manager.extract_params(args.compare[1])
        comparison = compare_params(params1, params2)
        print_param_comparison(comparison)
