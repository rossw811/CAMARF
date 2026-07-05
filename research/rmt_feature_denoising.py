"""
CAMARF rmt_feature_denoising.py — comparison/diagnostic method, NOT part
of the production pipeline.

Answers Ross's question (2026-07-05): CAMARF has PCA-based dimensionality
reduction already in production (`analysis.py`'s `EigenportfolioDecomposer`,
Marchenko-Pastur denoising for eigenportfolio construction/confirmatory
tiering) but NOT anywhere in `ml.py`'s meta-labeler feature pipeline
(confirmed directly by grep — zero PCA, zero `n_components` in ml.py).
This applies the SAME already-production eigendecomposition machinery to
`ml.py`'s own 8-feature set (`_FEATURE_COLS`) instead, to see which
features are genuinely redundant vs. carry independent signal — a real
gap-filler, not a replacement for a rule that doesn't exist yet (checked
directly: PAPER.md Section 10's "flat 0.85-correlation feature-drop rule"
was a planned Stage-2 rule for a feature set that was never decided —
Stage 1's actual 8 features, used here, have no existing correlation-
pruning step at all).

Method (RMT denoising + detoning + a practical version of ONC):
  1. Build real labeled examples across every confirmed pair via ml.py's
     own `_build_examples_for_pair` (temporarily redirecting `_tf_dirname`
     per timeframe to whichever archived/live results directory actually
     has data — the same stale-directory resolution used throughout this
     session — rather than reimplementing the entry-event/labeling logic,
     which risks silently diverging from production).
  2. Correlation matrix over the 8 `_FEATURE_COLS`.
  3. Marchenko-Pastur threshold (`EigenportfolioDecomposer._eigendecompose`,
     reused directly, not reimplemented) separates signal eigenvalues
     (above the MP noise edge) from noise eigenvalues.
  4. Denoise: reconstruct the correlation matrix keeping the signal
     eigenvalues as-is and replacing every noise eigenvalue with their
     shared average (preserves the matrix trace; the standard RMT
     denoising step — see López de Prado, MLAM Ch. 2).
  5. Detone: remove the top ("market"/common-factor) eigenvector's
     contribution from the denoised correlation matrix, then rescale back
     to a unit diagonal — removes the broad common-factor component so
     remaining structure reflects feature-specific relationships (MLAM
     Ch. 2's detoning step).
  6. A practical version of Optimal Number of Clusters (ONC, MLAM Ch. 4):
     hierarchical clustering on the detoned-correlation-implied distance
     matrix, trying every K from 2 to N-1 and selecting the K maximizing
     mean silhouette score — captures ONC's core idea (automatic K
     selection via cluster-quality, not a fixed threshold) without its
     full recursive re-clustering refinement step, which is not needed at
     this small scale (8 features).

Given only 24 real labeled examples exist currently (n < 8*3, a genuinely
small-N regime even by this project's own standards), results here are
reported as exploratory/directional, not a settled feature-selection
decision — re-run once more labeled examples accumulate.

Read-only. Never fetches, never trains a model, never modifies ml.py.

Usage:
    python research/rmt_feature_denoising.py
"""
import glob
import os
import sys

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.metrics import silhouette_score

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ml
from analysis import EigenportfolioDecomposer

_TF_DIRS = [
    "1min", "2min", "3min", "5min", "15min", "30min", "1hr", "4hr",
    "7day", "1mo", "3mo", "6mo",
]
_DIR_TO_LABEL = {
    "1min": "1m", "2min": "2m", "3min": "3m", "5min": "5m", "15min": "15m",
    "30min": "30m", "1hr": "1h", "4hr": "4h", "7day": "7D", "1mo": "1M",
    "3mo": "3M", "6mo": "6M",
}


def _resolve_tf_dirname(tf_dir):
    """Returns just the directory NAME (not full path) — live if present,
    else the most recent archived _stale_* snapshot's name."""
    live = os.path.join("output", "results", tf_dir)
    if os.path.isdir(live):
        return tf_dir
    candidates = sorted(glob.glob(os.path.join("output", "results", f"{tf_dir}_stale_*")))
    return os.path.basename(candidates[-1]) if candidates else tf_dir


def gather_real_examples():
    """Reuses ml.py's own `_build_examples_for_pair` directly (not
    reimplemented) across every confirmed pair, redirecting `_tf_dirname`
    per timeframe to the resolved live-or-archived directory. Restores
    `ml._tf_dirname` afterward regardless of outcome."""
    summary = ml.MLRunSummary()
    all_events = []
    orig_tf_dirname = ml._tf_dirname
    try:
        for tf_dir in _TF_DIRS:
            resolved_name = _resolve_tf_dirname(tf_dir)
            pairs_path = os.path.join("output", "results", resolved_name, "pairs.parquet")
            if not os.path.exists(pairs_path):
                continue
            tf_label = _DIR_TO_LABEL[tf_dir]
            pairs_df = pd.read_parquet(pairs_path)
            ml._tf_dirname = lambda _tfl, _rn=resolved_name: _rn
            for _, row in pairs_df.iterrows():
                try:
                    events = ml._build_examples_for_pair(
                        row["symbol_a"], row["symbol_b"], tf_label, row, summary
                    )
                    all_events.extend(events)
                except Exception:
                    continue
    finally:
        ml._tf_dirname = orig_tf_dirname
    if not all_events:
        return pd.DataFrame(columns=ml._FEATURE_COLS)
    return pd.DataFrame([vars(e) for e in all_events])[ml._FEATURE_COLS]


