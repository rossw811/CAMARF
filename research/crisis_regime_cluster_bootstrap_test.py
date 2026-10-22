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

D12 REDESIGN (Ross 2026-10-19, "y"; adversarial review of a51f926c): the cluster-RI CI above assumes crisis episodes
and calm years are exchangeable, but calm confirmation rates fall over time (right-censoring) and crisis episodes sit
in high-rate years -- under an era-matched null with no crisis effect it covered 0 in 31% of worlds. MAIN now: crisis-
first vs calm-first discoveries WITHIN the same calendar year, d_y = crisis rate - calm rate, mean over years with
both kinds, sign-flip randomization across years, CI by test inversion (within_year_ci). ri_ci / wild_cluster_ci are
kept for their tests only and are NOT run or cited. debug/_verify_crisis_regime_within_year_d12.py

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


def within_year_ci(df: pd.DataFrame, alpha: float = 0.05, n_sim: int = 20_000, rng=None, grid_n: int = 401,
                   exact_max_years: int = 16) -> dict:
    """MAIN (D12 redesign). df: one row per pair with year (discovery calendar year), crisis (bool), confirmed (bool).
    d_y = crisis rate - calm rate within year y, over years with both kinds; statistic = mean(d_y). Null for a shift
    delta: d_y - delta symmetric about 0 (sign-flip across years; exact enumeration for <= exact_max_years). CI = the
    deltas with two-sided p > alpha. min_p_achievable = 2^(1-K) for K years: with K < 6 nothing reaches 5%."""
    rng = rng or np.random.default_rng(0)
    g = df.groupby(["year", "crisis"])["confirmed"].agg(["mean", "size"]).unstack("crisis")
    both = g["mean"].notna().all(axis=1) if g.shape[1] == 4 else pd.Series(False, index=g.index)
    d = (g.loc[both, ("mean", True)] - g.loc[both, ("mean", False)]).to_numpy(float)
    K = len(d)
    out = {"n_years": int(K), "n_years_one_kind_only": int((~both).sum()),
           "min_p_achievable": float(2.0 ** (1 - K)) if K else 1.0,
           "rate_diff_mean_within_year": float(d.mean()) if K else float("nan"),
           "years": [int(y) for y in g.index[both]]}
    if K == 0:
        return {**out, "ci_low": float("nan"), "ci_high": float("nan"), "unbounded": True}
    if K <= exact_max_years:
        signs = 1 - 2 * ((np.arange(2 ** K)[:, None] >> np.arange(K)) & 1)
    else:
        signs = 1 - 2 * rng.integers(0, 2, size=(n_sim, K))
    span = 3 * max(np.abs(d).max(), 1e-6)
    grid = np.linspace(d.mean() - span, d.mean() + span, grid_n)
    ps = np.array([np.mean(np.abs(signs @ (d - dl)) >= abs((d - dl).sum()) - 1e-15) for dl in grid])
    keep = grid[ps > alpha]
    lo, hi = (float(keep.min()), float(keep.max())) if len(keep) else (float("nan"), float("nan"))
    return {**out, "ci_low": lo, "ci_high": hi,
            "unbounded": bool(len(keep) and (ps[0] > alpha or ps[-1] > alpha)), "exact": bool(K <= exact_max_years)}


def comparison_frame(pairs: pd.DataFrame, reference: str) -> pd.DataFrame:
    """Rows for crisis-first vs the reference group (review of N4, 2026-10-22): "calm" = calm-first pairs only (what the
    claim says; the earlier run used every non-crisis pair), "non_crisis" = every other pair (kept as an arm).
    Adds year, crisis and reappears_any: any later window (n_windows_tested > 1) -- the symmetric reappearance arm; the
    published reappears_in_different_regime counts only later windows in another regime, which short crisis spells
    satisfy mechanically."""
    p = pairs if reference == "non_crisis" else pairs[pairs["first_regime"].isin(["crisis", "calm"])]
    d = pd.to_datetime(p["first_window_end_date"])
    return p.assign(year=d.dt.year, crisis=p["first_regime"] == "crisis", reappears_any=p["n_windows_tested"] > 1)


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

    # D12 redesign (Ross 2026-10-19): within-year crisis vs calm, sign-flip across years. Cluster RI / wild are not run.
    pairs["first_window_end_date"] = pd.to_datetime(pairs["first_window_end_date"])
    rows = []
    for reference in ("calm", "non_crisis"):
        base = comparison_frame(pairs, reference)
        for metric, col in [("confirmation_rate", "confirmed"), ("reappearance_rate", "reappears_in_different_regime"),
                            ("reappearance_any_rate", "reappears_any")]:
            if col not in base.columns:
                log.warning(f"{col} not in the pair table -- {metric} skipped")
                continue
            r = within_year_ci(base[["year", "crisis"]].assign(confirmed=base[col].astype(bool)),
                               rng=np.random.default_rng(0))
            log.info(f"--- {metric}, crisis vs {reference} (D12 within-year) --- mean difference within year "
                     f"{r['rate_diff_mean_within_year']:+.4%} over {r['n_years']} years with both kinds "
                     f"({r['n_years_one_kind_only']} years one kind only); 95% CI [{r['ci_low']:+.4%}, {r['ci_high']:+.4%}]"
                     + ("  [CI unbounded on the grid]" if r["unbounded"] else "")
                     + f"; min achievable p {r['min_p_achievable']:.4f}")
            rows.append({"metric": metric, "reference": reference, **{k: v for k, v in r.items() if k != "years"},
                         "years": ",".join(map(str, r["years"]))})

    pd.DataFrame(rows).to_parquet(_OUT_PATH, index=False)   # always rewritten
    log.info(f"Saved -> {_OUT_PATH}")
    log.info("crisis_regime_cluster_bootstrap_test.py complete")


if __name__ == "__main__":
    main()
