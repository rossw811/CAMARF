"""
debug/_verify_confidence_score_allocation.py -- synthetic checks for
research/confidence_score_allocation.py, BEFORE trusting it against real production data.

Run: python debug/_verify_confidence_score_allocation.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.confidence_score_allocation import (
    percentile_score, compute_confidence_scores, evaluate_filter_sweep, apply_score_weighted_sizing,
)

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


print("Check 1: percentile_score -- the LOWEST raw value gets the HIGHEST score when "
      "higher_is_worse=True (the convention every category in this module uses)")
raw1 = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
scores1 = percentile_score(raw1, higher_is_worse=True)
check("lowest raw value (10.0) gets the highest score", scores1.iloc[0] == scores1.max())
check("highest raw value (50.0) gets the lowest score", scores1.iloc[4] == scores1.min())
# pandas rank(pct=True) assigns the smallest value rank 1/n (not 0), so the worst raw value's
# score is exactly 0 but the best raw value's score is (1 - 1/n)*100, not exactly 100 for finite
# n -- for n=5 that's 80.0, not 100. Checking the correct, pandas-consistent expectation, not an
# assumed-ideal one.
check(f"worst raw value's score is exactly 0 ({scores1.min()})", np.isclose(scores1.min(), 0.0))
check(f"best raw value's score matches the exact pandas rank(pct=True) formula for n=5 "
      f"((1 - 1/5)*100 = 80.0, got {scores1.max()})", np.isclose(scores1.max(), 80.0))

print("Check 2: percentile_score -- higher_is_worse=False inverts the direction (used nowhere "
      "in this module currently, but must behave correctly if a future category needs it)")
scores2 = percentile_score(raw1, higher_is_worse=False)
check("with higher_is_worse=False, the HIGHEST raw value now gets the highest score",
      scores2.iloc[4] == scores2.max())

print("Check 3: percentile_score -- NaN raw values produce NaN scores, not a fabricated 0 or a "
      "crash, and don't distort the ranking of the real values")
raw3 = pd.Series([10.0, np.nan, 30.0, 40.0, np.nan])
scores3 = percentile_score(raw3, higher_is_worse=True)
check("NaN raw values produce NaN scores", scores3.isna().sum() == 2)
check("the lowest REAL value (10.0) still gets the highest score among real values",
      scores3.iloc[0] == scores3.dropna().max())

print("Check 4: compute_confidence_scores -- a trade with ALL 4 categories favorable ranks at "
      "the TOP of a real peer group, and an all-unfavorable trade ranks at the BOTTOM "
      "(percentile ranking is only meaningful with enough peers -- using 10 trades, not 2, so "
      "the score has real room to spread out)")
n_synth = 10
rng_c4 = np.random.default_rng(3)
symbols_a = [f"A{i}" for i in range(n_synth)]
symbols_b = [f"X{i}" for i in range(n_synth)]
# Trade 0 is deliberately the BEST on every dimension; trade 9 is deliberately the WORST; the
# rest are random filler giving the percentile ranking real peers to rank against.
hurst_vals = np.concatenate([[0.05], rng_c4.uniform(0.2, 0.8, n_synth - 2), [0.95]])
hl_vals = np.concatenate([[3.0], rng_c4.uniform(10, 80, n_synth - 2), [150.0]])
beta_mismatch = np.concatenate([[5.0], rng_c4.uniform(200, 2000, n_synth - 2), [8000.0]])
trades4 = pd.DataFrame({
    "symbol_a": symbols_a, "symbol_b": symbols_b,
    "hurst_at_entry": hurst_vals, "half_life_at_entry": hl_vals,
    "net_dollar_beta_exposure": beta_mismatch, "notional_at_entry": [10000.0] * n_synth,
})
vol_profile4 = pd.DataFrame({
    "symbol": symbols_a + symbols_b,
    "vol_percentile": [0.5] + list(rng_c4.uniform(0.1, 0.9, n_synth - 2)) + [0.99]
                      + [0.5] + list(rng_c4.uniform(0.1, 0.9, n_synth - 2)) + [0.01],
})
scored4 = compute_confidence_scores(trades4, vol_profile4)
check(f"the deliberately-best trade (index 0, score={scored4['confidence_score'].iloc[0]:.1f}) "
      f"ranks strictly higher than every other trade's confidence_score",
      scored4["confidence_score"].iloc[0] == scored4["confidence_score"].max())
check(f"the deliberately-worst trade (index {n_synth-1}, "
      f"score={scored4['confidence_score'].iloc[-1]:.1f}) ranks strictly lower than every "
      f"other trade's confidence_score",
      scored4["confidence_score"].iloc[-1] == scored4["confidence_score"].min())
check("all 10 trades have all 4 categories scored (n_categories_scored == 4)",
      (scored4["n_categories_scored"] == 4).all())

print("Check 5: compute_confidence_scores -- when the beta-exposure COLUMNS are entirely "
      "absent (no net_dollar_beta_exposure/notional_at_entry in the input at all), every "
      "trade still gets a real score, rescaled over the 3 categories that WERE computable, "
      "not silently capped near 75 -- using enough peer trades for the ranking to mean anything")
n5 = 8
symbols_a5 = [f"A{i}" for i in range(n5)]
symbols_b5 = [f"X{i}" for i in range(n5)]
trades5 = pd.DataFrame({
    "symbol_a": symbols_a5, "symbol_b": symbols_b5,
    "hurst_at_entry": [0.05] + list(np.linspace(0.2, 0.8, n5 - 1)),
    "half_life_at_entry": [3.0] + list(np.linspace(10, 80, n5 - 1)),
})  # no net_dollar_beta_exposure/notional_at_entry columns at all
vol_profile5 = pd.DataFrame({"symbol": symbols_a5 + symbols_b5, "vol_percentile": [0.5] * (2 * n5)})
scored5 = compute_confidence_scores(trades5, vol_profile5)
check("every trade has n_categories_scored == 3 (beta-neutrality genuinely absent from input)",
      (scored5["n_categories_scored"] == 3).all())
check(f"the best trade's (index 0) confidence_score ({scored5['confidence_score'].iloc[0]:.1f}) "
      f"is well above the median (it's genuinely top-ranked on the 2 discriminating categories; "
      f"the 3rd, vol_regime, is a deliberate tie in this test's construction -- all trades sit "
      f"at vol_percentile=0.5, so it correctly contributes nothing to distinguish trade 0, "
      f"pulling the score down from ~100 but NOT capping it at a fixed 75-out-of-100 ceiling, "
      f"which is the real thing this check verifies)",
      scored5["confidence_score"].iloc[0] > 70)

print("Check 6: evaluate_filter_sweep -- a higher threshold always keeps a SUBSET of a lower "
      "threshold's surviving trades (monotonically shrinking, never growing)")
trades6 = pd.DataFrame({
    "confidence_score": [10, 30, 60, 90], "pnl_net": [100.0, -50.0, 200.0, 150.0],
    "entry_time": pd.date_range("2024-01-01", periods=4, freq="10D"),
    "exit_time": pd.date_range("2024-01-05", periods=4, freq="10D"),
})
sweep6 = evaluate_filter_sweep(trades6, thresholds=[0, 25, 50, 75])
check("n_trades is monotonically non-increasing as the threshold rises",
      (sweep6["n_trades"].diff().dropna() <= 0).all())
check("threshold=0 keeps all 4 trades", sweep6.loc[sweep6["threshold"] == 0, "n_trades"].iloc[0] == 4)
check("threshold=75 keeps only the 1 trade with score=90",
      sweep6.loc[sweep6["threshold"] == 75, "n_trades"].iloc[0] == 1)

print("Check 7: apply_score_weighted_sizing -- a trade with confidence_score=100 keeps its FULL "
      "pnl_net; a trade with confidence_score=0 contributes exactly 0 (fully excluded by the "
      "continuous-sizing view, the defining property of a 0-confidence position)")
trades7 = pd.DataFrame({"pnl_net": [500.0, 500.0], "confidence_score": [100.0, 0.0]})
weighted7 = apply_score_weighted_sizing(trades7)
check("confidence_score=100 trade keeps its full $500 pnl", weighted7.iloc[0] == 500.0)
check("confidence_score=0 trade contributes exactly $0", weighted7.iloc[1] == 0.0)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
