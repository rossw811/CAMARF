"""
research/cross_tf_lead_lag_scan.py -- combined lead-lag + cross-timeframe
pair-discovery methodology (built 2026-08-11, Ross's direct request: "there
should already be methodology built for combined lead lag and cross tf, if
not let's build it. the test should be run on the entire universe").

NO EXISTING SCRIPT TESTS THIS COMBINATION, confirmed before building this:
  - research/lead_lag_scan.py / wrds_universal_lead_lag_scan.py sweep a lag
    k over TWO SAME-TIMEFREQUENCY series (contemporaneous calendar, just
    offset in bars). Neither touches cross-timeframe data at all.
  - research/cross_timeframe_cointegration.py tests THREE ways two
    DIFFERENT-timeframe series can share a genuine equilibrium (downsample-
    to-shared-frequency EG, MIDAS residual-stationarity, coarse-leads-fine
    predictive-residual) -- but Method A/B are contemporaneous (no lag
    sweep) and Method C is fixed at "exactly one coarse period ahead," not
    a swept lag search. None of the three asks "at what LAG, if any, is
    the cross-timeframe relationship strongest."

THIS SCRIPT'S QUESTION: once two different-timeframe series are put on a
shared clock (the SAME causal, no-lookahead downsampling convention
cross_timeframe_cointegration.py's Method A already uses and has verified),
does the resulting relationship exhibit genuine LEAD-LAG structure -- i.e.
is lag k*!=0 measurably stronger than the contemporaneous (lag-0) relationship,
confirmed by an independent EG test at k* vs at 0 -- reusing lead_lag_scan.py's
own already-verified lagged_corr_scan/_eg_pvalue building blocks UNCHANGED,
not reimplemented.

Design, full-universe, three stages mirroring this project's established
cheap-filter -> expensive-confirm structure (cross_timeframe_cointegration.py's
own full_universe_scan, wrds_universal_lead_lag_scan.py's Stage 0/1/2):
  1. Same-TF correlation prefilter at coarse_tf (UniverseFilter, same as
     cross_timeframe_cointegration.py's full_universe_scan) -- keeps the
     combinatorial space tractable; a genuinely disclosed limitation, same
     one that module's own docstring states, not glossed over here either.
  2. For each candidate pair, BOTH directions (coarse=A/fine=B and
     coarse=B/fine=A -- a cross-TF lead-lag relationship is not
     necessarily symmetric): downsample the fine leg's close to the coarse
     leg's own index (causal last-value-at-or-before -- IDENTICAL
     convention to method_a_downsample_eg, not reimplemented differently),
     build log returns on the now-shared-frequency series, run
     lead_lag_scan.lagged_corr_scan + best_lag over the lag range.
  3. For every candidate where k* != 0 and the |corr| lift over lag 0
     clears --min-lift: EG-confirm (lead_lag_scan._eg_pvalue, same call
     shape) at k* AND at lag 0 on the downsampled log-price series shifted
     accordingly. A pair is "cross-TF lead-lag confirmed" only if EG at k*
     is materially better (lower p-value) than at lag 0 AND clears joint
     BH-FDR (analysis._benjamini_hochberg, same helper the rest of this
     project's episodic/static screens use) across the whole tested family.

Synthetic verification FIRST: debug/_verify_cross_tf_lead_lag_scan.py --
run that before trusting this script's real-data output.

Usage:
    python research/cross_tf_lead_lag_scan.py --full-universe --coarse-tf 1D --fine-tf 1h
    python research/cross_tf_lead_lag_scan.py --coarse-tf 1D --fine-tf 1h   # PIT-safe confirmed pairs only
"""
import argparse
import glob
import logging
import os
import sys

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from config import Config
from data import DataStore, _clean_close
from analysis import _benjamini_hochberg
from lead_lag_scan import lagged_corr_scan, best_lag, _MIN_EG_N

log = logging.getLogger("cross_tf_lead_lag_scan")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_cross_tf_lead_lag_scan.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def downsample_fine_to_coarse(coarse_index: pd.DatetimeIndex, fine_df: pd.DataFrame) -> pd.Series:
    """Causal, no-lookahead downsample: at each coarse timestamp, the most
    recent fine-leg close AT OR BEFORE that timestamp. IDENTICAL convention
    to cross_timeframe_cointegration.py's method_a_downsample_eg -- kept as
    a separate, small function here (not imported) so this module has no
    hard dependency on that one's internal helper naming, but the logic
    itself must never drift from that already-verified convention."""
    fine_close = pd.Series(_clean_close(fine_df), index=fine_df.index).dropna()
    values = []
    for ts in coarse_index:
        window = fine_close[fine_close.index <= ts]
        values.append(window.iloc[-1] if len(window) else np.nan)
    return pd.Series(values, index=coarse_index)


