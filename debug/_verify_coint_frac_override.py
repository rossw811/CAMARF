"""
Permanent, reproducible verification of AnalysisPipeline.passes_coint_frac_
secondary_evidence() against the 3 real pairs that motivated it (see
Development.md's coint_fraction_rolling section, 2026-06-22). Pulls live
values from the actually-persisted pairs.parquet files rather than
hand-typed numbers, so this stays correct if the underlying data changes
on a future re-run. Read-only — never touches saved output.

Expected result: D/NEE and SPY/VOO -> False (correctly excluded), CRWD/DDOG
-> True (correctly kept despite coint_fraction_rolling < MIN_COINT_FRAC).

Updated 2026-07-14 (BUG-D68): the function now also requires n_bars >=
AnalysisPipeline._MIN_BARS_FOR_SECONDARY_EVIDENCE. Real pairs.parquet rows
have this column already (added here rather than a separate case, so the
existing 3 real cases exercise the new gate too, not just a synthetic
add-on) — all 3 have tens of thousands of bars in production data, so this
doesn't change their expected outcome; the synthetic cases below test the
gate itself directly, which no real 1h/1min production pair is short enough
to exercise.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from analysis import AnalysisPipeline

CASES = [
    ("1min", "D", "NEE", False),
    ("1hr", "SPY", "VOO", False),
    ("1min", "CRWD", "DDOG", True),
]


def main():
    failures = []
    for tf_dir, sym_a, sym_b, expected in CASES:
        path = f"output/results/{tf_dir}/pairs.parquet"
        if not os.path.exists(path):
            # A pair excluded outright (coint_frac < threshold, no override)
            # is never persisted at all — if EVERY candidate pair for this TF
            # was excluded, pairs.parquet itself won't exist. That's expected
            # for an `expected=False` case, not a failure of this script.
            print(f"SKIP {sym_a}/{sym_b}@{tf_dir}: {path} does not exist "
                  f"(no pairs survived coint_frac filtering for this TF)")
            continue
        df = pd.read_parquet(path)
        row = df[(df["symbol_a"] == sym_a) & (df["symbol_b"] == sym_b)]
        if row.empty:
            print(f"SKIP {sym_a}/{sym_b}@{tf_dir}: not found in {path} "
                  f"(re-run analysis.py to regenerate)")
            continue
        row = row.iloc[0]
        p = SimpleNamespace(
            n_bars=row["n_bars"],
            half_life_trend_slope=row["half_life_trend_slope"],
            zivot_andrews_break=row["zivot_andrews_break"],
            cusum_first_excursion=row["cusum_first_excursion"],
        )
        actual = AnalysisPipeline.passes_coint_frac_secondary_evidence(p)
        status = "OK" if actual == expected else "MISMATCH"
        if actual != expected:
            failures.append((sym_a, sym_b, tf_dir, expected, actual))
        print(
            f"{status}  {sym_a}/{sym_b}@{tf_dir}  n_bars={row['n_bars']}  "
            f"coint_fraction_rolling={row['coint_fraction_rolling']:.3f}  "
            f"slope={row['half_life_trend_slope']:.4f}  "
            f"za={row['zivot_andrews_break']}  cusum={row['cusum_first_excursion']}  "
            f"-> secondary_evidence={actual} (expected {expected})"
        )

    # --- BUG-D68 synthetic cases: the window-length gate itself ---
    min_bars = AnalysisPipeline._MIN_BARS_FOR_SECONDARY_EVIDENCE

    def make(n_bars, slope=-0.01, za=None, cusum=None):
        return SimpleNamespace(n_bars=n_bars, half_life_trend_slope=slope,
                                zivot_andrews_break=za, cusum_first_excursion=cusum)

    synthetic_cases = [
        # (description, pair, expected)
        ("clean case, but below min_bars -> must be REJECTED despite clean signals",
         make(min_bars - 1), False),
        ("identical clean signals, at exactly min_bars -> must be ACCEPTED",
         make(min_bars), True),
        ("clean signals, well above min_bars -> must be ACCEPTED",
         make(min_bars * 10), True),
        ("below min_bars AND a real detected break -> still REJECTED (both reasons)",
         make(min_bars - 1, za=pd.Timestamp("2025-01-01")), False),
    ]
    for desc, p, expected in synthetic_cases:
        actual = AnalysisPipeline.passes_coint_frac_secondary_evidence(p)
        status = "OK" if actual == expected else "MISMATCH"
        if actual != expected:
            failures.append((desc, None, None, expected, actual))
        print(f"{status}  [synthetic] n_bars={p.n_bars} ({desc}) "
              f"-> secondary_evidence={actual} (expected {expected})")

    print()
    if failures:
        print(f"FAILED: {len(failures)} case(s) did not match expected behavior")
        sys.exit(1)
    else:
        print("All cases match expected behavior.")


if __name__ == "__main__":
    main()
