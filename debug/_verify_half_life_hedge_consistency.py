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
2026-11-11 (Ross): the rolling half-life takes its hedge from just before each window; Kendall-corrected arm.
  6. unrelated walks and 60/120-day plants are not pulled to ~20 days by an in-window hedge (rolling median > 27);
  7. the estimate at t reads no hedge value inside its window; the first window has no estimate (no in-window fallback);
  8. the Kendall correction moves a 5-day AR(1) on 42-bar windows toward 5; fit_pair returns half_life_rolling_bc_series.
  Old code (001d29c9): 12/19, checks 6-8 fail; new: 19/19.
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

# --- 2026-11-11 (Ross): rolling half-life uses the hedge from just before each window; Kendall correction arm ---
# 6. A hedge fitted inside the window made unrelated walks and slow plants read ~20 days (in-window hedge, 8 seeds:
#    null 21.6, 60-day 20.6, 120-day 21.7). With the prior hedge they read 32-36. Median over 4 seeds of per-pair medians.
def med_roll(make, seeds=range(4)):
    return float(np.median([np.nanmedian(production_fit(*make(s))["half_life_rolling_series"]) for s in seeds]))

def null_pair(s):
    r = np.random.default_rng(700 + s)
    return np.log(50) + np.cumsum(r.normal(0, .02, 3000)), np.log(40) + np.cumsum(r.normal(0, .02, 3000))

for lab, make in (("null", null_pair), ("60-day", lambda s: planted(60, seed=s)), ("120-day", lambda s: planted(120, seed=s))):
    m = med_roll(make)
    check(f"6 {lab}: rolling median not pulled to ~20 by an in-window hedge", m > 27, f"{m:.1f}")

# 7. The estimate at t reads no hedge value from inside its window, and the first window has no estimate.
la, lb = planted(20, n=1200, seed=3)
hedge = np.full(la.size, 1 / 0.9) + np.random.default_rng(1).normal(0, 0.01, la.size)
w, t = 100, 599
base = SpreadModel.rolling_half_life_hedged(la, lb, hedge, window=w, step=1)
pert = hedge.copy(); pert[t - w + 1: t + 1] *= 1.5
alt = SpreadModel.rolling_half_life_hedged(la, lb, pert, window=w, step=1)
check("7a no in-window hedge read", np.isfinite(base[t]) and base[t] == alt[t], (base[t], alt[t]))
check("7b first window empty (no in-window fallback)", np.all(np.isnan(base[: w])) and np.isfinite(base[w]),
      (int(np.isnan(base[:w]).sum()), base[w]))

# 8. Kendall correction: 5-day AR(1) on 42-bar windows (the production window for a 5-day pair). Uncorrected OLS is
#    biased short; the corrected median is closer to 5. fit_pair also returns the corrected series.
rng = np.random.default_rng(11); phi = 0.5 ** (1 / 5); unc, bc = [], []
for _ in range(3000):
    x = np.zeros(42 + 50); e = rng.normal(0, 1, x.size)
    for i in range(1, x.size):
        x[i] = phi * x[i - 1] + e[i]
    x = x[50:]
    try:
        unc.append(SpreadModel.half_life_ar1(x)); bc.append(SpreadModel.half_life_ar1(x, bias_correct=True))
    except TypeError:
        unc.append(SpreadModel.half_life_ar1(x)); bc.append(np.nan)
mu, mb = np.nanmedian(unc), np.nanmedian(bc)
check("8a correction moves a 5-day estimate toward truth", np.isfinite(mb) and abs(mb - 5) < abs(mu - 5), f"{mu:.2f} -> {mb:.2f}")
sm = production_fit(*planted(5, seed=0))
check("8b fit_pair returns half_life_rolling_bc_series", "half_life_rolling_bc_series" in sm
      and np.isfinite(sm["half_life_rolling_bc_series"]).any())

