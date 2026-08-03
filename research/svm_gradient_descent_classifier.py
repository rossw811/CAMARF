"""
CAMARF research/svm_gradient_descent_classifier.py — comparison/diagnostic
script, NOT part of the production pipeline (2026-08-02).

Ross asked for an SVM-via-gradient-descent alternate classifier for
ml.py's meta-labeler, A/B'd against whatever it currently uses (XGBoost,
see ml.py::_train_and_validate). "SVM trained by gradient descent" =
sklearn's SGDClassifier(loss="hinge") — hinge loss + (stochastic) gradient
descent is the standard linear-SVM training method (the Pegasos
algorithm is this exact combination). No new dependency — sklearn is
already used throughout ml.py (LabelEncoder, compute_sample_weight,
permutation_importance).

Reuses ml.py::build() directly (reads already-persisted spread_series/
pairs.parquet from disk, same real examples ml.py's own XGBoost trains
on — not a separate/inconsistent dataset) and reproduces
_train_and_validate's exact chronological-split + train-only-median-
imputation convention (duplicated here since that logic is inline in a
closure-shaped function, not standalone-importable — same precedent
aligned_pair_loader.py and the WRDS verify script already established for
"duplicate to match exactly, don't drift").

DISCLOSED LIMITATION: as of Session 29, the confirmed-pair set is tiny
(KVUE/KMB only) — this may report "insufficient data," honestly, rather
than force a comparison the data can't support (matches
Config.ML.MIN_CLASS_SAMPLES's own stated design intent).

Usage:
    python research/svm_gradient_descent_classifier.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
import ml


def chronological_split(df, feature_cols):
    """Exact reproduction of ml.py::_train_and_validate's split +
    train-only-median-imputation convention."""
    from sklearn.preprocessing import LabelEncoder

    df = df.sort_values("entry_time").reset_index(drop=True)
    X_raw = df[feature_cols]
    le = LabelEncoder()
    y = le.fit_transform(df["label_for_training"])

    n = len(df)
    train_end = int(n * Config.ML.TRAIN_PCT)
    val_end = train_end + int(n * Config.ML.VAL_PCT)

    train_median = X_raw.iloc[:train_end].median()
    X = X_raw.fillna(train_median)

    return {
        "X_train": X.iloc[:train_end], "y_train": y[:train_end],
        "X_val": X.iloc[train_end:val_end], "y_val": y[train_end:val_end],
        "X_test": X.iloc[val_end:], "y_test": y[val_end:],
        "label_encoder": le,
    }


def fit_svm_sgd(X_train, y_train, X_test, y_test, random_state=42):
    from sklearn.linear_model import SGDClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.utils.class_weight import compute_sample_weight

    # SGDClassifier's gradient steps are scale-sensitive (unlike
    # XGBoost's tree splits) -- standardize features first, fit ONLY on
    # train, matching this project's train-only-statistics convention.
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    weights = compute_sample_weight("balanced", y_train)
    model = SGDClassifier(loss="hinge", random_state=random_state, max_iter=1000, tol=1e-3)
    model.fit(X_train_s, y_train, sample_weight=weights)
    test_acc = float(model.score(X_test_s, y_test))
    return model, test_acc


def main():
    result = ml.build()
    if result.examples.empty:
        print("No labeled examples available (no confirmed pairs with persisted spread series) — nothing to compare.")
        return

    n = len(result.examples)
    min_per_class = (
        Config.ML.MIN_CLASS_SAMPLES if Config.ML.LABEL_SCHEME == "binary"
        else Config.ML.MIN_CLASS_SAMPLES
    )
    class_counts = result.examples["label_for_training"].value_counts()
    print(f"Total labeled examples: {n}")
    print(f"Class distribution: {class_counts.to_dict()}")

    if class_counts.min() < min_per_class or len(class_counts) < 2:
        print(f"\nINSUFFICIENT DATA for a fair train/test comparison: smallest class has "
              f"{class_counts.min()} examples, need >= {min_per_class} (Config.ML.MIN_CLASS_SAMPLES). "
              f"Reporting this honestly rather than forcing a comparison the data can't support.")
        return

    split = chronological_split(result.examples, ml._FEATURE_COLS)
    if len(split["X_train"]) == 0 or len(split["X_test"]) == 0:
        print("\nChronological split left an empty train or test fold — skipping comparison.")
        return

    svm_model, svm_acc = fit_svm_sgd(split["X_train"], split["y_train"], split["X_test"], split["y_test"])
    print(f"\nSVM (SGDClassifier, hinge loss): n_train={len(split['X_train'])} "
          f"n_test={len(split['X_test'])} test_accuracy={svm_acc:.2%}")

    # XGBoost baseline — ml.py's own function, on the IDENTICAL examples
    # (this call also persists ml.py's production model.pkl as a side
    # effect, same as running ml.py directly would).
    import ml as ml_module
    summary = ml_module.MLRunSummary()
    ml_module._train_and_validate(result, summary)
    if result.holdout_report:
        xgb_acc = result.holdout_report["test_accuracy"]
        print(f"XGBoost (ml.py production baseline): test_accuracy={xgb_acc:.2%}")
        print(f"\nDelta (SVM - XGBoost): {(svm_acc - xgb_acc) * 100:+.2f} percentage points")
    else:
        print("XGBoost baseline did not train (see ml.py's own logged reason).")


if __name__ == "__main__":
    main()
