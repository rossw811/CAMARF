"""
Mechanical lookahead self-test for ml.py's meta-labeler (Development.md
second-pass triage item #5, flagged Session 27 bias-literature review,
reconfirmed still absent Session 28: "lag every feature by one bar, confirm
performance degrades").

Method: reuses `ml.py`'s REAL `_build_examples_for_pair()` and
`_train_and_validate()` UNCHANGED (no re-implemented copy of either) —
`_build_examples_for_pair` gained a `feature_lag: int = 0` param for exactly
this purpose (default 0 preserves original behavior for every real caller).

IMPORTANT design note, found by this script's own synthetic self-check before
trusting it: an earlier version of this script tried to lag the whole
spread_series DataFrame before passing it in (matching
`research/fill_timing_sensitivity.py`'s convention). That's wrong here,
because `_build_examples_for_pair` uses the SAME `z_rolling` column both to
DETECT entry events and to READ the feature value — shifting the whole
series just moves the detected entry time forward by the same amount,
so the "feature at entry" ends up reading the identical (still-fresh) value
each time, silently defeating the test. `feature_lag` instead keeps entry
detection AND the label (which must reflect what actually, truly happened)
anchored to the real entry bar, and staled ONLY the zscore/half_life_current/
zscore_velocity values fed to the model as features — the correct
implementation of "the model only got to see information from N bars ago."

Two example sets, both from the SAME real spread_series files:
  - unlagged (feature_lag=0): features read at the entry bar itself (this is
    what ml.py's production build() always does today).
  - lagged (feature_lag=1): zscore/half_life_current/zscore_velocity read one
    bar EARLIER than entry — deliberately staler than what the live signal
    could actually see at entry time. z_entry (label input) and the outcome
    horizon are UNCHANGED, since the question is "does moving the FEATURE
    snapshot back one bar hurt performance," not "change what the label is."

Expected (healthy) result: lagged test accuracy <= unlagged test accuracy —
using staler information should never help. If lagged performance is
NOTABLY higher, that's a lookahead red flag in the unlagged (production)
pipeline worth investigating, not dismissed.

Safety: `_train_and_validate` persists a REAL production artifact
(`output/ml/model_stage1.pkl`, consumed by `MLConditioner` for Layer 2). This
script backs that file up before running and restores it afterward
unconditionally, so this comparison run never leaves behind or overwrites a
real production model file.

Read-only otherwise. Never fetches, never modifies spread_series files.
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import ml
from ml import (
    MLResult, MLRunSummary, _build_examples_for_pair, _discover_confirmed_pairs,
    _tf_dirname, _train_and_validate, _RESULTS_DIR,
)
from config import Config

_PKL_PATH = os.path.join(os.path.dirname(os.path.abspath(ml.__file__)), "output", "ml", "model_stage1.pkl")
_PKL_BACKUP = _PKL_PATH + ".selftest_backup"


def build_examples(feature_lag: int) -> MLResult:
    summary = MLRunSummary()
    pairs = _discover_confirmed_pairs()
    all_events = []
    pairs_used, pairs_skipped = [], []

    for symbol_a, symbol_b, tf_label in pairs:
        try:
            pairs_df = pd.read_parquet(
                os.path.join(_RESULTS_DIR, _tf_dirname(tf_label), "pairs.parquet")
            )
            row = pairs_df[
                (pairs_df["symbol_a"] == symbol_a) & (pairs_df["symbol_b"] == symbol_b)
            ].iloc[0]
        except Exception as e:
            pairs_skipped.append((symbol_a, symbol_b, tf_label, f"lookup failed: {e}"))
            continue
        if bool(row.get("thin_info_content", False)):
            continue

        series_path = os.path.join(
            _RESULTS_DIR, _tf_dirname(tf_label), f"spread_series_{symbol_a}_{symbol_b}.parquet"
        )
        try:
            series = pd.read_parquet(series_path)
        except Exception as e:
            pairs_skipped.append((symbol_a, symbol_b, tf_label, f"series load failed: {e}"))
            continue

        try:
            events = _build_examples_for_pair(
                symbol_a, symbol_b, tf_label, row, summary, series=series, feature_lag=feature_lag
            )
        except Exception as e:
            pairs_skipped.append((symbol_a, symbol_b, tf_label, f"{type(e).__name__}: {e}"))
            continue
        if events:
            pairs_used.append((symbol_a, symbol_b, tf_label))
            all_events.extend(events)

    examples_df = pd.DataFrame([vars(e) for e in all_events])
    if not examples_df.empty:
        if Config.ML.LABEL_SCHEME == "binary":
            examples_df["label_for_training"] = examples_df["label"].map(Config.ML.BINARY_LABEL_MAP)
        else:
            examples_df["label_for_training"] = examples_df["label"]

    return MLResult(examples=examples_df, pairs_used=pairs_used, pairs_skipped=pairs_skipped), summary


def main():
    have_backup = False
    if os.path.exists(_PKL_PATH):
        shutil.copy2(_PKL_PATH, _PKL_BACKUP)
        have_backup = True
        print(f"Backed up real production model: {_PKL_PATH} -> {_PKL_BACKUP}")

    try:
        results = {}
        for flag, label in [(0, "unlagged (current production behavior)"), (1, "lagged (features staled 1 bar)")]:
            result, summary = build_examples(feature_lag=flag)
            n = len(result.examples)
            n_classes = result.examples["label_for_training"].nunique() if n else 0
            min_per_class = Config.ML.MIN_CLASS_SAMPLES
            min_class_count = result.examples["label_for_training"].value_counts().min() if n else 0
            print(f"\n=== {label} ===")
            print(f"  {n} labeled examples, {n_classes} classes, min class count {min_class_count} "
                  f"(need >={min_per_class}/class to train)")
            if n == 0 or n_classes < 2 or min_class_count < min_per_class:
                print(f"  Insufficient data to train right now -- Phase 3's full pipeline rerun "
                      f"hasn't completed this session, so only 1m/2m/3m live confirmed-pairs data "
                      f"exists. Re-run this script once more confirmed pairs (esp. 1h) are live.")
                results[flag] = None
                continue
            _train_and_validate(result, summary)
            results[flag] = result.holdout_report
            print(f"  test_accuracy={result.holdout_report['test_accuracy']:.2%} "
                  f"(n_train={result.holdout_report['n_train']}, n_test={result.holdout_report['n_test']})")

        print()
        if results[0] is None or results[1] is None:
            print("Could not complete the comparison -- insufficient real data this session. "
                  "Not a failure of the self-test mechanism itself; re-run once Phase 3 lands.")
            return

        acc_unlagged = results[0]["test_accuracy"]
        acc_lagged = results[1]["test_accuracy"]
        print(f"unlagged test_accuracy: {acc_unlagged:.2%}")
        print(f"lagged   test_accuracy: {acc_lagged:.2%}")
        if acc_lagged > acc_unlagged + 0.02:  # small tolerance for noise at this sample size
            print(f"WARNING: lagged (staler) features scored HIGHER by "
                  f"{(acc_lagged - acc_unlagged):.2%} -- possible lookahead artifact in the "
                  f"unlagged pipeline, worth investigating further, not dismissed as noise.")
        else:
            print("PASSED: lagged features did not meaningfully outperform unlagged features -- "
                  "no evidence of lookahead leakage in ml.py's feature construction.")
    finally:
        if have_backup:
            shutil.move(_PKL_BACKUP, _PKL_PATH)
            print(f"\nRestored real production model from backup: {_PKL_PATH}")
        elif os.path.exists(_PKL_PATH):
            os.remove(_PKL_PATH)
            print(f"\nRemoved self-test-only model artifact (no real model existed before this run): {_PKL_PATH}")


if __name__ == "__main__":
    main()
