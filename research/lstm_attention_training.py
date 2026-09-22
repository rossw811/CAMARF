"""
research/lstm_attention_training.py -- the real training run `research/lstm_attention_
architecture.py` was deliberately built to wait for. That module's own docstring (2026-07-22,
Ross: "add the architecture for LSTM/attention but don't use it in actual backtesting") named its
own unblocking condition explicitly: "revisit once the confirmed-pair set... is large enough that
a train/test split has a realistic chance of generalizing." At the time: 24 labeled examples
across 3 pairs. As of tonight (2026-09-21): 69,592 labeled entry events across 1,225 of 1,375
episodic-confirmed pairs (`ml.py --pit-safe`, 2026-09-15 real run) -- Ross's own words: "we can
try the lstm as we have more data now." The condition is genuinely met, not just asserted.

Honest framing before results, not after: three independent methods have already shown the SAME
static feature set (zscore, half_life, coint_fraction_rolling, etc.) carries no usable signal for
predicting spread resolution on this pool -- a plain XGBoost classifier on the full 69,592
examples scored BELOW the majority-class baseline (54.24% vs 58.98%, 2026-09-15 real run). This
script is not testing "more capacity + more data = better" (that would be a weak reason to expect
a different answer) -- it is testing a genuinely different question the static-feature models
structurally cannot ask: does the SEQUENCE/temporal trajectory of z_rolling/half_life_rolling
leading up to an entry signal predict its outcome, beyond what a single snapshot value captures.
If the LSTM/attention models also fail to beat the majority baseline, that is a fourth independent
line of evidence the episodic pool lacks exploitable structure at this feature set, reported
honestly, not a failure of the exercise.

Reuses `ml.build(pit_safe=True)` directly for the event list (entry_time, label, pair identity) --
does NOT reimplement entry-detection or labeling. Only the INPUT REPRESENTATION differs from the
existing study: a (lookback_bars, 2) windowed sequence of z_rolling/half_life_rolling ending at
each event's own entry_time, instead of a static feature snapshot. Same chronological pooled
train/val/test split convention as `ml.py::_train_and_validate` (Config.ML.TRAIN_PCT/VAL_PCT,
sorted by entry_time, no shuffling -- this is a point-in-time-safe split, not a random one).

Usage:
    python research/lstm_attention_training.py
    python research/lstm_attention_training.py --lookback-bars 30
"""
import argparse
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import ml
from config import Config
from research.lstm_attention_architecture import (
    build_lstm_classifier, build_attention_classifier, DEFAULT_LOOKBACK_BARS, N_FEATURES,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")
_OUT_DIR = os.path.join(_ROOT, "output", "research")
_SEQ_FEATURES = ["z_rolling", "half_life_rolling"]

log = logging.getLogger("lstm_attention_training")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(os.path.join(_ROOT, "latest_run_lstm_attention_training.log"),
                              mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def _tf_dirname(tf_label: str) -> str:
    return ml._tf_dirname(tf_label)


def build_sequences(examples: pd.DataFrame, lookback_bars: int):
    """For each labeled entry event, extracts the last `lookback_bars` bars of
    z_rolling/half_life_rolling ending at (and including) entry_time from that pair's own
    spread_series_{A}_{B}.parquet. Events with fewer than `lookback_bars` real bars of history
    before entry_time are DROPPED (not padded with fabricated values) -- reported, not hidden.
    Groups by pair so each spread_series file is read exactly once regardless of how many events
    that pair contributes."""
    sequences, labels, entry_times, kept_idx = [], [], [], []
    n_dropped_short_history = 0
    n_dropped_missing_file = 0
    n_dropped_missing_cols = 0

    examples = examples.reset_index(drop=True)
    for (symbol_a, symbol_b, tf_label), group in examples.groupby(["symbol_a", "symbol_b", "tf_label"]):
        series_path = os.path.join(
            _RESULTS_DIR, _tf_dirname(tf_label), f"spread_series_{symbol_a}_{symbol_b}.parquet"
        )
        if not os.path.exists(series_path):
            n_dropped_missing_file += len(group)
            continue
        series = pd.read_parquet(series_path)
        if not all(c in series.columns for c in _SEQ_FEATURES):
            n_dropped_missing_cols += len(group)
            continue
        series = series[_SEQ_FEATURES]

        for idx, row in group.iterrows():
            entry_time = row["entry_time"]
            pos = series.index.searchsorted(entry_time, side="right") - 1
            if pos < 0 or series.index[pos] != entry_time:
                # entry_time must be an exact bar in this pair's own series -- ml.py's own
                # _find_entry_events sources entry_time FROM this same series, so an exact
                # match is expected; a miss means a real data-alignment problem, not padded over.
                n_dropped_missing_cols += 1
                continue
            start = pos - lookback_bars + 1
            if start < 0:
                n_dropped_short_history += 1
                continue
            window = series.iloc[start:pos + 1].to_numpy(dtype=np.float64)
            if not np.all(np.isfinite(window)):
                n_dropped_short_history += 1
                continue
            sequences.append(window)
            labels.append(row["label_for_training"])
            entry_times.append(entry_time)
            kept_idx.append(idx)

    log.info(f"Sequence build: {len(sequences)} kept, "
             f"{n_dropped_short_history} dropped (short/non-finite history), "
             f"{n_dropped_missing_file} dropped (no spread_series file), "
             f"{n_dropped_missing_cols} dropped (missing columns / entry_time mismatch)")

    if not sequences:
        return None, None, None

    X = np.stack(sequences)  # (n, lookback_bars, n_features)
    y = np.array(labels)
    order = np.argsort(entry_times)  # chronological, matches ml.py's own pooled-sort convention
    return X[order], y[order], np.array(entry_times)[order]


def _chronological_split(X, y):
    n = len(y)
    train_end = int(n * Config.ML.TRAIN_PCT)
    val_end = train_end + int(n * Config.ML.VAL_PCT)
    return (X[:train_end], y[:train_end]), (X[train_end:val_end], y[train_end:val_end]), \
           (X[val_end:], y[val_end:])


def _normalize(X_train, *others):
    """z-score each of the 2 features using TRAIN-only mean/std (matches ml.py's own
    train-only-imputation discipline -- computing normalization stats over val/test would leak
    their feature distribution into what the model sees at train time)."""
    mean = X_train.mean(axis=(0, 1), keepdims=True)
    std = X_train.std(axis=(0, 1), keepdims=True)
    std[std == 0] = 1.0
    return [(X - mean) / std for X in (X_train,) + others]


def _train_and_eval(name, build_fn, X_train, y_train, X_val, y_val, X_test, y_test, lookback_bars):
    from sklearn.utils.class_weight import compute_sample_weight

    model = build_fn(n_classes=2, lookback_bars=lookback_bars, n_features=N_FEATURES)
    sample_weight = compute_sample_weight("balanced", y_train)
    t0 = time.time()
    model.fit(
        X_train, y_train, sample_weight=sample_weight,
        validation_data=(X_val, y_val), epochs=30, batch_size=256, verbose=0,
    )
    fit_min = (time.time() - t0) / 60
    test_loss, test_acc = model.evaluate(X_test, y_test, verbose=0)
    majority_baseline = max(np.mean(y_test == 0), np.mean(y_test == 1))
    log.info(f"[{name}] trained in {fit_min:.1f} min, holdout accuracy={test_acc:.4f} "
             f"(majority baseline={majority_baseline:.4f}, "
             f"{'BEATS' if test_acc > majority_baseline else 'does NOT beat'} baseline)")
    return {"name": name, "test_accuracy": float(test_acc), "test_loss": float(test_loss),
            "majority_baseline": float(majority_baseline), "fit_minutes": fit_min,
            "n_train": len(y_train), "n_val": len(y_val), "n_test": len(y_test)}


def main():
    p = argparse.ArgumentParser(description="Train the LSTM/attention meta-labeler architectures "
                                             "for real, against the full episodic pool.")
    p.add_argument("--lookback-bars", type=int, default=DEFAULT_LOOKBACK_BARS)
    args = p.parse_args()

    _setup_logging()
    log.info("=== lstm_attention_training.py: real training run ===")
    log.info(f"lookback_bars={args.lookback_bars}")

    t0 = time.time()
    log.info("Running ml.build(pit_safe=True) to get the real, PIT-safe labeled event pool "
             "(same events/labels the existing XGBoost study used -- no relabeling)...")
    result = ml.build(pit_safe=True)
    log.info(f"ml.build() complete in {(time.time()-t0)/60:.1f} min, "
             f"{len(result.examples)} labeled examples across {len(result.pairs_used)} pairs")

    if result.examples.empty:
        log.error("No labeled examples produced -- nothing to train on.")
        return

    X, y_str, entry_times = build_sequences(result.examples, args.lookback_bars)
    if X is None:
        log.error("No sequences survived the lookback-history filter -- nothing to train on.")
        return

    classes = sorted(set(y_str))
    if len(classes) != 2:
        log.error(f"Expected binary labels, got {classes} -- LABEL_SCHEME must be 'binary'.")
        return
    y = (y_str == classes[1]).astype(int)
    log.info(f"Sequence dataset: {len(y)} examples, label distribution "
             f"{classes[0]}={int((y==0).sum())} ({(y==0).mean():.2%}) "
             f"{classes[1]}={int((y==1).sum())} ({(y==1).mean():.2%})")

    (X_train, y_train), (X_val, y_val), (X_test, y_test) = _chronological_split(X, y)
    if len(X_train) == 0 or len(X_test) == 0:
        log.error("Chronological split left an empty train or test fold -- stopping.")
        return
    X_train, X_val, X_test = _normalize(X_train, X_val, X_test)

    results = []
    results.append(_train_and_eval("lstm", build_lstm_classifier, X_train, y_train, X_val, y_val,
                                    X_test, y_test, args.lookback_bars))
    results.append(_train_and_eval("attention", build_attention_classifier, X_train, y_train,
                                    X_val, y_val, X_test, y_test, args.lookback_bars))

    out = {
        "lookback_bars": args.lookback_bars,
        "n_sequences_total": int(len(y)),
        "n_pairs": len(result.pairs_used),
        "label_positive_class": classes[1],
        "label_distribution": {classes[0]: int((y == 0).sum()), classes[1]: int((y == 1).sum())},
        "prior_static_feature_xgboost_holdout_accuracy": 0.5424,  # 2026-09-15 real run, for direct comparison
        "results": results,
    }
    out_path = os.path.join(_OUT_DIR, "lstm_attention_training_results.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    log.info(f"Saved => {out_path}")

    log.info("\n=== SUMMARY ===")
    log.info(f"Majority-class baseline (holdout): {results[0]['majority_baseline']:.4f}")
    log.info(f"Prior static-feature XGBoost (2026-09-15 real run): 0.5424 (BELOW majority baseline)")
    for r in results:
        verdict = "BEATS" if r["test_accuracy"] > r["majority_baseline"] else "does NOT beat"
        log.info(f"{r['name']}: holdout accuracy={r['test_accuracy']:.4f} ({verdict} majority baseline)")

    runtime = (time.time() - t0) / 60
    log.info(f"\nlstm_attention_training.py complete ({runtime:.1f} min total)")


if __name__ == "__main__":
    main()
