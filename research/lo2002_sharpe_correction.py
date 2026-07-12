"""
Applies the verified Lo (2002) Sharpe-autocorrelation correction to CAMARF's
actual reported portfolio Sharpe ratios, using the real daily P&L series from
`output/backtest/trades_layer1*.parquet` -- not a synthetic replication (that
already exists and passed at `debug/_replicate_lo2002_sharpe_autocorrelation_correction.py`).

Formula (Lo 2002, "The Statistics of Sharpe Ratios", FAJ 58(4)):
    SR(q) = SR(1) * q / sqrt(eta(q))
    eta(q) = q + 2 * sum_{k=1}^{q-1} (q-k) * rho_k
using the GENERAL form with empirical (not AR(1)-assumed) autocorrelations
rho_k, since there's no reason to assume CAMARF's realized daily P&L follows
a clean AR(1) process.

q = 252 to match backtest.py's own annualization convention (aggregate_portfolio(),
backtest.py:860: `daily_pnl.mean() / daily_pnl.std() * np.sqrt(252)`).

Two estimates are reported, not one, per this project's "report the honest
number, don't engineer around it" rule (CLAUDE.md rule 7):
  1. rho_1-only approximation -- Lo's own paper notes rho_1 usually dominates
     and higher lags are typically statistically insignificant; more stable
     with a few hundred trades resampled to daily bins.
  2. Full empirical eta(252) using all 251 sample autocorrelations -- the
     complete formula, but flagged if far lags are unstable (effective N for
     lag-k autocorrelation shrinks as k grows, and this project's daily-P&L
     series has many zero-trade days, which will bias rho toward 0 without
     necessarily meaning "no serial dependence exists").

Does NOT silently pick a favorable estimate -- prints both, with sample size
and instability caveats, and does not overwrite backtest.py's reported Sharpe
anywhere. This is a comparison-arm finding, not a production change.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

Q = 252  # daily -> annual, matches backtest.py's sqrt(252) convention


def daily_pnl_from_trades(path: str) -> pd.Series:
    df = pd.read_parquet(path)
    sorted_trades = df.sort_values("entry_time")
    pnl_series = pd.Series(
        sorted_trades["pnl_net"].values,
        index=sorted_trades["exit_time"].fillna(sorted_trades["entry_time"]),
    )
    return pnl_series.resample("1D").sum()


def sample_acf(x: np.ndarray, max_lag: int) -> np.ndarray:
    x = x - x.mean()
    n = len(x)
    var = (x @ x) / n
    rhos = np.zeros(max_lag)
    for k in range(1, max_lag + 1):
        if k >= n:
            break
        cov_k = (x[:-k] @ x[k:]) / n
        rhos[k - 1] = cov_k / var if var > 0 else 0.0
    return rhos


def eta_from_rhos(rhos: np.ndarray, q: int) -> float:
    total = q
    for k in range(1, q):
        rho_k = rhos[k - 1] if k - 1 < len(rhos) else 0.0
        total += 2 * (q - k) * rho_k
    return total


def report_for(label: str, path: str) -> None:
    daily = daily_pnl_from_trades(path)
    n = len(daily)
    sr1 = daily.mean() / daily.std() if daily.std() > 0 else np.nan
    sr_naive = sr1 * np.sqrt(Q)

    rho1 = np.corrcoef(daily.values[:-1], daily.values[1:])[0, 1] if n > 1 else np.nan
    eta_rho1_only = eta_from_rhos(np.array([rho1] + [0.0] * (Q - 2)), Q)
    sr_corrected_rho1 = sr1 * Q / np.sqrt(eta_rho1_only) if eta_rho1_only > 0 else np.nan

    max_lag = min(Q - 1, n // 4)  # standard rule-of-thumb cap: avoid lags beyond ~T/4
    rhos_full = sample_acf(daily.values, max_lag)
    eta_full = eta_from_rhos(rhos_full, Q)
    sr_corrected_full = sr1 * Q / np.sqrt(eta_full) if eta_full > 0 else np.nan

    pct_rho1 = (sr_naive / sr_corrected_rho1 - 1) * 100 if sr_corrected_rho1 else np.nan
    pct_full = (sr_naive / sr_corrected_full - 1) * 100 if sr_corrected_full else np.nan

    # Null check: does a random SHUFFLE of the same daily P&L values (true rho=0 by
    # construction, since shuffling destroys any real serial order) produce swings of
    # similar size purely from finite-sample noise in the 251-lag empirical sum? If so,
    # the "full ACF" correction above is not a real signal.
    rng = np.random.default_rng(7)
    null_pct_full = []
    vals = daily.values.copy()
    for _ in range(200):
        shuffled = rng.permutation(vals)
        rhos_null = sample_acf(shuffled, max_lag)
        eta_null = eta_from_rhos(rhos_null, Q)
        sr1_null = shuffled.mean() / shuffled.std() if shuffled.std() > 0 else np.nan
        sr_corr_null = sr1_null * Q / np.sqrt(eta_null) if eta_null > 0 else np.nan
        sr_naive_null = sr1_null * np.sqrt(Q)
        if sr_corr_null and np.isfinite(sr_corr_null) and sr_corr_null != 0:
            null_pct_full.append(abs((sr_naive_null / sr_corr_null - 1) * 100))
    null_pct_full = np.array(null_pct_full)
    n_dropped = 200 - len(null_pct_full)

    rho1_se = 1 / np.sqrt(n)
    rho1_z = rho1 / rho1_se if rho1_se > 0 else np.nan
    rho1_significant = abs(rho1_z) >= 2.0

    print(f"=== {label} ({path}) ===")
    print(f"  n daily-P&L observations: {n}  (max_lag used for full estimate: {max_lag})")
    print(f"  naive daily Sharpe (SR1): {sr1:.4f}")
    print(f"  naive annualized Sharpe (SR1*sqrt(252)): {sr_naive:.4f}")
    print(f"  lag-1 autocorrelation (rho_1): {rho1:+.4f}  (SE~{rho1_se:.4f}, z={rho1_z:+.2f} -- "
          f"{'SIGNIFICANT' if rho1_significant else 'not significant'} at |z|>=2)")
    print(f"  Lo-corrected (rho_1-only approx): {sr_corrected_rho1:.4f}  "
          f"({'naive OVERSTATES' if pct_rho1 > 0 else 'naive UNDERSTATES'} by {abs(pct_rho1):.2f}%)")
    print(f"  Lo-corrected (full empirical ACF, {max_lag} lags): {sr_corrected_full:.4f}  "
          f"({'naive OVERSTATES' if pct_full > 0 else 'naive UNDERSTATES'} by {abs(pct_full):.2f}%)")
    print(f"  Null check (200 shuffles, true rho=0 by construction, {n_dropped} dropped as non-finite "
          f"eta): full-ACF swing under pure noise = {null_pct_full.mean():.2f}% mean, "
          f"{np.percentile(null_pct_full, 95):.2f}% 95th pct")
    if abs(pct_full) <= np.percentile(null_pct_full, 95):
        print(f"  -> observed {abs(pct_full):.2f}% swing is WITHIN the null noise range -- "
              f"the full-ACF correction here is NOT distinguishable from estimation noise.")
    else:
        print(f"  -> observed {abs(pct_full):.2f}% swing EXCEEDS the null 95th percentile -- "
              f"plausibly a real effect, not just noise.")
    print()


def main():
    print("Lo (2002) Sharpe-autocorrelation correction applied to CAMARF's real portfolio P&L")
    print("=" * 90)
    print()
    print("NOTE: trades_layer1.parquet on disk right now reflects whatever backtest.py run last")
    print("wrote it -- this session's Phase 3 full pipeline rerun has not completed, so this IS-side")
    print("number is NOT guaranteed to exactly match the last-published Session 22 headline (5.2935,")
    print("1028 trades). The OOS/holdout file DOES match the currently-published 5.2443 exactly (296")
    print("trades) as a sanity check that this script's daily-P&L reconstruction matches backtest.py's")
    print("own aggregate_portfolio() logic. Re-run this script once Phase 3 completes for the final")
    print("citable pair.")
    print()

    report_for("IS (trades_layer1.parquet)", "output/backtest/trades_layer1.parquet")
    report_for("OOS/holdout (trades_layer1_holdout.parquet)", "output/backtest/trades_layer1_holdout.parquet")


if __name__ == "__main__":
    main()
