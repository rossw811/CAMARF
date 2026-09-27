"""
Regression test for code-review finding D1 (2026-09-26): DataCleaner._liquidity_filter NaN'd the
OHLC of every bar whose PER-BAR dollar volume was under Config.DATA.MIN_DOLLAR_VOLUME (a DAILY
threshold, $1M) and forward-filled -- fabricating copies of earlier bars that kept their real
volume and were later flagged NONE. At 1m nearly every bar of a mid-cap was overwritten; forex
(volume 0) daily files became 100% NaN. Liquidity is a universe-admission decision (the ADV
filter in analysis.py), never a reason to rewrite observed prices.

Checks, through the real DataCleaner.clean() entry point:
  1. equity 1m bars with small per-bar dollar volume keep their own, distinct closes;
  2. equity 1D low-volume days keep their own closes (no forward-filled copies);
  3. forex-style zero-volume daily data is not wiped to NaN.

Run: python debug/_verify_liquidity_filter_no_fabrication.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from data import DataCleaner

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _ohlcv(idx, close, volume):
    close = np.asarray(close, float)
    return pd.DataFrame({"open": close, "high": close * 1.001, "low": close * 0.999,
                         "close": close, "volume": np.asarray(volume, float)}, index=idx)


def _run(df, asset_class, tf_label, tf_ibkr):
    out, rep = DataCleaner.clean(df, "SYNTH", asset_class, tf_label, tf_ibkr)
    return out, rep


def main():
    rng = np.random.default_rng(0)

    # 1. Intraday equity: 3 sessions of 390 1m bars, $50/share, ~400 shares/bar -> ~$20k per bar,
    # far under the $1M DAILY threshold on a per-bar basis (a ~$8M/day name).
    sessions = pd.bdate_range("2026-03-02", periods=3)
    idx = pd.DatetimeIndex([d + pd.Timedelta(hours=9, minutes=30) + pd.Timedelta(minutes=m)
                            for d in sessions for m in range(390)])
    close = 50 * np.exp(np.cumsum(rng.normal(0, 5e-4, len(idx))))
    df = _ohlcv(idx, close, rng.integers(300, 500, len(idx)))
    out, rep = _run(df, "equity", "1m", "1 min")
    if out is None:
        check("intraday.clean_returned_data", False, f"clean() rejected: {getattr(rep, 'fail_reason', rep)}")
    else:
        kept = out["close"].reindex(idx)
        same = np.isclose(kept.to_numpy(), close, rtol=0, atol=1e-9)
        check("intraday.closes_not_overwritten", bool(np.nanmean(same) > 0.99),
              f"fraction of bars keeping their own close = {np.nanmean(same):.3f}")
        nonnull = out["close"].notna().mean()
        check("intraday.no_flat_copy_runs",
              bool(nonnull > 0.99 and (out['close'].diff() == 0).mean() < 0.01),
              f"non-NaN={nonnull:.3f}, zero-change fraction = {(out['close'].diff() == 0).mean():.3f}")

    # 2. Daily equity: 300 days, with every 5th day a low-volume day ($200k dollar volume).
    didx = pd.bdate_range("2024-01-01", periods=300)
    dclose = 30 * np.exp(np.cumsum(rng.normal(0, 0.01, len(didx))))
    vol = np.full(len(didx), 200_000.0)  # $6M/day
    vol[::5] = 200_000 / 30 * 0.2        # ~$200k on those days
    out2, rep2 = _run(_ohlcv(didx, dclose, vol), "equity", "1D", "1 day")
    if out2 is None:
        check("daily.clean_returned_data", False, f"clean() rejected: {getattr(rep2, 'fail_reason', rep2)}")
    else:
        # bdate_range includes NYSE holidays, which clean() correctly drops (found on the first
        # run: 7 of 60 "missing" low-volume days were exactly New Year/MLK/Presidents/Memorial/
        # Labor Day) -- compare only the low-volume days that are real sessions.
        expected = pd.Series(dclose, index=didx).iloc[::5]
        expected = expected[expected.index.isin(out2.index)]
        got = out2["close"].reindex(expected.index).to_numpy()
        check("daily.low_volume_days_keep_own_close",
              bool(len(expected) >= 50 and np.allclose(got, expected.to_numpy(), atol=1e-9)),
              f"n={len(expected)}, max abs diff = {np.max(np.abs(got - expected.to_numpy())):.6f}")

    # 3. Zero-volume (forex-like) daily series passed through the equity path (the real call sites
    # pass "equity" for every ticker) must not be wiped.
    fx = _ohlcv(didx, 1.1 * np.exp(np.cumsum(rng.normal(0, 0.004, len(didx)))), np.zeros(len(didx)))
    out3, rep3 = _run(fx, "equity", "1D", "1 day")
    ok3 = out3 is not None and out3["close"].notna().mean() > 0.99
    check("zero_volume.not_wiped", bool(ok3),
          "clean() rejected" if out3 is None else f"non-NaN close fraction = {out3['close'].notna().mean():.3f}")

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
