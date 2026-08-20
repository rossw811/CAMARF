"""
research/build_wrds_supplementary_data.py -- thin CLI wrapper. The actual
fetch logic (fetch_fama_french, fetch_compustat_fundamentals) was
consolidated into data_wrds.py on 2026-08-20 (Thread O software
optimization audit) per that file's own scope statement ("ALL WRDS data
sources live in this ONE file, one file per external PROVIDER"). This file
is kept as the documented, runnable entry point -- see data_wrds.py's
own docstrings on those two functions for the full scoping rationale (why
these two sources, why NOT a wholesale dump of every comp/ibes/audit
table, the standard CCM-link/indfmt-datafmt-popsrc-consol filter
convention).

DOES NOT wire this into any production/research pipeline -- per this
project's working-style rule, new data integration is discussed with Ross
before being built into features, not auto-wired the moment it's fetched.

Run: python research/build_wrds_supplementary_data.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_wrds import _connect, fetch_fama_french, fetch_compustat_fundamentals

log = logging.getLogger("build_wrds_supplementary_data")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")


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
