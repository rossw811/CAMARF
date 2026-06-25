"""
Synthetic verification for lead_lag_scan.py (2026-06-24).

Constructs two synthetic price series where B is a noisy, lagged copy of
A at a KNOWN, planted lag k_true (B_t = A_{t-k_true} + small i.i.d. level
noise). Confirms:
  1. lagged_corr_scan/best_lag recovers k_true exactly as the argmax-|corr|
     lag, with a large, unambiguous lift over lag 0.
  2. The EG test on the realigned series at k_true is far more significant
     (lower p-value, by construction much lower residual variance) than
     at lag 0 — the comparative claim the scan's "confirm stage" relies
     on. (Not asserting lag 0 fails outright: A_t - A_{t-k_true} is a
     finite-window sum of i.i.d. increments and so is itself stationary,
     a known property of any I(1) series vs its own fixed lag — so lag 0
     may also show nominal stationarity in this single-random-walk-source
     design, just with much higher residual variance. The meaningful,
     mathematically honest claim is the COMPARATIVE one.)

Run: python debug/_verify_lead_lag_scan.py
"""
import os
import sys

import numpy as np
import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "research"))

from lead_lag_scan import (
    _eg_pvalue,
    _gap_masked_log_price,
    best_lag,
    lagged_corr_scan,
)
from data import _gap_aware_returns

SEED = 42
N_VISIBLE = 600
BUFFER = 15
K_TRUE = 6
MAX_LAG = 10
SIGMA_A = 0.02
SIGMA_LEVEL = 0.002


def build_synthetic_pair():
    rng = np.random.default_rng(SEED)
    n_total = N_VISIBLE + BUFFER

    log_a_full = np.empty(n_total)
    log_a_full[0] = np.log(100.0)
    increments = rng.normal(0.0, SIGMA_A, size=n_total - 1)
    log_a_full[1:] = np.log(100.0) + np.cumsum(increments)

    log_b_full = np.full(n_total, np.nan)
    level_noise = rng.normal(0.0, SIGMA_LEVEL, size=n_total)
    for t in range(K_TRUE, n_total):
        log_b_full[t] = log_a_full[t - K_TRUE] + level_noise[t]

    log_a = log_a_full[BUFFER:]
    log_b = log_b_full[BUFFER:]
    assert np.all(np.isfinite(log_b)), "BUFFER must be >= K_TRUE"

    idx = pd.date_range("2026-01-01", periods=N_VISIBLE, freq="1min")
    df_a = pd.DataFrame({"close": np.exp(log_a)}, index=idx)
    df_b = pd.DataFrame({"close": np.exp(log_b)}, index=idx)
    return df_a, df_b


def main():
    df_a, df_b = build_synthetic_pair()

    ret_a = pd.Series(_gap_aware_returns(df_a), index=df_a.index)
    ret_b = pd.Series(_gap_aware_returns(df_b), index=df_b.index)
    scan = lagged_corr_scan(ret_a, ret_b, MAX_LAG)
    k_star, c_star, n_star = best_lag(scan)
    c0, n0 = scan[0]

    print(f"Planted lag k_true={K_TRUE}, max_lag={MAX_LAG}")
    print(f"Recovered best_lag={k_star}, corr_at_best_lag={c_star:.4f} (n={n_star})")
    print(f"corr_at_lag0={c0:.4f} (n={n0})")
    for k in sorted(scan):
        c, n = scan[k]
        marker = " <-- planted" if k == K_TRUE else (" <-- lag 0" if k == 0 else "")
        if c is not None:
            print(f"  lag {k:+3d}: corr={c:+.4f} n={n}{marker}")

    assert k_star == K_TRUE, f"FAILED: recovered lag {k_star} != planted lag {K_TRUE}"
    assert abs(c_star) > 0.8, f"FAILED: |corr| at planted lag too weak: {c_star}"
    assert abs(c0) < 0.3, f"FAILED: |corr| at lag 0 unexpectedly strong: {c0}"
    print("PASS: correlation scan recovers the planted lag with a clean lift over lag 0.")

    log_a = pd.Series(_gap_masked_log_price(df_a), index=df_a.index)
    log_b = pd.Series(_gap_masked_log_price(df_b), index=df_b.index)

    joined0 = pd.concat([log_a, log_b], axis=1, join="inner").dropna()
    eg_p0, n_eg0 = _eg_pvalue(joined0.iloc[:, 0].values, joined0.iloc[:, 1].values, max_eg_lag=10)

    shifted_b = log_b.shift(-K_TRUE)
    joined_k = pd.concat([log_a, shifted_b], axis=1, join="inner").dropna()
    eg_pk, n_eg_k = _eg_pvalue(joined_k.iloc[:, 0].values, joined_k.iloc[:, 1].values, max_eg_lag=10)

    print(f"\nEG p-value at lag 0:      {eg_p0} (n={n_eg0})")
    print(f"EG p-value at lag k_true: {eg_pk} (n={n_eg_k})")

    assert eg_pk is not None and eg_p0 is not None, "FAILED: EG test did not run on synthetic data"
    assert eg_pk < 0.01, f"FAILED: EG at planted lag not significant: p={eg_pk}"
    assert eg_pk < eg_p0, (
        f"FAILED: EG at planted lag ({eg_pk}) not better than at lag 0 ({eg_p0}) — "
        f"the comparative claim the scan's confirm stage relies on does not hold here."
    )
    print("PASS: EG confirms the planted lag is far more significant than lag 0.")
    print("\nALL CHECKS PASSED.")


if __name__ == "__main__":
    main()
