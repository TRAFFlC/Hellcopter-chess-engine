"""
引擎编译脚本

该脚本负责编译 engine_core.c 为共享库，支持：
1. 参数化编译：从配置文件生成 engine_params.h
2. 增量编译：仅在源文件或参数变化时重新编译
3. 编译优化：支持 -O3, -march=native 等优化选项
4. 跨平台支持：Windows, Linux, macOS

使用方法:
    python build_engine.py                    # 使用默认参数编译
    python build_engine.py --config v1.0.0    # 使用指定配置编译
    python build_engine.py --force            # 强制重新编译
    python build_engine.py --no-optimize      # 禁用优化
    python build_engine.py clean              # 清理生成文件
"""

import os
import platform
import shutil
import subprocess
import sys
import json
import hashlib
import argparse
from pathlib import Path
from typing import Optional, Dict, Any


def _find_compiler_windows() -> tuple[str, list[str]] | None:
    """在 Windows 上查找可用的 C 编译器，返回 (编译器命令, 额外参数列表)。"""
    if shutil.which("gcc"):
        return "gcc", []
    if shutil.which("cl"):
        return "cl", []
    return None


def _find_compiler_unix() -> tuple[str, list[str]] | None:
    """在 Linux/Mac 上查找可用的 C 编译器。"""
    if shutil.which("gcc"):
        return "gcc", []
    if shutil.which("clang"):
        return "clang", []
    return None


