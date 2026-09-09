"""
Tier A item #1 of the 2026-09-08 caveat/limitation search: does the
residual-correlation-factor split (6.7% of §5-confirmed crisis-first
pairs survive factor-adjustment) hold up under the SAME cluster-robust
treatment already applied to the parent crisis-vs-calm confirmation-rate
finding (crisis_regime_cluster_bootstrap_test.py), rather than a naive
pooled proportion across 929 confirmed pairs that are themselves
concentrated in just 12 historical crisis episodes?

Reuses cluster_bootstrap_confirmation_rate() unchanged. Assigns each
confirmed, crisis-first pair to one of the 12 known episodes by date
range (episode_start/episode_end from crisis_regime_episode_clustering.
parquet), then bootstraps the SURVIVES-RESIDUAL-CORRELATION rate among
confirmed pairs, episode as the resampling unit -- same logic as the
original test, different target metric.
"""
import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "research"))

from crisis_regime_cluster_bootstrap_test import cluster_bootstrap_confirmation_rate

_RESIDUAL_PATH = os.path.join(_ROOT, "output", "research", "residual_correlation_factor_test.parquet")
_EPISODES_PATH = os.path.join(_ROOT, "output", "research", "crisis_regime_episode_clustering.parquet")
_OUT_PATH = os.path.join(_ROOT, "output", "research", "residual_correlation_cluster_bootstrap.parquet")


def assign_episode(dates: pd.Series, episodes: pd.DataFrame) -> pd.Series:
    """Assigns each pair's first_window_end_date to the episode whose
    [episode_start, episode_end] range contains it, or -1 if none match
    (should not happen for genuine crisis-first pairs, but not silently
    assumed)."""
    ep_id = pd.Series(-1, index=dates.index)
    for eid, row in episodes.iterrows():
        mask = (dates >= row["episode_start"]) & (dates <= row["episode_end"])
        ep_id.loc[mask] = eid
    return ep_id


def main():
    if not (os.path.exists(_RESIDUAL_PATH) and os.path.exists(_EPISODES_PATH)):
        print("ERROR: missing input(s). Run residual_correlation_factor_test.py and "
              "crisis_regime_episode_clustering_check.py first.")
        return

    residual_df = pd.read_parquet(_RESIDUAL_PATH)
    episodes = pd.read_parquet(_EPISODES_PATH)

    confirmed = residual_df[residual_df["confirmed"] == True].copy()
    confirmed["first_window_end_date"] = pd.to_datetime(confirmed["first_window_end_date"])
    confirmed["episode_id"] = assign_episode(confirmed["first_window_end_date"], episodes)

    n_unassigned = int((confirmed["episode_id"] == -1).sum())
    print(f"{len(confirmed)} confirmed pairs; {n_unassigned} could not be assigned to any of "
          f"the 12 known episodes (excluded from the bootstrap, not silently included).")
    confirmed = confirmed[confirmed["episode_id"] != -1]

    per_episode = confirmed.groupby("episode_id").agg(
        n_pairs=("survives_residual_corr", "size"),
        n_survives=("survives_residual_corr", "sum"),
    )
    # Episodes with zero confirmed pairs assigned here still count as real
    # episodes in the resampling population (matching the parent test's
    # convention) -- reindex to all 12, filling zeros.
    per_episode = per_episode.reindex(range(len(episodes)), fill_value=0)

    episode_sizes = per_episode["n_pairs"].to_numpy()
    episode_survives = per_episode["n_survives"].to_numpy()

    if episode_sizes.sum() == 0:
        print("No confirmed pairs assignable to episodes -- cannot bootstrap.")
        return

    observed_rate = episode_survives.sum() / episode_sizes.sum()
    boot_rates = cluster_bootstrap_confirmation_rate(
        episode_sizes, episode_survives, n_boot=10_000, rng=np.random.default_rng(0)
    )
    ci_low, ci_high = np.percentile(boot_rates, [2.5, 97.5])

    print(f"\nObserved (naive pooled) survives-residual-correlation rate among confirmed "
          f"crisis-first pairs: {observed_rate:.4%}")
    print(f"Cluster-bootstrap 95% CI (episode-level resampling, n_boot=10000, "
          f"{len(episodes)} episodes): [{ci_low:.4%}, {ci_high:.4%}]")
    print(f"Per-episode breakdown:\n{per_episode}")

    pd.DataFrame([{
        "observed_rate": observed_rate, "ci_low": ci_low, "ci_high": ci_high,
        "n_confirmed_pairs": len(confirmed), "n_episodes": len(episodes),
    }]).to_parquet(_OUT_PATH)
    print(f"\nSaved to {_OUT_PATH}")


if __name__ == "__main__":
    main()
