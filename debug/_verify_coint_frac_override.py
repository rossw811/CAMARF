"""
Permanent, reproducible verification of AnalysisPipeline.passes_coint_frac_
secondary_evidence() against the 3 real pairs that motivated it (see
Development.md's coint_fraction_rolling section, 2026-06-22). Pulls live
values from the actually-persisted pairs.parquet files rather than
hand-typed numbers, so this stays correct if the underlying data changes
on a future re-run. Read-only — never touches saved output.

Expected result: D/NEE and SPY/VOO -> False (correctly excluded), CRWD/DDOG
-> True (correctly kept despite coint_fraction_rolling < MIN_COINT_FRAC).
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
        df = pd.read_parquet(path)
        row = df[(df["symbol_a"] == sym_a) & (df["symbol_b"] == sym_b)]
        if row.empty:
            print(f"SKIP {sym_a}/{sym_b}@{tf_dir}: not found in {path} "
                  f"(re-run analysis.py to regenerate)")
            continue
        row = row.iloc[0]
        p = SimpleNamespace(
            half_life_trend_slope=row["half_life_trend_slope"],
            zivot_andrews_break=row["zivot_andrews_break"],
            cusum_first_excursion=row["cusum_first_excursion"],
        )
        actual = AnalysisPipeline.passes_coint_frac_secondary_evidence(p)
        status = "OK" if actual == expected else "MISMATCH"
        if actual != expected:
            failures.append((sym_a, sym_b, tf_dir, expected, actual))
        print(
            f"{status}  {sym_a}/{sym_b}@{tf_dir}  "
            f"coint_fraction_rolling={row['coint_fraction_rolling']:.3f}  "
            f"slope={row['half_life_trend_slope']:.4f}  "
            f"za={row['zivot_andrews_break']}  cusum={row['cusum_first_excursion']}  "
            f"-> secondary_evidence={actual} (expected {expected})"
        )

    print()
    if failures:
        print(f"FAILED: {len(failures)} case(s) did not match expected behavior")
        sys.exit(1)
    else:
        print("All cases match expected behavior.")


if __name__ == "__main__":
    main()
