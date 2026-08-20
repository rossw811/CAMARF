"""
Synthetic verification of research/jkp_raw_characteristic_regression.py --
Option B's two core functions, run BEFORE trusting real WRDS data.

Checks:
  1. build_portfolio_characteristic_exposure correctly averages two legs'
     characteristic values for a pair, per month.
  2. A leg with a NaN characteristic value in a given month: the pair's
     exposure falls back to the OTHER leg's value (nanmean), not NaN
     outright -- avoids silently dropping months for a data gap on one leg.
  3. run_raw_characteristic_regression recovers a KNOWN, exactly-constructed
     loading: portfolio_return = 2.0 * char_1 (shifted) + noise=0 must
     recover a loading of ~2.0 on that characteristic and ~0 on unrelated
     ones.
  4. NO-LOOKAHEAD: characteristic exposure at month t must explain the
     return realized t->t+1, NOT the return realized ending AT t itself --
     verified by confirming the function's shift() call means an
     out-of-order/reversed relationship would NOT be recovered (a
     synthetic case where the true relationship is with the CONTEMPORANEOUS
     exposure, not the lagged one, must show a materially different/wrong
     loading than the true generating relationship, proving the lag is
     actually applied, not a no-op).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.jkp_raw_characteristic_regression import (
    build_portfolio_characteristic_exposure, run_raw_characteristic_regression, _CHAR_COLS
)


def main():
    failures = []

    # --- Check 1 & 2: exposure averaging, including a NaN-leg fallback ---
    panel = pd.DataFrame([
        {"permno": 1, "date": pd.Timestamp("2020-01-31"), "be_me": 0.4, "market_equity": 100,
         "ret_12_1": 0.1, "ni_be": 0.05, "at_gr1": 0.02, "beta_60m": 1.1},
        {"permno": 2, "date": pd.Timestamp("2020-01-31"), "be_me": 0.6, "market_equity": 200,
         "ret_12_1": 0.2, "ni_be": 0.03, "at_gr1": 0.04, "beta_60m": 0.9},
        # Month 2: permno 2's be_me is NaN -- should fall back to permno 1's value via nanmean.
        {"permno": 1, "date": pd.Timestamp("2020-02-29"), "be_me": 0.5, "market_equity": 110,
         "ret_12_1": 0.15, "ni_be": 0.06, "at_gr1": 0.01, "beta_60m": 1.0},
        {"permno": 2, "date": pd.Timestamp("2020-02-29"), "be_me": np.nan, "market_equity": 210,
         "ret_12_1": 0.25, "ni_be": 0.04, "at_gr1": 0.03, "beta_60m": 0.95},
    ])
    leg_permnos = {("A", "B"): (1, 2)}
    exposure = build_portfolio_characteristic_exposure(panel, leg_permnos)

    row1 = exposure[exposure["date"] == pd.Timestamp("2020-01-31")].iloc[0]
    if abs(row1["be_me"] - 0.5) > 1e-9:  # (0.4+0.6)/2
        failures.append(f"Check 1: expected be_me exposure 0.5, got {row1['be_me']}")

    row2 = exposure[exposure["date"] == pd.Timestamp("2020-02-29")].iloc[0]
    if abs(row2["be_me"] - 0.5) > 1e-9:  # nanmean(0.5, NaN) = 0.5, not NaN
        failures.append(f"Check 2: expected NaN-leg fallback be_me=0.5, got {row2['be_me']}")

    # --- Check 2b: the REAL sentinel involved (pandas nullable pd.NA, not plain
    # float NaN) -- the actual bug on the real run (2026-08-14) used a genuine
    # pd.NA value from raw_sql(), which crashed np.nanmean's internal `a != a`
    # comparison with "TypeError: boolean value of NA is ambiguous". Check 2
    # above uses np.nan (object dtype), which did NOT reproduce this -- must use
    # a real pandas nullable-dtype column to catch it, same lesson already
    # learned for the ticker-label pd.NA bug earlier this session.
    panel_na = pd.DataFrame({
        "permno": pd.array([1, 2], dtype="Int64"),
        "date": [pd.Timestamp("2020-03-31"), pd.Timestamp("2020-03-31")],
        "be_me": pd.array([0.5, pd.NA], dtype="Float64"),
        "market_equity": pd.array([100, 200], dtype="Float64"),
        "ret_12_1": pd.array([0.1, 0.2], dtype="Float64"),
        "ni_be": pd.array([0.05, 0.03], dtype="Float64"),
        "at_gr1": pd.array([0.02, 0.04], dtype="Float64"),
        "beta_60m": pd.array([1.1, 0.9], dtype="Float64"),
    })
    exposure_na = build_portfolio_characteristic_exposure(panel_na, {("A", "B"): (1, 2)})
    row2b = exposure_na.iloc[0]
    if abs(row2b["be_me"] - 0.5) > 1e-9:
        failures.append(f"Check 2b: genuine pd.NA leg should fall back to the other leg's value "
                         f"(0.5), got {row2b['be_me']} -- the exact real bug reproduced")

    # --- Check 3: recover a known exact loading via synthetic OLS data ---
    np.random.seed(0)
    months = pd.date_range("2010-01-31", periods=60, freq="ME")
    char_series = pd.DataFrame({
        "date": months,
        "pair_key": [("X", "Y")] * 60,
        **{c: np.random.randn(60) for c in _CHAR_COLS},
    })
    # exposure_df expects one row per (pair_key, date) with a groupby('date') mean downstream --
    # a single pair is fine since groupby collapses to the same series.
    exposure_df3 = char_series[["pair_key", "date"] + _CHAR_COLS]
    # True relationship: return(t+1) = 2.0 * be_me(t) -- no noise, exact.
    be_me_at_t = char_series.set_index("date")["be_me"]
    returns_shifted_forward = be_me_at_t.shift(-1) * 2.0  # return realized in month AFTER t's exposure
    # run_raw_characteristic_regression's OWN shift(1) on exposure means:
    # aligned return(t) is explained by exposure(t-1). So construct
    # portfolio_returns[t] = 2.0 * be_me[t-1] to match that convention exactly.
    portfolio_returns = (be_me_at_t.shift(1) * 2.0).dropna()
    result3 = run_raw_characteristic_regression(portfolio_returns, exposure_df3)
    if "error" in result3:
        failures.append(f"Check 3: regression failed unexpectedly: {result3}")
    else:
        got_loading = result3["loadings"]["be_me"]
        if abs(got_loading - 2.0) > 0.05:
            failures.append(f"Check 3: expected be_me loading ~2.0 (exact synthetic relationship), "
                             f"got {got_loading:.4f}")
        other_loadings = {c: v for c, v in result3["loadings"].items() if c != "be_me"}
        if any(abs(v) > 0.3 for v in other_loadings.values()):
            failures.append(f"Check 3: unrelated characteristics should have ~0 loading, "
                             f"got {other_loadings}")

    # --- Check 4: no-lookahead -- confirm the lag is REALLY applied, not a no-op.
    # If we instead built portfolio_returns from the CONTEMPORANEOUS (unshifted)
    # be_me, run_raw_characteristic_regression's internal shift(1) should now
    # recover a loading that does NOT match the true generating coefficient,
    # proving the function is not accidentally aligning on the same-period value.
    portfolio_returns_contemporaneous = (be_me_at_t * 2.0).dropna()
    result4 = run_raw_characteristic_regression(portfolio_returns_contemporaneous, exposure_df3)
    if "error" not in result4:
        got_loading4 = result4["loadings"]["be_me"]
        if abs(got_loading4 - 2.0) < 0.3:
            failures.append(f"Check 4: contemporaneous (same-period) relationship should NOT be "
                             f"recovered cleanly by a function that lags exposure by one period -- "
                             f"got loading {got_loading4:.4f}, too close to the true contemporaneous "
                             f"coefficient 2.0, suggesting the shift(1) lag isn't actually being applied")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All Option B (raw characteristic regression) checks passed.")
    print(f"  Check 1: exposure averaging -> be_me={row1['be_me']}")
    print(f"  Check 2: NaN-leg fallback -> be_me={row2['be_me']}")
    print(f"  Check 3: known synthetic loading recovered -> {result3['loadings']['be_me']:.4f} (expected ~2.0)")
    print(f"  Check 4: contemporaneous relationship correctly NOT recovered -> "
          f"loading={result4.get('loadings', {}).get('be_me')}")


if __name__ == "__main__":
    main()
