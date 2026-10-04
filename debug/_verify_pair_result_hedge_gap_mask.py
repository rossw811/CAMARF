"""
Regression test for code-review finding A3 (confirmed 2026-10-03, bug recheck T14): AnalysisPipeline._build_pair_result
built log prices from the aligned `close`, which DataAligner FORWARD-FILLS through DATA_GAP runs (verified: all 12
rows of a 12-bar hole carried the last real close), and fitted the hedge ratios (rolling OLS, TLS, Kalman) on them --
fake flat prices inside a cointegration input, against CLAUDE.md rule 3. (The spread model itself already excluded
DATA_GAP rows via clean_mask; the hedge ratios did not.)
Fix: log prices are NaN on rows where either leg is DATA_GAP before any hedge estimation -- part of the A2
comparison arm (Config.ANALYSIS.HEDGE_FALLBACK = "causal_expanding"), so this test switches the arm on.
Check: leg A has a 40-business-day hole during a strong move in leg B; the reported full-sample OLS hedge ratio must
equal OLS on the rows where BOTH legs have real data (not the value polluted by 40 flat forward-filled rows).
Run: python debug/_verify_pair_result_hedge_gap_mask.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from analysis import AnalysisPipeline
from config import Config
from data import DataAligner, GapFlag

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    idx = pd.bdate_range("2022-01-03", periods=600)
    rng = np.random.default_rng(4)
    lb = np.cumsum(rng.normal(0, 0.01, len(idx))) + 4.0
    lb[300:340] += np.linspace(0, 0.6, 40)                 # strong move in B during A's hole
    lb[340:] += 0.6
    la = 0.7 * lb + rng.normal(0, 0.003, len(idx)) + 1.0
    hole = np.zeros(len(idx), bool); hole[300:340] = True
    A = pd.DataFrame({"open": np.exp(la), "high": np.exp(la), "low": np.exp(la), "close": np.exp(la), "volume": 1e6},
                     index=idx)[~hole]
    B = pd.DataFrame({"open": np.exp(lb), "high": np.exp(lb), "low": np.exp(lb), "close": np.exp(lb), "volume": 1e6},
                     index=idx)
    al = DataAligner.align_universe({"AA_1D": A, "BB_1D": B}, "1D")
    common = al["AA"].index.intersection(al["BB"].index)
    al = {k: v.loc[common] for k, v in al.items()}
    gap = (al["AA"]["gap_flag"] == GapFlag.DATA_GAP).to_numpy() | (al["BB"]["gap_flag"] == GapFlag.DATA_GAP).to_numpy()
    print(f"DATA_GAP rows in the aligned pair: {int(gap.sum())}")
    _orig = Config.ANALYSIS.HEDGE_FALLBACK
    Config.ANALYSIS.HEDGE_FALLBACK = "causal_expanding"
    try:
        built = AnalysisPipeline._build_pair_result({"symbol_a": "AA", "symbol_b": "BB"}, al, "1D")
    finally:
        Config.ANALYSIS.HEDGE_FALLBACK = _orig
    pr = built[0] if isinstance(built, tuple) else built
    a = np.log(al["AA"]["close"].to_numpy()); b = np.log(al["BB"]["close"].to_numpy())
    m = ~gap & np.isfinite(a) & np.isfinite(b)
    ac, bc = a[m] - a[m].mean(), b[m] - b[m].mean()
    beta_real = float(ac @ bc / (bc @ bc))
    am, bm = a - a.mean(), b - b.mean()
    beta_polluted = float(am @ bm / (bm @ bm))
    got = float(pr.hedge_ratio_ols)
    check("ols_hedge_uses_real_rows_only", abs(got - beta_real) < 1e-9,
          f"got={got:.6f} real-rows={beta_real:.6f} with-filled-rows={beta_polluted:.6f}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
