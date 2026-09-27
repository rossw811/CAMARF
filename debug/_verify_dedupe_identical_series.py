"""
Regression test for the identity-pair root cause (2026-09-27): the WRDS cache holds some securities under two
labels (a ticker plus its own PERMNO<n> alias, e.g. COST / PERMNO87055; or two tickers whose series are
identical, e.g. UAA / UA), so discovery "confirmed" 110 stocks against themselves. universe_loader.
dedupe_identical_series() keeps ONE label per security:
  1. full-length duplicates (ticker vs PERMNO alias) -> keep the plain ticker;
  2. a shorter series identical to a longer one on their whole overlap -> keep the longer
     (a plain ticker still beats an alias regardless of length);
  3. a genuinely different stock with near-identical but not identical returns is NOT merged;
  4. every removal is reported (symbol -> kept symbol).
Run: python debug/_verify_dedupe_identical_series.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from universe_loader import dedupe_identical_series

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2010-01-01", periods=600)
    px = lambda r: 50 * np.exp(np.cumsum(r))
    base = rng.normal(0, 0.01, len(idx))
    other = rng.normal(0, 0.01, len(idx))
    f = lambda v, ix=idx: pd.DataFrame({"close": v}, index=ix)
    frames = {
        "COST": f(px(base)),
        "PERMNO87055": f(px(base)),                               # same security, alias label
        "UAA": f(px(other)),
        "UA": f(px(other)[200:], idx[200:]),                      # shorter, identical on overlap
        "NEAR": f(px(base + rng.normal(0, 1e-4, len(idx)))),      # different stock, near-identical
        "GVKEY000001_01W": f(px(rng.normal(0, 0.01, len(idx)))),  # unrelated
    }
    kept, removed = dedupe_identical_series(frames)
    check("alias_removed_ticker_kept", "COST" in kept and "PERMNO87055" not in kept, f"{sorted(kept)}")
    check("shorter_copy_removed_longer_kept", "UAA" in kept and "UA" not in kept, f"{sorted(kept)}")
    check("near_identical_not_merged", "NEAR" in kept)
    check("unrelated_untouched", "GVKEY000001_01W" in kept)
    check("removals_reported", removed == {"PERMNO87055": "COST", "UA": "UAA"}, f"{removed}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
