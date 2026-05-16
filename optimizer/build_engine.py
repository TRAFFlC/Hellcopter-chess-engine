import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, List


class EngineBuilder:
    def __init__(self, base_dir: str = "."):
        self.base_dir = Path(base_dir).resolve()
        self.source_dir = self.base_dir
        self.build_dir = self.base_dir / "build"
        self.output_dir = self.base_dir

    def build(self, compiler: Optional[str] = None,
              optimization: str = "O3",
              clean: bool = False,
              extra_flags: Optional[List[str]] = None,
              march_native: bool = True) -> str:
        if clean:
            self._clean()

        self.build_dir.mkdir(exist_ok=True)

        cc = compiler or self._detect_compiler()
        if not cc:
            raise RuntimeError("No C compiler found. Install gcc or clang.")

        c_flags = [f"-{optimization}", "-Wall", "-Wextra"]
        if march_native:
            c_flags.append("-march=native")
        if extra_flags:
            c_flags.extend(extra_flags)

        if sys.platform == "win32":
            c_flags.extend(["-DWIN32_LEAN_AND_MEAN"])
            if cc.endswith("gcc") or cc.endswith("g++"):
                c_flags.append("-mthreads")

        sources = list(self.source_dir.glob("engine_core.c"))
        if not sources:
            raise FileNotFoundError(
                f"No engine_core.c found in {self.source_dir}")

        output_name = "engine_core.dll" if sys.platform == "win32" else "engine_core.so"
        output_path = self.output_dir / output_name

        cmd = [cc] + c_flags + ["-shared", "-fPIC"]
        cmd.extend(["-o", str(output_path)])
        cmd.extend([str(s) for s in sources])

        if sys.platform == "win32" and (cc.endswith("gcc") or cc.endswith("g++")):
            cmd.extend(["-lws2_32"])

        print(f"Building: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"Build FAILED:\n{result.stderr}")
            raise RuntimeError(f"Build failed with code {result.returncode}")

        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)

        print(f"Build successful: {output_path}")
        return str(output_path)

    def _detect_compiler(self) -> Optional[str]:
        for cc in ["gcc", "clang", "cc", "x86_64-w64-mingw32-gcc"]:
            if shutil.which(cc):
                return cc
        return None

    def _clean(self):
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir)
        for pattern in ["engine_core.dll", "engine_core.so", "engine_core.o"]:
            p = self.output_dir / pattern
            if p.exists():
                p.unlink()

    def rebuild(self, compiler: Optional[str] = None,
                optimization: str = "O2",
                extra_flags: Optional[List[str]] = None) -> str:
        return self.build(compiler=compiler, optimization=optimization,
                          clean=True, extra_flags=extra_flags)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build Hellcopter engine")
    parser.add_argument("--compiler", default=None,
                        help="C compiler (gcc, clang, etc.)")
    parser.add_argument("--optimization", default="O2",
                        choices=["O0", "O1", "O2", "O3", "Os"])
    parser.add_argument("--clean", action="store_true",
                        help="Clean before building")
    parser.add_argument("--base-dir", default=".", help="Base directory")
    parser.add_argument("--extra-flags", nargs="*",
                        default=[], help="Extra compiler flags")
    args = parser.parse_args()

    builder = EngineBuilder(base_dir=args.base_dir)
    output = builder.build(compiler=args.compiler, optimization=args.optimization,
                           clean=args.clean, extra_flags=args.extra_flags)
    print(f"Output: {output}")


if __name__ == "__main__":
    main()
