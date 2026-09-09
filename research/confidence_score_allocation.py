"""
research/confidence_score_allocation.py -- Phase 4 (the last, most architecturally significant
item) of the new backlog: "confidence score as filter, then position allocation. max points in
each category = 100%."

Combines Phase 1-3's real signals into a single per-trade confidence score in [0, 100], built
from 4 categories, each contributing up to 25 points (an equal-weighting default, disclosed as a
default choice, not dogma -- swept as a real design question below, not asserted):

  1. Statistical confirmation strength (hurst_at_entry -- lower Hurst = more genuinely
     mean-reverting = stronger signal)
  2. Reversion speed (half_life_at_entry -- shorter half-life = more tractable within a normal
     holding period)
  3. Volatility regime normality (Phase 1's asset_volatility_profile.parquet vol_percentile for
     both legs, averaged -- penalizes entering when an asset is at an abnormal vol extreme,
     rewards a "normal for this asset" vol regime)
  4. Market-neutrality quality (Phase 3's beta_weighted_portfolio.parquet net_dollar_beta_
     exposure, normalized by trade notional -- penalizes pairs whose two legs' market betas are
     badly mismatched)

Each category is converted to a 0-100 score via a PERCENTILE RANK within the real trade set
(not an arbitrary hardcoded scale) -- "derive from the data, don't guess a constant," this
project's own standing convention. Direction per category is chosen so LOWER raw badness always
maps to a HIGHER score.

Validation, not just assertion: rather than assume a higher confidence score predicts better
trades, this directly TESTS it -- with/without comparison arms sweeping a filter threshold
(score >= {0, 25, 50, 75}) and reporting portfolio Sharpe/Sortino/Calmar at each, via this
project's own canonical portfolio_math.py. If confirmation strength / reversion speed /
vol-regime normality / beta-neutrality genuinely predict trade quality, higher thresholds should
show better risk-adjusted metrics on the surviving trades; if they don't, that's a real, honest
result to report, not a system to declare "working" by assertion.

Position-allocation sizing (score/100 as a notional multiplier, applied to pnl_net as a linear
size-scaling approximation -- a simplification disclosed here, not a full re-run of the
backtest engine at scaled size) is reported alongside the filter sweep as a second view of the
same underlying question.

Verified against synthetic ground truth first: debug/_verify_confidence_score_allocation.py.

Usage:
    python research/confidence_score_allocation.py
"""
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from portfolio_math import daily_pnl_from_trades, sharpe_from_daily_pnl, sortino_from_daily_pnl, \
    calmar_from_daily_pnl

log = logging.getLogger("confidence_score_allocation")

CATEGORY_MAX_POINTS = 25.0  # equal weighting default across the 4 categories (sums to 100)
FILTER_THRESHOLDS = [0, 25, 50, 75]
STARTING_CAPITAL = 100_000


def _setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")


def percentile_score(raw_values: pd.Series, higher_is_worse: bool = True) -> pd.Series:
    """Converts a raw per-trade value into a 0-100 score via percentile rank WITHIN the given
    series -- data-derived, not an arbitrary fixed scale. `higher_is_worse=True` (the default,
    matching every category in this module: high Hurst, long half-life, extreme vol percentile
    distance, and large beta mismatch are all BAD) inverts the rank so a low raw value gets a
    HIGH score. NaN raw values get a NaN score (excluded from the average, not silently zeroed
    -- a missing signal shouldn't be scored as "the worst possible," it should be scored as
    "not scored" and left out of that trade's total)."""
    valid = raw_values.dropna()
    if len(valid) < 2:
        return pd.Series(np.nan, index=raw_values.index)
    ranks = valid.rank(pct=True)  # 0 (lowest raw value) to 1 (highest raw value)
    score = (1.0 - ranks) if higher_is_worse else ranks
    return (score * 100.0).reindex(raw_values.index)


