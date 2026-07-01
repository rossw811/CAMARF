"""
Reproducible regeneration of the coint_fraction_rolling threshold
sensitivity table behind config.py's Config.UNIVERSE.MIN_COINT_FRAC = 0.70
decision (see Development.md's coint_fraction_rolling section, 2026-06-22).
Pulls real values from the currently-persisted pairs.parquet files —
result will track whatever analysis.py last actually confirmed, not a
frozen snapshot. Read-only.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

_TF_DIRS = ["1min", "2min", "3min", "5min", "15min", "30min", "1hr", "4hr", "1day", "7day", "1mo", "3mo", "6mo"]


def main():
    rows = []
    for tf in _TF_DIRS:
        path = f"output/results/{tf}/pairs.parquet"
        if not os.path.exists(path):
            continue
        df = pd.read_parquet(path)
        rows.append(df[["symbol_a", "symbol_b", "coint_fraction_rolling"]].assign(tf=tf))
    if not rows:
        print("No pairs.parquet files found — run analysis.py first.")
        return

    out = pd.concat(rows, ignore_index=True).sort_values("coint_fraction_rolling")
    n_total = len(out)
    n_nan = out["coint_fraction_rolling"].isna().sum()
    print(f"{n_total} confirmed pairs total, {n_nan} with NaN coint_fraction_rolling "
          f"(exempt from this filter by design at any threshold)\n")
    print(out.to_string(index=False))

    print("\nSensitivity (counts among the non-NaN pairs only):")
    real = out.dropna(subset=["coint_fraction_rolling"])
    for thresh in [0.40, 0.50, 0.60, 0.70, 0.80, 0.90]:
        n = (real["coint_fraction_rolling"] >= thresh).sum()
        print(f"  threshold {thresh:.2f}: {n}/{len(real)} survive")


if __name__ == "__main__":
    main()
