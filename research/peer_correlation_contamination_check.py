"""
CAMARF research/peer_correlation_contamination_check.py — comparison/
diagnostic script, NOT part of the production pipeline (2026-07-14,
task #59).

Extends `research/data_contamination_scan.py` (task #51, BUG-D65-style
jump detection) with a SECOND, independent signal — ensembled alongside
the existing split-history check, not replacing it, per the scoping
agreed with Ross (Development.md, "Four ideas scoped" 2026-07-13).

Idea: for each UNEXPLAINED large jump (not matched to a known split or a
macro crisis window), check whether a sample of OTHER symbols also show
an unusually large move on the SAME date. If peers move together, the
jump likely reflects a real (if unlabeled by this project's necessarily-
incomplete macro-window list) shared market event — softens the
contamination read. If the flagged symbol jumps in isolation while peers
are quiet, that's a SECOND, independent piece of evidence the original
scan's "unexplained" flag is a genuine data artifact, not a missed real
event — strengthens the contamination read. Neither signal alone is
proof; ensembling them (both must point the same way for a confident
verdict) is more robust than either check alone.

Peer definition: for tractability (261,797 raw events in the source
scan), a random sample of OTHER cached symbols at the SAME timeframe —
not a sector/GICS-matched set (no reliable per-symbol GICS mapping for
the full universe checked; a random broad-market sample already answers
"did the market/sector move that day," which is what this check needs).

Scope: the source scan's `explained=False` events are the candidates;
restricted further to the top-N by magnitude for tractability (261,797
is not tractable to cross-check exhaustively in one comparison-arm pass
— stated explicitly, not silently truncated).

Usage:
    python research/peer_correlation_contamination_check.py --top-n 200 --n-peers 15
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from data import DataStore, DataAligner, GapFlag
from data_contamination_scan import list_price_cache_files

PEER_JUMP_THRESHOLD = 0.05  # a peer "moving too" bar — much lower than the
                             # 0.15 contamination threshold, since a real
                             # shared market event doesn't need every peer
                             # to jump 15% too, just show elevated movement.


def _same_date_return(symbol, tf, date, cache_index=None):
    df = DataStore.load(symbol, tf)
    if df is None or df.empty:
        return None
    # Tier 2.12 fix (Grand Sweep 2026-07-20): raw DataStore.load() output
    # has no gap_flag column (only DataAligner adds one) -- the prior
    # version had no way to tell a genuine prior close from a stale,
    # forward-filled DATA_GAP anchor, which is exactly the population this
    # script exists to scrutinize (symbols already flagged as data-quality-
    # suspect by data_contamination_scan.py). Run through DataAligner
    # (single-symbol) so gap_flag is available, and skip both the same-day
    # bar and its prior anchor if either is DATA_GAP-flagged.
    aligned = DataAligner.align_universe({f"{symbol}_{tf}": df}, tf)
    df = aligned.get(symbol)
    if df is None or df.empty or "gap_flag" not in df.columns:
        return None
    idx = df.index
    # Match to the nearest bar on the same calendar date (jump dates come
    # from the source scan's own per-bar timestamps, which may not align
    # exactly across symbols with different session/gap histories).
    same_day = df[idx.normalize() == pd.Timestamp(date).normalize()]
    if same_day.empty:
        return None
    same_day_clean = same_day[same_day["gap_flag"] != GapFlag.DATA_GAP]
    if same_day_clean.empty:
        return None
    closes = same_day_clean["close"].astype(float)
    if len(closes) < 1:
        return None
    prior = df[(idx < same_day_clean.index.min()) & (df["gap_flag"] != GapFlag.DATA_GAP)]
    if prior.empty:
        return None
    prev_close = float(prior["close"].iloc[-1])
    if prev_close <= 0:
        return None
    return float(closes.iloc[-1] / prev_close - 1.0)


def run(top_n, n_peers, seed):
    rng = np.random.default_rng(seed)
    scan_path = os.path.join("output", "research", "data_contamination_scan.parquet")
    if not os.path.exists(scan_path):
        print(f"{scan_path} not found — run research/data_contamination_scan.py first.")
        return

    scan = pd.read_parquet(scan_path)
    unexplained = scan[scan["explained"] == False].copy()
    print(f"Source scan: {len(scan)} total events, {len(unexplained)} unexplained.")
    top = unexplained.sort_values("magnitude", ascending=False).head(top_n)
    print(f"Cross-checking top {len(top)} by magnitude against {n_peers} random peers each.\n")

    all_symbols_by_tf = {}
    for sym, tf, path in list_price_cache_files():
        all_symbols_by_tf.setdefault(tf, []).append(sym)

    rows = []
    for _, ev in top.iterrows():
        tf = ev["tf"]
        candidates = [s for s in all_symbols_by_tf.get(tf, []) if s != ev["symbol"]]
        if len(candidates) < n_peers:
            continue
        peers = rng.choice(candidates, size=n_peers, replace=False)
        peer_rets = []
        for p in peers:
            r = _same_date_return(p, tf, ev["date"])
            if r is not None:
                peer_rets.append(r)
        if not peer_rets:
            continue
        peer_rets = np.array(peer_rets)
        n_peers_elevated = int((np.abs(peer_rets) >= PEER_JUMP_THRESHOLD).sum())
        peer_corroborated = n_peers_elevated >= max(2, n_peers // 5)  # >=20% of sampled peers also moved
        rows.append({
            "symbol": ev["symbol"], "tf": tf, "date": ev["date"], "magnitude": ev["magnitude"],
            "explanation": ev["explanation"], "n_peers_checked": len(peer_rets),
            "n_peers_elevated": n_peers_elevated, "peer_corroborated": peer_corroborated,
            "ensemble_verdict": "likely_real_shared_event" if peer_corroborated else "likely_isolated_artifact",
        })

    df = pd.DataFrame(rows)
    if df.empty:
        print("No events could be cross-checked (insufficient peer data).")
        return

    n_isolated = (df["ensemble_verdict"] == "likely_isolated_artifact").sum()
    n_shared = (df["ensemble_verdict"] == "likely_real_shared_event").sum()
    print(f"Ensemble verdict across {len(df)} cross-checked events:")
    print(f"  likely_isolated_artifact (both checks agree -> contamination): {n_isolated}")
    print(f"  likely_real_shared_event (peers corroborate -> probably a real, unlabeled event): {n_shared}")

    print(f"\nTop 10 most likely isolated artifacts (highest priority for BUG-D65-style investigation):")
    isolated = df[df["ensemble_verdict"] == "likely_isolated_artifact"].sort_values("magnitude", ascending=False)
    print(isolated.head(10)[["symbol", "tf", "date", "magnitude", "n_peers_elevated", "n_peers_checked"]].to_string(index=False))

    out_dir = os.path.join("output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "peer_correlation_contamination_check.parquet")
    df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


def main():
    p = argparse.ArgumentParser(description="Peer-correlation contamination cross-check (2026-07-14)")
    p.add_argument("--top-n", type=int, default=200)
    p.add_argument("--n-peers", type=int, default=15)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    run(args.top_n, args.n_peers, args.seed)


if __name__ == "__main__":
    main()
