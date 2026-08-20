"""
research/full_us_market_price_fetch.py -- Thread K Part 1: full daily price
history for CRSP's ENTIRE historical US common-stock universe (2026-08-13,
Ross: "let's make sure we also get the entire US market and all what
assets we're when and where at what time").

Real, precisely-sized scope, not a guess: `output/cache/wrds/crsp_full_
security_master.parquet` (built and verified same session, data_wrds.py::
fetch_full_crsp_security_master) has **29,366 distinct permnos**
(shrcd 10/11/12, exchcd 1/2/3, i.e. common stock on NYSE/AMEX/NASDAQ),
1925-2026 -- about 16x CAMARF's current ~1,700-symbol universe. A real
200-symbol timed sample (fetch_symbols_bulk, same batched-query mechanism
as the rest of data_wrds.py) took 18.0s (0.09s/symbol), extrapolating to
~44 minutes of raw fetch time for the full universe -- a completely
different order of magnitude than the international fetch (which was slow
specifically because of its currency-lookup query pattern, not the bulk
price fetch itself).

LABEL COLLISION HANDLING, a real risk at this scale (checked directly, not
assumed): 29,366 permnos but only 28,509 distinct tickers -- ticker reuse
across different companies over a century is confirmed common (the entire
reason resolve_permno's point-in-time logic exists elsewhere in this
file). Reuses `data_wrds.py::build_delisted_label_map`'s exact collision-
avoidance logic (use last-known ticker, fall back to PERMNO<n> on any
collision), generalized here from its original "delisted vs. already-
fetched-active" scope to cover the FULL universe's own internal ticker
reuse.

Resumable (skip-if-cached), retried with backoff + statement timeout on
connection drops -- same hardened pattern already proven this session for
the international fetch (research/wrds_global_index_universe_fetch.py).

CAN BE RUN BY EITHER Ross or the assistant directly -- non-interactive WRDS
connections now work via an explicit wrds_username (see data_wrds.py::
_connect(), confirmed 2026-08-13), as long as the Duo "remember this
device" trust window from an earlier interactive login is still active.
Not guaranteed permanent.
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from data_wrds import (
    _connect, _OUT_DIR, fetch_full_crsp_security_master, fetch_symbols_bulk,
    build_delisted_label_map,
)

log = logging.getLogger("full_us_market_price_fetch")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
_LOG_FILE_PATH = "latest_run_full_us_market_price_fetch.log"
_fh = logging.FileHandler(_LOG_FILE_PATH, mode="a", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
log.addHandler(_fh)

_STATEMENT_TIMEOUT_MS = 120_000
_MASTER_PATH = os.path.join(_OUT_DIR, "crsp_full_security_master.parquet")
_LABEL_MAP_PATH = os.path.join(_OUT_DIR, "full_us_market_label_map.parquet")


def _connect_with_retry(max_attempts=5, base_delay=30.0):
    """Same pattern as wrds_global_index_universe_fetch.py's own version --
    not imported directly to avoid a cross-script coupling for what's a
    tiny, self-contained helper; kept in sync deliberately by copying the
    same tested logic, not by reference."""
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            db = _connect()
            db.connection.exec_driver_sql(f"SET statement_timeout = {_STATEMENT_TIMEOUT_MS}")
            return db
        except Exception as e:
            last_exc = e
            delay = base_delay * attempt
            log.warning(f"WRDS connect attempt {attempt}/{max_attempts} failed ({e}); "
                        f"retrying in {delay:.0f}s...")
            time.sleep(delay)
    raise RuntimeError(f"Could not connect to WRDS after {max_attempts} attempts") from last_exc


def build_full_market_label_map(master_df: pd.DataFrame) -> dict:
    """Most-recent ticker per permno (one label per permno, not per spell --
    fetch_symbols_bulk pulls a permno's FULL history under one label
    regardless of how many tickers it used over time), collision-checked
    across the WHOLE universe via build_delisted_label_map's exact logic."""
    last_known_raw = (
        master_df.sort_values("namedt").groupby("permno")["ticker"].last().to_dict()
    )
    # ALL permnos, regardless of whether they have a usable ticker -- a
    # null-ticker permno must still get fetched, just under a PERMNO<n>
    # fallback label, not silently dropped from the universe entirely.
    all_permnos = list(last_known_raw.keys())
    # Real bug caught on the actual run (2026-08-13): some CRSP tickers are
    # genuinely None/NaN (not a missing dict key -- a real null value for
    # that permno). build_delisted_label_map's `.get(p, default)` fallback
    # only triggers on a MISSING key, not a present-but-None value, so a
    # None ticker passed straight through and crashed downstream string
    # ops. Second real bug, found immediately after "fixing" the first:
    # `t is not None and pd.notna(t)` behaved INCONSISTENTLY across repeated
    # runs against the same real data (a permno with a null ticker was
    # correctly filtered in isolated tests but NOT in the actual script
    # run, producing a literal NaN dict key) -- pandas' nullable "string"
    # dtype represents missing values as pd.NA, which round-trips
    # unreliably through dict conversion / parquet reads (sometimes surfaces
    # as pd.NA, sometimes as plain None, sometimes as float NaN, depending
    # on the exact code path). Rather than keep chasing which NA sentinel
    # applies where, use a STRICT type check instead -- only a genuine `str`
    # instance counts as a usable ticker, sidestepping the whole ambiguity.
    last_known = {p: t for p, t in last_known_raw.items() if isinstance(t, str) and t}
    # build_delisted_label_map's signature expects `active_ticker_labels` as
    # the "already spoken for" set to check collisions against -- empty here
    # since we're building the label map for the WHOLE universe at once, not
    # layering delisted names on top of an already-fetched active set.
    return build_delisted_label_map(all_permnos, last_known, active_ticker_labels=set())


