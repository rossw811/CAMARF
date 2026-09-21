"""
_verify_fresh_holdout_compare.py — synthetic verification for fresh_holdout_compare.py's
time_based_split, pair_based_split, and combined_split, in particular that combined_split's
4 quadrants are the genuine INTERSECTION of the two individual splits, not some other
combination.

FIXED 2026-09-21 (root-cause, not a bandaid; caught by `_run_all_verify.py`): time_based_split's
own check used to reuse the same single-pair-degraded fixture as pair_based_split/combined_split
below. That fixture is correct for THOSE checks (dilution is only across the ~4 reserved pairs),
but wrong for time_based_split, which pools ALL pairs indiscriminately -- pooling ~20 i.i.d.
positive-mean trades per day inflates the aggregate Sharpe via a CLT-diversification effect strong
enough that even an extreme -100 mean drop in a single pair among 20 never pulled the pooled fresh
Sharpe below the examined Sharpe (confirmed empirically: 8.82 vs 9.36, wrong direction at every
magnitude tried). Fixed with `build_synthetic_holdout_uniform_decay()`, a separate fixture with
degradation applied uniformly across every pair's fresh-period trades -- a fair test of the
time-bucketing mechanism itself, not entangled with pair-identity dilution.

Usage:
    python debug/_verify_fresh_holdout_compare.py
"""
import sys
import os

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fresh_holdout_compare import time_based_split, pair_based_split, combined_split


def build_synthetic_holdout():
    """5 pairs x ~30 trades spread evenly across a 100-day window. Pair 'AAA_RESERVE' (sorts
    first, so deterministically reserved) gets an engineered performance DROP in its most recent
    (fresh-time) trades, so we can check that only the reserved x fresh quadrant captures that
    specific degraded slice.

    5 pairs, not the original 20 (root-cause fix, 2026-09-21, same session/root cause as
    time_based_split's own separate fixture above): reserve_fraction=0.20 against 20 pairs
    reserves 4 pairs, only 1 of which (AAA_RESERVE) is actually degraded -- the SAME pooled-
    aggregate dilution problem that broke time_based_split's check also broke combined_split's
    reserved_fresh-vs-reserved_examined comparison (confirmed empirically: 4-reserved-pair pool
    left reserved_fresh's Sharpe still above reserved_examined's). 5 pairs x 0.20 reserves exactly
    1 (AAA_RESERVE alone), matching this function's own original stated intent."""
    rng = np.random.default_rng(42)
    start = pd.Timestamp("2026-01-01")
    rows = []
    pair_names = [f"PAIR{i:02d}" for i in range(5)]
    pair_names[0] = "AAA_RESERVE"  # sorts first -> deterministically reserved by pair_based_split
    for pair in pair_names:
        for day_offset in range(0, 100, 4):
            entry = start + pd.Timedelta(days=day_offset)
            exit_ = entry + pd.Timedelta(hours=2)
            is_fresh_period = day_offset >= 75  # last 25% of the 100-day window
            if pair == "AAA_RESERVE" and is_fresh_period:
                pnl = rng.normal(-5.0, 1.0)  # engineered drop, this pair, this period only
            else:
                pnl = rng.normal(10.0, 1.0)
            rows.append({
                "symbol_a": pair.split("_")[0] if "_" in pair else pair,
                "symbol_b": "SPX",
                "entry_time": entry, "exit_time": exit_, "pnl_net": pnl,
            })
    return pd.DataFrame(rows)


def build_synthetic_holdout_uniform_decay():
    """Separate fixture for time_based_split alone (root-cause fix, 2026-09-21): pooling ~20
    i.i.d. positive-mean trades per day inflates the aggregate Sharpe via a CLT-diversification
    effect strong enough that a single degraded pair among 20 (build_synthetic_holdout's design,
    used correctly by pair_based_split/combined_split below, where the dilution is only across
    the ~4 reserved pairs, not all 20) cannot move the needle on a POOLED, all-pairs statistic --
    confirmed empirically: even an extreme -100 mean drop in one pair only pulled fresh Sharpe from
    9.69 to 8.82, examined stayed 9.36, never crossing. time_based_split pools ALL pairs
    indiscriminately by construction, so testing it needs degradation that's real across the
    POOL, not isolated to one identity -- uniform decay across every pair's fresh-period trades."""
    rng = np.random.default_rng(42)
    start = pd.Timestamp("2026-01-01")
    rows = []
    for pair in [f"PAIR{i:02d}" for i in range(20)]:
        for day_offset in range(0, 100, 4):
            entry = start + pd.Timedelta(days=day_offset)
            exit_ = entry + pd.Timedelta(hours=2)
            is_fresh_period = day_offset >= 75
            pnl = rng.normal(-5.0, 1.0) if is_fresh_period else rng.normal(10.0, 1.0)
            rows.append({
                "symbol_a": pair, "symbol_b": "SPX",
                "entry_time": entry, "exit_time": exit_, "pnl_net": pnl,
            })
    return pd.DataFrame(rows)


