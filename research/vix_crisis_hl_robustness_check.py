"""
CAMARF research/vix_crisis_hl_robustness_check.py -- comparison/diagnostic
script, NOT part of the production pipeline (2026-08-05).

Session 13's regime_conditional_analysis.py found pairs mean-revert 11x
faster during VIX crisis (hl_ratio=0.09 vs. full-series average, vs. 3.9x
SLOWER in "normal" VIX) -- cited since as "the empirical motivator for
Layer 2's RegimeConditioner" (Development.md), but that finding's own
writeup flagged an unresolved caveat: "The 'crisis hl is shortest' result
may partly reflect that crisis periods have higher volatility, making the
spread move more and thus appear to 'mean-revert' faster via OLS. Needs
verification with z-score normalized spread (not raw spread level)." That
verification was never built. Ross asked (2026-08-05) whether VIX crisis
is an event worth exploiting for entries/exits -- this script resolves
the open caveat FIRST, since building an exploit strategy on a possibly-
artifactual number would be a real methodological risk.

REUSES regime_conditional_analysis.py's exact pair-loading, spread
reconstruction, and regime-mapping logic (same load_aligned_pair,
_clean_close, macro.py regime columns, same 1h focus -- the original
finding's own "1h multi-regime finding is directionally clear" scope,
since 1m-3m pairs span too few days to see more than one macro regime)
so this is an apples-to-apples re-test of the SAME claim, not a new
dataset that would confound the comparison.

THREE half-life estimators computed on the SAME per-regime spread data:
  1. RAW OLS -- identical to the original finding's method (baseline,
     should reproduce hl_ratio=0.09 for crisis / 3.9 for normal).
  2. Z-SCORE-NORMALIZED OLS -- spread standardized (subtract regime-
     specific mean, divide by regime-specific std) before the same OLS.
     NOTE, worked out before running: OLS half-life from a
     delta~alpha*lag regression is mathematically scale-invariant to a
     CONSTANT multiplicative rescaling of the whole series (delta'=c*delta,
     lag'=c*lag => slope unchanged) -- so if regime-specific z-scoring
     doesn't change hl_ratio, that is not surprising, it is confirmation of
     this algebra, not proof there's no artifact. Included anyway because
     it's the exact check Session 13's own writeup asked for, so the
     record should show it was actually run, not skipped because the
     answer was predictable.
  3. WINSORIZED ROBUST OLS -- the mechanistically more plausible artifact,
     motivated directly by this session's OWN Lévy jump-diffusion finding
     (0.04%-1.6% of bars are statistically detected jumps, confirmed at
     206-symbol scale, docs/FINDINGS.md #14): crisis regimes have very
     few bars per pair (n=28-58 in the original run), so a single jump bar
     -- a large delta following a large lag, before the price has mean-
     reverted from the jump -- could dominate a small-sample OLS slope
     estimate and LOOK like fast mean-reversion without the broad-based
     process actually being faster. Winsorizing spread deltas at the
     1st/99th percentile before the OLS regression directly tests whether
     the crisis-regime result survives removing that specific outlier
     channel.

If (1) and (2) roughly agree (expected, per the algebra above) but (3)
materially shrinks the crisis-vs-normal gap, that is real evidence the
original finding is partly jump/outlier-driven, not a uniform faster-
reversion effect -- and any entry/exit rule built on it needs to account
for that (e.g., trigger on regime, not on the exact half-life magnitude).
If all three agree, the original finding is corroborated by an
independent, more skeptical method and is safe to build on directly.

Usage:
    python research/vix_crisis_hl_robustness_check.py
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
import ml

_OUT = "output/research/vix_crisis_hl_robustness_check.parquet"
_TF_LABEL = "1h"
_MIN_BARS_PER_REGIME = 30
_WINSOR_PCT = 0.01  # 1st/99th percentile


def _ols_half_life(delta, lag):
    mask = np.isfinite(delta) & np.isfinite(lag)
    if mask.sum() < 20:
        return np.nan, np.nan
    d, l = delta[mask], lag[mask]
    try:
        slope, *_ = stats.linregress(l, d)
    except Exception:
        return np.nan, np.nan
    if slope >= 0 or not np.isfinite(slope):
        return np.nan, slope
    return float(-np.log(2) / slope), float(slope)


def half_life_raw(spread):
    s = spread[np.isfinite(spread)]
    if len(s) < 20:
        return np.nan
    hl, _ = _ols_half_life(np.diff(s), s[:-1])
    return hl


def half_life_zscored(spread):
    """Regime-specific z-score: (spread - mean) / std, THEN OLS half-life.
    Mathematically expected to reproduce half_life_raw's slope exactly
    (see module docstring) -- run anyway per Session 13's own request."""
    s = spread[np.isfinite(spread)]
    if len(s) < 20:
        return np.nan
    std = s.std()
    if not np.isfinite(std) or std <= 0:
        return np.nan
    z = (s - s.mean()) / std
    hl, _ = _ols_half_life(np.diff(z), z[:-1])
    return hl


