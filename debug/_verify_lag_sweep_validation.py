"""
Synthetic verification for research/lag_sweep_validation.py (task #52,
2026-07-13), run BEFORE trusting the real-data sweep.

Design note, learned from an already-documented pitfall in this project
(research/lag_aware_cointegration_discovery.py's docstring, "first design
attempt genuinely failed"): a synthetic pair built by shifting a copy of a
shared random walk does NOT show cointegration present-only-at-the-true-lag
and absent-elsewhere. W[t]-W[t-k] is itself a stationary (fixed-variance)
process for ANY fixed k, so EVERY nearby lag shows SOME apparent
correlation/cointegration, just weaker (higher EG p-value, lower |corr|)
than the true lag. The correct assertion is therefore "the true lag is the
ARGMAX/peak" (sharpest signal), not "the true lag is the only lag with any
signal" — this test asserts the former, matching what
research/lag_sweep_validation.py's sweep_diagnostics() actually measures
(argmax_abs_corr_lag), not a stricter claim the underlying statistics
cannot support.

Construction: log_price_A is a random walk (small per-step vol). B is A's
level, lagged by a known k0, plus INDEPENDENT stationary (i.i.d., not
cumulative) noise with smaller variance than A's per-step vol — this makes
the off-true-lag spread variance grow quickly with |lag-k0| (since it picks
up |lag-k0| full steps of A's own random walk), giving a sharp, well-defined
peak at k0 rather than a flat/ambiguous one.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from data import _gap_aware_returns
from lead_lag_scan import _gap_masked_log_price
from lag_sweep_validation import full_lag_sweep, sweep_diagnostics


def _make_synthetic_pair(n, k0, sigma_a, sigma_noise, seed):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    innovations_a = rng.normal(0, sigma_a, n)
    log_price_a = 4.5 + np.cumsum(innovations_a)  # ~ log($90) base
    noise = rng.normal(0, sigma_noise, n)
    log_price_b = np.empty(n)
    for t in range(n):
        src = min(max(t - k0, 0), n - 1)
        log_price_b[t] = log_price_a[src] + noise[t]
    df_a = pd.DataFrame({"close": np.exp(log_price_a)}, index=idx)
    df_b = pd.DataFrame({"close": np.exp(log_price_b)}, index=idx)
    return df_a, df_b


def _sweep_pair(df_a, df_b, max_lag, max_eg_lag=5):
    ret_a = pd.Series(_gap_aware_returns(df_a), index=df_a.index)
    ret_b = pd.Series(_gap_aware_returns(df_b), index=df_b.index)
    logp_a = pd.Series(_gap_masked_log_price(df_a), index=df_a.index)
    logp_b = pd.Series(_gap_masked_log_price(df_b), index=df_b.index)
    sweep_df = full_lag_sweep(ret_a, ret_b, logp_a, logp_b, max_lag, max_eg_lag)
    diag = sweep_diagnostics(sweep_df)
    return sweep_df, diag


def main():
    failures = []

    # Case 1: known true lag k0=5, A leads B by 5 bars. argmax |corr| and
    # min EG p-value should both land at lag=+5 (matching lagged_corr_scan's
    # documented convention: lag>0 means A leads B by `lag` bars).
    k0 = 5
    df_a, df_b = _make_synthetic_pair(n=600, k0=k0, sigma_a=0.010, sigma_noise=0.003, seed=1)
    sweep_df, diag = _sweep_pair(df_a, df_b, max_lag=20)
    print(f"Case 1 (true lag={k0}): argmax_lag={diag['argmax_abs_corr_lag']}, "
          f"argmax_corr={diag['argmax_corr']:.4f}, eg_p@0={diag['eg_p_at_lag0']}")
    eg_valid = sweep_df.dropna(subset=["eg_p"])
    min_eg_row = eg_valid.loc[eg_valid["eg_p"].idxmin()] if not eg_valid.empty else None
    if min_eg_row is not None:
        print(f"  min EG p-value {min_eg_row['eg_p']:.6g} at lag={int(min_eg_row['lag'])}")
    if diag["argmax_abs_corr_lag"] != k0:
        failures.append(f"Case 1: expected argmax_abs_corr_lag={k0}, got {diag['argmax_abs_corr_lag']}")
    if min_eg_row is None or int(min_eg_row["lag"]) != k0:
        failures.append(f"Case 1: expected EG p-value minimized at lag={k0}, "
                         f"got {int(min_eg_row['lag']) if min_eg_row is not None else 'no valid EG'}")
    # Sharpness check: the true-lag EG p-value should be much smaller than
    # at a lag 10+ away from k0 (the "peak, not present/absent" property).
    far_row = eg_valid[eg_valid["lag"] == (k0 + 12 if k0 + 12 <= 20 else k0 - 12)]
    if min_eg_row is not None and not far_row.empty:
        far_p = float(far_row["eg_p"].iloc[0])
        print(f"  EG p-value at a far lag ({int(far_row['lag'].iloc[0])}): {far_p:.4g} "
              f"(should be >> min_eg_p={min_eg_row['eg_p']:.4g})")
        if not (far_p > min_eg_row["eg_p"] * 5 or far_p > 0.05):
            failures.append(f"Case 1: far-lag EG p-value ({far_p:.4g}) not meaningfully "
                             f"larger than true-lag EG p-value ({min_eg_row['eg_p']:.4g})")

    # Case 2: negative control -- k0=0 (contemporaneous, no true lag).
    # argmax should land at/near lag=0.
    df_a2, df_b2 = _make_synthetic_pair(n=600, k0=0, sigma_a=0.010, sigma_noise=0.003, seed=2)
    sweep_df2, diag2 = _sweep_pair(df_a2, df_b2, max_lag=20)
    print(f"Case 2 (true lag=0): argmax_lag={diag2['argmax_abs_corr_lag']}, "
          f"near_zero_is_peak={diag2['near_zero_is_peak']}")
    if diag2["argmax_abs_corr_lag"] != 0:
        failures.append(f"Case 2: expected argmax_abs_corr_lag=0, got {diag2['argmax_abs_corr_lag']}")
    if not diag2["near_zero_is_peak"]:
        failures.append("Case 2: expected near_zero_is_peak=True for a true lag-0 pair")

    # Case 3: negative-lag case -- B leads A by 7 bars (k0=-7 in the
    # A-leads-B convention). Confirms the sweep correctly detects the
    # OTHER direction, not just positive lags.
    k0_neg = -7
    df_a3, df_b3 = _make_synthetic_pair(n=600, k0=k0_neg, sigma_a=0.010, sigma_noise=0.003, seed=3)
    sweep_df3, diag3 = _sweep_pair(df_a3, df_b3, max_lag=20)
    print(f"Case 3 (true lag={k0_neg}, B leads A): argmax_lag={diag3['argmax_abs_corr_lag']}")
    if diag3["argmax_abs_corr_lag"] != k0_neg:
        failures.append(f"Case 3: expected argmax_abs_corr_lag={k0_neg}, got {diag3['argmax_abs_corr_lag']}")

    # Case 4: two fully independent random walks -- no shared structure at
    # all. argmax should NOT reliably land at any particular lag and
    # correlation magnitude should be modest (not the near-1.0 seen with a
    # real shared true-lag signal). This is a coarse sanity check, not a
    # strict assertion, since pure chance can occasionally produce a
    # moderate spurious correlation at some lag with finite N.
    rng4 = np.random.default_rng(4)
    idx4 = pd.date_range("2024-01-01", periods=600, freq="h")
    log_price_a4 = 4.5 + np.cumsum(rng4.normal(0, 0.01, 600))
    log_price_b4 = 4.5 + np.cumsum(rng4.normal(0, 0.01, 600))
    df_a4 = pd.DataFrame({"close": np.exp(log_price_a4)}, index=idx4)
    df_b4 = pd.DataFrame({"close": np.exp(log_price_b4)}, index=idx4)
    sweep_df4, diag4 = _sweep_pair(df_a4, df_b4, max_lag=20)
    print(f"Case 4 (independent random walks): argmax_lag={diag4['argmax_abs_corr_lag']}, "
          f"argmax_corr={diag4['argmax_corr']:.4f} (expect modest, not near 1.0 like Case 1's "
          f"peak)")
    if abs(diag4["argmax_corr"]) > 0.9:
        failures.append(f"Case 4: independent-walk argmax |corr| unexpectedly high "
                         f"({diag4['argmax_corr']:.4f}) -- possible bug inflating spurious correlation")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All 4 synthetic cases passed.")


if __name__ == "__main__":
    main()
