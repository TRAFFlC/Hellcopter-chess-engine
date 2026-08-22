"""Find optimal K (sigmoid scaling factor) for Texel tuning."""
import sys, os, json, numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine_wrapper import evaluate_fen, init
init()

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(base_dir, "master", "positions_200k_v2.json")) as f:
    data = json.load(f)
positions = [(p["fen"], p["result"]) for p in data["positions"]]
outcomes = np.array([r for _, r in positions])
print(f"Loaded {len(positions)} positions")
print(f"  outcomes: 0={(outcomes==0).sum()}, 0.5={(outcomes==0.5).sum()}, 1={(outcomes==1).sum()}")

print("Evaluating positions...")
evals = np.array([evaluate_fen(fen) for fen, _ in positions])
print(f"  eval: min={evals.min():.0f}, max={evals.max():.0f}, mean={evals.mean():.1f}, std={evals.std():.1f}")

def mse_for_K(K):
    pred = 1.0 / (1.0 + np.exp(-evals / K))
    return ((pred - outcomes) ** 2).mean()

# Coarse search
print("\nCoarse search:")
lo, hi = 50.0, 2000.0
for _ in range(15):
    m1 = lo + (hi - lo) / 3
    m2 = hi - (hi - lo) / 3
    if mse_for_K(m1) < mse_for_K(m2):
        hi = m2
    else:
        lo = m1
K_opt = (lo + hi) / 2
loss_opt = mse_for_K(K_opt)

print(f"Optimal K: {K_opt:.1f} (loss={loss_opt:.6f})")
print(f"  K=100: loss={mse_for_K(100):.6f}")
print(f"  K=200: loss={mse_for_K(200):.6f}")
print(f"  K=300: loss={mse_for_K(300):.6f}")
print(f"  K=400: loss={mse_for_K(400):.6f}")
