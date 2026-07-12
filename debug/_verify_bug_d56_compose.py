"""
Verifies the BUG-D56 fix in backtest.py (2026-07-11): coint_frac_sizing must
now COMPOSE (multiply) with continuous_forecast_carver/continuous_forecast_linear
sizing rather than being silently discarded when both STORM flags are set.

Runs the REAL BacktestEngine.run() (not a re-implemented copy of the formula)
on a minimal synthetic single-trade spread series, comparing n_shares_a across
4 storm_flags configurations:
  A. neither flag                      -> baseline N_SHARES_PER_TRADE
  B. coint_frac_sizing only            -> baseline * coint_frac
  C. continuous_forecast_carver only   -> baseline * carver_scale (coint_frac ignored, expected)
  D. both flags together               -> baseline * carver_scale * coint_frac (the fix)

Before the fix, case D would equal case C exactly (coint_frac silently
discarded). After the fix, case D must differ from case C by exactly the
coint_frac multiplier, and must NOT equal case B or C.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from backtest import BacktestEngine, RegimeConditioner, MLConditioner
from config import Config

COINT_FRAC = 0.5  # deliberately != 1.0 so composition is visible


def build_spread_df():
    n = 100
    idx = pd.date_range("2024-01-01 09:30", periods=n, freq="1h")
    z = np.full(n, 0.3)  # warm-up bars, nonzero (run() drops z_rolling==0 rows)
    z[60] = 2.5           # triggers entry (short side, |z|>=ENTRY_ZSCORE=2.0)
    z[61] = 0.0            # EXIT_ZSCORE=0.0 crossing -> immediate signal_exit next bar
    z[61] = 0.0001          # keep nonzero so the row isn't dropped, still <= EXIT_ZSCORE
    spread = np.zeros(n)
    hl = np.full(n, 20.0)  # >= MIN_HALF_LIFE_BARS=5
    df = pd.DataFrame(
        {
            "z_rolling": z,
            "spread": spread,
            "half_life_rolling": hl,
            "gap_flag_a": 0,
            "gap_flag_b": 0,
        },
        index=idx,
    )
    return df


def build_pair_row():
    return pd.Series({
        "symbol_a": "TESTA", "symbol_b": "TESTB", "tf_label": "1h",
        "hedge_ratio_ols": 1.0, "hedge_ratio_kalman_mean": 1.0,
        "hurst_rs": 0.4, "coint_fraction_rolling": COINT_FRAC,
    })


def run_case(storm_flags):
    engine = BacktestEngine(
        cfg=Config.BACKTEST,
        regime_cond=RegimeConditioner(enabled=False),
        ml_cond=MLConditioner(enabled=False),
        storm_flags=storm_flags,
    )
    trades = engine.run(build_pair_row(), build_spread_df(), hedge_method="ols")
    if not trades:
        return None
    return trades[0].n_shares_a


def main():
    failures = []

    n_baseline = run_case({})
    n_cfrac_only = run_case({"coint_frac_sizing": True})
    n_carver_only = run_case({"continuous_forecast_carver": True})
    n_both = run_case({"coint_frac_sizing": True, "continuous_forecast_carver": True})

    print(f"A. neither flag:                    n_shares_a = {n_baseline}")
    print(f"B. coint_frac_sizing only:           n_shares_a = {n_cfrac_only}  "
          f"(expected ~= {n_baseline} * {COINT_FRAC} = {n_baseline * COINT_FRAC})")
    print(f"C. continuous_forecast_carver only:  n_shares_a = {n_carver_only}")
    print(f"D. both (coint_frac_sizing + carver): n_shares_a = {n_both}  "
          f"(expected ~= {n_carver_only} * {COINT_FRAC} = {n_carver_only * COINT_FRAC})")

    if any(v is None for v in (n_baseline, n_cfrac_only, n_carver_only, n_both)):
        failures.append("one or more cases produced zero trades -- fixture bars need adjustment")
    else:
        if not np.isclose(n_cfrac_only, n_baseline * COINT_FRAC, atol=1):
            failures.append(f"case B: expected ~{n_baseline * COINT_FRAC}, got {n_cfrac_only}")

        # The pre-fix bug: case D would equal case C exactly (coint_frac discarded).
        if n_both == n_carver_only:
            failures.append(
                f"REGRESSION: case D ({n_both}) == case C ({n_carver_only}) -- "
                f"coint_frac_sizing is being silently discarded again, BUG-D56 not fixed"
            )
        if not np.isclose(n_both, n_carver_only * COINT_FRAC, atol=1):
            failures.append(
                f"case D: expected composed value ~{n_carver_only * COINT_FRAC}, got {n_both}"
            )

    print()
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("BUG-D56 compose fix verified: coint_frac_sizing correctly composes "
              "(multiplies) with continuous_forecast_carver instead of being discarded.")


if __name__ == "__main__":
    main()
