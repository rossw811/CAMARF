"""
data_wrds.py — WRDS (Wharton Research Data Services) supplemental/replacement
data pipeline for CAMARF. ALL WRDS data sources live in this ONE file
(consolidated 2026-07-27 per Ross's explicit direction — one file per
external PROVIDER, matching data_ibkr.py's own precedent, not one file per
data PRODUCT within that provider).
================================================================================
SEPARATE SCRIPT from data.py, mirroring data_ibkr.py's own precedent (never
merge a second fetch path into data.py's main loop — CLAUDE.md rule 2 exists
specifically because that was tried once with IBKR and cost weeks of
instability). Run manually.

Sections in this file (grep for "SECTION:" to jump between them):
  - CRSP (US equities/ETFs) — replaces yfinance for this subset.
  - Compustat Global (international equities) — fills the gap CRSP itself
    doesn't cover (7267.T/8058.T, Hong Kong tickers, etc.)
  - (planned, not yet built) Fama-French factors, Fed Reserve FX/rates,
    Macro Finance Society factors/uncertainty indices — see task list.

Scope, stated precisely (2026-07-27 design pass, see Development.md):
  - CRSP (`crsp_a_stock.dsf_v2`) covers US-listed common stocks and ETFs only.
  - It does NOT cover crypto, forex/FX spots, or foreign-primary listings
    (7267.T/8058.T, Hong Kong tickers, etc.) — Compustat Global (below)
    covers those instead; crypto/forex/fx_spot stay on yfinance regardless.

WRDS/CRSP license compliance — READ BEFORE TOUCHING THIS FILE:
  - This is WRDS data under a non-commercial academic license. NEVER commit,
    push, paste, or otherwise distribute raw or minimally-transformed CRSP
    data anywhere off this machine. output/ (where this script's cache lives)
    is already fully gitignored — verified 2026-07-22 — keep it that way.
  - Any external-facing writeup (PAPER.md, etc.) may describe the exact WRDS
    query/table/date-range used for reproducibility, but must NEVER embed the
    underlying price data itself. Reproducibility means "another WRDS-licensed
    person could rerun this query," not "a reader without WRDS access could
    reconstruct the dataset from what's published."

Identifier resolution (point-in-time correct, not a shortcut):
  CRSP's canonical key is PERMNO (a permanent security ID), not ticker —
  tickers change and get reused across different companies over time.
  `crsp_a_stock.stocknames` gives the ticker->permno mapping WITH the exact
  validity date range (namedt/nameenddt) each ticker mapping held. This script
  resolves ticker -> permno using an as-of date, not a bare "most recent"
  lookup, to avoid silently attaching the wrong company's history to a
  reused ticker.

Split/dividend adjustment (verified against a real, known event before
trusting it — see debug/_verify_data_wrds_adjustment.py):
  `dlycumfacpr` is CRSP's cumulative price adjustment factor. Confirmed
  directly against AAPL's real 2020-08-31 4-for-1 split: dividing raw
  `dlyclose` by `dlycumfacpr` produces a perfectly continuous adjusted price
  series across the split boundary (500.04/4.0 = 125.01, continuous with the
  very next trading day's 129.04) — this is the formula used here, not
  assumed from memory of the legacy `dsf` table's convention (which uses a
  differently-named but analogous `cfacpr` field).

Table used: `crsp_a_stock.dsf_v2` (the newer CRSP schema — verified 2026-07-27
to extend to 2025-12-31, a full year later than the legacy `dsf` table's
2024-12-31 cutoff).

Usage
-----
    python data_wrds.py                       # all US equity/ETF symbols in the current universe
    python data_wrds.py --symbols AAPL MSFT    # specific symbols
    python data_wrds.py --start 2015-01-01     # override history start (default: full available history)
    python data_wrds.py --dry-run              # resolve permnos, print counts, fetch nothing

Output
------
  output/cache/wrds/{SYMBOL}_1D.parquet — native daily (dsf_v2). Columns: open,
  high, low, close, close_total_return, volume (open/high/low/close are
  split-adjusted only; close_total_return additionally chains dlyret for
  dividends -- see fetch_symbol's docstring; volume is NOT adjusted for
  share-count changes).
  output/cache/wrds/{SYMBOL}_1M.parquet — native monthly (msf_v2, CRSP's own
  monthly file, NOT a resample of the 1D output). Columns: close,
  close_total_return, volume.
  output/cache/wrds/{SYMBOL}_{7D,3M,6M,1Y}.parquet — derived via
  resample_daily_to() from the 1D output, matching data.py's own
  _resample_from_daily conventions exactly. 1Y is new (not in production
  Config.DATA.TIMEFRAME_LABELS yet) -- see the "Derived/native coarser
  timeframes" section comment for why it's justified now.
  CRSP has NO intraday data -- 1m/2m/3m/5m/15m/30m/1h/4h stay on yfinance
  regardless; this file only ever serves 1D and coarser.
"""
import argparse
import logging
import os
import re
import sys
import time
import warnings
from typing import Dict, List, Optional, Tuple

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config

warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

_OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "cache", "wrds")
_LOG_PATH = "latest_run_data_wrds.log"


def _connect():
    """Real finding (2026-08-13): passing `wrds_username` explicitly lets
    wrds.Connection() skip its interactive `input()` username prompt
    entirely and go straight to .pgpass for the password -- confirmed to
    work fully non-interactively (no Duo re-prompt) when a valid Duo
    "remember this device" trust window is still active from an earlier
    interactive login. NOT guaranteed to always skip Duo -- once that trust
    window expires, a connection will fall back to needing an interactive
    session again (this project's earlier-established constraint), this
    doesn't change that. `WRDS_USERNAME` env var overrides the fallback
    default if ever needed for a different account."""
    import os
    import wrds
    username = os.environ.get("WRDS_USERNAME", "rossw0811")
    return wrds.Connection(wrds_username=username)


# =============================================================================
# SECTION: CRSP (US equities/ETFs)
# =============================================================================

def _get_universe_us_equity_etf_symbols() -> List[str]:
    """Reuses UniverseBuilder's own constituent list (S&P 1500 + ETFs), then
    filters to asset classes CRSP actually covers ('equity', 'etf') --
    excludes equity_intl/crypto/forex/fx_spot/commodity/futures explicitly,
    not just by omission."""
    from data import UniverseBuilder

    builder = UniverseBuilder()
    raw = builder._build_raw_list()
    exclusions = UniverseBuilder.load_exclusions()
    return sorted({
        sym for sym, cls in raw
        if cls in ("equity", "etf") and sym not in exclusions
    })


def resolve_permnos_bulk(db, tickers: List[str], as_of_date: Optional[str] = None) -> Dict[str, int]:
    """
    Bulk version of resolve_permno -- ONE query for the whole ticker list
    instead of one round-trip per symbol. Needed for whole-universe fetches
    (added 2026-07-27, Ross's direction to re-test cointegration over WRDS's
    much deeper history before trusting the current confirmed-pair set --
    one-symbol-at-a-time round trips don't scale to ~1500 symbols).

    Resolves each ticker to the permno(s) valid at the latest namedt <=
    as_of_date -- same nameenddt-staleness reasoning as resolve_permno's
    single-ticker version. Returns {ticker: permno} -- tickers with no valid
    mapping are simply absent from the result, not an error.

    Genuinely ambiguous tickers are ALSO excluded from the result, not
    silently guessed. Found directly (2026-07-27, live full-universe run):
    CRSP's stocknames has cases where TWO DIFFERENT PERMNOs share the
    identical bare ticker string with IDENTICAL namedt/nameenddt -- e.g.
    'CWEN' resolves to both permno 14030 ($31.42/share) and permno 15332
    ($33.26/share), both tagged "CLEARWAY ENERGY INC", both valid
    2024-06-20 onward, with no metadata field distinguishing which is the
    actual current-universe share class. A plain `DISTINCT ON (ticker)`
    query (the prior version of this function) picks whichever row
    PostgreSQL happens to return first among the tied pair -- an arbitrary,
    unverified choice, not a resolution. This mirrors exactly the ambiguity
    CRSP's own resolve_gvkey_global was already built to refuse for
    Compustat Global company-name collisions -- same principle, applied
    here to a ticker-level collision.
    """
    as_of = as_of_date or pd.Timestamp.today().strftime("%Y-%m-%d")
    tickers_sql = ",".join(f"'{t}'" for t in tickers)
    q = f"""
        with latest as (
            select ticker, max(namedt) as max_namedt
            from crsp_a_stock.stocknames
            where ticker in ({tickers_sql})
              and namedt <= '{as_of}'
            group by ticker
        )
        select s.ticker, s.permno
        from crsp_a_stock.stocknames s
        join latest l on s.ticker = l.ticker and s.namedt = l.max_namedt
        group by s.ticker, s.permno
    """
    df = db.raw_sql(q)
    if df.empty:
        return {}

    result: Dict[str, int] = {}
    for ticker, g in df.groupby("ticker"):
        distinct_permnos = g["permno"].unique()
        if len(distinct_permnos) == 1:
            result[ticker] = int(distinct_permnos[0])
        else:
            log.warning(f"resolve_permnos_bulk: '{ticker}' is AMBIGUOUS -- "
                        f"{len(distinct_permnos)} distinct permnos tied at the same "
                        f"namedt ({sorted(int(p) for p in distinct_permnos)}) -- "
                        f"refusing to guess, excluded from result")
    return result


