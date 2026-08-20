"""
research/fundamental_pair_tagger.py -- Thread F Part B of the WRDS
supplementary data integration plan
(C:\\Users\\RossW\\.claude\\plans\\ancient-mixing-feather.md).

Informational tags on confirmed pairs from Compustat fundamentals (already
cached by research/build_wrds_supplementary_data.py, NOT re-fetched here) --
same_gics_sector, a book-equity size-similarity ratio. Mirrors analysis.py's
CrossAssetTagger convention exactly (analysis.py:3644): tags pairs with
structural/economic context as an INFORMATIONAL field, never a gate. Whether
to promote any of this to an actual filter is a separate, later decision
once Ross reviews real tagged output on the (post-BUG-D112-redo) confirmed
pair set -- not decided or applied here.

PIT-SAFETY: Compustat fundamentals have a real-world reporting lag between
fiscal year-end (`datadate`) and public availability -- using a fundamentals
row as if known exactly on `datadate` would be a lookahead bug, the same
class this session already found and fixed twice (BUG-D103 for FRED
monthly-series publication lag in macro.py, BUG-D112 for episodic
candidate-generation). `rdq` (the exact 10-K filing date) was NOT fetched in
this round's comp.funda pull, so this uses a conservative FIXED lag
(_REPORTING_LAG_DAYS, default 90 -- the standard 10-K filing deadline for
most filers) as a disclosed first-pass approximation, not a precise figure.
Fetching the real `rdq` field is a cheap follow-up WRDS query if more
precision is wanted later.

Synthetic verification FIRST: debug/_verify_fundamental_pair_tagger.py --
run that before trusting this script's real-data output.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WRDS_CACHE_DIR = os.path.join(_ROOT, "output", "cache", "wrds")
_PERMNO_MAP_PATH = os.path.join(_WRDS_CACHE_DIR, "symbol_permno_map.parquet")
_FUNDA_PATH = os.path.join(_WRDS_CACHE_DIR, "compustat_funda_camarf_universe.parquet")
_COMPANY_PATH = os.path.join(_WRDS_CACHE_DIR, "compustat_company_camarf_universe.parquet")

_REPORTING_LAG_DAYS = 90


def load_fundamentals_cache():
    """Loads and lightly cleans the three cache files this module needs.
    Returns (permno_by_symbol, funda_df, company_by_gvkey) -- funda_df has
    a real datetime `datadate` and an `available_date` (datadate + reporting
    lag) column added. Returns (None, None, None) if any cache is missing --
    callers must treat this as "tagging unavailable," never "no pairs are
    similar" (same discipline as load_membership_gate's own contract)."""
    if not (os.path.exists(_PERMNO_MAP_PATH) and os.path.exists(_FUNDA_PATH) and os.path.exists(_COMPANY_PATH)):
        return None, None, None
    permno_map = pd.read_parquet(_PERMNO_MAP_PATH)
    permno_by_symbol = dict(zip(permno_map["symbol"], permno_map["permno"]))

    funda = pd.read_parquet(_FUNDA_PATH)
    funda["datadate"] = pd.to_datetime(funda["datadate"])
    funda["available_date"] = funda["datadate"] + pd.Timedelta(days=_REPORTING_LAG_DAYS)
    funda["permno"] = funda["permno"].astype("Int64")

    company = pd.read_parquet(_COMPANY_PATH)
    company_by_gvkey = company.set_index("gvkey")[["sic", "gsector", "gind", "conm"]].to_dict("index")

    return permno_by_symbol, funda, company_by_gvkey


def _latest_available_fundamentals(funda_df: pd.DataFrame, permno: int, as_of_date):
    """Latest fundamentals row for `permno` whose LAGGED available_date is
    <= as_of_date -- the actual PIT-safety enforcement point. A row whose
    available_date is after as_of_date (even if its datadate itself is
    before) must never be returned."""
    as_of = pd.Timestamp(as_of_date)
    rows = funda_df[(funda_df["permno"] == permno) & (funda_df["available_date"] <= as_of)]
    if rows.empty:
        return None
    return rows.sort_values("datadate").iloc[-1]


def tag_fundamental_similarity(sym_a: str, sym_b: str, as_of_date,
                                permno_by_symbol: dict, funda_df: pd.DataFrame,
                                company_by_gvkey: dict) -> dict:
    """Returns a dict: same_gics_sector (bool or None), size_ratio (float in
    (0,1] or None, smaller/larger book equity), plus the actual fundamentals
    dates used for each symbol (auditability). None values mean "not
    determinable" (missing permno resolution, no PIT-eligible fundamentals
    row yet, or non-positive book equity making a ratio meaningless) -- MUST
    be treated as "unknown," never as "not similar."""
    out = {
        "same_gics_sector": None, "size_ratio": None,
        "fundamentals_date_a": None, "fundamentals_date_b": None,
    }
    permno_a = permno_by_symbol.get(sym_a)
    permno_b = permno_by_symbol.get(sym_b)
    if permno_a is None or permno_b is None:
        return out

    row_a = _latest_available_fundamentals(funda_df, int(permno_a), as_of_date)
    row_b = _latest_available_fundamentals(funda_df, int(permno_b), as_of_date)
    if row_a is None or row_b is None:
        return out

    out["fundamentals_date_a"] = row_a["datadate"]
    out["fundamentals_date_b"] = row_b["datadate"]

    comp_a = company_by_gvkey.get(row_a["gvkey"])
    comp_b = company_by_gvkey.get(row_b["gvkey"])
    if comp_a is not None and comp_b is not None:
        out["same_gics_sector"] = comp_a["gsector"] == comp_b["gsector"]

    ceq_a, ceq_b = row_a["ceq"], row_b["ceq"]
    if pd.notna(ceq_a) and pd.notna(ceq_b) and ceq_a > 0 and ceq_b > 0:
        out["size_ratio"] = float(min(ceq_a, ceq_b) / max(ceq_a, ceq_b))

    return out


def main():
    import argparse
    p = argparse.ArgumentParser(description="Tag confirmed pairs with Compustat fundamental similarity")
    p.add_argument("--pairs", required=True, help="pairs.parquet-schema file with symbol_a/symbol_b/as_of_date")
    args = p.parse_args()

    permno_by_symbol, funda_df, company_by_gvkey = load_fundamentals_cache()
    if permno_by_symbol is None:
        print("Fundamentals cache unavailable -- run research/build_wrds_supplementary_data.py first.")
        return

    pairs_df = pd.read_parquet(args.pairs)
    rows = []
    for _, r in pairs_df.iterrows():
        as_of = r.get("as_of_date", pd.Timestamp.now())
        if pd.isna(as_of):
            as_of = pd.Timestamp.now()
        tag = tag_fundamental_similarity(
            r["symbol_a"], r["symbol_b"], as_of, permno_by_symbol, funda_df, company_by_gvkey
        )
        tag["symbol_a"] = r["symbol_a"]
        tag["symbol_b"] = r["symbol_b"]
        rows.append(tag)

    out_df = pd.DataFrame(rows)
    n_tagged = out_df["same_gics_sector"].notna().sum()
    print(f"Tagged {len(out_df)} pairs, {n_tagged} with a determinable GICS-sector match "
          f"({int(out_df['same_gics_sector'].sum())} same-sector)")
    print(out_df.to_string())
    return out_df


if __name__ == "__main__":
    main()
