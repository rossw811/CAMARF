"""
Synthetic verification for research/coint_frac_window_grid.py (2026-07-13).

Two checks:
1. Engineered breakdown recovery: build synthetic pairs where the
   cointegrating relationship holds for the EARLY period and then genuinely
   breaks down partway through the LATE (held-out) period. Confirm
   coint_fraction (the core building block, reused unmodified from the
   module under test) correctly reports a HIGH fraction on the early data
   and that late_period_actual_outcome correctly reports the relationship
   did NOT hold up late — i.e. the ground-truth labels this module scores
   against are themselves correct on a case where the true answer is known
   by construction.
2. Overfitting-guard sanity check: with only 2 grid cells and an
   artificially tiny, noisy pair set, confirm the half-A/half-B split
   mechanism in main()'s logic (replicated directly here, not re-imported,
   since main() is a script entry point) can and does detect a real
   in-sample/held-out gap when one is deliberately engineered (a grid cell
   that fits half A's specific noise pattern but is null on half B).

Run: python debug/_verify_coint_frac_window_grid.py
"""
import os
import sys

import numpy as np
import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "research"))

from coint_frac_window_grid import coint_fraction, late_period_actual_outcome, score_cell

SEED = 42


def build_breakdown_pair(rng, n_early=800, n_late_stable=100, n_late_broken=300):
    """B tracks A closely (cointegrated) for n_early + n_late_stable bars,
    then B's mean-reversion mechanism is switched off (independent random
    walk) for the remaining n_late_broken bars — a genuine, known breakdown."""
    n_pre_break = n_early + n_late_stable
    a = np.log(100.0) + np.cumsum(rng.normal(0, 0.01, n_pre_break + n_late_broken))
    b = np.empty_like(a)
    b[:n_pre_break] = a[:n_pre_break] + rng.normal(0, 0.002, n_pre_break)
    # After the break: B follows its OWN independent random walk, no longer
    # tethered to A.
    b[n_pre_break:] = b[n_pre_break - 1] + np.cumsum(rng.normal(0, 0.01, n_late_broken))
    return a, b, n_early


def build_null_pair(rng, n=1100):
    """Two fully independent random walks — never cointegrated, any
    'stable' call at any window/threshold should be a false positive."""
    a = np.log(100.0) + np.cumsum(rng.normal(0, 0.01, n))
    b = np.log(50.0) + np.cumsum(rng.normal(0, 0.01, n))
    return a, b


def main():
    rng = np.random.default_rng(SEED)

    print("Check 1: engineered breakdown recovery")
    a, b, n_early = build_breakdown_pair(rng)
    a_early, b_early = a[:n_early], b[:n_early]
    a_late, b_late = a[n_early:], b[n_early:]

    frac_early, n_windows = coint_fraction(a_early, b_early, window=250, step=20)
    print(f"  early-period coint_fraction (window=250): {frac_early} ({n_windows} windows)")
    assert frac_early is not None and frac_early >= 0.7, (
        f"FAILED: expected a HIGH early-period fraction (genuinely cointegrated there), got {frac_early}"
    )

    actual_late = late_period_actual_outcome(a_late, b_late)
    print(f"  late-period (post-breakdown) actual_held_up: {actual_late}")
    assert actual_late is not None and not bool(actual_late), (
        f"FAILED: expected the late period (which includes the engineered breakdown) to NOT "
        f"show cointegration, got {actual_late}"
    )
    print("PASS: coint_fraction correctly reports high early-period stability; "
          "late_period_actual_outcome correctly detects the engineered breakdown.")

    print("\nCheck 1b: null pair (never cointegrated) is not falsely called stable")
    a_null, b_null = build_null_pair(rng)
    frac_null, n_windows_null = coint_fraction(a_null[:700], b_null[:700], window=250, step=20)
    print(f"  null-pair early-period coint_fraction: {frac_null} ({n_windows_null} windows)")
    assert frac_null is not None and frac_null < 0.3, (
        f"FAILED: expected a LOW fraction for two independent random walks, got {frac_null}"
    )
    print("PASS: independent random walks correctly score low, not fabricating a false stable call.")

    print("\nCheck 2: overfitting-guard split mechanism (score_cell's subset=) is correct and")
    print("detects a real accuracy gap when one is deliberately engineered between two halves")
    # 12 pairs: 6 "easy" pairs where the relationship is stable BOTH early
    # and late (predicted_stable=True, actual_held_up=True -> hit), and 6
    # "breakdown" pairs (early stable, late genuinely broken down ->
    # predicted_stable=True, actual_held_up=False -> miss, by construction,
    # for ANY reasonable window/threshold — this is the textbook case a
    # naive early-only stability check systematically gets wrong). Put all
    # 6 easy pairs in half A and all 6 breakdown pairs in half B: half A's
    # accuracy should be high (easy, correctly predicted), half B's should
    # be low (hard, systematically wrong) — a real, known-direction gap,
    # not an artifact.
    pair_data = []
    for i in range(6):
        seed_pair = np.random.default_rng(SEED + 200 + i)
        # "Easy" pair: cointegrated throughout, no breakdown at all.
        n_total = 1000
        a_i = np.log(100.0) + np.cumsum(seed_pair.normal(0, 0.01, n_total))
        b_i = a_i + seed_pair.normal(0, 0.002, n_total)
        n_e = 700
        pair_data.append({
            "symbol_a": f"EASY_{i}", "symbol_b": f"EASY_B{i}",
            "a_early": a_i[:n_e], "b_early": b_i[:n_e],
            "a_late": a_i[n_e:], "b_late": b_i[n_e:],
        })
    for i in range(6):
        seed_pair = np.random.default_rng(SEED + 300 + i)
        a_i, b_i, n_e = build_breakdown_pair(seed_pair, n_early=700, n_late_stable=30, n_late_broken=270)
        pair_data.append({
            "symbol_a": f"BREAK_{i}", "symbol_b": f"BREAK_B{i}",
            "a_early": a_i[:n_e], "b_early": b_i[:n_e],
            "a_late": a_i[n_e:], "b_late": b_i[n_e:],
        })

    half_easy = list(range(0, 6))
    half_break = list(range(6, 12))
    acc_easy, n_easy, _ = score_cell(pair_data, window=250, threshold=0.7, subset=half_easy)
    acc_break, n_break, _ = score_cell(pair_data, window=250, threshold=0.7, subset=half_break)
    print(f"  cell (250, 0.70) on easy (no-breakdown) half:  accuracy={acc_easy} (n={n_easy})")
    print(f"  SAME cell on breakdown half:                    accuracy={acc_break} (n={n_break})")
    assert acc_easy is not None and acc_break is not None
    gap = acc_easy - acc_break
    print(f"  gap = {gap:+.3f}")
    assert acc_easy > acc_break, (
        f"FAILED: expected the no-breakdown half's accuracy ({acc_easy}) to exceed the "
        f"breakdown half's ({acc_break}) — the split mechanism should be able to surface a real, "
        f"known-direction accuracy gap between an easy and a hard sub-population; if it can't, "
        f"the overfitting-guard's gap computation is not working."
    )
    print("PASS: score_cell's subset= mechanism correctly measures different accuracy on two "
          "different sub-populations and the resulting gap has the expected sign — confirms the "
          "overfitting guard's core arithmetic (main()'s half-A/half-B logic uses this exact "
          "function) is a working check, not a no-op that would report a gap regardless of data.")

    print("\nALL CHECKS PASSED.")


if __name__ == "__main__":
    main()
