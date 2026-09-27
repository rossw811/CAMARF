"""
research/ml_model_comparison_purged.py -- audit step 3 (2026-09-26, Ross-approved plan).

COMPARISON ARM ONLY. Nothing here feeds backtest.py's MLConditioner.

What it does
------------
Re-runs the meta-labeler model comparison at the current event count (ml.build(pit_safe=True),
~74k labeled entry events) across nine classifiers on the IDENTICAL features/labels:
XGBoost (ml.py's own hyper-parameters), LightGBM, L2 and L1 logistic regression, Random Forest,
k-nearest neighbours, MLP, and an RBF-kernel SVM.

Every model is evaluated under TWO split conventions, side by side:
  * "positional" -- ml.py's existing chronological 60/20/20 split (kept as the comparison arm);
  * "purged"     -- the same boundaries, with AFML ch.7 purging (drop events whose label window
                    reaches into the next split) and an embargo after each boundary. This is the
                    fix for confirmed code-review finding R2.3 (no purge/embargo anywhere in ml.py
                    or the LSTM script, while labels look forward RESOLUTION_BARS_MULT*half-life
                    bars and hundreds of pairs share dates).
Split boundaries are placed by TIMESTAMP, so no entry_time straddles two splits (cross-sectional
duplicates on the same date stay together).

Pre-declared metrics (declared in the 2026-09-26 plan, BEFORE any result was seen)
-----------------------------------------------------------------------------------
PRIMARY: AUC-ROC on the purged test split, with a date-clustered bootstrap 90% CI, and the paired
         clustered-bootstrap AUC difference vs XGBoost.
SECOND PRIMARY (DEFERRED): capital-sim Sharpe of trades the model's filter admits. NOT computed:
         backtest.py's P&L accounting is confirmed broken (code review B2 beta drift, B3 unit
         mixing, B4 OLS/Kalman double count, P1 calendar-day sqrt(252)). Reported as deferred, not
         substituted by a proxy.
DESCRIPTIVE ONLY (no model is "selected" on these): PR-AUC, log-loss, Brier, ECE, accuracy,
         balanced accuracy, precision, recall, F1, MCC, Cohen's kappa, majority baseline.

Disclosed limitations of THIS run (provisional)
-----------------------------------------------
* Transfer-entropy features (te_directional_diff, te_significance) are EXCLUDED: they are computed
  over each pair's full history (code review R4.10, lookahead into every event).
* The underlying pair pool and spread series carry the open data-layer and discovery findings
  (D1-D4, U4, R1.1 local-currency legs, S3 Purity selection lookahead). Labels are z-score
  convergence, not P&L, so B2-B4 do not touch them, but these numbers must be re-run after the
  data-layer fixes before any of them is cited.
* Every model's hyper-parameters are fixed up front (no tuning on val/test); val is used only for
  the MLP's early stopping. Each (model, split) run is recorded as a trial in the output so the
  number of comparisons is explicit.
* RBF-SVM: sklearn SVC scales ~O(n^2) in training size; trained on the full train split unless
  --svm-max-train is given (then a time-stratified subsample, disclosed in the output). Scored by
  decision_function -> ranking metrics only; probability metrics reported NaN, not faked.

Verified against synthetic ground truth first: debug/_verify_ml_model_comparison_purged.py.

Usage (project root, CachyOS for RAM/CPU):
    python research/ml_model_comparison_purged.py [--embargo-pct 0.01] [--svm-max-train N]
"""
import argparse
import json
import logging
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")
_EXCLUDED_FEATURES = ("te_directional_diff", "te_significance")  # R4.10 lookahead

