import os
import sys
import subprocess
import shutil


def build_c_engine():
    print("=" * 60)
    print("步骤 1: 编译 C 引擎")
    print("=" * 60)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    build_script = os.path.join(script_dir, "build_engine.py")
    if not os.path.isfile(build_script):
        print("错误: build_engine.py 未找到")
        sys.exit(1)
    subprocess.check_call([sys.executable, build_script], cwd=script_dir)

    dll_name = "engine_core.dll" if sys.platform == "win32" else "engine_core.so"
    dll_path = os.path.join(script_dir, dll_name)
    if not os.path.isfile(dll_path):
        print(f"错误: 编译后未找到 {dll_name}")
        sys.exit(1)
    print(f"C 引擎编译成功: {dll_path}")
    return dll_path


def package_exe():
    print()
    print("=" * 60)
    print("步骤 2: PyInstaller 打包")
    print("=" * 60)
    script_dir = os.path.dirname(os.path.abspath(__file__))

    dll_name = "engine_core.dll" if sys.platform == "win32" else "engine_core.so"
    dll_path = os.path.join(script_dir, dll_name)
    if not os.path.isfile(dll_path):
        print(f"错误: {dll_name} 不存在，请先编译 C 引擎")
        sys.exit(1)

    book_bin = os.path.join(script_dir, "dist", "book.bin")
    if not os.path.isfile(book_bin):
        print("错误: dist/book.bin 不存在，请先运行 generate_book.py")
        sys.exit(1)

    dist_dir = os.path.join(script_dir, "dist")
    build_dir = os.path.join(script_dir, "build_pyinstaller")
    if os.path.isdir(build_dir):
        shutil.rmtree(build_dir)
    if os.path.isdir(dist_dir):
        shutil.rmtree(dist_dir)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "Hellcopter",
        "--distpath", dist_dir,
        "--workpath", build_dir,
        "--add-data", f"{dll_path}{os.pathsep}.",
        "--add-data", f"{book_bin}{os.pathsep}.",
        "--hidden-import", "chess",
        "--hidden-import", "engine",
        "--hidden-import", "engine_wrapper",
        "--clean",
        os.path.join(script_dir, "uci_engine.py"),
    ]

    print(f"执行命令: {' '.join(cmd)}")
    print()
    subprocess.check_call(cmd, cwd=script_dir)

    exe_name = "Hellcopter.exe" if sys.platform == "win32" else "Hellcopter"
    exe_path = os.path.join(dist_dir, exe_name)
    if os.path.isfile(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print()
        print("=" * 60)
        print("打包成功!")
        print(f"输出文件: {exe_path}")
        print(f"文件大小: {size_mb:.1f} MB")
        print()
        print("使用方式 (与其他 UCI 引擎相同):")
        print(f"  在 cutechess-cli 中: cmd={exe_path}")
        print(f"  命令行测试: echo go depth 10 | {exe_name}")
        print("=" * 60)
    else:
        print("错误: 打包后未找到可执行文件")
        sys.exit(1)


if __name__ == "__main__":
    build_c_engine()
    package_exe()
