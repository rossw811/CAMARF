"""
cvar.py — Historical (non-parametric) Conditional Value at Risk / Expected
Shortfall on CAMARF's portfolio-level daily P&L.

Motivation (STORM infrastructure gap analysis, 2026-07-01): no portfolio-
level tail-risk metric existed anywhere in this pipeline. VaR is deliberately
NOT what's implemented here: the STORM survey's own Skeptic-lens research
found VaR badly failed institutions heading into 2008 specifically because
its normal-distribution assumption understates fat-tail/asymmetric risk, and
this project's own trade P&L is already known to be strongly skewed and
fat-tailed (deflated_sharpe.py's IS/OOS skew=2.4-2.9, kurtosis=14.2-14.3 —
far from normal). Reporting a parametric VaR number here would repeat the
exact failure mode the survey flagged. Historical CVaR sidesteps the
normal-distribution assumption entirely: it is just the mean of the worst
(1-alpha) fraction of REALIZED daily P&L observations, not a fitted-
distribution quantile.

Method: reuses the same exit-date daily-P&L grouping convention as
deflated_sharpe.py's _daily_pnl_stats() and stats.py's permutation test
(group closed-trade pnl_net by exit date, sum to one portfolio P&L per day).
CVaR_alpha = mean loss among the worst (1-alpha) fraction of days, where
"loss" = -daily_pnl (so a profitable day contributes a negative "loss").

Output: output/stats/cvar.json
"""
import json
import logging
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

_ROOT = os.path.dirname(os.path.abspath(__file__))
_BACKTEST_DIR = os.path.join(_ROOT, "output", "backtest")
_STATS_DIR = os.path.join(_ROOT, "output", "stats")

log = logging.getLogger("cvar")

