"""
Synthetic verification for Tier 6 (Grand Sweep 2026-07-20): backtest.py's
BacktestEngine.run() previously ran `df[df["z_rolling"] != 0.0]` after
dropna(), under the incorrect assumption that warm-up bars (before
SpreadModel.rolling_zscore's rolling window fills) are represented as 0.0
rather than NaN. Confirmed directly against analysis.py::SpreadModel.
rolling_zscore: warm-up bars are genuine NaN (pandas rolling with
min_periods), already fully handled by dropna() alone -- the != 0.0 filter's
only real effect was to ALSO drop genuine mid-series exact-zero z-crossings.

This test builds a synthetic z_rolling series with NaN warm-up bars AND a
genuine exact-zero crossing mid-series, and confirms:
  - The OLD filter (dropna + != 0.0) drops both the warm-up bars AND the
    genuine zero-crossing bar.
  - The FIXED filter (dropna only) drops just the warm-up bars, keeping the
    genuine zero-crossing bar.

Run: python debug/_verify_backtest_zero_z_filter_fix.py
"""
import numpy as np
import pandas as pd


def main():
    n = 100
    z = np.linspace(-3, 3, n)  # crosses through 0 near the midpoint
    z[50] = 0.0  # force an exact mid-series zero-crossing (deterministic, not float-luck)
    z[:10] = np.nan  # simulated warm-up period (genuine NaN, per rolling_zscore)
    spread = pd.Series(np.random.default_rng(0).normal(0, 1, n))
    df = pd.DataFrame({"z_rolling": z, "spread": spread})

    zero_crossing_idx = np.where(z == 0.0)[0]
    assert len(zero_crossing_idx) == 1, "Test setup should have exactly one exact-zero crossing"
    zero_idx = zero_crossing_idx[0]
    print(f"Synthetic series: {n} bars, 10 NaN warm-up bars, exact-zero z-crossing at bar {zero_idx}")

    # OLD (buggy) behavior.
    old_df = df.dropna(subset=["z_rolling", "spread"]).copy()
    old_df = old_df[old_df["z_rolling"] != 0.0]

    # NEW (fixed) behavior.
    new_df = df.dropna(subset=["z_rolling", "spread"]).copy()

    print(f"OLD (dropna + != 0.0): {len(old_df)} rows, contains zero-crossing bar: "
          f"{zero_idx in old_df.index}")
    print(f"NEW (dropna only):     {len(new_df)} rows, contains zero-crossing bar: "
          f"{zero_idx in new_df.index}")

    assert zero_idx not in old_df.index, (
        "Test setup failed to reproduce the bug -- old filter should have dropped the "
        "genuine zero-crossing bar."
    )
    assert zero_idx in new_df.index, (
        "Fixed filter should retain the genuine zero-crossing bar."
    )
    # Both should still correctly exclude the 10 NaN warm-up bars.
    assert len(new_df) == n - 10, f"Fixed filter should drop exactly the 10 NaN warm-up bars, got {len(new_df)}"
    assert old_df.index.difference(new_df.index).empty, (
        "Old filter's surviving rows should be a strict subset of the fixed filter's -- "
        "confirms the only difference is the removed (harmful) != 0.0 exclusion, not a "
        "behavior change to the warm-up handling itself."
    )

    print("\nPASS: fixed filter retains the genuine mid-series exact-zero z-crossing bar "
          "while still correctly excluding all NaN warm-up bars.")


if __name__ == "__main__":
    main()
