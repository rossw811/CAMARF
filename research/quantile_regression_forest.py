"""
research/quantile_regression_forest.py — comparison/diagnostic method, NOT
part of the production pipeline.

Meinshausen (2006), "Quantile Regression Forests," Journal of Machine
Learning Research 7. ml.py's Stage 1 gate is a CLASSIFIER: given entry
features, predict a 4-class outcome bucket (strong_converge/weak_converge/
no_move/diverge_further). QRF asks a different, complementary question:
given the same features, what is the full CONDITIONAL DISTRIBUTION of the
continuous outcome (z_future, the actual forward z-score ml.py already
computes per EntryEvent but collapses into a class label) — not just "will
this converge" but "what's the 10th/50th/90th percentile of where it lands."

No `quantile-forest` package is installed in this environment (checked
directly rather than assumed) and adding a new dependency for something
implementable in ~20 lines on top of sklearn's own RandomForestRegressor
isn't warranted — implements Meinshausen's actual method directly: train a
standard RandomForestRegressor, then at prediction time, for each tree, find
which leaf a query point falls into and pool ALL training y-values sharing
that leaf across every tree, and take empirical quantiles of that pooled,
weighted set. This is NOT the same as sklearn's own `GradientBoostingRegressor
(loss="quantile")` (a different model family per quantile, no shared tree
structure across quantiles) — a real distinction worth being precise about,
since GBR-with-quantile-loss is sometimes miscited as "quantile regression
forest" in less careful writeups.

Reuses ml.py's own `_build_examples_for_pair` and `_FEATURE_COLS` directly
(same pattern as rmt_feature_denoising.py this session — redirect
`ml._tf_dirname` per timeframe to the resolved live/archived directory,
never reimplement the entry-event/labeling logic). Given ml.py's own
documented data constraint (20 examples vs. 30/class needed to even train
Stage 1's classifier), QRF faces the identical wall — reported honestly as
exploratory/insufficient-data if that's what the real run shows, exactly
like ml.py itself and rmt_feature_denoising.py before it.

Verified via a synthetic heteroskedastic dataset (known conditional
quantiles) before trusting real data.

Read-only. Never fetches, never trains a model that gets deployed, never
modifies ml.py.

Usage:
    python research/quantile_regression_forest.py
"""
import os
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # for aligned_pair_loader

import ml
from aligned_pair_loader import TF_DIRS as _TF_DIRS, DIR_TO_LABEL as _DIR_TO_LABEL
from aligned_pair_loader import resolve_tf_results_dir as _resolve_tf_results_dir_tuple

_QUANTILES = [0.1, 0.5, 0.9]
_MIN_EXAMPLES = 30  # same order-of-magnitude floor as Config.ML.MIN_CLASS_SAMPLES


class QuantileForest:
    """Meinshausen (2006) QRF on top of sklearn's RandomForestRegressor."""

    def __init__(self, **rf_kwargs):
        self.rf = RandomForestRegressor(**rf_kwargs)
        self._y_train = None
        self._leaf_train = None  # (n_train, n_trees) leaf index per tree

    def fit(self, X: np.ndarray, y: np.ndarray) -> "QuantileForest":
        self.rf.fit(X, y)
        self._y_train = np.asarray(y)
        self._leaf_train = self.rf.apply(X)  # (n_samples, n_trees)
        return self

    def predict_quantiles(self, X: np.ndarray, quantiles) -> np.ndarray:
        leaf_test = self.rf.apply(X)  # (n_test, n_trees)
        n_test = X.shape[0]
        n_trees = leaf_test.shape[1]
        out = np.full((n_test, len(quantiles)), np.nan)
        for i in range(n_test):
            pooled = []
            for tree_idx in range(n_trees):
                same_leaf = self._leaf_train[:, tree_idx] == leaf_test[i, tree_idx]
                pooled.append(self._y_train[same_leaf])
            pooled_arr = np.concatenate(pooled) if pooled else np.array([])
            if len(pooled_arr) > 0:
                out[i] = np.quantile(pooled_arr, quantiles)
        return out


def _resolve_tf_dirname(tf_dir):
    path, _is_stale = _resolve_tf_results_dir_tuple(tf_dir)
    return os.path.basename(path)


def gather_real_examples() -> pd.DataFrame:
    """Identical pattern to rmt_feature_denoising.py's gather_real_examples —
    reuses ml.py's own _build_examples_for_pair, never reimplements it."""
    summary = ml.MLRunSummary()
    all_events = []
    orig_tf_dirname = ml._tf_dirname
    try:
        for tf_dir in _TF_DIRS:
            resolved_name = _resolve_tf_dirname(tf_dir)
            pairs_path = os.path.join("output", "results", resolved_name, "pairs.parquet")
            if not os.path.exists(pairs_path):
                continue
            tf_label = _DIR_TO_LABEL[tf_dir]
            pairs_df = pd.read_parquet(pairs_path)
            ml._tf_dirname = lambda _tfl, _rn=resolved_name: _rn
            for _, row in pairs_df.iterrows():
                try:
                    events = ml._build_examples_for_pair(
                        row["symbol_a"], row["symbol_b"], tf_label, row, summary
                    )
                    all_events.extend(events)
                except Exception:
                    continue
    finally:
        ml._tf_dirname = orig_tf_dirname
    if not all_events:
        return pd.DataFrame()
    df = pd.DataFrame([vars(e) for e in all_events])
    return df


def main():
    examples = gather_real_examples()
    n = len(examples)
    print(f"Gathered {n} real labeled examples across all confirmed pairs")
    if n < _MIN_EXAMPLES:
        print(f"Too few examples ({n} < {_MIN_EXAMPLES}) for a meaningful QRF fit — "
              "reporting as exploratory/insufficient-data, same constraint ml.py's own "
              "Stage 1 classifier already documents. Not attempting a fit on this little data.")
        return

    X = examples[ml._FEATURE_COLS].to_numpy(dtype=float)
    y = examples["z_future"].to_numpy(dtype=float)
    valid = np.all(np.isfinite(X), axis=1) & np.isfinite(y)
    X, y = X[valid], y[valid]
    print(f"Using {len(y)} examples with complete features")

    qrf = QuantileForest(n_estimators=200, min_samples_leaf=max(3, len(y) // 20), random_state=0)
    qrf.fit(X, y)
    preds = qrf.predict_quantiles(X, _QUANTILES)
    print(f"\nIn-sample predicted quantile coverage check (should roughly bracket actual z_future):")
    for qi, q in enumerate(_QUANTILES):
        coverage = float(np.mean(y <= preds[:, qi]))
        print(f"  q={q}: predicted quantile mean={np.nanmean(preds[:, qi]):.3f}, "
              f"empirical coverage (fraction of y <= predicted q)={coverage:.3f}")

    os.makedirs("output/research", exist_ok=True)
    out_df = examples.loc[valid, ["symbol_a", "symbol_b", "tf_label"]].copy()
    for qi, q in enumerate(_QUANTILES):
        out_df[f"z_future_q{int(q*100)}"] = preds[:, qi]
    out_df["z_future_actual"] = y
    out_df.to_parquet("output/research/quantile_regression_forest.parquet")
    print("\nWrote output/research/quantile_regression_forest.parquet")


if __name__ == "__main__":
    main()
