"""
fresh_holdout_compare.py — compares two candidate mechanisms for a genuinely fresh (never
re-examined) holdout, per Ross's direction (2026-07-12): "For the holdout i think we should
compare both and see what happens."

Motivation: `deflated_sharpe.py` flags 29 evaluations against the SAME OOS holdout window across
this project's history (Garden-of-Forking-Paths risk, Gelman & Loken 2013) — every STORM/
comparison-arm decision has, directly or indirectly, been informed by repeated looks at the same
trailing-20% time slice. Two different, non-exclusive ways to get a genuinely untouched slice:

1. TIME-BASED: the underlying data keeps growing every session (new bars appended), so each
   historical run's "trailing 20% holdout" was a DIFFERENT, shorter absolute date range than
   today's. The most RECENT portion of today's holdout genuinely didn't exist when earlier
   sessions' evaluations ran — reserve that tail as the fresh slice, report metrics on it
   separately from the earlier (repeatedly-examined) portion.

2. PAIR-BASED: reserve a SUBSET of confirmed pairs, chosen deterministically (not tuned), that
   get walled off from any further comparison-arm testing going forward — a cross-validation-
   style held-out-symbols split, orthogonal to the time-based one (a pair-holdout trade can still
   fall in the time-already-examined period, and vice versa).

Neither mechanism is picked as "the" answer here -- both are computed and reported so Ross can
see what each shows before deciding whether to adopt one, both, or neither going forward.

Usage:
    python fresh_holdout_compare.py
"""
import logging
import os

import numpy as np
import pandas as pd

log = logging.getLogger("fresh_holdout_compare")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")

_TIME_FRESH_FRACTION = 0.25   # most recent 25% of the holdout window's date range
_PAIR_RESERVE_FRACTION = 0.20  # ~20% of confirmed pairs reserved, deterministically


def _pooled_sharpe(df: pd.DataFrame) -> tuple:
    """Portfolio Sharpe from pooled daily P&L, matching aggregate_portfolio()'s convention.
    Returns (sharpe, n_trades, n_days)."""
    if len(df) == 0:
        return float("nan"), 0, 0
    d = df.copy()
    d["exit_date"] = pd.to_datetime(d["exit_time"]).dt.date
    daily = d.groupby("exit_date")["pnl_net"].sum()
    if len(daily) < 5 or daily.std() == 0:
        return float("nan"), len(df), len(daily)
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252))
    return sharpe, len(df), len(daily)


def time_based_split(holdout: pd.DataFrame, fresh_fraction: float = _TIME_FRESH_FRACTION) -> dict:
    start = holdout["entry_time"].min()
    end = holdout["entry_time"].max()
    span = end - start
    cutoff = end - span * fresh_fraction

    already_examined = holdout[holdout["entry_time"] < cutoff]
    fresh = holdout[holdout["entry_time"] >= cutoff]

    sharpe_examined, n_examined, days_examined = _pooled_sharpe(already_examined)
    sharpe_fresh, n_fresh, days_fresh = _pooled_sharpe(fresh)

    return {
        "cutoff": cutoff, "start": start, "end": end,
        "already_examined": {"sharpe": sharpe_examined, "n_trades": n_examined, "n_days": days_examined},
        "fresh": {"sharpe": sharpe_fresh, "n_trades": n_fresh, "n_days": days_fresh},
    }


def pair_based_split(holdout: pd.DataFrame, reserve_fraction: float = _PAIR_RESERVE_FRACTION) -> dict:
    all_pairs = sorted(set(zip(holdout["symbol_a"], holdout["symbol_b"])))
    n_reserve = max(1, round(len(all_pairs) * reserve_fraction))
    # Deterministic, not tuned: every Nth pair by sorted (symbol_a, symbol_b) order.
    step = max(1, len(all_pairs) // n_reserve)
    reserved_pairs = set(all_pairs[::step][:n_reserve])
    dev_pairs = set(all_pairs) - reserved_pairs

    reserved_trades = holdout[holdout.apply(lambda r: (r["symbol_a"], r["symbol_b"]) in reserved_pairs, axis=1)]
    dev_trades = holdout[holdout.apply(lambda r: (r["symbol_a"], r["symbol_b"]) in dev_pairs, axis=1)]

    sharpe_dev, n_dev, days_dev = _pooled_sharpe(dev_trades)
    sharpe_reserved, n_reserved, days_reserved = _pooled_sharpe(reserved_trades)

    return {
        "reserved_pairs": sorted(reserved_pairs), "dev_pairs": sorted(dev_pairs),
        "dev": {"sharpe": sharpe_dev, "n_trades": n_dev, "n_days": days_dev},
        "reserved": {"sharpe": sharpe_reserved, "n_trades": n_reserved, "n_days": days_reserved},
    }


def main():
    holdout = pd.read_parquet("output/backtest/trades_layer1_holdout.parquet")
    holdout["entry_time"] = pd.to_datetime(holdout["entry_time"])
    holdout["exit_time"] = pd.to_datetime(holdout["exit_time"])
    log.info("Loaded %d holdout trades, %s to %s", len(holdout),
              holdout["entry_time"].min(), holdout["entry_time"].max())

    log.info("=" * 70)
    log.info("MECHANISM 1: TIME-BASED fresh slice (most recent %.0f%% of holdout window)",
              _TIME_FRESH_FRACTION * 100)
    log.info("=" * 70)
    t = time_based_split(holdout)
    log.info("  Cutoff: %s (window %s to %s)", t["cutoff"], t["start"], t["end"])
    log.info("  Already-examined portion: Sharpe=%.4f  n_trades=%d  n_days=%d",
              t["already_examined"]["sharpe"], t["already_examined"]["n_trades"], t["already_examined"]["n_days"])
    log.info("  FRESH portion:            Sharpe=%.4f  n_trades=%d  n_days=%d",
              t["fresh"]["sharpe"], t["fresh"]["n_trades"], t["fresh"]["n_days"])

    log.info("=" * 70)
    log.info("MECHANISM 2: PAIR-BASED reserve (~%.0f%% of confirmed pairs, deterministic selection)",
              _PAIR_RESERVE_FRACTION * 100)
    log.info("=" * 70)
    p = pair_based_split(holdout)
    log.info("  Reserved pairs (%d): %s", len(p["reserved_pairs"]), p["reserved_pairs"])
    log.info("  Dev pairs (%d): %s", len(p["dev_pairs"]), p["dev_pairs"])
    log.info("  Dev-pairs portion:      Sharpe=%.4f  n_trades=%d  n_days=%d",
              p["dev"]["sharpe"], p["dev"]["n_trades"], p["dev"]["n_days"])
    log.info("  RESERVED-pairs portion: Sharpe=%.4f  n_trades=%d  n_days=%d",
              p["reserved"]["sharpe"], p["reserved"]["n_trades"], p["reserved"]["n_days"])


if __name__ == "__main__":
    main()
