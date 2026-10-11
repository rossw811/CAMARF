"""
research/rederive_durability_claims.py -- S34 re-derivation of central claims P-009 / P-074 / P-075 / P-076
(PAPER.md abstract and §4.2 table: full-sample vs last-5-years Engle-Granger p-values for XOM/CVX, JPM/BAC, KO/PEP,
NTRS/STT, SHW/UNP on WRDS/CRSP total-return closes).

Two arms, same data, same production `analysis._eg_worker`:
  as_published  -- research/durability_vs_currency_wrds.py's method: one direction (A on B), close_total_return as
                   stored (CRSP no-trade midpoint days included).
  current_rules -- the rules discovery now uses: the S35 no-trade mask (data_wrds.crsp_no_trade_mask), the
                   both-directions max p-value and max_lag = Config.ANALYSIS.EG_MAX_LAG (wrds_deep_history_episodic_scan
                   / CointScanner.scan convention; the first version of this script left max_lag=None here -- caught by
                   the 2026-10-10 adversarial review). Each direction's p-value is reported beside the max.
For each test, the n reported is what EG actually used: `_eg_worker` keeps only the longest stretch with no genuine
data gap (data.longest_gap_respecting_segment), so its `n_overlap` and that stretch's first/last dates are reported,
alongside the count of days on which both legs have a price (what the published table counted).
Last 5 years = the 5 calendar years ending at the pair's last common valid date (published convention).
Output: output/research/rederive_durability_claims.parquet (never overwrites the original script's output).
Run: python research/rederive_durability_claims.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analysis import _eg_worker  # noqa: E402
from config import Config  # noqa: E402
from data import longest_gap_respecting_segment  # noqa: E402
import data_wrds as dw  # noqa: E402

WRDS_CACHE = ROOT / "output" / "cache" / "wrds"
OUT = ROOT / "output" / "research" / "rederive_durability_claims.parquet"
PAIRS = [("XOM", "CVX"), ("JPM", "BAC"), ("KO", "PEP"), ("NTRS", "STT"), ("SHW", "UNP")]


def load_close(symbol: str, mask_no_trade: bool) -> pd.Series:
    df = pd.read_parquet(WRDS_CACHE / f"{symbol}_1D.parquet")
    px = df["close_total_return"].astype(float)
    if mask_no_trade:
        px = dw.crsp_no_trade_mask(df, symbol, px)
    return px


def eg(a: pd.Series, b: pd.Series, current: bool) -> dict:
    la, lb = np.log(a.to_numpy()), np.log(b.to_numpy())
    lag = Config.ANALYSIS.EG_MAX_LAG if current else None
    r_ab = _eg_worker((a.name, b.name, la, lb, lag, "1D"))
    r_ba = _eg_worker((b.name, a.name, lb, la, lag, "1D"))
    p = max(r_ab["pvalue"], r_ba["pvalue"]) if current else r_ab["pvalue"]
    keep = longest_gap_respecting_segment(np.isfinite(la) & np.isfinite(lb), "1D")
    idx = a.index[keep]
    return {"p": float(p), "p_ab": float(r_ab["pvalue"]), "p_ba": float(r_ba["pvalue"]), "n_eg": int(r_ab["n_overlap"]),
            "seg_start": str(idx.min().date()), "seg_end": str(idx.max().date()),
            "n_both_valid": int((np.isfinite(la) & np.isfinite(lb)).sum())}


def run_pair(sa: str, sb: str, arm: str) -> dict:
    cur = arm == "current_rules"
    a, b = load_close(sa, cur), load_close(sb, cur)
    common = a.index.intersection(b.index)
    a, b = a.loc[common].rename(sa), b.loc[common].rename(sb)
    valid = np.isfinite(np.log(a)) & np.isfinite(np.log(b))
    end = common[valid.to_numpy()].max()
    cutoff = end - pd.DateOffset(years=5)
    full = eg(a, b, cur)
    rec = eg(a[common >= cutoff], b[common >= cutoff], cur)
    return {"pair": f"{sa}/{sb}", "arm": arm, "p_full": full["p"], "p_full_ab": full["p_ab"], "p_full_ba": full["p_ba"],
            "n_eg_full": full["n_eg"],
            "seg_start_full": full["seg_start"], "seg_end_full": full["seg_end"],
            "n_both_valid_full": full["n_both_valid"], "p_recent": rec["p"], "p_recent_ab": rec["p_ab"],
            "p_recent_ba": rec["p_ba"], "n_eg_recent": rec["n_eg"],
            "recent_start": str(cutoff.date()), "recent_end": str(end.date())}


def main():
    rows = [run_pair(a, b, arm) for arm in ("as_published", "current_rules") for a, b in PAIRS]
    out = pd.DataFrame(rows)
    out.to_parquet(OUT)
    with pd.option_context("display.width", 220, "display.max_columns", 20):
        print(out.to_string(index=False))
    print(f"\nSaved to {OUT}")


if __name__ == "__main__":
    main()
