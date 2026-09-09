"""
Analyst consensus price-target overlay -- pairs-relative design, Ross
approved 2026-09-08 over the literature's standalone single-name framing
(Brav & Lehavy 2003, Da & Schaumburg 2011), specifically to keep this
inside CAMARF's existing co-movement/pairs architecture rather than
introducing a new single-asset trade unit.

Signal: for each REAL trade already in this project's own trades table
(baseline_trades_layer1.parquet), compute each leg's own analyst-implied
return to target ((mean_price_target - price) / price) as of entry_time
(causal, `value_at_date`-style lookup -- no lookahead), then the
RELATIVE divergence between legs:

    relative_divergence = implied_return_a - implied_return_b

backtest.py's own convention (Trade.side = "long" means long leg A / short
leg B, betting the spread RISES; "short" is the reverse -- see
research/beta_weighted_portfolio.py's trade_net_dollar_beta_exposure
docstring for the same convention already documented there) means a
trade AGREES with the analyst consensus when:
    side == "long"  and relative_divergence > 0  (analysts also expect A to
                                                    outperform B)
    side == "short" and relative_divergence < 0  (analysts also expect B to
                                                    outperform A)

This is a comparison-arm DIAGNOSTIC, not a new backtest engine: it reuses
this project's own already-generated trades and asks whether analyst
consensus agreement/disagreement predicts trade P&L -- same honest-
negative-result-shaped test as confidence_score_allocation.py.
"""
import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "research"))

import options
from beta_weighted_portfolio import value_at_date

_TRADES_PATH = os.path.join(_ROOT, "output", "backtest", "baseline_trades_layer1.parquet")
_PERMNO_MAP_PATH = os.path.join(_ROOT, "output", "cache", "wrds", "symbol_permno_map.parquet")
_IBES_PATH = os.path.join(_ROOT, "output", "cache", "wrds", "ibes_price_targets_camarf_universe.parquet")
_OUT_PATH = os.path.join(_ROOT, "output", "research", "price_target_pairs_overlay.parquet")

_MAX_TARGET_STALENESS_DAYS = 120  # a target older than ~1 quarter is treated as stale, not
    # extrapolated forward indefinitely -- analysts revise targets roughly quarterly around
    # earnings, so a gap much longer than that means "no real current view," not "unchanged view."


def load_permno_map() -> dict:
    df = pd.read_parquet(_PERMNO_MAP_PATH)
    return dict(zip(df["symbol"], df["permno"]))


def build_target_series(permno: int, ibes_df: pd.DataFrame) -> pd.Series:
    """PIT-safe series: mean_price_target indexed by statpers (report
    date), one value per report date, ready for value_at_date's causal
    pad lookup."""
    sub = ibes_df[ibes_df["permno"] == permno].sort_values("statpers")
    if sub.empty:
        return pd.Series(dtype=float)
    return pd.Series(sub["mean_price_target"].values,
                      index=pd.to_datetime(sub["statpers"]))


def implied_return_to_target(symbol: str, entry_time, permno_map: dict, ibes_df: pd.DataFrame,
                              price_cache: dict) -> float:
    permno = permno_map.get(symbol)
    if permno is None:
        return float("nan")

    if symbol not in price_cache:
        price_cache[symbol] = options.load_price_series(symbol)
    price_series = price_cache[symbol]
    if price_series is None or len(price_series) == 0:
        return float("nan")
    price = value_at_date(price_series, entry_time)
    if not np.isfinite(price) or price <= 0:
        return float("nan")

    target_series = build_target_series(permno, ibes_df)
    if target_series.empty:
        return float("nan")
    # Causal "at or before" lookup, then a staleness gate -- value_at_date
    # alone would silently extrapolate a target from years ago forward
    # indefinitely if no later report exists before entry_time.
    idx = target_series.index.get_indexer([pd.Timestamp(entry_time)], method="pad")[0]
    if idx < 0:
        return float("nan")
    target_date = target_series.index[idx]
    staleness_days = (pd.Timestamp(entry_time) - target_date).days
    if staleness_days > _MAX_TARGET_STALENESS_DAYS:
        return float("nan")
    target = float(target_series.iloc[idx])
    if not np.isfinite(target) or target <= 0:
        return float("nan")

    return (target - price) / price


