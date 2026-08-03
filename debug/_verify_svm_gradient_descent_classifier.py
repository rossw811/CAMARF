"""
Synthetic verification for research/svm_gradient_descent_classifier.py,
before trusting it against real ml.py examples.

Checks:
  1. chronological_split()'s train/val/test row counts exactly match
     Config.ML.TRAIN_PCT/VAL_PCT arithmetic (int truncation, same as
     ml.py::_train_and_validate) -- this is a reproduction of that
     function's inline logic, so a mismatch here means the comparison
     arm is not actually testing what ml.py's XGBoost is trained on.
  2. Median imputation is fit on the TRAIN split only (matches the
     no-leakage fix ml.py's own docstring documents finding 2026-07-20).
  3. fit_svm_sgd() recovers a trivially linearly-separable synthetic
     3-class problem with high accuracy -- confirms the SGD-hinge fit
     mechanics (scaling, sample weighting, fit/score) work correctly
     before ever touching real, much harder, real-market data.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from config import Config
from svm_gradient_descent_classifier import chronological_split, fit_svm_sgd


def test_split_sizes_match_config_pcts():
    n = 1000
    df = pd.DataFrame({
        "entry_time": pd.date_range("2020-01-01", periods=n, freq="h"),
        "feat_a": np.random.default_rng(0).normal(0, 1, n),
        "label_for_training": np.random.default_rng(0).choice(["win", "loss"], n),
    })
    result = chronological_split(df, ["feat_a"])
    expected_train = int(n * Config.ML.TRAIN_PCT)
    expected_val = int(n * Config.ML.VAL_PCT)
    expected_test = n - expected_train - expected_val
    print(f"split sizes: train={len(result['X_train'])} (expect {expected_train}), "
          f"val={len(result['X_val'])} (expect {expected_val}), "
          f"test={len(result['X_test'])} (expect {expected_test})")
    assert len(result["X_train"]) == expected_train
    assert len(result["X_val"]) == expected_val
    assert len(result["X_test"]) == expected_test


def test_median_imputation_uses_train_only():
    n = 100
    rng = np.random.default_rng(1)
    feat = rng.normal(0, 1, n)
    feat[10] = np.nan  # a NaN inside the train split
    df = pd.DataFrame({
        "entry_time": pd.date_range("2020-01-01", periods=n, freq="h"),
        "feat_a": feat,
        "label_for_training": rng.choice(["win", "loss"], n),
    })
    train_end = int(n * Config.ML.TRAIN_PCT)
    expected_median = pd.Series(feat[:train_end]).median()  # median over TRAIN rows only
    result = chronological_split(df, ["feat_a"])
    filled_value = result["X_train"]["feat_a"].iloc[10]
    print(f"train-only median: expected={expected_median:.4f}, filled value at NaN position={filled_value:.4f}")
    assert abs(filled_value - expected_median) < 1e-9, "imputation should use the TRAIN-only median, not full-sample"


def test_svm_recovers_separable_synthetic_problem():
    rng = np.random.default_rng(2)
    n_per_class = 200
    # 3 well-separated clusters in 2D -- trivially linearly separable.
    X0 = rng.normal([-5, -5], 0.5, (n_per_class, 2))
    X1 = rng.normal([5, 5], 0.5, (n_per_class, 2))
    X2 = rng.normal([-5, 5], 0.5, (n_per_class, 2))
    X = pd.DataFrame(np.vstack([X0, X1, X2]), columns=["f0", "f1"])
    y = np.array([0] * n_per_class + [1] * n_per_class + [2] * n_per_class)

    n = len(X)
    split_idx = int(n * 0.8)
    perm = rng.permutation(n)
    X, y = X.iloc[perm].reset_index(drop=True), y[perm]
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    model, acc = fit_svm_sgd(X_train, y_train, X_test, y_test)
    print(f"SVM accuracy on trivially separable 3-class synthetic problem: {acc:.2%} (expect >0.95)")
    assert acc > 0.95, f"expected near-perfect accuracy on a trivially separable problem, got {acc}"


if __name__ == "__main__":
    test_split_sizes_match_config_pcts()
    test_median_imputation_uses_train_only()
    test_svm_recovers_separable_synthetic_problem()
    print("\nAll svm_gradient_descent_classifier.py synthetic checks passed.")
