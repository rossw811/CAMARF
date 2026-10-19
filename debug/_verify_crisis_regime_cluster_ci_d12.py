"""
D12 / R6.9 (Ross 2026-10-12; details 2026-10-17): research/crisis_regime_cluster_bootstrap_test.py treated the calm
rate as fixed and read "share of crisis-bootstrap draws <= calm rate" as a p-value -- the bootstrap is not centred on a
null, so that share is not a p-value; and with 12 very unequal clusters (93% of confirmations in 2) a pairs-style
cluster bootstrap is unreliable (Cameron-Gelbach-Miller 2008). Approved: main = randomization inference over
clusters (the D3 method: crisis episodes + calm calendar years), reported as a CI by test inversion; check = wild
cluster bootstrap with Webb six-point weights (percentile-t, CR1 standard error); both CIs, no p-value.
Checks:
  1. RI inversion: the CI contains the observed difference and p(delta = observed) is the largest on the grid;
  2. no effect (clustered, heterogeneous world): both CIs cover 0 in >= 88% of 100 worlds;
  3. a real crisis effect across many clusters: RI CI excludes 0 and covers the true difference;
  4. wild bootstrap: Webb weights have mean 0, variance 1, six points; the CR1 SE matches the pair-level formula;
  5. the output carries no "p-value equivalent" column.
Run: python debug/_verify_crisis_regime_cluster_ci_d12.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "research"))

import numpy as np

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def world(rng, n_crisis=12, n_calm=30, effect=0.0):
    """Cluster sizes very unequal; cluster base rates heterogeneous (beta-distributed); crisis adds `effect`."""
    n = np.r_[rng.integers(50, 4000, n_crisis), rng.integers(2000, 15000, n_calm)].astype(float)
    base = rng.beta(2, 600, n_crisis + n_calm)
    lab = np.r_[np.ones(n_crisis, bool), np.zeros(n_calm, bool)]
    p = np.clip(base + effect * lab, 0, 1)
    k = rng.binomial(n.astype(int), p).astype(float)
    return n, k, lab


def main():
    try:
        import crisis_regime_cluster_bootstrap_test as mod
        rng = np.random.default_rng(0)
        n, k, lab = world(rng, effect=0.002)
        r = mod.ri_ci(n, k, lab, n_sim=2000, rng=np.random.default_rng(1))
        obs = k[lab].sum() / n[lab].sum() - k[~lab].sum() / n[~lab].sum()
        check("ri_ci_contains_observed", r["ci_low"] <= obs <= r["ci_high"], f"obs {obs:.5f} in [{r['ci_low']:.5f}, {r['ci_high']:.5f}]")
        check("ri_p_peaks_at_observed", abs(r["delta_max_p"] - obs) <= 2 * r["grid_step"],
              f"argmax p at {r['delta_max_p']:.5f} vs obs {obs:.5f}")

        cov_ri = cov_w = 0
        for s in range(100):
            n, k, lab = world(np.random.default_rng(100 + s))
            a = mod.ri_ci(n, k, lab, n_sim=500, rng=np.random.default_rng(s))
            b = mod.wild_cluster_ci(n, k, lab, n_boot=999, rng=np.random.default_rng(s))
            cov_ri += a["ci_low"] <= 0 <= a["ci_high"]
            cov_w += b["ci_low"] <= 0 <= b["ci_high"]
        check("no_effect_ri_covers_zero", cov_ri >= 88, f"{cov_ri}/100")
        check("no_effect_wild_covers_zero", cov_w >= 88, f"{cov_w}/100")

        n, k, lab = world(np.random.default_rng(7), n_crisis=40, n_calm=40, effect=0.004)
        true = 0.004
        a = mod.ri_ci(n, k, lab, n_sim=2000, rng=np.random.default_rng(2))
        check("effect_ri_excludes_zero_covers_truth", a["ci_low"] > 0 and a["ci_low"] <= true <= a["ci_high"] + 0.002,
              f"[{a['ci_low']:.5f}, {a['ci_high']:.5f}] true {true}")

        w = mod.webb_weights()
        check("webb_weights", len(w) == 6 and abs(w.mean()) < 1e-12 and abs((w ** 2).mean() - 1) < 1e-12, f"{w}")
        n, k, lab = world(np.random.default_rng(9))
        se = mod.cr1_se(n, k, lab)
        # pair-level CR1 for the LPM y = a + b*crisis, residuals summed by cluster
        G = len(n)
        rc, rm = k[lab].sum() / n[lab].sum(), k[~lab].sum() / n[~lab].sum()
        U = np.where(lab, k - n * rc, k - n * rm)
        Nc, Nm = n[lab].sum(), n[~lab].sum()
        se_ref = np.sqrt(G / (G - 1) * (np.sum(U[lab] ** 2) / Nc ** 2 + np.sum(U[~lab] ** 2) / Nm ** 2))
        check("cr1_se_matches_formula", np.isclose(se, se_ref), f"{se:.6g} vs {se_ref:.6g}")
        check("no_p_value_equivalent_in_output", "cluster_robust_p_equivalent" not in mod.OUTPUT_COLUMNS)
    except (AttributeError, TypeError) as e:
        check("d12_functions_exist", False, f"{type(e).__name__}: {e}")

    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
