"""
research/wrds_global_index_universe_fetch.py -- fetch ALL populated Compustat
Global national/index constituents' full historical OHLCV, per Ross's direct
request (2026-08-12): "i want all of them - then we run a test to see which
tickers have actually liquid values and then use those."

MUST BE RUN BY ROSS, NOT CLAUDE: WRDS requires interactive Duo 2FA
authentication with no headless/scripted workaround (established this
session). Run this directly in your own terminal:

    C:\\Users\\RossW\\anaconda3\\envs\\trading\\python.exe research/wrds_global_index_universe_fetch.py

This is the EXECUTION half of the capability a prior session (2026-07-27)
already built and verified (`data_wrds.py::fetch_index_membership_history_
global`, `fetch_symbols_bulk_global` -- see Development.md's "Global/national
index point-in-time membership" entry). That session inventoried ~40
countries' worth of POPULATED national/global indices but explicitly left
"which ones to actually fetch" as an open decision -- this script picks
"all of them" (Ross's answer) and executes it.

Scope, stated precisely:
  - "Populated" means real rows in comp_global_daily.g_idxcst_his, not just
    a definition in g_idx_index -- checked directly, since a prior session
    found definitions like FTSE 100/CAC 40 that are defined but have ZERO
    constituent rows (see docstring in fetch_index_membership_history_global).
  - FULL HISTORICAL membership per index (not just current constituents) --
    matches this project's own anti-survivorship-bias principle (CLAUDE.md
    rule 6): a delisted/departed constituent's price history is still real
    data, not noise to discard.
  - A symbol appearing in multiple indices is fetched ONCE (deduped by
    (gvkey, iid)), with a manifest recording every index it belongs to.
  - Resumable: skips (gvkey, iid) pairs whose output/cache/wrds/{label}_1D.
    parquet already exists -- safe to stop and restart across a multi-day run.
  - Split-adjusted only (Compustat Global's own disclosed limitation, see
    fetch_symbol_global's docstring -- dividend/total-return adjustment via
    `trfd` remains unverified, not attempted here either).

This does NOT run the liquidity filter -- see research/international_
liquidity_filter.py for step 2 (also Ross-run, needs a fresh WRDS query for
each symbol's currency code).
"""
import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from data_wrds import (
    _connect, _OUT_DIR, fetch_index_membership_history_global,
    fetch_symbols_bulk_global, build_global_symbol_label,
)

log = logging.getLogger("wrds_global_index_universe_fetch")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")

_MANIFEST_PATH = os.path.join(_OUT_DIR, "global_universe_manifest.parquet")
_MIN_CONSTITUENTS = 20  # discovery threshold -- matches the 2026-07-27 inventory's own
                        # "genuinely usable" bar (FTSE 100/CAC 40 at 0 constituents were
                        # the motivating counterexample this threshold rules out)


