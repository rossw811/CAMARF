"""
Synthetic verification of cvar.py's historical_cvar() before trusting it on
real backtest P&L.

Case 1: large-N standard normal sample — compare empirical historical CVaR_95
against the known analytical closed-form for a Normal(0,1) loss distribution:
CVaR_alpha = phi(z_alpha) / (1 - alpha), where z_alpha = Phi^-1(alpha) and
phi is the standard normal density. For alpha=0.95: z=1.6449, phi(z)=0.1031,
CVaR_95 = 0.1031/0.05 = 2.0627. With N=200,000 samples, empirical should
converge within ~5% of this (Monte Carlo tolerance, not exact).

Case 2: known small integer case — losses = -[1..100] means daily_pnl =
[-100..-1] (i.e. losses = [1..100]). At alpha=0.95, VaR is the 95th
percentile of losses = 96 (0-indexed quantile via numpy's linear
interpolation), CVaR = mean of losses >= that value. Checked against a
hand-computed value, not just "some positive number."

Case 3: all-profitable days (no tail loss) — losses are all negative
(pnl all positive), so VaR/CVaR should both be negative (no loss risk),
not clipped to zero or crashing.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from scipy import stats as sp_stats

from cvar import historical_cvar

failures = []
rng = np.random.default_rng(7)

# --- Case 1: standard normal, large N ---
n = 200_000
sample = rng.normal(loc=0.0, scale=1.0, size=n)
result = historical_cvar(sample, 0.95)
z95 = sp_stats.norm.ppf(0.95)
analytical_cvar95 = sp_stats.norm.pdf(z95) / 0.05
rel_err = abs(result["cvar"] - analytical_cvar95) / analytical_cvar95
if rel_err > 0.05:
    failures.append(
        f"Case 1 (normal N={n}): empirical CVaR_95={result['cvar']:.4f} vs "
        f"analytical={analytical_cvar95:.4f}, rel_err={rel_err:.3f} > 0.05"
    )

# --- Case 2: known small integer case ---
daily_pnl = -np.arange(1, 101, dtype=float)  # pnl = [-1, -2, ..., -100] -> losses = [1..100]
result2 = historical_cvar(daily_pnl, 0.95)
losses = np.arange(1, 101, dtype=float)
expected_var = float(np.quantile(losses, 0.95))
expected_tail = losses[losses >= expected_var]
expected_cvar = float(expected_tail.mean())
if abs(result2["var"] - expected_var) > 1e-6 or abs(result2["cvar"] - expected_cvar) > 1e-6:
    failures.append(
        f"Case 2 (integer 1..100 losses): VaR={result2['var']} (expected {expected_var}), "
        f"CVaR={result2['cvar']} (expected {expected_cvar})"
    )

# --- Case 3: all-profitable days, no tail loss ---
all_profit = rng.uniform(10, 100, size=50)  # pnl always positive -> losses always negative
result3 = historical_cvar(all_profit, 0.95)
if result3["var"] >= 0 or result3["cvar"] >= 0:
    failures.append(
        f"Case 3 (all-profitable days): expected VaR and CVaR both negative "
        f"(no tail loss), got VaR={result3['var']}, CVaR={result3['cvar']}"
    )

if failures:
    print("FAILURES:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All cvar.py checks passed.")
print(f"  Case 1: empirical CVaR_95={result['cvar']:.4f} vs analytical={analytical_cvar95:.4f} "
      f"(rel_err={rel_err:.4f})")
print(f"  Case 2: VaR={result2['var']}, CVaR={result2['cvar']}")
print(f"  Case 3: VaR={result3['var']:.2f}, CVaR={result3['cvar']:.2f} (both negative, no tail loss)")
