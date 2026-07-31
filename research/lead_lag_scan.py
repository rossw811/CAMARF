"""
CAMARF lead_lag_scan.py — exploratory diagnostic, NOT part of the
production pipeline.

Motivated by a 2026-06-24 discussion with Ross: the existing pipeline
(correlation pre-filter, EG, OLS/Kalman hedge ratio) tests only the
CONTEMPORANEOUS relationship between two legs (bar t of A vs bar t of B).
Two assets that are not contemporaneously cointegrated may still be
genuinely related if one leads the other by k bars — the current
pipeline cannot see this at all, because the correlation pre-filter
would screen the pair out before EG (a lag-0-only test) ever ran.

This script is scoped narrowly per the project's existing comparison-arm
discipline (see audit_price_degeneracy.py, eg_permutation_check.py):
confirmed pairs only, not a full O(N^2 x K) universe-wide lag sweep
(that is a separate, much more expensive undertaking, flagged but not
attempted here).

Method, two stages mirroring the production pipeline's own cheap-filter
-> expensive-confirm structure:
  1. Cheap stage: for each confirmed pair, sweep lag k in [-max_lag, max_lag]
     bars and compute Pearson correlation of gap-aware returns,
     corr(ret_a_t, ret_b_{t+k}) — k>0 means A leads B (A's move today
     associated with B's move k bars later), k<0 means B leads A. Find
     the lag k* maximizing |corr|.
  2. Confirm stage: only for pairs where k* != 0 AND the correlation lift
     over lag 0 clears --min-lift, re-run the SAME production EG test
     (statsmodels coint(), same call shape as eg_permutation_check.py)
     on gap-masked log-prices realigned at k*, compared against the
     identical test at lag 0. A pair whose EG result is materially
     better (lower p-value) at k* than at lag 0 is evidence the relevant
     relationship is the lagged one, not the contemporaneous one the
     production pipeline currently tests exclusively.

This does NOT decide whether to build a lagged-cointegration entry rule
into the production pipeline — it answers the prior, cheaper question:
does the lag-0-only assumption actually cost anything on the pairs
already confirmed contemporaneously, and is there a hint of a more
informative lag nearby.

max_lag is a fixed bar count for all timeframes (not scaled per TF) —
a deliberate first-pass simplification, noted here rather than silently
assumed: 10 bars means 10 minutes at 1m but ~2 trading weeks at 1D.

Read-only. Loads cached price data via aligned_pair_loader.load_aligned_pair
(DataStore + DataAligner — see that module's docstring, fixed 2026-06-24:
raw DataStore.load() output has no gap_flag column, so calling
_gap_aware_returns directly on it silently skips all gap masking,
including the overnight/weekend-spanning return) — never fetches.

Usage:
    python research/lead_lag_scan.py
    python research/lead_lag_scan.py --max-lag 15 --min-lift 0.05
"""
import argparse
import logging
import os
import sys

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

log = logging.getLogger("lead_lag_scan")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aligned_pair_loader import load_aligned_pair
from analysis import Config
from data import _clean_close, _gap_aware_returns

_TF_DIRS = [
    "1min", "2min", "3min", "5min", "15min", "30min", "1hr", "4hr",
    "7day", "1mo", "3mo", "6mo",
]
_DIR_TO_LABEL = {
    "1min": "1m", "2min": "2m", "3min": "3m", "5min": "5m", "15min": "15m",
    "30min": "30m", "1hr": "1h", "4hr": "4h", "7day": "7D", "1mo": "1M",
    "3mo": "3M", "6mo": "6M",
}

_MIN_CORR_N = 30
_MIN_EG_N = 60


def _gap_masked_log_price(df):
    close = _clean_close(df)
    with np.errstate(invalid="ignore", divide="ignore"):
        log_p = np.log(close)
    log_p[~np.isfinite(log_p)] = np.nan
    return log_p


