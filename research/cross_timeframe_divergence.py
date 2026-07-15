"""
CAMARF research/cross_timeframe_divergence.py — comparison/diagnostic
script, NOT part of the production pipeline (2026-07-14, task #54).

Question: for the SAME pair, how consistent is the cointegration verdict
(EG p-value) across timeframes? Directly motivated by this session's task
#71 finding — the 1h confirmed-pair set collapsed to near-zero while
other timeframes (1m/2m/3m/1M) retained a handful of confirmed pairs —
without yet formally characterizing whether that's a general cross-
timeframe pattern or specific to whatever happened at 1h. Temporal-
aggregation effects on cointegration test power are a genuine, studied
phenomenon in the econometrics literature (more bars = more test power
but more microstructure noise; fewer, coarser bars = less noise per
observation but far less test power from a smaller sample) — this script
measures where CAMARF's own data actually falls on that tradeoff for a
known-good pair set, rather than assuming either direction.

Method: for each pair, compute the EG p-value (production's own gap-aware
methodology — _gap_masked_log_price/_eg_pvalue from lead_lag_scan.py,
reused directly for methodological consistency with every other EG test
run this session) independently at each of several cached timeframes.
Reports the full per-pair, per-TF p-value grid, plus whether each pair's
significance verdict (p<0.05) is CONSISTENT (same verdict at every TF
tested) or DIVERGENT, and checks for a systematic relationship between
timeframe granularity (bars/day) and p-value magnitude across the whole
set.

Usage:
    python research/cross_timeframe_divergence.py
    python research/cross_timeframe_divergence.py --tfs 15min 30min 1hr 4hr 1day
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from aligned_pair_loader import load_aligned_pair
from lead_lag_scan import _gap_masked_log_price, _eg_pvalue

_DEFAULT_PAIRS = [
    ("LNT", "VTR"), ("LNT", "WELL"), ("AME", "MAR"), ("CMS", "DUK"),
    ("EG", "WRB"), ("HAL", "NOV"), ("MET", "TMHC"), ("PFG", "STLD"),
    ("UMBF", "FHB"),
]

# Approximate bars/trading-day, for the granularity-vs-p-value check.
_BARS_PER_DAY = {
    "1min": 390.0, "5min": 78.0, "15min": 26.0, "30min": 13.0,
    "1hr": 6.5, "4hr": 1.625, "1day": 1.0,
}


def eg_pvalue_for_pair(symbol_a, symbol_b, tf_label, min_date=None):
    """min_date: if given, restricts to bars >= min_date. Required for a
    fair cross-TF comparison — see module docstring's sample-period
    confound note. Without this, a coarser TF's naturally longer cached
    history (e.g. 1day reaching back years further than 1h) mixes
    together periods where a relationship held and periods where it
    didn't, which looks like a granularity effect but isn't one."""
    df_a, df_b = load_aligned_pair(symbol_a, symbol_b, tf_label)
    if df_a is None or df_b is None or df_a.empty or df_b.empty:
        return None, 0
    log_a = pd.Series(_gap_masked_log_price(df_a), index=df_a.index)
    log_b = pd.Series(_gap_masked_log_price(df_b), index=df_b.index)
    common_idx = log_a.index.intersection(log_b.index)
    if min_date is not None:
        common_idx = common_idx[common_idx >= min_date]
    la = log_a.reindex(common_idx).values
    lb = log_b.reindex(common_idx).values
    return _eg_pvalue(la, lb, max_eg_lag=5)


def _run_group(tfs, group_label):
    """Run the full comparison for one group of timeframes, period-matched
    to THEIR OWN shared common start date. Groups must be chosen so their
    members have genuinely comparable native cached depth — mixing a TF
    with a few months of history (15min/30min) into the same group as one
    with years of history (1h/4h/1day) forces everything down to the
    shallowest TF's window and destroys the comparison (caught directly
    on real data, 2026-07-14: an initial single-group-of-5 version
    collapsed the 1h/4h/1day comparison to a ~4-month window because
    15min's cache only goes back that far, flipping 9/9 significant pairs
    down to 1/9 — not a real finding, a period-matching bug)."""
    from data import DataStore
    tf_starts = []
    for tf in tfs:
        df_ref = DataStore.load(_DEFAULT_PAIRS[0][0], tf)
        if df_ref is not None and not df_ref.empty:
            tf_starts.append(df_ref.index.min())
    match_start = max(tf_starts) if tf_starts else None
    print(f"\n{'='*70}\nGroup: {group_label} ({', '.join(tfs)})")
    print(f"Period-matched to >= {match_start.date() if match_start is not None else 'N/A'} "
          f"(latest common start among this group's own native depth)\n")

    rows = []
    for sym_a, sym_b in _DEFAULT_PAIRS:
        row = {"symbol_a": sym_a, "symbol_b": sym_b}
        for tf in tfs:
            pval, n = eg_pvalue_for_pair(sym_a, sym_b, tf, min_date=match_start)
            row[f"{tf}_p"] = pval
            row[f"{tf}_n"] = n
        rows.append(row)

    df = pd.DataFrame(rows)
    display_cols = ["symbol_a", "symbol_b"] + [f"{tf}_p" for tf in tfs]
    print(df[display_cols].to_string(index=False, float_format=lambda x: f"{x:.4f}" if pd.notna(x) else "N/A"))

    print(f"\nSignificance (p<0.05) rate by timeframe:")
    for tf in tfs:
        valid = df[f"{tf}_p"].dropna()
        n_sig = (valid < 0.05).sum()
        print(f"  {tf}: {n_sig}/{len(valid)} pairs significant")

    consistent_count = 0
    for _, r in df.iterrows():
        verdicts = [r[f"{tf}_p"] < 0.05 for tf in tfs if pd.notna(r[f"{tf}_p"])]
        if verdicts and len(set(verdicts)) == 1:
            consistent_count += 1
    print(f"\n{consistent_count}/{len(df)} pairs have a CONSISTENT significance verdict "
          f"across all {len(tfs)} TFs in this group.")

    grid = []
    for tf in tfs:
        valid = df[f"{tf}_p"].dropna()
        valid = valid[valid > 0]
        if valid.empty:
            continue
        mean_log_p = float(np.mean(np.log10(valid)))
        bpd = _BARS_PER_DAY.get(tf, np.nan)
        grid.append((tf, bpd, mean_log_p))
    if len(grid) >= 3:
        bpds = np.array([g[1] for g in grid])
        logps = np.array([g[2] for g in grid])
        corr = float(np.corrcoef(np.log10(bpds), logps)[0, 1])
        print(f"Correlation(log10(bars/day), mean log10(p)) = {corr:.3f} within this group.")

    return df


def main():
    p = argparse.ArgumentParser(description="Cross-timeframe cointegration divergence study (2026-07-14)")
    args = p.parse_args()

    # Two groups, chosen by comparable native cached depth (checked
    # directly, not assumed) — see _run_group's docstring for why mixing
    # depths breaks the comparison.
    df_deep = _run_group(["1hr", "4hr", "1day"], "deep-history group (~3yr+ shared depth)")
    df_shallow = _run_group(["15min", "30min", "1hr"], "shallow-history group (~4mo shared depth)")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    df_deep.to_parquet(os.path.join(out_dir, "cross_timeframe_divergence_deep.parquet"))
    df_shallow.to_parquet(os.path.join(out_dir, "cross_timeframe_divergence_shallow.parquet"))
    print(f"\nResults written to output/research/cross_timeframe_divergence_{{deep,shallow}}.parquet")


if __name__ == "__main__":
    main()
