"""
Synthetic replication of Benjamini & Hochberg (1995), "Controlling the False
Discovery Rate" (JRSSB 57(1), 289-300) -- BEFORE trusting that CAMARF's own
per-timeframe BH-FDR correction (`Config.STATS.FDR_ALPHA`, applied in
CointScanner after every batch of EG tests) actually controls the false
discovery rate at the claimed level, and BEFORE assuming it still does so
once the underlying tests are correlated (which CAMARF's own tests are --
one symbol appears in many pairs).

Checks:
  1. Independent tests, known ground truth (m0 true nulls + m1 true
     alternatives): realized FDR (false rejections / total rejections,
     averaged across many Monte Carlo repetitions) should sit at or below
     the nominal alpha -- Benjamini-Hochberg's theorem under independence.
  2. Positively-correlated tests (all null p-values driven off a shared
     latent factor, the PRDS condition BH's own theorem covers): realized
     FDR should STILL sit at or below nominal alpha -- this is the specific
     condition Benjamini & Yekutieli (2001) proved BH remains valid under,
     and the condition CAMARF's cross-pair-correlated tests should satisfy
     if the theorem is being invoked correctly.
  3. Power comparison: report BH's true-positive detection rate at m1=50
     genuine alternatives, so a real number exists for "how many of the
     true relationships does the correction still let through" rather than
     treating FDR control as costless.
  4. Naive (uncorrected) per-test alpha=0.05, no multiple-testing
     correction at all, run on the SAME 1000-test correlated scenario as a
     explicit contrast -- confirms the uncorrected false-rejection count is
     far higher than BH's actual number of false rejections, quantifying
     what BH-FDR is actually buying CAMARF at its current 10^6-test scale.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from statsmodels.stats.multitest import multipletests

N_TRIALS = 500
M_TOTAL = 1000
M1_TRUE_ALT = 50  # genuine alternatives among the 1000 tests
ALPHA = 0.05
EFFECT_SIZE = 3.0  # z-score mean shift for true alternatives
RNG = np.random.default_rng(7)


def _one_trial_independent():
    """m0 true nulls ~ N(0,1) z-scores, m1 true alternatives ~ N(effect,1)."""
    z_null = RNG.standard_normal(M_TOTAL - M1_TRUE_ALT)
    z_alt = RNG.normal(EFFECT_SIZE, 1.0, M1_TRUE_ALT)
    z = np.concatenate([z_null, z_alt])
    is_true_alt = np.concatenate([
        np.zeros(M_TOTAL - M1_TRUE_ALT, dtype=bool),
        np.ones(M1_TRUE_ALT, dtype=bool),
    ])
    p = 2 * (1 - _norm_cdf(np.abs(z)))
    return p, is_true_alt


def _one_trial_correlated():
    """Same null/alt split, but all null z-scores share a common latent
    factor loading of 0.6 -- positive regression dependence (PRDS), the
    exact condition Benjamini-Yekutieli (2001) proved BH remains valid
    under, and the structural analog of CAMARF's shared-symbol pair tests.
    """
    factor = RNG.standard_normal()
    loading = 0.6
    idio_null = RNG.standard_normal(M_TOTAL - M1_TRUE_ALT)
    z_null = loading * factor + np.sqrt(1 - loading ** 2) * idio_null
    z_alt = RNG.normal(EFFECT_SIZE, 1.0, M1_TRUE_ALT)
    z = np.concatenate([z_null, z_alt])
    is_true_alt = np.concatenate([
        np.zeros(M_TOTAL - M1_TRUE_ALT, dtype=bool),
        np.ones(M1_TRUE_ALT, dtype=bool),
    ])
    p = 2 * (1 - _norm_cdf(np.abs(z)))
    return p, is_true_alt


def _norm_cdf(x):
    from scipy.stats import norm
    return norm.cdf(x)


def _run_bh(p: np.ndarray, is_true_alt: np.ndarray) -> tuple:
    reject, _p_adj, _a_sidak, _a_bonf = multipletests(p, alpha=ALPHA, method="fdr_bh")
    n_rejected = int(reject.sum())
    n_false_rejected = int((reject & ~is_true_alt).sum())
    n_true_rejected = int((reject & is_true_alt).sum())
    fdr = n_false_rejected / n_rejected if n_rejected > 0 else 0.0
    power = n_true_rejected / is_true_alt.sum()
    return fdr, power, n_rejected


def _run_naive(p: np.ndarray, is_true_alt: np.ndarray) -> tuple:
    reject = p < ALPHA
    n_rejected = int(reject.sum())
    n_false_rejected = int((reject & ~is_true_alt).sum())
    return n_false_rejected, n_rejected


def main():
    failures = []

    fdr_indep, power_indep = [], []
    for _ in range(N_TRIALS):
        p, is_true_alt = _one_trial_independent()
        fdr, power, _n = _run_bh(p, is_true_alt)
        fdr_indep.append(fdr)
        power_indep.append(power)
    mean_fdr_indep = float(np.mean(fdr_indep))
    mean_power_indep = float(np.mean(power_indep))

    fdr_corr, power_corr = [], []
    naive_false_counts, naive_total_counts = [], []
    for _ in range(N_TRIALS):
        p, is_true_alt = _one_trial_correlated()
        fdr, power, _n = _run_bh(p, is_true_alt)
        fdr_corr.append(fdr)
        power_corr.append(power)
        n_false_naive, n_rej_naive = _run_naive(p, is_true_alt)
        naive_false_counts.append(n_false_naive)
        naive_total_counts.append(n_rej_naive)
    mean_fdr_corr = float(np.mean(fdr_corr))
    mean_power_corr = float(np.mean(power_corr))
    mean_naive_false = float(np.mean(naive_false_counts))

    if not (mean_fdr_indep <= ALPHA + 0.02):
        failures.append(
            f"BH-FDR did not control FDR under independence: mean realized FDR "
            f"= {mean_fdr_indep:.4f}, expected <= {ALPHA + 0.02:.3f}"
        )
    if not (mean_fdr_corr <= ALPHA + 0.03):
        failures.append(
            f"BH-FDR did not control FDR under positive correlation (PRDS): "
            f"mean realized FDR = {mean_fdr_corr:.4f}, expected <= {ALPHA + 0.03:.3f} "
            f"-- if this fails, CAMARF's flat per-timeframe BH-FDR may not be valid "
            f"the way it's currently being invoked"
        )
    if not (mean_power_indep > 0.2):
        # Sanity floor only, not a target: with m1=50 true alternatives out of
        # 1000 tests (pi0~0.95) and BH's adaptive rank-dependent threshold,
        # moderate power (~0.3-0.6) at effect size 3.0 is the expected,
        # honestly-reported result -- not a bug. This check exists only to
        # catch a genuine setup error (e.g. p-values computed wrong), which
        # would show up as power near 0, not moderate power.
        failures.append(
            f"BH-FDR power implausibly low for a real effect size of "
            f"{EFFECT_SIZE}: {mean_power_indep:.3f} -- check effect-size/test "
            f"setup before trusting the FDR numbers above"
        )
    if not (mean_naive_false > mean_fdr_corr * 1000 * 0.3):
        # sanity: naive uncorrected testing should produce far more false
        # rejections in absolute count than BH's controlled false-rejection
        # fraction implies -- if this doesn't hold the naive baseline is
        # miscomputed, not that BH is somehow worse than no correction
        failures.append(
            f"Naive-vs-BH contrast did not show the expected gap: naive mean "
            f"false rejections = {mean_naive_false:.1f} out of {M_TOTAL - M1_TRUE_ALT} "
            f"true nulls -- expected close to {ALPHA * (M_TOTAL - M1_TRUE_ALT):.0f} "
            f"(uncorrected alpha=0.05 on {M_TOTAL - M1_TRUE_ALT} true nulls)"
        )

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)

    print("Benjamini-Hochberg (1995) FDR control replication: PASSED")
    print(f"  Independent tests   -- mean realized FDR: {mean_fdr_indep:.4f}  "
          f"(nominal alpha={ALPHA}); mean power: {mean_power_indep:.3f}")
    print(f"  Correlated tests    -- mean realized FDR: {mean_fdr_corr:.4f}  "
          f"(nominal alpha={ALPHA}); mean power: {mean_power_corr:.3f}")
    print(f"  Naive uncorrected alpha=0.05, mean false rejections per trial: "
          f"{mean_naive_false:.1f} / {M_TOTAL - M1_TRUE_ALT} true nulls "
          f"(expected ~{ALPHA * (M_TOTAL - M1_TRUE_ALT):.0f} with no correction at all)")
    print(f"  Interpretation: BH-FDR controls FDR at the nominal level in both "
          f"the independent and the positively-correlated (PRDS) case, consistent "
          f"with Benjamini-Yekutieli (2001) -- CAMARF's flat per-timeframe BH-FDR "
          f"correction is validly invoked as long as test correlation within a "
          f"timeframe stays positive, which is the expected structure for "
          f"shared-symbol pairs. This does NOT by itself address the separate, "
          f"cross-timeframe multiplicity question (does testing the same symbols "
          f"across 14 timeframes need its own correction) -- that is the open "
          f"question the multilayer-FDR literature (Barber-Ramdas, Katsevich-"
          f"Sabatti) in the concept backlog speaks to, not this replication.")


if __name__ == "__main__":
    main()
