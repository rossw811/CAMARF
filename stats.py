# =============================================================================
# CAMARF — Cross-Asset Co-Movement Arbitrage Research Framework
# stats.py — Statistical validation layer
# github.com/rossw811/CAMARF
#
# Runs AFTER analysis.py (reads output/results/) and backtest.py (reads
# output/backtest/).  Produces output/stats/ — all results fully
# reproducible from saved parquets without re-running the pipeline.
#
# Sections (run in order):
#   1. Confirmatory cointegration   — KPSS + Phillips-Ouliaris → Gold/Silver/Bronze tiers
#   2. Robust hedge ratios          — Huber + MM alongside OLS/TLS/Kalman
#   3. EVT / GPD tail risk          — shape parameter ξ per pair
#   4. DCC-GARCH dynamic correlation— Engle (2002) two-step on pair P&L
#   5. Monte Carlo simulation       — Phases 1–4 (dist fit, regime, slippage, trade quality)
#   6. Permutation test             — portfolio-level White Reality Check
#
# All tests applied to CONFIRMED pairs only (analysis.py coint_pvalue_adjusted
# already passed BH-FDR correction).  The stats.py tier column `stats_tier`
# is the paper's primary confidence classification (§5.2 / §9.1).
# =============================================================================

from __future__ import annotations

import glob
import json
import logging
import os
import time
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from scipy.stats import genpareto
from sklearn.linear_model import HuberRegressor

from config import Config

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("CAMARF.stats")

_ROOT = os.path.dirname(os.path.abspath(__file__))
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")
_BACKTEST_DIR = os.path.join(_ROOT, "output", "backtest")
_STATS_DIR = os.path.join(_ROOT, "output", "stats")

# Maps tf_label (from pairs.parquet) → directory prefix used by analysis.py
_TF_DIR_MAP: Dict[str, str] = {
    "1m": "1min", "2m": "2min", "3m": "3min", "5m": "5min",
    "15m": "15min", "30m": "30min", "1h": "1hr", "4h": "4hr",
    "1d": "1day", "1W": "1W", "1M": "1M",
}

# Slippage levels in basis points per execution (Phase 3 Monte Carlo)
_SLIPPAGE_BPS = [0, 2, 5, 10, 20]
# Assumed notional per leg for slippage calculation ($50 stock × 100 shares)
_NOTIONAL_PER_LEG = 5_000.0
# Monte Carlo path count
_MC_PATHS = 10_000
# Permutation draws
_N_PERMS = 1_000
# Minimum observations for GARCH(1,1) estimation
_MIN_GARCH_OBS = 30
# GPD exceedance threshold (percentile)
_EVT_PCTILE = 95
# Tukey bisquare constant for MM estimator (95% Gaussian efficiency)
_MM_C = 4.685


# =============================================================================
# SUMMARY LOG
# =============================================================================


class SummaryLog:
    """Collects lines for latest_run_stats.log (mirrors ml.py / backtest.py pattern)."""

    def __init__(self) -> None:
        self._lines: List[str] = []
        self._t0 = time.time()

    def note(self, msg: str) -> None:
        self._lines.append(msg)

    def write(self, path: str) -> None:
        runtime_min = (time.time() - self._t0) / 60
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("=== CAMARF stats.py ===\n")
            fh.write(f"date:        {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")
            fh.write(f"runtime_min: {runtime_min:.1f}\n\n")
            for line in self._lines:
                fh.write(line + "\n")
            fh.write("\n=== end ===\n")


summary = SummaryLog()


# =============================================================================
# DATA LOADING
# =============================================================================


def _load_all_pairs() -> pd.DataFrame:
    """Load all current (non-stale) pairs.parquet files across TFs.

    Non-stale directories are named by TF only (e.g. output/results/1hr/).
    Stale directories have a _stale_TIMESTAMP suffix.
    """
    frames = []
    for pth in glob.glob(os.path.join(_RESULTS_DIR, "*", "pairs.parquet")):
        dir_name = os.path.basename(os.path.dirname(pth))
        if "stale" in dir_name or "_" in dir_name:
            continue  # skip stale and any other timestamped directory
        try:
            df = pd.read_parquet(pth)
            frames.append(df)
        except Exception as e:
            log.warning("Could not read %s: %s", pth, e)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _load_spread_series(symbol_a: str, symbol_b: str, tf_label: str) -> Optional[pd.Series]:
    """Return the spread column from spread_series_{A}_{B}.parquet for this TF.

    Prefers the non-stale (current) directory (e.g. output/results/1hr/) over any
    stale-timestamped directory (e.g. output/results/1hr_stale_20260628_205521/).
    """
    dir_prefix = _TF_DIR_MAP.get(tf_label, tf_label)
    fname = f"spread_series_{symbol_a}_{symbol_b}.parquet"

    # 1) Prefer current non-stale directory (exact name, no timestamp)
    exact = os.path.join(_RESULTS_DIR, dir_prefix, fname)
    if os.path.exists(exact):
        candidates = [exact]
    else:
        # 2) Fall back to any timestamped directory, skip stale ones first
        all_matches = sorted(glob.glob(os.path.join(_RESULTS_DIR, f"{dir_prefix}_*", fname)))
        non_stale = [p for p in all_matches if "stale" not in os.path.basename(os.path.dirname(p))]
        candidates = non_stale if non_stale else all_matches

    for path in candidates:
        try:
            df = pd.read_parquet(path)
            spread = df["spread"].dropna()
            if len(spread) >= 20:
                return spread
        except Exception:
            continue
    return None


def _load_spread_df(symbol_a: str, symbol_b: str, tf_label: str) -> Optional[pd.DataFrame]:
    """Return the full spread_series DataFrame (not just the spread column)."""
    dir_prefix = _TF_DIR_MAP.get(tf_label, tf_label)
    fname = f"spread_series_{symbol_a}_{symbol_b}.parquet"
    exact = os.path.join(_RESULTS_DIR, dir_prefix, fname)
    if os.path.exists(exact):
        candidates = [exact]
    else:
        all_matches = sorted(glob.glob(os.path.join(_RESULTS_DIR, f"{dir_prefix}_*", fname)))
        non_stale = [p for p in all_matches if "stale" not in os.path.basename(os.path.dirname(p))]
        candidates = non_stale if non_stale else all_matches
    for path in candidates:
        try:
            df = pd.read_parquet(path)
            if len(df) >= 20:
                return df
        except Exception:
            continue
    return None


def _load_trades(suffix: str = "layer1") -> pd.DataFrame:
    pth = os.path.join(_BACKTEST_DIR, f"trades_{suffix}.parquet")
    if not os.path.exists(pth):
        return pd.DataFrame()
    return pd.read_parquet(pth)


def _load_portfolio(suffix: str = "layer1") -> pd.DataFrame:
    pth = os.path.join(_BACKTEST_DIR, f"portfolio_{suffix}.parquet")
    if not os.path.exists(pth):
        return pd.DataFrame()
    return pd.read_parquet(pth)


