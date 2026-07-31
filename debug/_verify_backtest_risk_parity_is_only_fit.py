"""
Verification for the 2026-07-20 Grand Sweep fix to backtest.py (BUG-D76):
risk-parity/HRP/pnl-cap sizing weights previously always fit on the
full-series trades_layer1.parquet, which necessarily overlaps whatever
window a --holdout run evaluates as OOS -- real in-sample circularity
directly touching the "recommended production" risk-parity Sharpe claim.

Fix: BacktestEngine.run() gained an is_only parameter (the exact
chronological complement of holdout_only, same cutoff computation), and
compute_risk_parity_weights()/compute_hrp_weights()/compute_pnl_cap_thresholds()
now accept an in-memory trades_df so a genuinely non-overlapping IS-only
trades set (generated via a preliminary fitting pass) can be used instead of
reading the full-series file.

Two independent checks:
1. BacktestEngine.run(is_only=True) and run(holdout_only=True) on the SAME
   synthetic spread_df produce trade sets whose bars don't overlap -- the
   exact chronological complement, not an approximation.
2. compute_risk_parity_weights()/compute_pnl_cap_thresholds() correctly use
   an explicitly-provided trades_df instead of reading from disk, and give a
   DIFFERENT answer than a full-series trades_df with a different pair-level
   P&L variance profile would -- proving the fix's core mechanism (which
   trades feed weight-fitting) actually matters, not a no-op.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest import (
    BacktestEngine, RegimeConditioner, MLConditioner,
    compute_risk_parity_weights, compute_pnl_cap_thresholds,
)
from config import Config


def _make_spread_df(n=500, seed=0):
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.RandomState(seed)
    z = 3.0 * np.sin(np.linspace(0, 20 * np.pi, n)) + rng.normal(0, 0.15, n)
    spread = np.cumsum(rng.normal(0, 0.1, n))
    return pd.DataFrame({
        "z_rolling": z,
        "spread": spread,
        "half_life_rolling": np.full(n, 15.0),
        "gap_flag_a": np.zeros(n, dtype=int),
        "gap_flag_b": np.zeros(n, dtype=int),
        "hedge_ratio_ols_t": np.full(n, 1.5),
        "hedge_ratio_kalman_t": np.full(n, 1.5),
    }, index=idx)


def main() -> None:
    failures = []

    # --- Check 1: is_only / holdout_only are genuine chronological complements ---
    pair_row = pd.Series({
        "symbol_a": "A", "symbol_b": "B", "tf_label": "1h",
        "hedge_ratio_ols": 1.5, "hedge_ratio_kalman_mean": 1.5, "hurst_rs": 0.3,
    })
    spread_df = _make_spread_df()
    engine = BacktestEngine(
        cfg=Config.BACKTEST, regime_cond=RegimeConditioner(enabled=False),
        ml_cond=MLConditioner(enabled=False), layer2_enabled=False,
    )

    is_only_trades = engine.run(pair_row, spread_df, "ols", is_only=True)
    holdout_trades = engine.run(pair_row, spread_df, "ols", holdout_only=True)

    if not is_only_trades or not holdout_trades:
        failures.append(
            f"expected trades in both windows on the oscillating fixture, "
            f"got is_only={len(is_only_trades)} holdout={len(holdout_trades)}"
        )
    else:
        is_only_max_exit = max(t.exit_time for t in is_only_trades if t.exit_time is not None)
        holdout_min_entry = min(t.entry_time for t in holdout_trades)
        if is_only_max_exit >= holdout_min_entry:
            failures.append(
                f"is_only trades should all complete before holdout trades begin: "
                f"is_only max exit={is_only_max_exit}, holdout min entry={holdout_min_entry}"
            )

    # Mutually exclusive guard
    try:
        engine.run(pair_row, spread_df, "ols", holdout_only=True, is_only=True)
        failures.append("expected ValueError when both holdout_only and is_only are True")
    except ValueError:
        pass

    # --- Check 2: weight functions use the provided trades_df, and it matters ---
    # "IS-only" profile: A is quiet (low std), B is volatile (high std) -- risk
    # parity should upsize A and downsize B.
    is_only_df = pd.DataFrame({
        "symbol_a": ["A"] * 20 + ["B"] * 20,
        "symbol_b": ["X"] * 20 + ["Y"] * 20,
        "pnl_net": list(np.random.RandomState(1).normal(0, 10, 20)) +
                   list(np.random.RandomState(2).normal(0, 100, 20)),
    })
    # "Full-series" profile (hypothetically overlapping OOS): A and B swap
    # volatility characters entirely -- if the function ignores trades_df and
    # silently falls back to some other source, this swap wouldn't show up.
    full_series_df = pd.DataFrame({
        "symbol_a": ["A"] * 20 + ["B"] * 20,
        "symbol_b": ["X"] * 20 + ["Y"] * 20,
        "pnl_net": list(np.random.RandomState(2).normal(0, 100, 20)) +
                   list(np.random.RandomState(1).normal(0, 10, 20)),
    })

    w_is_only = compute_risk_parity_weights(trades_df=is_only_df)
    w_full = compute_risk_parity_weights(trades_df=full_series_df)

    if w_is_only.get("A/X", 0) <= w_is_only.get("B/Y", 0):
        failures.append(
            f"IS-only profile: expected A/X (quiet) upsized vs B/Y (volatile), "
            f"got {w_is_only}"
        )
    if w_full.get("A/X", 0) >= w_full.get("B/Y", 0):
        failures.append(
            f"Full-series profile (volatility swapped): expected A/X (now volatile) "
            f"downsized vs B/Y (now quiet), got {w_full}"
        )
    if np.isclose(w_is_only.get("A/X", 0), w_full.get("A/X", 0), atol=0.5):
        failures.append(
            "weights barely differ between the two trades_df profiles -- "
            "function may not actually be using the provided trades_df"
        )

    # P&L cap: same in-memory-override mechanism, quick smoke check. Needs a
    # clearly PROFITABLE (positive-total) fixture -- compute_pnl_cap_thresholds
    # only considers pairs with positive summed pnl_net, and the zero-mean
    # is_only_df above isn't reliably profitable in total by chance.
    profitable_df = pd.DataFrame({
        "symbol_a": ["A"] * 10, "symbol_b": ["X"] * 10,
        "pnl_net": np.random.RandomState(3).normal(50, 10, 10),  # clearly positive mean
    })
    cap_is_only = compute_pnl_cap_thresholds(trades_df=profitable_df)
    if not cap_is_only:
        failures.append("compute_pnl_cap_thresholds(trades_df=...) returned empty unexpectedly")

    # Empty trades_df must not crash (BUG found and fixed during this same
    # session's real-data run: --tf 1h currently has 0 confirmed pairs).
    empty_df = pd.DataFrame()
    if compute_risk_parity_weights(trades_df=empty_df) != {}:
        failures.append("empty trades_df should return {} (flat sizing), not crash or non-empty result")
    if compute_pnl_cap_thresholds(trades_df=empty_df) != {}:
        failures.append("empty trades_df should return {} for pnl_cap too")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("backtest.py risk-parity IS-only fitting fix verified.")
        print(f"  is_only trades: {len(is_only_trades)}, holdout trades: {len(holdout_trades)} (non-overlapping)")
        print(f"  IS-only profile weights: A/X={w_is_only.get('A/X'):.3f} B/Y={w_is_only.get('B/Y'):.3f}")
        print(f"  Full-series (swapped) weights: A/X={w_full.get('A/X'):.3f} B/Y={w_full.get('B/Y'):.3f}")
        print("  Empty trades_df: correctly returns {} without crashing.")


if __name__ == "__main__":
    main()
