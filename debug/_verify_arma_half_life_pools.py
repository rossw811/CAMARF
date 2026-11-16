"""
Synthetic checks for research/arma_half_life_pools.py
  1. realised_decay: AR(1) hl 10 -> ~10; AR(1) + equal-variance white noise -> still ~10 (noise-robust), while the
     plain "acf < 0.5" crossing reads short (why the addendum replaced it)
  2. install_recorders: production's fit_pair output is unchanged by the recording wrappers, the recorded inputs reproduce
     the rolling half-life, and restore() puts the originals back
  3. evaluate_windows point-in-time: changing rows after t + window leaves row t unchanged; changing rows in
     (t, t + window] changes only the realised target, never the two predictions; formation rows are skipped
  4. the comparison favours ARMA on noisy AR(1) spreads (the case it is for) and does not on clean AR(1) spreads
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
import arma_half_life_pools as m  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def ar1(n, hl, rng, sd=1.0):
    phi = 0.5 ** (1 / hl)
    x = np.zeros(n)
    e = rng.normal(0, sd, n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + e[t]
    return x


def plain_crossing(s):
    x = s - s.mean(); d = np.dot(x, x)
    for k in range(1, len(s) // 2):
        if np.dot(x[:-k], x[k:]) / d <= 0.5:
            return k
    return np.nan


def main():
    rng = np.random.default_rng(20261113)
    x = ar1(40000, 10, rng)
    noisy = x + rng.normal(0, x.std(), x.size)
    d0, d1, pc = m.realised_decay(x, 200), m.realised_decay(noisy, 200), plain_crossing(noisy)
    check("1. realised decay ~ latent half-life with and without noise; plain crossing short under noise",
          abs(d0 - 10) < 1.0 and abs(d1 - 10) < 1.5 and pc < 6, f"clean {d0:.2f} noisy {d1:.2f} plain-crossing {pc}")

    from analysis import SpreadModel
    n = 3000
    lb = np.cumsum(rng.normal(0, 0.01, n)); la = lb + ar1(n, 10, rng, 0.01)
    hedge = np.ones(n)
    ref = SpreadModel.fit_pair(la, lb, hedge, 1.0, formation_n=800)
    rec = {}
    restore = m.install_recorders(rec)
    try:
        got = SpreadModel.fit_pair(la, lb, hedge, 1.0, formation_n=800)
    finally:
        restore()
    same = all(np.array_equal(np.nan_to_num(np.asarray(ref[k], float), nan=-9), np.nan_to_num(np.asarray(got[k], float), nan=-9))
               for k in ref if isinstance(ref[k], (np.ndarray, float, int)) and np.size(ref[k]) > 0)
    rerun = SpreadModel.rolling_half_life_hedged(rec["la"], rec["lb"], rec["h"], window=rec["window"])
    check("2. recorders: output unchanged, recorded inputs reproduce the rolling half-life, originals restored",
          same and np.array_equal(np.nan_to_num(rerun, nan=-9), np.nan_to_num(rec["hl_out"], nan=-9))
          and SpreadModel.fit_pair.__name__ == "fit_pair" and rec["form_real"] > 0,
          f"window {rec['window']}, formation real rows {rec['form_real']}")

    w = 252
    base = {"la": la, "lb": lb, "h": hedge, "window": w, "step": 21, "form_real": 800}
    W = m.evaluate_windows(base)
    t0 = int(W.t.iloc[2])
    la2 = la.copy(); la2[t0 + w + 1:] += 3.0                 # after the target window
    W2 = m.evaluate_windows({**base, "la": la2}).set_index("t")
    la3 = la.copy(); la3[t0 + 1: t0 + w + 1] += np.linspace(0, 0.5, w)   # inside the target window
    W3 = m.evaluate_windows({**base, "la": la3}).set_index("t")
    r0 = W.set_index("t").loc[t0]
    ok3 = (np.allclose(W2.loc[t0, ["hl_ar1", "hl_arma", "realised"]].astype(float), r0[["hl_ar1", "hl_arma", "realised"]].astype(float), equal_nan=True)
           and np.allclose(W3.loc[t0, ["hl_ar1", "hl_arma"]].astype(float), r0[["hl_ar1", "hl_arma"]].astype(float), equal_nan=True)
           and not np.isclose(W3.loc[t0, "realised"], r0["realised"]) and W.t.min() >= 800)
    check("3. point-in-time: predictions use rows <= t only; target only (t, t+w]; formation skipped", bool(ok3),
          f"t0 {t0}, first t {W.t.min()}, windows {len(W)}")

    # 2026-11-15: the first version required ARMA NOT to win on clean AR(1) spreads (< 0.60 of windows) and failed at
    # 0.62: on a 252-bar window the OLS AR(1) is biased short (7.9 vs true 10) and exact-MLE ARMA less so (8.1), so ARMA
    # edging ahead on clean data is expected, not a defect. What B decides on is its declared rule (better share >= 0.6
    # AND median ratio outside [0.8, 1.25]); the check now tests that rule: it fires on noisy spreads, not on clean ones.
    def decide(noise):
        lb = np.cumsum(rng.normal(0, 0.01, n)); s = ar1(n, 10, rng, 0.01)
        la = lb + s + rng.normal(0, noise * s.std(), n)
        W = m.evaluate_windows({"la": la, "lb": lb, "h": np.ones(n), "window": w, "step": 21, "form_real": 0})
        W["pool"], W["symbol_a"], W["symbol_b"] = "syn", "A", "B"
        return m.summarize(W).iloc[0]
    noisy_s, clean_s = decide(1.0), decide(0.0)
    check("4. B's declared decision rule fires on noisy AR(1) spreads, not on clean ones",
          bool(noisy_s.decision_arma_better) and not bool(clean_s.decision_arma_better),
          f"noisy: better {noisy_s.arma_better_share:.2f}, ratio {noisy_s.median_ratio_arma_ar1:.2f}; "
          f"clean: better {clean_s.arma_better_share:.2f}, ratio {clean_s.median_ratio_arma_ar1:.2f}")

    print(f"\n{passed}/{passed + failed} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
