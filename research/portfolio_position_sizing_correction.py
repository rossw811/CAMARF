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
from comparison_arm_scaffold import walk_forward_windows

_TRAIN_WINDOW = 252  # matches k_bahc_covariance_cleaning.py's own convention
_TEST_WINDOW = 21


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


def _fit_schemes(train_panel: pd.DataFrame, cluster_labels: np.ndarray) -> dict:
    """Fits ALL weighting schemes from a TRAIN-window panel only (Tier 3.3
    retrofit, Grand Sweep 2026-07-20). `cluster_labels` is a STATIC,
    externally-supplied per-pair assignment (graphical_lasso_clusters.py's
    output) — not derived from this window's own price history, so it is
    NOT re-fit per window (there is nothing to leak: it is the same input
    every scheme in this comparison already treats as a fixed constant)."""
    n_pairs = train_panel.shape[1]
    cov = np.cov(train_panel.to_numpy().T)
    schemes = {"equal_weight": np.full(n_pairs, 1.0 / n_pairs)}
    schemes["erc"] = erc_weights(cov)
    schemes["inverse_cluster_size"] = inverse_cluster_size_weights(cluster_labels)
    return schemes


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

    # Tier 3.3 retrofit (Grand Sweep 2026-07-20): previously fit every
    # scheme's weights from the FULL panel and scored Sharpe on that SAME
    # full panel -- real in-sample circularity. Now genuine walk-forward
    # (comparison_arm_scaffold.walk_forward_windows, same train=252/test=21
    # convention as k_bahc_covariance_cleaning.py, the one script in this
    # family that already got this right): weights fit on each TRAIN
    # window only, scored on the immediately-following, disjoint TEST
    # window the fit never saw.
    if len(panel) < _TRAIN_WINDOW + _TEST_WINDOW:
        print(f"\nInsufficient daily history ({len(panel)} days) for a genuine walk-forward "
              f"split (need >= {_TRAIN_WINDOW + _TEST_WINDOW}) -- falling back to an EXPLICITLY "
              f"IN-SAMPLE-ONLY comparison (fit and scored on the same full panel). This number is "
              f"NOT a valid out-of-sample result and must not be read as one.")
        schemes = _fit_schemes(panel, cluster_labels)
        returns = panel.to_numpy()
        for name, w in schemes.items():
            print(f"[{name}] IN-SAMPLE Sharpe={portfolio_sharpe(w, returns):.4f}")
        return

    oos_sharpes = {name: [] for name in ("equal_weight", "erc", "inverse_cluster_size")}
    n_windows = 0
    for train_df, test_df in walk_forward_windows(panel, _TRAIN_WINDOW, _TEST_WINDOW):
        schemes = _fit_schemes(train_df, cluster_labels)
        test_returns = test_df.to_numpy()
        for name, w in schemes.items():
            oos_sharpes[name].append(portfolio_sharpe(w, test_returns))
        n_windows += 1

    print(f"=== Walk-forward OOS comparison across {n_windows} non-overlapping "
          f"train={_TRAIN_WINDOW}/test={_TEST_WINDOW}-day windows ===")
    mean_oos = {}
    for name, scores in oos_sharpes.items():
        finite = [s for s in scores if np.isfinite(s)]
        mean_oos[name] = float(np.mean(finite)) if finite else np.nan
        print(f"[{name}] mean OOS Sharpe={mean_oos[name]:.4f} across {len(finite)}/{n_windows} "
              f"valid windows (per-window: {[round(s, 3) for s in scores]})")

    best = max(mean_oos, key=lambda k: mean_oos[k] if np.isfinite(mean_oos[k]) else -np.inf)
    print(f"\nBest mean OOS Sharpe achieved by: {best} ({mean_oos[best]:.4f})")

    out_rows = [
        {"scheme": name, "window": i, "oos_sharpe": s}
        for name, scores in oos_sharpes.items()
        for i, s in enumerate(scores)
    ]
    os.makedirs("output/research", exist_ok=True)
    pd.DataFrame(out_rows).to_parquet("output/research/portfolio_position_sizing_correction.parquet")
    print("Wrote output/research/portfolio_position_sizing_correction.parquet")


if __name__ == "__main__":
    main()
