import json
import os
import re
import subprocess
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple


class MatchResult:
    def __init__(self, wins: int = 0, losses: int = 0, draws: int = 0,
                 opponent: str = "", time_control: str = "", rounds: int = 0,
                 elo_diff: float = 0.0, ci_low: float = 0.0, ci_high: float = 0.0,
                 winrate: float = 0.0):
        self.wins = wins
        self.losses = losses
        self.draws = draws
        self.opponent = opponent
        self.time_control = time_control
        self.rounds = rounds
        self.elo_diff = elo_diff
        self.ci_low = ci_low
        self.ci_high = ci_high
        self.winrate = winrate

    @property
    def total(self) -> int:
        return self.wins + self.losses + self.draws

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wins": self.wins, "losses": self.losses, "draws": self.draws,
            "opponent": self.opponent, "time_control": self.time_control,
            "rounds": self.rounds, "elo_diff": self.elo_diff,
            "ci_low": self.ci_low, "ci_high": self.ci_high,
            "winrate": self.winrate
        }


OPPONENTS = {
    "monarch": {"dir": "test_engines/Monarch/Monarch(v1.7)", "exe": "Monarch(v1.7).exe", "proto": "uci"},
    "apollo": {"dir": "test_engines/Apollo", "exe": "apollo.exe", "proto": "uci"},
    "rainman": {"dir": "test_engines/Rainman", "exe": "rainman.exe", "proto": "xboard"},
    "shallowblue": {"dir": "test_engines/ShallowBlue", "exe": "shallowblue.exe", "proto": "uci"},
    "pulsar": {"dir": "test_engines/Pulsar", "exe": "pulsar2009-9b.exe", "proto": "xboard"},
    "tscp181": {"dir": "test_engines/TSCP", "exe": "tscp181.exe", "proto": "xboard"},
}


