"""
Synthetic ground truth for research/inclusion_did.py (endogeneity arm (c), Ross 2026-10-13; written before the
module). Barberis, Shleifer & Wurgler (2005)-style identification: S&P 500 inclusion as a shock to a stock's
co-movement with incumbent members; difference-in-differences against matched non-added controls, pre-trend test.
Worlds (seeded): 60 events; each treated stock has 3 controls; members load on an index factor f_t.
  effect   -- after inclusion the treated stock gains loading 0.6 on f_t (controls do not)
  null     -- no change for anyone
  pretrend -- the treated stock's loading on f_t rises steadily through the PRE period too (no jump at inclusion)
Checks:
  1. comovement(): mean correlation of a stock with the members, on a known two-series case
  2. effect world: DiD estimate > 0.1 and its 95% bootstrap CI excludes 0
  3. null world: the 95% CI covers 0
  4. pre-trend test SIZE over 200 seeds (false-flag rate in the effect world, no pre-trend, <= 0.10 -- a correctly
     sized 5% test exceeds that with probability ~0.1%) and POWER over 40 seeds (pretrend world flagged >= 0.80);
     flag rate in the pretrend world >= 0.80. (First version checked one seed: the effect world was flagged at
     p = 0.021 -- measured over 60 seeds the false-flag rate is exactly 0.050, i.e. a 1-in-20 draw; changed
     2026-10-13 to test the property instead of one draw. A 40-seed version then read 0.125 and a 300-seed run 0.077;
     600 fresh seeds gave 0.045 (effect) / 0.053 (null) with pre-slopes centred on 0 -- sampling noise, not bias. The
     pre-trend p-value is now a sign-flip randomization test, exact under symmetry.)
Run: python debug/_verify_inclusion_did.py
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def simulate(rng, kind, n_events=60, n_ctrl=3, T_pre=250, T_post=250, n_members=20):
    events = []
    for _ in range(n_events):
        f = rng.normal(0, 0.01, T_pre + T_post)
        members = np.outer(np.ones(n_members), f) + rng.normal(0, 0.01, (n_members, T_pre + T_post))
        t = np.arange(T_pre + T_post)
        if kind == "effect":
            load = np.where(t >= T_pre, 0.6, 0.0)
        elif kind == "pretrend":
            load = 0.6 * t / (T_pre + T_post)
        else:
            load = np.zeros_like(t, dtype=float)
        treated = load * f + rng.normal(0, 0.01, len(t))
        controls = [rng.normal(0, 0.01, len(t)) for _ in range(n_ctrl)]
        events.append({"members": members, "treated": treated, "controls": controls, "t0": T_pre})
    return events


def main():
    try:
        import research.inclusion_did as m
    except ImportError as e:
        check("module_exists", False, e); return finish()
    a = np.array([1, 2, 3, 4, 5.0]); b = np.array([2, 4, 6, 8, 10.0]); c = np.array([5, 4, 3, 2, 1.0])
    check("comovement_known", abs(m.comovement(a, np.vstack([b, c])) - 0.0) < 1e-12, m.comovement(a, np.vstack([b, c])))
    rng = np.random.default_rng(7)
    res = {k: m.did_from_events(simulate(rng, k), rng=np.random.default_rng(1)) for k in ("effect", "null", "pretrend")}
    e, n, p = res["effect"], res["null"], res["pretrend"]
    check("effect_detected", e["did"] > 0.1 and e["ci_low"] > 0, e)
    check("null_covers_zero", n["ci_low"] <= 0 <= n["ci_high"], n)
    fe = np.mean([m.did_from_events(simulate(np.random.default_rng(2000 + s), "effect", n_events=40), n_boot=5,
                                     rng=np.random.default_rng(s))["pretrend_p"] < 0.05 for s in range(200)])
    fp = np.mean([m.did_from_events(simulate(np.random.default_rng(3000 + s), "pretrend", n_events=40), n_boot=20,
                                     rng=np.random.default_rng(s))["pretrend_p"] < 0.05 for s in range(40)])
    check("pretrend_size", fe <= 0.10, f"false-flag rate {fe:.3f}")
    check("pretrend_power", fp >= 0.80, f"flag rate {fp:.3f}")
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