_ALPHAS = (0.95, 0.99)


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(os.path.join(_ROOT, "latest_run_cvar.log"), mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def daily_pnl_series(trades_path: str) -> "pd.Series | None":
    if not os.path.exists(trades_path):
        return None
    trades = pd.read_parquet(trades_path)
    if trades.empty or "pnl_net" not in trades.columns:
        return None
    tr = trades.copy()
    tr["exit_date"] = pd.to_datetime(tr["exit_time"]).dt.date
    daily = tr.groupby("exit_date")["pnl_net"].sum()
    return daily if len(daily) >= 3 else None


def historical_cvar(daily_pnl: np.ndarray, alpha: float) -> dict:
    """
    Historical (empirical) VaR and CVaR at confidence level alpha, in P&L
    dollar units. losses = -daily_pnl, so VaR/CVaR are positive numbers
    representing a dollar loss magnitude (0 or negative means no tail loss
    at that confidence level — e.g. an all-profitable day set).
    """
    losses = -np.asarray(daily_pnl, dtype=float)
    var = float(np.quantile(losses, alpha))
    tail = losses[losses >= var]
    cvar = float(tail.mean()) if len(tail) > 0 else var
    return {
        "alpha": alpha,
        "var": var,
        "cvar": cvar,
        "n_tail_days": int(len(tail)),
        "n_total_days": int(len(losses)),
    }


def var_exceedance_backtest(daily_pnl: np.ndarray, alpha: float, min_calibration_days: int = 30) -> dict:
    """
    Kupiec (1995) unconditional-coverage test + Christoffersen (1998)
    independence and conditional-coverage tests on a VaR model's realized
    exceedance sequence — the specific validation cvar.py never had (a
    confirmed real gap flagged in the 2026-07-05 author-concept-backlog
    research pass, closed here rather than left as an open citation).

    VaR forecast for day t is the empirical `alpha`-quantile of losses on
    days [0, t) only (expanding-window, causal — never uses day t's own
    outcome to forecast day t). An "exceedance" is realized_loss_t >
    VaR_t. Under a correctly-calibrated model, exceedances should occur at
    rate (1-alpha) and be serially independent (no clustering).

    Kupiec POF (proportion-of-failures) LR statistic:
        LR_pof = -2 * ln[ (1-p)^(n-x) * p^x / ((1-x/n)^(n-x) * (x/n)^x) ]
    where p = 1-alpha (expected exceedance rate), x = observed exceedances,
    n = total forecast days. LR_pof ~ chi2(1) under H0: true rate = p.

    Christoffersen independence LR statistic, from the 2x2 transition
    matrix of the exceedance indicator sequence (counts n_ij = transitions
    from state i to state j, i,j in {0=no exceedance, 1=exceedance}):
        LR_ind = -2*ln[ (1-pi_hat)^(n00+n10) * pi_hat^(n01+n11) /
                         ((1-pi01)^n00 * pi01^n01 * (1-pi11)^n10 * pi11^n11) ]
    ~ chi2(1) under H0: exceedances are independent (no clustering).
    Combined conditional-coverage LR_cc = LR_pof + LR_ind ~ chi2(2).

    Returns None if there are too few post-calibration days to form any
    forecasts (rather than forcing a result on too little data).
    """
    losses = -np.asarray(daily_pnl, dtype=float)
    n_total = losses.size
    if n_total <= min_calibration_days + 5:
        return None

    p = 1.0 - alpha
    exceedances = np.empty(n_total - min_calibration_days, dtype=int)
    for i, t in enumerate(range(min_calibration_days, n_total)):
        var_t = np.quantile(losses[:t], alpha)
        exceedances[i] = int(losses[t] > var_t)

    n = exceedances.size
    x = int(exceedances.sum())

    # --- Kupiec POF ---
    pi_hat = x / n
    if pi_hat in (0.0, 1.0):
        # Degenerate: log-likelihood under pi_hat is undefined at the
        # boundary — report the exceedance count/rate but skip the LR
        # statistic rather than divide by zero or take log(0).
        lr_pof, pof_pvalue = np.nan, np.nan
    else:
        log_l_null = (n - x) * np.log(1 - p) + x * np.log(p)
        log_l_alt = (n - x) * np.log(1 - pi_hat) + x * np.log(pi_hat)
        lr_pof = -2 * (log_l_null - log_l_alt)
        pof_pvalue = float(1 - sp_stats.chi2.cdf(lr_pof, df=1))

    # --- Christoffersen independence ---
    n00 = int(np.sum((exceedances[:-1] == 0) & (exceedances[1:] == 0)))
    n01 = int(np.sum((exceedances[:-1] == 0) & (exceedances[1:] == 1)))
    n10 = int(np.sum((exceedances[:-1] == 1) & (exceedances[1:] == 0)))
    n11 = int(np.sum((exceedances[:-1] == 1) & (exceedances[1:] == 1)))
    pi01 = n01 / (n00 + n01) if (n00 + n01) > 0 else np.nan
    pi11 = n11 / (n10 + n11) if (n10 + n11) > 0 else np.nan
    pi_overall = (n01 + n11) / (n00 + n01 + n10 + n11) if (n00 + n01 + n10 + n11) > 0 else np.nan

    def _safe_term(count, prob):
        if count == 0:
            return 0.0
        if prob <= 0 or prob >= 1 or np.isnan(prob):
            return np.nan
        return count * np.log(prob)

    if np.isnan(pi01) or np.isnan(pi11) or np.isnan(pi_overall):
        lr_ind, ind_pvalue = np.nan, np.nan
    else:
        log_l_null_ind = (
            _safe_term(n00 + n10, 1 - pi_overall) + _safe_term(n01 + n11, pi_overall)
        )
        log_l_alt_ind = (
            _safe_term(n00, 1 - pi01) + _safe_term(n01, pi01)
            + _safe_term(n10, 1 - pi11) + _safe_term(n11, pi11)
        )
        if np.isnan(log_l_null_ind) or np.isnan(log_l_alt_ind):
            lr_ind, ind_pvalue = np.nan, np.nan
        else:
            lr_ind = -2 * (log_l_null_ind - log_l_alt_ind)
            ind_pvalue = float(1 - sp_stats.chi2.cdf(lr_ind, df=1))

    if np.isnan(lr_pof) or np.isnan(lr_ind):
        lr_cc, cc_pvalue = np.nan, np.nan
    else:
        lr_cc = lr_pof + lr_ind
        cc_pvalue = float(1 - sp_stats.chi2.cdf(lr_cc, df=2))

    return {
        "alpha": alpha,
        "n_forecasts": int(n),
        "n_exceedances": x,
        "exceedance_rate": float(pi_hat),
        "expected_rate": p,
        "kupiec_lr": float(lr_pof) if not np.isnan(lr_pof) else None,
        "kupiec_pvalue": pof_pvalue if not np.isnan(pof_pvalue) else None,
        "christoffersen_ind_lr": float(lr_ind) if not np.isnan(lr_ind) else None,
        "christoffersen_ind_pvalue": ind_pvalue if not np.isnan(ind_pvalue) else None,
        "conditional_coverage_lr": float(lr_cc) if not np.isnan(lr_cc) else None,
        "conditional_coverage_pvalue": cc_pvalue if not np.isnan(cc_pvalue) else None,
    }


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== cvar.py: Historical CVaR / Expected Shortfall (portfolio daily P&L) ===")

    results = {}
    for suffix, description in [
        ("layer1", "in-sample baseline"),
        ("layer1_holdout", "out-of-sample holdout baseline"),
    ]:
        trades_path = os.path.join(_BACKTEST_DIR, f"trades_{suffix}.parquet")
        daily = daily_pnl_series(trades_path)
        if daily is None:
            log.warning("  [%s] no usable trades at %s — skipping", suffix, trades_path)
            continue
        vals = daily.values.astype(float)
        entry = {"description": description, "n_days": len(vals), "mean_daily_pnl": float(np.mean(vals))}
        for alpha in _ALPHAS:
            r = historical_cvar(vals, alpha)
            entry[f"var_{int(alpha*100)}"] = r["var"]
            entry[f"cvar_{int(alpha*100)}"] = r["cvar"]
            entry[f"n_tail_days_{int(alpha*100)}"] = r["n_tail_days"]
            log.info(
                "  [%s] %s: VaR_%.0f%% = $%.2f, CVaR_%.0f%% (mean of worst %d/%d days) = $%.2f",
                suffix, description, alpha * 100, r["var"], alpha * 100,
                r["n_tail_days"], r["n_total_days"], r["cvar"],
            )
            backtest = var_exceedance_backtest(vals, alpha)
            if backtest is not None:
                entry[f"var_backtest_{int(alpha*100)}"] = backtest
                log.info(
                    "  [%s] VaR_%.0f%% backtest: %d/%d exceedances (rate=%.3f vs expected %.3f), "
                    "Kupiec p=%s, Christoffersen-independence p=%s, conditional-coverage p=%s",
                    suffix, alpha * 100, backtest["n_exceedances"], backtest["n_forecasts"],
                    backtest["exceedance_rate"], backtest["expected_rate"],
                    f"{backtest['kupiec_pvalue']:.3f}" if backtest["kupiec_pvalue"] is not None else "n/a",
                    f"{backtest['christoffersen_ind_pvalue']:.3f}" if backtest["christoffersen_ind_pvalue"] is not None else "n/a",
                    f"{backtest['conditional_coverage_pvalue']:.3f}" if backtest["conditional_coverage_pvalue"] is not None else "n/a",
                )
            else:
                log.info("  [%s] VaR_%.0f%% backtest: skipped (too few days for expanding-window forecasts)", suffix, alpha * 100)
        results[suffix] = entry

    if results:
        os.makedirs(_STATS_DIR, exist_ok=True)
        out_path = os.path.join(_STATS_DIR, "cvar.json")
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        log.info("Saved => %s", out_path)
    else:
        log.warning("No results produced — no usable trades_*.parquet found.")

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("cvar.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
