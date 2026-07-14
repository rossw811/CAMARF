"""
debug/_verify_regime_conditional_adjustment.py

Synthetic verification for backtest.py's RegimeConditioner (task 36, regime-
conditional entry sizing). Two checks:

  1. Look-ahead-bias check: RegimeConditioner._get_regime(ts) must only ever
     use macro data dated <= ts. Constructs a synthetic macro series with a
     regime shift at a known date, and confirms a timestamp just BEFORE the
     shift gets the PRE-shift regime label, not the post-shift one (i.e. no
     backward leakage of future regime state into earlier decisions).

  2. Sizing-logic check: confirms check_entry() applies the documented
     binary/continuous size multipliers correctly on a small, hand-computed
     case, and that disabled (enabled=False) always returns (True, 1.0, {}).

Run: python debug/_verify_regime_conditional_adjustment.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest import RegimeConditioner


def check_1_no_lookahead():
    print("Check 1 -- look-ahead bias (regime shift mid-series):")
    dates = pd.date_range("2026-01-01", "2026-01-20", freq="D")
    macro = pd.DataFrame(
        {
            "vix_term_structure": ["backwardation"] * 10 + ["contango"] * 10,
            "yield_curve_regime": ["flat_inverted"] * 10 + ["normal"] * 10,
        },
        index=dates,
    )

    rc = RegimeConditioner(enabled=False)
    rc.enabled = True
    rc._macro = macro
    rc._hmm = None

    # Shift happens exactly at dates[10] (2026-01-11). A timestamp on
    # 2026-01-10 (the last pre-shift day) must NOT see "contango"/"normal".
    pre_shift_ts = pd.Timestamp("2026-01-10 14:30:00")
    post_shift_ts = pd.Timestamp("2026-01-11 09:30:00")

    pre_regime = rc._get_regime(pre_shift_ts)
    post_regime = rc._get_regime(post_shift_ts)

    ok = (
        pre_regime["vix_ts"] == "backwardation"
        and pre_regime["yield"] == "flat_inverted"
        and post_regime["vix_ts"] == "contango"
        and post_regime["yield"] == "normal"
    )
    print(f"  pre-shift ({pre_shift_ts}): {pre_regime}")
    print(f"  post-shift ({post_shift_ts}): {post_regime}")
    print(f"  -> {'PASS' if ok else 'FAIL'}: pre-shift timestamp correctly sees only "
          f"pre-shift regime (no backward leakage)")
    assert ok, "Look-ahead leakage detected: pre-shift timestamp saw post-shift regime"

    # Also confirm a timestamp strictly BEFORE any macro data returns the
    # empty default, not a spurious label.
    before_all_ts = pd.Timestamp("2025-12-25")
    before_regime = rc._get_regime(before_all_ts)
    ok2 = before_regime == {"vix_ts": "", "yield": ""}
    print(f"  before any macro data ({before_all_ts}): {before_regime}")
    print(f"  -> {'PASS' if ok2 else 'FAIL'}: no macro history returns empty defaults, not a guess")
    assert ok2, "Expected empty regime for a timestamp before any macro data exists"


def check_2_sizing_logic():
    print("\nCheck 2 -- sizing logic (binary and continuous modes, and disabled state):")

    # Disabled conditioner must always be a no-op.
    rc_off = RegimeConditioner(enabled=False)
    allow, mult, ctx = rc_off.check_entry(pd.Timestamp("2026-01-15"), "1h")
    ok_off = (allow is True) and (mult == 1.0) and (ctx == {})
    print(f"  disabled -> allow={allow} mult={mult} ctx={ctx}  -> {'PASS' if ok_off else 'FAIL'}")
    assert ok_off

    # Binary mode: favorable regime (backwardation) should give 1.5x.
    import config
    orig_sizing = config.Config.BACKTEST.REGIME_SIZING
    orig_hard = config.Config.BACKTEST.REGIME_HARD_FILTER
    try:
        config.Config.BACKTEST.REGIME_SIZING = "binary"
        config.Config.BACKTEST.REGIME_HARD_FILTER = False

        dates = pd.date_range("2026-01-01", "2026-01-20", freq="D")
        macro = pd.DataFrame(
            {
                "vix_term_structure": ["backwardation"] * 20,
                "yield_curve_regime": ["normal"] * 20,
            },
            index=dates,
        )
        rc = RegimeConditioner(enabled=False)
        rc.enabled = True
        rc._macro = macro
        rc._hmm = None

        allow, mult, ctx = rc.check_entry(pd.Timestamp("2026-01-15"), "1h")
        ok_bin = allow is True and abs(mult - 1.5) < 1e-9
        print(f"  binary, favorable vix_ts=backwardation -> mult={mult}  -> "
              f"{'PASS' if ok_bin else 'FAIL'} (expect 1.5)")
        assert ok_bin

        # Continuous mode: backwardation hl_ratio=0.646 -> 1/0.646=1.548, clipped [0.5,2.0]
        config.Config.BACKTEST.REGIME_SIZING = "continuous"
        allow, mult, ctx = rc.check_entry(pd.Timestamp("2026-01-15"), "1h")
        expected = float(np.clip(1.0 / 0.646, 0.5, 2.0))
        ok_cont = allow is True and abs(mult - expected) < 1e-3
        print(f"  continuous, vix_ts=backwardation -> mult={mult}  -> "
              f"{'PASS' if ok_cont else 'FAIL'} (expect {expected:.4f})")
        assert ok_cont
    finally:
        config.Config.BACKTEST.REGIME_SIZING = orig_sizing
        config.Config.BACKTEST.REGIME_HARD_FILTER = orig_hard


if __name__ == "__main__":
    check_1_no_lookahead()
    check_2_sizing_logic()
    print("\nALL CHECKS PASSED -- RegimeConditioner is causal (no look-ahead leakage) and "
          "its binary/continuous sizing logic matches the documented formulas.")