def fetch_symbols_bulk(db, permno_by_symbol: Dict[str, int], start: Optional[str] = None,
                        batch_size: int = 200):
    """
    Bulk version of fetch_symbol -- fetches many permnos' dsf_v2 history in
    chunked batches (WHERE permno IN (...)) instead of one query per symbol.
    Same split/total-return adjustment logic as fetch_symbol, applied after
    the bulk pull. batch_size caps each round trip's result set to a
    manageable size (~200 symbols x full history is a few million rows at
    most, not an unwieldy single query for the whole universe at once).

    Generator, yielding (symbol, df) as each BATCH completes -- deliberately
    NOT returning one big dict at the end. Found directly (2026-07-27): the
    first full-universe run held every batch's results in memory until the
    very last batch finished, meaning nothing was persisted to disk if the
    process died partway through an ~8-batch, many-minute run. Yielding
    incrementally lets the caller (main(), below) write each batch to disk
    as it lands, so a crash only loses the CURRENT batch, not the whole run.
    """
    symbol_by_permno = {v: k for k, v in permno_by_symbol.items()}
    permnos = list(permno_by_symbol.values())

    for i in range(0, len(permnos), batch_size):
        batch = permnos[i:i + batch_size]
        permnos_sql = ",".join(str(p) for p in batch)
        start_clause = f"and dlycaldt >= '{start}'" if start else ""
        q = f"""
            select permno, dlycaldt, dlyopen, dlyhigh, dlylow, dlyclose, dlyvol, dlycumfacpr, dlyret
            from crsp_a_stock.dsf_v2
            where permno in ({permnos_sql})
            {start_clause}
            order by permno, dlycaldt
        """
        chunk = db.raw_sql(q)
        if chunk.empty:
            log.warning(f"  batch {i}-{i+len(batch)}: no rows returned for {len(batch)} permnos")
            continue
        chunk["dlycaldt"] = pd.to_datetime(chunk["dlycaldt"])

        n_in_batch = 0
        for permno, g in chunk.groupby("permno"):
            sym = symbol_by_permno.get(int(permno))
            if sym is None:
                continue
            g = g.set_index("dlycaldt").sort_index()
            fac = g["dlycumfacpr"].replace(0, pd.NA)
            close_split_adj = g["dlyclose"] / fac
            ret = g["dlyret"].fillna(0.0)
            first_valid = close_split_adj.dropna()
            if len(first_valid) == 0:
                close_tr = close_split_adj
            else:
                base = first_valid.iloc[0]
                base_idx = first_valid.index[0]
                growth = (1.0 + ret.loc[base_idx:]).cumprod()
                close_tr = pd.Series(index=close_split_adj.index, dtype=float)
                close_tr.loc[base_idx:] = base * growth / growth.iloc[0]
            df = pd.DataFrame({
                "open": g["dlyopen"] / fac,
                "high": g["dlyhigh"] / fac,
                "low": g["dlylow"] / fac,
                "close": close_split_adj,
                "close_total_return": close_tr,
                "volume": g["dlyvol"],
            })
            n_in_batch += 1
            yield sym, df
        log.info(f"  batch {i}-{i+len(batch)}/{len(permnos)}: {n_in_batch} symbols fetched")


def fetch_monthly_bulk(db, permno_by_symbol: Dict[str, int], start: Optional[str] = None,
                        batch_size: int = 200):
    """
    Bulk version of fetch_symbol_monthly_native -- same batching pattern as
    fetch_symbols_bulk, against CRSP's native msf_v2 monthly file instead of
    the daily dsf_v2. Generator, yields (symbol, df) per batch for the same
    incremental-persistence reason.
    """
    symbol_by_permno = {v: k for k, v in permno_by_symbol.items()}
    permnos = list(permno_by_symbol.values())

    for i in range(0, len(permnos), batch_size):
        batch = permnos[i:i + batch_size]
        permnos_sql = ",".join(str(p) for p in batch)
        start_clause = f"and mthcaldt >= '{start}'" if start else ""
        q = f"""
            select permno, mthcaldt, mthprc, mthvol, mthcumfacpr, mthret
            from crsp_a_stock.msf_v2
            where permno in ({permnos_sql})
            {start_clause}
            order by permno, mthcaldt
        """
        chunk = db.raw_sql(q)
        if chunk.empty:
            log.warning(f"  monthly batch {i}-{i+len(batch)}: no rows returned")
            continue
        chunk["mthcaldt"] = pd.to_datetime(chunk["mthcaldt"])

        n_in_batch = 0
        for permno, g in chunk.groupby("permno"):
            sym = symbol_by_permno.get(int(permno))
            if sym is None:
                continue
            g = g.set_index("mthcaldt").sort_index()
            fac = g["mthcumfacpr"].replace(0, pd.NA)
            close_split_adj = g["mthprc"].abs() / fac
            ret = g["mthret"].fillna(0.0)
            first_valid = close_split_adj.dropna()
            if len(first_valid) == 0:
                close_tr = close_split_adj
            else:
                base, base_idx = first_valid.iloc[0], first_valid.index[0]
                growth = (1.0 + ret.loc[base_idx:]).cumprod()
                close_tr = pd.Series(index=close_split_adj.index, dtype=float)
                close_tr.loc[base_idx:] = base * growth / growth.iloc[0]
            df = pd.DataFrame({
                "close": close_split_adj,
                "close_total_return": close_tr,
                "volume": g["mthvol"],
            })
            n_in_batch += 1
            yield sym, df
        log.info(f"  monthly batch {i}-{i+len(batch)}/{len(permnos)}: {n_in_batch} symbols fetched")


def resolve_permno(db, ticker: str, as_of_date: Optional[str] = None) -> Optional[Tuple[int, str, str]]:
    """
    Point-in-time-correct ticker -> PERMNO resolution.

    Returns (permno, namedt, nameenddt) for the ticker mapping valid at
    as_of_date (default: today), or None if no valid mapping exists.
    A ticker can be reused by an unrelated company after the original one
    delists/renames -- resolving "most recent PERMNO for this ticker string"
    without a date check would silently attach the wrong company's history.

    Deliberately does NOT require `nameenddt >= as_of_date`. Found directly
    (2026-07-27): `stocknames`'s nameenddt lags behind the actual price data
    -- AAPL's own current mapping shows nameenddt=2024-12-31 even though
    `dsf_v2` itself has real AAPL prices through 2025-12-31 (nameenddt looks
    like it reflects this table's own metadata refresh cadence, not a true
    "ticker stopped being valid" boundary). Requiring nameenddt >= today
    would incorrectly reject every still-active ticker whose stocknames
    metadata hasn't been refreshed as recently as its own price data.
    Instead: pick the mapping with the LATEST namedt that is <= as_of_date --
    the standard "which company held this ticker most recently, as of this
    date" resolution, robust to a stale nameenddt field. Still fully protects
    against the actual failure mode (a ticker reused by an unrelated company)
    since namedt itself (when a mapping STARTED) is reliable.

    Also refuses to guess when the ticker is genuinely AMBIGUOUS at that
    namedt -- i.e. more than one distinct permno shares the identical ticker
    string with the identical latest namedt (found directly 2026-07-27 for
    'CWEN'/'BF'/'BRK' -- see resolve_permnos_bulk's docstring for the full
    finding). The prior `order by namedt desc limit 1` silently picked
    whichever tied row PostgreSQL returned first; this version detects the
    tie and returns None instead, same principle as resolve_gvkey_global's
    ambiguous-name refusal.
    """
    as_of = as_of_date or pd.Timestamp.today().strftime("%Y-%m-%d")
    q = f"""
        select permno, namedt, nameenddt
        from crsp_a_stock.stocknames
        where ticker = '{ticker}'
          and namedt <= '{as_of}'
          and namedt = (
              select max(namedt) from crsp_a_stock.stocknames
              where ticker = '{ticker}' and namedt <= '{as_of}'
          )
    """
    df = db.raw_sql(q)
    if df.empty:
        return None
    distinct_permnos = df["permno"].unique()
    if len(distinct_permnos) > 1:
        log.warning(f"resolve_permno: '{ticker}' is AMBIGUOUS -- "
                    f"{len(distinct_permnos)} distinct permnos tied at the same "
                    f"namedt ({sorted(int(p) for p in distinct_permnos)}) -- "
                    f"refusing to guess, returning None")
        return None
    row = df.iloc[0]
    return int(row["permno"]), str(row["namedt"]), str(row["nameenddt"])


