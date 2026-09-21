# =============================================================================
# Synthetic verification of research/multivariate_pit_predictors.py's OWN new
# logic (hedge_ratio_stability's CV computation and edge cases, fit_logit's
# graceful handling of too-little-data). Does NOT re-test screen_universe_at_
# cutoff/backtest_pair_on_test_window (covered by debug/_verify_pit_wfa_wrds_
# daily.py) or _fold_start_dates (covered by debug/_verify_overlap_threshold_
# pit_test.py) -- reused unmodified from those.
# =============================================================================
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.multivariate_pit_predictors import hedge_ratio_stability, fit_logit

checks = []


def check(name, cond, detail=""):
    checks.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


class _FakePairResult:
    def __init__(self, a, b):
        self.symbol_a, self.symbol_b = a, b


def _ohlc(close, index):
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close,
                          "gap_flag": 0}, index=index)


rng = np.random.default_rng(0)
idx = pd.bdate_range("2015-01-01", periods=600)

# A genuinely cointegrated pair with a STABLE hedge ratio (B tracks a fixed
# multiple of A plus mean-reverting noise) should show low CV.
close_a = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx))))
noise = np.zeros(len(idx))
for t in range(1, len(idx)):
    noise[t] = 0.9 * noise[t - 1] + rng.normal(0, 0.02)
close_b_stable = close_a * 0.5 * np.exp(noise)
universe_stable = {
    "STABLE_A": _ohlc(close_a, idx),
    "STABLE_B": _ohlc(close_b_stable, idx),
}
cv_stable = hedge_ratio_stability(
    universe_stable, _FakePairResult("STABLE_A", "STABLE_B"), idx[0], idx[-1]
)
check("stable_pair.cv_is_finite", np.isfinite(cv_stable), f"got {cv_stable}")

# A pair whose relationship structurally BREAKS halfway through (B switches
# from tracking A to tracking an independent series) should show a higher CV
# -- the rolling hedge ratio has to visibly shift to follow the regime change.
close_c_indep = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx))))
close_b_unstable = close_b_stable.copy()
mid = len(idx) // 2
# second half re-based off an independent series at a very different implied ratio
close_b_unstable[mid:] = close_c_indep[mid:] * 3.0
universe_unstable = {
    "STABLE_A": _ohlc(close_a, idx),
    "UNSTABLE_B": _ohlc(close_b_unstable, idx),
}
cv_unstable = hedge_ratio_stability(
    universe_unstable, _FakePairResult("STABLE_A", "UNSTABLE_B"), idx[0], idx[-1]
)
check("unstable_pair.cv_higher_than_stable",
      np.isfinite(cv_unstable) and cv_unstable > cv_stable,
      f"stable={cv_stable:.4f} unstable={cv_unstable:.4f}")

# Missing symbol / too little data -> NaN, not a crash.
cv_missing = hedge_ratio_stability(
    universe_stable, _FakePairResult("STABLE_A", "DOES_NOT_EXIST"), idx[0], idx[-1]
)
check("missing_symbol.returns_nan_not_crash", np.isnan(cv_missing), f"got {cv_missing}")

short_idx = idx[:30]
short_universe = {k: v.loc[short_idx] for k, v in universe_stable.items()}
cv_short = hedge_ratio_stability(
    short_universe, _FakePairResult("STABLE_A", "STABLE_B"), short_idx[0], short_idx[-1]
)
check("insufficient_data.returns_nan_not_crash", np.isnan(cv_short), f"got {cv_short}")

# fit_logit must degrade gracefully (a message, not a crash) on too little
# clean data -- the real pooled dataset could plausibly be this small if most
# cells produce few confirmed pairs.
tiny_df = pd.DataFrame([
    {"actual_n_overlap": 300, "pearson_corr": 0.5, "coint_fraction_rolling": 0.8,
     "hedge_ratio_cv": 0.1, "held_up": True},
    {"actual_n_overlap": 400, "pearson_corr": 0.6, "coint_fraction_rolling": 0.9,
     "hedge_ratio_cv": 0.2, "held_up": False},
])
result = fit_logit(tiny_df)
check("fit_logit.degrades_gracefully_on_tiny_data",
      isinstance(result, str) and "Not enough clean data" in result, f"got: {result[:80]}")

n_pass = sum(1 for _, ok, _ in checks if ok)
print(f"\n{n_pass}/{len(checks)} checks passed")
sys.exit(0 if n_pass == len(checks) else 1)
