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


def yearly_family_tests(log_prices: dict, family: list, alpha: float = 0.05, years=None) -> pd.DataFrame:
    """`log_prices`: {symbol: pd.Series of log prices on its own dates}; `family`: [(a, b), ...] declared in advance."""
    from statsmodels.tsa.stattools import coint
    all_dates = pd.DatetimeIndex(sorted(set().union(*[s.index for s in log_prices.values()])))
    years = sorted(set(all_dates.year)) if years is None else years
    rows = []
    for y in years:
        cal_y = all_dates[all_dates.year == y]
        if len(cal_y) == 0:
            continue
        yr_rows = []
        for a, b in family:
            sa, sb = log_prices.get(a), log_prices.get(b)
            p, n = np.nan, 0
            if sa is not None and sb is not None:
                j = pd.concat([sa[sa.index.year == y], sb[sb.index.year == y]], axis=1, join="inner").dropna()
                n = len(j)
                if n >= MIN_BARS_SHARE * len(cal_y) and n >= 30:
                    p = float(coint(j.iloc[:, 0], j.iloc[:, 1])[1])
            yr_rows.append({"symbol_a": a, "symbol_b": b, "year": int(y), "n_bars": n, "pvalue": p})
        Y = pd.DataFrame(yr_rows)
        Y["rejected"] = bh_reject(Y["pvalue"].to_numpy(), alpha)
        Y["admitted_for"] = np.where(Y["rejected"], Y["year"] + 1, -1)
        rows.append(Y)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
