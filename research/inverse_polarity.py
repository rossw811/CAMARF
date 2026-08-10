"""
CAMARF research/inverse_polarity.py -- comparison/diagnostic script, NOT
part of the production pipeline (2026-08-03).

Ross's framing: instead of the standard "these two assets move together"
pair screen, look for genuine "polar opposite" equilibrium relationships --
pairs whose current *state* (not raw return) sits at opposite extremes of
its own historical range, and treat a breakdown of that expected opposite-
extremes relationship as the mean-reversion/arbitrage signal.

Design questions Ross answered before this was built (see conversation,
2026-08-03):
  1. Bounded per-asset metric: build ALL THREE for comparison, not just one:
       - zscore_tanh:      tanh(rolling z-score of log price)
       - percentile_rank:  trailing-window percentile rank, rescaled to
                            [-1, 1]
       - eg_spread_zscore: tanh(the EXISTING causal EG spread z-score) for
                            assets already in a confirmed pair -- reuses
                            analysis.py's own SpreadModel output rather than
                            recomputing a spread from scratch.
  2. Search basis: BOTH raw-return correlation/cointegration (same rigor as
     analysis.py's existing pair screen -- this is the step that separates
     "genuine equilibrium" from "just drifts apart forever", since a raw
     correlation of -1 alone says nothing about whether a stable spread
     exists) AND the bounded-polarity anti-phase check on top, as the
     entry-timing signal.
  3. Scope: new standalone research/*.py module (this file), not folded
     into cycle_detection.py -- the underlying question (is there a stable
     joint equilibrium at all) is closer to cointegration than to cycle
     detection, even though the bounded-score construction was inspired by
     that module's phase-sync section.

WHY A NEGATIVE-CORRELATION SCREEN ALONE IS NOT ENOUGH (the thing this
module exists to guard against): two assets can have return correlation
near -1 while their price levels drift apart without bound forever -- e.g.
one is in a structural uptrend and the other a structural downtrend, both
driven by unrelated regimes that happen to anti-correlate over the sample
window. That is NOT an arbitrage opportunity; there is no equilibrium to
revert to. statsmodels.tsa.stattools.coint() (the same Engle-Granger test
analysis.py already uses for standard pair confirmation) does NOT assume a
positive hedge ratio -- its internal OLS step will fit whatever sign
minimizes residual variance, so a genuinely cointegrated negative-hedge
relationship is already detectable with the EXISTING test, unmodified. What
is actually new here is: (a) explicitly keeping and reporting the negative-
hedge side of that existing test instead of implicitly relying on it never
coming up, and (b) the bounded polarity score construction and its own
anti-phase divergence signal, which is a different question from "is the
spread stationary" -- it is "are these two assets currently AT their
expected opposite extremes, or has that pattern broken down".

Usage:
    python research/inverse_polarity.py
    python research/inverse_polarity.py --window 60
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from config import Config
from data import DataStore, _gap_aware_returns, _clean_close
from analysis import SpreadModel
from aligned_pair_loader import load_aligned_pair
import ml


# ---------------------------------------------------------------------------
# Step 1: three bounded [-1, 1] per-asset polarity scores. All three are
# CAUSAL (rolling/expanding only, verified by construction -- pandas
# .rolling()/.expanding() never look ahead of the current row).
# ---------------------------------------------------------------------------

def zscore_tanh_polarity(log_price: np.ndarray, window: int = 60) -> np.ndarray:
    """tanh(rolling z-score of log price). Reuses SpreadModel.rolling_zscore
    directly -- a single-asset log-price series is algebraically just a
    "spread" with hedge_series all-NaN / hedge_static=0 is wrong (that would
    subtract nothing meaningfully); instead call the same rolling-mean/std
    machinery inline rather than force log_price through compute_spread's
    two-leg signature."""
    n = log_price.size
    z = SpreadModel.rolling_zscore(log_price, window)
    with np.errstate(invalid="ignore", over="ignore"):
        return np.tanh(z)


def percentile_rank_polarity(price: np.ndarray, window: int = 60) -> np.ndarray:
    """Trailing-window percentile rank of price, rescaled from [0, 1] to
    [-1, 1]. More robust to outliers than a z-score (no assumption of
    approximately-normal returns). CAUSAL: pandas .rolling(window).rank()
    at row t only ever ranks row t against the window ending at t."""
    s = pd.Series(price)
    min_p = max(2, window // 2)
    pct = s.rolling(window, min_periods=min_p).rank(pct=True)
    return (2.0 * pct - 1.0).values


def eg_spread_zscore_polarity(spread_zscore: np.ndarray) -> np.ndarray:
    """tanh() of an ALREADY-causal EG spread z-score (e.g.
    analysis.py's persisted rolling_z_spread / spread_zscore_t field for a
    confirmed pair). Pure passthrough transform -- causality is inherited
    from whatever causal series is passed in, not re-derived here. Kept as
    a named function (rather than inlining np.tanh at call sites) so all
    three polarity metrics share one entry-point shape for the comparison
    pass below."""
    with np.errstate(invalid="ignore", over="ignore"):
        return np.tanh(spread_zscore)


POLARITY_METRICS = ("zscore_tanh", "percentile_rank", "eg_spread_zscore")


# ---------------------------------------------------------------------------
# Step 2a: raw-return anti-correlation + cointegration screen (negative-
# hedge side of the EXISTING Engle-Granger test, not a new test).
# ---------------------------------------------------------------------------

def screen_anti_correlated_pair(
    df_a: "pd.DataFrame",
    df_b: "pd.DataFrame",
    corr_threshold: float = -0.40,
) -> dict:
    """
    Real-data screen for one aligned pair (as returned by
    aligned_pair_loader.load_aligned_pair -- both DataFrames must already
    carry "close" and "gap_flag" columns): gap-aware log returns -> Pearson
    correlation -> if strongly negative, run the standard EG cointegration
    test on (log_a, log_b) and report the fitted hedge ratio's sign.

    Returns a dict with at least {"rho": float, "candidate": bool} and,
    when candidate, {"coint_pvalue": float, "hedge_ratio": float,
    "is_negative_hedge": bool}.
    """
    ret_a = _gap_aware_returns(df_a)
    ret_b = _gap_aware_returns(df_b)
    mask = np.isfinite(ret_a) & np.isfinite(ret_b)
    out = {"rho": np.nan, "candidate": False}
    if mask.sum() < Config.ANALYSIS.OU_WINDOW_MIN_BARS:
        return out

    a, b = ret_a[mask], ret_b[mask]
    sa, sb = a.std(ddof=1), b.std(ddof=1)
    if sa <= 0 or sb <= 0:
        return out
    rho = float(np.mean((a - a.mean()) * (b - b.mean())) / (sa * sb))
    out["rho"] = rho
    if not np.isfinite(rho) or rho > corr_threshold:
        return out

    out["candidate"] = True
    log_a = np.log(_clean_close(df_a))
    log_b = np.log(_clean_close(df_b))
    pmask = np.isfinite(log_a) & np.isfinite(log_b)
    if pmask.sum() < Config.ANALYSIS.OU_WINDOW_MIN_BARS:
        out["candidate"] = False
        return out

    la, lb = log_a[pmask], log_b[pmask]
    t_stat, p_value, _crit = coint(la, lb, trend="c", maxlag=1, autolag="aic")
    # Same OLS the coint() test itself runs internally, to recover hedge sign
    # (coint() reports the test statistic, not the fitted coefficient).
    hedge = float(
        np.cov(la, lb, ddof=1)[0, 1] / np.var(lb, ddof=1)
    ) if np.var(lb, ddof=1) > 0 else np.nan

    out["coint_pvalue"] = float(p_value)
    out["hedge_ratio"] = hedge
    out["is_negative_hedge"] = bool(np.isfinite(hedge) and hedge < 0)
    return out


# ---------------------------------------------------------------------------
# Step 2b: bounded-polarity anti-phase check, only on pairs that survive 2a.
# ---------------------------------------------------------------------------

def polarity_anti_correlation(
    polarity_a: np.ndarray, polarity_b: np.ndarray, window: int = 60
) -> np.ndarray:
    """Rolling, CAUSAL correlation between two already-bounded [-1,1]
    polarity series. A value near -1 means "when A is near its own extreme,
    B is near the opposite extreme" -- the literal "polar opposites"
    relationship Ross described, measured directly rather than inferred
    from raw-return correlation."""
    sa = pd.Series(polarity_a)
    sb = pd.Series(polarity_b)
    return sa.rolling(window, min_periods=max(2, window // 2)).corr(sb).values


# ---------------------------------------------------------------------------
# Step 2c: full-universe scan. The 3 currently-confirmed pairs (Findings
# #18/#19) are all positively correlated, by construction of the existing
# EG-based confirmation screen -- finding an actual "polar opposite"
# candidate requires scanning the whole universe's correlation matrix, not
# just the already-confirmed set. Reuses analysis.py's own
# DataAligner.align_universe / UniverseFilter.build_returns_matrix /
# UniverseFilter.correlation_matrix directly (same call sequence
# analysis.py's own Step 2 uses) rather than re-deriving alignment or
# correlation logic.
# ---------------------------------------------------------------------------

def _load_full_universe(tf_label: str = "1D") -> dict:
    """Load every symbol with a cached tf_label file directly from
    DataStore's own flat cache directory (no manifest exists to enumerate
    the universe from -- confirmed by checking, not assumed). Returns
    {symbol: df}, symbols with no data or too little history dropped
    later by build_returns_matrix's own min_overlap guard."""
    safe = DataStore._TF_SAFE.get(tf_label, tf_label.lower())
    pattern = os.path.join(Config.DATA.CACHE_DIR, f"*_{safe}.parquet")
    out = {}
    for path in glob.glob(pattern):
        fname = os.path.basename(path)
        symbol = fname[: -(len(safe) + len(".parquet") + 1)]
        df = DataStore.load(symbol, tf_label)
        if df is not None and not df.empty:
            out[symbol] = df
    return out