def _eg_pvalue(a, b, max_eg_lag):
    mask = np.isfinite(a) & np.isfinite(b)
    a_, b_ = a[mask], b[mask]
    if a_.size < _MIN_EG_N:
        return None, a_.size
    try:
        _, pval, _ = coint(a_, b_, trend="c", maxlag=max_eg_lag, autolag="aic")
        return float(pval), a_.size
    except Exception as e:
        # Tier 6 fix (Grand Sweep 2026-07-20): previously swallowed silently
        # (bare except, no logging) -- shared by 7 consumer files, so an EG
        # failure anywhere in the pipeline was invisible. Logged at DEBUG
        # (not WARNING) since this is called in tight loops across large
        # candidate sets and an occasional EG numerical failure on a thin/
        # degenerate series is expected, not exceptional -- but it must be
        # discoverable, not silent.
        log.debug("EG coint() failed on a %d-obs series: %s", a_.size, e)
        return None, a_.size


def lagged_corr_scan(ret_a, ret_b, max_lag):
    """ret_a, ret_b: pandas Series, same (datetime) index space, gap-aware
    returns (NaN at masked positions already). Returns a dict
    {lag: (corr, n)} for lag in [-max_lag, max_lag]. lag>0 means
    corr(ret_a_t, ret_b_{t+lag}) — A leads B by `lag` bars."""
    out = {}
    for lag in range(-max_lag, max_lag + 1):
        shifted_b = ret_b.shift(-lag)
        joined = pd.concat([ret_a, shifted_b], axis=1, join="inner").dropna()
        n = len(joined)
        if n < _MIN_CORR_N:
            out[lag] = (None, n)
            continue
        c = float(np.corrcoef(joined.iloc[:, 0].values, joined.iloc[:, 1].values)[0, 1])
        # A zero-variance window (e.g. a BUG-D49 degenerate-price stretch
        # landing entirely inside the shifted overlap) makes corrcoef
        # return NaN, not raise — normalize to None here so every
        # downstream consumer's "is not None" filter actually excludes it.
        # (Found 2026-06-24: max(..., key=abs) over a dict containing NaN
        # silently mis-selected a NaN entry as "best" on real BUG-D49
        # pairs — NaN comparisons are always False, so max() can't tell
        # it apart from a string of ties. Caught on real data; the
        # synthetic test has no zero-variance windows so never hit this.)
        if not np.isfinite(c):
            c = None
        out[lag] = (c, n)
    return out


def best_lag(scan):
    """scan: output of lagged_corr_scan. Returns (best_lag, best_corr, best_n)
    among lags with a valid (non-None) correlation, by |corr|."""
    valid = {k: v for k, v in scan.items() if v[0] is not None}
    if not valid:
        return None, None, None
    k_star = max(valid, key=lambda k: abs(valid[k][0]))
    c_star, n_star = valid[k_star]
    return k_star, c_star, n_star


