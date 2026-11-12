"""
Synthetic ground truth for research/stochastic_vol_models.py (fixed seeds; Monte Carlo checks use 3 standard errors).
  Bachelier
    1. put-call parity exact; zero vol -> intrinsic
    2. closed form = Monte Carlo of F_T ~ N(F, sigma^2 T)
    3. hit probability = Monte Carlo first passage on a fine grid (discrete monitoring misses a little: one-sided)
  Heston
    4. xi -> 0 with v0 = theta: Heston call = Black-Scholes call at sigma = sqrt(theta)
    5. characteristic-function price = full-truncation Monte Carlo
    6. CF at u = -i equals S0 e^{rT} (martingale); daily returns fat-tailed when xi is large (kurtosis > 4)
  SABR
    7. beta = 1, nu = 0: implied vol = alpha at every strike (exact)
    8. ATM continuity: strike a hair off ATM matches the ATM branch
    9. Hagan vol prices = Monte Carlo prices at 3 strikes (Hagan is an approximation: 3 SE + 1% of price)
   10. beta = 0, nu = 0 reduces to Bachelier: Black at the Hagan vol = Bachelier price (rel err < 1e-4) -- tests the
       (1 - beta) terms that checks 7-9 (beta = 1) cannot (independent review 2026-11-11, finding 6)
   11. the small-z series of z / x(z) agrees with the closed form at the switch point
Run: python debug/_verify_stochastic_vol_models.py
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


def mc(payoff):
    return payoff.mean(), payoff.std(ddof=1) / np.sqrt(payoff.size)


def main():
    from research import stochastic_vol_models as M
    rng = np.random.default_rng(20261111)

    # ---- Bachelier
    F, K, T, s = 1.5, 1.2, 0.5, 0.8
    c, p = M.bachelier_price(F, K, T, s), M.bachelier_price(F, K, T, s, kind="put")
    check("1 Bachelier parity + zero vol", abs(c - p - (F - K)) < 1e-12
          and M.bachelier_price(F, K, T, 0.0) == F - K and M.bachelier_price(F, K, T, 0.0, kind="put") == 0.0,
          f"c-p={c - p:.12f}")
    FT = F + s * np.sqrt(T) * rng.standard_normal(400_000)
    m, se = mc(np.maximum(FT - K, 0))
    check("2 Bachelier closed form = MC", abs(m - c) < 3 * se, f"cf={c:.5f} mc={m:.5f} se={se:.5f}")
    n, steps, b, sig, TT = 20_000, 2000, 1.0, 1.0, 1.0
    ph = M.bachelier_hit_prob(b, sig, TT)               # one level at distance b
    hit_up = np.zeros(n, bool); W = np.zeros(n)
    for _ in range(steps):
        W += sig * np.sqrt(TT / steps) * rng.standard_normal(n)
        hit_up |= W >= b
    pm = hit_up.mean(); se = np.sqrt(pm * (1 - pm) / n)
    check("3 Bachelier first passage (one level) = MC", -3 * se <= ph - pm <= 3 * se + 0.02,
          f"formula={ph:.4f} mc={pm:.4f} (discrete monitoring biases MC low)")

    # ---- Heston
    S0, r = 100.0, 0.02
    th = 0.04
    bs = M.black_price(S0 * np.exp(r * 1.0), 100.0, 1.0, np.sqrt(th), df=np.exp(-r))
    h0 = M.heston_call(S0, 100.0, 1.0, r, th, 2.0, th, 1e-4, -0.5)
    check("4 Heston xi->0 = Black-Scholes", abs(h0 - bs) < 1e-3, f"heston={h0:.5f} bs={bs:.5f}")
    pars = dict(v0=0.04, kappa=1.5, theta=0.04, xi=0.5, rho=-0.7)
    hc = M.heston_call(S0, 105.0, 1.0, r, **pars)
    xT, _ = M.simulate_heston(200_000, 250, 1 / 250, S0, r, rng=rng, **pars)
    m, se = mc(np.exp(-r) * np.maximum(np.exp(xT) - 105.0, 0))
    check("5 Heston CF price = MC", abs(m - hc) < 3 * se + 0.02, f"cf={hc:.4f} mc={m:.4f} se={se:.4f}")
    fm = M.heston_cf(-1j, S0, 1.0, r, **pars)
    X, _ = M.simulate_heston(200, 2520, 1 / 252, 1.0, 0.0, 0.04, 3.0, 0.04, 1.0, -0.7, rng, return_paths=True)
    ret = np.diff(X, axis=0).ravel()
    kurt = float(np.mean((ret - ret.mean()) ** 4) / ret.var() ** 2)
    check("6 Heston martingale + fat tails", abs(fm.real - S0 * np.exp(r)) < 1e-8 and abs(fm.imag) < 1e-8
          and kurt > 4, f"cf(-i)={fm:.6f} target={S0 * np.exp(r):.6f} daily kurtosis={kurt:.2f}")

    # ---- SABR
    flat = [M.sabr_vol(100.0, k, 2.0, 0.25, 1.0, -0.3, 0.0) for k in (60, 90, 100, 130, 200)]
    check("7 SABR beta=1 nu=0 flat at alpha", max(abs(v - 0.25) for v in flat) < 1e-12, f"{flat}")
    atm = M.sabr_vol(100.0, 100.0, 1.0, 0.3, 0.5, -0.4, 0.6)
    near = M.sabr_vol(100.0, 100.0 * (1 + 1e-6), 1.0, 0.3, 0.5, -0.4, 0.6)
    check("8 SABR ATM continuity", abs(atm - near) < 1e-6, f"atm={atm:.8f} near={near:.8f}")
    a, be, rh, nu, TT = 0.25, 1.0, -0.3, 0.4, 1.0
    FT = M.simulate_sabr(200_000, 250, TT / 250, 100.0, a, be, rh, nu, rng)
    det = []
    ok = True
    for k in (85.0, 100.0, 115.0):
        hp = M.black_price(100.0, k, TT, M.sabr_vol(100.0, k, TT, a, be, rh, nu))
        m, se = mc(np.maximum(FT - k, 0))
        ok &= abs(m - hp) < 3 * se + 0.01 * hp
        det.append(f"K={k:.0f} hagan={hp:.3f} mc={m:.3f}+-{se:.3f}")
    check("9 SABR Hagan = MC", ok, "; ".join(det))

    # beta = 0, nu = 0 is exactly the Bachelier model: Black price at the Hagan vol must equal the Bachelier price.
    # This exercises every (1 - beta) term at full strength (checks 7-9 use beta = 1, where they vanish). Measured
    # 2026-11-11: correct formula |rel err| <= 2e-5 at K = 70..130; review mutants (1-beta)^2/24 -> /6 and
    # fk^(1-beta) -> fk^((1-beta)/2) in the alpha^2 term give 6e-4 .. 0.74.
    errs = [M.black_price(100.0, k, 1.0, M.sabr_vol(100.0, k, 1.0, 20.0, 0.0, 0.0, 0.0))
            / M.bachelier_price(100.0, k, 1.0, 20.0) - 1 for k in (70.0, 85.0, 100.0, 115.0, 130.0)]
    check("10 SABR beta=0 nu=0 = Bachelier", max(abs(e) for e in errs) < 1e-4, f"max rel err={max(map(abs, errs)):.1e}")
    t = M.ZX_SERIES_BELOW
    rh = -0.4
    closed = lambda z: z / np.log((np.sqrt(1 - 2 * rh * z + z * z) + z - rh) / (1 - rh))
    check("11 z/x(z) series branch = closed form at the switch", abs(M.z_over_x(0.99 * t, rh) - closed(1.01 * t)) < 1e-8
          and M.z_over_x(0.0, rh) == 1.0, f"series={M.z_over_x(0.99 * t, rh):.10f} closed={closed(1.01 * t):.10f}")

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
