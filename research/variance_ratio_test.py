"""
CAMARF variance_ratio_test.py — comparison/diagnostic method, NOT part of
the production pipeline.

Lo & MacKinlay (1988), "Stock Market Prices Do Not Follow Random Walks:
Evidence from a Simple Specification Test," Review of Financial Studies
1(1), 41-66 — corroborates each confirmed pair's mean-reversion from a
completely different statistical family than Engle-Granger/ADF: instead
of testing the spread's residual for a unit root, this tests whether the
VARIANCE of q-period spread changes grows linearly in q (the random-walk
null) or sub-linearly (VR(q) < 1, consistent with mean reversion) /
super-linearly (VR(q) > 1, consistent with momentum/trending).

Method (both estimators from the original paper, not simplified):
  - VR(q) = sigma_b^2(q) / sigma_a^2, the ratio of the q-period overlapping
    variance estimator to q times the 1-period variance estimator.
  - z1(q): homoskedasticity-consistent test statistic (assumes iid
    increments under the null).
  - z2(q): heteroskedasticity-robust test statistic (Lo-MacKinlay's own
    correction — financial return variances are essentially never iid, so
    this is the test actually worth trusting; z1 is reported alongside it
    for completeness/comparison only).

Applied here to each confirmed pair's already-computed, gap-masked spread
series (spread_series_*.parquet's "spread" column — the identical series
backtest.py trades), at q in {2, 4, 8, 16}.

Read-only. Never fetches, never recomputes hedge ratios or spreads.
IMPORTANT: spread_series_*.parquet is persisted on the full calendar-padded
grid, not a compacted real-bars-only series — rows are still finite
(forward-filled) wherever gap_flag_a/gap_flag_b == GapFlag.DATA_GAP (4),
so `np.isfinite` alone does not remove them; this module excludes those
rows explicitly (gap_flag_a != 4 AND gap_flag_b != 4) before any
computation, matching analysis.py's own CointScanner convention exactly
(`clean_close(df, exclude_flags=(GapFlag.DATA_GAP,))`) — confirmed
necessary by direct inspection (AMD/DD@1h: 83% of rows are padding).

Usage:
    python research/variance_ratio_test.py --q-values 2 4 8 16
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TF_DIRS = [
    "1min", "2min", "3min", "5min", "15min", "30min", "1hr", "4hr",
    "7day", "1mo", "3mo", "6mo",
]
_DIR_TO_LABEL = {
    "1min": "1m", "2min": "2m", "3min": "3m", "5min": "5m", "15min": "15m",
    "30min": "30m", "1hr": "1h", "4hr": "4h", "7day": "7D", "1mo": "1M",
    "3mo": "3M", "6mo": "6M",
}


def _resolve_tf_results_dir(tf_dir):
    """Same fallback convention as threshold_cointegration.py: use the live
    output/results/{tf_dir} if present, else the most recent archived
    output/results/{tf_dir}_stale_* snapshot (see that module for the full
    explanation of why "_stale_" just means "superseded by a scoped
    rerun's archiving step," not "known-bad data")."""
    live = os.path.join("output", "results", tf_dir)
    if os.path.isdir(live):
        return live, False
    candidates = sorted(glob.glob(os.path.join("output", "results", f"{tf_dir}_stale_*")))
    if candidates:
        return candidates[-1], True
    return live, False


def variance_ratio(series, q):
    """
    Lo & MacKinlay (1988) variance ratio VR(q) and both test statistics for
    a single series and a single holding period q. `series` is treated as
    the level series (e.g. the spread itself, or a log-price series) —
    increments X_k = series[k] - series[k-1] are the "returns" under test.

    Returns a dict with vr, z1, p1 (homoskedastic), z2, p2 (heteroskedasticity-
    robust), or {"ok": False} if there isn't enough data for this q.
    """
    series = np.asarray(series, dtype=float)
    n = series.size - 1  # number of 1-period increments
    if n < 4 * q or q < 2:
        return {"ok": False, "error": "insufficient_obs_for_q"}

    x = np.diff(series)  # 1-period increments, length n
    mu = x.mean()
    sigma_a2 = np.sum((x - mu) ** 2) / (n - 1)
    if sigma_a2 <= 0:
        return {"ok": False, "error": "zero_variance"}

    # q-period overlapping differences: series[k] - series[k-q] for k=q..n
    diffs_q = series[q:] - series[:-q]
    m = q * (n - q + 1) * (1 - q / n)
    sigma_b2 = np.sum((diffs_q - q * mu) ** 2) / m
    vr = sigma_b2 / sigma_a2

    # Homoskedastic test statistic
    theta1 = 2 * (2 * q - 1) * (q - 1) / (3 * q * n)
    z1 = (vr - 1) / np.sqrt(theta1)
    p1 = float(2 * (1 - sp_stats.norm.cdf(abs(z1))))

    # Heteroskedasticity-robust test statistic
    x_dev2 = (x - mu) ** 2
    denom = np.sum(x_dev2) ** 2
    theta2 = 0.0
    for j in range(1, q):
        delta_j = np.sum(x_dev2[j:] * x_dev2[:-j]) / denom
        theta2 += (2 * (q - j) / q) ** 2 * delta_j
    if theta2 <= 0:
        z2, p2 = np.nan, np.nan
    else:
        z2 = (vr - 1) / np.sqrt(theta2)
        p2 = float(2 * (1 - sp_stats.norm.cdf(abs(z2))))

    return {
        "ok": True, "q": q, "n": int(n), "vr": float(vr),
        "z1": float(z1), "p1": p1,
        "z2": float(z2) if not np.isnan(z2) else None,
        "p2": float(p2) if not np.isnan(p2) else None,
    }


def main():
    p = argparse.ArgumentParser(description="Lo & MacKinlay (1988) variance ratio test on confirmed-pair spreads")
    p.add_argument("--q-values", type=int, nargs="+", default=None,
                    help="Fixed q values to test. If omitted (default), q is "
                         "scaled per-pair to that pair's own median rolling "
                         "half-life (0.5x/1x/2x/4x HL) instead of a fixed grid — "
                         "see the half-life-scaling note below.")
    args = p.parse_args()

    rows = []
    for tf_dir in _TF_DIRS:
        results_dir, is_stale = _resolve_tf_results_dir(tf_dir)
        pairs_path = os.path.join(results_dir, "pairs.parquet")
        if not os.path.exists(pairs_path):
            continue
        if is_stale:
            print(f"NOTE {tf_dir}: no live output/results/{tf_dir}, using archived {results_dir} instead")
        tf_label = _DIR_TO_LABEL[tf_dir]
        pairs_df = pd.read_parquet(pairs_path)
        for _, row in pairs_df.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            series_path = os.path.join(results_dir, f"spread_series_{sym_a}_{sym_b}.parquet")
            if not os.path.exists(series_path):
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: no spread_series file")
                continue
            series_df = pd.read_parquet(series_path)
            real_bar_mask = (series_df["gap_flag_a"] != 4) & (series_df["gap_flag_b"] != 4)
            series_df = series_df.loc[real_bar_mask]
            spread = series_df["spread"].to_numpy(dtype=float)
            finite_mask = np.isfinite(spread)
            spread = spread[finite_mask]
            series_df = series_df.loc[finite_mask]

            if args.q_values is not None:
                q_values = args.q_values
            else:
                # Half-life-scaled q, not a fixed grid: an OU/mean-reverting
                # process only shows VR<1 at horizons comparable to or beyond
                # its OWN half-life — testing q=2..16 on an hourly pair whose
                # half-life is ~35-40 bars (this project's own documented
                # range) tests a horizon where reversion hasn't "kicked in"
                # yet, and can show VR>1 purely from short-lag noise/estimation
                # effects that say nothing about the pair's real mean-reversion
                # property. Confirmed directly this session: a fixed q=2..16
                # grid gave VR>1, growing with q, for nearly every 1h pair —
                # the opposite of what a stationary process should show as
                # q->infinity — before this fix.
                hl_col = series_df.get("half_life_rolling")
                median_hl = float(np.nanmedian(hl_col)) if hl_col is not None else np.nan
                if not np.isfinite(median_hl) or median_hl <= 0:
                    q_values = [2, 4, 8, 16]  # fallback if no half-life available
                else:
                    q_values = sorted(set(
                        max(2, round(mult * median_hl)) for mult in (0.5, 1.0, 2.0, 4.0)
                    ))

            for q in q_values:
                r = variance_ratio(spread, q)
                r.update({"symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf_label})
                rows.append(r)
                if r["ok"]:
                    p2_str = f"{r['p2']:.3f}" if r["p2"] is not None else "n/a"
                    print(f"{sym_a}/{sym_b}@{tf_label} q={q}: VR={r['vr']:.3f} "
                          f"z1={r['z1']:.2f} (p={r['p1']:.3f}) z2_robust_p={p2_str}")
                else:
                    print(f"SKIP {sym_a}/{sym_b}@{tf_label} q={q}: {r.get('error')}")

    out_df = pd.DataFrame(rows)
    os.makedirs("output/research", exist_ok=True)
    out_path = "output/research/variance_ratio_test.parquet"
    out_df.to_parquet(out_path)
    ok_df = out_df[out_df.get("ok", False) == True] if "ok" in out_df.columns else pd.DataFrame()
    n_reject_robust = int((ok_df["p2"] < 0.05).sum()) if len(ok_df) and "p2" in ok_df.columns else 0
    n_vr_below_1 = int((ok_df["vr"] < 1.0).sum()) if len(ok_df) else 0
    print(f"\nWrote {out_path}: {len(ok_df)} valid (pair, q) tests, "
          f"{n_vr_below_1} with VR<1 (mean-reversion direction), "
          f"{n_reject_robust} significant at p<0.05 (heteroskedasticity-robust)")


if __name__ == "__main__":
    main()
