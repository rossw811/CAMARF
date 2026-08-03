"""
Synthetic verification of BUG-D100: `garch_stop`'s "is current vol elevated"
check in wfa.py::_run_fold_backtest and backtest.py::BacktestEngine.run used
a full-sample `np.nanstd(z_arr)` as the comparison baseline — bar i's
"historical" volatility included every bar AFTER i in the same test
window/backtest run, not just bars at or before i. The causal 100-bar
rolling numerator (`_rolling_z_std`) was already fine; only the denominator
was full-sample.

Two checks:
  1. Structural: confirm both source files no longer contain the old
     full-sample `np.nanstd(z_arr)` baseline pattern for garch_stop, and do
     contain the new `.expanding(` causal baseline.
  2. Numerical: the causal formula itself (expanding std, floored at 1.0,
     min_periods=10) — reimplemented here identically to the fixed source —
     satisfies the actual no-lookahead invariant: bar i's value must be
     unchanged when later bars (i+1 onward) are altered. A flat
     np.nanstd(z_arr) baseline would fail this trivially (every bar's value
     depends on the whole array); an expanding-window baseline should pass
     by construction. This nails down that the fix wasn't accidentally
     implemented as some other look-ahead-preserving transform (e.g. a
     centered or backward-shifted window).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

rng = np.random.default_rng(100)


def _causal_hist_z_std(z_arr):
    """Mirrors the exact fixed formula in wfa.py/backtest.py."""
    arr = pd.Series(z_arr).expanding(min_periods=10).std().values
    return np.where(np.isfinite(arr) & (arr > 0), arr, 1.0)


def main():
    failures = []

    # --- 1. Structural check: source no longer has the full-sample pattern ---
    for fname in ("wfa.py", "backtest.py"):
        path = os.path.join(_ROOT, fname)
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        if re.search(r"_hist_z_std\s*=\s*float\(np\.nanstd\(z_arr\)\)", src):
            failures.append(f"{fname}: still contains the old full-sample np.nanstd(z_arr) baseline")
        if "_hist_z_std_arr" not in src or ".expanding(min_periods=10).std()" not in src:
            failures.append(f"{fname}: does not contain the new expanding-window causal baseline")
        if re.search(r"_rolling_z_std\[i\]\s*>\s*2\.0\s*\*\s*_hist_z_std\b(?!_arr)", src):
            failures.append(f"{fname}: usage site still compares against scalar _hist_z_std, not _hist_z_std_arr[i]")

    # --- 2. Numerical no-lookahead invariant ---
    n = 500
    cutoff = 250
    z_shared_past = rng.normal(scale=1.0, size=cutoff)

    # Two "futures" — one calm, one a huge vol spike — appended after the
    # same shared past.
    z_future_calm = rng.normal(scale=1.0, size=n - cutoff)
    z_future_spike = rng.normal(scale=15.0, size=n - cutoff)

    z_a = np.concatenate([z_shared_past, z_future_calm])
    z_b = np.concatenate([z_shared_past, z_future_spike])

    arr_a = _causal_hist_z_std(z_a)
    arr_b = _causal_hist_z_std(z_b)

    # Past-window values (indices < cutoff) must be IDENTICAL regardless of
    # what happens in the future tail — that's the whole point of "causal".
    past_diff = np.nanmax(np.abs(arr_a[:cutoff] - arr_b[:cutoff]))
    if past_diff > 1e-9:
        failures.append(
            f"LOOKAHEAD: past-window _hist_z_std_arr values differ by up to "
            f"{past_diff:.6f} depending on FUTURE data — baseline is not causal."
        )

    # Sanity: the future windows SHOULD differ substantially post-cutoff
    # (confirms the test construction actually distinguishes the two
    # scenarios — a formula that's constant everywhere would trivially also
    # pass the check above for the wrong reason).
    future_diff = np.nanmax(np.abs(arr_a[cutoff:] - arr_b[cutoff:]))
    if future_diff < 1.0:
        failures.append(
            f"future-window values only differ by {future_diff:.4f} — synthetic "
            "vol-spike construction too weak to meaningfully exercise the fix"
        )

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("BUG-D100 verification passed.")
    print(f"  past-window max diff under differing futures: {past_diff:.2e} (causal)")
    print(f"  future-window max diff (spike vs calm): {future_diff:.4f} (construction is meaningful)")


if __name__ == "__main__":
    main()