def main():
    os.makedirs(_OUT_DIR, exist_ok=True)
    if not os.path.exists(_MASTER_PATH):
        db0 = _connect_with_retry()
        master_df = fetch_full_crsp_security_master(db0)
        db0.close()
    else:
        master_df = pd.read_parquet(_MASTER_PATH)
    log.info(f"Security master: {master_df['permno'].nunique()} distinct permnos")

    if os.path.exists(_LABEL_MAP_PATH):
        label_map_df = pd.read_parquet(_LABEL_MAP_PATH)
        label_by_permno = dict(zip(label_map_df["label"], label_map_df["permno"]))
    else:
        label_by_permno = build_full_market_label_map(master_df)
        pd.DataFrame(
            [{"label": k, "permno": v} for k, v in label_by_permno.items()]
        ).to_parquet(_LABEL_MAP_PATH, index=False)
    n_relabeled = sum(1 for lbl in label_by_permno if lbl.startswith("PERMNO"))
    log.info(f"{len(label_by_permno)} labels built, {n_relabeled} collision-relabeled as PERMNO<n>")

    already_cached = {
        lbl for lbl in label_by_permno
        if os.path.exists(os.path.join(_OUT_DIR, f"{lbl}_1D.parquet"))
    }
    to_fetch = {lbl: p for lbl, p in label_by_permno.items() if lbl not in already_cached}
    log.info(f"{len(already_cached)}/{len(label_by_permno)} already cached (resuming), "
             f"{len(to_fetch)} remaining.")

    t0 = time.time()
    n_fetched_total = 0
    attempt = 0
    max_retries = 20
    db = _connect_with_retry()
    while to_fetch:
        try:
            n_this_attempt = 0
            for label, df in fetch_symbols_bulk(db, to_fetch, batch_size=200):
                df.to_parquet(os.path.join(_OUT_DIR, f"{label}_1D.parquet"))
                n_fetched_total += 1
                n_this_attempt += 1
                if n_fetched_total % 1000 == 0:
                    elapsed = (time.time() - t0) / 60
                    log.info(f"  progress: {n_fetched_total} fetched this session ({elapsed:.1f} min)")
            break  # generator exhausted cleanly
        except Exception as e:
            attempt += 1
            log.warning(f"Fetch interrupted after {n_this_attempt} symbols this attempt ({e}). "
                        f"Reconnecting (attempt {attempt}/{max_retries})...")
            if attempt >= max_retries:
                log.error(f"Giving up after {attempt} interrupted attempts.")
                raise
            time.sleep(min(300.0, 30.0 * attempt))
            db = _connect_with_retry()
            to_fetch = {
                lbl: p for lbl, p in label_by_permno.items()
                if not os.path.exists(os.path.join(_OUT_DIR, f"{lbl}_1D.parquet"))
            }

    log.info(f"Full US market price fetch complete: {n_fetched_total} symbols this session, "
             f"{(time.time()-t0)/60:.1f} min total.")


if __name__ == "__main__":
    main()
