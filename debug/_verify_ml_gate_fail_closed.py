"""
Regression test (inconsistency sweep C6, 2026-09-28): backtest.MLConditioner.predict_prob returned 1.0 -- "allow the
trade" -- on ANY exception, including a feature column the model expects being absent (KeyError), so a broken Layer-2
gate silently let every entry through. (Returning NaN would have done the same: `ml_prob < threshold` is False.)
Fix: fail CLOSED (0.0 -> the entry is gated out), count and log errors; features the model expects but the caller
did not provide are recorded once and warned about (their values are still zero-filled, a modelling choice now
visible, not silent).
Checks: 1. a model that raises -> 0.0 and n_predict_errors == 1; 2. a missing feature -> prediction still made, the
missing name recorded; 3. disabled conditioner -> 1.0 pass-through (unchanged: Layer 2 off means no gate).
Run: python debug/_verify_ml_gate_fail_closed.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from backtest import MLConditioner

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


class _Boom:
    def predict_proba(self, X):
        raise RuntimeError("boom")


class _Const:
    def predict_proba(self, X):
        return np.array([[0.3, 0.7]])


def _make(model, feats, enabled=True):
    m = object.__new__(MLConditioner)
    m.enabled, m._model, m._features, m._converge_indices = enabled, model, feats, [1]
    return m


def main():
    m = _make(_Boom(), ["a", "b"])
    p = m.predict_prob({"a": 1.0, "b": 2.0})
    check("error_fails_closed", p == 0.0 and getattr(m, "n_predict_errors", 0) == 1, f"p={p} errors={getattr(m, 'n_predict_errors', None)}")
    m2 = _make(_Const(), ["a", "b", "c"])
    p2 = m2.predict_prob({"a": 1.0, "b": 2.0})
    check("missing_feature_recorded", abs(p2 - 0.7) < 1e-12 and "c" in getattr(m2, "missing_features", set()),
          f"p={p2} missing={getattr(m2, 'missing_features', None)}")
    check("disabled_passthrough", _make(None, [], enabled=False).predict_prob({}) == 1.0)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
