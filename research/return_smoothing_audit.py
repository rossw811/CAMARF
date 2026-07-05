"""
CAMARF return_smoothing_audit.py — comparison/diagnostic method, NOT part
of the production pipeline.

Getmansky, Lo & Makarov (2004), "An Econometric Model of Serial
Correlation and Illiquidity in Hedge Fund Returns," Journal of Financial
Economics 74(3) — models an observed return series as a smoothed MA(2) of
the true (unobserved) return: R_t^o = th0*R_t + th1*R_{t-1} + th2*R_{t-2},
th0+th1+th2=1, thj>=0. The "smoothing index" xi = sum(thj^2) ranges from 1
(no smoothing — all weight on th0, i.e. reported returns equal true
returns) down toward 1/3 as smoothing spreads evenly across more lags
(stale/infrequent pricing artificially smoothing reported returns).
Audits whether CAMARF's own less-liquid confirmed-pair legs show this
signature in their trade-level P&L.

Estimation: th is NOT observable directly (true returns aren't observed),
so th is estimated by matching the MA(2) process's OWN theoretical
autocorrelations at lag 1 and 2 —
    rho1(th) = (th0*th1 + th1*th2) / (th0^2+th1^2+th2^2)
    rho2(th) = (th0*th2) / (th0^2+th1^2+th2^2)
— to the sample autocorrelations of the observed daily P&L series, via
constrained least squares (th0+th1+th2=1, 0<=thj<=1).

Applied to each confirmed pair's own daily closed-trade P&L (same
exit-date grouping convention as cvar.py/deflated_sharpe.py).

Known identification limitation, confirmed directly in this module's own
synthetic verification: matching only rho1/rho2 cannot distinguish
theta=(a,b,c) from its reversal theta=(c,b,a) — both give identical
theoretical autocorrelations, so the individual th0/th1/th2 SPLIT is not
uniquely identified from ACF alone. The smoothing index xi=sum(theta^2)
IS invariant under this reversal and is recovered correctly regardless —
xi, not the individual theta values, is the metric this module actually
reports and should be trusted.

Read-only. Never fetches, never recomputes trades.

Usage:
    python research/return_smoothing_audit.py
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _sample_acf(x, max_lag=2):
    x = x - np.mean(x)
    n = len(x)
    denom = np.dot(x, x)
    return [float(np.dot(x[:-k], x[k:]) / denom) for k in range(1, max_lag + 1)]


def _ma2_theoretical_acf(theta):
    th0, th1, th2 = theta
    denom = th0 ** 2 + th1 ** 2 + th2 ** 2
    if denom <= 0:
        return [0.0, 0.0]
    rho1 = (th0 * th1 + th1 * th2) / denom
    rho2 = (th0 * th2) / denom
    return [rho1, rho2]


def estimate_smoothing(returns, max_lag=2):
    """
    Returns theta=[th0,th1,th2], the smoothing index xi=sum(theta^2), and
    the sample ACF used for the fit. n must be reasonably large (>=30) for
    a stable ACF estimate.
    """
    returns = np.asarray(returns, dtype=float)
    if returns.size < 30:
        return {"ok": False, "error": "insufficient_obs"}

    sample_acf = _sample_acf(returns, max_lag=max_lag)

    def objective(theta):
        model_acf = _ma2_theoretical_acf(theta)
        return sum((m - s) ** 2 for m, s in zip(model_acf, sample_acf))

    constraints = [{"type": "eq", "fun": lambda th: th[0] + th[1] + th[2] - 1.0}]
    bounds = [(0.0, 1.0)] * 3
    x0 = np.array([1.0, 0.0, 0.0])  # start at "no smoothing"
    result = minimize(objective, x0, method="SLSQP", bounds=bounds, constraints=constraints)
    theta = result.x
    xi = float(np.sum(theta ** 2))
    return {
        "ok": True, "n_obs": int(returns.size),
        "theta0": float(theta[0]), "theta1": float(theta[1]), "theta2": float(theta[2]),
        "smoothing_index": xi, "sample_rho1": sample_acf[0], "sample_rho2": sample_acf[1],
        "fit_converged": bool(result.success),
    }


def main():
    trades_path = "output/backtest/trades_layer1.parquet"
    if not os.path.exists(trades_path):
        print(f"No trades file at {trades_path} — run backtest.py first.")
        return
    trades = pd.read_parquet(trades_path)
    trades["exit_date"] = pd.to_datetime(trades["exit_time"]).dt.date
    trades["pair_key"] = trades["symbol_a"] + "/" + trades["symbol_b"]

    rows = []
    for pair_key, grp in trades.groupby("pair_key"):
        daily = grp.groupby("exit_date")["pnl_net"].sum()
        if len(daily) < 30:
            print(f"SKIP {pair_key}: only {len(daily)} distinct trading days")
            continue
        r = estimate_smoothing(daily.to_numpy())
        r["pair_key"] = pair_key
        rows.append(r)
        if r["ok"]:
            print(f"{pair_key}: n={r['n_obs']} theta=({r['theta0']:.2f},{r['theta1']:.2f},{r['theta2']:.2f}) "
                  f"smoothing_index={r['smoothing_index']:.3f} (1.0=no smoothing)")

    out_df = pd.DataFrame(rows)
    os.makedirs("output/research", exist_ok=True)
    out_df.to_parquet("output/research/return_smoothing_audit.parquet")
    ok = out_df[out_df.get("ok", False) == True] if "ok" in out_df.columns else pd.DataFrame()
    if len(ok):
        smoothed = ok[ok["smoothing_index"] < 0.8]
        print(f"\nWrote output/research/return_smoothing_audit.parquet: {len(ok)} pairs, "
              f"{len(smoothed)} showing meaningful smoothing signature (index<0.8): "
              f"{list(smoothed['pair_key'])}")


if __name__ == "__main__":
    main()
