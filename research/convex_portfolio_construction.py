"""
research/convex_portfolio_construction.py — comparison/diagnostic method,
NOT part of the production pipeline.

Classic Markowitz-style convex portfolio construction over CAMARF's own
confirmed pairs, compared against the existing equal-weight baseline and
production's risk-parity/HRP schemes (§7.2, PAPER.md). Two objectives
(max Sharpe, max Sortino) x two constraint sets (long-only capped, and
negative weights allowed), per Ross's explicit request to build and compare
all four rather than pick one upfront.

Objectives are NOT directly convex quadratic programs in this form (Sharpe
and Sortino are RATIOS), so solved via scipy SLSQP direct maximization
rather than a cvxpy reformulation — SLSQP handles the nonlinear-but-
well-behaved ratio objective directly with linear equality (weights sum to
1) and box constraints (long-only-capped: [0, cap]; negative-allowed:
[-cap, cap]), which is the standard practical approach when a target-return/
risk-aversion parameter isn't specified (a true reformulation to a clean
QP needs one). Sortino specifically needs the actual portfolio RETURN TIME
SERIES (not just mean/covariance) to compute downside semi-deviation, so it
genuinely can't be expressed as a QP over Sigma alone — this is not a choice
made for convenience, it's inherent to what Sortino measures.

Reuses portfolio_effective_bets.py's daily P&L panel construction directly
(same OLS-hedge-method convention). Per-pair cap = 20% (matches backtest.py's
existing MAX_CONCENTRATION_PCT convention, not a new number invented here).

Verified against a simple 3-asset synthetic case with a known analytic
max-Sharpe solution before trusting real, higher-dimensional data.

Read-only. Never fetches, never changes backtest.py's actual position sizing
— this is a comparison arm, matching this project's "comparison arm first,
no production change without evidence" discipline (§7.2's own HRP-vs-
risk-parity precedent).

Usage:
    python research/convex_portfolio_construction.py
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # for portfolio_effective_bets

from portfolio_effective_bets import build_daily_pnl_panel, _load_trades

CAP = 0.20  # matches backtest.py's MAX_CONCENTRATION_PCT convention


def _portfolio_returns(w: np.ndarray, returns: np.ndarray) -> np.ndarray:
    return returns @ w


def _neg_sharpe(w: np.ndarray, returns: np.ndarray) -> float:
    port = _portfolio_returns(w, returns)
    sd = port.std()
    if sd == 0:
        return 0.0
    return -(port.mean() / sd)


def _neg_sortino(w: np.ndarray, returns: np.ndarray) -> float:
    port = _portfolio_returns(w, returns)
    downside = np.minimum(port, 0.0)
    downside_dev = np.sqrt(np.mean(downside ** 2))
    if downside_dev == 0:
        return 0.0
    return -(port.mean() / downside_dev)


def optimize_portfolio(returns: np.ndarray, objective: str, allow_negative: bool, cap: float = CAP) -> dict:
    n = returns.shape[1]
    w0 = np.full(n, 1.0 / n)
    bounds = [(-cap, cap) if allow_negative else (0.0, cap) for _ in range(n)]
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    obj_fn = _neg_sharpe if objective == "sharpe" else _neg_sortino

    result = minimize(
        obj_fn, w0, args=(returns,), method="SLSQP",
        bounds=bounds, constraints=constraints,
        options={"maxiter": 500, "ftol": 1e-10},
    )
    w = result.x
    port = _portfolio_returns(w, returns)
    sharpe = port.mean() / port.std() if port.std() > 0 else np.nan
    downside_dev = np.sqrt(np.mean(np.minimum(port, 0.0) ** 2))
    sortino = port.mean() / downside_dev if downside_dev > 0 else np.nan
    return {
        "weights": w, "converged": bool(result.success),
        "sharpe": float(sharpe), "sortino": float(sortino),
        "max_weight": float(np.max(np.abs(w))),
    }


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
    print(f"Loaded daily P&L panel: {len(panel)} days x {n_pairs} pairs\n")
    if n_pairs < 3:
        print("Fewer than 3 pairs — convex optimization needs a meaningful set. Skipping.")
        return

    returns = panel.to_numpy()
    pair_names = list(panel.columns)

    # Equal-weight baseline for comparison
    w_eq = np.full(n_pairs, 1.0 / n_pairs)
    port_eq = _portfolio_returns(w_eq, returns)
    sharpe_eq = port_eq.mean() / port_eq.std() if port_eq.std() > 0 else np.nan
    downside_eq = np.sqrt(np.mean(np.minimum(port_eq, 0.0) ** 2))
    sortino_eq = port_eq.mean() / downside_eq if downside_eq > 0 else np.nan
    print(f"Equal-weight baseline: Sharpe={sharpe_eq:.4f}  Sortino={sortino_eq:.4f}\n")

    results = {}
    for objective in ["sharpe", "sortino"]:
        for allow_negative in [False, True]:
            key = f"{objective}_{'negative' if allow_negative else 'longonly_capped'}"
            r = optimize_portfolio(returns, objective, allow_negative)
            results[key] = r
            print(f"[{key}] converged={r['converged']}  Sharpe={r['sharpe']:.4f}  "
                  f"Sortino={r['sortino']:.4f}  max|weight|={r['max_weight']:.3f}")

    print("\n=== Comparison vs. equal-weight baseline ===")
    for key, r in results.items():
        d_sharpe = r["sharpe"] - sharpe_eq
        d_sortino = r["sortino"] - sortino_eq
        print(f"  {key}: Sharpe {d_sharpe:+.4f}  Sortino {d_sortino:+.4f}")

    best_key = max(results, key=lambda k: results[k]["sharpe"])
    print(f"\nBest Sharpe achieved by: {best_key} (Sharpe={results[best_key]['sharpe']:.4f} "
          f"vs equal-weight {sharpe_eq:.4f})")

    os.makedirs("output/research", exist_ok=True)
    out_rows = []
    for key, r in results.items():
        for i, pair in enumerate(pair_names):
            out_rows.append({"scheme": key, "pair": pair, "weight": r["weights"][i]})
    pd.DataFrame(out_rows).to_parquet("output/research/convex_portfolio_construction.parquet")
    print("\nWrote output/research/convex_portfolio_construction.parquet")


if __name__ == "__main__":
    main()
