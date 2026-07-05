"""
Synthetic verification of compute_hrp_weights()'s new `shrinkage` parameter
before trusting it on real trade data. Complements
debug/_verify_hrp_weights.py, which only covers the underlying HRP
building blocks and is unaffected by this change.

Case 1 (regression safety): shrinkage="none" must reproduce exactly the
same weights as calling compute_hrp_weights() with no shrinkage argument
at all — the new parameter must not have altered prior behavior.

Case 2: on a small, high-noise synthetic sample (few days, real but weak
underlying correlation), Ledoit-Wolf shrinkage should measurably reduce
the estimated off-diagonal correlation magnitude relative to the raw
sample correlation — the entire point of shrinking toward a zero-
correlation identity target under estimation-error-prone conditions.

Case 3: on a LARGE synthetic sample (many days), shrinkage should matter
much less (the raw sample correlation is already reliable with enough
data) — confirms the shrinkage intensity responds to sample size/noise
rather than being a fixed, arbitrary discount.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from sklearn.covariance import ledoit_wolf

from backtest import compute_hrp_weights

failures = []


def _shrinkage_effect(trades_df, pair_keys):
    """Direct check on the actual mechanism (correlation shrinkage toward
    zero), independent of HRP's downstream nonlinear clustering response —
    testing HRP's resulting weight RANGE as a proxy for "did shrinkage
    work" turned out to be unreliable (HRP's hierarchical clustering does
    not respond to a shrunk correlation matrix in a simple monotonic way,
    confirmed by running it: shrinkage widened the weight range on one
    genuinely-equicorrelated synthetic case). This checks the actual
    mechanism directly instead: does sklearn's ledoit_wolf() correlation
    output have smaller-magnitude off-diagonal entries than the raw sample
    correlation, and what shrinkage coefficient did it choose."""
    daily = trades_df.copy()
    daily["exit_date"] = pd.to_datetime(daily["exit_time"]).dt.date
    daily["pair_key"] = daily["symbol_a"] + "/" + daily["symbol_b"]
    wide = daily.groupby(["pair_key", "exit_date"])["pnl_net"].sum().unstack("pair_key")
    filled = wide[pair_keys].fillna(0.0).to_numpy()
    raw_corr = np.corrcoef(filled.T)
    shrunk_cov, coef = ledoit_wolf(filled)
    row_std = np.sqrt(np.diag(shrunk_cov))
    shrunk_corr = shrunk_cov / np.outer(row_std, row_std)
    n = raw_corr.shape[0]
    off_diag_mask = ~np.eye(n, dtype=bool)
    raw_mag = np.mean(np.abs(raw_corr[off_diag_mask]))
    shrunk_mag = np.mean(np.abs(shrunk_corr[off_diag_mask]))
    return raw_mag, shrunk_mag, coef


def _make_synthetic_trades(n_pairs, n_days, true_corr, seed):
    """One trade per pair per day (dense — avoids the sparse-trading
    complications of real data, since this test targets the shrinkage
    behavior specifically, not the pairwise-complete-correlation handling
    already covered elsewhere)."""
    rng = np.random.default_rng(seed)
    chol = np.linalg.cholesky(true_corr)
    pnl = rng.standard_normal((n_days, n_pairs)) @ chol.T
    rows = []
    dates = pd.date_range("2025-01-01", periods=n_days, freq="D")
    for i in range(n_pairs):
        for d in range(n_days):
            rows.append({
                "symbol_a": f"P{i}", "symbol_b": "X",
                "exit_time": dates[d], "pnl_net": float(pnl[d, i]),
            })
    return pd.DataFrame(rows)


n_pairs = 5
true_rho = 0.4
true_corr = np.full((n_pairs, n_pairs), true_rho)
np.fill_diagonal(true_corr, 1.0)

with tempfile.TemporaryDirectory() as tmpdir:
    # --- Case 1: regression safety, small sample, explicit "none" vs default ---
    trades_small = _make_synthetic_trades(n_pairs, 40, true_corr, seed=1)
    path_small = os.path.join(tmpdir, "trades_small.parquet")
    trades_small.to_parquet(path_small)

    w_default = compute_hrp_weights(path_small)
    w_explicit_none = compute_hrp_weights(path_small, shrinkage="none")
    if w_default != w_explicit_none:
        failures.append(
            f"Case 1: shrinkage='none' should exactly reproduce default behavior. "
            f"default={w_default} vs explicit_none={w_explicit_none}"
        )
    else:
        print(f"Case 1 (regression safety): PASS — default and shrinkage='none' identical")

    # --- Case 2: small/noisy sample — shrinkage should pull the mean
    # |off-diagonal correlation| toward zero, and report a nonzero
    # shrinkage coefficient (there IS real estimation noise to correct at
    # n_days=40 for 5 pairs).
    pair_keys_small = [f"P{i}/X" for i in range(n_pairs)]
    raw_mag_small, shrunk_mag_small, coef_small = _shrinkage_effect(trades_small, pair_keys_small)
    print(f"Case 2 (small sample, n_days=40): mean|off-diag corr| "
          f"raw={raw_mag_small:.4f} -> shrunk={shrunk_mag_small:.4f}, "
          f"shrinkage coefficient={coef_small:.4f}")
    if shrunk_mag_small >= raw_mag_small:
        failures.append(
            f"Case 2: expected shrinkage to REDUCE mean |off-diagonal correlation| "
            f"on a small, noisy sample: raw={raw_mag_small:.4f} vs shrunk={shrunk_mag_small:.4f}"
        )
    if coef_small <= 0.01:
        failures.append(
            f"Case 2: expected a meaningfully nonzero shrinkage coefficient on a "
            f"40-day, 5-pair sample (real estimation noise should be present), "
            f"got {coef_small:.4f}"
        )

    # Also confirm compute_hrp_weights runs end-to-end with shrinkage="ledoit_wolf"
    # without error and returns a complete, sane weight dict (sums/ranges checked
    # generically — NOT asserting a specific direction on the resulting HRP
    # weights themselves, since that depends on HRP's own nonlinear clustering
    # response to the changed correlation structure, not just the shrinkage
    # mechanism tested directly above).
    w_lw_small = compute_hrp_weights(path_small, shrinkage="ledoit_wolf")
    if not w_lw_small or set(w_lw_small.keys()) != set(pair_keys_small):
        failures.append(f"Case 2: compute_hrp_weights(shrinkage='ledoit_wolf') returned "
                        f"an incomplete/empty result: {w_lw_small}")
    elif any(not np.isfinite(v) or v <= 0 for v in w_lw_small.values()):
        failures.append(f"Case 2: compute_hrp_weights(shrinkage='ledoit_wolf') returned "
                        f"non-finite or non-positive multipliers: {w_lw_small}")

    # --- Case 3: large sample — shrinkage coefficient should be much smaller ---
    trades_large = _make_synthetic_trades(n_pairs, 2000, true_corr, seed=2)
    path_large = os.path.join(tmpdir, "trades_large.parquet")
    trades_large.to_parquet(path_large)
    raw_mag_large, shrunk_mag_large, coef_large = _shrinkage_effect(trades_large, pair_keys_small)
    print(f"Case 3 (large sample, n_days=2000): mean|off-diag corr| "
          f"raw={raw_mag_large:.4f} -> shrunk={shrunk_mag_large:.4f}, "
          f"shrinkage coefficient={coef_large:.4f} (should be well below the "
          f"small-sample coefficient of {coef_small:.4f} — more data needs less shrinkage)")
    if coef_large >= coef_small:
        failures.append(
            f"Case 3: shrinkage coefficient should DECREASE with more data — "
            f"small-sample={coef_small:.4f}, large-sample={coef_large:.4f}"
        )

if failures:
    print("\nFAILURES:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
