"""
research/var_backtest_calibration.py -- Thread N #5: VaR model backtesting/
calibration check, the first sub-arm of the regulatory-risk-convention
comparison arm (ancient-mixing-feather.md Thread N). Sequenced first per that
thread's own design: answers "is a VaR framework even meaningful for this
strategy" BEFORE #1 (VaR-based position sizing) tries to use one.

STATED PLAINLY, PER THAT THREAD'S OWN FRAMING: this is a risk-METHODOLOGY
comparison, not a legal compliance certification. Whether any real fund
structure is actually regulatorily compliant depends on registration status,
jurisdiction, and fund documents -- not something this project can certify.
What this DOES do: test whether the strategy's realized daily P&L breaches a
standard historical-VaR estimate more often than a well-calibrated model
should, using the same well-known Basel "traffic light" exception-counting
convention (<=4 exceptions/250 days = green/acceptable, 5-9 = yellow, 10+ =
red) real risk-management functions use to validate VaR models before
trusting them for sizing.

Reuses research/fama_french_risk_decomposition.py::build_daily_return_series
directly (the same realized-trade -> daily-P&L reconstruction already built
and verified for Thread F Part A) -- not reimplemented.

Method: rolling HISTORICAL VaR (the simplest, most standard VaR estimator --
the empirical (1-confidence) percentile of a trailing window's own daily P&L,
no distributional assumption). At each day t, VaR_t = negative of the
`window`-day trailing empirical percentile of daily P&L (causal -- only uses
data BEFORE t, no lookahead). An "exception" is a day where realized loss
EXCEEDS (is worse than) that day's VaR estimate.

HONEST SCALE CAVEAT (disclosed, not hidden): Basel's 250-trading-day
convention assumes a full trading year of daily observations. CAMARF's own
realized backtest history is currently much shorter (see Thread M's Finding
#32 -- most arms have well under 250 days of REALIZED, non-zero P&L). This
script reports the exception RATE (exceptions / observations), not just a
raw count, and explicitly states whether the sample is long enough to apply
Basel's traffic-light convention at its intended scale.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.fama_french_risk_decomposition import build_daily_return_series

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STEP5_DIR = os.path.join(_ROOT, "output", "research", "step5_arm_results")
_OUT_PATH = os.path.join(_ROOT, "output", "research", "var_backtest_calibration_results.parquet")

_STARTING_CAPITAL = 100_000
_MIN_WINDOW_OBS = 20  # minimum trailing observations before a VaR estimate is even attempted


def rolling_historical_var(daily_pnl: pd.Series, window: int, confidence: float) -> pd.Series:
    """VaR_t = -1 * the (1-confidence) empirical percentile of daily_pnl over
    [t-window, t-1] (STRICTLY causal -- day t's own P&L is never in its own
    VaR estimate's window). NaN until `window` prior observations exist."""
    pct = (1.0 - confidence) * 100
    var_estimates = pd.Series(np.nan, index=daily_pnl.index)
    for i in range(len(daily_pnl)):
        if i < window:
            continue
        trailing = daily_pnl.iloc[i - window:i]
        if trailing.notna().sum() < _MIN_WINDOW_OBS:
            continue
        var_estimates.iloc[i] = -np.percentile(trailing.dropna(), pct)
    return var_estimates


def count_exceptions(daily_pnl: pd.Series, var_estimates: pd.Series) -> dict:
    """An exception: realized loss (-daily_pnl, when positive) exceeds the
    VaR estimate for that day. Only counted where a VaR estimate exists AND
    is non-degenerate (var_t > 0).

    Real finding made verifying this against CAMARF's own sparse-trading arms
    (2026-08-14): a trailing window that's mostly exact-zero P&L days (see
    Thread M's Finding #32 -- baseline/tiered are 81-82% zero-return months)
    produces a degenerate var_t <= 0 estimate for EVERY SINGLE observation --
    n_obs previously reported ALL attempted estimates (392 for baseline),
    silently including these degenerate ones, making a headline "0
    exceptions" look like a real calibration success when it was actually
    ZERO genuinely meaningful observations. n_obs now counts ONLY the
    non-degenerate ones; n_degenerate is reported separately so this can
    never be silently misread again."""
    valid = var_estimates.notna()
    realized_loss = -daily_pnl[valid]
    var_t = var_estimates[valid]
    meaningful = var_t > 0
    exceptions = (realized_loss > var_t) & meaningful
    n_obs = int(meaningful.sum())
    n_attempted = int(valid.sum())
    n_degenerate = n_attempted - n_obs
    n_exceptions = int(exceptions.sum())
    exception_rate = n_exceptions / n_obs if n_obs > 0 else np.nan
    return {
        "n_obs": n_obs,
        "n_attempted": n_attempted,
        "n_degenerate": n_degenerate,
        "n_exceptions": n_exceptions,
        "exception_rate": exception_rate,
        "exception_dates": list(daily_pnl.index[valid][exceptions]),
    }


def basel_traffic_light(n_exceptions: int, n_obs: int) -> str:
    """Basel's own convention is defined at exactly 250 obs AND specifically for 99% VaR (1%
    expected daily exceedance) -- the 4/9 thresholds are NOT confidence-level-agnostic. Real
    finding made while verifying this function (debug/_verify_var_backtest_calibration.py Check
    4): applying these same thresholds to a 95% VaR result (5% expected exceedance) will show
    "red" even for a PERFECTLY calibrated model, since 5% inherently exceeds what a 1%-oriented
    threshold tolerates -- a methodology mismatch, not a real risk-model failure. Callers must
    only interpret this function's output as a genuine calibration verdict for confidence=0.99
    results; a "red" light at confidence=0.95 says nothing about whether that model is actually
    miscalibrated. Also scales the exception count proportionally when n_obs != 250, explicitly
    disclosed as an approximation, not Basel's literal rule at a different sample size."""
    if n_obs == 0:
        return "insufficient_data"
    scaled = n_exceptions * (250.0 / n_obs)
    if scaled <= 4:
        return "green"
    elif scaled <= 9:
        return "yellow"
    else:
        return "red"


def main():
    results = []
    for arm in ["baseline", "hybrid", "purity", "tiered"]:
        for split in ["is", "oos"]:
            trades_path = os.path.join(_STEP5_DIR, f"real_{arm}_{split}_trades_capsim.parquet")
            if not os.path.exists(trades_path):
                continue
            trades_df = pd.read_parquet(trades_path)
            if trades_df.empty:
                continue
            daily_returns = build_daily_return_series(trades_df, _STARTING_CAPITAL)
            daily_pnl = daily_returns * _STARTING_CAPITAL  # back to dollar P&L for VaR units
            if len(daily_pnl) < _MIN_WINDOW_OBS * 2:
                print(f"{arm}/{split}: only {len(daily_pnl)} daily obs, too short for a "
                      f"meaningful rolling VaR window -- skipping")
                continue

            window = max(_MIN_WINDOW_OBS, len(daily_pnl) // 3)
            for confidence in (0.95, 0.99):
                var_est = rolling_historical_var(daily_pnl, window, confidence)
                exc = count_exceptions(daily_pnl, var_est)
                light = basel_traffic_light(exc["n_exceptions"], exc["n_obs"])
                is_full_scale = exc["n_obs"] >= 250
                light_caveat = "" if confidence == 0.99 else \
                    "  ** traffic_light not meaningful at this confidence level (Basel's 4/9 " \
                    "thresholds are calibrated for 99% VaR's 1% expected rate, not this " \
                    "confidence's own expected rate -- see basel_traffic_light()'s docstring) **"
                degenerate_flag = f" ({exc['n_degenerate']}/{exc['n_attempted']} DEGENERATE -- " \
                                   f"var_t<=0, excluded)" if exc["n_degenerate"] > 0 else ""
                print(f"{arm}/{split} VaR{int(confidence*100)}: n_obs={exc['n_obs']}{degenerate_flag} "
                      f"exceptions={exc['n_exceptions']} rate={exc['exception_rate']:.3f} "
                      f"(expected ~{1-confidence:.3f}) traffic_light={light} "
                      f"{'[FULL BASEL SCALE]' if is_full_scale else '[SCALED APPROXIMATION -- sample < 250 obs]'}"
                      f"{light_caveat}")
                results.append({
                    "arm": arm, "split": split, "confidence": confidence,
                    "n_obs": exc["n_obs"], "n_exceptions": exc["n_exceptions"],
                    "exception_rate": exc["exception_rate"],
                    "expected_rate": 1 - confidence,
                    "traffic_light": light, "full_basel_scale": is_full_scale,
                    "window": window,
                })

    if results:
        pd.DataFrame(results).to_parquet(_OUT_PATH, index=False)
        print(f"\nSaved {len(results)} VaR calibration results -> {_OUT_PATH}")
    else:
        print("\nNo arms had enough realized daily P&L for a meaningful VaR backtest.")


if __name__ == "__main__":
    main()