def discover_populated_indices(db, min_constituents: int = _MIN_CONSTITUENTS) -> pd.DataFrame:
    """
    Real query, not a hardcoded list -- re-derives the 2026-07-27 inventory
    fresh each run (WRDS coverage can be added to over time; a hardcoded
    gvkeyx list would silently go stale). Joins g_idxcst_his (actual
    constituent rows) to g_idx_index (index name) so a definition with zero
    real rows never appears in the result.

    Column-name self-healing: this project has no prior verified reference
    for g_idx_index's exact schema (a prior session's inventory pass never
    recorded its literal SQL, only prose findings), and a guessed country
    column (`i.loc`) failed against the real table (UndefinedColumn). Rather
    than guess a second time, this queries information_schema.columns FIRST
    to get the real column list, logs it (so it's on record for next time),
    then builds the query only from confirmed-real columns -- `gvkeyx` is
    guaranteed (it's the join key that already worked), `conm` is checked
    for and used if present (matches the company-name convention already
    verified elsewhere in this file for g_company), any country-like column
    is included opportunistically if one exists, never assumed by a fixed
    name.
    """
    cols_df = db.raw_sql("""
        select column_name from information_schema.columns
        where table_schema = 'comp_global_daily' and table_name = 'g_idx_index'
        order by ordinal_position
    """)
    real_cols = set(cols_df["column_name"])
    log.info(f"g_idx_index real columns (introspected, not guessed): {sorted(real_cols)}")

    name_col = "conm" if "conm" in real_cols else None
    country_candidates = [c for c in ("loc", "country", "iso", "isocur", "region") if c in real_cols]
    country_col = country_candidates[0] if country_candidates else None

    select_extra = []
    group_extra = []
    if name_col:
        select_extra.append(f"i.{name_col} as conm")
        group_extra.append(f"i.{name_col}")
    if country_col:
        select_extra.append(f"i.{country_col} as country")
        group_extra.append(f"i.{country_col}")
    select_clause = ", ".join(["h.gvkeyx"] + select_extra)
    group_clause = ", ".join(["h.gvkeyx"] + group_extra)

    q = f"""
        select {select_clause},
               count(distinct (h.gvkey, h.iid)) as n_constituents
        from comp_global_daily.g_idxcst_his h
        join comp_global_daily.g_idx_index i on h.gvkeyx = i.gvkeyx
        group by {group_clause}
        having count(distinct (h.gvkey, h.iid)) >= %(min_c)s
        order by n_constituents desc
    """
    df = db.raw_sql(q, params={"min_c": min_constituents})
    if "conm" not in df.columns:
        df["conm"] = "gvkeyx_" + df["gvkeyx"].astype(str)  # fallback display label if no name column found
    log.info(f"Discovered {len(df)} populated global indices with >= {min_constituents} "
             f"constituents each (total distinct constituents may overlap across indices).")
    return df


_STATEMENT_TIMEOUT_MS = 120_000  # 2 minutes -- see docstring below


def _connect_with_retry(max_attempts: int = 5, base_delay: float = 30.0):
    """WRDS's server dropped the connection mid-fetch on a real run (2026-08-12,
    'server closed the connection unexpectedly' after ~2200 symbols) and the
    very next immediate reconnect attempt ALSO failed ('SSL connection has
    been closed unexpectedly') -- a transient server-side issue, not
    something a code fix on this end can prevent, but retrying with backoff
    instead of dying on the first attempt is a real, warranted fix.

    Sets a server-side `statement_timeout` (2026-08-13, after a real run hung
    for 8+ hours with near-zero CPU accumulation -- a raw network/query stall
    never raises an exception on its own, so exception-based retry logic
    never gets a chance to catch it; a hard statement timeout forces the
    server to kill the query and return an error instead, which retry logic
    CAN catch). Applied once per connection, immediately after connecting."""
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            db = _connect()
            # NOT db.raw_sql() -- that wraps pd.read_sql_query(), which requires
            # a result set with rows. A `SET` command returns none, so raw_sql()
            # threw "This result object does not return rows" on the real run
            # (2026-08-13). Use the underlying SQLAlchemy connection's own
            # exec_driver_sql directly instead -- the same method wrds.Connection
            # itself uses internally for non-pandas execution.
            db.connection.exec_driver_sql(f"SET statement_timeout = {_STATEMENT_TIMEOUT_MS}")
            return db
        except Exception as e:
            last_exc = e
            delay = base_delay * attempt
            log.warning(f"WRDS connect attempt {attempt}/{max_attempts} failed ({e}); "
                        f"retrying in {delay:.0f}s...")
            time.sleep(delay)
    raise RuntimeError(f"Could not connect to WRDS after {max_attempts} attempts") from last_exc


def discover_and_build_manifest(db, min_constituents: int):
    """Discovery + membership union + manifest write -- cheap (~6s observed
    for the real run), safe to redo on every retry attempt rather than trying
    to persist/resume this specific step separately."""
    indices_df = discover_populated_indices(db, min_constituents)
    print(indices_df.to_string(index=False))

    label_by_pair = {}
    index_membership_by_pair = {}
    for _, row in indices_df.iterrows():
        gvkeyx, conm = row["gvkeyx"], row["conm"]
        cache_label = f"gvkeyx{gvkeyx}"
        mem_df = fetch_index_membership_history_global(db, gvkeyx, cache_label)
        if mem_df.empty:
            continue
        for gvkey, iid in mem_df[["gvkey", "iid"]].drop_duplicates().itertuples(index=False):
            pair = (gvkey, iid)
            label_by_pair.setdefault(pair, build_global_symbol_label(gvkey, iid))
            index_membership_by_pair.setdefault(pair, set()).add(conm)

    n_total_pairs = len(label_by_pair)
    log.info(f"Union across {len(indices_df)} indices: {n_total_pairs} distinct (gvkey, iid) "
             f"constituents to fetch (deduped across index overlap).")

    manifest_rows = [
        {"label": label_by_pair[pair], "gvkey": pair[0], "iid": pair[1],
         "indices": ";".join(sorted(idx_names)), "n_indices": len(idx_names)}
        for pair, idx_names in index_membership_by_pair.items()
    ]
    manifest_df = pd.DataFrame(manifest_rows)
    manifest_df.to_parquet(_MANIFEST_PATH, index=False)
    log.info(f"Manifest saved -> {_MANIFEST_PATH} ({len(manifest_df)} symbols)")
    return label_by_pair


