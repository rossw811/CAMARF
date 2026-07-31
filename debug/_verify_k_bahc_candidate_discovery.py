"""
Synthetic verification for research/k_bahc_candidate_discovery.py (built
2026-07-21, "start work on k-bahc" per Ross's direction).

Precise mechanism check, worked out BEFORE trusting real data: k-BAHC
cleaning (research/k_bahc_covariance_cleaning.py::clean_correlation_matrix)
keeps WITHIN-cluster correlation entries exactly as observed, and replaces
EVERY cross-cluster entry with the SAME single value: the average of all
observed cross-cluster correlations (`cross_mean`). This has a precise,
non-obvious consequence for "candidate discovery" (does cleaning ever admit
a pair that raw correlation excluded):

  - Cleaning can NEVER increase a within-cluster pair's correlation (those
    are untouched) -- so it cannot "rescue" a genuine same-cluster
    relationship that sampling noise pushed below threshold.
  - Cleaning CAN surface new cross-cluster candidates, but ONLY if
    `cross_mean` itself clears the threshold -- and since ALL cross-cluster
    pairs get set to that identical value, this happens for either ALL
    cross-cluster pairs simultaneously or NONE of them, never a subset.
  - Cleaning's other real effect is suppression: a cross-cluster pair whose
    RAW correlation cleared the threshold by pure sampling noise gets
    pulled down to `cross_mean` and correctly excluded, if `cross_mean`
    itself is below threshold.

This test verifies both regimes on a fully synthetic, ground-truth-known
universe: 3 clusters of 20 assets each (60 total), genuine within-cluster
correlation via a shared per-cluster latent factor, and two cross-cluster
noise regimes -- (A) near-zero true cross-cluster correlation (realistic
per this project's own prior finding that real full-universe rho_bar~0),
and (B) a deliberately-elevated true cross-cluster correlation (~0.45,
above the 0.40 threshold) to confirm the "surfaces ALL cross-cluster pairs
simultaneously" mechanism actually fires when the true signal supports it.

Run: python debug/_verify_k_bahc_candidate_discovery.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from k_bahc_covariance_cleaning import clean_correlation_matrix

THRESHOLD = 0.40


def _synthetic_universe(rng, n_clusters=3, per_cluster=20, n_bars=300,
                         within_loading=0.7, cross_true_corr=0.0, noise_std=1.0):
    """Builds a (n_bars, n_assets) return panel with a KNOWN cluster
    structure: each cluster has its own latent factor; asset returns load
    on their own cluster's factor (within_loading) plus idiosyncratic noise.
    `cross_true_corr` optionally adds a SHARED common factor across ALL
    clusters (on top of each asset's own cluster factor) to control the
    true cross-cluster correlation level."""
    n_assets = n_clusters * per_cluster
    cluster_factors = rng.normal(0, 1, (n_clusters, n_bars))
    common_factor = rng.normal(0, 1, n_bars)
    returns = np.zeros((n_bars, n_assets))
    true_cluster_id = np.zeros(n_assets, dtype=int)
    idx = 0
    # Solve for the common-factor loading that produces the desired implied
    # cross-cluster correlation, given within_loading and unit-variance
    # components: corr(cross) = common_loading^2 / (within_loading^2 + common_loading^2 + noise_std^2)
    # (two assets in different clusters share ONLY the common factor).
    if cross_true_corr <= 0:
        common_loading = 0.0
    else:
        # cross_true_corr * (within_loading^2 + common_loading^2 + noise_std^2) = common_loading^2
        # => common_loading^2 * (1 - cross_true_corr) = cross_true_corr * (within_loading^2 + noise_std^2)
        denom = 1 - cross_true_corr
        common_loading = np.sqrt(cross_true_corr * (within_loading ** 2 + noise_std ** 2) / denom)
    for c in range(n_clusters):
        for _ in range(per_cluster):
            idio = rng.normal(0, noise_std, n_bars)
            returns[:, idx] = (within_loading * cluster_factors[c] +
                                common_loading * common_factor + idio)
            true_cluster_id[idx] = c
            idx += 1
    return returns, true_cluster_id


def _mean_by_relationship(corr, true_cluster_id):
    n = corr.shape[0]
    within_vals, cross_vals = [], []
    for i in range(n):
        for j in range(i + 1, n):
            if true_cluster_id[i] == true_cluster_id[j]:
                within_vals.append(corr[i, j])
            else:
                cross_vals.append(corr[i, j])
    return float(np.mean(within_vals)), float(np.mean(cross_vals))


def _count_candidates(corr, threshold=THRESHOLD):
    n = corr.shape[0]
    count = 0
    for i in range(n):
        for j in range(i + 1, n):
            if abs(corr[i, j]) >= threshold:
                count += 1
    return count


def main():
    rng = np.random.default_rng(42)
    failures = []

    # --- Case A: realistic regime -- near-zero true cross-cluster correlation ---
    print("=== Case A: near-zero true cross-cluster correlation (realistic per prior finding) ===")
    returns_a, true_cluster_a = _synthetic_universe(rng, cross_true_corr=0.0)
    raw_corr_a = np.corrcoef(returns_a.T)
    cleaned_a, k_a = clean_correlation_matrix(raw_corr_a, max_k=6)

    within_mean_raw, cross_mean_raw = _mean_by_relationship(raw_corr_a, true_cluster_a)
    within_mean_clean, cross_mean_clean = _mean_by_relationship(cleaned_a, true_cluster_a)
    print(f"k chosen: {k_a} (true clusters: 3)")
    print(f"Raw:     within-cluster mean corr={within_mean_raw:.3f}, cross-cluster mean corr={cross_mean_raw:.3f}")
    print(f"Cleaned: within-cluster mean corr={within_mean_clean:.3f}, cross-cluster mean corr={cross_mean_clean:.3f}")

    raw_candidates_a = _count_candidates(raw_corr_a)
    clean_candidates_a = _count_candidates(cleaned_a)
    print(f"Candidates clearing |corr|>={THRESHOLD}: raw={raw_candidates_a}, cleaned={clean_candidates_a}")

    # Within-cluster entries must be EXACTLY unchanged by cleaning (the core
    # mechanism guarantee) -- check a specific pair, not just the mean.
    i, j = 0, 1  # both in cluster 0
    assert true_cluster_a[i] == true_cluster_a[j]
    unchanged = np.isclose(raw_corr_a[i, j], cleaned_a[i, j])
    print(f"Within-cluster pair (0,1) unchanged by cleaning: {unchanged} "
          f"(raw={raw_corr_a[i,j]:.4f}, cleaned={cleaned_a[i,j]:.4f})")
    if not unchanged:
        failures.append("Within-cluster correlation was modified by cleaning -- violates the core mechanism")

    # With near-zero true cross-cluster correlation, cross_mean should stay
    # well below threshold -- cleaning should NOT surface new candidates
    # from previously-below-threshold cross-cluster noise, and should
    # SUPPRESS any cross-cluster pair that raw noise pushed above threshold.
    if cross_mean_clean >= THRESHOLD:
        failures.append(f"Case A: cross_mean_clean ({cross_mean_clean:.3f}) unexpectedly >= threshold")
    if clean_candidates_a > raw_candidates_a:
        failures.append(
            f"Case A: cleaned candidate count ({clean_candidates_a}) should not exceed raw "
            f"({raw_candidates_a}) when true cross-cluster correlation is near zero"
        )
    print()

    # --- Case B: elevated true cross-cluster correlation (~0.45, above threshold) ---
    print("=== Case B: elevated true cross-cluster correlation (~0.45, deliberately above threshold) ===")
    returns_b, true_cluster_b = _synthetic_universe(rng, cross_true_corr=0.45)
    raw_corr_b = np.corrcoef(returns_b.T)
    cleaned_b, k_b = clean_correlation_matrix(raw_corr_b, max_k=6)

    within_mean_raw_b, cross_mean_raw_b = _mean_by_relationship(raw_corr_b, true_cluster_b)
    within_mean_clean_b, cross_mean_clean_b = _mean_by_relationship(cleaned_b, true_cluster_b)
    print(f"k chosen: {k_b} (true clusters: 3)")
    print(f"Raw:     within-cluster mean corr={within_mean_raw_b:.3f}, cross-cluster mean corr={cross_mean_raw_b:.3f}")
    print(f"Cleaned: within-cluster mean corr={within_mean_clean_b:.3f}, cross-cluster mean corr={cross_mean_clean_b:.3f}")

    raw_candidates_b = _count_candidates(raw_corr_b)
    clean_candidates_b = _count_candidates(cleaned_b)
    print(f"Candidates clearing |corr|>={THRESHOLD}: raw={raw_candidates_b}, cleaned={clean_candidates_b}")

    # Key mechanism check: when the TRUE average cross-cluster correlation
    # clears the threshold, cleaning should set EVERY cross-cluster pair to
    # (approximately) the same value >= threshold -- i.e. cleaned candidate
    # count should be much larger than raw (raw has noisy individual pairs,
    # many below threshold despite the true average being above it).
    if cross_mean_clean_b < THRESHOLD:
        failures.append(
            f"Case B: cross_mean_clean ({cross_mean_clean_b:.3f}) should clear the threshold "
            f"({THRESHOLD}) given the true cross-cluster correlation was set to 0.45"
        )
    if clean_candidates_b <= raw_candidates_b:
        failures.append(
            f"Case B: cleaned candidate count ({clean_candidates_b}) should exceed raw "
            f"({raw_candidates_b}) -- cleaning should surface new cross-cluster candidates "
            f"once the true average correlation clears threshold"
        )
    # Confirm the "all-or-nothing" property: the SAME cleaned value applies
    # to every cross-cluster pair (up to floating point), by checking the
    # std of cleaned cross-cluster entries is ~0.
    cross_vals_clean_b = [cleaned_b[i, j] for i in range(60) for j in range(i + 1, 60)
                          if true_cluster_b[i] != true_cluster_b[j]]
    cross_std_clean_b = float(np.std(cross_vals_clean_b))
    print(f"Std of cleaned cross-cluster values (should be ~0, all-or-nothing property): {cross_std_clean_b:.6f}")
    if cross_std_clean_b > 1e-9:
        failures.append("Cleaned cross-cluster values are not all identical -- violates the all-or-nothing property")

    print()
    if failures:
        print(f"FAILED: {failures}")
        sys.exit(1)
    print("PASS: k-BAHC cleaning mechanism verified on synthetic ground truth -- within-cluster "
          "correlations are never modified; cross-cluster correlations are all set to a single "
          "shared value that only clears the threshold (surfacing new candidates, all-or-nothing) "
          "when the TRUE average cross-cluster correlation itself clears it.")


if __name__ == "__main__":
    main()
