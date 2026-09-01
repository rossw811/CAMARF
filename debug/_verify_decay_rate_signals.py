"""Synthetic verification for research/decay_rate_signals.py -- Thread Q new
path (cointegration decay-rate sizing, scoped 2026-08-24 in Development.md).
Checks: causal correctness (no lookahead) of every smoothing method AND the
new expanding_eg_pvalue_series, correct strengthening/weakening detection on
synthetic trending series, and decay_rate_direction's sign convention."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.decay_rate_signals import (
    smooth_sma, smooth_kalman, smooth_fast_slow, causal_slope,
    decay_rate_series, decay_rate_direction, expanding_eg_pvalue_series,
)

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"{'PASS' if cond else 'FAIL'}: {name}")


rng = np.random.default_rng(42)

# --- Causal-invariance test: every smoothing fn must give the SAME value at
# bar i whether computed on the full series or a series truncated at i+1 --
# a lookahead bug would make truncation change earlier values.
trending = np.cumsum(rng.normal(0.05, 1.0, 300))
for name, fn in (("smooth_sma", lambda s: smooth_sma(s, window=10)),
                  ("smooth_kalman", smooth_kalman),
                  ("smooth_fast_slow", lambda s: smooth_fast_slow(s, 5, 20))):
    full = fn(trending)
    truncated = fn(trending[:150])
    same = np.allclose(full[:150], truncated, equal_nan=True)
    check(f"{name}: causal (truncating the tail doesn't change earlier values)", same)

full_slope = causal_slope(smooth_sma(trending, window=10), lookback=10)
trunc_slope = causal_slope(smooth_sma(trending[:150], window=10), lookback=10)
check("causal_slope: causal (matches on the truncated prefix)",
      np.allclose(full_slope[:150], trunc_slope, equal_nan=True))

# --- Strengthening/weakening detection on synthetic monotonic trends ---
rising = np.linspace(0, 1, 200) + rng.normal(0, 0.01, 200)
falling = np.linspace(1, 0, 200) + rng.normal(0, 0.01, 200)
flat = np.full(200, 0.5) + rng.normal(0, 0.01, 200)

for smoothing in ("sma", "kalman", "fast_slow"):
    r = decay_rate_series(rising, smoothing)
    f = decay_rate_series(falling, smoothing)
    r_tail = np.nanmean(r[-50:])
    f_tail = np.nanmean(f[-50:])
    check(f"decay_rate_series[{smoothing}]: rising series -> positive rate",
          np.isfinite(r_tail) and r_tail > 0)
    check(f"decay_rate_series[{smoothing}]: falling series -> negative rate",
          np.isfinite(f_tail) and f_tail < 0)
    check(f"decay_rate_series[{smoothing}]: rising rate > falling rate",
          r_tail > f_tail)

# --- decay_rate_direction sign convention ---
check("decay_rate_direction(coint_fraction) == +1 (rising = strengthening)",
      decay_rate_direction("coint_fraction") == 1)
check("decay_rate_direction(eg_pvalue) == -1 (rising p = weakening)",
      decay_rate_direction("eg_pvalue") == -1)
check("decay_rate_direction(half_life) == -1 (lengthening HL = weakening)",
      decay_rate_direction("half_life") == -1)
try:
    decay_rate_direction("bogus")
    check("decay_rate_direction: unknown signal raises ValueError", False)
except ValueError:
    check("decay_rate_direction: unknown signal raises ValueError", True)

# --- expanding_eg_pvalue_series: strongly cointegrated synthetic pair ---
n = 1500
common = np.cumsum(rng.normal(0, 1.0, n))
log_a = common + rng.normal(0, 0.05, n)
log_b = 0.5 * common + rng.normal(0, 0.05, n)
tf_label = "1D"

pvals = expanding_eg_pvalue_series(log_a, log_b, tf_label, window=252, step=21)
valid = np.isfinite(pvals)
check("expanding_eg_pvalue_series: produces some valid (non-NaN) values",
      valid.sum() > 0)
check("expanding_eg_pvalue_series: strongly cointegrated synthetic pair shows low p-values",
      np.nanmean(pvals) < 0.10)

pvals_trunc = expanding_eg_pvalue_series(log_a[:800], log_b[:800], tf_label, window=252, step=21)
overlap = min(len(pvals), len(pvals_trunc))
# Only compare positions BEFORE the truncation point where both have real values
cmp_mask = valid[:overlap] & np.isfinite(pvals_trunc[:overlap])
check("expanding_eg_pvalue_series: causal (truncating the tail doesn't change earlier values)",
      cmp_mask.sum() > 0 and np.allclose(pvals[:overlap][cmp_mask], pvals_trunc[:overlap][cmp_mask]))

# --- independent (non-cointegrated) synthetic pair: p-values should NOT be
# uniformly low the way the cointegrated case is ---
log_a_indep = np.cumsum(rng.normal(0, 1.0, n))
log_b_indep = np.cumsum(rng.normal(0, 1.0, n))
pvals_indep = expanding_eg_pvalue_series(log_a_indep, log_b_indep, tf_label, window=252, step=21)
check("expanding_eg_pvalue_series: independent random walks do NOT show the same low p-value pattern",
      np.nanmean(pvals_indep) > np.nanmean(pvals))

n_fail = sum(1 for _, c in checks if not c)
print(f"\n{len(checks) - n_fail}/{len(checks)} checks passed")
sys.exit(1 if n_fail else 0)
