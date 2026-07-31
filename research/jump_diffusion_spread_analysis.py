"""
research/jump_diffusion_spread_analysis.py — comparison/diagnostic method,
NOT part of the production pipeline.

Motivated by Akyildirim, Fabozzi, Goncu & Sensoy (2022), "Statistical
Arbitrage in Jump-Diffusion Models with Compound Poisson Processes," Annals
of Operations Research 313(2) — one of the 5 papers surveyed this session
(2026-07-10). The paper proves statistical arbitrage exists under
jump-diffusion with finite-moment jumps, using barrier-based strategies.
CAMARF's OU spread model (SpreadModel, analysis.py) assumes pure continuous
diffusion (an AR(1)/Ornstein-Uhlenbeck process) with no explicit jump
component — any real jump in the spread (earnings surprise on one leg,
a sudden re-rating, index-rebalance flow) is currently absorbed into the
SAME noise term as ordinary continuous mean-reversion noise, which:
  (a) may bias the half-life/theta estimate (jump-contaminated bars inflate
      apparent "volatility" without being genuine continuous mean-reversion
      dynamics), and
  (b) may mean the fixed entry_z=2.0/stop_z=3.5 thresholds don't distinguish
      "ordinary large move, will likely revert" from "genuine jump, may not
      revert the same way" — directly relevant given CAMARF's own EVT/GPD
      tail-risk work (stats.py §3) already found 19/26 pairs fat-tailed.

This is NOT a full re-derivation of the paper's barrier-based optimal
stopping theory (a much larger undertaking) — it targets the concrete,
actionable question the paper raises: does explicitly separating jump vs.
continuous-diffusion variance in the spread change anything CAMARF would
actually act on, using its own real, already-backtested data.

Method:
  1. Jump detection: a bar-to-bar z_rolling delta is flagged as a jump if
     |delta| > JUMP_THRESHOLD_SIGMA * trailing_rolling_std_of_delta (a
     standard local-volatility-normalized threshold in the spirit of Lee &
     Mykland 2008's jump test, simplified — no formal test statistic/p-value,
     just a practical detection rule). Trailing window excludes the current
     bar so a jump doesn't inflate its own detection threshold.
  2. Parameter estimation: jump intensity lambda (jumps/year), jump size
     mean/std from flagged deltas, and the fraction of total delta-variance
     attributable to jumps vs. the remaining (non-jump) continuous part.
  3. Trade-outcome comparison (the actionable part, reuses existing
     output/backtest/trades_layer1*.parquet — OLS hedge method only,
     matching this session's other comparison arms' baseline-method
     convention): do trades entered within JUMP_PROXIMITY_BARS bars after a
     detected jump have different win rate/mean P&L than trades entered
     during calm (non-jump-proximate) periods? Pooled across all pairs
     since per-pair jump-adjacent trade counts are likely small.

Read-only. Never fetches, never modifies production spread_series or
backtest.py itself.

Usage:
    python research/jump_diffusion_spread_analysis.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # for aligned_pair_loader

from aligned_pair_loader import (
    TF_DIRS as _TF_DIRS,
    DIR_TO_LABEL as _DIR_TO_LABEL,
    resolve_tf_results_dir as _resolve_tf_results_dir,
)

JUMP_THRESHOLD_SIGMA = 4.0
JUMP_VOL_WINDOW = 60  # trailing bars for the local-volatility normalizer
JUMP_PROXIMITY_BARS = 3
_BACKTEST_DIR = "output/backtest"


def detect_jumps(delta: np.ndarray) -> np.ndarray:
    """Returns a boolean array, True where the bar-to-bar delta is flagged
    as a jump relative to its own trailing local volatility. `delta` must
    already be diffed and gap-masked (NaN at any position whose diff spans
    a DATA_GAP-flagged bar) by the caller -- this function no longer
    computes np.diff() itself (Tier 2.6 fix, Grand Sweep 2026-07-20): the
    diff must happen BEFORE any gap-flagged rows are dropped/compacted, or
    a diff silently spanning a dropped multi-day gap becomes
    indistinguishable from a genuine single-bar jump to this detector."""
    s = pd.Series(delta)
    # shift(1) so the trailing window excludes the current bar itself
    trailing_std = s.shift(1).rolling(JUMP_VOL_WINDOW, min_periods=20).std()
    is_jump = (np.abs(delta) > JUMP_THRESHOLD_SIGMA * trailing_std.to_numpy())
    return np.nan_to_num(is_jump, nan=False).astype(bool)


def analyze_pair_jumps(results_dir: str, sym_a: str, sym_b: str) -> dict:
    path = os.path.join(results_dir, f"spread_series_{sym_a}_{sym_b}.parquet")
    if not os.path.exists(path):
        return {}
    df = pd.read_parquet(path)
    z_raw = df["z_rolling"].to_numpy(dtype=float)
    finite_mask = np.isfinite(z_raw)
    gap_bad = ((df["gap_flag_a"].to_numpy() == 4) | (df["gap_flag_b"].to_numpy() == 4))
    # Diff on the FULL, un-compacted series first (preserves real bar-to-bar
    # adjacency), THEN mask any diff whose start or end bar is DATA_GAP-
    # flagged, mirroring data.py::_gap_aware_returns' convention. Dropping
    # gap rows before diffing (the pre-fix order) silently concatenates
    # positions spanning a multi-bar/multi-day gap as if one bar apart --
    # exactly what this jump detector exists to distinguish from a genuine
    # single-bar jump.
    z_for_diff = np.where(finite_mask, z_raw, np.nan)
    delta = np.diff(z_for_diff, prepend=np.nan)
    bad_delta = gap_bad | np.roll(gap_bad, 1)
    bad_delta[0] = False
    delta = np.where(bad_delta, np.nan, delta)

    keep = finite_mask & ~gap_bad
    z = z_raw[keep]
    delta = delta[keep]
    timestamps = df.index[keep]
    if len(z) < JUMP_VOL_WINDOW * 2:
        return {}

    is_jump = detect_jumps(delta)
    n_jumps = int(is_jump.sum())
    if n_jumps == 0:
        return {
            "n_bars": len(z), "n_jumps": 0, "jump_fraction_of_variance": 0.0,
            "jump_dates": [],
        }

    jump_deltas = delta[is_jump]
    non_jump_deltas = delta[~is_jump & np.isfinite(delta)]
    var_jump_contrib = np.nanvar(delta[np.isfinite(delta)]) - np.nanvar(non_jump_deltas)
    total_var = np.nanvar(delta[np.isfinite(delta)])
    jump_frac_var = float(var_jump_contrib / total_var) if total_var > 0 else np.nan

    jump_idx = np.flatnonzero(is_jump)
    return {
        "n_bars": len(z),
        "n_jumps": n_jumps,
        "jump_mean_size": float(np.mean(jump_deltas)),
        "jump_std_size": float(np.std(jump_deltas)),
        "continuous_std": float(np.std(non_jump_deltas)),
        "jump_fraction_of_variance": jump_frac_var,
        "jump_timestamps": list(pd.to_datetime(timestamps[jump_idx])),
    }


def trade_outcomes_near_jumps(jump_timestamps_by_pair: dict) -> dict:
    """Loads real backtest trades (OLS method), flags each trade as
    jump-proximate (entered within JUMP_PROXIMITY_BARS... approximated here
    as within 1 trading day of a detected jump, since spread_series bar
    spacing isn't carried into trades_layer1.parquet) vs. calm, compares
    outcomes."""
    trades_path = os.path.join(_BACKTEST_DIR, "trades_layer1.parquet")
    if not os.path.exists(trades_path):
        return {}
    tr = pd.read_parquet(trades_path)
    tr = tr[tr["hedge_method"] == "ols"].copy()
    if tr.empty:
        return {}
    tr["entry_time"] = pd.to_datetime(tr["entry_time"])

    proximate_flags = []
    for _, row in tr.iterrows():
        key = f"{row['symbol_a']}/{row['symbol_b']}"
        jumps = jump_timestamps_by_pair.get(key, [])
        if not jumps:
            proximate_flags.append(False)
            continue
        jumps_ts = pd.to_datetime(jumps)
        near = any(abs((row["entry_time"] - jt).total_seconds()) < JUMP_PROXIMITY_BARS * 3600
                   for jt in jumps_ts)
        proximate_flags.append(bool(near))
    tr["jump_proximate"] = proximate_flags

    near = tr[tr["jump_proximate"]]
    calm = tr[~tr["jump_proximate"]]
    if len(near) < 5:
        return {"note": f"only {len(near)} jump-proximate trades — too few for a meaningful comparison"}

    return {
        "n_trades_near_jump": len(near),
        "n_trades_calm": len(calm),
        "win_rate_near_jump": float((near["pnl_net"] > 0).mean()),
        "win_rate_calm": float((calm["pnl_net"] > 0).mean()),
        "mean_pnl_near_jump": float(near["pnl_net"].mean()),
        "mean_pnl_calm": float(calm["pnl_net"].mean()),
    }


def main():
    rows = []
    jump_timestamps_by_pair = {}
    for tf_dir in _TF_DIRS:
        results_dir, is_stale = _resolve_tf_results_dir(tf_dir)
        pairs_path = os.path.join(results_dir, "pairs.parquet")
        if not os.path.exists(pairs_path):
            continue
        if is_stale:
            print(f"NOTE {tf_dir}: using archived {results_dir}")
        tf_label = _DIR_TO_LABEL[tf_dir]
        pairs_df = pd.read_parquet(pairs_path)
        for _, row in pairs_df.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            result = analyze_pair_jumps(results_dir, sym_a, sym_b)
            if not result:
                continue
            result.update({"symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf_label})
            rows.append(result)
            jump_timestamps_by_pair[f"{sym_a}/{sym_b}"] = result.get("jump_timestamps", [])
            print(f"{sym_a}/{sym_b}@{tf_label}: n_bars={result['n_bars']} n_jumps={result['n_jumps']} "
                  f"jump_frac_of_var={result.get('jump_fraction_of_variance', float('nan')):.3f}")

    if not rows:
        print("No confirmed pairs with spread_series found.")
        return

    df = pd.DataFrame(rows)
    print(f"\n=== Jump detection summary across {len(df)} pairs ===")
    print(f"Pairs with >=1 detected jump: {(df['n_jumps'] > 0).sum()}/{len(df)}")
    print(f"Mean jump fraction of variance (where jumps exist): "
          f"{df.loc[df['n_jumps'] > 0, 'jump_fraction_of_variance'].mean():.3f}")

    print("\n=== Trade-outcome comparison: jump-proximate vs. calm entries ===")
    outcome = trade_outcomes_near_jumps(jump_timestamps_by_pair)
    for k, v in outcome.items():
        print(f"  {k}: {v}")

    os.makedirs("output/research", exist_ok=True)
    df.drop(columns=["jump_timestamps"], errors="ignore").to_parquet(
        "output/research/jump_diffusion_spread_analysis.parquet"
    )
    print("\nWrote output/research/jump_diffusion_spread_analysis.parquet")


if __name__ == "__main__":
    main()
