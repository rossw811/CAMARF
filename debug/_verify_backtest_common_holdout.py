"""
Regression test for code-review B8 (confirmed 2026-09-26; comparison arm built 2026-10-04 per Ross: "one common
calendar date"): the holdout was the last 20% of EACH pair's own bars, so pairs with different histories had
different cutoffs and weights fitted on in-sample trades pooled across pairs used dates that were already
out-of-sample for other pairs. Arm: `--holdout-mode common_date` -> BacktestEngine(holdout_date=...) cuts every pair
at one date, `common_holdout_date` = the date with HOLDOUT_PCT of the pooled sample after it.
Checks (pair A 2010-2020, pair B 2016-2020, triangle-wave signals):
  1. per-pair rule REPRODUCES the leak: the latest in-sample trade exit (any pair) is after the earliest holdout
     trade entry (any pair);
  2. common date: every in-sample trade exits before the cutoff and every holdout trade enters on/after it;
  3. common_holdout_date returns the pooled quantile PER TIMEFRAME, {tf_label: date} -- pooling bars across
     timeframes let dense intraday bars set the daily cutoff (independent T14.7 review, 2026-10-04: no --tf gave a
     2026-06-17 cutoff and 0% holdout for every 1D pair); the engine uses the date of the pair's own timeframe.
Run: python debug/_verify_backtest_common_holdout.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest as _bt_basis  # 2026-10-07: BacktestEngine.run converts to dollar P&L; this test checks the event
_bt_basis.apply_pnl_basis = lambda trades, legacy=False, cfg=None: (trades, {})  # loop on synthetic symbols with no
# price files (the conversion would drop every trade). P&L basis is covered by _verify_engine_dollar_default.py.

from types import SimpleNamespace

import numpy as np
import pandas as pd

import backtest as bt
from config import Config

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def sdf(idx):
    t = np.arange(len(idx)) % 40
    z = np.where(t < 20, -1 + t / 10, 3 - t / 10) * 3.5
    n = len(idx)
    return pd.DataFrame({"spread": z * 0.5, "z_rolling": z, "z_expanding": z, "half_life_rolling": np.full(n, 20.0),
                         "gap_flag_a": np.zeros(n, "int8"), "gap_flag_b": np.zeros(n, "int8"),
                         "hedge_ratio_ols_t": np.ones(n), "hedge_ratio_kalman_t": np.ones(n)}, index=idx)


def row(a, b):
    return pd.Series({"symbol_a": a, "symbol_b": b, "tf_label": "1D", "hedge_ratio_ols": 1.0,
                      "hedge_ratio_kalman_mean": 1.0, "hurst_rs": 0.4, "coint_fraction_rolling": 0.5,
                      "half_life_trend_slope": 0.0, "mean_reversion_speed": 0.1})


def eng(date=None):
    date = {"1D": date} if date is not None and not isinstance(date, dict) else date
    return bt.BacktestEngine(cfg=Config.BACKTEST, regime_cond=bt.RegimeConditioner(enabled=False),
                             ml_cond=bt.MLConditioner(enabled=False), storm_flags={}, mm_hedge_map={}, holdout_date=date)


def leak(e, data):
    is_exit = max(pd.Timestamp(t.exit_time) for k, d in data.items() for t in e.run(row(*k), d, "ols", is_only=True))
    oos_entry = min(pd.Timestamp(t.entry_time) for k, d in data.items() for t in e.run(row(*k), d, "ols", holdout_only=True))
    return is_exit, oos_entry


def main():
    data = {("A1", "A2"): sdf(pd.bdate_range("2010-01-04", "2020-12-31")),
            ("B1", "B2"): sdf(pd.bdate_range("2016-01-04", "2020-12-31"))}
    is_exit, oos_entry = leak(eng(), data)
    check("1.per_pair_rule_leaks", is_exit > oos_entry, f"latest IS exit {is_exit.date()} > earliest OOS entry {oos_entry.date()}")
    if not hasattr(bt, "common_holdout_date"):
        check("2.common_date_exists", False); return finish()
    pooled = np.sort(np.concatenate([d.index.as_unit("ns").asi8 for d in data.values()]))
    cut = pd.Timestamp(pooled[int(np.floor(len(pooled) * (1 - Config.BACKTEST.HOLDOUT_PCT)))])
    is_exit2, oos_entry2 = leak(eng(cut), data)
    check("2.common_date_no_leak", is_exit2 < cut <= oos_entry2,
          f"cut {cut.date()}: latest IS exit {is_exit2.date()}, earliest OOS entry {oos_entry2.date()}")
    orig = (bt._pairs_for_tf, bt._load_spread, bt._TF_DIRS)
    try:
        hourly = sdf(pd.date_range("2026-01-05 09:30", periods=20000, freq="h"))     # dense, recent
        bt._TF_DIRS = [("1day", "1D"), ("1hr", "1h")]
        bt._pairs_for_tf = lambda tf_dir, tf_label, ov, log_pairs=False: (
            pd.DataFrame([{"symbol_a": a, "symbol_b": b} for a, b in data]) if tf_label == "1D"
            else pd.DataFrame([{"symbol_a": "H1", "symbol_b": "H2"}]))
        bt._load_spread = lambda tf_dir, a, b: data[(a, b)] if tf_dir == "1day" else hourly
        got = bt.common_holdout_date(SimpleNamespace(tf=None), None, Config.BACKTEST.HOLDOUT_PCT)
    finally:
        bt._pairs_for_tf, bt._load_spread, bt._TF_DIRS = orig
    check("3.pooled_quantile_per_tf", isinstance(got, dict) and got.get("1D") == cut and got.get("1h") is not None
          and got["1h"] > pd.Timestamp("2026-01-05"), f"got {got} expected 1D={cut}")
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
