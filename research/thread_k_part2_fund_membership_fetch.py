"""
research/thread_k_part2_fund_membership_fetch.py -- Thread K Part 2: fund-
membership fetch, run against Thread K Part 1's full US market universe
(29,366 symbols, `output/cache/wrds/full_us_market_label_map.parquet`),
satisfying Ross's "run thread K after the international liquidity sweep
finishes - includes finishing the US assets" (2026-08-14).

SCOPE CORRECTION made while building this: the international universe is
explicitly OUT of scope for this fetch, not silently included -- 13F filings
are a US-securities-specific SEC requirement, and Thread I's international
liquid universe uses synthetic Compustat Global (GVKEY) labels that could
never match tr_13f.s34's real ticker column regardless. See
build_combined_universe()'s own docstring for the full reasoning.

Real table check done live (2026-08-14): `tr_13f.s34` (Thomson Reuters 13F
institutional holdings, 127M rows, 1980-2025) has a direct `ticker` column
(no CUSIP crosswalk needed) plus `rdate` (report/as-of date -- the genuine
point-in-time quarter), `mgrno`/`mgrname` (the holding institution), `shares`.

DESIGN -- point-in-time "what/when/where/how-long" spell-based, per Ross's
original request: for each (ticker, rdate) quarter, aggregate total
institutional shares held and DISTINCT MANAGER COUNT (a degree measure,
mirroring Thread J's own strong/moderate/weak strength-gradation approach
rather than a blunt binary "in a fund y/n" split -- more managers holding a
name is a real, continuous signal of fund-driven demand, not just a
threshold). shrout1 (shares outstanding) is present but mostly NULL in this
table for older/smaller names -- reported as-is, not backfilled from another
source this pass (a disclosed limitation, not silently patched).

Real, timed cost (2026-08-14): a 190-ticker batched IN-clause query completed
in 12.5s (0.066s/ticker) -- ~35 minutes extrapolated for the full ~32,296-
symbol combined universe. Resumable (per-batch checkpointing) + retry-
hardened, same pattern established for every other long WRDS fetch this
session.
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from data_wrds import _connect, _OUT_DIR

log = logging.getLogger("thread_k_part2_fund_membership_fetch")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
_LOG_FILE_PATH = "latest_run_thread_k_part2_fund_membership_fetch.log"
_fh = logging.FileHandler(_LOG_FILE_PATH, mode="a", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
log.addHandler(_fh)

_STATEMENT_TIMEOUT_MS = 120_000
_OUT_PATH = os.path.join("output", "research", "fund_membership_history.parquet")
_CHECKPOINT_DIR = os.path.join("output", "research", "fund_membership_checkpoints")
_BATCH_SIZE = 190  # matches the real-timed sample above


def _connect_with_retry(max_attempts=5, base_delay=30.0):
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


def build_combined_universe() -> list:
    """US-ONLY, not a combined US+international universe -- corrected scope,
    found while building this (2026-08-14): Thread I's international liquid
    universe uses synthetic `GVKEYxxxxxx_yyW` labels (Compustat Global
    identifiers), not real ticker strings that could ever match tr_13f.s34's
    `ticker` column. More fundamentally, 13F filings are an SEC requirement
    for US-registered equity securities specifically -- international
    (non-US-listed) names structurally don't appear in this table at all,
    real ticker match or not. Ross's original "includes finishing the US
    assets" instruction is satisfied by Thread K Part 1's full US market
    alone; the international universe's own fund-membership question (if
    wanted later) would need a DIFFERENT data source entirely, not tr_13f --
    out of scope for this fetch, not silently attempted and producing
    guaranteed-empty results for ~2,930 wasted query slots."""
    us_map = pd.read_parquet(os.path.join(_OUT_DIR, "full_us_market_label_map.parquet"))
    # Excludes PERMNO<n> collision-fallback labels -- tr_13f is ticker-keyed,
    # a synthetic PERMNO<n> label can never match a real 13F filing.
    us_tickers = [l for l in us_map["label"] if not str(l).startswith("PERMNO")]
    return sorted(set(us_tickers))


def fetch_batch(db, tickers: list) -> pd.DataFrame:
    tickers_sql = ",".join(f"'{t}'" for t in tickers if "'" not in t)
    q = f"""
        select rdate, ticker, sum(shares) as total_inst_shares,
               count(distinct mgrno) as n_managers, max(shrout1) as shrout1
        from tr_13f.s34
        where ticker in ({tickers_sql})
        group by rdate, ticker
    """
    return db.raw_sql(q)


def main():
    os.makedirs(_CHECKPOINT_DIR, exist_ok=True)
    universe = build_combined_universe()
    log.info(f"US universe: {len(universe)} tickers (Thread K Part 1's full US market only -- "
             f"international excluded, see build_combined_universe()'s docstring)")

    batches = [universe[i:i + _BATCH_SIZE] for i in range(0, len(universe), _BATCH_SIZE)]
    already_done = {
        int(f.split("_")[1].split(".")[0])
        for f in os.listdir(_CHECKPOINT_DIR) if f.startswith("batch_")
    }
    log.info(f"{len(already_done)}/{len(batches)} batches already checkpointed (resuming)")

    db = _connect_with_retry()
    t0 = time.time()
    n_fetched = 0
    for i, batch in enumerate(batches):
        if i in already_done:
            continue
        attempt = 0
        while True:
            try:
                df = fetch_batch(db, batch)
                break
            except Exception as e:
                attempt += 1
                log.warning(f"batch {i} failed ({e}), reconnecting (attempt {attempt}/10)...")
                if attempt >= 10:
                    log.error(f"Giving up on batch {i} after {attempt} attempts.")
                    raise
                time.sleep(min(120.0, 15.0 * attempt))
                db = _connect_with_retry()
        df.to_parquet(os.path.join(_CHECKPOINT_DIR, f"batch_{i}.parquet"), index=False)
        n_fetched += 1
        if n_fetched % 20 == 0:
            elapsed = (time.time() - t0) / 60
            log.info(f"  progress: {n_fetched}/{len(batches) - len(already_done)} new batches "
                     f"this session ({elapsed:.1f} min)")

    log.info(f"Fetch complete. Assembling final output from all {len(batches)} checkpoints...")
    all_dfs = [
        pd.read_parquet(os.path.join(_CHECKPOINT_DIR, f"batch_{i}.parquet"))
        for i in range(len(batches))
    ]
    combined = pd.concat(all_dfs, ignore_index=True)
    combined.to_parquet(_OUT_PATH, index=False)
    log.info(f"Saved {len(combined)} (ticker, rdate) rows -> {_OUT_PATH}, "
             f"{combined['ticker'].nunique()} distinct tickers with any real institutional-"
             f"holding history found.")


if __name__ == "__main__":
    main()
