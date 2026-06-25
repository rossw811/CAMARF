"""
CAMARF tail_dependence_deep.py — comparison/diagnostic, NOT part of the
production pipeline.

Direct extension of tail_dependence.py per Ross's "how can we get as
much data and inference as possible" (2026-06-24): the asymmetry
reliability gate (n_L/n_U >= 10 conditioning observations) is bottlenecked
by how much history is available, and the regular rolling cache is much
shallower than the IBKR deep-history supplement already fetched for
confirmed pairs (data_ibkr.py, 10-year depth at 1h/4h, 2-year at 15m/30m
— see ALL_SUPPLEMENT_TFS in data_ibkr.py; note 1m's supplement depth is
only 7 days and 3m has no supplement file format at all, so this does
NOT deepen every TF equally). Reuses data_ibkr.py's own
load_supplement + merge_with_yfinance directly — the exact same merge
already used by analysis.py's _enrich_with_deep_history — rather than
reimplementing the merge.

Two modes:
  1. Default: scan every confirmed pair (output/results/*/pairs.parquet)
     across every TF that has an IBKR supplement format at all (1m, 5m,
     15m, 30m, 1h, 4h, 1D per ALL_SUPPLEMENT_TFS — 2m/3m/7D/1M/3M/6M are
     never fetched by data_ibkr.py and skipped here). For pairs where
     BOTH legs have a supplement file, report shallow (regular cache)
     vs deep (merged) tail-dependence side by side — this is the direct
     "does more data change the reliability verdict" comparison.
  2. --symbol-a/--symbol-b/--tf: check one explicit pair at one TF, even
     if not "confirmed" there (e.g. CCL/NCLH at 1h/4h, where deep history
     exists but the pair isn't confirmed at those TFs — exploratory,
     clearly labeled as such, not a claim that the pair is confirmed
     there).

Read-only. Loads cached price data and IBKR supplement files directly —
never fetches.

Usage:
    python research/tail_dependence_deep.py
    python research/tail_dependence_deep.py --symbol-a CCL --symbol-b NCLH --tf 1h
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import DataStore, _gap_aware_returns
from data_ibkr import load_supplement, merge_with_yfinance
from tail_dependence import _empirical_tail_dependence

_SUPPLEMENT_TFS = ["1m", "5m", "15m", "30m", "1h", "4h", "1D"]
_TF_DIRS = [
    "1min", "2min", "3min", "5min", "15min", "30min", "1hr", "4hr",
    "7day", "1mo", "3mo", "6mo",
]
_DIR_TO_LABEL = {
    "1min": "1m", "2min": "2m", "3min": "3m", "5min": "5m", "15min": "15m",
    "30min": "30m", "1hr": "1h", "4hr": "4h", "7day": "7D", "1mo": "1M",
    "3mo": "3M", "6mo": "6M",
}


def deep_series(symbol, tf_label):
    """IBKR-deep-merged dataframe, or None if no supplement exists for
    this symbol/TF. Returned alongside (not just its returns) so callers
    can report the actual date range achieved — load_supplement's "_deep"
    naming and data_ibkr.py's requested duration string (e.g. "10 Y") are
    not, by themselves, proof the fetch actually reached that far back;
    2026-06-24 found SPY/VOO@4h's supplement starts on the exact same
    date as the main cache despite a 10-year request — see
    Development.md Session 11. Always report actual date ranges achieved,
    not the requested depth, to avoid silently repeating that mistake."""
    sup = load_supplement(symbol, tf_label)
    if sup is None:
        return None
    merged = merge_with_yfinance(sup, symbol, tf_label)
    if merged is None or merged.empty:
        return None
    return merged


def shallow_series(symbol, tf_label):
    return DataStore.load(symbol, tf_label)


def compare_pair(symbol_a, symbol_b, tf_label, q=0.10):
    shallow_a = shallow_series(symbol_a, tf_label)
    shallow_b = shallow_series(symbol_b, tf_label)
    deep_a = deep_series(symbol_a, tf_label)
    deep_b = deep_series(symbol_b, tf_label)

    out = {"symbol_a": symbol_a, "symbol_b": symbol_b, "tf": tf_label}

    def _date_range(df):
        if df is None or df.empty:
            return None, None
        return df.index.min(), df.index.max()

    out["shallow_a_start"], out["shallow_a_end"] = _date_range(shallow_a)
    out["shallow_b_start"], out["shallow_b_end"] = _date_range(shallow_b)
    out["deep_a_start"], out["deep_a_end"] = _date_range(deep_a)
    out["deep_b_start"], out["deep_b_end"] = _date_range(deep_b)

    # Did the supplement actually extend earlier than the main cache for
    # EITHER leg, or does it just duplicate the same window (the SPY/VOO
    # @4h failure mode)?
    out["deep_actually_extends_a"] = bool(
        out["deep_a_start"] is not None and out["shallow_a_start"] is not None
        and out["deep_a_start"] < out["shallow_a_start"]
    )
    out["deep_actually_extends_b"] = bool(
        out["deep_b_start"] is not None and out["shallow_b_start"] is not None
        and out["deep_b_start"] < out["shallow_b_start"]
    )

    ret_a_shallow = pd.Series(_gap_aware_returns(shallow_a), index=shallow_a.index) if shallow_a is not None else None
    ret_b_shallow = pd.Series(_gap_aware_returns(shallow_b), index=shallow_b.index) if shallow_b is not None else None
    if ret_a_shallow is not None and ret_b_shallow is not None:
        joined = pd.concat([ret_a_shallow, ret_b_shallow], axis=1, join="inner").dropna()
        if len(joined) >= 30:
            r = _empirical_tail_dependence(joined.iloc[:, 0].values, joined.iloc[:, 1].values, q)
            if r is not None:
                out["shallow_lambda_L"], out["shallow_lambda_U"], out["shallow_n_L"], out["shallow_n_U"] = r
                out["shallow_n_obs"] = len(joined)

    if deep_a is None or deep_b is None:
        out["deep_available"] = False
        return out
    out["deep_available"] = True
    ret_a_deep = pd.Series(_gap_aware_returns(deep_a), index=deep_a.index)
    ret_b_deep = pd.Series(_gap_aware_returns(deep_b), index=deep_b.index)
    joined_deep = pd.concat([ret_a_deep, ret_b_deep], axis=1, join="inner").dropna()
    out["deep_n_obs"] = len(joined_deep)
    if len(joined_deep) >= 30:
        r = _empirical_tail_dependence(joined_deep.iloc[:, 0].values, joined_deep.iloc[:, 1].values, q)
        if r is not None:
            out["deep_lambda_L"], out["deep_lambda_U"], out["deep_n_L"], out["deep_n_U"] = r

    return out


def main():
    p = argparse.ArgumentParser(description="Deep-history tail-dependence comparison (2026-06-24)")
    p.add_argument("--symbol-a", default=None)
    p.add_argument("--symbol-b", default=None)
    p.add_argument("--tf", default=None)
    p.add_argument("--q", type=float, default=0.10)
    args = p.parse_args()

    rows = []
    if args.symbol_a and args.symbol_b:
        tf = args.tf or "1h"
        rows.append(compare_pair(args.symbol_a, args.symbol_b, tf, q=args.q))
    else:
        for tf_dir in _TF_DIRS:
            tf_label = _DIR_TO_LABEL[tf_dir]
            if tf_label not in _SUPPLEMENT_TFS:
                continue
            path = f"output/results/{tf_dir}/pairs.parquet"
            if not os.path.exists(path):
                continue
            df = pd.read_parquet(path)
            for _, row in df.iterrows():
                rows.append(compare_pair(row["symbol_a"], row["symbol_b"], tf_label, q=args.q))

    if not rows:
        print("No pairs evaluated.")
        return

    result_df = pd.DataFrame(rows)
    with_deep = result_df[result_df["deep_available"]]
    print(f"{len(with_deep)}/{len(result_df)} pairs/TFs have an IBKR supplement for BOTH legs.")
    if with_deep.empty:
        print("No deep-history comparisons available.")
        return

    cols = [c for c in [
        "symbol_a", "symbol_b", "tf", "shallow_n_obs", "deep_n_obs",
        "shallow_lambda_L", "shallow_lambda_U", "deep_lambda_L", "deep_lambda_U",
        "shallow_n_L", "shallow_n_U", "deep_n_L", "deep_n_U",
    ] if c in with_deep.columns]
    print(with_deep[cols].to_string(index=False))

    date_cols = [c for c in [
        "symbol_a", "symbol_b", "tf",
        "shallow_a_start", "deep_a_start", "deep_actually_extends_a",
        "shallow_b_start", "deep_b_start", "deep_actually_extends_b",
    ] if c in with_deep.columns]
    print("\nDate ranges (does the supplement actually extend earlier than the "
          "main cache, or just duplicate the same window — see SPY/VOO@4h in "
          "Development.md Session 11 for why this is checked explicitly rather "
          "than assumed from the requested fetch depth):")
    print(with_deep[date_cols].to_string(index=False))

    if "shallow_n_obs" in with_deep.columns and "deep_n_obs" in with_deep.columns:
        gain = (with_deep["deep_n_obs"] - with_deep["shallow_n_obs"]).fillna(with_deep["deep_n_obs"])
        print(f"\nMean additional observations from deep history: {gain.mean():.0f} "
              f"(median {gain.median():.0f})")
        n_no_gain = int((gain <= 0).sum())
        if n_no_gain:
            print(f"WARNING: {n_no_gain}/{len(gain)} pairs/TFs show ZERO or negative "
                  f"gain from the supplement — check the date-range table above before "
                  f"assuming deep history is helping for these.")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "tail_dependence_deep_comparison.parquet")
    result_df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
