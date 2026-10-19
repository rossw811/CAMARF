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

D12 / R6.9 (Ross 2026-10-12, details 2026-10-17; fixed 2026-10-19): the bootstrap above held the calm rate fixed and
read "share of crisis draws <= calm rate" as a p-value -- the bootstrap is not centred on a null, so it is not one;
with 12 very unequal clusters (93% of confirmations in 2) a pairs cluster bootstrap is unreliable (Cameron, Gelbach &
Miller 2008). Now, on the D3 clusters (crisis episodes + calm calendar years): MAIN = randomization inference over
clusters, reported as a CI by test inversion (ri_ci); CHECK = wild cluster bootstrap, Webb (2014) six-point weights,
percentile-t with the CR1 standard error (wild_cluster_ci). CIs only -- no p-value. With 93% of the signal in 2 of 12
clusters an inconclusive CI is a real result. The old resampling function is kept, superseded, for its own test.
debug/_verify_crisis_regime_cluster_ci_d12.py

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
_CRISIS_PAIRS_PATH = os.path.join(_ROOT, "output", "research", "crisis_regime_episode_crisis_pairs.parquet")  # D3 table
OUTPUT_COLUMNS = ["metric", "observed_crisis_rate", "observed_calm_rate", "rate_diff", "n_crisis_clusters",
                  "n_calm_clusters", "ri_ci_low", "ri_ci_high", "ri_ci_at_grid_edge", "wild_ci_low", "wild_ci_high",
                  "wild_se_cr1"]

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
    """SUPERSEDED by ri_ci / wild_cluster_ci (D12); kept for its own pinned test, no longer called by main().
    Resamples the episode-level (size, confirmed) pairs WITH REPLACEMENT
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


def _rates(n, k, lab):
    return k[lab].sum() / n[lab].sum(), k[~lab].sum() / n[~lab].sum()


def ri_ci(n, k, lab, alpha: float = 0.05, n_sim: int = 10_000, rng=None, grid_n: int = 201) -> dict:
    """MAIN (D12): CI for (pooled crisis rate - pooled calm rate) by inverting cluster randomization inference (the D3
    test). For a shift delta, crisis clusters' events become k - delta*n; the crisis label is then exchangeable across
    clusters (their number fixed). delta is in the CI when the two-sided permutation p (statistic centred on its
    permutation mean) exceeds alpha. n, k, lab: per-cluster pairs, events, crisis flag."""
    rng = rng or np.random.default_rng(0)
    n, k, lab = np.asarray(n, float), np.asarray(k, float), np.asarray(lab, bool)
    rc, rm = _rates(n, k, lab)
    obs = rc - rm
    perms = rng.permuted(np.tile(lab, (n_sim, 1)), axis=1).astype(float)
    Pn, Tn = perms @ n, n.sum()

    def pval(delta):
        ka = k - delta * n * lab
        Pk, Tk = perms @ ka, ka.sum()
        sims = Pk / Pn - (Tk - Pk) / (Tn - Pn)
        m = sims.mean()
        t_obs = ka[lab].sum() / n[lab].sum() - ka[~lab].sum() / n[~lab].sum()
        return (1 + np.sum(np.abs(sims - m) >= abs(t_obs - m) - 1e-15)) / (n_sim + 1), sims.std()

    _, sd = pval(obs)
    sd = sd if sd > 0 else max(abs(obs), 1e-6)
    grid = np.linspace(obs - 6 * sd, obs + 6 * sd, grid_n)
    ps = np.array([pval(d)[0] for d in grid])
    keep = grid[ps > alpha]
    lo, hi = (float(keep.min()), float(keep.max())) if len(keep) else (float("nan"), float("nan"))
    return {"ci_low": lo, "ci_high": hi, "rate_diff": float(obs), "delta_max_p": float(grid[np.argmax(ps)]),
            "grid_step": float(grid[1] - grid[0]),
            "at_grid_edge": bool(len(keep) and (ps[0] > alpha or ps[-1] > alpha)), "n_sim": n_sim}


def webb_weights() -> np.ndarray:
    """Webb (2014) six-point distribution: +-sqrt(1/2), +-1, +-sqrt(3/2), equal probability (mean 0, variance 1)."""
    return np.array([-np.sqrt(1.5), -1.0, -np.sqrt(0.5), np.sqrt(0.5), 1.0, np.sqrt(1.5)])


def _cr1(U, lab, Nc, Nm, G):
    return np.sqrt(G / (G - 1) * ((U[..., lab] ** 2).sum(-1) / Nc ** 2 + (U[..., ~lab] ** 2).sum(-1) / Nm ** 2))


def cr1_se(n, k, lab) -> float:
    """CR1 cluster-robust SE of the crisis coefficient in the linear probability model y = a + b*crisis (pair level),
    from per-cluster residual sums U_g."""
    n, k, lab = np.asarray(n, float), np.asarray(k, float), np.asarray(lab, bool)
    rc, rm = _rates(n, k, lab)
    U = np.where(lab, k - n * rc, k - n * rm)
    return float(_cr1(U, lab, n[lab].sum(), n[~lab].sum(), len(n)))


def wild_cluster_ci(n, k, lab, alpha: float = 0.05, n_boot: int = 9_999, rng=None) -> dict:
    """CHECK (D12): wild cluster bootstrap-t CI for the crisis coefficient, Webb weights, unrestricted residuals,
    CR1 SE recomputed in every draw."""
    rng = rng or np.random.default_rng(0)
    n, k, lab = np.asarray(n, float), np.asarray(k, float), np.asarray(lab, bool)
    rc, rm = _rates(n, k, lab)
    b = rc - rm
    U = np.where(lab, k - n * rc, k - n * rm)
    Nc, Nm, G = n[lab].sum(), n[~lab].sum(), len(n)
    se = float(_cr1(U, lab, Nc, Nm, G))
    W = rng.choice(webb_weights(), size=(n_boot, G))
    WU = W * U
    dc, dm = WU[:, lab].sum(1) / Nc, WU[:, ~lab].sum(1) / Nm
    Ustar = WU - n * np.where(lab, dc[:, None], dm[:, None])
    t = (dc - dm) / _cr1(Ustar, lab, Nc, Nm, G)
    qlo, qhi = np.quantile(t, [alpha / 2, 1 - alpha / 2])
    return {"ci_low": float(b - qhi * se), "ci_high": float(b - qlo * se), "se_cr1": se, "rate_diff": float(b),
            "n_boot": n_boot}


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

    if not os.path.exists(_CRISIS_PAIRS_PATH):
        log.error(f"{_CRISIS_PAIRS_PATH} missing -- run crisis_regime_episode_clustering_check.py first (D3 writes it).")
        sys.exit(1)
    crisis = pd.read_parquet(_CRISIS_PAIRS_PATH)
    calm_all = pairs[pairs["first_regime"] != "crisis"].copy()          # same clusters as D3: calm calendar years
    calm_all["first_window_end_date"] = pd.to_datetime(calm_all["first_window_end_date"])
    clus = pd.concat([crisis.assign(cluster="crisis_" + crisis["episode"].astype(str), crisis_flag=True),
                      calm_all.assign(cluster="calm_" + calm_all["first_window_end_date"].dt.year.astype(str),
                                      crisis_flag=False)], ignore_index=True)
    rows = []
    for metric, col in [("confirmation_rate", "confirmed"), ("reappearance_rate", "reappears_in_different_regime")]:
        if col not in clus.columns:
            log.warning(f"{col} not in the pair tables -- {metric} skipped")
            continue
        g = clus.groupby("cluster").agg(n=(col, "size"), k=(col, "sum"), crisis=("crisis_flag", "first"))
        n, k, lab = g["n"].to_numpy(float), g["k"].to_numpy(float), g["crisis"].to_numpy(bool)
        ri = ri_ci(n, k, lab, n_sim=10_000, rng=np.random.default_rng(0))
        wild = wild_cluster_ci(n, k, lab, n_boot=9_999, rng=np.random.default_rng(0))
        rc, rm = _rates(n, k, lab)
        log.info(f"--- {metric} (D12) --- crisis {rc:.4%} vs calm {rm:.4%}, difference {rc - rm:+.4%} over "
                 f"{int(lab.sum())} crisis episodes and {int((~lab).sum())} calm years")
        log.info(f"  MAIN randomization-inference 95% CI (test inversion): [{ri['ci_low']:+.4%}, {ri['ci_high']:+.4%}]"
                 + ("  [CI reaches the grid edge -- widen]" if ri["at_grid_edge"] else ""))
        log.info(f"  CHECK wild cluster bootstrap-t 95% CI (Webb weights, CR1 SE {wild['se_cr1']:.4%}): "
                 f"[{wild['ci_low']:+.4%}, {wild['ci_high']:+.4%}]")
        rows.append({"metric": metric, "observed_crisis_rate": rc, "observed_calm_rate": rm, "rate_diff": rc - rm,
                     "n_crisis_clusters": int(lab.sum()), "n_calm_clusters": int((~lab).sum()),
                     "ri_ci_low": ri["ci_low"], "ri_ci_high": ri["ci_high"], "ri_ci_at_grid_edge": ri["at_grid_edge"],
                     "wild_ci_low": wild["ci_low"], "wild_ci_high": wild["ci_high"], "wild_se_cr1": wild["se_cr1"]})

    pd.DataFrame(rows, columns=OUTPUT_COLUMNS).to_parquet(_OUT_PATH, index=False)   # always rewritten
    log.info(f"Saved -> {_OUT_PATH}")
    log.info("crisis_regime_cluster_bootstrap_test.py complete")


if __name__ == "__main__":
    main()
