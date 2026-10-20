"""
D12 redesign (Ross 2026-10-19, "y"): the cluster randomization-inference CI (2026-10-19 morning) assumed crisis
episodes and calm years are exchangeable, but the calm confirmation rate falls over time (0.46% in 2009 -> 0.02% in
2022+, consistent with right-censoring: recent discoveries have had less time to reappear) and crisis episodes sit in
high-rate years -- under an era-matched null with NO crisis effect that CI covered 0 in 31% of worlds (adversarial
review). New design: compare crisis-first and calm-first discoveries WITHIN the same calendar year (removes the era
trend), d_y = crisis rate - calm rate in year y; statistic = mean of d_y over years with both kinds; sign-flip
randomization across years; reported as a CI by inverting the sign-flip test (no p-value).
Checks:
  1. era-trend world, no crisis effect (crisis episodes in high-rate years): within-year CI covers 0 in >= 90% of 100
     worlds, while the old cluster-RI CI does not (covers 0 in < 70%) -- the failure the review found;
  2. a real within-year crisis effect: the CI excludes 0 and covers the true difference;
  3. years with only one kind of discovery do not enter; their count is reported.
Run: python debug/_verify_crisis_regime_within_year_d12.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "research"))

import numpy as np
import pandas as pd

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def era_world(rng, effect=0.0):
    """Calm rate falls 0.5% -> 0.02% over 1995-2024; crisis-first pairs only in early (high-rate) years
    (higher-rate years); within each year crisis rate = that year's calm rate + effect."""
    years = np.arange(1995, 2025)
    base = np.linspace(0.005, 0.0002, len(years))
    crisis_years = {1997, 1998, 2000, 2001, 2002, 2003}   # early = high-rate years, as crisis episodes sit in the real data
    rows = []
    for y, p in zip(years, base):
        n_calm = int(rng.integers(3000, 12000))
        rows.append(pd.DataFrame({"year": y, "crisis": False, "confirmed": rng.random(n_calm) < p}))
        if y in crisis_years:
            n_c = int(rng.integers(300, 3000))
            rows.append(pd.DataFrame({"year": y, "crisis": True, "confirmed": rng.random(n_c) < p + effect}))
    return pd.concat(rows, ignore_index=True)


def main():
    try:
        import crisis_regime_cluster_bootstrap_test as mod
        cov_new = cov_old = 0
        for s in range(100):
            df = era_world(np.random.default_rng(500 + s))
            r = mod.within_year_ci(df, n_sim=2000, rng=np.random.default_rng(s))
            cov_new += r["ci_low"] <= 0 <= r["ci_high"]
            g = df.assign(cluster=np.where(df["crisis"], "c" + df["year"].astype(str), "m" + df["year"].astype(str)))
            g = g.groupby("cluster").agg(n=("confirmed", "size"), k=("confirmed", "sum"), crisis=("crisis", "first"))
            o = mod.ri_ci(g["n"].to_numpy(float), g["k"].to_numpy(float), g["crisis"].to_numpy(bool), n_sim=500,
                          rng=np.random.default_rng(s))
            cov_old += o["ci_low"] <= 0 <= o["ci_high"]
        check("era_null_within_year_covers_zero", cov_new >= 90, f"{cov_new}/100")
        check("era_null_old_cluster_ri_fails", cov_old < 70, f"{cov_old}/100 (the defect the review found)")

        df = era_world(np.random.default_rng(9), effect=0.004)
        r = mod.within_year_ci(df, n_sim=4000, rng=np.random.default_rng(1))
        check("effect_excludes_zero_covers_truth", r["ci_low"] > 0 and r["ci_low"] <= 0.004 <= r["ci_high"],
              f"[{r['ci_low']:.5f}, {r['ci_high']:.5f}] true 0.004")
        check("years_with_both_kinds_counted", r["n_years"] == 6 and r["n_years_one_kind_only"] == 24,
              f"{r['n_years']} used, {r['n_years_one_kind_only']} one-kind-only")
    except (AttributeError, TypeError) as e:
        check("within_year_ci_exists", False, f"{type(e).__name__}: {e}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
