"""
research/jump_diffusion_parameter_fit.py — comparison/diagnostic method,
NOT part of the production pipeline.

Extends research/jump_diffusion_spread_analysis.py (threshold-based jump
DETECTION: |delta| > 4*trailing_std, reports jump count and variance share)
to jump-ARRIVAL-PROCESS ESTIMATION: a Merton (1976) jump-diffusion model
fit via MLE directly to the spread's z_rolling delta series, giving a real
jump intensity (jumps/bar, converted to jumps/year) and jump-size
distribution (mu_J, sigma_J) rather than just a variance-share summary.

Sourced from a 2026-07-13 GitHub-repo survey (cantaro86/Financial-Models-
Numerical-Methods) that flagged Merton/Variance-Gamma parameter estimation
as a real extension opportunity distinct from that repo's own primary use
case (option pricing under these processes, which is explicitly NOT used
or adapted here -- only the parameter-estimation half is relevant to
CAMARF's spread-tail-modeling question).

Model (Merton 1976): over each bar, the observed delta X_t is drawn from
a mixture -- with probability governed by a Poisson process of rate
lambda (jumps/bar), a jump of size ~ N(mu_J, sigma_J^2) is added to an
underlying continuous-diffusion increment ~ N(mu, sigma^2). The likelihood
of a single observation is the Poisson-weighted sum over the (unobserved)
jump count n:

    f(x) = sum_{n=0}^{N_MAX} [Pois(n; lambda) * Normal_pdf(x; mu + n*mu_J,
                                                             sigma^2 + n*sigma_J^2)]

N_MAX=10 is a finite truncation (lambda is small -- typically well under 1
jump/bar for this project's confirmed pairs per the existing threshold-
detection finding, ~1-2% of bars -- so terms beyond n=10 are negligible).
Estimated via negative-log-likelihood minimization (scipy.optimize).

Verified against known-parameter synthetic data first:
debug/_verify_jump_diffusion_fit.py (run that before trusting this on real
data; do not skip).

Read-only. Never fetches, never modifies production spread_series.

Usage:
    python research/jump_diffusion_parameter_fit.py
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import norm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # for aligned_pair_loader

from aligned_pair_loader import (
    TF_DIRS as _TF_DIRS,
    DIR_TO_LABEL as _DIR_TO_LABEL,
    resolve_tf_results_dir as _resolve_tf_results_dir,
)
N_MAX = 10  # truncation of the Poisson jump-count sum
BARS_PER_YEAR_1H = 1638  # 6.5h/session * 252 sessions/year, for interpretability only


def _neg_log_likelihood(params, x):
    mu, log_sigma, log_lam, mu_j, log_sigma_j = params
    sigma = np.exp(log_sigma)
    lam = np.exp(log_lam)
    sigma_j = np.exp(log_sigma_j)
    if sigma <= 0 or sigma_j <= 0:
        return np.inf

    n = np.arange(N_MAX + 1)
    # Poisson weights (log-space then exponentiate; lambda is small so this is stable)
    log_pois = n * np.log(lam + 1e-300) - lam - gammaln(n + 1)
    pois_w = np.exp(log_pois)
    pois_w = pois_w / pois_w.sum()  # renormalize truncation

    # mixture normal pdf per observation, per n
    means = mu + n * mu_j
    variances = sigma ** 2 + n * sigma_j ** 2
    # x: (T,), means/variances: (N_MAX+1,) -> broadcast to (T, N_MAX+1)
    pdf_vals = norm.pdf(x[:, None], loc=means[None, :], scale=np.sqrt(variances)[None, :])
    mix = (pdf_vals * pois_w[None, :]).sum(axis=1)
    mix = np.clip(mix, 1e-300, None)
    return -np.sum(np.log(mix))


def fit_merton_jump_diffusion(x: np.ndarray) -> dict:
    """MLE fit of a Merton jump-diffusion model to a 1D delta series.
    Returns dict with mu, sigma, lam (per-observation jump rate), mu_j, sigma_j."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]

    # Initial guess: a simple trailing-local-vol threshold on x itself (same
    # spirit as jump_diffusion_spread_analysis.detect_jumps, applied directly
    # to the already-differenced series rather than round-tripping through a
    # reconstructed level series). This is only a warm start for the MLE
    # below, not itself the estimate.
    trailing_std = pd.Series(x).shift(1).rolling(60, min_periods=20).std().to_numpy()
    is_jump = np.abs(x) > 4.0 * np.nan_to_num(trailing_std, nan=np.inf)
    if is_jump.sum() >= 2:
        mu0 = float(np.mean(x[~is_jump]))
        sigma0 = float(np.std(x[~is_jump])) or 0.01
        lam0 = float(is_jump.mean())
        mu_j0 = float(np.mean(x[is_jump]) - mu0)
        sigma_j0 = float(np.std(x[is_jump])) or sigma0 * 3
    else:
        mu0, sigma0, lam0, mu_j0, sigma_j0 = float(np.mean(x)), float(np.std(x)) or 0.01, 0.01, 0.0, (float(np.std(x)) or 0.01) * 3

    lam0 = min(max(lam0, 1e-4), 0.15)
    sigma0 = max(sigma0, 1e-6)
    sigma_j0 = max(sigma_j0, 1e-6)

    # Bounds address a real Merton-MLE identifiability pathology, confirmed
    # empirically (debug/_verify_jump_diffusion_fit.py case 2): without
    # bounds, the optimizer can converge to a degenerate solution where a
    # large lambda (>1 "jump"/bar, not a sensible rare-event rate) paired
    # with a tiny sigma_j approximates a slightly-different Gaussian via the
    # CLT, rather than recovering the true no-jump (lambda=0) process. Rare-
    # event jump models are only meaningfully identified when jumps are
    # comparatively infrequent -- lambda is capped well under 1, on the
    # standard rare-jump interpretation this project's own threshold-based
    # detector already assumes (~1-2% of bars).
    overall_scale = float(np.std(x)) or 1.0
    bounds = [
        (mu0 - 10 * overall_scale, mu0 + 10 * overall_scale),      # mu
        (np.log(1e-8 * overall_scale), np.log(10 * overall_scale)),  # log_sigma
        (np.log(1e-6), np.log(0.3)),                                # log_lambda, capped <1 (rare-event regime)
        (mu_j0 - 20 * overall_scale, mu_j0 + 20 * overall_scale),  # mu_j
        (np.log(1e-8 * overall_scale), np.log(50 * overall_scale)),  # log_sigma_j
    ]

    x0 = [mu0, np.log(sigma0), np.log(lam0), mu_j0, np.log(sigma_j0)]
    res = minimize(_neg_log_likelihood, x0, args=(x,), method="L-BFGS-B", bounds=bounds,
                    options={"maxiter": 4000, "ftol": 1e-12, "gtol": 1e-10})
    mu, log_sigma, log_lam, mu_j, log_sigma_j = res.x
    return {
        "mu": float(mu),
        "sigma": float(np.exp(log_sigma)),
        "lam": float(np.exp(log_lam)),
        "mu_j": float(mu_j),
        "sigma_j": float(np.exp(log_sigma_j)),
        "converged": bool(res.success),
        "n_obs": int(len(x)),
        "nll": float(res.fun),
    }