def fetch_symbol(db, symbol: str, start: Optional[str] = None) -> Optional[pd.DataFrame]:
    """
    Fetch one symbol's full CRSP daily history via dsf_v2.

    Two close-price conventions are both returned, deliberately NOT
    collapsed into one (same "expose every method side by side" habit this
    project already applies to hedge ratios): CRSP intentionally keeps
    price and dividend return as separate fields, unlike yfinance's default
    auto-adjusted close which bundles both. Found via direct comparison
    against the existing yfinance cache (2026-07-27): split-only-adjusted
    WRDS close differs from yfinance's close by an amount proportional to
    each symbol's accumulated dividends (FELE, low/no dividend: 1.9% gap;
    KMB, a steady dividend payer: 8.2% gap) -- not a data quality problem in
    either source, a genuine convention difference that would have silently
    produced non-comparable return series if not caught here.

      - 'close': split-adjusted only (dlyclose / dlycumfacpr), CRSP's own
        native price convention.
      - 'close_total_return': split-AND-dividend-adjusted, reconstructed by
        chaining CRSP's own dlyret (total return, dividends included) as a
        cumulative product from the first available split-adjusted close --
        this is the series comparable to yfinance's default auto-adjusted
        close, and the one CAMARF's cointegration/correlation engine should
        actually use for return calculations.

    Volume is NOT share-count-adjusted in this first pass -- CRSP's
    dlycumfacshr exists for exactly this purpose (analogous to dlycumfacpr
    for price), but the correct adjustment DIRECTION for volume needs its
    own verification against a known split (likely multiply, not divide,
    since post-split volume in the same share units should be larger for a
    forward split) before being trusted -- not done here, flagged rather
    than guessed. Raw dlyvol is persisted as-is; a `volume_adjusted` column
    is deliberately NOT added until that's verified.
    """
    resolved = resolve_permno(db, symbol)
    if resolved is None:
        log.warning(f"  {symbol}: no PERMNO mapping found (as-of today) -- skipping")
        return None
    permno, namedt, nameenddt = resolved

    start_clause = f"and dlycaldt >= '{start}'" if start else ""
    q = f"""
        select dlycaldt, dlyopen, dlyhigh, dlylow, dlyclose, dlyvol, dlycumfacpr, dlyret
        from crsp_a_stock.dsf_v2
        where permno = {permno}
        {start_clause}
        order by dlycaldt
    """
    df = db.raw_sql(q)
    if df.empty:
        log.warning(f"  {symbol}: PERMNO {permno} resolved but no dsf_v2 rows returned")
        return None

    df["dlycaldt"] = pd.to_datetime(df["dlycaldt"])
    df = df.set_index("dlycaldt")
    # Split-adjust OHLC by dividing by the cumulative price factor -- verified
    # against AAPL's real 2020-08-31 4-for-1 split (see module docstring).
    fac = df["dlycumfacpr"].replace(0, pd.NA)
    close_split_adj = df["dlyclose"] / fac

    # Total-return-adjusted close: chain (1 + dlyret) as a cumulative product
    # from the first valid split-adjusted close -- standard total-return-
    # index construction, using CRSP's own authoritative total-return field
    # rather than re-deriving dividends from raw dividend-amount fields.
    ret = df["dlyret"].fillna(0.0)
    first_valid = close_split_adj.dropna()
    if len(first_valid) == 0:
        close_tr = close_split_adj
    else:
        base = first_valid.iloc[0]
        base_idx = first_valid.index[0]
        growth = (1.0 + ret.loc[base_idx:]).cumprod()
        close_tr = pd.Series(index=close_split_adj.index, dtype=float)
        close_tr.loc[base_idx:] = base * growth / growth.iloc[0]

    out = pd.DataFrame({
        "open": df["dlyopen"] / fac,
        "high": df["dlyhigh"] / fac,
        "low": df["dlylow"] / fac,
        "close": close_split_adj,
        "close_total_return": close_tr,
        "volume": df["dlyvol"],
    })
    out.index.name = None
    return out


# =============================================================================
# SECTION: Derived/native coarser timeframes (7D/1M/3M/6M, plus a NEW 1Y)
# =============================================================================
#
# CRSP has NO intraday data at all (that's what real TAQ access would have
# needed to provide -- confirmed not actually available, see module history
# in Development.md). WRDS's real contribution is therefore 1D and coarser
# ONLY -- 1m/2m/3m/5m/15m/30m/1h/4h stay on yfinance regardless of "max
# data" ambition; this is a hard fact about what CRSP contains, not a scope
# choice made here.
#
# 1M uses CRSP's NATIVE monthly file (crsp_a_stock.msf_v2) rather than
# resampling daily bars -- confirmed to exist, same 1925-2025-12-31 range as
# dsf_v2, with its own authoritative mthret (total return) field, avoiding
# any resampling artifacts for the timeframe CRSP itself natively maintains.
# 7D/3M/6M/1Y are all derived by resampling the daily data_wrds close series,
# using the EXACT SAME resample rules/label/closed conventions data.py's own
# `_resample_from_daily` already uses for 7D/1M/3M/6M (data.py:1973-1977) --
# not a new, independently-chosen convention that could silently drift from
# production's.
#
# 1Y is a genuinely NEW timeframe, not currently in Config.DATA.
# TIMEFRAME_LABELS -- added here per Ross's direct request ("we can maybe
# even add yearly now too"), justified specifically by WRDS's depth: 100
# years of daily CRSP history gives ~100 meaningful yearly bars, where
# yfinance's much shorter history would give at most a decade or two.
# Fetchable here; NOT yet wired into the production Config.DATA.
# TIMEFRAME_LABELS list or analysis.py's per-TF loop -- that's a separate,
# explicit step (adding a new TF to the production pipeline touches several
# places: Config.STATS.MIN_OVERLAP_BY_TF, the DataStore._TF_SAFE mapping,
# etc.) flagged here rather than silently done as a side effect of this file.

_RESAMPLE_RULES = {
    # (rule, label, closed) -- identical to data.py's _resample_from_daily
    "7D": ("W-FRI", "right", "right"),
    "3M": ("QS", "left", "left"),
    "6M": ("2QS", "left", "left"),
    "1Y": ("YS", "left", "left"),  # NEW -- year-start stamp, same convention family
}


def resample_daily_to(df: pd.DataFrame, tf_label: str) -> Optional[pd.DataFrame]:
    """Resamples a data_wrds daily OHLCV(+close_total_return) DataFrame to
    7D/3M/6M/1Y, matching data.py's own _resample_from_daily conventions
    exactly (same rule/label/closed per TF, same agg functions, same
    empty-period drop). Returns None for unrecognized tf_label rather than
    silently guessing a rule."""
    if tf_label not in _RESAMPLE_RULES:
        log.warning(f"resample_daily_to: no rule defined for '{tf_label}' "
                    f"(known: {list(_RESAMPLE_RULES)})")
        return None
    rule, lbl, closed = _RESAMPLE_RULES[tf_label]
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if "close_total_return" in df.columns:
        agg["close_total_return"] = "last"
    agg = {k: v for k, v in agg.items() if k in df.columns}
    resampled = df.resample(rule, label=lbl, closed=closed).agg(agg)
    resampled = resampled.dropna(subset=["close"])
    resampled = resampled[resampled["close"] > 0]
    return resampled


def fetch_symbol_monthly_native(db, symbol: str, start: Optional[str] = None) -> Optional[pd.DataFrame]:
    """
    Fetch one symbol's NATIVE CRSP monthly history via msf_v2 -- CRSP's own
    authoritative monthly file, not a resample of daily bars. Same
    split-adjustment (mthcumfacpr) and total-return (mthret, chained the
    same way fetch_symbol() does for dlyret) pattern as the daily fetch.
    """
    resolved = resolve_permno(db, symbol)
    if resolved is None:
        log.warning(f"  {symbol}: no PERMNO mapping found -- skipping monthly fetch")
        return None
    permno, _, _ = resolved

    start_clause = f"and mthcaldt >= '{start}'" if start else ""
    q = f"""
        select mthcaldt, mthprc, mthvol, mthcumfacpr, mthret
        from crsp_a_stock.msf_v2
        where permno = {permno}
        {start_clause}
        order by mthcaldt
    """
    df = db.raw_sql(q)
    if df.empty:
        log.warning(f"  {symbol}: PERMNO {permno} resolved but no msf_v2 rows returned")
        return None

    df["mthcaldt"] = pd.to_datetime(df["mthcaldt"])
    df = df.set_index("mthcaldt")
    fac = df["mthcumfacpr"].replace(0, pd.NA)
    close_split_adj = df["mthprc"].abs() / fac  # CRSP's price can be negative (bid/ask avg convention)

    ret = df["mthret"].fillna(0.0)
    first_valid = close_split_adj.dropna()
    if len(first_valid) == 0:
        close_tr = close_split_adj
    else:
        base, base_idx = first_valid.iloc[0], first_valid.index[0]
        growth = (1.0 + ret.loc[base_idx:]).cumprod()
        close_tr = pd.Series(index=close_split_adj.index, dtype=float)
        close_tr.loc[base_idx:] = base * growth / growth.iloc[0]

    out = pd.DataFrame({
        "close": close_split_adj,
        "close_total_return": close_tr,
        "volume": df["mthvol"],
    })
    out.index.name = None
    return out