def denoise_correlation(corr, n_periods):
    """Steps 3-4: MP-threshold + denoise. Returns (denoised_corr, K_signal)."""
    n = corr.shape[0]
    eigenvalues, eigenvectors, lambda_plus, _ = EigenportfolioDecomposer._eigendecompose(
        corr, n_periods
    )
    k_signal = int(np.sum(eigenvalues > lambda_plus))
    k_signal = max(1, min(k_signal, n - 1))  # keep at least 1 signal, at least 1 noise eigenvalue

    noise_eigenvalues = eigenvalues[k_signal:]
    denoised_eigenvalues = eigenvalues.copy()
    denoised_eigenvalues[k_signal:] = np.mean(noise_eigenvalues)

    denoised_corr = eigenvectors @ np.diag(denoised_eigenvalues) @ eigenvectors.T
    # Rescale to unit diagonal (reconstruction can drift slightly off 1.0)
    d = np.sqrt(np.diag(denoised_corr))
    denoised_corr = denoised_corr / np.outer(d, d)
    np.fill_diagonal(denoised_corr, 1.0)
    return denoised_corr, k_signal


def detone(corr, eigenvalues, eigenvectors, n_market_components=1):
    """Step 5: remove the top n_market_components eigenvector(s)' contribution,
    then rescale back to a unit diagonal."""
    market_part = (
        eigenvectors[:, :n_market_components]
        @ np.diag(eigenvalues[:n_market_components])
        @ eigenvectors[:, :n_market_components].T
    )
    detoned = corr - market_part
    d = np.sqrt(np.clip(np.diag(detoned), 1e-12, None))
    detoned = detoned / np.outer(d, d)
    np.fill_diagonal(detoned, 1.0)
    return detoned


def optimal_clustering(corr, max_k=None):
    """Step 6: hierarchical clustering, K selected by max mean silhouette
    score over the correlation-implied distance matrix. Returns (labels, best_k)."""
    n = corr.shape[0]
    if max_k is None:
        max_k = n - 1
    dist = np.sqrt(np.clip(0.5 * (1 - corr), 0, None))
    np.fill_diagonal(dist, 0.0)
    condensed = squareform(dist, checks=False)
    link = linkage(condensed, method="average")

    best_k, best_score, best_labels = 1, -1.0, np.ones(n, dtype=int)
    for k in range(2, max_k + 1):
        labels = fcluster(link, t=k, criterion="maxclust")
        if len(set(labels)) < 2:
            continue
        try:
            score = silhouette_score(dist, labels, metric="precomputed")
        except ValueError:
            continue
        if score > best_score:
            best_k, best_score, best_labels = k, score, labels
    return best_labels, best_k, best_score


def main():
    examples = gather_real_examples()
    n = len(examples)
    print(f"Gathered {n} real labeled examples across all confirmed pairs")
    if n < 15:
        print("Too few examples for a meaningful correlation matrix (need >=15) — "
              "reporting the raw correlation matrix only, no denoising/clustering.")

    corr = examples.corr().to_numpy()
    corr = np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(corr, 1.0)
    print("\nRaw correlation matrix (8 ml.py Stage-1 features):")
    print(examples.corr().round(2).to_string())

    if n < 15:
        return

    denoised_corr, k_signal = denoise_correlation(corr, n_periods=n)
    print(f"\nMarchenko-Pastur signal eigenvalue count: K={k_signal} of 8 features "
          f"(n={n} examples, ratio c=8/{n}={8/n:.2f})")

    eigenvalues, eigenvectors, _lp, _k = EigenportfolioDecomposer._eigendecompose(
        denoised_corr, n
    )
    detoned_corr = detone(denoised_corr, eigenvalues, eigenvectors, n_market_components=1)

    labels, best_k, best_score = optimal_clustering(detoned_corr)
    print(f"\nOptimal clustering on detoned correlation: K={best_k} clusters "
          f"(mean silhouette={best_score:.3f})")
    for cluster_id in sorted(set(labels)):
        members = [ml._FEATURE_COLS[i] for i in range(len(labels)) if labels[i] == cluster_id]
        print(f"  Cluster {cluster_id}: {members}")

    os.makedirs("output/research", exist_ok=True)
    pd.DataFrame(detoned_corr, index=ml._FEATURE_COLS, columns=ml._FEATURE_COLS).to_parquet(
        "output/research/rmt_feature_denoising_detoned_corr.parquet"
    )
    print("\nWrote output/research/rmt_feature_denoising_detoned_corr.parquet")


if __name__ == "__main__":
    main()
