"""
research/backtest_overfitting_detector.py -- the backtest-overfitting-detector application
flagged (not built) in Finding #55, per Ross's own notes on Breeden-Litzenberger: "and also a
backtest overfitting detector."

Compares an asset's REALIZED historical return distribution (from real cached price data,
scaled to the same horizon as a live option chain's expiry) against the market's CURRENT
risk-neutral density for that same asset (research/risk_neutral_density.py) -- if a backtest's
assumed/realized risk profile looks nothing like what options markets are actually pricing in
right now (e.g., realized history shows a much narrower or differently-shaped distribution than
the market currently expects), that mismatch is itself a real, actionable signal: either the
historical sample period was unusually calm/turbulent relative to the market's current view, or
a strategy built on that history is implicitly betting the future won't look like what options
markets are pricing -- both worth surfacing, not silently assumed away.

Method: pulls a live risk-neutral density for a symbol/expiry (reusing research/risk_neutral_
density.py directly, not reimplemented), converts the extracted strike-space density into
return space (return = strike/S - 1), computes its mean/std/skew via the same weighted-moment
approach already verified in debug/_verify_risk_neutral_density.py. Separately computes the
REALIZED historical return distribution for the same asset and same horizon length (T years),
using non-overlapping historical windows (never overlapping windows -- overlapping windows
would understate the realized variance's true sampling uncertainty, a real, disclosed
methodology choice). Reports both distributions' mean/std/skew side by side, plus a direct
comparison metric: how many standard deviations apart are the two means, and what's the ratio
of realized-to-implied volatility (a ratio far from 1 in either direction is the real "does this
look like overfitting/regime mismatch" signal).

Verified against synthetic ground truth first: debug/_verify_backtest_overfitting_detector.py.

Usage:
    python research/backtest_overfitting_detector.py --symbol SPY --expiry 2026-09-18
"""
import argparse
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from options import load_price_series
from research.risk_neutral_density import fetch_live_option_chain, extract_risk_neutral_density

log = logging.getLogger("backtest_overfitting_detector")


def _setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")


def weighted_moments(values: np.ndarray, weights: np.ndarray) -> dict:
    """Mean/std/skew of a discrete weighted distribution -- the same weighted third-standardized-
    moment approach already verified in debug/_verify_risk_neutral_density.py, factored out here
    as a shared utility so both the RND side and the realized-return side use IDENTICAL moment
    math (a real methodology risk if the two sides used even slightly different formulas -- any
    difference found would then be ambiguous between "a real distributional difference" and "an
    artifact of inconsistent moment computation")."""
    w = weights / weights.sum()
    mean = float((values * w).sum())
    var = float((w * (values - mean) ** 2).sum())
    std = float(np.sqrt(var))
    skew = float((w * (values - mean) ** 3).sum() / std ** 3) if std > 0 else np.nan
    return {"mean": mean, "std": std, "skew": skew}


def rnd_to_return_space(rnd: pd.DataFrame, S: float) -> dict:
    """Converts a strike-space risk-neutral density into return space (return = strike/S - 1)
    and computes its weighted moments."""
    returns = rnd["strike"].to_numpy() / S - 1.0
    weights = rnd["density_clipped"].to_numpy()
    return weighted_moments(returns, weights)


def realized_return_distribution(close: pd.Series, T_years: float) -> dict:
    """Realized historical return distribution over non-overlapping windows of length T_years --
    NOT a rolling/overlapping-window sample, which would understate the true sampling
    uncertainty of the realized variance (adjacent overlapping windows share almost all their
    data, so they aren't independent observations, and naively treating them as if they were
    would make the realized distribution look artificially more precise/narrow than it really
    is). Returns NaN fields (not a crash) if there's less than 2 full non-overlapping windows of
    history available -- can't estimate a distribution's spread from a single point."""
    if close is None or len(close) < 10:
        return {"mean": np.nan, "std": np.nan, "skew": np.nan, "n_windows": 0}
    window_bars = max(int(round(T_years * 252)), 1)
    n_windows = len(close) // window_bars
    if n_windows < 2:
        return {"mean": np.nan, "std": np.nan, "skew": np.nan, "n_windows": n_windows}
    prices = close.to_numpy()[-(n_windows * window_bars):]
    windows = prices.reshape(n_windows, window_bars)
    period_returns = windows[:, -1] / windows[:, 0] - 1.0
    weights = np.ones(n_windows)
    moments = weighted_moments(period_returns, weights)
    moments["n_windows"] = n_windows
    return moments


