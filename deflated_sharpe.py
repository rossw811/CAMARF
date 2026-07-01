"""
deflated_sharpe.py — Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014,
"The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest
Overfitting and Non-Normality").

Motivation (2026-06-30 STORM literature survey, §7 "Performance Claims and
Their Replication Record"): CAMARF has run 13+ named backtest variants
(baseline, risk_parity, neg_hedge, hub_weight, pnl_cap, 4+ STORM flags,
entry-z overrides, plus WFA folds and sensitivity-grid points) without ever
correcting the headline OOS Sharpe (5.2443) for the fact that many
configurations were tried before settling on one. The "False Strategy
Theorem" (Bailey & Lopez de Prado, 2014): the expected maximum Sharpe ratio
achievable by N genuinely skill-less strategies grows with N — so a raw
Sharpe ratio, however large, says nothing about genuine skill without also
reporting how many configurations were searched to find it. This script
reports that correction honestly: whatever the DSR says, including a low
probability, is the number that gets recorded — this is not built to
validate a target outcome.

Method:
  1. Retroactively backfill trial_registry.json from every existing
     output/backtest/portfolio_*.parquet file not already recorded (so
     variants run in prior sessions, before trial_registry.py existed,
     still count toward N).
  2. Build the real daily P&L series for the configuration being evaluated
     (same grouping stats.py's permutation test uses: group closed-trade
     pnl_net by exit date) to get the true per-period (non-annualized)
     Sharpe SR_hat, sample size T, skewness, and kurtosis — NOT the
     annualized sharpe_portfolio number, which would mismatch the T used
     in the DSR's sqrt(T-1) term.
  3. Estimate Var[{SR_n}] from the annualized sharpe_portfolio values
     recorded in trial_registry.json, CONVERTED to the same per-period
     (daily) units as SR_hat before computing variance — every trial's
     sharpe_portfolio comes from backtest.py's aggregate_portfolio(), which
     always resamples to daily P&L and annualizes by a fixed sqrt(252)
     regardless of the pair's native timeframe, so dividing every recorded
     Sharpe by sqrt(252) is an exact, not approximate, unit conversion back
     to daily terms. (An earlier version of this script mixed annualized
     variance directly against per-period SR_hat — caught by actually
     running it on real data and finding the DSR flipped from ~1.0 to ~0.0
     depending on which units were used; verify_only comparing the two is
     exactly the kind of silent unit-mismatch this project's synthetic-test
     discipline is meant to catch, and a synthetic test alone did not catch
     it because it never tests unit consistency across two different data
     sources — only running on real numbers surfaced the sensitivity.)
  4. Compute the Deflated Sharpe Ratio as a probability P(true Sharpe > 0),
     report alongside the raw trial count N and Var[{SR_n}] used.

Output:
  output/stats/deflated_sharpe.json
  latest_run_deflated_sharpe.log
"""
import glob
import json
import logging
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trial_registry import load_trials, record_trial, _REGISTRY_PATH

_ROOT = os.path.dirname(os.path.abspath(__file__))
_BACKTEST_DIR = os.path.join(_ROOT, "output", "backtest")
_STATS_DIR = os.path.join(_ROOT, "output", "stats")

_EULER_MASCHERONI = 0.5772156649015329

log = logging.getLogger("deflated_sharpe")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_deflated_sharpe.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


# =============================================================================
# CORE MATH — Bailey & Lopez de Prado (2014)
# =============================================================================