def main():
    p = argparse.ArgumentParser(description="Lead-lag scan on confirmed pairs (2026-06-24)")
    p.add_argument("--max-lag", type=int, default=Config.RESEARCH.LEAD_LAG_MAX_LAG,
                    help="Max bars to search in each direction (fixed bar count, not TF-scaled). "
                         "Default sourced from Config.RESEARCH.LEAD_LAG_MAX_LAG (2026-07-20).")
    p.add_argument("--min-lift", type=float, default=0.05,
                    help="Minimum |corr(k*)| - |corr(0)| to flag a pair as lag-lift-worthy "
                         "and trigger the EG confirm stage")
    args = p.parse_args()
    max_eg_lag = Config.ANALYSIS.EG_MAX_LAG

    rows = []
    for tf_dir in _TF_DIRS:
        path = f"output/results/{tf_dir}/pairs.parquet"
        if not os.path.exists(path):
            continue
        tf_label = _DIR_TO_LABEL[tf_dir]
        df = pd.read_parquet(path)
        for _, row in df.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            df_a, df_b = load_aligned_pair(sym_a, sym_b, tf_label)
            if df_a is None or df_b is None:
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: cache missing for one leg")
                continue

            ret_a = pd.Series(_gap_aware_returns(df_a), index=df_a.index)
            ret_b = pd.Series(_gap_aware_returns(df_b), index=df_b.index)
            scan = lagged_corr_scan(ret_a, ret_b, args.max_lag)
            k_star, c_star, n_star = best_lag(scan)
            c0, n0 = scan.get(0, (None, 0))
            if k_star is None or c0 is None:
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: insufficient overlapping "
                      f"return data at any lag (need >={_MIN_CORR_N})")
                continue

            lift = abs(c_star) - abs(c0)
            flagged = (k_star != 0) and (lift >= args.min_lift)

            eg_p0 = eg_pstar = None
            n_eg0 = n_eg_star = 0
            if flagged:
                log_a = _gap_masked_log_price(df_a)
                log_b = _gap_masked_log_price(df_b)
                logp_a = pd.Series(log_a, index=df_a.index)
                logp_b = pd.Series(log_b, index=df_b.index)

                joined0 = pd.concat([logp_a, logp_b], axis=1, join="inner").dropna()
                eg_p0, n_eg0 = _eg_pvalue(
                    joined0.iloc[:, 0].values, joined0.iloc[:, 1].values, max_eg_lag
                )

                shifted_logp_b = logp_b.shift(-k_star)
                joined_k = pd.concat([logp_a, shifted_logp_b], axis=1, join="inner").dropna()
                eg_pstar, n_eg_star = _eg_pvalue(
                    joined_k.iloc[:, 0].values, joined_k.iloc[:, 1].values, max_eg_lag
                )

            rows.append({
                "tf": tf_label, "symbol_a": sym_a, "symbol_b": sym_b,
                "best_lag": k_star, "corr_at_best_lag": c_star, "n_at_best_lag": n_star,
                "corr_at_lag0": c0, "n_at_lag0": n0, "corr_lift": lift,
                "flagged_lag_worth_checking": flagged,
                "eg_p_lag0": eg_p0, "eg_p_best_lag": eg_pstar,
                "n_eg_lag0": n_eg0, "n_eg_best_lag": n_eg_star,
            })
            status = "FLAG" if flagged else "ok"
            extra = ""
            if flagged:
                extra = f" eg_p0={eg_p0} eg_p*={eg_pstar}"
            print(f"{status:5s} {sym_a}/{sym_b}@{tf_label}: best_lag={k_star} "
                  f"corr*={c_star:.3f}(n={n_star}) corr0={c0:.3f}(n={n0}) "
                  f"lift={lift:.3f}{extra}")

    if not rows:
        print("No confirmed pairs with sufficient data found.")
        return

    result_df = pd.DataFrame(rows)
    flagged_df = result_df[result_df["flagged_lag_worth_checking"]]
    print(f"\n{len(flagged_df)}/{len(result_df)} confirmed pairs show a non-zero lag "
          f"with a correlation lift >= {args.min_lift} over lag 0.")
    if not flagged_df.empty:
        cols = ["tf", "symbol_a", "symbol_b", "best_lag", "corr_at_best_lag",
                "corr_at_lag0", "corr_lift", "eg_p_lag0", "eg_p_best_lag"]
        print(flagged_df[cols].to_string(index=False))
        eg_improves = flagged_df[
            flagged_df["eg_p_best_lag"].notna() & flagged_df["eg_p_lag0"].notna()
            & (flagged_df["eg_p_best_lag"] < flagged_df["eg_p_lag0"])
        ]
        print(f"\nOf those, {len(eg_improves)}/{len(flagged_df)} also show a LOWER "
              f"(more significant) EG p-value at the lagged alignment than at lag 0 — "
              f"this is the subset where the lagged relationship looks genuinely "
              f"stronger than the contemporaneous one currently tested in production, "
              f"not just a correlation-scan artifact.")
        print("GATE RESULT: at least one confirmed pair shows evidence the lagged "
              "alignment may be more informative than lag 0 — worth a closer look "
              "before deciding whether a lag-realignment step belongs ahead of "
              "CointScanner. Do not wire anything into the production pipeline on "
              "this evidence alone.")
    else:
        print("GATE RESULT: no evidence among current confirmed pairs that a "
              "non-zero lag is more informative than lag 0 — the contemporaneous "
              "assumption looks fine for THIS set. This does not rule out lead-lag "
              "structure existing among pairs that fail the lag-0 pre-filter and "
              "never reach this confirmed-pairs list at all; that is a separate, "
              "much more expensive universe-wide question, not addressed here.")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "lead_lag_scan.parquet")
    result_df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