log = logging.getLogger("ml_model_comparison_purged")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    fh = logging.FileHandler(os.path.join(_ROOT, "latest_run_ml_model_comparison_purged.log"),
                             mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(ch)
    log.addHandler(fh)


# ---------------------------------------------------------------------------
# Split
# ---------------------------------------------------------------------------

def purged_embargoed_split(df: pd.DataFrame, purge: bool = True, embargo: pd.Timedelta = pd.Timedelta(0),
                           train_pct: float = None, val_pct: float = None) -> dict:
    """Chronological train/val/test split of an events frame with `entry_time` and
    `label_end_time`. Returns {"train","val","test"} -> index labels of `df`.

    Boundaries are the entry_time found at positional rows int(n*train_pct) and
    int(n*(train_pct+val_pct)) of the time-sorted frame; membership is by timestamp
    (< boundary), so events sharing an entry_time never straddle a boundary.
    purge: drop train events with label_end_time >= val boundary, and val events with
    label_end_time >= test boundary. embargo: drop val events with entry_time < val
    boundary + embargo, and test events with entry_time < test boundary + embargo."""
    train_pct = Config.ML.TRAIN_PCT if train_pct is None else train_pct
    val_pct = Config.ML.VAL_PCT if val_pct is None else val_pct
    d = df.sort_values("entry_time", kind="mergesort")
    n = len(d)
    t = d["entry_time"]
    b_val = t.iloc[int(n * train_pct)]
    b_test = t.iloc[int(n * (train_pct + val_pct))]
    train = d[t < b_val]
    val = d[(t >= b_val) & (t < b_test)]
    test = d[t >= b_test]
    if purge:
        train = train[train["label_end_time"] < b_val]
        val = val[val["label_end_time"] < b_test]
    if embargo > pd.Timedelta(0):
        val = val[val["entry_time"] >= b_val + embargo]
        test = test[test["entry_time"] >= b_test + embargo]
    return {"train": train.index, "val": val.index, "test": test.index,
            "boundary_val": b_val, "boundary_test": b_test}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _ece(y, p, n_bins=10):
    bins = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, bins) - 1, 0, n_bins - 1)
    e = 0.0
    for b in range(n_bins):
        m = idx == b
        if m.any():
            e += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(e)


def _cluster_boot_auc(y, s, days, n_boot, rng, s_ref=None):
    """Resample whole entry DATES (all events on a date together) -- events on the same date
    share market moves and are not independent. Returns bootstrap AUCs (and paired diffs
    vs s_ref if given)."""
    from sklearn.metrics import roc_auc_score
    codes, uniq = pd.factorize(pd.Series(days).dt.normalize())
    groups = [np.flatnonzero(codes == k) for k in range(len(uniq))]
    aucs, diffs = [], []
    for _ in range(n_boot):
        pick = rng.integers(0, len(groups), len(groups))
        ix = np.concatenate([groups[k] for k in pick])
        yb = y[ix]
        if yb.min() == yb.max():
            continue
        a = roc_auc_score(yb, s[ix])
        aucs.append(a)
        if s_ref is not None:
            diffs.append(a - roc_auc_score(yb, s_ref[ix]))
    return np.array(aucs), np.array(diffs)


def metric_panel(y, score, has_proba: bool, threshold: float = 0.5, cluster_days=None,
                 n_boot: int = 0, rng=None, score_ref=None) -> dict:
    """Full metric panel for a binary classifier. `score` is P(class 1) when has_proba, else a
    ranking score (e.g. SVM decision_function; hard predictions then use score >= 0)."""
    from sklearn import metrics as M
    y = np.asarray(y).astype(int)
    s = np.asarray(score, dtype=float)
    pred = (s >= threshold).astype(int) if has_proba else (s >= 0).astype(int)
    out = {
        "auc_roc": float(M.roc_auc_score(y, s)),
        "pr_auc": float(M.average_precision_score(y, s)),
        "accuracy": float(M.accuracy_score(y, pred)),
        "balanced_accuracy": float(M.balanced_accuracy_score(y, pred)),
        "precision": float(M.precision_score(y, pred, zero_division=0)),
        "recall": float(M.recall_score(y, pred, zero_division=0)),
        "f1": float(M.f1_score(y, pred, zero_division=0)),
        "mcc": float(M.matthews_corrcoef(y, pred)),
        "cohen_kappa": float(M.cohen_kappa_score(y, pred)),
        "log_loss": float(M.log_loss(y, np.clip(s, 1e-12, 1 - 1e-12))) if has_proba else float("nan"),
        "brier": float(M.brier_score_loss(y, s)) if has_proba else float("nan"),
        "ece": _ece(y, s) if has_proba else float("nan"),
        "n": int(len(y)), "pos_rate": float(y.mean()),
    }
    if n_boot and cluster_days is not None:
        rng = rng or np.random.default_rng(42)
        aucs, diffs = _cluster_boot_auc(y, s, cluster_days, n_boot, rng,
                                        None if score_ref is None else np.asarray(score_ref, float))
        out["auc_ci_lo"], out["auc_ci_hi"] = (float(np.percentile(aucs, 5)), float(np.percentile(aucs, 95))) \
            if len(aucs) else (float("nan"), float("nan"))
        if len(diffs):
            out["auc_diff_vs_ref"] = float(out["auc_roc"] - M.roc_auc_score(y, np.asarray(score_ref, float)))
            out["auc_diff_ci_lo"] = float(np.percentile(diffs, 5))
            out["auc_diff_ci_hi"] = float(np.percentile(diffs, 95))
    return out