# =============================================================================
# SECTION: S&P 500 point-in-time membership (survivorship-bias fix)
# =============================================================================
# Added 2026-07-27 per Ross's direct request: CAMARF's universe construction
# (UniverseBuilder, data.py) scrapes TODAY's Wikipedia S&P 1500 constituent
# table -- this misses every company that was ever a member but has since
# been delisted, acquired, or dropped from the index. `crsp_a_indexes.
# dsp500list_v2` gives CRSP's own point-in-time S&P 500 membership history
# (permno, mbrstartdt, mbrenddt) back to 1925 -- confirmed directly (see
# Development.md): 1,956 distinct permnos have EVER been S&P 500 members,
# vs. only 503 today (~74% of the historical universe is invisible to the
# current Wikipedia-scrape approach).
#
# Scope, stated precisely: this section fixes S&P 500 ONLY. S&P 400/600
# have NO equivalent point-in-time product available in this WRDS
# subscription (checked directly -- see Development.md's "S&P 400/600 --
# NOT yet solved" entry) -- they remain on the existing Wikipedia
# current-constituents approach, same disclosed bias as before.

_SP500_MEMBERSHIP_CACHE = os.path.join(_OUT_DIR, "sp500_membership_history.parquet")


def fetch_sp500_membership_history(db) -> pd.DataFrame:
    """
    Pulls CRSP's full point-in-time S&P 500 membership history. Cleans the
    "still current" placeholder found directly in dsp500list_v2 (503 rows
    share the table's own max mbrenddt -- the data's last refresh date, NOT
    a real departure, same staleness-placeholder pattern already found for
    stocknames.nameenddt) into an explicit `is_current` flag, keeping
    `mbrenddt` as a genuine departure date only for actual historical exits.

    Returns one row per membership SPELL, not one row per permno -- a
    company dropped and later re-added (confirmed real cases exist, e.g.
    permno 10233 has 4 separate spells) gets multiple rows, each with its
    own start/end. Caches to output/cache/wrds/sp500_membership_history.parquet.
    """
    q = """
        select permno, mbrstartdt, mbrenddt
        from crsp_a_indexes.dsp500list_v2
        order by permno, mbrstartdt
    """
    df = db.raw_sql(q)
    df["mbrstartdt"] = pd.to_datetime(df["mbrstartdt"])
    df["mbrenddt"] = pd.to_datetime(df["mbrenddt"])
    max_end = df["mbrenddt"].max()
    df["is_current"] = df["mbrenddt"] == max_end
    df.loc[df["is_current"], "mbrenddt"] = pd.NaT

    os.makedirs(_OUT_DIR, exist_ok=True)
    df.to_parquet(_SP500_MEMBERSHIP_CACHE, index=False)
    log.info(f"S&P 500 membership history: {len(df)} spells, {df['permno'].nunique()} distinct permnos "
             f"({int(df['is_current'].sum())} currently active)")
    return df


_CRSP_SECURITY_MASTER_CACHE = os.path.join(_OUT_DIR, "crsp_full_security_master.parquet")


def fetch_full_crsp_security_master(db) -> pd.DataFrame:
    """
    Thread K Part 1 (2026-08-13, Ross: "let's make sure we also get the
    entire US market and all what assets we're when and where at what
    time") -- the point-in-time "who/when/where" security master for
    CRSP's ENTIRE historical common-stock universe (shrcd 10/11/12,
    NYSE/AMEX/NASDAQ exchcd 1/2/3), not just the current ~1,700-symbol
    S&P-1500-based universe this project otherwise uses. One row per
    (permno, ticker/exchange/name) SPELL -- a security that changed
    ticker, exchange, or name gets multiple rows, each with its own
    namedt/nameenddt validity range (confirmed real, e.g. permno 10001
    spans 6 spells across 1986-2017 as it moved tickers/exchanges).

    "Still current" placeholder handling, checked directly before writing
    this (not assumed from the S&P 500/Compustat Global precedent alone):
    stocknames.nameenddt has ZERO genuine NULLs -- currently-active spells
    instead share the table's own max nameenddt (2024-12-31, confirmed via
    a real query: 4,758 rows share this exact date) as a refresh-date
    placeholder, same convention already fixed for dsp500list_v2 and
    Compustat Global's g_idxcst_his. Same fix applied here.

    This is METADATA ONLY (ticker/exchange/name/date-range) -- does NOT
    fetch price history, a separate, dramatically more expensive step
    (29,366 distinct securities vs. this project's current ~1,700; sizing
    that separately before any commitment, not bundled into this function).
    Caches to output/cache/wrds/crsp_full_security_master.parquet.
    """
    q = """
        select permno, permco, namedt, nameenddt, shrcd, exchcd, ncusip, ticker, comnam
        from crsp_a_stock.stocknames
        where shrcd in (10, 11, 12) and exchcd in (1, 2, 3)
        order by permno, namedt
    """
    df = db.raw_sql(q)
    df["namedt"] = pd.to_datetime(df["namedt"])
    df["nameenddt"] = pd.to_datetime(df["nameenddt"])
    max_end = df["nameenddt"].max()
    df["is_current"] = df["nameenddt"] == max_end
    df.loc[df["is_current"], "nameenddt"] = pd.NaT

    os.makedirs(_OUT_DIR, exist_ok=True)
    df.to_parquet(_CRSP_SECURITY_MASTER_CACHE, index=False)
    log.info(f"Full CRSP security master: {len(df)} spells, {df['permno'].nunique()} distinct "
             f"permnos, {df['ticker'].nunique()} distinct tickers, "
             f"{df['namedt'].min().date()}-{df['nameenddt'].fillna(pd.Timestamp('today')).max().date()} "
             f"({int(df['is_current'].sum())} currently active spells)")
    return df


def security_master_asof(master_df: pd.DataFrame, as_of_date: Optional[str] = None) -> pd.DataFrame:
    """Point-in-time lookup mirroring sp500_members_asof's own convention:
    returns the rows (permno, ticker, exchange, etc.) that were valid on
    as_of_date -- i.e. which securities genuinely existed, under which
    ticker, on which exchange, at that point in time."""
    as_of = pd.Timestamp(as_of_date) if as_of_date else pd.Timestamp.today()
    return master_df[
        (master_df["namedt"] <= as_of)
        & (master_df["is_current"] | (master_df["nameenddt"] >= as_of))
    ]


def sp500_members_asof(membership_df: pd.DataFrame, as_of_date: Optional[str] = None) -> set:
    """
    The actual point-in-time FIX: returns the set of permnos that were S&P
    500 members on `as_of_date` (default: today) -- correctly handling
    multi-spell membership (a permno with an earlier spell that ended before
    as_of_date, and a later spell that started after it, is correctly
    EXCLUDED, not included just because it appears somewhere in the table).
    """
    as_of = pd.Timestamp(as_of_date) if as_of_date else pd.Timestamp.today()
    active = membership_df[
        (membership_df["mbrstartdt"] <= as_of)
        & (membership_df["is_current"] | (membership_df["mbrenddt"] >= as_of))
    ]
    return set(active["permno"].astype(int))


def resolve_last_known_tickers(db, permnos: List[int]) -> Dict[int, str]:
    """
    For historically-delisted permnos with no CURRENT ticker mapping (their
    ticker string may have been reused by an unrelated company since), finds
    each permno's LAST ticker string it ever held -- used purely as a
    human-readable file-naming label, not as an identifier (permno remains
    the authoritative join key throughout). Ambiguity-safe: if a permno's
    own last-namedt row is itself ambiguous (shares that namedt with another
    permno under the same ticker -- ticker collision, not permno collision,
    so this is a DIFFERENT ambiguity class than resolve_permno's), the label
    falls back to the permno itself (e.g. "PERMNO12345") rather than
    guessing, since correctness of the underlying price data (keyed by
    permno) is unaffected by this either way -- only the filename readability is.
    """
    if not permnos:
        return {}
    permnos_sql = ",".join(str(p) for p in permnos)
    q = f"""
        with latest as (
            select permno, max(namedt) as max_namedt
            from crsp_a_stock.stocknames
            where permno in ({permnos_sql})
            group by permno
        )
        select s.permno, s.ticker
        from crsp_a_stock.stocknames s
        join latest l on s.permno = l.permno and s.namedt = l.max_namedt
    """
    df = db.raw_sql(q)
    result: Dict[int, str] = {}
    for permno, g in df.groupby("permno"):
        # stocknames.ticker can itself be NULL for some rows (a real data
        # gap, found directly while running this against the full delisted
        # S&P 500 set) -- drop nulls before uniquifying, since a null isn't
        # a usable label and comparing it downstream (pd.NA != str) raises
        # TypeError rather than behaving like a normal string mismatch.
        tickers = g["ticker"].dropna().unique()
        result[int(permno)] = tickers[0] if len(tickers) == 1 else f"PERMNO{int(permno)}"
    return result


