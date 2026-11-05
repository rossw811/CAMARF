"""
BUG-D123 (2026-11-05): the spread model's half-lives did not recover a known half-life. Found by the E1 v2 placebo's
planted pairs: a pair built with a 5-day AR(1) spread read 107-815 days, 20-day ones up to 33,690 days. Cause: every
half-life (full, formation-window, rolling) was an AR(1) fit on the TRADING spread, log_a - h_t * log_b, where h_t is
re-estimated daily over a rolling window; its wobble times the log-price level makes the spread's level drift, so the
AR(1) sees a near-unit root. With a hedge held fixed inside each estimation window the same pairs read 5.2 and ~20.

Checks (production path: HedgeRatioEstimator.estimate_all_for_pair + causal expanding fallback + SpreadModel.fit_pair,
as in analysis._build_pair_result):
  1. half_life_full within [0.6, 1.5] x the planted half-life (5 and 20 days, both leg orders);
  2. half_life_rolling_median within [0.4, 1.6] x planted (short windows bias AR(1) down; old code is 20-1000x off);
  3. the z-score window follows the half-life: 5-day pair window < 100 bars (old code: the 252 ceiling);
  4. null: two independent random walks never read as a fast pair (half_life_full NaN or > 60);
  5. prefix invariance: with formation_n set, outputs on the first formation_n bars do not change when later bars
     are appended (point-in-time).
Run: python debug/_verify_half_life_hedge_consistency.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np

from analysis import HedgeRatioEstimator, SpreadModel

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def planted(hl, n=3000, beta=0.9, sd=0.10, seed=0):
    rng = np.random.default_rng(seed)
    la = np.log(50) + np.cumsum(rng.normal(0.0003, 0.02, n))
    phi = 0.5 ** (1 / hl)
    s = np.zeros(n)
    eps = rng.normal(0, sd * np.sqrt(1 - phi ** 2), n)
    for t in range(1, n):
        s[t] = phi * s[t - 1] + eps[t]
    lb = 0.3 + beta * la + s
    return la, lb


def production_fit(log_a, log_b, formation_n=None):
    """analysis._build_pair_result's hedge + spread path (HEDGE_FALLBACK = causal_expanding)."""
    n_form = formation_n if formation_n is not None else log_a.size
    w = min(252, max(60, n_form // 4))
    hr = HedgeRatioEstimator.estimate_all_for_pair(log_a, log_b, w)
    exp = HedgeRatioEstimator.ols_expanding(log_a, log_b, min_obs=w // 2)
    hs = np.where(np.isfinite(hr["ols_series"]), hr["ols_series"], exp)
    return SpreadModel.fit_pair(log_a, log_b, hs, hr["ols_point"], clean_mask=None, static_fallback=False,
                                formation_n=formation_n)


for hl in (5, 20):
    la, lb = planted(hl, seed=hl)
    for order, (x, y) in (("a=base", (la, lb)), ("a=plant", (lb, la))):
        sm = production_fit(x, y)
        f, r, w = sm["half_life_full"], sm["half_life_rolling_median"], sm["window"]
        check(f"1 hl{hl} {order}: half_life_full near truth", np.isfinite(f) and 0.6 * hl <= f <= 1.5 * hl, f"{f:.1f}")
        check(f"2 hl{hl} {order}: rolling median near truth", np.isfinite(r) and 0.4 * hl <= r <= 1.6 * hl, f"{r:.1f}")
        if hl == 5:
            check(f"3 hl5 {order}: z window follows half-life", w < 100, f"window {w}")

rng = np.random.default_rng(99)
nulls = []
for k in range(10):
    xa = np.log(50) + np.cumsum(rng.normal(0, 0.02, 3000))
    xb = np.log(40) + np.cumsum(rng.normal(0, 0.02, 3000))
    nulls.append(production_fit(xa, xb)["half_life_full"])
check("4 null random walks never read fast", all((not np.isfinite(v)) or v > 60 for v in nulls),
      [round(v, 1) for v in nulls])

la, lb = planted(20, n=3000, seed=7)
nf = 1500
s_short = production_fit(la[:2000], lb[:2000], formation_n=nf)
s_long = production_fit(la, lb, formation_n=nf)
same = all(np.allclose(s_short[c][:nf], s_long[c][:nf], equal_nan=True)
           for c in ("spread", "z_rolling", "half_life_rolling_series", "mean_reversion_speed_t"))
check("5 prefix invariance on formation bars", same and s_short["window"] == s_long["window"],
      (s_short["window"], s_long["window"]))

print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
