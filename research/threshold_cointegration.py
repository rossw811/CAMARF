"""
CAMARF threshold_cointegration.py — comparison/diagnostic method, NOT part
of the production pipeline.

Hansen & Seo (2002), "Testing for two-regime threshold cointegration in
vector error-correction models," Journal of Econometrics 110(2), 293-318 —
tests whether a pair's error-correction adjustment is genuinely nonlinear
(threshold-triggered, switching reversion speed at some equilibrium-error
size) rather than the constant-speed linear reversion the production
OU/EG pipeline assumes throughout. Economically motivated by transaction-
cost/liquidity bands: a spread may barely move (or random-walk) while
inside a band no one will pay to arbitrage away, then revert quickly once
it's wide enough to be worth trading.

Method actually implemented here (practical grid-search + fixed-regressor
wild bootstrap, not a literal re-derivation of Hansen-Seo's own asymptotic
sup-Wald theory — flagged explicitly so this isn't mistaken for an exact
reproduction of their paper):
  1. Take a confirmed pair's already-computed, gap-masked spread series
     (spread_series_*.parquet's "spread" column — the identical series
     backtest.py trades, not a recomputed one).
  2. Linear null: Δspread_t = c + alpha*spread_{t-1} + eps_t (single-regime
     AR(1) error-correction, the production model's implicit assumption).
  3. Grid-search threshold gamma over the middle (1 - 2*trim) of the
     empirical spread_{t-1} distribution (default 15% trim each tail, the
     standard Hansen convention keeping enough observations per regime);
     for each gamma, fit Δspread_t = c_i + alpha_i*spread_{t-1} + eps_t
     separately in regime 1 (spread_{t-1} <= gamma) and regime 2
     (spread_{t-1} > gamma), sum both regimes' SSR. gamma* minimizes total
     SSR (concentrated least squares — this part IS Hansen-Seo's actual
     point estimator for gamma).
  4. F-type improvement statistic comparing linear-null SSR to the
     threshold model's SSR at gamma*.
  5. gamma is a nuisance parameter unidentified under the linear null
     (Davies' problem — the same identification issue the sup-Wald/sup-LM
     tests and Andrews & Ploberger (1994) theory already used elsewhere in
     this project's research formalize), so the F-stat's null distribution
     is NOT a standard F or chi-square. A wild (Rademacher) bootstrap
     under the fitted linear null is used instead: resample the null
     model's own residuals with random +/-1 signs, rebuild a bootstrap
     Δspread series, rerun the identical grid search, record each
     replicate's own best F. The reported p-value is the fraction of
     bootstrap best-F values at least as large as the real one.
  6. Reports gamma* (spread level and percentile), alpha_inside/outside,
     and whether outside-regime reversion is faster in magnitude — the
     economically expected direction under a transaction-cost-band story.

Read-only. Loads spread_series_*.parquet directly — never fetches, never
recomputes hedge ratios or spreads. IMPORTANT: spread_series_*.parquet is
persisted on the full calendar-padded grid, not a compacted real-bars-only
series — rows are still finite (forward-filled) wherever gap_flag_a/
gap_flag_b == GapFlag.DATA_GAP (4), so `np.isfinite` alone does NOT remove
them. This is the exact calendar-padding artifact PAPER.md Section 4.5
documents and analysis.py's own CointScanner already excludes via
`clean_close(df, exclude_flags=(GapFlag.DATA_GAP,))` — this module applies
the identical exclusion (gap_flag_a != 4 AND gap_flag_b != 4) before any
computation, confirmed necessary by direct inspection (AMD/DD@1h: 25,730
total rows, only 4,397 with gap_flag==0 — 83% padding).

Usage:
    python research/threshold_cointegration.py --n-boot 500 --trim 0.15
"""
import argparse
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


def _ols_ssr(z_lag, dz):
    """SSR of Δz = c + alpha*z_lag over the given (already-masked) sample."""
    n = z_lag.size
    if n < 5:
        return np.inf, np.nan, np.nan
    X = np.column_stack([np.ones(n), z_lag])
    coef, _resid, _rank, _sv = np.linalg.lstsq(X, dz, rcond=None)
    fitted = X @ coef
    resid = dz - fitted
    ssr = float(np.dot(resid, resid))
    return ssr, float(coef[1]), float(coef[0])  # ssr, alpha, c


def _threshold_grid_search(z_lag, dz, trim=0.15, n_grid=100):
    """Grid-search gamma minimizing total two-regime SSR. Returns dict with
    gamma, ssr_threshold, alpha1 (z_lag<=gamma), alpha2 (z_lag>gamma), and
    the regime split used (for diagnostics / re-use inside the bootstrap)."""
    lo, hi = np.quantile(z_lag, [trim, 1 - trim])
    candidates = np.linspace(lo, hi, n_grid)
    best = {"ssr": np.inf, "gamma": np.nan, "alpha1": np.nan, "alpha2": np.nan,
            "c1": np.nan, "c2": np.nan}
    min_regime_n = max(10, int(0.05 * z_lag.size))
    for gamma in candidates:
        mask1 = z_lag <= gamma
        mask2 = ~mask1
        if mask1.sum() < min_regime_n or mask2.sum() < min_regime_n:
            continue
        ssr1, a1, c1 = _ols_ssr(z_lag[mask1], dz[mask1])
        ssr2, a2, c2 = _ols_ssr(z_lag[mask2], dz[mask2])
        total = ssr1 + ssr2
        if total < best["ssr"]:
            best = {"ssr": total, "gamma": float(gamma),
                     "alpha1": a1, "alpha2": a2, "c1": c1, "c2": c2}
    return best


