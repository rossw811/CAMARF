"""
research/fill_timing_sensitivity.py — comparison/diagnostic method, NOT part
of the production pipeline.

Answers a gap flagged by tonight's data-hygiene/bias literature review (see
Development.md Session 27 addendum): CAMARF's backtest.py currently assumes
SAME-BAR execution — the entry/exit decision at bar i (z_arr[i]) fills at
that SAME bar's spread (spread_arr[i]). In live trading you only KNOW a
bar's close-derived z-score after that bar closes, so the earliest real fill
is the NEXT bar, not the same one — the "Fill-timing bias" entry in the
"Taxonomy of Backtest Lies" writeup this review turned up names this
explicitly as a distinct bias from transaction-cost/slippage modeling
(which CAMARF already has via COMMISSION_PER_SHARE/SLIPPAGE_BPS).

Method: reuses `backtest.BacktestEngine.run()` UNCHANGED — no new event-loop
logic to duplicate/risk diverging from production. Builds a "lagged" copy of
each pair's spread_series where z_rolling (the entry/exit DECISION series)
is shifted forward by one bar relative to spread/exit values (the FILL
series): decision at logical bar i uses z_rolling from bar i-1, but still
fills at bar i's spread — i.e. "you only know last bar's signal, but you can
only execute at this bar's price," the correct causal ordering. Everything
else (half_life_rolling, gap flags) shifts along with z_rolling since they're
part of the same "what you knew as of last bar" decision context.

Runs BOTH the current (same-bar) and lagged (next-bar) variants through the
identical engine/hedge_scalar/pair_row for every confirmed 1h pair (OLS hedge
method only, matching this session's other comparison arms' convention of
using the primary/baseline method), reports Sharpe/PnL/trade-count deltas.

Read-only. Never fetches, never modifies production spread_series files or
backtest.py itself.

Usage:
    python research/fill_timing_sensitivity.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest import BacktestEngine, RegimeConditioner, MLConditioner, compute_metrics
from config import Config

_TF_DIR, _TF_LABEL = "1hr", "1h"


def build_lagged_spread_df(spread_df: pd.DataFrame) -> pd.DataFrame:
    """Shifts the DECISION columns (z_rolling, z_expanding, half_life_rolling,
    gap flags) forward by one bar relative to the FILL columns (spread stays
    in place) — bar i's decision now reflects what was knowable as of bar
    i-1, while the fill price is still bar i's own spread, the earliest a
    real order could actually execute."""
    lagged = spread_df.copy()
    decision_cols = [
        c for c in ["z_rolling", "z_expanding", "half_life_rolling", "gap_flag_a", "gap_flag_b"]
        if c in lagged.columns
    ]
    lagged[decision_cols] = lagged[decision_cols].shift(1)
    return lagged


def main():
    pairs_path = f"output/results/{_TF_DIR}/pairs.parquet"
    if not os.path.exists(pairs_path):
        print(f"No pairs.parquet at {pairs_path} — run analysis.py first.")
        return
    pairs = pd.read_parquet(pairs_path)
    if "tf_label" not in pairs.columns:
        pairs["tf_label"] = _TF_LABEL

    engine = BacktestEngine(
        cfg=Config.BACKTEST,
        regime_cond=RegimeConditioner(enabled=False),
        ml_cond=MLConditioner(enabled=False),
    )

    rows = []
    for _, row in pairs.iterrows():
        sym_a, sym_b = row["symbol_a"], row["symbol_b"]
        series_path = f"output/results/{_TF_DIR}/spread_series_{sym_a}_{sym_b}.parquet"
        if not os.path.exists(series_path):
            continue
        spread_df = pd.read_parquet(series_path)

        trades_same_bar = engine.run(row, spread_df, "ols")
        trades_lagged = engine.run(row, build_lagged_spread_df(spread_df), "ols")

        m_same = compute_metrics(trades_same_bar, _TF_LABEL, sym_a, sym_b, "ols") if trades_same_bar else {}
        m_lag = compute_metrics(trades_lagged, _TF_LABEL, sym_a, sym_b, "ols") if trades_lagged else {}

        rows.append({
            "pair": f"{sym_a}/{sym_b}",
            "n_trades_same_bar": m_same.get("n_trades", 0),
            "n_trades_lagged": m_lag.get("n_trades", 0),
            "sharpe_same_bar": m_same.get("sharpe", np.nan),
            "sharpe_lagged": m_lag.get("sharpe", np.nan),
            "pnl_same_bar": m_same.get("total_pnl", np.nan),
            "pnl_lagged": m_lag.get("total_pnl", np.nan),
        })
        print(f"{sym_a}/{sym_b}: same-bar n={m_same.get('n_trades',0)} "
              f"sharpe={m_same.get('sharpe', float('nan')):.2f} pnl={m_same.get('total_pnl', float('nan')):.2f}  |  "
              f"lagged n={m_lag.get('n_trades',0)} "
              f"sharpe={m_lag.get('sharpe', float('nan')):.2f} pnl={m_lag.get('total_pnl', float('nan')):.2f}")

    if not rows:
        print("No confirmed pairs with spread_series found.")
        return

    df = pd.DataFrame(rows)
    valid = df.dropna(subset=["sharpe_same_bar", "sharpe_lagged"])
    print(f"\n=== Summary ({len(valid)}/{len(df)} pairs with valid Sharpe both ways) ===")
    print(f"Mean Sharpe same-bar: {valid['sharpe_same_bar'].mean():.3f}")
    print(f"Mean Sharpe lagged:   {valid['sharpe_lagged'].mean():.3f}")
    print(f"Total PnL same-bar:   {df['pnl_same_bar'].sum():.2f}")
    print(f"Total PnL lagged:     {df['pnl_lagged'].sum():.2f}")
    pct_degradation = (
        100 * (1 - valid['sharpe_lagged'].mean() / valid['sharpe_same_bar'].mean())
        if valid['sharpe_same_bar'].mean() != 0 else float("nan")
    )
    print(f"Sharpe degradation from a realistic 1-bar fill lag: {pct_degradation:.1f}%")

    os.makedirs("output/research", exist_ok=True)
    df.to_parquet("output/research/fill_timing_sensitivity.parquet")
    print("\nWrote output/research/fill_timing_sensitivity.parquet")


if __name__ == "__main__":
    main()
