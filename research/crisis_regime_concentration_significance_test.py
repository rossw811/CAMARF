"""
research/crisis_regime_concentration_significance_test.py -- is the "top 2 of
12 crisis episodes carry 93.1% of confirmations" concentration itself just
what a small, right-skewed count distribution produces by chance, or is it
genuinely surprising given each episode's pair count?

Motivation (2026-09-02, council-quant-pm review of PAPER_MAGNITUDE.md): the
episode-clustering check (crisis_regime_episode_clustering_check.py) found
that 27 of 29 crisis-first confirmations come from just 2 of 12 historical
episodes (2008-09 GFC, 2011 debt crisis). Flagged, but left unresolved in the
paper: with only 12 episodes, "top 2 explain 93%" is exactly the kind of
concentrated pattern a small, right-skewed count distribution can produce
even under a boring null -- no formal test had been run to check.

The null this script tests directly: if each of the 29 crisis-first
confirmations were independently, uniformly likely to land on ANY crisis-first
pair regardless of which episode that pair belongs to (i.e. confirmation
probability is constant per-pair, NOT episode-dependent), confirmations would
be multinomially distributed across the 12 episodes with probability equal to
each episode's SHARE OF CRISIS-FIRST PAIRS (its size), not uniform across
episodes. Episode 1 (4,084 of 11,715 pairs, 34.9%) and episode 3 (2,253 pairs,
19.2%) together hold 54.1% of all crisis-first pairs -- so SOME concentration
in those two is expected even under the null. The real question the earlier
disclosure left open: is 93.1% MORE concentrated than 54.1% would predict, by
more than chance?

Two tests, both exact/simulated, no new statistical machinery invented:
  1. Binomial test: under the null, P(episodes 1+3 jointly capture >= 27 of 29
     confirmations | n=29, p=0.541) -- exact, via scipy.stats.binom.
  2. Monte Carlo simulation: draw 29 confirmations from a multinomial with
     per-episode probability proportional to pair count, N_SIM times, and
     report what fraction of simulated draws are AT LEAST as concentrated
     (by max-2-episode share) as the real 93.1% -- a permutation-style check
     that doesn't depend on which specific 2 episodes are "the top 2."

Verified against synthetic ground truth first:
debug/_verify_crisis_regime_concentration_significance_test.py.

Usage:
    python research/crisis_regime_concentration_significance_test.py
"""
import logging
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EPISODES_PATH = os.path.join(_ROOT, "output", "research", "crisis_regime_episode_clustering.parquet")
_OUT_PATH = os.path.join(_ROOT, "output", "research",
                          "crisis_regime_concentration_significance.parquet")

log = logging.getLogger("crisis_regime_concentration_significance_test")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)


def top2_share_binomial_test(episode_sizes: np.ndarray, episode_confirms: np.ndarray) -> dict:
    """Exact binomial test for whether the two LARGEST-CONFIRMATION episodes'
    combined confirmation count is more than their combined PAIR-COUNT SHARE
    would predict under the null (confirmation probability constant per pair,
    independent of episode). Returns the observed top-2 episodes' indices,
    their combined pair-count share, observed confirmations, and the exact
    one-sided binomial p-value for "at least this many"."""
    n_total_confirmed = int(episode_confirms.sum())
    n_total_pairs = int(episode_sizes.sum())
    top2_idx = np.argsort(episode_confirms)[-2:]
    top2_confirmed = int(episode_confirms[top2_idx].sum())
    top2_pair_share = float(episode_sizes[top2_idx].sum() / n_total_pairs)
    # P(X >= top2_confirmed) under Binomial(n_total_confirmed, top2_pair_share)
    p_value = float(stats.binom.sf(top2_confirmed - 1, n_total_confirmed, top2_pair_share))
    return {
        "top2_episode_idx": top2_idx.tolist(),
        "top2_pair_share": top2_pair_share,
        "top2_confirmed": top2_confirmed,
        "n_total_confirmed": n_total_confirmed,
        "expected_under_null": top2_pair_share * n_total_confirmed,
        "p_value": p_value,
    }


def max2_share_monte_carlo(episode_sizes: np.ndarray, n_total_confirmed: int,
                            observed_max2_share: float, n_sim: int = 100_000,
                            rng: np.random.Generator = None) -> dict:
    """Monte Carlo null: draw n_total_confirmed confirmations from a
    multinomial with per-episode probability proportional to episode pair
    count, N_SIM times. For each draw, compute the max-2-episode share of
    confirmations. Returns the fraction of simulated draws AT LEAST as
    concentrated as the real observed max-2-episode share -- a permutation
    p-value that doesn't depend on which 2 episodes happen to be "the top 2"
    in the real data, unlike the binomial test above (which fixes the top-2
    identity from the observed data, a milder test)."""
    if rng is None:
        rng = np.random.default_rng(0)
    probs = episode_sizes / episode_sizes.sum()
    draws = rng.multinomial(n_total_confirmed, probs, size=n_sim)
    sorted_draws = np.sort(draws, axis=1)
    max2_shares = sorted_draws[:, -2:].sum(axis=1) / n_total_confirmed
    p_value = float((max2_shares >= observed_max2_share).mean())
    return {
        "observed_max2_share": observed_max2_share,
        "null_mean_max2_share": float(max2_shares.mean()),
        "null_p95_max2_share": float(np.percentile(max2_shares, 95)),
        "n_sim": n_sim,
        "p_value": p_value,
    }


def main():
    _setup_logging()
    log.info("=== crisis_regime_concentration_significance_test.py: is the top-2-of-12-episode "
             "confirmation concentration surprising given episode sizes, or expected by chance? ===")

    if not os.path.exists(_EPISODES_PATH):
        log.error(f"{_EPISODES_PATH} does not exist -- run "
                  f"research/crisis_regime_episode_clustering_check.py first.")
        sys.exit(1)

    episodes = pd.read_parquet(_EPISODES_PATH)
    episode_sizes = episodes["n_pairs"].to_numpy()
    episode_confirms = episodes["n_confirmed"].to_numpy()
    log.info(f"Loaded {len(episodes)} episodes, {episode_sizes.sum()} total crisis-first pairs, "
             f"{episode_confirms.sum()} total confirmations.")

    binom_result = top2_share_binomial_test(episode_sizes, episode_confirms)
    log.info(f"Binomial test (top-2 episodes fixed from observed data): "
             f"top-2 pair-count share={binom_result['top2_pair_share']:.3f}, "
             f"expected confirmations under null={binom_result['expected_under_null']:.1f}, "
             f"observed={binom_result['top2_confirmed']}, p={binom_result['p_value']:.6f}")

    observed_max2_share = binom_result["top2_confirmed"] / binom_result["n_total_confirmed"]
    mc_result = max2_share_monte_carlo(
        episode_sizes, binom_result["n_total_confirmed"], observed_max2_share,
        n_sim=100_000, rng=np.random.default_rng(0),
    )
    log.info(f"Monte Carlo test (top-2 identity NOT fixed, {mc_result['n_sim']} draws): "
             f"observed max-2-episode share={mc_result['observed_max2_share']:.3f}, "
             f"null mean={mc_result['null_mean_max2_share']:.3f}, "
             f"null 95th pctile={mc_result['null_p95_max2_share']:.3f}, "
             f"p={mc_result['p_value']:.6f}")

    pd.DataFrame([{**binom_result, **{f"mc_{k}": v for k, v in mc_result.items()}}]).to_parquet(_OUT_PATH)
    log.info(f"Saved -> {_OUT_PATH}")
    log.info("crisis_regime_concentration_significance_test.py complete")


if __name__ == "__main__":
    main()
