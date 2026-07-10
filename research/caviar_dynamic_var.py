"""
research/caviar_dynamic_var.py — comparison/diagnostic method, NOT part of
the production pipeline.

Engle & Manganelli (2004), "CAViaR: Conditional Autoregressive Value at
Risk by Regression Quantiles," Journal of Business & Economic Statistics
22(4) — a DYNAMIC VaR model, compared against cvar.py's existing STATIC
historical VaR/CVaR and the EVT/GPD tail-risk work (stats.py §3). Static
historical VaR answers "what's the alpha-quantile loss over the whole
sample"; CAViaR answers "what's today's alpha-quantile loss, GIVEN
yesterday's VaR level and yesterday's loss magnitude" — lets the VaR
threshold itself widen after a big loss and narrow during calm stretches,
the same volatility-clustering intuition GARCH captures for variance,
applied directly to a quantile instead.

Symmetric Absolute Value (SAV) specification, the simplest and most-cited
of Engle & Manganelli's four proposed forms:

    VaR_t = beta0 + beta1 * VaR_{t-1} + beta2 * |loss_{t-1}|

losses = -daily_pnl (same sign convention as cvar.py's historical_cvar, so
VaR_t is a positive dollar-loss-magnitude quantile, directly comparable).
Estimated by minimizing the quantile ("tick") loss:

    L(beta) = sum_t rho_alpha(loss_t - VaR_t),  rho_alpha(u) = u*(alpha - 1{u<0})

via Nelder-Mead (the check-loss function is non-smooth — no clean gradient
for a standard gradient-based optimizer, and Nelder-Mead is what Engle &
Manganelli's own original implementation used). VaR_0 initialized at the
empirical alpha-quantile of the first `min_calibration_days` losses (same
no-lookahead calibration-then-freeze-parameters convention this project
already uses for its Kalman/GARCH work) — beta itself is fit ONCE on the
full series (standard CAViaR practice; the recursion, not a rolling refit,
is what makes VaR_t time-varying) then the fitted recursion is unrolled
forward, same in-sample fit convention historical_cvar already uses (not
claimed as an OOS forecast).

Verified against a synthetic GARCH-like volatility-clustering series before
trusting real data: CAViaR's VaR_t should visibly widen during the simulated
high-vol regime and narrow during the low-vol regime, unlike a static VaR
which is constant by construction.

Read-only. Never fetches, never modifies cvar.py's own output.

Usage:
    python research/caviar_dynamic_var.py
"""
import logging
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvar import daily_pnl_series, historical_cvar

_BACKTEST_DIR = "output/backtest"
_STATS_DIR = "output/stats"
_MIN_CALIBRATION_DAYS = 30

log = logging.getLogger("caviar_dynamic_var")


def _tick_loss(u: np.ndarray, alpha: float) -> float:
    return float(np.sum(u * (alpha - (u < 0).astype(float))))


def _unroll_var(beta: np.ndarray, losses: np.ndarray, var0: float) -> np.ndarray:
    beta0, beta1, beta2 = beta
    n = len(losses)
    var = np.empty(n)
    var[0] = var0
    for t in range(1, n):
        var[t] = beta0 + beta1 * var[t - 1] + beta2 * abs(losses[t - 1])
    return var


def _objective(beta: np.ndarray, losses: np.ndarray, var0: float, alpha: float) -> float:
    var = _unroll_var(beta, losses, var0)
    return _tick_loss(losses - var, alpha)


def fit_caviar_sav(daily_pnl: np.ndarray, alpha: float,
                    min_calibration_days: int = _MIN_CALIBRATION_DAYS) -> dict:
    losses = -np.asarray(daily_pnl, dtype=float)
    n = len(losses)
    if n < min_calibration_days + 10:
        return {}

    var0 = float(np.quantile(losses[:min_calibration_days], alpha))
    # Starting guess: a mild persistence + reaction, standard CAViaR init
    beta_init = np.array([var0 * 0.1, 0.85, 0.10])
    bounds = [(None, None), (0.0, 0.995), (0.0, None)]  # beta1 < 1 for stability

    # BUG FIX (found via synthetic verification): scipy >= 1.7's Nelder-Mead
    # DOES accept `bounds` directly (enforced by clipping proposed simplex
    # points) — passing it here instead of relying on incomplete post-hoc
    # clipping (the original version only clipped beta1, not beta2, which
    # went negative and produced a nonsensical VaR with a 95% exceedance
    # rate against a 5% target).
    result = minimize(
        _objective, beta_init, args=(losses, var0, alpha),
        method="Nelder-Mead", bounds=bounds,
        options={"maxiter": 5000, "xatol": 1e-8, "fatol": 1e-8},
    )
    beta_fit = result.x
    var_series = _unroll_var(beta_fit, losses, var0)

    exceedances = losses > var_series
    n_exceed = int(exceedances.sum())
    exceed_rate = n_exceed / n

    return {
        "beta0": float(beta_fit[0]), "beta1": float(beta_fit[1]), "beta2": float(beta_fit[2]),
        "var_series": var_series, "losses": losses,
        "n_exceedances": n_exceed, "n_total": n, "exceedance_rate": exceed_rate,
        "target_alpha": alpha, "converged": bool(result.success),
    }


def main():
    for suffix in ["layer1", "layer1_holdout"]:
        trades_path = os.path.join(_BACKTEST_DIR, f"trades_{suffix}.parquet")
        daily = daily_pnl_series(trades_path)
        if daily is None:
            print(f"[{suffix}] no usable trades — skipping")
            continue

        alpha = 0.95  # matches cvar.py's own _ALPHAS convention (upper quantile of losses)
        result = fit_caviar_sav(daily.to_numpy(), alpha)
        if not result:
            print(f"[{suffix}] insufficient history for CAViaR (n={len(daily)})")
            continue

        static = historical_cvar(daily.to_numpy(), alpha)
        print(f"[{suffix}] n_days={result['n_total']}  "
              f"CAViaR: beta=({result['beta0']:.2f}, {result['beta1']:.3f}, {result['beta2']:.3f})  "
              f"exceedance_rate={result['exceedance_rate']:.3f} (target={alpha})  "
              f"converged={result['converged']}")
        print(f"  Static historical VaR (constant): ${static['var']:.2f}  "
              f"CAViaR VaR range: [${result['var_series'].min():.2f}, ${result['var_series'].max():.2f}] "
              f"(mean=${result['var_series'].mean():.2f})")

        os.makedirs(_STATS_DIR, exist_ok=True)
        out_df = pd.DataFrame({
            "date": daily.index, "loss": result["losses"], "caviar_var": result["var_series"],
        })
        out_df.to_parquet(os.path.join(_STATS_DIR, f"caviar_dynamic_var_{suffix}.parquet"), index=False)
        print(f"  Wrote output/stats/caviar_dynamic_var_{suffix}.parquet")


if __name__ == "__main__":
    main()
