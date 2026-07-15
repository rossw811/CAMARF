"""
CAMARF research/wavelet_hurst_comparison.py — comparison/diagnostic
script, NOT part of the production pipeline (2026-07-14, task #43: a
third Hurst estimator alongside analysis.py's existing R/S and DFA).

Adds a Haar-wavelet-variance Hurst estimator (Abry-Veitch style: for a
self-similar increment process with Hurst exponent H, the variance of
Haar wavelet detail coefficients at dyadic scale j scales as
E[d_j^2] ~ 2^(j*(2H+1)), so a log2(variance) vs. j regression recovers
H = (slope - 1) / 2). No new dependency — implemented directly with
numpy rather than adding PyWavelets, given this project's documented
history of environment/dependency pain (pyarrow version mismatches,
base-vs-trading-env confusion) and that the Haar transform is simple
enough to implement correctly without a library.

Operates on the SAME quantity as the two existing estimators — spread
INCREMENTS, not levels (analysis.py's HurstEstimator docstring explains
why: level autocorrelation from AR(1)/OU dynamics gives a spuriously
high H on levels; increments correctly reflect mean-reversion).

Reuses analysis.py's actual HurstEstimator.hurst_rs / hurst_dfa directly
(not reimplemented) for a true apples-to-apples comparison against the
new wavelet estimator, computed on the same spread series.

Spread construction: simple full-sample OLS hedge ratio (log_a - beta *
log_b), not analysis.py's full point-in-time HedgeRatioEstimator/
SpreadModel machinery — this script is comparing Hurst ESTIMATORS on a
given spread, not re-deriving the spread itself, so a straightforward
consistent construction across all pairs is the right scope (stated
explicitly, not silently simplified).

Usage:
    python research/wavelet_hurst_comparison.py --tf 1h
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from aligned_pair_loader import load_aligned_pair
from lead_lag_scan import _gap_masked_log_price
from analysis import HurstEstimator

_DEFAULT_PAIRS = [
    ("LNT", "VTR"), ("LNT", "WELL"), ("AME", "MAR"), ("CMS", "DUK"),
    ("EG", "WRB"), ("HAL", "NOV"), ("MET", "TMHC"), ("PFG", "STLD"),
    ("UMBF", "FHB"),
]


def wavelet_hurst(spread: np.ndarray, min_scale_pts: int = 4) -> float:
    """
    Haar-wavelet-variance Hurst estimator on spread INCREMENTS (same
    convention as HurstEstimator.hurst_rs/hurst_dfa).

    At dyadic scale j (block size 2^j), the Haar detail coefficient for
    block k is (mean of first half - mean of second half) / sqrt(2) — a
    block-mean-difference Haar-style transform applied to the increment
    series (not the textbook Abry-Veitch DWT-on-levels construction, whose
    published H formula does NOT apply directly here — verified and fixed
    2026-07-14 after a synthetic random-walk test caught H=0.000 instead
    of the expected ~0.5, see debug/_verify_wavelet_hurst.py).

    Derivation for THIS construction: for a self-similar increment process
    where the variance of an m-term partial sum scales as m^(2H) (the same
    defining relationship R/S and DFA rest on), a block-mean of `half`
    increments has variance ~ half^(2H-2), so the detail coefficient
    (difference of two block-means) has the same scaling: var_j ~
    block^(2H-2) (block = 2^j). Hence log2(var_j) = (2H-2)*j + const, i.e.
    slope = 2H - 2, so H = slope/2 + 1. Checked against white noise
    (H should be ~0.5 -> slope should be ~-1): confirmed directly.
    """
    s = spread[np.isfinite(spread)]
    inc = np.diff(s)
    n = inc.size
    if n < HurstEstimator.MIN_BARS:
        return np.nan

    max_j = int(np.floor(np.log2(n // 4)))  # need >=4 blocks at the coarsest scale
    if max_j < 2:
        return np.nan

    js, log2_vars = [], []
    for j in range(1, max_j + 1):
        block = 2 ** j
        n_blocks = n // block
        if n_blocks < min_scale_pts:
            continue
        trimmed = inc[: n_blocks * block].reshape(n_blocks, block)
        half = block // 2
        first_half_mean = trimmed[:, :half].mean(axis=1)
        second_half_mean = trimmed[:, half:].mean(axis=1)
        details = (first_half_mean - second_half_mean) / np.sqrt(2)
        var_j = float(np.mean(details ** 2))
        if var_j > 1e-18:
            js.append(j)
            log2_vars.append(np.log2(var_j))

    if len(js) < 3:
        return np.nan
    js = np.array(js, dtype=float)
    log2_vars = np.array(log2_vars)
    slope = HurstEstimator._ols_slope(js, log2_vars)
    if not np.isfinite(slope):
        return np.nan
    H = slope / 2.0 + 1.0
    return float(np.clip(H, 0.0, 1.0))


def _ols_hedge_spread(log_a: np.ndarray, log_b: np.ndarray) -> np.ndarray:
    mask = np.isfinite(log_a) & np.isfinite(log_b)
    a_, b_ = log_a[mask], log_b[mask]
    beta = np.dot(b_ - b_.mean(), a_ - a_.mean()) / np.dot(b_ - b_.mean(), b_ - b_.mean())
    alpha = a_.mean() - beta * b_.mean()
    full_spread = np.full_like(log_a, np.nan)
    full_spread[mask] = log_a[mask] - (alpha + beta * log_b[mask])
    return full_spread


def run_pair(symbol_a, symbol_b, tf_label):
    df_a, df_b = load_aligned_pair(symbol_a, symbol_b, tf_label)
    if df_a is None or df_b is None or df_a.empty or df_b.empty:
        return None
    log_a = pd.Series(_gap_masked_log_price(df_a), index=df_a.index)
    log_b = pd.Series(_gap_masked_log_price(df_b), index=df_b.index)
    common_idx = log_a.index.intersection(log_b.index)
    log_a, log_b = log_a.reindex(common_idx).values, log_b.reindex(common_idx).values

    spread = _ols_hedge_spread(log_a, log_b)
    h_rs = HurstEstimator.hurst_rs(spread)
    h_dfa = HurstEstimator.hurst_dfa(spread)
    h_wav = wavelet_hurst(spread)

    return {
        "symbol_a": symbol_a, "symbol_b": symbol_b,
        "hurst_rs": h_rs, "hurst_dfa": h_dfa, "hurst_wavelet": h_wav,
        "rs_dfa_divergence": abs(h_rs - h_dfa) if np.isfinite(h_rs) and np.isfinite(h_dfa) else np.nan,
        "rs_wavelet_divergence": abs(h_rs - h_wav) if np.isfinite(h_rs) and np.isfinite(h_wav) else np.nan,
        "dfa_wavelet_divergence": abs(h_dfa - h_wav) if np.isfinite(h_dfa) and np.isfinite(h_wav) else np.nan,
    }


def main():
    p = argparse.ArgumentParser(description="Wavelet Hurst as a third comparison estimator (2026-07-14)")
    p.add_argument("--tf", default="1h")
    args = p.parse_args()

    rows = []
    for sym_a, sym_b in _DEFAULT_PAIRS:
        r = run_pair(sym_a, sym_b, args.tf)
        if r is not None:
            rows.append(r)
            print(f"{sym_a}/{sym_b}@{args.tf}: H_rs={r['hurst_rs']:.3f} H_dfa={r['hurst_dfa']:.3f} "
                  f"H_wavelet={r['hurst_wavelet']:.3f}  "
                  f"(rs-dfa={r['rs_dfa_divergence']:.3f}, rs-wav={r['rs_wavelet_divergence']:.3f}, "
                  f"dfa-wav={r['dfa_wavelet_divergence']:.3f})")

    if not rows:
        print("No results.")
        return
    df = pd.DataFrame(rows)
    print(f"\nMean |divergence|: rs-dfa={df['rs_dfa_divergence'].mean():.3f}, "
          f"rs-wavelet={df['rs_wavelet_divergence'].mean():.3f}, "
          f"dfa-wavelet={df['dfa_wavelet_divergence'].mean():.3f}")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"wavelet_hurst_comparison_{args.tf}.parquet")
    df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
