"""
research/crisis_regime_episode_clustering_check.py -- does the crisis-vs-calm
confirmation-rate and reappearance-rate result from crisis_regime_correlation_
diagnostic.py survive once crisis-first pairs are grouped into distinct
historical EPISODES instead of treated as 11,715 independent draws?

Motivation (2026-09-02, adversarial review of PAPER_MAGNITUDE.md): the
two-proportion z-tests in crisis_regime_correlation_diagnostic.py's
summarize() treat every crisis-first pair as an independent Bernoulli trial.
That assumption is almost certainly wrong -- "first qualifying window falls
in a crisis-VIX regime" is not spread uniformly through history, it clusters
into a handful of real historical crisis periods (2008-09 GFC, 2020 COVID,
etc.), each contributing thousands of pairs whose discovery is driven by the
SAME market-wide shock, not independent events. If confirmation is
concentrated in one or two episodes, the true effective sample size behind
the p=0.0056 confirmation-rate result is far smaller than n=11,715 suggests,
and the finding needs to be reported at the episode level, not just the
pooled pair level, to be honest about what's actually been shown.

This script does NOT replace crisis_regime_correlation_diagnostic.py's own
tests -- it adds an episode-level robustness check on top of them, using the
same already-computed, already-verified pair-level table
(crisis_regime_correlation_diagnostic_pairs.parquet) rather than re-deriving
anything from raw data.

Verified against synthetic ground truth first:
debug/_verify_crisis_regime_episode_clustering_check.py.

Usage:
    python research/crisis_regime_episode_clustering_check.py
"""
import logging
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PAIRS_PATH = os.path.join(_ROOT, "output", "research",
                            "crisis_regime_correlation_diagnostic_pairs.parquet")
_OUT_PATH = os.path.join(_ROOT, "output", "research",
                          "crisis_regime_episode_clustering.parquet")

log = logging.getLogger("crisis_regime_episode_clustering_check")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)


def cluster_into_episodes(dates: pd.Series, gap_months: int = 3) -> pd.Series:
    """Groups a series of dates into contiguous 'episodes': a new episode
    starts whenever the gap since the previous distinct calendar month with
    an observation exceeds `gap_months`. Returns an episode-id Series aligned
    to `dates`'s index. Deterministic, not tuned to produce a particular
    episode count -- the 3-month gap is a fixed, disclosed choice (roughly
    "no new crisis-first pairs for a full quarter means the prior episode
    has ended"), not chosen after seeing the result."""
    months = dates.dt.to_period("M")
    distinct_months = sorted(months.unique())
    episode_of_month = {}
    episode_id = 0
    prev = None
    for m in distinct_months:
        if prev is not None and (m - prev).n > gap_months:
            episode_id += 1
        episode_of_month[m] = episode_id
        prev = m
    return months.map(episode_of_month)


def summarize_by_episode(pairs_df: pd.DataFrame) -> pd.DataFrame:
    """One row per crisis-discovery episode: pair count, confirmation count/
    rate, and reappearance count/rate. `pairs_df` must already be filtered
    to first_regime == 'crisis' and have an 'episode' column."""
    return pairs_df.groupby("episode").agg(
        n_pairs=("confirmed", "size"),
        n_confirmed=("confirmed", "sum"),
        n_reappear=("reappears_in_different_regime", "sum"),
        episode_start=("first_window_end_date", "min"),
        episode_end=("first_window_end_date", "max"),
    ).assign(
        confirmation_rate=lambda d: d["n_confirmed"] / d["n_pairs"],
        reappearance_rate=lambda d: d["n_reappear"] / d["n_pairs"],
    )


def main():
    _setup_logging()
    log.info("=== crisis_regime_episode_clustering_check.py: does the crisis-vs-calm "
             "result survive grouping crisis-first pairs into distinct historical "
             "episodes instead of treating them as independent draws? ===")

    if not os.path.exists(_PAIRS_PATH):
        log.error(f"{_PAIRS_PATH} does not exist -- run "
                  f"research/crisis_regime_correlation_diagnostic.py first.")
        sys.exit(1)

    df = pd.read_parquet(_PAIRS_PATH)
    df["first_window_end_date"] = pd.to_datetime(df["first_window_end_date"])
    crisis = df[df["first_regime"] == "crisis"].copy()
    crisis["episode"] = cluster_into_episodes(crisis["first_window_end_date"])
    log.info(f"{len(crisis)} crisis-first pairs cluster into "
             f"{crisis['episode'].nunique()} distinct episodes (3-month gap rule) "
             f"-- NOT {len(crisis)} independent draws, the assumption the pooled "
             f"two-proportion z-test implicitly relies on.")

    by_episode = summarize_by_episode(crisis)
    by_episode.to_parquet(_OUT_PATH)
    log.info(f"\n{by_episode.to_string()}")

    n_episodes = len(by_episode)
    n_episodes_with_confirmation = (by_episode["n_confirmed"] > 0).sum()
    top2 = by_episode.nlargest(2, "n_confirmed")
    top2_share = top2["n_confirmed"].sum() / by_episode["n_confirmed"].sum()
    log.info(f"Episodes with >=1 confirmation: {n_episodes_with_confirmation} of {n_episodes}")
    log.info(f"Top 2 episodes by confirmation count carry "
             f"{top2['n_confirmed'].sum()}/{by_episode['n_confirmed'].sum()} "
             f"({top2_share:.1%}) of all crisis-first confirmations: "
             f"{top2.index.tolist()}")

    reappear_rates_excl_recent = by_episode.sort_values("episode_end").iloc[:-2]["reappearance_rate"]
    log.info(f"Reappearance rate range, excluding the 2 most recent episodes "
             f"(right-censoring risk -- not enough subsequent history to observe "
             f"reappearance yet): [{reappear_rates_excl_recent.min():.3f}, "
             f"{reappear_rates_excl_recent.max():.3f}], "
             f"median={reappear_rates_excl_recent.median():.3f}")

    # GAP-RULE SENSITIVITY (2026-09-02, Ross: brainstorm item -- "sensitivity-check the
    # episode-clustering gap rule"): the 3-month threshold is a fixed, disclosed choice, but
    # was never checked against alternatives -- a skeptical reader's natural next question.
    log.info("Gap-rule sensitivity check (does the concentration finding depend on the "
             "specific 3-month threshold chosen?):")
    for gap in (1, 2, 3, 4, 6):
        crisis["episode"] = cluster_into_episodes(crisis["first_window_end_date"], gap_months=gap)
        alt_by_episode = summarize_by_episode(crisis)
        alt_top2 = alt_by_episode.nlargest(2, "n_confirmed")
        alt_top2_share = alt_top2["n_confirmed"].sum() / alt_by_episode["n_confirmed"].sum()
        log.info(f"  gap={gap}mo: {len(alt_by_episode)} episodes, "
                 f"top-2 confirmation share={alt_top2_share:.3f}")

    log.info("crisis_regime_episode_clustering_check.py complete")


if __name__ == "__main__":
    main()
