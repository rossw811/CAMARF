"""
D10 / R5.8 (Ross 2026-10-12: stationary block bootstrap of daily P&L including zeros, block length by Politis-White
automatic selection; correct the label) for research/pit_wfa_trade_bootstrap.py.
Before: iid resampling of days (destroys serial dependence); all-zero draws gave std 0 -> NaN -> silently dropped by
np.nanpercentile (fold2_roll had 5 non-zero days, so many draws were all-zero and the CI described only the rest);
the daily series was zero-filled only between the first and last exit, not over the fold's test window (R5.1); the log
said "resampling N trades" while it resampled days.
Checks:
  1. block length (Politis-White, stationary): persistent series -> long blocks; iid -> ~1;
  2. zero-inflated series: every draw is kept (n_boot finite Sharpes; all-zero draws counted, Sharpe 0 by
     definition: no P&L), none dropped;
  3. the stationary bootstrap keeps serial dependence (mean lag-1 autocorrelation of draws of an AR(1) .8 series > .5);
  4. the daily series spans the whole test window when start/end are given (edge no-trade days are zeros);
  5. reproduces the point estimate's formula on the un-resampled series (Sharpe = mean/std*sqrt(252)).
Run: python debug/_verify_pit_wfa_bootstrap_d10.py
"""
import os
import sys
from types import SimpleNamespace

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "research"))

import numpy as np
import pandas as pd

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def ar1(n, rho, rng):
    e = rng.normal(0, 1, n)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = rho * x[t - 1] + e[t]
    return x


def main():
    try:
        import pit_wfa_trade_bootstrap as mod
        rng = np.random.default_rng(0)
        L_ar = mod.politis_white_block_length(ar1(1000, 0.8, rng))
        L_iid = mod.politis_white_block_length(rng.normal(0, 1, 1000))
        check("block_length_persistent_longer", L_ar > 5 and L_iid < 3, f"AR(.8) {L_ar:.2f}, iid {L_iid:.2f}")

        z = np.zeros(250)
        z[[10, 50, 90, 130, 170]] = [1.0, -0.5, 2.0, 0.3, -1.0]
        r = mod.stationary_bootstrap_sharpe(z, n_boot=2000, rng=np.random.default_rng(1))
        check("zero_inflated_no_draw_dropped", len(r["sharpes"]) == 2000 and np.isfinite(r["sharpes"]).all(),
              f"{np.isfinite(r['sharpes']).sum()}/2000 finite, {r['n_degenerate_draws']} all-zero draws")
        check("all_zero_draws_counted", r["n_degenerate_draws"] > 0 and np.sum(r["sharpes"] == 0) >= r["n_degenerate_draws"],
              f"{r['n_degenerate_draws']}")

        x = ar1(500, 0.8, np.random.default_rng(2))
        r2 = mod.stationary_bootstrap_sharpe(x, n_boot=300, rng=np.random.default_rng(3), return_draws=True)
        ac = np.mean([np.corrcoef(d[1:], d[:-1])[0, 1] for d in r2["draws"]])
        check("serial_dependence_kept", ac > 0.5, f"mean lag-1 autocorr of draws {ac:.3f} (series ~0.8)")

        trades = [SimpleNamespace(entry_time=pd.Timestamp("2024-03-04"), exit_time=pd.Timestamp("2024-03-05"), pnl_net=10.0),
                  SimpleNamespace(entry_time=pd.Timestamp("2024-03-11"), exit_time=pd.Timestamp("2024-03-12"), pnl_net=-4.0)]
        d = mod._daily_pnl_series(trades, start="2024-03-01", end="2024-03-29")
        check("window_edges_zero_filled", d.index.min() == pd.Timestamp("2024-03-01")
              and d.index.max() == pd.Timestamp("2024-03-29") and len(d) == 21 and (d != 0).sum() == 2,
              f"{d.index.min().date()}..{d.index.max().date()}, {len(d)} days")
        s = d.to_numpy()
        import portfolio_math
        check("point_formula_matches_production", np.isclose(mod.sharpe_of(s), portfolio_math.sharpe_from_daily_pnl(d)),
              "ddof=1 as portfolio_math.sharpe_from_daily_pnl (the old bootstrap used numpy's ddof=0)")
    except (AttributeError, TypeError) as e:
        check("d10_functions_exist", False, f"{type(e).__name__}: {e}")

    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