def threshold_coint_test(spread, trim=0.15, n_grid=100, n_boot=500, rng=None):
    """
    Full test on one pair's spread series. `spread` must already be a clean
    (NaN-free, gap-masked) 1-D array in chronological order.

    Returns a dict: gamma, gamma_percentile, alpha_linear, alpha_inside,
    alpha_outside, ssr_linear, ssr_threshold, f_stat, boot_pvalue, n_obs.
    """
    if rng is None:
        rng = np.random.default_rng(0)
    spread = np.asarray(spread, dtype=float)
    z_lag = spread[:-1]
    dz = np.diff(spread)
    n = z_lag.size
    if n < 60:
        return {"ok": False, "error": "insufficient_obs", "n_obs": int(n)}

    ssr_linear, alpha_linear, c_linear = _ols_ssr(z_lag, dz)
    best = _threshold_grid_search(z_lag, dz, trim=trim, n_grid=n_grid)
    if not np.isfinite(best["ssr"]):
        return {"ok": False, "error": "no_valid_threshold_split", "n_obs": int(n)}

    ssr_threshold = best["ssr"]
    # F-type improvement statistic (2 extra free parameters: alpha2, c2)
    df_denom = max(n - 4, 1)
    f_stat = ((ssr_linear - ssr_threshold) / 2) / (ssr_threshold / df_denom)

    # Wild (Rademacher) bootstrap under the fitted LINEAR null.
    fitted_null = c_linear + alpha_linear * z_lag
    resid_null = dz - fitted_null
    boot_f = np.empty(n_boot)
    for b in range(n_boot):
        signs = rng.choice([-1.0, 1.0], size=n)
        dz_boot = fitted_null + resid_null * signs
        ssr_l_b, _, _ = _ols_ssr(z_lag, dz_boot)
        best_b = _threshold_grid_search(z_lag, dz_boot, trim=trim, n_grid=n_grid)
        if not np.isfinite(best_b["ssr"]) or best_b["ssr"] <= 0:
            boot_f[b] = 0.0
            continue
        boot_f[b] = ((ssr_l_b - best_b["ssr"]) / 2) / (best_b["ssr"] / df_denom)
    boot_pvalue = float(np.mean(boot_f >= f_stat))

    gamma_pctile = float(np.mean(z_lag <= best["gamma"]))
    return {
        "ok": True,
        "n_obs": int(n),
        "gamma": best["gamma"],
        "gamma_percentile": gamma_pctile,
        "alpha_linear": alpha_linear,
        "alpha_inside": best["alpha1"],
        "alpha_outside": best["alpha2"],
        "outside_faster": bool(abs(best["alpha2"]) > abs(best["alpha1"])),
        "ssr_linear": ssr_linear,
        "ssr_threshold": ssr_threshold,
        "f_stat": float(f_stat),
        "boot_pvalue": boot_pvalue,
    }


def main():
    p = argparse.ArgumentParser(description="Hansen & Seo threshold-cointegration test on confirmed pairs")
    p.add_argument("--n-boot", type=int, default=500)
    p.add_argument("--n-grid", type=int, default=100)
    p.add_argument("--trim", type=float, default=0.15)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    rng = np.random.default_rng(args.seed)

    rows = []
    for tf_dir in _TF_DIRS:
        results_dir, is_stale = _resolve_tf_results_dir(tf_dir)
        pairs_path = os.path.join(results_dir, "pairs.parquet")
        if not os.path.exists(pairs_path):
            continue
        if is_stale:
            print(f"NOTE {tf_dir}: no live output/results/{tf_dir}, "
                  f"using archived {results_dir} instead")
        tf_label = _DIR_TO_LABEL[tf_dir]
        pairs_df = pd.read_parquet(pairs_path)
        for _, row in pairs_df.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            series_path = os.path.join(
                results_dir, f"spread_series_{sym_a}_{sym_b}.parquet"
            )
            if not os.path.exists(series_path):
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: no spread_series file")
                continue
            series_df = pd.read_parquet(series_path)
            real_bar_mask = (series_df["gap_flag_a"] != 4) & (series_df["gap_flag_b"] != 4)
            spread = series_df.loc[real_bar_mask, "spread"].to_numpy(dtype=float)
            spread = spread[np.isfinite(spread)]
            result = threshold_coint_test(
                spread, trim=args.trim, n_grid=args.n_grid,
                n_boot=args.n_boot, rng=rng,
            )
            result["symbol_a"] = sym_a
            result["symbol_b"] = sym_b
            result["tf_label"] = tf_label
            rows.append(result)
            if result.get("ok"):
                print(
                    f"{sym_a}/{sym_b}@{tf_label}: gamma={result['gamma']:.4f} "
                    f"(p{result['gamma_percentile']*100:.0f}) "
                    f"alpha_in={result['alpha_inside']:.4f} "
                    f"alpha_out={result['alpha_outside']:.4f} "
                    f"outside_faster={result['outside_faster']} "
                    f"boot_p={result['boot_pvalue']:.3f}"
                )
            else:
                print(f"FAIL {sym_a}/{sym_b}@{tf_label}: {result.get('error')}")

    out_df = pd.DataFrame(rows)
    os.makedirs("output/research", exist_ok=True)
    out_path = "output/research/threshold_cointegration.parquet"
    out_df.to_parquet(out_path)
    n_ok = int(out_df["ok"].sum()) if "ok" in out_df.columns and len(out_df) else 0
    n_sig = int((out_df.get("boot_pvalue", pd.Series(dtype=float)) < 0.05).sum())
    print(f"\nWrote {out_path}: {len(out_df)} pairs tested, {n_ok} valid, "
          f"{n_sig} significant threshold effects at p<0.05")


if __name__ == "__main__":
    main()
