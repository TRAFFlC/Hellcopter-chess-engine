"""
工具集成器模块

集成现有调优工具：
- auto_tune.py
- auto_ladder.py
- spsa_tuner.py
- texel_tuner.py
"""

import json
import os
import sys
import subprocess
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple


@dataclass
class ToolResult:
    tool_name: str
    success: bool
    output: str
    result_data: Dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    elapsed_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "output": self.output[:1000],
            "result_data": self.result_data,
            "error_message": self.error_message,
            "elapsed_time": self.elapsed_time,
        }


class ToolIntegrator:
    """工具集成器"""

    def __init__(self, config_manager, base_dir: str):
        self.config_manager = config_manager
        self.base_dir = base_dir
        self.python_exe = sys.executable or "python"
        self.tool_logs: List[Dict[str, Any]] = []
        self.logs_file = config_manager.get_output_path("tool_logs.json")
        self._load_logs()

    def _load_logs(self):
        if os.path.isfile(self.logs_file):
            try:
                with open(self.logs_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.tool_logs = data.get("logs", [])
            except Exception as e:
                print(f"加载工具日志失败: {e}")

    def save_logs(self):
        data = {
            "total_logs": len(self.tool_logs),
            "logs": self.tool_logs[-100:],
        }
        try:
            with open(self.logs_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存工具日志失败: {e}")

    def _log_tool_call(self, tool_name: str, command: List[str], result: ToolResult):
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "tool_name": tool_name,
            "command": " ".join(command),
            "success": result.success,
            "error_message": result.error_message,
            "elapsed_time": result.elapsed_time,
        }
        self.tool_logs.append(log_entry)
        self.save_logs()

    def _run_tool(self, tool_name: str, script_path: str, args: List[str],
                  timeout: int = 3600, cwd: Optional[str] = None) -> ToolResult:
        """运行工具脚本"""
        if not os.path.isfile(script_path):
            return ToolResult(
                tool_name=tool_name,
                success=False,
                output="",
                error_message=f"脚本未找到: {script_path}",
            )

        command = [self.python_exe, script_path] + args
        print(f"\n运行工具: {tool_name}")
        print(f"命令: {' '.join(command)}")

        import time
        start_time = time.perf_counter()

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=cwd or self.base_dir,
                timeout=timeout,
            )
            elapsed = time.perf_counter() - start_time

            output = result.stdout + result.stderr
            success = result.returncode == 0

            tool_result = ToolResult(
                tool_name=tool_name,
                success=success,
                output=output,
                error_message="" if success else f"Return code: {result.returncode}",
                elapsed_time=elapsed,
            )

            self._log_tool_call(tool_name, command, tool_result)
            return tool_result

        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - start_time
            tool_result = ToolResult(
                tool_name=tool_name,
                success=False,
                output="",
                error_message=f"超时 ({timeout}s)",
                elapsed_time=elapsed,
            )
            self._log_tool_call(tool_name, command, tool_result)
            return tool_result
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            tool_result = ToolResult(
                tool_name=tool_name,
                success=False,
                output="",
                error_message=str(e),
                elapsed_time=elapsed,
            )
            self._log_tool_call(tool_name, command, tool_result)
            return tool_result

    def run_auto_tune(self, base_config: str = "configs/v1.5.0.json",
                      rounds: int = 11, tc: str = "96+0.8",
                      accept_threshold: float = 0.55) -> ToolResult:
        """运行 auto_tune.py"""
        script = os.path.join(self.base_dir, "auto_tune.py")
        args = [
            "--base-config", base_config,
            "--rounds", str(rounds),
            "--tc", tc,
            "--accept-threshold", str(accept_threshold),
        ]
        return self._run_tool("auto_tune", script, args, timeout=7200)

    def run_auto_ladder(self, config: str = "configs/v1.3.0.json",
                        start_from: str = "shallowblue",
                        skip_quick: bool = False) -> ToolResult:
        """运行 auto_ladder.py"""
        script = os.path.join(self.base_dir, "auto_ladder.py")
        args = [
            "--config", config,
            "--start-from", start_from,
        ]
        if skip_quick:
            args.append("--skip-quick")
        return self._run_tool("auto_ladder", script, args, timeout=7200)

    def run_spsa_tuner(self, base_version: str = "v1.5.0",
                       iterations: int = 50, games: int = 100,
                       tc: str = "10+0.1", opponent: str = "tscp181",
                       params: Optional[List[str]] = None) -> ToolResult:
        """运行 spsa_tuner.py"""
        script = os.path.join(self.base_dir, "spsa_tuner.py")
        args = [
            "run",
            "--config", base_version,
            "--iterations", str(iterations),
            "--games", str(games),
            "--tc", tc,
            "--opponent", opponent,
        ]
        if params:
            args.extend(["--params"] + params)
        return self._run_tool("spsa_tuner", script, args, timeout=7200)

    def run_texel_tuner(self, positions_file: str,
                        output: str = "tuning_result.json",
                        iterations: int = 1000,
                        learning_rate: float = 0.01) -> ToolResult:
        """运行 texel_tuner.py"""
        script = os.path.join(self.base_dir, "texel_tuner.py")
        args = [
            "--positions", positions_file,
            "--output", output,
            "--iterations", str(iterations),
            "--learning-rate", str(learning_rate),
        ]
        return self._run_tool("texel_tuner", script, args, timeout=3600)

    def run_velvet_analyze(self, pgn_file: str, output: str = "analysis.json",
                           depth: int = 20, time_limit: float = 0.5) -> ToolResult:
        """运行 velvet_analyze.py"""
        script = os.path.join(self.base_dir, "velvet_analyze.py")
        args = [
            "--pgn", pgn_file,
            "--output", output,
            "--depth", str(depth),
            "--time", str(time_limit),
        ]
        return self._run_tool("velvet_analyze", script, args, timeout=3600)

    def run_match(self, opponent: str = "tscp181", rounds: int = 20,
                  tc: str = "96+0.8", config: Optional[str] = None) -> ToolResult:
        """运行 run_match.py"""
        script = os.path.join(self.base_dir, "run_match.py")
        args = [
            "--opponent", opponent,
            "--rounds", str(rounds),
            "--tc", tc,
        ]
        if config:
            args.extend(["--config", config])
        return self._run_tool("run_match", script, args, timeout=3600)

    def get_tool_history(self, tool_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取工具调用历史"""
        if tool_name:
            return [log for log in self.tool_logs if log["tool_name"] == tool_name]
        return self.tool_logs

    def get_last_successful_result(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """获取最后一次成功的结果"""
        for log in reversed(self.tool_logs):
            if log["tool_name"] == tool_name and log["success"]:
                return log
        return None
