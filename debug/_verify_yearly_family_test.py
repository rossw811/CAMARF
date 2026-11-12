"""
Synthetic ground truth for research/yearly_family_test.py (P2 feasibility engine).
  1. bh_reject matches statsmodels multipletests('fdr_bh') on random p-values, NaN never rejected
  2. power: 10 episodic pairs (AR(1) half-life 5, spread s.d. 0.05, 3-year episode, random walk outside) in a family of
     100. Expected power is DERIVED, not guessed: one year of EG on phi = 0.87, T = 252 gives ADF ~ (phi - 1) /
     sqrt((1 - phi^2) / T) ~ -4.2, typical p ~ 5e-3; with ~3 true episodes among 100 tests a year the BH cutoff is
     ~0.05 * 3 / 100 ~ 1.5e-3 -> power ~0.3-0.5. ASSERTED with legs at 3% daily vol (hedge identifiable): inside in
     [0.25, 0.7], outside <= 0.05. REPORTED (not asserted) with calm 1.5% legs, where errors-in-variables attenuates the
     hedge as well (A moves about as much within a year as the spread).
     History: first draft asserted > 0.6 (a guess) and got 0.13 on calm legs, then 0.43 on 3% legs; raw in-episode
     p-values (both regression directions alike, 1e-4 .. 1e-2) confirmed the derivation (Development.md 2026-11-11).
  3. false admissions: 90 null pairs over 8 years -- share of null (pair, year) rejections <= 0.05 (BH controls the
     FDR; with few true discoveries per year the per-test rate should be small)
  4. point-in-time: changing year y+1 prices leaves year y's pvalues and admissions unchanged; admitted_for = y + 1
  5. small family beats the discovery-sized cutoff: the same episodic pairs tested against a family of 1,000,000 (BH
     cutoff ~ alpha / m with ~no other rejections) reject in far fewer episode years (< 0.2)
Run: python debug/_verify_yearly_family_test.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
import pandas as pd

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    from statsmodels.stats.multitest import multipletests
    from research.yearly_family_test import bh_reject, yearly_family_tests
    rng = np.random.default_rng(20261111)
    p = rng.uniform(0, 0.1, 200) ** 2
    p[::17] = np.nan
    ok = np.isfinite(p)
    ref = np.zeros(len(p), bool)
    ref[ok] = multipletests(p[ok], 0.05, "fdr_bh")[0]
    check("1 BH matches statsmodels", np.array_equal(bh_reject(p, 0.05), ref), f"rejections={ref.sum()}")

    cal = pd.bdate_range("2010-01-01", "2017-12-31")

    def universe(leg_vol, seed):
        g = np.random.default_rng(seed)
        n, phi = len(cal), 0.5 ** (1 / 5)
        lp, family, episode = {}, [], {}
        for i in range(10):
            A = np.cumsum(g.normal(0, leg_vol, n))
            y0 = 2011 + i % 4
            ins = (cal.year >= y0) & (cal.year < y0 + 3)
            u, c = np.zeros(n), 0.0
            for t in range(1, n):
                if ins[t] and not ins[t - 1]:
                    c = u[t - 1]
                e = g.normal(0, 0.05 * np.sqrt(1 - phi ** 2))
                u[t] = c + phi * (u[t - 1] - c) + e if ins[t] else u[t - 1] + e
            lp[f"A{i}"], lp[f"B{i}"] = pd.Series(A, cal), pd.Series(A + u, cal)
            family.append((f"A{i}", f"B{i}"))
            episode[(f"A{i}", f"B{i}")] = set(range(y0, y0 + 3))
        for i in range(90):
            lp[f"X{i}"] = pd.Series(np.cumsum(g.normal(0, leg_vol, n)), cal)
            lp[f"Y{i}"] = pd.Series(np.cumsum(g.normal(0, leg_vol, n)), cal)
            family.append((f"X{i}", f"Y{i}"))
        R = yearly_family_tests(lp, family)
        R["true"] = [r.year in episode.get((r.symbol_a, r.symbol_b), set()) for r in R.itertuples()]
        return lp, family, R

    lp, family, R = universe(0.03, 1)
    planted = R["symbol_a"].str.startswith("A")
    pw_in = R.loc[planted & R["true"], "rejected"].mean()
    pw_out = R.loc[planted & ~R["true"], "rejected"].mean()
    _, _, Rc = universe(0.015, 2)
    pc = Rc["symbol_a"].str.startswith("A")
    check("2 episode years found (identifiable hedge)", 0.25 <= pw_in <= 0.7 and pw_out <= 0.05,
          f"legs 3%: power inside={pw_in:.2f} outside={pw_out:.2f} | REPORTED legs 1.5%: inside="
          f"{Rc.loc[pc & Rc['true'], 'rejected'].mean():.2f} outside={Rc.loc[pc & ~Rc['true'], 'rejected'].mean():.2f}")
    fa = pd.concat([R.loc[~planted, "rejected"], Rc.loc[~pc, "rejected"]]).mean()
    check("3 null admissions rare", fa <= 0.05, f"null (pair, year) rejection share={fa:.4f} over {int((~planted).sum() + (~pc).sum())}")

    lp2 = {k: v.copy() for k, v in lp.items()}
    for k in lp2:
        lp2[k][lp2[k].index.year == 2015] += rng.normal(0, 0.3, (lp2[k].index.year == 2015).sum())
    R2 = yearly_family_tests(lp2, family)
    a, b = R[R["year"] <= 2014].reset_index(drop=True), R2[R2["year"] <= 2014].reset_index(drop=True)
    check("4 point-in-time", a[["pvalue", "rejected", "admitted_for"]].equals(b[["pvalue", "rejected", "admitted_for"]])
          and (R.loc[R["rejected"], "admitted_for"] == R.loc[R["rejected"], "year"] + 1).all())

    big = R[planted & R["true"]]
    cut = 0.05 / 1_000_000
    check("5 discovery-sized family loses the episodes", (big["pvalue"] <= cut).mean() < 0.2,
          f"episode years passing alpha/1e6: {(big['pvalue'] <= cut).mean():.2f} vs family of 100: {pw_in:.2f}")

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
