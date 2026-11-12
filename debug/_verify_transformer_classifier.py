"""
Synthetic ground truth for research/lstm_attention_architecture.build_transformer_classifier (architecture-only, like
the LSTM/attention arms -- nothing here touches real CAMARF data).
  1. builds and FITS (not only predicts -- the 2026-09-21 shape bug was invisible to predict-only checks) for binary
     and 3-class labels; outputs are valid probabilities
  2. order task: random windows of 20 bars, label = 1 if the window's maximum comes before its minimum. Shuffling bars
     leaves the value set unchanged, so only an order-aware model can beat chance. With the position embedding the
     transformer reaches > 0.85 held-out accuracy ...
  3. ... and without it (permutation-invariant) it stays at chance (< 0.6)
Run: python debug/_verify_transformer_classifier.py   (TensorFlow, a few minutes on the Surface)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import numpy as np

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    import tensorflow as tf
    import lstm_attention_architecture as laa
    rng = np.random.default_rng(20261111)
    L, nf = laa.DEFAULT_LOOKBACK_BARS, laa.N_FEATURES

    ok, det = True, []
    for nc in (2, 3):
        tf.keras.utils.set_random_seed(0)
        m = laa.build_transformer_classifier(nc)
        X = rng.normal(size=(64, L, nf)).astype("float32")
        m.fit(X, rng.integers(0, nc, 64), epochs=1, verbose=0)
        p = m.predict(X, verbose=0)
        good = np.all(np.isfinite(p)) and p.min() >= 0 and p.max() <= 1 and \
            (p.shape == (64, 1) if nc == 2 else (p.shape == (64, 3) and np.allclose(p.sum(1), 1, atol=1e-5)))
        ok &= good
        det.append(f"{nc}-class shape={p.shape}")
    check("1 builds, fits, valid probabilities", ok, "; ".join(det))

    n = 6000
    X = rng.normal(size=(n, L, nf)).astype("float32")
    y = (X[:, :, 0].argmax(1) < X[:, :, 0].argmin(1)).astype("float32")
    acc = {}
    for pos in (True, False):
        tf.keras.utils.set_random_seed(0)
        m = laa.build_transformer_classifier(2, positional=pos)
        m.fit(X[:5000], y[:5000], validation_split=0.1, epochs=40, batch_size=64, verbose=0,
              callbacks=[tf.keras.callbacks.EarlyStopping(patience=8, restore_best_weights=True)])
        acc[pos] = float(m.evaluate(X[5000:], y[5000:], verbose=0)[1])
    check("2 order task learned with position embedding", acc[True] > 0.85, f"held-out acc={acc[True]:.3f}")
    check("3 without position embedding: chance", acc[False] < 0.6, f"held-out acc={acc[False]:.3f} (base rate "
          f"{y[5000:].mean():.3f})")

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
