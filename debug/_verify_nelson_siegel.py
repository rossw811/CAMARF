"""
Synthetic ground truth for research/nelson_siegel.py.
  1. loadings: slope loading -> 1 at tau -> 0 and -> 0 at long tau; curvature loading peaks near 30 months at lam=0.0609
  2. exact curve from known betas -> betas recovered to 1e-10, rmse ~ 0
  3. noisy curve (5 bp noise) -> betas within tolerance; rmse ~ noise level
  4. missing maturities handled per row; < 4 maturities -> NaN factors
  5. point-in-time: changing other dates' yields leaves a date's factors unchanged
Run: python debug/_verify_nelson_siegel.py
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
    from research.nelson_siegel import FRED_TREASURY_MONTHS, fit_ns, ns_loadings
    tau = np.array(list(FRED_TREASURY_MONTHS.values()), float)
    cols = list(FRED_TREASURY_MONTHS)
    fine = np.linspace(0.01, 400, 40001)
    L = ns_loadings(fine)
    peak = fine[np.argmax(L[:, 2])]
    check("1 loadings shape", abs(L[0, 1] - 1) < 1e-3 and L[-1, 1] < 0.05 and 25 < peak < 35, f"curv peak={peak:.1f}m")

    rng = np.random.default_rng(7)
    B = np.column_stack([rng.uniform(2, 6, 50), rng.uniform(-3, 1, 50), rng.uniform(-2, 2, 50)])
    idx = pd.bdate_range("2020-01-01", periods=50)
    Y = pd.DataFrame(B @ ns_loadings(tau).T, index=idx, columns=cols)
    f = fit_ns(Y, tau)
    check("2 exact recovery", np.abs(f[["level", "slope", "curvature"]].to_numpy() - B).max() < 1e-10
          and f["rmse"].max() < 1e-10)

    Yn = Y + rng.normal(0, 0.05, Y.shape)
    fn = fit_ns(Yn, tau)
    err = np.abs(fn[["level", "slope", "curvature"]].to_numpy() - B).max(axis=0)
    check("3 noisy recovery", err[0] < 0.15 and err[1] < 0.25 and err[2] < 0.4 and abs(fn["rmse"].mean() - 0.05) < 0.02,
          f"max abs err level/slope/curv={np.round(err, 3)} mean rmse={fn['rmse'].mean():.3f}")

    Ym = Y.copy()
    Ym.iloc[0, [0, 3, 7]] = np.nan                        # 8 maturities left
    Ym.iloc[1, 4:] = np.nan                               # 4 left
    Ym.iloc[2, 3:] = np.nan                               # 3 left -> NaN
    fm = fit_ns(Ym, tau)
    check("4 missing maturities", np.abs(fm.iloc[:2, :3].to_numpy() - B[:2]).max() < 1e-9
          and fm.iloc[2, :3].isna().all() and fm["n_maturities"].iloc[:3].tolist() == [8, 4, 3])

    Yp = Y.copy()
    Yp.iloc[25:] += 3.0
    check("5 point-in-time", fit_ns(Yp, tau).iloc[:25].equals(f.iloc[:25]))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
