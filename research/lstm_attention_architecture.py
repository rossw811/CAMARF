"""
research/lstm_attention_architecture.py -- Ross's direct request (2026-07-22):
"add the architecture for LSTM/attention but don't use it in actual
backtesting" (dedicated_pass.md sec 11.8).

ARCHITECTURE ONLY. This module defines and mechanically verifies two
sequence-model architectures (LSTM, attention/transformer-encoder-style) so
they exist, are known to compile and run correctly, and are ready to pick
up the moment the blocking condition below is actually met. It does NOT:
  - train on any real CAMARF data,
  - get imported by ml.py, backtest.py, or MLConditioner,
  - produce a model artifact any production or comparison-arm path reads.

Why architecture-only, not trained: dedicated_pass.md sec 11.8 already
flagged this as a real, current blocker, not a caveat to add after building
anyway -- `research/ml_model_comparison.py` (built the same session) just
QUANTIFIED exactly how severe: ml.build() currently produces 24 total
labeled entry events across ALL 3 confirmed pairs combined (22
"not_converged" vs 2 "converged"), and even simple, low-capacity models
(logistic regression, shallow trees) could not beat a trivial majority-
class baseline on a 6-example test fold at that sample size. A sequence
model with materially MORE parameters than any of those, trained on FEWER
usable examples than that (building input sequences requires a lookback
window per example, which only shrinks the usable count further), would
not "learn a subtler pattern" -- it would memorize 20-odd training examples
with zero ability to distinguish real structure from noise, and no
holdout fold would be large enough to catch it. This isn't a hypothetical
risk to caveat after training; it's disqualifying at today's sample size,
and training anyway would produce a number that looks like a result but
means nothing.

**Unblocking condition** (dedicated_pass.md sec 11.8, unchanged): revisit
once the confirmed-pair set (or an appropriately-scoped adjacent dataset --
e.g. spread-level features pooled across a much larger candidate universe
rather than only the confirmed set) is large enough that a train/test split
has a realistic chance of generalizing. Not currently met.

Architectures defined:
  - build_lstm_classifier: a small 1-2 layer LSTM over a lookback window of
    the same per-bar features already computed for every confirmed pair
    (z_rolling, half_life_rolling -- persisted in each pair's
    spread_series_{A}_{B}.parquet), followed by a dense classification head.
  - build_attention_classifier: a single-head scaled dot-product
    self-attention block over the same windowed input (a minimal
    transformer-encoder-style layer, not a full multi-block transformer --
    proportionate to a comparison arm, not an attempt at a state-of-the-art
    architecture), followed by global average pooling and a dense head.

Both take input shaped (batch, timesteps, n_features) and output a
softmax/sigmoid probability over the SAME label scheme ml.py already uses
(Config.ML.LABEL_SCHEME), so if/when real training becomes responsible,
these plug into the same label vocabulary without redesign.

When the unblocking condition is met, real sequences would be built from
each entry event's own per_bar_by_pair series (z_rolling/half_life_rolling_
series, exactly what SpreadModel.fit_pair already computes and analysis.py
already persists) -- windowed to the same horizon_bars ml.py's own
EntryEvent labeling already uses, not a new convention. That extraction
pipeline is intentionally NOT built here yet -- building it would invite
"since it's built, let's just try training on real data anyway," exactly
the pressure this module's whole design is meant to resist.

Verified against synthetic ground truth only (by design -- no real data
touches this file): debug/_verify_lstm_attention_architecture.py confirms
both architectures compile, accept the documented input shape, produce
valid probability outputs (rows sum to 1, no NaN/Inf) on synthetic random
sequences, and that neither architecture is importable from ml.py or
backtest.py's own import graphs (a static guard against accidental wiring).

Usage (mechanical smoke test only, not training):
    python research/lstm_attention_architecture.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Two per-bar features currently persisted for every pair (z_rolling,
# half_life_rolling_series) -- see analysis.py's SpreadModel.fit_pair and
# CointScanner._enrich_with_deep_history's per_bar_by_pair construction.
# Matches ml.py's own _FEATURE_COLS vocabulary where the two overlap
# (zscore <-> z_rolling, half_life_current <-> half_life_rolling_series).
N_FEATURES = 2
DEFAULT_LOOKBACK_BARS = 20  # arbitrary, stated, not tuned -- a placeholder window size


def build_lstm_classifier(n_classes: int, lookback_bars: int = DEFAULT_LOOKBACK_BARS,
                           n_features: int = N_FEATURES):
    """Small 1-layer LSTM + dense head. Returns a compiled tf.keras.Model.
    NOT trained here -- see module docstring."""
    from tensorflow import keras
    from tensorflow.keras import layers

    inputs = keras.Input(shape=(lookback_bars, n_features), name="windowed_features")
    x = layers.LSTM(16, return_sequences=False)(inputs)
    x = layers.Dropout(0.3)(x)  # meaningful only once real training is responsible; harmless now
    outputs = layers.Dense(n_classes, activation="softmax" if n_classes > 2 else "sigmoid")(x)

    model = keras.Model(inputs, outputs, name="lstm_meta_labeler")
    model.compile(
        optimizer="adam",
        loss="sparse_categorical_crossentropy" if n_classes > 2 else "binary_crossentropy",
        metrics=["accuracy"],
    )
    return model


def build_attention_classifier(n_classes: int, lookback_bars: int = DEFAULT_LOOKBACK_BARS,
                                n_features: int = N_FEATURES):
    """Minimal single-head self-attention block (scaled dot-product) over the
    windowed input, global-average-pooled, + dense head. A proportionate
    comparison-arm architecture, not a full multi-block transformer. Returns
    a compiled tf.keras.Model. NOT trained here -- see module docstring."""
    from tensorflow import keras
    from tensorflow.keras import layers

    inputs = keras.Input(shape=(lookback_bars, n_features), name="windowed_features")
    # Project into a small embedding dim before attention -- MultiHeadAttention
    # needs key_dim, not raw n_features (often 2, too small to attend over
    # meaningfully on its own).
    x = layers.Dense(8, activation="relu")(inputs)
    attn_out = layers.MultiHeadAttention(num_heads=1, key_dim=8)(x, x)
    x = layers.Add()([x, attn_out])  # residual connection
    x = layers.LayerNormalization()(x)
    x = layers.GlobalAveragePooling1D()(x)
    outputs = layers.Dense(n_classes, activation="softmax" if n_classes > 2 else "sigmoid")(x)

    model = keras.Model(inputs, outputs, name="attention_meta_labeler")
    model.compile(
        optimizer="adam",
        loss="sparse_categorical_crossentropy" if n_classes > 2 else "binary_crossentropy",
        metrics=["accuracy"],
    )
    return model


def _mechanical_smoke_test():
    """Confirms both architectures compile and produce valid probability
    outputs on synthetic random data -- NOT a training run, NOT real data.
    Run directly (python research/lstm_attention_architecture.py) as a
    quick sanity check; the real verification lives in debug/_verify_
    lstm_attention_architecture.py."""
    rng = np.random.default_rng(0)
    X_synthetic = rng.normal(0, 1, size=(8, DEFAULT_LOOKBACK_BARS, N_FEATURES)).astype("float32")

    for name, builder in [("lstm", build_lstm_classifier), ("attention", build_attention_classifier)]:
        model = builder(n_classes=2)
        preds = model.predict(X_synthetic, verbose=0)
        print(f"{name}: output shape {preds.shape}, "
              f"min={preds.min():.4f} max={preds.max():.4f}, "
              f"any NaN={np.isnan(preds).any()}")


if __name__ == "__main__":
    print("=== Mechanical smoke test only -- NOT training on real data, "
          "NOT wired into any production path ===")
    _mechanical_smoke_test()
