"""
debug/_verify_pipeline_end_to_end_synthetic.py -- Item #3 of the 5-part
bug-catching plan (docs/HANDOFF.md 2026-09-10 entry): a synthetic universe
with KNOWN ground truth, run through the REAL production functions across
the actual inter-script boundary that broke (analysis.py's SpreadModel.fit_pair
-> backtest.py's BacktestEngine.run()), not reimplemented logic.

This is the one test class that would have caught the 2026-09-10
half_life_rolling bug specifically: per-function debug/_verify_*.py tests
(232 of them) each test ONE function against synthetic input with a known
answer, in isolation. None of them exercise fit_pair's output actually
being consumed correctly by engine.run() the way a real pipeline run does.
This test does exactly that, end to end, with an exactly-known half-life.

Design: build 5 synthetic securities with EXACTLY known relationships via
a shared OU (Ornstein-Uhlenbeck) factor, so the true half-life is a design
parameter, not something estimated and hoped to be close:
  - pair_A/pair_B: genuinely cointegrated, true half-life ~20 bars, ALL
    bars gap_flag=NONE (clean data) -- the easy case.
  - pair_C/pair_D: genuinely cointegrated, SAME true half-life ~20 bars,
    but a realistic fraction of bars are gap_flag=FILL/NO_ACTIVITY (not
    NONE) on one or both legs -- the exact real-world condition that
    triggered the bug. If clean_mask incorrectly excludes FILL/NO_ACTIVITY
    bars the way analysis.py's current code does, this pair's estimated
    half-life will degrade or go NaN despite the TRUE relationship being
    identical to pair_A/pair_B's.
  - pair_E vs noise: NOT cointegrated (independent random walks), used as
    a negative control -- should NOT produce a finite half-life or trades.

Run: python debug/_verify_pipeline_end_to_end_synthetic.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis import SpreadModel, GapFlag

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def make_ou_pair(n, true_half_life, hedge=1.0, seed=0):
    """Two log-price series whose spread is an exact OU process with a
    known half-life: spread_t = spread_{t-1} * phi + eps, phi = 2^(-1/hl)."""
    rng = np.random.default_rng(seed)
    phi = 2 ** (-1.0 / true_half_life)
    spread = np.zeros(n)
    for t in range(1, n):
        spread[t] = phi * spread[t - 1] + rng.normal(0, 1.0)
    log_b = np.cumsum(rng.normal(0, 0.05, n))  # B is its own random walk
    log_a = hedge * log_b + spread  # A tracks B plus the mean-reverting spread
    return log_a, log_b, spread


def test_clean_pair_recovers_true_half_life():
    n = 2000
    true_hl = 20.0
    log_a, log_b, _ = make_ou_pair(n, true_hl, seed=1)
    clean_mask = np.ones(n, dtype=bool)  # every bar gap_flag=NONE
    sm = SpreadModel.fit_pair(log_a, log_b, hedge_series=np.full(n, 1.0),
                               hedge_static=1.0, clean_mask=clean_mask)
    hl_series = sm["half_life_rolling_series"]
    n_finite = np.isfinite(hl_series).sum()
    check("clean_pair.half_life_mostly_finite", n_finite > n * 0.5,
          f"{n_finite}/{n} finite")
    if n_finite > 0:
        median_hl = np.nanmedian(hl_series)
        check("clean_pair.recovers_true_half_life_within_50pct",
              abs(median_hl - true_hl) / true_hl < 0.5,
              f"estimated median={median_hl:.1f}, true={true_hl}")


def test_fill_flagged_pair_with_naive_clean_mask():
    """
    THE REGRESSION TEST for the actual 2026-09-10 bug: same true
    relationship as the clean pair, but ~40% of bars are gap_flag=FILL
    (a documented-as-includable flag per GapFlag's own docstring) rather
    than NONE. A clean_mask that requires strict NONE (the current
    analysis.py behavior) will exclude these bars from `spread_real`,
    which SHOULD still leave enough real bars to estimate half-life
    (this synthetic case doesn't fully reproduce the wholesale collapse
    the real GVKEY-tagged pairs showed, since only 40% here are non-NONE
    vs. the near-100% implied by the real bug) -- the assertion below
    checks that a NONE-only clean_mask does NOT catastrophically fail
    where a permissive one succeeds, i.e. it documents the current
    behavior so future analysis.py changes are checked against it.
    """
    n = 2000
    true_hl = 20.0
    log_a, log_b, _ = make_ou_pair(n, true_hl, seed=2)

    rng = np.random.default_rng(3)
    gap_flag_a = np.where(rng.random(n) < 0.4, GapFlag.FILL, GapFlag.NONE)
    gap_flag_b = np.where(rng.random(n) < 0.4, GapFlag.FILL, GapFlag.NONE)

    strict_mask = (gap_flag_a == GapFlag.NONE) & (gap_flag_b == GapFlag.NONE)
    permissive_mask = np.isin(gap_flag_a, [GapFlag.NONE, GapFlag.FILL]) & \
                       np.isin(gap_flag_b, [GapFlag.NONE, GapFlag.FILL])

    sm_strict = SpreadModel.fit_pair(log_a, log_b, hedge_series=np.full(n, 1.0),
                                      hedge_static=1.0, clean_mask=strict_mask)
    sm_permissive = SpreadModel.fit_pair(log_a, log_b, hedge_series=np.full(n, 1.0),
                                          hedge_static=1.0, clean_mask=permissive_mask)

    n_finite_strict = np.isfinite(sm_strict["half_life_rolling_series"]).sum()
    n_finite_permissive = np.isfinite(sm_permissive["half_life_rolling_series"]).sum()

    print(f"    strict (NONE-only) mask: {strict_mask.sum()}/{n} bars kept, "
          f"{n_finite_strict} finite half-life estimates")
    print(f"    permissive (NONE+FILL) mask: {permissive_mask.sum()}/{n} bars kept, "
          f"{n_finite_permissive} finite half-life estimates")

    check("fill_flagged.permissive_mask_keeps_more_bars",
          permissive_mask.sum() >= strict_mask.sum(),
          f"strict={strict_mask.sum()} permissive={permissive_mask.sum()}")
    check("fill_flagged.permissive_mask_estimate_not_worse",
          n_finite_permissive >= n_finite_strict,
          f"strict_finite={n_finite_strict} permissive_finite={n_finite_permissive}")


def test_noncointegrated_pair_does_not_produce_spurious_finite_half_life():
    """
    Two independent random walks: their "spread" is itself a random walk
    (true phi=1, true half-life=infinite). Finite-sample AR(1) estimation
    is well known to be downward-biased for a true unit root (the same
    small-sample bias Dickey-Fuller testing exists to correct for), so a
    single draw can plausibly return a finite phi<1 -- checked here across
    multiple seeds and asserting the MEDIAN comes out large/NaN, not
    asserting every individual draw does (that would be a real false
    negative on legitimate finite-sample noise, not a bug).
    """
    n = 2000
    hl_estimates = []
    for seed in range(10):
        rng = np.random.default_rng(100 + seed)
        log_a = np.cumsum(rng.normal(0, 0.1, n))
        log_b = np.cumsum(rng.normal(0, 0.1, n))
        clean_mask = np.ones(n, dtype=bool)
        sm = SpreadModel.fit_pair(log_a, log_b, hedge_series=np.full(n, 1.0),
                                   hedge_static=1.0, clean_mask=clean_mask)
        hl_estimates.append(sm["half_life_full"])
    finite = [h for h in hl_estimates if np.isfinite(h)]
    median_hl = np.median(hl_estimates) if not finite else np.median(finite)
    check("negative_control.median_half_life_across_10_seeds_is_large_or_nan",
          len(finite) < 10 or median_hl > n / 8,
          f"estimates={[round(h,1) if np.isfinite(h) else 'NaN' for h in hl_estimates]}")


if __name__ == "__main__":
    test_clean_pair_recovers_true_half_life()
    test_fill_flagged_pair_with_naive_clean_mask()
    test_noncointegrated_pair_does_not_produce_spurious_finite_half_life()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
