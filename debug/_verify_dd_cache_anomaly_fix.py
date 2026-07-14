"""
BUG-D65 verification: DataStore.append() split-adjustment-seam reconciliation.

Synthetic fixture reproducing the exact bug class found in DD's real cache:
an "existing" cached series left on an OLD adjustment basis, appended to a
freshly-fetched "new_df" series already reflecting a real split that
occurred between the two fetches. Confirms:

1. Before the fix (raw concat, no reconciliation): the combined series has
   a discontinuity at the seam.
2. After the fix: the seam is smooth, and NOT because new_df was touched —
   the fix rescales only the historical (existing) side, and only when a
   real recorded split explains the observed gap.
3. Negative control: a large gap NOT backed by any recorded split (e.g. a
   genuine earnings-crash move) is left unadjusted — the fix must not
   "guess" and corrupt legitimate data.
"""
import os
import sys
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data as data_mod  # noqa: E402

DataStore = data_mod.DataStore


def _make_series(start, n, base_price, freq="1h"):
    idx = pd.date_range(start=start, periods=n, freq=freq)
    rng = np.random.RandomState(0)
    close = base_price + np.cumsum(rng.normal(0, 0.05, n))
    close = np.abs(close) + base_price * 0.5
    df = pd.DataFrame(
        {
            "open": close - 0.02,
            "high": close + 0.05,
            "low": close - 0.05,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )
    return df


class FakeSplits:
    """Mimics yf.Ticker(symbol).splits — a tz-aware DatetimeIndex-keyed Series."""

    def __init__(self, splits_series):
        self._s = splits_series

    def __getattr__(self, name):
        return getattr(self._s, name)


def test_reconciles_real_split_gap():
    # existing: 10 bars on OLD basis (pre-split), ends 2026-06-23 15:00
    existing = _make_series("2026-06-22 09:30", 10, base_price=45.0)
    # new_df: 5 bars on NEW basis (post 1-for-3 reverse split, factor 3x),
    # starts right after existing ends.
    new_df = _make_series("2026-06-24 09:30", 5, base_price=135.0)

    split_dates = pd.DatetimeIndex(["2026-06-24 00:00:00-04:00"]).tz_convert("UTC")
    split_series = pd.Series([1.0 / 3.0], index=split_dates)

    with mock.patch.object(data_mod, "yf") as _:
        pass  # placeholder; real patch below via sys.modules

    class FakeTicker:
        def __init__(self, sym):
            self.splits = split_series

    fake_yf_module = type(sys)("yfinance")
    fake_yf_module.Ticker = FakeTicker

    with mock.patch.dict(sys.modules, {"yfinance": fake_yf_module}):
        reconciled = DataStore._reconcile_split_adjustment("DD_TEST", existing, new_df)

    seam_ratio_before = new_df["close"].iloc[0] / existing["close"].iloc[-1]
    seam_ratio_after = new_df["close"].iloc[0] / reconciled["close"].iloc[-1]

    assert abs(seam_ratio_before - 1.0) > 1.5, (
        f"fixture didn't reproduce a large seam gap: {seam_ratio_before}"
    )
    assert abs(seam_ratio_after - 1.0) < 0.20, (
        f"reconciliation failed to close the seam: ratio={seam_ratio_after:.4f}"
    )
    # Confirm existing was actually rescaled (not new_df, not a no-op)
    assert not np.allclose(reconciled["close"].values, existing["close"].values)
    print(
        f"[PASS] real-split case: seam ratio {seam_ratio_before:.3f}x -> {seam_ratio_after:.3f}x"
    )


def test_leaves_unexplained_gap_alone():
    # A large gap with NO matching recorded split (e.g. a genuine
    # earnings-crash overnight move) must NOT be rescaled.
    existing = _make_series("2026-06-22 09:30", 10, base_price=45.0)
    new_df = _make_series("2026-06-24 09:30", 5, base_price=20.0)  # crashed, real move

    empty_splits = pd.Series([], index=pd.DatetimeIndex([], tz="UTC"), dtype=float)

    class FakeTicker:
        def __init__(self, sym):
            self.splits = empty_splits

    fake_yf_module = type(sys)("yfinance")
    fake_yf_module.Ticker = FakeTicker

    with mock.patch.dict(sys.modules, {"yfinance": fake_yf_module}):
        reconciled = DataStore._reconcile_split_adjustment("DD_TEST", existing, new_df)

    assert np.allclose(reconciled["close"].values, existing["close"].values), (
        "negative control failed: unexplained gap was rescaled anyway (data corruption risk)"
    )
    print("[PASS] negative control: unexplained gap left unadjusted")


def test_ordinary_gap_not_touched():
    existing = _make_series("2026-06-22 09:30", 10, base_price=45.0)
    new_df = _make_series("2026-06-24 09:30", 5, base_price=46.5)  # ordinary ~3% gap

    reconciled = DataStore._reconcile_split_adjustment("DD_TEST", existing, new_df)
    assert np.allclose(reconciled["close"].values, existing["close"].values)
    print("[PASS] ordinary small gap: no split-history lookup triggered, no change")


if __name__ == "__main__":
    test_reconciles_real_split_gap()
    test_leaves_unexplained_gap_alone()
    test_ordinary_gap_not_touched()
    print("\nAll BUG-D65 verification tests passed.")
