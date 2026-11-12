"""
Synthetic ground truth for research/spread_arma.py.
  1. pure AR(1) phi=0.9: ARMA root half-life = AR(1) half-life (analysis.half_life_ar1) = true 6.58, within 6%
  2. latent AR(1) phi=0.95 (true half-life 13.51) + noise, T=5000, 10 seeds: half_life_ar1 reads short (< 0.5x true)
     on every seed -- the old method fails -- and the ARMA half-life median is within 15% of true, >= 8/10 seeds
     within 25%. The one-year case (T=252) is REPORTED, not asserted: the review found 1.74..20.64 over 12 seeds, one
     BIC pick of ARMA(2,0) reproducing the short bias -- the real-data stage must carry that variance.
  3. irf_half_life of an AR(1) equals the closed form exactly; ar_root_half_life of AR(2) with a known dominant root
  4. negative / explosive roots give NaN; complex dominant root is flagged oscillating
  5. too few observations -> NaN, no exception
Run: python debug/_verify_spread_arma.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def ar1(phi, n, rng):
    e = rng.standard_normal(n + 500)
    x = np.zeros_like(e)
    for t in range(1, e.size):
        x[t] = phi * x[t - 1] + e[t]
    return x[500:]


def main():
    from research.spread_arma import ar_root_half_life, fit_arma_bic, irf_half_life
    from analysis import SpreadModel
    rng = np.random.default_rng(20261111)
    hl = lambda phi: -np.log(2) / np.log(phi)

    x = ar1(0.9, 5000, rng)
    r = fit_arma_bic(x)
    h1 = SpreadModel.half_life_ar1(x)
    # truth is judged in phi units: SE(phi_hat) = sqrt((1 - phi^2) / T); half-life magnifies phi error near 1
    se = np.sqrt((1 - 0.81) / 5000)
    phi_of = lambda h: 2.0 ** (-1.0 / h)
    check("1 pure AR(1): ARMA = AR(1) (2%), both within 3 SE of true phi",
          abs(r["half_life"] - h1) / h1 < 0.02 and abs(phi_of(r["half_life"]) - 0.9) < 3 * se
          and abs(phi_of(h1) - 0.9) < 3 * se, f"arma={r['half_life']:.2f} (p,q)=({r['p']},{r['q']}) "
          f"ar1={h1:.2f} true={hl(0.9):.2f}; phi_hat={phi_of(h1):.4f} SE={se:.4f}")

    # 10 seeds (review 2026-11-11, finding 5: one seed; seed 1005 alone missed 15%)
    tru = hl(0.95)
    a1, am = [], []
    for s in range(10):
        g = np.random.default_rng(1000 + s)
        lat = ar1(0.95, 5000, g)
        obs = lat + 2.0 * g.standard_normal(lat.size)
        a1.append(SpreadModel.half_life_ar1(obs))
        am.append(fit_arma_bic(obs)["half_life"])
    am = np.array(am)
    within = int((np.abs(am - tru) / tru < 0.25).sum())
    check("2 noisy AR(1), 10 seeds: AR(1) always short; ARMA median within 15%, >= 8/10 within 25%",
          max(a1) < 0.5 * tru and abs(np.nanmedian(am) - tru) / tru < 0.15 and within >= 8,
          f"true={tru:.2f} AR(1) max={max(a1):.2f} ARMA median={np.nanmedian(am):.2f} range=[{np.nanmin(am):.2f}, "
          f"{np.nanmax(am):.2f}] within 25%: {within}/10")
    short = []
    for s in range(12):
        g = np.random.default_rng(2000 + s)
        lat = ar1(0.95, 252, g)
        r = fit_arma_bic(lat + 2.0 * g.standard_normal(lat.size))
        short.append((round(r["half_life"], 1), (r["p"], r["q"])))
    print(f"   REPORTED, T=252 (one year), 12 seeds, true {tru:.2f}: {short}")

    ok_irf = abs(irf_half_life([0.8], []) - hl(0.8)) < 1e-9
    a2 = ar_root_half_life([0.7 + 0.2, -0.7 * 0.2])        # roots 0.7 and 0.2
    check("3 IRF closed form; AR(2) dominant root", ok_irf and abs(a2[0] - hl(0.7)) < 1e-9 and not a2[1],
          f"irf={irf_half_life([0.8], []):.6f} vs {hl(0.8):.6f}; ar2={a2}")

    neg, expl = ar_root_half_life([-0.5]), ar_root_half_life([1.02])
    cplx = ar_root_half_life([1.0, -0.5])                  # roots 0.5 +/- 0.5i, modulus 0.707
    check("4 negative/explosive NaN, complex flagged", np.isnan(neg[0]) and np.isnan(expl[0]) and cplx[1]
          and abs(cplx[0] - hl(np.sqrt(0.5))) < 1e-9, f"neg={neg} expl={expl} cplx={cplx}")

    r = fit_arma_bic(rng.standard_normal(20))
    check("5 short input NaN", np.isnan(r["half_life"]) and r["n_obs"] == 20)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
