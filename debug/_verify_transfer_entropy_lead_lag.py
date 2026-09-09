"""Synthetic proof for research/transfer_entropy_lead_lag.py -- constructs
a known coupled system (Y causes X at a known lag) and confirms transfer
entropy recovers the correct lag/direction and flags it significant, while
an independent-noise pair shows no significant coupling in either
direction. Not a production script, run manually before trusting real
confirmed-pair output."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from transfer_entropy_lead_lag import transfer_entropy, te_with_significance, discretize

n_checks = 0
n_passed = 0


def check(name, cond):
    global n_checks, n_passed
    n_checks += 1
    status = "PASS" if cond else "FAIL"
    if cond:
        n_passed += 1
    print(f"[{status}] {name}")


rng = np.random.default_rng(7)
N = 8000
TRUE_LAG = 2
COUPLING = 0.85

# Y: independent AR(1) noise (no external driver).
y = np.zeros(N)
noise_y = rng.normal(0, 1.0, N)
for t in range(1, N):
    y[t] = 0.3 * y[t - 1] + noise_y[t]

# X: driven by Y at TRUE_LAG bars back, plus its own noise -- a real,
# known Y->X coupling at a known lag.
x = np.zeros(N)
noise_x = rng.normal(0, 1.0, N)
for t in range(TRUE_LAG, N):
    x[t] = COUPLING * y[t - TRUE_LAG] + 0.4 * noise_x[t]

# --- 1. discretize: check bin balance (quantile bins should be roughly equal-population) ---
bins = discretize(rng.normal(0, 1, 4000), n_bins=4)
counts = np.bincount(bins.astype(int))
check("quantile bins are roughly balanced (within 20% of expected)",
      bool(np.all(np.abs(counts - 1000) < 200)))

# --- 2. transfer_entropy: TE_{Y->X} should peak at the TRUE lag ---
te_by_lag = {lag: transfer_entropy(x, y, lag, n_bins=4) for lag in range(1, 6)}
print("TE_{Y->X} by lag:", {k: round(v, 4) for k, v in te_by_lag.items()})
best_lag = max(te_by_lag, key=te_by_lag.get)
check(f"TE_Y->X peaks at the true lag ({TRUE_LAG}), got lag {best_lag}", best_lag == TRUE_LAG)

# --- 3. TE_{Y->X} at the true lag should exceed TE_{X->Y} at every lag (correct direction) ---
te_reverse_by_lag = {lag: transfer_entropy(y, x, lag, n_bins=4) for lag in range(1, 6)}
print("TE_{X->Y} by lag:", {k: round(v, 4) for k, v in te_reverse_by_lag.items()})
check("TE_Y->X at the true lag exceeds every TE_X->Y value (correct causal direction)",
      te_by_lag[TRUE_LAG] > max(te_reverse_by_lag.values()))

# --- 4. Permutation significance: the real coupling should be significant at the true lag ---
rng2 = np.random.default_rng(99)
sig_result = te_with_significance(x, y, TRUE_LAG, n_bins=4, n_perm=100, rng=rng2)
print("Significance at true lag:", sig_result)
check("real coupling is significant at the true lag (p < 0.05)",
      sig_result["status"] == "ok" and sig_result["p_value"] < 0.05)

# --- 5. Independent-noise pair: no significant coupling in either direction ---
x_indep = rng.normal(0, 1, N)
y_indep = rng.normal(0, 1, N)
rng3 = np.random.default_rng(123)
sig_indep_fwd = te_with_significance(x_indep, y_indep, TRUE_LAG, n_bins=4, n_perm=100, rng=rng3)
rng4 = np.random.default_rng(124)
sig_indep_rev = te_with_significance(y_indep, x_indep, TRUE_LAG, n_bins=4, n_perm=100, rng=rng4)
print("Independent-noise significance (fwd/rev):", sig_indep_fwd["p_value"], sig_indep_rev["p_value"])
check("independent noise pair shows NO significant coupling either direction (p >= 0.05 both ways)",
      sig_indep_fwd["p_value"] >= 0.05 and sig_indep_rev["p_value"] >= 0.05)

print(f"\n{n_passed}/{n_checks} checks passed")
sys.exit(0 if n_passed == n_checks else 1)
