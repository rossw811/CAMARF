"""
research/pit_precision_by_regime_strength.py -- Thread J follow-up: does PIT
confirmation's precision (Finding #23) differ by regime STRENGTH (Finding
#28), not just regime presence/absence? Confirmed independent of Thread J
Test 1 (window-size sweep) -- uses only already-complete Finding #23/#28
outputs, no new expensive scan needed.

Reuses Finding #23's own methodology directly (imports build_pair_data/
score_cell from episodic_duration_degree_usability.py, not reimplemented)
at its recommended cell (min_windows_confirmed=3, alpha=0.10), then joins
each CONFIRMED pair against Finding #28's regime segments
(cointegration_regime_segments.parquet) to find which regime-strength
bucket (strong/moderate/weak) its EARLY-PERIOD cointegrated span falls
into -- "early period" matched exactly to Finding #23's own early/late
split (the regime span used must overlap the EARLY window range only, to
avoid leaking late-period/ground-truth information into the strength
label).

Question this answers: among pairs the methodology confirms, does
precision (does the confirmation actually hold up forward) differ between
pairs confirmed during a STRONG cointegration regime vs. a WEAK one? If PIT
confirmation is already implicitly capturing regime strength, precision
should be flat across strength buckets (the confirmation gate doesn't need
strength info, it already works). If precision differs meaningfully by
strength, that's real evidence a strength-aware confidence tier (already
motivated by Session 31's "Tiered" arm being currently degenerate, see
docs/FINDINGS.md's Step 5 writeup) would add real value beyond what BH-FDR
confirmation alone captures.

Uses ONLY the Tier 3 source (Tier 2 excluded from PIT-safe methodology per
BUG-D112 -- same scope as every post-fix Finding #23 retest this session).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from research.episodic_duration_degree_usability import (
    load_window_rows, build_pair_data, score_cell,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")
_SEGMENTS_PATH = os.path.join(_OUT_DIR, "cointegration_regime_segments.parquet")
_OUT_PATH = os.path.join(_OUT_DIR, "pit_precision_by_regime_strength.parquet")

_MIN_WINDOWS_CONFIRMED = 3  # Finding #23's own recommended cell
_ALPHA = 0.10


def early_regime_strength(pair_key, early_rows, segments_df):
    """Finds the pair's EARLY-PERIOD coint regime strength: among Finding
    #28's 'coint' spans for this pair, take the one(s) overlapping the
    early_rows' own date range (min to max window_end_date), and return the
    strength of whichever span covers the LATEST early-period date (most
    relevant to the confirmation decision, which happens at the end of the
    early period). Returns None if no coint span overlaps the early period
    at all (the pair was never in a detected coint regime early on, despite
    getting confirmed by the raw BH-FDR test -- itself informative)."""
    sym_a, sym_b = pair_key
    pair_segments = segments_df[
        (segments_df["symbol_a"] == sym_a) & (segments_df["symbol_b"] == sym_b)
        & (segments_df["state"] == "coint")
    ]
    if pair_segments.empty:
        return None
    early_dates = [r["window_end_date"] for r in early_rows]
    early_min, early_max = min(early_dates), max(early_dates)
    overlapping = pair_segments[
        (pair_segments["start_date"] <= early_max) & (pair_segments["end_date"] >= early_min)
    ]
    if overlapping.empty:
        return None
    latest = overlapping.sort_values("end_date").iloc[-1]
    return latest["strength"]


def main():
    if not os.path.exists(_SEGMENTS_PATH):
        print(f"FATAL: {_SEGMENTS_PATH} not found -- run cointegration_regime_segmentation.py first")
        sys.exit(1)
    segments_df = pd.read_parquet(_SEGMENTS_PATH)
    print(f"Loaded {len(segments_df)} regime segments")

    rows = load_window_rows(["tier3"])
    print(f"Loaded {len(rows)} Tier 3 window rows (Tier 2 excluded, BUG-D112 scope)")
    pair_data = build_pair_data(rows)
    print(f"{len(pair_data)} pairs with a valid early/late split")

    precision, recall, n_confirmed, n_scored, per_pair_rows = score_cell(
        pair_data, _MIN_WINDOWS_CONFIRMED, _ALPHA
    )
    print(f"Overall (pooled) precision at cell ({_MIN_WINDOWS_CONFIRMED}, {_ALPHA}): "
          f"{precision:.4f} ({n_confirmed}/{n_scored} confirmed)")

    pair_data_by_key = {(d["symbol_a"], d["symbol_b"]): d for d in pair_data}
    out_rows = []
    for r in per_pair_rows:
        if not r["predicted_confirmed"]:
            continue
        key = (r["symbol_a"], r["symbol_b"])
        d = pair_data_by_key[key]
        strength = early_regime_strength(key, d["early_rows"], segments_df)
        out_rows.append({
            "symbol_a": key[0], "symbol_b": key[1],
            "early_regime_strength": strength,
            "actual_held_up": r["actual_held_up"],
        })

    out_df = pd.DataFrame(out_rows)
    out_df.to_parquet(_OUT_PATH, index=False)
    print(f"\n{len(out_df)} confirmed pairs, saved -> {_OUT_PATH}\n")

    print("=== Precision by early-period regime strength ===")
    out_df["early_regime_strength"] = out_df["early_regime_strength"].fillna("no_detected_regime")
    summary = out_df.groupby("early_regime_strength")["actual_held_up"].agg(["mean", "count"])
    summary.columns = ["precision", "n_confirmed_pairs"]
    print(summary.to_string())


if __name__ == "__main__":
    main()
