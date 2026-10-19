"""
D13 / R8.12 (Ross 2026-10-12: "Report the MC power of the 5-year test at the observed effect") for
research/durability_vs_currency_wrds.py. The script reads a non-significant last-5-years EG test (n ~1,260) beside a
significant full-sample one (n ~10,000+) as "the relationship already failed" -- but the shorter test may simply lack
power. Power is simulated at the effect the full sample estimates (residual AR(1) rho and innovation s.d., hedge
ratio, the regressor leg's daily return s.d.), with the production EG call (analysis.eg_pvalue_pair, both
directions, Config.ANALYSIS.EG_MAX_LAG) -- R8.12 also flagged the one-direction, max_lag=None call and the missing
output directory.
Checks:
  1. estimate_effect recovers rho, beta and the innovation s.d. on a synthetic cointegrated pair;
  2. power_at: rho = 1 (no cointegration) -> rejection near the test's size (<= 0.10);
  3. power_at: rho = 0.5 at n = 1,260 -> power > 0.9; rho = 0.995 -> far lower (power falls as rho -> 1);
  4. run_pair reports p_recent from the production two-direction call and power fields in [0, 1].
Run: python debug/_verify_durability_power_d13.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "research"))

import numpy as np
import pandas as pd

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    try:
        import durability_vs_currency_wrds as mod
        from analysis import eg_pvalue_pair
        from config import Config
        rng = np.random.default_rng(3)
        n = 10_000
        x = np.cumsum(rng.normal(0, 0.012, n))
        u = np.zeros(n)
        e = rng.normal(0, 0.004, n)
        for t in range(1, n):
            u[t] = 0.95 * u[t - 1] + e[t]
        y = 0.3 + 0.8 * x + u
        eff = mod.estimate_effect(y, x)
        check("estimate_rho", abs(eff["rho"] - 0.95) < 0.02, f"{eff['rho']:.4f}")
        check("estimate_beta", abs(eff["beta"] - 0.8) < 0.05, f"{eff['beta']:.4f}")
        check("estimate_sigma_u", abs(eff["sigma_e"] - 0.004) / 0.004 < 0.05, f"{eff['sigma_e']:.5f}")
        check("estimate_sigma_x", abs(eff["sigma_x"] - 0.012) / 0.012 < 0.05, f"{eff['sigma_x']:.5f}")

        base = {"beta": 0.8, "sigma_e": 0.004, "sigma_x": 0.012}
        p_null = mod.power_at({**base, "rho": 1.0}, n=1260, n_sim=200, rng=np.random.default_rng(0))
        check("rho_1_is_size", p_null <= 0.10, f"{p_null:.3f}")
        p_fast = mod.power_at({**base, "rho": 0.5}, n=1260, n_sim=200, rng=np.random.default_rng(0))
        p_slow = mod.power_at({**base, "rho": 0.995}, n=1260, n_sim=200, rng=np.random.default_rng(0))
        check("power_high_fast_reversion", p_fast > 0.9, f"{p_fast:.3f}")
        check("power_falls_as_rho_to_1", p_slow < p_fast - 0.3, f"rho .995 -> {p_slow:.3f}")

        idx = pd.bdate_range("1990-01-01", periods=n)
        frames = {"YA": pd.Series(y, index=idx), "XB": pd.Series(x, index=idx)}
        mod.load_log_close = lambda s: (frames[s].to_numpy(), frames[s].index)
        r = mod.run_pair("YA", "XB", n_sim=100, rng=np.random.default_rng(1))
        cut = idx[-1] - pd.DateOffset(years=5)
        m = idx >= cut
        p_prod, _ = eg_pvalue_pair(y[m], x[m], Config.ANALYSIS.EG_MAX_LAG, "1D")
        check("p_recent_is_production_call", np.isclose(r["p_recent"], p_prod), f"{r['p_recent']:.6g} vs {p_prod:.6g}")
        check("power_fields", all(0 <= r[k] <= 1 for k in ("power_recent_at_full_effect", "power_recent_at_recent_effect")),
              f"{r.get('power_recent_at_full_effect')}, {r.get('power_recent_at_recent_effect')}")
    except (AttributeError, TypeError, KeyError) as e:
        check("d13_functions_exist", False, f"{type(e).__name__}: {e}")

    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
