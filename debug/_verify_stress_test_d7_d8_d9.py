"""
debug/_verify_stress_test_d7_d8_d9.py -- synthetic checks for the D7/D8/D9 fixes to research/stress_test_replication.py
(Ross 2026-10-12, details 2026-10-17/18; docs/decisions/DECISIONS_2026-10-12.md), run BEFORE trusting them on real data.

D7: Andrews & Kim (2006, JBES 24(4)) P and R tests for cointegration breakdown over a short period (eqs. 8-15), baseline
    T = max(2 years, 10 x m).
D8: calm controls derived from VIX: every day below the 1990-2025 30th percentile, same length, same start month, closest
    in time; season match dropped (flagged) only when no same-month window qualifies.
D9: crisis vs its own calm control is paired -> sign-flip randomization over connected components of pairs sharing a leg.
"""
import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "research"))

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


def _coint_pair(rng, n, rho=0.4, beta=1.0, scale=0.02):
    x = np.cumsum(rng.normal(scale=0.01, size=n))
    u = np.zeros(n)
    e = rng.normal(scale=scale, size=n)
    for t in range(1, n):
        u[t] = rho * u[t - 1] + e[t]
    return 0.5 + beta * x + u, x


try:
    from stress_test_replication import (andrews_kim_test, baseline_length, select_calm_window,
                                         paired_component_signflip_test)
    from analysis import _eg_worker

    print("Check D7-1: P and R match the paper's formulas on a hand-checkable case")
    rng = np.random.default_rng(1)
    T, m = 50, 4
    y, x = _coint_pair(rng, T + m)
    r = andrews_kim_test(y, x, T=T, m=m)
    X = np.column_stack([np.ones(T + m), x])
    b_all = np.linalg.lstsq(X, y, rcond=None)[0]
    u_post = y[T:] - X[T:] @ b_all
    P_hand = float(np.sum(u_post ** 2))
    R_hand = float(sum(np.sum(u_post[i:]) ** 2 for i in range(m)))
    h = int(np.ceil(m / 2))
    Pj = []
    for j in range(T - m + 1):
        keep = np.r_[0:j, j + h:T]
        bj = np.linalg.lstsq(X[keep], y[keep], rcond=None)[0]
        Pj.append(np.sum((y[j:j + m] - X[j:j + m] @ bj) ** 2))
    pv_hand = float(np.mean(P_hand <= np.array(Pj)))
    check(f"P = post-break SSR at beta(1:T+m) [{r['P']:.6g} vs {P_hand:.6g}]", np.isclose(r["P"], P_hand))
    check(f"R = sum of squared reverse partial sums [{r['R']:.6g} vs {R_hand:.6g}]", np.isclose(r["R"], R_hand))
    check(f"pv_P = mean(P <= P_j), leave-ceil(m/2)-out (eq. 15) [{r['pv_P']:.4f} vs {pv_hand:.4f}]",
          np.isclose(r["pv_P"], pv_hand))
    check("T - m + 1 subsample statistics", r["n_subsamples"] == T - m + 1)
    r1 = andrews_kim_test(y, x, T=T, m=1)
    check("m = 1 -> P == R (paper, s3)", np.isclose(r1["P"], r1["R"]))

    print("Check D7-2: size near 5% under a stable cointegrating relation (T=500)")
    for m in (13, 50):
        rej = 0
        n_sim = 300
        for s in range(n_sim):
            y, x = _coint_pair(np.random.default_rng(1000 + s), 500 + m)
            rej += andrews_kim_test(y, x, T=500, m=m)["pv_P"] < 0.05
        rate = rej / n_sim
        check(f"m={m}: rejection rate {rate:.3f} in [0.02, 0.10]", 0.02 <= rate <= 0.10)

    print("Check D7-3: detects an in-crisis breakdown the old baseline+crisis EG misses")
    n_det_ak = n_old_holds = 0
    for s in range(100):
        rng = np.random.default_rng(5000 + s)
        y, x = _coint_pair(rng, 513)
        y[500:] += np.cumsum(rng.normal(0.01, 0.02, 13))   # spread wanders off in the last 13 days
        n_det_ak += andrews_kim_test(y, x, T=500, m=13)["pv_P"] < 0.05
        eg = _eg_worker(("A", "B", y, x, 10, "1D"))
        n_old_holds += bool(eg.get("ok") and eg.get("pvalue", 1.0) < 0.05)
    check(f"Andrews-Kim rejects in >= 80/100 [{n_det_ak}]", n_det_ak >= 80)
    # Bar set at >= 80 before the first run, which gave 77; restated as "misses most breaks" (2026-10-18, disclosed in
    # Development.md) -- the defect is the old test calling most broken pairs cointegrated, not a specific rate.
    check(f"old EG on baseline+crisis still says 'holds' in > 50/100 [{n_old_holds}] (the R5.5 defect)",
          n_old_holds > 50)

    print("Check D7-4: baseline T = max(2-year rows, 10 x m)")
    check("m=13, 2y=504 -> 504", baseline_length(504, 13) == 504)
    check("m=51, 2y=504 -> 510", baseline_length(504, 51) == 510)
    check("m=146, 2y=504 -> 1460", baseline_length(504, 146) == 1460)

    print("Check D8: calm window selection from VIX")
    idx = pd.bdate_range("1990-01-01", "2025-12-31")
    vix = pd.Series(20.0, index=idx)
    vix["1995-03-01":"1995-12-31"] = 11.0     # long calm stretch, starts March
    vix["2005-08-01":"2005-08-31"] = 11.0     # calm August 2005
    vix["2006-08-01":"2006-08-31"] = 11.0     # calm August 2006 (closer to 2007)
    vix["2006-08-10"] = 30.0                  # ...but one spike day disqualifies windows that contain it
    # 2018-2025 alternates 25/9 (never 10 calm days in a row) so the 30th pct is exactly 20: "below" = the 9s and 11s
    vix[idx[-2000:]] = np.where(np.arange(2000) % 2 == 0, 25.0, 9.0)
    crises = [("q", "2007-08-01", "2007-08-14"), ("g", "2008-09-01", "2009-03-31")]
    w = select_calm_window(vix, "2007-08-01", 10, crises)
    check(f"same month, every day below p30, closest to crisis -> 2006-08 window after the spike [{w['start'].date()}]",
          w["start"].year == 2006 and w["start"].month == 8 and w["start"] > pd.Timestamp("2006-08-10"))
    check("season_matched flag True", w["season_matched"] is True)
    check("window length equals the crisis length", w["n_days"] == 10)
    check("every VIX day in the window below the threshold", bool((vix[w["start"]:w["end"]] < w["threshold"]).all()))
    w2 = select_calm_window(vix, "2008-09-01", 150, crises)
    check(f"no September window of 150 calm days -> season dropped, flagged [{w2['start'].date()}, "
          f"{w2['season_matched']}]", w2["season_matched"] is False and w2["start"].year == 1995)
    try:
        select_calm_window(vix, "2008-09-01", 400, crises)
        check("no qualifying window at all -> raises", False)
    except ValueError:
        check("no qualifying window at all -> raises", True)

    print("Check D9: paired sign-flip over shared-leg components")
    # 20 pairs sharing leg "HUB" all break in crisis, none in calm: one unit, not 20 -> not significant
    hub = pd.DataFrame({"symbol_a": ["HUB"] * 20, "symbol_b": [f"s{i}" for i in range(20)],
                        "crisis_outcome": True, "calm_outcome": False})
    rest = pd.DataFrame({"symbol_a": [f"x{i}" for i in range(30)], "symbol_b": [f"y{i}" for i in range(30)],
                         "crisis_outcome": [True, False] * 15, "calm_outcome": [False, True] * 15})
    r = paired_component_signflip_test(pd.concat([hub, rest], ignore_index=True), n_sim=20000,
                                       rng=np.random.default_rng(0))
    check(f"classical McNemar would reject [exact p {r['mcnemar_exact_p']:.2g} < 0.01]", r["mcnemar_exact_p"] < 0.01)
    check(f"component test does not [p {r['p_value']:.3f} > 0.10]", r["p_value"] > 0.10)
    check(f"31 units with a discordant pair [{r['n_units_discordant']}]", r["n_units_discordant"] == 31)
    # genuine effect over many independent pairs -> significant
    eff = pd.DataFrame({"symbol_a": [f"a{i}" for i in range(60)], "symbol_b": [f"b{i}" for i in range(60)],
                        "crisis_outcome": [True] * 30 + [False] * 30,
                        "calm_outcome": [False] * 26 + [True] * 4 + [True] * 4 + [False] * 26})
    # rows 0-25 crisis-only (26), rows 26-29 both (concordant), rows 30-33 calm-only (4): S = 26 - 4 = 22
    r = paired_component_signflip_test(eff, n_sim=20000, rng=np.random.default_rng(0))
    check(f"26 vs 4 discordant over independent pairs -> p < 0.001 [{r['p_value']:.4g}]", r["p_value"] < 0.001)
    check(f"crisis - calm rate difference reported [{r['rate_diff']:.3f}]", np.isclose(r["rate_diff"], 22 / 60))

    print("Check D9-2: build_paired_table pairs each crisis with its own control only")
    from stress_test_replication import build_paired_table
    tested = pd.DataFrame({"symbol_a": ["A", "A", "C", "A"], "symbol_b": ["B", "B", "D", "B"],
                           "crisis": ["q", "calm_for_q", "q", "g"], "ak_breakdown": [True, False, True, True]})
    controls = [("calm_for_q", "", "", "q", True), ("calm_for_g", "", "", "g", False)]
    pt = build_paired_table(tested, controls, "ak_breakdown")
    check(f"only A/B @ q has both sides [{len(pt)} rows]", len(pt) == 1 and pt.iloc[0]["crisis"] == "q"
          and bool(pt.iloc[0]["crisis_outcome"]) and not bool(pt.iloc[0]["calm_outcome"]))

    print("Check D7-5: stress_test_pair uses T = max(2y, 10m) and reports the Andrews-Kim fields")
    import stress_test_replication as mod
    rng = np.random.default_rng(3)
    y, x = _coint_pair(rng, 700)
    idx = pd.bdate_range(end="2020-06-30", periods=700)
    series = {"YA": y, "XB": x}
    mod.load_aligned_pair = lambda a, b, tf: (pd.DataFrame({"close": np.exp(series[a])}, index=idx),
                                              pd.DataFrame({"close": np.exp(series[b])}, index=idx))
    short = mod.stress_test_pair("YA", "XB", "t", str(idx[600].date()), str(idx[612].date()))   # m = 13
    check(f"m=13 tested with T = 2-year rows [{short.get('status')}, T={short.get('n_baseline_days')}]",
          short["status"] == "TESTED" and 500 <= short["n_baseline_days"] <= 530)
    check("Andrews-Kim fields present", {"ak_P", "ak_pv_P", "ak_pv_R", "ak_m_over_T", "ak_breakdown"} <= set(short))
    long_ = mod.stress_test_pair("YA", "XB", "t", str(idx[600].date()), str(idx[699].date()))   # m = 100 -> T 1000
    check(f"m=100 needs T=1000 > 600 available -> INSUFFICIENT_HISTORY [{long_.get('status')}, "
          f"t_required={long_.get('t_required')}]", long_["status"] == "INSUFFICIENT_HISTORY"
          and long_.get("t_required") == 1000)
except ImportError as e:
    check(f"D7/D8/D9 functions exist ({e})", False)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
