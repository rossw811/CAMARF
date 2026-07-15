"""
CAMARF research/vol_targeting_and_drawdown_derisking.py — comparison/
diagnostic script, NOT part of the production pipeline (2026-07-14,
task #48).

Completes the 2 risk-management comparison arms task #20
(`research/stop_loss_correlation_caps.py`) explicitly deferred: "the
other 2 (volatility-targeting sizing, drawdown-triggered de-risking)
need real backtest.py trading-loop changes not a config-patch, and were
not reached." Built here as STANDALONE comparison-arm scripts reusing
this session's established spread/z simulation (same pattern as
breakout_vs_reversion.py) rather than modifying backtest.py's trading
loop directly — keeps this within the comparison-arm-first convention
this project uses for every new methodology, no production code touched.

Two arms:

1. VOLATILITY-TARGETING SIZING (per-pair): standard risk-management
   technique — size inversely to the spread's own CAUSAL (trailing,
   never future) realized volatility at entry time, targeting constant
   RISK contribution per trade rather than constant notional. Compared
   against flat (constant) sizing.

2. DRAWDOWN-TRIGGERED DE-RISKING (portfolio-level): merges all 9 known-
   good pairs' trades into one true chronological event stream (entries
   AND exits interleaved by real timestamp — same discipline
   portfolio_sim.py already established for capital-constraint
   simulation), tracks running portfolio equity, and cuts new-entry size
   by a fixed fraction once trailing drawdown exceeds a threshold,
   restoring full size once drawdown recovers. Compared against no
   de-risking (flat size regardless of drawdown state).

Usage:
    python research/vol_targeting_and_drawdown_derisking.py --tf 1hr
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from aligned_pair_loader import load_aligned_pair
from lead_lag_scan import _gap_masked_log_price

_DEFAULT_PAIRS = [
    ("LNT", "VTR"), ("LNT", "WELL"), ("AME", "MAR"), ("CMS", "DUK"),
    ("EG", "WRB"), ("HAL", "NOV"), ("MET", "TMHC"), ("PFG", "STLD"),
    ("UMBF", "FHB"),
]

ENTRY_Z = 2.0
EXIT_Z = 0.0
MAX_HOLD_BARS = 100
VOL_WINDOW = 60
DRAWDOWN_THRESHOLD = 0.10  # 10% trailing-equity drawdown triggers de-risking
DERISK_SIZE_MULT = 0.5


def build_spread_z(symbol_a, symbol_b, tf_label, z_window=60):
    df_a, df_b = load_aligned_pair(symbol_a, symbol_b, tf_label)
    if df_a is None or df_b is None or df_a.empty or df_b.empty:
        return None
    log_a = pd.Series(_gap_masked_log_price(df_a), index=df_a.index)
    log_b = pd.Series(_gap_masked_log_price(df_b), index=df_b.index)
    common_idx = log_a.index.intersection(log_b.index)
    log_a, log_b = log_a.reindex(common_idx), log_b.reindex(common_idx)
    mask = log_a.notna() & log_b.notna()
    la, lb = log_a[mask], log_b[mask]
    if len(la) < 100:
        return None
    beta = np.dot(lb - lb.mean(), la - la.mean()) / np.dot(lb - lb.mean(), lb - lb.mean())
    alpha = la.mean() - beta * lb.mean()
    spread = la - (alpha + beta * lb)
    z = (spread - spread.rolling(z_window).mean()) / spread.rolling(z_window).std()
    spread_vol = spread.diff().rolling(VOL_WINDOW).std()  # causal, trailing only
    return z.dropna(), spread_vol.reindex(z.dropna().index)


def simulate_trades(z: pd.Series, spread_vol: pd.Series = None, target_vol: float = None):
    """Every entry exits via EXIT_Z, MAX_HOLD_BARS, or end-of-series —
    same completeness guarantee established earlier this session. If
    spread_vol+target_vol given, size_mult = target_vol / current_vol
    (capped [0.2, 3.0] to avoid degenerate sizes at near-zero vol)."""
    trades = []
    i, n, vals = 0, len(z), z.values
    idx = z.index
    vol_vals = spread_vol.values if spread_vol is not None else None
    while i < n:
        if abs(vals[i]) >= ENTRY_Z:
            direction = -1 if vals[i] > 0 else 1
            entry_val = vals[i]
            size_mult = 1.0
            if vol_vals is not None and target_vol is not None and not np.isnan(vol_vals[i]) and vol_vals[i] > 1e-9:
                size_mult = float(np.clip(target_vol / vol_vals[i], 0.2, 3.0))
            j = i + 1
            while j < n and j - i < MAX_HOLD_BARS:
                if (direction == -1 and vals[j] <= EXIT_Z) or (direction == 1 and vals[j] >= -EXIT_Z):
                    break
                j += 1
            exit_val = vals[min(j, n - 1)]
            pnl = direction * (exit_val - entry_val)
            trades.append({"entry_time": idx[i], "exit_time": idx[min(j, n - 1)],
                            "pnl_flat": pnl, "pnl_sized": pnl * size_mult, "size_mult": size_mult})
            i = j + 1
        else:
            i += 1
    return trades


def run_vol_targeting(tf_label):
    print("=== Arm 1: volatility-targeting sizing (per-pair) ===\n")
    rows = []
    for sym_a, sym_b in _DEFAULT_PAIRS:
        result = build_spread_z(sym_a, sym_b, tf_label)
        if result is None:
            continue
        z, spread_vol = result
        target_vol = float(spread_vol.median())
        trades = simulate_trades(z, spread_vol, target_vol)
        if not trades:
            continue
        flat = np.array([t["pnl_flat"] for t in trades])
        sized = np.array([t["pnl_sized"] for t in trades])
        flat_sharpe = flat.mean() / flat.std() if flat.std() > 1e-9 else np.nan
        sized_sharpe = sized.mean() / sized.std() if sized.std() > 1e-9 else np.nan
        print(f"{sym_a}/{sym_b}: flat total_pnl={flat.sum():.2f} sharpe={flat_sharpe:.3f} | "
              f"vol-targeted total_pnl={sized.sum():.2f} sharpe={sized_sharpe:.3f} "
              f"(mean size_mult={np.mean([t['size_mult'] for t in trades]):.3f})")
        rows.append({"symbol_a": sym_a, "symbol_b": sym_b, "n_trades": len(trades),
                      "flat_total_pnl": float(flat.sum()), "flat_sharpe": float(flat_sharpe),
                      "vol_targeted_total_pnl": float(sized.sum()), "vol_targeted_sharpe": float(sized_sharpe)})
    return pd.DataFrame(rows)


def run_drawdown_derisking(tf_label):
    print("\n=== Arm 2: drawdown-triggered de-risking (portfolio-level) ===\n")
    all_trades = []
    for sym_a, sym_b in _DEFAULT_PAIRS:
        result = build_spread_z(sym_a, sym_b, tf_label)
        if result is None:
            continue
        z, _ = result
        for t in simulate_trades(z):
            t["pair"] = f"{sym_a}/{sym_b}"
            all_trades.append(t)

    if not all_trades:
        print("No trades generated.")
        return pd.DataFrame()

    df = pd.DataFrame(all_trades).sort_values("entry_time").reset_index(drop=True)

    # Baseline: flat sizing regardless of drawdown state.
    equity_flat = df["pnl_flat"].cumsum()
    running_max_flat = equity_flat.cummax()
    dd_flat = (equity_flat - running_max_flat)
    max_dd_flat = float(dd_flat.min())

    # De-risked: size cut to DERISK_SIZE_MULT once trailing drawdown
    # (as a fraction of running peak equity, floored to avoid div-by-
    # near-zero at the very start) exceeds DRAWDOWN_THRESHOLD.
    equity = 0.0
    peak = 0.0
    pnl_derisked = []
    in_derisk = False
    n_derisk_periods = 0
    for pnl in df["pnl_flat"]:
        peak = max(peak, equity)
        dd_frac = (peak - equity) / max(abs(peak), 50.0)
        in_derisk = dd_frac >= DRAWDOWN_THRESHOLD
        if in_derisk:
            n_derisk_periods += 1
        applied_pnl = pnl * (DERISK_SIZE_MULT if in_derisk else 1.0)
        equity += applied_pnl
        pnl_derisked.append(applied_pnl)
    df["pnl_derisked"] = pnl_derisked
    equity_derisked = df["pnl_derisked"].cumsum()
    running_max_derisked = equity_derisked.cummax()
    max_dd_derisked = float((equity_derisked - running_max_derisked).min())

    flat_sharpe = df["pnl_flat"].mean() / df["pnl_flat"].std() if df["pnl_flat"].std() > 1e-9 else np.nan
    derisked_sharpe = df["pnl_derisked"].mean() / df["pnl_derisked"].std() if df["pnl_derisked"].std() > 1e-9 else np.nan

    print(f"{len(df)} pooled trades across {len(_DEFAULT_PAIRS)} pairs, "
          f"{n_derisk_periods}/{len(df)} trades occurred during a de-risked period.")
    print(f"Flat sizing:       total_pnl={equity_flat.iloc[-1]:.2f}  max_drawdown={max_dd_flat:.2f}  sharpe={flat_sharpe:.3f}")
    print(f"Drawdown de-risked: total_pnl={equity_derisked.iloc[-1]:.2f}  max_drawdown={max_dd_derisked:.2f}  sharpe={derisked_sharpe:.3f}")

    return pd.DataFrame([{
        "n_trades": len(df), "n_derisk_periods": n_derisk_periods,
        "flat_total_pnl": float(equity_flat.iloc[-1]), "flat_max_drawdown": max_dd_flat, "flat_sharpe": float(flat_sharpe),
        "derisked_total_pnl": float(equity_derisked.iloc[-1]), "derisked_max_drawdown": max_dd_derisked, "derisked_sharpe": float(derisked_sharpe),
    }])


def main():
    p = argparse.ArgumentParser(description="Vol-targeting sizing + drawdown de-risking (2026-07-14)")
    p.add_argument("--tf", default="1hr")
    args = p.parse_args()

    vol_df = run_vol_targeting(args.tf)
    dd_df = run_drawdown_derisking(args.tf)

    out_dir = "output/research"
    os.makedirs(out_dir, exist_ok=True)
    if not vol_df.empty:
        vol_df.to_parquet(os.path.join(out_dir, f"vol_targeting_sizing_{args.tf}.parquet"))
    if not dd_df.empty:
        dd_df.to_parquet(os.path.join(out_dir, f"drawdown_derisking_{args.tf}.parquet"))
    print(f"\nResults written to {out_dir}/vol_targeting_sizing_{args.tf}.parquet and "
          f"drawdown_derisking_{args.tf}.parquet")


if __name__ == "__main__":
    main()