def main():
    p = argparse.ArgumentParser(description="Fetch ALL populated Compustat Global index constituents")
    p.add_argument("--min-constituents", type=int, default=_MIN_CONSTITUENTS)
    p.add_argument("--start", default=None, help="History start date (default: full available)")
    p.add_argument("--batch-size", type=int, default=200)
    p.add_argument("--dry-run", action="store_true", help="Discover + resolve, fetch nothing")
    p.add_argument("--max-retries", type=int, default=20,
                    help="Max reconnect-and-resume attempts across the whole run (default: 20 -- "
                         "a multi-hour fetch across thousands of symbols should survive several "
                         "transient WRDS connection drops without dying).")
    args = p.parse_args()

    os.makedirs(_OUT_DIR, exist_ok=True)

    db = _connect_with_retry()
    label_by_pair = discover_and_build_manifest(db, args.min_constituents)
    n_total_pairs = len(label_by_pair)

    if args.dry_run:
        log.info("--dry-run: stopping before any price fetch.")
        return

    t0 = time.time()
    n_fetched_total = 0
    attempt = 0
    while True:
        already_cached = {
            pair for pair, label in label_by_pair.items()
            if os.path.exists(os.path.join(_OUT_DIR, f"{label}_1D.parquet"))
        }
        to_fetch = {label_by_pair[pair]: pair for pair in label_by_pair if pair not in already_cached}
        log.info(f"{len(already_cached)}/{n_total_pairs} cached so far, {len(to_fetch)} remaining "
                 f"(attempt {attempt + 1}/{args.max_retries}).")
        if not to_fetch:
            log.info(f"Fetch complete: all {n_total_pairs} symbols cached, "
                      f"{(time.time()-t0)/60:.1f} min total this session.")
            return

        try:
            n_fetched_this_attempt = 0
            for label, df in fetch_symbols_bulk_global(db, to_fetch, start=args.start,
                                                          batch_size=args.batch_size):
                df.to_parquet(os.path.join(_OUT_DIR, f"{label}_1D.parquet"))
                n_fetched_total += 1
                n_fetched_this_attempt += 1
                if n_fetched_total % 200 == 0:
                    elapsed = time.time() - t0
                    log.info(f"  progress: {n_fetched_total} fetched this session "
                              f"({elapsed/60:.1f} min elapsed)")
            # Generator exhausted with no exception -- genuinely done (the
            # while-loop's top will confirm via the already_cached recheck).
        except Exception as e:
            attempt += 1
            log.warning(f"Fetch attempt interrupted after {n_fetched_this_attempt} symbols this "
                        f"attempt ({e}). Already-fetched symbols are safely cached on disk "
                        f"(written before this exception, per the per-batch persistence design) -- "
                        f"only the batch in flight when this happened is lost, will be re-fetched.")
            if attempt >= args.max_retries:
                log.error(f"Giving up after {attempt} interrupted attempts -- "
                          f"{n_fetched_total} symbols fetched this session, "
                          f"{len(already_cached) + n_fetched_this_attempt}/{n_total_pairs} total cached. "
                          f"Rerun this script to resume from here.")
                raise
            delay = min(300.0, 30.0 * attempt)
            log.info(f"Reconnecting in {delay:.0f}s (attempt {attempt}/{args.max_retries})...")
            time.sleep(delay)
            db = _connect_with_retry()


if __name__ == "__main__":
    main()
