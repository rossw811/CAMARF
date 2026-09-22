"""
Synthetic verification for ml.py's threshold recalibration (2026-09-22, added alongside AUC-ROC
after Ross's direct question "should we consider integrating AUC?" -- the naive 0.5 probability
threshold is exactly what made a model with real AUC-ROC look like it had "no signal" on raw
accuracy the night before).

Checks `_youden_optimal_threshold()` directly against hand-constructed (y_true, predicted-
probability) arrays with an ANALYTICALLY KNOWN optimal threshold, not only end-to-end through a
real XGBoost fit -- isolates the threshold-selection logic itself from model-fitting noise.

Run: python debug/_verify_ml_threshold_recalibration.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from ml import _youden_optimal_threshold

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def test_perfect_separation_finds_the_true_gap():
    # y=0 examples all have probability < 0.3, y=1 examples all have probability > 0.7 --
    # ANY threshold in (0.3, 0.7) achieves perfect separation (J=1.0); Youden's J is flat across
    # that whole gap, so just confirm the returned threshold actually achieves perfect accuracy
    # (a "some" number here is stronger evidence of correctness than pinning one exact value the
    # implementation isn't required to prefer).
    rng = np.random.default_rng(1)
    y0 = np.zeros(200, dtype=int)
    probs0 = rng.uniform(0.0, 0.3, 200)
    y1 = np.ones(200, dtype=int)
    probs1 = rng.uniform(0.7, 1.0, 200)
    y = np.concatenate([y0, y1])
    probs = np.concatenate([probs0, probs1])

    t = _youden_optimal_threshold(y, probs)
    preds = (probs >= t).astype(int)
    acc = np.mean(preds == y)
    check("perfect_separation.threshold_achieves_perfect_accuracy", acc == 1.0,
          f"threshold={t:.4f} accuracy={acc:.4f}")


def test_recalibration_beats_naive_0p5_on_a_shifted_distribution():
    # Both classes' predicted probabilities are shifted well below 0.5 (e.g. an imbalanced
    # model whose predict_proba output skews low overall) but still cleanly separated from
    # each other -- the naive 0.5 threshold classifies EVERYTHING as the negative class (useless,
    # accuracy = majority fraction), while the Youden's-J-optimal threshold (sitting inside the
    # actual gap between the two distributions) should recover near-perfect accuracy. This is
    # exactly the failure mode motivating this feature: real separation the 0.5 default misses.
    rng = np.random.default_rng(2)
    y0 = np.zeros(300, dtype=int)
    probs0 = rng.uniform(0.05, 0.15, 300)
    y1 = np.ones(100, dtype=int)  # imbalanced, like the real label distribution
    probs1 = rng.uniform(0.25, 0.35, 100)
    y = np.concatenate([y0, y1])
    probs = np.concatenate([probs0, probs1])

    naive_preds = (probs >= 0.5).astype(int)
    naive_acc = np.mean(naive_preds == y)
    check("shifted_distribution.naive_0p5_threshold_is_useless_here",
          naive_acc == np.mean(y == 0), f"naive_acc={naive_acc:.4f}")

    t = _youden_optimal_threshold(y, probs)
    recalibrated_preds = (probs >= t).astype(int)
    recalibrated_acc = np.mean(recalibrated_preds == y)
    check("shifted_distribution.recalibrated_threshold_recovers_real_separation",
          recalibrated_acc > naive_acc, f"threshold={t:.4f} recalibrated_acc={recalibrated_acc:.4f}")
    check("shifted_distribution.recalibrated_accuracy_is_near_perfect",
          recalibrated_acc > 0.95, f"recalibrated_acc={recalibrated_acc:.4f}")


def test_no_signal_returns_a_threshold_near_chance():
    # Both classes drawn from the SAME distribution (no real separation) -- Youden's J should be
    # near 0 everywhere, and accuracy at the chosen threshold should be close to the majority
    # fraction, not artificially inflated (confirms this isn't silently overfitting a threshold
    # to noise on a case with no real signal to find).
    rng = np.random.default_rng(3)
    n = 500
    y = (rng.uniform(0, 1, n) > 0.6).astype(int)  # 60/40 imbalanced, matches the real label split
    probs = rng.uniform(0, 1, n)  # pure noise, independent of y

    t = _youden_optimal_threshold(y, probs)
    preds = (probs >= t).astype(int)
    acc = np.mean(preds == y)
    majority = max(np.mean(y == 0), np.mean(y == 1))
    check("no_signal.recalibrated_accuracy_does_not_wildly_exceed_majority_baseline",
          acc < majority + 0.10, f"threshold={t:.4f} acc={acc:.4f} majority_baseline={majority:.4f}")


if __name__ == "__main__":
    test_perfect_separation_finds_the_true_gap()
    test_recalibration_beats_naive_0p5_on_a_shifted_distribution()
    test_no_signal_returns_a_threshold_near_chance()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