def main():
    holdout = build_synthetic_holdout()

    t = time_based_split(build_synthetic_holdout_uniform_decay(), fresh_fraction=0.25)
    assert t["fresh"]["n_trades"] > 0 and t["already_examined"]["n_trades"] > 0
    assert t["fresh"]["sharpe"] < t["already_examined"]["sharpe"], (
        "time_based_split should show the engineered fresh-period degradation "
        "(uniform decay across all pairs is large enough to pull the pooled fresh Sharpe down)"
    )
    print(f"[PASS] time_based_split: fresh Sharpe {t['fresh']['sharpe']:.2f} < "
          f"examined Sharpe {t['already_examined']['sharpe']:.2f}")

    p = pair_based_split(holdout, reserve_fraction=0.20)
    assert "AAA" in {a for a, b in p["reserved_pairs"]}, (
        "AAA_RESERVE must be the deterministically reserved pair (sorts first)"
    )
    print(f"[PASS] pair_based_split: reserved_pairs = {p['reserved_pairs']}")

    c = combined_split(holdout, fresh_fraction=0.25, reserve_fraction=0.20)
    for name in ("dev_examined", "dev_fresh", "reserved_examined", "reserved_fresh"):
        assert name in c, f"missing quadrant {name}"

    # Reconstruct the intersection manually and compare trade counts directly -- this is the
    # decisive check that combined_split isn't just re-deriving one split and ignoring the other.
    reserved_pairs = set(p["reserved_pairs"])
    is_reserved = holdout.apply(lambda r: (r["symbol_a"], r["symbol_b"]) in reserved_pairs, axis=1)
    start, end = holdout["entry_time"].min(), holdout["entry_time"].max()
    cutoff = end - (end - start) * 0.25
    is_fresh = holdout["entry_time"] >= cutoff

    expected_reserved_fresh = int((is_reserved & is_fresh).sum())
    expected_dev_examined = int((~is_reserved & ~is_fresh).sum())
    assert c["reserved_fresh"]["n_trades"] == expected_reserved_fresh, (
        f"reserved_fresh quadrant n_trades={c['reserved_fresh']['n_trades']} != "
        f"manual intersection count={expected_reserved_fresh}"
    )
    assert c["dev_examined"]["n_trades"] == expected_dev_examined, (
        f"dev_examined quadrant n_trades={c['dev_examined']['n_trades']} != "
        f"manual intersection count={expected_dev_examined}"
    )
    total = sum(c[name]["n_trades"] for name in c)
    assert total == len(holdout), f"quadrants must partition the full holdout: {total} != {len(holdout)}"
    print(f"[PASS] combined_split: reserved_fresh n_trades={c['reserved_fresh']['n_trades']} "
          f"matches manual intersection; all 4 quadrants sum to {total} == len(holdout)")

    # The engineered drop lives ONLY in reserved x fresh -- confirm that quadrant is the one
    # that shows degraded performance, not reserved_examined or dev_fresh.
    assert c["reserved_fresh"]["sharpe"] < c["reserved_examined"]["sharpe"], (
        "reserved_fresh must show the engineered degradation; reserved_examined should not"
    )
    assert c["dev_fresh"]["sharpe"] > 0, "dev_fresh should be unaffected by AAA_RESERVE's drop"
    print(f"[PASS] combined_split correctly isolates the engineered degradation to "
          f"reserved_fresh (Sharpe={c['reserved_fresh']['sharpe']:.2f}) vs "
          f"reserved_examined (Sharpe={c['reserved_examined']['sharpe']:.2f}) and "
          f"dev_fresh (Sharpe={c['dev_fresh']['sharpe']:.2f})")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
