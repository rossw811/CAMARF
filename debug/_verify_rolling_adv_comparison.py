"""
debug/_verify_rolling_adv_comparison.py -- synthetic ground-truth
verification for research/rolling_adv_comparison.py, BEFORE trusting it
against real WRDS data.

Three things must be proven, not just asserted:
  1. Causal correctness: rolling_adv() at date T depends ONLY on data up to
     and including T -- mutating data strictly AFTER T must not change the
     value AT T. This is the single most important check (the exact
     `center=True`-class lookahead bug this project's CLAUDE.md already
     flags as a known failure pattern), proven directly by mutation, not
     assumed from pandas' documented rolling-window default behavior.
  2. The flat (whole-history) ADV genuinely blends distinct liquidity
     regimes into one number that can misrepresent EITHER regime --
     demonstrated with two synthetic symbols, one producing a "false
     liquid" disagreement (flat says OK, an early window actually wasn't)
     and one producing a "false illiquid" disagreement (flat says NO, a
     later window actually was liquid).
  3. compare_symbol() correctly flags these disagreements at the exact
     window indices where they're expected, not just "some" disagreement
     somewhere.

Run: python debug/_verify_rolling_adv_comparison.py
(All checks are synthetic/offline -- no WRDS connection needed.)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research.rolling_adv_comparison as rac


def check(name, cond):
    # bool(cond) rather than returning cond as-is -- a short-circuited
    # `list_var and expr` can return the empty list itself (not False) when
    # list_var is falsy, which then breaks a later `ok &= check(...)` with a
    # TypeError instead of a clean FAIL. Found directly while writing this
    # file's own tests.
    cond = bool(cond)
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


def make_two_regime_df(regime1_days, regime1_dv, regime2_days, regime2_dv):
    """Synthetic OHLCV-shaped df: constant dollar volume per regime (price
    fixed at $50, volume chosen so close*volume == the target dollar
    volume exactly), regime1 first then regime2."""
    n = regime1_days + regime2_days
    price = 50.0
    vol1 = regime1_dv / price
    vol2 = regime2_dv / price
    volume = np.concatenate([np.full(regime1_days, vol1), np.full(regime2_days, vol2)])
    idx = pd.date_range("2000-01-01", periods=n, freq="B")
    return pd.DataFrame({"close": price, "volume": volume}, index=idx)


def verify_na_dollar_volume_handled():
    print("\n=== 0. flat_adv/rolling_adv: pd.NA in close/volume doesn't crash (regression) ===")
    # Found live (2026-07-27): running against the real 2,846-symbol WRDS
    # cache crashed on the first symbol whose close*volume product's .mean()
    # returned pandas' own pd.NA (nullable-dtype or all-null column) rather
    # than np.nan -- float(pd.NA) raises TypeError, not a clean NaN result.
    all_na_df = pd.DataFrame({
        "close": pd.array([None, None, None], dtype="Float64"),
        "volume": pd.array([None, None, None], dtype="Float64"),
    })
    flat_val = rac.flat_adv(all_na_df)
    ok = check("flat_adv on an all-null nullable-dtype df returns a plain NaN float, not a crash",
               isinstance(flat_val, float) and np.isnan(flat_val))

    mixed_df = pd.DataFrame({
        "close": pd.array([50.0, None, 50.0], dtype="Float64"),
        "volume": pd.array([1000.0, None, 2000.0], dtype="Float64"),
    })
    roll = rac.rolling_adv(mixed_df, window=2)
    ok &= check("rolling_adv on a mixed null/real nullable-dtype df runs without crashing",
                isinstance(roll, pd.Series))
    return ok


def verify_rolling_adv_causality():
    print("\n=== 1. rolling_adv: causal correctness (no lookahead) ===")
    df = make_two_regime_df(150, 2_000_000, 150, 40_000_000)
    roll_before = rac.rolling_adv(df, window=50)

    df_mutated = df.copy()
    # Mutate everything AFTER index 100 to wildly different values.
    df_mutated.iloc[101:, df_mutated.columns.get_loc("volume")] = 999_999_999.0
    roll_after = rac.rolling_adv(df_mutated, window=50)

    ok = check("rolling_adv value AT index 100 is UNCHANGED after mutating everything after it",
               abs(roll_before.iloc[100] - roll_after.iloc[100]) < 1e-6)
    ok &= check("rolling_adv value AT index 50 is UNCHANGED after mutating everything after index 100",
                abs(roll_before.iloc[50] - roll_after.iloc[50]) < 1e-6)
    ok &= check("rolling_adv value AFTER the mutation point DOES change (sanity -- the mutation is real)",
                abs(roll_before.iloc[150] - roll_after.iloc[150]) > 1e6)
    return ok


def verify_flat_adv_blends_regimes():
    print("\n=== 2. flat_adv genuinely blends distinct liquidity regimes into one number ===")
    illiquid_then_liquid = make_two_regime_df(150, 2_000_000, 150, 40_000_000)
    flat_val = rac.flat_adv(illiquid_then_liquid)
    ok = check(f"flat ADV ({flat_val/1e6:.1f}M) sits strictly between the two regimes' own values "
               f"(2M and 40M) -- neither regime's true liquidity is represented",
               2_000_000 < flat_val < 40_000_000)
    return ok


def verify_false_illiquid_case():
    print("\n=== 3. 'false illiquid' disagreement: flat says NO, a later window actually was liquid ===")
    df = make_two_regime_df(150, 2_000_000, 150, 40_000_000)  # illiquid first, liquid second
    threshold = 25_000_000.0
    rows = rac.compare_symbol("FALSE_ILLIQUID_TEST", df, threshold, window_bars=100, step_bars=50,
                               rolling_window=30)
    by_start = {r["window_start_idx"]: r for r in rows}

    ok = check("flat_adv verdict for this symbol is 'NOT eligible' (below $25M)",
               rows and not rows[0]["flat_eligible"])
    ok &= check("window starting at idx=200 (fully within the later liquid regime) IS rolling-eligible",
                200 in by_start and by_start[200]["rolling_eligible"])
    ok &= check("window starting at idx=200 is flagged as a 'false_illiquid' disagreement",
                200 in by_start and by_start[200]["false_illiquid"])
    ok &= check("window starting at idx=50 (fully within the early illiquid regime) is NOT flagged as disagreeing",
                50 in by_start and not by_start[50]["disagree"])
    return ok


def verify_false_liquid_case():
    print("\n=== 4. 'false liquid' disagreement (the dangerous case): flat says OK, an early window actually wasn't ===")
    # illiquid first (100 days) then liquid (200 days) -- proportions chosen
    # so the flat average lands ABOVE the threshold (says "eligible" overall)
    # even though the first 100 days were genuinely illiquid.
    df = make_two_regime_df(100, 2_000_000, 200, 40_000_000)
    threshold = 25_000_000.0
    flat_val = rac.flat_adv(df)
    print(f"    flat_adv = {flat_val/1e6:.1f}M (expect > 25M)")

    rows = rac.compare_symbol("FALSE_LIQUID_TEST", df, threshold, window_bars=100, step_bars=50,
                               rolling_window=30)
    by_start = {r["window_start_idx"]: r for r in rows}

    ok = check("flat_adv verdict for this symbol IS 'eligible' (above $25M)",
               rows and rows[0]["flat_eligible"])
    ok &= check("window starting at idx=50 (fully within the early illiquid regime) is FALSE_LIQUID-flagged",
                50 in by_start and by_start[50]["false_liquid"])
    ok &= check("window starting at idx=200 (fully within the later liquid regime) is NOT flagged as disagreeing",
                200 in by_start and not by_start[200]["disagree"])
    return ok


def main():
    results = [
        verify_na_dollar_volume_handled(),
        verify_rolling_adv_causality(),
        verify_flat_adv_blends_regimes(),
        verify_false_illiquid_case(),
        verify_false_liquid_case(),
    ]
    print("\n" + "=" * 60)
    if all(results):
        print("ALL CHECKS PASSED")
    else:
        print(f"FAILURES: {results.count(False)}/{len(results)} check groups failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
