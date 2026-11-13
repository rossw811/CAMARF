"""
research/yearly_family_test.py -- proposal P2 (Ross 2026-11-11, "yes to all"): a confirmatory test that can see fast
relations lasting 2-5 years. FEASIBILITY ENGINE ONLY -- runs on placebo/synthetic data; which REAL pairs form the declared
family is Ross's decision and is not made here.

Why: Engle-Granger power at the real discovery cutoff (~2e-5 over ~1.8M tests) is limited by the size of the test
family, not the window: the BH cutoff scales with alpha * R / m. A small family declared in advance (economically linked
pairs) gets a cutoff near alpha * R / m with m in the tens or hundreds, so one year of data can be enough.

Procedure, for each calendar year y with enough bars:
  1. for every pair in the declared family, Engle-Granger (statsmodels coint, constant) on year y's bars only
     (both legs present on >= MIN_BARS_SHARE of the year's calendar days, aligned on common dates)
  2. Benjamini-Hochberg at `alpha` across the family's year-y tests
  3. rejected pairs are ADMITTED for year y + 1 only (decision date = last bar of year y; nothing from y + 1 is used)
Output: one row per (pair, year): pvalue, rejected, admitted_for (= y + 1), n_bars.
2026-11-12 (Ross took the recommendation: fixed-hedge positive-control family first):
  test="fixed_adf" -- ADF with a constant on log a - log b (slope fixed at 1, so any constant price ratio, e.g. a
  1,500:1 share-class pair, sits in the intercept; nothing is estimated from the pair before the test). Critical values
  are the plain Dickey-Fuller ones (5% ~ -2.86), not Engle-Granger's (~ -3.34): that, plus no hedge estimate, is the
  power gain. Lag order by AIC (statsmodels adfuller autolag="AIC").
  `family` may be {year: [(a, b), ...]}, a point-in-time family that changes by year
  (research/p2_share_class_family.py); a list is the same family every year.
Verify: debug/_verify_yearly_family_test.py
"""
import numpy as np
import pandas as pd

MIN_BARS_SHARE = 0.8


def bh_reject(p: np.ndarray, alpha: float) -> np.ndarray:
    p = np.asarray(p, float)
    out = np.zeros(len(p), bool)
    ok = np.isfinite(p)
    if not ok.any():
        return out
    q = p[ok]
    order = np.argsort(q)
    m = len(q)
    passed = q[order] <= alpha * np.arange(1, m + 1) / m
    k = np.max(np.nonzero(passed)[0]) + 1 if passed.any() else 0
    rej = np.zeros(m, bool)
    rej[order[:k]] = True
    out[np.flatnonzero(ok)] = rej
    return out


TESTS = ("eg", "fixed_adf", "fixed_adf_schwert", "fixed_adf_tstat")


def schwert_lag(n: int) -> int:
    """Schwert (1989) long lag rule int(12 * (n / 100) ** 0.25): 15 lags at n = 252."""
    return int(12 * (n / 100) ** 0.25)


def _pvalue(x: pd.Series, y: pd.Series, test: str) -> float:
    """2026-11-13 comparison arms (P2 placebo: share-class spread returns are negatively autocorrelated, median lag-1
    -0.13, and AIC picks ~1 lag, so fixed_adf rejected 7.5% at 5% / 3.2x at 0.1% on the null):
    fixed_adf_schwert = ADF with Schwert's fixed lag order; fixed_adf_tstat = general-to-specific t-test lag selection
    (Ng-Perron 1995) from the same maximum. Comparison arms, not replacements (Ross decides)."""
    from statsmodels.tsa.stattools import adfuller, coint
    if test == "eg":
        return float(coint(x, y)[1])
    s = (x - y).to_numpy()
    if test == "fixed_adf":
        return float(adfuller(s, regression="c", autolag="AIC")[1])
    if test == "fixed_adf_schwert":
        return float(adfuller(s, regression="c", maxlag=schwert_lag(len(s)), autolag=None)[1])
    if test == "fixed_adf_tstat":
        return float(adfuller(s, regression="c", maxlag=schwert_lag(len(s)), autolag="t-stat")[1])
    raise ValueError(f"test must be one of {TESTS}")


def yearly_family_tests(log_prices: dict, family, alpha: float = 0.05, years=None, test: str = "eg") -> pd.DataFrame:
    """`log_prices`: {symbol: pd.Series of log prices on its own dates}; `family`: [(a, b), ...] declared in advance,
    or {year: [(a, b), ...]} (only that year's pairs are tested in that year)."""
    if test not in TESTS:
        raise ValueError(f"test must be one of {TESTS}")
    all_dates = pd.DatetimeIndex(sorted(set().union(*[s.index for s in log_prices.values()])))
    years = sorted(set(all_dates.year)) if years is None else years
    rows = []
    for y in years:
        cal_y = all_dates[all_dates.year == y]
        if len(cal_y) == 0:
            continue
        yr_rows = []
        fam_y = family.get(y, []) if isinstance(family, dict) else family
        if not fam_y:
            continue
        for a, b in fam_y:
            sa, sb = log_prices.get(a), log_prices.get(b)
            p, n = np.nan, 0
            if sa is not None and sb is not None:
                j = pd.concat([sa[sa.index.year == y], sb[sb.index.year == y]], axis=1, join="inner").dropna()
                n = len(j)
                if n >= MIN_BARS_SHARE * len(cal_y) and n >= 30:
                    p = _pvalue(j.iloc[:, 0], j.iloc[:, 1], test)
            yr_rows.append({"symbol_a": a, "symbol_b": b, "year": int(y), "n_bars": n, "pvalue": p})
        Y = pd.DataFrame(yr_rows)
        Y["rejected"] = bh_reject(Y["pvalue"].to_numpy(), alpha)
        Y["admitted_for"] = np.where(Y["rejected"], Y["year"] + 1, -1)
        rows.append(Y)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