def build_delisted_label_map(delisted_permnos, last_known_tickers: Dict[int, str],
                              active_ticker_labels: set) -> Dict[str, int]:
    """
    Builds {label: permno} for the delisted-permno fetch, guarding against
    two collision risks: (1) two different delisted permnos sharing the same
    last-known ticker string, and (2) FAR more dangerous -- a delisted
    permno's last-known ticker being reused by a CURRENTLY ACTIVE company
    already in the main universe fetch (ticker reuse is confirmed common in
    this project -- it's the entire reason resolve_permno's PIT-correctness
    logic exists). Writing under that label would silently OVERWRITE the
    live company's own parquet file with the delisted company's historical
    data. Either collision falls back to a PERMNO-based label
    ("PERMNO<n>") instead -- checked and prevented explicitly, never assumed
    impossible.
    """
    seen_labels = set()
    result: Dict[str, int] = {}
    for p in delisted_permnos:
        label = last_known_tickers.get(p, f"PERMNO{p}")
        if label in active_ticker_labels or label in seen_labels:
            label = f"PERMNO{p}"
        seen_labels.add(label)
        result[label] = p
    return result


def get_delisted_sp500_permnos(membership_df: pd.DataFrame, already_covered_permnos: set) -> set:
    """
    Returns the set of permnos that have EVER been an S&P 500 member but are
    NOT already covered by the existing ticker-based universe fetch
    (`already_covered_permnos` -- pass permno_by_symbol.values() from the
    current S&P 1500 ticker-based resolution). This is the concrete set of
    "survivorship-bias" companies whose price history WRDS/CRSP can supply
    but the current Wikipedia-scrape approach would never even attempt to
    fetch, since they aren't in today's constituent table at all. Caller
    resolves human-readable labels for these via resolve_last_known_tickers
    before fetching (permno is the authoritative identifier throughout;
    the label is filename cosmetics only).
    """
    all_permnos = set(membership_df["permno"].astype(int).unique())
    return all_permnos - set(already_covered_permnos)


_ILLIQUID_EXCLUSION_CACHE = os.path.join(_OUT_DIR, "sp500_delisted_illiquid_exclusion.parquet")
_DELISTED_LABEL_MAP_CACHE = os.path.join(_OUT_DIR, "sp500_delisted_label_map.parquet")


def compute_symbol_adv_wrds(label: str, window_days: int = 252) -> float:
    """
    Average daily dollar volume for an already-fetched WRDS symbol, read
    from output/cache/wrds/{label}_1D.parquet. Mirrors analysis.py's own
    ADV-filter formula (close * volume, then mean -- WRDS daily data is
    already one row per calendar day, so no groupby-and-sum aggregation step
    is needed the way analysis.py's hourly-cache path requires).

    Deliberately NOT a flat mean over the symbol's ENTIRE available history
    -- found directly to matter (Ross, 2026-07-27): WRDS's history can span
    80-100 years, so a flat full-history mean would blend a symbol's 1950s
    dollar volume with its 2020s dollar volume into one economically
    meaningless number (share counts, price levels, and market structure
    are utterly different across those eras). Instead uses only the LAST
    `window_days` rows of the symbol's own available data (default ~1
    trading year) -- for a currently-delisted symbol, this means the window
    immediately before its last available bar (i.e. shortly before
    delisting), which is the actually-relevant "was this liquid when it was
    still trading" measure, not an average smeared across incomparable eras.

    Returns NaN if the file is missing/malformed (treated as "not confirmed
    liquid" by build_illiquid_exclusion_list, not silently assumed liquid).
    """
    path = os.path.join(_OUT_DIR, f"{label}_1D.parquet")
    if not os.path.exists(path):
        return float("nan")
    try:
        df = pd.read_parquet(path)
        if "close" not in df.columns or "volume" not in df.columns:
            return float("nan")
        recent = df.tail(window_days)
        if recent.empty:
            return float("nan")
        return float((recent["close"] * recent["volume"]).mean())
    except Exception:
        return float("nan")


def build_illiquid_exclusion_list(permno_by_label: Dict[str, int], threshold: Optional[float] = None) -> pd.DataFrame:
    """
    Computes ADV for every {label: permno} pair just fetched this run and
    flags which fall below the SAME liquidity bar production already applies
    (Config.STATS.ADV_FILTER_USD, $25M) -- the concrete mechanism behind
    "future runs won't be so big": once a historically-delisted symbol is
    confirmed illiquid, later refresh runs skip re-fetching its full
    multi-decade history entirely (see load_illiquid_permnos, consulted in
    main() before the fetch loop) rather than pulling it again every time.

    MERGES with any existing exclusion cache (keyed by permno, keeping the
    latest ADV computation) rather than overwriting it -- a symbol excluded
    in a prior run and therefore NOT re-fetched this run would otherwise be
    silently dropped from the cache the moment this function only saw the
    current run's (smaller) fetch batch.
    """
    thr = threshold if threshold is not None else Config.STATS.ADV_FILTER_USD
    rows = []
    for label, permno in permno_by_label.items():
        adv = compute_symbol_adv_wrds(label)
        rows.append({"permno": permno, "label": label, "adv": adv, "is_illiquid": not (adv >= thr)})
    new_df = pd.DataFrame(rows)

    if os.path.exists(_ILLIQUID_EXCLUSION_CACHE):
        existing_df = pd.read_parquet(_ILLIQUID_EXCLUSION_CACHE)
        combined = pd.concat([existing_df, new_df], ignore_index=True).drop_duplicates(
            subset="permno", keep="last"
        )
    else:
        combined = new_df

    os.makedirs(_OUT_DIR, exist_ok=True)
    combined.to_parquet(_ILLIQUID_EXCLUSION_CACHE, index=False)
    n_illiquid = int(combined["is_illiquid"].sum())
    log.info(f"Illiquid exclusion list: {n_illiquid}/{len(combined)} total known symbols below "
             f"${thr/1e6:.0f}M ADV (this run added/refreshed {len(new_df)} entries) -- "
             f"future runs will skip these {n_illiquid} permnos entirely.")
    return combined


def load_illiquid_permnos() -> set:
    """Loads the permno set already confirmed illiquid from a prior run's
    exclusion cache -- empty set (fetch everything) on the very first run,
    since ADV can't be known before a symbol's price/volume data has ever
    been fetched at least once."""
    if not os.path.exists(_ILLIQUID_EXCLUSION_CACHE):
        return set()
    df = pd.read_parquet(_ILLIQUID_EXCLUSION_CACHE)
    return set(df.loc[df["is_illiquid"], "permno"].astype(int))


# =============================================================================
# SECTION: Global/national index point-in-time membership (generic, added
# 2026-07-27 per Ross's "add all of them, global and national" request)
# =============================================================================
# Genuinely different data source from the S&P 500 section above: Compustat
# Global's `g_idxcst_his` (gvkey, iid, gvkeyx, from, thru), keyed by gvkeyx
# (an index identifier looked up via `g_idx_index`), NOT CRSP's indno-based
# scheme. Confirmed directly this table has REAL point-in-time departure
# data for many (not all) global indices -- 18,329 of 23,711 total rows
# across the whole table have a genuine `thru` date, in clear contrast to
# the North American `comp_na_daily_all.idxcst_his` product, which came back
# CURRENT-MEMBERSHIP-ONLY (zero departures) for every US index code checked
# (S&P 500/400/600/1500 Super Composite -- see Development.md).
#
# IMPORTANT, found directly rather than assumed: a gvkeyx being DEFINED in
# g_idx_index does NOT mean its constituent history is POPULATED in
# g_idxcst_his. FTSE 100 (gvkeyx=150008) and CAC 40 (gvkeyx=150093) both
# came back with ZERO g_idxcst_his rows despite being real, valid index
# definitions -- their broader sibling indices (SBF 120 for France, STOXX
# 600/50 for pan-Europe) ARE populated instead. Always verify a specific
# gvkeyx has real rows in g_idxcst_his before relying on it -- don't assume
# from the index's name/fame alone. Verified-populated examples used in
# debug/_verify_data_wrds.py: Composite DAX (gvkeyx=150007, Germany, 1,014
# distinct gvkeys), TOPIX (gvkeyx=150194, Japan, 2,903 distinct gvkeys).

