"""
Edge accounting (docs/EDGE_ACCOUNTING_DESIGN_2026-10-25.md, Ross 2026-10-25). Checks:
  1. pnl_dollar.add_dollar_pnl(check_holes=False) prices a trade across an 810-day leg hole (status ok, finite P&L,
     the BUG-D119 behaviour the "error present" cells need); the default still gives unrealizable_gap
  2. cell_returns: one trade universe for all cells (dollar-priceable apart from holes); X corrected drops the hole
     trade; P old uses pnl_net / n_shares_a / (1 + |beta|), P corrected pnl_dollar_net / notional_dollar_entry;
     excluded trades are counted
  3. shapley: exact per-factor effects on an additive function; efficiency (sum = v(all corrected) - v(all old)) and
     symmetry on an interacting one
  4. joint bootstrap: the same day indices for every cell (identical columns -> identical draws)
  5. backtest.SPREAD_ROOT moves the spread path (default unchanged); the whole-history arm never writes output/results
  6. clean_pool_identity_pairs.clean_pool exists (the PIT pools' cleaning, reusable for the whole-history pool)
Run: python debug/_verify_edge_accounting.py
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import pnl_dollar  # noqa: E402


def series(drop=()):
    idx = pd.bdate_range("2019-01-01", "2026-06-30")
    px = pd.Series(np.linspace(10, 20, len(idx)), index=idx)
    for a, b in drop:
        px = px[(px.index < pd.Timestamp(a)) | (px.index > pd.Timestamp(b))]
    f = pd.DataFrame({"close": px, "tr": px})
    f.attrs["usd"] = True
    return f


A, B = series(), series(drop=[("2023-09-29", "2025-12-16")])
t = pd.DataFrame([{"symbol_a": "A", "symbol_b": "B", "tf": "1D", "hedge_ratio": 1.0, "side": "long",
                   "entry_time": pd.Timestamp("2023-03-01"), "exit_time": pd.Timestamp("2025-12-17"), "n_shares_a": 100}])
pnl_dollar._cache.clear()
d0 = pnl_dollar.add_dollar_pnl(t, price_loader={"A": A, "B": B}.get).iloc[0]
try:
    d1 = pnl_dollar.add_dollar_pnl(t, price_loader={"A": A, "B": B}.get, check_holes=False).iloc[0]
    ok1 = d1["pnl_dollar_status"] == "ok" and np.isfinite(d1["pnl_dollar_net"])
    det = f"default {d0['pnl_dollar_status']}, check_holes=False {d1['pnl_dollar_status']} {d1['pnl_dollar_net']:.1f}"
except TypeError as e:
    ok1, det = False, f"{e}"
check("1 check_holes=False prices across the hole; default unchanged", ok1 and d0["pnl_dollar_status"] == "unrealizable_gap", det)

try:
    import edge_accounting as ea
except ImportError as e:
    check("edge_accounting importable", False, str(e))
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1)

T = pd.DataFrame({
    "exit_time": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]),
    "pnl_net": [2.0, -1.0, 4.0, 3.0], "n_shares_a": [10, 10, 10, 10], "hedge_ratio": [1.0, 1.0, -3.0, 1.0],
    "status_holes": ["ok", "ok", "unrealizable_gap", "missing_price"],
    "status_noholes": ["ok", "ok", "ok", "missing_price"],
    "pnl_dollar_net": [50.0, -20.0, 300.0, np.nan], "notional_dollar_entry": [1000.0, 1000.0, 2000.0, np.nan]})
c00 = ea.cell_returns(T, p_corrected=False, x_corrected=False)
c11 = ea.cell_returns(T, p_corrected=True, x_corrected=True)
c01 = ea.cell_returns(T, p_corrected=False, x_corrected=True)
check("2 cell rules: universe, X drop, P formulas, excluded count",
      np.allclose(c00["ret"], [0.1, -0.05, 0.1]) and np.allclose(c11["ret"], [0.05, -0.02]) and len(c01) == 2
      and ea.n_excluded(T) == 1, f"{c00['ret'].tolist()} {c11['ret'].tolist()} {len(c01)} {ea.n_excluded(T)}")

add = {(s, p, x): 1.0 * s + 2.0 * p + 3.0 * x for s in (0, 1) for p in (0, 1) for x in (0, 1)}
sh = ea.shapley(add)
g = np.random.default_rng(1)
rnd = {k: float(g.normal()) for k in add}
shr = ea.shapley(rnd)
sym = {k: (1.0 if k[0] or k[1] else 0.0) for k in add}          # S and P interchangeable
shs = ea.shapley(sym)
check("3 shapley: additive exact, efficiency, symmetry",
      np.allclose([sh["S"], sh["P"], sh["X"]], [1, 2, 3])
      and np.isclose(sum(shr.values()), rnd[(1, 1, 1)] - rnd[(0, 0, 0)]) and np.isclose(shs["S"], shs["P"]),
      f"{sh} {sum(shr.values()):.4f} vs {rnd[(1, 1, 1)] - rnd[(0, 0, 0)]:.4f} {shs}")

x = g.normal(size=500)
M = np.column_stack([x, x, g.normal(size=500)])
D = ea.joint_bootstrap_sharpes(M, block=10, reps=50, seed=3)
check("4 joint bootstrap: same indices across cells", D.shape == (50, 3) and np.allclose(D[:, 0], D[:, 1])
      and not np.allclose(D[:, 0], D[:, 2]), str(D.shape))

import backtest as bt  # noqa: E402
p_default = bt._spread_path("daily", "X", "Y")
old = bt.SPREAD_ROOT
bt.SPREAD_ROOT = "output/results_wholehistory"
p_moved = bt._spread_path("daily", "X", "Y")
bt.SPREAD_ROOT = old
check("5 SPREAD_ROOT moves the spread path; whole-history root is not output/results",
      p_default == "output/results/daily/spread_series_X_Y.parquet"
      and p_moved == "output/results_wholehistory/daily/spread_series_X_Y.parquet"
      and os.path.normpath(ea.WH_RESULTS) != os.path.normpath(os.path.join(ROOT, "output", "results")),
      f"{p_default} {p_moved} {ea.WH_RESULTS}")

import clean_pool_identity_pairs as cpi  # noqa: E402
check("6 clean_pool reusable", callable(getattr(cpi, "clean_pool", None)))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
