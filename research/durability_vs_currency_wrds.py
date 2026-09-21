"""
research/durability_vs_currency_wrds.py -- Re-derives PAPER.md §4.2's
durability-vs-currency demonstration (NTRS/STT, SHW/UNP: full-sample EG
significance vs. last-5-years-only EG significance) on real WRDS/CRSP
data, replacing the original pre-WRDS (yfinance-era) demonstration per
Ross's 2026-09-10 instruction: nothing pre-WRDS gets considered for
writing. Same pairs, same logic, same `analysis.py._eg_worker` production
function -- only the data source changes, so this is a direct like-for-
like re-derivation, not a new claim.

Run: python research/durability_vs_currency_wrds.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis import _eg_worker

WRDS_CACHE = Path(__file__).resolve().parent.parent / "output" / "cache" / "wrds"
PAIRS = [("XOM", "CVX"), ("JPM", "BAC"), ("KO", "PEP"), ("NTRS", "STT"), ("SHW", "UNP")]


def load_log_close(symbol):
    df = pd.read_parquet(WRDS_CACHE / f"{symbol}_1D.parquet")
    close = df["close_total_return"].astype(float)
    return np.log(close.values), df.index


def run_pair(sym_a, sym_b):
    a_log, a_idx = load_log_close(sym_a)
    b_log, b_idx = load_log_close(sym_b)
    a_series = pd.Series(a_log, index=a_idx)
    b_series = pd.Series(b_log, index=b_idx)
    common = a_series.index.intersection(b_series.index)
    a_aligned = a_series.loc[common]
    b_aligned = b_series.loc[common]

    full_start, full_end = common.min(), common.max()
    n_full = len(common)

    r_full = _eg_worker((sym_a, sym_b, a_aligned.values, b_aligned.values, None, "1D"))

    cutoff = full_end - pd.DateOffset(years=5)
    recent_mask = common >= cutoff
    a_recent = a_aligned.values[recent_mask]
    b_recent = b_aligned.values[recent_mask]
    r_recent = _eg_worker((sym_a, sym_b, a_recent, b_recent, None, "1D"))

    print(f"\n{sym_a}/{sym_b}:")
    print(f"  Full-sample ({full_start.date()} to {full_end.date()}, n={n_full}): "
          f"EG p={r_full['pvalue']:.4f} (ok={r_full['ok']})")
    print(f"  Last 5 years ({cutoff.date()} to {full_end.date()}, n={recent_mask.sum()}): "
          f"EG p={r_recent['pvalue']:.4f} (ok={r_recent['ok']})")
    return {
        "pair": f"{sym_a}/{sym_b}",
        "full_start": str(full_start.date()),
        "full_end": str(full_end.date()),
        "n_full": n_full,
        "p_full": r_full["pvalue"],
        "n_recent": int(recent_mask.sum()),
        "p_recent": r_recent["pvalue"],
    }


if __name__ == "__main__":
    results = [run_pair(a, b) for a, b in PAIRS]
    out_df = pd.DataFrame(results)
    out_path = Path(__file__).resolve().parent.parent / "output" / "research" / "durability_vs_currency_wrds.parquet"
    out_df.to_parquet(out_path)
    print(f"\nSaved to {out_path}")
    print(out_df.to_string())