def scan_pair_cross_tf_lead_lag(
    coarse_df: pd.DataFrame, fine_df: pd.DataFrame, max_lag: int, min_lift: float,
    eg_max_lag: int,
) -> dict:
    """Core per-(coarse,fine)-direction logic, pure enough for synthetic
    testing: downsample fine->coarse frequency, lag-sweep on returns,
    EG-confirm at k* vs lag 0 if the lift clears threshold. Returns a dict
    with ok=False and a reason if any stage can't proceed."""
    downsampled_close = downsample_fine_to_coarse(coarse_df.index, fine_df)
    coarse_close = pd.Series(_clean_close(coarse_df), index=coarse_df.index)

    mask = np.isfinite(coarse_close.values) & np.isfinite(downsampled_close.values) & \
        (coarse_close.values > 0) & (downsampled_close.values.astype(float) > 0)
    if mask.sum() < _MIN_EG_N:
        return {"ok": False, "reason": "insufficient_overlap", "n": int(mask.sum())}

    log_coarse = pd.Series(np.log(coarse_close.values), index=coarse_df.index)[mask]
    log_fine_ds = pd.Series(np.log(downsampled_close.values.astype(float)), index=coarse_df.index)[mask]
    ret_coarse = log_coarse.diff()
    ret_fine_ds = log_fine_ds.diff()

    scan = lagged_corr_scan(ret_coarse, ret_fine_ds, max_lag)
    k_star, c_star, n_star = best_lag(scan)
    if k_star is None:
        return {"ok": False, "reason": "no_valid_lag", "n": int(mask.sum())}

    c0, n0 = scan.get(0, (None, 0))
    lift = (abs(c_star) - abs(c0)) if (c0 is not None and c_star is not None) else None

    result = {
        "ok": True, "n": int(mask.sum()), "best_lag": k_star, "best_corr": c_star,
        "lag0_corr": c0, "lift": lift,
    }
    if k_star == 0 or lift is None or lift < min_lift:
        result["eg_tested"] = False
        return result

    # EG-confirm at k* vs lag 0, on the shared-frequency LOG PRICE series
    # (not returns) realigned at each lag -- same call shape as
    # lead_lag_scan.py's own confirm stage.
    shifted_fine_star = log_fine_ds.shift(-k_star)
    joined_star = pd.concat([log_coarse, shifted_fine_star], axis=1, join="inner").dropna()
    joined_0 = pd.concat([log_coarse, log_fine_ds], axis=1, join="inner").dropna()

    result["eg_tested"] = True
    result["eg_pvalue_at_kstar"] = None
    result["eg_pvalue_at_lag0"] = None
    if len(joined_star) >= _MIN_EG_N:
        try:
            _, p_star, _ = coint(joined_star.iloc[:, 0].values, joined_star.iloc[:, 1].values,
                                  trend="c", maxlag=eg_max_lag, autolag="aic")
            result["eg_pvalue_at_kstar"] = float(p_star)
        except Exception as e:
            log.debug("EG at k*=%d failed: %s", k_star, e)
    if len(joined_0) >= _MIN_EG_N:
        try:
            _, p0, _ = coint(joined_0.iloc[:, 0].values, joined_0.iloc[:, 1].values,
                              trend="c", maxlag=eg_max_lag, autolag="aic")
            result["eg_pvalue_at_lag0"] = float(p0)
        except Exception as e:
            log.debug("EG at lag0 failed: %s", e)

    p_star, p0 = result["eg_pvalue_at_kstar"], result["eg_pvalue_at_lag0"]
    result["lagged_is_better"] = (
        p_star is not None and p0 is not None and p_star < p0
    )
    return result


def full_universe_candidates(coarse_tf: str, corr_threshold: float = None) -> list:
    """Same-TF correlation prefilter at coarse_tf, IDENTICAL pattern to
    cross_timeframe_cointegration.py's full_universe_scan Stage 1 -- reused
    by construction (same imports, same threshold default), not
    reimplemented independently."""
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
    log.info(f"Loaded {len(raw)} symbols at {coarse_tf}")
    if len(raw) < 10:
        return []

    aligned = DataAligner.align_universe({f"{s}_{coarse_tf}": df for s, df in raw.items()}, coarse_tf)
    returns, symbols, _idx = UniverseFilter.build_returns_matrix(aligned, min_overlap=252)
    log.info(f"{len(symbols)} symbols survive min_overlap, computing correlation matrix...")
    corr = UniverseFilter.correlation_matrix(returns)

    n = corr.shape[0]
    candidates = []
    for i in range(n):
        for j in range(i + 1, n):
            c = corr[i, j]
            if np.isfinite(c) and abs(c) >= corr_threshold:
                candidates.append((symbols[i], symbols[j]))
    log.info(f"{len(candidates)} candidate pairs clear |rho| >= {corr_threshold} at {coarse_tf}")
    return candidates


