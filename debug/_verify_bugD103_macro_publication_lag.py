"""
Synthetic verification of BUG-D103: macro.py's _align_to_trading_calendar()
indexed monthly FRED series by REFERENCE period (e.g. UNRATE's January 2024
reading stamped "2024-01-01"), not the date the print was actually published
to the public (~5-6 weeks later for UNRATE). reindex(..., method="ffill")
against the trading calendar therefore made a reading available weeks before
it was really released.

Verifies: a synthetic monthly series with ONE known value at a reference
date T is only visible on the trading calendar from T + the configured
publication lag onward -- not from T itself.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from macro import _align_to_trading_calendar, _MONTHLY_PUBLICATION_LAG_DAYS


def main():
    failures = []

    master_idx = pd.bdate_range("2024-01-01", "2024-04-01", freq="B")

    ref_date = pd.Timestamp("2024-02-01")  # February 2024 reading
    monthly_native = {
        "unemployment_rate": pd.Series([3.9], index=[ref_date]),
    }
    lag = _MONTHLY_PUBLICATION_LAG_DAYS["unemployment_rate"]
    expected_available_from = ref_date + pd.Timedelta(days=lag)

    out = _align_to_trading_calendar({}, monthly_native, master_idx)

    if "unemployment_rate" not in out.columns:
        failures.append("unemployment_rate column missing from aligned output — test construction issue")
    else:
        col = out["unemployment_rate"]
        # Any trading day strictly BEFORE the real publication date must NOT
        # already show the 3.9 reading (that would mean the value was
        # visible before it was actually released).
        pre_release = col.loc[col.index < expected_available_from]
        leaked = pre_release[pre_release == 3.9]
        if len(leaked) > 0:
            failures.append(
                f"LOOKAHEAD BUG: unemployment_rate=3.9 visible on {len(leaked)} trading day(s) "
                f"before its real publication date ({expected_available_from.date()}) — "
                f"earliest leak at {leaked.index.min().date()}"
            )

        # Sanity: it SHOULD become visible on/after the real publication date
        # (a formula that never surfaces the value at all would trivially
        # also pass the no-leak check above for the wrong reason).
        post_release = col.loc[col.index >= expected_available_from]
        if not (post_release == 3.9).any():
            failures.append(
                f"unemployment_rate=3.9 never appears on/after its publication date "
                f"({expected_available_from.date()}) — construction or reindex issue"
            )

    # Reference check: with lag_days=0 (old, buggy behavior), the value
    # WOULD leak onto trading days between ref_date and expected_available_from
    # -- confirms the test actually distinguishes lagged vs unlagged behavior.
    old_behavior = monthly_native["unemployment_rate"].sort_index().reindex(master_idx, method="ffill")
    old_leaked = old_behavior.loc[(old_behavior.index >= ref_date) & (old_behavior.index < expected_available_from)]
    if not (old_leaked == 3.9).any():
        failures.append("test construction issue: old (unlagged) behavior doesn't actually leak in this window — lag/window too small to distinguish")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("BUG-D103 verification passed.")
    print(f"  reference date = {ref_date.date()}, publication lag = {lag} days, real availability = {expected_available_from.date()}")
    print(f"  value correctly absent from trading calendar until {expected_available_from.date()}")


if __name__ == "__main__":
    main()
