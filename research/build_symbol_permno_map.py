"""
research/build_symbol_permno_map.py -- thin CLI wrapper. The actual logic
(cached_wrds_symbols, build_symbol_permno_map) was consolidated into
data_wrds.py on 2026-08-20 (Thread O software optimization audit) per that
file's own scope statement ("ALL WRDS data sources live in this ONE file,
one file per external PROVIDER"). This file is kept as the documented,
runnable entry point -- see data_wrds.py::build_symbol_permno_map for the
full docstring (why this exists, PIT-membership motivation, output schema).

REQUIRES a live WRDS connection for the ticker->permno resolution query.
Run manually via:
    python research/build_symbol_permno_map.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_wrds import build_symbol_permno_map

log = logging.getLogger("build_symbol_permno_map")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")


def main():
    return build_symbol_permno_map()


if __name__ == "__main__":
    main()
