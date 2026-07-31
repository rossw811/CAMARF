"""
Synthetic verification for the 2026-07-20 Grand Sweep fix to
run_storm_grid.py's portfolio_sharpe(): previously pooled daily P&L via
groupby("date") (drops zero-P&L calendar days, inflates Sharpe -- the
BUG-D62/D64/D70/D71 class), now uses portfolio_math.sharpe_from_trades()
(zero-filled via resample("1D"), matching aggregate_portfolio()'s
convention). This is the 7th confirmed recurrence of this bug class.
"""
import os
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_storm_grid import portfolio_sharpe


def _make_trade(exit_time, pnl_net):
    return SimpleNamespace(exit_time=pd.Timestamp(exit_time), pnl_net=pnl_net)


def _old_buggy_portfolio_sharpe(trades):
    pnl = np.array([t.pnl_net for t in trades])
    exit_times = [t.exit_time for t in trades if t.exit_time is not None]
    df = pd.DataFrame({"exit_time": exit_times, "pnl_net": pnl})
    df["date"] = pd.to_datetime(df["exit_time"]).dt.date
    daily = df.groupby("date")["pnl_net"].sum()
    if len(daily) >= 5 and daily.std() > 0:
        return float(daily.mean() / daily.std() * np.sqrt(252))
    return float("nan")


def main() -> None:
    failures = []

    # 5 trades clustered in the first week, then one 19 days later -- 15
    # zero-P&L calendar days in between (same fixture shape as BUG-D70's own
    # verification, for a consistent, comparable regression signature).
    trades = [
        _make_trade("2026-01-01", 100.0),
        _make_trade("2026-01-02", -50.0),
        _make_trade("2026-01-03", 75.0),
        _make_trade("2026-01-04", -20.0),
        _make_trade("2026-01-20", 30.0),
    ]

    new_sharpe, total, n, wr = portfolio_sharpe(trades)
    old_sharpe = _old_buggy_portfolio_sharpe(trades)

    if total != 135.0 or n != 5:
        failures.append(f"total/n unchanged by the fix should be 135.0/5, got {total}/{n}")
    if np.isclose(new_sharpe, old_sharpe, atol=1e-6):
        failures.append(
            f"new Sharpe ({new_sharpe}) suspiciously matches OLD buggy groupby convention "
            f"({old_sharpe}) on a fixture with real gaps -- fix may not be wired correctly"
        )

    # No-gap fixture: old and new must agree (no-op case).
    trades_clean = [_make_trade(f"2026-02-{d:02d}", 10.0 * ((-1) ** d)) for d in range(1, 11)]
    new_clean, _, _, _ = portfolio_sharpe(trades_clean)
    old_clean = _old_buggy_portfolio_sharpe(trades_clean)
    if not np.isclose(new_clean, old_clean, atol=1e-10):
        failures.append(f"no-gap fixture should agree exactly: new={new_clean} old={old_clean}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("run_storm_grid.py portfolio_sharpe() fix verified.")
        print(f"  Gappy fixture: OLD={old_sharpe:.6f}  NEW={new_sharpe:.6f}")
        print(f"  No-gap fixture: both agree, sharpe={new_clean:.6f}")


if __name__ == "__main__":
    main()
