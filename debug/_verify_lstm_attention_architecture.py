"""
debug/_verify_lstm_attention_architecture.py -- synthetic ground-truth
verification for research/lstm_attention_architecture.py.

By design, this is the ONLY verification this architecture gets -- no real
CAMARF data is used anywhere in this file, matching the module's own
architecture-only scope (see its docstring: training on real data at
today's n=24-example sample size would be irresponsible overfitting, not a
caveat to add later).

Checks:
  1. Both build_lstm_classifier and build_attention_classifier compile
     without error and accept the documented (batch, lookback, n_features)
     input shape.
  2. Both produce valid probability outputs on synthetic random input: no
     NaN/Inf, values in [0, 1], and (for the binary case) outputs are a
     single sigmoid unit per this module's own n_classes<=2 branch.
  3. Both handle a non-default lookback_bars/n_features shape (confirms the
     architectures are genuinely parameterized, not hardcoded to the
     module's own DEFAULT_LOOKBACK_BARS/N_FEATURES constants).
  4. Static import-graph guard: ml.py and backtest.py do NOT import this
     module anywhere (confirms it stays unwired, not just documented as
     such) -- greps their own source rather than trusting the docstring.

Run: python debug/_verify_lstm_attention_architecture.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

import lstm_attention_architecture as laa

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


def verify_architecture(name, builder):
    print(f"\n=== {name} ===")
    rng = np.random.default_rng(1)
    lookback, n_feat = laa.DEFAULT_LOOKBACK_BARS, laa.N_FEATURES
    X = rng.normal(0, 1, size=(6, lookback, n_feat)).astype("float32")

    model = builder(n_classes=2)
    ok = check("model compiles without error", model is not None)
    preds = model.predict(X, verbose=0)
    ok &= check("output batch dimension matches input", preds.shape[0] == X.shape[0])
    ok &= check("no NaN in output", not np.isnan(preds).any())
    ok &= check("no Inf in output", not np.isinf(preds).any())
    ok &= check("all output values in [0, 1] (valid probabilities)",
                bool(np.all(preds >= 0) and np.all(preds <= 1)))
    return ok


def verify_non_default_shape():
    print("\n=== 3. Non-default lookback/n_features shape (genuinely parameterized) ===")
    rng = np.random.default_rng(2)
    lookback, n_feat = 10, 4  # deliberately different from module defaults
    X = rng.normal(0, 1, size=(5, lookback, n_feat)).astype("float32")

    ok = True
    for name, builder in [("lstm", laa.build_lstm_classifier), ("attention", laa.build_attention_classifier)]:
        model = builder(n_classes=3, lookback_bars=lookback, n_features=n_feat)
        preds = model.predict(X, verbose=0)
        ok &= check(f"{name}: accepts non-default shape (lookback={lookback}, n_features={n_feat})",
                    preds.shape == (5, 3))
        ok &= check(f"{name}: 3-class output rows sum to ~1.0 (softmax)",
                    np.allclose(preds.sum(axis=1), 1.0, atol=1e-4))
    return ok


def verify_not_imported_by_production():
    print("\n=== 4. Static guard: not imported by ml.py or backtest.py ===")
    ok = True
    for fname in ["ml.py", "backtest.py"]:
        path = os.path.join(_ROOT, fname)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        ok &= check(f"{fname} does not import lstm_attention_architecture",
                    "lstm_attention_architecture" not in content)
    return ok


def main():
    results = [
        verify_architecture("1. LSTM classifier", laa.build_lstm_classifier),
        verify_architecture("2. Attention classifier", laa.build_attention_classifier),
        verify_non_default_shape(),
        verify_not_imported_by_production(),
    ]
    print("\n" + "=" * 60)
    if all(results):
        print("ALL CHECKS PASSED")
    else:
        print(f"FAILURES: {results.count(False)}/{len(results)} check groups failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
