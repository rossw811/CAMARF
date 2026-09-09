"""
debug/_verify_asset_volatility_profile.py -- synthetic checks for
research/asset_volatility_profile.py's compute_volatility_profile(), BEFORE trusting it against
real cached price data.

Run: python debug/_verify_asset_volatility_profile.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.asset_volatility_profile import compute_volatility_profile

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


print("Check 1: a series too short for even the short window returns all-NaN fields "
      "(not a crash, not a fabricated 0)")
short_series = pd.Series(np.linspace(100, 101, 10),
                          index=pd.date_range("2024-01-01", periods=10, freq="D"))
r1 = compute_volatility_profile(short_series, short_window=21)
check("current_vol_short is NaN for a too-short series", np.isnan(r1["current_vol_short"]))
check("n_bars still correctly reports the real (short) length", r1["n_bars"] == 10)

print("Check 2: None input returns all-NaN with n_bars=0, not a crash")
r2 = compute_volatility_profile(None)
check("None input handled gracefully", np.isnan(r2["current_vol_short"]) and r2["n_bars"] == 0)

print("Check 3: a KNOWN constant-volatility synthetic series produces a current_vol_short close "
      "to the injected annualized volatility (sanity check on realized_vol_proxy reuse)")
rng = np.random.default_rng(0)
n = 400
true_daily_vol = 0.02
log_rets = rng.normal(0, true_daily_vol, n)
prices = pd.Series(100 * np.exp(np.cumsum(log_rets)),
                    index=pd.date_range("2023-01-01", periods=n, freq="D"))
r3 = compute_volatility_profile(prices, short_window=21, long_window=63)
expected_annualized = true_daily_vol * np.sqrt(252)
check(f"current_vol_short ({r3['current_vol_short']:.4f}) is close to the injected annualized "
      f"vol ({expected_annualized:.4f}) within a reasonable sampling-noise band",
      abs(r3["current_vol_short"] - expected_annualized) < 0.15)

print("Check 4: avg_daily_abs_return is a real, positive, unannualized figure -- materially "
      "smaller in magnitude than the annualized vol figures (sanity check they're not "
      "accidentally the same computation)")
check(f"avg_daily_abs_return ({r3['avg_daily_abs_return']:.5f}) is much smaller than "
      f"current_vol_short ({r3['current_vol_short']:.4f}) -- confirms it's genuinely "
      f"unannualized, not a duplicate of the annualized figure",
      r3["avg_daily_abs_return"] < r3["current_vol_short"] / 5)

print("Check 5: vol_percentile -- a symbol whose CURRENT vol is a deliberate, sharp spike above "
      "its own recent history lands near the top of its own percentile distribution")
calm_rets = rng.normal(0, 0.01, 300)
spike_rets = rng.normal(0, 0.08, 30)  # sharp recent vol spike, 8x the calm period's daily vol
combined_rets = np.concatenate([calm_rets, spike_rets])
prices5 = pd.Series(100 * np.exp(np.cumsum(combined_rets)),
                     index=pd.date_range("2023-01-01", periods=len(combined_rets), freq="D"))
r5 = compute_volatility_profile(prices5, short_window=21, long_window=63, percentile_lookback=252)
check(f"vol_percentile ({r5['vol_percentile']:.3f}) is high (>0.8), correctly flagging the "
      f"current window as unusually volatile relative to its own history",
      r5["vol_percentile"] > 0.8)

print("Check 6: vol_percentile -- a symbol with insufficient history for a real percentile "
      "(fewer than 20 valid rolling-vol observations) returns NaN, not a fabricated percentile "
      "computed from too few points")
medium_series = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 25))),
                           index=pd.date_range("2023-01-01", periods=25, freq="D"))
r6 = compute_volatility_profile(medium_series, short_window=21)
check("too few rolling-vol observations -> vol_percentile is NaN", np.isnan(r6["vol_percentile"]))

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
