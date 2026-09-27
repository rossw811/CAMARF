"""
Synthetic checks for research/meta_label_capital_sim.py (2026-09-27).

1. features_at_entry reads the entry bar exactly (hand values), incl. 5-bar z velocity and hedge drift.
2. Planted signal: trade profitability is determined by one feature (coint_fraction_rolling > 0.5 ->
   +$100, else -$100). A working pipeline must (a) reach a high meta-label AUC and (b) produce a
   filtered replay Sharpe ABOVE the unfiltered one. A pure-noise score must not reach high AUC.
   The capital replay is replaced by an unconstrained Sharpe stand-in (injectable `replay`) so the
   test isolates the split/scoring/admission logic from price data.

Run: python debug/_verify_meta_label_capital_sim.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.meta_label_capital_sim import FEATURES, evaluate, features_at_entry

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def test_features():
    idx = pd.bdate_range("2026-01-01", periods=10)
    sp = pd.DataFrame({"z_rolling": np.arange(10, dtype=float), "half_life_rolling": 7.0,
                       "hedge_ratio_ols_t": 2.0, "hedge_ratio_kalman_t": 1.5, "hurst_rs_t": 0.4,
                       "coint_fraction_rolling_t": 0.6, "half_life_trend_slope_t": 0.1,
                       "mean_reversion_speed_t": 0.2, "squeeze_indicator_a_t": 0.9,
                       "squeeze_indicator_b_t": 1.2, "rsi_diff_velocity_t": -0.3}, index=idx)
    f = features_at_entry(sp, idx[7])
    check("feat.zscore", f["zscore"] == 7.0)
    check("feat.zvel_5bar", f["zscore_velocity"] == 5.0, f"{f['zscore_velocity']}")
    check("feat.hedge_drift", abs(f["hedge_ratio_drift"] - 0.25) < 1e-12)
    check("feat.squeeze_min", f["squeeze_min"] == 0.9)
    check("feat.missing_bar_empty", features_at_entry(sp, pd.Timestamp("2030-01-01")) == {})


def _identity_models():
    from sklearn.linear_model import LogisticRegression
    return {"logreg": (LogisticRegression(max_iter=1000), True, False)}


def test_planted_signal():
    import portfolio_math as pm
    rng = np.random.default_rng(0)
    n = 3000
    entry = pd.Timestamp("2010-01-04") + pd.to_timedelta(np.sort(rng.integers(0, 3000, n)), "D")
    ds = pd.DataFrame({c: rng.normal(size=n) for c in FEATURES})
    ds["coint_fraction_rolling"] = rng.uniform(0, 1, n)
    ds["pnl_dollar_net"] = np.where(ds["coint_fraction_rolling"] > 0.5, 100.0, -100.0)
    ds["entry_time"] = entry
    ds["exit_time"] = entry + pd.Timedelta(days=3)
    ds["label_end_time"] = ds["exit_time"]
    ds["y"] = (ds["pnl_dollar_net"] > 0).astype(int)
    stand_in = lambda df: (pm.sharpe_from_trades(df, "pnl_dollar_net") if len(df) else float("nan"), len(df))
    r = evaluate(ds, _identity_models(), replay=stand_in).iloc[0]
    check("planted.auc_high", r["meta_auc"] > 0.95, f"auc={r['meta_auc']:.3f}")
    check("planted.filtered_beats_all", r["capsim_sharpe_filtered"] > r["capsim_sharpe_all"],
          f"filtered={r['capsim_sharpe_filtered']:.2f} all={r['capsim_sharpe_all']:.2f}")
    ds2 = ds.copy()
    ds2["coint_fraction_rolling"] = rng.uniform(0, 1, n)  # break the link: pure noise
    r2 = evaluate(ds2, _identity_models(), replay=stand_in).iloc[0]
    check("noise.auc_near_half", abs(r2["meta_auc"] - 0.5) < 0.06, f"auc={r2['meta_auc']:.3f}")


if __name__ == "__main__":
    test_features()
    test_planted_signal()
    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
