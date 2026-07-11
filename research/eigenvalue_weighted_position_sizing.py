"""
CAMARF eigenvalue_weighted_position_sizing.py — comparison/diagnostic
method, NOT part of the production pipeline.

Builds the "natural next step" PAPER.md §7.2 itself flags as not yet
attempted: "a position-sizing follow-up (correlation-aware weight
scaling)" motivated directly by the Meucci-vs-Grinold-Kahn divergence
(portfolio_effective_bets.py) — real correlation is concentrated in a
handful of specific pair-pairs (AVGO/CRWD-CVX/OXY 0.31, CVX/OXY-KVUE/KMB
0.30, AXP/CRWD-ZION/FHB 0.29), not spread uniformly, which is exactly why
Meucci's eigenvalue decomposition (ENB=9.78) diverges from Grinold-Kahn's
equicorrelation assumption (BR_eff=19.5).

`portfolio_position_sizing_correction.py` already compared ERC (loses)
against simple inverse-cluster-size (wins) — but inverse-cluster-size
uses DISCRETE cluster labels from graphical_lasso_clusters.py's own
partial-correlation clustering (itself flagged inconclusive at current
sample size). This script tests a CONTINUOUS alternative that uses the
SAME eigen-decomposition machinery Meucci's ENB is already built on
(`dd_hub_effective_bets.meucci_effective_bets`'s own eigenvalue/
eigenvector formula, same convention, not reimplemented differently):
weight each pair inversely to its loading on the TOP_K dominant
principal components (the shared/systematic risk factors), rather than
inversely to a discrete cluster's size. A pair that loads heavily onto a
dominant shared factor gets downweighted continuously by how much it
loads, not just by which discrete bucket a separate clustering algorithm
assigned it to.

Compared against equal-weight, ERC, and inverse-cluster-size on the SAME
daily P&L panel and the SAME portfolio_sharpe() evaluation
(`portfolio_position_sizing_correction.py`'s own functions, imported
directly) for a fair, apples-to-apples comparison — not a separately
constructed evaluation that could quietly favor this new scheme.

Read-only. Never fetches, never changes backtest.py's actual position
sizing — a comparison arm, matching this project's established discipline.

Usage:
    python research/eigenvalue_weighted_position_sizing.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from portfolio_effective_bets import build_daily_pnl_panel, _load_trades
from portfolio_position_sizing_correction import (
    erc_weights, inverse_cluster_size_weights, portfolio_sharpe,
)

def marchenko_pastur_upper_bound(n_assets: int, n_obs: int) -> float:
    """Closed-form MP upper bound for a correlation matrix's noise-band
    eigenvalues, lambda_max = (1 + sqrt(n/T))^2 — same theoretical basis
    as analysis.py's EigenportfolioDecomposer / research/rmt_feature_
    denoising.py's own MP denoising step (not imported directly, since
    those operate on a different N/T regime — this is the standard
    closed-form bound, self-contained here). Eigenvalues above this bound
    are very unlikely to be pure sampling noise."""
    if n_obs <= 0:
        return float("inf")
    q = n_assets / n_obs
    return float((1 + np.sqrt(q)) ** 2)


def eigenvalue_penalized_weights(corr: np.ndarray, top_k: int = None,
                                  n_obs: int = None) -> np.ndarray:
    """
    Weight each pair inversely to its loading on the dominant eigenvectors
    of the correlation matrix — same eigen-decomposition convention as
    dd_hub_effective_bets.meucci_effective_bets (descending eigenvalue
    order), applied to derive WEIGHTS rather than just a diversification
    score. Pure function — no I/O — so
    debug/_verify_eigenvalue_weighted_position_sizing.py can call it
    directly on synthetic matrices.

    top_k: if given, uses exactly that many top eigenvectors (fixed).
    n_obs: if given (and top_k is None), determines top_k ADAPTIVELY via
    the Marchenko-Pastur threshold — the number of eigenvalues that
    exceed the noise band. This matters in practice: when most pairs are
    genuinely near-uncorrelated (CAMARF's own real portfolio, rho_bar~0),
    most eigenvalues cluster near 1 (near-degenerate) and a FIXED top_k
    picks an ARBITRARY basis among them (numpy's eigh has no reason to
    prefer one direction over another for equal eigenvalues) — verified
    directly in debug/_verify_eigenvalue_weighted_position_sizing.py Case
    2: a fixed top_k=2 on a fully uncorrelated 5-asset system produced
    wildly uneven weights (0.333 vs 0.00003) purely from this arbitrary
    tie-breaking, not genuine structure. The MP-adaptive top_k avoids
    this by only penalizing eigenvalues that clear the noise band in the
    first place — if zero eigenvalues clear it, this returns equal-weight
    (no genuine common-factor structure to penalize).
    Must supply exactly one of top_k or n_obs.

    systematic_exposure_i = sum_{k=1..top_k} (v_k[i]^2 * lambda_k)
    weight_i ∝ 1 / sqrt(systematic_exposure_i)
    """
    corr = np.asarray(corr, dtype=float)
    n = corr.shape[0]
    eigenvalues, eigenvectors = np.linalg.eigh(corr)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[order]
    eigenvectors = eigenvectors[:, order]

    if top_k is None:
        if n_obs is None:
            raise ValueError("must supply exactly one of top_k or n_obs")
        mp_bound = marchenko_pastur_upper_bound(n, n_obs)
        top_k = int(np.sum(eigenvalues > mp_bound))
        if top_k == 0:
            return np.full(n, 1.0 / n)
    top_k = min(top_k, n)

    top_eigenvalues = eigenvalues[:top_k]
    top_eigenvectors = eigenvectors[:, :top_k]
    systematic_exposure = np.sum((top_eigenvectors ** 2) * top_eigenvalues[np.newaxis, :], axis=1)
    systematic_exposure = np.clip(systematic_exposure, 1e-8, None)
    raw_w = 1.0 / np.sqrt(systematic_exposure)
    return raw_w / raw_w.sum()


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
    if n_pairs < 4:
        print("Fewer than 4 pairs — skipping.")
        return
    returns = panel.to_numpy()
    cov = np.cov(returns.T)
    corr = panel.corr().to_numpy()
    corr = np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(corr, 1.0)
    pair_names = list(panel.columns)
    print(f"Loaded daily P&L panel: {len(panel)} days x {n_pairs} pairs\n")

    schemes = {"equal_weight": np.full(n_pairs, 1.0 / n_pairs)}
    schemes["erc"] = erc_weights(cov)

    cluster_path = "output/research/graphical_lasso_clusters.parquet"
    if os.path.exists(cluster_path):
        cluster_df = pd.read_parquet(cluster_path).set_index("pair").reindex(pair_names)
        if not cluster_df["cluster_marginal"].isna().any():
            schemes["inverse_cluster_size"] = inverse_cluster_size_weights(
                cluster_df["cluster_marginal"].to_numpy()
            )

    n_obs = len(panel)
    mp_bound = marchenko_pastur_upper_bound(n_pairs, n_obs)
    k_signal = int(np.sum(np.linalg.eigvalsh(corr)[::-1] > mp_bound))
    print(f"Marchenko-Pastur upper bound (n={n_pairs}, T={n_obs}): {mp_bound:.3f} — "
          f"{k_signal} eigenvalue(s) clear the noise band")
    schemes["eigenvalue_penalized_mp_adaptive"] = eigenvalue_penalized_weights(corr, n_obs=n_obs)
    # Fixed top_k variants kept as a sensitivity check alongside the adaptive default.
    for k in (2, 3, 5):
        schemes[f"eigenvalue_penalized_k{k}"] = eigenvalue_penalized_weights(corr, top_k=k)

    print("=== Scheme comparison ===")
    results = {}
    for name, w in schemes.items():
        sharpe = portfolio_sharpe(w, returns)
        max_w = float(np.max(w))
        port_var = w @ corr @ w
        idm = float(1.0 / np.sqrt(port_var)) if port_var > 0 else np.nan
        results[name] = sharpe
        print(f"[{name}] Sharpe={sharpe:.4f}  max_weight={max_w:.3f}  "
              f"portfolio_variance(w'Rw)={port_var:.4f}  Carver_IDM={idm:.3f}")

    best = max(results, key=lambda k: results[k] if np.isfinite(results[k]) else -np.inf)
    print(f"\nBest Sharpe achieved by: {best} ({results[best]:.4f})")
    if "inverse_cluster_size" in results:
        print(f"Comparison vs. the previously-established winner (inverse_cluster_size, "
              f"Sharpe={results['inverse_cluster_size']:.4f}): "
              f"eigenvalue_penalized_k3={results.get('eigenvalue_penalized_k3', float('nan')):.4f}")

    comp_df = pd.DataFrame({"pair": pair_names, **{f"w_{k}": v for k, v in schemes.items()}})
    os.makedirs("output/research", exist_ok=True)
    comp_df.to_parquet("output/research/eigenvalue_weighted_position_sizing.parquet")
    print("\nWrote output/research/eigenvalue_weighted_position_sizing.parquet")


if __name__ == "__main__":
    main()
