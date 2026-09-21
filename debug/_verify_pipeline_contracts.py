"""
Synthetic verification for research/pipeline_contracts.py.
Run: python debug/_verify_pipeline_contracts.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.pipeline_contracts import (
    PAIRS_OVERRIDE_CONTRACT, SPREAD_SERIES_CONTRACT, TRADES_CONTRACT, validate,
)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def test_pairs_override_stripped_schema_fails():
    # Exactly the real mistake: 3-column override file
    df = pd.DataFrame({"symbol_a": ["A"], "symbol_b": ["B"], "tf_label": ["1D"]})
    violations = validate(df, PAIRS_OVERRIDE_CONTRACT)
    check("pairs_override.stripped_schema_flagged", len(violations) > 0, violations)
    check("pairs_override.flags_missing_hedge_ratio",
          any("hedge_ratio_ols" in v for v in violations), violations)


def test_pairs_override_full_schema_passes():
    df = pd.DataFrame({
        "symbol_a": ["A", "B"], "symbol_b": ["X", "Y"], "tf_label": ["1D", "1D"],
        "hedge_ratio_ols": [1.02, 0.87], "coint_fraction_rolling": [0.9, 0.8],
        "coint_pvalue_adjusted": [0.01, 0.02],
    })
    violations = validate(df, PAIRS_OVERRIDE_CONTRACT)
    check("pairs_override.full_schema_passes", len(violations) == 0, violations)


def test_spread_series_all_nan_half_life_fails():
    # Exactly the real KVUE/KMB bug shape
    n = 100
    df = pd.DataFrame({
        "spread": np.random.randn(n), "z_rolling": np.random.randn(n),
        "half_life_rolling": [np.nan] * n,
    })
    violations = validate(df, SPREAD_SERIES_CONTRACT)
    check("spread_series.all_nan_half_life_flagged",
          any("half_life_rolling" in v for v in violations), violations)


def test_spread_series_healthy_passes():
    n = 100
    df = pd.DataFrame({
        "spread": np.random.randn(n), "z_rolling": np.random.randn(n),
        "half_life_rolling": np.abs(np.random.randn(n)) + 5,
    })
    violations = validate(df, SPREAD_SERIES_CONTRACT)
    check("spread_series.healthy_passes", len(violations) == 0, violations)


def test_spread_series_too_few_rows_fails():
    df = pd.DataFrame({"spread": [1.0] * 10, "z_rolling": [0.5] * 10, "half_life_rolling": [10.0] * 10})
    violations = validate(df, SPREAD_SERIES_CONTRACT)
    check("spread_series.too_few_rows_flagged", any("rows" in v for v in violations), violations)


def test_trades_missing_symbol_columns_fails():
    df = pd.DataFrame({"total_pnl": [1.0, 2.0]})
    violations = validate(df, TRADES_CONTRACT)
    check("trades.missing_symbols_flagged", len(violations) >= 2, violations)


def test_trades_zero_rows_ok():
    df = pd.DataFrame({"symbol_a": [], "symbol_b": [], "total_pnl": []})
    violations = validate(df, TRADES_CONTRACT)
    check("trades.zero_rows_legitimately_ok", len(violations) == 0, violations)


if __name__ == "__main__":
    test_pairs_override_stripped_schema_fails()
    test_pairs_override_full_schema_passes()
    test_spread_series_all_nan_half_life_fails()
    test_spread_series_healthy_passes()
    test_spread_series_too_few_rows_fails()
    test_trades_missing_symbol_columns_fails()
    test_trades_zero_rows_ok()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