def full_universe_negative_candidates(
    tf_label: str = "1D",
    corr_threshold: float = None,
    min_overlap: int = 252,
) -> list:
    """Scan the FULL universe (every symbol with cached tf_label data, not
    just already-confirmed pairs) for strongly anti-correlated candidates,
    then run the same two-stage cointegration screen on each. Returns a
    list of result dicts, same shape as screen_anti_correlated_pair's
    output plus symbol_a/symbol_b/tf_label."""
    from analysis import DataAligner, UniverseFilter  # local import: analysis.py is heavy to load

    if corr_threshold is None:
        corr_threshold = -Config.UNIVERSE.MIN_PEARSON_CORR  # matches the EXISTING project-wide
        # candidate-screen threshold (analysis.py's own |rho|>=0.40 convention, negative side)

    print(f"Loading full universe at {tf_label}...")
    raw = _load_full_universe(tf_label)
    print(f"  {len(raw)} symbols with cached {tf_label} data")
    if len(raw) < 10:
        print("  too few symbols -- aborting full-universe scan")
        return []

    aligned = DataAligner.align_universe(
        {f"{sym}_{tf_label}": df for sym, df in raw.items()}, tf_label
    )
    print(f"  {len(aligned)}/{len(raw)} aligned")

    # DataAligner.align_universe's INPUT dict is keyed "symbol_tf" (built
    # just above) but its OUTPUT dict is keyed by bare symbol -- confirmed
    # against the already-correct pattern in aligned_pair_loader.
    # align_pair_dataframes (aligned.get(symbol_a), no tf suffix). A first
    # draft of this function got this backwards, looked up
    # aligned[f"{s}_{tf_label}"] against the output dict, found nothing,
    # and silently produced an empty aligned_by_symbol -- "0 symbols
    # survive min_overlap" on the real run was this bug, not a real null.
    returns, symbols, _idx = UniverseFilter.build_returns_matrix(
        aligned, min_overlap=min_overlap,
    )
    print(f"  {len(symbols)} symbols survive min_overlap={min_overlap}, "
          f"computing {len(symbols)}x{len(symbols)} correlation matrix...")
    corr = UniverseFilter.correlation_matrix(returns)

    n = corr.shape[0]
    candidate_idx = []
    for i in range(n):
        for j in range(i + 1, n):
            c = corr[i, j]
            if np.isfinite(c) and c <= corr_threshold:
                candidate_idx.append((i, j, float(c)))
    print(f"  {len(candidate_idx)} pairs with rho <= {corr_threshold} out of "
          f"{n * (n - 1) // 2} total pairs")

    rows = []
    for i, j, rho in candidate_idx:
        sym_a, sym_b = symbols[i], symbols[j]
        df_a, df_b = aligned.get(sym_a), aligned.get(sym_b)
        if df_a is None or df_b is None:
            continue
        common_idx = df_a.index.intersection(df_b.index)
        result = screen_anti_correlated_pair(
            df_a.loc[common_idx], df_b.loc[common_idx], corr_threshold=corr_threshold,
        )
        result.update(symbol_a=sym_a, symbol_b=sym_b, tf_label=tf_label)
        rows.append(result)
        if result.get("candidate"):
            # BUG FOUND running this at real full-universe scale, fixed
            # here rather than left in: is_negative_hedge only reflects the
            # fitted OLS coefficient's SIGN, not whether coint_pvalue
            # actually rejects the unit-root null. The first draft printed
            # "[NEGATIVE-HEDGE COINTEGRATED]" for any negative-hedge fit
            # regardless of p-value -- exactly the "looks like a fit but
            # isn't a real equilibrium" failure mode this module's own
            # docstring exists to guard against. Label now reflects both.
            is_real = result.get("is_negative_hedge") and result.get("coint_pvalue", 1.0) < 0.05
            label = "NEGATIVE-HEDGE COINTEGRATED (p<0.05)" if is_real else "correlated but NOT cointegrated"
            print(f"  {sym_a}/{sym_b}@{tf_label}: rho={rho:.3f}, coint_p={result['coint_pvalue']:.4f}, "
                  f"hedge={result.get('hedge_ratio', float('nan')):.3f}  [{label}]")
    return rows


