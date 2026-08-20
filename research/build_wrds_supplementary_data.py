"""
research/build_wrds_supplementary_data.py -- run-once-yourself (2026-08-11,
Ross: "import all the data possible then build individually").

Fetches two SCOPED, well-established WRDS data sources -- deliberately NOT
"literally every table in every accessible library" (comp alone has 293
tables, ibes 194, audit 388 -- a wholesale dump would be mostly irrelevant
noise and a real license-compliance/storage burden for no analytical gain).
Scoped to what's directly useful for CAMARF's pairs-trading thesis and
buildable with high schema confidence in one pass (avoiding a failed
round-trip that costs another WRDS 2FA login):

1. FAMA-FRENCH FACTORS (`ff` library) -- market-wide, no per-symbol linking
   needed. 3-factor and 5-factor, daily. Directly useful for risk-factor-
   adjusted Sharpe ratios and macro.py-style regime context (already
   flagged as "planned, not yet built" in data_wrds.py's own docstring).
   Output: output/cache/wrds/ff_factors_3_daily.parquet,
   output/cache/wrds/ff_factors_5_daily.parquet.

2. COMPUSTAT FUNDAMENTALS (`comp.funda`, annual) for CAMARF's universe --
   joined via CRSP-Compustat Merged (`crsp_a_ccm.ccmxpf_lnkhist`, the
   STANDARD linking table every WRDS Compustat tutorial uses) against the
   permnos already resolved in output/cache/wrds/symbol_permno_map.parquet
   (built 2026-08-11 for the point-in-time membership gate -- reused
   directly here, not re-resolved). Standard "one record per company per
   fiscal year" filter (indfmt='INDL', datafmt='STD', popsrc='D',
   consol='C' -- the canonical WRDS Compustat convention, not invented
   here). Fields: total assets, revenue, net income, book equity, shares
   outstanding, SIC code -- enough for a first-pass economic-rationale
   check on candidate pairs, not a full fundamentals warehouse.
   Output: output/cache/wrds/compustat_funda_camarf_universe.parquet.

NOT fetched this pass (deferred, not forgotten): IBES analyst estimates
(schema/linking-table confidence lower, would risk a wasted round-trip if
guessed wrong -- a separate, scoped follow-up once this pass's data is
reviewed), TRACE (bond data, tangential to an equity/ETF pairs strategy),
`audit` library (Audit Analytics -- 388 tables, needs its own scoping pass
before fetching anything).

DOES NOT wire this into any production/research pipeline -- per this
project's working-style rule, new data integration is discussed with Ross
before being built into features, not auto-wired the moment it's fetched.

Run: python research/build_wrds_supplementary_data.py
"""
import logging
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_wrds import _connect, _OUT_DIR

log = logging.getLogger("build_wrds_supplementary_data")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")

_PERMNO_MAP_PATH = os.path.join(_OUT_DIR, "symbol_permno_map.parquet")


def fetch_fama_french(db):
    q3 = "select * from ff.factors_daily order by date"
    q5 = "select * from ff.fivefactors_daily order by date"
    df3 = db.raw_sql(q3)
    df5 = db.raw_sql(q5)
    df3.to_parquet(os.path.join(_OUT_DIR, "ff_factors_3_daily.parquet"), index=False)
    df5.to_parquet(os.path.join(_OUT_DIR, "ff_factors_5_daily.parquet"), index=False)
    log.info(f"Fama-French 3-factor daily: {len(df3)} rows, {df3['date'].min()} to {df3['date'].max()}")
    log.info(f"Fama-French 5-factor daily: {len(df5)} rows, {df5['date'].min()} to {df5['date'].max()}")


def fetch_compustat_fundamentals(db):
    if not os.path.exists(_PERMNO_MAP_PATH):
        log.warning(f"{_PERMNO_MAP_PATH} not found -- run research/build_symbol_permno_map.py "
                    f"first. Skipping Compustat fundamentals.")
        return
    permno_map = pd.read_parquet(_PERMNO_MAP_PATH)
    permnos = permno_map["permno"].dropna().astype(int).unique().tolist()
    log.info(f"Fetching Compustat fundamentals for {len(permnos)} permnos (via CRSP-Compustat "
             f"Merged link, standard indfmt/datafmt/popsrc/consol filter)...")

    permnos_sql = ",".join(str(p) for p in permnos)
    # `sic` is NOT a column on comp.funda (found live, 2026-08-11:
    # UndefinedColumn) -- it lives on comp.company, a separate small
    # reference table, fetched here as its own query rather than joined
    # into every funda row (sic classification doesn't change per fiscal
    # year the way funda's financials do).
    q = f"""
        with linked as (
            select gvkey, lpermno as permno, linkdt, linkenddt
            from crsp_a_ccm.ccmxpf_lnkhist
            where lpermno in ({permnos_sql})
              and linktype in ('LU', 'LC')
              and linkprim in ('P', 'C')
        )
        select f.gvkey, l.permno, f.datadate, f.fyear, f.at, f.sale, f.revt, f.ni, f.ceq, f.csho
        from comp.funda f
        join linked l on f.gvkey = l.gvkey
        where f.indfmt = 'INDL' and f.datafmt = 'STD' and f.popsrc = 'D' and f.consol = 'C'
          and f.datadate >= l.linkdt
          and (l.linkenddt is null or f.datadate <= l.linkenddt)
        order by l.permno, f.datadate
    """
    df = db.raw_sql(q)
    df.to_parquet(os.path.join(_OUT_DIR, "compustat_funda_camarf_universe.parquet"), index=False)
    log.info(f"Compustat fundamentals: {len(df)} rows, {df['permno'].nunique()} distinct permnos, "
             f"{df['datadate'].min()} to {df['datadate'].max()}")

    gvkeys = df["gvkey"].dropna().unique().tolist()
    if gvkeys:
        gvkeys_sql = ",".join(f"'{g}'" for g in gvkeys)
        company_q = f"""
            select gvkey, sic, gsector, gind, conm
            from comp.company
            where gvkey in ({gvkeys_sql})
        """
        company_df = db.raw_sql(company_q)
        company_df.to_parquet(os.path.join(_OUT_DIR, "compustat_company_camarf_universe.parquet"), index=False)
        log.info(f"Compustat company reference (SIC/GICS sector): {len(company_df)} companies")


def main():
    db = _connect()
    log.info("=== Fama-French factors ===")
    fetch_fama_french(db)
    log.info("=== Compustat fundamentals (CAMARF universe, CCM-linked) ===")
    fetch_compustat_fundamentals(db)
    db.close()
    log.info("Done. Review the new output/cache/wrds/*.parquet files, then discuss with Claude "
             "which features/comparison arms to build from them.")


if __name__ == "__main__":
    main()
