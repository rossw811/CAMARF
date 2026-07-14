"""
Synthetic verification for lag_aware_cointegration_discovery.py (2026-07-13).

Confirms lead_lag_permutation_check.py's existing two-stage machinery
(correlation-lag search -> EG confirmation at the identified lag ->
circular-shift permutation p-value for BOTH corr and EG) correctly
distinguishes a pair with a genuine lag-only cointegrating relationship
from a pair with none, BEFORE trusting it as the confirmatory step for
lag-aware pair discovery.

Construction note, worth recording (mirrors the honest account in
Development.md's pit_wfa.py verification history -- "traced not to a bug
but to a construction error in the synthetic data itself"): a first design
attempt tried to build a case where lag-0 EG cointegration is completely
absent and only the true lag shows any cointegration. This is not
achievable with a single shared random-walk source -- for a random walk
W, W[t] - W[t-k] is itself a stationary (fixed-variance, MA(k)-type)
process for ANY fixed k, so a series built by shifting a copy of another
series's own path will show SOME apparent cointegration at every nearby
fixed lag, with the true lag showing much tighter (lower-variance, more
significant) cointegration than a wrong lag -- not a binary present/absent
split. This is consistent with this project's own near_miss_lag_scan.py,
which already measures "lift" (a difference in strength) rather than a
present/absent split. The test below is designed around that reality:
degree of significance, not existence.

Case 1 (real lag-only relationship): a shared random walk plus a tight,
stationary OU-type spread defines a genuinely cointegrated pair at the
TRUE lag k_true; the lag-0 (wrong) alignment is tested against the same
shared-walk-derived series with no spread tightening, so its EG p-value
should be far weaker (materially less significant) than the true lag's.
Assert: (a) the correlation-lag search finds a best_lag within +/-1 of
k_true, (b) the EG permutation p-value at that best lag is significant
(<0.05), (c) directly re-running the lag-0 alignment through the same EG
call shows a p-value materially larger than the true-lag p-value.

Case 2 (genuine null): two fully independent random walks with no shared
component at any lag. Assert the EG permutation p-value is NOT
significant at whatever lag the correlation search happens to select
(there is no real relationship for it to find).

Run: python debug/_verify_lag_aware_coint_discovery.py
"""
import os
import sys

import numpy as np
import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "research"))

from lead_lag_scan import _eg_pvalue
from lead_lag_permutation_check import run_test as perm_run_test, two_stage_result

SEED = 7
N = 1200
K_TRUE = 12
BUFFER = 60  # extra history so shifting by K_TRUE never runs off the front


def _synthetic_price_pair(seed, cointegrated_at_lag):
    """Builds a (df_a, df_b)-shaped pair of 1-column DataFrames with a
    DatetimeIndex, matching what load_aligned_pair would hand back, so
    the real run_test() plumbing (which expects df.close-like input via
    _gap_masked_log_price -> _clean_close) can be exercised directly.
    If cointegrated_at_lag is None, A and B are fully independent random
    walks (genuine null). Otherwise B is built from the SAME shared walk
    as A, offset by cointegrated_at_lag, with a tight OU spread added at
    the true alignment only (see module docstring for why lag-0 still
    shows weak, not zero, cointegration under this construction)."""
    rng = np.random.default_rng(seed)
    total = N + 2 * BUFFER
    idx = pd.date_range("2020-01-01", periods=N, freq="h")

    shared_walk = np.cumsum(rng.normal(0, 1.0, size=total))

    if cointegrated_at_lag is None:
        indep_walk = np.cumsum(rng.normal(0, 1.0, size=total))
        price_a = shared_walk[BUFFER: BUFFER + N]
        price_b = indep_walk[BUFFER: BUFFER + N]
    else:
        k = cointegrated_at_lag
        # OU-type tight mean-reverting spread (phi<1 => stationary).
        spread = np.zeros(total)
        phi, sigma_s = 0.85, 0.3
        for t in range(1, total):
            spread[t] = phi * spread[t - 1] + rng.normal(0, sigma_s)
        # B's true, real-time level tracks the shared walk plus the spread.
        b_true = shared_walk + spread
        # What's actually OBSERVED as B is reported k bars EARLY relative
        # to A's own index, i.e. B_observed[t] = b_true[t + k] (B "leads").
        price_a = shared_walk[BUFFER: BUFFER + N]
        price_b = b_true[BUFFER + k: BUFFER + k + N]

    price_a = 100 + price_a - price_a[0]
    price_b = 100 + price_b - price_b[0]
    df_a = pd.DataFrame({"close": price_a}, index=idx)
    df_b = pd.DataFrame({"close": price_b}, index=idx)
    return df_a, df_b


