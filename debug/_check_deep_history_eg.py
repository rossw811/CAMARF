"""
Ad-hoc check (task #71 follow-up, 2026-07-14): does IBKR 10-year deep history
restore/strengthen EG cointegration significance for the 9 formerly-confirmed
1h pairs that do NOT involve the BUG-D65/D66-contaminated symbols?

Reuses production's own gap-aware EG machinery (_gap_masked_log_price,
_eg_pvalue from research/lead_lag_scan.py) and the exact same main+supplement
merge logic as analysis.py's _enrich_with_deep_history (supplement's older
history + main cache's current window, main cache wins on overlap).
"""
import sys
import os
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "research"))

import pandas as pd
import numpy as np

from data import DataStore
from ibkr_supplement_reader import load_supplement
from lead_lag_scan import _gap_masked_log_price, _eg_pvalue

PAIRS = [
    ("LNT", "VTR"), ("LNT", "WELL"), ("AME", "MAR"), ("CMS", "DUK"),
    ("EG", "WRB"), ("HAL", "NOV"), ("MET", "TMHC"), ("PFG", "STLD"),
    ("UMBF", "FHB"),
]

TF = "1hr"


def _merge(main_df, sup_df):
    if sup_df is None:
        return main_df
    combined = pd.concat([sup_df, main_df])
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


print(f"{'pair':<16} {'main_n':>8} {'deep_n':>8} {'merged_n':>9} {'p_main':>10} {'p_merged':>10}")
for sym_a, sym_b in PAIRS:
    main_a = DataStore.load(sym_a, TF)
    main_b = DataStore.load(sym_b, TF)
    sup_a = load_supplement(sym_a, TF)
    sup_b = load_supplement(sym_b, TF)

    merged_a = _merge(main_a, sup_a)
    merged_b = _merge(main_b, sup_b)

    # main-only (matches what production's EG+BH-FDR stage actually sees)
    log_a_main = pd.Series(_gap_masked_log_price(main_a), index=main_a.index)
    log_b_main = pd.Series(_gap_masked_log_price(main_b), index=main_b.index)
    shared_main = log_a_main.index.intersection(log_b_main.index)
    la_m = log_a_main.reindex(shared_main).values
    lb_m = log_b_main.reindex(shared_main).values
    p_main, n_main = _eg_pvalue(la_m, lb_m, max_eg_lag=5)

    # merged (main + IBKR deep supplement)
    log_a_deep = pd.Series(_gap_masked_log_price(merged_a), index=merged_a.index)
    log_b_deep = pd.Series(_gap_masked_log_price(merged_b), index=merged_b.index)
    shared_deep = log_a_deep.index.intersection(log_b_deep.index)
    la_d = log_a_deep.reindex(shared_deep).values
    lb_d = log_b_deep.reindex(shared_deep).values
    p_deep, n_deep = _eg_pvalue(la_d, lb_d, max_eg_lag=5)

    deep_n_a = len(sup_a) if sup_a is not None else 0

    p_main_s = f"{p_main:.6f}" if p_main is not None else "N/A"
    p_deep_s = f"{p_deep:.6f}" if p_deep is not None else "N/A"
    print(f"{sym_a}/{sym_b:<12} {n_main:>8} {deep_n_a:>8} {n_deep:>9} {p_main_s:>10} {p_deep_s:>10}")
