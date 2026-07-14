"""
CAMARF lag_sweep_validation.py — methodology validation, NOT part of the
production pipeline. Task #52 (2026-07-13).

Ross's concern: every existing lead-lag module (lead_lag_scan.py,
near_miss_lag_scan.py, lag_aware_cointegration_discovery.py) reports a
single "best lag" collapsed from lagged_corr_scan()'s internal dict — never
the full profile across the lag range. Three independent prior modules on
this universe all found "no exploitable lag structure" (lead_lag_scan.py:
lag-0 dominant; cross_session_leadlag.py: mostly null;
lag_aware_cointegration_discovery.py: 0/2 near-miss pairs survived BY
correction). Before trusting that convergent null, this checks whether the
underlying lag-search MACHINERY itself is sound, not just its conclusions.

Method: reuse lagged_corr_scan() (research/lead_lag_scan.py) and
_eg_pvalue() (also lead_lag_scan.py) directly — no reimplementation — and
report the FULL profile (correlation AND EG p-value at every lag in
[-max_lag, max_lag], both directions) for two groups:
  1. Known-confirmed pairs (already cointegrated at lag 0 by construction,
     since that's how they were selected) — the positive control. If the
     machinery works, these should show a coherent, interpretable
     structure with lag 0 special (at or very near the |corr| peak, EG
     significant at/near lag 0).
  2. Comparison pairs with no known relationship (random cross-sector
     pairs) plus the 2 pairs already flagged by the existing (stale,
     pre-universe-expansion, 2026-06-28) near_miss_lag_scan.py output —
     the negative-ish control. These should NOT show a clean lag-0-special
     structure (or, for the 2 flagged near-miss pairs, should show
     whatever structure led to their original flag, evaluated honestly
     here rather than assumed).

This is a DIAGNOSTIC on the search mechanism, not a new discovery tool —
it does not by itself confirm or reject any pair as tradeable.

Read-only. Loads cached price data via aligned_pair_loader.load_aligned_pair
— never fetches, never writes to output/cache/.

Usage:
    python research/lag_sweep_validation.py --tf 1h --max-lag 20
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aligned_pair_loader import load_aligned_pair
from analysis import Config
from data import _gap_aware_returns
from lead_lag_scan import _eg_pvalue, _gap_masked_log_price, lagged_corr_scan

_MIN_EG_N = 60


def full_lag_sweep(ret_a, ret_b, logp_a, logp_b, max_lag, max_eg_lag, compute_eg=True):
    """Core, independently-testable logic. ret_a/ret_b: gap-aware return
    Series. logp_a/logp_b: gap-masked log-price Series (None to skip EG).
    lag>0 means A leads B by `lag` bars (matches lagged_corr_scan's own
    documented convention exactly — inherited, not redefined).
    Returns a DataFrame with one row per lag in [-max_lag, max_lag]:
    lag, corr, n_corr, eg_p, n_eg."""
    corr_scan = lagged_corr_scan(ret_a, ret_b, max_lag)
    rows = []
    for lag in range(-max_lag, max_lag + 1):
        c, n_corr = corr_scan[lag]
        eg_p, n_eg = None, None
        if compute_eg and logp_a is not None and logp_b is not None:
            shifted_b = logp_b.shift(-lag)
            joined = pd.concat([logp_a, shifted_b], axis=1, join="inner").dropna()
            if len(joined) >= _MIN_EG_N:
                eg_p, n_eg = _eg_pvalue(joined.iloc[:, 0].values, joined.iloc[:, 1].values, max_eg_lag)
        rows.append({"lag": lag, "corr": c, "n_corr": n_corr, "eg_p": eg_p, "n_eg": n_eg})
    return pd.DataFrame(rows)


def sweep_diagnostics(sweep_df):
    """Summarize a full_lag_sweep() DataFrame into pass/fail-relevant
    diagnostics for the sanity check, not a verdict by itself."""
    valid_corr = sweep_df.dropna(subset=["corr"])
    if valid_corr.empty:
        return {"status": "no_valid_corr"}
    abs_corr = valid_corr["corr"].abs()
    argmax_idx = abs_corr.idxmax()
    argmax_lag = int(valid_corr.loc[argmax_idx, "lag"])
    argmax_corr = float(valid_corr.loc[argmax_idx, "corr"])
    corr_at_0_row = valid_corr[valid_corr["lag"] == 0]
    corr_at_0 = float(corr_at_0_row["corr"].iloc[0]) if not corr_at_0_row.empty else None
    # "lag 0 is at or very near the peak" -- within 3 lags of the argmax,
    # OR |corr(0)| is within 10% (relative) of the peak magnitude.
    near_zero_is_peak = None
    if corr_at_0 is not None:
        near_zero_is_peak = (abs(argmax_lag) <= 3) or (
            abs(argmax_corr) > 0 and abs(abs(corr_at_0) - abs(argmax_corr)) / abs(argmax_corr) < 0.10
        )
    eg_valid = sweep_df.dropna(subset=["eg_p"])
    eg_p_at_0 = None
    if not eg_valid.empty:
        row0 = eg_valid[eg_valid["lag"] == 0]
        eg_p_at_0 = float(row0["eg_p"].iloc[0]) if not row0.empty else None
    n_eg_significant = int((eg_valid["eg_p"] < 0.05).sum()) if not eg_valid.empty else 0
    return {
        "status": "ok",
        "argmax_abs_corr_lag": argmax_lag,
        "argmax_corr": argmax_corr,
        "corr_at_lag0": corr_at_0,
        "near_zero_is_peak": near_zero_is_peak,
        "eg_p_at_lag0": eg_p_at_0,
        "n_lags_eg_significant": n_eg_significant,
        "n_lags_eg_tested": len(eg_valid),
    }


def run_pair_sweep(symbol_a, symbol_b, tf_label, max_lag, max_eg_lag, compute_eg=True):
    """Load + sweep one real pair. Returns (sweep_df, diagnostics) or
    (None, {"status": "missing_cache"/...})."""
    df_a, df_b = load_aligned_pair(symbol_a, symbol_b, tf_label)
    if df_a is None or df_b is None:
        return None, {"status": "missing_cache"}
    ret_a = pd.Series(_gap_aware_returns(df_a), index=df_a.index)
    ret_b = pd.Series(_gap_aware_returns(df_b), index=df_b.index)
    logp_a = pd.Series(_gap_masked_log_price(df_a), index=df_a.index) if compute_eg else None
    logp_b = pd.Series(_gap_masked_log_price(df_b), index=df_b.index) if compute_eg else None
    sweep_df = full_lag_sweep(ret_a, ret_b, logp_a, logp_b, max_lag, max_eg_lag, compute_eg)
    diag = sweep_diagnostics(sweep_df)
    return sweep_df, diag


def main():
    p = argparse.ArgumentParser(description="Lag-sweep methodology validation (task #52, 2026-07-13)")
    p.add_argument("--tf", default="1h")
    p.add_argument("--max-lag", type=int, default=20)
    p.add_argument("--pairs-file", default=None,
                    help="Optional parquet with symbol_a/symbol_b columns to sweep instead of the defaults")
    args = p.parse_args()
    max_eg_lag = Config.ANALYSIS.EG_MAX_LAG

    # Group 1: known-confirmed pairs (positive control). Pulled directly
    # from the last complete real analysis.py output (see caller notes in
    # Development.md for exactly which run this came from — the manifest
    # may be mid-refresh from a concurrent background pipeline run at the
    # time this executes, so this uses the archived-but-real 1hr pairs
    # output, not the live manifest, and says so explicitly).
    confirmed_pairs = [
        ("LNT", "VTR"), ("LNT", "WELL"), ("AXP", "CRWD"), ("AME", "DD"), ("AME", "MAR"),
        ("AMAT", "DD"), ("APP", "CRWD"), ("AVGO", "CRWD"), ("CAT", "DD"), ("CMS", "DUK"),
        ("FIX", "MLI"), ("DE", "DD"), ("DAL", "DD"), ("EME", "MLI"), ("EG", "WRB"),
        ("GS", "MLI"), ("HAL", "NOV"), ("MET", "TMHC"), ("PFG", "STLD"), ("VRT", "MTZ"),
        ("QQQ", "MLI"), ("FHN", "MLI"), ("MTSI", "WCC"), ("UMBF", "FHB"),
    ]

    # Group 2: comparison pairs -- 2 real near-miss pairs already flagged
    # by the existing (stale, pre-expansion, 2026-06-28) near_miss_lag_scan.py
    # output, plus 6 hand-picked cross-sector pairs with no known
    # relationship (arbitrary symbols from unrelated sectors already
    # present in the confirmed-pair list above, deliberately mismatched).
    comparison_pairs = [
        ("CVSA", "STEP"), ("MPT", "SPG"),  # real flagged near-miss (stale scan)
        ("LNT", "HAL"), ("CAT", "WRB"), ("DUK", "MTSI"), ("STLD", "VTR"),
        ("FHB", "EME"), ("QQQ", "GS"),  # arbitrary cross-sector, no known relationship
    ]

    if args.pairs_file:
        pf = pd.read_parquet(args.pairs_file)
        confirmed_pairs = []
        comparison_pairs = list(zip(pf["symbol_a"], pf["symbol_b"]))

    def run_group(pairs, label):
        print(f"\n=== {label} ({len(pairs)} pairs) ===")
        results = []
        for sym_a, sym_b in pairs:
            sweep_df, diag = run_pair_sweep(sym_a, sym_b, args.tf, args.max_lag, max_eg_lag)
            if diag.get("status") != "ok":
                print(f"  {sym_a}/{sym_b}: {diag.get('status')}")
                continue
            diag_row = {"symbol_a": sym_a, "symbol_b": sym_b, **diag}
            results.append(diag_row)
            print(f"  {sym_a}/{sym_b}: argmax_lag={diag['argmax_abs_corr_lag']:+3d} "
                  f"argmax_corr={diag['argmax_corr']:.3f} corr@0={diag['corr_at_lag0']:.3f} "
                  f"near_zero_is_peak={diag['near_zero_is_peak']} "
                  f"eg_p@0={diag['eg_p_at_lag0']} "
                  f"n_eg_sig={diag['n_lags_eg_significant']}/{diag['n_lags_eg_tested']}")
        return pd.DataFrame(results)

    confirmed_df = run_group(confirmed_pairs, "GROUP 1: known-confirmed pairs (positive control)")
    comparison_df = run_group(comparison_pairs, "GROUP 2: comparison pairs (near-miss + random)")

    print("\n=== SUMMARY ===")
    if not confirmed_df.empty:
        frac_near_zero = confirmed_df["near_zero_is_peak"].mean()
        print(f"Group 1 (confirmed pairs): {frac_near_zero:.1%} show lag-0 at or near the |corr| peak "
              f"({int(confirmed_df['near_zero_is_peak'].sum())}/{len(confirmed_df)}).")
        print(f"Group 1 mean EG p-value at lag 0: {confirmed_df['eg_p_at_lag0'].mean():.4f} "
              f"(median n_lags_eg_significant: {confirmed_df['n_lags_eg_significant'].median()})")
    if not comparison_df.empty:
        frac_near_zero_cmp = comparison_df["near_zero_is_peak"].mean()
        print(f"Group 2 (comparison pairs): {frac_near_zero_cmp:.1%} show lag-0 at or near the |corr| peak "
              f"({int(comparison_df['near_zero_is_peak'].sum())}/{len(comparison_df)}).")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    if not confirmed_df.empty:
        confirmed_df.to_parquet(os.path.join(out_dir, f"lag_sweep_validation_confirmed_{args.tf}.parquet"))
    if not comparison_df.empty:
        comparison_df.to_parquet(os.path.join(out_dir, f"lag_sweep_validation_comparison_{args.tf}.parquet"))
    print(f"\nFull results written to {out_dir}/lag_sweep_validation_{{confirmed,comparison}}_{args.tf}.parquet")


if __name__ == "__main__":
    main()
