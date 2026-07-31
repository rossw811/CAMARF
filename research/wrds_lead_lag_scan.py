"""
research/wrds_lead_lag_scan.py -- lead-lag scan extended to WRDS-confirmed
pairs (the Tier 1/2/3 episodic scan's own output), added 2026-07-27 per
Ross's direct request: "as for the international symbols we do want to do
the lead lag tests we currently have."

The existing `research/lead_lag_scan.py` only reads production's own
confirmed pairs (`output/results/*/pairs.parquet`), loaded via
`aligned_pair_loader.load_aligned_pair` (the yfinance/IBKR-based
`DataStore`/`DataAligner`) -- it has NO path to WRDS-sourced data at all,
and the new international symbols will never appear in
`output/results/*/pairs.parquet` since they aren't part of production's own
analysis.py pipeline. This script reuses `lead_lag_scan.py`'s exact
two-stage methodology (cheap lagged-correlation scan -> EG-at-best-lag
confirm) unchanged, swapping only the two things that genuinely differ for
WRDS data:
  1. Confirmed-pair SOURCE: reads from this project's own WRDS episodic-scan
     output (`output/research/wrds_deep_history_episodic_scan_tier{1,2,3}
     _*.parquet`) instead of production's `output/results/*/pairs.parquet`.
  2. Price-data SOURCE: loads directly from `output/cache/wrds/{label}_1D.
     parquet` (same close/close_total_return convention
     `wrds_deep_history_episodic_scan.py`'s own `load_wrds_universe` uses)
     instead of `load_aligned_pair`'s yfinance/IBKR `DataStore`, which has no
     knowledge of the WRDS cache layout.

WRDS daily data does NOT need `lead_lag_scan.py`'s `_gap_aware_returns`
24/7-calendar-padding correction -- that problem is specific to yfinance/
IBKR INTRADAY data reindexed onto a 24/7 calendar by
`DataAligner.align_intraday()`. WRDS's CRSP/Compustat Global daily bars are
already real, unpadded trading-day observations, so plain log-price
differencing is used instead (matching `wrds_deep_history_episodic_scan.py`'s
own `build_log_prices_and_returns` convention) -- deliberately NOT
importing `_gap_aware_returns`/`_clean_close` from `data.py`, since that
would drag in data.py's yfinance/IBKR import chain into a WRDS-only,
read-only research script (same reasoning `ml.py`'s own `_TF_SAFE`
duplication comment already gives for staying import-independent).

Verified against synthetic ground truth first:
debug/_verify_wrds_lead_lag_scan.py.

Usage:
    python research/wrds_lead_lag_scan.py                  # Tier 1 confirmed pairs
    python research/wrds_lead_lag_scan.py --tier 2          # Tier 2 episodic-confirmed pairs
    python research/wrds_lead_lag_scan.py --max-lag 15 --min-lift 0.05
"""
import argparse
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from analysis import _eg_worker

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WRDS_CACHE_DIR = os.path.join(_ROOT, "output", "cache", "wrds")
_RESEARCH_DIR = os.path.join(_ROOT, "output", "research")

_MIN_CORR_N = 30
_MIN_EG_N = 60
_TF_LABEL = "1D_wrds_leadlag"

