"""
research/regime_age_at_entry_diagnostic.py -- Thread Q Idea 1, Path D (docs/HANDOFF.md's
one-line "bullish/quick cointegration-regime timing" idea, expanded 2026-08-23 into a real menu
of paths, see Development.md's Thread Q scoping entry for the other 3).

QUESTION: does how RECENTLY a pair's cointegrating relationship began (its "regime age" at trade
entry) correlate with real trade performance? Answered BEFORE building any sizing/gating
mechanism around the hypothesis, per this project's own verify-before-building discipline --
building path (A)/(B) (onset-recency sizing / regime-strength gating) around an unverified
assumption would be wasted work if the hypothesis turns out false.

METHOD, reusing production code directly, not reimplemented:
  1. For each unique (symbol_a, symbol_b, tf) in a trades file, compute break history via
     structural_break_onset_detection.py::find_all_breaks (now calendar-time-correct after
     today's MIN_SEGMENT_BARS fix -- this diagnostic would have been unreliable before that fix).
  2. For each trade, find the most recent "onset" break strictly before entry_time -> regime_age
     = entry_time - that onset date. No prior onset found -> regime age is unknown/at-least-as-
     old-as-available-history (bucketed separately, not silently dropped or treated as zero).
  3. Bucket by regime age: fresh (<90d), established (90-365d), long-running (>365d), unknown.
  4. Report per-bucket real-trade stats: n_trades, win_rate, mean/median pnl_net, a Sharpe proxy
     (mean/std of pnl_net, NOT annualized -- comparing bucket to bucket at CAMARF's own trade
     counts, not claiming a real annualized Sharpe at n this small).

HONEST LIMITATIONS, disclosed not hidden:
  - Break detection needs real price history BEFORE a pair's cached data starts to distinguish
    "genuinely always coupled" from "coupled since before we have data" -- both land in the
    "unknown" bucket here, not silently merged into "long-running".
  - Uses whatever trades file is passed in (existing backtest.py output) -- inherits that file's
    own pair set and any staleness it has relative to the current confirmed-pairs manifest. This
    is a diagnostic reading EXISTING trades, not a fresh backtest run.
  - Small-n buckets are reported as-is, not hidden -- a bucket with <10 trades gets flagged
    low_confidence=True rather than a false-precision Sharpe number.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

import numpy as np
import pandas as pd

from data import DataStore, _clean_close
from structural_break_onset_detection import find_all_breaks, compute_ols_spread

_MIN_CONFIDENT_N = 10


def _onset_dates_for_pair(symbol_a, symbol_b, tf_label):
    """Real onset dates for one pair -- reuses compute_ols_spread + find_all_breaks exactly as
    structural_break_onset_detection.py's own main() loop does, not reimplemented differently."""
    df_a, df_b = DataStore.load(symbol_a, tf_label), DataStore.load(symbol_b, tf_label)
    if df_a is None or df_b is None:
        return []
    common_idx = df_a.index.intersection(df_b.index)
    if len(common_idx) < 200:
        return []
    df_a, df_b = df_a.loc[common_idx], df_b.loc[common_idx]
    log_a, log_b = np.log(_clean_close(df_a)), np.log(_clean_close(df_b))
    spread = compute_ols_spread(log_a, log_b)
    breaks = find_all_breaks(spread, df_a.index)  # min_segment_bars=None -> calendar-normalized
    return sorted(b["break_date"] for b in breaks if b["break_type"] == "onset")


def _bucket(age_days):
    if age_days is None:
        return "unknown"
    if age_days < 90:
        return "fresh_<90d"
    if age_days < 365:
        return "established_90-365d"
    return "long_running_>365d"


def run(trades_path: str):
    """Returns (bucket_summary_df, trades_with_regime_age_df) -- the per-trade detail is what
    backtest.py::compute_regime_age_weights (added 2026-08-23, Thread Q Idea 1 Path A) reads,
    keeping backtest.py decoupled from importing research/ code directly (this project's own
    established dependency direction: research/ imports from root, not the reverse)."""
    trades = pd.read_parquet(trades_path)
    trades["entry_time"] = pd.to_datetime(trades["entry_time"])

    onset_cache = {}
    ages = []
    for _, row in trades.iterrows():
        key = (row["symbol_a"], row["symbol_b"], row["tf"])
        if key not in onset_cache:
            onset_cache[key] = _onset_dates_for_pair(*key)
        onsets = onset_cache[key]
        prior_onsets = [d for d in onsets if pd.Timestamp(d) < row["entry_time"]]
        if prior_onsets:
            age_days = (row["entry_time"] - pd.Timestamp(max(prior_onsets))).days
        else:
            age_days = None
        ages.append(age_days)

    trades["regime_age_days"] = ages
    trades["regime_bucket"] = trades["regime_age_days"].apply(_bucket)

    rows = []
    for bucket, grp in trades.groupby("regime_bucket"):
        n = len(grp)
        pnl = grp["pnl_net"].dropna()
        win_rate = float((pnl > 0).mean()) if len(pnl) else np.nan
        mean_pnl = float(pnl.mean()) if len(pnl) else np.nan
        median_pnl = float(pnl.median()) if len(pnl) else np.nan
        sharpe_proxy = float(pnl.mean() / pnl.std()) if len(pnl) > 1 and pnl.std() > 0 else np.nan
        rows.append({
            "regime_bucket": bucket, "n_trades": n, "win_rate": win_rate,
            "mean_pnl_net": mean_pnl, "median_pnl_net": median_pnl,
            "sharpe_proxy_unannualized": sharpe_proxy,
            "low_confidence": n < _MIN_CONFIDENT_N,
        })
    return pd.DataFrame(rows).sort_values("n_trades", ascending=False), trades


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Thread Q Idea 1 Path D: regime-age-at-entry diagnostic")
    p.add_argument("--trades", default="output/backtest/baseline_trades_layer1.parquet")
    args = p.parse_args()

    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    trades_path = args.trades if os.path.isabs(args.trades) else os.path.join(_root, args.trades)
    if not os.path.exists(trades_path):
        print(f"Trades file not found: {trades_path}")
        sys.exit(1)

    result, trades_with_age = run(trades_path)
    out_path = os.path.join(_root, "output", "research", "regime_age_at_entry_diagnostic.parquet")
    detail_path = os.path.join(_root, "output", "research", "regime_age_at_entry_detail.parquet")
    result.to_parquet(out_path)
    trades_with_age.to_parquet(detail_path)
    print(f"Trades source: {trades_path}")
    print(result.to_string(index=False))
    print(f"\nSaved: {out_path}")
    print(f"Saved (per-trade detail, for compute_regime_age_weights): {detail_path}")
