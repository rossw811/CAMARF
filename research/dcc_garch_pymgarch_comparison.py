"""
research/dcc_garch_pymgarch_comparison.py -- comparison/diagnostic script,
NOT part of the production pipeline (2026-09-01).

SCOPE (per Ross's "always scope before the build" standing instruction):
`stats.py` Section 4 hand-rolls Engle (2002) two-step DCC-GARCH
(`_fit_garch_residuals` + `_dcc_update`) on top of `arch`'s univariate
`arch_model` GARCH(1,1), because `arch.multivariate`'s own DCC class was
removed in `arch` 7+ (see stats.py lines 594-596). Ross asked directly
whether a newer package covers this gap. `pymgarch` (PyPI 0.1.1, installed
2026-09-01) is real, built on the SAME `arch>=7.0` univariate marginals
CAMARF already fits, with validated two-stage Engle-Sheppard standard
errors against R's rmgarch/tsmarch reference implementation.

Question this answers: does CAMARF's hand-rolled DCC agree with pymgarch's
DCC when fit on the SAME data? Two checks, in order of how much they can be
trusted:
  1. PRIMARY, decisive: fit both on a SYNTHETIC multi-series panel with a
     KNOWN dynamic-correlation ground truth (baseline low correlation,
     jumping to high correlation during a "crisis" sub-window, then back
     down) -- confirms each method's fitted rho_t actually TRACKS the true
     regime, not just that they happen to agree with each other (two
     methods could agree while both being wrong).
  2. SECONDARY, best-effort: fit both on CAMARF's own real
     output/backtest/trades_layer1.parquet trade log (constructing the
     "pair" column run_dcc_garch's _build_daily_pnl expects from
     symbol_a/symbol_b) -- reported honestly as INSUFFICIENT if there
     isn't enough real data (matching run_dcc_garch's own existing
     "skip, don't fabricate" convention), not forced to produce a number.

Also reports wall-clock time for each method on the same input, since
efficiency was explicitly part of what Ross asked to compare.

Read-only against real data; only writes to output/research/.

Usage:
    python research/dcc_garch_pymgarch_comparison.py
"""
import logging
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stats import _fit_garch_residuals, _dcc_update, _build_daily_pnl, _MIN_GARCH_OBS

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")
_REAL_TRADES_PATH = os.path.join(_ROOT, "output", "backtest", "trades_layer1.parquet")

log = logging.getLogger("dcc_garch_pymgarch_comparison")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_dcc_garch_pymgarch_comparison.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def make_synthetic_dcc_panel(n_series: int = 4, n_days: int = 500, seed: int = 0,
                              crisis_start: int = 250, crisis_end: int = 350,
                              baseline_rho: float = 0.15, crisis_rho: float = 0.75):
    """Pure function -- returns (returns_df, true_rho_schedule) where
    returns_df is a (n_days, n_series) DataFrame with a KNOWN target
    pairwise correlation that steps from baseline_rho to crisis_rho during
    [crisis_start, crisis_end) and back, and true_rho_schedule is the
    per-day target correlation array (same for every pair, for simplicity
    -- a single shared-factor structure, not independently varying
    pairwise correlations). Built via a shared-factor model: each series
    is w*common_factor + sqrt(1-w^2)*idiosyncratic, where w is chosen per
    day so the implied pairwise correlation equals the day's target rho
    (corr(a,b) = w^2 for two series sharing the same single factor
    loading -- so w = sqrt(rho)). Kept free of any GARCH/DCC fitting so
    debug/_verify_dcc_garch_pymgarch_comparison.py can check the panel's
    OWN realized correlation matches the target before either DCC method
    ever sees it."""
    rng = np.random.default_rng(seed)
    true_rho = np.full(n_days, baseline_rho)
    true_rho[crisis_start:crisis_end] = crisis_rho
    common = rng.normal(0, 1, n_days)
    idio = rng.normal(0, 1, size=(n_days, n_series))
    w = np.sqrt(true_rho)
    returns = w[:, None] * common[:, None] + np.sqrt(1 - w[:, None] ** 2) * idio
    returns_df = pd.DataFrame(returns, columns=[f"synthetic_pair_{i}" for i in range(n_series)],
                               index=pd.date_range("2024-01-01", periods=n_days, freq="D"))
    return returns_df, true_rho


def fit_camarf_dcc(returns_df: pd.DataFrame):
    """Wraps stats.py's own _fit_garch_residuals + _dcc_update, UNCHANGED,
    on an arbitrary (T, N) returns panel (not just a trades DataFrame) --
    returns (T, N, N) conditional correlations, or None if too few series
    had a successful GARCH fit."""
    std_resid_cols = {}
    for col in returns_df.columns:
        resid = _fit_garch_residuals(returns_df[col].to_numpy())
        if resid is not None:
            std_resid_cols[col] = resid
    if len(std_resid_cols) < 2:
        return None, list(std_resid_cols.keys())
    names = list(std_resid_cols.keys())
    min_len = min(len(v) for v in std_resid_cols.values())
    mat = np.column_stack([std_resid_cols[n][-min_len:] for n in names])
    return _dcc_update(mat), names