def _find_cutechess(base_dir: str) -> Optional[str]:
    found = shutil.which("cutechess-cli")
    if found:
        return found
    candidates = [
        os.path.join(base_dir, "cutechess-cli.exe"),
        os.path.join(base_dir, "cutechess-cli"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _calc_elo(wins: int, losses: int, draws: int) -> Tuple[float, float, float]:
    import math
    total = wins + losses + draws
    if total == 0:
        return 0.0, 0.0, 0.0
    score = (wins + draws * 0.5) / total
    if score <= 0.0 or score >= 1.0:
        if score <= 0.0:
            return -1000.0, -1000.0, -1000.0
        return 1000.0, 1000.0, 1000.0
    elo_diff = -400.0 * math.log10(1.0 / score - 1.0)
    z = 1.96
    n = total
    p_hat = (wins + draws * 0.5) / n
    denom = 1.0 + z * z / n
    center = (p_hat + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p_hat * (1 - p_hat) + z * z / (4 * n)) / n) / denom
    lo = max(center - margin, 0.0001)
    hi = min(center + margin, 0.9999)
    elo_lo = -400.0 * math.log10(1.0 / lo - 1.0)
    elo_hi = -400.0 * math.log10(1.0 / hi - 1.0)
    return elo_diff, elo_lo, elo_hi


def _parse_cutechess_output(output: str) -> Tuple[int, int, int]:
    pattern = re.compile(
        r"Score of\s+.+?\s+vs\s+.+?:\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)"
    )
    for line in output.splitlines():
        m = pattern.search(line)
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return 0, 0, 0


class MatchRunner:
    def __init__(self, base_dir: str = ".", results_dir: str = "test_results"):
        self.base_dir = os.path.abspath(base_dir)
        self.results_dir = os.path.join(self.base_dir, results_dir)
        os.makedirs(self.results_dir, exist_ok=True)

    def _get_opponent_exe(self, opponent: str) -> Tuple[str, str]:
        opp = OPPONENTS.get(opponent)
        if not opp:
            raise ValueError(
                f"Unknown opponent: {opponent}. Available: {list(OPPONENTS.keys())}")
        exe_path = os.path.join(self.base_dir, opp["dir"], opp["exe"])
        if not os.path.isfile(exe_path):
            raise FileNotFoundError(
                f"Opponent executable not found: {exe_path}")
        return exe_path, opp["proto"]

    def run_match(self, opponent: str = "pulsar", rounds: int = 51,
                  time_control: str = "9+0.1", config_version: str = "",
                  pgnout: Optional[str] = None) -> MatchResult:
        cutechess = _find_cutechess(self.base_dir)
        if not cutechess:
            raise FileNotFoundError("cutechess-cli not found")

        opp_exe, opp_proto = self._get_opponent_exe(opponent)
        python_exe = sys.executable or "python"
        uci_script = os.path.join(self.base_dir, "uci_engine.py")

        opp_name = opponent.capitalize()
        if pgnout is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            pgnout = os.path.join(
                self.results_dir, f"match_{opponent}_{ts}.pgn")

        cmd = [
            cutechess,
            "-engine", "name=Hellcopter", "proto=uci",
            f"cmd={python_exe}", f"arg={uci_script}",
            "-engine", f"name={opp_name}", f"proto={opp_proto}",
            f"cmd={opp_exe}",
            "-each", f"tc={time_control}",
            "-rounds", str(rounds),
            "-pgnout", pgnout,
        ]

        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )
        full_output = []
        for line in process.stdout:
            stripped = line.rstrip()
            print(stripped, flush=True)
            full_output.append(stripped)
        process.wait()

        output = "\n".join(full_output)
        wins, losses, draws = _parse_cutechess_output(output)
        total = wins + losses + draws
        winrate = (wins + draws * 0.5) / total if total > 0 else 0.0
        elo_diff, ci_low, ci_high = _calc_elo(wins, losses, draws)

        result = MatchResult(
            wins=wins, losses=losses, draws=draws,
            opponent=opponent, time_control=time_control,
            rounds=rounds, elo_diff=elo_diff,
            ci_low=ci_low, ci_high=ci_high, winrate=winrate
        )

        self._save_result(result, config_version, pgnout)
        return result

    def run_self_play(self, v1: str, v2: str, rounds: int = 51,
                      time_control: str = "9+0.1") -> MatchResult:
        cutechess = _find_cutechess(self.base_dir)
        if not cutechess:
            raise FileNotFoundError("cutechess-cli not found")

        python_exe = sys.executable or "python"
        uci_script = os.path.join(self.base_dir, "uci_engine.py")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        pgnout = os.path.join(
            self.results_dir, f"selfplay_{v1}_vs_{v2}_{ts}.pgn")

        cmd = [
            cutechess,
            "-engine", f"name=Hellcopter-{v1}", "proto=uci",
            f"cmd={python_exe}", f"arg={uci_script}",
            "-engine", f"name=Hellcopter-{v2}", "proto=uci",
            f"cmd={python_exe}", f"arg={uci_script}",
            "-each", f"tc={time_control}",
            "-rounds", str(rounds),
            "-pgnout", pgnout,
        ]

        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )
        full_output = []
        for line in process.stdout:
            stripped = line.rstrip()
            print(stripped, flush=True)
            full_output.append(stripped)
        process.wait()

        output = "\n".join(full_output)
        wins, losses, draws = _parse_cutechess_output(output)
        total = wins + losses + draws
        winrate = (wins + draws * 0.5) / total if total > 0 else 0.0
        elo_diff, ci_low, ci_high = _calc_elo(wins, losses, draws)

        result = MatchResult(
            wins=wins, losses=losses, draws=draws,
            opponent=f"self-play({v1} vs {v2})",
            time_control=time_control, rounds=rounds,
            elo_diff=elo_diff, ci_low=ci_low, ci_high=ci_high,
            winrate=winrate
        )
        self._save_result(result, v1, pgnout)
        return result

    def run_benchmark(self, config_version: str = "",
                      positions: Optional[List[str]] = None,
                      depth: int = 10) -> Dict[str, Any]:
        from engine_wrapper import EngineWrapper
        eng = EngineWrapper()
        if positions is None:
            positions = [
                "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
                "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
                "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
                "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
            ]
        results = []
        total_nodes = 0
        total_time = 0.0
        for fen in positions:
            t0 = time.perf_counter()
            move, nodes = eng.find_best_move(
                fen, time_limit=10.0, max_depth=depth)
            elapsed = time.perf_counter() - t0
            nps = nodes / elapsed if elapsed > 0 else 0
            total_nodes += nodes
            total_time += elapsed
            results.append({
                "fen": fen, "move": move, "nodes": nodes,
                "time": round(elapsed, 3), "nps": round(nps, 0)
            })
        avg_nps = total_nodes / total_time if total_time > 0 else 0
        benchmark = {
            "config_version": config_version,
            "timestamp": datetime.now().isoformat(),
            "depth": depth,
            "positions_tested": len(positions),
            "total_nodes": total_nodes,
            "total_time": round(total_time, 3),
            "avg_nps": round(avg_nps, 0),
            "results": results
        }
        bench_path = os.path.join(
            self.results_dir, f"benchmark_{config_version or 'default'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(bench_path, 'w', encoding='utf-8') as f:
            json.dump(benchmark, f, indent=2, ensure_ascii=False)
        return benchmark

    def _save_result(self, result: MatchResult, config_version: str, pgn_path: str):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        data = {
            "test_id": f"test_{ts}",
            "timestamp": datetime.now().isoformat(),
            "config_version": config_version,
            "results": result.to_dict(),
            "pgn_file": pgn_path
        }
        out_path = os.path.join(self.results_dir, f"test_{ts}.json")
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def list_results(self) -> List[Dict[str, Any]]:
        results = []
        for f in sorted(Path(self.results_dir).glob("test_*.json")):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    results.append(json.load(fh))
            except (json.JSONDecodeError, KeyError):
                continue
        return results