def fetch_index_membership_history_global(db, gvkeyx: str, cache_label: str) -> pd.DataFrame:
    """
    Generic point-in-time membership history for ANY Compustat Global index,
    parameterized by gvkeyx -- NOT hand-coded per index, so adding a new
    national/global index later is a one-line call, not a new function.

    Returns one row per (gvkey, iid) membership spell -- a company can be
    dropped and re-added, same multi-spell reality already confirmed for the
    S&P 500. Caches to output/cache/wrds/index_membership_{cache_label}.parquet.

    "Still current" detection auto-adapts to whichever convention the raw
    data actually uses -- checked directly, NOT assumed. Found a real bug
    here (2026-07-27): the original version blindly copied
    fetch_sp500_membership_history's CRSP convention (no genuine NULLs,
    "current" inferred as whichever rows share the table's own max `thru`
    date) without verifying it against Compustat Global's own data. Confirmed
    directly this table uses the OPPOSITE, more standard convention -- Nikkei
    225 (gvkeyx=150069) has 225 genuinely NULL `thru` rows, matching its real
    ~225 current constituents exactly, while the max FINITE `thru` value is
    just the most recent real historical departure. The original max-date
    inference logic incorrectly matched only that one most-recent-departure
    row (since NaT never equals a finite date), undercounting "current" by
    orders of magnitude for every index checked this way (Nikkei 225 showed
    2 "current" instead of ~225; Topix showed 1 instead of ~2000). Now checks
    for genuine NULLs first and uses them directly if present; only falls
    back to the shared-max-date inference (verified correct for CRSP
    specifically -- see fetch_sp500_membership_history's own docstring) when
    the table has zero genuine nulls at all.
    """
    q = f"""
        select gvkey, iid, "from" as start_dt, thru as end_dt
        from comp_global_daily.g_idxcst_his
        where gvkeyx = '{gvkeyx}'
        order by gvkey, iid, start_dt
    """
    df = db.raw_sql(q)
    if df.empty:
        log.warning(f"fetch_index_membership_history_global: gvkeyx={gvkeyx} has ZERO rows in "
                    f"g_idxcst_his -- this index is defined in g_idx_index but its constituent "
                    f"history is NOT populated in this WRDS subscription (same finding as FTSE "
                    f"100/CAC 40 -- verify before relying on this gvkeyx).")
        return df
    df["start_dt"] = pd.to_datetime(df["start_dt"])
    df["end_dt"] = pd.to_datetime(df["end_dt"])
    if df["end_dt"].isna().any():
        df["is_current"] = df["end_dt"].isna()
    else:
        max_end = df["end_dt"].max()
        df["is_current"] = df["end_dt"] == max_end
        df.loc[df["is_current"], "end_dt"] = pd.NaT

    os.makedirs(_OUT_DIR, exist_ok=True)
    cache_path = os.path.join(_OUT_DIR, f"index_membership_{cache_label}.parquet")
    df.to_parquet(cache_path, index=False)
    log.info(f"Index membership history ({cache_label}, gvkeyx={gvkeyx}): {len(df)} spells, "
             f"{df.groupby(['gvkey', 'iid']).ngroups} distinct constituents "
             f"({int(df['is_current'].sum())} currently active)")
    return df


def index_members_asof(membership_df: pd.DataFrame, as_of_date: Optional[str] = None) -> set:
    """
    Generic point-in-time membership lookup for ANY index fetched via
    fetch_index_membership_history_global -- returns the set of (gvkey, iid)
    tuples that were members on `as_of_date` (default: today). Same
    multi-spell-correct logic as sp500_members_asof, generalized beyond the
    permno-keyed CRSP case to Compustat's (gvkey, iid) identifier pair.
    """
    as_of = pd.Timestamp(as_of_date) if as_of_date else pd.Timestamp.today()
    active = membership_df[
        (membership_df["start_dt"] <= as_of)
        & (membership_df["is_current"] | (membership_df["end_dt"] >= as_of))
    ]
    return set(zip(active["gvkey"], active["iid"]))


# =============================================================================
# SECTION: Compustat Global (international equities -- fills the gap CRSP
# itself doesn't cover, e.g. 7267.T/8058.T, Hong Kong tickers)
# =============================================================================
#
# Identifier resolution here is NOT ticker-based, unlike CRSP. Found directly
# (2026-07-27): Compustat Global's own `tic` field is unreliably populated
# for non-US listings (confirmed null for Toyota Motor Corp, gvkey=019661,
# across every one of its 11 cross-listing rows). yfinance's `.isin` field
# is ALSO not usable as a bridge -- confirmed it returns the ISIN of a
# DIFFERENT, secondary cross-listing rather than the primary local listing
# a ticker like "7267.T" actually represents (Honda Motor's EUR-denominated
# `iid='96W'` row has ISIN CA4381261045 -- the exact value yfinance's `.isin`
# returned for "7267.T" -- while the real primary JPY Tokyo listing is
# `iid='01W'`, ISIN JP3854600008). Using either would have silently attached
# the wrong listing's price history.
#
# Working resolution: company name (from yfinance's reliable `.info
# ['longName']` field, NOT `.isin`) + country/currency hint, matched against
# `g_company`/`g_secd` with an exact currency filter to disambiguate
# multiple name matches (e.g. "MITSUBISHI CORP" alone matches both the real
# Japanese parent, JPY, and an unrelated "MITSUBISHI CORP FINANCE" GBR
# entity -- the currency filter picks the right one). This requires a
# one-time, semi-manual resolution per symbol (not a fully automatic bulk
# process) -- stated as a real limitation, not glossed over.

_LEGAL_SUFFIX_PATTERN = re.compile(
    r"\s*,?\s*(Corporation|Corp\.?|Co\.,?\s*Ltd\.?|Company,?\s*Limited|Public Limited Company|"
    r"Limited|Ltd\.?|Inc\.?|plc|PLC|p\.l\.c\.|Holdings?|Company)\s*\.?\s*$",
    re.IGNORECASE,
)


def core_company_name(name: str) -> str:
    """
    Strips trailing legal-entity-type suffixes (Corporation/Corp/Co., Ltd./
    Limited/Inc./plc/p.l.c./Holdings, applied iteratively) from a yfinance-
    style verbose company name, e.g. "Toyota Motor Corporation" -> "Toyota
    Motor", "HSBC Holdings plc" -> "HSBC".

    Found necessary (2026-07-27) while batch-resolving CAMARF's ~89
    international symbols: resolve_gvkey_global's SQL is a PREFIX match
    (`conm ilike '{company_name}%%'`), but Compustat's own `conm` field uses
    abbreviated, punctuation-stripped, all-caps legal-entity conventions
    ("TOYOTA MOTOR CORP", not "Toyota Motor Corporation") -- passing
    yfinance's verbose longName directly as the prefix query fails for
    the OVERWHELMING majority of international names (confirmed: 60/88
    symbols returned "0 company matches" using the raw yfinance name,
    despite being real, correctly-named companies).

    This is intentionally AGGRESSIVE (strips "Holdings" too, which is
    sometimes part of a company's genuinely meaningful core name, e.g.
    "HSBC Holdings") -- safe specifically because the search is a PREFIX
    match, not exact: a shorter, more-stripped prefix can only make the
    match MORE permissive, and any resulting ambiguity (multiple companies
    sharing the shorter prefix) is still caught and refused by
    resolve_gvkey_global's existing != 1 match check, never silently
    guessed. Does not replace manual review for genuinely ambiguous or
    still-unresolved cases -- a targeted normalization aid, not a claim of
    fully automatic bulk resolution.
    """
    prev = None
    result = name
    while prev != result:
        prev = result
        result = _LEGAL_SUFFIX_PATTERN.sub("", result).strip().rstrip(",").strip()
    return result


def resolve_gvkey_global(db, company_name: str, currency: str) -> Optional[Tuple[str, str, str]]:
    """
    Name+currency-based GVKEY/IID resolution for Compustat Global.

    Returns (gvkey, iid, isin) for the row matching company_name (ILIKE,
    trailing wildcard) whose most recent real quote is denominated in
    `currency` -- e.g. currency='JPY' to get the primary Tokyo listing, not
    a secondary EUR/USD/BRL cross-listing of the same underlying company.

    Uses currency as a genuine DISAMBIGUATOR across ALL name-matched
    companies, not merely a listing lookup performed after already requiring
    the name match to be unique -- rewritten 2026-07-27 after finding the
    original single-company-then-currency design failed the overwhelming
    majority of a real batch of ~88 international symbols purely because
    common company names (e.g. "Shell", "Tesco", "Unilever") match several
    real, DIFFERENT companies in `g_company` (foreign subsidiaries, unrelated
    similarly-named firms) -- most of which don't share the target currency
    at all and were never genuinely competing candidates. Finds every
    name-matched gvkey, keeps only those with an ACTUAL `currency`-
    denominated listing, and resolves if exactly one remains -- if the
    currency filter still leaves 0 or >1 candidates, this is refused exactly
    as before (a genuine ambiguity, not silently guessed).
    """
    name_q = f"""
        select gvkey, conm from comp_global_daily.g_company
        where conm ilike '{company_name}%%'
    """
    companies = db.raw_sql(name_q)
    if companies.empty:
        log.warning(f"  resolve_gvkey_global('{company_name}'): 0 company-name matches")
        return None

    gvkeys_sql = ",".join(f"'{g}'" for g in companies["gvkey"].unique())
    listing_q = f"""
        select gvkey, iid, isin, curcdd, datadate,
               row_number() over (partition by gvkey order by datadate desc) as rn
        from comp_global_daily.g_secd
        where gvkey in ({gvkeys_sql}) and curcdd = '{currency}' and prccd is not null
    """
    all_listings = db.raw_sql(listing_q)
    latest_per_gvkey = all_listings[all_listings["rn"] == 1]

    if len(latest_per_gvkey) != 1:
        matched_names = companies.set_index("gvkey")["conm"].to_dict()
        candidates_desc = [matched_names.get(g, g) for g in latest_per_gvkey["gvkey"]] \
            if not latest_per_gvkey.empty else []
        log.warning(f"  resolve_gvkey_global('{company_name}'): {len(companies)} name matches, "
                    f"{len(latest_per_gvkey)} with a {currency}-denominated listing (need exactly 1) -- "
                    f"name matches: {companies['conm'].tolist()}"
                    + (f" | currency-matching: {candidates_desc}" if candidates_desc else ""))
        return None

    row = latest_per_gvkey.iloc[0]
    return str(row["gvkey"]), str(row["iid"]), str(row["isin"])


