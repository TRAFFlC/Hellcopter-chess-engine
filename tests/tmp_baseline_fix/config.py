import json
import copy
from pathlib import Path

LOG_LEVEL: str = "INFO"

ENGINE_MAX_DEPTH: int = 100
ENGINE_TIME_LIMIT: float = 2.0

PIECE_VALUES: dict = {
    "pawn": 100,
    "knight": 320,
    "bishop": 340,
    "rook": 480,
    "queen": 900,
    "king": 20000,
}

CONFIGS_DIR = Path(__file__).parent.resolve() / "configs"


def resolve_config(config: dict) -> dict:
    if "base_version" not in config:
        return copy.deepcopy(config)

    base_version = config["base_version"]
    base_path = CONFIGS_DIR / f"{base_version}.json"
    if not base_path.exists():
        base_path = CONFIGS_DIR / f"v{base_version}.json"
    if not base_path.exists():
        raise FileNotFoundError(f"Base config not found: {base_version}")

    with open(base_path, "r", encoding="utf-8") as f:
        base_config = json.load(f)

    resolved_base = resolve_config(base_config)

    result = copy.deepcopy(resolved_base)
    result["version"] = config.get("version", result.get("version"))
    result["created_at"] = config.get("created_at", result.get("created_at"))
    result["description"] = config.get("description", result.get("description"))

    if "metadata" in config:
        result["metadata"] = config["metadata"]
    if "base_version" in config:
        result["base_version"] = config["base_version"]

    for extra_key in ("win_rate", "iteration"):
        if extra_key in config:
            result[extra_key] = config[extra_key]

    current_params = config.get("parameters", {})
    if current_params:
        if "parameters" not in result:
            result["parameters"] = {}
        for group_name, group_value in current_params.items():
            result["parameters"][group_name] = copy.deepcopy(group_value)

    return result


def load_and_resolve_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    return resolve_config(config)
