"""
N14 (Ross, DECISIONS_2026-10-21 #5): size of the production EG screen on its own candidate population. Null = a
stationary block bootstrap of each candidate pair's JOINT returns (one index path for both legs: contemporaneous and
short-lag cross-correlation kept), re-integrated to log prices (cointegration removed). Checks on
research/eg_null_correlation_matched_n14.py:
  1. stationary_indices: length n, values in range, mean run length ~ the block length, deterministic per seed
  2. joint bootstrap keeps the pair's return correlation (0.8 in -> ~0.8 out)
  3. the null removes cointegration: a strongly cointegrated pair (half-life 5) rejected ~100% on its real levels,
     at most 15% across its bootstrap draws
  4. power construction: cointegrated_version with half-life 20 on T = 2500 is rejected >= 80%
  5. sample_candidates returns distinct pairs, all with |corr| >= threshold, none an exact duplicate (corr >= 0.999999)
"""
import os
import sys

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
    import research.eg_null_correlation_matched_n14 as n14  # noqa: E402
except ImportError as e:
    check("module exists", False, str(e))
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1)
from analysis import eg_pvalue_pair  # noqa: E402
from config import Config  # noqa: E402

rng = np.random.default_rng(3)
ix = n14.stationary_indices(5000, 8.0, np.random.default_rng(1))
runs = np.diff(np.flatnonzero(np.diff(ix) != 1))
check("1 indices: range, mean run ~ block length, deterministic",
      len(ix) == 5000 and ix.min() >= 0 and ix.max() < 5000 and 5 < runs.mean() < 11
      and np.array_equal(ix, n14.stationary_indices(5000, 8.0, np.random.default_rng(1))), f"mean run {runs.mean():.2f}")

T = 2500
z = rng.normal(size=(T, 2)) @ np.linalg.cholesky([[1, 0.8], [0.8, 1]]).T * 0.01
la, lb = np.cumsum(z[:, 0]), np.cumsum(z[:, 1])
A, B = n14.joint_bootstrap(la, lb, 5.0, np.random.default_rng(2))
c = np.corrcoef(np.diff(A), np.diff(B))[0, 1]
check("2 joint bootstrap keeps return correlation", abs(c - 0.8) < 0.05 and A[0] == la[0] and B[0] == lb[0], f"{c:.3f}")

w = np.cumsum(rng.normal(size=T) * 0.01)
e = np.zeros(T)
phi = 0.5 ** (1 / 5)
for t in range(1, T):
    e[t] = phi * e[t - 1] + rng.normal() * 0.005
lb2 = 0.9 * w + 0.3 + e
p_real, _ = eg_pvalue_pair(w, lb2, Config.ANALYSIS.EG_MAX_LAG, "1D")
L = n14.block_length(w, lb2)
rej = np.mean([eg_pvalue_pair(*n14.joint_bootstrap(w, lb2, L, np.random.default_rng(s)), Config.ANALYSIS.EG_MAX_LAG, "1D")[0] < 0.05
               for s in range(60)])
check("3 null removes cointegration", p_real < 0.01 and rej <= 0.15, f"real p {p_real:.2e}; null rejection {rej:.3f}; L {L:.2f}")

pw = np.mean([eg_pvalue_pair(*n14.cointegrated_version(la, lb, 20, np.random.default_rng(s)), Config.ANALYSIS.EG_MAX_LAG, "1D")[0] < 0.05
              for s in range(40)])
check("4 power construction (half-life 20, T 2500)", pw >= 0.8, f"{pw:.3f}")

