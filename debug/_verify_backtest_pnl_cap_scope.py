"""
Regression test for code-review B5 (confirmed 2026-09-26, fixed 2026-10-03, bug recheck T14.4): BacktestEngine's
P&L-cap running total (`_pair_pnl`) was keyed by pair only and never reset, so one run's P&L carried into the next
run of the same pair (another timeframe; before B4, the other hedge method) -- a later run could be gated by P&L
it had not earned yet. Fix: the running total is per run (pair, timeframe, hedge method) and starts at zero.
Also (found while fixing): since B2/B3 the cap budget (from in-sample trades) is in DOLLARS while the engine's
running total is in spread units, so `--pnl-cap` now requires `--legacy-pnl` (checked in main(); here: source).
Checks:
  1. with a tiny cap (1e-6) already reached by a first 1D run, a second run of the same pair at 1h still trades
     (identical to a fresh engine's 1h run);
  2. within ONE run the cap still works: a 1e-6 cap stops entries after the first closed trade with P&L >= 0;
  3. backtest.py refuses --pnl-cap without --legacy-pnl (source check).
Run: python debug/_verify_backtest_pnl_cap_scope.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from backtest import BacktestEngine, RegimeConditioner, MLConditioner
from config import Config

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def tri(n, period=40, amp=3.5):
    t = np.arange(n) % period
    h = period / 2.0
    return np.where(t < h, -1 + 2 * t / h, 3 - 2 * t / h) * amp


def sdf(ts, hl=20.0):
    z = tri(len(ts))
    n = len(ts)
    return pd.DataFrame({"spread": z * 0.5, "z_rolling": z, "z_expanding": z, "half_life_rolling": np.full(n, hl),
                         "gap_flag_a": np.zeros(n, "int8"), "gap_flag_b": np.zeros(n, "int8"),
                         "hedge_ratio_ols_t": np.ones(n), "hedge_ratio_kalman_t": np.ones(n)}, index=ts)


def row(tf):
    return pd.Series({"symbol_a": "SYNA", "symbol_b": "SYNB", "tf_label": tf, "hedge_ratio_ols": 1.0,
                      "hedge_ratio_kalman_mean": 1.0, "hurst_rs": 0.4, "coint_fraction_rolling": 0.5,
                      "half_life_trend_slope": 0.0, "mean_reversion_speed": 0.1})


def eng(cap):
    return BacktestEngine(cfg=Config.BACKTEST, regime_cond=RegimeConditioner(enabled=False),
                          ml_cond=MLConditioner(enabled=False), storm_flags={}, mm_hedge_map={},
                          pnl_cap_by_pair={"SYNA/SYNB": cap})


def main():
    d1 = pd.bdate_range("2020-01-02", periods=400)
    days = pd.bdate_range("2024-01-02", periods=60)
    h1 = pd.DatetimeIndex([pd.Timestamp(f"{d.date()} {h}") for d in days
                           for h in ("09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30")])
    huge = 1e18
    fresh_1h = eng(huge).run(row("1h"), sdf(h1), "ols")
    e = eng(1e-6)
    first = e.run(row("1D"), sdf(d1), "ols")
    second = e.run(row("1h"), sdf(h1), "ols")
    capped_alone = eng(1e-6).run(row("1h"), sdf(h1), "ols")
    check("1.second_run_not_gated_by_first", len(second) == len(capped_alone) and len(second) > 0,
          f"first(1D)={len(first)} trades, sum P&L {sum(t.pnl_net for t in first):.2f}; second(1h)={len(second)} "
          f"vs same run on a fresh engine={len(capped_alone)}")
    check("2.cap_still_works_within_run", 0 < len(capped_alone) < len(fresh_1h),
          f"capped={len(capped_alone)} uncapped={len(fresh_1h)}")
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtest.py"),
               encoding="utf-8").read()
    check("3.pnl_cap_requires_legacy", "--pnl-cap requires --legacy-pnl" in src)
    # 4 (T14.7 review): thresholds refuse dollar-basis trades (a default run writes the file they read)
    import backtest as _bt
    t = pd.DataFrame({"symbol_a": ["A"], "symbol_b": ["B"], "pnl_net": [5.0], "pnl_basis": ["dollar"]})
    try:
        _bt.compute_pnl_cap_thresholds(trades_df=t); check("4.thresholds_refuse_dollar_basis", False)
    except ValueError:
        check("4.thresholds_refuse_dollar_basis", True)
    ok_legacy = _bt.compute_pnl_cap_thresholds(trades_df=t.assign(pnl_basis="legacy_known_wrong"))
    check("4b.legacy_basis_accepted", ok_legacy == {"A/B": 5.0}, str(ok_legacy))
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
