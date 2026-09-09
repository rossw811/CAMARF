"""
Synthetic verification for a real crash hit live (2026-09-03) on
research/pit_wfa_wrds_daily.py's first full-scale expanding-fold run:

    TypeError: float() argument must be a string or a real number, not 'NoneType'
    File "backtest.py", line 484, in run
        hurst = float(pair_row.get("hurst_rs", np.nan))

Root cause: pandas Series.get(key, default) only returns the default when
the KEY is absent -- pit_wfa_wrds_daily.py's pair_row always sets the
"hurst_rs" key (via getattr(pair_result, "hurst_rs", np.nan) at
pit_wfa_wrds_daily.py:260), but the underlying hurst_rs computation itself
can genuinely return None (insufficient data for the R/S Hurst estimate),
so the key exists with value None. .get()'s default never fires; float(None)
crashes. pit_wfa.py's own 1h path apparently never hit this in practice
(more bars per pair -> hurst_rs estimate reliably succeeds), but the bug is
in the shared BacktestEngine.run(), not either caller.

Run: python debug/_verify_backtest_hurst_none_fix.py
"""
import numpy as np
import pandas as pd


def old_behavior(pair_row):
    return float(pair_row.get("hurst_rs", np.nan))


def new_behavior(pair_row):
    _hurst_raw = pair_row.get("hurst_rs", np.nan)
    return float(_hurst_raw) if _hurst_raw is not None else np.nan


def main():
    # Reproduces the exact real scenario: key present, value is None. Needs at least one
    # other float field alongside the strings/None -- with only strings+None, pandas
    # infers a 'str' dtype and silently normalizes None to NaN itself (verified directly),
    # masking the bug. The real pair_row always carries several float fields
    # (hedge_ratio_ols, coint_fraction_rolling, ...) alongside hurst_rs, which is what
    # forces the object dtype that lets a real None survive into pair_row.get().
    pair_row_none = pd.Series({
        "hurst_rs": None, "symbol_a": "AAA", "symbol_b": "BBB",
        "hedge_ratio_ols": 1.05, "coint_fraction_rolling": 0.7,
    })

    crashed = False
    try:
        old_behavior(pair_row_none)
    except TypeError:
        crashed = True
    assert crashed, "Test setup failed to reproduce the real crash -- old behavior should raise TypeError"
    print("PASS: old behavior reproduces the real TypeError crash on hurst_rs=None")

    fixed_result = new_behavior(pair_row_none)
    assert np.isnan(fixed_result), f"Fixed behavior should coerce None to NaN, got {fixed_result}"
    print(f"PASS: fixed behavior coerces hurst_rs=None to NaN ({fixed_result}), no crash")

    # Missing key entirely (the case .get()'s default was originally meant for) still works.
    pair_row_missing = pd.Series({
        "symbol_a": "AAA", "symbol_b": "BBB", "hedge_ratio_ols": 1.05, "coint_fraction_rolling": 0.7,
    })
    assert np.isnan(new_behavior(pair_row_missing)), "Missing key should still default to NaN"
    print("PASS: missing hurst_rs key still defaults to NaN (unchanged)")

    # A genuine finite value passes through unaffected.
    pair_row_valid = pd.Series({
        "hurst_rs": 0.35, "symbol_a": "AAA", "symbol_b": "BBB",
        "hedge_ratio_ols": 1.05, "coint_fraction_rolling": 0.7,
    })
    assert new_behavior(pair_row_valid) == 0.35, "A genuine finite hurst_rs value must pass through unchanged"
    print("PASS: a genuine finite hurst_rs value (0.35) passes through unchanged")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