def compute_overlay(trades: pd.DataFrame, permno_map: dict, ibes_df: pd.DataFrame) -> pd.DataFrame:
    price_cache: dict = {}
    rows = []
    for _, t in trades.iterrows():
        ir_a = implied_return_to_target(t["symbol_a"], t["entry_time"], permno_map, ibes_df, price_cache)
        ir_b = implied_return_to_target(t["symbol_b"], t["entry_time"], permno_map, ibes_df, price_cache)
        rel_div = ir_a - ir_b if (np.isfinite(ir_a) and np.isfinite(ir_b)) else float("nan")
        agrees = None
        if np.isfinite(rel_div):
            if t["side"] == "long":
                agrees = rel_div > 0
            elif t["side"] == "short":
                agrees = rel_div < 0
        rows.append({
            "symbol_a": t["symbol_a"], "symbol_b": t["symbol_b"], "entry_time": t["entry_time"],
            "side": t["side"], "pnl_net": t["pnl_net"],
            "implied_return_a": ir_a, "implied_return_b": ir_b,
            "relative_divergence": rel_div, "agrees_with_consensus": agrees,
        })
    return pd.DataFrame(rows)


def main():
    if not (os.path.exists(_TRADES_PATH) and os.path.exists(_PERMNO_MAP_PATH) and os.path.exists(_IBES_PATH)):
        print(f"ERROR: missing input(s). trades={os.path.exists(_TRADES_PATH)}, "
              f"permno_map={os.path.exists(_PERMNO_MAP_PATH)}, ibes={os.path.exists(_IBES_PATH)}")
        return

    trades = pd.read_parquet(_TRADES_PATH)
    permno_map = load_permno_map()
    ibes_df = pd.read_parquet(_IBES_PATH)

    print(f"Loaded {len(trades)} real trades, {len(permno_map)} symbol->permno mappings, "
          f"{len(ibes_df)} IBES price-target rows.")

    overlay = compute_overlay(trades, permno_map, ibes_df)
    n_scored = overlay["agrees_with_consensus"].notna().sum()
    print(f"Scored {n_scored}/{len(overlay)} trades with a usable analyst-consensus signal "
          f"(rest: missing permno, no price data, or no target within "
          f"{_MAX_TARGET_STALENESS_DAYS} days of entry).")

    if n_scored > 0:
        # agrees_with_consensus is object-dtype (True/False/None), so `~`
        # does Python bitwise NOT (~True == -2), not boolean negation --
        # cast to a real bool dtype first (caught live: `~` on the object
        # column raised a KeyError from selecting columns [-2, -1, ...]
        # instead of negating the mask).
        scored = overlay[overlay["agrees_with_consensus"].notna()].copy()
        scored["agrees_with_consensus"] = scored["agrees_with_consensus"].astype(bool)
        agree = scored[scored["agrees_with_consensus"]]
        disagree = scored[~scored["agrees_with_consensus"]]
        print(f"\nAgrees with consensus:    n={len(agree)}, mean P&L=${agree['pnl_net'].mean():.2f}, "
              f"win rate={(agree['pnl_net'] > 0).mean():.2%}")
        print(f"Disagrees with consensus: n={len(disagree)}, mean P&L=${disagree['pnl_net'].mean():.2f}, "
              f"win rate={(disagree['pnl_net'] > 0).mean():.2%}")
        if len(agree) > 1 and len(disagree) > 1:
            from scipy import stats
            t_stat, p_val = stats.ttest_ind(agree["pnl_net"], disagree["pnl_net"], equal_var=False)
            print(f"Welch's t-test (agree vs disagree P&L): t={t_stat:.4f}, p={p_val:.4f}")

    os.makedirs(os.path.dirname(_OUT_PATH), exist_ok=True)
    overlay.to_parquet(_OUT_PATH)
    print(f"\nSaved to {_OUT_PATH}")


if __name__ == "__main__":
    main()