def expected_max_sharpe_null(n_trials: int, var_sr_across_trials: float) -> float:
    """
    SR0*: the expected maximum Sharpe ratio achievable by chance alone across
    n_trials independent, genuinely skill-less strategies, given the
    empirical variance of Sharpe outcomes observed across those trials
    (Bailey & Lopez de Prado 2014, eq. 8 — the "False Strategy Theorem").
    n_trials <= 1 means no multiple-testing correction applies (SR0*=0).
    """
    if n_trials <= 1 or var_sr_across_trials <= 0:
        return 0.0
    z1 = stats.norm.ppf(1 - 1.0 / n_trials)
    z2 = stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
    return float(np.sqrt(var_sr_across_trials) * (
        (1 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2
    ))


def deflated_sharpe_ratio(
    sr_hat: float,
    t_obs: int,
    skew: float,
    kurtosis: float,
    n_trials: int,
    var_sr_across_trials: float,
) -> float:
    """
    Returns the Deflated Sharpe Ratio as a probability in [0, 1]:
    P(true per-period Sharpe > 0 | observed SR_hat over t_obs periods with
    the given return skew/kurtosis, after correcting for n_trials
    configurations having been searched). Bailey & Lopez de Prado (2014).

    sr_hat, skew, kurtosis must be computed on the SAME per-period return
    series (t_obs = number of periods in that series) — mixing an
    annualized Sharpe with a daily T is a unit mismatch that silently
    breaks the sqrt(t_obs-1) scaling.
    """
    z_stat = deflated_sharpe_z_stat(sr_hat, t_obs, skew, kurtosis, n_trials, var_sr_across_trials)
    if not np.isfinite(z_stat):
        return float("nan")
    return float(stats.norm.cdf(z_stat))


def deflated_sharpe_z_stat(
    sr_hat: float,
    t_obs: int,
    skew: float,
    kurtosis: float,
    n_trials: int,
    var_sr_across_trials: float,
) -> float:
    """
    The underlying z-statistic behind deflated_sharpe_ratio()'s probability —
    reported separately because a DSR of 1.0000 (saturated) doesn't convey
    HOW MUCH margin there is above the "no genuine skill" null; a z-stat of
    3 and a z-stat of 30 both round to DSR=1.0000 but mean very different
    things about how decisively the null is rejected.
    """
    sr0 = expected_max_sharpe_null(n_trials, var_sr_across_trials)
    denom = np.sqrt(1 - skew * sr_hat + ((kurtosis - 1) / 4) * sr_hat ** 2)
    if not np.isfinite(denom) or denom <= 0 or t_obs <= 1:
        return float("nan")
    return float((sr_hat - sr0) * np.sqrt(t_obs - 1) / denom)


# =============================================================================
# DATA LOADING
# =============================================================================

def _backfill_trial_registry() -> int:
    """Scan every output/backtest/portfolio_*.parquet not already in
    trial_registry.json and record it as a historical trial (timestamp_run
    unknown for backfilled entries — file mtime used as a best-effort proxy).
    Returns the number of new entries added."""
    existing_labels = {t["label"] for t in load_trials()}
    n_added = 0
    for path in sorted(glob.glob(os.path.join(_BACKTEST_DIR, "portfolio_*.parquet"))):
        fname = os.path.basename(path)
        label = fname[len("portfolio_"):-len(".parquet")]
        if label in existing_labels:
            continue
        try:
            df = pd.read_parquet(path)
            if df.empty:
                continue
            sharpe = df.iloc[0].get("sharpe_portfolio")
            n_trades = int(df.iloc[0].get("n_trades_total", 0) or 0)
        except Exception as e:
            log.debug("  backfill skip %s: %s", fname, e)
            continue
        mtime = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(path)))
        record_trial(label=label, sharpe=sharpe, n_trades=n_trades,
                      script="backtest.py (backfilled)", timestamp_run=mtime)
        existing_labels.add(label)
        n_added += 1
    return n_added


