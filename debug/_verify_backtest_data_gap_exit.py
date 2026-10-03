"""
Regression test for code-review finding B1 (2026-09-26; fixed 2026-10-03, bug recheck T14; Ross approved "fix it so
data gaps force-close positions"). BacktestEngine.run dropped NaN-z/NaN-spread rows BEFORE the event loop, so the
loop's `data_gap` force-close could never fire: a position was carried straight across a data outage and closed
later as if nothing happened. Real data (2026-10-03): 25 of 27 saved 1-day spread files have mid-series runs of >5
missing bars (33 outages); their gap flags are all None (deep-history path writes none -- documented), so flags
cannot be the trigger.
Rule (matches data.py's DATA_GAP definition, _MAX_FILL_BARS = 5, measured in TRADING DAYS so nights and weekends on
intraday grids are not outages): a held position exits at the FIRST valid bar after more than 5 business days with
no valid bar, at that bar's spread, exit_reason "data_gap". (Exiting at the last bar BEFORE the gap would use
knowledge that a gap is coming -- lookahead.) Known limit: an intraday outage shorter than a trading day is not
caught.
Checks:
  1. daily: a 7-business-day hole inside a held position -> that trade exits "data_gap" at the first bar after it;
  2. daily: no hole -> no "data_gap" exit;
  3. intraday (7 bars/day, nights + weekends absent): no "data_gap" exits;
  4. intraday: a 7-business-day hole inside a held position -> "data_gap" exit at the first bar after it.
Run: python debug/_verify_backtest_data_gap_exit.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from backtest import BacktestEngine, RegimeConditioner, MLConditioner
from config import Config

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def triangle(n, period=40, amp=3.5):
    t = np.arange(n) % period
    h = period / 2.0
    return np.where(t < h, -1 + 2 * t / h, 3 - 2 * t / h) * amp


def spread_df(ts, z, hl=20.0):
    n = len(ts)
    return pd.DataFrame({"spread": z * 0.5, "z_rolling": z, "z_expanding": z, "half_life_rolling": np.full(n, hl),
                         "gap_flag_a": np.zeros(n, "int8"), "gap_flag_b": np.zeros(n, "int8"),
                         "hedge_ratio_ols_t": np.ones(n), "hedge_ratio_kalman_t": np.ones(n)}, index=ts)


def engine():
    return BacktestEngine(cfg=Config.BACKTEST, regime_cond=RegimeConditioner(enabled=False),
                          ml_cond=MLConditioner(enabled=False), storm_flags={}, mm_hedge_map={})


def pair(tf):
    return pd.Series({"symbol_a": "SYNA", "symbol_b": "SYNB", "tf_label": tf, "hedge_ratio_ols": 1.0,
                      "hedge_ratio_kalman_mean": 1.0, "hurst_rs": 0.4, "coint_fraction_rolling": 0.5,
                      "half_life_trend_slope": 0.0, "mean_reversion_speed": 0.1})


def hole_case(ts, tf, label):
    """Find a held trade on the dense series, then remove every bar of the 7 business days after its entry day."""
    z = triangle(len(ts), period=(40 if tf == "1D" else 280))
    hl = 20.0 if tf == "1D" else 100.0     # intraday: max hold = 2 x half-life must outlast a 7-day hole
    dense = engine().run(pair(tf), spread_df(ts, z, hl), hedge_method="ols")
    check(f"{label}.dense_has_trades", len(dense) > 0, f"n={len(dense)}")
    check(f"{label}.dense_no_gap_exit", not any(t.exit_reason == "data_gap" for t in dense),
          str(sorted({t.exit_reason for t in dense})))
    days = pd.DatetimeIndex(ts.normalize().unique())
    target = None
    for t in dense:
        d0 = pd.Timestamp(t.entry_time).normalize()
        i0 = days.get_loc(d0)
        if i0 + 9 < len(days) and pd.Timestamp(t.exit_time).normalize() > days[i0 + 8]:
            target = (t, days[i0 + 1:i0 + 8])          # 7 business days removed, position still open after
            break
    if target is None:
        check(f"{label}.found_long_enough_trade", False); return
    t, hole_days = target
    df = spread_df(ts, z, hl)
    hole = df.index.normalize().isin(hole_days)
    df.loc[hole, ["z_rolling", "spread"]] = np.nan
    first_after = df.index[(~hole) & (df.index > hole_days[-1] + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))][0]
    got = [x for x in engine().run(pair(tf), df, hedge_method="ols") if pd.Timestamp(x.entry_time) == pd.Timestamp(t.entry_time)]
    ok = len(got) == 1 and got[0].exit_reason == "data_gap" and pd.Timestamp(got[0].exit_time) == first_after
    check(f"{label}.gap_inside_position_exits_after_gap", ok,
          f"entry={t.entry_time} hole={hole_days[0].date()}..{hole_days[-1].date()} expected exit {first_after}; "
          f"got {[(x.exit_reason, str(x.exit_time)) for x in got]}")


def main():
    hole_case(pd.bdate_range("2020-01-02", periods=500), "1D", "daily")
    days = pd.bdate_range("2024-01-02", periods=150)
    hrs = ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"]
    hole_case(pd.DatetimeIndex(sorted(pd.Timestamp(f"{d.date()} {h}") for d in days for h in hrs)), "1h", "intraday")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
