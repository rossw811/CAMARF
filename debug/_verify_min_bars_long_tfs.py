"""
Regression test for code-review finding C13 (2026-09-26): Config.DATA.MIN_BARS_REQUIRED had no
3M/6M/1Y entries although all three are in WRDS_PRIMARY_TFS, so DataCleaner.clean() fell back to
100 bars -- 25 years of quarters, 50 of half-years, 100 of annual bars -- rejecting nearly every
symbol at those timeframes (the same gap was fixed in MIN_OVERLAP_BY_TF on 2026-09-12). Missing
entries now derive from MIN_OVERLAP_BY_TF (a symbol can never meet the overlap floor with fewer
bars), instead of a second hardcoded copy.

Run: python debug/_verify_min_bars_long_tfs.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from data import DataCleaner

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _bars(n, freq):
    idx = pd.date_range("1990-01-01", periods=n, freq=freq)
    c = 50 * np.exp(np.cumsum(np.random.default_rng(0).normal(0, 0.05, n)))
    return pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1e6}, index=idx)


def main():
    for tf, freq, n_ok in (("3M", "QS", 40), ("6M", "6MS", 20), ("1Y", "YS", 30)):
        out, rep = DataCleaner.clean(_bars(n_ok, freq), "SYNTH", "equity", tf, tf, source="wrds")
        check(f"{tf}.{n_ok}_bars_accepted", out is not None,
              "" if out is not None else f"rejected: {getattr(rep, 'fail_reason', rep)}")
        out2, rep2 = DataCleaner.clean(_bars(2, freq), "SYNTH", "equity", tf, tf, source="wrds")
        check(f"{tf}.2_bars_rejected", out2 is None, "" if out2 is None else "accepted 2 bars")
    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
