"""
Synthetic verification for research/confirmatory_cointegration_check.py's
run_confirmatory_pair() (2026-07-20). Constructs one genuinely cointegrated
pair (shared random-walk common factor + independent stationary idiosyncratic
noise per leg) and one genuinely non-cointegrated pair (two fully independent
random walks -- the textbook spurious-regression case), and confirms:

1. The cointegrated pair: Johansen rejects "no cointegration" at 95%, and
   KPSS fails to reject stationarity of the OLS residual (p>0.05) -- both
   test families agree the pair is cointegrated, as expected.
2. The non-cointegrated pair: Johansen does NOT reject "no cointegration"
   at 95% (fails to find a cointegrating relationship, correctly), and KPSS
   REJECTS stationarity of the residual (p<=0.05) -- the classic spurious-
   regression signature (a random-walk residual, not a stationary one).

This is the exact property the real run's "corroboration verdict" logic
rests on -- if the harness got either direction backwards here, every
corroboration claim on real pairs would be untrustworthy.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.confirmatory_cointegration_check import run_confirmatory_pair

rng = np.random.default_rng(20260720)
n = 3000

# --- Cointegrated pair ---
common = np.cumsum(rng.normal(0, 1.0, n))
a_coint = common + rng.normal(0, 0.3, n)
b_coint = common + rng.normal(0, 0.3, n)
res_coint = run_confirmatory_pair(a_coint, b_coint)

check1a = res_coint["ok"] and res_coint["johansen_rejects_no_coint_95"] is True
check1b = res_coint["ok"] and res_coint["kpss_fails_to_reject_stationarity_95"] is True
print(f"Cointegrated pair -- Johansen rejects no-coint@95: {res_coint.get('johansen_rejects_no_coint_95')} "
      f"({'PASS' if check1a else 'FAIL'})")
print(f"Cointegrated pair -- KPSS fails to reject stationarity@95: "
      f"{res_coint.get('kpss_fails_to_reject_stationarity_95')} (p={res_coint.get('kpss_pvalue')}) "
      f"({'PASS' if check1b else 'FAIL'})")

# --- Non-cointegrated pair: two independent random walks ---
a_indep = np.cumsum(rng.normal(0, 1.0, n))
b_indep = np.cumsum(rng.normal(0, 1.0, n))
res_indep = run_confirmatory_pair(a_indep, b_indep)

check2a = res_indep["ok"] and res_indep["johansen_rejects_no_coint_95"] is False
check2b = res_indep["ok"] and res_indep["kpss_fails_to_reject_stationarity_95"] is False
print(f"\nIndependent-walks pair -- Johansen rejects no-coint@95: "
      f"{res_indep.get('johansen_rejects_no_coint_95')} ({'PASS' if check2a else 'FAIL'})")
print(f"Independent-walks pair -- KPSS fails to reject stationarity@95: "
      f"{res_indep.get('kpss_fails_to_reject_stationarity_95')} (p={res_indep.get('kpss_pvalue')}) "
      f"({'PASS' if check2b else 'FAIL'})")

ok = check1a and check1b and check2a and check2b
print("\nPASS" if ok else "\nFAIL")
sys.exit(0 if ok else 1)
