"""
Synthetic ground-truth checks for research/distribution_fits.py (2026-09-26, audit step 3).

Draws samples from KNOWN distributions and checks that AIC/BIC selection recovers the true family,
that nested alternatives are not preferred when the simpler model is true (Poisson vs negative
binomial; binomial vs beta-binomial), that fitted parameters land near the truth, and that the
parametric-bootstrap goodness-of-fit test does not reject a correctly-specified sample while it
does reject a clearly misspecified one.

Run: python debug/_verify_distribution_fits.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from scipy import stats

from research.distribution_fits import fit_binomial_family, fit_continuous, fit_counts

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def best(df, crit="bic"):
    return df.sort_values(crit).iloc[0]["family"]


def test_positive_continuous():
    rng = np.random.default_rng(1)
    x = stats.weibull_min(c=1.6, scale=20).rvs(4000, random_state=rng)
    r = fit_continuous(x, ["expon", "gamma", "weibull_min", "lognorm"], positive=True, gof_reps=100, rng=rng)
    check("weibull.selected", best(r) == "weibull_min", f"best={best(r)}")
    c = r.set_index("family").loc["weibull_min", "params"]["c"]
    check("weibull.shape_near_1.6", abs(c - 1.6) < 0.1, f"c={c:.3f}")
    check("weibull.gof_not_rejected", r.set_index("family").loc["weibull_min", "gof_p"] > 0.01)
    check("expon.gof_rejected", r.set_index("family").loc["expon", "gof_p"] < 0.01)
    x2 = stats.expon(scale=5).rvs(4000, random_state=rng)
    r2 = fit_continuous(x2, ["expon", "gamma", "weibull_min"], positive=True, gof_reps=0, rng=rng)
    check("expon.bic_prefers_simpler_when_true", best(r2, "bic") == "expon", f"best={best(r2, 'bic')}")


def test_real_line_heavy_tails():
    rng = np.random.default_rng(2)
    x = stats.cauchy(loc=0.5, scale=2).rvs(4000, random_state=rng)
    r = fit_continuous(x, ["norm", "cauchy", "t"], positive=False, gof_reps=0, rng=rng)
    check("cauchy.beats_normal", best(r, "aic") in ("cauchy", "t"), f"best={best(r, 'aic')}")
    check("normal.worst", r.sort_values("aic").iloc[-1]["family"] == "norm")
    xn = stats.norm(1, 3).rvs(4000, random_state=rng)
    rn = fit_continuous(xn, ["norm", "cauchy", "t"], positive=False, gof_reps=0, rng=rng)
    check("normal.bic_selected_when_true", best(rn, "bic") == "norm", f"best={best(rn, 'bic')}")


def test_counts():
    rng = np.random.default_rng(3)
    k = stats.poisson(3.2).rvs(5000, random_state=rng)
    r = fit_counts(k, ["poisson", "nbinom"], gof_reps=100, rng=rng)
    check("poisson.bic_selected_when_true", best(r, "bic") == "poisson", f"best={best(r, 'bic')}")
    check("poisson.gof_not_rejected", r.set_index("family").loc["poisson", "gof_p"] > 0.01)
    k2 = stats.nbinom(n=2, p=0.3).rvs(5000, random_state=rng)  # mean 4.67, var 15.6
    r2 = fit_counts(k2, ["poisson", "nbinom"], gof_reps=100, rng=rng)
    check("nbinom.selected_when_overdispersed", best(r2, "bic") == "nbinom", f"best={best(r2, 'bic')}")
    check("poisson.gof_rejected_when_overdispersed", r2.set_index("family").loc["poisson", "gof_p"] < 0.01)
    g = stats.geom(0.2).rvs(5000, random_state=rng)  # support 1,2,...
    r3 = fit_counts(g, ["geom", "poisson"], gof_reps=0, rng=rng)
    p = r3.set_index("family").loc["geom", "params"]["p"]
    check("geom.selected_and_p_near_0.2", best(r3) == "geom" and abs(p - 0.2) < 0.01, f"p={p:.4f}")


def test_binomial_family():
    rng = np.random.default_rng(4)
    n = rng.integers(20, 200, 800)
    s = rng.binomial(n, 0.4)
    r = fit_binomial_family(s, n)
    check("binomial.bic_selected_when_homogeneous", best(r, "bic") == "binomial", f"best={best(r, 'bic')}")
    p_i = rng.beta(2, 3, 800)  # heterogeneous per-unit rates, mean 0.4
    s2 = rng.binomial(n, p_i)
    r2 = fit_binomial_family(s2, n)
    check("betabinom.selected_when_heterogeneous", best(r2, "bic") == "betabinom", f"best={best(r2, 'bic')}")
    a, b = (r2.set_index("family").loc["betabinom", "params"][k] for k in ("a", "b"))
    check("betabinom.mean_near_0.4", abs(a / (a + b) - 0.4) < 0.03, f"a={a:.2f} b={b:.2f}")


if __name__ == "__main__":
    test_positive_continuous()
    test_real_line_heavy_tails()
    test_counts()
    test_binomial_family()
    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
