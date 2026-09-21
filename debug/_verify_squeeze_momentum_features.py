"""
Synthetic verification for research/squeeze_momentum_features.py -- the
additive spread_series augmentation script that wires analysis.py's
already-computed squeeze_indicator/rsi_14 into backtest.py's entry gate
(2026-09-15, Ross's direct instruction: no squeeze/momentum check existed).

No live data, no network -- fabricated OHLCV and a temp spread_series file.

Run: python debug/_verify_squeeze_momentum_features.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.squeeze_momentum_features import augment_pair, _TF_LABEL_TO_DIR

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _make_ohlcv(n=300, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0.5, 2.0, n)
    low = close - rng.uniform(0.5, 2.0, n)
    open_ = close + rng.normal(0, 0.5, n)
    volume = rng.uniform(1e5, 1e6, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                          "close": close, "volume": volume}, index=idx)


def test_augment_pair_adds_expected_columns():
    tmpdir = tempfile.mkdtemp()
    try:
        tf_dir = _TF_LABEL_TO_DIR["1D"]
        results_dir = os.path.join(tmpdir, "output", "results", tf_dir)
        os.makedirs(results_dir, exist_ok=True)
        idx = pd.date_range("2024-01-01", periods=300, freq="B")
        spread_df = pd.DataFrame({
            "spread": np.random.default_rng(1).normal(0, 1, 300),
            "z_rolling": np.random.default_rng(2).normal(0, 1, 300),
        }, index=idx)

        with mock.patch("research.squeeze_momentum_features._spread_path",
                         return_value=os.path.join(results_dir, "spread_series_A_B.parquet")):
            spread_df.to_parquet(os.path.join(results_dir, "spread_series_A_B.parquet"))

            feat_a = _make_ohlcv(seed=10)
            feat_b = _make_ohlcv(seed=20)
            from analysis import VolumeStructure
            cache = {
                ("A", "1D"): VolumeStructure.compute_features(feat_a),
                ("B", "1D"): VolumeStructure.compute_features(feat_b),
            }
            ok = augment_pair("A", "B", "1D", cache)
            check("augment_pair.returns_true_when_file_exists", ok is True)

            result = pd.read_parquet(os.path.join(results_dir, "spread_series_A_B.parquet"))
            expected_new_cols = {"squeeze_indicator_a_t", "squeeze_indicator_b_t",
                                  "rsi_14_a_t", "rsi_14_b_t", "rsi_diff_t",
                                  "rsi_diff_velocity_t"}
            check("augment_pair.adds_all_6_new_columns",
                  expected_new_cols.issubset(set(result.columns)))
            check("augment_pair.preserves_existing_columns",
                  {"spread", "z_rolling"}.issubset(set(result.columns)))
            check("augment_pair.preserves_original_row_count", len(result) == len(spread_df))
            check("augment_pair.rsi_diff_equals_a_minus_b",
                  np.allclose(result["rsi_diff_t"].fillna(-999).values,
                              (result["rsi_14_a_t"] - result["rsi_14_b_t"]).fillna(-999).values))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_augment_pair_skips_missing_file():
    with mock.patch("research.squeeze_momentum_features._spread_path",
                     return_value="/nonexistent/path/spread_series_X_Y.parquet"):
        ok = augment_pair("X", "Y", "1D", {})
        check("augment_pair.returns_false_when_file_missing", ok is False)


def test_augment_pair_skips_when_both_legs_have_no_features():
    tmpdir = tempfile.mkdtemp()
    try:
        idx = pd.date_range("2024-01-01", periods=50, freq="B")
        spread_df = pd.DataFrame({"spread": np.zeros(50), "z_rolling": np.zeros(50)}, index=idx)
        p = os.path.join(tmpdir, "spread_series_M_N.parquet")
        spread_df.to_parquet(p)
        with mock.patch("research.squeeze_momentum_features._spread_path", return_value=p):
            cache = {("M", "1D"): pd.DataFrame(), ("N", "1D"): pd.DataFrame()}
            ok = augment_pair("M", "N", "1D", cache)
            check("augment_pair.returns_false_when_both_legs_empty", ok is False)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_augment_pair_reindexes_onto_spread_series_index_not_feature_index():
    """The spread_series file's own index is authoritative -- a feature
    DataFrame with a DIFFERENT (e.g. wider/shifted) index must be reindexed
    onto it, not the other way around, per the reasoning in this script's
    own docstring (the stale-cache mismatch that motivated this whole fix)."""
    tmpdir = tempfile.mkdtemp()
    try:
        narrow_idx = pd.date_range("2024-03-01", periods=20, freq="B")
        spread_df = pd.DataFrame({"spread": np.zeros(20), "z_rolling": np.zeros(20)},
                                  index=narrow_idx)
        p = os.path.join(tmpdir, "spread_series_P_Q.parquet")
        spread_df.to_parquet(p)

        wide_idx = pd.date_range("2020-01-01", periods=500, freq="B")
        feat_wide = pd.DataFrame({
            "squeeze_indicator": np.linspace(0.5, 1.5, 500),
            "rsi_14": np.linspace(20, 80, 500),
        }, index=wide_idx)

        with mock.patch("research.squeeze_momentum_features._spread_path", return_value=p):
            cache = {("P", "1D"): feat_wide, ("Q", "1D"): feat_wide}
            ok = augment_pair("P", "Q", "1D", cache)
            check("augment_pair.reindex.returns_true", ok is True)
            result = pd.read_parquet(p)
            check("augment_pair.reindex.output_length_matches_spread_series_not_feature",
                  len(result) == 20, f"got {len(result)}, expected 20")
            check("augment_pair.reindex.output_index_matches_spread_series",
                  list(result.index) == list(narrow_idx))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    test_augment_pair_adds_expected_columns()
    test_augment_pair_skips_missing_file()
    test_augment_pair_skips_when_both_legs_have_no_features()
    test_augment_pair_reindexes_onto_spread_series_index_not_feature_index()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
