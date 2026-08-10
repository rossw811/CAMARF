"""
CAMARF research/cross_tf_break_divergence.py -- comparison/diagnostic
script, NOT part of the production pipeline (2026-08-04).

Ross's question, from a live design discussion (2026-08-04): does a
structural break on ONE timeframe, while the relationship remains intact
on ANOTHER timeframe (same pair), represent a real, exploitable divergence
signal -- distinct from either timeframe's break status considered alone.
This is Tier 1 of a 3-tier design Ross approved: same-pair, break-status
disagreement across two timeframes, here. Tier 2 (a real joint test via
cross_timeframe_cointegration.py's cross-frequency machinery) and Tier 3
(genuinely cross-asset, cross-TF) are explicitly deferred -- Tier 2 until
this shows the pattern occurs often enough to be worth the heavier test,
Tier 3 until the episodic scan gives a broader, more reliable candidate
universe to draw cross-asset candidates from.

REUSES structural_break_onset_detection.py's find_all_breaks() and
compute_ols_spread() directly, run independently at two timeframes for the
same pair -- not reimplemented.

Method: for each pair with break histories at both TF1 and TF2, find every
DECOUPLING break on one side, then check whether the OTHER side has any
break (of either type) after that same date. If not, the other side's
relationship has remained unbroken since the first side decoupled --
flagged as a divergence event. Checked symmetrically in both directions
(TF1 decouples/TF2 intact, and TF2 decouples/TF1 intact).

DISCLOSED LIMITATION: this is DETECTION-ONLY. It flags where and when the
divergence pattern occurs; it does NOT evaluate whether trading the
still-intact side during these windows produces excess returns over
baseline. That backtest-based validation is deferred (matching task #7's
own onset-age precedent) until this detection step shows the pattern is
common enough, on enough pairs, to justify the backtest-wiring effort.

Usage:
    python research/cross_tf_break_divergence.py
    python research/cross_tf_break_divergence.py --pit-safe
    python research/cross_tf_break_divergence.py --tf1 1D --tf2 1h
    python research/cross_tf_break_divergence.py --full-universe --tf1 1D --tf2 1h
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from data import DataStore, _clean_close
import ml
from structural_break_onset_detection import find_all_breaks, compute_ols_spread, MIN_SEGMENT_BARS


def _breaks_for_pair(symbol_a: str, symbol_b: str, tf_label: str, min_segment_bars: int = MIN_SEGMENT_BARS):
    """Break history for (symbol_a, symbol_b) at a single timeframe, reusing
    structural_break_onset_detection.py's own main()-loop logic exactly
    (same OLS spread construction, same find_all_breaks call)."""
    df_a, df_b = DataStore.load(symbol_a, tf_label), DataStore.load(symbol_b, tf_label)
    if df_a is None or df_b is None:
        return None
    common_idx = df_a.index.intersection(df_b.index)
    if len(common_idx) < min_segment_bars:
        return None
    df_a, df_b = df_a.loc[common_idx], df_b.loc[common_idx]
    log_a, log_b = np.log(_clean_close(df_a)), np.log(_clean_close(df_b))
    spread = compute_ols_spread(log_a, log_b)
    return find_all_breaks(spread, df_a.index, min_segment_bars=min_segment_bars)


def find_divergence_events(broken_side_breaks: list, intact_side_breaks: list) -> list:
    """For every DECOUPLING break on the 'broken' side, check whether the
    'intact' side has any break (either type) after that same date. If not,
    the intact side has stayed unbroken since -- a divergence event."""
    events = []
    for b in broken_side_breaks:
        if b["break_type"] != "decoupling":
            continue
        break_date = b["break_date"]
        after = [x for x in intact_side_breaks if x["break_date"] > break_date]
        if after:
            continue
        events.append({
            "broken_side_break_date": break_date,
            "broken_side_pre_phi": b["pre_phi"],
            "broken_side_post_phi": b["post_phi"],
            "intact_side_ever_broke": len(intact_side_breaks) > 0,
            "intact_side_n_prior_breaks": len(intact_side_breaks),
        })
    return events


def scan_pair(symbol_a: str, symbol_b: str, tf1: str, tf2: str, min_segment_bars: int = MIN_SEGMENT_BARS) -> list:
    breaks_tf1 = _breaks_for_pair(symbol_a, symbol_b, tf1, min_segment_bars)
    breaks_tf2 = _breaks_for_pair(symbol_a, symbol_b, tf2, min_segment_bars)
    if breaks_tf1 is None or breaks_tf2 is None:
        return None

    rows = []
    for direction_events, broken_tf, intact_tf in (
        (find_divergence_events(breaks_tf1, breaks_tf2), tf1, tf2),
        (find_divergence_events(breaks_tf2, breaks_tf1), tf2, tf1),
    ):
        for ev in direction_events:
            ev.update(symbol_a=symbol_a, symbol_b=symbol_b, broken_tf=broken_tf, intact_tf=intact_tf)
            rows.append(ev)
    return rows


def _unique_pairs(pit_safe: bool) -> list:
    if pit_safe:
        from pit_pair_discovery import discover_pit_confirmed_pairs
        pit_pairs = discover_pit_confirmed_pairs()
        return sorted(set((a, b) for a, b, _tf in pit_pairs))
    else:
        confirmed = ml._discover_confirmed_pairs()
        return sorted(set((a, b) for a, b, _tf in confirmed))


def main():
    ap = argparse.ArgumentParser(description="Cross-timeframe break-status divergence diagnostic (2026-08-04)")
    ap.add_argument("--tf1", type=str, default="1D")
    ap.add_argument("--tf2", type=str, default="1h")
    ap.add_argument("--pit-safe", action="store_true",
                     help="Source pairs from research/pit_pair_discovery.py's PIT-safe episodic "
                          "screen instead of ml._discover_confirmed_pairs(). Pairs are deduplicated "
                          "across tf_label since this script tests two EXPLICIT timeframes (--tf1/--tf2) "
                          "for every pair regardless of which tf it was originally confirmed at.")
    args = ap.parse_args()

    pairs = _unique_pairs(args.pit_safe)
    print(f"Scanning {len(pairs)} unique pairs at {args.tf1} vs {args.tf2}")

    all_rows = []
    n_skipped = 0
    for symbol_a, symbol_b in pairs:
        result = scan_pair(symbol_a, symbol_b, args.tf1, args.tf2)
        if result is None:
            n_skipped += 1
            continue
        if result:
            print(f"  {symbol_a}/{symbol_b}: {len(result)} divergence event(s)")
            for ev in result:
                print(f"    {ev['broken_tf']} decoupled {ev['broken_side_break_date']}, "
                      f"{ev['intact_tf']} intact since (ever broke before: {ev['intact_side_ever_broke']})")
        all_rows.extend(result)
    print(f"\n{n_skipped}/{len(pairs)} pairs skipped (insufficient aligned history at one or both timeframes)")

    out_df = pd.DataFrame(all_rows)
    out_dir = os.path.join("output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "cross_tf_break_divergence.parquet")
    out_df.to_parquet(out_path)
    n_pairs_with_events = out_df[["symbol_a", "symbol_b"]].drop_duplicates().shape[0] if len(out_df) else 0
    print(f"\nDone. {len(out_df)} divergence event(s) across {n_pairs_with_events} pair(s). Saved -> {out_path}")
    print("DETECTION-ONLY: no backtest evaluation performed. See module docstring.")


if __name__ == "__main__":
    main()
