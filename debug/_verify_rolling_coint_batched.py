"""Verification that the 2026-08-23 batched rewrite of analysis.py::_rolling_coint_worker and
::expanding_coint_fraction produces IDENTICAL output to their original per-window
coint(a_w, b_w, trend="c", maxlag=1, autolag=None) loop -- reconstructed here as an independent
reference (the loop itself was replaced, not kept as a code path to compare against directly).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

from analysis import _rolling_coint_worker, CointScanner, longest_gap_respecting_segment
expanding_coint_fraction = CointScanner.expanding_coint_fraction

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"{'PASS' if cond else 'FAIL'}: {name}")


def reference_rolling_fraction(log_a, log_b, window, step, tf_label):
    mask = np.isfinite(log_a) & np.isfinite(log_b)
    keep = longest_gap_respecting_segment(mask, tf_label)
    a, b = log_a[keep], log_b[keep]
    n = a.size
    if n < window + step:
        return np.nan, 0
    n_sig, n_win = 0, 0
    for start in range(0, n - window + 1, step):
        a_w, b_w = a[start:start + window], b[start:start + window]
        try:
            _t, p, _c = coint(a_w, b_w, trend="c", maxlag=1, autolag=None)
            if p < 0.05:
                n_sig += 1
            n_win += 1
        except Exception:
            continue
    return (n_sig / n_win if n_win > 0 else np.nan), n_win


def reference_expanding_fraction(log_a, log_b, tf_label, window=252, step=21):
    mask = np.isfinite(log_a) & np.isfinite(log_b)
    keep = longest_gap_respecting_segment(mask, tf_label)
    frac_series = np.full(log_a.size, np.nan, dtype=float)
    n = int(np.sum(keep))
    if n < window + step:
        new_window = max(60, n // 3)
        new_step = max(5, new_window // 10)
        if new_window < window + new_step:
            return frac_series
        window, step = new_window, new_step
    a, b = log_a[keep], log_b[keep]
    real_positions = np.flatnonzero(keep)
    n_sig, n_win = 0, 0
    for start in range(0, n - window + 1, step):
        a_w, b_w = a[start:start + window], b[start:start + window]
        try:
            _t, p, _c = coint(a_w, b_w, trend="c", maxlag=1, autolag=None)
            if p < 0.05:
                n_sig += 1
            n_win += 1
        except Exception:
            continue
        end_pos_full = real_positions[start + window - 1]
        frac_series[end_pos_full] = n_sig / n_win if n_win > 0 else np.nan
    return pd.Series(frac_series).ffill().values


rng = np.random.default_rng(13)
tf_label = "1D"
n_bars = 1000
shared = rng.standard_normal(n_bars).cumsum()
log_a = shared + rng.standard_normal(n_bars) * 0.3 + 100
log_b = shared + rng.standard_normal(n_bars) * 0.3 + 50

# --- _rolling_coint_worker ---
ref_frac, ref_nwin = reference_rolling_fraction(log_a, log_b, window=252, step=21, tf_label=tf_label)
result = _rolling_coint_worker((("A", "B", log_a, log_b, 252, 21, tf_label)))
check("rolling: fraction matches reference", abs(result["fraction"] - ref_frac) < 1e-9)
check("rolling: n_windows matches reference", result["n_windows"] == ref_nwin)

# --- expanding_coint_fraction ---
ref_series = reference_expanding_fraction(log_a, log_b, tf_label, window=252, step=21)
new_series = expanding_coint_fraction(log_a, log_b, tf_label, window=252, step=21)
check("expanding: series length matches", len(ref_series) == len(new_series))
check("expanding: values match reference (nan-aware)",
      np.allclose(ref_series, new_series, atol=1e-9, equal_nan=True))

# --- Edge case: a pair with a genuinely degenerate window (constant b) ---
log_b_degenerate = log_b.copy()
log_b_degenerate[300:600] = log_b_degenerate[300]  # flat segment -> zero-variance windows inside it
ref_frac2, ref_nwin2 = reference_rolling_fraction(log_a, log_b_degenerate, window=252, step=21, tf_label=tf_label)
result2 = _rolling_coint_worker((("A", "B", log_a, log_b_degenerate, 252, 21, tf_label)))
check("rolling (degenerate windows present): fraction matches reference",
      (np.isnan(result2["fraction"]) and np.isnan(ref_frac2)) or abs(result2["fraction"] - ref_frac2) < 1e-9)
check("rolling (degenerate windows present): n_windows matches reference", result2["n_windows"] == ref_nwin2)

n_fail = sum(1 for _, c in checks if not c)
print(f"\n{len(checks) - n_fail}/{len(checks)} checks passed")
sys.exit(1 if n_fail else 0)