def main():
    p = argparse.ArgumentParser(description="Combined lead-lag + cross-timeframe pair discovery")
    p.add_argument("--full-universe", action="store_true",
                    help="Discover candidates via same-TF correlation prefilter across the whole "
                         "cached universe, not just PIT-confirmed pairs.")
    p.add_argument("--coarse-tf", default="1D")
    p.add_argument("--fine-tf", default="1h")
    p.add_argument("--max-lag", type=int, default=Config.RESEARCH.LEAD_LAG_MAX_LAG)
    p.add_argument("--min-lift", type=float, default=0.05)
    p.add_argument("--corr-threshold", type=float, default=None)
    args = p.parse_args()
    _setup_logging()

    log.info(f"=== cross_tf_lead_lag_scan.py: coarse={args.coarse_tf} fine={args.fine_tf} "
             f"max_lag={args.max_lag} min_lift={args.min_lift} full_universe={args.full_universe} ===")

    if args.full_universe:
        candidate_symbol_pairs = full_universe_candidates(args.coarse_tf, args.corr_threshold)
    else:
        from pit_pair_discovery import discover_pit_confirmed_pairs
        pit_pairs = discover_pit_confirmed_pairs()
        candidate_symbol_pairs = [(a, b) for a, b, _tf in pit_pairs]
        log.info(f"{len(candidate_symbol_pairs)} PIT-confirmed pairs (confirmed-pairs-only mode)")

    if not candidate_symbol_pairs:
        log.warning("No candidate pairs -- nothing to scan.")
        return pd.DataFrame()

    rows = []
    for sym_a, sym_b in candidate_symbol_pairs:
        coarse_a = DataStore.load(sym_a, args.coarse_tf)
        coarse_b = DataStore.load(sym_b, args.coarse_tf)
        fine_a = DataStore.load(sym_a, args.fine_tf)
        fine_b = DataStore.load(sym_b, args.fine_tf)
        if coarse_a is None or coarse_b is None or fine_a is None or fine_b is None:
            continue
        for coarse_sym, coarse_df, fine_sym, fine_df in (
            (sym_a, coarse_a, sym_b, fine_b), (sym_b, coarse_b, sym_a, fine_a),
        ):
            try:
                r = scan_pair_cross_tf_lead_lag(
                    coarse_df, fine_df, args.max_lag, args.min_lift, Config.ANALYSIS.EG_MAX_LAG
                )
            except Exception as e:
                log.debug("scan failed for coarse=%s fine=%s: %s", coarse_sym, fine_sym, e)
                continue
            r.update(coarse_symbol=coarse_sym, fine_symbol=fine_sym,
                      coarse_tf=args.coarse_tf, fine_tf=args.fine_tf)
            rows.append(r)

    df = pd.DataFrame(rows)
    os.makedirs(_OUT_DIR, exist_ok=True)
    out_path = os.path.join(_OUT_DIR, "cross_tf_lead_lag_scan.parquet")
    df.to_parquet(out_path, index=False)
    log.info(f"Scanned {len(df)} (coarse,fine)-direction pairs -> {out_path}")

    eg_tested = df[df.get("eg_tested", False) == True].copy() if not df.empty else df
    if eg_tested.empty or "eg_pvalue_at_kstar" not in eg_tested.columns:
        log.info("No pairs reached EG-confirm stage (no lift cleared --min-lift with k*!=0).")
        return df

    eg_tested = eg_tested[eg_tested["eg_pvalue_at_kstar"].notna()]
    if eg_tested.empty:
        log.info("No EG-testable pairs after dropping NaN p-values.")
        return df

    rejected, adjusted = _benjamini_hochberg(eg_tested["eg_pvalue_at_kstar"].to_numpy(), Config.STATS.FDR_ALPHA)
    eg_tested["fdr_adjusted_pvalue"] = adjusted
    eg_tested["fdr_confirmed"] = rejected & eg_tested["lagged_is_better"]
    n_confirmed = int(eg_tested["fdr_confirmed"].sum())
    log.info(f"=== {n_confirmed}/{len(eg_tested)} pairs CONFIRMED: cross-TF relationship is "
             f"genuinely lagged (k*!=0, EG at k* beats EG at lag 0, joint BH-FDR alpha="
             f"{Config.STATS.FDR_ALPHA}) ===")
    confirmed = eg_tested[eg_tested["fdr_confirmed"]].sort_values("fdr_adjusted_pvalue")
    for _, r in confirmed.head(30).iterrows():
        log.info(f"  CONFIRMED: {r['coarse_symbol']}@{r['coarse_tf']} / {r['fine_symbol']}@{r['fine_tf']}: "
                 f"lag={r['best_lag']} lift={r['lift']:.3f} eg_p(k*)={r['eg_pvalue_at_kstar']:.3e} "
                 f"eg_p(0)={r['eg_pvalue_at_lag0']:.3e} adj={r['fdr_adjusted_pvalue']:.3e}")
    eg_tested.to_parquet(os.path.join(_OUT_DIR, "cross_tf_lead_lag_scan_confirmed.parquet"), index=False)
    return df


if __name__ == "__main__":
    main()
