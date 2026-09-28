"""
Synthetic check for research/clean_pool_identity_pairs.identity_share: an alias (identical returns) with a SHORTER
history -- the case universe_loader.dedupe_identical_series cannot see (its buckets use the last 60 dates) -- is
flagged; an unrelated series and a near-copy with noise are not. Also: universe_loader.dedupe_identical_series now
catches that alias too (it bucketed only by the LAST 60 dates, so an alias ending earlier was never compared).
Run: python debug/_verify_clean_pool_identity_pairs.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

import numpy as np
import pandas as pd

from clean_pool_identity_pairs import identity_share
from universe_loader import dedupe_identical_series

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    idx = pd.bdate_range("2015-01-01", periods=1500)
    r = pd.Series(np.random.default_rng(0).normal(0, 0.01, len(idx)), index=idx)
    alias = r.iloc[:1000]                                   # same security, history ends earlier
    other = pd.Series(np.random.default_rng(1).normal(0, 0.01, len(idx)), index=idx)
    near = r + np.random.default_rng(2).normal(0, 1e-4, len(idx))
    s, n = identity_share(r, alias)
    check("shorter_alias_flagged", s >= 0.99 and n == 1000, f"share={s} n={n}")
    check("unrelated_not_flagged", identity_share(r, other)[0] < 0.01)
    check("near_copy_not_flagged", identity_share(r, near)[0] < 0.99)
    to_px = lambda x: pd.DataFrame({"close": 100 * np.exp(x.cumsum())})
    _, removed = dedupe_identical_series({"TICK": to_px(r), "PERMNO1": to_px(alias)})
    check("loader_dedupe_catches_shorter_alias", removed.get("PERMNO1") == "TICK",
          f"loader dedupe removed={removed} (was missed when buckets used only the last 60 dates)")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