# ---------------------------------------------------------------------------
# Models (hyper-parameters fixed up front -- no tuning on val/test)
# ---------------------------------------------------------------------------

def _models(seed: int = 42):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC
    import xgboost as xgb
    n_jobs = os.cpu_count() or 1
    m = {
        # ml.py's exact XGBoost settings (binary objective).
        "xgboost": (xgb.XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.05,
                                      objective="binary:logistic", eval_metric="logloss",
                                      random_state=seed, n_jobs=1), True, True),
        "logreg_l2": (make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000,
                      class_weight="balanced")), True, False),
        "logreg_l1": (make_pipeline(StandardScaler(), LogisticRegression(C=1.0, penalty="l1",
                      solver="liblinear", max_iter=2000, class_weight="balanced")), True, False),
        "random_forest": (RandomForestClassifier(n_estimators=300, min_samples_leaf=50,
                          class_weight="balanced", random_state=seed, n_jobs=n_jobs), True, False),
        "knn": (make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=101,
                weights="distance", n_jobs=n_jobs)), True, False),
        "mlp": (make_pipeline(StandardScaler(), MLPClassifier(hidden_layer_sizes=(64, 32),
                alpha=1e-3, early_stopping=True, validation_fraction=0.1, max_iter=300,
                random_state=seed)), True, False),
        "svm_rbf": (make_pipeline(StandardScaler(), SVC(kernel="rbf", C=1.0, gamma="scale",
                    class_weight="balanced", cache_size=4000)), False, False),
    }
    try:
        import lightgbm as lgb
        m["lightgbm"] = (lgb.LGBMClassifier(n_estimators=300, num_leaves=31, learning_rate=0.05,
                         class_weight="balanced", random_state=seed, verbose=-1), True, False)
    except ImportError:
        log.warning("lightgbm not installed -- arm skipped (disclosed, not silently dropped)")
    return m