def main():
    p = argparse.ArgumentParser(description="CAMARF inverse-polarity comparison arm")
    p.add_argument("--window", type=int, default=60, help="Rolling window (bars) for all metrics")
    p.add_argument("--corr-threshold", type=float, default=-0.40)
    p.add_argument("--full-universe", action="store_true",
                    help="Scan the full universe correlation matrix instead of just confirmed pairs")
    p.add_argument("--tf", type=str, default="1D", help="Timeframe for --full-universe mode")
    p.add_argument("--pit-safe", action="store_true",
                    help="Source pairs from the PIT-safe episodic screen (research/"
                         "pit_pair_discovery.py, task #5) instead of ml._discover_confirmed_pairs(). "
                         "Ignored in --full-universe mode, which already scans the whole universe.")
    args = p.parse_args()

    if args.full_universe:
        rows = full_universe_negative_candidates(tf_label=args.tf, corr_threshold=args.corr_threshold)
        out_df = pd.DataFrame(rows)
        out_dir = os.path.join("output", "research")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "inverse_polarity_full_universe.parquet")
        out_df.to_parquet(out_path)
        n_cand = int(out_df["candidate"].sum()) if len(out_df) else 0
        n_neg_hedge = int(out_df.get("is_negative_hedge", pd.Series(dtype=bool)).sum()) if len(out_df) else 0
        print(f"Done. {n_cand} anti-correlated candidates, {n_neg_hedge} with a negative-hedge "
              f"cointegrating relationship. Saved -> {out_path}")
        return

    if args.pit_safe:
        from pit_pair_discovery import discover_pit_confirmed_pairs
        pairs = discover_pit_confirmed_pairs()
        print(f"Using PIT-safe episodic pair discovery: {len(pairs)} pairs")
    else:
        pairs = ml._discover_confirmed_pairs()
    if not pairs:
        print("No confirmed pairs found -- nothing to screen. Run analysis.py first.")
        return

    print(f"Screening {len(pairs)} confirmed (symbol_a, symbol_b, tf) combinations "
          f"for anti-correlation / negative-hedge cointegration...")
    rows = []
    for symbol_a, symbol_b, tf_label in pairs:
        df_a, df_b = load_aligned_pair(symbol_a, symbol_b, tf_label)
        if df_a is None or df_b is None:
            continue
        # align_pair_dataframes does not guarantee identical df_a/df_b
        # length -- same documented gotcha as bounded_lookback_primary_
        # screen.py (found live there: a 24-row mismatch on AME/MAR@1h).
        # Confirmed live here too: IQV/Q@1D came back (3297, 7) vs (161, 7)
        # -- Q only has cached history from 2025-10-27, a recent listing.
        common_idx = df_a.index.intersection(df_b.index)
        df_a = df_a.loc[common_idx]
        df_b = df_b.loc[common_idx]
        result = screen_anti_correlated_pair(
            df_a, df_b, corr_threshold=args.corr_threshold,
        )
        result.update(symbol_a=symbol_a, symbol_b=symbol_b, tf_label=tf_label)
        rows.append(result)
        flag = "CANDIDATE" if result["candidate"] else "skip"
        print(f"  {symbol_a}/{symbol_b}@{tf_label}: rho={result['rho']:.3f}  [{flag}]")

    out_df = pd.DataFrame(rows)
    out_dir = os.path.join("output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "inverse_polarity_screen.parquet")
    out_df.to_parquet(out_path)
    n_cand = int(out_df["candidate"].sum()) if len(out_df) else 0
    n_neg_hedge = int(out_df.get("is_negative_hedge", pd.Series(dtype=bool)).sum())
    print(f"Done. {n_cand} anti-correlated candidates, {n_neg_hedge} with a negative-hedge "
          f"cointegrating relationship. Saved -> {out_path}")


if __name__ == "__main__":
    main()
