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

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PAIRS_PATH = os.path.join(_ROOT, "output", "research",
                            "crisis_regime_correlation_diagnostic_pairs.parquet")
_CRISIS_PAIRS_PATH = os.path.join(_ROOT, "output", "research", "crisis_regime_episode_crisis_pairs.parquet")
_D3_PATH = os.path.join(_ROOT, "output", "research", "crisis_regime_episode_crisis_vs_calm_ri.parquet")
_D4_PATH = os.path.join(_ROOT, "output", "research", "crisis_regime_episode_gap_null.parquet")
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


def crisis_calm_cluster_ri(df: pd.DataFrame, n_sim: int = 10_000, rng=None) -> dict:
    """D3 (Ross 2026-10-12, R3.5): episode-level crisis-vs-calm test by randomization inference over CLUSTERS.
    df: one row per pair with `cluster` (a crisis episode or a calm calendar year), `crisis` (bool, constant within a
    cluster) and `confirmed` (bool). Statistic: pooled crisis confirmation rate minus pooled calm rate. Null: the
    crisis label is exchangeable across clusters -- shuffle which clusters are 'crisis' (their number fixed), so
    within-cluster dependence is kept intact. One-sided p = share of shuffles with a difference >= observed."""
    rng = rng or np.random.default_rng(0)
    g = df.groupby("cluster").agg(n=("confirmed", "size"), k=("confirmed", "sum"), crisis=("crisis", "first"))
    n, k, lab = g["n"].to_numpy(float), g["k"].to_numpy(float), g["crisis"].to_numpy(bool)

    def diff(mask):
        return k[mask].sum() / n[mask].sum() - k[~mask].sum() / n[~mask].sum()
    obs = diff(lab)
    sims = np.array([diff(rng.permutation(lab)) for _ in range(n_sim)])
    return {"rate_diff": float(obs), "p_value": float((1 + np.sum(sims >= obs - 1e-15)) / (n_sim + 1)),
            "n_crisis_clusters": int(lab.sum()), "n_calm_clusters": int((~lab).sum()), "n_sim": n_sim}


def gap_null_table(crisis: pd.DataFrame, gaps=(1, 2, 3, 4, 6), n_sim: int = 20_000, rng=None) -> pd.DataFrame:
    """D4 (Ross 2026-10-12, R3.6): per episode gap rule, the observed top-2 share of confirmations NEXT TO its null --
    research/crisis_regime_concentration_significance_test.component_max2_test with episodes defined by that gap
    (confirmations sharing a stock are one unit). A share that rises with the gap only because episodes merge is
    visible as a rising null too."""
    from research.crisis_regime_concentration_significance_test import component_max2_test
    rng = rng or np.random.default_rng(0)
    rows = []
    for gap in gaps:
        c = crisis.assign(episode=cluster_into_episodes(pd.to_datetime(crisis["first_window_end_date"]), gap_months=gap))
        sizes = c.groupby("episode").size().sort_index().to_numpy()
        conf = c[c["confirmed"].astype(bool)][["symbol_a", "symbol_b", "episode"]]
        if conf.empty:
            continue
        r = component_max2_test(conf, sizes, n_sim=n_sim, rng=rng)
        rows.append({"gap_months": gap, "n_episodes": len(sizes), "observed_top2_share": r["observed_max2_share"],
                     "null_mean_top2_share": r["null_mean_max2_share"], "p_value": r["p_value"], "n_units": r["n_units"]})
    return pd.DataFrame(rows)


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

    # Pair-level crisis table for the concentration test's component-level null (D2)
    crisis.to_parquet(_CRISIS_PAIRS_PATH)

    # D3 (Ross 2026-10-12, R3.5): episode-level crisis-vs-calm test -- clusters = crisis episodes + calm calendar
    # years; randomization inference over clusters keeps within-episode dependence intact
    calm = df[df["first_regime"] != "crisis"].copy()
    clus = pd.concat([crisis.assign(cluster="crisis_" + crisis["episode"].astype(str), crisis_flag=True),
                      calm.assign(cluster="calm_" + calm["first_window_end_date"].dt.year.astype(str), crisis_flag=False)])
    ri = crisis_calm_cluster_ri(clus.rename(columns={"crisis_flag": "crisis"})[["cluster", "crisis", "confirmed"]],
                                n_sim=20_000, rng=np.random.default_rng(0))
    log.info(f"D3 episode-level crisis-vs-calm (cluster randomization inference): crisis minus calm confirmation rate "
             f"{ri['rate_diff']:+.5f}, p = {ri['p_value']:.4f} ({ri['n_crisis_clusters']} crisis episodes vs "
             f"{ri['n_calm_clusters']} calm years)")
    pd.DataFrame([ri]).to_parquet(_D3_PATH)

    # D4 (Ross 2026-10-12, R3.6): gap-rule sensitivity WITH a null per gap (component-level, D2)
    gt = gap_null_table(crisis, gaps=(1, 2, 3, 4, 6), n_sim=20_000, rng=np.random.default_rng(0))
    log.info("D4 gap-rule sensitivity (observed top-2 share vs its null):\n" + gt.to_string(index=False))
    gt.to_parquet(_D4_PATH)

    log.info("crisis_regime_episode_clustering_check.py complete")


if __name__ == "__main__":
    main()
