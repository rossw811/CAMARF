"""
Synthetic verification of research/fama_french_risk_decomposition.py's
build_daily_return_series/run_regression BEFORE trusting it on real backtest
output.

Checks:
  1. build_daily_return_series correctly reconstructs a daily equity curve
     and returns from a synthetic trades DataFrame with known P&L on known
     exit dates.
  2. A portfolio built EXACTLY as `0.5*mktrf + tiny_noise` recovers a ~0.5
     mktrf loading, ~0 alpha, and high R² -- confirms the regression
     mechanics are correct, not spuriously over/under-fitting.
  3. A portfolio built from pure independent noise (no relationship to any
     factor) shows ~0 loadings on every factor and low R² -- confirms the
     regression doesn't spuriously find structure that isn't there.
  4. Insufficient overlap (fewer than 30 joined days) returns ok=False,
     not a crash or a spurious regression on too little data.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.fama_french_risk_decomposition import build_daily_return_series, run_regression


def main():
    failures = []
    rng = np.random.default_rng(5)

    # --- 1: daily return series reconstruction ---
    trades = pd.DataFrame([
        {"exit_time": pd.Timestamp("2024-01-02"), "actual_pnl": 1000.0},
        {"exit_time": pd.Timestamp("2024-01-02"), "actual_pnl": 500.0},
        {"exit_time": pd.Timestamp("2024-01-04"), "actual_pnl": -300.0},
    ])
    returns = build_daily_return_series(trades, starting_capital=100000.0)
    expected_day1_return = 1500.0 / 100000.0
    if not np.isclose(returns.loc[pd.Timestamp("2024-01-02")], expected_day1_return, atol=1e-9):
        failures.append(f"Day-1 return should be {expected_day1_return}, got "
                         f"{returns.loc[pd.Timestamp('2024-01-02')]}")
    if not np.isclose(returns.loc[pd.Timestamp("2024-01-03")], 0.0, atol=1e-9):
        failures.append(f"No-exit day should have 0 return, got {returns.loc[pd.Timestamp('2024-01-03')]}")
    equity_after_day1 = 100000.0 + 1500.0
    expected_day3_return = -300.0 / equity_after_day1
    if not np.isclose(returns.loc[pd.Timestamp("2024-01-04")], expected_day3_return, atol=1e-9):
        failures.append(f"Day-3 return should be {expected_day3_return} (relative to updated "
                         f"equity), got {returns.loc[pd.Timestamp('2024-01-04')]}")

    # --- 2 & 3: regression mechanics ---
    n = 500
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    mktrf = rng.normal(0.0004, 0.01, n)
    smb = rng.normal(0.0, 0.005, n)
    hml = rng.normal(0.0, 0.006, n)
    rf = np.full(n, 0.00008)
    factors_df = pd.DataFrame({"mktrf": mktrf, "smb": smb, "hml": hml, "rf": rf}, index=dates)

    factor_driven_returns = pd.Series(0.5 * mktrf + rng.normal(0, 0.0005, n), index=dates)
    r_factor = run_regression(factor_driven_returns, factors_df, ["mktrf", "smb", "hml"])
    if not r_factor.get("ok"):
        failures.append(f"Factor-driven portfolio regression should succeed, got {r_factor}")
    else:
        if not np.isclose(r_factor["loadings"]["mktrf"], 0.5, atol=0.1):
            failures.append(f"Factor-driven portfolio should recover mktrf loading ~0.5, "
                             f"got {r_factor['loadings']['mktrf']}")
        if abs(r_factor["alpha_annualized"]) > 0.05:
            failures.append(f"Factor-driven portfolio should have ~0 alpha, got "
                             f"{r_factor['alpha_annualized']}")
        if r_factor["r_squared"] < 0.7:
            failures.append(f"Factor-driven portfolio should have high R² (>=0.7), "
                             f"got {r_factor['r_squared']}")

    noise_returns = pd.Series(rng.normal(0.0, 0.01, n), index=dates)
    r_noise = run_regression(noise_returns, factors_df, ["mktrf", "smb", "hml"])
    if not r_noise.get("ok"):
        failures.append(f"Noise portfolio regression should succeed, got {r_noise}")
    else:
        if any(abs(v) > 0.3 for v in r_noise["loadings"].values()):
            failures.append(f"Noise portfolio should have near-0 loadings, got {r_noise['loadings']}")
        if r_noise["r_squared"] > 0.15:
            failures.append(f"Noise portfolio should have low R², got {r_noise['r_squared']}")

    # --- 4: insufficient overlap ---
    short_returns = pd.Series(rng.normal(0, 0.01, 10), index=dates[:10])
    r_short = run_regression(short_returns, factors_df, ["mktrf", "smb", "hml"])
    if r_short.get("ok"):
        failures.append(f"10-day overlap should be rejected as insufficient, got ok=True")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All Fama-French risk decomposition checks passed.")
    print(f"  factor-driven: mktrf loading={r_factor['loadings']['mktrf']:.3f}, "
          f"alpha_annualized={r_factor['alpha_annualized']:.4f}, R²={r_factor['r_squared']:.3f}")
    print(f"  noise: loadings={r_noise['loadings']}, R²={r_noise['r_squared']:.3f}")
    print(f"  insufficient overlap: ok={r_short.get('ok')}")


if __name__ == "__main__":
    main()
