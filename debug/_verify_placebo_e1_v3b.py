"""
Synthetic checks for the E1 v3b placebo (research/placebo_discovery_e1.py: market_vol_state, vol_matched_paths).
DGP: N series, a persistent two-regime market (Markov); calm days sd 1%, factor share 0.10; stress days sd 3%, factor
share 0.60 -- correlation rises with volatility, as in real data (v3's seed-1 guard stop, 2026-11-12).
  1. v3 reproduces the flaw: placebo mean correlation clearly below the real one (> 3 SE across seeds)
  2. v3b keeps the correlation level: |placebo - real| / real <= 10% at the chosen VOL_BINS; the grid is reported
     and VOL_BINS must be the smallest grid value that passes
  3. structure: every source day is in the target's year and the target's volatility bin
  4. own volatility path kept as well as v3 (paired over series and seeds, corr of 21-day rolling sd real vs placebo):
     v3b - v3 > -3 SE and v3b - v2 > 3 SE. (A fixed 0.8 bar, first draft, was a guess: v3 itself has median 0.778.)
  5. long-run relations broken: a planted cointegrated pair (5-day half-life) is EG-confirmed in real data and not in
     the v3b placebo (median p over seeds > 0.10)
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import placebo_discovery_e1 as m  # noqa: E402
from statsmodels.tsa.stattools import coint  # noqa: E402

N, YEARS, BLOCK = 30, 6, 3.5
cal = pd.bdate_range("2010-01-01", periods=261 * YEARS)


def dgp(seed):
    rng = np.random.default_rng(seed)
    n = len(cal)
    reg = np.zeros(n, int)
    for t in range(1, n):
        stay = 0.985 if reg[t - 1] == 0 else 0.95
        reg[t] = reg[t - 1] if rng.random() < stay else 1 - reg[t - 1]
    sd = np.where(reg == 1, 0.03, 0.01)
    share = np.where(reg == 1, 0.60, 0.10)
    f = rng.normal(size=n)
    R = {f"S{i}": sd * (np.sqrt(share) * f + np.sqrt(1 - share) * rng.normal(size=n)) for i in range(N)}
    # planted cointegrated pair: P1 = S0 + AR(1) spread, 5-day half-life
    phi, e = 0.5 ** (1 / 5), np.zeros(n)
    for t in range(1, n):
        e[t] = phi * e[t - 1] + rng.normal(0, 0.01)
    lp = {k: pd.Series(np.cumsum(v), cal) for k, v in R.items()}
    lp["P1"] = lp["S0"] + pd.Series(e, cal)
    return lp, reg


def mean_corr(lp, names):
    C = pd.DataFrame({k: lp[k].diff() for k in names}).corr().to_numpy()
    return float(np.nanmean(C[np.triu_indices(len(names), 1)]))


def placebo(lp, paths, lam):
    sp = m.source_positions(cal, paths)
    return {k: m.placebo_series(v, cal, paths, src_pos=sp, vol_lambda=lam) for k, v in lp.items()}


names = [f"S{i}" for i in range(N)]
SEEDS = range(6)
res = {"real": [], "v3": [], **{f"v3b_{b}": [] for b in m.VOL_BINS_GRID}}
volcorr, vc3, vc2, p_real, p_pl, struct_ok = [], [], [], [], [], True
for s in SEEDS:
    lp, reg = dgp(s)
    rets = pd.DataFrame({k: lp[k].diff() for k in names})
    lam = m.choose_ewma_lambda({c: rets[c] for c in rets.columns})
    res["real"].append(mean_corr(lp, names))
    ypaths = m.year_index_paths(cal, BLOCK, seed=s)
    pl3, pl2 = placebo(lp, ypaths, lam), placebo(lp, ypaths, None)
    res["v3"].append(mean_corr(pl3, names))
    state = m.market_vol_state(rets, lam)
    for b in m.VOL_BINS_GRID:
        paths = m.vol_matched_paths(cal, state, BLOCK, n_bins=b, seed=s)
        pl = placebo(lp, paths, lam)
        res[f"v3b_{b}"].append(mean_corr(pl, names))
        if b == m.VOL_BINS:
            # 3. structure: same year, same bin
            st = state.reindex(cal).to_numpy()
            years = cal.year.to_numpy()
            for y, path in paths.items():
                pos = np.flatnonzero(years == y)
                rank = np.empty(len(pos), int)
                rank[np.argsort(st[pos], kind="stable")] = np.arange(len(pos))
                bins = (rank * b) // len(pos)
                bin_of = dict(zip(pos, bins))
                struct_ok &= bool(np.all(years[path] == y)) and all(bin_of[src] == bins[i] for i, src in enumerate(path))
            # 4. own vol path
            for k in names:
                a = lp[k].diff().rolling(21).std()
                volcorr.append(a.corr(pl[k].diff().rolling(21).std()))
                vc3.append(a.corr(pl3[k].diff().rolling(21).std()))
                vc2.append(a.corr(pl2[k].diff().rolling(21).std()))
            # 5. planted pair
            p_real.append(coint(lp["S0"], lp["P1"])[1])
            p_pl.append(coint(pl["S0"], pl["P1"])[1])

R = {k: np.array(v) for k, v in res.items()}
real = R["real"]
d3 = real - R["v3"]
check("1. v3 loses correlation (real - v3 > 3 SE over seeds)", d3.mean() > 3 * d3.std(ddof=1) / np.sqrt(len(d3)),
      f"real {real.mean():.3f} v3 {R['v3'].mean():.3f}")
rel = {b: abs(R[f"v3b_{b}"].mean() - real.mean()) / real.mean() for b in m.VOL_BINS_GRID}
grid_txt = ", ".join(f"{b} bins {R[f'v3b_{b}'].mean():.3f} ({rel[b]:.1%})" for b in m.VOL_BINS_GRID)
passing = [b for b in m.VOL_BINS_GRID if rel[b] <= 0.10]
check("2. v3b keeps the correlation level (within 10%) and VOL_BINS = smallest passing grid value",
      bool(passing) and m.VOL_BINS == min(passing), f"real {real.mean():.3f}; {grid_txt}; VOL_BINS={m.VOL_BINS}")
check("3. every source day in the target's year and volatility bin", struct_ok)
vb, v3a, v2a = map(np.array, (volcorr, vc3, vc2))
d_3, d_2 = vb - v3a, vb - v2a
se = lambda d: d.std(ddof=1) / np.sqrt(len(d))
check("4. own volatility path kept as well as v3 (paired: v3b-v3 > -3SE, v3b-v2 > 3SE)",
      d_3.mean() > -3 * se(d_3) and d_2.mean() > 3 * se(d_2),
      f"median v3b {np.median(vb):.3f} v3 {np.median(v3a):.3f} v2 {np.median(v2a):.3f}; "
      f"v3b-v3 {d_3.mean():+.3f} (SE {se(d_3):.3f})")
check("5. planted cointegration broken (real p < 0.01 every seed; placebo median p > 0.10)",
      max(p_real) < 0.01 and np.median(p_pl) > 0.10, f"real max {max(p_real):.1e}; placebo median {np.median(p_pl):.3f}")


# 6. v2b (vol-matched paths on RAW returns, the variant chosen on the real check): correlation within 10% of real,
#    volatility clustering (mean ACF of |r|, lags 1-20) above v2 by > 3 paired SE, planted cointegration broken.
def acf_abs(lp_):
    return np.mean([[lp_[k].diff().abs().autocorr(lag) for lag in range(1, 21)] for k in names], axis=1)


c2b, a2b, a2, p2b = [], [], [], []
for s_ in SEEDS:
    lp, _ = dgp(s_)
    rets = pd.DataFrame({k: lp[k].diff() for k in names})
    lam = m.choose_ewma_lambda({c: rets[c] for c in rets.columns})
    pb = placebo(lp, m.vol_matched_paths(cal, m.market_vol_state(rets, lam), BLOCK, n_bins=m.VOL_BINS, seed=s_), None)
    p2 = placebo(lp, m.year_index_paths(cal, BLOCK, seed=s_), None)
    c2b.append(mean_corr(pb, names))
    a2b += list(acf_abs(pb))
    a2 += list(acf_abs(p2))
    p2b.append(coint(pb["S0"], pb["P1"])[1])
da = np.array(a2b) - np.array(a2)
rel2b = abs(np.mean(c2b) - real.mean()) / real.mean()
check("6. v2b: corr within 10% of real, clustering > v2 by 3 paired SE, planted cointegration broken",
      rel2b <= 0.10 and da.mean() > 3 * da.std(ddof=1) / np.sqrt(len(da)) and np.median(p2b) > 0.10,
      f"corr {np.mean(c2b):.3f} vs real {real.mean():.3f} ({rel2b:.1%}); ACF|r| v2b {np.mean(a2b):.3f} "
      f"v2 {np.mean(a2):.3f}; placebo median p {np.median(p2b):.3f}")

# 7. v2c (top volatility bin without replacement): every top-bin day of each year is a source exactly once; the other
#    bins are untouched (same draws as v2b would not hold -- only structure is checked); correlation within 10% of
#    real; planted cointegration broken.
once_ok, c2c, p2c = True, [], []
for s_ in SEEDS:
    lp, _ = dgp(s_)
    rets = pd.DataFrame({k: lp[k].diff() for k in names})
    lam = m.choose_ewma_lambda({c: rets[c] for c in rets.columns})
    state = m.market_vol_state(rets, lam)
    paths = m.vol_matched_paths(cal, state, BLOCK, n_bins=m.VOL_BINS, seed=s_, stress_once=True)
    st, years = state.reindex(cal).to_numpy(), cal.year.to_numpy()
    for y, path in paths.items():
        pos = np.flatnonzero(years == y)
        rank = np.empty(len(pos), int)
        rank[np.argsort(st[pos], kind="stable")] = np.arange(len(pos))
        top = (rank * m.VOL_BINS) // len(pos) == m.VOL_BINS - 1
        once_ok &= sorted(path[top].tolist()) == sorted(pos[top].tolist())
    pc = placebo(lp, paths, None)
    c2c.append(mean_corr(pc, names))
    p2c.append(coint(pc["S0"], pc["P1"])[1])
rel2c = abs(np.mean(c2c) - real.mean()) / real.mean()
check("7. v2c: each top-bin day used exactly once; corr within 10% of real; planted cointegration broken",
      once_ok and rel2c <= 0.10 and np.median(p2c) > 0.10,
      f"once {once_ok}; corr {np.mean(c2c):.3f} vs real {real.mean():.3f} ({rel2c:.1%}); placebo median p {np.median(p2c):.3f}")

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