def implied_jump_variance_share(fit: dict) -> float:
    """Fraction of total per-bar variance attributable to the jump component,
    under the fitted Merton model: Var_jump = lambda*(mu_J^2 + sigma_J^2)."""
    var_jump = fit["lam"] * (fit["mu_j"] ** 2 + fit["sigma_j"] ** 2)
    var_diff = fit["sigma"] ** 2
    total = var_diff + var_jump
    return float(var_jump / total) if total > 0 else float("nan")


def _load_z_delta(results_dir: str, sym_a: str, sym_b: str) -> np.ndarray:
    """Diffs z_rolling on the FULL, un-compacted series first, then masks
    (drops) any diff whose start or end bar is DATA_GAP-flagged. Inherited
    the same defect as jump_diffusion_spread_analysis.py (Tier 2.6, Grand
    Sweep 2026-07-20) -- the prior version dropped gap rows BEFORE
    diffing, silently concatenating positions spanning a multi-bar/multi-
    day gap as if one bar apart, feeding the Merton MLE fit a delta series
    where genuine gaps look identical to real single-bar jumps."""
    path = os.path.join(results_dir, f"spread_series_{sym_a}_{sym_b}.parquet")
    if not os.path.exists(path):
        return np.array([])
    df = pd.read_parquet(path)
    z_raw = df["z_rolling"].to_numpy(dtype=float)
    finite_mask = np.isfinite(z_raw)
    gap_bad = ((df["gap_flag_a"].to_numpy() == 4) | (df["gap_flag_b"].to_numpy() == 4))
    z_for_diff = np.where(finite_mask, z_raw, np.nan)
    delta = np.diff(z_for_diff, prepend=np.nan)
    bad_delta = gap_bad | np.roll(gap_bad, 1)
    bad_delta[0] = False
    delta = np.where(bad_delta, np.nan, delta)
    keep = finite_mask & ~gap_bad
    return delta[keep][np.isfinite(delta[keep])]


def main():
    target_pairs = [("AMD", "DD", "1h")]  # same pair as the existing threshold-detection finding, for direct comparison

    for sym_a, sym_b, tf_want in target_pairs:
        results_dir = None
        for tf_dir in _TF_DIRS:
            if _DIR_TO_LABEL[tf_dir] == tf_want:
                results_dir, _ = _resolve_tf_results_dir(tf_dir)
                break
        if results_dir is None:
            print(f"No results dir found for {tf_want}")
            continue

        delta = _load_z_delta(results_dir, sym_a, sym_b)
        if len(delta) < 200:
            print(f"{sym_a}/{sym_b}@{tf_want}: insufficient data ({len(delta)} deltas)")
            continue

        fit = fit_merton_jump_diffusion(delta)
        jump_share = implied_jump_variance_share(fit)
        jumps_per_year = fit["lam"] * BARS_PER_YEAR_1H

        print(f"=== Merton jump-diffusion MLE fit: {sym_a}/{sym_b}@{tf_want} ===")
        print(f"n_obs={fit['n_obs']}  converged={fit['converged']}  nll={fit['nll']:.2f}")
        print(f"mu={fit['mu']:.5f}  sigma={fit['sigma']:.5f} (continuous diffusion)")
        print(f"lambda={fit['lam']:.5f} per bar  (~{jumps_per_year:.1f} jumps/year at {BARS_PER_YEAR_1H} bars/year)")
        print(f"mu_J={fit['mu_j']:.5f}  sigma_J={fit['sigma_j']:.5f} (jump size distribution)")
        print(f"implied jump-variance-share: {jump_share:.4f}")

        out = pd.DataFrame([{
            "symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf_want,
            **fit, "jumps_per_year": jumps_per_year, "implied_jump_variance_share": jump_share,
        }])
        os.makedirs("output/research", exist_ok=True)
        out_path = "output/research/jump_diffusion_parameter_fit.parquet"
        out.to_parquet(out_path)
        print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