def fetch_symbol_global(db, gvkey: str, iid: str, start: Optional[str] = None) -> Optional[pd.DataFrame]:
    """
    Fetch one international symbol's full Compustat Global daily history.

    Split-adjusted only in this first pass ('close' = prccd / ajexdi) --
    verified against Toyota Motor's REAL 2021-10-01 5-for-1 split
    (gvkey=019661, iid='01W'): 10385/5.0=2077, continuous with the next
    trading day's 2073.

    Total-return (dividend) adjustment is deliberately NOT attempted here.
    g_secd has a `trfd` field that Compustat documents as a total-return
    factor, analogous in spirit to CRSP's dlyret used for close_total_return
    in fetch_symbol() above -- but its exact combination convention with
    prccd/ajexdi was not verified against a known dividend event the same
    rigorous way the split adjustment was, so it is not used. Flagged as a
    real follow-up, not silently assumed to work the same way as CRSP's.
    """
    q = f"""
        select datadate, prcod, prchd, prcld, prccd, cshtrd, ajexdi
        from comp_global_daily.g_secd
        where gvkey = '{gvkey}' and iid = '{iid}'
        {f"and datadate >= '{start}'" if start else ""}
        and datadate <= current_date
        order by datadate
    """
    df = db.raw_sql(q)
    if df.empty:
        log.warning(f"  gvkey={gvkey}/iid={iid}: no g_secd rows returned")
        return None

    df["datadate"] = pd.to_datetime(df["datadate"])
    df = df.set_index("datadate")
    fac = df["ajexdi"].replace(0, pd.NA)
    out = pd.DataFrame({
        "open": df["prcod"] / fac,
        "high": df["prchd"] / fac,
        "low": df["prcld"] / fac,
        "close": df["prccd"] / fac,
        "volume": df["cshtrd"],
    })
    out.index.name = None
    return out


def fetch_symbols_bulk_global(db, label_by_gvkey_iid: Dict[str, Tuple[str, str]], start: Optional[str] = None,
                               batch_size: int = 200):
    """
    Bulk version of fetch_symbol_global -- fetches many (gvkey, iid) pairs'
    g_secd history in chunked batches, mirroring fetch_symbols_bulk's exact
    pattern for CRSP (same batching/generator/incremental-persistence
    design, added 2026-07-27 for the international-index-expansion fetch).

    `label_by_gvkey_iid` maps {label: (gvkey, iid)} -- label is whatever the
    caller wants used for the output filename (there is no natural "ticker"
    for most of these international index constituents the way CRSP/US
    symbols have one, so callers typically use a `GVKEY{gvkey}_{iid}`-style
    label -- see build_global_symbol_label).

    Generator, yielding (label, df) per batch -- same incremental-
    persistence reasoning as fetch_symbols_bulk: a crash mid-run only loses
    the current batch, not everything fetched so far.

    Split-adjusted only (same as fetch_symbol_global) -- total-return
    reconstruction via `trfd` remains unverified/not attempted, same
    disclosed limitation as the single-symbol version.
    """
    gvkey_iid_by_label = dict(label_by_gvkey_iid)
    pairs = list(gvkey_iid_by_label.values())

    for i in range(0, len(pairs), batch_size):
        batch = pairs[i:i + batch_size]
        values_sql = ",".join(f"('{g}','{iid}')" for g, iid in batch)
        start_clause = f"and datadate >= '{start}'" if start else ""
        q = f"""
            select gvkey, iid, datadate, prcod, prchd, prcld, prccd, cshtrd, ajexdi
            from comp_global_daily.g_secd
            where (gvkey, iid) in ({values_sql})
            {start_clause}
            and datadate <= current_date
            order by gvkey, iid, datadate
        """
        chunk = db.raw_sql(q)
        if chunk.empty:
            log.warning(f"  batch {i}-{i+len(batch)}: no rows returned for {len(batch)} (gvkey,iid) pairs")
            continue
        chunk["datadate"] = pd.to_datetime(chunk["datadate"])

        label_by_pair = {v: k for k, v in gvkey_iid_by_label.items()}
        n_in_batch = 0
        for (gvkey, iid), g in chunk.groupby(["gvkey", "iid"]):
            label = label_by_pair.get((gvkey, iid))
            if label is None:
                continue
            g = g.set_index("datadate").sort_index()
            fac = g["ajexdi"].replace(0, pd.NA)
            df = pd.DataFrame({
                "open": g["prcod"] / fac,
                "high": g["prchd"] / fac,
                "low": g["prcld"] / fac,
                "close": g["prccd"] / fac,
                "volume": g["cshtrd"],
            })
            n_in_batch += 1
            yield label, df
        log.info(f"  batch {i}-{i+len(batch)}/{len(pairs)}: {n_in_batch} symbols fetched")


def build_global_symbol_label(gvkey: str, iid: str) -> str:
    """
    Human-inspectable, guaranteed-unique file-naming label for a Compustat
    Global (gvkey, iid) pair with no natural ticker -- most international
    index constituents don't have one the way CRSP/US symbols do (see
    fetch_symbols_bulk_global's docstring). Format: GVKEY{gvkey}_{iid} --
    deliberately verbose/unambiguous rather than attempting to derive a
    ticker-like label that could collide with an existing CRSP-ticker-based
    filename (the exact class of bug already fixed once this session for
    the delisted-S&P-500 label-collision case).
    """
    return f"GVKEY{gvkey}_{iid}"


# =============================================================================
# SECTION: FX (Federal Reserve exchange rates, `frb_all.fx_daily`)
# =============================================================================
# Added 2026-07-27 per Ross's direct request to check what WRDS has for FX/
# commodities/crypto/futures ("replace yfinance where we can"). Researched
# broadly (see Development.md for the full inventory) before building
# anything -- concrete findings:
#   - FX: real, substantial, genuinely usable -- `frb_all.fx_daily`/
#     `fx_monthly`, Federal Reserve Board data, one wide table (one column
#     per currency pair, e.g. `dexjpus`=JPY/USD, `dexuseu`=USD/EUR), back to
#     1971-01-04 -- this section.
#   - Commodities: NOT FOUND. Checked broadly (commod/futures/cftc/nymex/
#     cme/gold/oil/metal/energy/agri/grain/wti/brent/wrdscomm/ice_/bbg/
#     bloomberg -- all zero library matches). Not a scope choice: this
#     WRDS subscription does not appear to carry a dedicated commodity
#     price product at all.
#   - Crypto: NOT FOUND (matches Ross's own expectation -- WRDS is an
#     academic equity/fixed-income-focused platform, crypto price data
#     isn't a typical product here; zero library matches for
#     crypto/bitcoin/btc/coin).
#   - Futures: found `trsamp_dsfut` (Thomson Reuters/Refinitiv Datastream
#     futures) -- genuinely real data (13.7M rows, back to at least 2006,
#     NOT a toy sample despite the "samp" in its name), but stored in an
#     unusual long-format table mixing metadata descriptor rows with actual
#     price rows (distinguished by a `_name_` field) -- needs real
#     structural investigation before it's usable, flagged as a follow-up,
#     not built here. `optionmsamp_us`/`optionmsamp_europe` (OptionMetrics)
#     also present but similarly named like the confirmed-sample-only TAQ
#     product -- not investigated further given it's off-thesis for CAMARF's
#     current scope (options.py already exists as a separate, non-WRDS
#     comparison arm).
#
# IMPORTANT LIMITATION, found directly: `fx_daily`'s most recent date is
# 2025-02-07 -- over 5 months stale relative to CRSP/Compustat's own data in
# this same account (through late 2025/2026). This table is NOT a live/
# current data replacement -- its real value is the 1971-2025 historical
# DEPTH for backtesting, not as a current-data source. Any live/current FX
# need stays on yfinance's existing fx_spot path.

_FX_COLUMN_TO_LABEL = {
    "dexjpus": "USDJPY", "dexuseu": "EURUSD", "dexusuk": "GBPUSD", "dexukus": "USDGBP",
    "dexcaus": "USDCAD", "dexchus": "USDCNY", "dexhkus": "USDHKD", "dexinus": "USDINR",
    "dexkous": "USDKRW", "dexmxus": "USDMXN", "dexsfus": "USDZAR", "dexszus": "USDCHF",
    "dexsius": "USDSGD", "dextaus": "USDTWD", "dexthus": "USDTHB", "dexbzus": "USDBRL",
    "dexalus": "USDAUD", "dexusal": "AUDUSD", "dexnzus": "USDNZD", "dexusnz": "NZDUSD",
    "dexnous": "USDNOK", "dexsdus": "USDSEK", "dexdnus": "USDDKK", "dexmaus": "USDMYR",
    "dexslus": "USDLKR", "dexvzus": "USDVES",
}