# =============================================================================
# SECTION 1 — CONFIRMATORY COINTEGRATION (KPSS + Phillips-Ouliaris proxy)
# =============================================================================
#
# Phillips-Ouliaris Z_t implemented as the Phillips-Perron test on OLS residuals
# (the spread series), which IS the PO statistic for a bivariate cointegrating
# regression — see Phillips & Ouliaris (1990).  arch.unitroot.PhillipsPerron uses
# MacKinnon (2010) response surfaces for critical values.
#
# KPSS null: series IS stationary.  Fail to reject (p > 0.05) → stationarity
# not ruled out → cointegration consistent.
# PO (PP on residuals) null: unit root.  Reject (p < 0.10) → stationary residuals
# → cointegration confirmed.
# EG: already in pairs.parquet as coint_pvalue_adjusted.
#
# Tier assignment:
#   n_confirm = (EG p < 0.05) + (KPSS p > 0.05) + (PO p < 0.10)
#   Gold   = n_confirm == 3
#   Silver = n_confirm == 2
#   Bronze = n_confirm == 1  (EG-only)
#   Flagged = KPSS rejects stationarity AND EG confirms cointegration (conflict)


def _run_coint_tests(spread: pd.Series, eg_pval: float) -> Dict:
    """Run KPSS and PP (PO proxy) on the spread, combine with EG for tier."""
    from arch.unitroot import KPSS as ArchKPSS
    from arch.unitroot import PhillipsPerron

    vals = spread.values.astype(float)
    result = {
        "eg_pval": float(eg_pval),
        "kpss_stat": np.nan,
        "kpss_pval": np.nan,
        "po_stat": np.nan,
        "po_pval": np.nan,
        "n_confirm": 0,
        "stats_tier": "bronze",
        "flagged_conflict": False,
    }

    try:
        kpss = ArchKPSS(vals)  # lags=None → data-dependent selection (arch 8)
        result["kpss_stat"] = float(kpss.stat)
        result["kpss_pval"] = float(kpss.pvalue)
    except Exception as e:
        log.debug("KPSS failed: %s", e)

    try:
        pp = PhillipsPerron(vals, trend="c")  # lags=None → data-dependent selection
        result["po_stat"] = float(pp.stat)
        result["po_pval"] = float(pp.pvalue)
    except Exception as e:
        log.debug("PP/PO failed: %s", e)

    eg_ok = float(eg_pval) < 0.05
    kpss_ok = not np.isnan(result["kpss_pval"]) and result["kpss_pval"] > 0.05
    po_ok = not np.isnan(result["po_pval"]) and result["po_pval"] < 0.10

    n_confirm = int(eg_ok) + int(kpss_ok) + int(po_ok)
    result["n_confirm"] = n_confirm

    if n_confirm == 3:
        result["stats_tier"] = "gold"
    elif n_confirm == 2:
        result["stats_tier"] = "silver"
    else:
        result["stats_tier"] = "bronze"

    # Conflict: EG confirms cointegration but KPSS also rejects stationarity
    # (suggests possible structural break rather than weaker evidence)
    if eg_ok and not np.isnan(result["kpss_pval"]) and result["kpss_pval"] < 0.05:
        result["flagged_conflict"] = True

    return result


def run_confirmatory_cointegration(pairs: pd.DataFrame) -> pd.DataFrame:
    """Run KPSS + PO for all pairs.  Returns augmented DataFrame with tier column."""
    log.info("=== Section 1: Confirmatory Cointegration (KPSS + PO) ===")
    rows = []
    counts = {"gold": 0, "silver": 0, "bronze": 0, "no_spread": 0, "conflict": 0}

    for _, row in pairs.iterrows():
        a, b, tf = row["symbol_a"], row["symbol_b"], row["tf_label"]
        eg_pval = float(row.get("coint_pvalue_adjusted", 1.0))
        spread = _load_spread_series(a, b, tf)

        base = row.to_dict()

        if spread is None:
            base.update({
                "eg_pval": eg_pval, "kpss_stat": np.nan, "kpss_pval": np.nan,
                "po_stat": np.nan, "po_pval": np.nan, "n_confirm": 0,
                "stats_tier": "bronze", "flagged_conflict": False,
            })
            counts["no_spread"] += 1
            rows.append(base)
            continue

        tests = _run_coint_tests(spread, eg_pval)
        base.update(tests)
        tier = tests["stats_tier"]
        counts[tier] = counts.get(tier, 0) + 1
        if tests["flagged_conflict"]:
            counts["conflict"] += 1

        log.info(
            "  %s/%s@%s  EG=%.3f  KPSS=%.3f  PO=%.3f  n_confirm=%d  tier=%s%s",
            a, b, tf, eg_pval,
            tests["kpss_pval"] if not np.isnan(tests["kpss_pval"]) else -1,
            tests["po_pval"] if not np.isnan(tests["po_pval"]) else -1,
            tests["n_confirm"], tier,
            " [CONFLICT]" if tests["flagged_conflict"] else "",
        )
        rows.append(base)

    out = pd.DataFrame(rows)
    log.info(
        "  Tiers: gold=%d  silver=%d  bronze=%d  no_spread=%d  flagged_conflict=%d",
        counts["gold"], counts["silver"], counts["bronze"],
        counts.get("no_spread", 0), counts["conflict"],
    )
    summary.note(
        f"[S1 Cointegration tiers] gold={counts['gold']} silver={counts['silver']} "
        f"bronze={counts['bronze']} no_spread={counts.get('no_spread',0)} "
        f"conflict={counts['conflict']}"
    )
    return out


# =============================================================================
# SECTION 2 — ROBUST HEDGE RATIO COMPARISON (Huber + MM)
# =============================================================================


def _mm_estimator(x: np.ndarray, y: np.ndarray) -> float:
    """MM-estimator via IRLS with Tukey bisquare weights (simplified S-init via MAD scale).

    Engle & Granger (1987) OLS hedge ratios can be contaminated by earnings
    announcements and flash-crash spikes.  MM estimator gives 50% breakdown
    point with near-Gaussian efficiency (c=4.685 → 95% at Normal).
    """
    if len(x) < 5:
        return np.nan
    x2 = np.column_stack([np.ones(len(x)), x])
    # Initial estimate via OLS
    try:
        beta_init, _, _, _ = np.linalg.lstsq(x2, y, rcond=None)
    except np.linalg.LinAlgError:
        return np.nan

    beta = beta_init.copy()
    for _ in range(50):
        resid = y - x2 @ beta
        scale = np.median(np.abs(resid)) / 0.6745  # MAD-based scale (consistent for Normal)
        if scale < 1e-10:
            break
        u = resid / (scale * _MM_C)
        # Tukey bisquare weights
        w = np.where(np.abs(u) <= 1.0, (1.0 - u**2) ** 2, 0.0)
        W = np.diag(w)
        try:
            beta_new = np.linalg.solve(x2.T @ W @ x2, x2.T @ W @ y)
        except np.linalg.LinAlgError:
            break
        if np.max(np.abs(beta_new - beta)) < 1e-8:
            beta = beta_new
            break
        beta = beta_new

    return float(beta[1])  # slope only


