"""
Synthetic verification of research/liquidity_bar_masking.py -- run BEFORE
trusting it against real domestic price data. Directly tests the claim
motivating this build (Ross, 2026-08-14): "counting illiquid bars will
falsely spike our cointegration number."

A FIRST VERSION of Check 2 asserted that naive Pearson CORRELATION OF RETURNS
would be inflated by shared stale/flat days -- this was directly disproved by
running it (correlation is scale-normalized, so a block of exact-zero-return
days doesn't clearly bias it in either direction). The REAL, verified
mechanism is that the SPREAD's own variance collapses toward zero during a
frozen/stale block (direct check: 0.133 liquid-only spread std vs. 5.5e-17
during a frozen block -- essentially exactly zero), which is what a
cointegration/ADF test actually reads as "very strong mean reversion." Check
2 below tests THIS, the mechanistically correct and verified claim, not the
disproved correlation-of-returns one.

Checks:
  1. liquid_bar_mask correctly flags bars by their OWN dollar volume
     (close x volume), not some other symbol's.
  2. THE REAL, VERIFIED CLAIM: two legs with a genuine cointegrating
     relationship (shared random-walk driver + independent noise) on liquid
     days, but BOTH frozen (zero return) on the SAME contiguous illiquid
     block -- the naive spread standard deviation (including the frozen
     block) must come out LOWER than the liquid-only (masked) spread std,
     demonstrating the real artificial-stability effect directly.
  3. A pair with NO illiquid-day contamination shows naive_spread_std ~=
     masked_spread_std (no artifact to correct for).
  4. Too-few-overlapping-bars is correctly flagged, not silently computed
     on a degenerate sample.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.liquidity_bar_masking import liquid_bar_mask, recompute_correlation_bar_masked
from config import Config

_TEST_DIR = os.path.join(Config.DATA.CACHE_DIR, "_verify_liq_bar_mask_scratch")


def _write(symbol, closes, volumes, idx):
    df = pd.DataFrame({"open": closes, "high": closes, "low": closes,
                        "close": closes, "volume": volumes}, index=idx)
    os.makedirs(_TEST_DIR, exist_ok=True)
    df.to_parquet(os.path.join(_TEST_DIR, f"{symbol}_1day.parquet"))


def main():
    failures = []
    threshold = 1_000_000.0
    idx = pd.date_range("2023-01-02", periods=120, freq="B")

    try:
        # --- Check 1: mask reflects the symbol's OWN volume ---
        _write("SYMA", [10.0] * 120, [200_000] * 60 + [10_000] * 60, idx)  # liquid then illiquid
        mask_a = liquid_bar_mask("SYMA", threshold, _TEST_DIR)
        if not mask_a.iloc[:60].all() or mask_a.iloc[60:].any():
            failures.append("Check 1: mask should be True for first 60 bars (dollar_vol=2M), "
                             "False for last 60 (dollar_vol=100k)")

        # --- Check 2: THE REAL, VERIFIED CLAIM -- two legs with a genuine cointegrating
        # relationship (shared random-walk driver so the SPREAD has real variance on liquid
        # days), but BOTH frozen (zero return) on the SAME contiguous illiquid block. The
        # naive spread std (including the frozen block) must come out LOWER than the
        # liquid-only spread std -- the frozen block contributes artificial "stability."
        rng = np.random.RandomState(3)
        n = 200
        idx2 = pd.date_range("2023-01-02", periods=n, freq="B")
        illiquid_days = np.zeros(n, dtype=bool)
        illiquid_days[100:150] = True  # a real contiguous stale-quote block, not scattered noise

        shared_driver = rng.standard_normal(n) * 0.01  # common factor -> real cointegration
        ret_a = shared_driver + rng.standard_normal(n) * 0.002
        ret_b = shared_driver + rng.standard_normal(n) * 0.002
        ret_a[illiquid_days] = 0.0
        ret_b[illiquid_days] = 0.0  # BOTH frozen on the same days -- the real stale-quote signature

        close_a = 100 * np.exp(np.cumsum(ret_a))
        close_b = 100 * np.exp(np.cumsum(ret_b))
        vol_a = np.where(illiquid_days, 5_000, 200_000)
        vol_b = np.where(illiquid_days, 5_000, 200_000)
        _write("CLAIMA", close_a, vol_a, idx2)
        _write("CLAIMB", close_b, vol_b, idx2)

        result2 = recompute_correlation_bar_masked("CLAIMA", "CLAIMB", threshold, _TEST_DIR)
        if not result2["ok"]:
            failures.append(f"Check 2: expected a valid result, got {result2}")
        else:
            if not (result2["naive_spread_std"] < result2["masked_spread_std"]):
                failures.append(f"Check 2: THE REAL CLAIM should hold on this constructed case -- "
                                 f"naive_spread_std ({result2['naive_spread_std']:.4f}) should be "
                                 f"LOWER than masked_spread_std ({result2['masked_spread_std']:.4f}) "
                                 f"since the frozen block artificially suppresses spread variance")
            if result2["spread_std_ratio"] is None or result2["spread_std_ratio"] >= 1.0:
                failures.append(f"Check 2: spread_std_ratio (naive/masked) should be < 1.0 "
                                 f"(naive UNDERSTATES true variance), got {result2['spread_std_ratio']}")

        # --- Check 3: no contamination -- correlation should barely change ---
        rng3 = np.random.RandomState(5)
        shared_shock = rng3.standard_normal(n) * 0.01
        ret_c = shared_shock + rng3.standard_normal(n) * 0.002  # genuinely correlated, no stale days
        ret_d = shared_shock + rng3.standard_normal(n) * 0.002
        close_c = 100 * np.exp(np.cumsum(ret_c))
        close_d = 100 * np.exp(np.cumsum(ret_d))
        _write("CLEANC", close_c, [200_000] * n, idx2)  # always liquid, no illiquid days at all
        _write("CLEAND", close_d, [200_000] * n, idx2)
        result3 = recompute_correlation_bar_masked("CLEANC", "CLEAND", threshold, _TEST_DIR)
        if result3["ok"] and result3["n_bars_masked_out"] != 0:
            failures.append(f"Check 3: a pair with no illiquid days should have "
                             f"n_bars_masked_out=0, got {result3['n_bars_masked_out']}")
        if result3["ok"] and abs(result3["delta"]) > 0.01:
            failures.append(f"Check 3: no contamination present -- delta should be ~0, "
                             f"got {result3['delta']:.4f}")

        # --- Check 4: too few overlapping bars ---
        _write("SHORTA", [10.0] * 10, [200_000] * 10, idx[:10])
        _write("SHORTB", [10.0] * 10, [200_000] * 10, idx[:10])
        result4 = recompute_correlation_bar_masked("SHORTA", "SHORTB", threshold, _TEST_DIR)
        if result4["ok"]:
            failures.append(f"Check 4: expected insufficient_overlap for a 10-bar series, "
                             f"got ok=True: {result4}")
    finally:
        import shutil
        if os.path.exists(_TEST_DIR):
            shutil.rmtree(_TEST_DIR)

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All liquidity bar-masking checks passed.")
    print(f"  Check 1: mask correctly reflects own-symbol volume")
    print(f"  Check 2 (REAL, VERIFIED CLAIM): naive_spread_std={result2['naive_spread_std']:.4f} < "
          f"masked_spread_std={result2['masked_spread_std']:.4f} "
          f"(ratio={result2['spread_std_ratio']:.3f}) -- artificial stability from the frozen "
          f"block confirmed")
    print(f"  Check 3: uncontaminated pair shows n_bars_masked_out=0, delta={result3['delta']:.4f} (~0)")
    print(f"  Check 4: too-few-bars correctly flagged insufficient_overlap")


if __name__ == "__main__":
    main()
