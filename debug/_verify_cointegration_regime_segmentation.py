"""
Synthetic verification of research/cointegration_regime_segmentation.py's
segment_regimes() -- run BEFORE trusting it on the real 1.2M-row Tier 3
windows file. This is genuinely new code (the hysteresis regime-boundary
logic), not a parameter tweak, so it gets the full synthetic treatment per
this project's standing discipline.

Checks:
  1. A single clean regime (all p-values below alpha) -> exactly 1 span.
  2. A clean, sustained transition (coint -> not_coint, both runs well past
     min_regime_windows) -> exactly 2 spans, boundary at the right index.
  3. A single-window noise blip (does NOT meet min_regime_windows) does NOT
     create a new regime -- the surrounding "coint" state should absorb it,
     producing 1 span, not 3.
  4. A short-lived but REAL regime (meets min_regime_windows exactly) DOES
     get its own span -- 3 spans, not 1.
  5. Strength gradation: a "coint" span with a known p-value distribution
     buckets into strong/moderate/weak via terciles as expected.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from research.cointegration_regime_segmentation import segment_regimes, assign_strength_terciles


def _make_df(pvalues):
    dates = pd.date_range("2010-01-01", periods=len(pvalues), freq="YS")
    return pd.DataFrame({"window_end_date": dates, "pvalue": pvalues})


def main():
    failures = []

    # --- 1: single clean regime ---
    df1 = _make_df([0.01] * 15)
    spans1 = segment_regimes(df1, alpha=0.05, min_regime_windows=3)
    if len(spans1) != 1 or spans1[0]["state"] != "coint":
        failures.append(f"Check 1: expected 1 coint span, got {spans1}")

    # --- 2: clean sustained transition ---
    df2 = _make_df([0.01] * 10 + [0.90] * 10)
    spans2 = segment_regimes(df2, alpha=0.05, min_regime_windows=3)
    if len(spans2) != 2:
        failures.append(f"Check 2: expected 2 spans, got {len(spans2)}: {spans2}")
    else:
        if spans2[0]["state"] != "coint" or spans2[1]["state"] != "not_coint":
            failures.append(f"Check 2: wrong states, got {[s['state'] for s in spans2]}")
        if spans2[0]["n_windows"] != 10 or spans2[1]["n_windows"] != 10:
            failures.append(f"Check 2: wrong span lengths, got "
                             f"{[s['n_windows'] for s in spans2]}")

    # --- 3: single-window noise blip absorbed, no new regime ---
    df3 = _make_df([0.01] * 10 + [0.90] + [0.01] * 10)
    spans3 = segment_regimes(df3, alpha=0.05, min_regime_windows=3)
    if len(spans3) != 1:
        failures.append(f"Check 3: expected 1 span (blip absorbed), got {len(spans3)}: {spans3}")
    elif spans3[0]["n_windows"] != 21:
        failures.append(f"Check 3: expected all 21 windows in one span, got {spans3[0]['n_windows']}")

    # --- 4: short-lived but real regime (exactly meets min_regime_windows) ---
    df4 = _make_df([0.01] * 10 + [0.90] * 3 + [0.01] * 10)
    spans4 = segment_regimes(df4, alpha=0.05, min_regime_windows=3)
    if len(spans4) != 3:
        failures.append(f"Check 4: expected 3 spans (real short regime), got {len(spans4)}: {spans4}")
    elif [s["state"] for s in spans4] != ["coint", "not_coint", "coint"]:
        failures.append(f"Check 4: wrong state sequence, got {[s['state'] for s in spans4]}")

    # --- 5: GLOBAL strength gradation via terciles (across multiple pairs'
    # spans -- per-pair terciles were a real bug, caught running against real
    # data: most real pairs have 0-1 coint spans, so per-pair terciles are
    # meaningless. assign_strength_terciles() operates on the COMBINED
    # spans_df across all pairs, matching how main() actually calls it.) ---
    df5a = _make_df([0.001] * 5)   # pair A: one strong coint span
    df5b = _make_df([0.03] * 5)    # pair B: one weaker coint span
    df5c = _make_df([0.045] * 5)   # pair C: one weakest coint span
    spans5 = []
    for pair_id, pdf in (("A", df5a), ("B", df5b), ("C", df5c)):
        for s in segment_regimes(pdf, alpha=0.05, min_regime_windows=3):
            s["pair"] = pair_id
            spans5.append(s)
    spans5_df = pd.DataFrame(spans5)
    out5 = assign_strength_terciles(spans5_df)
    strength_by_pair = dict(zip(out5["pair"], out5["strength"]))
    if strength_by_pair != {"A": "strong", "B": "moderate", "C": "weak"}:
        failures.append(f"Check 5: expected A=strong, B=moderate, C=weak (global terciles across "
                         f"pairs), got {strength_by_pair}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All cointegration regime-segmentation checks passed.")
    print(f"  Check 1 (single regime): {len(spans1)} span")
    print(f"  Check 2 (clean transition): {len(spans2)} spans")
    print(f"  Check 3 (noise blip absorbed): {len(spans3)} span")
    print(f"  Check 4 (real short regime): {len(spans4)} spans")
    print(f"  Check 5 (global strength terciles): {strength_by_pair}")


if __name__ == "__main__":
    main()