log = logging.getLogger("wrds_lead_lag_scan")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(os.path.join(_ROOT, "latest_run_wrds_lead_lag_scan.log"),
                              mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def load_price_series(label: str):
    """Loads one WRDS-cached symbol's LOG-price series (not returns yet),
    using close_total_return where available (CRSP), falling back to
    split-only close (Compustat Global, not yet total-return-adjusted --
    same disclosed convention as load_wrds_universe). Returns None if the
    symbol's cache file doesn't exist."""
    path = os.path.join(_WRDS_CACHE_DIR, f"{label}_1D.parquet")
    if not os.path.exists(path):
        return None
    df = pd.read_parquet(path)
    if "close_total_return" in df.columns and df["close_total_return"].notna().any():
        close = df["close_total_return"]
    else:
        close = df["close"]
    close = pd.to_numeric(close, errors="coerce").astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        log_p = np.log(close)
    log_p[~np.isfinite(log_p)] = np.nan
    return pd.Series(log_p.values, index=close.index)


def lagged_corr_scan(ret_a: pd.Series, ret_b: pd.Series, max_lag: int):
    """Identical methodology to lead_lag_scan.py's own function of the same
    name (kept as a separate implementation, not imported, specifically to
    avoid dragging data.py's yfinance/IBKR import chain into this WRDS-only
    script). Returns {lag: (corr, n)} for lag in [-max_lag, max_lag] --
    lag>0 means corr(ret_a_t, ret_b_{t+lag}), i.e. A leads B by `lag` bars."""
    out = {}
    for lag in range(-max_lag, max_lag + 1):
        shifted_b = ret_b.shift(-lag)
        joined = pd.concat([ret_a, shifted_b], axis=1, join="inner").dropna()
        n = len(joined)
        if n < _MIN_CORR_N:
            out[lag] = (None, n)
            continue
        c = float(np.corrcoef(joined.iloc[:, 0].values, joined.iloc[:, 1].values)[0, 1])
        if not np.isfinite(c):
            c = None
        out[lag] = (c, n)
    return out


def best_lag(scan):
    """Returns (best_lag, best_corr, best_n) among lags with a valid
    (non-None) correlation, by |corr| -- identical to lead_lag_scan.py's own."""
    valid = {k: v for k, v in scan.items() if v[0] is not None}
    if not valid:
        return None, None, None
    k_star = max(valid, key=lambda k: abs(valid[k][0]))
    c_star, n_star = valid[k_star]
    return k_star, c_star, n_star


def load_confirmed_pairs(tier: int):
    """Loads the (symbol_a, symbol_b) confirmed-pair list from the WRDS
    episodic scan's own Tier 1/2/3 output. Tier 1 = full-sample-confirmed
    (fdr_confirmed column); Tier 2/3 = episodic-confirmed (their own
    *_confirmed.parquet files, already only contain confirmed rows)."""
    if tier == 1:
        path = os.path.join(_RESEARCH_DIR, "wrds_deep_history_episodic_scan_tier1.parquet")
        if not os.path.exists(path):
            return []
        df = pd.read_parquet(path)
        if "fdr_confirmed" not in df.columns:
            return []
        df = df[df["fdr_confirmed"] == True]  # noqa: E712
        return list(zip(df["symbol_a"], df["symbol_b"]))
    else:
        path = os.path.join(_RESEARCH_DIR, f"wrds_deep_history_episodic_scan_tier{tier}_confirmed.parquet")
        if not os.path.exists(path):
            return []
        df = pd.read_parquet(path)
        return list(zip(df["symbol_a"], df["symbol_b"]))


def scan_pair(sym_a: str, sym_b: str, max_lag: int, min_lift: float, max_eg_lag: int):
    """Runs the full two-stage lead-lag check for one confirmed pair.
    Returns a result dict, or None if there's insufficient data to say
    anything (logged by the caller, not silently dropped)."""
    logp_a = load_price_series(sym_a)
    logp_b = load_price_series(sym_b)
    if logp_a is None or logp_b is None:
        return {"skip_reason": "cache missing for one leg"}

    ret_a = logp_a.diff()
    ret_b = logp_b.diff()
    scan = lagged_corr_scan(ret_a, ret_b, max_lag)
    k_star, c_star, n_star = best_lag(scan)
    c0, n0 = scan.get(0, (None, 0))
    if k_star is None or c0 is None:
        return {"skip_reason": f"insufficient overlapping return data at any lag (need >={_MIN_CORR_N})"}

    lift = abs(c_star) - abs(c0)
    flagged = (k_star != 0) and (lift >= min_lift)

    eg_p0 = eg_pstar = None
    if flagged:
        joined0 = pd.concat([logp_a, logp_b], axis=1, join="inner").dropna()
        if len(joined0) >= _MIN_EG_N:
            r0 = _eg_worker(("A", "B", joined0.iloc[:, 0].to_numpy(), joined0.iloc[:, 1].to_numpy(),
                              max_eg_lag, _TF_LABEL))
            eg_p0 = r0.get("pvalue") if r0.get("ok") else None

        shifted_b = logp_b.shift(-k_star)
        joined_k = pd.concat([logp_a, shifted_b], axis=1, join="inner").dropna()
        if len(joined_k) >= _MIN_EG_N:
            rk = _eg_worker(("A", "B", joined_k.iloc[:, 0].to_numpy(), joined_k.iloc[:, 1].to_numpy(),
                              max_eg_lag, _TF_LABEL))
            eg_pstar = rk.get("pvalue") if rk.get("ok") else None

    return {
        "best_lag": k_star, "corr_at_best_lag": c_star, "n_at_best_lag": n_star,
        "corr_at_lag0": c0, "n_at_lag0": n0, "corr_lift": lift,
        "flagged_lag_worth_checking": flagged,
        "eg_p_lag0": eg_p0, "eg_p_best_lag": eg_pstar,
    }


def main():
    p = argparse.ArgumentParser(description="Lead-lag scan on WRDS-confirmed pairs (2026-07-27)")
    p.add_argument("--max-lag", type=int, default=Config.RESEARCH.LEAD_LAG_MAX_LAG,
                    help="Max bars to search in each direction (fixed bar count). "
                         "Default sourced from Config.RESEARCH.LEAD_LAG_MAX_LAG, same as lead_lag_scan.py.")
    p.add_argument("--min-lift", type=float, default=0.05,
                    help="Minimum |corr(k*)| - |corr(0)| to flag a pair and trigger the EG confirm stage")
    p.add_argument("--tier", type=int, default=1, choices=[1, 2, 3],
                    help="Which WRDS episodic-scan tier's confirmed pairs to scan (default: Tier 1)")
    args = p.parse_args()
    _setup_logging()
    max_eg_lag = Config.ANALYSIS.EG_MAX_LAG

    pairs = load_confirmed_pairs(args.tier)
    log.info(f"=== wrds_lead_lag_scan.py: Tier {args.tier} confirmed pairs, "
             f"applying lead_lag_scan.py's methodology to WRDS-sourced data ===")
    log.info(f"Tier {args.tier}: {len(pairs)} confirmed pairs to scan")
    if not pairs:
        log.warning(f"No confirmed pairs found for Tier {args.tier} -- has "
                    f"research/wrds_deep_history_episodic_scan.py been run yet?")
        return

    rows = []
    for sym_a, sym_b in pairs:
        result = scan_pair(sym_a, sym_b, args.max_lag, args.min_lift, max_eg_lag)
        if "skip_reason" in result:
            log.info(f"SKIP {sym_a}/{sym_b}: {result['skip_reason']}")
            continue
        result["symbol_a"], result["symbol_b"] = sym_a, sym_b
        rows.append(result)
        status = "FLAG" if result["flagged_lag_worth_checking"] else "ok"
        log.info(f"{status:5s} {sym_a}/{sym_b}: best_lag={result['best_lag']} "
                 f"corr*={result['corr_at_best_lag']:.3f}(n={result['n_at_best_lag']}) "
                 f"corr0={result['corr_at_lag0']:.3f}(n={result['n_at_lag0']}) "
                 f"lift={result['corr_lift']:.3f}")

    if not rows:
        log.warning("No confirmed pairs with sufficient data found.")
        return

    result_df = pd.DataFrame(rows)
    flagged_df = result_df[result_df["flagged_lag_worth_checking"]]
    log.info(f"=== {len(flagged_df)}/{len(result_df)} confirmed pairs show a non-zero lag with "
             f"a correlation lift >= {args.min_lift} over lag 0 ===")
    if not flagged_df.empty:
        eg_improves = flagged_df[
            flagged_df["eg_p_best_lag"].notna() & flagged_df["eg_p_lag0"].notna()
            & (flagged_df["eg_p_best_lag"] < flagged_df["eg_p_lag0"])
        ]
        log.info(f"Of those, {len(eg_improves)}/{len(flagged_df)} also show a LOWER "
                 f"(more significant) EG p-value at the lagged alignment than at lag 0.")

    os.makedirs(_RESEARCH_DIR, exist_ok=True)
    out_path = os.path.join(_RESEARCH_DIR, f"wrds_lead_lag_scan_tier{args.tier}.parquet")
    result_df.to_parquet(out_path, index=False)
    log.info(f"Saved -> output/research/wrds_lead_lag_scan_tier{args.tier}.parquet")


if __name__ == "__main__":
    main()
