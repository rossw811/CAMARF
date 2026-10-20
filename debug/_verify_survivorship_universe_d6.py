"""
Synthetic proof for research/survivorship_universe_delisting_d6.py (D6 / R3.11, Ross 2026-10-19).

D6 asks whether the discovery universe (securities with a WRDS price file) is survivorship-biased against the rest of
the CRSP common-stock market: at each date, securities active then are split into included vs excluded, and their
eventual outcome (performance delisting 500-599, merger 200-299, still active 100, other) is compared.

Checks: delisting-code classes; only share codes 10/11 on NYSE/AMEX/NASDAQ count, per spell; a security counts at a
date only inside an eligible spell; a planted gap (excluded securities die more often) is recovered with the right
sign by the per-date test and the stratified (CMH) test; a no-gap world is not flagged; the outcome is the
security's last delisting record.
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name} {detail}")
    else:
        failed += 1
        print(f"[FAIL] {name} {detail}")


try:
    import survivorship_universe_delisting_d6 as d6
except Exception as e:  # noqa: BLE001
    print(f"[FAIL] import: {type(e).__name__}: {e}")
    print(f"\n0/1 checks passed")
    sys.exit(1)

# 1. delisting classes
c = d6.classify_delisting(pd.Series([100, 231, 241, 331, 450, 520, 584, 600, np.nan]))
check("classify", list(c) == ["active", "merger", "merger", "exchange", "liquidation", "performance", "performance",
                              "other", "active"], str(list(c)))

# 2. eligible spells: share code and exchange filter, per spell
names = pd.DataFrame({
    "permno": [1, 1, 2, 3, 4],
    "namedt": pd.to_datetime(["2000-01-01", "2005-01-01", "2000-01-01", "2000-01-01", "2000-01-01"]),
    "nameenddt": pd.to_datetime(["2004-12-31", "2010-12-31", "2010-12-31", "2010-12-31", "2010-12-31"]),
    "shrcd": [10, 73, 11, 12, 10],   # permno 1 becomes an ETF-like code in 2005; permno 3 is a foreign share code
    "exchcd": [1, 1, 3, 1, 4],       # permno 4 trades on another exchange
})
sp = d6.common_stock_spells(names)
check("spells: share code / exchange filter", sorted(sp.permno.unique()) == [1, 2], str(sorted(sp.permno.unique())))
act = d6.active_on(sp, pd.Timestamp("2007-06-30"))
check("active only inside an eligible spell", sorted(act) == [2], str(sorted(act)))
act2 = d6.active_on(sp, pd.Timestamp("2003-06-30"))
check("active in the earlier spell", sorted(act2) == [1, 2], str(sorted(act2)))

# 3. outcome = last delisting record
dl = pd.DataFrame({"permno": [5, 5, 6], "dlstdt": pd.to_datetime(["2001-01-01", "2009-01-01", "2003-01-01"]),
                   "dlstcd": [100, 520, 231]})
o = d6.outcome_by_permno(dl)
check("outcome = last record", o.loc[5] == "performance" and o.loc[6] == "merger", str(o.to_dict()))

# 4. planted gap: excluded securities die (performance) at 30%, included at 10%
rng = np.random.default_rng(7)
n = 4000
perm = np.arange(10_000, 10_000 + n)
names = pd.DataFrame({"permno": perm, "namedt": pd.Timestamp("1990-01-01"), "nameenddt": pd.Timestamp("2020-12-31"),
                      "shrcd": 10, "exchcd": 1})
included = set(perm[: n // 2])
p_perf = np.where(np.isin(perm, list(included)), 0.10, 0.30)
codes = np.where(rng.random(n) < p_perf, 550, 100)
dl = pd.DataFrame({"permno": perm, "dlstdt": pd.Timestamp("2021-01-01"), "dlstcd": codes})
dates = pd.to_datetime(["1995-12-31", "2005-12-31"])
tab = d6.universe_outcome_table(d6.common_stock_spells(names), included, d6.outcome_by_permno(dl), dates)
check("table rows per date x group", len(tab) == 4, str(len(tab)))
res = d6.compare_groups(tab)
row = res[res.date == "pooled_cmh"].iloc[0]
check("planted gap recovered (excluded worse, p < 0.001)", row.diff_perf_rate < -0.1 and row.p_value < 1e-3,
      f"diff {row.diff_perf_rate:.3f} p {row.p_value:.2e}")
per = res[res.date != "pooled_cmh"]
check("per-date tests agree in sign", (per.diff_perf_rate < 0).all(), str(per.diff_perf_rate.round(3).tolist()))

# 5. no gap
codes0 = np.where(rng.random(n) < 0.2, 550, 100)
dl0 = pd.DataFrame({"permno": perm, "dlstdt": pd.Timestamp("2021-01-01"), "dlstcd": codes0})
tab0 = d6.universe_outcome_table(d6.common_stock_spells(names), included, d6.outcome_by_permno(dl0), dates[:1])
r0 = d6.compare_groups(tab0)
check("no gap: not flagged at 1%", r0[r0.date == "pooled_cmh"].iloc[0].p_value > 0.01,
      f"p {r0[r0.date == 'pooled_cmh'].iloc[0].p_value:.3f}")

# 6. security level: each security once, stratum = decade of first eligible spell
names6 = pd.DataFrame({"permno": [1, 1, 2, 3], "namedt": pd.to_datetime(["1985-01-01", "1992-01-01", "1995-06-01",
                                                                         "1988-01-01"]),
                       "nameenddt": pd.to_datetime(["1991-12-31", "2000-12-31", "2000-12-31", "2000-12-31"]),
                       "shrcd": [10, 10, 11, 10], "exchcd": [1, 1, 3, 2]})
sec = d6.security_level_table(d6.common_stock_spells(names6), {1, 2}, pd.Series({1: "performance"}))
n80 = sec[(sec.date == "1980s")].set_index("group")["n"].to_dict()
n90 = sec[(sec.date == "1990s")].set_index("group")["n"].to_dict()
check("security level: counted once, by first decade", n80 == {"included": 1, "excluded": 1}
      and n90 == {"included": 1, "excluded": 0} and int(sec.n.sum()) == 3, f"{n80} {n90}")

# 7. eligible life sums only eligible spells (both of permno 1's spells are eligible here)
lf = d6.eligible_life_years(d6.common_stock_spells(names6))
check("eligible life years", abs(lf.loc[1] - 16.0) < 0.01 and abs(lf.loc[3] - 13.0) < 0.01, str(lf.round(2).to_dict()))

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
