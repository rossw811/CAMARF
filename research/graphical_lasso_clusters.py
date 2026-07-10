"""
research/graphical_lasso_clusters.py — comparison/diagnostic method, NOT
part of the production pipeline.

Friedman, Hastie & Tibshirani (2008), "Sparse inverse covariance estimation
with the graphical lasso," Biostatistics 9(3). portfolio_effective_bets.py
(this session, earlier) used the raw Pearson correlation matrix of confirmed
pairs' daily P&L to find "top correlated pair-pairs" — but marginal
correlation can be misleading: if A and C are both driven by a shared factor
B, A and C can show real marginal correlation even with ZERO direct
relationship once B's influence is partialled out. Graphical lasso estimates
a SPARSE PRECISION MATRIX (inverse covariance) directly — off-diagonal zeros
in the precision matrix mean two pairs are CONDITIONALLY INDEPENDENT given
every other pair, a materially different (and for cluster identification,
more defensible) notion of "genuinely connected" than raw correlation.

Feeds directly into the position-sizing correction task (graphical-lasso-
identified clusters, not marginal-correlation clusters, are the basis for
that comparison) — this script's own job stops at identifying clusters and
reporting them; the position-sizing weight scheme itself lives in
research/portfolio_position_sizing_correction.py.

Method: reuse portfolio_effective_bets.py's own daily P&L panel construction
directly (same OLS-hedge-method convention, same 0-fill-on-no-trade-day
convention — not reimplemented). Standardize (z-score) each pair's daily
P&L series before fitting (GraphicalLassoCV is scale-sensitive; CAMARF's
pairs have very different natural P&L magnitudes). Fit GraphicalLassoCV
(regularization strength selected by cross-validation, not a hand-picked
alpha). Convert the resulting precision matrix to partial correlations
(rho_ij = -Theta_ij / sqrt(Theta_ii * Theta_jj), the standard transform) and
feed that into rmt_feature_denoising.py's own `optimal_clustering` (silhouette-
score K selection on a correlation-like matrix) — reused directly, not
reimplemented, since it's already generic (operates on any correlation-shaped
matrix, not RMT-specific despite its module name).

Read-only. Never fetches, never modifies backtest.py or its outputs.

Usage:
    python research/graphical_lasso_clusters.py
"""
import os
import sys

import numpy as np
import pandas as pd
from sklearn.covariance import GraphicalLassoCV

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # for aligned_pair_loader, rmt_feature_denoising

from portfolio_effective_bets import build_daily_pnl_panel, _load_trades
from rmt_feature_denoising import optimal_clustering


def precision_to_partial_corr(precision: np.ndarray) -> np.ndarray:
    d = np.sqrt(np.diag(precision))
    partial_corr = -precision / np.outer(d, d)
    np.fill_diagonal(partial_corr, 1.0)
    return partial_corr


def main():
    trades_is = _load_trades("layer1")
    trades_oos = _load_trades("layer1_holdout")
    all_trades = (
        pd.concat([trades_is, trades_oos], ignore_index=True)
        if len(trades_is) > 0 else trades_oos
    )
    if all_trades.empty:
        print("No trades found — run backtest.py first.")
        return

    panel = build_daily_pnl_panel(all_trades)
    n_pairs = panel.shape[1]
    print(f"Loaded daily P&L panel: {len(panel)} days x {n_pairs} pairs")
    if n_pairs < 4:
        print("Fewer than 4 pairs — graphical lasso clustering needs a meaningful matrix. Skipping.")
        return

    # Standardize each pair's series (z-score) — GraphicalLassoCV assumes
    # comparable scale across variables, and these pairs' natural P&L
    # magnitudes differ by orders of magnitude (see tonight's Kalman
    # position-sizing investigation for exactly why that matters).
    standardized = (panel - panel.mean()) / panel.std().replace(0, 1)
    standardized = standardized.fillna(0.0)

    model = GraphicalLassoCV(cv=5, max_iter=200)
    try:
        model.fit(standardized.to_numpy())
    except Exception as e:
        print(f"GraphicalLassoCV failed to converge: {type(e).__name__}: {e} — try more data or fewer pairs.")
        return

    precision = model.precision_
    partial_corr = precision_to_partial_corr(precision)
    n_nonzero_edges = int((np.abs(precision) > 1e-6).sum() - n_pairs) // 2  # exclude diagonal, count each edge once
    total_possible_edges = n_pairs * (n_pairs - 1) // 2
    print(f"\nSelected regularization alpha={model.alpha_:.4f} (cross-validated)")
    print(f"Sparse precision matrix: {n_nonzero_edges}/{total_possible_edges} nonzero off-diagonal edges "
          f"({100*n_nonzero_edges/total_possible_edges:.1f}% density)")

    labels, best_k, best_score = optimal_clustering(np.abs(partial_corr))
    print(f"\nOptimal clustering on partial-correlation structure: K={best_k} clusters "
          f"(mean silhouette={best_score:.3f})")
    pair_names = list(panel.columns)
    for cluster_id in sorted(set(labels)):
        members = [pair_names[i] for i in range(len(labels)) if labels[i] == cluster_id]
        print(f"  Cluster {cluster_id}: {members}")

    # Compare to marginal-correlation clustering (portfolio_effective_bets.py's
    # own view) on the SAME pair set, to make the "conditional vs marginal"
    # distinction concrete rather than asserted.
    marginal_corr = panel.corr().to_numpy()
    marginal_corr = np.nan_to_num(marginal_corr, nan=0.0)
    np.fill_diagonal(marginal_corr, 1.0)
    labels_marginal, best_k_marginal, _ = optimal_clustering(np.abs(marginal_corr))
    print(f"\nFor comparison, marginal-correlation clustering (ignoring conditional "
          f"independence): K={best_k_marginal} clusters")
    agreement = float(np.mean(labels == labels_marginal)) if len(labels) == len(labels_marginal) else np.nan
    print(f"Cluster-label agreement between the two methods: {agreement:.2f} "
          f"(low agreement = marginal correlation was misleading about true structure)")

    os.makedirs("output/research", exist_ok=True)
    pd.DataFrame(partial_corr, index=pair_names, columns=pair_names).to_parquet(
        "output/research/graphical_lasso_partial_corr.parquet"
    )
    pd.DataFrame({"pair": pair_names, "cluster_partial": labels, "cluster_marginal": labels_marginal}).to_parquet(
        "output/research/graphical_lasso_clusters.parquet"
    )
    print("\nWrote output/research/graphical_lasso_partial_corr.parquet and graphical_lasso_clusters.parquet")


if __name__ == "__main__":
    main()
