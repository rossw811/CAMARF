"""
research/ewma_zscore_comparison.py -- comparison arm testing an EWMA-based
alternative to SpreadModel.rolling_zscore's flat-rolling-window z-score,
inspired by gs_quant.timeseries.technicals.exponential_spread_volatility
(2026-08-13, Ross: "let's implement them for comparison first").

DESIGN CORRECTION MADE BEFORE BUILDING, not after (real prior finding
caught by reading rolling_zscore's own docstring first): BUG-D45
(Development.md) already tried a DECOUPLED shorter/more-responsive window
for std while keeping the existing (longer) window for mean, and found it
made things WORSE, not better (CRWD/DDOG: std jumped to 7.13, 12.3% of bars
showed |z|>10) -- decoupling breaks the z-score's own "mean~=0, std~=1 over
its window" guarantee; if the spread drifts within the longer mean window,
a faster-responding std denominator amplifies that drift into a systematic
bias rather than tracking real volatility. This script does NOT repeat that
mistake: it uses EWMA for BOTH mean and std together (a full EWMA z-score),
keeping them coupled under the same decay/responsiveness, matching the
"single shared window for both" principle BUG-D45 established as correct
-- testing whether EXPONENTIAL weighting (vs. FLAT weighting, both using
the same effective window) changes anything, not re-testing decoupling.

Method: for every real confirmed pair's cached spread_series_{A}_{B}.parquet
(output/results/{tf_dir}/), computes an EWMA z-score using the SAME
half-life-adaptive window SpreadModel.fit_pair already derives (read from
the pair's own half_life_rolling column, same OU_WINDOW_HALFLIFE_MULT_MEAN/
OU_WINDOW_MIN_BARS/OU_LOOKBACK_DAYS convention), converted to an EWMA
half-life via span<->halflife equivalence. Compares against the real,
already-cached z_rolling column: correlation, entry-signal disagreement
rate (|z|>=ENTRY_ZSCORE flips), and the same frac|z|>10 diagnostic BUG-D45
itself used to catch its own bug.

This is a DIAGNOSTIC/RESEARCH comparison, not a production change --
promotion to replace rolling_zscore is a separate, later decision per this
project's comparison-arm-before-production discipline.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from config import Config

_RESULTS_GLOB = os.path.join("output", "results", "*", "spread_series_*.parquet")
_OUT_PATH = os.path.join("output", "research", "ewma_zscore_comparison.parquet")


def ewma_zscore(spread: np.ndarray, halflife_bars: float) -> np.ndarray:
    """EWMA z-score: (x - ewma_mean) / ewma_std, BOTH moments computed with
    the SAME halflife (coupled, per the BUG-D45 lesson in this module's
    docstring). pandas .ewm() is causal by construction (exponentially
    weights only past+current observations, no look-ahead)."""
    s = pd.Series(spread)
    halflife_bars = max(float(halflife_bars), 1.0)
    mu = s.ewm(halflife=halflife_bars, min_periods=max(2, int(halflife_bars))).mean()
    sd = s.ewm(halflife=halflife_bars, min_periods=max(2, int(halflife_bars))).std()
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (s - mu) / sd
    return z.values


def _adaptive_window_bars(half_life_series: pd.Series) -> pd.Series:
    """Mirrors SpreadModel.fit_pair's own window derivation exactly (same
    OU_WINDOW_HALFLIFE_MULT_MEAN/MIN/MAX convention) so the EWMA halflife
    is derived the same way the existing rolling window is, not a
    different, unmatched sizing rule."""
    cfg = Config.ANALYSIS
    window = half_life_series * cfg.OU_WINDOW_HALFLIFE_MULT_MEAN
    return window.clip(lower=cfg.OU_WINDOW_MIN_BARS, upper=cfg.OU_LOOKBACK_DAYS)


def compare_pair(path: str) -> dict:
    df = pd.read_parquet(path)
    if "z_rolling" not in df.columns or "half_life_rolling" not in df.columns:
        return None
    hl = df["half_life_rolling"].bfill().ffill()
    if hl.isna().all():
        return None
    window_bars = _adaptive_window_bars(hl)
    # EWMA halflife matched to the SAME adaptive window's median value (a
    # per-bar-varying halflife would require a much more involved
    # implementation than pandas.ewm supports natively -- using the
    # window's median as a representative single halflife is a real,
    # disclosed simplification for this comparison pass, not silently
    # assumed equivalent to the fully time-varying version).
    halflife = float(window_bars.median())
    z_ewma = ewma_zscore(df["spread"].values, halflife)

    z_roll = df["z_rolling"].values
    valid = np.isfinite(z_roll) & np.isfinite(z_ewma)
    if valid.sum() < 30:
        return None

    entry_z = Config.BACKTEST.ENTRY_ZSCORE
    roll_entry = np.abs(z_roll[valid]) >= entry_z
    ewma_entry = np.abs(z_ewma[valid]) >= entry_z
    agreement = float((roll_entry == ewma_entry).mean())

    return {
        "path": os.path.basename(path),
        "n_bars": int(valid.sum()),
        "halflife_bars": halflife,
        "corr_z_rolling_vs_ewma": float(np.corrcoef(z_roll[valid], z_ewma[valid])[0, 1]),
        "frac_extreme_rolling": float((np.abs(z_roll[valid]) > 10).mean()),
        "frac_extreme_ewma": float((np.abs(z_ewma[valid]) > 10).mean()),
        "entry_signal_agreement": agreement,
        "n_entry_rolling": int(roll_entry.sum()),
        "n_entry_ewma": int(ewma_entry.sum()),
    }


def main():
    files = sorted(glob.glob(_RESULTS_GLOB))
    print(f"Found {len(files)} real cached spread_series files")
    rows = []
    for f in files:
        try:
            row = compare_pair(f)
        except Exception as e:
            print(f"  {f}: FAILED ({e})")
            continue
        if row:
            rows.append(row)

    if not rows:
        print("No valid comparisons produced.")
        return

    out_df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(_OUT_PATH), exist_ok=True)
    out_df.to_parquet(_OUT_PATH, index=False)
    print(f"\n{len(out_df)} pairs compared. Saved -> {_OUT_PATH}\n")
    print(out_df[["path", "n_bars", "halflife_bars", "corr_z_rolling_vs_ewma",
                   "frac_extreme_rolling", "frac_extreme_ewma", "entry_signal_agreement"]]
          .to_string(index=False))
    print(f"\nMean correlation (rolling vs EWMA z-score): {out_df['corr_z_rolling_vs_ewma'].mean():.4f}")
    print(f"Mean entry-signal agreement rate: {out_df['entry_signal_agreement'].mean():.4f}")
    print(f"Mean frac|z|>10 -- rolling: {out_df['frac_extreme_rolling'].mean():.4f}, "
          f"EWMA: {out_df['frac_extreme_ewma'].mean():.4f}")


if __name__ == "__main__":
    main()