def fetch_fx_wrds(db) -> Dict[str, pd.Series]:
    """
    Fetches every FX series in frb_all.fx_daily, labeled by the currency
    pair it represents (see _FX_COLUMN_TO_LABEL -- Fed column names like
    'dexjpus' aren't self-describing, mapped to conventional pair labels
    like 'USDJPY'). Returns {label: pd.Series} indexed by date, NOT written
    to output/cache/wrds/ automatically -- caller decides persistence, since
    this is a single small table fetch, not a per-symbol bulk pattern like
    the rest of this file.

    STALENESS WARNING (see section docstring above): this table's most
    recent date is 2025-02-07, not current -- do not use this as a live FX
    data source, only for its 1971+ historical depth.
    """
    q = f"""
        select date, {", ".join(_FX_COLUMN_TO_LABEL.keys())}
        from frb_all.fx_daily
        order by date
    """
    df = db.raw_sql(q)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    out = {}
    for col, label in _FX_COLUMN_TO_LABEL.items():
        if col in df.columns:
            series = pd.to_numeric(df[col], errors="coerce").dropna()
            if not series.empty:
                out[label] = series
    log.info(f"Fetched {len(out)} FX series from frb_all.fx_daily "
             f"(1971-01-04 through {df.index.max().date()} -- STALE, see staleness warning)")
    return out


def main():
    p = argparse.ArgumentParser(description="CAMARF WRDS/CRSP data pipeline")
    p.add_argument("--symbols", nargs="+", default=None, help="Specific symbols (default: full US equity/ETF universe)")
    p.add_argument("--start", default=None, help="History start date (YYYY-MM-DD), default: full available history")
    p.add_argument("--dry-run", action="store_true", help="Resolve PERMNOs and print counts, fetch nothing")
    p.add_argument("--batch-size", type=int, default=200, help="Symbols per bulk dsf_v2 query")
    p.add_argument("--skip-delisted-sp500", action="store_true",
                    help="Skip the survivorship-bias-fix pass (historically-delisted S&P 500 members)")
    p.add_argument("--only-delisted-sp500", action="store_true",
                    help="Skip the main universe fetch entirely (assumes it already ran) and go "
                         "straight to the delisted-S&P-500 survivorship-bias-fix pass")
    p.add_argument("--only-fx", action="store_true",
                    help="Skip everything else and just fetch frb_all.fx_daily FX series")
    args = p.parse_args()

    fh = logging.FileHandler(_LOG_PATH, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    log.addHandler(fh)

    if args.only_fx:
        db = _connect()
        os.makedirs(_OUT_DIR, exist_ok=True)
        fx_series = fetch_fx_wrds(db)
        for label, series in fx_series.items():
            series.to_frame("close").to_parquet(os.path.join(_OUT_DIR, f"FX_{label}_1D.parquet"))
        log.info(f"--only-fx complete: {len(fx_series)} FX series saved to output/cache/wrds/FX_*_1D.parquet")
        return

    symbols = args.symbols if args.symbols else _get_universe_us_equity_etf_symbols()
    log.info(f"CAMARF data_wrds.py -- {len(symbols)} US equity/ETF symbols targeted (bulk mode)")

    db = _connect()
    os.makedirs(_OUT_DIR, exist_ok=True)

    t0 = time.time()
    # Bulk resolve ALL tickers to PERMNOs in one round trip (chunked at 500
    # tickers per IN-list to stay comfortably under typical query-length
    # limits), instead of one round trip per symbol.
    permno_by_symbol: Dict[str, int] = {}
    for i in range(0, len(symbols), 500):
        chunk = symbols[i:i + 500]
        permno_by_symbol.update(resolve_permnos_bulk(db, chunk))
    n_unresolved = len(symbols) - len(permno_by_symbol)
    log.info(f"Resolved {len(permno_by_symbol)}/{len(symbols)} symbols to PERMNOs "
             f"({n_unresolved} not found)")

    if args.dry_run:
        for sym in symbols:
            status = f"PERMNO {permno_by_symbol[sym]}" if sym in permno_by_symbol else "NOT RESOLVED"
            log.info(f"  {sym}: {status}")
        return

    derived_tfs = list(_RESAMPLE_RULES)  # ["7D", "3M", "6M", "1Y"]

    if not args.only_delisted_sp500:
        # Persist each batch to disk AS IT ARRIVES (fetch_symbols_bulk is a
        # generator specifically for this reason) -- a crash mid-run only loses
        # the current batch, not every symbol fetched so far.
        #
        # Every derived timeframe (7D/3M/6M/1Y) is produced from the SAME daily
        # fetch via resample_daily_to -- no separate query per derived TF -- so
        # this loop is still one dsf_v2 round trip per batch, same cost as the
        # 1D-only version, just more files written per symbol.
        n_saved = 0
        for sym, df in fetch_symbols_bulk(db, permno_by_symbol, start=args.start, batch_size=args.batch_size):
            df.to_parquet(os.path.join(_OUT_DIR, f"{sym}_1D.parquet"))
            for tf in derived_tfs:
                resampled = resample_daily_to(df, tf)
                if resampled is not None and not resampled.empty:
                    resampled.to_parquet(os.path.join(_OUT_DIR, f"{sym}_{tf}.parquet"))
            n_saved += 1

        n_failed = len(symbols) - n_saved
        log.info(f"Daily+derived pass complete in {(time.time()-t0)/60:.1f} min: "
                 f"{n_saved} saved, {n_failed} failed/unresolved")

        # Native monthly (msf_v2) -- CRSP's own authoritative monthly file, NOT a
        # resample of the daily bars above (see fetch_monthly_bulk's docstring --
        # own mthret field, own split-adjustment factor, own recordkeeping).
        # Second full pass over the same permno_by_symbol mapping already resolved
        # above -- no re-resolution needed.
        t1 = time.time()
        n_monthly = 0
        for sym, df in fetch_monthly_bulk(db, permno_by_symbol, start=args.start, batch_size=args.batch_size):
            df.to_parquet(os.path.join(_OUT_DIR, f"{sym}_1M.parquet"))
            n_monthly += 1
        log.info(f"Native monthly pass complete in {(time.time()-t1)/60:.1f} min: {n_monthly} saved")
    else:
        log.info("--only-delisted-sp500: skipping the main universe fetch (assumed already run), "
                 "going straight to the survivorship-bias-fix pass.")

    # -------------------------------------------------------------------
    # Survivorship-bias fix: fetch historically-delisted S&P 500 members
    # that the ticker-based universe above never touches, since they aren't
    # in today's Wikipedia-scraped constituent table at all. See the
    # "SECTION: S&P 500 point-in-time membership" functions above.
    # -------------------------------------------------------------------
    if not args.skip_delisted_sp500 and args.symbols is None:
        t2 = time.time()
        membership_df = fetch_sp500_membership_history(db)
        delisted_permnos = get_delisted_sp500_permnos(membership_df, set(permno_by_symbol.values()))
        log.info(f"Survivorship-bias fix: {len(delisted_permnos)} historically-delisted S&P 500 "
                 f"permnos not covered by the ticker-based universe above -- fetching their full history.")

        labels = resolve_last_known_tickers(db, list(delisted_permnos))
        delisted_permno_by_label = build_delisted_label_map(
            delisted_permnos, labels, active_ticker_labels=set(permno_by_symbol.keys())
        )
        n_relabeled = sum(
            1 for label, p in delisted_permno_by_label.items()
            if label != labels.get(p, f"PERMNO{p}")
        )
        if n_relabeled:
            log.warning(f"  {n_relabeled} label collision(s) with an active ticker or another delisted "
                        f"permno's last-known ticker -- re-labeled as PERMNO<n> to avoid overwriting "
                        f"a live symbol's file")

        n_delisted_daily = 0
        for label, df in fetch_symbols_bulk(db, delisted_permno_by_label, start=args.start, batch_size=args.batch_size):
            df.to_parquet(os.path.join(_OUT_DIR, f"{label}_1D.parquet"))
            for tf in derived_tfs:
                resampled = resample_daily_to(df, tf)
                if resampled is not None and not resampled.empty:
                    resampled.to_parquet(os.path.join(_OUT_DIR, f"{label}_{tf}.parquet"))
            n_delisted_daily += 1
        n_delisted_monthly = 0
        for label, df in fetch_monthly_bulk(db, delisted_permno_by_label, start=args.start, batch_size=args.batch_size):
            df.to_parquet(os.path.join(_OUT_DIR, f"{label}_1M.parquet"))
            n_delisted_monthly += 1
        log.info(f"Survivorship-bias fix complete in {(time.time()-t2)/60:.1f} min: "
                 f"{n_delisted_daily} delisted S&P 500 symbols fetched (daily+derived), "
                 f"{n_delisted_monthly} (monthly)")

    log.info(f"ALL DONE in {(time.time()-t0)/60:.1f} min total. "
             f"Timeframes written per symbol: 1D, 1M (native), {', '.join(derived_tfs)} (derived).")


if __name__ == "__main__":
    main()
