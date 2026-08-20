"""
research/confirmatory_cointegration_check.py -- Ross's direct request (2026-07-20),
following the 4-method FDR comparison (research/fdr_method_comparison.py) which
showed NONE of the 8 previously-flagged non-DD pairs survive ANY of 4 multiple-
testing corrections (including chain-independent Bonferroni) at CAMARF's full-
universe scale (m~36,753). That result settled "is it a rank-chain artifact" (no)
but left open a different, legitimate question: are these 8 pairs' raw EG signals
(individually significant at p<0.001) genuine economic cointegration that a
DIFFERENT test family would also detect, or are they EG-specific artifacts?

This does NOT bypass or re-litigate the FDR result. Corroboration from an
independent test family is supplementary evidence about whether the underlying
signal is real, matching CAMARF's own §4.1 "confirmatory tier" design intent --
it is explicitly NOT a route to promoting these pairs to "confirmed" status in
production, which remains governed by the primary EG+BH-FDR screen.

Two independent test families, both already available in statsmodels (no
hand-rolled test statistics needing separate verification):

1. Johansen's test (coint_johansen) -- VECM-rank-based, estimates the number
   of cointegrating relationships via eigenvalues of a canonical correlation
   between levels and differences. Fundamentally different estimation
   approach from EG's two-step OLS-residual-then-ADF (no asymmetric choice
   of dependent variable, no plug-in residual step).
2. KPSS (kpss) -- run on the EG regression's OWN OLS residuals. KPSS's null
   is STATIONARITY (opposite of ADF's null of a unit root) -- pairing
   ADF-rejects-unit-root with KPSS-fails-to-reject-stationarity is the
   textbook "confirmatory combination" precisely because the two tests can
   fail in different directions, so agreement between them is much stronger
   evidence than either alone.

Known bounded-range caveat (documented, not glossed over): statsmodels' KPSS
p-value is table-interpolated and clipped to [0.01, 0.10] -- same class of
caveat as MacKinnon's EG response-surface p-values noted elsewhere in this
project. A KPSS p-value reported as exactly 0.01 or 0.10 means "at or beyond
the edge of the reference table," not a precise tail probability.

Target pairs:
  - The 8 previously-flagged non-DD pairs (LNT/VTR, LNT/WELL, CMS/DUK, EG/WRB,
    HAL/NOV, MET/TMHC, PFG/STLD, UMBF/FHB) -- the actual subject of the check.
  - The 3 pairs that DID survive the 4-method FDR comparison (SPY/VOO, FELE/MAS,
    PNC/ZION) -- included as a positive-control sanity check: if Johansen/KPSS
    don't corroborate pairs that already cleared full FDR correction, that's a
    sign the confirmatory harness itself is broken, not that those pairs are bad.
  - 4 real negative-control pairs pulled directly from the same production run's
    raw output (MU/ORCL, CAT/HLI, AMG/BX, ATI/PNR -- each raw EG p-value exactly
    1.0, i.e. decisively non-cointegrated) -- if Johansen/KPSS corroborate THESE,
    the harness is broken.

Output: output/research/confirmatory_cointegration_check.parquet,
latest_run_confirmatory_cointegration_check.log
"""
import logging
import os
import sys

import numpy as np
import pandas as pd
from statsmodels.tsa.vector_ar.vecm import coint_johansen
from statsmodels.tsa.stattools import kpss

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from data import DataAligner
from analysis import CointScanner

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_DIR = os.path.join(_ROOT, "output", "cache")
_OUT_DIR = os.path.join(_ROOT, "output", "research")
TF_LABEL = "1h"