def run_robust_hedge_ratios(pairs: pd.DataFrame) -> pd.DataFrame:
    """Compute Huber and MM hedge ratios alongside OLS/TLS/Kalman for each pair."""
    log.info("=== Section 2: Robust Hedge Ratio Comparison ===")
    rows = []

    for _, row in pairs.iterrows():
        a, b, tf = row["symbol_a"], row["symbol_b"], row["tf_label"]
        spread = _load_spread_series(a, b, tf)

        rec = {
            "symbol_a": a, "symbol_b": b, "tf_label": tf,
            "beta_ols": float(row.get("hedge_ratio_ols", np.nan)),
            "beta_tls": float(row.get("hedge_ratio_tls", np.nan)),
            "beta_kalman": float(row.get("hedge_ratio_kalman_mean", np.nan)),
            "beta_huber": np.nan,
            "beta_mm": np.nan,
            "max_spread_bps": np.nan,
            "robust": False,
        }

        if spread is None or len(spread) < 10:
            rows.append(rec)
            continue

        # For robust estimation we need A and B price series.  Reconstruct
        # approximately from the spread (spread = log_A - β_ols * log_B + const)
        # by treating spread as "y" and using a proxy x = exp(mean + trend).
        # For simplicity, use the spread series as the dependent variable and
        # fit a constant + time-trend — this gives us the "net drift" hedge.
        # The primary robust signal is agreement across all five estimators.
        # Full price reconstruction would require the raw cache — deferred.
        # Here we estimate the TIME SERIES regression instead: spread_t = α + β * t.
        # Better: read actual prices from cache to get true bivariate fit.
        cache_dir = os.path.join(_ROOT, "output", "cache")
        # Cache filenames use IBKR bar size suffix (different from tf_label or dir prefix)
        tf_cache = {
            "1m": "1min", "2m": "2min", "3m": "3min", "5m": "5min",
            "15m": "15min", "30m": "30min", "1h": "1hr",
            "4h": "4hr", "1d": "1day", "1W": "1W", "1M": "1M",
        }
        ibkr_tf = tf_cache.get(tf, tf)
        cache_a = os.path.join(cache_dir, f"{a}_{ibkr_tf}.parquet")
        cache_b = os.path.join(cache_dir, f"{b}_{ibkr_tf}.parquet")

        try:
            if os.path.exists(cache_a) and os.path.exists(cache_b):
                pa = pd.read_parquet(cache_a)[["close"]].rename(columns={"close": "a"})
                pb = pd.read_parquet(cache_b)[["close"]].rename(columns={"close": "b"})
                aligned = pa.join(pb, how="inner").dropna()
                if len(aligned) >= 20:
                    log_a = np.log(aligned["a"].values)
                    log_b = np.log(aligned["b"].values)

                    # Huber
                    hub = HuberRegressor(epsilon=1.35, max_iter=200)
                    hub.fit(log_b.reshape(-1, 1), log_a)
                    rec["beta_huber"] = float(hub.coef_[0])

                    # MM
                    rec["beta_mm"] = _mm_estimator(log_b, log_a)

                    # Range of estimators as a robustness check
                    betas = [v for v in [
                        rec["beta_ols"], rec["beta_tls"], rec["beta_kalman"],
                        rec["beta_huber"], rec["beta_mm"],
                    ] if not np.isnan(v)]
                    if len(betas) >= 3:
                        spread_bps = (max(betas) - min(betas)) / abs(np.mean(betas)) * 10_000
                        rec["max_spread_bps"] = float(spread_bps)
                        rec["robust"] = spread_bps < 500  # < 5% disagreement across estimators
        except Exception as e:
            log.debug("Cache read failed for %s/%s@%s: %s", a, b, tf, e)

        log.info(
            "  %s/%s@%s  OLS=%.3f  TLS=%.3f  Kal=%.3f  Hub=%.3f  MM=%.3f  "
            "spread_bps=%.0f  robust=%s",
            a, b, tf,
            rec["beta_ols"], rec["beta_tls"], rec["beta_kalman"],
            rec["beta_huber"] if not np.isnan(rec["beta_huber"]) else -999,
            rec["beta_mm"] if not np.isnan(rec["beta_mm"]) else -999,
            rec["max_spread_bps"] if not np.isnan(rec["max_spread_bps"]) else -1,
            rec["robust"],
        )
        rows.append(rec)

    out = pd.DataFrame(rows)
    n_robust = int(out["robust"].sum())
    n_total = len(out)

    # hedge_direction_conflict: OLS and MM disagree on sign of the hedge ratio.
    # Flags pairs like CPF/WAFD where OLS says long A/short B but MM says
    # the opposite — the two estimators see different "true" relationships,
    # which means the spread definition is ambiguous. Should not be traded
    # without resolving which estimator is correct.
    def _sign_conflict(row: pd.Series) -> bool:
        ols, mm = row["beta_ols"], row["beta_mm"]
        if np.isnan(ols) or np.isnan(mm):
            return False
        return (ols > 0) != (mm > 0)

    out["hedge_direction_conflict"] = out.apply(_sign_conflict, axis=1)
    n_conflict = int(out["hedge_direction_conflict"].sum())
    if n_conflict:
        conflict_pairs = out[out["hedge_direction_conflict"]][["symbol_a", "symbol_b", "tf_label", "beta_ols", "beta_mm"]].to_string(index=False)
        log.warning("  hedge_direction_conflict (%d pairs):\n%s", n_conflict, conflict_pairs)

    log.info("  Robust pairs (all estimators agree within 5%%): %d/%d", n_robust, n_total)
    log.info("  Hedge direction conflicts (OLS vs MM sign flip): %d/%d", n_conflict, n_total)
    summary.note(f"[S2 Hedge ratios] robust={n_robust}/{n_total} (spread_bps < 500) conflicts={n_conflict}")
    return out


# =============================================================================
# SECTION 3 — EVT / GPD TAIL RISK
# =============================================================================


def _fit_gpd(values: np.ndarray) -> Tuple[float, float, float, int]:
    """Fit GPD to exceedances beyond the _EVT_PCTILE-th percentile of |values|.

    Returns (xi, sigma, threshold, n_exceedances).
    xi > 0: Pareto (fat tail), xi ≈ 0: exponential, xi < 0: bounded.
    """
    threshold = np.percentile(np.abs(values), _EVT_PCTILE)
    exceedances = np.abs(values[np.abs(values) > threshold]) - threshold
    if len(exceedances) < 5:
        return np.nan, np.nan, float(threshold), len(exceedances)
    try:
        xi, loc, sigma = genpareto.fit(exceedances, floc=0)
        return float(xi), float(sigma), float(threshold), len(exceedances)
    except Exception:
        return np.nan, np.nan, float(threshold), len(exceedances)


