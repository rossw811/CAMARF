"""
debug/_verify_adv_1day_fallback.py -- synthetic ground-truth verification for
the ADV liquidity filter's 1hr->1day fallback (analysis.py's _run_one_tf,
fixed 2026-07-22 after the fresh BUG-D96 rerun revealed 8058.T has no
{sym}_1hr.parquet at all, so its ADV computed as NaN and it was silently
excluded from EVERY timeframe's candidate pool -- including 1M, which needs
no 1hr data -- dropping the real, previously-confirmed 7267.T/8058.T@1M pair
for a data-availability reason, not actual illiquidity).

Replicates the exact _compute_adv closure logic from analysis.py (that
function is a local closure inside _run_one_tf, not separately importable --
this test mirrors it precisely rather than refactoring production code
purely to make it testable, matching this project's simplicity-first
convention) against a temp cache directory, never the real one.

Checks:
  1. A symbol with 1hr cache uses it (unchanged behavior).
  2. A symbol with ONLY 1day cache (no 1hr) falls back to 1day and computes
     a real ADV value.
  3. A symbol with NEITHER 1hr nor 1day cache returns NaN cleanly (no crash).
  4. A 1day file missing the "volume" column falls through to NaN cleanly
     (not a crash), rather than a KeyError.
  5. When BOTH 1hr and 1day exist, 1hr is preferred (matches the existing,
     unchanged convention -- 1hr is the finer-grained, presumably more
     current proxy).

Run: python debug/_verify_adv_1day_fallback.py
"""
import os
import shutil
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _compute_adv(cache_dir, sym):
    """Exact mirror of analysis.py's _run_one_tf._compute_adv closure."""
    for _suffix in ("1hr", "1day"):
        _path = os.path.join(cache_dir, f"{sym}_{_suffix}.parquet")
        if not os.path.exists(_path):
            continue
        try:
            _df = pd.read_parquet(_path)
            if "close" not in _df.columns or "volume" not in _df.columns:
                continue
            _df.index = pd.to_datetime(_df.index)
            _dv = _df["close"] * _df["volume"]
            _daily_dv = _dv.groupby(_df.index.date).sum()
            if len(_daily_dv) > 0:
                return float(_daily_dv.mean())
        except Exception:
            continue
    return float("nan")


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


def _mkbars(n_days=5, close=100.0, volume=1000, freq="1h"):
    idx = pd.date_range("2024-01-01 09:30", periods=n_days * 6, freq=freq)
    return pd.DataFrame({"close": close, "volume": volume}, index=idx)


def main():
    tmpdir = tempfile.mkdtemp(prefix="camarf_adv_test_")
    ok = True
    try:
        # 1. 1hr cache exists -> used, real value
        _mkbars(close=100.0, volume=1000).to_parquet(os.path.join(tmpdir, "HAS1HR_1hr.parquet"))
        v = _compute_adv(tmpdir, "HAS1HR")
        ok &= check("symbol with 1hr cache: real value computed", v == v and v > 0)

        # 2. Only 1day cache -> falls back, real value
        daily = pd.DataFrame(
            {"close": [50.0] * 10, "volume": [2000] * 10},
            index=pd.date_range("2024-01-01", periods=10, freq="D"),
        )
        daily.to_parquet(os.path.join(tmpdir, "ONLY1DAY_1day.parquet"))
        v = _compute_adv(tmpdir, "ONLY1DAY")
        ok &= check("symbol with ONLY 1day cache: falls back and computes real value",
                    v == v and abs(v - 100_000.0) < 1e-6)  # 50*2000 = 100,000/day, constant

        # 3. Neither exists -> NaN, no crash
        v = _compute_adv(tmpdir, "NOSUCHSYMBOL")
        ok &= check("symbol with NEITHER cache: returns NaN cleanly (no crash)", v != v)

        # 4. 1day file missing 'volume' column -> falls through to NaN, no crash
        bad = pd.DataFrame({"close": [50.0] * 5}, index=pd.date_range("2024-01-01", periods=5, freq="D"))
        bad.to_parquet(os.path.join(tmpdir, "NOVOLUME_1day.parquet"))
        v = _compute_adv(tmpdir, "NOVOLUME")
        ok &= check("1day file missing 'volume' column: returns NaN cleanly (no crash)", v != v)

        # 5. Both exist -> 1hr preferred
        hr_bars = _mkbars(close=999.0, volume=999)
        hr_bars.to_parquet(os.path.join(tmpdir, "BOTH_1hr.parquet"))
        daily2 = pd.DataFrame(
            {"close": [1.0] * 10, "volume": [1] * 10},
            index=pd.date_range("2024-01-01", periods=10, freq="D"),
        )
        daily2.to_parquet(os.path.join(tmpdir, "BOTH_1day.parquet"))
        v_1hr_only = _compute_adv(tmpdir, "BOTH")
        # Expected value derived directly from the mock 1hr data itself
        # (not a hand-recomputed assumption about bars/day) -- the point of
        # this check is DIRECTION (1hr chosen over 1day's very different
        # 1.0*1=1/day value), not re-deriving groupby arithmetic already
        # covered by checks 1-2 above.
        expected_1hr_value = (hr_bars["close"] * hr_bars["volume"]).groupby(hr_bars.index.date).sum().mean()
        ok &= check("when BOTH exist, 1hr is preferred (matches 1hr's own computed value)",
                    abs(v_1hr_only - expected_1hr_value) < 1e-6)
        ok &= check("when BOTH exist, 1hr's value is NOT the 1day fallback's (1.0*1=1) value",
                    abs(v_1hr_only - 1.0) > 1.0)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("\n" + "=" * 60)
    if ok:
        print("ALL CHECKS PASSED")
    else:
        print("SOME CHECKS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
