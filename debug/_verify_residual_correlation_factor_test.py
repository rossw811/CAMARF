"""
debug/_verify_residual_correlation_factor_test.py -- synthetic checks for
research/residual_correlation_factor_test.py, run BEFORE trusting it
against real return data.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.residual_correlation_factor_test import (
    compute_residual_returns, residual_correlation_from_precomputed, two_proportion_z_test,
    safe_log_returns,
)

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


print("Check 1: compute_residual_returns -- a symbol that IS the factor (beta=1, no alpha) has "
      "near-zero residuals")
rng = np.random.default_rng(0)
n = 500
idx = pd.date_range("2015-01-01", periods=n, freq="B")
factor = pd.Series(rng.normal(0, 0.01, n), index=idx)
same_as_factor = factor.copy()  # a symbol that's literally the factor
resid = compute_residual_returns(same_as_factor, factor)
check("a symbol identical to the factor has near-zero residual variance (correctly explained away)",
      resid.std() < 1e-10)

print("Check 2: compute_residual_returns -- a symbol with a real IDIOSYNCRATIC component keeps "
      "that component after factor removal")
idiosyncratic = pd.Series(rng.normal(0, 0.02, n), index=idx)
mixed = 0.5 * factor + idiosyncratic  # real factor exposure (beta=0.5) PLUS real idio noise
resid2 = compute_residual_returns(mixed, factor)
check("residual std is close to the injected idiosyncratic std (0.02), not near-zero",
      abs(resid2.std() - idiosyncratic.reindex(resid2.index).std()) < 0.005)

print("Check 3: compute_residual_returns -- insufficient overlap (< 60 obs) returns an empty Series")
short_series = pd.Series(rng.normal(0, 0.01, 30), index=idx[:30])
resid3 = compute_residual_returns(short_series, factor)
check("fewer than 60 overlapping observations produces an empty Series, not a fabricated result",
      len(resid3) == 0)

print("Check 4: residual_correlation_from_precomputed -- two symbols that ONLY correlate via a "
      "shared factor show near-zero RESIDUAL correlation once factor-adjusted")
sym_a = 3.0 * factor + pd.Series(rng.normal(0, 0.005, n), index=idx)
sym_b = 3.0 * factor + pd.Series(rng.normal(0, 0.005, n), index=idx)
raw_corr = sym_a.corr(sym_b)
resid_a = compute_residual_returns(sym_a, factor)
resid_b = compute_residual_returns(sym_b, factor)
residual_corr = residual_correlation_from_precomputed(resid_a, resid_b)
check(f"raw correlation is meaningfully positive (factor-driven, {raw_corr:.3f})", raw_corr > 0.3)
check(f"residual correlation collapses toward zero once the shared factor is removed "
      f"({residual_corr:.3f}, vs. raw {raw_corr:.3f}) -- the CONFOUND CASE this test exists "
      f"to detect", abs(residual_corr) < 0.15 and abs(residual_corr) < abs(raw_corr))

print("Check 5: residual_correlation_from_precomputed -- two symbols with a REAL idiosyncratic "
      "relationship (beyond the factor) keep a real residual correlation")
shared_idio = pd.Series(rng.normal(0, 0.015, n), index=idx)
sym_c = 0.3 * factor + shared_idio + pd.Series(rng.normal(0, 0.005, n), index=idx)
sym_d = 0.3 * factor + shared_idio + pd.Series(rng.normal(0, 0.005, n), index=idx)
resid_c = compute_residual_returns(sym_c, factor)
resid_d = compute_residual_returns(sym_d, factor)
residual_corr2 = residual_correlation_from_precomputed(resid_c, resid_d)
check(f"a genuine idiosyncratic relationship SURVIVES factor-adjustment "
      f"({residual_corr2:.3f}, should stay well above 0.3) -- the NON-confound case",
      residual_corr2 > 0.3)

print("Check 6: two_proportion_z_test -- matches the same formula already used and verified "
      "elsewhere in this project's discovery-event work")
test_real_gap = two_proportion_z_test(8, 10, 2, 10)
check("a real, large constructed gap (0.8 vs 0.2) registers as significant (p < 0.05)",
      test_real_gap["p_value"] is not None and test_real_gap["p_value"] < 0.05)
test_zero_n = two_proportion_z_test(0, 0, 5, 10)
check("zero-n group returns None (not a crash, not a fabricated p-value)",
      test_zero_n["p_value"] is None)

print("Check 7: safe_log_returns -- a zero/negative close price does NOT silently produce -inf; "
      "real bug found live (2026-09-03): a naive np.log(close).diff() hit 'divide by zero' "
      "2,092 times across the real full universe before this fix")
import warnings
bad_close = pd.Series([100.0, 101.0, 0.0, 103.0, -5.0, 104.0],
                       index=pd.date_range("2020-01-01", periods=6, freq="D"))
with warnings.catch_warnings():
    warnings.simplefilter("error")  # any RuntimeWarning (divide-by-zero, invalid log) now raises
    try:
        result7 = safe_log_returns(bad_close)
        no_warning_raised = True
    except RuntimeWarning:
        no_warning_raised = False
check("a zero/negative close price produces NO divide-by-zero/invalid-log warning "
      "(masked to NaN before the log, not after)", no_warning_raised)
check("no -inf or inf values leak into the output (the exact corruption this fix prevents)",
      not np.isinf(result7).any())
check("every return touching a masked (non-positive) price is correctly NaN-dropped, not "
      "just the bad bar itself -- close=[100,101,0,103,-5,104] only yields ONE clean return "
      "(day1->day2, 100->101); every other diff touches a masked NaN on one side",
      len(result7) == 1)

print("Check 8: safe_log_returns -- the REAL root cause, reproduced directly: pandas nullable "
      "Float64 dtype (not plain float64) with NaN values, no zero/negative prices at all -- "
      "this is what the real WRDS cache actually looks like (traced live, not assumed)")
import warnings
nullable_close = pd.Series(
    [100.0, 101.0, None, 103.0, 104.0, None, 106.0],
    index=pd.date_range("2020-01-01", periods=7, freq="D"), dtype="Float64",
)
check("input is genuinely the nullable Float64 dtype (matching real WRDS data), not plain "
      "float64 -- confirms this check targets the real scenario",
      str(nullable_close.dtype) == "Float64")
with warnings.catch_warnings():
    warnings.simplefilter("error")
    try:
        result8 = safe_log_returns(nullable_close)
        no_warning_raised2 = True
    except RuntimeWarning:
        no_warning_raised2 = False
check("a nullable-Float64 series with NaN (but NO non-positive prices) produces NO "
      "divide-by-zero warning after converting to plain float64 first",
      no_warning_raised2)
check("no inf/-inf leaks into the output", not np.isinf(result8).any())
check("valid returns are still computed correctly around the NaN gaps "
      "(100->101 and 103->104 are clean adjacent pairs, both should survive)",
      len(result8) == 2)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
