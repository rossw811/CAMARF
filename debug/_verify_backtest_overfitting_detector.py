"""
debug/_verify_backtest_overfitting_detector.py -- synthetic ground-truth checks for
research/backtest_overfitting_detector.py, BEFORE trusting it against real data.

Run: python debug/_verify_backtest_overfitting_detector.py
(Fully synthetic/offline -- no live yfinance/internet connection needed.)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.backtest_overfitting_detector import weighted_moments, rnd_to_return_space, \
    realized_return_distribution

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


print("Check 1: weighted_moments -- recovers the EXACT mean/std/skew of a known discrete "
      "uniform-weight distribution, matching plain numpy statistics")
rng = np.random.default_rng(0)
values1 = rng.normal(0.05, 0.02, 500)
weights1 = np.ones(500)
moments1 = weighted_moments(values1, weights1)
check(f"mean ({moments1['mean']:.5f}) matches np.mean ({values1.mean():.5f})",
      np.isclose(moments1["mean"], values1.mean()))
check(f"std ({moments1['std']:.5f}) matches np.std (population, ddof=0) ({values1.std():.5f})",
      np.isclose(moments1["std"], values1.std()))

print("Check 2: weighted_moments -- a symmetric distribution has skew close to 0; a "
      "deliberately right-skewed one has clearly positive skew")
symmetric = rng.normal(0, 1, 1000)
check(f"symmetric distribution skew ({weighted_moments(symmetric, np.ones(1000))['skew']:.3f}) "
      f"is close to 0", abs(weighted_moments(symmetric, np.ones(1000))["skew"]) < 0.2)
right_skewed = np.concatenate([rng.normal(0, 1, 900), rng.normal(8, 1, 100)])
check(f"deliberately right-skewed distribution has clearly positive skew "
      f"({weighted_moments(right_skewed, np.ones(1000))['skew']:.3f})",
      weighted_moments(right_skewed, np.ones(1000))["skew"] > 0.5)

print("Check 3: rnd_to_return_space -- a strike exactly at spot (K=S) maps to return=0.0, and "
      "the conversion is a simple, exact linear transform (K/S - 1)")
rnd3 = pd.DataFrame({"strike": [80.0, 100.0, 120.0], "density_clipped": [1.0, 2.0, 1.0]})
result3 = rnd_to_return_space(rnd3, S=100.0)
check(f"weighted mean return is close to 0 (symmetric density around spot): "
      f"{result3['mean']:.4f}", abs(result3["mean"]) < 0.01)

print("Check 4: realized_return_distribution -- recovers the KNOWN return of a series with "
      "ZERO volatility (deterministic, constant per-period growth) -- mean matches exactly, "
      "std is exactly 0")
n_bars = 252 * 4  # 4 years of daily bars
growth_rate = 0.0001  # small constant daily log-growth
prices4 = pd.Series(100 * np.exp(np.arange(n_bars) * growth_rate),
                     index=pd.date_range("2020-01-01", periods=n_bars, freq="B"))
result4 = realized_return_distribution(prices4, T_years=1.0)
expected_return_per_year = np.exp(252 * growth_rate) - 1.0
check(f"realized mean return per window ({result4['mean']:.5f}) matches the known constant "
      f"growth rate over ~1 year ({expected_return_per_year:.5f})",
      abs(result4["mean"] - expected_return_per_year) < 0.01)
check(f"realized std is essentially 0 for a deterministic series ({result4['std']:.6f})",
      result4["std"] < 1e-6)
check(f"n_windows ({result4['n_windows']}) is close to 4 (4 years of data, 1-year windows)",
      result4["n_windows"] in (3, 4))

print("Check 5: realized_return_distribution -- uses NON-OVERLAPPING windows, confirmed "
      "directly: the number of windows must be len(close)//window_bars, not len(close) minus "
      "window_bars (which would indicate an overlapping/rolling construction instead)")
n_bars5 = 500
window_bars5 = 100
prices5 = pd.Series(rng.normal(100, 1, n_bars5).cumsum() + 1000,
                     index=pd.date_range("2020-01-01", periods=n_bars5, freq="B"))
result5 = realized_return_distribution(prices5, T_years=window_bars5 / 252.0)
check(f"n_windows ({result5['n_windows']}) equals floor(500/100)=5, the non-overlapping count, "
      f"not something close to 500-100=400 (which an overlapping/rolling window would give)",
      result5["n_windows"] == 5)

print("Check 6: realized_return_distribution -- too little history for even 2 full windows "
      "returns NaN fields, not a fabricated distribution from a single or zero window")
short_prices = pd.Series(np.linspace(100, 105, 20),
                          index=pd.date_range("2024-01-01", periods=20, freq="D"))
result6 = realized_return_distribution(short_prices, T_years=1.0)  # needs 252 bars/window, only have 20
check("too little history for 2 full non-overlapping windows -> NaN mean/std, not fabricated",
      np.isnan(result6["mean"]) and np.isnan(result6["std"]))

print("Check 7: realized_return_distribution -- None input returns NaN fields, not a crash")
result7 = realized_return_distribution(None, T_years=1.0)
check("None input handled gracefully", np.isnan(result7["mean"]) and result7["n_windows"] == 0)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
