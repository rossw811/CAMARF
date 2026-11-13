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


def permno_labels(src: str, permno_of: dict = None) -> dict:
    """{permno: sorted 1D file labels} from the BUG-D117 content-verified map (data_wrds.label_permno_map), the only map
    every consumer may use; the keys are the PERMNOs that "have a file". 2026-11-13: P2 scripts had read
    full_us_market_label_map, which names the wrong security for some files -- e.g. the 'BRK' file holds Berkshire B, so
    BRK.A (17778) and BRK.B (83443) read the SAME series and their 'spread' was exactly constant (five such pairs, plus
    three whose leg has no verified file; all eight leave the family)."""
    import os
    from data_wrds import label_permno_map
    permno_of = label_permno_map() if permno_of is None else permno_of
    by_p = {}
    for lab, p in permno_of.items():
        if os.path.exists(os.path.join(src, f"{lab}_1D.parquet")):
            by_p.setdefault(int(p), []).append(str(lab))
    return {p: sorted(v) for p, v in by_p.items()}


def leg_label(src: str, labels: list) -> str:
    """One file label for a PERMNO. Several labels are accepted only if every file holds the identical total-return
    series (then the first is used); otherwise it raises -- never a silent pick."""
    import os
    import numpy as np
    import parquet_io
    if len(labels) > 1:
        s = [parquet_io.read_parquet(os.path.join(src, f"{l}_1D.parquet"))["close_total_return"] for l in labels]
        if not all(x.index.equals(s[0].index) and np.allclose(x.to_numpy(float), s[0].to_numpy(float), equal_nan=True)
                   for x in s[1:]):
            raise ValueError(f"one PERMNO, {len(labels)} different files {labels}; resolve before use")
    return labels[0]


def adv_gated(family: dict, adv_by_permno: dict, threshold: float) -> dict:
    """The tradeable (headline) family: keep a year-y pair only if BOTH legs' trailing ADV on Dec 31 of y (adv_at:
    the last row at or before T, NaN across a data gap) is >= `threshold` (the discovery gate,
    Config.STATS.ADV_FILTER_USD). Point-in-time: rolling_adv is trailing. Moved here from
    debug/_tmp_p2_adv_gate_*.py (review 2026-11-13: the headline family came from a debug script with no test)."""
    from rolling_adv_comparison import adv_at
    out = {}
    for y, prs in family.items():
        T = pd.Timestamp(f"{int(y)}-12-31")
        out[y] = [pr for pr in prs if all(adv_at(adv_by_permno.get(p), T) >= threshold for p in pr)]
    return out


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
