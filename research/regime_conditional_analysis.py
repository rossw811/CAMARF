"""
CAMARF regime_conditional_analysis.py — research/comparison script, NOT
part of the production pipeline.

Tests whether confirmed pairs' mean-reversion properties differ descriptively
across macro regime states. The central question: does the RegimeClassifier's
per-bar regime output in analysis.py already capture structurally different
spread behavior, or are the regimes post-hoc labels on a uniform process?

Method:
  For each confirmed pair:
    1. Load aligned price data via load_aligned_pair.
    2. Reconstruct the spread: close_A - hedge_ratio_ols * close_B.
    3. Load macro regime data (yield_curve_regime, vix_regime) from macro.py's
       build() output — these are daily labels ffilled to the spread's bar
       frequency.
    4. Within each regime bucket, estimate the spread's half-life via OLS
       on (spread_t+1 - spread_t) ~ alpha * spread_t.
    5. Compare each regime's half-life against the pair's OWN full-series
       half-life via a simple ratio (hl_ratio = half_life_in_regime /
       half_life_full_series; <1.0 = faster mean-reversion in this regime).

Key output columns per pair-regime combination:
  half_life_in_regime, n_bars_in_regime, mean_abs_spread_in_regime,
  half_life_full_series, hl_ratio.

Doc-drift fix (Tier 6, Grand Sweep 2026-07-20): earlier versions of this
docstring described a "Welch t-test (unequal variance)" significance
comparison and a "whether the difference ... is significant" output column —
neither was ever actually implemented (confirmed directly: no ttest/scipy.stats
significance call exists anywhere in this file, and no "significant" column is
produced). This is a purely DESCRIPTIVE ratio comparison, not a formal
hypothesis test. Building the promised Welch t-test would be new statistical
methodology and needs its own sign-off before being added (CLAUDE.md's
working-style rule) — not silently invented here; this fix corrects the
documentation to match what the code actually does.

Usage:
    python research/regime_conditional_analysis.py
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aligned_pair_loader import load_aligned_pair
from data import _clean_close
from macro import build as macro_build

_OUT = "output/research/regime_conditional_analysis.parquet"
_TF_DIRS = [
    ("1min", "1m"), ("2min", "2m"), ("3min", "3m"), ("5min", "5m"),
    ("15min", "15m"), ("30min", "30m"), ("1hr", "1h"), ("4hr", "4h"),
]
_REGIME_COLS = ["yield_curve_regime", "vix_regime", "vix_term_structure"]
_MIN_BARS_PER_REGIME = 30


def _ols_half_life(spread):
    """OLS estimate of mean-reversion half-life from spread differences."""
    s = spread[np.isfinite(spread)]
    if len(s) < 20:
        return np.nan, np.nan
    delta = np.diff(s)
    lag = s[:-1]
    mask = np.isfinite(delta) & np.isfinite(lag)
    if mask.sum() < 20:
        return np.nan, np.nan
    d, l = delta[mask], lag[mask]
    # OLS: delta ~ alpha * lag => half_life = -log(2) / alpha
    try:
        slope, _, _, _, _ = stats.linregress(l, d)
    except Exception:
        return np.nan, np.nan
    if slope >= 0 or not np.isfinite(slope):
        return np.nan, slope
    hl = float(-np.log(2) / slope)
    return hl, float(slope)


def main():
    print("Loading macro regime data...")
    warnings.filterwarnings("ignore")
    macro = macro_build(force_refresh=False)
    regime_df = macro.data  # DatetimeIndex at NYSE daily frequency

    # Ensure regime columns present
    available = [c for c in _REGIME_COLS if c in regime_df.columns]
    if not available:
        print(f"No regime columns found in macro output. Available: {list(regime_df.columns)}")
        return
    print(f"Regime columns available: {available}")

    rows = []
    for tf_dir, tf_label in _TF_DIRS:
        path = f"output/results/{tf_dir}/pairs.parquet"
        if not os.path.exists(path):
            continue
        pairs = pd.read_parquet(path)
        print(f"\n[{tf_label}] {len(pairs)} pairs")

        for _, pair_row in pairs.iterrows():
            sym_a, sym_b = pair_row["symbol_a"], pair_row["symbol_b"]
            hedge = float(pair_row.get("hedge_ratio_ols", np.nan))
            if not np.isfinite(hedge):
                continue

            df_a, df_b = load_aligned_pair(sym_a, sym_b, tf_label)
            if df_a is None or df_b is None:
                continue

            close_a = pd.Series(_clean_close(df_a), index=df_a.index, name="a")
            close_b = pd.Series(_clean_close(df_b), index=df_b.index, name="b")
            combined = pd.concat([close_a, close_b], axis=1).dropna()
            if len(combined) < 100:
                continue

            spread = combined["a"] - hedge * combined["b"]

            # Map daily macro regimes to the spread's bar frequency (ffill by date)
            spread_dates = spread.index.normalize()  # date component only
            for regime_col in available:
                regime_series = regime_df[regime_col].dropna()
                regime_map = regime_series.to_dict()

                # Map each bar to its daily regime (ffill within spread dates)
                regime_labels = []
                for d in spread_dates:
                    # find the most recent regime label at or before this date
                    candidates = regime_series[regime_series.index <= d]
                    lbl = candidates.iloc[-1] if len(candidates) > 0 else np.nan
                    regime_labels.append(lbl)
                regime_arr = pd.Series(regime_labels, index=spread.index)

                # Compute per-regime half-life
                unique_regimes = regime_arr.dropna().unique()
                regime_hls = {}
                for regime_val in unique_regimes:
                    mask = regime_arr == regime_val
                    sub = spread[mask]
                    if mask.sum() < _MIN_BARS_PER_REGIME:
                        continue
                    hl, slope = _ols_half_life(sub.values)
                    regime_hls[str(regime_val)] = {
                        "half_life": hl, "slope": slope, "n_bars": int(mask.sum()),
                        "mean_abs_spread": float(sub.abs().mean()),
                    }

                if not regime_hls:
                    continue

                # Baseline: full-series half-life
                hl_full, _ = _ols_half_life(spread.values)

                for regime_val, stats_dict in regime_hls.items():
                    rows.append({
                        "tf": tf_label, "symbol_a": sym_a, "symbol_b": sym_b,
                        "regime_col": regime_col, "regime_val": regime_val,
                        "half_life_in_regime": stats_dict["half_life"],
                        "mr_slope_in_regime": stats_dict["slope"],
                        "n_bars_in_regime": stats_dict["n_bars"],
                        "mean_abs_spread_in_regime": stats_dict["mean_abs_spread"],
                        "half_life_full_series": hl_full,
                        "hl_ratio": (stats_dict["half_life"] / hl_full
                                     if hl_full and np.isfinite(hl_full) and hl_full > 0
                                     else np.nan),
                    })

                if regime_hls:
                    vals = [f"{k}:{v['half_life']:.1f}" for k, v in regime_hls.items()
                            if np.isfinite(v['half_life'])]
                    print(f"  {sym_a}/{sym_b}  {regime_col}: {', '.join(vals)}  "
                          f"(full={hl_full:.1f})")

    if not rows:
        print("No results produced.")
        return

    out = pd.DataFrame(rows)

    print(f"\n=== Summary ===")
    print(f"Total rows: {len(out)}")
    print(f"\nPairs showing fastest mean-reversion (by regime):")
    fast = out[out["half_life_in_regime"].notna()].nsmallest(15, "half_life_in_regime")
    print(fast[["tf", "symbol_a", "symbol_b", "regime_col", "regime_val",
                "half_life_in_regime", "half_life_full_series", "hl_ratio",
                "n_bars_in_regime"]].to_string(index=False))

    print(f"\nMean half-life ratio by regime (hl_regime / hl_full; <1.0 = faster in this regime):")
    ratio_summary = (out.groupby(["regime_col", "regime_val"])["hl_ratio"]
                     .agg(["mean", "count"]).reset_index()
                     .rename(columns={"mean": "mean_hl_ratio", "count": "n_pairs"}))
    print(ratio_summary.sort_values(["regime_col", "mean_hl_ratio"]).to_string(index=False))

    os.makedirs(os.path.dirname(_OUT), exist_ok=True)
    out.to_parquet(_OUT, index=False)
    print(f"\nFull results written to {_OUT}")


if __name__ == "__main__":
    main()
