"""
research/confirmed_pairs_contamination_followup.py -- targeted follow-up,
NOT part of the production pipeline (2026-09-01).

SCOPE: data_contamination_scan.py's confirmed-pairs cross-check flagged all
10 unique symbols across CAMARF's currently-confirmed pairs as having
unexplained jumps, 7 at the 1day production timeframe. Before treating that
as real contamination, run the SAME peer-corroboration check
peer_correlation_contamination_check.py already does (reused directly, not
reimplemented) -- but targeted at exactly these 10 symbols' own unexplained
events, not a top-N-by-magnitude sample across the whole universe (which
might miss or dilute these specific symbols).

Read-only. Reuses data_contamination_scan.parquet (already computed) and
peer_correlation_contamination_check.py's _same_date_return +
PEER_JUMP_THRESHOLD, unchanged.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from data_contamination_scan import list_price_cache_files
from peer_correlation_contamination_check import _same_date_return, PEER_JUMP_THRESHOLD

FLAGGED_SYMBOLS = ["7267.T", "8058.T", "EQR", "INVH", "IQV", "KMB", "KVUE", "PNC", "Q", "ZION"]
N_PEERS = 20
SEED = 42


def main():
    scan_path = os.path.join("output", "research", "data_contamination_scan.parquet")
    if not os.path.exists(scan_path):
        print(f"{scan_path} not found — run research/data_contamination_scan.py first.")
        return

    scan = pd.read_parquet(scan_path)
    unexplained = scan[(scan["explained"] == False) & (scan["symbol"].isin(FLAGGED_SYMBOLS))].copy()
    print(f"Source scan: {len(scan)} total events. {len(unexplained)} unexplained events across "
          f"the {len(FLAGGED_SYMBOLS)} flagged confirmed-pair symbols.")

    rng = np.random.default_rng(SEED)
    all_symbols_by_tf = {}
    for sym, tf, path in list_price_cache_files():
        all_symbols_by_tf.setdefault(tf, []).append(sym)

    rows = []
    for _, ev in unexplained.iterrows():
        tf = ev["tf"]
        candidates = [s for s in all_symbols_by_tf.get(tf, []) if s != ev["symbol"]]
        if len(candidates) < N_PEERS:
            continue
        peers = rng.choice(candidates, size=N_PEERS, replace=False)
        peer_rets = []
        for p in peers:
            r = _same_date_return(p, tf, ev["date"])
            if r is not None:
                peer_rets.append(r)
        if not peer_rets:
            continue
        peer_rets = np.array(peer_rets)
        n_peers_elevated = int((np.abs(peer_rets) >= PEER_JUMP_THRESHOLD).sum())
        peer_corroborated = n_peers_elevated >= max(2, N_PEERS // 5)
        rows.append({
            "symbol": ev["symbol"], "tf": tf, "date": ev["date"], "magnitude": ev["magnitude"],
            "n_peers_checked": len(peer_rets), "n_peers_elevated": n_peers_elevated,
            "peer_corroborated": peer_corroborated,
            "ensemble_verdict": "likely_real_shared_event" if peer_corroborated else "likely_isolated_artifact",
        })

    df = pd.DataFrame(rows)
    if df.empty:
        print("No events could be cross-checked (insufficient peer data).")
        return

    print(f"\nCross-checked {len(df)}/{len(unexplained)} events (rest skipped for insufficient peer data).")
    print("\nPer-symbol verdict breakdown:")
    for sym in FLAGGED_SYMBOLS:
        sub = df[df["symbol"] == sym]
        if sub.empty:
            print(f"  {sym:10s}: 0 events cross-checked")
            continue
        n_isolated = int((sub["ensemble_verdict"] == "likely_isolated_artifact").sum())
        n_shared = int((sub["ensemble_verdict"] == "likely_real_shared_event").sum())
        day1_sub = sub[sub["tf"] == "1day"]
        day1_isolated = int((day1_sub["ensemble_verdict"] == "likely_isolated_artifact").sum())
        print(f"  {sym:10s}: {len(sub)} events, {n_isolated} likely_isolated_artifact, "
              f"{n_shared} likely_real_shared_event  |  1day: {len(day1_sub)} events, "
              f"{day1_isolated} isolated")

    out_dir = os.path.join("output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "confirmed_pairs_contamination_followup.parquet")
    df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
