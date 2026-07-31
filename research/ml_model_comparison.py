"""
research/ml_model_comparison.py -- Ross's direct request (2026-07-22):
"let's add all the ML things as comparison and only for comparison until
enough data is found" (dedicated_pass.md sec 11.7).

COMPARISON ARM ONLY. `ml.py`'s Stage 1 meta-labeler (XGBoost) stays the
sole model persisted to output/ml/model_stage1.pkl and read by backtest.py's
MLConditioner for Layer 2 gating -- nothing here is wired into that path.
This script trains LightGBM, L2-penalized ("Ridge-equivalent") and
L1-penalized ("Lasso-equivalent") logistic regression, and Random Forest on
the IDENTICAL feature set, labels, and chronological train/val/test split
`ml.py`'s own `_train_and_validate()` uses -- reusing `ml.build()` and
`ml._train_and_validate()` directly (not a reimplementation) so the XGBoost
baseline reported here is the SAME run, not a separately-generated number
that could drift out of sync.

Honest scope, stated up front, not discovered after the fact: at this
project's current confirmed-pair count (3, post this session's collapse
investigation), `ml.build()` produces a total of 24 labeled entry events
across ALL pairs combined, severely class-imbalanced (22 "not_converged" vs
2 "converged" at last check). A 6-example test fold (per Config.ML.TRAIN_PCT/
VAL_PCT's chronological split) cannot meaningfully distinguish any of these
models' true skill from noise, and a naive "always predict the majority
training class" baseline is reported ALONGSIDE every model's accuracy for
exactly this reason -- an accuracy number with no majority-baseline context
next to it is not informative at this sample size, and this script will not
pretend otherwise. This is "comparison only until enough data is found" in
its most literal form: the comparison infrastructure is real and ready: the
verdict on which model is actually better is not answerable yet.

Verified against synthetic ground truth first:
debug/_verify_ml_model_comparison.py.

Usage:
    python research/ml_model_comparison.py
"""
import logging
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
import ml

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")

log = logging.getLogger("ml_model_comparison")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_ml_model_comparison.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def chronological_split(examples: pd.DataFrame):
    """Reproduces ml.py's _train_and_validate() split EXACTLY: same sort key,
    same TRAIN_PCT/VAL_PCT, same train-only median imputation (BUG fixed
    2026-07-20 in ml.py: computing the median over train+val+test leaks
    val/test feature distribution into training-set NaN fills)."""
    from sklearn.preprocessing import LabelEncoder

    df = examples.sort_values("entry_time").reset_index(drop=True)
    X_raw = df[ml._FEATURE_COLS]
    le = LabelEncoder()
    y = le.fit_transform(df["label_for_training"])

    n = len(df)
    train_end = int(n * Config.ML.TRAIN_PCT)
    val_end = train_end + int(n * Config.ML.VAL_PCT)

    train_median = X_raw.iloc[:train_end].median()
    X = X_raw.fillna(train_median)

    return (
        X.iloc[:train_end], y[:train_end],
        X.iloc[train_end:val_end], y[train_end:val_end],
        X.iloc[val_end:], y[val_end:],
        le,
    )


def majority_baseline_accuracy(y_train, y_test):
    """Naive 'always predict the most common training class' baseline --
    the honest floor any model must clear to be doing something real."""
    if len(y_train) == 0 or len(y_test) == 0:
        return np.nan
    majority_class = np.bincount(y_train).argmax()
    preds = np.full(len(y_test), majority_class)
    return float(np.mean(preds == y_test))


