"""
Synthetic ground truth for research/regime_volatility_bias_check.py (endogeneity arm (b), Ross 2026-10-13; written
before the module). Forbes & Rigobon (2002): measured correlation rises with the common factor's variance even when
every loading is unchanged, so a correlation prefilter passes more pairs in high-volatility windows mechanically.
Checks:
  1. fr_adjust(rho, delta) = rho / sqrt(1 + delta (1 - rho^2)): delta 0 -> unchanged; (0.5, 1) -> 0.377964...
  2. constant-beta world (identical betas and idiosyncratic risk, market sd 1% calm vs 3% crisis): the RAW share of
     pairs with |rho| >= 0.4 is clearly higher in the crisis window; the FR-ADJUSTED share removes most of the spike
     (< 20% of the raw crisis share) but NOT all of it -- FR is exact for a series' correlation with the factor, only
     approximate for two stocks that both load on it (first version of this test asserted "flat" for FR and failed:
     crisis 0.080 vs calm 0.000; changed 2026-10-13 after that result, with this reason); the FACTOR-RESCALED share
     (each stock's market component rescaled to the reference volatility -- exact in a one-factor world) is within
     0.05 of calm
  3. genuine-change world (betas truly double in the crisis): the adjusted crisis share still clearly exceeds calm --
     the adjustment must not erase a real increase
  4. simulate_null_share (constant betas, the window's actual market path) reproduces the constant-beta world's raw
     share within 0.05 in both regimes
Run: python debug/_verify_regime_volatility_bias_check.py
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def world(rng, n_stocks, T, mkt_sd, betas, idio_sd):
    m = rng.normal(0, mkt_sd, T)
    R = np.outer(betas, m) + rng.normal(0, 1, (n_stocks, T)) * idio_sd[:, None]
    return R, m


def main():
    try:
        import research.regime_volatility_bias_check as m
    except ImportError as e:
        check("module_exists", False, e); return finish()
    check("fr_identity", abs(m.fr_adjust(0.6, 0.0) - 0.6) < 1e-12)
    check("fr_value", abs(m.fr_adjust(0.5, 1.0) - 0.5 / np.sqrt(1.75)) < 1e-12, m.fr_adjust(0.5, 1.0))
    rng = np.random.default_rng(0)
    n, T, thr = 300, 1000, 0.4
    betas = rng.uniform(0.5, 1.5, n); idio = np.full(n, 0.02)
    Rc, mc = world(rng, n, T, 0.01, betas, idio)
    Rk, mk = world(rng, n, T, 0.03, betas, idio)
    ref_var = mc.var()
    raw_c, raw_k = m.candidate_share(Rc, thr), m.candidate_share(Rk, thr)
    adj_c = m.candidate_share(Rc, thr, delta=m.window_delta(mc, ref_var))
    adj_k = m.candidate_share(Rk, thr, delta=m.window_delta(mk, ref_var))
    check("raw_rises_mechanically", raw_k > raw_c + 0.2, f"calm {raw_c:.3f} crisis {raw_k:.3f}")
    check("fr_removes_most_of_spike", adj_k < 0.2 * raw_k, f"calm {adj_c:.3f} crisis {adj_k:.3f} (raw {raw_k:.3f})")
    sd_ref = float(np.sqrt(ref_var))
    resc_c, resc_k = m.rescaled_share(Rc, mc, sd_ref, thr), m.rescaled_share(Rk, mk, sd_ref, thr)
    check("rescaled_flat_constant_beta", abs(resc_k - resc_c) < 0.05, f"calm {resc_c:.3f} crisis {resc_k:.3f}")
    Rg, mg = world(rng, n, T, 0.01, 2 * betas, idio)   # same market vol as calm, loadings truly doubled
    adj_g = m.candidate_share(Rg, thr, delta=m.window_delta(mg, ref_var))
    check("adjusted_keeps_genuine_increase", adj_g > adj_c + 0.2, f"calm {adj_c:.3f} genuine {adj_g:.3f}")
    resc_g = m.rescaled_share(Rg, mg, float(np.sqrt(ref_var)), thr)
    check("rescaled_keeps_genuine_increase", resc_g > m.rescaled_share(Rc, mc, float(np.sqrt(ref_var)), thr) + 0.2,
          f"genuine {resc_g:.3f}")
    nc = m.simulate_null_share(mc, betas, idio, thr, rng)
    nk = m.simulate_null_share(mk, betas, idio, thr, rng)
    check("null_matches_constant_beta_world", abs(nc - raw_c) < 0.05 and abs(nk - raw_k) < 0.05,
          f"null calm {nc:.3f} vs {raw_c:.3f}; null crisis {nk:.3f} vs {raw_k:.3f}")
    # 2026-10-15 independent review: the null above keeps the window's market volatility, so it must be compared with the
    # RAW share; comparing it with the rescaled share mixes two quantities. A null rescaled the same way is required.
    try:
        rnc = m.simulate_null_share(mc, betas, idio, thr, np.random.default_rng(5), ref_sd=sd_ref)
        rnk = m.simulate_null_share(mk, betas, idio, thr, np.random.default_rng(6), ref_sd=sd_ref)
        check("rescaled_null_matches_rescaled_constant_beta_world", abs(rnk - resc_k) < 0.05 and abs(rnc - resc_c) < 0.05,
              f"rescaled null calm {rnc:.3f} vs {resc_c:.3f}; crisis {rnk:.3f} vs {resc_k:.3f}")
        rng_g = m.simulate_null_share(mg, betas, idio, thr, np.random.default_rng(7), ref_sd=sd_ref)
        check("genuine_increase_exceeds_rescaled_null", resc_g > rng_g + 0.2, f"genuine {resc_g:.3f} vs null {rng_g:.3f}")
        lo, mid, hi = m.reference_sds(pd.Series(np.r_[np.random.default_rng(8).normal(0, 0.01, 2520),
                                                     np.random.default_rng(9).normal(0, 0.03, 252)],
                                                index=pd.bdate_range("1990-01-01", periods=2772)))
        check("reference_sds_ordered_from_data", 0 < lo < hi and lo <= mid <= hi * 1.5, f"{lo:.4f} {mid:.4f} {hi:.4f}")
    except (TypeError, AttributeError) as e:
        check("rescaled_null_and_reference_sds_exist", False, e)
    # 2026-10-19 (Ross 2026-10-17: "the D8 calm rule defines the calm period ... full-sample variance as the
    # sensitivity"): the MAIN reference variance is the market variance on D8-calm days (VIX below its 1990-2025 30th
    # percentile, the same constants stress_test_replication uses); full-sample is the sensitivity.
    try:
        idx = pd.bdate_range("1990-01-01", "2025-12-31")
        rng_v = np.random.default_rng(10)
        vix = pd.Series(np.where(rng_v.random(len(idx)) < 0.4, 12.0, 25.0) + rng_v.uniform(0, 1, len(idx)), index=idx)  # continuous: a two-value VIX makes p30 = 12 and "strictly below" empty
        mkt = pd.Series(np.where(vix < 15, rng_v.normal(0, 0.005, len(idx)), rng_v.normal(0, 0.02, len(idx))), index=idx)
        ref = m.reference_variances(mkt, vix)
        calm = vix < vix.quantile(0.30)
        check("main_reference_is_d8_calm", ref["main"] == "calm_d8"
              and np.isclose(ref["calm_d8"], mkt[calm].var()) and np.isclose(ref["full_sample"], mkt.var()),
              f"calm {ref['calm_d8']:.3g} vs {mkt[calm].var():.3g}; full {ref['full_sample']:.3g}")
        import stress_test_replication as st
        check("one_calm_definition", m._CALM_Q is st._CALM_VIX_QUANTILE and m._CALM_PERIOD is st._CALM_VIX_PERIOD)
    except (TypeError, AttributeError, KeyError, ImportError) as e:
        check("calm_reference_exists", False, f"{type(e).__name__}: {e}")
    # sealed holdout (E13, 2026-10-20): one window end per year, none on/after SEALED_FROM
    try:
        e_all = pd.Series(pd.to_datetime(["2024-03-01", "2024-11-29", "2025-12-31", "2026-02-02", "2026-08-11"]))
        ends = m.yearly_window_ends(e_all, pd.Timestamp("2026-01-01"))
        check("sealed_yearly_window_ends", [str(x.date()) for x in ends] == ["2024-11-29", "2025-12-31"], f"{ends}")
    except (TypeError, AttributeError) as e:
        check("sealed_yearly_window_ends", False, f"{type(e).__name__}: {e}")
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
