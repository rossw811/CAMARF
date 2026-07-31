"""
CAMARF research/k_bahc_covariance_cleaning.py — comparison/diagnostic
script, NOT part of the production pipeline (2026-07-14, task #58).

Interpretation stated explicitly, not assumed: "k-BAHC" is implemented
here as k-cluster Bounded/Block Asset Hierarchical-Clustering covariance
cleaning — a hierarchical-clustering-based correlation matrix denoiser,
distinct from HRP (backtest.py's compute_hrp_weights, which uses
hierarchical clustering for PORTFOLIO WEIGHTING, not for producing a
cleaned covariance matrix as an estimator in its own right) and distinct
from Ledoit-Wolf shrinkage (already in production, backtest.py/
financial_turbulence_index.py, via sklearn.covariance.ledoit_wolf).

Method: cluster assets via scipy hierarchical clustering (average linkage
on a 1-correlation distance, same distance convention HRP already uses),
cut the dendrogram into k clusters, then reconstruct the correlation
matrix: within-cluster off-diagonal entries keep their observed sample
correlation; cross-cluster entries are shrunk toward the GLOBAL mean
cross-cluster correlation (reduces noise in the many small, likely-
spurious cross-cluster correlations while preserving the presumably more
reliable within-cluster structure). k is chosen by silhouette score on
the same clustering used for the reconstruction — not tuned by trying
several k and picking whichever produces the best out-of-sample result
(that would be Garden-of-Forking-Paths on the evaluation metric itself).

Evaluation: reuses the standard covariance-estimator evaluation from the
Ledoit-Wolf literature — rolling walk-forward global-minimum-variance
(GMV) portfolio, fit on a trailing window, realized variance measured on
the FOLLOWING out-of-sample window. Lower realized variance = better
covariance estimate. Compares three estimators on identical data/windows:
raw sample covariance, Ledoit-Wolf shrinkage, k-BAHC.

Usage:
    python research/k_bahc_covariance_cleaning.py --tf 1D --train-window 252 --test-window 21
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform
from sklearn.covariance import ledoit_wolf
from sklearn.metrics import silhouette_score

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from data import DataStore, _gap_aware_returns

_DEFAULT_PAIRS = [
    ("LNT", "VTR"), ("LNT", "WELL"), ("AME", "MAR"), ("CMS", "DUK"),
    ("EG", "WRB"), ("HAL", "NOV"), ("MET", "TMHC"), ("PFG", "STLD"),
    ("UMBF", "FHB"),
]


def _unique_symbols(pairs):
    out, seen = [], set()
    for a, b in pairs:
        for s in (a, b):
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


def build_return_matrix(symbols, tf_label):
    series = {}
    for sym in symbols:
        df = DataStore.load(sym, tf_label)
        if df is None or df.empty:
            continue
        series[sym] = pd.Series(_gap_aware_returns(df), index=df.index)
    mat = pd.DataFrame(series)
    return mat.dropna()  # need fully-overlapping bars for covariance work


def _best_k_by_silhouette(dist_matrix: np.ndarray, max_k: int) -> int:
    condensed = squareform(dist_matrix, checks=False)
    link = linkage(condensed, method="average")
    best_k, best_score = 2, -1.0
    n = dist_matrix.shape[0]
    for k in range(2, min(max_k, n - 1) + 1):
        labels = fcluster(link, k, criterion="maxclust")
        if len(set(labels)) < 2:
            continue
        try:
            score = silhouette_score(dist_matrix, labels, metric="precomputed")
        except Exception:
            continue
        if score > best_score:
            best_score, best_k = score, k
    return best_k, link


def clean_correlation_matrix(corr: np.ndarray, max_k: int = 6, force_k: int = None):
    """Core k-BAHC cleaning routine, operating on an ALREADY-COMPUTED
    correlation matrix directly. Split out from k_bahc_correlation()
    2026-07-21 for research/k_bahc_candidate_discovery.py's reuse: that
    script needs to clean UniverseFilter's own NaN-padding-aware,
    pairwise-complete Pearson matrix (analysis.py's _vectorized_pairwise_stats),
    which a naive returns.corr() call does NOT correctly reproduce (it
    doesn't handle UniverseFilter's per-asset different-length NaN-prefix
    padding scheme the same way) -- so the correlation-FROM-returns
    computation and the cleaning-of-an-existing-matrix concern must be
    separable. k_bahc_correlation() below is unchanged in behavior, now
    just a thin wrapper.

    force_k (added 2026-07-21, k-BAHC candidate-discovery follow-up #1):
    if given, bypasses silhouette-based k selection entirely and cuts the
    dendrogram at exactly this k. Silhouette consistently picked k=2 on the
    real full 1h universe (1567 assets) regardless of max_k up to 40 --
    this override exists specifically to test whether a deliberately finer
    (but not metric-optimized -- no Garden-of-Forking-Paths risk here since
    the caller states a k up front rather than searching over several and
    keeping whichever produces the best downstream result) partition
    surfaces genuine sub-cluster structure silhouette's global optimum
    misses at whole-universe scale."""
    corr = np.nan_to_num(corr, nan=0.0)
    dist = np.sqrt(np.clip((1 - corr) / 2, 0, None))
    np.fill_diagonal(dist, 0.0)
    if force_k is not None:
        condensed = squareform(dist, checks=False)
        link = linkage(condensed, method="average")
        k = force_k
    else:
        k, link = _best_k_by_silhouette(dist, max_k)
    labels = fcluster(link, k, criterion="maxclust")

    cleaned = corr.copy()
    cross_vals = []
    n = corr.shape[0]
    for i in range(n):
        for j in range(i + 1, n):
            if labels[i] != labels[j]:
                cross_vals.append(corr[i, j])
    cross_mean = float(np.mean(cross_vals)) if cross_vals else 0.0
    for i in range(n):
        for j in range(i + 1, n):
            if labels[i] != labels[j]:
                cleaned[i, j] = cleaned[j, i] = cross_mean
    return cleaned, k


def k_bahc_correlation(returns: pd.DataFrame, max_k: int = 6) -> np.ndarray:
    corr = returns.corr().values
    return clean_correlation_matrix(corr, max_k)


def _gmv_weights(cov: np.ndarray) -> np.ndarray:
    inv = np.linalg.pinv(cov)
    ones = np.ones(cov.shape[0])
    w = inv @ ones
    return w / w.sum()


def run(tf_label, train_window, test_window, max_k=6):
    symbols = _unique_symbols(_DEFAULT_PAIRS)
    ret_matrix = build_return_matrix(symbols, tf_label)
    n = len(ret_matrix)
    print(f"Return matrix: {n} bars x {ret_matrix.shape[1]} symbols "
          f"({ret_matrix.index.min().date()} to {ret_matrix.index.max().date()})")

    results = {"raw": [], "ledoit_wolf": [], "k_bahc": []}
    k_choices = []
    step = test_window
    start = train_window
    while start + test_window <= n:
        train = ret_matrix.iloc[start - train_window:start]
        test = ret_matrix.iloc[start:start + test_window]
        std = train.std().values.copy()
        std[std == 0] = 1e-12

        raw_corr = train.corr().values
        raw_cov = np.outer(std, std) * raw_corr
        lw_cov, _ = ledoit_wolf(train.values)
        kb_corr, k_used = k_bahc_correlation(train, max_k)
        kb_cov = np.outer(std, std) * kb_corr
        k_choices.append(k_used)

        test_cov_realized = test.cov().values  # realized out-of-sample covariance

        for name, cov in (("raw", raw_cov), ("ledoit_wolf", lw_cov), ("k_bahc", kb_cov)):
            w = _gmv_weights(cov)
            realized_var = float(w @ test_cov_realized @ w)
            results[name].append(realized_var)

        start += step

    print(f"\n{len(results['raw'])} walk-forward windows "
          f"(train={train_window} bars, test={test_window} bars). "
          f"k-BAHC chose k in range [{min(k_choices)}, {max(k_choices)}], "
          f"median={int(np.median(k_choices))}.")
    for name in ("raw", "ledoit_wolf", "k_bahc"):
        vals = np.array(results[name])
        print(f"  {name}: mean realized variance={vals.mean():.6e}, "
              f"median={np.median(vals):.6e}, std={vals.std():.6e}")

    raw_vals = np.array(results["raw"])
    lw_vals = np.array(results["ledoit_wolf"])
    kb_vals = np.array(results["k_bahc"])
    print(f"\nk-BAHC vs raw: lower realized variance in "
          f"{(kb_vals < raw_vals).sum()}/{len(raw_vals)} windows.")
    print(f"k-BAHC vs Ledoit-Wolf: lower realized variance in "
          f"{(kb_vals < lw_vals).sum()}/{len(lw_vals)} windows.")

    out_df = pd.DataFrame(results)
    out_df["k_used"] = k_choices
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"k_bahc_covariance_cleaning_{tf_label}.parquet")
    out_df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


def main():
    p = argparse.ArgumentParser(description="k-BAHC hierarchical-clustering covariance cleaning comparison (2026-07-14)")
    p.add_argument("--tf", default="1D")
    p.add_argument("--train-window", type=int, default=252)
    p.add_argument("--test-window", type=int, default=21)
    p.add_argument("--max-k", type=int, default=6)
    args = p.parse_args()
    run(args.tf, args.train_window, args.test_window, args.max_k)


if __name__ == "__main__":
    main()
