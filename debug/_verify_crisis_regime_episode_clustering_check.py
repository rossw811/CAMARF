"""
debug/_verify_crisis_regime_episode_clustering_check.py -- synthetic checks
for research/crisis_regime_episode_clustering_check.py, run BEFORE trusting
it against real crisis_regime_correlation_diagnostic_pairs.parquet data.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.crisis_regime_episode_clustering_check import (
    cluster_into_episodes, summarize_by_episode,
)

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


print("Check 1: cluster_into_episodes -- a >3-month gap starts a new episode")
dates = pd.Series(pd.to_datetime([
    "2008-09-15", "2008-10-01", "2008-12-01",   # episode 0: gaps of 1, 2 months
    "2011-08-01", "2011-09-15",                  # episode 1: gap from prev is 32 months
    "2011-11-01",                                 # still episode 1: gap of 1.5 months from prior
]))
episodes = cluster_into_episodes(dates)
check("first 3 dates (tight cluster) are the SAME episode",
      episodes.iloc[0] == episodes.iloc[1] == episodes.iloc[2])
check("2011-08 starts a NEW episode (32-month gap from 2008-12)",
      episodes.iloc[3] != episodes.iloc[0])
check("2011-08, 2011-09, 2011-11 are all the SAME episode (gaps <=3mo)",
      episodes.iloc[3] == episodes.iloc[4] == episodes.iloc[5])
check("exactly 2 distinct episodes produced", episodes.nunique() == 2)

print("Check 2: cluster_into_episodes -- exactly a 3-month gap does NOT start a new episode "
      "(boundary case)")
boundary_dates = pd.Series(pd.to_datetime(["2020-01-15", "2020-04-15"]))  # exactly 3 months apart
boundary_episodes = cluster_into_episodes(boundary_dates)
check("a gap of exactly 3 months stays in the SAME episode (> not >=)",
      boundary_episodes.iloc[0] == boundary_episodes.iloc[1])

print("Check 3: cluster_into_episodes -- a gap of 4 months DOES start a new episode")
just_over_dates = pd.Series(pd.to_datetime(["2020-01-15", "2020-05-15"]))  # 4 months apart
just_over_episodes = cluster_into_episodes(just_over_dates)
check("a gap of 4 months (>3) starts a NEW episode",
      just_over_episodes.iloc[0] != just_over_episodes.iloc[1])

print("Check 4: summarize_by_episode -- confirmation/reappearance rates computed correctly per episode")
synthetic_pairs = pd.DataFrame({
    "confirmed": [True, True, False, False, True],
    "reappears_in_different_regime": [True, False, False, True, True],
    "first_window_end_date": pd.to_datetime(
        ["2008-09-01", "2008-10-01", "2008-11-01", "2011-08-01", "2011-09-01"]),
    "episode": [0, 0, 0, 1, 1],
})
by_episode = summarize_by_episode(synthetic_pairs)
check("episode 0: n_pairs=3, n_confirmed=2, confirmation_rate=2/3",
      by_episode.loc[0, "n_pairs"] == 3 and by_episode.loc[0, "n_confirmed"] == 2
      and abs(by_episode.loc[0, "confirmation_rate"] - 2 / 3) < 1e-9)
check("episode 1: n_pairs=2, n_confirmed=1, confirmation_rate=1/2",
      by_episode.loc[1, "n_pairs"] == 2 and by_episode.loc[1, "n_confirmed"] == 1
      and abs(by_episode.loc[1, "confirmation_rate"] - 0.5) < 1e-9)
check("episode 0: reappearance_rate = 1/3 (only the first row reappears)",
      abs(by_episode.loc[0, "reappearance_rate"] - 1 / 3) < 1e-9)
check("episode 0 start/end dates are the min/max of its rows",
      by_episode.loc[0, "episode_start"] == pd.Timestamp("2008-09-01")
      and by_episode.loc[0, "episode_end"] == pd.Timestamp("2008-11-01"))

print("Check 5: a real-world-shaped scenario -- confirmation concentrated in one episode "
      "of many is correctly surfaced, not averaged away")
concentrated = pd.DataFrame({
    "confirmed": [True] * 20 + [False] * 4080 + [False] * 900,  # episode 0 has all confirmations
    "reappears_in_different_regime": [True] * 5000,
    "first_window_end_date": (
        [pd.Timestamp("2008-10-01")] * 4100 + [pd.Timestamp("2011-08-01")] * 900
    ),
    "episode": [0] * 4100 + [1] * 900,
})
by_episode_concentrated = summarize_by_episode(concentrated)
check("episode 0 carries ALL 20 confirmations (concentration correctly visible per-episode)",
      by_episode_concentrated.loc[0, "n_confirmed"] == 20
      and by_episode_concentrated.loc[1, "n_confirmed"] == 0)

# D3 / D4 (Ross 2026-10-12, R3.5 / R3.6; added 2026-10-15, written before the code)
try:
    from research.crisis_regime_episode_clustering_check import crisis_calm_cluster_ri, gap_null_table
    def _world(rng, effect, n_crisis=10, n_calm=30, per=200):
        rows = []
        for c in range(n_crisis + n_calm):
            crisis = c < n_crisis
            base = np.clip(rng.normal(0.05, 0.03), 0.001, 0.5)          # cluster-level heterogeneity
            p = min(base * (effect if crisis else 1.0), 0.9)
            rows += [{"cluster": c, "crisis": crisis, "confirmed": bool(x)} for x in rng.random(per) < p]
        return pd.DataFrame(rows)
    print("Check D3a: cluster randomization inference is sized (no crisis effect, 120 seeds)")
    ps = [crisis_calm_cluster_ri(_world(np.random.default_rng(s), 1.0), n_sim=400, rng=np.random.default_rng(s))["p_value"] for s in range(120)]
    rate = float(np.mean(np.array(ps) < 0.05))
    check(f"false-positive rate at 5% <= 0.10 [{rate:.3f}]", rate <= 0.10)
    print("Check D3b: a real crisis effect (rate x3) is detected")
    r = crisis_calm_cluster_ri(_world(np.random.default_rng(999), 3.0), n_sim=2000, rng=np.random.default_rng(1))
    check(f"p < 0.01 [{r['p_value']:.4f}], diff > 0 [{r['rate_diff']:.4f}]", r["p_value"] < 0.01 and r["rate_diff"] > 0)
    print("Check D4: gap_null_table reports observed top-2 share and its null per gap")
    dates = pd.Series(pd.to_datetime(["2008-01-15"] * 40 + ["2008-06-15"] * 40 + ["2011-08-15"] * 40 + ["2020-03-15"] * 40))
    cr = pd.DataFrame({"first_window_end_date": dates, "confirmed": [True] * 6 + [False] * 154,
                       "symbol_a": [f"a{i}" for i in range(160)], "symbol_b": [f"b{i}" for i in range(160)]})
    T = gap_null_table(cr, gaps=(1, 3, 6), n_sim=2000, rng=np.random.default_rng(2))
    check("one row per gap with observed / null mean / p", list(T["gap_months"]) == [1, 3, 6]
          and {"observed_top2_share", "null_mean_top2_share", "p_value", "n_episodes"} <= set(T.columns))
    check("coarser gap -> fewer episodes", T["n_episodes"].is_monotonic_decreasing)
except ImportError as e:
    check(f"D3/D4 functions exist ({e})", False)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