def _daily_pnl_stats(trades_path: str) -> Optional[Tuple[float, int, float, float]]:
    """Returns (sr_hat, t_obs, skew, kurtosis) for the per-period (daily)
    closed-trade P&L series — same grouping stats.py's permutation test
    uses (group pnl_net by exit date)."""
    if not os.path.exists(trades_path):
        return None
    trades = pd.read_parquet(trades_path)
    if trades.empty or "pnl_net" not in trades.columns:
        return None
    tr = trades.copy()
    tr["exit_date"] = pd.to_datetime(tr["exit_time"]).dt.date
    daily = tr.groupby("exit_date")["pnl_net"].sum()
    vals = daily.values.astype(float)
    if len(vals) < 3 or np.std(vals, ddof=1) == 0:
        return None
    sr_hat = float(np.mean(vals) / np.std(vals, ddof=1))
    t_obs = len(vals)
    skew = float(stats.skew(vals))
    kurt = float(stats.kurtosis(vals, fisher=False))  # normal = 3, matches DSR formula convention
    return sr_hat, t_obs, skew, kurt


# =============================================================================
# MAIN
# =============================================================================

def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== deflated_sharpe.py: Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014) ===")

    n_backfilled = _backfill_trial_registry()
    log.info("Backfilled %d historical trial(s) from output/backtest/portfolio_*.parquet "
              "not already in trial_registry.json", n_backfilled)

    trials = load_trials()
    if len(trials) < 2:
        log.warning("Fewer than 2 trials recorded (%d) — DSR multiple-testing "
                    "correction is not meaningful yet. Run more backtest.py "
                    "variants first.", len(trials))
        return

    # Every trial's sharpe_portfolio is annualized by the SAME fixed sqrt(252)
    # in backtest.py's aggregate_portfolio() (daily P&L resample regardless of
    # the pair's native timeframe) — dividing by sqrt(252) is therefore an
    # exact conversion back to per-period (daily) units, matching SR_hat's
    # units below. Do NOT compute this variance on the raw annualized values;
    # see module docstring for what happens if you do.
    _ANNUALIZATION = np.sqrt(252)
    trial_sharpes_annualized = np.array([t["sharpe"] for t in trials], dtype=float)
    trial_sharpes_daily = trial_sharpes_annualized / _ANNUALIZATION
    var_sr = float(np.var(trial_sharpes_daily, ddof=1))
    n_trials = len(trials)
    log.info("N trials = %d, Var[Sharpe across trials] = %.6f (per-period/daily units, "
              "converted from annualized sharpe_portfolio via /sqrt(252))",
              n_trials, var_sr)

    results = {}
    for suffix, description in [
        ("layer1", "in-sample baseline"),
        ("layer1_holdout", "out-of-sample holdout baseline"),
    ]:
        trades_path = os.path.join(_BACKTEST_DIR, f"trades_{suffix}.parquet")
        stats_tuple = _daily_pnl_stats(trades_path)
        if stats_tuple is None:
            log.warning("  [%s] no usable trades at %s — skipping", suffix, trades_path)
            continue
        sr_hat, t_obs, skew, kurt = stats_tuple
        dsr = deflated_sharpe_ratio(sr_hat, t_obs, skew, kurt, n_trials, var_sr)
        z_stat = deflated_sharpe_z_stat(sr_hat, t_obs, skew, kurt, n_trials, var_sr)
        log.info(
            "  [%s] %s: per-period SR_hat=%.4f (T=%d, skew=%.3f, kurt=%.3f) "
            "-> DSR = %.4f (z=%.2f, P(true Sharpe > 0), corrected for %d trials)",
            suffix, description, sr_hat, t_obs, skew, kurt, dsr, z_stat, n_trials,
        )
        results[suffix] = {
            "description": description,
            "sr_hat_per_period": sr_hat,
            "t_obs": t_obs,
            "skew": skew,
            "kurtosis": kurt,
            "n_trials": n_trials,
            "var_sr_across_trials": var_sr,
            "deflated_sharpe_ratio": dsr,
            "z_stat": z_stat,
        }

    if results:
        out_path = os.path.join(_STATS_DIR, "deflated_sharpe.json")
        os.makedirs(_STATS_DIR, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        log.info("Saved => %s", out_path)
    else:
        log.warning("No results produced — no usable trades_*.parquet found.")

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("deflated_sharpe.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
