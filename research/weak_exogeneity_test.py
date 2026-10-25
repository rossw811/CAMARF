"""
research/weak_exogeneity_test.py — comparison/diagnostic method, NOT part of
the production pipeline. DESCRIPTIVE: whole pre-seal history per pair, never a
decision input.

Weak exogeneity in a bivariate cointegrating relationship (A, B): does leg A
itself adjust to restore equilibrium when the spread deviates (alpha_A != 0
in the VECM error-correction term), or does all the adjustment happen on
leg B's side (alpha_A == 0, A is weakly exogenous w.r.t. the cointegrating
relation — B "leads," A merely gets dragged along)? CAMARF's existing hedge-
ratio/spread machinery treats both legs symmetrically (spread = log_a -
beta*log_b); this answers a genuinely different question the OLS/Kalman/TLS
hedge-ratio estimation never asks: WHICH leg actually does the reverting.

Method: a rank-1 VECM (statsmodels) on each pool pair's log-prices with the
RESTRICTED constant (deterministic="ci", constant inside the cointegrating
relation: production's Johansen specification since 2026-10-25, johansen.py),
k_ar_diff = Config.ANALYSIS.JOHANSEN_K_AR_DIFF, and `pvalues_alpha` per leg.
p > 0.05 for a leg's alpha = fail to reject weak exogeneity for that leg.

Rebuilt 2026-10-25 (PAPER.md section 7.14, ERRATA "Johansen trio specification"):
  - specification: the old script used no deterministic term (det_order -1), which mis-specifies log-price
    relations with an intercept
  - gaps: legs are cut to the longest run that never spans a genuine data gap (data.longest_gap_respecting_segment,
    production's rule); the old script packed finite rows, stitching across outages (BUG-D77 pattern)
  - pairs: the point-in-time pool (Config.DATA.PIT_POOL_PATHS), not legacy per-run pairs files
  - reading: "A leads" depends on which leg the pool calls A (an orientation rule, not economics), so the headline
    is the symmetric split -- one leg adjusts / both adjust / neither adjusts. The old "70% symbol_a leads" was an
    order-dependent count on a 20-pair legacy set.
Each pair's two alpha tests are at 5% with no multiplicity correction: the split is a description, not a test.

Read-only. Never fetches, never recomputes hedge ratios.
Output: output/research/weak_exogeneity_test_{pool}.parquet and a printed summary.
Usage:
    python research/weak_exogeneity_test.py [--pool k1|k2]
Check: debug/_verify_weak_exogeneity_restricted.py
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from statsmodels.tsa.vector_ar.vecm import VECM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import Config  # noqa: E402
from data import longest_gap_respecting_segment  # noqa: E402



def min_bars(tf: str) -> int:
    """The project's pair-test overlap floor (Config.STATS.MIN_OVERLAP_BY_TF), as the EG screen uses."""
    return int(Config.STATS.MIN_OVERLAP_BY_TF.get(tf, 252))


def test_weak_exogeneity(log_a: np.ndarray, log_b: np.ndarray, deterministic: str = "ci", tf: str = "1D") -> dict:
    X = np.column_stack([log_a, log_b])
    if not np.all(np.isfinite(X)) or X.shape[0] < min_bars(tf):
        return {}
    res = VECM(X, k_ar_diff=Config.ANALYSIS.JOHANSEN_K_AR_DIFF, deterministic=deterministic, coint_rank=1).fit()
    p_alpha_a = float(res.pvalues_alpha[0, 0])
    p_alpha_b = float(res.pvalues_alpha[1, 0])
    return {
        "p_alpha_a": p_alpha_a, "p_alpha_b": p_alpha_b,
        "alpha_a": float(res.alpha[0, 0]), "alpha_b": float(res.alpha[1, 0]),
        "a_weakly_exogenous": p_alpha_a > 0.05, "b_weakly_exogenous": p_alpha_b > 0.05,
        "verdict": _verdict(p_alpha_a, p_alpha_b), "deterministic": deterministic, "n_bars": int(len(X)),
    }


