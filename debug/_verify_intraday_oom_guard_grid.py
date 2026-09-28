"""
Regression test for code-review finding D7 (2026-09-26): DataAligner.align_intraday's OOM guard (expected grid rows
> _MAX_REINDEX) returned the symbol's RAW index with every gap_flag = NONE. That output is off the uniform grid that
build_returns_matrix's right-aligned row-count join relies on, and nothing is masked, so every overnight/weekend jump
becomes an ordinary bar return in correlation/EG.
Fix: keep the grid; trim only the OLDEST history so the grid fits under the cap (logged as a warning).
Checks on a synthetic 1m equity whose full span needs > 500,000 grid rows:
  1. output index is a uniform 1-minute grid (the guard no longer returns raw bars);
  2. overnight rows are DATA_GAP (gap classification ran);
  3. output ends at the input's last bar and has <= 500,000 rows (the trim dropped the oldest data, not the newest);
  4. real bars inside the kept window are unchanged.
Run: python debug/_verify_intraday_oom_guard_grid.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from data import DataAligner, GapFlag

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    days = pd.bdate_range("2024-01-01", periods=300)                      # ~420 calendar days -> ~605k 1m grid rows
    mins = pd.timedelta_range("09:30:00", "15:59:00", freq="1min")
    idx = pd.DatetimeIndex((days.values[:, None] + mins.values[None, :]).ravel())
    c = 50 + np.cumsum(np.random.default_rng(0).normal(0, 0.01, len(idx)))
    df = pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1.0}, index=idx)
    span_rows = int((idx[-1] - idx[0]).total_seconds() / 60) + 1
    print(f"input: {len(idx)} bars, full-span grid would be {span_rows} rows")
    out = DataAligner.align_intraday({"EQ1M": df}, "1m")["EQ1M"]
    d = out.index.to_series().diff().dropna().unique()
    check("uniform_1min_grid", len(d) > 0 and (d == pd.Timedelta(minutes=1)).all(), f"distinct steps={list(d)}")
    on = out[(out.index.hour == 20) & (out.index.dayofweek < 4)]
    check("overnight_rows_data_gap", len(on) > 0 and (on["gap_flag"] == GapFlag.DATA_GAP).all(),
          f"n={len(on)} flags={on['gap_flag'].value_counts().to_dict()}")
    check("ends_at_last_bar_and_capped", out.index[-1] == idx[-1] and len(out) <= 500_000,
          f"last={out.index[-1]} rows={len(out)}")
    kept = df.loc[out.index[0]:]
    check("kept_real_bars_unchanged", np.allclose(out.loc[kept.index, "close"].to_numpy(), kept["close"].to_numpy()))
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
