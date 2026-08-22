import os, sys, json, time, numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine_wrapper import evaluate_fen, reload_params
from config import load_and_resolve_config

def sigmoid(x, K):
    return 1.0 / (1.0 + np.exp(-x / K))

def mse(evals, outcomes, K):
    return ((sigmoid(evals, K) - outcomes) ** 2).mean()

def load_tunable_params(path):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    params = {}
    for group, members in raw.items():
        deduped = {}
        for k, v in members.items():
            deduped[k] = v
        params[group] = deduped
    return params

def extract_params(resolved, param_defs):
    vals, keys = [], []
    for group, members in param_defs.items():
        for name, meta in members.items():
            v = resolved.get("parameters", {}).get(group, {}).get(name, meta["initial"])
            vals.append(float(v))
            keys.append((group, name))
    return np.array(vals), keys

def apply_params(resolved, param_defs, keys, x):
    idx = 0
    for group, members in param_defs.items():
        for name in members:
            v = int(round(float(x[idx])))
            v = max(members[name]["min"], min(members[name]["max"], v))
            resolved.setdefault("parameters", {}).setdefault(group, {})[name] = v
            idx += 1

def evaluate_all_stm(fens):
    """Evaluate all FENs, returning scores from side-to-move perspective.
    evaluate_fen returns White's eval; flip if Black to move."""
    evals = np.empty(len(fens), dtype=np.float64)
    for i in range(0, len(fens), 512):
        batch = fens[i:i+512]
        for j, fen in enumerate(batch):
            score = evaluate_fen(fen)
            if fen.split(" ")[1] == 'b':
                score = -score
            evals[i+j] = score
    return evals

CACHE_PATH = "master/positions_quality.json"
PARAMS_PATH = "tuning/tunable_params.json"
CONFIG_PATH = "engine_params.json"
TEMP_CFG = ".__texel_temp__.json"
K = 150.0
LR = 1.0
BETA1, BETA2 = 0.9, 0.999
EPS_ADAM = 1e-8
N_ITERS = 80
GRAD_EPS = 2.0
L2_LAMBDA = 1e-6
GRAD_CLIP = 0.1
SAVE_EVERY = 5
SAMPLE_SIZE = int(os.environ.get("TEXEL_SAMPLE", "0"))  # 0 = use all (1.24M)

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load positions (outcomes already in side-to-move perspective)
with open(os.path.join(base_dir, CACHE_PATH), encoding="utf-8") as f:
    data = json.load(f)
positions = data["positions"]
fens = np.array([p["fen"] for p in positions])
outcomes = np.array([p["result"] for p in positions])
print(f"Positions: {len(positions)}")
print(f"  STM-win={(outcomes==1).sum()} STM-loss={(outcomes==0).sum()} Draw={(outcomes==0.5).sum()}")

if SAMPLE_SIZE > 0 and len(positions) > SAMPLE_SIZE:
    idx = np.random.RandomState(42).choice(len(positions), SAMPLE_SIZE, replace=False)
    fens = fens[idx]
    outcomes = outcomes[idx]
    print(f"Subsampled to {SAMPLE_SIZE}")

# Load param defs
param_defs = load_tunable_params(os.path.join(base_dir, PARAMS_PATH))
resolved = load_and_resolve_config(os.path.join(base_dir, CONFIG_PATH))
x0, keys = extract_params(resolved, param_defs)
n_params = len(x0)
print(f"Parameters: {n_params}")

# Warm up
print("Warming up...")
_ = evaluate_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")

# Base eval (from STM perspective)
print("Base eval...")
evals_base = evaluate_all_stm(fens)
loss_base = mse(evals_base, outcomes, K) + L2_LAMBDA * (x0 * x0).sum()
print(f"  Initial loss (MSE+L2): {loss_base:.6f}  (K={K})")

# Adam state
m, v = np.zeros(n_params), np.zeros(n_params)
t, x = 0, x0.copy()
history = []
log_path = os.path.join(base_dir, "tuning", "texel_log.json")

print(f"\nStarting {N_ITERS} iterations (lr={LR}, K={K}, l2={L2_LAMBDA})")

