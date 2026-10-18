"""
debug/_verify_crisis_regime_survivorship_confound_test.py -- synthetic checks
for research/crisis_regime_survivorship_confound_test.py (D5 / R3.10, Ross
2026-10-12: filter the test to crisis-first pairs), run BEFORE trusting it
against real crisis_regime_correlation_diagnostic_pairs.parquet data.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.crisis_regime_survivorship_confound_test import add_survival_columns

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


def _world(rng):
    """A survivorship effect ONLY among crisis-first pairs (both-survived pairs confirm at 6% vs 1%), none among the
    calm pairs, which outnumber them 20:1 -- the all-regime test is diluted, the crisis-first test is not."""
    rows = []
    for regime, n, p_surv, p_dead in (("crisis", 2000, 0.06, 0.01), ("calm", 40000, 0.01, 0.01)):
        surv = rng.random(n) < 0.5
        conf = rng.random(n) < np.where(surv, p_surv, p_dead)
        for i in range(n):
            a, b = f"{regime}_a{i}", f"{regime}_b{i}"
            rows.append((a, b, regime, bool(conf[i]), bool(surv[i])))
    df = pd.DataFrame(rows, columns=["symbol_a", "symbol_b", "first_regime", "confirmed", "surv"])
    permno = {s: k for k, s in enumerate(pd.unique(df[["symbol_a", "symbol_b"]].values.ravel()))}
    survival = {}
    for a, b, s in zip(df["symbol_a"], df["symbol_b"], df["surv"]):
        survival[permno[a]] = True
        survival[permno[b]] = bool(s)
    return df.drop(columns="surv"), permno, survival


try:
    from research.crisis_regime_survivorship_confound_test import survivorship_test

    df, permno, survival = _world(np.random.default_rng(7))
    joined = add_survival_columns(df, permno, survival)

    print("Check D5-1: the crisis-first test detects an effect the all-regime test dilutes away")
    r_all = survivorship_test(joined, regime=None)
    r_cri = survivorship_test(joined, regime="crisis")
    check(f"crisis-first n = 2000 [{r_cri['n_a'] + r_cri['n_b']}]", r_cri["n_a"] + r_cri["n_b"] == 2000)
    check(f"crisis-first test rejects (p {r_cri['p_value']:.2g} < 0.001)", r_cri["p_value"] < 0.001)
    check(f"all-regime test is weaker (p {r_all['p_value']:.2g} > crisis p)", r_all["p_value"] > r_cri["p_value"])
    check("rows carry their scope label", r_cri["scope"] == "crisis" and r_all["scope"] == "all_regimes")

    print("Check D5-2: untrackable pairs are excluded, not assumed survived")
    j2 = joined.copy()
    j2.loc[j2.index[:100], "both_trackable"] = False
    r2 = survivorship_test(j2, regime="crisis")
    check(f"100 untrackable crisis pairs dropped [{r2['n_a'] + r2['n_b']}]", r2["n_a"] + r2["n_b"] == 1900)

    print("Check D5-3: small counts -> exact test reported and flagged")
    small = pd.DataFrame({"first_regime": ["crisis"] * 400, "both_trackable": True,
                          "both_survived": [True] * 200 + [False] * 200,
                          "confirmed": [True] * 3 + [False] * 197 + [True] * 1 + [False] * 199})
    r3 = survivorship_test(small, regime="crisis")
    check("fisher_p present and in (0, 1]", 0 < r3["fisher_p"] <= 1)
    check(f"min expected cell {r3['min_expected']:.2f} < 5 -> small_count flag", r3["small_count"] is True)
    check(f"large world not flagged [{r_cri['min_expected']:.1f}]", r_cri["small_count"] is False)
except ImportError as e:
    check(f"D5 functions exist ({e})", False)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
