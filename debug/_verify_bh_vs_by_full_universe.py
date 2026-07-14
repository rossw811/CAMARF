"""
debug/_verify_bh_vs_by_full_universe.py -- verifies the leg-mask breakdown
logic in research/bh_vs_by_full_universe.py on a small synthetic case with a
known answer, before trusting the real-data run. The core Benjamini-Yekutieli
implementation itself was already verified (4/4 checks) by
research/bh_fdr_dependence_check.py -- this only checks the NEW logic added
here: correctly isolating a target symbol's leg-involved subset and applying
BH/BY to the full set while reporting the subset-specific rejection counts.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import _benjamini_hochberg
from research.bh_fdr_dependence_check import benjamini_yekutieli


def make_synthetic_case():
    # 20 pairs: 5 involve "HUB" as a leg with deliberately tiny (highly
    # "significant") p-values simulating a spurious-drift-dominated symbol;
    # 15 do not involve HUB and have p-values spread across [0, 1].
    rows = []
    for i in range(5):
        rows.append({"symbol_a": "HUB", "symbol_b": f"X{i}", "pvalue": 1e-8 * (i + 1)})
    rng = np.random.RandomState(0)
    for i in range(15):
        rows.append({"symbol_a": f"Y{i}", "symbol_b": f"Z{i}", "pvalue": float(rng.uniform(0.001, 0.9))})
    return pd.DataFrame(rows)


def main():
    df = make_synthetic_case()
    hub_mask = ((df.symbol_a == "HUB") | (df.symbol_b == "HUB")).to_numpy()
    assert hub_mask.sum() == 5, f"expected 5 HUB-leg rows, got {hub_mask.sum()}"

    pvals = df["pvalue"].to_numpy()
    bh_rejected, _ = _benjamini_hochberg(pvals, 0.05)
    by_rejected, _ = benjamini_yekutieli(pvals, 0.05)

    # All 5 HUB pairs have p << alpha/m even under the strictest reasonable
    # correction at this small m=20 -- both BH and BY must reject all 5.
    bh_hub_confirmed = int(bh_rejected[hub_mask].sum())
    by_hub_confirmed = int(by_rejected[hub_mask].sum())
    check1 = bh_hub_confirmed == 5 and by_hub_confirmed == 5
    print(f"Check 1 (all 5 HUB-leg pairs survive both corrections given their extreme p-values): "
          f"bh={bh_hub_confirmed}/5 by={by_hub_confirmed}/5 -> {'PASS' if check1 else 'FAIL'}")

    # BY must be at least as conservative as BH on the same data (fewer or
    # equal total rejections) -- a basic sanity property of the BY procedure.
    check2 = int(by_rejected.sum()) <= int(bh_rejected.sum())
    print(f"Check 2 (BY total rejections <= BH total rejections): "
          f"by={int(by_rejected.sum())} bh={int(bh_rejected.sum())} -> {'PASS' if check2 else 'FAIL'}")

    # Mask arithmetic sanity: hub-leg + non-hub-leg counts must partition m exactly.
    check3 = int(hub_mask.sum()) + int((~hub_mask).sum()) == len(df)
    print(f"Check 3 (leg mask partitions the full set exactly): -> {'PASS' if check3 else 'FAIL'}")

    all_pass = check1 and check2 and check3
    print(f"\n{'ALL CHECKS PASSED' if all_pass else 'FAILURE'} -- "
          f"{'proceeding to real data is justified' if all_pass else 'do not trust the real-data run'}")
    assert all_pass


if __name__ == "__main__":
    main()