def _load_config(config_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    加载配置文件
    
    Args:
        config_path: 配置文件路径，如果为 None 则不加载配置
        
    Returns:
        配置字典，如果加载失败则返回 None
    """
    if config_path is None:
        return None
    
    # 如果只提供版本号，构建完整路径
    if not config_path.endswith('.json'):
        config_path = f"configs/{config_path}.json"
    
    config_file = Path(config_path)
    if not config_file.exists():
        print(f"警告: 配置文件不存在: {config_path}", file=sys.stderr)
        return None
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        print(f"已加载配置: {config.get('version', 'unknown')} - {config.get('description', '')}")
        return config
    except json.JSONDecodeError as e:
        print(f"错误: 配置文件格式不正确: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"错误: 无法读取配置文件: {e}", file=sys.stderr)
        return None


def _generate_params_header(config: Dict[str, Any], output_path: str) -> bool:
    """
    从配置生成 engine_params.h 头文件
    
    Args:
        config: 配置字典
        output_path: 输出文件路径
        
    Returns:
        是否成功生成
    """
    try:
        parameters = config.get("parameters", {})
        
        with open(output_path, 'w', encoding='utf-8') as f:
            # 写入文件头
            f.write("/* ============================================================================\n")
            f.write(" * ENGINE_PARAMS.H - Chess Engine Parameter Definitions\n")
            f.write(" * ============================================================================\n")
            f.write(f" * Auto-generated from config version: {config.get('version', 'unknown')}\n")
            f.write(f" * Generated at: {config.get('created_at', 'unknown')}\n")
            f.write(f" * Description: {config.get('description', '')}\n")
            f.write(" * \n")
            f.write(" * DO NOT EDIT MANUALLY - Use the configuration management system to modify\n")
            f.write(" * parameters and regenerate this file.\n")
            f.write(" * ============================================================================\n")
            f.write(" */\n\n")
            f.write("#ifndef ENGINE_PARAMS_H\n")
            f.write("#define ENGINE_PARAMS_H\n\n")
            
            # 棋子价值
            piece_values = parameters.get("piece_values", {})
            f.write("/* ============================================================================\n")
            f.write(" * SECTION 1: PIECE VALUES\n")
            f.write(" * ============================================================================\n")
            f.write(" */\n\n")
            f.write(f"#define PAWN_VALUE {piece_values.get('pawn', 100)}\n")
            f.write(f"#define KNIGHT_VALUE {piece_values.get('knight', 300)}\n")
            f.write(f"#define BISHOP_VALUE {piece_values.get('bishop', 320)}\n")
            f.write(f"#define ROOK_VALUE {piece_values.get('rook', 480)}\n")
            f.write(f"#define QUEEN_VALUE {piece_values.get('queen', 900)}\n")
            f.write(f"#define KING_VALUE {piece_values.get('king', 20000)}\n\n")
            
            # PST 表
            pst = parameters.get("pst", {})
            f.write("/* ============================================================================\n")
            f.write(" * SECTION 2: PIECE-SQUARE TABLES (PST)\n")
            f.write(" * ============================================================================\n")
            f.write(" */\n\n")
            
            for table_name in ["mg_pawn", "eg_pawn", "mg_knight", "eg_knight", 
                             "mg_bishop", "eg_bishop", "mg_rook", "eg_rook",
                             "mg_queen", "eg_queen", "mg_king", "eg_king"]:
                values = pst.get(table_name, [0] * 64)
                f.write(f"static const int {table_name}[64] = {{\n")
                for i in range(0, 64, 8):
                    row = ", ".join(f"{v:4d}" for v in values[i:i+8])
                    f.write(f"    {row},\n")
                f.write("};\n\n")
            
            # 评估权重
            eval_weights = parameters.get("eval_weights", {})
            f.write("/* ============================================================================\n")
            f.write(" * SECTION 3: EVALUATION WEIGHTS\n")
            f.write(" * ============================================================================\n")
            f.write(" */\n\n")
            f.write(f"#define BISHOP_PAIR_BONUS {eval_weights.get('bishop_pair_bonus', 50)}\n")
            f.write(f"#define DOUBLED_PAWN_PENALTY {eval_weights.get('doubled_pawn_penalty', -10)}\n")
            f.write(f"#define ISOLATED_PAWN_PENALTY {eval_weights.get('isolated_pawn_penalty', -20)}\n")
            f.write(f"#define PAWN_CHAIN_BONUS 10\n\n")
            f.write(f"#define SIMPLIFY_THRESHOLD {eval_weights.get('simplify_threshold', 200)}\n")
            f.write(f"#define SIMPLIFY_BONUS {eval_weights.get('simplify_bonus', 15)}\n\n")
            
            # 通路兵奖励
            passed_pawn_bonus = eval_weights.get('passed_pawn_bonus', [0, 10, 20, 30, 50, 80, 120, 0])
            f.write("static const int passed_pawn_bonus[8] = {\n")
            f.write("    " + ", ".join(str(v) for v in passed_pawn_bonus) + "\n")
            f.write("};\n\n")
            
            f.write(f"#define OPEN_FILE_BONUS {eval_weights.get('open_file_bonus', 15)}\n")
            f.write(f"#define SEMI_OPEN_FILE_BONUS {eval_weights.get('semi_open_file_bonus', 10)}\n")
            f.write("#define ROOK_POTENTIAL_OPEN_FILE 8\n")
            f.write("#define ROOK_POTENTIAL_SEMI_OPEN 4\n")
            f.write("#define ROOK_ON_7TH_BONUS 30\n")
            f.write("#define ROOK_ON_7TH_WITH_KING 20\n")
            f.write("#define BISHOP_MOBILITY_BONUS 15\n")
            f.write("#define BISHOP_BAD_PENALTY -15\n\n")
            
            # 搜索参数
            search_params = parameters.get("search_params", {})
            f.write("/* ============================================================================\n")
            f.write(" * SECTION 4: SEARCH PARAMETERS\n")
            f.write(" * ============================================================================\n")
            f.write(" */\n\n")
            f.write(f"#define NULL_MOVE_REDUCTION {search_params.get('null_move_reduction', 2)}\n")
            f.write(f"#define NULL_MOVE_MIN_DEPTH {search_params.get('null_move_min_depth', 3)}\n")
            f.write("#define NULL_MOVE_VERIFICATION_DEPTH 6\n")
            f.write("#define NULL_MOVE_VERIFICATION_REDUCTION 5\n\n")
            
            f.write(f"#define LMR_ENABLED {1 if search_params.get('lmr_enabled', False) else 0}\n")
            f.write(f"#define LMR_MIN_DEPTH {search_params.get('lmr_min_depth', 3)}\n")
            f.write(f"#define LMR_MOVE_THRESHOLD {search_params.get('lmr_move_threshold', 2)}\n\n")
            
            f.write(f"#define FUTILITY_ENABLED {1 if search_params.get('futility_enabled', False) else 0}\n")
            f.write(f"#define FUTILITY_MARGIN_BASE {search_params.get('futility_margin_base', 150)}\n\n")
            
            f.write(f"#define RAZORING_ENABLED {1 if search_params.get('razoring_enabled', False) else 0}\n")
            f.write(f"#define RAZORING_MARGIN {search_params.get('razoring_margin', 300)}\n\n")
            
            f.write(f"#define QS_MAX_DEPTH_MG {search_params.get('qs_max_depth_mg', 8)}\n")
            f.write(f"#define QS_MAX_DEPTH_EG {search_params.get('qs_max_depth_eg', 16)}\n\n")
            
            # 常量
            constants = parameters.get("constants", {})
            f.write("/* ============================================================================\n")
            f.write(" * SECTION 5: CONSTANTS\n")
            f.write(" * ============================================================================\n")
            f.write(" */\n\n")
            f.write(f"#define MATE_SCORE {constants.get('mate_score', 900000)}\n")
            f.write(f"#define DELTA {constants.get('delta', 900)}\n\n")
            
            f.write("/* ============================================================================\n")
            f.write(" * SECTION 5.5: ENDGAME PARAMETERS\n")
            f.write(" * ============================================================================\n")
            f.write(" */\n\n")
            f.write(f"#define ENDGAME_PHASE_THRESHOLD {constants.get('endgame_phase_threshold', 6)}\n")
            f.write(f"#define ENDGAME_DEPTH_BONUS {constants.get('endgame_depth_bonus', 0)}\n")
            f.write(f"#define ENDGAME_NMR_BONUS {constants.get('endgame_nmr_bonus', 1)}\n")
            f.write(f"#define KING_ACTIVITY_WEIGHT {constants.get('king_activity_weight', 10)}\n\n")
            
            # 多线程
            threading = parameters.get("threading", {})
            f.write("/* ============================================================================\n")
            f.write(" * SECTION 6: THREADING\n")
            f.write(" * ============================================================================\n")
            f.write(" */\n\n")
            f.write(f"#define THREADING_ENABLED {1 if threading.get('enabled', False) else 0}\n")
            f.write(f"#define NUM_THREADS {threading.get('num_threads', 1)}\n\n")
            
            # 参数验证
            f.write("/* ============================================================================\n")
            f.write(" * PARAMETER VALIDATION MACROS\n")
            f.write(" * ============================================================================\n")
            f.write(" */\n\n")
            f.write("#if PAWN_VALUE <= 0 || KNIGHT_VALUE <= 0 || BISHOP_VALUE <= 0 || \\\n")
            f.write("    ROOK_VALUE <= 0 || QUEEN_VALUE <= 0 || KING_VALUE <= 0\n")
            f.write('#error "Piece values must be positive"\n')
            f.write("#endif\n\n")
            f.write("#if NUM_THREADS < 1 || NUM_THREADS > 64\n")
            f.write('#error "NUM_THREADS must be between 1 and 64"\n')
            f.write("#endif\n\n")
            f.write("#if NULL_MOVE_MIN_DEPTH < 1 || LMR_MIN_DEPTH < 1\n")
            f.write('#error "Minimum depth parameters must be at least 1"\n')
            f.write("#endif\n\n")
            
            f.write("#endif /* ENGINE_PARAMS_H */\n")
        
        print(f"已生成参数头文件: {output_path}")
        return True
    except Exception as e:
        print(f"错误: 生成头文件失败: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def _compute_file_hash(file_path: str) -> str:
    """
    计算文件的 MD5 哈希值
    
    Args:
        file_path: 文件路径
        
    Returns:
        MD5 哈希值（十六进制字符串）
    """
    md5 = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5.update(chunk)
        return md5.hexdigest()
    except Exception:
        return ""


def _needs_rebuild(src_file: str, output_file: str, params_header: str) -> bool:
    """
    检查是否需要重新编译
    
    Args:
        src_file: 源文件路径
        output_file: 输出文件路径
        params_header: 参数头文件路径
        
    Returns:
        是否需要重新编译
    """
    # 如果输出文件不存在，需要编译
    if not os.path.exists(output_file):
        print("输出文件不存在，需要编译")
        return True
    
    # 获取文件修改时间
    output_mtime = os.path.getmtime(output_file)
    src_mtime = os.path.getmtime(src_file)
    
    # 如果源文件更新，需要编译
    if src_mtime > output_mtime:
        print("源文件已更新，需要重新编译")
        return True
    
    # 如果参数头文件更新，需要编译
    if os.path.exists(params_header):
        params_mtime = os.path.getmtime(params_header)
        if params_mtime > output_mtime:
            print("参数头文件已更新，需要重新编译")
            return True
    
    print("无需重新编译（使用增量编译）")
    return False


def build(config_path: Optional[str] = None, force: bool = False, optimize: bool = True) -> bool:
    """
    检测平台并编译 engine_core.c 为共享库。
    
    Args:
        config_path: 配置文件路径或版本号（如 "v1.0.0"），如果为 None 则使用现有的 engine_params.h
        force: 是否强制重新编译
        optimize: 是否启用编译优化
    
    Returns:
        True 表示编译成功，False 表示失败。
    """
    system = platform.system()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    src_file = os.path.join(script_dir, "engine_core.c")
    params_header = os.path.join(script_dir, "engine_params.h")

    if not os.path.exists(src_file):
        print(f"错误: 源文件未找到: {src_file}", file=sys.stderr)
        return False

    # 如果提供了配置文件，生成参数头文件
    if config_path:
        config = _load_config(config_path)
        if config is None:
            print("错误: 无法加载配置文件", file=sys.stderr)
            return False
        
        if not _generate_params_header(config, params_header):
            print("错误: 无法生成参数头文件", file=sys.stderr)
            return False
    else:
        # 检查参数头文件是否存在
        if not os.path.exists(params_header):
            print(f"警告: 参数头文件不存在: {params_header}", file=sys.stderr)
            print("将使用默认参数编译", file=sys.stderr)

    # 确定输出文件
    if system == "Windows":
        output_file = os.path.join(script_dir, "engine_core.dll")
    elif system == "Linux":
        output_file = os.path.join(script_dir, "engine_core.so")
    elif system == "Darwin":
        output_file = os.path.join(script_dir, "engine_core.dylib")
    else:
        print(f"错误: 不支持的操作系统: {system}", file=sys.stderr)
        return False

    # 检查是否需要重新编译
    if not force and not _needs_rebuild(src_file, output_file, params_header):
        print(f"编译已是最新: {output_file}")
        return True

    # 查找编译器
    if system == "Windows":
        compiler_info = _find_compiler_windows()
        if compiler_info is None:
            print(
                "错误: 未找到可用的 C 编译器。"
                "请安装 MinGW-w64 (gcc) 或 Microsoft Visual C++ (cl) 并将其加入 PATH。",
                file=sys.stderr,
            )
            return False

        compiler, _ = compiler_info

        if compiler == "gcc":
            cmd = [
                "gcc",
                "-shared",
                "-std=c99",
                "-o", output_file,
                src_file,
                "-lm",
            ]
            
            # 添加优化选项
            if optimize:
                cmd.insert(2, "-O3")
                cmd.insert(3, "-march=native")
                cmd.insert(4, "-fomit-frame-pointer")
                cmd.insert(5, "-DNDEBUG")
                # LTO 在某些 MinGW 版本上可能有问题，暂时禁用
                # cmd.insert(4, "-flto")
        else:  # cl
            obj_file = os.path.join(script_dir, "engine_core.obj")
            cmd = [
                "cl",
                "/LD",
                f"/Fe{output_file}",
                f"/Fo{obj_file}",
                src_file,
            ]
            
            # 添加优化选项
            if optimize:
                cmd.insert(1, "/O2")
                cmd.insert(2, "/GL")
                cmd.insert(3, "/DNDEBUG")

    elif system == "Linux":
        compiler_info = _find_compiler_unix()
        if compiler_info is None:
            print(
                "错误: 未找到可用的 C 编译器。请安装 gcc 或 clang。",
                file=sys.stderr,
            )
            return False

        compiler, _ = compiler_info
        cmd = [
            compiler,
            "-shared",
            "-std=c99",
            "-fPIC",
            "-o", output_file,
            src_file,
            "-lm",
        ]
        
        # 添加优化选项
        if optimize:
            cmd.insert(3, "-O3")
            cmd.insert(4, "-march=native")
            cmd.insert(5, "-fomit-frame-pointer")
            cmd.insert(6, "-DNDEBUG")
            # LTO 可选
            # cmd.insert(5, "-flto")

    elif system == "Darwin":
        compiler_info = _find_compiler_unix()
        if compiler_info is None:
            print(
                "错误: 未找到可用的 C 编译器。请安装 gcc 或 clang (Xcode Command Line Tools)。",
                file=sys.stderr,
            )
            return False

        compiler, _ = compiler_info
        cmd = [
            compiler,
            "-dynamiclib",
            "-std=c99",
            "-o", output_file,
            src_file,
        ]
        
        # 添加优化选项
        if optimize:
            cmd.insert(2, "-O3")
            cmd.insert(3, "-march=native")
            cmd.insert(4, "-flto")
            cmd.insert(5, "-fomit-frame-pointer")
            cmd.insert(6, "-DNDEBUG")

    print(f"\n{'='*60}")
    print(f"检测到平台: {system}")
    print(f"使用编译器: {compiler}")
    print(f"优化选项: {'启用' if optimize else '禁用'}")
    print(f"输出文件: {output_file}")
    print(f"执行命令: {' '.join(cmd)}")
    print(f"{'='*60}\n")

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=script_dir)

    if result.returncode != 0:
        print("编译失败！", file=sys.stderr)
        if result.stdout:
            print("stdout:\n" + result.stdout, file=sys.stderr)
        if result.stderr:
            print("stderr:\n" + result.stderr, file=sys.stderr)
        return False

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if os.path.exists(output_file):
        file_size = os.path.getsize(output_file)
        print(f"\n{'='*60}")
        print(f"[SUCCESS] 编译成功: {output_file}")
        print(f"  文件大小: {file_size:,} 字节")
        print(f"{'='*60}\n")
        return True
    else:
        print("错误: 编译命令返回 0，但输出文件未生成。", file=sys.stderr)
        return False


def build_exe(config_path: Optional[str] = None, force: bool = False, optimize: bool = True) -> bool:
    """
    编译 uci_main.c 和 engine_core.c 为独立的 UCI 可执行文件。
    """
    system = platform.system()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    engine_src = os.path.join(script_dir, "engine_core.c")
    uci_src = os.path.join(script_dir, "uci_main.c")
    params_header = os.path.join(script_dir, "engine_params.h")

    if not os.path.exists(engine_src):
        print(f"错误: 源文件未找到: {engine_src}", file=sys.stderr)
        return False
    if not os.path.exists(uci_src):
        print(f"错误: 源文件未找到: {uci_src}", file=sys.stderr)
        return False

    if config_path:
        config = _load_config(config_path)
        if config is None:
            print("错误: 无法加载配置文件", file=sys.stderr)
            return False
        if not _generate_params_header(config, params_header):
            print("错误: 无法生成参数头文件", file=sys.stderr)
            return False

    dist_dir = os.path.join(script_dir, "dist")
    os.makedirs(dist_dir, exist_ok=True)

    if system == "Windows":
        output_file = os.path.join(dist_dir, "Hellcopter.exe")
    else:
        output_file = os.path.join(dist_dir, "Hellcopter")

    if not force and not _needs_rebuild(engine_src, output_file, params_header):
        if not _needs_rebuild(uci_src, output_file, params_header):
            print(f"编译已是最新: {output_file}")
            return True

    if system == "Windows":
        compiler_info = _find_compiler_windows()
        if compiler_info is None:
            print("错误: 未找到可用的 C 编译器。", file=sys.stderr)
            return False

        compiler, _ = compiler_info
        if compiler == "gcc":
            cmd = [
                "gcc", "-std=c99",
                "-o", output_file,
                engine_src, uci_src,
                "-lm",
            ]
            if optimize:
                cmd.insert(2, "-O3")
                cmd.insert(3, "-march=native")
                cmd.insert(4, "-fomit-frame-pointer")
                cmd.insert(5, "-DNDEBUG")
        else:
            obj_engine = os.path.join(script_dir, "engine_core.obj")
            obj_uci = os.path.join(script_dir, "uci_main.obj")
            cmd = [
                "cl",
                f"/Fe{output_file}",
                f"/Fo{obj_engine}",
                engine_src, uci_src,
            ]
            if optimize:
                cmd.insert(1, "/O2")
                cmd.insert(2, "/GL")
                cmd.insert(3, "/DNDEBUG")
    elif system in ("Linux", "Darwin"):
        compiler_info = _find_compiler_unix()
        if compiler_info is None:
            print("错误: 未找到可用的 C 编译器。", file=sys.stderr)
            return False

        compiler, _ = compiler_info
        cmd = [
            compiler, "-std=c99",
            "-o", output_file,
            engine_src, uci_src,
            "-lm", "-lpthread",
        ]
        if optimize:
            cmd.insert(2, "-O3")
            cmd.insert(3, "-march=native")
            cmd.insert(4, "-fomit-frame-pointer")
            cmd.insert(5, "-DNDEBUG")
    else:
        print(f"错误: 不支持的操作系统: {system}", file=sys.stderr)
        return False

    print(f"\n{'='*60}")
    print(f"编译 UCI 可执行文件")
    print(f"检测到平台: {system}")
    print(f"使用编译器: {compiler}")
    print(f"优化选项: {'启用' if optimize else '禁用'}")
    print(f"输出文件: {output_file}")
    print(f"执行命令: {' '.join(cmd)}")
    print(f"{'='*60}\n")

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=script_dir)

    if result.returncode != 0:
        print("编译失败！", file=sys.stderr)
        if result.stdout:
            print("stdout:\n" + result.stdout, file=sys.stderr)
        if result.stderr:
            print("stderr:\n" + result.stderr, file=sys.stderr)
        return False

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if os.path.exists(output_file):
        file_size = os.path.getsize(output_file)
        book_src = os.path.join(script_dir, "dist", "book.bin")
        if os.path.exists(book_src):
            print(f"  开局库已存在: {book_src}")
        else:
            gen_script = os.path.join(script_dir, "generate_book.py")
            if os.path.exists(gen_script):
                print("  生成开局库...")
                subprocess.run([sys.executable, gen_script], cwd=script_dir, check=True)
        print(f"\n{'='*60}")
        print(f"[SUCCESS] 编译成功: {output_file}")
        print(f"  文件大小: {file_size:,} 字节 ({file_size / 1024:.1f} KB)")
        print(f"{'='*60}\n")
        return True
    else:
        print("错误: 编译命令返回 0，但输出文件未生成。", file=sys.stderr)
        return False


def clean():
    """删除生成的共享库和中间文件。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    files_to_remove = [
        "engine_core.dll",
        "engine_core.so",
        "engine_core.dylib",
        "engine_core.obj",
        "engine_core.o",
        "libengine_core.a",
    ]
    
    print("清理生成文件...")
    removed_count = 0
    for name in files_to_remove:
        path = os.path.join(script_dir, name)
        if os.path.exists(path):
            os.remove(path)
            print(f"  已删除: {name}")
            removed_count += 1
    
    if removed_count == 0:
        print("  没有需要清理的文件")
    else:
        print(f"已清理 {removed_count} 个文件")


def main():
    """主函数，处理命令行参数"""
    parser = argparse.ArgumentParser(
        description="编译 hellcopter 国际象棋引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python build_engine.py                    # 使用默认参数编译共享库
  python build_engine.py exe                # 编译为独立 UCI 可执行文件
  python build_engine.py --config v1.0.0    # 使用指定配置编译
  python build_engine.py --force            # 强制重新编译
  python build_engine.py --no-optimize      # 禁用优化
  python build_engine.py clean              # 清理生成文件
        """
    )
    
    parser.add_argument(
        'action',
        nargs='?',
        default='build',
        choices=['build', 'exe', 'clean'],
        help='执行的操作：build（编译共享库）、exe（编译可执行文件）或 clean（清理）'
    )
    
    parser.add_argument(
        '--config', '-c',
        type=str,
        help='配置文件路径或版本号（如 v1.0.0）'
    )
    
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='强制重新编译，忽略增量编译检查'
    )
    
    parser.add_argument(
        '--no-optimize',
        action='store_true',
        help='禁用编译优化（用于调试）'
    )
    
    args = parser.parse_args()
    
    if args.action == 'clean':
        clean()
        sys.exit(0)
    elif args.action == 'exe':
        success = build_exe(
            config_path=args.config,
            force=args.force,
            optimize=not args.no_optimize
        )
        sys.exit(0 if success else 1)
    else:
        success = build(
            config_path=args.config,
            force=args.force,
            optimize=not args.no_optimize
        )
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
