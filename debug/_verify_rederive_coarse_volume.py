"""
Synthetic check for research/rederive_coarse_volume.py (DEV-003 follow-up, 2026-10-07): the 7D/1M/3M/6M/1Y WRDS
files carry RAW volume (7D/3M/6M/1Y summed from raw daily volume at fetch time; 1M is CRSP's native mthvol, which
equals the summed raw daily volume -- ratio 1.0000 p5..p95 on 8 large caps), so pre-split dollar volume is
understated exactly as it was for the daily files before the restatement.
Ground truth: a daily series with a 2:1 split mid-month (raw shares double after the split, factor 2 before it).
Checks:
  1. a split month's restated volume = sum(raw x factor) over its days (known by construction), for 1M and 7D
  2. the old raw value is kept in volume_raw; close and every other column untouched
  3. a period containing a day with an unknown factor (NaN adjusted volume) gets NaN, not a partial sum
  4. a bar whose stored volume does NOT equal the summed raw daily volume is not restated (NaN, counted) -- the
     guard that the bar really was built from these daily rows
  5. idempotent: a second pass changes nothing
Run: python debug/_verify_rederive_coarse_volume.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from period_bars import resample_to_period_end

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def make_daily():
    idx = pd.bdate_range("2020-01-01", "2020-04-30")
    split = pd.Timestamp("2020-02-14")
    raw = np.where(idx < split, 1000.0, 2000.0)                  # shares double after a 2:1 split
    fac = np.where(idx < split, 2.0, 1.0)                        # today's units
    close = np.full(len(idx), 50.0)                              # split-adjusted close: continuous
    d = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "close_total_return": close,
                      "volume": raw * fac, "volume_raw": raw, "volume_adj_factor": fac}, index=idx)
    d.loc[pd.Timestamp("2020-04-15"), ["volume", "volume_adj_factor"]] = np.nan   # unknown-factor day in April
    return d


def main():
    try:
        from research.rederive_coarse_volume import restate_coarse
    except ImportError as e:
        check("module_exists", False, str(e)); return finish()
    daily = make_daily()
    raw_daily = daily.assign(volume=daily["volume_raw"]).drop(columns=["volume_raw", "volume_adj_factor"])
    for tf in ("1M", "7D"):
        coarse = resample_to_period_end(raw_daily, tf)              # what the fetch wrote: raw sums
        if tf == "1M":
            coarse = coarse[["close", "close_total_return", "volume"]]   # native monthly's columns
            coarse.loc[pd.Timestamp("2020-01-31"), "volume"] += 7.0     # a bar not built from these daily rows
        new, stats = restate_coarse(daily, coarse, tf)
        keys = pd.DatetimeIndex(daily.index.to_period("M" if tf == "1M" else "W-FRI").end_time.normalize())
        truth = daily["volume_raw"].mul(daily["volume_adj_factor"]).groupby(keys).sum(min_count=1)
        feb = pd.Timestamp("2020-02-29")
        if tf == "1M":
            check("1M_split_month_exact", np.isclose(new.loc[feb, "volume"], truth.loc[feb]),
                  f"{new.loc[feb, 'volume']} vs {truth.loc[feb]}")
            check("1M_unknown_day_gives_nan", np.isnan(new.loc[pd.Timestamp("2020-04-30"), "volume"]))
            check("1M_mismatched_bar_not_restated", np.isnan(new.loc[pd.Timestamp("2020-01-31"), "volume"])
                  and stats["mismatch"] == 1, f"{stats}")
            check("1M_unknown_counted", stats["unknown"] == 1, f"{stats}")
        else:
            wk = keys[daily.index.get_loc(pd.Timestamp("2020-02-12"))]
            check("7D_pre_split_week_exact", np.isclose(new.loc[wk, "volume"], truth.loc[wk]),
                  f"{new.loc[wk, 'volume']} vs {truth.loc[wk]}")
            check("7D_no_mismatch", stats["mismatch"] == 0, f"{stats}")
        check(f"{tf}_raw_kept", new["volume_raw"].equals(coarse["volume"]))
        check(f"{tf}_other_columns_untouched", new.drop(columns=["volume", "volume_raw"]).equals(
            coarse.drop(columns=["volume"])))
        again, st2 = restate_coarse(daily, new, tf)
        check(f"{tf}_idempotent", again.equals(new) and st2.get("skipped") is True, f"{st2}")
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
