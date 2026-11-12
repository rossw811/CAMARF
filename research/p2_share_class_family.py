"""
research/p2_share_class_family.py -- P2 positive-control family, sub-family 1: share classes of one company
(Ross 2026-11-12: "I'll take your recommendations" -- fixed-hedge family first, as a positive control).

Two share classes of one company (same CRSP PERMCO) carry claims on one set of cash flows, so their log-price difference
should be stationary up to class-specific features (votes, dividend differences, liquidity). If the yearly fixed-hedge
test (research/yearly_family_test.py, test="fixed_adf") plus next-year trading cannot find these, the pipeline cannot
find a relation that is there; if it can, the nulls elsewhere mean more. Positive control, not a headline.

Point-in-time family at each decision date T (normally a year-end), from the CRSP name history only:
  - both securities are common shares (SHRCD 10 or 11) on a name row covering T (namedt <= T <= nameenddt);
  - same PERMCO on those rows;
  - each security's first CRSP name date is >= `min_listed_years` before T;
  - each has a WRDS daily file (the caller passes the PERMNOs that do).
No price, return or test result is read, so membership cannot depend on whether the pair mean-reverted.
Disclosed: (1) the CRSP name snapshot in the cache ends 2024-12-31, so the 2025 family cannot be formed from it as is;
(2) the liquidity gate (rolling ADV) is applied after this step, by the caller, with the discovery gate's function;
(3) class-specific dividends make a total-return log spread drift by the dividend difference -- part of what the test
must tolerate, reported per pair.
Verify: debug/_verify_p2_share_class_family.py
"""
import itertools

import pandas as pd

COMMON_SHRCD = (10, 11)
MIN_LISTED_YEARS = 2


def share_class_family(names: pd.DataFrame, have_permnos, T, min_listed_years: int = MIN_LISTED_YEARS) -> list:
    """`names`: CRSP stocknames rows (permno, permco, namedt, nameenddt, shrcd). Returns sorted [(permno_a, permno_b)]
    with permno_a < permno_b, every same-PERMCO pair of common-share securities active at T."""
    T = pd.Timestamp(T)
    n = names.copy()
    n["namedt"] = pd.to_datetime(n["namedt"])
    n["nameenddt"] = pd.to_datetime(n["nameenddt"])
    n = n[n["namedt"] <= T]                                   # nothing dated after the decision date
    first = n.groupby("permno")["namedt"].min()
    act = n[(n["nameenddt"] >= T) & n["shrcd"].isin(COMMON_SHRCD)].drop_duplicates("permno")
    have = set(int(p) for p in have_permnos)
    act = act[act["permno"].astype(int).isin(have)]
    act = act[act["permno"].map(first) <= T - pd.DateOffset(years=min_listed_years)]
    out = []
    for _, g in act.groupby("permco"):
        out += [tuple(sorted(map(int, p))) for p in itertools.combinations(g["permno"], 2)]
    return sorted(out)


def family_by_year(names: pd.DataFrame, have_permnos, years, min_listed_years: int = MIN_LISTED_YEARS) -> dict:
    """{year: pairs} with each year's family decided at that year's Dec 31 (the yearly test's decision date)."""
    return {int(y): share_class_family(names, have_permnos, f"{int(y)}-12-31", min_listed_years) for y in years}


CLASSIFICATION_CSV = "research/p2_share_class_classification.csv"


def apply_classification(family: dict, cls: pd.DataFrame) -> tuple:
    """Keep a pair in year y only if it is declared same-claim from that year (`same_claim_from_year` <= y).
    Tracking stocks (two different businesses under one PERMCO) and years with a charter difference in economics are
    dropped. FAIL-CLOSED: a pair with no row in `cls` is dropped and returned in `unclassified`, never kept silently.
    The classification comes from charters / filings (research/p2_share_class_classification.csv, sources per row,
    2026-11-12), never from prices. Returns (kept {year: pairs}, unclassified {year: pairs})."""
    key = {(int(min(a, b)), int(max(a, b))): r for a, b, r in
           zip(cls["permno_a"], cls["permno_b"], pd.to_numeric(cls["same_claim_from_year"], errors="coerce"))}
    kept, unclassified = {}, {}
    for y, prs in family.items():
        kept[y] = [p for p in prs if p in key and pd.notna(key[p]) and key[p] <= y]
        unclassified[y] = [p for p in prs if p not in key]
    return kept, unclassified