def run_evt_tail_risk(pairs: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    """Fit GPD to each confirmed pair's spread return distribution."""
    log.info("=== Section 3: EVT / GPD Tail Risk ===")
    rows = []

    for _, row in pairs.iterrows():
        a, b, tf = row["symbol_a"], row["symbol_b"], row["tf_label"]

        rec = {
            "symbol_a": a, "symbol_b": b, "tf_label": tf,
            "gpd_xi_spread": np.nan, "gpd_sigma_spread": np.nan,
            "gpd_threshold_spread": np.nan, "n_exceedances_spread": 0,
            "gpd_xi_pnl": np.nan, "gpd_sigma_pnl": np.nan,
            "gpd_threshold_pnl": np.nan, "n_exceedances_pnl": 0,
            "fat_tail": False,
        }

        # Spread returns (differenced spread series)
        spread = _load_spread_series(a, b, tf)
        if spread is not None and len(spread) >= 20:
            spread_returns = spread.diff().dropna().values
            xi_s, sigma_s, thresh_s, n_s = _fit_gpd(spread_returns)
            rec.update({
                "gpd_xi_spread": xi_s, "gpd_sigma_spread": sigma_s,
                "gpd_threshold_spread": thresh_s, "n_exceedances_spread": n_s,
            })

        # Per-trade P&L distribution
        pair_trades = pd.DataFrame()
        if len(trades) > 0:
            mask = (trades["symbol_a"] == a) & (trades["symbol_b"] == b) & (trades["tf"] == tf)
            pair_trades = trades[mask]
        if len(pair_trades) >= 5:
            pnl_vals = pair_trades["pnl_net"].values.astype(float)
            xi_p, sigma_p, thresh_p, n_p = _fit_gpd(pnl_vals)
            rec.update({
                "gpd_xi_pnl": xi_p, "gpd_sigma_pnl": sigma_p,
                "gpd_threshold_pnl": thresh_p, "n_exceedances_pnl": n_p,
            })

        # Fat-tail flag: either spread or P&L tail shape > 0.3
        xi_s_val = rec["gpd_xi_spread"] if not np.isnan(rec["gpd_xi_spread"]) else 0.0
        xi_p_val = rec["gpd_xi_pnl"] if not np.isnan(rec["gpd_xi_pnl"]) else 0.0
        rec["fat_tail"] = bool(xi_s_val > 0.3 or xi_p_val > 0.3)

        log.info(
            "  %s/%s@%s  ξ_spread=%.3f  ξ_pnl=%.3f  fat_tail=%s",
            a, b, tf,
            rec["gpd_xi_spread"] if not np.isnan(rec["gpd_xi_spread"]) else -99,
            rec["gpd_xi_pnl"] if not np.isnan(rec["gpd_xi_pnl"]) else -99,
            rec["fat_tail"],
        )
        rows.append(rec)

    out = pd.DataFrame(rows)
    n_fat = int(out["fat_tail"].sum()) if len(out) else 0
    log.info("  Fat-tailed pairs (ξ > 0.3): %d/%d", n_fat, len(out))
    summary.note(f"[S3 EVT/GPD] fat_tail_pairs={n_fat}/{len(out)} (xi > 0.30)")
    return out


# =============================================================================
# SECTION 4 — DCC-GARCH DYNAMIC CORRELATION
# =============================================================================
#
# Engle (2002) two-step:
#   1. Fit GARCH(1,1) per pair daily P&L series → standardized residuals ε_t
#   2. DCC update: Q_t = (1-a-b)*Q̄ + a*ε_{t-1}ε'_{t-1} + b*Q_{t-1}
#   3. R_t = diag(Q_t)^{-0.5} * Q_t * diag(Q_t)^{-0.5}
#
# arch.multivariate was removed in arch 7+.  We implement DCC from the
# univariate GARCH standardized residuals directly (this is exactly what
# the arch DCC class was doing internally — see Engle 2002 §2).


def _build_daily_pnl(trades: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-trade P&L to daily frequency, one column per pair."""
    if len(trades) == 0:
        return pd.DataFrame()
    tr = trades.copy()
    tr["pair"] = tr["symbol_a"] + "/" + tr["symbol_b"] + "@" + tr["tf"]
    tr["exit_date"] = pd.to_datetime(tr["exit_time"]).dt.date
    daily = tr.groupby(["exit_date", "pair"])["pnl_net"].sum().unstack("pair")
    daily.index = pd.to_datetime(daily.index)
    return daily.fillna(0.0)


def _fit_garch_residuals(series: np.ndarray) -> Optional[np.ndarray]:
    """Fit GARCH(1,1) and return standardized residuals.  None if insufficient data."""
    from arch import arch_model
    if len(series) < _MIN_GARCH_OBS or np.std(series) < 1e-10:
        return None
    try:
        # Rescale to unit-variance before fitting (arch recommends scale in 1–1000)
        scale = np.std(series)
        scaled = series / scale
        am = arch_model(scaled, vol="Garch", p=1, q=1, dist="normal", rescale=False)
        res = am.fit(disp="off", show_warning=False)
        cond_vol = res.conditional_volatility
        resid = res.resid
        std_resid = resid / np.where(cond_vol > 1e-10, cond_vol, 1e-10)
        return std_resid
    except Exception:
        return None


def _dcc_update(std_resids: np.ndarray, a: float = 0.04, b: float = 0.94) -> np.ndarray:
    """Engle (2002) DCC update.  Returns T×n×n array of dynamic correlations."""
    T, n = std_resids.shape
    Q_bar = np.cov(std_resids.T)
    Q = Q_bar.copy()
    correlations = np.zeros((T, n, n))
    for t in range(T):
        if t > 0:
            eps = std_resids[t - 1:t].T  # n×1
            Q = (1 - a - b) * Q_bar + a * (eps @ eps.T) + b * Q
        d = np.sqrt(np.diag(Q))
        d_inv = np.where(d > 1e-10, 1.0 / d, 0.0)
        R = d_inv[:, None] * Q * d_inv[None, :]
        correlations[t] = R
    return correlations


def run_dcc_garch(trades: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Fit GARCH(1,1) per pair, run DCC, return (pair_garch_stats, peak_corr_df)."""
    log.info("=== Section 4: DCC-GARCH Dynamic Correlation ===")
    daily = _build_daily_pnl(trades)

    if daily.shape[0] < _MIN_GARCH_OBS or daily.shape[1] < 2:
        log.warning("  Insufficient daily P&L data for DCC (need ≥%d days, ≥2 pairs)", _MIN_GARCH_OBS)
        summary.note(
            f"[S4 DCC-GARCH] skipped — only {daily.shape[0]} days, {daily.shape[1]} pairs "
            f"(need {_MIN_GARCH_OBS} days and ≥2 pairs)"
        )
        return pd.DataFrame(), pd.DataFrame()

    # Fit GARCH per pair, keep those with enough data
    std_resid_cols = {}
    garch_rows = []
    for col in daily.columns:
        series = daily[col].values
        nonzero = np.sum(np.abs(series) > 1e-6)
        if nonzero < _MIN_GARCH_OBS:
            log.info("  Skipping %s (only %d non-zero days)", col, nonzero)
            garch_rows.append({"pair": col, "garch_fitted": False, "nonzero_days": int(nonzero)})
            continue
        std_resid = _fit_garch_residuals(series)
        if std_resid is None:
            log.info("  GARCH failed for %s", col)
            garch_rows.append({"pair": col, "garch_fitted": False, "nonzero_days": int(nonzero)})
        else:
            std_resid_cols[col] = std_resid
            garch_rows.append({"pair": col, "garch_fitted": True, "nonzero_days": int(nonzero)})
            log.info("  GARCH(1,1) fitted for %s (%d non-zero days)", col, nonzero)

    garch_df = pd.DataFrame(garch_rows)

    if len(std_resid_cols) < 2:
        log.warning("  Only %d pairs with fitted GARCH — need ≥2 for DCC", len(std_resid_cols))
        summary.note(f"[S4 DCC-GARCH] only {len(std_resid_cols)} pairs with GARCH fit; DCC skipped")
        return garch_df, pd.DataFrame()

    # Align residual series
    pair_names = list(std_resid_cols.keys())
    min_len = min(len(v) for v in std_resid_cols.values())
    mat = np.column_stack([std_resid_cols[p][-min_len:] for p in pair_names])

    correlations = _dcc_update(mat)
    T = correlations.shape[0]
    dates = daily.index[-min_len:]

    # Build peak correlation summary (pair i vs pair j over time)
    peak_rows = []
    n = len(pair_names)
    for i in range(n):
        for j in range(i + 1, n):
            rho_series = correlations[:, i, j]
            peak_rows.append({
                "pair_i": pair_names[i],
                "pair_j": pair_names[j],
                "peak_rho": float(np.max(rho_series)),
                "mean_rho": float(np.mean(rho_series)),
                "min_rho": float(np.min(rho_series)),
                "peak_date": str(dates[np.argmax(rho_series)]) if len(dates) > 0 else "",
            })

    peak_df = pd.DataFrame(peak_rows)

    # Save the full rolling correlation to parquet
    rho_data = {}
    for i in range(n):
        for j in range(i + 1, n):
            col_name = f"{pair_names[i]}|{pair_names[j]}"
            rho_data[col_name] = correlations[:, i, j]
    rho_df = pd.DataFrame(rho_data, index=dates[:T])
    rho_df.to_parquet(os.path.join(_STATS_DIR, "dcc_rolling_correlation.parquet"))

    n_high = int((peak_df["peak_rho"] > 0.7).sum())
    log.info("  DCC complete: %d pair-pairs, %d with peak ρ > 0.70", len(peak_rows), n_high)
    summary.note(
        f"[S4 DCC-GARCH] {len(peak_rows)} pair-pairs; "
        f"peak_rho>0.70: {n_high} (correlated-loss risk)"
    )
    return garch_df, peak_df


# =============================================================================
# SECTION 5 — MONTE CARLO SIMULATION (Phases 1–4)
# =============================================================================


def _portfolio_sharpe(pnl_series: np.ndarray, ann_factor: float = 252.0) -> float:
    """Annualized Sharpe from daily P&L series."""
    if len(pnl_series) < 5 or np.std(pnl_series) < 1e-10:
        return np.nan
    return float(np.mean(pnl_series) / np.std(pnl_series) * np.sqrt(ann_factor))


def run_montecarlo(trades: pd.DataFrame, daily_pnl: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Phases 1–4.  Returns dict of DataFrames keyed by phase name."""
    log.info("=== Section 5: Monte Carlo Simulation ===")
    results: Dict[str, pd.DataFrame] = {}

    if len(trades) == 0:
        log.warning("  No trades — skipping Monte Carlo")
        summary.note("[S5 Monte Carlo] skipped — no trades")
        return results

    pnl_arr = trades["pnl_net"].values.astype(float)
    total_pnl = float(pnl_arr.sum())
    n_trades = len(pnl_arr)

    # ------ Phase 1: Distribution fitting ----------------------------------------
    log.info("  Phase 1: Distribution fitting (%d per-trade P&L observations)", n_trades)
    dist_rows = []
    families = {
        "normal": sp_stats.norm,
        "t": sp_stats.t,
        "nig_proxy_skewnorm": sp_stats.skewnorm,  # NIG proxy via skewnorm
        "laplace": sp_stats.laplace,
    }
    for name, dist in families.items():
        try:
            params = dist.fit(pnl_arr)
            log_lik = float(np.sum(dist.logpdf(pnl_arr, *params)))
            k = len(params)
            aic = 2 * k - 2 * log_lik
            bic = k * np.log(n_trades) - 2 * log_lik
            dist_rows.append({
                "distribution": name, "n_params": k, "log_lik": log_lik,
                "aic": aic, "bic": bic, "params": str(params),
            })
            log.info("    %s: AIC=%.1f  BIC=%.1f", name, aic, bic)
        except Exception as e:
            log.debug("    %s fit failed: %s", name, e)

    # GARCH(1,1)-filtered (fit on daily P&L, simulate residuals)
    if daily_pnl is not None and not daily_pnl.empty and daily_pnl.shape[0] >= _MIN_GARCH_OBS:
        portfolio_daily = daily_pnl.sum(axis=1).values
        std_resid = _fit_garch_residuals(portfolio_daily)
        if std_resid is not None:
            try:
                params_g = sp_stats.norm.fit(std_resid)
                log_lik_g = float(np.sum(sp_stats.norm.logpdf(std_resid, *params_g)))
                k_g = 2 + 2  # GARCH(1,1) has 2 params + mean + var0
                aic_g = 2 * k_g - 2 * log_lik_g
                bic_g = k_g * np.log(len(std_resid)) - 2 * log_lik_g
                dist_rows.append({
                    "distribution": "garch11_normal_resid", "n_params": k_g,
                    "log_lik": log_lik_g, "aic": aic_g, "bic": bic_g, "params": str(params_g),
                })
                log.info("    garch11_normal_resid: AIC=%.1f  BIC=%.1f", aic_g, bic_g)
            except Exception:
                pass

    dist_df = pd.DataFrame(dist_rows)
    if len(dist_df):
        best_dist = dist_df.loc[dist_df["aic"].idxmin(), "distribution"]
        log.info("  Best-fit distribution (AIC): %s", best_dist)
        summary.note(f"[S5 Phase 1] best_fit_dist={best_dist} (AIC), n_trades={n_trades}")
    results["dist_fit"] = dist_df

    # ------ Phase 2: Regime-conditional bootstrap --------------------------------
    log.info("  Phase 2: Regime-conditional bootstrap")
    regime_col = "vix_ts_regime" if "vix_ts_regime" in trades.columns else None
    regime_rows = []

    if regime_col and trades[regime_col].notna().any() and trades[regime_col].str.len().gt(0).any():
        for regime, grp in trades.groupby(regime_col):
            if len(grp) < 3:
                continue
            pnl_r = grp["pnl_net"].values.astype(float)
            # Bootstrap 1000 path simulated Sharpes
            rng = np.random.default_rng(42)
            sim_sharpes = []
            for _ in range(1000):
                resampled = rng.choice(pnl_r, size=len(pnl_r), replace=True)
                s = _portfolio_sharpe(resampled)
                if not np.isnan(s):
                    sim_sharpes.append(s)
            regime_rows.append({
                "regime": regime, "n_trades": len(grp),
                "mean_pnl": float(np.mean(pnl_r)), "std_pnl": float(np.std(pnl_r)),
                "sim_sharpe_5pct": float(np.percentile(sim_sharpes, 5)) if sim_sharpes else np.nan,
                "sim_sharpe_median": float(np.median(sim_sharpes)) if sim_sharpes else np.nan,
                "sim_sharpe_95pct": float(np.percentile(sim_sharpes, 95)) if sim_sharpes else np.nan,
            })
        log.info("  Regime-conditional bootstrap: %d regimes", len(regime_rows))
    else:
        # IID bootstrap when no regime tags
        rng = np.random.default_rng(42)
        sim_sharpes_iid = []
        for _ in range(1000):
            resampled = rng.choice(pnl_arr, size=len(pnl_arr), replace=True)
            s = _portfolio_sharpe(resampled)
            if not np.isnan(s):
                sim_sharpes_iid.append(s)
        regime_rows.append({
            "regime": "iid_all",
            "n_trades": n_trades,
            "mean_pnl": float(np.mean(pnl_arr)),
            "std_pnl": float(np.std(pnl_arr)),
            "sim_sharpe_5pct": float(np.percentile(sim_sharpes_iid, 5)) if sim_sharpes_iid else np.nan,
            "sim_sharpe_median": float(np.median(sim_sharpes_iid)) if sim_sharpes_iid else np.nan,
            "sim_sharpe_95pct": float(np.percentile(sim_sharpes_iid, 95)) if sim_sharpes_iid else np.nan,
        })
        log.info("  No regime tags — IID bootstrap: Sharpe 5/50/95 pct = %.2f/%.2f/%.2f",
                 regime_rows[-1]["sim_sharpe_5pct"], regime_rows[-1]["sim_sharpe_median"],
                 regime_rows[-1]["sim_sharpe_95pct"])

    results["regime_bootstrap"] = pd.DataFrame(regime_rows)
    summary.note(
        f"[S5 Phase 2] regime_bootstrap: {len(regime_rows)} groups, "
        f"iid_median_sharpe={regime_rows[-1]['sim_sharpe_median']:.2f}"
    )

    # ------ Phase 3: Slippage sensitivity ----------------------------------------
    log.info("  Phase 3: Slippage sensitivity")
    # Additional cost per trade = 2 legs × 2 sides × notional × bps/10000
    # = 4 × _NOTIONAL_PER_LEG × bps/10000
    slippage_rows = []
    if daily_pnl is not None and not daily_pnl.empty:
        portfolio_daily = daily_pnl.sum(axis=1).values
        baseline_sharpe = _portfolio_sharpe(portfolio_daily)
        total_trading_days = len(portfolio_daily)
        n_active_days = int(np.sum(np.abs(portfolio_daily) > 0))
        avg_trades_per_day = n_trades / max(n_active_days, 1)

        for bps in _SLIPPAGE_BPS:
            cost_per_trade = 4.0 * _NOTIONAL_PER_LEG * bps / 10_000.0
            daily_extra_cost = cost_per_trade * avg_trades_per_day
            adj_daily = portfolio_daily - daily_extra_cost
            adj_sharpe = _portfolio_sharpe(adj_daily)
            adj_total_pnl = float(np.sum(adj_daily))
            slippage_rows.append({
                "slippage_bps_per_side": bps,
                "cost_per_trade_dollars": float(cost_per_trade),
                "sharpe": float(adj_sharpe) if not np.isnan(adj_sharpe) else np.nan,
                "total_pnl": adj_total_pnl,
                "sharpe_vs_zero_bps": (adj_sharpe - slippage_rows[0]["sharpe"])
                    if slippage_rows else 0.0,
            })
            log.info(
                "    %2d bps/side: Sharpe=%.3f  TotalPnL=$%.0f",
                bps, adj_sharpe if not np.isnan(adj_sharpe) else -999, adj_total_pnl,
            )
        # Find breakeven
        for rec in slippage_rows:
            if not np.isnan(rec["sharpe"]) and rec["sharpe"] <= 0:
                log.info("  Slippage breakeven between %d and previous bps level", rec["slippage_bps_per_side"])
                break
        else:
            log.info("  Strategy Sharpe positive across all tested slippage levels")
    else:
        for bps in _SLIPPAGE_BPS:
            slippage_rows.append({"slippage_bps_per_side": bps, "sharpe": np.nan, "total_pnl": np.nan})

    results["slippage"] = pd.DataFrame(slippage_rows)
    summary.note(f"[S5 Phase 3] slippage tested at {_SLIPPAGE_BPS} bps/side")

    # ------ Phase 4: Trade quality (MAE / MFE) -----------------------------------
    log.info("  Phase 4: Trade quality (MAE/MFE)")
    if "mae" in trades.columns and "mfe" in trades.columns:
        mae_arr = trades["mae"].values.astype(float)
        mfe_arr = trades["mfe"].values.astype(float)
        valid = (np.isfinite(mae_arr)) & (np.isfinite(mfe_arr)) & (np.abs(mfe_arr) > 1e-6)
        mae_v = mae_arr[valid]
        mfe_v = mfe_arr[valid]
        pnl_v = pnl_arr[valid]

        efficiency = pnl_v / np.where(mfe_v > 0, mfe_v, 1e-6)  # final P&L / MFE
        bliss = float(np.mean(np.abs(mfe_v))) / max(float(np.mean(np.abs(mae_v))), 1e-6)

        # Bootstrap 1000 paths for confidence intervals
        rng = np.random.default_rng(42)
        sim_efficiency = []
        sim_bliss = []
        for _ in range(1000):
            idx = rng.integers(0, len(mae_v), size=len(mae_v))
            sim_eff = float(np.mean(pnl_v[idx] / np.where(mfe_v[idx] > 0, mfe_v[idx], 1e-6)))
            sim_bl = float(np.mean(np.abs(mfe_v[idx]))) / max(float(np.mean(np.abs(mae_v[idx]))), 1e-6)
            sim_efficiency.append(sim_eff)
            sim_bliss.append(sim_bl)

        quality_df = pd.DataFrame([{
            "metric": "efficiency", "realized": float(np.mean(efficiency)),
            "sim_5pct": float(np.percentile(sim_efficiency, 5)),
            "sim_95pct": float(np.percentile(sim_efficiency, 95)),
            "description": "mean(pnl / mfe) — 1.0 = always exit at peak",
        }, {
            "metric": "bliss_index", "realized": bliss,
            "sim_5pct": float(np.percentile(sim_bliss, 5)),
            "sim_95pct": float(np.percentile(sim_bliss, 95)),
            "description": "mean(|MFE|) / mean(|MAE|) — >1.0 = more upside than downside",
        }, {
            "metric": "win_rate", "realized": float(np.mean(pnl_v > 0)),
            "sim_5pct": np.nan, "sim_95pct": np.nan,
            "description": "fraction of trades with positive P&L",
        }])
        log.info(
            "  efficiency=%.3f  bliss=%.3f  win_rate=%.3f",
            float(np.mean(efficiency)), bliss, float(np.mean(pnl_v > 0)),
        )
        summary.note(
            f"[S5 Phase 4] efficiency={np.mean(efficiency):.3f} "
            f"bliss={bliss:.3f} win_rate={np.mean(pnl_v > 0):.3f}"
        )
        results["trade_quality"] = quality_df
    else:
        log.info("  MAE/MFE columns not found in trades — skipping Phase 4")
        results["trade_quality"] = pd.DataFrame()

    return results


# =============================================================================
# SECTION 6 — PERMUTATION TEST / WHITE REALITY CHECK
# =============================================================================


def run_permutation_test(
    trades: pd.DataFrame, portfolio_parquet_suffix: str = "layer1_holdout"
) -> Dict:
    """Portfolio-level White Reality Check (White 2000).

    Null hypothesis: entry signal timing has no skill — any realized P&L distribution
    could have been achieved by randomly reassigning trade outcomes to the same entry dates.

    Method:
    1. Realized statistic: daily closed-trade portfolio Sharpe (consistent between
       realized and permuted paths).  Backtest equity-curve Sharpe (3.249) also reported.
    2. Generate N_PERMS permuted portfolios by randomly shuffling pnl_net values
       across trades (keeps entry/exit date structure, destroys outcome-signal link).
    3. p-value = fraction of permuted Sharpes >= realized closed-trade Sharpe.
    """
    log.info("=== Section 6: Permutation Test / White Reality Check ===")

    if len(trades) == 0:
        log.warning("  No trades — skipping permutation test")
        summary.note("[S6 Permutation] skipped — no trades")
        return {}

    # Equity-curve Sharpe from backtest.py (reference number for paper)
    backtest_sharpe = np.nan
    port_path = os.path.join(_BACKTEST_DIR, f"portfolio_{portfolio_parquet_suffix}.parquet")
    if os.path.exists(port_path):
        try:
            port = pd.read_parquet(port_path)
            backtest_sharpe = float(port.iloc[0]["sharpe_portfolio"])
        except Exception:
            pass

    # Build realized closed-trade daily P&L
    tr = trades.copy()
    tr["exit_date"] = pd.to_datetime(tr["exit_time"]).dt.date
    daily_agg = tr.groupby("exit_date")["pnl_net"].sum()
    daily_vals = daily_agg.values.astype(float)

    realized_closed_sharpe = _portfolio_sharpe(daily_vals)
    log.info(
        "  Realized: backtest_equity_sharpe=%.4f  closed_trade_sharpe=%.4f  n_trades=%d",
        backtest_sharpe if not np.isnan(backtest_sharpe) else -999,
        realized_closed_sharpe if not np.isnan(realized_closed_sharpe) else -999,
        len(trades),
    )

    if np.isnan(realized_closed_sharpe):
        summary.note("[S6 Permutation] realized closed-trade Sharpe is NaN — skipping")
        return {}

    # Permutation: shuffle pnl_net values across trades, recompute daily P&L + Sharpe
    # This preserves the marginal distribution of per-trade outcomes but destroys the
    # link between WHICH entry signal produced WHICH outcome — testing outcome-timing skill
    pnl_arr = tr["pnl_net"].values.astype(float)
    rng = np.random.default_rng(42)
    perm_sharpes = []
    for _ in range(_N_PERMS):
        perm_pnl = rng.permutation(pnl_arr)
        tr_perm = tr.copy()
        tr_perm["pnl_net"] = perm_pnl
        daily_perm = tr_perm.groupby("exit_date")["pnl_net"].sum().values.astype(float)
        s = _portfolio_sharpe(daily_perm)
        if not np.isnan(s):
            perm_sharpes.append(s)

    perm_arr = np.array(perm_sharpes)
    pvalue = float(np.mean(perm_arr >= realized_closed_sharpe))
    significant = pvalue < 0.05

    log.info(
        "  Permutation test: realized=%.4f  perm_mean=%.4f  perm_95pct=%.4f  "
        "p_value=%.4f  significant=%s  n_perms=%d",
        realized_closed_sharpe,
        float(np.mean(perm_arr)),
        float(np.percentile(perm_arr, 95)) if len(perm_arr) else np.nan,
        pvalue, significant, len(perm_arr),
    )
    summary.note(
        f"[S6 Permutation] backtest_equity_sharpe={backtest_sharpe:.4f} "
        f"closed_trade_sharpe={realized_closed_sharpe:.4f} "
        f"p_value={pvalue:.4f} significant={significant} n_perms={len(perm_arr)}"
    )

    return {
        "backtest_equity_sharpe": float(backtest_sharpe) if not np.isnan(backtest_sharpe) else None,
        "realized_closed_trade_sharpe": float(realized_closed_sharpe),
        "n_trades": len(trades),
        "n_active_days": int(len(daily_agg)),
        "n_perms": len(perm_arr),
        "perm_mean_sharpe": float(np.mean(perm_arr)),
        "perm_std_sharpe": float(np.std(perm_arr)),
        "perm_5pct_sharpe": float(np.percentile(perm_arr, 5)) if len(perm_arr) else None,
        "perm_95pct_sharpe": float(np.percentile(perm_arr, 95)) if len(perm_arr) else None,
        "pvalue": pvalue,
        "significant_at_0_05": significant,
        "note": (
            "Null: entry signal timing has no skill — pnl_net values randomly reassigned "
            "across trades, keeping exit-date structure.  p-value = fraction of permuted "
            "closed-trade Sharpes >= realized.  Backtest equity-curve Sharpe (from "
            "backtest.py) reported separately as the primary paper number."
        ),
    }


# =============================================================================
# SECTION 7 — HALF-LIFE STATIONARITY
# =============================================================================


def run_halflife_stationarity(pairs: pd.DataFrame) -> pd.DataFrame:
    """AR(1) + Zivot-Andrews on the rolling half-life series per pair.

    Tests whether each pair's mean-reversion speed is itself stable or
    drifts over time.  A stationary HL series (ZA rejects unit root) means
    the pair's dynamics are well-behaved; a unit-root HL means reversion
    speed wanders and the OU model parameters estimated in-sample may not
    hold OOS.

    Outputs per pair:
      hl_ar1_rho      — AR(1) lag-1 coefficient (1=random walk, 0=white noise)
      hl_ar1_pval     — t-test p-value for rho != 0
      hl_za_stat      — Zivot-Andrews test statistic (more negative = more stationary)
      hl_za_pval      — ZA p-value (< 0.05 → reject unit root → HL is stationary)
      hl_za_breakdate — Detected structural break date in HL series
      hl_stationary   — bool: ZA p-value < 0.10
    """
    log.info("=== Section 7: Half-Life Stationarity (AR(1) + Zivot-Andrews) ===")

    try:
        from statsmodels.tsa.stattools import zivot_andrews
        _za_available = True
    except ImportError:
        log.warning("  statsmodels.tsa.stattools.zivot_andrews not available — ZA skipped")
        _za_available = False

    rows = []

    for _, row in pairs.iterrows():
        a, b, tf = row["symbol_a"], row["symbol_b"], row["tf_label"]

        rec = {
            "symbol_a": a, "symbol_b": b, "tf_label": tf,
            "hl_ar1_rho": np.nan, "hl_ar1_pval": np.nan,
            "hl_za_stat": np.nan, "hl_za_pval": np.nan,
            "hl_za_breakdate": None, "hl_stationary": False,
        }

        spread = _load_spread_df(a, b, tf)
        if spread is None or "half_life_rolling" not in spread.columns:
            rows.append(rec)
            continue

        hl = spread["half_life_rolling"].dropna()
        hl = hl[np.isfinite(hl) & (hl > 0)]

        if len(hl) < 30:
            log.debug("  %s/%s@%s: insufficient HL observations (%d)", a, b, tf, len(hl))
            rows.append(rec)
            continue

        # AR(1): regress hl[t] on hl[t-1]
        try:
            y = hl.values[1:]
            x = hl.values[:-1]
            x2 = np.column_stack([np.ones(len(x)), x])
            coef, _, _, _ = np.linalg.lstsq(x2, y, rcond=None)
            rho = float(coef[1])
            resid = y - x2 @ coef
            se = float(np.sqrt(np.var(resid) / np.sum((x - x.mean()) ** 2)))
            t_stat = rho / se if se > 1e-10 else np.nan
            ar1_pval = float(2 * (1 - sp_stats.t.cdf(abs(t_stat), df=len(y) - 2))) if np.isfinite(t_stat) else np.nan
            rec["hl_ar1_rho"] = round(rho, 4)
            rec["hl_ar1_pval"] = round(ar1_pval, 4) if np.isfinite(ar1_pval) else np.nan
        except Exception as e:
            log.debug("  AR(1) failed for %s/%s@%s: %s", a, b, tf, e)

        # Zivot-Andrews: unit root test allowing for one structural break
        if _za_available and len(hl) >= 20:
            try:
                za_result = zivot_andrews(hl.values, trim=0.15, regression="c", autolag="AIC")
                rec["hl_za_stat"] = round(float(za_result[0]), 4)
                rec["hl_za_pval"] = round(float(za_result[1]), 4)
                # za_result[4] is baselag; za_result[3] is the break index
                break_idx = int(za_result[3]) if len(za_result) > 3 else None
                if break_idx is not None and break_idx < len(hl):
                    rec["hl_za_breakdate"] = str(hl.index[break_idx])
                rec["hl_stationary"] = bool(za_result[1] < 0.10)
            except Exception as e:
                log.debug("  ZA failed for %s/%s@%s: %s", a, b, tf, e)

        log.info(
            "  %s/%s@%s  AR1_rho=%.3f  ZA_stat=%.2f  ZA_pval=%.3f  stationary=%s",
            a, b, tf,
            rec["hl_ar1_rho"] if np.isfinite(rec["hl_ar1_rho"]) else float("nan"),
            rec["hl_za_stat"] if np.isfinite(rec["hl_za_stat"]) else float("nan"),
            rec["hl_za_pval"] if np.isfinite(rec["hl_za_pval"]) else float("nan"),
            rec["hl_stationary"],
        )
        rows.append(rec)

    out = pd.DataFrame(rows)
    n_stat = int(out["hl_stationary"].sum())
    n_total = len(out)
    log.info(
        "  HL stationary (ZA p<0.10): %d/%d  |  mean AR1_rho=%.3f",
        n_stat, n_total,
        out["hl_ar1_rho"].mean() if not out["hl_ar1_rho"].isna().all() else float("nan"),
    )
    summary.note(f"[S7 HL stationarity] stationary={n_stat}/{n_total} (ZA p<0.10)")
    return out


# =============================================================================
# MAIN
# =============================================================================


def main() -> None:
    t0 = time.time()
    log.info("=" * 70)
    log.info("CAMARF  —  stats.py  —  Statistical Validation Layer")
    log.info("=" * 70)

    os.makedirs(_STATS_DIR, exist_ok=True)

    # ---- Load inputs ------------------------------------------------------------
    pairs = _load_all_pairs()
    if len(pairs) == 0:
        log.error("No pairs found in output/results/ — run analysis.py first")
        summary.note("ERROR: No pairs found — analysis.py must run first")
        summary.write(os.path.join(_ROOT, "latest_run_stats.log"))
        return
    log.info("Loaded %d confirmed pairs across %d TFs", len(pairs),
             pairs["tf_label"].nunique() if "tf_label" in pairs.columns else 0)
    summary.note(f"Input: {len(pairs)} confirmed pairs")

    trades_is = _load_trades("layer1")
    trades_oos = _load_trades("layer1_holdout")
    trades_neghedge = _load_trades("layer1_holdout_neghedge")
    log.info("Trades: IS=%d  OOS=%d  OOS+neg-hedge=%d",
             len(trades_is), len(trades_oos), len(trades_neghedge))
    summary.note(f"Trades: IS={len(trades_is)} OOS={len(trades_oos)} neghedge={len(trades_neghedge)}")

    # Primary analysis trades (use IS for distribution fitting; OOS for permutation test)
    all_trades = pd.concat([trades_is, trades_oos], ignore_index=True) if len(trades_is) > 0 else trades_oos
    daily_is = _build_daily_pnl(trades_is)
    daily_oos = _build_daily_pnl(trades_oos)

    # ---- Section 1: Confirmatory cointegration ----------------------------------
    tier_df = run_confirmatory_cointegration(pairs)
    tier_df.to_parquet(os.path.join(_STATS_DIR, "cointegration_tiers.parquet"), index=False)
    log.info("  Saved → output/stats/cointegration_tiers.parquet")

    # ---- Section 2: Robust hedge ratios -----------------------------------------
    hedge_df = run_robust_hedge_ratios(pairs)
    hedge_df.to_parquet(os.path.join(_STATS_DIR, "hedge_ratio_comparison.parquet"), index=False)
    log.info("  Saved → output/stats/hedge_ratio_comparison.parquet")

    # Propagate hedge_direction_conflict into tiers parquet so downstream
    # scripts (backtest, wfa, report) can filter on it without re-running S2.
    conflict_cols = ["symbol_a", "symbol_b", "tf_label", "hedge_direction_conflict"]
    if "hedge_direction_conflict" in hedge_df.columns:
        tier_df = tier_df.merge(
            hedge_df[conflict_cols], on=["symbol_a", "symbol_b", "tf_label"], how="left"
        )
        tier_df["hedge_direction_conflict"] = tier_df["hedge_direction_conflict"].fillna(False)
        tier_df.to_parquet(os.path.join(_STATS_DIR, "cointegration_tiers.parquet"), index=False)
        log.info("  Updated cointegration_tiers.parquet with hedge_direction_conflict")

    # ---- Section 3: EVT / GPD tail risk -----------------------------------------
    evt_df = run_evt_tail_risk(pairs, all_trades)
    evt_df.to_parquet(os.path.join(_STATS_DIR, "evt_tail_risk.parquet"), index=False)
    log.info("  Saved → output/stats/evt_tail_risk.parquet")

    # ---- Section 4: DCC-GARCH ---------------------------------------------------
    garch_df, peak_df = run_dcc_garch(all_trades)
    if not garch_df.empty:
        garch_df.to_parquet(os.path.join(_STATS_DIR, "dcc_garch_stats.parquet"), index=False)
    if not peak_df.empty:
        peak_df.to_parquet(os.path.join(_STATS_DIR, "dcc_peak_correlation.parquet"), index=False)
        log.info("  Saved → output/stats/dcc_garch_stats.parquet + dcc_peak_correlation.parquet")

    # ---- Section 5: Monte Carlo (use IS trades for distribution fitting) --------
    daily_combined = _build_daily_pnl(all_trades)
    mc_results = run_montecarlo(all_trades, daily_combined)
    for phase_name, df in mc_results.items():
        if not df.empty:
            df.to_parquet(os.path.join(_STATS_DIR, f"montecarlo_{phase_name}.parquet"), index=False)
    log.info("  Saved → output/stats/montecarlo_*.parquet")

    # ---- Section 6: Permutation test — OOS holdout (primary) + IS (for power) ----
    perm_result = run_permutation_test(trades_oos, "layer1_holdout")
    if perm_result:
        with open(os.path.join(_STATS_DIR, "permutation_test_oos.json"), "w") as fh:
            json.dump(perm_result, fh, indent=2)
        log.info("  Saved OOS permutation → output/stats/permutation_test_oos.json")

    # Always run IS permutation too (more trades → more statistical power)
    if len(trades_is) > 0:
        perm_is = run_permutation_test(trades_is, "layer1")
        if perm_is:
            perm_is["note"] += "  [IN-SAMPLE — reported for power; OOS result is primary for paper]"
            with open(os.path.join(_STATS_DIR, "permutation_test_is.json"), "w") as fh:
                json.dump(perm_is, fh, indent=2)
            log.info("  Saved IS permutation → output/stats/permutation_test_is.json")

    # ---- Section 7: Half-life stationarity ----
    if tier_df is not None and len(tier_df) > 0:
        hl_stat = run_halflife_stationarity(tier_df)
        hl_stat.to_parquet(os.path.join(_STATS_DIR, "halflife_stationarity.parquet"), index=False)
        log.info("  Saved => output/stats/halflife_stationarity.parquet (%d rows)", len(hl_stat))

    # ---- Final log --------------------------------------------------------------
    runtime = (time.time() - t0) / 60
    log.info("=" * 70)
    log.info("stats.py complete  (%.1f min)", runtime)
    log.info("Output: %s", _STATS_DIR)

    summary.note(f"\nruntime_min: {runtime:.1f}")
    summary.write(os.path.join(_ROOT, "latest_run_stats.log"))
    log.info("Log written → latest_run_stats.log")


if __name__ == "__main__":
    main()