def fit_pymgarch_dcc(returns_df: pd.DataFrame):
    """Wraps pymgarch.DCC().fit() -- returns (T, N, N) conditional
    correlations (pymgarch's own convention, verified via
    result.conditional_correlations) or None if fitting fails/doesn't
    converge."""
    import pymgarch
    try:
        result = pymgarch.DCC().fit(returns_df, compute_se=False)
        return result.conditional_correlations, list(returns_df.columns)
    except Exception as e:
        log.warning("pymgarch DCC fit failed: %s", e)
        return None, []


def rmse_vs_target(fitted_corr: np.ndarray, target_rho: np.ndarray) -> float:
    """Pure function -- average pairwise off-diagonal correlation at each
    day vs. the known target_rho for that day, RMSE across days. Used to
    score each method against synthetic ground truth."""
    T, n, _ = fitted_corr.shape
    iu = np.triu_indices(n, k=1)
    avg_pairwise = fitted_corr[:, iu[0], iu[1]].mean(axis=1)
    return float(np.sqrt(np.mean((avg_pairwise - target_rho) ** 2)))


def main():
    _setup_logging()
    log.info("=== dcc_garch_pymgarch_comparison.py: CAMARF's hand-rolled DCC vs. pymgarch's DCC ===")

    log.info("")
    log.info("--- PRIMARY: synthetic panel with known correlation regime (baseline=0.15, crisis=0.75) ---")
    returns_df, true_rho = make_synthetic_dcc_panel()

    t0 = time.time()
    camarf_corr, camarf_names = fit_camarf_dcc(returns_df)
    camarf_elapsed = time.time() - t0
    t0 = time.time()
    pymgarch_corr, pymgarch_names = fit_pymgarch_dcc(returns_df)
    pymgarch_elapsed = time.time() - t0

    summary_rows = []
    if camarf_corr is not None:
        rmse_camarf = rmse_vs_target(camarf_corr, true_rho)
        log.info("  CAMARF hand-rolled DCC: fit in %.3fs, RMSE vs. known-true rho schedule = %.4f",
                  camarf_elapsed, rmse_camarf)
        summary_rows.append({"method": "camarf_handrolled", "dataset": "synthetic",
                              "fit_seconds": camarf_elapsed, "rmse_vs_truth": rmse_camarf})
    else:
        log.warning("  CAMARF hand-rolled DCC: fit failed on the synthetic panel")

    if pymgarch_corr is not None:
        rmse_pymgarch = rmse_vs_target(pymgarch_corr, true_rho)
        log.info("  pymgarch DCC:            fit in %.3fs, RMSE vs. known-true rho schedule = %.4f",
                  pymgarch_elapsed, rmse_pymgarch)
        summary_rows.append({"method": "pymgarch", "dataset": "synthetic",
                              "fit_seconds": pymgarch_elapsed, "rmse_vs_truth": rmse_pymgarch})
    else:
        log.warning("  pymgarch DCC: fit failed on the synthetic panel")

    if camarf_corr is not None and pymgarch_corr is not None:
        min_T = min(camarf_corr.shape[0], pymgarch_corr.shape[0])
        # direct method-vs-method comparison (not vs. truth)
        iu = np.triu_indices(camarf_corr.shape[1], k=1)
        camarf_avg = camarf_corr[-min_T:, iu[0], iu[1]].mean(axis=1)
        pymgarch_avg = pymgarch_corr[-min_T:, iu[0], iu[1]].mean(axis=1)
        method_agreement_rmse = float(np.sqrt(np.mean((camarf_avg - pymgarch_avg) ** 2)))
        log.info("  Method-vs-method RMSE (CAMARF fitted rho vs. pymgarch fitted rho, same data): %.4f",
                  method_agreement_rmse)
        summary_rows.append({"method": "agreement", "dataset": "synthetic",
                              "fit_seconds": None, "rmse_vs_truth": None,
                              "method_vs_method_rmse": method_agreement_rmse})

    log.info("")
    log.info("--- SECONDARY, best-effort: real output/backtest/trades_layer1.parquet ---")
    if not os.path.exists(_REAL_TRADES_PATH):
        log.info("  No real trades file found at %s -- skipping real-data check.", _REAL_TRADES_PATH)
    else:
        trades = pd.read_parquet(_REAL_TRADES_PATH)
        trades = trades.copy()
        trades["pair"] = trades["symbol_a"] + "/" + trades["symbol_b"]
        daily = _build_daily_pnl(trades)
        log.info("  Real trades: %d rows -> %d days x %d pairs of daily P&L", len(trades), *daily.shape)
        if daily.shape[0] < _MIN_GARCH_OBS or daily.shape[1] < 2:
            log.info("  INSUFFICIENT real data for a DCC fit (need >=%d days, >=2 pairs) -- "
                      "honestly skipped, not forced. This is expected at 90-trade scale.", _MIN_GARCH_OBS)
        else:
            camarf_real, _ = fit_camarf_dcc(daily)
            pymgarch_real, _ = fit_pymgarch_dcc(daily)
            log.info("  CAMARF fit: %s, pymgarch fit: %s",
                      "succeeded" if camarf_real is not None else "failed/insufficient",
                      "succeeded" if pymgarch_real is not None else "failed/insufficient")

    os.makedirs(_OUT_DIR, exist_ok=True)
    pd.DataFrame(summary_rows).to_parquet(
        os.path.join(_OUT_DIR, "dcc_garch_pymgarch_comparison_summary.parquet"), index=False
    )
    log.info("")
    log.info("Saved -> output/research/dcc_garch_pymgarch_comparison_summary.parquet")


if __name__ == "__main__":
    main()
