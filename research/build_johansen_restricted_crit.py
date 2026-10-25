"""
research/build_johansen_restricted_crit.py -- the committed critical-value table for production's restricted-constant
Johansen trace test (johansen.py): for each number of common trends m (1..M_MAX) and series length T on
johansen.JOHANSEN_T_GRID, the (1 - level) quantiles of the rank-0 restricted-constant trace statistic on m independent
driftless random walks, JOHANSEN_CRIT_REPS seeded draws per (T, m), levels 0.10 / 0.05 / 0.01 from the same draws.
Derived, not copied from a published table; deterministic (seed 20261021 + m, as johansen_crit_n).
2026-10-25: the max-eigenvalue statistic's quantiles from the same draws go to research/johansen_restricted_maxeig_crit.csv
(for m = 1 the two statistics coincide); the trace table is reproduced unchanged.
Output: research/johansen_restricted_crit.csv and _maxeig_crit.csv (T, m, level, crit, reps, k_ar_diff).
Usage: python research/build_johansen_restricted_crit.py
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import Config  # noqa: E402
from johansen import CRIT_TABLE, JOHANSEN_CRIT_REPS, JOHANSEN_T_GRID, MAXEIG_TABLE, johansen_eigs_n  # noqa: E402

M_MAX = 3            # production tests trios: n = 3 series -> m = 3, 2, 1 trends
LEVELS = (0.10, 0.05, 0.01)


def main():
    k = Config.ANALYSIS.JOHANSEN_K_AR_DIFF
    rows = {"trace": [], "maxeig": []}
    for m in range(1, M_MAX + 1):
        for T in JOHANSEN_T_GRID:
            rng = np.random.default_rng(20261021 + m)      # same seed rule as johansen.johansen_crit_n
            st = {"trace": [], "maxeig": []}
            for _ in range(JOHANSEN_CRIT_REPS):
                lam, TT = johansen_eigs_n(np.cumsum(rng.normal(size=(T, m)), axis=0), k)
                st["trace"].append(-TT * np.cumsum(np.log(1 - lam)[::-1])[::-1][0])   # johansen_trace_n(..)[0] exactly
                st["maxeig"].append(-TT * np.log(1 - lam[0]))       # = johansen_maxeig_n(..)[0]
            for name, v in st.items():
                for lev in LEVELS:
                    rows[name].append({"T": T, "m": m, "level": lev, "crit": float(np.quantile(v, 1 - lev)),
                                       "reps": JOHANSEN_CRIT_REPS, "k_ar_diff": k})
            print(f"m={m} T={T}: crit 5% trace {np.quantile(st['trace'], 0.95):.3f} "
                  f"max-eig {np.quantile(st['maxeig'], 0.95):.3f}", flush=True)
    for name, path in (("trace", CRIT_TABLE), ("maxeig", MAXEIG_TABLE)):
        pd.DataFrame(rows[name]).to_csv(path, index=False)
        print(f"-> {path} ({len(rows[name])} rows)")


if __name__ == "__main__":
    main()