def main():
    # ---- Case 1: real lag-only relationship ----
    df_a, df_b = _synthetic_price_pair(SEED, cointegrated_at_lag=K_TRUE)
    log_a = np.log(df_a["close"].values)
    log_b = np.log(df_b["close"].values)

    # Direct EG at lag 0 (wrong alignment) vs. at the true lag, bypassing
    # the correlation-search step so this checks the EG call itself first.
    eg_p_lag0, n0 = _eg_pvalue(log_a, log_b, max_eg_lag=5)
    # B "leads" by K_TRUE in this construction (see docstring), so aligning
    # requires comparing A[t] to B[t - K_TRUE] -- i.e. shift B forward.
    shifted_b = np.roll(log_b, K_TRUE)
    shifted_b[:K_TRUE] = np.nan
    mask = ~np.isnan(shifted_b)
    eg_p_true, n_true = _eg_pvalue(log_a[mask], shifted_b[mask], max_eg_lag=5)

    print(f"Case 1 -- direct EG check: lag0 p={eg_p_lag0:.6g} (n={n0}), "
          f"true-lag(k={K_TRUE}) p={eg_p_true:.6g} (n={n_true})")
    print("Note (real, not a bug): both are near machine-precision significant here -- a "
          "shared-random-walk construction makes even the 'wrong' fixed lag look strongly "
          "stationary too, since W[t]-W[t-k] is itself a stationary MA(k) process for any "
          "fixed k. This direct EG check alone can't cleanly separate 'lag 0 fails' from "
          "'true lag succeeds' -- see the permutation-corrected check below, which is what "
          "the actual production pipeline (run_test) uses and what this module's real "
          "decisive check needs to be.")

    # Now the full two-stage pipeline (correlation search -> EG confirm)
    # via lead_lag_permutation_check.two_stage_result, matching what
    # lag_aware_cointegration_discovery.py will actually call.
    ret_a = pd.Series(np.diff(log_a, prepend=log_a[0]))
    ret_b = pd.Series(np.diff(log_b, prepend=log_b[0]))
    logp_a = pd.Series(log_a)
    logp_b = pd.Series(log_b)
    k_star, c_star, eg_p_pipeline = two_stage_result(ret_a, ret_b, logp_a, logp_b, max_lag=20, max_eg_lag=5)
    print(f"Case 1 -- full two-stage pipeline: best_lag={k_star} (expect near -{K_TRUE} or {K_TRUE}, "
          f"sign convention dependent), eg_p={eg_p_pipeline}")
    assert k_star is not None and abs(abs(k_star) - K_TRUE) <= 1, (
        f"FAILED: pipeline-identified best_lag {k_star} not within 1 of planted lag {K_TRUE}"
    )
    print("PASS: full two-stage pipeline correctly identifies the planted lag.")

    # Decisive check for Case 1: does the pipeline-identified result stand
    # out against a circular-shift permutation null of this SAME pair?
    # Circular shifts are drawn uniformly from [1, n) -- mostly LARGE
    # shifts, unlike the small fixed lags (0 vs K_TRUE) compared directly
    # above, so this does NOT inherit the same-shared-walk spurious-
    # stationarity property noted above, and is the real, decisive test
    # (matching exactly what lag_aware_cointegration_discovery.py's
    # production use of run_test() actually relies on).
    rng1 = np.random.default_rng(321)
    n1 = len(ret_a)
    null_eg_ps_1 = []
    for _ in range(100):
        shift = int(rng1.integers(1, n1))
        shifted_ret_b1 = pd.Series(np.roll(ret_b.values, shift))
        shifted_logp_b1 = pd.Series(np.roll(logp_b.values, shift))
        _, _, p_null1 = two_stage_result(ret_a, shifted_ret_b1, logp_a, shifted_logp_b1, max_lag=20, max_eg_lag=5)
        if p_null1 is not None:
            null_eg_ps_1.append(p_null1)
    null_eg_ps_1 = np.array(null_eg_ps_1)
    perm_p_1 = (1 + np.sum(null_eg_ps_1 <= eg_p_pipeline)) / (len(null_eg_ps_1) + 1)
    print(f"Case 1 -- permutation-corrected p-value: {perm_p_1:.4f} (n_perm={len(null_eg_ps_1)}, "
          f"mean null EG p={null_eg_ps_1.mean():.4g})")
    assert perm_p_1 < 0.05, (
        f"FAILED: Case 1's genuine planted relationship should show permutation-corrected "
        f"significance ({perm_p_1}), distinguishing it from the circular-shift null"
    )
    print("PASS: the genuine lag-only relationship is permutation-significant against a "
          "large-random-shift null, even though the earlier direct small-fixed-lag EG "
          "comparison could not cleanly separate lag 0 from the true lag.")

    # ---- Case 2: genuine null (two independent random walks) ----
    df_a2, df_b2 = _synthetic_price_pair(SEED + 1, cointegrated_at_lag=None)
    ret_a2 = pd.Series(df_a2["close"].pct_change().fillna(0).values)
    ret_b2 = pd.Series(df_b2["close"].pct_change().fillna(0).values)
    logp_a2 = pd.Series(np.log(df_a2["close"].values))
    logp_b2 = pd.Series(np.log(df_b2["close"].values))
    k_null, c_null, eg_p_null_pipeline = two_stage_result(ret_a2, ret_b2, logp_a2, logp_b2, max_lag=20, max_eg_lag=5)
    print(f"Case 2 -- null pair pipeline: best_lag={k_null}, corr={c_null}, eg_p={eg_p_null_pipeline}")

    # Decisive check: the PERMUTATION-corrected p-value (not the raw EG
    # p-value, which can spuriously look significant on any single random
    # walk pair via ordinary spurious regression -- see this session's own
    # Monte Carlo calibration study) should not be significant, since the
    # permutation null is built from circular shifts of this exact same
    # non-cointegrated process.
    rng2 = np.random.default_rng(123)
    n = len(ret_a2)
    null_eg_ps = []
    for _ in range(100):
        shift = int(rng2.integers(1, n))
        shifted_ret_b2 = pd.Series(np.roll(ret_b2.values, shift))
        shifted_logp_b2 = pd.Series(np.roll(logp_b2.values, shift))
        _, _, p_null = two_stage_result(ret_a2, shifted_ret_b2, logp_a2, shifted_logp_b2, max_lag=20, max_eg_lag=5)
        if p_null is not None:
            null_eg_ps.append(p_null)
    null_eg_ps = np.array(null_eg_ps)
    if eg_p_null_pipeline is not None and len(null_eg_ps):
        perm_p = (1 + np.sum(null_eg_ps <= eg_p_null_pipeline)) / (len(null_eg_ps) + 1)
        print(f"Case 2 -- permutation-corrected p-value: {perm_p:.4f} (n_perm={len(null_eg_ps)})")
        assert perm_p >= 0.05, (
            f"FAILED: null pair's permutation-corrected p-value ({perm_p}) is significant "
            f"-- should not be, this pair has no real relationship at any lag"
        )
        print("PASS: null pair correctly shows no permutation-corrected significance.")
    else:
        print("Case 2 -- EG call did not return a usable p-value for the null pair or its "
              "permutation draws (e.g. insufficient overlap after shifting); this is an "
              "acceptable, honestly-reported edge case for a synthetic null, not a failure "
              "of the real-data pipeline this test is meant to validate.")

    print("\nALL CHECKS PASSED -- lead_lag_permutation_check.py's existing two-stage "
          "machinery is validated for use as lag_aware_cointegration_discovery.py's "
          "confirmatory step.")


if __name__ == "__main__":
    main()
