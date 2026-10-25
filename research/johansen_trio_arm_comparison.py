"""
research/johansen_trio_arm_comparison.py -- Johansen trios: production (statsmodels det_order -1) vs det_order 0 vs the
restricted-constant arm, on real candidate trios (Ross, DECISIONS_2026-10-21 #3: comparison arm first, then decide).

Why: production's trio test (analysis._johansen_worker) runs coint_johansen with JOHANSEN_DET_ORDER = -1 (no
deterministic term). The approved switch to det_order 0 was not applied: statsmodels' det_order 0 is the UNRESTRICTED
constant (drift critical values) and over-rejects driftless random walks (11.7% bivariate, 7.7% for trios at a nominal
5%), while -1 has almost no power once the cointegrating relation has an intercept, as log-price relations do (3.3%
on simulated trios with intercept 20). The restricted constant (Johansen's case 2) is the specification for price
levels without trend: `cointegration_estimator_arms.johansen_rank_restricted`, critical values simulated per number of
common trends and window length. debug/_verify_johansen_trio_restricted.py

Candidates: production's own rule (analysis.TrioBuilder.candidate_trios: two pool pairs sharing a leg), from the
point-in-time pool's 1D pairs, every candidate (no TRIO_MAX_CANDIDATES cap: this compares test specifications).
Legs: universe_loader.load_symbol (WRDS priority; sealed rows never present), log close, the longest run that never
spans a genuine data gap (production's rule). Whole pre-seal history per trio: DESCRIPTIVE, never a decision input.
Output: output/research/johansen_trio_arm_comparison.parquet (one row per trio) and a printed summary.
Usage: python research/johansen_trio_arm_comparison.py [--pool k1|k2] [--level 0.05]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import Config  # noqa: E402
from data import longest_gap_respecting_segment  # noqa: E402
from johansen import crit_from_table, johansen_rank_restricted  # noqa: E402

_COL = {0.10: 0, 0.05: 1, 0.01: 2}
OUT = os.path.join(ROOT, "output", "research", "johansen_trio_arm_comparison.parquet")


def compare_trio(Y: np.ndarray, level: float = 0.05, k_ar_diff: int = None, crit=None, crit_maxeig=None) -> dict:
    """Rank-0 decision and sequential rank under the three specifications on one (T x 3) log-level matrix, plus the
    restricted-constant max-eigenvalue rank (2026-10-25; replaces the legacy trace/max-eigenvalue agreement check, which
    ran on production's old no-constant spec). Max-eig critical values: johansen.MAXEIG_TABLE unless given."""
    from statsmodels.tsa.vector_ar.vecm import coint_johansen
    k = Config.ANALYSIS.JOHANSEN_K_AR_DIFF if k_ar_diff is None else k_ar_diff
    c = _COL[round(level, 4)]
    out = {"n_bars": int(len(Y))}
    for name, det in (("prod_det_m1", -1), ("det0", 0)):
        j = coint_johansen(Y, det_order=det, k_ar_diff=k)
        above = j.lr1 > j.cvt[:, c]
        out[f"{name}_trace0"] = float(j.lr1[0])
        out[f"{name}_reject0"] = bool(above[0])
        out[f"{name}_rank"] = int(np.argmin(above)) if not above.all() else len(above)
    r = johansen_rank_restricted(Y, level, k, crit=crit)
    out["restricted_trace0"], out["restricted_crit0"] = float(r["trace"][0]), float(r["crit"][0])
    out["restricted_reject0"], out["restricted_rank"] = bool(r["rank"] >= 1), int(r["rank"])
    cm = crit_maxeig or (lambda T, m, lev, kk: crit_from_table(T, m, lev, kk, stat="maxeig"))
    x = johansen_rank_restricted(Y, level, k, crit=cm, stat="maxeig")
    out["restricted_maxeig0"], out["restricted_maxeig_crit0"] = float(x["trace"][0]), float(x["crit"][0])
    out["restricted_maxeig_reject0"], out["restricted_maxeig_rank"] = bool(x["rank"] >= 1), int(x["rank"])
    return out


def candidate_trios(pool: pd.DataFrame) -> list:
    from analysis import TrioBuilder
    p = pool[pool["tf_label"] == "1D"].sort_values(["symbol_a", "symbol_b"])
    pairs = [{"symbol_a": a, "symbol_b": b} for a, b in zip(p["symbol_a"], p["symbol_b"])]
    return TrioBuilder.candidate_trios(pairs, max_candidates=10 ** 9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="k1", choices=sorted(Config.DATA.PIT_POOL_PATHS))
    ap.add_argument("--level", type=float, default=Config.ANALYSIS.JOHANSEN_SIGNIFICANCE)
    a = ap.parse_args()
    import universe_loader as ul
    pool = pd.read_parquet(Config.DATA.PIT_POOL_PATHS[a.pool])
    trios = candidate_trios(pool)
    print(f"pool {a.pool}: {len(pool)} pairs -> {len(trios)} candidate 1D trios (production rule, uncapped)")
    cache = {}

    def logp(sym):
        if sym not in cache:
            d = ul.load_symbol(sym, "1D")
            s = None if d is None else pd.to_numeric(d["close"], errors="coerce").astype(float)
            cache[sym] = None if s is None else np.log(s.where(s > 0))
        return cache[sym]

    rows = []
    for i, (x, y, z) in enumerate(trios):
        L = [logp(s) for s in (x, y, z)]
        row = {"symbol_a": x, "symbol_b": y, "symbol_c": z}
        if any(v is None for v in L):
            rows.append({**row, "error": "missing_leg"}); continue
        F = pd.concat(L, axis=1, join="outer").sort_index()
        F = F[F.index < pd.Timestamp(Config.DATA.SEALED_FROM)]
        keep = longest_gap_respecting_segment(np.isfinite(F.to_numpy()).all(axis=1), "1D")
        Y = F.to_numpy()[keep]
        if len(Y) < 60:
            rows.append({**row, "error": "insufficient_overlap", "n_bars": int(len(Y))}); continue
        try:
            rows.append({**row, **compare_trio(Y, a.level), "error": ""})
        except Exception as e:  # noqa: BLE001 -- recorded per trio, never dropped
            rows.append({**row, "error": f"{type(e).__name__}: {e}"[:200]})
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(trios)}", flush=True)
    R = pd.DataFrame(rows)
    R.to_parquet(OUT)
    ok = R[R["error"] == ""]
    print(f"tested {len(ok)} of {len(R)} trios ({R['error'].value_counts().to_dict()})")
    for s in ("prod_det_m1", "det0", "restricted"):
        print(f"  {s}: rank-0 rejected {int(ok[f'{s}_reject0'].sum())} ({ok[f'{s}_reject0'].mean():.1%}); "
              f"rank distribution {ok[f'{s}_rank'].value_counts().sort_index().to_dict()}")
    print(f"  restricted max-eig: rank-0 rejected {int(ok['restricted_maxeig_reject0'].sum())} "
          f"({ok['restricted_maxeig_reject0'].mean():.1%}); trace/max-eig rank disagree on "
          f"{int((ok['restricted_rank'] != ok['restricted_maxeig_rank']).sum())} trios")
    print("  agreement (restricted vs production):")
    print(pd.crosstab(ok["restricted_reject0"], ok["prod_det_m1_reject0"], rownames=["restricted"], colnames=["prod -1"]))
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