# Gradient sanity check
g0_check = L2_LAMBDA * (x * x).sum()
m0_check = mse(evals_base, outcomes, K)
base_loss_sanity = m0_check + g0_check
print("\nGradient sanity check:")
for i in range(min(3, n_params)):
    x_pert = x.copy()
    x_pert[i] += GRAD_EPS
    apply_params(resolved, param_defs, keys, x_pert)
    with open(os.path.join(base_dir, TEMP_CFG), "w") as f:
        json.dump(resolved, f)
    reload_params(os.path.join(base_dir, TEMP_CFG))
    evals_p = evaluate_all_stm(fens)
    l2_p = L2_LAMBDA * (x_pert * x_pert).sum()
    loss_p = mse(evals_p, outcomes, K) + l2_p
    g = (loss_p - base_loss_sanity) / GRAD_EPS
    print(f"  {keys[i][1]:35s}  grad={g:.6f}  {'OK' if abs(g) > 1e-7 else 'WARNING: near zero'}")
apply_params(resolved, param_defs, keys, x)
with open(os.path.join(base_dir, TEMP_CFG), "w") as f:
    json.dump(resolved, f)
reload_params(os.path.join(base_dir, TEMP_CFG))
evals_base = evaluate_all_stm(fens)
print()

for it in range(N_ITERS):
    t0 = time.time()
    t += 1

    grad = np.zeros(n_params)
    mse_base = mse(evals_base, outcomes, K)
    l2_base = L2_LAMBDA * (x * x).sum()
    base_loss = mse_base + l2_base

    for i in range(n_params):
        x_pert = x.copy()
        x_pert[i] += GRAD_EPS
        apply_params(resolved, param_defs, keys, x_pert)
        with open(os.path.join(base_dir, TEMP_CFG), "w") as f:
            json.dump(resolved, f)
        reload_params(os.path.join(base_dir, TEMP_CFG))
        evals_p = evaluate_all_stm(fens)
        loss_p = mse(evals_p, outcomes, K) + L2_LAMBDA * (x_pert * x_pert).sum()
        grad[i] = (loss_p - base_loss) / GRAD_EPS
        if i % 10 == 9:
            print(f"  grad[{i:3d}/{n_params}] = {grad[i]:.6f}")

    # Gradient clip
    gnorm = np.linalg.norm(grad)
    if gnorm > GRAD_CLIP:
        grad *= GRAD_CLIP / gnorm

    # Adam
    m = BETA1 * m + (1 - BETA1) * grad
    v = BETA2 * v + (1 - BETA2) * (grad * grad)
    m_hat = m / (1 - BETA1 ** t)
    v_hat = v / (1 - BETA2 ** t)
    x -= LR * m_hat / (np.sqrt(v_hat) + EPS_ADAM)

    # Clamp to bounds
    idx = 0
    for group, members in param_defs.items():
        for name, meta in members.items():
            x[idx] = max(float(meta["min"]), min(float(meta["max"]), x[idx]))
            idx += 1

    # Re-eval
    apply_params(resolved, param_defs, keys, x)
    with open(os.path.join(base_dir, TEMP_CFG), "w") as f:
        json.dump(resolved, f)
    reload_params(os.path.join(base_dir, TEMP_CFG))
    evals_base = evaluate_all_stm(fens)
    loss_new = mse(evals_base, outcomes, K) + L2_LAMBDA * (x * x).sum()

    elapsed = time.time() - t0
    entry = {"iter": it+1, "loss": round(loss_new, 6), "grad_norm": round(float(gnorm), 6), "time_s": round(elapsed, 1)}
    history.append(entry)
    print(f"iter {it+1:3d}: loss={loss_new:.6f}  |grad|={gnorm:.6f}  [{elapsed:.1f}s]")

    if gnorm < 0.00005 and it > 50:
        print("Converged.")
        break

    if (it + 1) % SAVE_EVERY == 0:
        with open(log_path, "w") as f:
            json.dump({"K": K, "history": history,
                        "params": {k[1]: float(x[i]) for i, k in enumerate(keys)},
                        "final_loss": round(float(loss_new), 6)}, f)

# Save
apply_params(resolved, param_defs, keys, x)
out_path = os.path.join(base_dir, "tuning", "texel_tuned.json")
with open(out_path, "w") as f:
    json.dump(resolved, f, indent=2)
print(f"\nSaved to {out_path}")
print("Final params:")
idx = 0
for group, members in param_defs.items():
    for name in members:
        delta = x[idx] - x0[idx]
        print(f"  {name:40s} {x0[idx]:8.1f}  →  {x[idx]:8.1f}  ({delta:+.1f})")
        idx += 1
