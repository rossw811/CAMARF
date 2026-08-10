"""
CAMARF research/cross_timeframe_cointegration.py -- comparison/diagnostic
script, NOT part of the production pipeline (2026-08-04).

Ross's framing: does a genuine COINTEGRATING (stable, mean-reverting)
equilibrium exist between two assets sampled at DIFFERENT timeframes --
not just "does A's fine-frequency history predict B's coarse-frequency
next return" (already covered by research/midas_cross_asset_lead_lag.py,
a correlation-based screen, explicitly not a cointegration test per that
module's own docstring), and not just "does the same pair's same-TF test
verdict replicate across timeframes" (research/cross_timeframe_
divergence.py, cycle_detection.py's cross_timeframe_consistency -- both
still same-TF-per-leg, just repeated at different granularities).

THE CORE METHODOLOGICAL PROBLEM this module exists to solve: the
Engle-Granger test needs a shared time index. Two series sampled at
different frequencies do not have one. Three genuinely distinct ways to
resolve this were scoped with Ross and are all built here for comparison
(his explicit choice -- "try all for comparison"), not because they are
equivalent, but because they encode different bets about what "cross-
timeframe cointegration" should mean:

  METHOD A -- downsample-to-shared-frequency EG test. Resample the finer
    leg down to the coarser leg's own frequency (last-close-of-period),
    then run the EXISTING production EG test (same statsmodels.coint()
    call, same gap-aware convention as lead_lag_scan.py) at the shared,
    coarser frequency. Cheapest, most defensible (reuses the exact
    already-validated test), but throws away everything the fine leg's
    intraday dynamics might contribute -- if the interesting relationship
    IS in the fine leg's intraday behavior, downsampling erases it before
    the test ever runs.

  METHOD B -- MIDAS residual-stationarity test. Regresses the coarse
    leg's log-price LEVEL on a MIDAS-weighted (beta-polynomial, reusing
    midas_feature.py's beta_weights/midas_aggregate directly, not
    reimplemented) causal rolling aggregate of the fine leg's log-price
    level, then tests whether the regression RESIDUAL is stationary
    (ADF). This is the genuinely novel piece -- an actual mixed-frequency
    equilibrium test (is there a stable long-run relationship between the
    coarse level and a weighted summary of the fine leg's recent
    history), not a same-frequency proxy and not a correlation screen.

  METHOD C -- coarse-leads-fine predictive-residual test. Regresses the
    fine leg's FUTURE cumulative return (over the next coarse period)
    against the coarse leg's CURRENT level, then tests whether the
    resulting forecast residual behaves like a stationary, mean-reverting
    series (ADF on the residual) rather than just reporting a correlation
    coefficient (which is what midas_cross_asset_lead_lag.py already
    does). A forward-looking/predictive framing, distinct from Method B's
    contemporaneous-equilibrium framing, deliberately reusing the same
    "test the residual for stationarity" discipline rather than stopping
    at correlation.

SCOPE LIMITATION, disclosed upfront rather than discovered by a reader:
the full-universe scan (--full-universe) pre-filters CANDIDATE pairs via
the EXISTING same-timeframe correlation matrix at the COARSE timeframe
(reusing analysis.py's own UniverseFilter machinery, same convention as
research/inverse_polarity.py's full-universe mode built the same
session). This is a real, acknowledged limitation: a pair that is
genuinely unrelated at the coarse-frequency SAME-TF level but has a real
cross-frequency equilibrium would be filtered out before ever reaching
the cross-TF test. An unconstrained full N-by-N cross-TF search (loading
BOTH timeframes for every candidate pair) was judged too expensive for a
first pass; this pre-filter is the same tradeoff every other full-
universe screen this session made (a correlation-based Stage 1 ahead of
an expensive Stage 2), stated plainly rather than silently narrowing scope.

Usage:
    python research/cross_timeframe_cointegration.py
    python research/cross_timeframe_cointegration.py --full-universe --coarse-tf 1D --fine-tf 1h
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from config import Config
from data import DataStore, _gap_aware_returns, _clean_close
from midas_feature import beta_weights, midas_aggregate
import ml


# ---------------------------------------------------------------------------
# Method A -- downsample-to-shared-frequency EG test.
# ---------------------------------------------------------------------------

def method_a_downsample_eg(coarse_df: pd.DataFrame, fine_df: pd.DataFrame) -> dict:
    """Downsample fine_df's close to coarse_df's own index (last value at
    or before each coarse timestamp -- causal, no lookahead), then run the
    standard EG test at the shared, coarse frequency."""
    from statsmodels.tsa.stattools import coint

    coarse_close = _clean_close(coarse_df)
    fine_close_series = pd.Series(_clean_close(fine_df), index=fine_df.index).dropna()

    downsampled = []
    for ts in coarse_df.index:
        window = fine_close_series[fine_close_series.index <= ts]
        downsampled.append(window.iloc[-1] if len(window) else np.nan)
    downsampled = np.array(downsampled)

    mask = np.isfinite(coarse_close) & np.isfinite(downsampled) & (coarse_close > 0) & (downsampled > 0)
    if mask.sum() < Config.ANALYSIS.OU_WINDOW_MIN_BARS:
        return {"method": "A_downsample_eg", "n": int(mask.sum()), "coint_pvalue": np.nan}

    log_coarse = np.log(coarse_close[mask])
    log_fine_ds = np.log(downsampled[mask])
    t_stat, p_value, _crit = coint(log_coarse, log_fine_ds, trend="c", maxlag=1, autolag="aic")
    return {"method": "A_downsample_eg", "n": int(mask.sum()), "coint_pvalue": float(p_value)}


# ---------------------------------------------------------------------------
# Method B -- MIDAS residual-stationarity test.
# ---------------------------------------------------------------------------

def method_b_midas_residual_stationarity(
    coarse_log_price: pd.Series, fine_log_price: pd.Series, K: int = 5,
    theta1: float = 1.0, theta2: float = 3.0,
) -> dict:
    """Regress coarse_log_price (level) on a causal MIDAS aggregate of
    fine_log_price's trailing K observations, ADF-test the residual.
    A stationary residual means the coarse level and the fine leg's
    recent-history summary share a genuine long-run equilibrium -- the
    actual mixed-frequency cointegration test this module exists for."""
    agg = midas_aggregate(fine_log_price, coarse_log_price.index, K, theta1, theta2)
    joined = pd.DataFrame({"coarse": coarse_log_price, "agg": agg}).dropna()
    if len(joined) < Config.ANALYSIS.OU_WINDOW_MIN_BARS:
        return {"method": "B_midas_residual", "n": len(joined), "adf_pvalue": np.nan, "hedge_ratio": np.nan}

    x = joined["agg"].values
    y = joined["coarse"].values
    x_c = np.column_stack([np.ones_like(x), x])
    beta, *_ = np.linalg.lstsq(x_c, y, rcond=None)
    resid = y - x_c @ beta
    adf_stat, adf_p, *_ = adfuller(resid, autolag="aic")
    return {"method": "B_midas_residual", "n": len(joined), "adf_pvalue": float(adf_p), "hedge_ratio": float(beta[1])}


# ---------------------------------------------------------------------------
# Method C -- coarse-leads-fine predictive-residual test.
# ---------------------------------------------------------------------------

def method_c_coarse_predicts_fine_cumret(
    coarse_log_price: pd.Series, fine_returns: pd.Series, n_perm: int = 500, seed: int = 0,
) -> dict:
    """For each coarse timestamp, compute the fine leg's cumulative return
    over the NEXT coarse period (strictly after that timestamp -- a
    genuine forward target, testing predictive structure, not a
    contemporaneous equilibrium like Methods A/B).

    REDESIGNED (2026-08-04, caught by this module's own synthetic
    verification before touching real data): the original version
    ADF-tested the regression residual for stationarity. That test is
    structurally invalid here -- fwd_cumret (a cumulative-return series
    over a fixed window) is already close to stationary BY CONSTRUCTION,
    regardless of whether any real relationship with coarse_level exists,
    so a residual regressed against it will essentially always "pass" an
    ADF test. Verified live: adf_p=0.0000 for BOTH a true synthetic
    cross-TF relationship AND a synthetic pair with fully independent
    trends -- zero discriminating power, not just low power.

    Fixed by dropping the ADF-on-residual entirely and instead using a
    circular-shift permutation test on the regression's own correlation
    coefficient -- the SAME convention this project already uses for
    lead-lag significance testing (research/lead_lag_permutation_check.py,
    research/eg_permutation_check.py: np.roll one series relative to the
    other, rebuild the null distribution, empirical p-value = fraction of
    |permuted stat| >= |observed stat|). This is a genuine predictive-
    significance test, robust to the autocorrelation that would make a
    naive parametric regression p-value overstate significance."""
    coarse_idx = coarse_log_price.index
    fwd_cumret = []
    for i in range(len(coarse_idx) - 1):
        start, end = coarse_idx[i], coarse_idx[i + 1]
        window = fine_returns[(fine_returns.index > start) & (fine_returns.index <= end)]
        fwd_cumret.append(window.sum() if len(window) else np.nan)
    fwd_cumret.append(np.nan)  # no forward window for the last coarse bar
    fwd_cumret = pd.Series(fwd_cumret, index=coarse_idx)

    joined = pd.DataFrame({"coarse_level": coarse_log_price, "fwd_cumret": fwd_cumret}).dropna()
    if len(joined) < Config.ANALYSIS.OU_WINDOW_MIN_BARS:
        return {"method": "C_coarse_predicts_fine", "n": len(joined), "perm_pvalue": np.nan,
                "observed_corr": np.nan, "beta": np.nan}

    x = joined["coarse_level"].values
    y = joined["fwd_cumret"].values
    x_c = np.column_stack([np.ones_like(x), x])
    beta, *_ = np.linalg.lstsq(x_c, y, rcond=None)

    x_dm, y_dm = x - x.mean(), y - y.mean()
    denom = x_dm.std(ddof=1) * y_dm.std(ddof=1)
    observed_corr = float(np.dot(x_dm, y_dm) / (len(x) * denom)) if denom > 0 else np.nan

    rng = np.random.default_rng(seed)
    n = len(x)
    null_corrs = np.empty(n_perm)
    for k in range(n_perm):
        shift = rng.integers(1, n)  # never 0 -- that would be the real, unshifted alignment
        y_shift = np.roll(y, shift)
        y_shift_dm = y_shift - y_shift.mean()
        d = x_dm.std(ddof=1) * y_shift_dm.std(ddof=1)
        null_corrs[k] = np.dot(x_dm, y_shift_dm) / (n * d) if d > 0 else 0.0

    if not np.isfinite(observed_corr):
        perm_p = np.nan
    else:
        perm_p = float(np.mean(np.abs(null_corrs) >= abs(observed_corr)))

    return {"method": "C_coarse_predicts_fine", "n": n, "perm_pvalue": perm_p,
            "observed_corr": observed_corr, "beta": float(beta[1])}


def run_all_methods(coarse_df: pd.DataFrame, fine_df: pd.DataFrame, K: int = 5) -> list:
    """Run all 3 methods on one (coarse_df, fine_df) pair, return a list
    of result dicts. coarse_df/fine_df must already carry gap-aware
    'close' columns (as returned by DataStore.load)."""
    coarse_log = pd.Series(np.log(_clean_close(coarse_df)), index=coarse_df.index).replace([np.inf, -np.inf], np.nan)
    fine_log = pd.Series(np.log(_clean_close(fine_df)), index=fine_df.index).replace([np.inf, -np.inf], np.nan)
    fine_returns = pd.Series(_gap_aware_returns(fine_df), index=fine_df.index)

    return [
        method_a_downsample_eg(coarse_df, fine_df),
        method_b_midas_residual_stationarity(coarse_log.dropna(), fine_log.dropna(), K=K),
        method_c_coarse_predicts_fine_cumret(coarse_log.dropna(), fine_returns.dropna()),
    ]


# ---------------------------------------------------------------------------
# Full-universe scan.
# ---------------------------------------------------------------------------

def full_universe_scan(coarse_tf: str = "1D", fine_tf: str = "1h", corr_threshold: float = None, K: int = 5) -> list:
    """Stage 1: same-TF correlation pre-filter at coarse_tf (reuses
    analysis.py's DataAligner/UniverseFilter, same pattern as
    inverse_polarity.py's --full-universe mode). Stage 2: for candidates
    clearing the threshold, load BOTH legs at fine_tf too and run all 3
    cross-TF methods. See module docstring for the disclosed limitation
    of this pre-filter approach."""
    from analysis import DataAligner, UniverseFilter

    if corr_threshold is None:
        corr_threshold = Config.UNIVERSE.MIN_PEARSON_CORR

    safe = DataStore._TF_SAFE.get(coarse_tf, coarse_tf.lower())
    pattern = os.path.join(Config.DATA.CACHE_DIR, f"*_{safe}.parquet")
    raw = {}
    for path in glob.glob(pattern):
        fname = os.path.basename(path)
        symbol = fname[: -(len(safe) + len(".parquet") + 1)]
        df = DataStore.load(symbol, coarse_tf)
        if df is not None and not df.empty:
            raw[symbol] = df
    print(f"Loaded {len(raw)} symbols at {coarse_tf}")
    if len(raw) < 10:
        print("Too few symbols -- aborting.")
        return []

    aligned = DataAligner.align_universe({f"{s}_{coarse_tf}": df for s, df in raw.items()}, coarse_tf)
    print(f"{len(aligned)}/{len(raw)} aligned")

    returns, symbols, _idx = UniverseFilter.build_returns_matrix(aligned, min_overlap=252)
    print(f"{len(symbols)} symbols survive min_overlap, computing {len(symbols)}x{len(symbols)} correlation matrix...")
    corr = UniverseFilter.correlation_matrix(returns)

    n = corr.shape[0]
    candidates = []
    for i in range(n):
        for j in range(i + 1, n):
            c = corr[i, j]
            if np.isfinite(c) and abs(c) >= corr_threshold:
                candidates.append((symbols[i], symbols[j], float(c)))
    print(f"{len(candidates)} candidate pairs clear |rho| >= {corr_threshold} at {coarse_tf}")

    rows = []
    for sym_a, sym_b, rho in candidates:
        coarse_a, coarse_b = aligned.get(sym_a), aligned.get(sym_b)
        fine_a, fine_b = DataStore.load(sym_a, fine_tf), DataStore.load(sym_b, fine_tf)
        if coarse_a is None or coarse_b is None or fine_a is None or fine_b is None:
            continue
        # A leads B (coarse=A, fine=B) and B leads A, both directions -- a
        # cross-TF relationship is not necessarily symmetric.
        for coarse_sym, coarse_df, fine_sym, fine_df in (
            (sym_a, coarse_a, sym_b, fine_b), (sym_b, coarse_b, sym_a, fine_a),
        ):
            try:
                results = run_all_methods(coarse_df, fine_df, K=K)
            except Exception as e:
                continue
            for r in results:
                r.update(coarse_symbol=coarse_sym, fine_symbol=fine_sym, coarse_tf=coarse_tf,
                          fine_tf=fine_tf, same_tf_rho=rho)
                rows.append(r)
    return rows


def main():
    p = argparse.ArgumentParser(description="CAMARF cross-timeframe cointegration comparison arm")
    p.add_argument("--full-universe", action="store_true")
    p.add_argument("--coarse-tf", type=str, default="1D")
    p.add_argument("--fine-tf", type=str, default="1h")
    p.add_argument("--corr-threshold", type=float, default=None)
    p.add_argument("--K", type=int, default=5, help="MIDAS aggregation window (fine bars per coarse bar)")
    p.add_argument("--pit-safe", action="store_true",
                    help="Source pairs from research/pit_pair_discovery.py's PIT-safe episodic "
                         "screen instead of ml._discover_confirmed_pairs() (task #5). Ignored "
                         "with --full-universe, which already sources candidates from its own "
                         "same-TF correlation pre-filter.")
    args = p.parse_args()

    if args.full_universe:
        rows = full_universe_scan(args.coarse_tf, args.fine_tf, args.corr_threshold, K=args.K)
        out_df = pd.DataFrame(rows)
        out_dir = os.path.join("output", "research")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "cross_timeframe_cointegration_full_universe.parquet")
        out_df.to_parquet(out_path)
        if len(out_df):
            sig_b = ((out_df["method"] == "B_midas_residual") & (out_df["adf_pvalue"] < 0.05)).sum()
            sig_c = ((out_df["method"] == "C_coarse_predicts_fine") & (out_df["perm_pvalue"] < 0.05)).sum()
            sig_a = ((out_df["method"] == "A_downsample_eg") & (out_df["coint_pvalue"] < 0.05)).sum()
            print(f"Done. {len(out_df)} (direction, method) rows. Method A significant: {sig_a}, "
                  f"Method B significant: {sig_b}, Method C significant: {sig_c}. Saved -> {out_path}")
        else:
            print(f"Done. No candidates produced usable output. Saved -> {out_path}")
        return

    if args.pit_safe:
        from pit_pair_discovery import discover_pit_confirmed_pairs
        pit_pairs = discover_pit_confirmed_pairs()
        pairs = sorted(set((a, b, None) for a, b, _tf in pit_pairs))
        print(f"Using PIT-safe episodic pair discovery: {len(pairs)} unique pairs")
    else:
        pairs = ml._discover_confirmed_pairs()
    coarse_tf, fine_tf = args.coarse_tf, args.fine_tf
    print(f"Running on {'PIT-safe' if args.pit_safe else 'confirmed'} pairs, "
          f"testing each leg as coarse={coarse_tf}/fine={fine_tf}...")
    rows = []
    for symbol_a, symbol_b, _tf in pairs:
        coarse_a, coarse_b = DataStore.load(symbol_a, coarse_tf), DataStore.load(symbol_b, coarse_tf)
        fine_a, fine_b = DataStore.load(symbol_a, fine_tf), DataStore.load(symbol_b, fine_tf)
        if any(d is None for d in (coarse_a, coarse_b, fine_a, fine_b)):
            print(f"  skip {symbol_a}/{symbol_b}: missing {coarse_tf} or {fine_tf} data")
            continue
        for coarse_sym, coarse_df, fine_sym, fine_df in (
            (symbol_a, coarse_a, symbol_b, fine_b), (symbol_b, coarse_b, symbol_a, fine_a),
        ):
            results = run_all_methods(coarse_df, fine_df, K=args.K)
            for r in results:
                r.update(coarse_symbol=coarse_sym, fine_symbol=fine_sym)
                rows.append(r)
                print(f"  {coarse_sym}(coarse)/{fine_sym}(fine) [{r['method']}]: {r}")

    out_df = pd.DataFrame(rows)
    out_dir = os.path.join("output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "cross_timeframe_cointegration.parquet")
    out_df.to_parquet(out_path)
    print(f"Done. Saved -> {out_path}")


if __name__ == "__main__":
    main()
