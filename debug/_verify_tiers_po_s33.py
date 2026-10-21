"""
S33 (plan 2026-10-07; Ross: fix, 2026-10-20). The Gold/Silver/Bronze tiers used a "Phillips-Ouliaris proxy" that was
PhillipsPerron on the estimated spread with univariate critical values (27.3% rejections at nominal 10% on independent
random walks) and KPSS on residuals with univariate critical values (needs Shin 1994). Fix: PO is
arch.unitroot.cointegration.phillips_ouliaris on the two legs' log prices (residual-based critical values); KPSS is
still reported but no longer enters the tier until a Shin (1994) version is verified. Tier = EG + PO: "gold" both,
"bronze" EG only ("silver" no longer produced).
Checks: (1) stats._run_coint_tests(log_a, log_b, spread, eg_pval) gives PO's p equal to phillips_ouliaris on the legs;
(2) size of the PO component at 10% on independent random walks <= 15% (old proxy 27%); (3) tier ignores KPSS;
(4) run_confirmatory_cointegration loads the legs.
"""
import inspect
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import stats  # noqa: E402
from arch.unitroot.cointegration import phillips_ouliaris  # noqa: E402

rng = np.random.default_rng(11)
x = np.cumsum(rng.normal(0, 0.01, 600)) + 3
y = 0.9 * x + 0.1 + rng.normal(0, 0.01, 600)
spread = pd.Series(y - 0.9 * x)
try:
    r = stats._run_coint_tests(y, x, spread, 0.001)
    ref = phillips_ouliaris(y, x, trend="c", test_type="Zt").pvalue
    check("1. PO p = phillips_ouliaris on the legs", np.isclose(r["po_pval"], ref), f"{r['po_pval']} vs {ref}")
    rej = 0
    for _ in range(200):
        a = np.cumsum(rng.normal(size=500)); b = np.cumsum(rng.normal(size=500))
        rr = stats._run_coint_tests(a, b, pd.Series(a - b), 1.0)
        rej += rr["po_pval"] < 0.10
    check("2. PO size at 10% on independent random walks <= 15%", rej / 200 <= 0.15, f"{rej / 200:.3f}")
    check("3a. EG + PO -> gold, n_confirm 2", r["stats_tier"] == "gold" and r["n_confirm"] == 2, f"{r['stats_tier']}")
    r_eg = stats._run_coint_tests(np.cumsum(rng.normal(size=500)), np.cumsum(rng.normal(size=500)),
                                  pd.Series(np.cumsum(rng.normal(size=500))), 0.001)
    check("3b. tier never 'silver'; KPSS not counted", r_eg["stats_tier"] in ("gold", "bronze")
          and r_eg["n_confirm"] <= 2, f"{r_eg['stats_tier']} {r_eg['n_confirm']}")
except TypeError as e:
    check("_run_coint_tests takes the legs", False, str(e))
check("4. run_confirmatory_cointegration loads the legs (WRDS-first loader)",
      "_load_leg_log_prices(" in inspect.getsource(stats.run_confirmatory_cointegration)
      and "load_aligned_pair(" in inspect.getsource(stats._load_leg_log_prices))
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
