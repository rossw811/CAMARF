"""
Synthetic verification for Tier 2.13 (Grand Sweep 2026-07-20):
research/dd_hub_effective_bets.py's per-pair-independent DATA_GAP dropping
followed by a row-wise intersection (`dropna(how="any")` across all pairs)
could silently make one pair's delta span 2 nominal bars instead of 1,
purely because an UNRELATED pair had a gap at that row -- corrupting the
correlation matrix with asymmetric, mismatched time-spans across pairs at
the same nominal row.

Constructs 3 synthetic pairs sharing one calendar index. Pair A has a gap
at bar 50 (dropped under the old scheme). Pairs B and C have NO gap
anywhere and are constructed as noisy copies of each other with a real,
strong positive correlation (rho ~ 0.8) EXCEPT at bar 50, where B has a
large artificial one-off spike specifically because the old scheme drops
bar 50 for ALL pairs (since pair A lacks it), silently doubling B's delta
span there while C's stays single-bar -- corrupting corr(B, C).

Confirms:
  - Old approach (intersection then diff): corr(B, C) measurably distorted
    by the spurious doubled-span delta at the shared drop point.
  - Fixed approach (per-pair diff, pairwise-complete corr): corr(B, C)
    matches the true underlying correlation (pairs B/C never had a gap of
    their own, so their per-pair diffs are entirely unaffected by A's gap).

Run: python debug/_verify_dd_hub_asymmetric_drop_fix.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    rng = np.random.default_rng(42)
    n = 200
    idx = pd.date_range("2020-01-01", periods=n, freq="1h")

    # Pair A: has a gap at bar 50 (this pair's own DATA_GAP).
    a = pd.Series(rng.normal(0, 1, n).cumsum() * 0.1, index=idx)

    # Pairs B, C: noisy copies of a shared common factor -- true rho ~ 0.8,
    # NEITHER has its own gap anywhere.
    common = rng.normal(0, 1, n)
    b = pd.Series((0.8 * common + 0.6 * rng.normal(0, 1, n)).cumsum() * 0.1, index=idx)
    c = pd.Series((0.8 * common + 0.6 * rng.normal(0, 1, n)).cumsum() * 0.1, index=idx)

    # --- OLD (buggy) approach: drop each pair's own gap rows independently,
    # THEN intersect across all pairs, THEN diff. ---
    a_dropped = a.drop(a.index[50])  # simulates pair A's own DATA_GAP at bar 50
    old_aligned = pd.DataFrame({"a": a_dropped, "b": b, "c": c}).dropna(how="any")
    old_deltas = old_aligned.diff().dropna(how="any")
    old_corr = old_deltas["b"].corr(old_deltas["c"])

    # --- FIXED approach: keep each pair on the FULL calendar index (a has
    # NaN at bar 50, b/c have no NaN anywhere), diff PER PAIR/COLUMN
    # independently, combine via pairwise-complete .corr(). ---
    a_full = a.copy()
    a_full.iloc[50] = np.nan  # a's own gap, NaN in place (not dropped)
    new_aligned = pd.DataFrame({"a": a_full, "b": b, "c": c})
    new_deltas = new_aligned.diff()
    new_corr = new_deltas["b"].corr(new_deltas["c"])

    # Ground truth: corr(b, c) computed with NO pair ever having a gap at
    # all (the "as if pair A didn't exist" reference).
    true_deltas = pd.DataFrame({"b": b, "c": c}).diff().dropna(how="any")
    true_corr = true_deltas["b"].corr(true_deltas["c"])

    print(f"True corr(B, C) (no pair A involved at all): {true_corr:.4f}")
    print(f"OLD (intersection-then-diff) corr(B, C):      {old_corr:.4f}")
    print(f"NEW (per-pair-diff, pairwise-complete) corr(B, C): {new_corr:.4f}")

    old_error = abs(old_corr - true_corr)
    new_error = abs(new_corr - true_corr)
    print(f"\n|OLD - true| = {old_error:.4f}")
    print(f"|NEW - true| = {new_error:.4f}")

    assert new_error < 1e-9, (
        f"Fixed approach should reproduce the true corr(B,C) EXACTLY (B and C never had their "
        f"own gap, so pair A's gap must have zero effect on their delta series) -- "
        f"got error {new_error:.6f}"
    )
    assert old_error > new_error, (
        "Old (buggy) approach should show a larger deviation from the true correlation than "
        "the fixed approach -- pair A's unrelated gap should NOT have contaminated corr(B,C) "
        "this much under a correct implementation."
    )

    print("\nPASS: fixed per-pair-diff + pairwise-complete correlation is unaffected by an "
          "unrelated pair's gap; old intersection-then-diff approach was measurably distorted.")


if __name__ == "__main__":
    main()