# 9. (Ross 2026-11-11) A refresh that finds no mean reversion leaves the bars up to the next refresh NaN; it does not
#    carry the previous estimate. Spread = a (hedge 0, b = 0): stationary AR(1) up to bar 600, then a convex trend that
#    makes every later window's phi > 1.
rng = np.random.default_rng(4); n9 = 900; a9 = np.zeros(n9)
for i in range(1, n9):
    a9[i] = 0.8 * a9[i - 1] + rng.normal(0, 0.01)
a9[600:] += 1e-4 * np.arange(n9 - 600) ** 2
r9 = SpreadModel.rolling_half_life_hedged(a9, np.zeros(n9), np.zeros(n9), window=100, step=21)
t_ok, t_bad = 498, 750                                   # refresh bars: 99 + 21k; window of 750 lies in the trend
check("9a stationary stretch has an estimate", np.isfinite(r9[t_ok + 5]), r9[t_ok + 5])
check("9b failed refresh is not filled with the old estimate", np.isnan(r9[t_bad]) and np.isnan(r9[t_bad + 10]),
      (r9[t_bad], r9[t_bad + 10]))

# 10. (review of 2aa51cbb, 2026-11-12: three mutants -- forward-fill limited to one refresh, fill from the NEXT refresh
#     (lookahead), Kendall arm keeping the old forward-fill -- passed 9 because it looked only deep inside a run of
#     failures with step 1 elsewhere.) Hold boundaries with step 21, against per-refresh values computed directly
#     here, for both the primary and the Kendall arm.
def _refresh_values(a, b, h, window, step, bc):
    out = {}
    for t in range(window - 1, a.size, step):
        ok = t - window >= 0 and np.isfinite(h[t - window])
        out[t] = SpreadModel.half_life_ar1(a[t - window + 1: t + 1] - h[t - window] * b[t - window + 1: t + 1],
                                           bias_correct=bc) if ok else np.nan
    return out


def _held_exactly(r, vals, n):
    ts = sorted(vals)
    for k, t in enumerate(ts):
        seg = r[t: ts[k + 1] if k + 1 < len(ts) else n]
        v = vals[t]
        if not (np.all(np.isnan(seg)) if np.isnan(v) else np.allclose(seg, v)):
            return False, t
    lead_ok = bool(np.all(np.isnan(r[: ts[0]])))
    return lead_ok, (None if lead_ok else 0)


for bc in (False, True):
    tag = "Kendall" if bc else "primary"
    r = SpreadModel.rolling_half_life_hedged(a9, np.zeros(n9), np.zeros(n9), window=100, step=21, bias_correct=bc)
    vals = _refresh_values(a9, np.zeros(n9), np.zeros(n9), 100, 21, bc)
    ok, at = _held_exactly(r, vals, n9)
    fails = [t for t in sorted(vals) if t > 600 and np.isnan(vals[t])]
    check(f"10a {tag}: every bar holds exactly its latest refresh (trend series, step 21)", ok, f"first mismatch at {at}")
    check(f"10b {tag}: first failed refresh in the trend is NaN at its own bar, the bar before keeps the old value",
          bool(fails) and np.isnan(r[fails[0]]) and np.isfinite(r[fails[0] - 1]), fails[:2])
    # failure then success: hedge NaN where refresh 141 looks (141 - 100 = 41) -> 141..161 NaN, 162 switches back
    h = np.zeros(n9); h[41] = np.nan
    r2 = SpreadModel.rolling_half_life_hedged(a9, np.zeros(n9), h, window=100, step=21, bias_correct=bc)
    v2 = _refresh_values(a9, np.zeros(n9), h, 100, 21, bc)
    ok2, at2 = _held_exactly(r2, v2, n9)
    check(f"10c {tag}: failure then success switches exactly at the refresh bars", ok2 and np.isnan(r2[161])
          and np.isfinite(r2[162]) and np.isfinite(r2[140]), f"mismatch {at2}; r[140,141,161,162]={r2[[140, 141, 161, 162]]}")

print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
