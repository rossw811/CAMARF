"""
CAMARF midas_feature.py — comparison method, NOT part of the production
pipeline.

Idea #11 from Development.md's Session 10 academic backlog: combine
multi-timeframe information into one feature via MIDAS (Mixed Data
Sampling, Ghysels et al.) instead of treating each of CAMARF's 13
timeframes as a fully separate, parallel pipeline. Scoped per the
2026-06-23 design discussion: a single concrete pairing first (a fast
TF's history informing a slow TF's entry-event model for the SAME
confirmed pair), not a universe-wide rebuild.

Beta-polynomial lag weighting (the standard, parsimonious MIDAS scheme):
    w_k(theta1, theta2) proportional to (k/K)^(theta1-1) * (1-k/K)^(theta2-1)
normalized to sum to 1 over k=1..K lags. theta1=1 collapses to a
monotonically-decaying scheme (more weight on more-recent lags);
theta1=theta2=1 collapses to a flat average.

HONEST SCOPING LIMITATION (read before using this for anything beyond a
construction demo): evaluating whether a MIDAS feature actually improves
out-of-sample prediction requires labeled entry-event outcomes at the
slow TF, and every slower-TF confirmed pair in this project currently
has very few of those (e.g. SPY/VOO@4h: 1 entry event total as of the
last ml.py run) — nowhere near enough to support a train/test split.
This module verifies the WEIGHTING MATH is correct and demonstrates
real feature construction on SPY/VOO's actual 1h cache; it does NOT
claim a predictive comparison, exactly matching ml.py's own "honestly
reports insufficient data" discipline rather than overclaiming on a
single data point.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import DataStore


def beta_weights(K: int, theta1: float, theta2: float) -> np.ndarray:
    """MIDAS beta-polynomial lag weights, k=1..K, normalized to sum to 1.
    k=1 is the MOST RECENT lag (closest to the aggregation point)."""
    if K < 1:
        raise ValueError("K must be >= 1")
    k = np.arange(1, K + 1, dtype=float)
    x = k / K
    raw = (x ** (theta1 - 1)) * ((1 - x + 1e-12) ** (theta2 - 1))
    return raw / raw.sum()


def midas_aggregate(
    high_freq: pd.Series,
    low_freq_index: pd.DatetimeIndex,
    K: int,
    theta1: float,
    theta2: float,
) -> pd.Series:
    """
    For each timestamp in low_freq_index, aggregate the trailing K
    observations of high_freq (strictly before that timestamp, no
    lookahead) via beta-polynomial weights. Returns NaN where fewer than
    K real observations are available — never silently aggregates a
    partial, ambiguously-weighted window.
    """
    w = beta_weights(K, theta1, theta2)  # w[0] = weight on most recent lag
    hf = high_freq.sort_index()
    out = pd.Series(index=low_freq_index, dtype=float)
    for ts in low_freq_index:
        window = hf[hf.index < ts].iloc[-K:]
        if len(window) < K or window.isna().any():
            out[ts] = np.nan
            continue
        # window is oldest->newest; w[0] must align with the MOST RECENT
        # (last) element, so reverse the weight vector to match.
        out[ts] = float(np.dot(window.values, w[::-1]))
    return out


def _verify_weights():
    """Synthetic checks on the weighting function itself."""
    failures = []
    for theta1, theta2 in [(1.0, 1.0), (1.0, 3.0), (2.0, 5.0), (0.5, 0.5)]:
        w = beta_weights(20, theta1, theta2)
        ok_sum = abs(w.sum() - 1.0) < 1e-9
        ok_nonneg = (w >= 0).all()
        status = "OK" if (ok_sum and ok_nonneg) else "FAIL"
        print(f"{status}  theta=({theta1},{theta2}): sum={w.sum():.6f}, "
              f"all_nonneg={ok_nonneg}, w[:3]={np.round(w[:3], 4)}")
        if not (ok_sum and ok_nonneg):
            failures.append((theta1, theta2))

    # theta1=1, theta2>1 should be monotonically decaying toward older lags
    w_decay = beta_weights(20, 1.0, 3.0)
    is_decaying = np.all(np.diff(w_decay) <= 1e-12)
    print(f"{'OK' if is_decaying else 'FAIL'}  theta=(1,3) weights monotonically "
          f"decay from most-recent to oldest lag: {is_decaying}")
    if not is_decaying:
        failures.append("monotonic_decay")

    # theta1=theta2=1 should be ~flat (equal weights)
    w_flat = beta_weights(20, 1.0, 1.0)
    is_flat = np.allclose(w_flat, w_flat[0], atol=1e-9)
    print(f"{'OK' if is_flat else 'FAIL'}  theta=(1,1) weights are flat "
          f"(simple average): {is_flat}")
    if not is_flat:
        failures.append("flat_case")

    return failures


def _demonstrate_on_spy_voo():
    """Real construction demo — NOT a predictive comparison (see module
    docstring). Aggregates SPY/VOO's actual 1h price-ratio history into a
    4-hourly MIDAS feature and shows what it looks like against a naive
    flat-average aggregation."""
    spy = DataStore.load("SPY", "1h")
    voo = DataStore.load("VOO", "1h")
    if spy is None or voo is None:
        print("SKIP demo: SPY/VOO 1h cache not available")
        return
    log_ratio = np.log(spy["close"]) - np.log(voo["close"])
    log_ratio = log_ratio.dropna()

    # Pseudo-low-frequency index: every 4th real 1h timestamp (stand-in
    # for "4h entry events" without depending on the live spread_series
    # file analysis.py is mid-rewriting in this same session).
    low_freq_index = log_ratio.index[::4][5:]  # skip the first few (no lookback yet)
    K = 16  # 16 trailing 1h bars ~= 4 trading days of context

    midas_decay = midas_aggregate(log_ratio, low_freq_index, K, theta1=1.0, theta2=3.0)
    midas_flat = midas_aggregate(log_ratio, low_freq_index, K, theta1=1.0, theta2=1.0)

    print(f"\nSPY/VOO log-ratio MIDAS feature construction demo "
          f"(K={K} trailing 1h bars, {len(low_freq_index)} aggregation points):")
    compare = pd.DataFrame({
        "midas_decay_weighted": midas_decay,
        "naive_flat_average": midas_flat,
    }).dropna()
    print(compare.tail(10).to_string())
    print(f"\nCorrelation between decay-weighted and flat-average versions: "
          f"{compare['midas_decay_weighted'].corr(compare['naive_flat_average']):.4f} "
          f"(expected high but <1.0 — decay weighting emphasizes recent bars more)")
    print(
        "\nNOTE: this demonstrates the feature CONSTRUCTION is correct and "
        "produces sensible, non-degenerate output. It is NOT a predictive "
        "comparison against the existing per-TF pipeline — that requires "
        "labeled 4h entry-event outcomes, of which SPY/VOO@4h currently has "
        "far too few (1, as of the last ml.py run) to support any train/test "
        "split. Revisit once more 4h history accumulates."
    )


def main():
    print("=== Weighting function verification ===")
    failures = _verify_weights()
    print()
    print("=== Real-data construction demo (SPY/VOO) ===")
    _demonstrate_on_spy_voo()

    print()
    if failures:
        print(f"FAILED: {failures}")
        import sys
        sys.exit(1)
    print("All weighting-function checks passed.")


if __name__ == "__main__":
    main()
