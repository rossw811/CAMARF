"""
CAMARF research/leg_level_early_exit.py — comparison/diagnostic script,
NOT part of the production pipeline (2026-07-14, task #60).

Scoped with Ross 2026-07-13 as idea (2) of the relational-adaptation
program, explicitly split in two: a broadly-testable claim (does a
pair's own LEG-LEVEL price action improve exit timing beyond the
z-score/stop-loss baseline) and a thinner-evidence claim (true cross-
asset lead-lag exits). This script covers ONLY the first claim — the
second was explicitly gated on task #53's fresh near-miss rerun, and
today's session independently ran FOUR separate lead-lag tests (task #69
Pieces B/C, task #56's MIDAS cross-asset test, on top of the pre-existing
near-miss work) — all four converged on a clean null (no detectable
lagged relationship for this pair set). Building the cross-asset lead-lag
EXIT variant on top of a signal that's now been independently tested and
rejected four separate ways this session would not be a good use of
effort; the leg-level (single-pair, no cross-asset dependency) claim is
the one worth testing.

Question: once a pair is in a mean-reversion trade (z-score triggered
entry, same convention as breakout_vs_reversion.py — reuses that
script's spread/z construction), does adding a LEG-LEVEL momentum signal
(RSI on each individual leg) let the strategy exit earlier — locking in
the same convergence profit with less holding-period risk — versus the
pure z-score-crosses-zero baseline exit?

Rule: baseline exits when z reaches EXIT_Z (matches
breakout_vs_reversion.py/config.py convention). The leg-level variant
exits at the FIRST bar where the baseline condition is close (|z| below
a tolerance) AND the CONVERGING leg's own RSI confirms a reversal
(RSI crossing back through 50 in the direction that supports
convergence) — a leg-level confirmation that fires at or before the pure
z-based exit, never later (so it can only IMPROVE hold time, not worsen
it, by construction — the comparison is whether it improves it
MEANINGFULLY, not whether it's structurally capable of doing so).

Usage:
    python research/leg_level_early_exit.py --tf 1hr
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
RSI_WINDOW = 14
Z_TOLERANCE = 0.5  # "close to baseline exit" band the leg-level confirmation can fire within


def build_spread_z_and_legs(symbol_a, symbol_b, tf_label, z_window=60):
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
    z = z.dropna()
    la, lb = la.reindex(z.index), lb.reindex(z.index)
    return z, la, lb


def _rsi(log_price: pd.Series, window=RSI_WINDOW):
    delta = log_price.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def simulate_baseline(z: pd.Series):
    trades = []
    i, n, vals = 0, len(z), z.values
    while i < n:
        if abs(vals[i]) >= ENTRY_Z:
            direction = -1 if vals[i] > 0 else 1
            entry_val = vals[i]
            j = i + 1
            while j < n and j - i < MAX_HOLD_BARS:
                if (direction == -1 and vals[j] <= EXIT_Z) or (direction == 1 and vals[j] >= -EXIT_Z):
                    break
                j += 1
            exit_val = vals[min(j, n - 1)]
            pnl = direction * (exit_val - entry_val)
            trades.append({"entry_idx": i, "exit_idx": min(j, n - 1), "hold": j - i, "pnl_z": pnl, "direction": direction})
            i = j + 1
        else:
            i += 1
    return trades


def simulate_leg_confirmed(z: pd.Series, rsi_a: pd.Series, rsi_b: pd.Series):
    """Same entries as baseline. Exit at the EARLIER of: the pure z-based
    exit, or (once |z| is within Z_TOLERANCE of the exit threshold) the
    first bar where the converging leg's own RSI confirms a reversal
    through 50 in the direction supporting convergence. Guaranteed to
    exit at or before the baseline (never later, by construction) — see
    module docstring."""
    trades = []
    i, n, vals = 0, len(z), z.values
    ra, rb = rsi_a.values, rsi_b.values
    while i < n:
        if abs(vals[i]) >= ENTRY_Z:
            direction = -1 if vals[i] > 0 else 1
            entry_val = vals[i]
            j = i + 1
            confirmed_exit = None
            while j < n and j - i < MAX_HOLD_BARS:
                baseline_hit = (direction == -1 and vals[j] <= EXIT_Z) or \
                               (direction == 1 and vals[j] >= -EXIT_Z)
                if baseline_hit:
                    break
                near_exit = abs(vals[j] - EXIT_Z) <= Z_TOLERANCE
                if near_exit and not np.isnan(ra[j]) and not np.isnan(rb[j]):
                    # direction=-1 (fading a positive spread, expects A's
                    # relative strength to fade): confirm via A's RSI
                    # crossing below 50 (A losing momentum) OR B's RSI
                    # crossing above 50 (B gaining) — either leg
                    # confirming supports the same convergence direction.
                    if direction == -1 and (ra[j] < 50 or rb[j] > 50):
                        confirmed_exit = j
                        break
                    if direction == 1 and (ra[j] > 50 or rb[j] < 50):
                        confirmed_exit = j
                        break
                j += 1
            exit_idx = confirmed_exit if confirmed_exit is not None else min(j, n - 1)
            exit_val = vals[exit_idx]
            pnl = direction * (exit_val - entry_val)
            trades.append({"entry_idx": i, "exit_idx": exit_idx, "hold": exit_idx - i, "pnl_z": pnl,
                            "leg_confirmed_early": confirmed_exit is not None})
            i = exit_idx + 1
        else:
            i += 1
    return trades


def _summarize(trades, label):
    if not trades:
        return {"strategy": label, "n_trades": 0}
    pnls = np.array([t["pnl_z"] for t in trades])
    holds = np.array([t["hold"] for t in trades])
    std_pnl = pnls.std()
    return {
        "strategy": label, "n_trades": len(trades), "win_rate": float((pnls > 0).mean()),
        "mean_pnl_z": float(pnls.mean()), "total_pnl_z": float(pnls.sum()),
        "sharpe_like": float(pnls.mean() / std_pnl) if std_pnl > 1e-9 else np.nan,
        "mean_hold_bars": float(holds.mean()),
    }


def main():
    p = argparse.ArgumentParser(description="Leg-level early-exit comparison arm (2026-07-14)")
    p.add_argument("--tf", default="1hr")
    args = p.parse_args()

    rows = []
    for sym_a, sym_b in _DEFAULT_PAIRS:
        result = build_spread_z_and_legs(sym_a, sym_b, args.tf)
        if result is None:
            print(f"{sym_a}/{sym_b}: insufficient data")
            continue
        z, la, lb = result
        rsi_a, rsi_b = _rsi(la), _rsi(lb)

        base_trades = simulate_baseline(z)
        leg_trades = simulate_leg_confirmed(z, rsi_a, rsi_b)
        base_sum = _summarize(base_trades, "baseline_z_only")
        leg_sum = _summarize(leg_trades, "leg_level_confirmed")
        n_early = sum(1 for t in leg_trades if t.get("leg_confirmed_early"))
        base_sum.update({"symbol_a": sym_a, "symbol_b": sym_b})
        leg_sum.update({"symbol_a": sym_a, "symbol_b": sym_b, "n_early_exits": n_early})
        rows.append(base_sum)
        rows.append(leg_sum)
        print(f"{sym_a}/{sym_b}@{args.tf}: "
              f"baseline hold={base_sum.get('mean_hold_bars',float('nan')):.1f} "
              f"total_pnl_z={base_sum.get('total_pnl_z',float('nan')):.2f} | "
              f"leg-confirmed hold={leg_sum.get('mean_hold_bars',float('nan')):.1f} "
              f"total_pnl_z={leg_sum.get('total_pnl_z',float('nan')):.2f} "
              f"({n_early}/{leg_sum.get('n_trades',0)} exited early)")

    df = pd.DataFrame(rows)
    if not df.empty:
        agg = df.groupby("strategy").agg(
            n_pairs=("symbol_a", "count"), total_trades=("n_trades", "sum"),
            mean_hold_bars=("mean_hold_bars", "mean"), mean_total_pnl_z=("total_pnl_z", "mean"),
            mean_sharpe_like=("sharpe_like", "mean"),
        )
        print(f"\nAggregate across {len(_DEFAULT_PAIRS)} pairs:")
        print(agg.to_string())

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"leg_level_early_exit_{args.tf}.parquet")
    df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
