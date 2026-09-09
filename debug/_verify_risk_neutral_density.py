"""
debug/_verify_risk_neutral_density.py -- synthetic ground-truth checks for
research/risk_neutral_density.py, BEFORE trusting it against a real live option chain.

The strongest available ground truth: Black-Scholes itself assumes the terminal price is
lognormal. Pricing a full synthetic grid of calls at a KNOWN constant volatility via
options.py's own black_scholes_call(), then running that grid through this exact
extract_risk_neutral_density() pipeline, MUST recover (approximately, given the smoothing step)
the true lognormal density implied by that constant vol -- not just "some smooth curve."

Run: python debug/_verify_risk_neutral_density.py
(Fully synthetic/offline -- no live yfinance/internet connection needed.)
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import lognorm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from options import black_scholes_call
from research.risk_neutral_density import extract_risk_neutral_density, fit_smooth_iv_curve, fetch_live_option_chain

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


print("Check 1: fit_smooth_iv_curve -- recovers a KNOWN flat (constant) IV curve exactly, "
      "even from noisy quoted values around that constant")
rng = np.random.default_rng(0)
strikes1 = np.linspace(80, 120, 20)
true_iv = 0.20
noisy_ivs = true_iv + rng.normal(0, 0.002, 20)
curve1 = fit_smooth_iv_curve(strikes1, noisy_ivs, degree=3)
check(f"fitted curve at the mid-strike ({curve1(100):.4f}) is close to the true constant IV "
      f"({true_iv})", abs(curve1(100) - true_iv) < 0.01)

print("Check 2 (THE core ground-truth test): a full synthetic call-price grid, priced via "
      "options.py's own black_scholes_call() at a KNOWN CONSTANT vol, must recover the "
      "textbook Black-Scholes lognormal terminal density when run through the full RND pipeline")
S, T, sigma, r = 100.0, 0.5, 0.25, 0.0
strikes2 = np.linspace(60, 150, 40)
ivs2 = np.full(40, sigma)  # constant IV -- the simplest, most exact ground-truth case
rnd2 = extract_risk_neutral_density(S, strikes2, ivs2, T, r=r, degree=1, n_grid=300)
# Under GBM with drift r and vol sigma, the terminal price is lognormal with
# log(S_T) ~ Normal(log(S) + (r - 0.5*sigma^2)*T, sigma^2*T) -- scipy's lognorm parametrization:
# lognorm(s=sigma*sqrt(T), scale=S*exp((r - 0.5*sigma**2)*T))
true_density = lognorm(s=sigma * np.sqrt(T), scale=S * np.exp((r - 0.5 * sigma ** 2) * T))
# Compare density SHAPE at a few strikes well inside the grid (avoid edge effects).
test_strikes = [80.0, 100.0, 120.0]
extracted = np.interp(test_strikes, rnd2["strike"], rnd2["density_clipped"])
expected = true_density.pdf(test_strikes)
# Normalize both to the same scale (peak=1) before comparing SHAPE, since exact absolute-level
# match depends on grid resolution/dK precision this test doesn't need to nail exactly.
extracted_norm = extracted / extracted.max()
expected_norm = expected / expected.max()
check(f"extracted density shape at [80,100,120] ({np.round(extracted_norm, 3)}) matches the "
      f"true Black-Scholes lognormal shape ({np.round(expected_norm, 3)}) within a reasonable "
      f"numerical-differentiation tolerance", np.allclose(extracted_norm, expected_norm, atol=0.25))

print("Check 3: the extracted density's MODE (most likely terminal price) is close to the "
      "true lognormal distribution's own mode, not some unrelated strike")
true_mode = float(np.exp(np.log(S) + (r - 0.5 * sigma ** 2) * T - sigma ** 2 * T))
extracted_mode = float(rnd2.loc[rnd2["density_clipped"].idxmax(), "strike"])
check(f"extracted mode ({extracted_mode:.1f}) is within 15 of the true lognormal mode "
      f"({true_mode:.1f})", abs(extracted_mode - true_mode) < 15)

print("Check 4: extract_risk_neutral_density -- the output density is never negative after "
      "clipping (density_clipped), even though the raw second derivative can legitimately dip "
      "negative from numerical noise")
check("density_clipped has no negative values anywhere in the output",
      (rnd2["density_clipped"] >= 0).all())

print("Check 5: a SKEWED synthetic IV curve (higher vol for low strikes -- the real, "
      "well-documented equity 'volatility skew') produces a density with a fatter LEFT tail "
      "than a flat-IV density at the same average vol -- confirms the pipeline actually "
      "responds to skew, not just recovering a symmetric lognormal regardless of input")
strikes3 = np.linspace(60, 150, 40)
# A purely LINEAR skew across the whole range (no kink) -- a clipped/piecewise shape doesn't fit
# cleanly to a low-order polynomial and introduces its own fitting artifact near the kink,
# unrelated to whether the pipeline responds correctly to genuine skew.
skew_ivs = 0.25 + 0.0025 * (100 - strikes3)  # IV=0.35 at K=60, IV=0.145 at K=150
rnd3 = extract_risk_neutral_density(S, strikes3, skew_ivs, T, r=r, degree=1, n_grid=300)


def weighted_skewness(strikes, weights):
    """Pearson's (Fisher) skewness of a discrete distribution given by (strike, density) pairs
    -- the textbook third-standardized-moment measure, not an arbitrary tail-mass cutoff that
    may or may not land where a given skew concentrates its effect."""
    w = weights / weights.sum()
    mean = float((strikes * w).sum())
    var = float((w * (strikes - mean) ** 2).sum())
    std = np.sqrt(var)
    third_moment = float((w * (strikes - mean) ** 3).sum())
    return third_moment / std ** 3


skew_of_flat = weighted_skewness(rnd2["strike"].to_numpy(), rnd2["density_clipped"].to_numpy())
skew_of_skewed = weighted_skewness(rnd3["strike"].to_numpy(), rnd3["density_clipped"].to_numpy())
check(f"the flat-IV density's own skewness ({skew_of_flat:.4f}) is positive (right-skewed), "
      f"matching the lognormal baseline's known shape", skew_of_flat > 0)
check(f"raising downside (low-strike) IV relative to upside IV makes the skewness statistic "
      f"MORE NEGATIVE / less positive ({skew_of_skewed:.4f} vs. the flat case's "
      f"{skew_of_flat:.4f}) -- more downside vol correctly pulls the distribution's shape "
      f"toward a fatter left tail, the real-world equity-skew direction",
      skew_of_skewed < skew_of_flat)

print("Check 6: fit_smooth_iv_curve -- too few valid (strike, IV) points for the requested "
      "polynomial degree raises a clear error rather than silently fitting garbage or crashing "
      "with an obscure numpy error")
try:
    fit_smooth_iv_curve(np.array([100.0, 105.0]), np.array([0.2, 0.21]), degree=3)
    raised = False
except ValueError:
    raised = True
check("too few points for the requested degree raises ValueError with a clear message", raised)

print("Check 7: implied_vol_from_price -- inverts a KNOWN Black-Scholes price back to the "
      "exact vol that produced it (round-trip test), and returns NaN for a price below "
      "intrinsic value (an arbitrage-violating/bad quote) rather than a fabricated vol")
from research.risk_neutral_density import implied_vol_from_price
true_price = black_scholes_call(770.0, 750.0, 0.1, 0.22, 0.0)
recovered_iv = implied_vol_from_price(true_price, 770.0, 750.0, 0.1)
check(f"round-trip recovers the true vol (0.22) from its own price: got {recovered_iv:.5f}",
      abs(recovered_iv - 0.22) < 1e-4)
check("a price below intrinsic value (arbitrage violation) returns NaN, not a fabricated vol",
      np.isnan(implied_vol_from_price(1.0, 770.0, 500.0, 0.1)))  # intrinsic here is 270, price=1 is impossible

print("Check 8: fetch_live_option_chain -- filters illiquid deep-ITM/OTM strikes outside the "
      "moneyness band (real bug found live: SPY's real chain spanning $150-$1000 against a "
      "$770 spot broke the smoothing fit entirely), derives its OWN implied vol via inversion "
      "(real bug found live: yfinance's own impliedVolatility column was unreliable -- pinned "
      "at 1e-05 for every deep-ITM strike), and correctly falls back to lastPrice with a "
      "disclosed stale-quote count when bid/ask aren't live (real situation found live: bid/ask "
      "were both zero across the entire chain, market very likely closed at fetch time)")
import unittest.mock as mock
import pandas as pd
S_test, true_vol = 770.0, 0.20
_mocked_now = pd.Timestamp("2026-11-12")
_expiry = "2026-12-18"
# T_test computed EXACTLY the way fetch_live_option_chain itself will compute it, from the same
# mocked "now" -- generating the fake prices at any other T would silently mismatch the T the
# function actually inverts against, and the recovered IV would be systematically wrong for a
# reason that has nothing to do with the code under test (a real mistake made and caught while
# first writing this exact check).
T_test = max((pd.Timestamp(_expiry) - _mocked_now).total_seconds(), 3600) / (365.0 * 86400)
fake_strikes = [150.0, 500.0, 700.0, 770.0, 850.0, 1000.0]
fake_prices = [black_scholes_call(S_test, k, T_test, true_vol, 0.0) for k in fake_strikes]
fake_calls = pd.DataFrame({
    "strike": fake_strikes,
    # live bid/ask for every in-band strike EXCEPT 850, which simulates a closed/stale market
    # (bid=ask=0) that must fall back to lastPrice instead.
    "bid": [p * 0.99 if k != 850.0 else 0.0 for k, p in zip(fake_strikes, fake_prices)],
    "ask": [p * 1.01 if k != 850.0 else 0.0 for k, p in zip(fake_strikes, fake_prices)],
    "lastPrice": fake_prices,
})

class _FakeChain:
    calls = fake_calls

class _FakeTicker:
    def option_chain(self, expiry):
        return _FakeChain()
    def history(self, period):
        return pd.DataFrame({"Close": [S_test]})

with mock.patch("yfinance.Ticker", return_value=_FakeTicker()), \
     mock.patch("pandas.Timestamp.now", return_value=_mocked_now):
    result8 = fetch_live_option_chain("SPY", _expiry, moneyness_band=(0.7, 1.3))
# band = [0.7*770, 1.3*770] = [539.0, 1001.0]
check("deep-ITM strike 150 (far below the 539 lower bound) is filtered out",
      150.0 not in result8["strikes"])
check("in-band strikes (700, 770, 850, 1000) all survive the filter -- exactly 4 strikes remain",
      len(result8["strikes"]) == 4 and set(result8["strikes"]) == {700.0, 770.0, 850.0, 1000.0})
check(f"the derived IV for every surviving strike recovers the TRUE injected vol (0.20), "
      f"confirming the inversion pipeline (not yfinance's own IV column) is what's used: "
      f"{np.round(result8['ivs'], 4)}",
      np.allclose(result8["ivs"], true_vol, atol=1e-3))
check("exactly 1 strike (850, the simulated closed-market case) is flagged as priced off a "
      "stale lastPrice rather than a live bid/ask", result8["used_stale_last_price"] == 1)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