def compute_confidence_scores(trades: pd.DataFrame, vol_profile: pd.DataFrame,
                                category_max: float = CATEGORY_MAX_POINTS) -> pd.DataFrame:
    """Computes the 4 category scores (each 0 to `category_max`) and their sum (0-100 total)
    for every trade. Returns trades with new columns: score_confirmation, score_reversion_speed,
    score_vol_regime, score_beta_neutrality, confidence_score, n_categories_scored (a trade
    missing some categories' data still gets a score, averaged over however many WERE
    computable -- disclosed via n_categories_scored, not silently treated as if all 4 existed)."""
    trades = trades.copy()

    raw_confirmation = trades["hurst_at_entry"]  # lower = more mean-reverting = better
    raw_reversion = trades["half_life_at_entry"]  # lower = faster = better

    vol_lookup = vol_profile.set_index("symbol")["vol_percentile"]
    vp_a = trades["symbol_a"].map(vol_lookup)
    vp_b = trades["symbol_b"].map(vol_lookup)
    avg_vol_percentile = (vp_a + vp_b) / 2.0
    raw_vol_distance = (avg_vol_percentile - 0.5).abs()  # higher distance from "normal" = worse

    if "net_dollar_beta_exposure" in trades.columns and "notional_at_entry" in trades.columns:
        raw_beta_mismatch = (trades["net_dollar_beta_exposure"] / trades["notional_at_entry"]).abs()
    else:
        raw_beta_mismatch = pd.Series(np.nan, index=trades.index)

    scale = category_max / 100.0
    trades["score_confirmation"] = percentile_score(raw_confirmation) * scale
    trades["score_reversion_speed"] = percentile_score(raw_reversion) * scale
    trades["score_vol_regime"] = percentile_score(raw_vol_distance) * scale
    trades["score_beta_neutrality"] = percentile_score(raw_beta_mismatch) * scale

    score_cols = ["score_confirmation", "score_reversion_speed", "score_vol_regime", "score_beta_neutrality"]
    trades["n_categories_scored"] = trades[score_cols].notna().sum(axis=1)
    # Rescale to a full 0-100 based on however many categories WERE computable, so a trade
    # missing 1 category isn't unfairly capped at 75 -- its 3 real scores are averaged up to
    # what they'd be worth out of 100, not penalized for a missing signal.
    trades["confidence_score"] = np.where(
        trades["n_categories_scored"] > 0,
        trades[score_cols].sum(axis=1, skipna=True) / trades["n_categories_scored"].replace(0, np.nan) * 4,
        np.nan,
    )
    return trades


def evaluate_filter_sweep(trades: pd.DataFrame, thresholds: list = FILTER_THRESHOLDS) -> pd.DataFrame:
    """Sweeps a confidence-score filter threshold and reports portfolio Sharpe/Sortino/Calmar
    on the SURVIVING trades at each -- the real validation of whether the score predicts
    anything, not just an assertion that it does."""
    rows = []
    for thr in thresholds:
        subset = trades[trades["confidence_score"] >= thr] if thr > 0 else trades
        daily_pnl = daily_pnl_from_trades(subset)
        rows.append({
            "threshold": thr, "n_trades": len(subset),
            "sharpe": sharpe_from_daily_pnl(daily_pnl), "sortino": sortino_from_daily_pnl(daily_pnl),
            "calmar": calmar_from_daily_pnl(daily_pnl, STARTING_CAPITAL),
            "total_pnl": float(subset["pnl_net"].sum()) if len(subset) else np.nan,
        })
    return pd.DataFrame(rows)


def apply_score_weighted_sizing(trades: pd.DataFrame) -> pd.Series:
    """Position-allocation view: scales each trade's pnl_net by confidence_score/100, a linear
    size-scaling APPROXIMATION (not a full backtest-engine re-run at scaled size, disclosed as
    a simplification) -- trades the score likes keep full size, trades it doesn't get shrunk
    proportionally rather than excluded outright (the filter sweep above is the hard-cutoff
    view; this is the continuous-allocation view of the same score)."""
    return trades["pnl_net"] * (trades["confidence_score"].fillna(0) / 100.0)


