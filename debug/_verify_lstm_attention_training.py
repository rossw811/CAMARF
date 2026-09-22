"""
Synthetic verification for research/lstm_attention_training.py -- no real ml.py/spread_series
data, fabricated pairs with a KNOWN entry-time/history-length shape, run BEFORE trusting the real
training run.

Checks:
  1. build_sequences() extracts a window of exactly `lookback_bars` bars ENDING AT entry_time
     (inclusive), reads the correct pair's own spread_series file, and correctly DROPS an event
     whose pre-entry history is shorter than the requested lookback (not padded/fabricated).
  2. _chronological_split() matches Config.ML.TRAIN_PCT/VAL_PCT sizes and preserves time order
     (no shuffling).
  3. _normalize() computes mean/std from the TRAIN split only, not leaked from val/test.
  4. End-to-end: both real architectures (build_lstm_classifier, build_attention_classifier)
     train on a tiny synthetic dataset without crashing and report a holdout accuracy in [0, 1].
     Skipped (not failed) if tensorflow isn't installed in this environment -- a real
     environment gap, not a logic bug in this test.

Run: python debug/_verify_lstm_attention_training.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from config import Config
from research.lstm_attention_training import build_sequences, _chronological_split, _normalize

PASS, FAIL, SKIP = [], [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _write_spread_series(root, tf_dir, symbol_a, symbol_b, n_bars):
    d = os.path.join(root, tf_dir)
    os.makedirs(d, exist_ok=True)
    idx = pd.date_range("2020-01-01", periods=n_bars, freq="1h")
    rng = np.random.default_rng(hash((symbol_a, symbol_b)) % (2**31))
    df = pd.DataFrame({
        "z_rolling": rng.normal(0, 1, n_bars),
        "half_life_rolling": rng.uniform(5, 50, n_bars),
    }, index=idx)
    path = os.path.join(d, f"spread_series_{symbol_a}_{symbol_b}.parquet")
    df.to_parquet(path)
    return df


def test_build_sequences(tmp_root):
    import research.lstm_attention_training as mod
    mod._RESULTS_DIR = tmp_root  # monkeypatch the results dir to our synthetic tree

    # Pair AAA/BBB: 100 bars, plenty of history for any entry after bar 20.
    series1 = _write_spread_series(tmp_root, "1day", "AAA", "BBB", 100)
    # Pair CCC/DDD: only 15 bars -- any entry event here has <20 bars of history.
    series2 = _write_spread_series(tmp_root, "1day", "CCC", "DDD", 15)

    examples = pd.DataFrame([
        {"symbol_a": "AAA", "symbol_b": "BBB", "tf_label": "1D",
         "entry_time": series1.index[50], "label_for_training": "converged"},
        {"symbol_a": "AAA", "symbol_b": "BBB", "tf_label": "1D",
         "entry_time": series1.index[10], "label_for_training": "not_converged"},  # <20 bars before it
        {"symbol_a": "CCC", "symbol_b": "DDD", "tf_label": "1D",
         "entry_time": series2.index[14], "label_for_training": "converged"},  # only 15 bars total
    ])

    X, y, entry_times = build_sequences(examples, lookback_bars=20)
    check("build_sequences.drops_short_history_examples", X is not None and len(X) == 1, len(X) if X is not None else None)
    if X is not None and len(X) == 1:
        check("build_sequences.correct_window_shape", X.shape == (1, 20, 2), X.shape)
        expected_window = series1.iloc[31:51][["z_rolling", "half_life_rolling"]].to_numpy()
        check("build_sequences.window_ends_at_entry_time_inclusive",
              np.allclose(X[0], expected_window))
        check("build_sequences.correct_label_kept", y[0] == "converged", y[0])


def test_chronological_split():
    n = 1000
    X = np.arange(n).reshape(n, 1, 1).astype(float)
    y = np.zeros(n, dtype=int)
    (X_train, y_train), (X_val, y_val), (X_test, y_test) = _chronological_split(X, y)
    check("split.train_size_matches_config",
          len(X_train) == int(n * Config.ML.TRAIN_PCT), len(X_train))
    check("split.val_size_matches_config",
          len(X_val) == int(n * Config.ML.VAL_PCT), len(X_val))
    check("split.sizes_sum_to_total", len(X_train) + len(X_val) + len(X_test) == n)
    check("split.preserves_chronological_order",
          X_train[-1, 0, 0] < X_val[0, 0, 0] < X_test[0, 0, 0] if len(X_val) and len(X_test) else True)


def test_normalize_no_leakage():
    rng = np.random.default_rng(3)
    X_train = rng.normal(0, 1, (100, 5, 2))
    X_val = rng.normal(100, 50, (20, 5, 2))    # deliberately very different distribution
    X_test = rng.normal(-100, 50, (20, 5, 2))  # deliberately very different distribution

    X_train_n, X_val_n, X_test_n = _normalize(X_train, X_val, X_test)
    check("normalize.train_mean_near_zero_after_own_normalization",
          abs(X_train_n.mean()) < 0.2, X_train_n.mean())
    # If val/test leaked into the normalization stats, their normalized mean would also land
    # near 0 despite being drawn from wildly different distributions -- it should NOT.
    check("normalize.val_not_renormalized_to_zero_mean_no_leakage",
          abs(X_val_n.mean()) > 1.0, X_val_n.mean())
    check("normalize.test_not_renormalized_to_zero_mean_no_leakage",
          abs(X_test_n.mean()) > 1.0, X_test_n.mean())


def test_end_to_end_training():
    try:
        from research.lstm_attention_architecture import build_lstm_classifier, build_attention_classifier
        import tensorflow  # noqa
    except ImportError:
        SKIP.append("end_to_end_training (tensorflow not installed)")
        print("[SKIP] end_to_end_training -- tensorflow not installed in this environment")
        return

    from research.lstm_attention_training import _train_and_eval

    rng = np.random.default_rng(11)
    n = 200
    X = rng.normal(0, 1, (n, 20, 2))
    y = (rng.uniform(0, 1, n) > 0.5).astype(int)
    X_train, y_train = X[:120], y[:120]
    X_val, y_val = X[120:160], y[120:160]
    X_test, y_test = X[160:], y[160:]

    r = _train_and_eval("lstm_smoke", build_lstm_classifier, X_train, y_train, X_val, y_val,
                         X_test, y_test, lookback_bars=20)
    check("end_to_end.lstm_returns_valid_accuracy", 0.0 <= r["test_accuracy"] <= 1.0, r["test_accuracy"])
    check("end_to_end.lstm_returns_valid_auc", 0.0 <= r["test_auc_roc"] <= 1.0, r["test_auc_roc"])
    r2 = _train_and_eval("attention_smoke", build_attention_classifier, X_train, y_train, X_val, y_val,
                          X_test, y_test, lookback_bars=20)
    check("end_to_end.attention_returns_valid_accuracy", 0.0 <= r2["test_accuracy"] <= 1.0, r2["test_accuracy"])
    check("end_to_end.attention_returns_valid_auc", 0.0 <= r2["test_auc_roc"] <= 1.0, r2["test_auc_roc"])


def main():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        test_build_sequences(tmp)
    test_chronological_split()
    test_normalize_no_leakage()
    test_end_to_end_training()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed" +
          (f", {len(SKIP)} skipped (environment gap)" if SKIP else ""))
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
