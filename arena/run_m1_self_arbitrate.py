"""
Hellcopter vs Monarch 2005 v1.7 — 96s+0.8s 标定对局脚本（自仲裁 / LOS 早停）

口径：与 arena/run_m1.ps1 / EXPERIMENTS.md 标定一致
  - Hellcopter：Threads=1, Ponder=false, OwnBook=false, SyzygyPath 显式置空
  - Monarch   ：默认选项（无 book、无 EGTB、自身不支持 Threads/Ponder setoption）
  - 时制     ：96s + 0.8s（基准 + 增量）
  - 先后手   ：奇数局 Hellcopter 白、偶数局 Hellcopter 黑（100 局 50/50 对半）
  - 早停     ：LOS > 0.95 或 LOS < 0.05 即停（并报告方向）
  - 落盘     ：每局即时落 PGN，便于中断后仍能部分回收
  - 控制台   ：每局输出 W/L/D + 累计 + 实时 LOS

走子时间策略（关键修复）
  旧实现：脚本发 `go wtime/btime/winc/binc`，Hellcopter C 端 init_time_manager
          收到 time_left=96s 后自己算 max_time=8s+，导致单步实际走到 11.5s
          （50 步 576s，已在 PGN 验证）。
  新实现：脚本算一个"分阶段单步预算"，用 `go movetime <budget_ms>` 模式——
          time_left=0 触发 init_time_manager 的 fallback 路径，
          C 端严格把 time_limit 设为 movetime，单步 ≤ 8s。
  阶段：早期 1-10 手 * 0.5；中局 11-20 * 0.8；21-40 * 1.0；残局 >40 * 1.0。

兜底（5 层防御）
  1) movetime 本身是硬上界（C 端 search_time = time_limit）
  2) engine_comm 30s readline timeout（get_best_move 内部）
  3) 后台 stopper：budget+1s 时主动 stop（防 C 端不遵守）
  4) chess 库兜底：引擎返回 None/非法/超时 → 取第一个合法着法
  5) 引擎真死：可选 --engine-dead-as-draw 判和而非判负

LOS（Likelihood of Superiority）
  LOS ≈ Phi( (wins - losses) / sqrt(wins + losses + draws) )
  LOS>0.95 显著优势 / LOS<0.05 显著劣势 → 早停。

用法（在项目根目录下）：
    python arena/run_m1_self_arbitrate.py
可选参数：
    --rounds N           最大对局数（默认 100）
    --tc SEC,INC         时制，格式 'base,inc' 秒（默认 96,0.8）
    --los-stop-high H    LOS 高阈值，> 该值停止（默认 0.95）
    --los-stop-low L     LOS 低阈值，< 该值停止（默认 0.05）
    --out PATH           PGN 输出路径（默认 arena/m1_self_<timestamp>.pgn）
    --min-rounds K       前 K 局不允许早停（默认 10）
    --movetime-cap MS    单步硬上界（毫秒），默认 8000
    --engine-dead-as-draw  引擎真死时本局判和而非判负（默认 off）

依赖：python-chess；复用本仓库 engine_comm.Engine。
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime

# 让脚本既能从项目根跑也能从 arena/ 子目录跑
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import chess  # noqa: E402

from engine_comm import Engine  # noqa: E402


# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
ENGINE_PARAMS = os.path.join(_ROOT, "engine_params.json")
MONARCH_EXE = os.path.join(_ROOT, "test_engines", "Monarch 2005",
                           "Monarch(v1.7)", "Monarch(v1.7).exe")
MAX_PLIES = 600   # 防互相喂招的硬上限
ILLEGAL_FALLBACK = "0000"


# ---------------------------------------------------------------------------
# 静默模式（屏蔽 engine_comm.Engine 内部的 [ENGINE-DBG]）
# ---------------------------------------------------------------------------
@contextmanager
def _quiet_output(quiet: bool):
    if not quiet:
        yield
        return
    devnull = open(os.devnull, "w")
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = devnull, devnull
        yield
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        devnull.close()


# ---------------------------------------------------------------------------
# UCI 启动包装
# ---------------------------------------------------------------------------
def _make_hellcopter(quiet: bool) -> Engine:
    """Hellcopter 启动 + UCI 选项锁死（Threads=1, Ponder=false, OwnBook=false, SyzygyPath 置空）"""
    if not os.path.isfile(ENGINE_PARAMS):
        raise FileNotFoundError(f"engine_params.json not found: {ENGINE_PARAMS}")
    uci_script = os.path.join(_ROOT, "uci_engine.py")
    if not os.path.isfile(uci_script):
        raise FileNotFoundError(f"uci_engine.py not found: {uci_script}")

    env = os.environ.copy()
    env["ENGINE_PARAMS"] = ENGINE_PARAMS

    eng = Engine(sys.executable, engine_args=[uci_script],
                 protocol="uci", init_env=env)
    eng.syzygy_path = None  # 避免 Engine.start() 探测 dist/syzygy
    with _quiet_output(quiet):
        if not eng.start():
            raise RuntimeError("Hellcopter engine failed to start")
        for name, val in [("Threads", "1"), ("Ponder", "false"),
                          ("OwnBook", "false"), ("BookPath", ""),
                          ("SyzygyPath", "")]:
            eng.set_option(name, val)
    return eng


def _make_monarch(quiet: bool) -> Engine:
    """Monarch 2005 v1.7：不接 setoption，以默认选项起。"""
    if not os.path.isfile(MONARCH_EXE):
        raise FileNotFoundError(f"Monarch exe not found: {MONARCH_EXE}")
    eng = Engine(MONARCH_EXE, protocol="uci")
    eng.syzygy_path = None
    with _quiet_output(quiet):
        if not eng.start():
            raise RuntimeError("Monarch engine failed to start")
    return eng


# ---------------------------------------------------------------------------
# 时间预算
# ---------------------------------------------------------------------------
def _compute_budget_ms(mover_clk_ms: int, inc_ms: int,
                       fullmove: int, movetime_cap_ms: int) -> int:
    """
    脚本层单步预算（毫秒）。模仿 Hellcopter 内部 _compute_time 但更紧：
      - 早期 1-10 手：× 0.5（≈ 1.2-1.5s）
      - 中局 11-20：× 0.8（≈ 2-3s）
      - 中后 21-40：× 1.0（≈ 3-4s）
      - 残局 >40：× 1.0（≈ 4-5s）
    硬上界 = min(剩余 - 5*inc, movetime_cap_ms, 8000ms)，最小 200ms。
    """
    if fullmove <= 10:
        est_left, factor = max(15, 40 - fullmove), 0.5
    elif fullmove <= 20:
        est_left, factor = 30, 0.8
    elif fullmove <= 40:
        est_left, factor = max(15, 50 - fullmove), 1.0
    else:
        est_left, factor = max(10, 60 - fullmove), 1.0

    base = mover_clk_ms / est_left + inc_ms * 0.85
    base = min(base, mover_clk_ms * 0.5) * factor
    upper = max(500, mover_clk_ms - 5 * inc_ms)
    cap = movetime_cap_ms if movetime_cap_ms > 0 else 3000
    return max(200, int(min(base, upper, cap)))


# ---------------------------------------------------------------------------
# 走子
# ---------------------------------------------------------------------------
def _get_move(eng: Engine, move_history: list[str],
              budget_ms: int, board_for_fallback: chess.Board,
              mover_label: str, quiet: bool) -> tuple[str | None, int, bool]:
    """
    走一步子。用 go movetime <budget_ms> 模式（关键修复）。
    返回 (move_uci, elapsed_ms, used_fallback)。
    used_fallback=True 表示走了 chess 库兜底，引擎真实状态可能异常。
    """
    t0 = time.perf_counter()

    # 后台 stopper：budget + 1s 时主动发 stop 兜底（防 C 端不遵守）
    import threading

    def _stop():
        try:
            if eng.is_alive():
                with _quiet_output(quiet):
                    eng.send("stop")
        except Exception:
            pass

    stopper = threading.Timer((budget_ms + 1000) / 1000.0, _stop)
    stopper.daemon = True
    stopper.start()

    try:
        with _quiet_output(quiet):
            move_uci = eng.get_best_move(move_history, budget_ms)
    finally:
        stopper.cancel()

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    def _legal(u: str | None) -> bool:
        if not u or u == ILLEGAL_FALLBACK:
            return False
        try:
            return chess.Move.from_uci(u) in board_for_fallback.legal_moves
        except ValueError:
            return False

    if _legal(move_uci):
        return move_uci, elapsed_ms, False

    if not eng.is_alive():
        return None, elapsed_ms, False

    # 引擎回了个无效/超时答案：stop 收尾 + chess 库兜底
    try:
        eng.send("stop")
    except Exception:
        pass
    deadline = time.time() + 2.0
    while time.time() < deadline:
        line = eng.readline(timeout=0.3)
        if line and line.startswith("bestmove"):
            break

    legal = list(board_for_fallback.legal_moves)
    if legal:
        fb = legal[0].uci()
        print(f"  [fallback] {mover_label} no legal move; using {fb}")
        return fb, int((time.perf_counter() - t0) * 1000), True
    return None, int((time.perf_counter() - t0) * 1000), False


# ---------------------------------------------------------------------------
# 单局
# ---------------------------------------------------------------------------
def play_one_game(
    hcopter: Engine, monarch: Engine,
    hellcopter_is_white: bool,
    base_ms: int, inc_ms: int,
    movetime_cap_ms: int,
    engine_dead_as_draw: bool,
    quiet: bool,
) -> tuple[str, list[str]]:
    """跑一局。返回 (结果, 走子历史)。"""
    board = chess.Board()
    h_clk = m_clk = base_ms  # 仅用于超时判定

    # 双方先做一次稳健的局前 reset
    with _quiet_output(quiet):
        for eng, tag in ((hcopter, "HELL"), (monarch, "MON")):
            try:
                eng.send("stop")
            except Exception:
                pass
            time.sleep(0.1)
            eng.send("ucinewgame")
            eng.send("isready")
            deadline = time.time() + 15.0
            while time.time() < deadline:
                line = eng.readline(timeout=0.5)
                if line and "readyok" in line:
                    break
            else:
                print(f"  [!] {tag} not ready (no readyok within 15s); abort")
                return ("0-1" if tag == "HELL" else "1-0"), []

    move_history: list[str] = []
    plies = 0
    fallback_streak = 0

    while not board.is_game_over(claim_draw=True) and plies < MAX_PLIES:
        is_white_turn = board.turn == chess.WHITE
        hellcopter_to_move = (is_white_turn == hellcopter_is_white)
        mover = hcopter if hellcopter_to_move else monarch
        mover_label = "HELL" if hellcopter_to_move else "MON"
        mover_clk = h_clk if hellcopter_to_move else m_clk

        # 走子方剩余 < 1.6s 直接判超时
        if mover_clk < max(500, 2 * inc_ms):
            print(f"  [!] {mover_label} out of time ({mover_clk}ms); loss for {mover_label}")
            return ("0-1" if hellcopter_to_move else "1-0"), move_history

        # 算脚本层 movetime 预算
        budget_ms = _compute_budget_ms(
            mover_clk, inc_ms, board.fullmove_number, movetime_cap_ms,
        )

        move_uci, elapsed_ms, used_fallback = _get_move(
            mover, move_history, budget_ms, board, mover_label, quiet,
        )

        # 连续 fallback → 强制 ucinewgame 清理引擎状态
        if used_fallback:
            fallback_streak += 1
            if fallback_streak >= 2:
                print(f"  [recovery] {mover_label} consecutive fallback; "
                      f"forcing ucinewgame to clear state")
                with _quiet_output(quiet):
                    mover.send("stop")
                    time.sleep(0.1)
                    mover.send("ucinewgame")
                    mover.send("isready")
                deadline = time.time() + 5.0
                while time.time() < deadline:
                    line = mover.readline(timeout=0.3)
                    if line and "readyok" in line:
                        break
                fallback_streak = 0
        else:
            fallback_streak = 0

        if move_uci is None:
            if engine_dead_as_draw:
                print(f"  [draw] {mover_label} process dead; treating as draw")
                return "1/2-1/2", move_history
            print(f"  [!] {mover_label} process dead; loss for {mover_label}")
            return ("0-1" if hellcopter_to_move else "1-0"), move_history

        try:
            move = chess.Move.from_uci(move_uci)
        except ValueError:
            print(f"  [!] {mover_label} bad uci {move_uci}; loss for {mover_label}")
            return ("0-1" if hellcopter_to_move else "1-0"), move_history

        # 时钟记账（脚本侧）：
        #   - 正常走子：扣真实墙钟 + 增量
        #   - fallback 走子：扣 movetime 预算（不能用 30s readline timeout
        #     那段时间来扣，否则几手 fallback 后 h_clk 直接扣成 0）
        if used_fallback:
            clock_spent_ms = budget_ms
        else:
            clock_spent_ms = elapsed_ms
        mover_clk = max(0, mover_clk - clock_spent_ms + inc_ms)
        if hellcopter_to_move:
            h_clk = mover_clk
        else:
            m_clk = mover_clk

        board.push(move)
        move_history.append(move_uci)
        plies += 1

    outcome = board.outcome(claim_draw=True)
    return (outcome.result() if outcome else "1/2-1/2"), move_history


# ---------------------------------------------------------------------------
# LOS
# ---------------------------------------------------------------------------
def los_score(wins: int, losses: int, draws: int) -> float:
    """LOS ≈ Phi((wins - losses) / sqrt(N))，N = 总对局数"""
    n = wins + losses + draws
    if n <= 0:
        return 0.5
    s = (wins - losses) / math.sqrt(n)
    return 0.5 * (1.0 + math.erf(s / math.sqrt(2.0)))


# ---------------------------------------------------------------------------
# PGN 落盘
# ---------------------------------------------------------------------------
def write_pgn(pgn_path: str, game_no: int,
              hellcopter_is_white: bool, result: str,
              move_history: list[str], base_s: float, inc_s: float) -> None:
    white = "Hellcopter" if hellcopter_is_white else "Monarch 2005 v1.7"
    black = "Monarch 2005 v1.7" if hellcopter_is_white else "Hellcopter"
    body_parts = []
    for i in range(0, len(move_history), 2):
        n = i // 2 + 1
        if i + 1 < len(move_history):
            body_parts.append(f"{n}. {move_history[i]} {move_history[i+1]}")
        else:
            body_parts.append(f"{n}. {move_history[i]}")
    body = " ".join(body_parts)
    tc = f"{base_s:g}+{inc_s:g}"
    with open(pgn_path, "a", encoding="utf-8") as f:
        f.write(f'[Event "M1 calibration self-arbitrated"]\n')
        f.write('[Site "arena"]\n')
        f.write(f'[Date "{datetime.now().strftime("%Y.%m.%d")}"]\n')
        f.write(f'[Round "{game_no}"]\n')
        f.write(f'[White "{white}"]\n')
        f.write(f'[Black "{black}"]\n')
        f.write(f'[Result "{result}"]\n')
        f.write(f'[TimeControl "{tc}"]\n')
        f.write('[WhiteThreads "1"]\n')
        f.write('[WhiteOwnBook "false"]\n')
        f.write('[WhitePonder "false"]\n')
        f.write('\n')
        f.write(f'{body} {result}\n\n')


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Hellcopter vs Monarch 96+0.8 self-arbitrated match with LOS early-stop",
    )
    ap.add_argument("--rounds", type=int, default=100, help="最大对局数（默认 100）")
    ap.add_argument("--tc", type=str, default="96,0.8",
                    help="时制，格式 'base,inc' 秒（默认 96,0.8）")
    ap.add_argument("--los-stop-high", type=float, default=0.95,
                    help="LOS 高阈值，> 该值停止（默认 0.95）")
    ap.add_argument("--los-stop-low", type=float, default=0.05,
                    help="LOS 低阈值，< 该值停止（默认 0.05）")
    ap.add_argument("--out", type=str, default=None,
                    help="PGN 输出路径（默认 arena/m1_self_<timestamp>.pgn）")
    ap.add_argument("--min-rounds", type=int, default=10,
                    help="前 K 局不允许早停（默认 10）")
    ap.add_argument("--movetime-cap", type=int, default=3000,
                    help="单步硬上界（毫秒），默认 3000（96+0.8 时制下 5s/步 × 50 步会超时）")
    ap.add_argument("--engine-dead-as-draw", action="store_true",
                    help="引擎真死时本局判和而非判负（默认 off）")
    ap.add_argument("--no-quiet", action="store_true",
                    help="关闭静默模式（默认屏蔽 engine_comm 内部 [ENGINE-DBG]）")
    args = ap.parse_args()
    quiet = not args.no_quiet

    base_s, inc_s = [float(x) for x in args.tc.split(",")]
    base_ms = int(base_s * 1000)
    inc_ms = int(inc_s * 1000)

    if args.out is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        args.out = os.path.join(_HERE, f"m1_self_{ts}.pgn")

    print("=" * 70)
    print("Hellcopter vs Monarch 2005 v1.7 — 96+0.8 self-arbitrated match")
    print(f"  rounds       : {args.rounds}")
    print(f"  time control : {base_s:.0f}+{inc_s:.1f}  (ms base={base_ms} inc={inc_ms})")
    print(f"  LOS early-stp: > {args.los_stop_high} or < {args.los_stop_low} "
          f"(after {args.min_rounds} games)")
    print(f"  movetime cap : {args.movetime_cap} ms (96+0.8 时制推荐 2000-3000)")
    print(f"  quiet        : {'on' if quiet else 'off'}")
    print(f"  dead→draw    : {'yes' if args.engine_dead_as_draw else 'no'}")
    print(f"  PGN output   : {args.out}")
    print("=" * 70)

    hcopter = _make_hellcopter(quiet=quiet)
    monarch = _make_monarch(quiet=quiet)

    if os.path.exists(args.out):
        os.remove(args.out)

    wins = losses = draws = 0
    t0 = time.time()

    try:
        for game_no in range(1, args.rounds + 1):
            hellcopter_is_white = (game_no % 2 == 1)
            color = "White" if hellcopter_is_white else "Black"
            print(f"\n[Game {game_no:3d}] Hellcopter plays {color} "
                  f"({base_s:.0f}+{inc_s:.1f})", flush=True)

            t_g = time.time()
            result, moves = play_one_game(
                hcopter, monarch, hellcopter_is_white,
                base_ms, inc_ms,
                movetime_cap_ms=args.movetime_cap,
                engine_dead_as_draw=args.engine_dead_as_draw,
                quiet=quiet,
            )
            dt = time.time() - t_g

            if result == "1-0":
                if hellcopter_is_white:
                    wins += 1
                    outcome = "WIN  (1-0)"
                else:
                    losses += 1
                    outcome = "LOSS (0-1)"
            elif result == "0-1":
                if hellcopter_is_white:
                    losses += 1
                    outcome = "LOSS (0-1)"
                else:
                    wins += 1
                    outcome = "WIN  (0-1)"
            else:
                draws += 1
                outcome = "DRAW (½-½)"

            total = wins + losses + draws
            winrate = (wins + 0.5 * draws) / total if total else 0.0
            los = los_score(wins, losses, draws)

            print(f"  -> {outcome}  | 累计 W/L/D = {wins}/{losses}/{draws}  "
                  f"WR={winrate:.3f}  LOS={los:.3f}  "
                  f"(本局 {dt:.1f}s, 总用时 {(time.time()-t0)/60:.1f}min)")

            write_pgn(args.out, game_no, hellcopter_is_white, result,
                      moves, base_s, inc_s)

            if total >= args.min_rounds:
                if los > args.los_stop_high:
                    print(f"\n>>> EARLY STOP: LOS={los:.3f} > {args.los_stop_high} "
                          f"(Hellcopter 显著优势)")
                    break
                if los < args.los_stop_low:
                    print(f"\n>>> EARLY STOP: LOS={los:.3f} < {args.los_stop_low} "
                          f"(Hellcopter 显著劣势)")
                    break
    finally:
        # 干净关引擎
        for eng in (hcopter, monarch):
            try:
                eng.send("quit")
            except Exception:
                pass
        time.sleep(0.2)
        for eng in (hcopter, monarch):
            try:
                if eng.process and eng.process.poll() is None:
                    eng.process.terminate()
            except Exception:
                pass

    # 总结
    total = wins + losses + draws
    print()
    print("=" * 70)
    print("MATCH SUMMARY")
    print(f"  Games played : {total}")
    print(f"  W / L / D    : {wins} / {losses} / {draws}")
    if total:
        p = (wins + 0.5 * draws) / total
        print(f"  Score (H)    : {p:.4f}  ({p*100:.2f}%)")
        if 0 < p < 1:
            elo = -400 * math.log10(1 / p - 1)
            print(f"  Elo diff     : {elo:+.2f}  (Hellcopter vs Monarch)")
        print(f"  LOS (final)  : {los_score(wins, losses, draws):.3f}")
    print(f"  PGN          : {args.out}")
    print(f"  Total time   : {(time.time()-t0)/60:.1f} min")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
