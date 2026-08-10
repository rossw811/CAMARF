"""
research/episodic_duration_degree_usability.py -- Thread B of the CAMARF master plan
(C:\\Users\\RossW\\.claude\\plans\\ancient-mixing-feather.md).

Directly answers Ross's request: "run the test for at what length of time and degree of
cointegration is it actually accurate and usable for us." Distinct from Step 1's
intraday_episodic_window_sensitivity.py (which tested rolling-WINDOW WIDTH/step for a new
scanner) -- this tests the EPISODIC CONFIRMATION's own two knobs, DURATION
(`min_windows_confirmed` -- how many confirming windows a pair needs) and DEGREE
(`alpha` -- how strict the significance bar is), against REAL forward usability rather
than just in-sample statistical confirmation.

Follows research/coint_frac_window_grid.py's existing, already-verified precedent exactly
(same early/late split + REQUIRED overfitting guard pattern -- reused, not reinvented):
grid over candidate configs, score each on a predictive task using only early data, then a
mandatory held-out-pairs overfitting check before trusting any "winning" cell.

DATA SOURCE AND GROUND-TRUTH DESIGN (a real choice, disclosed plainly): rather than
re-loading raw WRDS price data for an independent late-period EG test (coint_frac_window_
grid.py's approach), this reuses the episodic scan's OWN window-level output
(wrds_deep_history_episodic_scan_tier{2,3}_windows.parquet -- real, on disk, no re-run
needed) and splits each pair's tested windows chronologically into an EARLY 70% (used to
decide "confirmed" under a given (min_windows_confirmed, alpha) grid cell) and a LATE 30%
(ground truth: did the relationship show real significance going forward). Ground truth is
FIXED and independent of the grid being swept (>=1 late window with raw pvalue < 0.05) --
using a parametrized ground truth would make the accuracy comparison circular. This design
choice is more consistent with the episodic methodology itself (the same rolling-window EG
machinery, not a different single-shot test mixed in) than re-deriving a fresh raw-data test
would be, and avoids a real re-fetch/re-load cost.

REQUIRED overfitting guard (not optional, matching coint_frac_window_grid.py's own
discipline): pairs are split into two disjoint halves; the best grid cell is SELECTED on one
half and its accuracy is REPORTED on the other, untouched half. A large in-sample-vs-held-out
gap is itself the finding and is reported, not hidden.

Usage:
    python research/episodic_duration_degree_usability.py
    python research/episodic_duration_degree_usability.py --sources tier2 tier3
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.wrds_deep_history_episodic_scan import episodic_bhfdr_confirm

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")

_MIN_WINDOWS_CONFIRMED_GRID = [1, 2, 3, 5]
_ALPHA_GRID = [0.01, 0.05, 0.10]
_EARLY_FRACTION = 0.70
_MIN_WINDOWS_PER_PAIR = 4  # need enough windows to make an early/late split meaningful
_GROUND_TRUTH_ALPHA = 0.05  # fixed, independent of the grid -- avoids circularity


def load_window_rows(sources):
    rows = []
    for source in sources:
        path = os.path.join(_OUT_DIR, f"wrds_deep_history_episodic_scan_{source}_windows.parquet")
        if not os.path.exists(path):
            print(f"SKIP {source}: {path} not found")
            continue
        df = pd.read_parquet(path)
        rows.extend(df.to_dict("records"))
    return rows


def build_pair_data(all_rows):
    """Groups flat window rows by pair, splits each pair's own windows
    chronologically into early (70%) / late (30%). Returns a list of dicts,
    each with early_rows/late_rows (flat row lists) and ground_truth_held_up
    (fixed, independent of the grid)."""
    by_pair = {}
    for r in all_rows:
        if r.get("window_end_date") is None:
            continue
        key = (r["symbol_a"], r["symbol_b"])
        by_pair.setdefault(key, []).append(r)

    out = []
    for (sym_a, sym_b), rows in by_pair.items():
        rows_sorted = sorted(rows, key=lambda r: r["window_end_date"])
        if len(rows_sorted) < _MIN_WINDOWS_PER_PAIR:
            continue
        split_idx = max(1, int(len(rows_sorted) * _EARLY_FRACTION))
        early_rows = rows_sorted[:split_idx]
        late_rows = rows_sorted[split_idx:]
        if not early_rows or not late_rows:
            continue
        ground_truth_held_up = any(r["pvalue"] < _GROUND_TRUTH_ALPHA for r in late_rows)
        out.append({
            "symbol_a": sym_a, "symbol_b": sym_b,
            "early_rows": early_rows, "late_rows": late_rows,
            "ground_truth_held_up": ground_truth_held_up,
        })
    return out


def score_cell(pair_data, min_windows_confirmed, alpha, subset=None):
    """PRECISION/RECALL (not raw accuracy) of (min_windows_confirmed, alpha)
    over pair_data (or a named index subset of it). Confirms jointly across
    ALL pairs' early_rows (episodic_bhfdr_confirm's own joint-BH-FDR design
    requires this -- confirming one pair at a time would be a different,
    weaker test).

    Raw accuracy was tried first and rejected: ground truth is only ~8%
    positive (most candidate pairs genuinely aren't real relationships), so
    a trivial "always predict not-confirmed" baseline already scores ~92%
    accuracy by matching the majority class -- confirmed directly by
    computing it before trusting this metric. PRECISION -- of the pairs
    this cell would confirm, what fraction actually held up forward -- is
    the metric that actually answers "is it accurate and usable": if we're
    deciding whether to trade a pair because it was episodically confirmed,
    precision is exactly "how often is that confirmation trustworthy."
    RECALL is reported alongside, honestly, since a precision-only report
    would hide a cell that achieves high precision by confirming almost
    nothing (recall near zero) -- not silently a "good" cell just because
    its few predictions are usually right.

    Returns (precision, recall, n_confirmed, n_scored, per_pair_rows)."""
    data = pair_data if subset is None else [pair_data[i] for i in subset]
    if not data:
        return None, None, 0, 0, []

    early_flat = []
    for d in data:
        early_flat.extend(d["early_rows"])
    confirmed = episodic_bhfdr_confirm(early_flat, alpha, min_windows_confirmed)
    confirmed_keys = {(c["symbol_a"], c["symbol_b"]) for c in confirmed}

    rows = []
    true_positives = 0
    n_predicted_confirmed = 0
    n_actual_held_up = 0
    for d in data:
        key = (d["symbol_a"], d["symbol_b"])
        predicted_confirmed = key in confirmed_keys
        actual_held_up = d["ground_truth_held_up"]
        if predicted_confirmed:
            n_predicted_confirmed += 1
        if actual_held_up:
            n_actual_held_up += 1
        if predicted_confirmed and actual_held_up:
            true_positives += 1
        rows.append({
            "symbol_a": d["symbol_a"], "symbol_b": d["symbol_b"],
            "min_windows_confirmed": min_windows_confirmed, "alpha": alpha,
            "predicted_confirmed": predicted_confirmed, "actual_held_up": actual_held_up,
        })
    precision = true_positives / n_predicted_confirmed if n_predicted_confirmed > 0 else None
    recall = true_positives / n_actual_held_up if n_actual_held_up > 0 else None
    return precision, recall, n_predicted_confirmed, len(data), rows


def main():
    p = argparse.ArgumentParser(description="Episodic confirmation duration/degree usability test")
    p.add_argument("--sources", nargs="+", default=["tier2", "tier3"], choices=["tier2", "tier3"])
    args = p.parse_args()

    all_rows = load_window_rows(args.sources)
    print(f"Loaded {len(all_rows)} raw window rows from sources={args.sources}")
    pair_data = build_pair_data(all_rows)
    n = len(pair_data)
    print(f"{n} pairs have >= {_MIN_WINDOWS_PER_PAIR} windows for an early/late split")
    if n < 8:
        print("Too few pairs with sufficient data for a meaningful grid -- stopping.")
        return

    # A cell that confirms almost nothing can win on precision alone with a
    # tiny, unreliable sample (seen directly: (5,0.10) confirmed only 10/
    # 202,257 pairs). Require a minimum confirmed-count floor for a cell to
    # be ELIGIBLE as "best" -- reported for every cell regardless, just not
    # eligible to be silently selected as the recommendation.
    _MIN_N_CONFIRMED_FOR_ELIGIBILITY = 20

    print(f"\n{'='*70}\nDURATION x DEGREE GRID (min_windows_confirmed x alpha)\n{'='*70}")
    joint_results = {}
    for mwc in _MIN_WINDOWS_CONFIRMED_GRID:
        for alpha in _ALPHA_GRID:
            precision, recall, n_confirmed, scored, _ = score_cell(pair_data, mwc, alpha)
            joint_results[(mwc, alpha)] = (precision, recall, n_confirmed, scored)
            print(f"  min_windows_confirmed={mwc} alpha={alpha:.2f}: "
                  f"precision={precision} recall={recall} n_confirmed={n_confirmed}/{n}")
    eligible = {k: v for k, v in joint_results.items()
                if v[0] is not None and v[2] >= _MIN_N_CONFIRMED_FOR_ELIGIBILITY}
    if not eligible:
        print(f"WARNING: no cell confirms >= {_MIN_N_CONFIRMED_FOR_ELIGIBILITY} pairs -- "
              f"the whole grid is too sparse to recommend from at this data scale.")
    best_cell = max(eligible, key=lambda k: eligible[k][0]) if eligible else None
    print(f"In-sample-recommended (min_windows_confirmed, alpha), among cells confirming "
          f">= {_MIN_N_CONFIRMED_FOR_ELIGIBILITY} pairs: {best_cell} "
          f"(precision {eligible.get(best_cell, (None,))[0]})")

    print(f"\n{'='*70}\nOVERFITTING GUARD -- select on half A, score on held-out half B\n{'='*70}")
    rng = np.random.RandomState(42)
    idx = list(range(n))
    rng.shuffle(idx)
    half = n // 2
    half_a, half_b = idx[:half], idx[half:]
    print(f"Split: {len(half_a)} pairs in half A (selection), {len(half_b)} pairs in half B (held-out)")

    half_a_results = {}
    for mwc in _MIN_WINDOWS_CONFIRMED_GRID:
        for alpha in _ALPHA_GRID:
            precision, recall, n_confirmed, scored, _ = score_cell(pair_data, mwc, alpha, subset=half_a)
            half_a_results[(mwc, alpha)] = (precision, recall, n_confirmed, scored)
    eligible_a = {k: v for k, v in half_a_results.items()
                  if v[0] is not None and v[2] >= _MIN_N_CONFIRMED_FOR_ELIGIBILITY}
    best_on_a = max(eligible_a, key=lambda k: eligible_a[k][0]) if eligible_a else None
    print(f"Best cell selected on half A: {best_on_a} "
          f"(half-A precision {eligible_a.get(best_on_a, (None,))[0]})")

    if best_on_a is not None:
        held_out_precision, held_out_recall, held_out_n_confirmed, held_out_n, _ = \
            score_cell(pair_data, *best_on_a, subset=half_b)
        print(f"Held-out half-B precision for that SAME cell: {held_out_precision} "
              f"(n_confirmed={held_out_n_confirmed}/{held_out_n})")
        gap = (eligible_a[best_on_a][0] - held_out_precision) if held_out_precision is not None else None
        print(f"In-sample-selected vs held-out precision gap: {gap} "
              f"({'overfitting risk' if gap is not None and gap > 0.10 else 'no strong overfitting signal'})")
    else:
        held_out_precision = None
        gap = None

    os.makedirs(_OUT_DIR, exist_ok=True)
    result_df = pd.DataFrame([
        {"min_windows_confirmed": k[0], "alpha": k[1], "precision": v[0], "recall": v[1],
         "n_confirmed": v[2], "n_scored": v[3]}
        for k, v in joint_results.items()
    ])
    result_df["best_cell_full"] = str(best_cell)
    result_df["best_cell_half_a"] = str(best_on_a)
    result_df["held_out_half_b_precision"] = held_out_precision
    result_df["overfitting_gap"] = gap
    out_path = os.path.join(_OUT_DIR, "episodic_duration_degree_usability.parquet")
    result_df.to_parquet(out_path)
    print(f"\nWrote {out_path}")
    return result_df


if __name__ == "__main__":
    main()
