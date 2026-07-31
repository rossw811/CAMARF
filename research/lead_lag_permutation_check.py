"""
CAMARF lead_lag_permutation_check.py — comparison/robustness method, NOT
part of the production pipeline.

Direct generalization of eg_permutation_check.py's circular-shift null
to the lag-search context, built per Ross's direction (2026-06-24)
after near_miss_lag_scan.py flagged 9 near-miss pairs with a real
correlation lift at a non-zero lag — a tight, sector-clustered set
(regional banks around UCB, asset managers BX/ARES leading STEP,
semiconductors DIOD/VSH, semicap AEIS/MKSI — see Development.md
Session 11).

The problem this corrects: searching K=21 lags per pair is extra
researcher degrees of freedom. Even two UNRELATED series will show SOME
lag, by chance, with a better correlation than lag 0 —
lead_lag_scan.py's own synthetic test already demonstrated a version of
this (the deliberately-wrong lag-0 alignment still showed nominal EG
significance). Applying lag-0's calibrated threshold to a "best of 21"
result is statistically invalid; this script builds the correct null.

Method, generalizing eg_permutation_check.py's circular-shift approach:
for each candidate pair, run the SAME two-stage procedure
lead_lag_scan.py uses on the real data (best lag via correlation sweep,
then EG confirmation at that lag only) — call this the real result.
Then build a null distribution by circularly shifting one leg's series N
times (random shift, wrap-around — preserves that leg's own
autocorrelation/trend, breaks only the true cross-alignment) and running
the IDENTICAL two-stage procedure on each shifted null. The permutation
p-value is the fraction of null draws at least as extreme as the real
result. This answers "is the real pair's best-of-K-lags result better
than what circularly-shifted (no true relationship) data ALSO achieves
when given the same K-lag search freedom" — the correct null, unlike
comparing against a lag-0-calibrated threshold.

Read-only. Loads cached price data via aligned_pair_loader.load_aligned_pair
(fixed 2026-06-24 — raw DataStore.load() output has no gap_flag column,
so _gap_aware_returns silently skipped all gap masking including the
overnight/weekend-spanning return; see Development.md Session 11) —
never fetches.

Usage:
    python research/lead_lag_permutation_check.py --pairs-file output/research/near_miss_lag_scan_1h.parquet --tf 1h
    python research/lead_lag_permutation_check.py --symbol-a UCB --symbol-b CATY --tf 1h
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aligned_pair_loader import load_aligned_pair
from analysis import Config
from data import DataStore, _gap_aware_returns
from lead_lag_scan import _eg_pvalue, _gap_masked_log_price, best_lag, lagged_corr_scan


def two_stage_result(ret_a, ret_b, logp_a, logp_b, max_lag, max_eg_lag=None):
    """The real (or null) two-stage procedure: best lag via correlation
    sweep, then EG confirm at that lag only (skipped if max_eg_lag is
    None). Returns (best_lag, best_corr, eg_p_at_best_lag) — eg_p is
    None when max_eg_lag is None or insufficient EG sample size."""
    scan = lagged_corr_scan(ret_a, ret_b, max_lag)
    k_star, c_star, n_star = best_lag(scan)
    if k_star is None:
        return None, None, None
    if max_eg_lag is None or logp_a is None or logp_b is None:
        return k_star, c_star, None
    shifted_b = logp_b.shift(-k_star)
    joined = pd.concat([logp_a, shifted_b], axis=1, join="inner").dropna()
    eg_p, n_eg = _eg_pvalue(joined.iloc[:, 0].values, joined.iloc[:, 1].values, max_eg_lag)
    return k_star, c_star, eg_p


def run_test(symbol_a, symbol_b, tf_label, max_lag=10, n_perm=500, seed=42, run_eg=True):
    rng = np.random.default_rng(seed)
    max_eg_lag = Config.ANALYSIS.EG_MAX_LAG if run_eg else None

    df_a, df_b = load_aligned_pair(symbol_a, symbol_b, tf_label)
    if df_a is None or df_b is None:
        return {"status": "missing_cache"}

    ret_a = pd.Series(_gap_aware_returns(df_a), index=df_a.index)
    ret_b = pd.Series(_gap_aware_returns(df_b), index=df_b.index)
    logp_a = pd.Series(_gap_masked_log_price(df_a), index=df_a.index) if run_eg else None
    logp_b = pd.Series(_gap_masked_log_price(df_b), index=df_b.index) if run_eg else None

    real_lag, real_corr, real_eg_p = two_stage_result(ret_a, ret_b, logp_a, logp_b, max_lag, max_eg_lag)
    if real_lag is None:
        return {"status": "insufficient_data"}

    n = len(ret_b)
    null_corrs, null_eg_ps = [], []
    for _ in range(n_perm):
        shift = int(rng.integers(1, n))
        shifted_ret_b = pd.Series(np.roll(ret_b.values, shift), index=ret_b.index)
        shifted_logp_b = (
            pd.Series(np.roll(logp_b.values, shift), index=logp_b.index) if run_eg else None
        )

        k_null, c_null, p_null = two_stage_result(
            ret_a, shifted_ret_b, logp_a, shifted_logp_b, max_lag, max_eg_lag
        )
        if c_null is not None:
            null_corrs.append(abs(c_null))
        if p_null is not None:
            null_eg_ps.append(p_null)

    null_corrs = np.array(null_corrs)
    null_eg_ps = np.array(null_eg_ps)

    corr_perm_p = (
        (1 + np.sum(null_corrs >= abs(real_corr))) / (len(null_corrs) + 1)
        if len(null_corrs) else None
    )
    eg_perm_p = (
        (1 + np.sum(null_eg_ps <= real_eg_p)) / (len(null_eg_ps) + 1)
        if (len(null_eg_ps) and real_eg_p is not None) else None
    )

    return {
        "status": "ok", "symbol_a": symbol_a, "symbol_b": symbol_b, "tf": tf_label,
        "real_best_lag": real_lag, "real_best_corr": real_corr, "real_eg_p": real_eg_p,
        "n_perm_corr": len(null_corrs), "n_perm_eg": len(null_eg_ps),
        "corr_perm_pvalue": corr_perm_p, "eg_perm_pvalue": eg_perm_p,
        "mean_abs_null_corr": float(np.mean(null_corrs)) if len(null_corrs) else None,
    }


def main():
    p = argparse.ArgumentParser(description="Permutation-corrected best-of-K-lags significance test (2026-06-24)")
    p.add_argument("--pairs-file", default=None,
                    help="Parquet with symbol_a/symbol_b columns (e.g. near_miss_lag_scan output)")
    p.add_argument("--symbol-a", default=None)
    p.add_argument("--symbol-b", default=None)
    p.add_argument("--tf", default="1h")
    p.add_argument("--max-lag", type=int, default=10)
    p.add_argument("--n-perm", type=int, default=500)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    if args.pairs_file:
        pairs_df = pd.read_parquet(args.pairs_file)
        targets = list(zip(pairs_df["symbol_a"], pairs_df["symbol_b"]))
    elif args.symbol_a and args.symbol_b:
        targets = [(args.symbol_a, args.symbol_b)]
    else:
        print("Provide either --pairs-file or --symbol-a/--symbol-b.")
        return

    rows = []
    for sym_a, sym_b in targets:
        result = run_test(sym_a, sym_b, args.tf, max_lag=args.max_lag, n_perm=args.n_perm, seed=args.seed)
        if result["status"] != "ok":
            print(f"{sym_a}/{sym_b}@{args.tf}: {result['status']}")
            continue
        rows.append(result)
        sig = "SIG" if (result["corr_perm_pvalue"] is not None and result["corr_perm_pvalue"] < 0.05) else "ns "
        print(f"{sig} {sym_a}/{sym_b}@{args.tf}: best_lag={result['real_best_lag']} "
              f"corr={result['real_best_corr']:.3f} eg_p={result['real_eg_p']} "
              f"corr_perm_p={result['corr_perm_pvalue']:.4f} eg_perm_p={result['eg_perm_pvalue']}")

    if not rows:
        print("No results.")
        return

    result_df = pd.DataFrame(rows)
    sig_df = result_df[result_df["corr_perm_pvalue"] < 0.05]
    print(f"\n{len(sig_df)}/{len(result_df)} pairs remain significant after the "
          f"look-elsewhere correction (corr_perm_pvalue < 0.05).")
    if not sig_df.empty:
        print(sig_df[["symbol_a", "symbol_b", "real_best_lag", "real_best_corr",
                       "corr_perm_pvalue", "eg_perm_pvalue"]].to_string(index=False))

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    safe_tf = DataStore._TF_SAFE.get(args.tf, args.tf.lower())
    out_path = os.path.join(out_dir, f"lead_lag_permutation_check_{safe_tf}.parquet")
    result_df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