def _fit_score(name, model, has_proba, balanced_weight, Xtr, ytr, Xte):
    kw = {}
    if balanced_weight:  # ml.py weights XGBoost with balanced sample weights
        from sklearn.utils.class_weight import compute_sample_weight
        kw["sample_weight"] = compute_sample_weight("balanced", ytr)
    model.fit(Xtr, ytr, **kw)
    return model.predict_proba(Xte)[:, 1] if has_proba else model.decision_function(Xte)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--embargo-pct", type=float, default=0.01,
                    help="Embargo after each split boundary as a fraction of the events' total time span.")
    ap.add_argument("--svm-max-train", type=int, default=None)
    ap.add_argument("--n-boot", type=int, default=500)
    args = ap.parse_args()
    _setup_logging()
    import ml
    t0 = time.time()

    res = ml.build(min_class_samples=0, pit_safe=True)
    ex = res.examples.copy()
    if ex.empty or "label_end_time" not in ex:
        log.error("No examples or no label_end_time column (ml.py too old?) -- aborting")
        return
    ex["entry_time"] = pd.to_datetime(ex["entry_time"])
    ex["label_end_time"] = pd.to_datetime(ex["label_end_time"])
    feats = [c for c in ml._FEATURE_COLS if c not in _EXCLUDED_FEATURES]
    from sklearn.preprocessing import LabelEncoder
    le = LabelEncoder()
    ex["y"] = le.fit_transform(ex["label_for_training"])
    if len(le.classes_) != 2:
        log.error("Expected a binary label scheme, got %s -- aborting", list(le.classes_))
        return
    span = ex["entry_time"].max() - ex["entry_time"].min()
    embargo = span * args.embargo_pct
    log.info("Events: %d | classes %s | pos rate %.4f | features %s (excluded %s) | embargo %s",
             len(ex), list(le.classes_), ex["y"].mean(), feats, list(_EXCLUDED_FEATURES), embargo)

    rows, trials = [], []
    for split_name, purge, emb in (("positional", False, pd.Timedelta(0)), ("purged", True, embargo)):
        sp = purged_embargoed_split(ex, purge=purge, embargo=emb)
        tr, te = ex.loc[sp["train"]], ex.loc[sp["test"]]
        med = tr[feats].median()  # train-only imputation (ml.py convention)
        Xtr, Xte = tr[feats].fillna(med).to_numpy(), te[feats].fillna(med).to_numpy()
        ytr, yte = tr["y"].to_numpy(), te["y"].to_numpy()
        log.info("[%s] train %d | val %d | test %d | val boundary %s | test boundary %s",
                 split_name, len(tr), len(sp["val"]), len(te), sp["boundary_val"], sp["boundary_test"])
        maj = float((yte == np.bincount(ytr).argmax()).mean())
        ref_score = None
        for name, (model, has_proba, bal) in _models().items():
            t1 = time.time()
            Xfit, yfit, note = Xtr, ytr, ""
            if name == "svm_rbf" and args.svm_max_train and len(ytr) > args.svm_max_train:
                keep = np.linspace(0, len(ytr) - 1, args.svm_max_train).astype(int)  # time-stratified
                Xfit, yfit, note = Xtr[keep], ytr[keep], f"trained on {len(keep)} of {len(ytr)} (time-stratified)"
            try:
                s = _fit_score(name, model, has_proba, bal, Xfit, yfit, Xte)
            except Exception as e:
                log.warning("  %s failed: %s: %s", name, type(e).__name__, e)
                continue
            if name == "xgboost":
                ref_score = s
            m = metric_panel(yte, s, has_proba, cluster_days=te["entry_time"], n_boot=args.n_boot,
                             rng=np.random.default_rng(42),
                             score_ref=None if (name == "xgboost" or ref_score is None) else ref_score)
            m.update({"split": split_name, "model": name, "majority_baseline_acc": maj,
                      "n_train": len(yfit), "note": note, "fit_seconds": round(time.time() - t1, 1),
                      "capital_sim_sharpe": "DEFERRED (P&L findings B2-B4, P1)"})
            rows.append(m)
            trials.append({"split": split_name, "model": name, "auc_roc": m["auc_roc"]})
            log.info("  %-14s AUC %.4f [%.4f, %.4f]  PR-AUC %.4f  bal-acc %.4f  MCC %.4f  brier %s  (%.0fs)%s",
                     name, m["auc_roc"], m.get("auc_ci_lo", np.nan), m.get("auc_ci_hi", np.nan),
                     m["pr_auc"], m["balanced_accuracy"], m["mcc"],
                     f"{m['brier']:.4f}" if np.isfinite(m["brier"]) else "n/a", m["fit_seconds"],
                     f"  [{note}]" if note else "")

    out = pd.DataFrame(rows)
    os.makedirs(_OUT_DIR, exist_ok=True)
    out.to_parquet(os.path.join(_OUT_DIR, "ml_model_comparison_purged.parquet"))
    with open(os.path.join(_OUT_DIR, "ml_model_comparison_purged_trials.json"), "w") as f:
        json.dump({"n_trials": len(trials), "trials": trials,
                   "primary_metric": "auc_roc on purged test split",
                   "deferred_metric": "capital-sim Sharpe of model-filtered trades (B2-B4, P1)"}, f, indent=1)
    log.info("Saved %d (split, model) results = %d trials; %.1f min total",
             len(out), len(trials), (time.time() - t0) / 60)


if __name__ == "__main__":
    main()