def compare_realized_vs_implied(symbol: str, expiry: str, moneyness_band: tuple = (0.7, 1.3)) -> dict:
    """Full comparison: fetches the live RND for (symbol, expiry), computes the realized
    historical return distribution for the same symbol at the same horizon, and reports both
    side by side plus a direct comparison metric."""
    data = fetch_live_option_chain(symbol, expiry, moneyness_band=moneyness_band)
    rnd = extract_risk_neutral_density(data["S"], data["strikes"], data["ivs"], data["T"])
    implied = rnd_to_return_space(rnd, data["S"])

    close = load_price_series(symbol)
    realized = realized_return_distribution(close, data["T"])

    vol_ratio = (realized["std"] / implied["std"]) if implied["std"] and np.isfinite(implied["std"]) \
        and implied["std"] > 0 and np.isfinite(realized["std"]) else np.nan
    mean_gap_in_implied_stds = ((realized["mean"] - implied["mean"]) / implied["std"]) \
        if implied["std"] and np.isfinite(implied["std"]) and implied["std"] > 0 \
        and np.isfinite(realized["mean"]) else np.nan

    return {"symbol": symbol, "expiry": expiry, "T_years": data["T"], "S": data["S"],
            "implied_mean": implied["mean"], "implied_std": implied["std"], "implied_skew": implied["skew"],
            "realized_mean": realized["mean"], "realized_std": realized["std"], "realized_skew": realized["skew"],
            "realized_n_windows": realized["n_windows"],
            "realized_to_implied_vol_ratio": vol_ratio,
            "mean_gap_in_implied_stds": mean_gap_in_implied_stds}


def main():
    _setup_logging()
    parser = argparse.ArgumentParser(description="Backtest-overfitting detector: realized history vs. live market-implied risk-neutral density")
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--expiry", required=True, help="Option expiry date, e.g. 2026-09-18")
    args = parser.parse_args()

    log.info(f"=== backtest_overfitting_detector.py: realized history vs. live RND for "
              f"{args.symbol} @ {args.expiry} ===")
    result = compare_realized_vs_implied(args.symbol, args.expiry)
    log.info(f"S={result['S']:.2f}, T={result['T_years']:.4f} years")
    log.info(f"  MARKET-IMPLIED (live RND):  mean={result['implied_mean']:.4f}  "
              f"std={result['implied_std']:.4f}  skew={result['implied_skew']:.4f}")
    log.info(f"  REALIZED (history, {result['realized_n_windows']} non-overlapping windows): "
              f"mean={result['realized_mean']:.4f}  std={result['realized_std']:.4f}  "
              f"skew={result['realized_skew']:.4f}")
    log.info(f"  realized/implied vol ratio: {result['realized_to_implied_vol_ratio']:.3f} "
              f"(1.0 = history matches the market's current view; far from 1.0 = a real regime "
              f"mismatch worth investigating before trusting a backtest over this horizon)")
    log.info(f"  mean gap: {result['mean_gap_in_implied_stds']:.3f} implied standard deviations")

    out_path = f"output/research/backtest_overfitting_detector_{args.symbol}_{args.expiry}.parquet"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    pd.DataFrame([result]).to_parquet(out_path)
    log.info(f"Saved -> {out_path}")
    log.info("backtest_overfitting_detector.py complete")


if __name__ == "__main__":
    main()
