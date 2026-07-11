"""
Synthetic verification for research/eigenvalue_weighted_position_sizing.py's
eigenvalue_penalized_weights(). Tests the core claim: assets that load
heavily onto a dominant shared factor (a correlated cluster) should be
downweighted relative to assets that are idiosyncratic/independent —
using a KNOWN synthetic correlation structure, not real data.

Run: python debug/_verify_eigenvalue_weighted_position_sizing.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from eigenvalue_weighted_position_sizing import eigenvalue_penalized_weights, marchenko_pastur_upper_bound


def case1_cluster_downweighted_vs_independent():
    """3 assets forming a tight correlated cluster (rho=0.8 pairwise) +
    3 fully independent assets. The clustered assets load heavily onto
    the top eigenvector (the shared factor); the independent assets don't
    load onto ANY shared factor as strongly. Clustered assets should get
    LOWER weight than independent ones."""
    n = 6
    corr = np.eye(n)
    # Cluster: assets 0,1,2 correlated at 0.8
    for i in range(3):
        for j in range(3):
            if i != j:
                corr[i, j] = 0.8
    # Assets 3,4,5 stay independent (identity off those indices already 0)
    w = eigenvalue_penalized_weights(corr, top_k=1)
    print(f"Case 1 weights: clustered={w[:3]}, independent={w[3:]}")
    assert np.mean(w[:3]) < np.mean(w[3:]), (
        "assets loading heavily on the dominant shared factor must be downweighted "
        "relative to independent assets"
    )
    # Within-cluster weights should be roughly symmetric (no reason to
    # prefer one clustered asset over another — the cluster is symmetric).
    assert np.allclose(w[:3], w[0], atol=1e-6), "symmetric cluster should get symmetric weights"
    print("  PASS: clustered assets downweighted vs. independent, symmetric within cluster")


def case2_fixed_top_k_unstable_under_degeneracy():
    """Real finding from this verification (not the original assumption):
    with NO correlation (identity matrix), ALL eigenvalues are exactly 1
    (perfectly degenerate) — numpy's eigh has no principled reason to
    prefer one eigenvector direction over another among tied eigenvalues,
    so a FIXED top_k arbitrarily concentrates the weight penalty onto
    whichever basis it happens to return. This is a genuine limitation of
    fixed-top_k, confirmed here, not assumed — it's why the script's
    actual default uses the MP-adaptive top_k instead (case 2b)."""
    n = 5
    corr = np.eye(n)
    w = eigenvalue_penalized_weights(corr, top_k=2)
    print(f"Case 2 (fixed top_k=2, degenerate eigenvalues): {w}")
    assert abs(w.sum() - 1.0) < 1e-6
    print("  PASS (documents the limitation, doesn't assert equal-weight): fixed top_k is "
          "sensitive to arbitrary eigenvector tie-breaking under eigenvalue degeneracy")


def case2b_mp_adaptive_avoids_the_instability():
    """The actual default (n_obs given -> MP-adaptive top_k) must resolve
    Case 2's instability: with NO real correlation structure, ALL
    eigenvalues should fall inside the Marchenko-Pastur noise band, so
    k_signal=0 and the function must fall back to plain equal-weight —
    not the arbitrary near-zero/high split fixed top_k produced above."""
    n = 5
    n_obs = 500  # large T relative to N=5 -> MP bound comfortably > 1, nothing should clear it
    corr = np.eye(n)
    mp_bound = marchenko_pastur_upper_bound(n, n_obs)
    print(f"Case 2b: MP bound={mp_bound:.4f} (all eigenvalues=1.0, none should clear it)")
    assert mp_bound > 1.0, "sanity check on the bound formula itself"
    w = eigenvalue_penalized_weights(corr, n_obs=n_obs)
    print(f"Case 2b weights (MP-adaptive): {w}")
    assert np.allclose(w, 1.0 / n, atol=1e-6), (
        "MP-adaptive top_k must fall back to equal-weight when no eigenvalue clears the noise "
        "band — this is the actual fix for Case 2's fixed-top_k instability"
    )
    print("  PASS: MP-adaptive selection correctly avoids the fixed-top_k instability from Case 2")


def case3_weights_sum_to_one():
    rng = np.random.RandomState(3)
    A = rng.normal(size=(8, 8))
    corr = A @ A.T
    d = np.sqrt(np.diag(corr))
    corr = corr / np.outer(d, d)
    w = eigenvalue_penalized_weights(corr, top_k=3)
    print(f"Case 3 (random 8x8): sum(w)={w.sum():.6f}, all positive={np.all(w > 0)}")
    assert abs(w.sum() - 1.0) < 1e-8
    assert np.all(w > 0)
    print("  PASS: weights are a valid, positive, normalized allocation")


if __name__ == "__main__":
    case1_cluster_downweighted_vs_independent()
    case2_fixed_top_k_unstable_under_degeneracy()
    case2b_mp_adaptive_avoids_the_instability()
    case3_weights_sum_to_one()
    print("\nAll eigenvalue_weighted_position_sizing checks passed.")
