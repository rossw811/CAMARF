"""
Synthetic verification for research/tail_dependence_universe_screen.py
(built 2026-07-21, per Ross's "push on the two follow ups and do copulas"
direction -- the copula/tail-dependence universe-wide discovery screen).

Two things verified before trusting this on real data:

1. `binomial_tail_pvalue()`'s closed-form null matches a genuine Monte Carlo
   simulation under independence -- i.e. the shortcut taken for compute
   reasons (avoiding per-pair permutation resampling across potentially
   thousands of near-miss pairs) is not silently wrong.
2. The full screen correctly identifies a pair with PLANTED tail dependence
   (built via a real Clayton-copula-style joint-crash mechanism) among a
   population of pure independent-noise near-miss pairs, and does NOT
   flag the noise pairs after BY-FDR correction.

Run: python debug/_verify_tail_dependence_universe_screen.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from tail_dependence_universe_screen import binomial_tail_pvalue
from tail_dependence import _empirical_tail_dependence
from bh_fdr_dependence_check import benjamini_yekutieli


def _verify_binomial_null_matches_monte_carlo():
    print("=== Part 1: closed-form binomial null vs. Monte Carlo simulation ===\n")
    rng = np.random.default_rng(0)
    n_obs = 2000
    q = 0.05
    n_trials = 3000

    # Simulate the null directly: many draws of two INDEPENDENT standard
    # normal series, compute the real joint-tail-hit count each time, and
    # build an empirical null distribution to compare against the
    # closed-form Binomial(n_L, q).
    hit_counts = []
    n_ls = []
    for _ in range(n_trials):
        a = rng.normal(0, 1, n_obs)
        b = rng.normal(0, 1, n_obs)
        result = _empirical_tail_dependence(a, b, q)
        if result is None:
            continue
        lam_l, lam_u, n_l, n_u = result
        if n_l > 0:
            hit_counts.append(int(round(lam_l * n_l)))
            n_ls.append(n_l)

    hit_counts = np.array(hit_counts)
    mean_n_l = int(np.mean(n_ls))
    mc_mean_hits = hit_counts.mean()
    binom_mean_hits = mean_n_l * q  # E[X] under Binomial(n_L, q)

    print(f"Monte Carlo ({n_trials} independent draws): mean joint-tail hit count = {mc_mean_hits:.3f}")
    print(f"Closed-form Binomial(n_L={mean_n_l}, q={q}) expectation:      {binom_mean_hits:.3f}")
    assert abs(mc_mean_hits - binom_mean_hits) < 0.5, (
        f"Monte Carlo mean ({mc_mean_hits:.3f}) diverges too far from the closed-form "
        f"Binomial expectation ({binom_mean_hits:.3f}) -- the binomial null approximation "
        f"may not be valid."
    )

    # Compare the actual TAIL PROBABILITY: what fraction of Monte Carlo
    # draws exceed a given hit count vs. what the closed-form binomial
    # p-value predicts for that same count.
    test_hit_count = int(np.percentile(hit_counts, 95))
    mc_p = float(np.mean(hit_counts >= test_hit_count))
    binom_p = binomial_tail_pvalue(test_hit_count, mean_n_l, q)
    print(f"\nAt hit_count={test_hit_count}: Monte Carlo P(X>=count)={mc_p:.4f}, "
          f"closed-form binomial P(X>=count)={binom_p:.4f}")
    assert abs(mc_p - binom_p) < 0.03, (
        f"Monte Carlo tail probability ({mc_p:.4f}) diverges too far from the closed-form "
        f"binomial p-value ({binom_p:.4f})."
    )
    print("\nPASS: closed-form binomial null matches Monte Carlo simulation under independence.")


def _verify_screen_identifies_planted_tail_dependence():
    print("\n\n=== Part 2: screen identifies a planted tail-dependent pair among pure noise ===\n")
    rng = np.random.default_rng(1)
    n_obs = 1500
    q_values = [0.05, 0.10]
    alpha = 0.05

    # Build 20 pure-noise "near-miss" pairs (independent standard normals --
    # any weak correlation is pure sampling noise, no real tail structure).
    pairs_data = {}
    for i in range(20):
        pairs_data[f"NOISE{i}A"] = rng.normal(0, 1, n_obs)
        pairs_data[(f"NOISE{i}A", f"NOISE{i}B")] = None  # placeholder, filled below
    noise_pairs = []
    for i in range(20):
        a = rng.normal(0, 1, n_obs)
        b = rng.normal(0, 1, n_obs)
        noise_pairs.append((f"NOISE{i}A", f"NOISE{i}B", a, b))

    # One PLANTED tail-dependent pair: independent in the BODY of the
    # distribution, but with a real joint-crash mechanism spliced in --
    # whenever leg A has an extreme negative move, leg B also gets a
    # correlated extreme negative move (a crude but genuine lower-tail
    # dependence mechanism, not just elevated overall correlation).
    a_planted = rng.normal(0, 1, n_obs)
    b_planted = rng.normal(0, 1, n_obs)
    extreme_mask = a_planted < np.percentile(a_planted, 5)
    b_planted[extreme_mask] = a_planted[extreme_mask] + rng.normal(0, 0.1, extreme_mask.sum())

    all_pairs = noise_pairs + [("PLANTED_A", "PLANTED_B", a_planted, b_planted)]

    all_rows = []
    for sym_a, sym_b, a_vals, b_vals in all_pairs:
        for q in q_values:
            result = _empirical_tail_dependence(a_vals, b_vals, q)
            if result is None:
                continue
            lam_l, lam_u, n_l, n_u = result
            p_lower = binomial_tail_pvalue(int(round(lam_l * n_l)), n_l, q) if (lam_l is not None and n_l > 0) else None
            p_upper = binomial_tail_pvalue(int(round(lam_u * n_u)), n_u, q) if (lam_u is not None and n_u > 0) else None
            all_rows.append({
                "symbol_a": sym_a, "symbol_b": sym_b, "q": q,
                "lambda_L": lam_l, "lambda_U": lam_u, "p_lower": p_lower, "p_upper": p_upper,
            })

    result_df = pd.DataFrame(all_rows)
    rej_l, adj_l = benjamini_yekutieli(result_df["p_lower"].dropna().to_numpy(), alpha)
    result_df.loc[result_df["p_lower"].notna(), "significant_lower_by"] = rej_l

    survivors = result_df[result_df["significant_lower_by"].fillna(False)]
    survivor_pairs = set(zip(survivors["symbol_a"], survivors["symbol_b"]))

    print(f"Survivors after BY-FDR correction: {survivor_pairs}")
    assert ("PLANTED_A", "PLANTED_B") in survivor_pairs, (
        "FAILED: the planted lower-tail-dependent pair was not flagged as significant -- "
        "the screen's detection power is insufficient or something is wrong with the pipeline."
    )
    noise_survivors = survivor_pairs - {("PLANTED_A", "PLANTED_B")}
    print(f"Noise pairs incorrectly flagged: {noise_survivors}")
    assert len(noise_survivors) == 0, (
        f"FAILED: {len(noise_survivors)} pure-noise pair(s) were flagged as significant after "
        f"BY-FDR correction -- the multiple-testing correction is not adequately controlling "
        f"false positives at this candidate count."
    )
    print("\nPASS: screen correctly identifies the planted tail-dependent pair and correctly "
          "rejects all 20 pure-noise pairs after BY-FDR correction.")


def main():
    _verify_binomial_null_matches_monte_carlo()
    _verify_screen_identifies_planted_tail_dependence()
    print("\n\nALL CHECKS PASSED.")


if __name__ == "__main__":
    main()
