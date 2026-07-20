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
HELLCOPTER_EXE_PATH = os.path.join(BASE_DIR, "dist", "Hellcopter.exe")
COPTER_PATH = os.path.join(BASE_DIR, "dist", "new", "Copter.exe")
COPTER_BOOK_PATH = os.path.join(BASE_DIR, "dist", "Goi5.1.bin")

SYZYGY_PATH = os.path.join(BASE_DIR, "dist", "syzygy")


def _detect_syzygy_path():
    if os.path.isdir(SYZYGY_PATH) and any(
        f.endswith(".rtbw") for f in os.listdir(SYZYGY_PATH)
    ):
        return SYZYGY_PATH
    return None


def _make_hellcopter(name):
    env = os.environ.copy()
    params_path = os.path.join(BASE_DIR, "engine_params.json")
    if os.path.isfile(params_path):
        env["ENGINE_PARAMS"] = params_path
    # 优先使用 Python 直接运行 uci_engine.py（确保使用最新代码和开局库）
    # 仅在 engine_core.dll 不存在时回退到打包的 exe
    uci_script = os.path.join(BASE_DIR, "uci_engine.py")
    if os.path.isfile(uci_script):
        import sys
        eng = Engine(sys.executable, engine_args=[uci_script], protocol="uci", init_env=env)
    else:
        eng = Engine(HELLCOPTER_EXE_PATH, protocol="uci", init_env=env)
    eng._syzygy_path = _detect_syzygy_path()
    return eng


ENGINE_REGISTRY = [
    {"id": "chess3super", "name": "Chess3Super",
     "path": CHESS3SUPER_PATH, "args": [], "protocol": "uci", "options": []},
    {"id": "copter", "name": "Copter (最新编译)",
     "path": COPTER_PATH, "args": [], "protocol": "uci",
     "options": [{"name": "BookPath", "label": "开局库路径", "type": "string", "default": COPTER_BOOK_PATH},
                 {"name": "OwnBook", "label": "使用开局库", "type": "check", "default": True}]},
    {"id": "hellcopter", "name": "Hellcopter v1.9.5",
     "path": None, "factory": lambda: _make_hellcopter("Hellcopter v1.9.5"),
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
                    opts[opt["name"]] = extra_options[opt["name"]]
                elif "default" in opt:
                    opts[opt["name"]] = opt["default"]

            if "factory" in entry:
                eng = entry["factory"]()
                for k, v in opts.items():
                    if k == "limitStrength" and v:
                        eng.set_option("UCI_LimitStrength", "true")
                    elif k == "UCI_Elo":
                        eng.set_option("UCI_Elo", str(v))
                if eng._syzygy_path:
                    eng.syzygy_path = eng._syzygy_path
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

            if entry.get("protocol") == "uci":
                sz = _detect_syzygy_path()
                if sz:
                    eng.syzygy_path = sz

            return eng, entry
    return None, None
