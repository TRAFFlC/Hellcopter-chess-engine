import os
import platform
import shutil
import subprocess
import sys


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


def build() -> bool:
    """
    检测平台并编译 engine_core.c 为共享库。

    返回 True 表示编译成功，False 表示失败。
    """
    system = platform.system()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    src_file = os.path.join(script_dir, "engine_core.c")

    if not os.path.exists(src_file):
        print(f"错误: 源文件未找到: {src_file}", file=sys.stderr)
        return False

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
        output_file = os.path.join(script_dir, "engine_core.dll")

        if compiler == "gcc":
            cmd = [
                "gcc",
                "-shared",
                "-O3",
                "-o", output_file,
                src_file,
                "-lm",
            ]
        else:  # cl
            obj_file = os.path.join(script_dir, "engine_core.obj")
            cmd = [
                "cl",
                "/O2",
                "/LD",
                f"/Fe{output_file}",
                f"/Fo{obj_file}",
                src_file,
            ]

    elif system == "Linux":
        compiler_info = _find_compiler_unix()
        if compiler_info is None:
            print(
                "错误: 未找到可用的 C 编译器。请安装 gcc 或 clang。",
                file=sys.stderr,
            )
            return False

        compiler, _ = compiler_info
        output_file = os.path.join(script_dir, "engine_core.so")
        cmd = [
            compiler,
            "-shared",
            "-fPIC",
            "-O3",
            "-o", output_file,
            src_file,
            "-lm",
        ]

    elif system == "Darwin":
        compiler_info = _find_compiler_unix()
        if compiler_info is None:
            print(
                "错误: 未找到可用的 C 编译器。请安装 gcc 或 clang (Xcode Command Line Tools)。",
                file=sys.stderr,
            )
            return False

        compiler, _ = compiler_info
        output_file = os.path.join(script_dir, "engine_core.dylib")
        cmd = [
            compiler,
            "-dynamiclib",
            "-O3",
            "-o", output_file,
            src_file,
        ]

    else:
        print(f"错误: 不支持的操作系统: {system}", file=sys.stderr)
        return False

    print(f"检测到平台: {system}")
    print(f"使用编译器: {compiler}")
    print(f"输出文件: {output_file}")
    print(f"执行命令: {' '.join(cmd)}")

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
        print(f"编译成功: {output_file}")
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
    ]
    for name in files_to_remove:
        path = os.path.join(script_dir, name)
        if os.path.exists(path):
            os.remove(path)
            print(f"已删除: {path}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "clean":
        clean()
    else:
        success = build()
        sys.exit(0 if success else 1)
