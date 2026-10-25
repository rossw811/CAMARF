"""
E1 (Ross 2026-10-24: "build, yes to all"): end-to-end placebo discovery. A placebo universe keeps every series'
cross-sectional correlation and its own listing span, liquidity and holes, but no cointegration; planted pairs with
known half-lives measure the whole pipeline's power. Checks on research/placebo_discovery_e1.py:
  1. year_index_paths: one path per calendar year, values stay inside that year, deterministic per seed
  2. placebo_series: same dates as the source (within its own span; real holes kept), first log price equal, and the
     returns are the source's returns at the shared path's dates (so two symbols keep their contemporaneous correlation)
  3. cross-correlation kept, cointegration removed: a strongly cointegrated real pair is rejected by production EG on
     its real levels and not (p > 0.05) on its placebo levels; return correlation within 0.05
  4. plant_pair: B = mu + beta * A + AR(1) with the requested half-life (estimated within 30%), same dates as A, label is
     a GVKEY id no real file uses
  5. write_placebo_file keeps volume and writes every price column present
"""
import os
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


try:
    import research.placebo_discovery_e1 as e1  # noqa: E402
except ImportError as e:
    check("module exists", False, str(e))
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1)
from analysis import eg_pvalue_pair  # noqa: E402
from config import Config  # noqa: E402

cal = pd.bdate_range("2010-01-01", "2013-12-31")
paths = e1.year_index_paths(cal, 5.0, seed=3)
ok_years = all(pd.DatetimeIndex(cal[v]).year.unique().tolist() == [y] for y, v in paths.items())
check("1 one path per year, inside its year, deterministic",
      sorted(paths) == [2010, 2011, 2012, 2013] and ok_years
      and all(np.array_equal(paths[y], e1.year_index_paths(cal, 5.0, seed=3)[y]) for y in paths))

rng = np.random.default_rng(0)
T = len(cal)
w = np.cumsum(rng.normal(0, 0.01, T))
e = np.zeros(T)
for t in range(1, T):
    e[t] = 0.7 * e[t - 1] + rng.normal(0, 0.004)
la = pd.Series(w, index=cal)
lb = pd.Series(0.9 * w + 0.3 + e, index=cal)
lb.iloc[100:110] = np.nan                                  # a real hole
pa, pb = e1.placebo_series(la, cal, paths), e1.placebo_series(lb, cal, paths)
check("2 same dates (hole kept), first value equal",
      pa.index.equals(la.dropna().index) and pb.index.equals(lb.dropna().index) and np.isclose(pb.iloc[0], lb.dropna().iloc[0]))
p_real, _ = eg_pvalue_pair(la.to_numpy(), lb.reindex(cal).to_numpy(), Config.ANALYSIS.EG_MAX_LAG, "1D")
p_plac, _ = eg_pvalue_pair(pa.reindex(cal).to_numpy(), pb.reindex(cal).to_numpy(), Config.ANALYSIS.EG_MAX_LAG, "1D")
c_real = la.diff().corr(lb.diff())
c_plac = pa.reindex(cal).diff().corr(pb.reindex(cal).diff())
check("3 placebo keeps return correlation, removes cointegration",
      p_real < 0.01 and p_plac > 0.05 and abs(c_real - c_plac) < 0.05, f"p {p_real:.1e} -> {p_plac:.3f}; corr {c_real:.3f} -> {c_plac:.3f}")

A = pa
B, info = e1.plant_pair(A, 20.0, np.random.default_rng(1), sd=0.05)
x = (B - info["mu"] - info["beta"] * A).to_numpy()
phi = np.corrcoef(x[1:], x[:-1])[0, 1]
hl = np.log(0.5) / np.log(phi)
check("4 planted spread half-life ~ requested; same dates", B.index.equals(A.index) and 14 < hl < 26, f"hl {hl:.1f}")
lab = e1.plant_label(7)
check("4b plant label is a GVKEY id in the reserved 9xxxxx range", lab == "GVKEY900007_01W", lab)

with tempfile.TemporaryDirectory() as td:
    src = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "close_usd": 1.0, "volume": 5.0}, index=cal[:50])
    src.index.name = "datadate"
    out = os.path.join(td, "X_1D.parquet")
    e1.write_placebo_file(src, pd.Series(np.linspace(0, 0.1, 50), index=cal[:50]), out)
    d = pd.read_parquet(out)
    check("5 volume kept, every price column = exp(placebo log price)",
          (d["volume"] == 5.0).all() and np.allclose(d["close_usd"], np.exp(np.linspace(0, 0.1, 50)))
          and np.allclose(d["open"], d["close"]), str(list(d.columns)))

# 6. (CachyOS build 2026-10-24: mean block 68 days from the equal-weight index -- stale prices make the index
# autocorrelated -- long enough to keep a real pair's within-block error correction) block length = median of the
# per-series Politis-White estimates, as N14 uses per pair.
g6 = np.random.default_rng(6)
series = {f"S{i}": pd.Series(g6.normal(0, 0.01, 1500)) for i in range(40)}
L = e1.choose_block_length(series) if hasattr(e1, "choose_block_length") else float("nan")
stale = {f"T{i}": pd.Series(np.repeat(g6.normal(0, 0.01, 300), 5)) for i in range(5)}   # 5-day stale prints
L2 = e1.choose_block_length({**series, **stale}) if hasattr(e1, "choose_block_length") else float("nan")
check("6 block length = median per-series estimate (iid -> short; a few stale series do not set it)",
      1.0 <= L <= 3.0 and L2 <= 3.0, f"{L:.2f} {L2:.2f}")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
