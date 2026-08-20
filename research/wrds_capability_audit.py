"""
research/wrds_capability_audit.py -- one-shot, run-once-yourself script
(2026-08-11, Ross: "let's also integrate the other useful data from WRDS...
do a check on everything WRDS can provide me").

Requires a live, INTERACTIVE WRDS connection (2FA/Duo per session, confirmed
live this session -- pgpass alone is not enough to skip the prompt). Run
this yourself in your own terminal:
    python research/wrds_capability_audit.py

Does TWO things, both READ-ONLY metadata operations (no bulk price data
fetched, license-compliant -- see data_wrds.py's own header comment):

1. FULL LIBRARY/TABLE AUDIT: lists every library and table this WRDS
   subscription can actually access (db.list_libraries()/list_tables()),
   saved to output/cache/wrds/wrds_capability_audit.json -- a real,
   subscription-specific inventory, not a guess from WRDS's general public
   documentation. This directly answers "what can Baruch's subscription
   actually provide" instead of assuming.

2. S&P 400/600 POINT-IN-TIME MEMBERSHIP: extends the S&P-500-only
   membership gate (2026-08-11, wrds_deep_history_episodic_scan.py) to the
   REST of CAMARF's S&P Composite 1500 universe. Looks up the gvkeyx codes
   for S&P MidCap 400 / SmallCap 600 in Compustat Global's index-name
   table, then calls data_wrds.fetch_index_membership_history_global
   (already built, unchanged, gvkeyx-parameterized) for each -- same
   pattern already proven for Nikkei 225/DAX/Topix in that function's own
   docstring, just pointed at two new gvkeyx codes. Output:
   output/cache/wrds/index_membership_sp400.parquet,
   output/cache/wrds/index_membership_sp600.parquet.

Nothing here modifies wrds_deep_history_episodic_scan.py's own membership
gate wiring -- that still only consumes the S&P 500 table
(load_membership_gate) until Ross reviews this audit's findings and
decides whether/how to extend it, per this project's own working-style
rule (new data-source integration is discussed before it's wired into the
production/research pipeline, not silently expanded).
"""
import json
import logging
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_wrds import _connect, fetch_index_membership_history_global, _OUT_DIR

log = logging.getLogger("wrds_capability_audit")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")

_AUDIT_OUT_PATH = os.path.join(_OUT_DIR, "wrds_capability_audit.json")


def audit_libraries(db) -> dict:
    log.info("Listing accessible libraries (this may take a minute)...")
    libraries = db.list_libraries()
    log.info(f"{len(libraries)} libraries accessible under this subscription")
    result = {}
    # Only inventory libraries plausibly relevant to CAMARF's thesis --
    # a FULL table listing for all ~200+ WRDS libraries would be noisy and
    # slow; these are the ones worth knowing about concretely.
    of_interest = [
        "crsp_a_stock", "crsp_a_indexes", "comp_global_daily", "comp_global",
        "comp", "compa", "compna", "optionm_all", "optionm", "ff", "ff_all",
        "frb_all", "ibes", "taqmsec", "trace", "audit",
    ]
    for lib in of_interest:
        if lib not in libraries:
            result[lib] = None
            continue
        try:
            tables = db.list_tables(library=lib)
            result[lib] = tables
            log.info(f"  {lib}: {len(tables)} tables")
        except Exception as e:
            result[lib] = f"ERROR: {e}"
            log.warning(f"  {lib}: could not list tables ({e})")
    return {"all_libraries": libraries, "tables_of_interest": result}


def find_gvkeyx(db, name_fragment: str) -> pd.DataFrame:
    # `%` must be escaped as `%%` -- psycopg2's paramstyle treats a bare `%`
    # in the SQL string as a parameter placeholder (found live, 2026-08-11:
    # "immutabledict is not a sequence" -- an opaque SQLAlchemy error for
    # what is actually an unescaped LIKE wildcard, same class of gotcha as
    # BUG-D50's $-in-URL issue, just a different driver/special character).
    q = f"""
        select gvkeyx, conm
        from comp_global_daily.g_idx_index
        where lower(conm) like lower('%%{name_fragment}%%')
    """
    return db.raw_sql(q)


def main():
    db = _connect()

    if os.path.exists(_AUDIT_OUT_PATH):
        log.info(f"{_AUDIT_OUT_PATH} already exists -- skipping the library/table audit "
                 f"(delete the file first if you want it re-run).")
    else:
        audit = audit_libraries(db)
        os.makedirs(_OUT_DIR, exist_ok=True)
        with open(_AUDIT_OUT_PATH, "w") as f:
            json.dump(audit, f, indent=2, default=str)
        log.info(f"Saved library/table audit -> {_AUDIT_OUT_PATH}")

    for label, fragment in [("S&P MidCap 400", "S&P MidCap 400"), ("S&P SmallCap 600", "S&P SmallCap 600")]:
        log.info(f"Looking up gvkeyx for '{label}'...")
        matches = find_gvkeyx(db, fragment)
        if matches.empty:
            log.warning(f"No gvkeyx match found for '{label}' -- trying a looser search...")
            matches = find_gvkeyx(db, fragment.split()[1])  # e.g. "MidCap" alone
        if matches.empty:
            log.warning(f"Still no match for '{label}' -- skipping. Check "
                        f"comp_global_daily.g_idx_index manually.")
            continue
        log.info(f"  Matches: {matches.to_dict('records')}")
        gvkeyx = str(matches.iloc[0]["gvkeyx"])
        cache_label = "sp400" if "400" in label else "sp600"
        df = fetch_index_membership_history_global(db, gvkeyx, cache_label)
        if not df.empty:
            log.info(f"  {label} (gvkeyx={gvkeyx}): {len(df)} membership spells cached")

    db.close()
    log.info("Done. Review output/cache/wrds/wrds_capability_audit.json and the "
             "index_membership_sp{400,600}.parquet files, then discuss with Claude "
             "which integrations are worth wiring into the pipeline.")


if __name__ == "__main__":
    main()
