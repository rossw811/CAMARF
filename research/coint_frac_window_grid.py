"""
CAMARF coint_frac_window_grid.py — exploratory diagnostic, NOT part of the
production pipeline.

Extends `CointScanner.rolling_fraction()` (analysis.py, ~line 1492) — the
already-validated `coint_fraction_rolling` diagnostic behind MIN_COINT_FRAC
(config.py, 0.70) — along one new dimension: is the CURRENT fixed choice
(window=252 bars, threshold=0.70) actually the best available combination
for predicting whether a pair's cointegrating relationship holds up on
FUTURE data, or just the first one that was tried?

Two grid modes, built and compared per Ross's explicit direction (2026-07-13):
  (a) Window-length sweep: fix threshold at the current production value
      (0.70), sweep window length only.
  (b) Joint grid: sweep window length AND threshold together.

Both are scored on the SAME predictive task: using only the EARLY 70% of
each confirmed pair's available history, compute coint_fraction_rolling
(does this window/threshold combo call the pair "stable"?); then check
against the LATE, held-out 30% whether the pair's cointegration ACTUALLY
held up there (single EG test on the held-out slice, p<0.05 = held up).
"Predictive accuracy" = fraction of confirmed pairs where the early-period
stable/unstable call matches the late-period actual outcome.

REQUIRED overfitting guard (not optional): whichever grid cell scores best
is itself selected using the SAME 24 confirmed pairs it's evaluated on — a
textbook multiple-comparisons setup. This module additionally splits the 24
confirmed pairs into two disjoint halves (even a small, honestly-flagged
n=12/12 split is far better than none): the best cell is SELECTED on one
half and its accuracy is reported on the OTHER, untouched half. A large
gap between in-sample-selected and held-out accuracy IS the overfitting
finding and is reported as such, not hidden. Given n=24 total confirmed
pairs, this check itself is thin (n=12 per half) — flagged explicitly as a
real, honestly-reported limitation of the check, not a reason to skip it.

Read-only. Loads cached price data via aligned_pair_loader.load_aligned_pair
(gap-flag-aware, DataAligner-based — see that module's docstring for why a
raw join is not safe for this project's data).

Usage:
    python research/coint_frac_window_grid.py
    python research/coint_frac_window_grid.py --tf 1h
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aligned_pair_loader import load_aligned_pair
from data import _clean_close

_MANIFEST_PATH = os.path.join("output", "results", "confirmed_pairs_manifest.json")
_PROD_THRESHOLD = 0.70  # matches config.py Config.UNIVERSE.MIN_COINT_FRAC
_WINDOW_GRID = [250, 500, 1000, 1500]  # bars; ~1mo,2mo,4mo,6mo at 1h; project's own
                                        # docstring precedent labels these loosely
                                        # (252 bars ~= "1yr" is analysis.py's own
                                        # comment for DAILY bars — at 1h these are
                                        # much shorter spans; grid values themselves
                                        # are what matters, not their calendar label)
_THRESHOLD_GRID = [0.50, 0.60, 0.70, 0.80]
_EARLY_FRACTION = 0.70
_STEP_DIVISOR = 12  # step = window // 12, keeps window/step ratio consistent
                     # with production's 252/21 ~= 12


def _log_price(df):
    close = _clean_close(df)
    with np.errstate(invalid="ignore", divide="ignore"):
        lp = np.log(close)
    lp[~np.isfinite(lp)] = np.nan
    return lp


def coint_fraction(a, b, window, step):
    """Same test as analysis.py's _rolling_coint_worker: fraction of rolling
    windows where EG p<0.05. Reused logic, not reimplemented differently."""
    mask = np.isfinite(a) & np.isfinite(b)
    a_, b_ = a[mask], b[mask]
    n = a_.size
    if n < window + step:
        return None, 0
    n_sig = n_win = 0
    for start in range(0, n - window + 1, step):
        aw, bw = a_[start:start + window], b_[start:start + window]
        try:
            _t, p, _c = coint(aw, bw, trend="c", maxlag=1, autolag=None)
            if p < 0.05:
                n_sig += 1
            n_win += 1
        except Exception:
            continue
    if n_win == 0:
        return None, 0
    return n_sig / n_win, n_win


def late_period_actual_outcome(a, b):
    """Ground truth on the held-out late slice: single EG test, p<0.05 = the
    relationship actually held up there."""
    mask = np.isfinite(a) & np.isfinite(b)
    a_, b_ = a[mask], b[mask]
    if a_.size < 60:
        return None
    try:
        _t, p, _c = coint(a_, b_, trend="c", maxlag=1, autolag="aic")
        return p < 0.05
    except Exception:
        return None


def load_confirmed_pairs(tf_label):
    tf_dir_map = {
        "1m": "1min", "2m": "2min", "3m": "3min", "5m": "5min", "15m": "15min",
        "30m": "30min", "1h": "1hr", "4h": "4hr", "7D": "7day", "1M": "1mo",
        "3M": "3mo", "6M": "6mo",
    }
    tf_dir = tf_dir_map.get(tf_label, tf_label)
    path = os.path.join("output", "results", tf_dir, "pairs.parquet")
    if not os.path.exists(path):
        return []
    df = pd.read_parquet(path)
    return list(zip(df["symbol_a"], df["symbol_b"]))


def build_pair_data(pairs, tf_label):
    """For each pair, load aligned log-price arrays split into early/late."""
    out = []
    for sym_a, sym_b in pairs:
        df_a, df_b = load_aligned_pair(sym_a, sym_b, tf_label)
        if df_a is None or df_b is None:
            continue
        joined = pd.concat(
            [pd.Series(_log_price(df_a), index=df_a.index),
             pd.Series(_log_price(df_b), index=df_b.index)],
            axis=1, join="inner"
        ).dropna()
        n = len(joined)
        if n < 200:
            continue
        split = int(n * _EARLY_FRACTION)
        a_early, b_early = joined.iloc[:split, 0].values, joined.iloc[:split, 1].values
        a_late, b_late = joined.iloc[split:, 0].values, joined.iloc[split:, 1].values
        out.append({
            "symbol_a": sym_a, "symbol_b": sym_b,
            "a_early": a_early, "b_early": b_early,
            "a_late": a_late, "b_late": b_late,
        })
    return out


def score_cell(pair_data, window, threshold, subset=None):
    """Predictive accuracy of (window, threshold) over pair_data (or a named
    subset of it). Returns (accuracy, n_scored, per_pair_rows)."""
    data = pair_data if subset is None else [pair_data[i] for i in subset]
    rows = []
    correct = 0
    scored = 0
    for pd_row in data:
        step = max(5, window // _STEP_DIVISOR)
        frac, n_windows = coint_fraction(pd_row["a_early"], pd_row["b_early"], window, step)
        if frac is None:
            continue
        predicted_stable = frac >= threshold
        actual_held_up = late_period_actual_outcome(pd_row["a_late"], pd_row["b_late"])
        if actual_held_up is None:
            continue
        hit = (predicted_stable == actual_held_up)
        correct += int(hit)
        scored += 1
        rows.append({
            "symbol_a": pd_row["symbol_a"], "symbol_b": pd_row["symbol_b"],
            "window": window, "threshold": threshold, "early_frac": frac,
            "predicted_stable": predicted_stable, "actual_held_up": actual_held_up, "hit": hit,
        })
    acc = correct / scored if scored > 0 else None
    return acc, scored, rows


def main():
    p = argparse.ArgumentParser(description="coint_fraction_rolling window/threshold grid (2026-07-13)")
    p.add_argument("--tf", default="1h")
    p.add_argument("--pit-safe", action="store_true",
                    help="Source pairs from research/pit_pair_discovery.py's PIT-safe episodic "
                         "screen instead of production's pairs.parquet at --tf (task #5). Filtered "
                         "to pairs confirmed at this exact tf_label, same per-TF scoping the "
                         "production path already uses.")
    args = p.parse_args()

    if args.pit_safe:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from pit_pair_discovery import discover_pit_confirmed_pairs
        pit_pairs = discover_pit_confirmed_pairs()
        pairs = sorted(set((a, b) for a, b, tf in pit_pairs if tf == args.tf))
        print(f"Using PIT-safe episodic pair discovery: {len(pairs)} pairs at tf={args.tf}")
    else:
        pairs = load_confirmed_pairs(args.tf)
    if not pairs:
        print(f"No {'PIT-safe' if args.pit_safe else 'confirmed'} pairs found at tf={args.tf}.")
        return
    pair_data = build_pair_data(pairs, args.tf)
    n = len(pair_data)
    print(f"{n}/{len(pairs)} confirmed pairs have sufficient early+late data at tf={args.tf}.")
    if n < 8:
        print("Too few pairs with sufficient data for a meaningful grid — stopping.")
        return

    # --- (a) Window-length sweep, threshold fixed at production value ---
    print(f"\n{'='*70}\n(a) WINDOW-LENGTH SWEEP (threshold fixed at production {_PROD_THRESHOLD})\n{'='*70}")
    sweep_results = {}
    for w in _WINDOW_GRID:
        acc, scored, _ = score_cell(pair_data, w, _PROD_THRESHOLD)
        sweep_results[w] = (acc, scored)
        print(f"  window={w:5d} bars: accuracy={acc} (n={scored}/{n})")
    valid_sweep = {w: a for w, (a, s) in sweep_results.items() if a is not None}
    best_window_sweep = max(valid_sweep, key=valid_sweep.get) if valid_sweep else None
    print(f"Sweep-recommended window: {best_window_sweep} "
          f"(in-sample accuracy {valid_sweep.get(best_window_sweep)})")

    # --- (b) Joint grid ---
    print(f"\n{'='*70}\n(b) JOINT GRID (window x threshold)\n{'='*70}")
    joint_results = {}
    for w in _WINDOW_GRID:
        for t in _THRESHOLD_GRID:
            acc, scored, _ = score_cell(pair_data, w, t)
            joint_results[(w, t)] = (acc, scored)
            print(f"  window={w:5d} threshold={t:.2f}: accuracy={acc} (n={scored}/{n})")
    valid_joint = {k: a for k, (a, s) in joint_results.items() if a is not None}
    best_cell_joint = max(valid_joint, key=valid_joint.get) if valid_joint else None
    print(f"Joint-grid-recommended (window, threshold): {best_cell_joint} "
          f"(in-sample accuracy {valid_joint.get(best_cell_joint)})")

    # --- REQUIRED overfitting guard: split pairs into two disjoint halves ---
    print(f"\n{'='*70}\nOVERFITTING GUARD — select on half A, score on held-out half B\n{'='*70}")
    print(f"n={n} confirmed pairs total — split n_a={n//2}/n_b={n - n//2}. "
          f"THIS SPLIT ITSELF IS THIN (small-N) — flagged, not hidden.")
    idx = list(range(n))
    half_a = idx[0::2]
    half_b = idx[1::2]

    # Select best joint cell on half A only
    joint_a = {}
    for w in _WINDOW_GRID:
        for t in _THRESHOLD_GRID:
            acc, scored, _ = score_cell(pair_data, w, t, subset=half_a)
            joint_a[(w, t)] = acc
    valid_joint_a = {k: v for k, v in joint_a.items() if v is not None}
    best_cell_a = max(valid_joint_a, key=valid_joint_a.get) if valid_joint_a else None
    acc_a_selected, _, _ = score_cell(pair_data, *best_cell_a, subset=half_a) if best_cell_a else (None, 0, [])
    acc_b_heldout, n_b_scored, _ = score_cell(pair_data, *best_cell_a, subset=half_b) if best_cell_a else (None, 0, [])

    # Compare: does the SIMPLE single-dimension sweep's choice hold up
    # out-of-sample better than the joint grid's choice?
    sweep_a = {}
    for w in _WINDOW_GRID:
        acc, scored, _ = score_cell(pair_data, w, _PROD_THRESHOLD, subset=half_a)
        sweep_a[w] = acc
    valid_sweep_a = {k: v for k, v in sweep_a.items() if v is not None}
    best_window_a = max(valid_sweep_a, key=valid_sweep_a.get) if valid_sweep_a else None
    acc_sweep_b_heldout, _, _ = score_cell(pair_data, best_window_a, _PROD_THRESHOLD, subset=half_b) if best_window_a else (None, 0, [])

    print(f"Joint grid selected on half A: {best_cell_a} (half-A accuracy={acc_a_selected})")
    print(f"  -> scored on held-out half B: accuracy={acc_b_heldout} (n={n_b_scored})")
    print(f"Simple sweep selected on half A: window={best_window_a} (half-A accuracy={valid_sweep_a.get(best_window_a)})")
    print(f"  -> scored on held-out half B: accuracy={acc_sweep_b_heldout}")

    if acc_a_selected is not None and acc_b_heldout is not None:
        gap = acc_a_selected - acc_b_heldout
        print(f"\nJoint grid in-sample-vs-held-out gap: {gap:+.3f}")
        if gap > 0.15:
            print("OVERFITTING FLAGGED: the joint grid's in-sample-selected cell does NOT hold up "
                  "on the held-out half — its apparent advantage is likely noise, not a real "
                  "improvement. This is a real finding, reported honestly, not hidden.")
        else:
            print("No large in-sample-vs-held-out gap detected for the joint grid at this (thin) "
                  "sample size — but n is small enough that this should not be read as strong "
                  "reassurance either way.")

    result_rows = []
    for w in _WINDOW_GRID:
        for t in _THRESHOLD_GRID:
            acc, scored = joint_results[(w, t)]
            result_rows.append({"window": w, "threshold": t, "accuracy": acc, "n_scored": scored})
    result_df = pd.DataFrame(result_rows)
    out_dir = os.path.join("output", "research")
    os.makedirs(out_dir, exist_ok=True)
    tf_dir_map = {
        "1m": "1min", "2m": "2min", "3m": "3min", "5m": "5min", "15m": "15min",
        "30m": "30min", "1h": "1hr", "4h": "4hr", "7D": "7day", "1M": "1mo",
        "3M": "3mo", "6M": "6mo",
    }
    safe_tf = tf_dir_map.get(args.tf, args.tf.lower())
    # Previously wrote one fixed filename regardless of --tf, silently
    # overwriting the prior timeframe's grid results on every run at a
    # different tf (Tier 5, Grand Sweep 2026-07-20) -- not a case-collision,
    # a missing suffix entirely.
    out_path = os.path.join(out_dir, f"coint_frac_window_grid_{safe_tf}.parquet")
    result_df.to_parquet(out_path)
    print(f"\nFull grid written to {out_path}")

    print(f"\n{'='*70}\nFINAL RECOMMENDATION\n{'='*70}")
    print("Per this project's rule 7 (no inflating apparent robustness): the joint grid's raw "
          "in-sample 'winner' is NOT reported as automatically better than the current production "
          "window=252/threshold=0.70 default without the held-out check above. If the held-out gap "
          "is large, the SIMPLER single-dimension sweep (fewer degrees of freedom) is the more "
          "trustworthy choice, consistent with preferring less overfitting risk over a larger but "
          "noisier apparent gain.")


if __name__ == "__main__":
    main()
