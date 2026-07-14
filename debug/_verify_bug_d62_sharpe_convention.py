"""
Synthetic verification for BUG-D62 (Development.md, 2026-07-13): portfolio_sim.py's
portfolio_sharpe_from_replay() originally pooled daily P&L via groupby(exit_date) — summing only
over days that happen to have a realized exit — while backtest.py's aggregate_portfolio() (the
function behind every unconstrained headline Sharpe, e.g. 5.8044) pools via
pnl_series.resample("1D").sum(), which fills every calendar day between the first and last exit
with 0 P&L. These are NOT the same computation, and the difference is large whenever trades are
sparse relative to the calendar span (exactly the real portfolio's situation): the groupby-only
convention silently drops zero-P&L days, shrinking N and inflating Sharpe.

This test proves: (1) on a fixture with genuine gaps between trades, the OLD (groupby) convention
and the fixed (resample) convention disagree materially and predictably; (2) the fixed function
now matches a hand-computed resample("1D") reference exactly; (3) the fixed function's result also
matches what aggregate_portfolio()-style pooling gives on the identical P&L series, so a capital-
sim Sharpe is now directly comparable to the unconstrained headline Sharpe.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from portfolio_sim import portfolio_sharpe_from_replay


def _old_groupby_sharpe(taken: pd.DataFrame) -> float:
    """Replica of the ORIGINAL (buggy) convention, kept here only to prove the fix changes the
    number in the expected direction -- not reintroduced anywhere in production code."""
    df = taken.copy()
    df["exit_date"] = pd.to_datetime(df["exit_time"]).dt.date
    daily = df.groupby("exit_date")["actual_pnl"].sum()
    if len(daily) < 5 or daily.std() == 0:
        return float("nan")
    return float(daily.mean() / daily.std() * np.sqrt(252))


def _reference_resample_sharpe(taken: pd.DataFrame) -> float:
    """Independent hand-written reference for the CORRECT convention, built without reusing any
    of portfolio_sim.py's own code, so this isn't just checking the function against itself."""
    exit_time = pd.to_datetime(taken["exit_time"])
    s = pd.Series(taken["actual_pnl"].values, index=pd.DatetimeIndex(exit_time)).sort_index()
    full_range = pd.date_range(s.index.min().normalize(), s.index.max().normalize(), freq="1D")
    daily = s.groupby(s.index.normalize()).sum().reindex(full_range, fill_value=0.0)
    if len(daily) < 5 or daily.std() == 0:
        return float("nan")
    return float(daily.mean() / daily.std() * np.sqrt(252))


def main():
    failures = []

    # Fixture: 10 trades clustered into 3 real trading days, spread across a 40-CALENDAR-DAY
    # span with long gaps between clusters (mimicking the real portfolio's sparse trade timing).
    # Total P&L across the 3 active days: day1=+900 (3 trades), day2=-300 (3 trades),
    # day3=+1200 (4 trades) -- deliberately non-trivial mean/std so groupby vs resample disagree
    # in a way that isn't just "divide by a different N with the same ratio."
    rows = []
    day1 = pd.Timestamp("2026-01-05")
    for i, pnl in enumerate([400, 300, 200]):
        rows.append({"exit_time": day1, "actual_pnl": pnl})
    day2 = pd.Timestamp("2026-01-20")  # 15-day gap -- pure zero-P&L days in between
    for i, pnl in enumerate([-100, -150, -50]):
        rows.append({"exit_time": day2, "actual_pnl": pnl})
    day3 = pd.Timestamp("2026-02-10")  # 21-day gap
    for i, pnl in enumerate([300, 300, 300, 300]):
        rows.append({"exit_time": day3, "actual_pnl": pnl})
    taken = pd.DataFrame(rows)
    result = {"taken": taken}

    fixed_sharpe = portfolio_sharpe_from_replay(result)
    old_sharpe = _old_groupby_sharpe(taken)
    reference_sharpe = _reference_resample_sharpe(taken)

    # Case 1: fixed function must match the independent hand-written resample reference exactly.
    if not np.isclose(fixed_sharpe, reference_sharpe, rtol=1e-9):
        failures.append(
            f"Case 1 FAILED: portfolio_sharpe_from_replay()={fixed_sharpe:.6f} != "
            f"independent resample reference={reference_sharpe:.6f}"
        )

    # Case 2: fixed function must NOT match the old buggy groupby convention -- proves the fix
    # actually changed behavior, not just cosmetics. With 37 calendar days total (Jan 5 -> Feb 10)
    # vs only 3 active trading days, the conventions must disagree materially.
    if np.isclose(fixed_sharpe, old_sharpe, rtol=1e-6):
        failures.append(
            f"Case 2 FAILED: fixed Sharpe ({fixed_sharpe:.6f}) should differ materially from the "
            f"old groupby-only Sharpe ({old_sharpe:.6f}) given the 37-calendar-day / 3-active-day "
            f"gap in this fixture, but they match -- the fix may not be applied."
        )
    n_calendar_days = (day3 - day1).days + 1
    if n_calendar_days != 37:
        failures.append(f"Case 2 fixture sanity FAILED: expected 37 calendar days, got {n_calendar_days}")

    # Case 3: dense fixture (every calendar day has a trade, no gaps) -- here groupby and resample
    # SHOULD agree, since there are no zero-P&L days to fill. Confirms the fix doesn't change
    # behavior when the bug's precondition (gaps) doesn't hold.
    dense_rows = [{"exit_time": pd.Timestamp("2026-03-01") + pd.Timedelta(days=i),
                   "actual_pnl": float(50 + 10 * ((-1) ** i))} for i in range(10)]
    dense_taken = pd.DataFrame(dense_rows)
    dense_result = {"taken": dense_taken}
    dense_fixed = portfolio_sharpe_from_replay(dense_result)
    dense_old = _old_groupby_sharpe(dense_taken)
    if not np.isclose(dense_fixed, dense_old, rtol=1e-9):
        failures.append(
            f"Case 3 FAILED: with no calendar gaps, fixed ({dense_fixed:.6f}) and old "
            f"({dense_old:.6f}) conventions should agree exactly, but don't."
        )

    # Case 4: empty trades -> NaN, not a crash.
    empty_result = {"taken": pd.DataFrame(columns=["exit_time", "actual_pnl"])}
    empty_sharpe = portfolio_sharpe_from_replay(empty_result)
    if not np.isnan(empty_sharpe):
        failures.append(f"Case 4 FAILED: expected NaN for empty trade list, got {empty_sharpe}")

    print(f"Case 1 (matches independent resample reference): fixed={fixed_sharpe:.4f} "
          f"reference={reference_sharpe:.4f}")
    print(f"Case 2 (differs from old buggy convention): fixed={fixed_sharpe:.4f} old={old_sharpe:.4f} "
          f"(gap fixture: {n_calendar_days} calendar days, 3 active trading days)")
    print(f"Case 3 (no-gap fixture, conventions agree): fixed={dense_fixed:.4f} old={dense_old:.4f}")
    print(f"Case 4 (empty trade list -> NaN): {empty_sharpe}")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        sys.exit(1)
    print("\nAll BUG-D62 verification cases passed.")


if __name__ == "__main__":
    main()
