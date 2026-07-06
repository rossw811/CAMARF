"""
CAMARF grid_bootstrap_ar_ci.py — comparison/diagnostic method, NOT part of
the production pipeline.

Hansen (1999), "The Grid Bootstrap and the Autoregressive Model," Review
of Economics and Statistics 81(4) — standard bootstrap confidence
intervals for an AR(1) coefficient are known to be unreliable near a unit
root (exactly CAMARF's regime: a slowly mean-reverting spread has an AR
coefficient close to 1). The grid bootstrap inverts a bootstrap test over
a grid of candidate null coefficients instead of bootstrapping the point
estimate directly, and stays first-order correct even near unit root.
Gives a genuine confidence interval (not just reject/fail-to-reject) for
each confirmed pair's own spread mean-reversion AR coefficient — most
informative exactly where a pair's persistence sits closest to the
random-walk boundary.

Method: for a candidate rho0 on a grid around the point estimate,
1. Fit z_t = c_hat0 + rho0*z_{t-1} + e_t^0 with rho0 FIXED (only c is
   re-estimated) to get the null-restricted residuals.
2. Bootstrap (i.i.d. resample of these residuals — a block bootstrap would
   better handle residual autocorrelation but adds real complexity; flagged
   here as a simplification, not silently assumed away) B synthetic series
   under rho0, refit UNRESTRICTED OLS on each to get a bootstrap t-stat
   for testing H0: rho=rho0.
3. rho0 is included in the (1-alpha) confidence set if the REAL data's own
   t-stat for testing rho=rho0 falls within the middle (1-alpha) of that
   bootstrap distribution.
The confidence interval is the full set of grid points not rejected.

Read-only. Excludes DATA_GAP-flagged padding on both legs.

Usage:
    python research/grid_bootstrap_ar_ci.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # for aligned_pair_loader

from aligned_pair_loader import (
    TF_DIRS as _TF_DIRS,
    DIR_TO_LABEL as _DIR_TO_LABEL,
    resolve_tf_results_dir as _resolve_tf_results_dir,
)


def _ols_ar1(z_lag, z_t):
    n = z_lag.size
    X = np.column_stack([np.ones(n), z_lag])
    coef, _r, _rk, _sv = np.linalg.lstsq(X, z_t, rcond=None)
    fitted = X @ coef
    resid = z_t - fitted
    se_rho = np.sqrt(np.sum(resid ** 2) / (n - 2) * np.linalg.inv(X.T @ X)[1, 1])
    return float(coef[0]), float(coef[1]), resid, float(se_rho)


def grid_bootstrap_ci(z, n_grid=60, n_boot=200, conf_level=0.90, rng=None, grid_halfwidth=0.15):
    """
    z: 1-D array, real bars only. Returns the confidence set of rho values
    (as [lo, hi] bounds of the grid points not rejected) plus the point
    estimate for comparison.
    """
    if rng is None:
        rng = np.random.default_rng(0)
    z = np.asarray(z, dtype=float)
    z_lag, z_t = z[:-1], z[1:]
    n = z_lag.size
    if n < 100:
        return {"ok": False, "error": "insufficient_obs"}

    c_hat, rho_hat, resid_hat, se_hat = _ols_ar1(z_lag, z_t)
    grid = np.linspace(max(rho_hat - grid_halfwidth, -0.999), min(rho_hat + grid_halfwidth, 0.999), n_grid)
    alpha = 1 - conf_level

    included = []
    for rho0 in grid:
        # Step 1: null-restricted fit (rho0 fixed, only intercept re-estimated)
        c0 = float(np.mean(z_t - rho0 * z_lag))
        resid0 = z_t - c0 - rho0 * z_lag

        # Real data's own t-stat for testing rho=rho0 (using the UNRESTRICTED fit's SE)
        t_real = (rho_hat - rho0) / se_hat

        boot_t = np.empty(n_boot)
        for b in range(n_boot):
            resampled = rng.choice(resid0, size=n, replace=True)
            z_boot = np.empty(n)
            z_boot[0] = z_lag[0]
            for t in range(1, n):
                z_boot[t] = c0 + rho0 * z_boot[t - 1] + resampled[t]
            zb_lag, zb_t = z_boot[:-1], z_boot[1:]
            if zb_lag.size < 20:
                boot_t[b] = 0.0
                continue
            _cb, rho_b, _resb, se_b = _ols_ar1(zb_lag, zb_t)
            boot_t[b] = (rho_b - rho0) / se_b if se_b > 0 else 0.0

        lo_q, hi_q = np.quantile(boot_t, [alpha / 2, 1 - alpha / 2])
        if lo_q <= t_real <= hi_q:
            included.append(rho0)

    if not included:
        return {"ok": True, "rho_hat": rho_hat, "ci_lo": np.nan, "ci_hi": np.nan,
                "n_obs": int(n), "note": "empty_confidence_set_widen_grid"}
    return {
        "ok": True, "rho_hat": rho_hat, "ci_lo": float(min(included)),
        "ci_hi": float(max(included)), "n_obs": int(n),
    }


def main():
    rng = np.random.default_rng(0)
    rows = []
    for tf_dir in _TF_DIRS:
        results_dir, is_stale = _resolve_tf_results_dir(tf_dir)
        pairs_path = os.path.join(results_dir, "pairs.parquet")
        if not os.path.exists(pairs_path):
            continue
        if is_stale:
            print(f"NOTE {tf_dir}: using archived {results_dir}")
        tf_label = _DIR_TO_LABEL[tf_dir]
        pairs_df = pd.read_parquet(pairs_path)
        for _, row in pairs_df.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            series_path = os.path.join(results_dir, f"spread_series_{sym_a}_{sym_b}.parquet")
            if not os.path.exists(series_path):
                continue
            df = pd.read_parquet(series_path)
            real_mask = (df["gap_flag_a"] != 4) & (df["gap_flag_b"] != 4)
            z = df.loc[real_mask, "spread"].to_numpy(dtype=float)
            z = z[np.isfinite(z)]
            r = grid_bootstrap_ci(z, n_grid=40, n_boot=100, rng=rng)
            r.update({"symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf_label})
            rows.append(r)
            if r["ok"] and np.isfinite(r.get("ci_lo", np.nan)):
                print(f"{sym_a}/{sym_b}@{tf_label}: rho_hat={r['rho_hat']:.4f} "
                      f"90% CI=[{r['ci_lo']:.4f}, {r['ci_hi']:.4f}]")

    out_df = pd.DataFrame(rows)
    os.makedirs("output/research", exist_ok=True)
    out_df.to_parquet("output/research/grid_bootstrap_ar_ci.parquet")
    ok = out_df[out_df.get("ok", False) == True] if "ok" in out_df.columns else pd.DataFrame()
    print(f"\nWrote output/research/grid_bootstrap_ar_ci.parquet: {len(ok)} pairs")


if __name__ == "__main__":
    main()
