"""
CAMARF eg_permutation_check.py — comparison/robustness method, NOT part
of the production pipeline.

Idea #4 from Development.md's Session 10 academic backlog, reframed per
Ross's direction (2026-06-23): knockoff filters don't transplant cleanly
onto this project's pairwise-hypothesis-testing setup (they're built for
variable selection in regression, not many independent-ish tests with
shared-leg dependence). This is the substitute Ross approved: a
circular-shift permutation robustness check on the EXISTING Engle-
Granger screen, run ALONGSIDE production BH-FDR (production is
untouched) rather than replacing it.

Method: for each currently-confirmed pair, recompute the IDENTICAL EG
test analysis.py's CointScanner._eg_worker uses (coint(a, b, trend="c",
maxlag=Config.ANALYSIS.EG_MAX_LAG, autolag="aic"), same gap-masked
log-prices via data.py's _clean_close). Then build a null distribution
by circularly shifting one leg's log-price series by a random amount
(wrap-around) and recomputing EG — circular shift preserves each
series' OWN autocorrelation/trend structure (unlike i.i.d. shuffling,
which would destroy it and test the wrong null) while breaking the
actual temporal alignment between the two legs. The permutation p-value
is the fraction of shifted-null EG p-values at least as extreme as the
real one. A pair whose real EG p-value is significant but whose
permutation p-value is not is a candidate false positive that BH-FDR's
classical independence-leaning guarantee would not have flagged.

This also directly corroborates (or refutes) BUG-D49's open question for
the implicated symbols (APAM/AZTA/INVX/NBHC): if their apparent
cointegration is mostly an artifact of each series' own near-constant
structure rather than genuine temporal co-movement, circular-shift
permutation should show a high rate of "accidentally significant" shifts
too.

Read-only. Loads cached price data directly via DataStore.load — never
fetches.

Usage:
    python eg_permutation_check.py --n-perm 500
"""
import argparse
import os

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

from analysis import Config
from data import DataStore, _clean_close

_TF_DIRS = [
    "1min", "2min", "3min", "5min", "15min", "30min", "1hr", "4hr",
    "7day", "1mo", "3mo", "6mo",
]
_DIR_TO_LABEL = {
    "1min": "1m", "2min": "2m", "3min": "3m", "5min": "5m", "15min": "15m",
    "30min": "30m", "1hr": "1h", "4hr": "4h", "7day": "7D", "1mo": "1M",
    "3mo": "3M", "6mo": "6M",
}


def _gap_masked_log_price(df):
    close = _clean_close(df)  # NaN at DATA_GAP bars, matches production
    with np.errstate(invalid="ignore", divide="ignore"):
        log_p = np.log(close)
    log_p[~np.isfinite(log_p)] = np.nan
    return log_p


def _eg_pvalue(a, b, max_lag):
    mask = np.isfinite(a) & np.isfinite(b)
    a_, b_ = a[mask], b[mask]
    if a_.size < 60:
        return None
    try:
        _, pval, _ = coint(a_, b_, trend="c", maxlag=max_lag, autolag="aic")
        return float(pval)
    except Exception:
        return None


def _circular_shift_null(a, b, max_lag, n_perm, rng):
    """Shift b by a random amount (wrap-around), preserving b's own
    autocorrelation structure while breaking temporal alignment with a."""
    n = len(b)
    null_pvals = []
    for _ in range(n_perm):
        shift = rng.integers(1, n)  # never shift==0 (that's the real data)
        b_shifted = np.roll(b, shift)
        p = _eg_pvalue(a, b_shifted, max_lag)
        if p is not None:
            null_pvals.append(p)
    return np.array(null_pvals)


def main():
    p = argparse.ArgumentParser(description="EG permutation robustness check (idea #4)")
    p.add_argument("--n-perm", type=int, default=500)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    rng = np.random.default_rng(args.seed)
    max_lag = Config.ANALYSIS.EG_MAX_LAG

    rows = []
    for tf_dir in _TF_DIRS:
        path = f"output/results/{tf_dir}/pairs.parquet"
        if not os.path.exists(path):
            continue
        tf_label = _DIR_TO_LABEL[tf_dir]
        df = pd.read_parquet(path)
        for _, row in df.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            df_a = DataStore.load(sym_a, tf_label)
            df_b = DataStore.load(sym_b, tf_label)
            if df_a is None or df_b is None:
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: cache missing")
                continue
            log_a = _gap_masked_log_price(df_a)
            log_b = _gap_masked_log_price(df_b)
            joined = pd.DataFrame({"a": log_a}, index=df_a.index).join(
                pd.DataFrame({"b": log_b}, index=df_b.index), how="inner"
            )
            if len(joined) < 60:
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: only {len(joined)} "
                      f"overlapping bars (<60)")
                continue
            a_vals, b_vals = joined["a"].values, joined["b"].values

            real_p = _eg_pvalue(a_vals, b_vals, max_lag)
            if real_p is None:
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: EG failed on real data")
                continue
            null_pvals = _circular_shift_null(a_vals, b_vals, max_lag, args.n_perm, rng)
            if len(null_pvals) == 0:
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: all permutations failed")
                continue
            perm_p = (1 + np.sum(null_pvals <= real_p)) / (len(null_pvals) + 1)
            frac_null_significant = float(np.mean(null_pvals < 0.05))
            divergent = (real_p < 0.05) and (perm_p >= 0.05)
            rows.append({
                "tf": tf_label, "symbol_a": sym_a, "symbol_b": sym_b,
                "real_eg_pvalue": real_p, "permutation_pvalue": perm_p,
                "null_frac_significant": frac_null_significant,
                "n_perm_used": len(null_pvals), "n_overlap": len(joined),
                "flagged_divergent": divergent,
            })
            status = "FLAG" if divergent else "ok"
            print(f"{status:5s} {sym_a}/{sym_b}@{tf_label}: real_p={real_p:.4f} "
                  f"perm_p={perm_p:.4f} null_frac_sig={frac_null_significant:.3f} "
                  f"(n_overlap={len(joined)})")

    if not rows:
        print("No confirmed pairs with sufficient data found.")
        return

    result_df = pd.DataFrame(rows)
    flagged = result_df[result_df["flagged_divergent"]]
    print(f"\n{len(flagged)}/{len(result_df)} confirmed pairs flagged: real EG "
          f"significant but permutation-based check is not — BH-FDR's "
          f"independence-leaning guarantee may be optimistic for these.")
    if not flagged.empty:
        print(flagged[["tf", "symbol_a", "symbol_b", "real_eg_pvalue",
                        "permutation_pvalue", "null_frac_significant"]].to_string(index=False))
    print(f"\nMean null_frac_significant across ALL confirmed pairs: "
          f"{result_df['null_frac_significant'].mean():.3f} (expected ~0.05 under a "
          f"well-behaved null with no excess structure-driven false positives; "
          f"materially higher indicates spurious-significance risk from each "
          f"series' own structure, independent of true cross-series alignment).")

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "eg_permutation_check.parquet")
    result_df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