N = 40
F = rng.normal(size=(600, 1))
R = np.hstack([0.9 * F + 0.4 * rng.normal(size=(600, 20)), rng.normal(size=(600, N - 20))]) * 0.01
R[:, 1] = R[:, 0]                                       # an exact duplicate of symbol 0
syms = [f"S{i}" for i in range(N)]
rets = pd.DataFrame(R, columns=syms)
pairs = n14.sample_candidates(rets, 0.6, 30, np.random.default_rng(5), min_obs=100)
cs = [abs(np.corrcoef(rets[a], rets[b])[0, 1]) for a, b in pairs]
check("5 candidates distinct, |corr| >= threshold, no exact duplicates",
      len(pairs) > 0 and len(set(map(frozenset, pairs))) == len(pairs) and min(cs) >= 0.6 and max(cs) < 0.999999,
      f"n {len(pairs)} corr [{min(cs):.3f}, {max(cs):.6f}]")

# 6. (CachyOS 1h run, 2026-10-22: 13 of 300 pairs found) the 1h common calendar is sparse per symbol (crypto's 24/7
# hours in the union); returns from adjacent grid rows were almost all NaN (gap_aware_returns / build_returns_matrix too).
# Candidate returns are taken between each symbol's own consecutive valid prices.
g = pd.date_range("2025-01-02 10:00", periods=4000, freq="30min")
zz = rng.normal(size=(2000, 2)) @ np.linalg.cholesky([[1, 0.8], [0.8, 1]]).T * 0.01
pa = pd.Series(np.nan, index=g)
pb = pd.Series(np.nan, index=g)
pa.iloc[::2] = np.exp(np.cumsum(zz[:, 0]))
pb.iloc[::2] = np.exp(np.cumsum(zz[:, 1]))          # same stamps, NaN rows in between
alg = {"PA": pd.DataFrame({"close": pa}), "PB": pd.DataFrame({"close": pb})}
naive = pd.DataFrame({k: np.diff(np.log(v["close"].to_numpy())) for k, v in alg.items()})
cr = n14.candidate_returns(alg, 100) if hasattr(n14, "candidate_returns") else None
cc = cr["PA"].corr(cr["PB"]) if cr is not None else float("nan")
check("6 sparse calendar: adjacent-row diffs give no returns, own-price returns recover the correlation",
      naive["PA"].notna().sum() == 0 and abs(cc - 0.8) < 0.05, f"naive finite {naive['PA'].notna().sum()}, corr {cc:.3f}")

# 7. N14 v2 (review 2026-10-24): pairs sampled UNIFORMLY from the screen's own candidate list (the anchor sampler
# over-weighted low-degree symbols), after the screen's filters incl. the same-company rule; power at fixed spread s.d.
if hasattr(n14, "screen_sample"):
    g7 = np.random.default_rng(7)
    pop = pd.DataFrame({"symbol_a": [f"T{i}" for i in range(750)] + [f"GVKEY{i:06d}_01W" for i in range(250)],
                        "symbol_b": [f"U{i}" for i in range(750)] + [f"GVKEY{i + 500000:06d}_01W" for i in range(250)],
                        "pearson_corr": 0.7})
    pop.loc[0, ["symbol_a", "symbol_b"]] = ["GVKEY000001_01W", "GVKEY000001_02W"]     # same company
    ids = {"GVKEY000001_01W": frozenset({"g1"}), "GVKEY000001_02W": frozenset({"g1"})}
    smp = n14.screen_sample(pop, 300, g7, ids=ids)
    tt = np.mean([not a.startswith("GVKEY") for a in smp["symbol_a"]])
    check("7a uniform over the screen's pairs (type mix ~ population 75%)", abs(tt - 0.75) < 0.07 and len(smp) == 300,
          f"{tt:.3f}")
    check("7b same-company pair never sampled", not (smp["symbol_a"] == "GVKEY000001_01W").any())
    A7, B7 = n14.cointegrated_version(la, lb, 20, np.random.default_rng(8), 1.0, spread_sd=0.02)
    x7 = B7 - np.polyval(np.polyfit(A7, B7, 1), A7)
    check("7c fixed spread s.d. honoured", 0.012 < np.std(x7) < 0.03, f"{np.std(x7):.4f}")
else:
    check("7 screen_sample exists", False)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
