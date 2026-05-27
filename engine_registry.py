import os
import sys
from engine_comm import Engine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.join(BASE_DIR, "test_engines", "Chess3Super", "chess3super.exe")

VELVET_PATH = os.path.join(BASE_DIR, "test_engines", "Velvet", "velvet-v8.1.1-x86_64-avx2.exe")
STOCKFISH_PATH = os.path.join(BASE_DIR, "test_engines", "Stockfish", "src", "stockfish.exe")
SHALLOWBLUE_PATH = os.path.join(BASE_DIR, "test_engines", "ShallowBlue 1575", "shallowblue.exe")
APOLLO_PATH = os.path.join(BASE_DIR, "test_engines", "Apollo 1663", "apollo.exe")
MONARCH_PATH = os.path.join(BASE_DIR, "test_engines", "Monarch 2005", "Monarch(v1.7)", "Monarch(v1.7).exe")
RAINMAN_PATH = os.path.join(BASE_DIR, "test_engines", "Rainman 1427", "rainman.exe")
SARGON_PATH = os.path.join(BASE_DIR, "test_engines", "sargon 1163", "sargon-engine-static-link.exe")
TSCP_PATH = os.path.join(BASE_DIR, "test_engines", "TSCP 1607", "tscp181.exe")
CHESS3SUPER_PATH = ENGINE_PATH
HELLCOPTER_ADAPTER_DIR = os.path.join(BASE_DIR, "temp_hellcopter_uci")


def create_hellcopter_adapter():
    env_params = os.path.join(BASE_DIR, "configs", "v1.7.0.json")
    os.makedirs(HELLCOPTER_ADAPTER_DIR, exist_ok=True)
    adapter_path = os.path.join(HELLCOPTER_ADAPTER_DIR, "hellcopter_uci.py")

    env_params_fwd = env_params.replace("\\", "/")
    base_dir_fwd = BASE_DIR.replace("\\", "/")

    with open(adapter_path, "w", encoding="utf-8") as f:
        f.write("import os\n")
        f.write("import sys\n\n")
        f.write(f'os.environ["ENGINE_PARAMS"] = "{env_params_fwd}"\n')
        f.write(f'sys.path.insert(0, "{base_dir_fwd}")\n\n')
        f.write("from uci_engine import UCIEngine\n\n")
        f.write('if __name__ == "__main__":\n')
        f.write("    uci = UCIEngine()\n")
        f.write("    uci.run()\n")

    return adapter_path


def _make_hellcopter(name):
    ap = create_hellcopter_adapter()
    return Engine(sys.executable, engine_args=[ap], protocol="uci")


ENGINE_REGISTRY = [
    {"id": "chess3super", "name": "Chess3Super",
     "path": CHESS3SUPER_PATH, "args": [], "protocol": "uci", "options": []},
    {"id": "hellcopter", "name": "Hellcopter v1.7.0",
     "path": None, "factory": lambda: _make_hellcopter("Hellcopter v1.7.0"),
     "protocol": "uci", "options": []},
    {"id": "velvet", "name": "Velvet v8.1.1",
     "path": VELVET_PATH, "args": [], "protocol": "uci",
     "options": [{"name": "limitStrength", "label": "限制强度", "type": "check", "default": False},
                 {"name": "UCI_Elo", "label": "Elo 等级", "type": "spin", "default": 2000, "min": 1225, "max": 3000}]},
    {"id": "stockfish", "name": "Stockfish",
     "path": STOCKFISH_PATH, "args": [], "protocol": "uci", "options": []},
    {"id": "shallowblue", "name": "ShallowBlue 1575",
     "path": SHALLOWBLUE_PATH, "args": [], "protocol": "uci", "options": []},
    {"id": "apollo", "name": "Apollo 1663",
     "path": APOLLO_PATH, "args": [], "protocol": "uci", "options": []},
    {"id": "monarch", "name": "Monarch 2005 v1.7",
     "path": MONARCH_PATH, "args": [], "protocol": "uci", "options": []},
    {"id": "sargon", "name": "Sargon 1978 v1.01b",
     "path": SARGON_PATH, "args": [], "protocol": "uci", "options": []},
    {"id": "rainman", "name": "Rainman 1427",
     "path": RAINMAN_PATH, "args": [], "protocol": "xboard", "options": []},
    {"id": "tscp", "name": "TSCP 181",
     "path": TSCP_PATH, "args": [], "protocol": "tscp", "options": []},
]


def resolve_engine(engine_id, extra_options=None):
    for entry in ENGINE_REGISTRY:
        if entry["id"] == engine_id:
            opts = {}
            for opt in entry.get("options", []):
                if extra_options and opt["name"] in extra_options:
                    val = extra_options[opt["name"]]
                    opts[opt["name"]] = val

            if "factory" in entry:
                eng = entry["factory"]()
                for k, v in opts.items():
                    if k == "limitStrength" and v:
                        eng.set_option("UCI_LimitStrength", "true")
                    elif k == "UCI_Elo":
                        eng.set_option("UCI_Elo", str(v))
                return eng, entry

            init_opts = {}
            for opt_name, opt_val in opts.items():
                if opt_name == "limitStrength":
                    if opt_val:
                        init_opts["UCI_LimitStrength"] = True
                elif opt_name == "UCI_Elo":
                    init_opts["UCI_Elo"] = int(opt_val) if isinstance(opt_val, (str, int)) else opt_val
                else:
                    init_opts[opt_name] = opt_val
            if init_opts:
                eng = Engine(entry["path"], entry.get("args", []), entry.get("protocol", "auto"), init_opts)
            else:
                eng = Engine(entry["path"], entry.get("args", []), entry.get("protocol", "auto"))
            return eng, entry
    return None, None
