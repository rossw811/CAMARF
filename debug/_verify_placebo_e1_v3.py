"""
E1 v3 placebo (research/placebo_discovery_e1.py, proposal P1, Ross 2026-11-11 "yes to all").
  1. volatility path kept: 20 GARCH(1,1)-t(5) series (persistence 0.98) with a 60-bar crisis (variance x9, volatility
     x3) inside one year. Placebo volatility in the crisis / the rest of that year, mean over series: v2 spreads the
     crisis over its year (expected ~1; threshold < 1.5 -- the old method fails), v3 keeps it (the causal EWMA captures
     ~0.83 of a crisis jump on such data, so ~2.5 expected; threshold > 2.0).
     First draft used one step-shaped crisis (x4) with lambda fixed at 0.94 and required > 3: v3 1.90, and even the
     TRUE volatility gave only 3.12 there. Estimator comparison on GARCH-t data (Development.md 2026-11-11): causal
     EWMA (fitted lambda) log-sigma RMSE 0.155 vs two-sided EWMA 0.200 and centered 11/21/41-bar windows
     0.333/0.256/0.224 (centered windows leave clustering in the standardized returns), so the module keeps it.
  2. long-run relations still broken: 20 cointegrated pairs (half-life 10, real Engle-Granger p < 1e-4 for all) put
     through the v3 placebo on a shared path: at most 4 of 20 reject at 0.05
  3. ewma_sigma is causal: changing returns from bar t on leaves sigma[: t + 1] unchanged; choose_ewma_lambda recovers
     the decay of a simulated EWMA-variance process (0.94 -> within [0.90, 0.97])
  4. episodic plant: inside the episode the spread's AR(1) half-life is near target (within x0.5..x2); outside it the
     spread is a random walk (ADF p > 0.05 on the pre-episode part); dates reported match the episode
  5. plant_grid: v2 unchanged (128 rows, same labels); v3 adds 48 episodic rows, persistent labels identical
  6. v2 default untouched: placebo_series without vol_lambda gives the same output as before (same as vol_lambda=None)
Run: python debug/_verify_placebo_e1_v3.py
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
    from statsmodels.tsa.stattools import adfuller, coint
    from research import placebo_discovery_e1 as E
    rng = np.random.default_rng(20261111)
    cal = pd.bdate_range("2010-01-01", "2014-12-31")
    paths = E.year_index_paths(cal, 3.5, seed=7)

    # 1 crisis volatility: GARCH(1,1)-t(5) returns (persistence 0.98), variance x9 for 60 bars inside one year
    gcal = pd.bdate_range("2010-01-01", periods=2520)
    gpaths = E.year_index_paths(gcal, 3.5, seed=7)
    y0 = gcal[1200].year
    yr = gcal.year == y0
    cmask = np.zeros(len(gcal), bool)
    cmask[1200:1260] = True
    assert (gcal[cmask].year == y0).all()
    ratios = {"v2": [], "v3": []}
    for rep in range(20):
        g = np.random.default_rng(100 + rep)
        w, a, b = 2e-6, 0.08, 0.90
        v, r = w / (1 - a - b), np.empty(len(gcal))
        for t in range(len(gcal)):
            boost = 9.0 if cmask[t] else 1.0
            r[t] = np.sqrt(v * boost) * g.standard_t(5) / np.sqrt(5 / 3)
            v = w + a * r[t] ** 2 / boost + b * v
        lp = pd.Series(np.cumsum(r), index=gcal)
        lam = E.choose_ewma_lambda({0: np.diff(lp.to_numpy())})
        for name, l in (("v2", None), ("v3", lam)):
            pr = E.placebo_series(lp, gcal, gpaths, vol_lambda=l).diff().to_numpy()
            ratios[name].append(np.nanstd(pr[cmask]) / np.nanstd(pr[yr & ~cmask]))
    m2, m3 = np.mean(ratios["v2"]), np.mean(ratios["v3"])
    check("1 crisis volatility kept in place", m2 < 1.5 and m3 > 2.0,
          f"mean crisis/calm vol ratio over 20 series: v2={m2:.2f} v3={m3:.2f} (real 3)")
    sd = np.full(len(cal), 0.01)
    lp = pd.Series(np.cumsum(rng.normal(0, 1, len(cal)) * sd), index=cal)

    # 2 cointegration broken
    rej, real_p = 0, []
    for i in range(20):
        A = pd.Series(np.cumsum(rng.normal(0, 0.01, len(cal)) * np.where(np.arange(len(cal)) % 500 < 60, 3, 1)),
                      index=cal)
        phi = 0.5 ** (1 / 10)
        u = np.zeros(len(cal))
        for t in range(1, len(cal)):
            u[t] = phi * u[t - 1] + rng.normal(0, 0.01)
        B = A + u
        real_p.append(coint(A, B)[1])
        pa = E.placebo_series(A, cal, paths, vol_lambda=0.94)
        pb = E.placebo_series(B, cal, paths, vol_lambda=0.94)
        rej += coint(pa, pb)[1] < 0.05
    check("2 cointegration broken by v3", max(real_p) < 1e-4 and rej <= 4,
          f"real max p={max(real_p):.1e}; placebo rejections at 0.05: {rej}/20")

    # 3 causal sigma + lambda recovery
    x = rng.normal(0, 0.01, 800)
    s1 = E.ewma_sigma(x, 0.94)
    x2 = x.copy()
    x2[400:] *= 10
    causal = np.array_equal(s1[:401], E.ewma_sigma(x2, 0.94)[:401])
    lams = []
    for _ in range(15):
        v, r = 1e-4, np.empty(2000)
        for t in range(2000):
            r[t] = np.sqrt(v) * rng.standard_normal()
            v = 0.94 * v + 0.06 * r[t] ** 2
        lams.append(r)
    lam_hat = E.choose_ewma_lambda({i: r for i, r in enumerate(lams)})
    check("3 sigma causal; lambda recovered", causal and 0.90 <= lam_hat <= 0.97, f"lambda_hat={lam_hat}")

    # 4 episodic plant
    A = pd.Series(np.cumsum(rng.normal(0, 0.01, 2520)), index=pd.bdate_range("2000-01-03", periods=2520))
    B, info = E.plant_pair_episodic(A, 5, np.random.default_rng(3), sd=0.10, episode_years=3)
    u = (B - info["mu"] - info["beta"] * A)
    ins = u[info["episode_start"]: info["episode_end"]].to_numpy()
    from analysis import SpreadModel
    hl_in = SpreadModel.half_life_ar1(ins)
    pre = u[: info["episode_start"]].to_numpy()[:-1]
    adf_pre = adfuller(pre)[1] if len(pre) > 100 else np.nan
    n_in = len(ins)
    check("4 episodic plant", 2.5 <= hl_in <= 10 and (np.isnan(adf_pre) or adf_pre > 0.05) and abs(n_in - 756) <= 1,
          f"inside hl={hl_in:.2f} (target 5), pre-episode ADF p={adf_pre:.3f} (n={len(pre)}), episode bars={n_in}")

    # 5 grid
    g2, g3 = E.plant_grid(), E.plant_grid(episodic=True)
    per = g3[g3["episode_years"].isna()].reset_index(drop=True)
    check("5 plant grid", len(g2) == 128 and len(g3) == 176 and per[["plant", "arm", "half_life", "spread_sd"]]
          .equals(g2[["plant", "arm", "half_life", "spread_sd"]]), f"v2 {len(g2)} v3 {len(g3)}")

    # 6 v2 default untouched
    check("6 v2 default = vol_lambda None", E.placebo_series(lp, cal, paths).equals(E.placebo_series(lp, cal, paths,
                                                                                                      vol_lambda=None)))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
