"""
CAMARF research/breakout_vs_reversion.py — comparison/diagnostic script,
NOT part of the production pipeline (2026-07-14, task #55).

CAMARF's production strategy is pure mean-reversion: enter when the
spread's rolling z-score exceeds a threshold (config.py's ENTRY_ZSCORE,
default 2.0), betting on convergence back toward zero (EXIT_ZSCORE=0.0).
This script builds the opposite-philosophy comparison: a BREAKOUT
strategy that trades WITH a z-score extreme (momentum continuation —
betting the spread keeps diverging once it crosses a threshold) rather
than against it, using the identical spread/z-score construction and
threshold conventions as production for a fair, apples-to-apples
comparison.

Spread construction: full-sample OLS hedge ratio (log_a - beta*log_b),
same simplification used in wavelet_hurst_comparison.py and
k_bahc_covariance_cleaning.py earlier this session — this script compares
STRATEGY LOGIC given a spread, not the spread-construction method itself,
so a consistent, simple construction across pairs is the right scope.

Rules (both use production's own ENTRY_ZSCORE=2.0 threshold for the
entry trigger, so any performance difference reflects strategy LOGIC, not
a different threshold):
  Mean-reversion: |z| >= 2.0 -> enter fading the move (short if z>0, long
    if z<0). Exit when z crosses 0 (production's EXIT_ZSCORE) OR a fixed
    max holding period elapses (protects against non-convergence).
  Breakout: |z| >= 2.0 -> enter WITH the move (long if z>0, short if
    z<0), betting on continuation. Exit at a fixed profit target
    (|z| increases by a further BREAKOUT_TARGET_DELTA) or a fixed max
    holding period / stop-loss if the move reverses instead.

Honest scope note: this is a simple, single fixed-parameter comparison
(not a parameter sweep) using a full-sample hedge ratio, not backtest.py's
full point-in-time/gap-aware/transaction-cost machinery — a first-pass
comparison-arm result, not a production-ready strategy evaluation.

Result note (2026-07-14): mean-reversion came back at a 100.000% win rate
across 665 real-data trades on the 9 known-good pairs. Checked, not
assumed correct — confirmed NOT a trivial instant-exit bug (mean holding
period 28-35 bars, well under the 100-bar cap). But the exact 100% figure
should NOT be read as a tradeable result: the full-sample hedge ratio
above is a genuine lookahead bias (it uses data from AFTER any given
trade), and this pair set was hand-picked for already-verified strong
signal, not randomly sampled. The DIRECTIONAL result (mean-reversion
decisively beats breakout) is real and consistent with this session's
other findings; the magnitude is inflated by both of the above and should
not be cited as a real backtest number. See Development.md for the full
writeup, including the sign-error bug this same implausible-result check
initially caught (a first version showed 0.00 win rate — the exact
opposite bug, same root check applied).

Usage:
    python research/breakout_vs_reversion.py --tf 1hr
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
from spread_construction import full_sample_ols_spread
from config import Config

_DEFAULT_PAIRS = [
    ("LNT", "VTR"), ("LNT", "WELL"), ("AME", "MAR"), ("CMS", "DUK"),
    ("EG", "WRB"), ("HAL", "NOV"), ("MET", "TMHC"), ("PFG", "STLD"),
    ("UMBF", "FHB"),
]

# Sourced from Config.RESEARCH (2026-07-20, Grand Sweep task #24) -- was
# hardcoded here (and independently in 4 sibling files); see config.py's
# ResearchConfig docstring.
ENTRY_Z = Config.RESEARCH.ENTRY_Z
EXIT_Z = Config.RESEARCH.EXIT_Z
BREAKOUT_TARGET_DELTA = 1.0   # breakout profit target: |z| grows by this much further -- unique to this file
MAX_HOLD_BARS = Config.RESEARCH.MAX_HOLD_BARS

# Entry/exit combination sweep grid (added 2026-07-14, per Ross's direction
# to sweep the same way production already does — config.py's
# COARSE_ENTRY_ZSCORE/COARSE_EXIT_ZSCORE). ENTRY_GRID reused verbatim for
# a direct match; EXIT_GRID reused for mean-reversion's exit-at-z
# threshold. Breakout has no equivalent "exit toward the mean" concept, so
# its second dimension is the continuation TARGET_DELTA instead, values
# chosen on the same relative scale as EXIT_GRID's spacing.
ENTRY_GRID = [1.5, 2.0, 2.5, 3.0]      # matches config.py COARSE_ENTRY_ZSCORE exactly
EXIT_GRID = [0.0, 0.25, 0.5, 0.75]     # matches config.py COARSE_EXIT_ZSCORE exactly
TARGET_DELTA_GRID = [0.5, 1.0, 1.5, 2.0]


def build_spread_and_z(symbol_a, symbol_b, tf_label, z_window=60):
    # Full-sample static OLS hedge ratio -- consolidated 2026-07-20 into
    # spread_construction.py (this file was the ORIGIN that leg_level_early_exit.py,
    # archetype_conditional_sizing.py, vol_targeting_and_drawdown_derisking.py, and
    # hub_leg_stop_conditioning.py all independently copy-pasted; see that
    # module's docstring for the non-causal/lookahead disclosure this
    # function must keep making to its own callers, per this file's own
    # docstring above).
    result = full_sample_ols_spread(symbol_a, symbol_b, tf_label)
    if result is None:
        return None
    la, lb, beta, alpha, spread = result
    z = (spread - spread.rolling(z_window).mean()) / spread.rolling(z_window).std()
    return spread.dropna(), z.dropna()


def simulate_mean_reversion(z: pd.Series, entry_threshold=ENTRY_Z, exit_threshold=EXIT_Z):
    """exit_threshold is a magnitude (>=0): position exits once |z| has
    fallen to this level, matching config.py's EXIT_ZSCORE convention
    (0.0 = wait for a full return to the mean; larger = take profit
    earlier, before full reversion). Every entry is guaranteed a paired
    exit — either the threshold condition, the MAX_HOLD_BARS cap, or the
    end of the series (min(j, n-1)) — no position is ever left open and
    uncounted (checked explicitly per Ross's 2026-07-14 request to sweep
    for exactly this failure mode after a prior project incident)."""
    trades = []
    i, n = 0, len(z)
    vals = z.values
    while i < n:
        if abs(vals[i]) >= entry_threshold:
            direction = -1 if vals[i] > 0 else 1  # fade the extreme
            entry_val = vals[i]
            j = i + 1
            while j < n and j - i < MAX_HOLD_BARS:
                if (direction == -1 and vals[j] <= exit_threshold) or \
                   (direction == 1 and vals[j] >= -exit_threshold):
                    break
                j += 1
            exit_val = vals[min(j, n - 1)]
            # direction=-1 means "I bet z decreases" (fading a positive
            # extreme); direction=+1 means "I bet z increases" (fading a
            # negative extreme). Profit = direction * (exit_val - entry_val)
            # in BOTH cases — e.g. direction=-1, entry=2.5, exit=0.0 (z
            # fell as bet): profit = -1*(0.0-2.5) = +2.5, correctly a win.
            # An earlier version used direction*(entry_val-exit_val) here —
            # the exact opposite sign — which is why the first real-data
            # run showed a 0.00 win rate across 665 trades on pairs
            # independently confirmed as genuinely mean-reverting: every
            # real win was being recorded as a loss. Caught by that
            # implausible result, not assumed correct from code review.
            pnl = direction * (exit_val - entry_val)
            trades.append({"entry_idx": i, "exit_idx": min(j, n - 1), "hold": j - i, "pnl_z": pnl})
            i = j + 1
        else:
            i += 1
    return trades


def simulate_breakout(z: pd.Series, entry_threshold=ENTRY_Z, target_delta=BREAKOUT_TARGET_DELTA):
    """Every entry is guaranteed a paired exit (target/stop, MAX_HOLD_BARS
    cap, or end of series) — same completeness guarantee as
    simulate_mean_reversion, see its docstring."""
    trades = []
    i, n = 0, len(z)
    vals = z.values
    while i < n:
        if abs(vals[i]) >= entry_threshold:
            direction = 1 if vals[i] > 0 else -1  # trade WITH the extreme
            entry_val = vals[i]
            target = entry_val + direction * target_delta
            stop = entry_val - direction * target_delta  # symmetric stop
            j = i + 1
            while j < n and j - i < MAX_HOLD_BARS:
                if (direction == 1 and (vals[j] >= target or vals[j] <= stop)) or \
                   (direction == -1 and (vals[j] <= target or vals[j] >= stop)):
                    break
                j += 1
            exit_val = vals[min(j, n - 1)]
            pnl = direction * (exit_val - entry_val)  # continuation in our direction is profit
            trades.append({"entry_idx": i, "exit_idx": min(j, n - 1), "hold": j - i, "pnl_z": pnl})
            i = j + 1
        else:
            i += 1
    return trades


def _summarize(trades, label):
    if not trades:
        return {"strategy": label, "n_trades": 0}
    pnls = np.array([t["pnl_z"] for t in trades])
    holds = np.array([t["hold"] for t in trades])
    win_rate = float((pnls > 0).mean())
    mean_pnl = float(pnls.mean())
    std_pnl = float(pnls.std())
    sharpe_like = mean_pnl / std_pnl if std_pnl > 1e-9 else np.nan
    return {
        "strategy": label, "n_trades": len(trades), "win_rate": win_rate,
        "mean_pnl_z": mean_pnl, "total_pnl_z": float(pnls.sum()),
        "sharpe_like": sharpe_like, "mean_hold_bars": float(holds.mean()),
    }


def main():
    p = argparse.ArgumentParser(description="Mean-reversion vs breakout comparison arm (2026-07-14)")
    p.add_argument("--tf", default="1hr")
    args = p.parse_args()

    rows = []
    all_mr_trades = []
    all_bo_trades = []
    for sym_a, sym_b in _DEFAULT_PAIRS:
        result = build_spread_and_z(sym_a, sym_b, args.tf)
        if result is None:
            print(f"{sym_a}/{sym_b}: insufficient data")
            continue
        spread, z = result
        mr_trades = simulate_mean_reversion(z)
        bo_trades = simulate_breakout(z)
        all_mr_trades.extend(mr_trades)
        all_bo_trades.extend(bo_trades)
        mr_sum = _summarize(mr_trades, "mean_reversion")
        bo_sum = _summarize(bo_trades, "breakout")
        mr_sum.update({"symbol_a": sym_a, "symbol_b": sym_b})
        bo_sum.update({"symbol_a": sym_a, "symbol_b": sym_b})
        rows.append(mr_sum)
        rows.append(bo_sum)
        print(f"{sym_a}/{sym_b}@{args.tf}: "
              f"MR n={mr_sum.get('n_trades',0)} win={mr_sum.get('win_rate',float('nan')):.2f} "
              f"total_pnl_z={mr_sum.get('total_pnl_z',float('nan')):.2f} | "
              f"BO n={bo_sum.get('n_trades',0)} win={bo_sum.get('win_rate',float('nan')):.2f} "
              f"total_pnl_z={bo_sum.get('total_pnl_z',float('nan')):.2f}")

    df = pd.DataFrame(rows)
    if not df.empty:
        agg = df.groupby("strategy").agg(
            n_pairs=("symbol_a", "count"),
            total_trades=("n_trades", "sum"),
            mean_win_rate=("win_rate", "mean"),
            mean_total_pnl_z=("total_pnl_z", "mean"),
        )
        # Tier 4.1 fix (BUG-D59-class, Grand Sweep 2026-07-20): the previous
        # "mean_sharpe_like" column averaged each PAIR's own sharpe_like --
        # the exact BUG-D59 pattern run_combination_sweep() (a few dozen
        # lines below) already avoids by pooling trades across pairs FIRST.
        # A single low-trade-count pair's noisy per-pair ratio could
        # otherwise dominate the aggregate the way a naive per-pair average
        # does. Pool here the same way.
        pooled_sharpe = {}
        for label, trades in (("mean_reversion", all_mr_trades), ("breakout", all_bo_trades)):
            pnls = np.array([t["pnl_z"] for t in trades]) if trades else np.array([])
            pooled_sharpe[label] = float(pnls.mean() / pnls.std()) if len(pnls) > 1 and pnls.std() > 1e-9 else np.nan
        agg["pooled_sharpe_like"] = agg.index.map(pooled_sharpe)
        print(f"\nAggregate across {len(_DEFAULT_PAIRS)} pairs:")
        print(agg.to_string())

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"breakout_vs_reversion_{args.tf}.parquet")
    df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")

    sweep_df = run_combination_sweep(args.tf)
    sweep_path = os.path.join(out_dir, f"breakout_vs_reversion_sweep_{args.tf}.parquet")
    sweep_df.to_parquet(sweep_path)
    print(f"\nSweep results written to {sweep_path}")


def run_combination_sweep(tf_label):
    """Entry/exit combination sweep, matching the same practice already
    used in production (config.py's COARSE_ENTRY_ZSCORE x
    COARSE_EXIT_ZSCORE grid) — per Ross's 2026-07-14 request to find the
    best-performing combination the same way it's already done for entry
    alone. Pools trades across ALL pairs for each combination before
    computing Sharpe-like, rather than averaging per-pair Sharpe-likes —
    avoids letting a single low-trade-count pair's noisy ratio dominate
    the aggregate the way a naive per-pair average would."""
    spreads_z = {}
    for sym_a, sym_b in _DEFAULT_PAIRS:
        result = build_spread_and_z(sym_a, sym_b, tf_label)
        if result is not None:
            spreads_z[(sym_a, sym_b)] = result[1]

    rows = []
    for entry_thr in ENTRY_GRID:
        for exit_thr in EXIT_GRID:
            pooled_pnls = []
            for z in spreads_z.values():
                for t in simulate_mean_reversion(z, entry_threshold=entry_thr, exit_threshold=exit_thr):
                    pooled_pnls.append(t["pnl_z"])
            if pooled_pnls:
                pnls = np.array(pooled_pnls)
                sharpe_like = float(pnls.mean() / pnls.std()) if pnls.std() > 1e-9 else np.nan
                rows.append({"strategy": "mean_reversion", "entry": entry_thr, "exit_or_target": exit_thr,
                             "n_trades": len(pnls), "win_rate": float((pnls > 0).mean()),
                             "total_pnl_z": float(pnls.sum()), "sharpe_like": sharpe_like})

    for entry_thr in ENTRY_GRID:
        for target_delta in TARGET_DELTA_GRID:
            pooled_pnls = []
            for z in spreads_z.values():
                for t in simulate_breakout(z, entry_threshold=entry_thr, target_delta=target_delta):
                    pooled_pnls.append(t["pnl_z"])
            if pooled_pnls:
                pnls = np.array(pooled_pnls)
                sharpe_like = float(pnls.mean() / pnls.std()) if pnls.std() > 1e-9 else np.nan
                rows.append({"strategy": "breakout", "entry": entry_thr, "exit_or_target": target_delta,
                             "n_trades": len(pnls), "win_rate": float((pnls > 0).mean()),
                             "total_pnl_z": float(pnls.sum()), "sharpe_like": sharpe_like})

    df = pd.DataFrame(rows)
    print(f"\n{'='*70}\nEntry/exit combination sweep ({len(ENTRY_GRID)}x{len(EXIT_GRID)} mean-reversion, "
          f"{len(ENTRY_GRID)}x{len(TARGET_DELTA_GRID)} breakout, pooled across {len(spreads_z)} pairs):\n")
    for strategy in ("mean_reversion", "breakout"):
        sub = df[df["strategy"] == strategy].dropna(subset=["sharpe_like"])
        if sub.empty:
            continue
        best = sub.loc[sub["sharpe_like"].idxmax()]
        label = "exit" if strategy == "mean_reversion" else "target_delta"
        print(f"{strategy}: best combination entry={best['entry']}, {label}={best['exit_or_target']} "
              f"-> sharpe_like={best['sharpe_like']:.3f}, n_trades={int(best['n_trades'])}, "
              f"win_rate={best['win_rate']:.3f}")
    return df


if __name__ == "__main__":
    main()