def half_life_winsorized(spread, pct=_WINSOR_PCT):
    """OLS half-life after winsorizing the DELTA series at the given
    percentile -- directly tests whether a small number of large jumps
    (this session's own Lévy jump-diffusion finding) are driving the
    crisis-regime result in a small (n=28-58 bar) sample."""
    s = spread[np.isfinite(spread)]
    if len(s) < 20:
        return np.nan
    delta = np.diff(s)
    lag = s[:-1]
    mask = np.isfinite(delta) & np.isfinite(lag)
    if mask.sum() < 20:
        return np.nan
    d, l = delta[mask], lag[mask]
    lo, hi = np.percentile(d, [pct * 100, (1 - pct) * 100])
    d_w = np.clip(d, lo, hi)
    hl, _ = _ols_half_life(d_w, l)
    return hl


def main():
    print("Loading macro regime data...")
    warnings.filterwarnings("ignore")
    macro = macro_build(force_refresh=False)
    regime_df = macro.data

    if "vix_regime" not in regime_df.columns:
        print(f"vix_regime not found. Available: {list(regime_df.columns)}")
        return

    # SCOPE NOTE (2026-08-05): the original Session 13 finding read 1h
    # pairs from output/results/1hr/pairs.parquet, which existed under the
    # pre-WRDS confirmed universe. That directory no longer exists -- the
    # current WRDS-primary confirmed set (IQV/Q@1D, KVUE/KMB@3m, PNC/ZION@4h)
    # has no 1h-confirmed pairs at all (a direct consequence of the same
    # universe collapse documented throughout this session). Rather than
    # skip the check, this re-derives the SAME underlying pairs' 1h price
    # dynamics directly from cache (which does still exist at 1h for all
    # 3 symbols) and fits a fresh full-sample OLS hedge ratio for
    # break-scanning purposes -- same disclosed simplification
    # structural_break_onset_detection.py::compute_ols_spread already
    # uses, not the production PIT hedge ratio (this module is a
    # diagnostic, not a trading signal).
    confirmed = ml._discover_confirmed_pairs()
    pairs = sorted(set((a, b) for a, b, _tf in confirmed))
    print(f"Testing {len(pairs)} currently-confirmed pairs' 1h dynamics (pairs.parquet no longer "
          f"has a native 1hr entry under the current WRDS-primary universe -- see module comment)")

    regime_series = regime_df["vix_regime"].dropna()

    rows = []
    for sym_a, sym_b in pairs:
        df_a, df_b = load_aligned_pair(sym_a, sym_b, _TF_LABEL)
        if df_a is None or df_b is None:
            continue
        close_a = pd.Series(_clean_close(df_a), index=df_a.index, name="a")
        close_b = pd.Series(_clean_close(df_b), index=df_b.index, name="b")
        combined = pd.concat([close_a, close_b], axis=1).dropna()
        if len(combined) < 100:
            continue
        b_c = combined["b"] - combined["b"].mean()
        a_c = combined["a"] - combined["a"].mean()
        var_b = float(np.dot(b_c, b_c))
        if var_b <= 0:
            continue
        hedge = float(np.dot(a_c, b_c) / var_b)
        spread = combined["a"] - hedge * combined["b"]

        spread_dates = spread.index.normalize()
        regime_labels = []
        for d in spread_dates:
            candidates = regime_series[regime_series.index <= d]
            regime_labels.append(candidates.iloc[-1] if len(candidates) > 0 else np.nan)
        regime_arr = pd.Series(regime_labels, index=spread.index)

        hl_full_raw = half_life_raw(spread.values)
        hl_full_z = half_life_zscored(spread.values)
        hl_full_w = half_life_winsorized(spread.values)

        for regime_val in regime_arr.dropna().unique():
            mask = regime_arr == regime_val
            n_bars = int(mask.sum())
            if n_bars < _MIN_BARS_PER_REGIME:
                continue
            sub = spread[mask].values
            hl_raw = half_life_raw(sub)
            hl_z = half_life_zscored(sub)
            hl_w = half_life_winsorized(sub)
            rows.append({
                "symbol_a": sym_a, "symbol_b": sym_b, "vix_regime": str(regime_val),
                "n_bars": n_bars,
                "hl_raw": hl_raw, "hl_ratio_raw": hl_raw / hl_full_raw if hl_full_raw and hl_full_raw > 0 else np.nan,
                "hl_zscored": hl_z, "hl_ratio_zscored": hl_z / hl_full_z if hl_full_z and hl_full_z > 0 else np.nan,
                "hl_winsorized": hl_w, "hl_ratio_winsorized": hl_w / hl_full_w if hl_full_w and hl_full_w > 0 else np.nan,
            })

    if not rows:
        print("No usable pair-regime combinations -- nothing to report.")
        return

    out_df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(_OUT), exist_ok=True)
    out_df.to_parquet(_OUT)

    print(f"\n{'='*70}\nRESULT: hl_ratio by vix_regime, three estimators (n_pairs shown)\n{'='*70}")
    summary = out_df.groupby("vix_regime").agg(
        n_pairs=("symbol_a", "count"),
        mean_hl_ratio_raw=("hl_ratio_raw", "mean"),
        mean_hl_ratio_zscored=("hl_ratio_zscored", "mean"),
        mean_hl_ratio_winsorized=("hl_ratio_winsorized", "mean"),
    ).sort_values("mean_hl_ratio_raw")
    print(summary.to_string())

    if "crisis" in summary.index:
        raw_c = summary.loc["crisis", "mean_hl_ratio_raw"]
        wins_c = summary.loc["crisis", "mean_hl_ratio_winsorized"]
        z_c = summary.loc["crisis", "mean_hl_ratio_zscored"]
        print(f"\nCrisis regime: raw={raw_c:.3f}, z-scored={z_c:.3f}, winsorized={wins_c:.3f}")
        if np.isfinite(raw_c) and np.isfinite(wins_c) and raw_c > 0:
            shrink_pct = (wins_c - raw_c) / raw_c * 100
            print(f"Winsorized vs. raw shift: {shrink_pct:+.1f}%")
            if shrink_pct > 50:
                print("SUBSTANTIAL shrinkage under winsorization -- real evidence the raw result is "
                      "partly outlier/jump-driven, not a uniform faster-reversion effect.")
            else:
                print("No substantial shrinkage under winsorization -- the faster-reversion effect "
                      "survives outlier-robust re-estimation, corroborating the original finding.")

    print(f"\nSaved -> {_OUT}")


if __name__ == "__main__":
    main()
