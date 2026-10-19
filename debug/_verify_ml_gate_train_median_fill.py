"""
Regression test (found 2026-10-19 while building the PIT-pool default): ml.py imputes missing features with the TRAIN
split's median (_chronological_split_impute, BUG-D75), but the saved model payload carried no median, so
backtest.MLConditioner.predict_prob filled every missing feature with 0.0 -- train/serve skew (e.g. a missing Hurst
exponent was scored as 0.0, an extreme value the model never saw for missing rows).
Fix: ml.py saves the train median in the payload ("impute_median"); MLConditioner fills with it, and falls back to 0.0
with a one-time warning only for a model saved before the fix.
Checks: 1. payload helper stores the median per feature; 2. a loaded payload's median is what NaN features become;
3. an old payload (no median) still zero-fills, flagged; 4. supplied values are never overwritten.
Run: python debug/_verify_ml_gate_train_median_fill.py
"""
import os
import pickle
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


class _Spy:
    classes_ = None

    def __init__(self):
        self.seen = None

    def predict_proba(self, X):
        self.seen = X.copy()
        return np.array([[0.4, 0.6]])


def _load_payload(payload):
    from backtest import MLConditioner
    d = tempfile.mkdtemp()
    p = os.path.join(d, "model_stage1.pkl")
    with open(p, "wb") as f:
        pickle.dump(payload, f)
    m = object.__new__(MLConditioner)
    m.enabled, m._model, m._features, m._converge_indices = True, None, None, []
    m._load(model_path=p)
    return m


def main():
    try:
        import ml
        med = pd.Series({"a": 5.0, "b": -2.0})
        payload = ml._build_model_payload(_Spy(), None, ["a", "b"], med)
        check("payload_stores_train_median", payload.get("impute_median") == {"a": 5.0, "b": -2.0},
              f"{payload.get('impute_median')}")
    except Exception as e:  # missing helper on the old code
        check("payload_stores_train_median", False, f"{type(e).__name__}: {e}")
        payload = {"model": _Spy(), "feature_names": ["a", "b"], "classes": ["converged", "diverged"],
                   "impute_median": {"a": 5.0, "b": -2.0}}

    payload["model"] = spy = _Spy()
    payload["classes"] = ["converged", "diverged"]
    m = _load_payload(payload)
    m.predict_prob({"a": np.nan, "b": 1.0})
    seen = m._model.seen
    check("nan_feature_gets_train_median", seen is not None and seen.loc[0, "a"] == 5.0,
          f"a filled with {None if seen is None else seen.loc[0, 'a']}")
    check("supplied_value_kept", seen is not None and seen.loc[0, "b"] == 1.0)

    old = {"model": _Spy(), "feature_names": ["a", "b"], "classes": ["converged", "diverged"]}
    m_old = _load_payload(old)
    m_old.predict_prob({"a": np.nan, "b": 1.0})
    check("old_payload_zero_fill_flagged", m_old._model.seen is not None and m_old._model.seen.loc[0, "a"] == 0.0
          and getattr(m_old, "impute_fallback_zero", False) is True,
          f"flag={getattr(m_old, 'impute_fallback_zero', None)}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
