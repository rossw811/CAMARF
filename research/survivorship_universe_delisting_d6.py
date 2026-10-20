"""
STATUS 2026-10-20: FIRST CUT, READING WITHDRAWN -- the "excluded" set is 98% the D18 quote-only series (a point-in-
time data rule), not survivorship selection; redesign per Development.md "Review of the D6 first cut". Kept as record.

D6 / R3.11 (Ross 2026-10-19): is the discovery universe survivorship-biased against the rest of the CRSP market?

The earlier survivorship test (crisis_regime_survivorship_confound_test.py) could only compare pairs INSIDE the
discovery universe, using S&P 500 membership as "survived". It cannot see securities the universe never contained.
This script compares the universe with what it left out.

  included  = CRSP common stocks (share code 10/11, NYSE/AMEX/NASDAQ) that have a WRDS price file in the discovery
              universe (label -> PERMNO via the content-verified map, wrds_label_permno_final.parquet)
  excluded  = CRSP common stocks active at the same dates with no such file
  outcome   = the security's last CRSP delisting record (legacy dsedelist dlstcd): performance 500-599, merger
              200-299, active 100 (or no record), exchange 300s, liquidation 400s, other

Two views:
  * security level (primary): each security once, stratified by the decade it first became eligible; per-decade
    two-proportion z-tests and a Cochran-Mantel-Haenszel test pooled over decades (strata are disjoint sets of
    securities, so they are independent).
  * by date (descriptive): securities active at each year-end. The same security recurs across dates, so no pooled
    test is reported over dates.

Disclosed: "eventual" outcome runs to the end of CRSP, so a later stratum has had less time to delist -- groups are
compared only within a stratum. The universe was built from today's caches; a security fetched under a ticker that
was later reused can be missing from it for that reason alone (data_wrds resolves each ticker to its latest PERMNO),
which is one of the biases this measures, not a defect in the measurement.
Inputs: output/cache/wrds/{crsp_stocknames_all, wrds_label_permno_final, crsp_delisting_legacy}.parquet.
Scopes: all eligible securities, and those with >= 10 eligible years (discovery's 2520-bar windows need ~10 years).
Output: output/research/survivorship_universe_delisting_d6.parquet (column `scope`; + _by_date.parquet).
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.contingency_tables import StratifiedTable

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_W = os.path.join(_ROOT, "output", "cache", "wrds")
_OUT = os.path.join(_ROOT, "output", "research", "survivorship_universe_delisting_d6.parquet")
_OUT_DATE = os.path.join(_ROOT, "output", "research", "survivorship_universe_delisting_d6_by_date.parquet")
_COMMON_SHRCD = (10, 11)
_MAJOR_EXCHCD = (1, 2, 3)
OUTCOMES = ("performance", "merger", "active", "exchange", "liquidation", "other")


def classify_delisting(dlstcd: pd.Series) -> pd.Series:
    c = pd.to_numeric(dlstcd, errors="coerce")
    g = (c // 100)
    out = pd.Series("other", index=c.index, dtype=object)
    out[c.isna() | (g == 1)] = "active"
    out[g == 2] = "merger"
    out[g == 3] = "exchange"
    out[g == 4] = "liquidation"
    out[g == 5] = "performance"
    return out


def common_stock_spells(names: pd.DataFrame) -> pd.DataFrame:
    """Name spells on which the security is an ordinary common stock on a major exchange (filter per spell)."""
    s = names.copy()
    s["namedt"] = pd.to_datetime(s["namedt"])
    s["nameenddt"] = pd.to_datetime(s["nameenddt"])
    keep = s["shrcd"].isin(_COMMON_SHRCD) & s["exchcd"].isin(_MAJOR_EXCHCD)
    return s.loc[keep, ["permno", "namedt", "nameenddt"]].reset_index(drop=True)


def active_on(spells: pd.DataFrame, date: pd.Timestamp) -> np.ndarray:
    m = (spells["namedt"] <= date) & (spells["nameenddt"] >= date)
    return spells.loc[m, "permno"].unique()


def outcome_by_permno(delist: pd.DataFrame) -> pd.Series:
    d = delist.copy()
    d["dlstdt"] = pd.to_datetime(d["dlstdt"])
    last = d.sort_values(["permno", "dlstdt"]).groupby("permno").tail(1).set_index("permno")
    return classify_delisting(last["dlstcd"])


def eligible_life_years(spells: pd.DataFrame) -> pd.Series:
    """Years each security spent as an eligible common stock (sum over its eligible spells)."""
    return (spells["nameenddt"] - spells["namedt"]).dt.days.groupby(spells["permno"]).sum() / 365.25


def _counts(permnos, outcomes: pd.Series) -> dict:
    o = outcomes.reindex(pd.Index(permnos)).fillna("active")
    vc = o.value_counts()
    return {"n": int(len(o)), **{f"n_{k}": int(vc.get(k, 0)) for k in OUTCOMES}}


def universe_outcome_table(spells, included, outcomes, dates) -> pd.DataFrame:
    """By-date view: one row per (date, group)."""
    inc = set(included)
    rows = []
    for d in pd.to_datetime(list(dates)):
        act = active_on(spells, d)
        for grp, sel in (("included", [p for p in act if p in inc]), ("excluded", [p for p in act if p not in inc])):
            rows.append({"date": d.strftime("%Y-%m-%d"), "group": grp, **_counts(sel, outcomes)})
    return pd.DataFrame(rows)


def security_level_table(spells, included, outcomes) -> pd.DataFrame:
    """Security-level view: each security once, stratum = decade of its first eligible date."""
    first = spells.groupby("permno")["namedt"].min()
    dec = (first.dt.year // 10 * 10).astype(int)
    inc = set(included)
    rows = []
    for decade, perms in dec.groupby(dec):
        p = perms.index
        for grp, sel in (("included", [x for x in p if x in inc]), ("excluded", [x for x in p if x not in inc])):
            rows.append({"date": f"{decade}s", "group": grp, **_counts(sel, outcomes)})
    return pd.DataFrame(rows)


def _ztest(x1, n1, x0, n0):
    if min(n1, n0) == 0:
        return float("nan"), float("nan")
    p = (x1 + x0) / (n1 + n0)
    se = np.sqrt(p * (1 - p) * (1 / n1 + 1 / n0))
    if se == 0:
        return float("nan"), float("nan")
    z = (x1 / n1 - x0 / n0) / se
    return float(z), float(2 * stats.norm.sf(abs(z)))


def compare_groups(tab: pd.DataFrame, outcome: str = "performance") -> pd.DataFrame:
    """Per-stratum included-minus-excluded rate of `outcome`, z-test; plus a pooled CMH row (strata assumed
    independent -- valid for the security-level table, not for overlapping dates). Also merger-rate difference."""
    rows, tables, w_num, w_den = [], [], 0.0, 0.0
    for d, g in tab.groupby("date", sort=False):
        i = g[g.group == "included"].iloc[0]
        e = g[g.group == "excluded"].iloc[0]
        x1, n1, x0, n0 = i[f"n_{outcome}"], i["n"], e[f"n_{outcome}"], e["n"]
        z, p = _ztest(x1, n1, x0, n0)
        r1 = x1 / n1 if n1 else np.nan
        r0 = x0 / n0 if n0 else np.nan
        m1 = i["n_merger"] / n1 if n1 else np.nan
        m0 = e["n_merger"] / n0 if n0 else np.nan
        rows.append({"date": d, "n_included": int(n1), "n_excluded": int(n0), "perf_rate_included": r1,
                     "perf_rate_excluded": r0, "diff_perf_rate": r1 - r0, "z": z, "p_value": p,
                     "diff_merger_rate": m1 - m0})
        if n1 and n0:
            tables.append(np.array([[x1, n1 - x1], [x0, n0 - x0]], dtype=float))
            w = n1 * n0 / (n1 + n0)
            w_num += w * (r1 - r0)
            w_den += w
    out = pd.DataFrame(rows)
    if tables:
        st = StratifiedTable(tables)
        t = st.test_null_odds(correction=False)
        out = pd.concat([out, pd.DataFrame([{
            "date": "pooled_cmh", "n_included": int(out.n_included.sum()), "n_excluded": int(out.n_excluded.sum()),
            "diff_perf_rate": w_num / w_den, "z": float("nan"), "p_value": float(t.pvalue),
            "mh_odds_ratio": float(st.oddsratio_pooled)}])], ignore_index=True)
    return out


def main():
    names = pd.read_parquet(os.path.join(_W, "crsp_stocknames_all.parquet"))
    lab = pd.read_parquet(os.path.join(_W, "wrds_label_permno_final.parquet"))
    dl = pd.read_parquet(os.path.join(_W, "crsp_delisting_legacy.parquet"))
    spells = common_stock_spells(names)
    included = set(pd.to_numeric(lab["permno"], errors="coerce").dropna().astype(int))
    outcomes = outcome_by_permno(dl)
    elig = set(spells.permno)
    print(f"CRSP common-stock securities: {len(elig):,}; in the discovery universe: {len(included & elig):,} "
          f"({len(included & elig) / len(elig):.1%}); universe PERMNOs outside common-stock spells: "
          f"{len(included - elig):,}")
    # Two scopes: every eligible security, and those with >= 10 eligible years -- discovery's episodic windows are
    # 2520 bars (~10 trading years), so a shorter-lived security could never enter a window whether included or not.
    life = eligible_life_years(spells)
    parts = []
    for scope, min_years in (("all", 0.0), ("life_ge_10y", 10.0)):
        sp_s = spells[spells.permno.isin(life[life >= min_years].index)]
        sec = security_level_table(sp_s, included, outcomes)
        r = compare_groups(sec)
        r_m = compare_groups(sec, outcome="merger")[["date", "diff_perf_rate", "p_value"]].rename(
            columns={"diff_perf_rate": "diff_merger_rate_cmh", "p_value": "p_value_merger"})
        parts.append(r.merge(r_m, on="date", how="left").assign(scope=scope))
    res = pd.concat(parts, ignore_index=True)
    years = pd.date_range("1930-12-31", "2024-12-31", freq="YE")
    by_date = universe_outcome_table(spells, included, outcomes, years)
    bd = compare_groups(by_date)
    bd = bd[bd.date != "pooled_cmh"]  # overlapping securities across dates: no pooled test
    os.makedirs(os.path.dirname(_OUT), exist_ok=True)
    res.to_parquet(_OUT, index=False)
    bd.to_parquet(_OUT_DATE, index=False)
    pd.set_option("display.width", 220)
    print(res.round(4).to_string(index=False))
    print(bd.iloc[::10].round(4).to_string(index=False))
    print(f"-> {_OUT}\n-> {_OUT_DATE}")


if __name__ == "__main__":
    main()
