"""
Synthetic verification of research/jkp_thread_m_driver.py::run_monthly_regression
-- run BEFORE trusting it against CAMARF's real Step 5 backtest returns.

Checks:
  1. A known, exactly-constructed relationship (portfolio_return = rf + 0.5 *
     factor_1, no noise) recovers a ~0.5 loading on factor_1 and ~0 alpha.
  2. Insufficient overlap (fewer months than n_params + 3) is correctly
     flagged ok=False, not silently fit on too few observations.
  3. dof_trustworthy correctly flips False when n_params approaches n_months
     (the real constraint this driver's docstring is built around), and
     True when there's ample slack.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.jkp_thread_m_driver import run_monthly_regression


def main():
    failures = []
    np.random.seed(0)

    # --- Check 1: known exact relationship recovered ---
    months = pd.date_range("2015-01-31", periods=60, freq="ME")
    factor_1 = pd.Series(np.random.randn(60) * 0.05, index=months)
    factor_2 = pd.Series(np.random.randn(60) * 0.05, index=months)  # unrelated
    rf = pd.Series(0.001, index=months)  # flat 0.1%/month risk-free
    portfolio_returns = rf + 0.5 * factor_1  # exact, no noise, no alpha
    factors_df = pd.DataFrame({"f1": factor_1, "f2": factor_2})

    result1 = run_monthly_regression(portfolio_returns, factors_df, ["f1", "f2"], rf)
    if not result1["ok"]:
        failures.append(f"Check 1: regression unexpectedly failed: {result1}")
    else:
        if abs(result1["loadings"]["f1"] - 0.5) > 0.01:
            failures.append(f"Check 1: expected f1 loading ~0.5, got {result1['loadings']['f1']:.4f}")
        if abs(result1["loadings"]["f2"]) > 0.05:
            failures.append(f"Check 1: expected f2 loading ~0 (unrelated), "
                             f"got {result1['loadings']['f2']:.4f}")
        if abs(result1["alpha_monthly"]) > 0.001:
            failures.append(f"Check 1: expected alpha ~0 (exact relationship, no excess), "
                             f"got {result1['alpha_monthly']:.6f}")

    # --- Check 2: insufficient overlap correctly flagged ---
    short_months = pd.date_range("2020-01-31", periods=5, freq="ME")
    short_returns = pd.Series(np.random.randn(5) * 0.01, index=short_months)
    short_factors = pd.DataFrame({
        "f1": np.random.randn(5) * 0.05, "f2": np.random.randn(5) * 0.05,
    }, index=short_months)
    short_rf = pd.Series(0.001, index=short_months)
    result2 = run_monthly_regression(short_returns, short_factors, ["f1", "f2"], short_rf)
    if result2["ok"]:
        failures.append(f"Check 2: expected insufficient_overlap with only 5 months vs 3 params, "
                         f"got ok=True: {result2}")

    # --- Check 3: dof_trustworthy flips correctly ---
    # 20 months, 17 factors + const = 18 params -> dof = 2, should be untrustworthy.
    many_months = pd.date_range("2018-01-31", periods=20, freq="ME")
    many_factor_names = [f"f{i}" for i in range(17)]
    many_factors = pd.DataFrame(
        {name: np.random.randn(20) * 0.05 for name in many_factor_names}, index=many_months
    )
    many_rf = pd.Series(0.001, index=many_months)
    many_returns = pd.Series(np.random.randn(20) * 0.02, index=many_months) + many_rf
    result3_thin = run_monthly_regression(many_returns, many_factors, many_factor_names, many_rf)
    if result3_thin["ok"] and result3_thin["dof_trustworthy"]:
        failures.append(f"Check 3a: 20 months vs 18 params (dof=2) should be flagged NOT "
                         f"trustworthy, got dof_trustworthy=True (dof={result3_thin.get('dof')})")

    # Same 20 months, only 2 factors -> dof = 17, should be trustworthy.
    result3_ample = run_monthly_regression(many_returns, many_factors, many_factor_names[:2], many_rf)
    if result3_ample["ok"] and not result3_ample["dof_trustworthy"]:
        failures.append(f"Check 3b: 20 months vs 3 params (dof=17) should be flagged "
                         f"trustworthy, got dof_trustworthy=False (dof={result3_ample.get('dof')})")

    # --- Check 4: sparse-trading flag (real finding, 2026-08-14: baseline/tiered arms were
    # 81% exact-zero months, producing spuriously extreme t-stats) is correctly raised. ---
    sparse_months = pd.date_range("2020-01-31", periods=30, freq="ME")
    sparse_returns = pd.Series(0.0, index=sparse_months)
    sparse_returns.iloc[[5, 15, 25]] = [0.02, -0.015, 0.03]  # only 3/30 nonzero -> 90% zero
    sparse_factors = pd.DataFrame({
        "f1": np.random.randn(30) * 0.05, "f2": np.random.randn(30) * 0.05,
    }, index=sparse_months)
    sparse_rf = pd.Series(0.001, index=sparse_months)
    result4 = run_monthly_regression(sparse_returns, sparse_factors, ["f1", "f2"], sparse_rf)
    if result4["ok"] and not result4["sparse_trading"]:
        failures.append(f"Check 4: 90% zero-return months should be flagged sparse_trading=True, "
                         f"got False (zero_month_frac={result4.get('zero_month_frac')})")
    if result4["ok"] and result4["trustworthy"]:
        failures.append(f"Check 4: a sparse-trading result should never be marked overall "
                         f"trustworthy=True regardless of DOF, got trustworthy=True")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All Thread M driver (monthly regression) checks passed.")
    print(f"  Check 1: known relationship recovered -> f1 loading={result1['loadings']['f1']:.4f} "
          f"(expected 0.5), alpha={result1['alpha_monthly']:.6f} (expected ~0)")
    print(f"  Check 2: insufficient overlap correctly flagged ok=False")
    print(f"  Check 3: dof_trustworthy correctly flips (thin dof={result3_thin.get('dof')} -> False, "
          f"ample dof={result3_ample.get('dof')} -> True)")


if __name__ == "__main__":
    main()