def main():
    _setup_logging()
    log.info("=== confidence_score_allocation.py: Phase 4 -- combining Phase 1-3 signals into "
              "a per-trade confidence score, validated via filter-threshold and sizing sweeps ===")

    trades_path = "output/backtest/baseline_trades_layer1.parquet"
    vol_path = "output/research/asset_volatility_profile.parquet"
    beta_path = "output/research/beta_weighted_portfolio.parquet"
    if not (os.path.exists(trades_path) and os.path.exists(vol_path)):
        log.warning("Missing required Phase 1/3 output -- run those scripts first.")
        return

    trades = pd.read_parquet(trades_path)
    trades = trades[trades["hedge_method"] == "ols"].copy()
    trades["entry_time"] = pd.to_datetime(trades["entry_time"])
    trades["exit_time"] = pd.to_datetime(trades["exit_time"])

    # Real methodology bug found live (2026-09-08): the pre-computed asset_volatility_
    # profile.parquet (Finding #54) was built over confirmed_pairs_list()'s CURRENT confirmed-
    # pair universe, but baseline_trades_layer1.parquet's actual traded symbols turned out to be
    # almost entirely DISJOINT from that set (23/24 traded symbols were simply absent from the
    # file, not "missing data" -- never even looked up) -- likely a legacy trades file from an
    # earlier confirmed-pair set. Computing the volatility profile ON DEMAND here for exactly
    # the symbols this run actually needs, reusing research/asset_volatility_profile.py's own
    # compute_volatility_profile() function (not duplicated), sidesteps the universe-mismatch
    # entirely rather than depending on a static file that may not cover the trades in question.
    from research.asset_volatility_profile import compute_volatility_profile

    # Phase 3's beta exposure was computed per-trade internally but not persisted per-trade
    # (only the daily aggregate was saved) -- recomputed here directly via the same functions,
    # reused rather than duplicated, so this script and Phase 3 never drift on the same math.
    from options import load_price_series
    from research.beta_weighted_portfolio import (
        load_spy_returns, rolling_beta, value_at_date, trade_net_dollar_beta_exposure,
    )
    spy_returns = load_spy_returns()
    beta_cache, price_cache = {}, {}

    def get_beta_series(sym):
        if sym not in beta_cache:
            close = load_price_series(sym)
            price_cache[sym] = close
            beta_cache[sym] = None if close is None else rolling_beta(np.log(close).diff(), spy_returns)
        return beta_cache[sym]

    exposures, notionals = [], []
    for _, t in trades.iterrows():
        beta_a, beta_b = get_beta_series(t["symbol_a"]), get_beta_series(t["symbol_b"])
        price_a, price_b = price_cache.get(t["symbol_a"]), price_cache.get(t["symbol_b"])
        if beta_a is None or beta_b is None or price_a is None or price_b is None:
            exposures.append(np.nan)
            notionals.append(np.nan)
            continue
        p_a, p_b = value_at_date(price_a, t["entry_time"]), value_at_date(price_b, t["entry_time"])
        exposures.append(trade_net_dollar_beta_exposure(
            t["symbol_a"], t["symbol_b"], t["entry_time"], p_a, p_b,
            t["n_shares_a"], t["n_shares_b"], t["side"], beta_a, beta_b))
        notionals.append(t["n_shares_a"] * p_a + t["n_shares_b"] * p_b if np.isfinite(p_a) and np.isfinite(p_b) else np.nan)
    trades["net_dollar_beta_exposure"] = exposures
    trades["notional_at_entry"] = notionals

    vol_profile_rows = []
    for sym, close in price_cache.items():
        profile = compute_volatility_profile(close)
        profile["symbol"] = sym
        vol_profile_rows.append(profile)
    vol_profile = pd.DataFrame(vol_profile_rows)
    log.info(f"On-demand volatility profile computed for {len(vol_profile)} symbols actually "
             f"used by these trades ({vol_profile['vol_percentile'].notna().sum()} with a valid "
             f"vol_percentile).")

    trades = compute_confidence_scores(trades, vol_profile)
    log.info(f"{len(trades)} trades scored; mean confidence_score="
             f"{trades['confidence_score'].mean():.1f}, "
             f"median n_categories_scored={trades['n_categories_scored'].median():.0f}/4")

    sweep = evaluate_filter_sweep(trades)
    log.info("Filter-threshold sweep (portfolio metrics on SURVIVING trades at each score cutoff):")
    for _, r in sweep.iterrows():
        log.info(f"  score>={r['threshold']:>3}: n_trades={r['n_trades']:>4}  "
                  f"Sharpe={r['sharpe']:.4f}  Sortino={r['sortino']:.4f}  Calmar={r['calmar']:.4f}  "
                  f"total_pnl=${r['total_pnl']:,.2f}")

    weighted_pnl = apply_score_weighted_sizing(trades)
    log.info(f"Score-weighted continuous sizing: total_pnl=${weighted_pnl.sum():,.2f} "
             f"(vs. full-size total_pnl=${trades['pnl_net'].sum():,.2f})")

    os.makedirs("output/research", exist_ok=True)
    trades.to_parquet("output/research/confidence_score_allocation_trades.parquet")
    sweep.to_parquet("output/research/confidence_score_allocation_sweep.parquet")
    log.info("Saved -> output/research/confidence_score_allocation_{trades,sweep}.parquet")
    log.info("confidence_score_allocation.py complete")


if __name__ == "__main__":
    main()
