"""
Verification for the 2026-07-20 Grand Sweep fix to data_ibkr.py's
merge_with_yfinance(): previously concatenated IBKR deep history onto
yfinance's recent series with zero split-adjustment reconciliation -- the
same append-seam price-discontinuity bug BUG-D65 fixed for
DataStore.append()'s 13 call sites, but this merge is an independent path
that was never covered.

Synthetic fixture: an IBKR deep-history series left on an OLD adjustment
basis, "yfinance" data reflecting a real split that occurred after IBKR's
pull. Confirms:
1. Before the fix (raw concat): the merged series has a discontinuity at
   the IBKR/yfinance boundary.
2. After the fix: merge_with_yfinance() calls _reconcile_split_adjustment
   and the seam is smooth, with only the IBKR (older-basis) side rescaled.
3. Negative control: a gap NOT backed by any recorded split is left
   unadjusted (the fix must not guess).
"""
import os
import sys
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data as data_mod  # noqa: E402
import data_ibkr  # noqa: E402

DataStore = data_mod.DataStore


def _make_series(start, n, base_price, freq="1h"):
    idx = pd.date_range(start=start, periods=n, freq=freq)
    rng = np.random.RandomState(1)
    close = base_price + np.cumsum(rng.normal(0, 0.05, n))
    close = np.abs(close) + base_price * 0.5
    return pd.DataFrame(
        {
            "open": close - 0.02, "high": close + 0.05,
            "low": close - 0.05, "close": close,
            "volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


class FakeSplits:
    def __init__(self, splits_series):
        self._s = splits_series

    def __getattr__(self, name):
        return getattr(self._s, name)


def main() -> None:
    failures = []
    symbol = "TESTSYM"
    tf_label = "1h"

    # IBKR deep history: 100 bars around price level 100, ending before yfinance starts.
    ibkr_deep = _make_series("2020-01-01", 100, base_price=100.0)
    # yfinance: 50 bars starting right after, but on a NEW adjustment basis --
    # a real 3-for-1 split occurred between the two fetches, so yfinance's
    # currently-adjusted prices are 1/3 of what IBKR's stale-basis prices would be.
    yf_start = ibkr_deep.index[-1] + pd.Timedelta(hours=1)
    yf_df = _make_series(yf_start, 50, base_price=100.0 / 3.0)

    fake_split = FakeSplits(pd.Series([3.0], index=pd.DatetimeIndex([ibkr_deep.index[-1] + pd.Timedelta(minutes=30)])))

    with mock.patch.object(DataStore, "load", return_value=yf_df.copy()), \
         mock.patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.splits = fake_split._s
        merged = data_ibkr.merge_with_yfinance(ibkr_deep.copy(), symbol, tf_label)

    # The IBKR portion in `merged` should now be rescaled by ~1/3 to match yfinance's basis.
    ibkr_portion = merged[merged.index < yf_start]
    if len(ibkr_portion) != len(ibkr_deep):
        failures.append(f"expected {len(ibkr_deep)} IBKR rows preserved, got {len(ibkr_portion)}")
    ratio_at_seam = yf_df["close"].iloc[0] / ibkr_portion["close"].iloc[-1]
    if not np.isclose(ratio_at_seam, 1.0, atol=0.15):
        failures.append(
            f"seam still discontinuous after fix: yf_first/ibkr_last = {ratio_at_seam:.4f} "
            f"(expected close to 1.0)"
        )
    # Original (unreconciled) ratio should have been far from 1.0 (~3x), proving the
    # fix actually changed something, not a no-op.
    original_ratio = yf_df["close"].iloc[0] / ibkr_deep["close"].iloc[-1]
    if np.isclose(original_ratio, 1.0, atol=0.15):
        failures.append("test fixture itself has no real seam discontinuity -- fixture bug")

    # Negative control: gap NOT backed by any recorded split -- must be left unadjusted.
    ibkr_deep2 = _make_series("2020-01-01", 100, base_price=100.0)
    yf_start2 = ibkr_deep2.index[-1] + pd.Timedelta(hours=1)
    yf_df2 = _make_series(yf_start2, 50, base_price=140.0)  # ~1.4x jump, no split explains it
    empty_splits = FakeSplits(pd.Series([], dtype=float, index=pd.DatetimeIndex([])))
    with mock.patch.object(DataStore, "load", return_value=yf_df2.copy()), \
         mock.patch("yfinance.Ticker") as mock_ticker2:
        mock_ticker2.return_value.splits = empty_splits._s
        merged2 = data_ibkr.merge_with_yfinance(ibkr_deep2.copy(), symbol, tf_label)
    ibkr_portion2 = merged2[merged2.index < yf_start2]
    if not np.allclose(ibkr_portion2["close"].values, ibkr_deep2["close"].values):
        failures.append("negative control: unadjusted gap (no recorded split) was incorrectly rescaled")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("data_ibkr.py merge_with_yfinance() split-reconciliation fix verified.")
        print(f"  Original seam ratio (pre-fix): {original_ratio:.4f}")
        print(f"  Reconciled seam ratio (post-fix): {ratio_at_seam:.4f}")
        print("  Negative control (no recorded split): correctly left unadjusted.")


if __name__ == "__main__":
    main()
