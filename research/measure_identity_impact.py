"""
research/measure_identity_impact.py -- how much the label -> PERMNO identity bug (2026-10-12) could have changed the
discovery runs (beb004b4 primary + grids), before deciding whether discovery must be re-run.

Two channels:
  1. Membership gate (Tier 2/3): wrds_deep_history_episodic_scan.load_membership_gate maps symbol -> PERMNO with
     symbol_permno_map.parquet, wrong for ~1,959 labels. For every label where that map differs from the final
     content-verified map (research/identify_wrds_files.py), compare S&P 500 membership under both PERMNOs at every
     window end date the scan used (taken from the saved Tier 2/3 windows files). A label "flips" on a date when
     exactly one of the two PERMNOs was a member.
  2. Volume restatement: files restated with another security's split factors (apply_crsp_volume_adjustment report
     vs the final map) -- listed; their ADV gate effect is measured after the re-restatement.
Then: how many Tier 2/3 confirmed pairs, and tested (pair, window) rows, involve a flipped label.
Output: output/research/identity_impact.parquet (per label) + printed summary.
Usage (CachyOS, after copying wrds_label_permno_final.parquet): python research/measure_identity_impact.py
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_W = os.path.join(ROOT, "output", "cache", "wrds")
_R = os.path.join(ROOT, "output", "research")


def main():
    from data_wrds import sp500_members_asof
    final = pd.read_parquet(os.path.join(_W, "wrds_label_permno_final.parquet"))
    fmap = dict(zip(final["label"], final["permno"]))
    sm = pd.read_parquet(os.path.join(_W, "symbol_permno_map.parquet"))
    smap = dict(zip(sm["symbol"], sm["permno"]))
    mem = pd.read_parquet(os.path.join(_W, "sp500_membership_history.parquet"))
    dates = set()
    tested = {}
    for tier in (2, 3):
        w = pd.read_parquet(os.path.join(_R, f"wrds_deep_history_episodic_scan_tier{tier}_windows.parquet"),
                            columns=["symbol_a", "symbol_b", "window_end_date"])
        dates |= set(pd.to_datetime(w["window_end_date"]).unique())
        tested[tier] = w
    dates = sorted(dates)
    members = {d: sp500_members_asof(mem, d) for d in dates}
    rows = []
    for lab, p_old in smap.items():
        p_new = fmap.get(lab)
        if pd.isna(p_new) or int(p_new) == int(p_old):
            continue
        flips = [d for d in dates if (int(p_old) in members[d]) != (int(p_new) in members[d])]
        rows.append({"label": lab, "permno_symbol_map": int(p_old), "permno_final": int(p_new),
                     "n_dates": len(dates), "n_flip_dates": len(flips),
                     "old_member_dates": sum(int(p_old) in members[d] for d in dates),
                     "new_member_dates": sum(int(p_new) in members[d] for d in dates)})
    R = pd.DataFrame(rows)
    R.to_parquet(os.path.join(_R, "identity_impact.parquet"))
    flipped = set(R.loc[R["n_flip_dates"] > 0, "label"])
    print(f"labels where symbol_permno_map != final map: {len(R):,}; with >= 1 membership flip on a scan window date: "
          f"{len(flipped):,} (window end dates checked: {len(dates)})")
    print(f"  of those: wrongly EXCLUDED (true security a member, old permno not) on some date: "
          f"{int((R['new_member_dates'] > R['old_member_dates']).sum()):,}; wrongly INCLUDED: "
          f"{int((R['old_member_dates'] > R['new_member_dates']).sum()):,}")
    for tier, w in tested.items():
        hit = w["symbol_a"].isin(flipped) | w["symbol_b"].isin(flipped)
        print(f"Tier {tier}: tested (pair, window) rows involving a flipped label: {int(hit.sum()):,} of {len(w):,}; "
              f"distinct pairs {w.loc[hit, ['symbol_a', 'symbol_b']].drop_duplicates().shape[0]:,}")
        cf = os.path.join(_R, f"wrds_deep_history_episodic_scan_tier{tier}_confirmed.parquet")
        if os.path.exists(cf):
            c = pd.read_parquet(cf)
            ch = c["symbol_a"].isin(flipped) | c["symbol_b"].isin(flipped)
            print(f"  confirmed pairs involving a flipped label: {int(ch.sum()):,} of {len(c):,}")
    print(R.sort_values("n_flip_dates", ascending=False).head(15).to_string(index=False))


if __name__ == "__main__":
    main()
