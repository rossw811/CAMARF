"""
Synthetic checks for research/stochvol_null_calibration.py
  1. series_moments: iid normal -> ACF ~ 0, excess kurtosis ~ 0; t(5) -> kurtosis ~ 6; GARCH -> ACF clearly > 0
  2. generators: Heston xi = 0 and SABR nu = 0 are iid Gaussian (ACF ~ 0, kurtosis ~ 0); more vol-of-vol -> more ACF
  3. fit recovers a Heston grid point from its own simulated moments (distance small, ACF matched)
  4. make_pairs: return correlation 0 / 0.6 as asked; log prices are cumulated returns (no cointegration built in)
  5. _eg_both = production's analysis._eg_worker in both directions; the scan's crash rule (p = 1.0)
  6. iid control: EG and P2 AIC size at 5% near nominal; a strongly clustered Heston null rejects MORE (same seed scheme)
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
import stochvol_null_calibration as m  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    rng = np.random.default_rng(20261113)
    a0, k0 = m.series_moments(rng.normal(size=40000))
    _, kt = m.series_moments(rng.standard_t(5, size=200000))
    e = rng.normal(size=40000); h = np.ones(40000); x = np.zeros(40000)
    for t in range(1, 40000):
        h[t] = 0.05 + 0.1 * x[t - 1] ** 2 + 0.85 * h[t - 1]; x[t] = np.sqrt(h[t]) * e[t]
    ag, _ = m.series_moments(x)
    check("1. moments: iid ~0/0, t5 kurtosis ~6, GARCH ACF > 0.05",
          abs(a0) < 0.01 and abs(k0) < 0.15 and 4.5 < kt < 8 and ag > 0.05,
          f"iid acf {a0:.4f} kurt {k0:.3f}; t5 kurt {kt:.2f}; garch acf {ag:.3f}")

    ah, kh = m.sim_moments(m.generator("heston", {"kappa": 0.05, "xi": 0.0}), rng)
    as_, ks = m.sim_moments(m.generator("sabr", {"nu": 0.0}), rng)
    ah2, _ = m.sim_moments(m.generator("heston", {"kappa": 0.02, "xi": 0.006}), rng)
    as2, _ = m.sim_moments(m.generator("sabr", {"nu": 0.03}), rng)
    check("2. zero vol-of-vol = iid; more vol-of-vol -> more clustering",
          abs(ah) < 0.01 and abs(kh) < 0.2 and abs(as_) < 0.01 and abs(ks) < 0.2 and ah2 > ah + 0.03 and as2 > as_ + 0.03,
          f"heston xi0 {ah:.4f}/{kh:.3f} xi.006 {ah2:.3f}; sabr nu0 {as_:.4f}/{ks:.3f} nu.03 {as2:.3f}")

    true = {"kappa": 0.02, "xi": 0.006}
    tgt = m.sim_moments(m.generator("heston", true), np.random.default_rng(5), n_paths=80)
    f = m.fit("heston", tgt, np.random.default_rng(6))
    check("3. fit recovers its own grid point's moments", f["dist"] < 0.05 and abs(f["acf"] - tgt[0]) < 0.02,
          f"target {tgt[0]:.3f}/{tgt[1]:.2f} fit {f}")

    g = m.generator("iid", {})
    A, B = m.make_pairs(g, 400, 2520, 0.6, rng)
    c6 = np.median([np.corrcoef(np.diff(A[:, j]), np.diff(B[:, j]))[0, 1] for j in range(400)])
    A0, B0 = m.make_pairs(g, 400, 2520, 0.0, rng)
    c0 = np.median([np.corrcoef(np.diff(A0[:, j]), np.diff(B0[:, j]))[0, 1] for j in range(400)])
    check("4. make_pairs return correlation as asked", abs(c6 - 0.6) < 0.02 and abs(c0) < 0.02, f"0.6 -> {c6:.3f}, 0 -> {c0:.3f}")

    from analysis import _eg_worker
    a, b = A0[:, 0], B0[:, 0]
    mine = m._eg_both((a, b))
    ref = [_eg_worker(("A", "B", a, b, 10, "1D"))["pvalue"], _eg_worker(("A", "B", b, a, 10, "1D"))["pvalue"]]
    crash = m._eg_both((np.full(2520, np.nan), np.full(2520, np.nan)))
    check("5. _eg_both = production worker both directions; short overlap -> not a test",
          np.allclose(mine, ref) and all(np.isnan(crash)), f"{mine} vs {ref}; all-NaN -> {crash}")

    base = m.run_cell(m.generator("iid", {}), 600, 0.0, 11, 4, 150)
    het = m.run_cell(m.generator("heston", {"kappa": 0.01, "xi": 0.015}), 600, 0.0, 11, 4, 150)
    se_eg = np.sqrt(0.05 * 0.95 / base["eg_tests"]); se_p2 = np.sqrt(0.05 * 0.95 / base["p2_tests"])
    check("6. iid control near nominal; clustered Heston rejects more (EG)",
          abs(base["eg_p<0.05"] - 0.05) <= 3 * se_eg and abs(base["p2_aic_p<0.05"] - 0.05) <= 3 * se_p2
          and het["eg_p<0.05"] > base["eg_p<0.05"],
          f"iid EG {base['eg_p<0.05']:.3f} P2 {base['p2_aic_p<0.05']:.3f} (3SE {3*se_eg:.3f}/{3*se_p2:.3f}); "
          f"heston EG {het['eg_p<0.05']:.3f} P2 {het['p2_aic_p<0.05']:.3f}; sim share {het['sim_share']}")

    print(f"\n{passed}/{passed + failed} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
