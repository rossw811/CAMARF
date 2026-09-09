"""
research/crisis_regime_cluster_bootstrap_test.py -- does the crisis-vs-calm
confirmation-rate gap (0.248% vs 0.146%, pooled two-proportion z=2.77,
p=0.0056) survive once crisis-first pairs' episode-clustering is accounted
for properly, via a cluster bootstrap, rather than just disclosed as a risk?

Motivation (2026-09-02, Ross: "the independence review let's do that too"):
crisis_regime_episode_clustering_check.py already showed the 11,715
crisis-first pairs are really 12 historical episodes, and
crisis_regime_concentration_significance_test.py showed the resulting
confirmation concentration (93.1% in 2 episodes) is itself statistically
real, not a chance artifact. Neither of those tests, though, re-derives a
cluster-robust p-value for the ORIGINAL crisis-vs-calm comparison itself --
this script does exactly that, treating EPISODE (not pair) as the unit of
resampling, the standard fix for a pooled proportion test on clustered data.

Method: a cluster bootstrap. Resample the 12 crisis episodes WITH
REPLACEMENT B times; each resample, pool all pairs from the resampled
episodes (an episode drawn twice contributes its pairs twice) and recompute
the crisis confirmation rate. This produces a bootstrap distribution for the
crisis rate that correctly reflects "only 12 independent units of evidence,"
not "11,715 independent trials." Calm's confirmation rate is NOT
re-bootstrapped -- calm-first pairs are drawn from 291,109-281,654-pair
pools spread continuously across nearly the entire 30-year history, in far
more than 12 effectively-independent chunks (this is disclosed, not
assumed: see the calm-side month-count check in main()), so the original
pooled calm rate remains the reference point the crisis bootstrap is judged
against.

Verified against synthetic ground truth first:
debug/_verify_crisis_regime_cluster_bootstrap_test.py.

Usage:
    python research/crisis_regime_cluster_bootstrap_test.py
"""
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PAIRS_PATH = os.path.join(_ROOT, "output", "research", "crisis_regime_correlation_diagnostic_pairs.parquet")
_EPISODES_PATH = os.path.join(_ROOT, "output", "research", "crisis_regime_episode_clustering.parquet")
_OUT_PATH = os.path.join(_ROOT, "output", "research", "crisis_regime_cluster_bootstrap.parquet")

log = logging.getLogger("crisis_regime_cluster_bootstrap_test")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)


def cluster_bootstrap_confirmation_rate(episode_sizes: np.ndarray, episode_confirms: np.ndarray,
                                         n_boot: int = 10_000,
                                         rng: np.random.Generator = None) -> np.ndarray:
    """Resamples the episode-level (size, confirmed) pairs WITH REPLACEMENT
    n_boot times; each draw pools the resampled episodes' pairs/confirmations
    and computes the resulting confirmation rate. Returns the array of
    n_boot bootstrap confirmation rates (not yet summarized), so the caller
    can compute whatever percentiles/comparisons it needs."""
    if rng is None:
        rng = np.random.default_rng(0)
    n_episodes = len(episode_sizes)
    rates = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n_episodes, size=n_episodes)
        rates[b] = episode_confirms[idx].sum() / episode_sizes[idx].sum()
    return rates


def main():
    _setup_logging()
    log.info("=== crisis_regime_cluster_bootstrap_test.py: does the crisis-vs-calm confirmation "
             "rate gap survive a cluster bootstrap treating episode as the resampling unit? ===")

    if not os.path.exists(_EPISODES_PATH) or not os.path.exists(_PAIRS_PATH):
        log.error("Required input files missing -- run crisis_regime_episode_clustering_check.py "
                  "and crisis_regime_correlation_diagnostic.py first.")
        sys.exit(1)

    episodes = pd.read_parquet(_EPISODES_PATH)
    episode_sizes = episodes["n_pairs"].to_numpy()

    pairs = pd.read_parquet(_PAIRS_PATH)
    calm = pairs[pairs["first_regime"] == "calm"]
    calm["first_window_end_date"] = pd.to_datetime(calm["first_window_end_date"])
    n_calm_months = calm["first_window_end_date"].dt.to_period("M").nunique()
    log.info(f"Calm-first pairs span {n_calm_months} distinct discovery months (vs. crisis's 12 "
             f"episodes across 30 discovery months) -- calm's own clustering risk is far lower "
             f"and not bootstrapped here; disclosed, not assumed.")

    results = {}
    for metric, episode_col, calm_col in [
        ("confirmation_rate", "n_confirmed", "confirmed"),
        ("reappearance_rate", "n_reappear", "reappears_in_different_regime"),
    ]:
        episode_events = episodes[episode_col].to_numpy()
        calm_rate = calm[calm_col].mean()
        boot_rates = cluster_bootstrap_confirmation_rate(
            episode_sizes, episode_events, n_boot=10_000, rng=np.random.default_rng(0)
        )
        observed_crisis_rate = episode_events.sum() / episode_sizes.sum()
        ci_low, ci_high = np.percentile(boot_rates, [2.5, 97.5])
        frac_boot_at_or_below_calm = float((boot_rates <= calm_rate).mean())
        log.info(f"--- {metric} ---")
        log.info(f"Observed calm rate (reference, not bootstrapped): {calm_rate:.4%}")
        log.info(f"Observed crisis rate (pooled): {observed_crisis_rate:.4%}")
        log.info(f"Cluster-bootstrap 95% CI (episode-level resampling, n_boot=10000): "
                 f"[{ci_low:.4%}, {ci_high:.4%}]")
        log.info(f"Fraction of bootstrap draws with crisis rate <= calm's observed rate: "
                 f"{frac_boot_at_or_below_calm:.4f} -- cluster-robust one-sided p-value "
                 f"equivalent for 'crisis rate > calm rate', properly accounting for only "
                 f"12 independent episodes rather than 11,715 independent pairs.")
        results[metric] = {
            "observed_crisis_rate": observed_crisis_rate, "observed_calm_rate": calm_rate,
            "ci_low": ci_low, "ci_high": ci_high,
            "cluster_robust_p_equivalent": frac_boot_at_or_below_calm,
        }

    pd.DataFrame(results).T.to_parquet(_OUT_PATH)
    log.info(f"Saved -> {_OUT_PATH}")
    log.info("crisis_regime_cluster_bootstrap_test.py complete")


if __name__ == "__main__":
    main()
