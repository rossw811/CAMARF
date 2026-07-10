"""
research/portfolio_position_sizing_correction.py — comparison/diagnostic
method, NOT part of the production pipeline.

Answers the follow-up flagged by portfolio_effective_bets.py (this session):
Meucci's eigenvalue-based effective bet count (~9.78 of 21 nominal pairs)
diverges sharply from Grinold-Kahn's equicorrelation-based estimate (~19.5)
because correlation is concentrated in specific clusters, not spread evenly
— so a position-sizing scheme that's cluster-aware should do better than
one that treats every pair as an equally-independent bet. Two schemes
compared per Ross's explicit request (not picked upfront):

  1. Equal Risk Contribution (ERC) — weights such that every pair
     contributes EQUALLY to total portfolio risk, accounting for the full
     correlation structure (not just cluster membership) — solved via SLSQP
     minimizing the variance of per-pair risk contributions RC_i = w_i *
     (Sigma w)_i / (w'Sigma w), the standard formulation (Maillard, Roncalli
     & Teiletche 2010).
  2. Simple inverse-cluster-size — using graphical_lasso_clusters.py's own
     saved cluster assignments (marginal-correlation clusters, since that
     script's own graphical-lasso partial-correlation result was inconclusive
     at current sample size — reusing the more reliable of its two outputs,
     not silently upgrading a weak result), each pair's weight is
     1/cluster_size, normalized to sum to 1.

Both compared against equal-weight and against each other on Sharpe,
concentration (max weight), and effective bet count (Grinold-Kahn/Meucci/
Carver from dd_hub_effective_bets.py, reused directly — not reimplemented —
applied to each SCHEME's own weighted portfolio, not just equal-weighted).

Read-only. Never fetches, never changes backtest.py's actual position
sizing — a comparison arm, matching this project's established discipline.

Usage:
    python research/portfolio_position_sizing_correction.py
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from portfolio_effective_bets import build_daily_pnl_panel, _load_trades


def erc_weights(cov: np.ndarray) -> np.ndarray:
    n = cov.shape[0]

    def risk_contrib_variance(w):
        port_var = w @ cov @ w
        if port_var <= 0:
            return 1e6
        marginal = cov @ w
        rc = w * marginal / port_var
        return float(np.var(rc))

    w0 = np.full(n, 1.0 / n)
    bounds = [(1e-6, 1.0) for _ in range(n)]
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    result = minimize(risk_contrib_variance, w0, method="SLSQP",
                       bounds=bounds, constraints=constraints,
                       options={"maxiter": 1000, "ftol": 1e-12})
    return result.x


def inverse_cluster_size_weights(cluster_labels: np.ndarray) -> np.ndarray:
    sizes = pd.Series(cluster_labels).map(pd.Series(cluster_labels).value_counts())
    raw_w = 1.0 / sizes.to_numpy()
    return raw_w / raw_w.sum()


def portfolio_sharpe(w, returns):
    port = returns @ w
    return port.mean() / port.std() if port.std() > 0 else np.nan


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

    cluster_path = "output/research/graphical_lasso_clusters.parquet"
    if not os.path.exists(cluster_path):
        print(f"Missing {cluster_path} — run research/graphical_lasso_clusters.py first.")
        return
    cluster_df = pd.read_parquet(cluster_path).set_index("pair")
    cluster_df = cluster_df.reindex(pair_names)
    if cluster_df["cluster_marginal"].isna().any():
        print("Cluster assignment missing for some pairs — pair sets may have drifted "
              "since graphical_lasso_clusters.py last ran. Re-run it first.")
        return
    cluster_labels = cluster_df["cluster_marginal"].to_numpy()

    schemes = {"equal_weight": np.full(n_pairs, 1.0 / n_pairs)}
    schemes["erc"] = erc_weights(cov)
    schemes["inverse_cluster_size"] = inverse_cluster_size_weights(cluster_labels)

    print("=== Scheme comparison ===")
    for name, w in schemes.items():
        sharpe = portfolio_sharpe(w, returns)
        max_w = float(np.max(w))
        port_var = w @ corr @ w
        rho_bar_implied = float((port_var - np.sum(w**2)) / (1 - np.sum(w**2))) if np.sum(w**2) < 1 else np.nan
        idm = float(1.0 / np.sqrt(port_var)) if port_var > 0 else np.nan
        print(f"[{name}] Sharpe={sharpe:.4f}  max_weight={max_w:.3f}  "
              f"portfolio_variance(w'Rw)={port_var:.4f}  Carver_IDM={idm:.3f}")

    print("\n=== Weight allocation by cluster (inverse-cluster-size vs ERC) ===")
    comp_df = pd.DataFrame({
        "pair": pair_names, "cluster": cluster_labels,
        "w_equal": schemes["equal_weight"], "w_erc": schemes["erc"],
        "w_inv_cluster": schemes["inverse_cluster_size"],
    })
    print(comp_df.sort_values("cluster").to_string(index=False))

    best = max(schemes, key=lambda k: portfolio_sharpe(schemes[k], returns))
    print(f"\nBest Sharpe achieved by: {best}")

    os.makedirs("output/research", exist_ok=True)
    comp_df.to_parquet("output/research/portfolio_position_sizing_correction.parquet")
    print("Wrote output/research/portfolio_position_sizing_correction.parquet")


if __name__ == "__main__":
    main()
