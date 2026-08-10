"""
CAMARF research/trig_convergence.py -- comparison/diagnostic script, NOT
part of the production pipeline (2026-08-03).

Ross's framing: take a bounded metric CAMARF already computes and map it
onto trig identities to look for convergence/divergence, and/or use trig
for a graphed relationship (a phase-portrait-style visualization).

WHERE THIS SITS RELATIVE TO WHAT ALREADY EXISTS -- stated plainly rather
than oversold as a wholly new capability, because it mostly is not one:
  - Pearson correlation (analysis.py's own correlation matrices) already
    IS cos(theta) -- the cosine of the angle between two demeaned return
    vectors in n-dimensional space. This module does not add that; it was
    already true of every correlation number this project has ever
    computed.
  - research/cycle_detection.py's rolling PLV is already the trig-identity
    form of phase synchronization by construction:
    PLV = |mean(cos(dphi)) + i*mean(sin(dphi))|, an average over the
    complex unit circle derived from the Hilbert transform's instantaneous
    phase. This module does not duplicate that.

WHAT IS ACTUALLY NEW HERE: mapping the bounded [-1,1] polarity scores
already built in research/inverse_polarity.py onto an ANGLE (via arccos or
arcsin -- both built and compared, per Ross's explicit request), then using
a sum-to-product trig identity to decompose the raw polarity DIFFERENCE
into two interpretable multiplicative factors:

  arccos mapping (theta = arccos(p), theta in [0, pi], cos(theta) = p):
      p_A - p_B = cos(theta_A) - cos(theta_B)
                = -2 * sin((theta_A + theta_B) / 2) * sin((theta_A - theta_B) / 2)
      "co-movement" term:  sin((theta_A + theta_B) / 2)
      "divergence" term:   sin((theta_A - theta_B) / 2)

  arcsin mapping (theta = arcsin(p), theta in [-pi/2, pi/2], sin(theta) = p):
      p_A - p_B = sin(theta_A) - sin(theta_B)
                = 2 * cos((theta_A + theta_B) / 2) * sin((theta_A - theta_B) / 2)
      "co-movement" term:  cos((theta_A + theta_B) / 2)
      "divergence" term:   sin((theta_A - theta_B) / 2)

These are EXACT algebraic identities, not approximations or new
information -- p_A - p_B is fully recovered by multiplying the two factors
back together (verified in debug/_verify_trig_convergence.py to
floating-point precision).

**A design error caught by synthetic verification before this ever touched
real data, worth recording rather than quietly fixing** (per CLAUDE.md rule
8): the first draft of this module claimed a true polar-opposite pair
(p_B = -p_A always) produces theta_A - theta_B stationary near +/-pi under
BOTH mappings, and proposed trading DRIFT in that difference as the "break"
signal. That is only true exactly AT the extremes (p=+/-1); for an
oscillating pair -- the realistic case -- it is false. The identities
arccos(-x) = pi - arccos(x) and arcsin(-x) = -arcsin(x) mean that for a
perfect opposite pair, theta_A - theta_B = 2*theta_A - pi (arccos) or
2*theta_A (arcsin) -- NOT constant, it swings across the full range as the
pair cycles. What actually IS constant for a true polar-opposite pair is
the SUM: theta_A + theta_B = pi (arccos, always) or = 0 (arcsin, always),
regardless of where in the cycle the pair currently sits. This means the
CO-MOVEMENT factor (built from the half-SUM) is the real polar-opposite
invariant -- when it stays pinned near its expected extreme, the pair is
holding the opposite-extremes relationship; when it drifts away, the
relationship is breaking down. The DIVERGENCE factor (half-DIFFERENCE) is
NOT a break indicator -- it tracks where the pair currently sits within an
(assumed still-valid) cycle, closer to a phase-position indicator than a
health check. The tradeable signal is therefore built on co_movement's
drift from its theoretical constant, not on the divergence term.

Usage:
    python research/trig_convergence.py
    python research/trig_convergence.py --window 60
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from aligned_pair_loader import load_aligned_pair
from inverse_polarity import (
    zscore_tanh_polarity,
    percentile_rank_polarity,
    POLARITY_METRICS,
)
import ml

ANGLE_MAPPINGS = ("arccos", "arcsin")


def to_angle(polarity: np.ndarray, mapping: str) -> np.ndarray:
    """Map a bounded [-1,1] polarity score to an angle. Pointwise (not
    windowed) -- causality is inherited directly from whatever causal
    series is passed in, since arccos/arcsin apply independently to each
    bar with no lookback or lookahead of their own."""
    p = np.clip(polarity, -1.0, 1.0)
    if mapping == "arccos":
        return np.arccos(p)
    if mapping == "arcsin":
        return np.arcsin(p)
    raise ValueError(f"unknown angle mapping: {mapping}")


def trig_decompose(theta_a: np.ndarray, theta_b: np.ndarray, mapping: str) -> dict:
    """Sum-to-product decomposition of the polarity difference implied by
    (theta_a, theta_b). Returns co_movement, divergence, and a
    reconstruction check (co_movement/divergence recombined should equal
    the original polarity difference to floating precision -- this is an
    exact identity, not a fit)."""
    half_sum = (theta_a + theta_b) / 2.0
    half_diff = (theta_a - theta_b) / 2.0
    if mapping == "arccos":
        co_movement = np.sin(half_sum)
        divergence = np.sin(half_diff)
        reconstructed_diff = -2.0 * co_movement * divergence  # cos(a)-cos(b)
    elif mapping == "arcsin":
        co_movement = np.cos(half_sum)
        divergence = np.sin(half_diff)
        reconstructed_diff = 2.0 * co_movement * divergence  # sin(a)-sin(b)
    else:
        raise ValueError(f"unknown angle mapping: {mapping}")
    return {
        "co_movement": co_movement,
        "divergence": divergence,
        "reconstructed_diff": reconstructed_diff,
        "angle_diff": theta_a - theta_b,
    }


_MIN_STD_FLOOR = 1e-6  # see docstring "numerical stability" note below


def opposite_equilibrium_break_signal(co_movement: np.ndarray, mapping: str, window: int = 60) -> np.ndarray:
    """CAUSAL rolling z-score of co_movement against its own trailing
    history. co_movement = sin((theta_A+theta_B)/2) [arccos] or
    cos((theta_A+theta_B)/2) [arcsin] is the actual polar-opposite
    invariant (theta_A+theta_B is algebraically constant -- pi for arccos,
    0 for arcsin -- for a true opposite pair, REGARDLESS of where in the
    cycle either leg currently sits; see module docstring for the design
    error this corrects). A true polar-opposite pair should have
    co_movement pinned near its theoretical extreme (sin(pi/2)=1 for
    arccos, cos(0)=1 for arcsin) and STAY there; large deviations are drift
    away from the expected opposite-extremes relationship -- this is the
    actual break/health signal, not a function of theta_A - theta_B.

    NUMERICAL STABILITY (found comparing real KVUE/KMB output across
    mappings, 2026-08-03): co_movement is PROVABLY IDENTICAL between
    arccos and arcsin (verified to ~5e-16, machine precision) -- so this
    function's output should be mapping-invariant too. In practice, real
    data showed a real discrepancy (12343 vs 13536 finite bars out of the
    same series) traced to the rolling std denominator: in the exact
    regime this module cares about most (co_movement pinned near-constant,
    i.e. a genuine polar-opposite pair), the true rolling variance is at
    or below float64 noise, so which side of exactly-zero the computed std
    lands on differs by mapping due to the ~5e-16 rounding difference in
    co_movement itself -- one side divides by ~0 (NaN), the other by a
    tiny-but-nonzero epsilon (a huge but finite spike). Floored at
    _MIN_STD_FLOOR (well above float64 noise, far below any real economic
    variance in a [-1,1]-bounded series) so both mappings agree and the
    signal degrades gracefully (bounded, not NaN) instead of blowing up,
    exactly where it matters most."""
    s = pd.Series(co_movement)
    mu = s.rolling(window, min_periods=max(2, window // 2)).mean()
    sd = s.rolling(window, min_periods=max(2, window // 2)).std(ddof=1)
    sd = sd.clip(lower=_MIN_STD_FLOOR)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (s - mu) / sd
    return z.values


def main():
    p = argparse.ArgumentParser(description="CAMARF trig-identity convergence/divergence comparison arm")
    p.add_argument("--window", type=int, default=60)
    p.add_argument("--pit-safe", action="store_true",
                    help="Source pairs from the PIT-safe episodic screen (research/"
                         "pit_pair_discovery.py, task #5) instead of ml._discover_confirmed_pairs().")
    args = p.parse_args()

    if args.pit_safe:
        from pit_pair_discovery import discover_pit_confirmed_pairs
        pairs = discover_pit_confirmed_pairs()
        print(f"Using PIT-safe episodic pair discovery: {len(pairs)} pairs")
    else:
        pairs = ml._discover_confirmed_pairs()
    if not pairs:
        print("No confirmed pairs found -- nothing to analyze. Run analysis.py first.")
        return

    print(f"Analyzing {len(pairs)} confirmed pairs across {len(ANGLE_MAPPINGS)} angle mappings "
          f"x 2 polarity metrics (zscore_tanh, percentile_rank -- eg_spread_zscore needs a "
          f"pair-specific spread series, skipped in this universe-agnostic pass)...")
    rows = []
    for symbol_a, symbol_b, tf_label in pairs:
        df_a, df_b = load_aligned_pair(symbol_a, symbol_b, tf_label)
        if df_a is None or df_b is None:
            continue
        common_idx = df_a.index.intersection(df_b.index)
        df_a, df_b = df_a.loc[common_idx], df_b.loc[common_idx]
        if len(df_a) < args.window:
            continue

        log_a = np.log(df_a["close"].values.astype(float))
        log_b = np.log(df_b["close"].values.astype(float))

        for metric_name, metric_fn in (
            ("zscore_tanh", zscore_tanh_polarity),
            ("percentile_rank", lambda x, w: percentile_rank_polarity(np.exp(x), w)),
        ):
            pol_a = metric_fn(log_a, args.window)
            pol_b = metric_fn(log_b, args.window)
            for mapping in ANGLE_MAPPINGS:
                theta_a = to_angle(pol_a, mapping)
                theta_b = to_angle(pol_b, mapping)
                decomp = trig_decompose(theta_a, theta_b, mapping)
                sig = opposite_equilibrium_break_signal(decomp["co_movement"], mapping, args.window)

                expected_sum = np.pi if mapping == "arccos" else 0.0
                angle_sum = theta_a + theta_b
                finite = np.isfinite(angle_sum)
                mean_sum_deviation = float(np.nanmean(np.abs(angle_sum[finite] - expected_sum))) if finite.any() else np.nan
                rows.append({
                    "symbol_a": symbol_a, "symbol_b": symbol_b, "tf_label": tf_label,
                    "metric": metric_name, "mapping": mapping,
                    "mean_theta_sum_deviation_from_invariant": mean_sum_deviation,
                    "mean_break_signal_abs_z": float(np.nanmean(np.abs(sig[np.isfinite(sig)]))) if np.isfinite(sig).any() else np.nan,
                })
        print(f"  {symbol_a}/{symbol_b}@{tf_label}: done")

    out_df = pd.DataFrame(rows)
    out_dir = os.path.join("output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "trig_convergence.parquet")
    out_df.to_parquet(out_path)
    print(f"Done. {len(out_df)} (pair, metric, mapping) rows. Saved -> {out_path}")
    if len(out_df):
        print(out_df.to_string(index=False))


if __name__ == "__main__":
    main()
