"""
Synthetic verification for ml.py's ConformalPredictor (Session 10
academic backlog, idea #9). Real ml.py training is still gated on
insufficient sample size (12 examples as of this session), so this is
the only way to verify the conformal-coverage guarantee actually holds
before it's ever exercised on real data.

Checks the core theoretical property directly: with a large enough
calibration set, empirical coverage on a held-out i.i.d. test set should
land close to (at or above) the target 1-alpha, regardless of how good
or bad the underlying classifier is — that's the whole point of split
conformal prediction (distribution-free, model-agnostic guarantee under
exchangeability).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from sklearn.linear_model import LogisticRegression

from ml import ConformalPredictor


def main():
    rng = np.random.RandomState(0)
    failures = []

    # --- Case 1: large i.i.d. dataset, deliberately weak/noisy classifier
    # (3 informative-ish features + 5 pure-noise features) — coverage
    # should hold even though accuracy is mediocre.
    n_train, n_cal, n_test = 400, 300, 2000
    n_features = 8
    X_all = rng.randn(n_train + n_cal + n_test, n_features)
    true_logit = X_all[:, 0] * 1.2 - X_all[:, 1] * 0.8 + rng.randn(len(X_all)) * 1.5
    y_all = (true_logit > 0).astype(int)

    X_train, y_train = X_all[:n_train], y_all[:n_train]
    X_cal, y_cal = X_all[n_train:n_train + n_cal], y_all[n_train:n_train + n_cal]
    X_test, y_test = X_all[n_train + n_cal:], y_all[n_train + n_cal:]

    clf = LogisticRegression().fit(X_train, y_train)
    test_acc = clf.score(X_test, y_test)

    for alpha in [0.1, 0.2]:
        cp = ConformalPredictor(clf, clf.classes_)
        cp.calibrate(X_cal, y_cal)
        pred_sets = cp.predict_sets(X_test, alpha=alpha)
        coverage = np.mean([y_test[i] in pred_sets[i] for i in range(len(pred_sets))])
        avg_size = np.mean([len(s) for s in pred_sets])
        target = 1 - alpha
        # Allow a small finite-sample tolerance band around the target —
        # split conformal guarantees coverage >= 1-alpha in expectation
        # over calibration draws, not exactly per-draw.
        ok = coverage >= target - 0.05
        status = "OK" if ok else "FAIL"
        print(f"{status}  alpha={alpha}: target_coverage>={target:.2f}, "
              f"empirical_coverage={coverage:.3f}, avg_set_size={avg_size:.2f}, "
              f"underlying_clf_test_acc={test_acc:.2%}")
        if not ok:
            failures.append(f"alpha={alpha} coverage {coverage:.3f} < {target - 0.05:.3f}")

    # --- Case 2: tiny calibration set (mirrors this project's real
    # constraint) — must not crash, sets should be valid (1 or 2 classes).
    cp_small = ConformalPredictor(clf, clf.classes_)
    cp_small.calibrate(X_cal[:8], y_cal[:8])
    small_sets = cp_small.predict_sets(X_test[:20], alpha=0.1)
    valid = all(1 <= len(s) <= 2 for s in small_sets)
    print(f"{'OK' if valid else 'FAIL'}  tiny calibration set (n=8): "
          f"no crash, all prediction sets non-degenerate "
          f"(sizes: {[len(s) for s in small_sets]})")
    if not valid:
        failures.append("tiny calibration set produced degenerate (empty) prediction sets")

    print()
    if failures:
        print(f"FAILED: {failures}")
        sys.exit(1)
    print("All cases match expected behavior.")


if __name__ == "__main__":
    main()
