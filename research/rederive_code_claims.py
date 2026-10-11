"""
research/rederive_code_claims.py -- S34 re-derivation of the central claims that describe code or exact arithmetic
(no market data needed). Each check runs against the production code on synthetic input with a known answer, or
reads the production constant, and prints the evidence; the verdict per claim is recorded in docs/CLAIMS_REGISTRY.md.
  P-087  coint_fraction_rolling = fraction of 252-bar windows with EG p < 0.05; MIN_COINT_FRAC = 0.70
  P-088  override: kept if half-life trend <= 0 and neither Zivot-Andrews nor CUSUM detects a break
  P-091  (n-1)/sqrt(n) = 15.8115 at n=252 for a rolling z-score with n-1 identical points and one different
  M-038  chunked_pearson_candidate_pairs is bit-exact vs the direct correlation_matrix + candidate_pairs call
  M-040  _benjamini_hochberg == statsmodels multipletests(method="fdr_bh"); alpha = Config.STATS.FDR_ALPHA
  M-041  EPISODIC_WINDOW_BARS = 2520, EPISODIC_STEP_BARS = 252 in the discovery scan
(M-039, "both-directions max identical to CointScanner.scan", is BUG-D115: identical max rule, different crash
handling until 2026-10-10 -- recorded there.)
Output: output/research/rederive_code_claims.parquet. Run: python research/rederive_code_claims.py
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.argv = [sys.argv[0]]
OUT = os.path.join(ROOT, "output", "research", "rederive_code_claims.parquet")
rows = []


def rec(claim, holds, evidence):
    rows.append({"claim": claim, "holds": bool(holds), "evidence": evidence})
    print(f"[{'HOLDS' if holds else 'DIFFERS'}] {claim}: {evidence}")


def main():
    import inspect
    from analysis import (AnalysisPipeline, CointScanner, UniverseFilter, _benjamini_hochberg,
                          _rolling_coint_worker)
    from config import Config
    import research.wrds_deep_history_episodic_scan as scan

    # P-087
    sig = inspect.signature(CointScanner.rolling_fraction) if hasattr(CointScanner, "rolling_fraction") \
        else None
    src = inspect.getsource(_rolling_coint_worker)
    w_default = sig.parameters["window"].default if sig else None
    rec("P-087", Config.UNIVERSE.MIN_COINT_FRAC == 0.70 and "pvals < 0.05" in src and w_default == 252,
        f"MIN_COINT_FRAC={Config.UNIVERSE.MIN_COINT_FRAC}; worker counts p < 0.05: {'pvals < 0.05' in src}; "
        f"default window={w_default}, step={sig.parameters['step'].default if sig else None}; NOTE the window shrinks "
        f"to max(60, n//3) when a pair has fewer than window+step bars (analysis.py rolling-coint caller)")

    # P-088
    src88 = inspect.getsource(AnalysisPipeline.passes_coint_frac_secondary_evidence)
    min_bars = AnalysisPipeline._MIN_BARS_FOR_SECONDARY_EVIDENCE
    rec("P-088", False,
        f"code: slope <= 0 AND no Zivot-Andrews break AND no CUSUM excursion (matches) PLUS n_overlap >= "
        f"_MIN_BARS_FOR_SECONDARY_EVIDENCE = {min_bars} bars (BUG-D68, 2026-07-14) -- a fourth condition the paper's "
        f"rule omits; n_overlap condition present in source: {'_MIN_BARS_FOR_SECONDARY_EVIDENCE' in src88}")

    # P-091: rolling z over n points, n-1 identical and the last different (pandas rolling std, ddof=1)
    n = 252
    x = pd.Series([1.0] * (n - 1) + [2.0])
    z = (x - x.rolling(n).mean()) / x.rolling(n).std()
    zz = float(z.iloc[-1])
    rec("P-091", abs(zz - (n - 1) / np.sqrt(n)) < 1e-9 and abs(zz - 15.8115) < 1e-4,
        f"z at the differing point = {zz:.10f}; (n-1)/sqrt(n) = {(n - 1) / np.sqrt(n):.10f} (ddof=1 rolling std)")

    # M-038: chunked vs direct on synthetic returns
    rng = np.random.default_rng(20261010)
    k, T = 120, 600
    f = rng.normal(size=(T, 6))
    R = (f @ rng.normal(size=(6, k)) + rng.normal(size=(T, k))).T   # assets as rows, as the scan passes it
    syms = [f"S{i:03d}" for i in range(k)]
    acm = {s: "equity" for s in syms}
    thr = Config.UNIVERSE.MIN_PEARSON_CORR
    direct = UniverseFilter.candidate_pairs(UniverseFilter.correlation_matrix(R), syms, thr, acm)
    chunk = UniverseFilter.chunked_pearson_candidate_pairs(R, syms, thr, acm, batch_size=37)
    key = lambda L: sorted((d["symbol_a"], d["symbol_b"], d["pearson_corr"]) for d in L)
    a, b = key(direct), key(chunk)
    exact = len(a) == len(b) and all(p[:2] == q[:2] and p[2] == q[2] for p, q in zip(a, b))
    maxdiff = max((abs(p[2] - q[2]) for p, q in zip(a, b)), default=0.0) if len(a) == len(b) else np.nan
    rec("M-038", exact, f"{len(a)} direct vs {len(b)} chunked pairs at |rho|>={thr}; bit-exact={exact}; "
                        f"max |diff|={maxdiff:.3g} (batch_size=37 forces several blocks)")

    # M-040
    from statsmodels.stats.multitest import multipletests
    ok = True
    for seed in range(20):
        p = np.random.default_rng(seed).uniform(size=500) ** 3
        rej, adj = _benjamini_hochberg(p, Config.STATS.FDR_ALPHA)
        r2, a2, _, _ = multipletests(p, alpha=Config.STATS.FDR_ALPHA, method="fdr_bh")
        ok &= bool(np.array_equal(rej, r2) and np.allclose(adj, a2, rtol=0, atol=1e-12))
    rec("M-040", ok and Config.STATS.FDR_ALPHA == 0.05,
        f"rejections and adjusted p identical to statsmodels fdr_bh on 20 x 500 p-values: {ok}; "
        f"FDR_ALPHA={Config.STATS.FDR_ALPHA}")

    # M-041
    rec("M-041", scan.EPISODIC_WINDOW_BARS == 2520 and scan.EPISODIC_STEP_BARS == 252,
        f"EPISODIC_WINDOW_BARS={scan.EPISODIC_WINDOW_BARS}, EPISODIC_STEP_BARS={scan.EPISODIC_STEP_BARS}")

    pd.DataFrame(rows).to_parquet(OUT)
    print(f"\nSaved to {OUT}")


if __name__ == "__main__":
    main()
