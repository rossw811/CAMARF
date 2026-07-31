"""
research/network_momentum.py — comparison/diagnostic method, NOT part of
the production pipeline.

Pu, Roberts, Dong & Zohren (2023), "Network Momentum across Asset Classes,"
arXiv:2308.11294 — a graph-learning model capturing MOMENTUM SPILLOVER
across assets (does asset A's PAST return predict asset B's FUTURE return,
through time), a genuinely different signal family from CAMARF's existing
methodology, which is entirely about CONTEMPORANEOUS co-movement
(cointegration, correlation, eigenportfolio structure — all same-time-t
relationships, never lagged cross-asset prediction).

Does NOT re-implement the paper's actual graph neural network (a
substantial undertaking needing far more data/training infrastructure than
this environment has for a research comparison arm) — implements the core,
testable claim directly: is there real LEAD-LAG momentum spillover in
CAMARF's own confirmed-pair universe, beyond what a naive single-asset
momentum baseline already captures? Method:

  1. Universe: reuses absorption_ratio.py's confirmed_universe_symbols() +
     _load_daily_log_returns() directly (same universe, same data source,
     not reimplemented).
  2. Lead-lag network: for every ordered pair (i, j), i != j, compute the
     lag-1 cross-correlation corr(return_i[t], return_j[t+1]) over a
     trailing calibration window — this IS the "network" (edge weight =
     spillover strength), a simple, transparent proxy for what the paper's
     GNN learns implicitly.
  3. Network-momentum signal for asset j at t+1: weighted average of every
     OTHER asset's return at t, weighted by that pair's own lag-1
     cross-correlation (only positive-correlation edges contribute,
     negative ones would predict a reversal, a separate signal not tested
     here).
  4. Baseline for comparison: naive single-asset momentum (does asset j's
     OWN past return predict its own future return) — the incremental
     value of NETWORK (cross-asset) momentum over single-asset momentum is
     the actual, specific claim worth testing, not just "is there momentum
     at all."
  5. Both signals evaluated the same way: correlation between the signal
     and the realized forward return (not a full backtest — a real
     trading-cost-aware backtest would be the natural next step if this
     shows genuine signal, not attempted here).

Read-only. Never fetches, never modifies analysis.py's contemporaneous
cointegration/correlation pipeline.

Usage:
    python research/network_momentum.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from absorption_ratio import confirmed_universe_symbols, _load_daily_log_returns

_CALIBRATION_WINDOW = 120


def lead_lag_network(returns_df: pd.DataFrame, window: int = _CALIBRATION_WINDOW) -> np.ndarray:
    """Returns an (N, N) matrix W where W[i, j] = corr(return_i[t], return_j[t+1])
    over the full available history (a stable, in-sample network structure —
    used only to WEIGHT the cross-asset signal, evaluated out of the window
    it's estimated from is not attempted here; this is a signal-existence
    test, not a walk-forward backtest).

    NOTE (Tier 2.10 fix, Grand Sweep 2026-07-20): previously fillna(0.0)'d
    the whole returns panel before computing any correlation, fabricating
    a "0% return" for genuinely missing days (thin/newer symbols with less
    history than others in the panel). A real non-zero return elsewhere in
    the panel paired against a fabricated 0.0 distorts the lag-1 cross-
    correlation, especially for thinner symbols. Fixed via pairwise-
    complete correlation (NaN preserved, only mutually-finite days used per
    pair)."""
    values = returns_df.to_numpy()
    n_assets = values.shape[1]
    lead = values[:-1]   # returns at t
    lag = values[1:]     # returns at t+1
    W = np.zeros((n_assets, n_assets))
    for i in range(n_assets):
        for j in range(n_assets):
            if i == j:
                continue
            xi, yj = lead[:, i], lag[:, j]
            valid = np.isfinite(xi) & np.isfinite(yj)
            if valid.sum() < 30 or np.std(xi[valid]) == 0 or np.std(yj[valid]) == 0:
                continue
            W[i, j] = np.corrcoef(xi[valid], yj[valid])[0, 1]
    return W


def network_momentum_signal(returns_df: pd.DataFrame, W: np.ndarray) -> pd.DataFrame:
    """Signal_j[t+1] = weighted avg of OTHER assets' return_i[t], weighted by
    max(W[i,j], 0) (only positive spillover edges contribute).

    Tier 2.10 fix: a source asset with a genuinely missing return at t is
    excluded from BOTH the weighted sum and its own weight's contribution
    to the normalizing row_sum (rather than being fillna(0.0)'d in, which
    would silently treat "no data" as "predicted zero move" and dilute the
    signal). Signal is NaN wherever no valid-weighted source exists."""
    values = returns_df.to_numpy()
    W_pos = np.maximum(W, 0.0)
    n_assets = values.shape[1]
    signal = np.full_like(values, np.nan)
    for t in range(len(values) - 1):
        row = values[t]
        valid_src = np.isfinite(row)
        masked_row = np.where(valid_src, row, 0.0)
        for j in range(n_assets):
            weights = W_pos[:, j] * valid_src
            wsum = weights.sum()
            if wsum > 0:
                signal[t + 1, j] = np.dot(weights, masked_row) / wsum
    return pd.DataFrame(signal, index=returns_df.index, columns=returns_df.columns)


def single_asset_momentum_signal(returns_df: pd.DataFrame) -> pd.DataFrame:
    """Naive baseline: today's signal = yesterday's own return. NaN where
    yesterday's return is genuinely missing (Tier 2.10 fix: previously
    fillna(0.0)'d, fabricating a "predicted zero move" on days with no
    real data)."""
    return returns_df.shift(1)


def evaluate_signal(signal: pd.DataFrame, returns_df: pd.DataFrame) -> dict:
    """Pooled correlation between signal[t] and realized return[t] across
    all assets and all valid days — a signal-existence check, not a
    backtest. Tier 2.10 fix: no longer fillna(0.0)'s the realized-return
    leg -- both sides now keep NaN for genuinely missing data, and the
    `np.isfinite` mask (no longer needing a `sig_flat != 0` heuristic to
    filter out fabricated zeros) excludes them naturally."""
    sig_flat = signal.to_numpy().flatten()
    ret_flat = returns_df.to_numpy().flatten()
    valid = np.isfinite(sig_flat) & np.isfinite(ret_flat)
    if valid.sum() < 100:
        return {"corr": np.nan, "n_obs": int(valid.sum())}
    corr = float(np.corrcoef(sig_flat[valid], ret_flat[valid])[0, 1])
    return {"corr": corr, "n_obs": int(valid.sum())}


def main():
    symbols = confirmed_universe_symbols()
    print(f"Universe: {len(symbols)} unique symbols across all confirmed pairs")
    if len(symbols) < 10:
        print("Too few symbols — run analysis.py first. Aborting.")
        return

    returns_df = _load_daily_log_returns(symbols)
    print(f"Loaded daily returns: {returns_df.shape[0]} dates x {returns_df.shape[1]} symbols")
    if returns_df.empty or returns_df.shape[0] < _CALIBRATION_WINDOW * 2:
        print("Insufficient daily history — aborting.")
        return

    W = lead_lag_network(returns_df)
    n_assets = W.shape[0]
    off_diag = W[~np.eye(n_assets, dtype=bool)]
    print(f"\nLead-lag network: {n_assets} assets, mean |edge weight|={np.mean(np.abs(off_diag)):.4f}, "
          f"max edge weight={np.max(off_diag):.4f}")

    net_signal = network_momentum_signal(returns_df, W)
    own_signal = single_asset_momentum_signal(returns_df)

    net_result = evaluate_signal(net_signal, returns_df)
    own_result = evaluate_signal(own_signal, returns_df)

    print(f"\nNetwork momentum signal: corr(signal, forward return)={net_result['corr']:.4f} "
          f"(n={net_result['n_obs']})")
    print(f"Single-asset momentum baseline: corr(signal, forward return)={own_result['corr']:.4f} "
          f"(n={own_result['n_obs']})")
    print(f"\nIncremental value of cross-asset network momentum over single-asset momentum: "
          f"{net_result['corr'] - own_result['corr']:+.4f}")

    os.makedirs("output/research", exist_ok=True)
    pd.DataFrame(W, index=returns_df.columns, columns=returns_df.columns).to_parquet(
        "output/research/network_momentum_lead_lag_matrix.parquet"
    )
    print("\nWrote output/research/network_momentum_lead_lag_matrix.parquet")


if __name__ == "__main__":
    main()