def fit_and_score(model, X_train, y_train, X_test, y_test, sample_weight=None):
    if len(np.unique(y_train)) < 2:
        return None  # can't fit a classifier on a single class
    try:
        if sample_weight is not None:
            model.fit(X_train, y_train, sample_weight=sample_weight)
        else:
            model.fit(X_train, y_train)
        return float(model.score(X_test, y_test))
    except Exception as e:
        log.warning("  model fit/score failed: %s: %s", type(e).__name__, e)
        return None


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== ml_model_comparison.py: LightGBM/Ridge/Lasso/RandomForest vs. ml.py's "
              "XGBoost, COMPARISON ARM ONLY (nothing here feeds backtest.py's MLConditioner) ===")

    result = ml.build(min_class_samples=0)
    examples = result.examples
    log.info("Loaded %d labeled entry events (ml.build(min_class_samples=0), same data "
              "ml.py's own XGBoost trains on)", len(examples))
    if examples.empty:
        log.warning("No labeled examples at all -- aborting, nothing to compare.")
        return

    counts = examples["label_for_training"].value_counts()
    log.info("Label distribution: %s", counts.to_dict())
    if counts.min() < 5:
        log.warning(
            "HONEST FLAG: minority class has only %d examples. Any model's accuracy "
            "below is not a meaningful skill signal at this sample size -- reported "
            "alongside the majority-class baseline for exactly this reason, not instead "
            "of stating this plainly.", counts.min()
        )

    X_train, y_train, X_val, y_val, X_test, y_test, le = chronological_split(examples)
    log.info("Chronological split: n_train=%d n_val=%d n_test=%d", len(X_train), len(X_val), len(X_test))

    if len(X_train) == 0 or len(X_test) == 0:
        log.warning("Empty train or test fold -- aborting, nothing to compare.")
        return

    baseline_acc = majority_baseline_accuracy(y_train, y_test)
    log.info("Majority-class baseline accuracy on test fold: %.2f%% (the floor any real model must clear)",
              baseline_acc * 100)

    from sklearn.utils.class_weight import compute_sample_weight
    train_weights = compute_sample_weight("balanced", y_train)

    rows = []

    # --- XGBoost (ml.py's own production model, run here for a same-run side-by-side) ---
    xgb_summary = ml.MLRunSummary()
    xgb_result = ml.MLResult(examples=examples, pairs_used=result.pairs_used, pairs_skipped=result.pairs_skipped)
    ml._train_and_validate(xgb_result, xgb_summary)
    xgb_acc = xgb_result.holdout_report.get("test_accuracy") if xgb_result.holdout_report else None
    rows.append({"model": "xgboost (production)", "test_accuracy": xgb_acc})
    log.info("  xgboost (production): test_accuracy=%s", f"{xgb_acc:.2%}" if xgb_acc is not None else "N/A")

    # --- LightGBM ---
    import lightgbm as lgb
    lgbm = lgb.LGBMClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.05,
        random_state=42, n_jobs=1, verbose=-1,
    )
    acc = fit_and_score(lgbm, X_train, y_train, X_test, y_test, sample_weight=train_weights)
    rows.append({"model": "lightgbm", "test_accuracy": acc})
    log.info("  lightgbm: test_accuracy=%s", f"{acc:.2%}" if acc is not None else "N/A")

    # --- Ridge-equivalent: L2-penalized logistic regression ---
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler().fit(X_train)
    X_train_s, X_test_s = scaler.transform(X_train), scaler.transform(X_test)
    ridge = LogisticRegression(penalty="l2", C=1.0, max_iter=2000, random_state=42)
    acc = fit_and_score(ridge, X_train_s, y_train, X_test_s, y_test, sample_weight=train_weights)
    rows.append({"model": "ridge_logistic (l2)", "test_accuracy": acc})
    log.info("  ridge_logistic (l2): test_accuracy=%s", f"{acc:.2%}" if acc is not None else "N/A")

    # --- Lasso-equivalent: L1-penalized logistic regression ---
    lasso = LogisticRegression(penalty="l1", solver="liblinear", C=1.0, max_iter=2000, random_state=42)
    acc = fit_and_score(lasso, X_train_s, y_train, X_test_s, y_test, sample_weight=train_weights)
    rows.append({"model": "lasso_logistic (l1)", "test_accuracy": acc})
    log.info("  lasso_logistic (l1): test_accuracy=%s", f"{acc:.2%}" if acc is not None else "N/A")

    # --- Random Forest ---
    from sklearn.ensemble import RandomForestClassifier
    rf = RandomForestClassifier(
        n_estimators=200, max_depth=4, random_state=42, n_jobs=1, class_weight="balanced",
    )
    acc = fit_and_score(rf, X_train, y_train, X_test, y_test)
    rows.append({"model": "random_forest", "test_accuracy": acc})
    log.info("  random_forest: test_accuracy=%s", f"{acc:.2%}" if acc is not None else "N/A")

    for r in rows:
        r["majority_baseline_accuracy"] = baseline_acc
        r["n_train"] = len(X_train)
        r["n_test"] = len(X_test)
        r["minority_class_count"] = int(counts.min())
        r["beats_baseline"] = (
            (r["test_accuracy"] - baseline_acc) if r["test_accuracy"] is not None else np.nan
        )

    result_df = pd.DataFrame(rows)
    log.info("")
    log.info("=== Summary (test_accuracy - majority_baseline; positive = beats the naive floor) ===")
    for _, r in result_df.iterrows():
        if pd.isna(r["beats_baseline"]):
            log.info("  %-22s: N/A", r["model"])
        else:
            log.info("  %-22s: %+.1f%% vs. baseline", r["model"], r["beats_baseline"] * 100)

    os.makedirs(_OUT_DIR, exist_ok=True)
    result_df.to_parquet(os.path.join(_OUT_DIR, "ml_model_comparison.parquet"), index=False)
    log.info("Saved -> output/research/ml_model_comparison.parquet")

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("ml_model_comparison.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
