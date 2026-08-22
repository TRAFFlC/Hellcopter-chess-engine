import os
import sys
import json
import math
import time
import argparse
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine_wrapper import evaluate_fen, reload_params
from config import load_and_resolve_config


def sigmoid(x: float, K: float = 400.0) -> float:
    return 1.0 / (1.0 + math.exp(-x / K))


def load_tunable_params(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def extract_params(resolved: dict, param_defs: dict) -> np.ndarray:
    vals = []
    for group, params in param_defs.items():
        for name, meta in params.items():
            v = resolved.get("parameters", {}).get(group, {}).get(name, meta["initial"])
            vals.append(float(v))
    return np.array(vals)


def apply_params(resolved: dict, param_defs: dict, x: np.ndarray):
    idx = 0
    for group, params in param_defs.items():
        for name in params:
            resolved.setdefault("parameters", {}).setdefault(group, {})[name] = round(float(x[idx]), 1)
            idx += 1


_TEMP_CONFIG_PATH = None

def _get_temp_path(base_dir: str) -> str:
    global _TEMP_CONFIG_PATH
    if _TEMP_CONFIG_PATH is None:
        _TEMP_CONFIG_PATH = os.path.join(base_dir, ".__texel_temp__.json")
    return _TEMP_CONFIG_PATH


def set_params_and_eval(resolved: dict, param_defs: dict, x: np.ndarray,
                        positions: list, base_dir: str) -> np.ndarray:
    apply_params(resolved, param_defs, x)
    cfg_path = _get_temp_path(base_dir)
    with open(cfg_path, "w") as f:
        json.dump(resolved, f)
    reload_params(cfg_path)

    evals = np.zeros(len(positions))
    for i, (fen, _, _) in enumerate(positions):
        evals[i] = evaluate_fen(fen)
    return evals


def compute_loss_from_evals(evals: np.ndarray, positions: list,
                            K: float = 400.0) -> float:
    total = 0.0
    for i, (_, outcome, _) in enumerate(positions):
        pred = sigmoid(evals[i], K)
        err = pred - outcome
        total += err * err
    return total / len(positions)


def numeric_gradient(resolved: dict, param_defs: dict, x: np.ndarray,
                     positions: list, base_dir: str,
                     K: float = 400.0, eps: float = 0.1) -> np.ndarray:
    grad = np.zeros_like(x)
    evals_base = set_params_and_eval(resolved, param_defs, x, positions, base_dir)
    loss_base = compute_loss_from_evals(evals_base, positions, K)

    for i in range(len(x)):
        x_pert = x.copy()
        x_pert[i] += eps
        evals_pert = set_params_and_eval(resolved, param_defs, x_pert, positions, base_dir)
        loss_pert = compute_loss_from_evals(evals_pert, positions, K)
        grad[i] = (loss_pert - loss_base) / eps
        if i % 10 == 9:
            print(f"    grad[{i:3d}/{len(x)}] = {grad[i]:.6f}")

    return grad


def lbfgs_optimize(resolved: dict, param_defs: dict, x0: np.ndarray,
                   positions: list, base_dir: str,
                   max_iters: int = 100, K: float = 400.0,
                   lr: float = 1.0, m: int = 10) -> np.ndarray:
    x = x0.copy()
    n = len(x)
    s_list, y_list, rho_list = [], [], []

    for it in range(max_iters):
        t0 = time.time()
        evals = set_params_and_eval(resolved, param_defs, x, positions, base_dir)
        loss = compute_loss_from_evals(evals, positions, K)
        grad = numeric_gradient(resolved, param_defs, x, positions, base_dir, K)
        grad_norm = np.linalg.norm(grad)
        elapsed = time.time() - t0
        print(f"  iter {it:3d}: loss={loss:.6f}  |grad|={grad_norm:.4f}  [{elapsed:.0f}s]")

        if grad_norm < 0.005:
            print("  Converged.")
            break

        if it == 0:
            direction = -grad
        else:
            q = grad.copy()
            for i in range(min(it, m) - 1, -1, -1):
                alpha_i = rho_list[i] * np.dot(s_list[i], q)
                q = q - alpha_i * y_list[i]
            z = q
            for i in range(min(it, m)):
                beta = rho_list[i] * np.dot(y_list[i], z)
                z = z + s_list[i] * (alpha[i] - beta)
            direction = -z

        step = lr
        for _ in range(8):
            x_new = x + step * direction
            evals_new = set_params_and_eval(resolved, param_defs, x_new, positions, base_dir)
            loss_new = compute_loss_from_evals(evals_new, positions, K)
            if loss_new < loss:
                break
            step *= 0.5

        evals_new = set_params_and_eval(resolved, param_defs, x + step * direction, positions, base_dir)
        loss_new = compute_loss_from_evals(evals_new, positions, K)

        s = step * direction
        _, grad_new_val = grad, numeric_gradient(resolved, param_defs, x, positions, base_dir, K)
        y_vec = grad_new_val - grad
        sy = np.dot(s, y_vec)

        x = x + step * direction

        if sy > 1e-10:
            s_list.append(s.copy())
            y_list.append(y_vec.copy())
            rho_list.append(1.0 / sy)
            if len(s_list) > m:
                s_list.pop(0)
                y_list.pop(0)
                rho_list.pop(0)

    return x


def load_quiet_positions(pgn_path: str, max_positions: int = 100000,
                         min_ply: int = 8, max_ply: int = 80) -> list:
    import chess.pgn
    positions = []
    count_games = 0
    with open(pgn_path, encoding="utf-8", errors="replace") as f:
        while True:
            game = chess.pgn.read_game(f)
            if game is None:
                break
            count_games += 1
            result = game.headers.get("Result", "*")
            if result == "1-0":
                outcome = 1.0
            elif result == "0-1":
                outcome = 0.0
            elif result == "1/2-1/2":
                outcome = 0.5
            else:
                continue

            board = game.board()
            for i, move in enumerate(game.mainline_moves()):
                ply = i + 1
                if ply < min_ply or ply > max_ply:
                    board.push(move)
                    continue
                is_cap = board.is_capture(move)
                board.push(move)
                if board.is_check():
                    continue
                if is_cap or move.promotion is not None:
                    continue
                total_material = sum(
                    1 for sq in chess.SQUARES
                    if (p := board.piece_at(sq)) and p.piece_type != chess.KING
                )
                if total_material < 2:
                    continue
                positions.append((board.fen(), outcome, ply))
                if len(positions) >= max_positions:
                    return positions, count_games
    return positions, count_games


def main():
    parser = argparse.ArgumentParser(description="Texel Tuning for Hellcopter")
    parser.add_argument("--pgn", required=True, help="Path to PGN training data")
    parser.add_argument("--config", default=None, help="Base config path")
    parser.add_argument("--params", default=None, help="Tunable param defs JSON")
    parser.add_argument("--output", default=None, help="Output config path")
    parser.add_argument("--iters", type=int, default=50, help="Max iterations")
    parser.add_argument("--max-positions", type=int, default=50000)
    parser.add_argument("--lr", type=float, default=1.0)
    parser.add_argument("--K", type=float, default=400.0)
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    param_path = args.params or os.path.join(os.path.dirname(__file__), "tunable_params.json")
    param_defs = load_tunable_params(param_path)
    total_params = sum(len(p) for p in param_defs.values())
    print(f"Loaded {total_params} tunable parameters")

    config_path = args.config or os.path.join(base_dir, "engine_params.json")
    print(f"Resolving base config from {config_path}...")
    resolved = load_and_resolve_config(config_path)

    print(f"Loading quiet positions from {args.pgn}...")
    positions, game_count = load_quiet_positions(args.pgn, args.max_positions)
    print(f"  Games scanned: ~{game_count}")
    print(f"  Quiet positions: {len(positions)}")

    if len(positions) < 100:
        print("Too few positions, aborting.")
        return

    x0 = extract_params(resolved, param_defs)
    print(f"\nStarting Texel tuning ({args.iters} iters)...")
    x_opt = lbfgs_optimize(resolved, param_defs, x0, positions, base_dir,
                           max_iters=args.iters, K=args.K, lr=args.lr)

    print("\nOptimized parameters:")
    idx = 0
    for group, params in param_defs.items():
        for name in params:
            print(f"  {group}.{name} = {x_opt[idx]:.1f}")
            idx += 1

    apply_params(resolved, param_defs, x_opt)
    out_path = args.output or os.path.join(os.path.dirname(__file__), "tuned_config.json")
    with open(out_path, "w") as f:
        json.dump(resolved, f, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
