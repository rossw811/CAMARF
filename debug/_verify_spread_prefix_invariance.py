"""
Point-in-time property of the per-bar spread series (Ross 2026-10-19, decision 1; adversarial review of a51f926c):
two pairs whose prices are IDENTICAL up to a date and differ afterwards must get IDENTICAL per-bar values (spread,
z_rolling, half_life_rolling, hedge_ratio_ols_t) on every bar up to that date. Before: the spread's warm-up bars used
the FULL-SAMPLE OLS hedge (HEDGE_FALLBACK = "full_sample"), the z-score / rolling half-life window came from the
whole-history half-life (SpreadModel.fit_pair hl_full), and the hedge window from the whole series length
(_build_pair_result hr_window = log_a.size // 4) -- all three let later data change earlier bars.
Fix: HEDGE_FALLBACK = "causal_expanding"; window lengths from the data up to the pair's formation end (its
eligible_from: the confirming window's end, as GGR's formation-then-trading design). A pair with no formation end is
the descriptive whole-history path (unchanged).
Run: python debug/_verify_spread_prefix_invariance.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from config import Config

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def frames(seed_future, n=2400, cut=1500):
    idx = pd.bdate_range("2010-01-01", periods=n)
    # separate generators so a longer series keeps the same prefix draws
    x = np.cumsum(np.random.default_rng(1).normal(0, 0.01, n))
    u = np.zeros(n)
    e = np.random.default_rng(11).normal(0, 0.01, n)
    for t in range(1, n):
        u[t] = 0.9 * u[t - 1] + e[t]
    # after `cut`, a different future: other noise, slower reversion, a hedge-ratio shift
    r2 = np.random.default_rng(seed_future)
    for t in range(cut, n):
        u[t] = 0.995 * u[t - 1] + r2.normal(0, 0.02)
    beta = np.where(np.arange(n) < cut, 1.0, 1.0 + 0.5 * (seed_future % 2))
    a = np.exp(3 + beta * x + u)
    b = np.exp(3 + x)
    mk = lambda c: pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1e6, "gap_flag": 0}, index=idx)
    return {"A": mk(a), "B": mk(b)}, idx


def main():
    from analysis import AnalysisPipeline
    cut = 1500
    check("hedge_fallback_causal", getattr(Config.ANALYSIS, "HEDGE_FALLBACK", None) == "causal_expanding",
          f"{getattr(Config.ANALYSIS, 'HEDGE_FALLBACK', None)}")
    f1, idx = frames(seed_future=2)
    f2, _ = frames(seed_future=3)
    form_end = idx[1200]                       # formation ends before the futures diverge
    meta = {"symbol_a": "A", "symbol_b": "B", "eligible_from": form_end}
    r1 = AnalysisPipeline._build_pair_result(dict(meta), f1, "1D")
    r2 = AnalysisPipeline._build_pair_result(dict(meta), f2, "1D")
    if r1 is None or r2 is None:
        check("pair_results_built", False, f"{r1 is None} {r2 is None}")
    else:
        s1, s2 = r1[1], r2[1]
        for k in ("spread", "z_rolling", "z_expanding", "half_life_rolling_series", "hedge_ratio_ols_t", "hedge_ratio_kalman_t",
                  "coint_fraction_rolling_t", "half_life_trend_slope_t", "mean_reversion_speed_t", "hurst_rs_t"):
            a1 = np.asarray(s1.get(k), float)[:cut]
            a2 = np.asarray(s2.get(k), float)[:cut]
            same = np.allclose(a1, a2, equal_nan=True)
            check(f"prefix_invariant_{k}", same,
                  f"max |diff| over the first {cut} bars {np.nanmax(np.abs(a1 - a2)) if not same else 0:.3g}")
        # a LONGER future (window lengths derived from the series length -- e.g. the hedge window -- would differ)
        f3, _ = frames(seed_future=2, n=3600)
        r3 = AnalysisPipeline._build_pair_result(dict(meta), f3, "1D")
        bad = [k for k in s1 if k not in ("index", "gap_flag_a", "gap_flag_b")
               and not np.allclose(np.asarray(s1[k], float)[:cut], np.asarray(r3[1][k], float)[:cut], equal_nan=True)]
        check("prefix_invariant_to_future_length", r3 is not None and not bad, f"differing: {bad}")
    # the pool spread rebuild (chain stage pool_spreads) passes each pair's eligible_from as the formation end
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))
    import regenerate_pool_spread_series as rg
    seen = {}
    rg.ad._load_aligned = lambda a, b, tf, as_of_date=None, preloaded=None: {"A": None}
    rg.ad.write_spread_series = lambda a, b, tf, per_bar: None
    orig = AnalysisPipeline._build_pair_result
    AnalysisPipeline._build_pair_result = staticmethod(lambda meta, al, tf: seen.update(meta) or (None, {"index": []}))
    try:
        rg._one(("A", "B", "1D", pd.Timestamp("2015-06-30")))
    finally:
        AnalysisPipeline._build_pair_result = orig
    check("pool_rebuild_passes_eligible_from", seen.get("eligible_from") == pd.Timestamp("2015-06-30"), f"{seen}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