TARGET_PAIRS = [
    # The 8 pairs under actual investigation
    ("LNT", "VTR", "target"), ("LNT", "WELL", "target"), ("CMS", "DUK", "target"),
    ("EG", "WRB", "target"), ("HAL", "NOV", "target"), ("MET", "TMHC", "target"),
    ("PFG", "STLD", "target"), ("UMBF", "FHB", "target"),
    # Positive controls -- already cleared full FDR correction this session
    ("SPY", "VOO", "positive_control"), ("FELE", "MAS", "positive_control"),
    ("PNC", "ZION", "positive_control"),
    # Negative controls -- raw EG p-value exactly 1.0 in the same production run
    ("MU", "ORCL", "negative_control"), ("CAT", "HLI", "negative_control"),
    ("AMG", "BX", "negative_control"), ("ATI", "PNR", "negative_control"),
]

log = logging.getLogger("confirmatory_cointegration_check")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_confirmatory_cointegration_check.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def run_confirmatory_pair(log_p_a: np.ndarray, log_p_b: np.ndarray, max_lag: int = 10) -> dict:
    """
    Pure function -- runs Johansen + KPSS on one pair's aligned log-price
    arrays. Kept data-loading-free so debug/_verify_confirmatory_cointegration_check.py
    can call it directly on synthetic arrays with known expected outcomes.
    """
    mask = np.isfinite(log_p_a) & np.isfinite(log_p_b)
    a = log_p_a[mask]
    b = log_p_b[mask]
    n = a.size
    if n < 60:
        return {"ok": False, "error": "insufficient_overlap", "n_overlap": n}

    out = {"ok": True, "n_overlap": n}

    # --- Johansen ---
    try:
        endog = np.column_stack([a, b])
        jres = coint_johansen(endog, det_order=0, k_ar_diff=1)
        trace_stat_r0 = float(jres.lr1[0])
        trace_crit_r0 = jres.cvt[0]  # [90%, 95%, 99%]
        out["johansen_trace_stat_r0"] = trace_stat_r0
        out["johansen_trace_crit90_r0"] = float(trace_crit_r0[0])
        out["johansen_trace_crit95_r0"] = float(trace_crit_r0[1])
        out["johansen_trace_crit99_r0"] = float(trace_crit_r0[2])
        out["johansen_rejects_no_coint_95"] = bool(trace_stat_r0 > trace_crit_r0[1])
    except Exception as e:
        out["johansen_rejects_no_coint_95"] = None
        out["johansen_error"] = f"{type(e).__name__}: {e}"

    # --- OLS residual (same convention as _eg_worker) + KPSS ---
    try:
        b_centered = b - b.mean()
        a_centered = a - a.mean()
        var_b = np.dot(b_centered, b_centered)
        hr = np.dot(a_centered, b_centered) / var_b if var_b > 0 else np.nan
        resid = a - hr * b
        kpss_stat, kpss_pvalue, kpss_lags, kpss_crit = kpss(resid, regression="c", nlags="auto")
        out["kpss_stat"] = float(kpss_stat)
        out["kpss_pvalue"] = float(kpss_pvalue)
        out["kpss_pvalue_bounded"] = bool(kpss_pvalue in (0.01, 0.1))
        out["kpss_fails_to_reject_stationarity_95"] = bool(kpss_pvalue > 0.05)
    except Exception as e:
        out["kpss_fails_to_reject_stationarity_95"] = None
        out["kpss_error"] = f"{type(e).__name__}: {e}"

    return out


