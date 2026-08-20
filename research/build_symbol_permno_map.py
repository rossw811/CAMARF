"""
research/build_symbol_permno_map.py -- one-time (re-runnable) bridge between
the ticker-keyed WRDS price cache (output/cache/wrds/{TICKER}_1D.parquet)
and CRSP's permno-keyed S&P 500 membership history
(output/cache/wrds/sp500_membership_history.parquet, already fetched and
cached -- NOT re-fetched here).

WHY THIS EXISTS: point-in-time index-membership filtering (2026-08-11,
Ross's direct observation) needs to know, for each symbol the episodic
scanner tests, WHEN it was actually an S&P 500 member -- not just whether
its price history happens to be cached back to some date. CRSP's
`crsp_a_indexes.dsp500list_v2` (already wrapped by
data_wrds.py::fetch_sp500_membership_history/sp500_members_asof) is the
authoritative, multi-spell-aware source for this, but it's keyed by
`permno`, while the price cache is keyed by ticker. The ticker->permno
mapping was only ever built IN-MEMORY during the original data_wrds.py
fetch run and never persisted -- this script derives and caches it
separately, a metadata-only operation (no price data is re-fetched).

REQUIRES a live WRDS connection for the ticker->permno resolution query
(resolve_permnos_bulk, unchanged, reused). Run this manually once (or
whenever the symbol universe changes) via:
    python research/build_symbol_permno_map.py
It will prompt for WRDS credentials interactively the first time, then
call db.create_pgpass_file() so subsequent connections (by this script or
any other data_wrds.py caller) do not need to prompt again.

Symbols already cached under a PERMNOxxxxx_1D.parquet filename (the
existing fallback naming for tickers data_wrds.py's original fetch found
ambiguous/delisted) already carry their own permno directly in the
filename -- no resolution needed for those, handled here without a query.

Output: output/cache/wrds/symbol_permno_map.parquet, columns
[symbol, permno] -- one row per resolved WRDS-cached ticker symbol.
"""
import glob
import logging
import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_wrds import _connect, resolve_permnos_bulk, _OUT_DIR

log = logging.getLogger("build_symbol_permno_map")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")

_MAP_OUT_PATH = os.path.join(_OUT_DIR, "symbol_permno_map.parquet")
_PERMNO_FILENAME_RE = re.compile(r"^PERMNO(\d+)_1D\.parquet$")


def cached_wrds_symbols() -> list:
    """Every symbol with a cached output/cache/wrds/*_1D.parquet file."""
    out = []
    for path in glob.glob(os.path.join(_OUT_DIR, "*_1D.parquet")):
        fname = os.path.basename(path)
        out.append(fname[: -len("_1D.parquet")])
    return out


def main():
    symbols = cached_wrds_symbols()
    log.info(f"{len(symbols)} symbols with cached WRDS daily price data")

    # Symbols already keyed by permno in the filename need no resolution.
    already_permno = {}
    ticker_symbols = []
    for sym in symbols:
        m = _PERMNO_FILENAME_RE.match(f"{sym}_1D.parquet")
        if m:
            already_permno[sym] = int(m.group(1))
        else:
            ticker_symbols.append(sym)
    log.info(f"{len(already_permno)} already permno-keyed by filename, "
             f"{len(ticker_symbols)} need ticker->permno resolution")

    db = _connect()
    if not os.path.exists(os.path.expanduser("~/.pgpass")):
        db.create_pgpass_file()
        log.info("Wrote ~/.pgpass -- future connections will not need interactive credentials")

    permno_by_symbol = dict(already_permno)
    for i in range(0, len(ticker_symbols), 500):
        chunk = ticker_symbols[i:i + 500]
        permno_by_symbol.update(resolve_permnos_bulk(db, chunk))
    n_unresolved = len(symbols) - len(permno_by_symbol)
    log.info(f"Resolved {len(permno_by_symbol)}/{len(symbols)} symbols to permnos "
             f"({n_unresolved} not found -- likely non-CRSP-covered tickers, e.g. international ADRs)")

    out = pd.DataFrame(
        [{"symbol": s, "permno": p} for s, p in permno_by_symbol.items()]
    )
    out.to_parquet(_MAP_OUT_PATH, index=False)
    log.info(f"Saved -> {_MAP_OUT_PATH} ({len(out)} rows)")
    return out


if __name__ == "__main__":
    main()