def _verdict(p_a: float, p_b: float) -> str:
    a_exo, b_exo = p_a > 0.05, p_b > 0.05
    if a_exo and not b_exo:
        return "A_leads"          # A does not respond to disequilibrium; B does the adjusting
    if b_exo and not a_exo:
        return "B_leads"
    return "both_adjust" if not a_exo else "neither_adjusts"


def pair_segment(sa: pd.Series, sb: pd.Series, tf: str):
    """The two log-price legs on their longest common run that never spans a genuine data gap (production's rule),
    or None if shorter than min_bars(tf)."""
    F = pd.concat([sa, sb], axis=1, join="outer").sort_index()
    F = F[F.index < pd.Timestamp(Config.DATA.SEALED_FROM if tf in ("1D", "1W", "1M") else Config.DATA.SEALED_FROM_INTRADAY)]
    if F.empty:
        return None
    keep = longest_gap_respecting_segment(np.isfinite(F.to_numpy()).all(axis=1), tf)
    S = F[keep]
    return S if len(S) >= min_bars(tf) else None


def summarize(R: pd.DataFrame) -> dict:
    """Verdict counts. one_leg_adjusts / both_adjust / neither_adjusts are symmetric in the legs; A_leads / B_leads
    depend on the pool's leg order and are reported only alongside them."""
    v = pd.Series([_verdict(a, b) for a, b in zip(R["p_alpha_a"], R["p_alpha_b"])], dtype=object)
    c = v.value_counts()
    out = {k: int(c.get(k, 0)) for k in ("A_leads", "B_leads", "both_adjust", "neither_adjusts")}
    out["one_leg_adjusts"] = out["A_leads"] + out["B_leads"]
    out["n"] = int(len(v))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="k2", choices=sorted(Config.DATA.PIT_POOL_PATHS))
    a = ap.parse_args()
    import universe_loader as ul
    pool = pd.read_parquet(Config.DATA.PIT_POOL_PATHS[a.pool])
    cache = {}

    def logp(sym, tf):
        if (sym, tf) not in cache:
            d = ul.load_symbol(sym, tf)
            s = None if d is None else pd.to_numeric(d["close"], errors="coerce").astype(float)
            cache[(sym, tf)] = None if s is None else np.log(s.where(s > 0))
        return cache[(sym, tf)]

    rows = []
    for _, p in pool.iterrows():
        sa, sb, tf = str(p["symbol_a"]), str(p["symbol_b"]), str(p["tf_label"])
        base = {"symbol_a": sa, "symbol_b": sb, "tf_label": tf}
        la, lb = logp(sa, tf), logp(sb, tf)
        if la is None or lb is None:
            rows.append({**base, "error": "missing_leg"}); continue
        S = pair_segment(la, lb, tf)
        if S is None:
            rows.append({**base, "error": "insufficient_overlap"}); continue
        try:
            r = test_weak_exogeneity(S.iloc[:, 0].to_numpy(), S.iloc[:, 1].to_numpy(), tf=tf)
            rows.append({**base, **r, "seg_start": S.index[0], "seg_end": S.index[-1], "error": ""})
        except Exception as e:  # noqa: BLE001 -- recorded per pair, never dropped
            rows.append({**base, "error": f"{type(e).__name__}: {e}"[:200]})
    R = pd.DataFrame(rows)
    out = os.path.join(ROOT, "output", "research", f"weak_exogeneity_test_{a.pool}.parquet")
    R.to_parquet(out)
    ok = R[R["error"] == ""]
    print(f"pool {a.pool}: {len(R)} pairs, tested {len(ok)} ({R['error'].value_counts().to_dict()})")
    s = summarize(ok)
    print(f"  one leg adjusts {s['one_leg_adjusts']} ({s['one_leg_adjusts'] / max(s['n'], 1):.1%}), both adjust "
          f"{s['both_adjust']}, neither adjusts {s['neither_adjusts']}  [order-dependent: A leads {s['A_leads']}, "
          f"B leads {s['B_leads']}]")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
