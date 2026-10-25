"""
research/build_johansen_restricted_crit.py -- the committed critical-value table for production's restricted-constant
Johansen trace test (johansen.py): for each number of common trends m (1..M_MAX) and series length T on
johansen.JOHANSEN_T_GRID, the (1 - level) quantiles of the rank-0 restricted-constant trace statistic on m independent
driftless random walks, JOHANSEN_CRIT_REPS seeded draws per (T, m), levels 0.10 / 0.05 / 0.01 from the same draws.
Derived, not copied from a published table; deterministic (seed 20261021 + m, as johansen_crit_n).
Output: research/johansen_restricted_crit.csv (T, m, level, crit, reps, k_ar_diff).
Usage: python research/build_johansen_restricted_crit.py
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import Config  # noqa: E402
from johansen import CRIT_TABLE, JOHANSEN_CRIT_REPS, JOHANSEN_T_GRID, johansen_trace_n  # noqa: E402

M_MAX = 3            # production tests trios: n = 3 series -> m = 3, 2, 1 trends
LEVELS = (0.10, 0.05, 0.01)


def main():
    k = Config.ANALYSIS.JOHANSEN_K_AR_DIFF
    rows = []
    for m in range(1, M_MAX + 1):
        for T in JOHANSEN_T_GRID:
            rng = np.random.default_rng(20261021 + m)      # same seed rule as johansen.johansen_crit_n
            st = np.array([johansen_trace_n(np.cumsum(rng.normal(size=(T, m)), axis=0), k)[0]
                           for _ in range(JOHANSEN_CRIT_REPS)])
            for lev in LEVELS:
                rows.append({"T": T, "m": m, "level": lev, "crit": float(np.quantile(st, 1 - lev)),
                             "reps": JOHANSEN_CRIT_REPS, "k_ar_diff": k})
            print(f"m={m} T={T}: crit 5% {np.quantile(st, 0.95):.3f}", flush=True)
    pd.DataFrame(rows).to_csv(CRIT_TABLE, index=False)
    print(f"-> {CRIT_TABLE} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
