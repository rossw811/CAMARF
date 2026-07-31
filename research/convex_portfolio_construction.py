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
from comparison_arm_scaffold import walk_forward_windows

CAP = 0.20  # matches backtest.py's MAX_CONCENTRATION_PCT convention
_TRAIN_WINDOW = 252  # matches k_bahc_covariance_cleaning.py's own convention
_TEST_WINDOW = 21


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


def fit_portfolio_weights(train_returns: np.ndarray, objective: str, allow_negative: bool,
                           cap: float = CAP) -> dict:
    """Fits weights via SLSQP on TRAIN data only. Returns {"weights", "converged"} —
    NOT a score, since Tier 3.3's fix (Grand Sweep 2026-07-20) is specifically to
    stop reporting the objective function's own optimal value (necessarily
    computed on the same data it was fit on) as if it were a real result. Score
    the returned weights separately, against a DIFFERENT (test) sample, via
    score_portfolio_weights()."""
    n = train_returns.shape[1]
    w0 = np.full(n, 1.0 / n)
    bounds = [(-cap, cap) if allow_negative else (0.0, cap) for _ in range(n)]
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    obj_fn = _neg_sharpe if objective == "sharpe" else _neg_sortino

    result = minimize(
        obj_fn, w0, args=(train_returns,), method="SLSQP",
        bounds=bounds, constraints=constraints,
        options={"maxiter": 500, "ftol": 1e-10},
    )
    return {"weights": result.x, "converged": bool(result.success)}


def score_portfolio_weights(w: np.ndarray, returns: np.ndarray) -> dict:
    """Scores an ALREADY-FIT weight vector against `returns` — the caller
    decides whether `returns` is the same sample `w` was fit on (in-sample,
    must be labeled as such) or a disjoint one (genuine OOS)."""
    port = _portfolio_returns(w, returns)
    sharpe = port.mean() / port.std() if port.std() > 0 else np.nan
    downside_dev = np.sqrt(np.mean(np.minimum(port, 0.0) ** 2))
    sortino = port.mean() / downside_dev if downside_dev > 0 else np.nan
    return {"sharpe": float(sharpe), "sortino": float(sortino), "max_weight": float(np.max(np.abs(w)))}


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

    pair_names = list(panel.columns)
    schemes = ["sharpe_longonly_capped", "sharpe_negative", "sortino_longonly_capped", "sortino_negative"]

    def _scheme_args(key):
        objective = "sharpe" if key.startswith("sharpe") else "sortino"
        allow_negative = key.endswith("negative")
        return objective, allow_negative

    # Tier 3.3 retrofit (Grand Sweep 2026-07-20) — the STARKEST in-sample-
    # circularity instance the audit found: the SLSQP objective function's
    # own optimal value (necessarily computed on the exact data it was fit
    # on) WAS the reported metric. Now genuine walk-forward: weights fit
    # on a TRAIN window only, scored on the immediately-following, disjoint
    # TEST window (comparison_arm_scaffold.walk_forward_windows,
    # train=252/test=21 days, matching k_bahc_covariance_cleaning.py).
    if len(panel) < _TRAIN_WINDOW + _TEST_WINDOW:
        print(f"\nInsufficient daily history ({len(panel)} days) for a genuine walk-forward "
              f"split (need >= {_TRAIN_WINDOW + _TEST_WINDOW}) -- falling back to an EXPLICITLY "
              f"IN-SAMPLE-ONLY comparison (fit and scored on the same full panel). These numbers "
              f"are NOT valid out-of-sample results.")
        returns = panel.to_numpy()
        w_eq = np.full(n_pairs, 1.0 / n_pairs)
        eq_score = score_portfolio_weights(w_eq, returns)
        print(f"Equal-weight baseline (IN-SAMPLE): Sharpe={eq_score['sharpe']:.4f}  "
              f"Sortino={eq_score['sortino']:.4f}\n")
        for key in schemes:
            objective, allow_negative = _scheme_args(key)
            fit = fit_portfolio_weights(returns, objective, allow_negative)
            score = score_portfolio_weights(fit["weights"], returns)
            print(f"[{key}] IN-SAMPLE converged={fit['converged']}  Sharpe={score['sharpe']:.4f}  "
                  f"Sortino={score['sortino']:.4f}  max|weight|={score['max_weight']:.3f}")
        return

    oos_scores = {key: [] for key in schemes}
    eq_oos_scores = []
    n_windows = 0
    for train_df, test_df in walk_forward_windows(panel, _TRAIN_WINDOW, _TEST_WINDOW):
        test_returns = test_df.to_numpy()
        w_eq = np.full(n_pairs, 1.0 / n_pairs)
        eq_oos_scores.append(score_portfolio_weights(w_eq, test_returns))
        train_returns = train_df.to_numpy()
        for key in schemes:
            objective, allow_negative = _scheme_args(key)
            fit = fit_portfolio_weights(train_returns, objective, allow_negative)
            oos_scores[key].append(score_portfolio_weights(fit["weights"], test_returns))
        n_windows += 1

    def _mean_metric(score_list, metric):
        vals = [s[metric] for s in score_list if np.isfinite(s[metric])]
        return float(np.mean(vals)) if vals else np.nan

    print(f"=== Walk-forward OOS comparison across {n_windows} non-overlapping "
          f"train={_TRAIN_WINDOW}/test={_TEST_WINDOW}-day windows ===")
    eq_sharpe_oos = _mean_metric(eq_oos_scores, "sharpe")
    eq_sortino_oos = _mean_metric(eq_oos_scores, "sortino")
    print(f"Equal-weight baseline: mean OOS Sharpe={eq_sharpe_oos:.4f}  mean OOS Sortino={eq_sortino_oos:.4f}\n")

    mean_oos_sharpe = {}
    for key in schemes:
        mean_sharpe = _mean_metric(oos_scores[key], "sharpe")
        mean_sortino = _mean_metric(oos_scores[key], "sortino")
        mean_oos_sharpe[key] = mean_sharpe
        print(f"[{key}] mean OOS Sharpe={mean_sharpe:.4f} ({mean_sharpe - eq_sharpe_oos:+.4f} vs "
              f"equal-weight)  mean OOS Sortino={mean_sortino:.4f} ({mean_sortino - eq_sortino_oos:+.4f} "
              f"vs equal-weight)")

    best_key = max(mean_oos_sharpe, key=lambda k: mean_oos_sharpe[k] if np.isfinite(mean_oos_sharpe[k]) else -np.inf)
    print(f"\nBest mean OOS Sharpe achieved by: {best_key} ({mean_oos_sharpe[best_key]:.4f} "
          f"vs equal-weight {eq_sharpe_oos:.4f})")

    os.makedirs("output/research", exist_ok=True)
    out_rows = [
        {"scheme": "equal_weight", "window": i, "oos_sharpe": s["sharpe"], "oos_sortino": s["sortino"]}
        for i, s in enumerate(eq_oos_scores)
    ] + [
        {"scheme": key, "window": i, "oos_sharpe": s["sharpe"], "oos_sortino": s["sortino"]}
        for key in schemes for i, s in enumerate(oos_scores[key])
    ]
    pd.DataFrame(out_rows).to_parquet("output/research/convex_portfolio_construction.parquet")
    print("\nWrote output/research/convex_portfolio_construction.parquet")


if __name__ == "__main__":
    main()
