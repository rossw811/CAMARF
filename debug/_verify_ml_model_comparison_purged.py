"""
Synthetic ground-truth checks for research/ml_model_comparison_purged.py (2026-09-26, audit step 3).

Tests the two pieces the real run's credibility rests on, against hand-constructed inputs with an
analytically known answer (no model-fitting noise):

  1. purged_embargoed_split(): chronological 60/20/20 by entry_time, then
     - PURGE: drop train events whose label_end_time >= first val entry_time, and val events whose
       label_end_time >= first test entry_time (their outcome window overlaps the next split);
     - EMBARGO: drop val/test events whose entry_time falls within `embargo` of the split boundary
       (cross-sectional contamination: other pairs trading the same dates right at the boundary).
     Also checks the unpurged comparison arm reproduces ml.py's plain positional split exactly.
  2. metric_panel(): every metric vs a hand-computed value on a tiny fixed array, plus the
     day-cluster bootstrap CI containing the point AUC.

Run: python debug/_verify_ml_model_comparison_purged.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.ml_model_comparison_purged import metric_panel, purged_embargoed_split

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _events(n=100, horizon_days=3):
    t0 = pd.Timestamp("2020-01-01")
    entry = [t0 + pd.Timedelta(days=i) for i in range(n)]
    return pd.DataFrame({
        "entry_time": entry,
        "label_end_time": [e + pd.Timedelta(days=horizon_days) for e in entry],
        "y": np.arange(n) % 2,
    })


def test_unpurged_matches_positional_split():
    df = _events()
    s = purged_embargoed_split(df, purge=False, embargo=pd.Timedelta(0))
    check("unpurged.sizes_60_20_20", (len(s["train"]), len(s["val"]), len(s["test"])) == (60, 20, 20),
          f"got {(len(s['train']), len(s['val']), len(s['test']))}")
    check("unpurged.train_is_first_60", list(s["train"]) == list(range(60)))


def test_purge_drops_exactly_the_overlapping_tail():
    # One event per day, label resolves 3 days later. Val starts at day 60 -> train events whose
    # label_end (day i+3) >= day 60 are i = 57, 58, 59 -> exactly 3 dropped. Same at test start
    # (day 80): val events 77, 78, 79 dropped.
    df = _events()
    s = purged_embargoed_split(df, purge=True, embargo=pd.Timedelta(0))
    check("purge.train_drops_57_58_59", list(s["train"]) == list(range(57)),
          f"train tail={list(s['train'])[-3:]}")
    check("purge.val_drops_77_78_79", list(s["val"]) == list(range(60, 77)),
          f"val={list(s['val'])[:2]}..{list(s['val'])[-2:]}")
    check("purge.test_untouched", list(s["test"]) == list(range(80, 100)))
    ends = df.loc[list(s["train"]), "label_end_time"]
    check("purge.no_train_label_reaches_val", bool((ends < df.loc[60, "entry_time"]).all()))


def test_embargo_drops_boundary_starts():
    # Embargo 2 days: val events with entry < day 60 + 2d (days 60, 61) and test events with
    # entry < day 80 + 2d (days 80, 81) are dropped.
    df = _events()
    s = purged_embargoed_split(df, purge=True, embargo=pd.Timedelta(days=2))
    check("embargo.val_starts_at_62", list(s["val"])[0] == 62, f"val[0]={list(s['val'])[0]}")
    check("embargo.test_starts_at_82", list(s["test"])[0] == 82, f"test[0]={list(s['test'])[0]}")


def test_split_boundaries_are_by_time_not_row_for_ties():
    # Two pairs entering on the SAME timestamps (cross-sectional duplicates): a positional split
    # could put one copy of a date in train and its twin in val. The split must keep all events
    # sharing a timestamp on the same side.
    a = _events(50)
    b = _events(50)
    df = pd.concat([a, b], ignore_index=True)
    s = purged_embargoed_split(df, purge=False, embargo=pd.Timedelta(0))
    tr_times = set(df.loc[list(s["train"]), "entry_time"])
    va_times = set(df.loc[list(s["val"]), "entry_time"])
    te_times = set(df.loc[list(s["test"]), "entry_time"])
    check("ties.no_timestamp_straddles_train_val", tr_times.isdisjoint(va_times))
    check("ties.no_timestamp_straddles_val_test", va_times.isdisjoint(te_times))


def test_metric_panel_hand_values():
    # y = [0,0,1,1], scores = [0.1, 0.4, 0.35, 0.8]: AUC = 3/4 (pairs (1,0): 0.35>0.1 yes,
    # 0.35>0.4 no, 0.8>0.1 yes, 0.8>0.4 yes). At threshold 0.5: preds [0,0,0,1] -> TP=1 FN=1
    # TN=2 FP=0 -> accuracy 0.75, balanced acc (0.5+1)/2 = 0.75, precision 1.0, recall 0.5,
    # F1 = 2/3. Brier = mean((p-y)^2) = (0.01+0.16+0.4225+0.04)/4 = 0.158125.
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.4, 0.35, 0.8])
    m = metric_panel(y, p, has_proba=True)
    check("metric.auc", abs(m["auc_roc"] - 0.75) < 1e-12, f"{m['auc_roc']}")
    check("metric.accuracy", abs(m["accuracy"] - 0.75) < 1e-12, f"{m['accuracy']}")
    check("metric.balanced_accuracy", abs(m["balanced_accuracy"] - 0.75) < 1e-12)
    check("metric.precision", abs(m["precision"] - 1.0) < 1e-12)
    check("metric.recall", abs(m["recall"] - 0.5) < 1e-12)
    check("metric.f1", abs(m["f1"] - 2 / 3) < 1e-12, f"{m['f1']}")
    check("metric.brier", abs(m["brier"] - 0.158125) < 1e-12, f"{m['brier']}")
    # Score-only model (e.g. SVM decision_function): probability metrics must be NaN, not faked.
    m2 = metric_panel(y, p * 10 - 3, has_proba=False)
    check("metric.score_only_auc_same", abs(m2["auc_roc"] - 0.75) < 1e-12)
    check("metric.score_only_brier_nan", np.isnan(m2["brier"]) and np.isnan(m2["log_loss"]))


def test_cluster_bootstrap_ci_contains_point():
    rng = np.random.default_rng(0)
    n = 2000
    y = rng.integers(0, 2, n)
    s = y * 0.6 + rng.normal(0, 1, n)
    days = pd.Series(pd.Timestamp("2020-01-01") + pd.to_timedelta(rng.integers(0, 200, n), "D"))
    m = metric_panel(y, s, has_proba=False, cluster_days=days, n_boot=300, rng=rng)
    check("bootstrap.ci_contains_point", m["auc_ci_lo"] <= m["auc_roc"] <= m["auc_ci_hi"],
          f"{m['auc_ci_lo']:.3f} <= {m['auc_roc']:.3f} <= {m['auc_ci_hi']:.3f}")
    check("bootstrap.ci_nondegenerate", m["auc_ci_hi"] - m["auc_ci_lo"] > 0.005)


if __name__ == "__main__":
    test_unpurged_matches_positional_split()
    test_purge_drops_exactly_the_overlapping_tail()
    test_embargo_drops_boundary_starts()
    test_split_boundaries_are_by_time_not_row_for_ties()
    test_metric_panel_hand_values()
    test_cluster_bootstrap_ci_contains_point()
    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
