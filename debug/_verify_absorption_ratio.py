"""
Synthetic verification of absorption_ratio.py's rolling_absorption_ratio(),
using the two degenerate cases named in the Phase 3 plan, BEFORE trusting it
on real CAMARF universe data:

  1. All assets identical (perfectly correlated, single shared factor) ->
     Absorption Ratio should be ~1.0 (nearly all variance explained by the
     top eigenvalue alone).
  2. All assets independent i.i.d. noise (no shared factor at all) ->
     Absorption Ratio should be ~K/N (each eigenvalue of a near-identity
     correlation matrix is ~1, so the top-K sum over the total-N sum is
     just K/N — no concentration beyond chance).

Also checks a monotonic sanity property: a universe that's a mix (half
driven by a common factor, half pure noise) should land strictly between
the two degenerate cases.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from absorption_ratio import rolling_absorption_ratio

rng = np.random.default_rng(7)
N, T, WINDOW = 30, 400, 252


def _make_returns_df(matrix: np.ndarray) -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=T, freq="B")
    return pd.DataFrame(matrix.T, index=dates, columns=[f"SYM{i}" for i in range(N)])


def main():
    failures = []

    # --- 1. All assets identical -> AR ~ 1.0 ---
    common = rng.normal(size=T)
    identical_matrix = np.tile(common, (N, 1))  # every row is the exact same series
    identical_df = _make_returns_df(identical_matrix)
    ar_identical = rolling_absorption_ratio(identical_df, window=WINDOW, step=WINDOW)
    if ar_identical.empty:
        failures.append("identical-assets case produced no windows")
    else:
        mean_ar = ar_identical["absorption_ratio"].mean()
        if mean_ar < 0.95:
            failures.append(f"Identical-assets AR should be ~1.0, got {mean_ar:.4f}")

    # --- 2. All assets independent -> AR ~ K/N ---
    independent_matrix = rng.normal(size=(N, T))
    independent_df = _make_returns_df(independent_matrix)
    ar_independent = rolling_absorption_ratio(independent_df, window=WINDOW, step=WINDOW)
    k_expected = max(1, round(N / 5))
    expected_ar = k_expected / N
    if ar_independent.empty:
        failures.append("independent-assets case produced no windows")
    else:
        mean_ar = ar_independent["absorption_ratio"].mean()
        # Allow a reasonably wide tolerance — finite-sample eigenvalues of a
        # random correlation matrix are noisy even under the true null.
        if abs(mean_ar - expected_ar) > 0.15:
            failures.append(
                f"Independent-assets AR should be ~K/N={expected_ar:.4f}, got {mean_ar:.4f}"
            )

    # --- 3. Mixed case lands strictly between the two degenerate cases ---
    factor = rng.normal(size=T)
    mixed_matrix = np.vstack([
        np.tile(0.9 * factor + rng.normal(scale=0.1, size=T), (N // 2, 1)),
        rng.normal(size=(N - N // 2, T)),
    ])
    mixed_df = _make_returns_df(mixed_matrix)
    ar_mixed = rolling_absorption_ratio(mixed_df, window=WINDOW, step=WINDOW)
    if not ar_identical.empty and not ar_independent.empty and not ar_mixed.empty:
        mean_mixed = ar_mixed["absorption_ratio"].mean()
        mean_id = ar_identical["absorption_ratio"].mean()
        mean_indep = ar_independent["absorption_ratio"].mean()
        if not (mean_indep < mean_mixed < mean_id):
            failures.append(
                f"Mixed AR ({mean_mixed:.4f}) should land strictly between "
                f"independent ({mean_indep:.4f}) and identical ({mean_id:.4f})"
            )

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All absorption_ratio checks passed.")
    print(f"  identical AR (expect ~1.0): {ar_identical['absorption_ratio'].mean():.4f}")
    print(f"  independent AR (expect ~{expected_ar:.4f}): {ar_independent['absorption_ratio'].mean():.4f}")
    print(f"  mixed AR (expect between): {ar_mixed['absorption_ratio'].mean():.4f}")


if __name__ == "__main__":
    main()
