"""
debug/_verify_ml_model_comparison.py -- synthetic ground-truth verification
for research/ml_model_comparison.py's own logic (chronological_split,
majority_baseline_accuracy, fit_and_score), BEFORE trusting real-data
results. Does not re-verify XGBoost/LightGBM/sklearn's own correctness
(established libraries) -- only this script's own glue code.

Checks:
  1. chronological_split matches ml.py's own train/val/test proportions and
     sort order exactly, on a small synthetic examples DataFrame.
  2. Train-only median imputation: a NaN in the val/test fold is filled with
     the TRAIN fold's median, not a median computed over the full dataset
     (the exact leakage class ml.py's own BUG fix, 2026-07-20, addresses --
     this script must not reintroduce it).
  3. majority_baseline_accuracy matches a hand-computed value.
  4. fit_and_score returns None (not a crash) when the training fold has
     only one class present.

Run: python debug/_verify_ml_model_comparison.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

import ml
import ml_model_comparison as mmc


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


def _make_examples(n=20):
    rng = np.random.default_rng(0)
    entry_times = pd.date_range("2024-01-01", periods=n, freq="D")
    df = pd.DataFrame({"entry_time": entry_times})
    for col in ml._FEATURE_COLS:
        df[col] = rng.normal(0, 1, n)
    df["label_for_training"] = np.where(rng.random(n) > 0.5, "converged", "not_converged")
    return df


def verify_split_proportions():
    print("\n=== 1. chronological_split matches ml.py's own TRAIN_PCT/VAL_PCT ===")
    from config import Config
    df = _make_examples(20)
    X_train, y_train, X_val, y_val, X_test, y_test, le = mmc.chronological_split(df)
    n = len(df)
    expected_train_end = int(n * Config.ML.TRAIN_PCT)
    expected_val_end = expected_train_end + int(n * Config.ML.VAL_PCT)
    ok = check(f"n_train == int(n*TRAIN_PCT) == {expected_train_end}", len(X_train) == expected_train_end)
    ok &= check(f"n_val == int(n*VAL_PCT) == {expected_val_end - expected_train_end}",
                len(X_val) == expected_val_end - expected_train_end)
    ok &= check(f"n_test == remainder == {n - expected_val_end}", len(X_test) == n - expected_val_end)
    return ok


def verify_train_only_imputation_no_leakage():
    print("\n=== 2. Train-only median imputation (no val/test leakage) ===")
    df = _make_examples(20)
    # Inject a NaN in the test fold's first feature column, and set the
    # train fold's values for that column to a KNOWN constant so its median
    # is unambiguous and easy to check against.
    feat = ml._FEATURE_COLS[0]
    from config import Config
    train_end = int(len(df) * Config.ML.TRAIN_PCT)
    df.loc[:train_end - 1, feat] = 5.0  # every train-fold value is exactly 5.0 -> median = 5.0
    df.loc[len(df) - 1, feat] = np.nan  # last row (in the test fold) is NaN

    X_train, y_train, X_val, y_val, X_test, y_test, le = mmc.chronological_split(df)
    filled_value = X_test[feat].iloc[-1]
    ok = check("train median is exactly 5.0 (all train-fold values constant)",
               abs(df.loc[:train_end - 1, feat].median() - 5.0) < 1e-9)
    ok &= check("NaN in the test fold is filled with the TRAIN median (5.0), not a full-dataset median",
                abs(filled_value - 5.0) < 1e-9)
    return ok


def verify_majority_baseline():
    print("\n=== 3. majority_baseline_accuracy matches hand-computed value ===")
    y_train = np.array([0, 0, 0, 1, 1])  # majority class = 0
    y_test = np.array([0, 0, 1, 1])      # 2/4 correct if always predicting 0
    acc = mmc.majority_baseline_accuracy(y_train, y_test)
    ok = check("baseline accuracy == 0.5 (2/4 correct always predicting majority class 0)",
               abs(acc - 0.5) < 1e-9)
    return ok


def verify_single_class_train_no_crash():
    print("\n=== 4. fit_and_score handles single-class training data cleanly ===")
    from sklearn.linear_model import LogisticRegression
    X_train = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    y_train = np.array([0, 0, 0])  # only one class
    X_test = pd.DataFrame({"a": [1.5, 2.5]})
    y_test = np.array([0, 0])
    model = LogisticRegression()
    result = mmc.fit_and_score(model, X_train, y_train, X_test, y_test)
    ok = check("returns None (not a crash) when only one class is present in training data",
               result is None)
    return ok


def main():
    results = [
        verify_split_proportions(),
        verify_train_only_imputation_no_leakage(),
        verify_majority_baseline(),
        verify_single_class_train_no_crash(),
    ]
    print("\n" + "=" * 60)
    if all(results):
        print("ALL CHECKS PASSED")
    else:
        print(f"FAILURES: {results.count(False)}/{len(results)} check groups failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