def main():
    _setup_logging()
    log.info("=== confirmatory_cointegration_check.py: Johansen + KPSS on %d target/control pairs ===",
              len(TARGET_PAIRS))
    log.info("Supplementary evidence only -- does NOT bypass or re-derive the FDR-corrected "
              "confirmed-pair set. See module docstring.")

    needed_symbols = sorted({s for a, b, _ in TARGET_PAIRS for s in (a, b)})
    tf_data_raw = {}
    for sym in needed_symbols:
        path = os.path.join(_CACHE_DIR, f"{sym}_1hr.parquet")
        if os.path.exists(path):
            df = pd.read_parquet(path)
            if df is not None and not df.empty and "close" in df.columns:
                tf_data_raw[sym] = df
    missing = set(needed_symbols) - set(tf_data_raw)
    if missing:
        log.warning("Missing cache for: %s", sorted(missing))

    aligned = DataAligner.align_universe(
        {f"{sym}_{TF_LABEL}": df for sym, df in tf_data_raw.items()}, TF_LABEL
    )
    log.info("Aligned %d/%d needed symbols", len(aligned), len(needed_symbols))

    # BUG-D111 fix (found live, 2026-08-11): DataAligner.align_universe does NOT
    # guarantee every symbol shares one common index -- each symbol's own history
    # depth (e.g. TMHC ending 2026-07-22 vs MET/LNT/VTR's 2026-07-31) produces a
    # DIFFERENT-length array. _build_log_price_map returns bare np.ndarray with no
    # index, so passing two different symbols' arrays straight into
    # run_confirmatory_pair as if positionally aligned crashed with a numpy
    # broadcast ValueError the moment two target-pair symbols had unequal depth
    # (MET/TMHC: 26478 vs 26262). Fixed the same way episodic_pairs_adapter.py's
    # _load_aligned/ridge_hedge_ratio_comparison.py's evaluate_pair already do:
    # keep the index, inner-join per pair before treating the two series as
    # parallel arrays.
    log_price_series = {}
    for sym in aligned:
        close = CointScanner._build_log_price_map({sym: aligned[sym]}, [sym]).get(sym)
        if close is not None:
            log_price_series[sym] = pd.Series(close, index=aligned[sym].index)

    rows = []
    for sym_a, sym_b, role in TARGET_PAIRS:
        s_a = log_price_series.get(sym_a)
        s_b = log_price_series.get(sym_b)
        if s_a is None or s_b is None:
            log.warning("  %s/%s (%s): no aligned data, skipping", sym_a, sym_b, role)
            rows.append({"symbol_a": sym_a, "symbol_b": sym_b, "role": role, "ok": False,
                         "error": "no_aligned_data"})
            continue
        common_idx = s_a.index.intersection(s_b.index)
        lp_a = s_a.loc[common_idx].to_numpy()
        lp_b = s_b.loc[common_idx].to_numpy()
        res = run_confirmatory_pair(lp_a, lp_b, max_lag=Config.ANALYSIS.EG_MAX_LAG)
        res["symbol_a"] = sym_a
        res["symbol_b"] = sym_b
        res["role"] = role
        rows.append(res)
        if res.get("ok"):
            j = res.get("johansen_rejects_no_coint_95")
            k = res.get("kpss_fails_to_reject_stationarity_95")
            both = (j is True) and (k is True)
            log.info(
                "  %-6s/%-6s (%-17s) n=%4d  Johansen_rejects_no_coint@95=%-5s  "
                "KPSS_fails_to_reject_stationarity@95=%-5s  BOTH_CORROBORATE=%s",
                sym_a, sym_b, role, res["n_overlap"], j, k, both,
            )
        else:
            log.warning("  %-6s/%-6s (%-17s): %s", sym_a, sym_b, role, res.get("error"))

    df = pd.DataFrame(rows)
    os.makedirs(_OUT_DIR, exist_ok=True)
    df.to_parquet(os.path.join(_OUT_DIR, "confirmatory_cointegration_check.parquet"), index=False)
    log.info("Saved -> output/research/confirmatory_cointegration_check.parquet")

    log.info("")
    log.info("=== Summary by role ===")
    for role in ("target", "positive_control", "negative_control"):
        sub = df[df["role"] == role]
        ok_sub = sub[sub.get("ok", False) == True] if "ok" in sub.columns else sub.iloc[0:0]
        n_both = int(((ok_sub.get("johansen_rejects_no_coint_95") == True) &
                       (ok_sub.get("kpss_fails_to_reject_stationarity_95") == True)).sum()) if len(ok_sub) else 0
        log.info("  %-18s: %d/%d pairs corroborated by BOTH Johansen and KPSS",
                  role, n_both, len(sub))


if __name__ == "__main__":
    main()
