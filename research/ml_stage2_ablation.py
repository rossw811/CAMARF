"""
CAMARF ml_stage2_ablation.py — research script, NOT part of the
production pipeline.

Builds ml.py's own documented "STAGE 2" (module docstring: "macro
context / asset characteristics get added in later stages... Per-bar
regime labels and macro context are deliberately NOT joined in here yet")
per Ross's explicit instruction: "try run ml stage 2 to see what it gives
us but not rely on it yet."

Design: does NOT modify ml.py's core Stage-1 extraction/labeling at all
(that pipeline is stable and already validated) — calls `ml.build()`
directly to get the exact same labeled `EntryEvent` examples Stage 1
uses, then ADDITIVELY joins macro regime context (`macro.py`'s own
classification, reused directly) onto each example by `entry_time`.
Attempts the identical MIN_CLASS_SAMPLES-gated train/validate discipline
Stage 1 uses on the EXPANDED feature set — same honest-refusal-to-train-
on-too-little discipline, not a bypassed or relaxed gate for Stage 2.

Usage:
    python research/ml_stage2_ablation.py
"""
import logging
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ml
from config import Config

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")

_STAGE2_MACRO_COLS = ["yield_curve_regime", "credit_regime", "vix_regime", "recession_state"]

log = logging.getLogger("ml_stage2_ablation")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_ml_stage2_ablation.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def join_macro_features(examples: pd.DataFrame) -> pd.DataFrame:
    """Pure-ish function (one macro.build() call, then pandas joins) — adds
    _STAGE2_MACRO_COLS to `examples` via entry_time, forward-filled onto
    the nearest prior trading date. Returns a NEW DataFrame; does not
    mutate the input. If macro.py has no cached/fetchable data (e.g. no
    FRED API key), the macro columns are added as all-NaN/'unknown'
    rather than raising — Stage 2 should degrade gracefully, not crash,
    when macro context isn't available."""
    df = examples.copy()
    if df.empty:
        for c in _STAGE2_MACRO_COLS:
            df[c] = "unknown"
        return df
    try:
        from macro import build as macro_build
        macro_result = macro_build()
        macro_df = macro_result.data
    except Exception as e:
        log.warning("macro.build() failed (%s) — Stage 2 macro columns will be 'unknown', "
                    "not fabricated.", e)
        macro_df = None

    if macro_df is None or macro_df.empty:
        for c in _STAGE2_MACRO_COLS:
            df[c] = "unknown"
        return df

    available = [c for c in _STAGE2_MACRO_COLS if c in macro_df.columns]
    missing = [c for c in _STAGE2_MACRO_COLS if c not in macro_df.columns]
    if missing:
        log.info("macro.py did not provide %s (likely no FRED API key / series not cached) — "
                 "Stage 2 proceeds with the available macro columns only: %s", missing, available)

    entry_dates = pd.to_datetime(df["entry_time"]).dt.normalize()
    # merge_asof (nearest PRIOR macro date, "backward") is the correct tool
    # here — a plain reindex-then-ffill breaks when entry_dates has repeats
    # (multiple examples on the same date), which duplicate-index reindex
    # cannot handle (found live, not assumed: this exact crash on real data).
    macro_sorted = macro_df[available].sort_index()
    macro_sorted = macro_sorted.rename_axis("_macro_date").reset_index()
    macro_sorted["_macro_date"] = macro_sorted["_macro_date"].astype("datetime64[ns]")
    left = pd.DataFrame({
        "_pos": np.arange(len(df)),
        "_entry_date": pd.DatetimeIndex(entry_dates).astype("datetime64[ns]"),
    })
    left_sorted = left.sort_values("_entry_date")
    joined = pd.merge_asof(
        left_sorted, macro_sorted,
        left_on="_entry_date", right_on="_macro_date", direction="backward",
    ).sort_values("_pos")
    for c in available:
        df[c] = joined[c].values
    for c in missing:
        df[c] = "unknown"
    return df


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== ml_stage2_ablation.py: macro-context ablation on ml.py's Stage 1 examples ===")

    result = ml.build()
    n_stage1 = len(result.examples)
    log.info("Stage 1 examples available: %d (pairs_used=%d, pairs_skipped=%d)",
              n_stage1, len(result.pairs_used), len(result.pairs_skipped))

    stage2_examples = join_macro_features(result.examples)
    log.info("Stage 2: joined macro columns %s onto %d examples", _STAGE2_MACRO_COLS, len(stage2_examples))
    if not stage2_examples.empty:
        for c in _STAGE2_MACRO_COLS:
            log.info("  %s distribution: %s", c, dict(stage2_examples[c].value_counts()))

    # Attempt the SAME MIN_CLASS_SAMPLES-gated discipline Stage 1 uses —
    # not relaxed for Stage 2. Example count is IDENTICAL to Stage 1
    # (Stage 2 adds FEATURES, not new labeled events), so if Stage 1 was
    # blocked, Stage 2 is deterministically blocked for the identical
    # reason — this is the honest, expected finding, not a bug in this script.
    min_per_class = Config.ML.MIN_CLASS_SAMPLES
    if stage2_examples.empty:
        n_classes_present, min_class_count = 0, 0
    else:
        if "label_for_training" not in stage2_examples.columns:
            if Config.ML.LABEL_SCHEME == "binary":
                stage2_examples["label_for_training"] = stage2_examples["label"].map(
                    Config.ML.BINARY_LABEL_MAP
                )
            else:
                stage2_examples["label_for_training"] = stage2_examples["label"]
        n_classes_present = stage2_examples["label_for_training"].nunique()
        min_class_count = stage2_examples["label_for_training"].value_counts().min()

    blocked = stage2_examples.empty or n_classes_present < 2 or min_class_count < min_per_class
    if blocked:
        log.warning(
            "Stage 2 blocked by the SAME gate as Stage 1: %d examples, %d classes, "
            "min class count=%d (need >=%d/class). This is the expected result, not a Stage-2-"
            "specific failure — Stage 2 adds feature columns to the SAME %d labeled events Stage 1 "
            "has, it cannot manufacture more labeled events. Per Ross's explicit instruction, this "
            "confirms the infrastructure is built and ready, without training (or reporting a "
            "'model') on data this thin. Re-run once Stage 1's own example count clears the gate.",
            len(stage2_examples), n_classes_present, min_class_count, min_per_class, n_stage1,
        )
    else:
        log.info("Stage 2 has enough data to attempt training — running comparison against Stage 1...")
        # Not reached at current data volume; if this branch DOES fire in a
        # future re-run, a real ablation (Stage 1 features alone vs. Stage 1
        # + macro, same CPCV/holdout discipline as ml.py's _train_and_validate)
        # belongs here — not built now since it was never reachable this
        # session, and building untested code for an unreachable branch would
        # violate this project's own verify-before-trusting discipline.
        log.info("NOT IMPLEMENTED YET — this branch was unreachable at this session's data volume "
                 "(13 examples). Build the real Stage1-vs-Stage1+macro comparison here once reached.")

    os.makedirs(_OUT_DIR, exist_ok=True)
    stage2_examples.to_parquet(os.path.join(_OUT_DIR, "ml_stage2_examples.parquet"), index=False)
    log.info("Saved -> output/research/ml_stage2_examples.parquet (%d examples with macro columns "
             "joined, ready for training once the label-count gate clears)", len(stage2_examples))

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("ml_stage2_ablation.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
