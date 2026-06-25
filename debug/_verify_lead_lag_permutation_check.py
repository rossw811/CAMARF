"""
Synthetic verification for lead_lag_permutation_check.py (2026-06-24).

Two checks:
  1. Positive control: the same planted-lag synthetic pair used in
     debug/_verify_lead_lag_scan.py (B_t = A_{t-6} + small noise) should
     remain significant AFTER the look-elsewhere correction — a real
     signal should survive proper correction, not just a lag-0 test.
  2. False-positive calibration: M independent pairs of completely
     UNRELATED random walks (no shared structure at all) should reject
     at roughly the nominal ~5% rate, not an inflated rate — this is the
     actual point of building this script. If the correction doesn't
     work, this check will show a wildly inflated false-positive rate
     even though each individual null draw "only" searches 21 lags.

Run: python debug/_verify_lead_lag_permutation_check.py
"""
import os
import sys

import numpy as np
import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "research"))

from lead_lag_permutation_check import run_test

SEED = 123


def build_planted_lag_pair(seed=42, n_visible=600, buffer=15, k_true=6,
                            sigma_a=0.02, sigma_level=0.002):
    rng = np.random.default_rng(seed)
    n_total = n_visible + buffer

    log_a_full = np.empty(n_total)
    log_a_full[0] = np.log(100.0)
    increments = rng.normal(0.0, sigma_a, size=n_total - 1)
    log_a_full[1:] = np.log(100.0) + np.cumsum(increments)

    log_b_full = np.full(n_total, np.nan)
    level_noise = rng.normal(0.0, sigma_level, size=n_total)
    for t in range(k_true, n_total):
        log_b_full[t] = log_a_full[t - k_true] + level_noise[t]

    log_a = log_a_full[buffer:]
    log_b = log_b_full[buffer:]
    idx = pd.date_range("2026-01-01", periods=n_visible, freq="1min")
    df_a = pd.DataFrame({"close": np.exp(log_a)}, index=idx)
    df_b = pd.DataFrame({"close": np.exp(log_b)}, index=idx)
    return df_a, df_b


def build_independent_pair(seed, n_visible=600, sigma=0.02):
    rng = np.random.default_rng(seed)
    log_a = np.log(100.0) + np.cumsum(rng.normal(0.0, sigma, size=n_visible))
    log_b = np.log(100.0) + np.cumsum(rng.normal(0.0, sigma, size=n_visible))
    idx = pd.date_range("2026-01-01", periods=n_visible, freq="1min")
    df_a = pd.DataFrame({"close": np.exp(log_a)}, index=idx)
    df_b = pd.DataFrame({"close": np.exp(log_b)}, index=idx)
    return df_a, df_b


def main():
    import data

    # --- Positive control ---
    df_a, df_b = build_planted_lag_pair(seed=42)

    orig_load = data.DataStore.load

    def fake_load(symbol, tf_label):
        return {"A": df_a, "B": df_b}.get(symbol)

    # Patches the DataStore CLASS itself — aligned_pair_loader.py's
    # `from data import DataAligner, DataStore` binds the same class
    # object, so this patch is visible there too without re-patching.
    data.DataStore.load = staticmethod(fake_load)
    try:
        result = run_test("A", "B", "1m", max_lag=10, n_perm=300, seed=1, run_eg=True)
    finally:
        data.DataStore.load = orig_load

    print(f"[positive control] {result}")
    assert result["status"] == "ok"
    assert result["real_best_lag"] == 6, f"FAILED: expected lag 6, got {result['real_best_lag']}"
    assert result["corr_perm_pvalue"] < 0.05, (
        f"FAILED: planted-lag pair not significant after correction: "
        f"corr_perm_pvalue={result['corr_perm_pvalue']}"
    )
    assert result["eg_perm_pvalue"] is not None and result["eg_perm_pvalue"] < 0.05, (
        f"FAILED: planted-lag pair's EG result not significant after correction: "
        f"eg_perm_pvalue={result['eg_perm_pvalue']}"
    )
    print("PASS: genuine lagged relationship survives the look-elsewhere correction.\n")

    # --- False-positive calibration ---
    M = 24
    n_reject = 0
    pvals = []
    for trial in range(M):
        df_a, df_b = build_independent_pair(seed=1000 + trial)

        def fake_load_indep(symbol, tf_label, _a=df_a, _b=df_b):
            return {"A": _a, "B": _b}.get(symbol)

        data.DataStore.load = staticmethod(fake_load_indep)
        try:
            r = run_test("A", "B", "1m", max_lag=10, n_perm=200, seed=2000 + trial, run_eg=False)
        finally:
            data.DataStore.load = orig_load

        if r["status"] == "ok" and r["corr_perm_pvalue"] is not None:
            pvals.append(r["corr_perm_pvalue"])
            if r["corr_perm_pvalue"] < 0.05:
                n_reject += 1

    rate = n_reject / len(pvals) if pvals else float("nan")
    print(f"[calibration] {n_reject}/{len(pvals)} independent random-walk pairs "
          f"falsely rejected at p<0.05 (rate={rate:.3f}, nominal=0.05)")
    assert n_reject < 6, (
        f"FAILED: false-positive rate too high after correction: {n_reject}/{len(pvals)} "
        f"(rate={rate:.3f}) — the look-elsewhere correction is not working as intended."
    )
    print("PASS: false-positive rate on unrelated pairs stays near nominal — "
          "the correction is doing its job, not just adding noise.")

    print("\nALL CHECKS PASSED.")


if __name__ == "__main__":
    main()
