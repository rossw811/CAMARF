"""
research/international_liquidity_filter.py -- Step 2 of Ross's request
(2026-08-12): "run a test to see which tickers have actually liquid values
and then use those. we run it once entirely then we have a filtered list."

MUST BE RUN BY ROSS: needs a live WRDS connection (currency-code lookup) --
same Duo 2FA constraint as the fetch step. Run AFTER research/wrds_global_
index_universe_fetch.py has populated output/cache/wrds/GVKEY*_1D.parquet
(can be run against a partial/in-progress fetch too -- just filters whatever
labels are currently cached against the manifest).

    C:\\Users\\RossW\\anaconda3\\envs\\trading\\python.exe research/international_liquidity_filter.py

Method, stated precisely:
  1. Load the manifest (label, gvkey, iid, indices) from the fetch step.
  2. For each cached symbol, look up its trading currency (`curcdd` from
     comp_global_daily.g_secd -- the SAME field already used elsewhere in
     data_wrds.py for currency disambiguation, not a new assumption).
  3. Convert local-currency dollar volume to USD. WRDS's own FX table
     (frb_all.fx_daily) is STALE past 2025-02-07 (disclosed limitation in
     data_wrds.py's FX section) -- NOT used here, since this fetch's price
     data runs through 2026. Uses a recent yfinance FX snapshot instead
     (already a proven, in-use dependency in this project) for the current
     conversion rate per currency.
  4. Average daily dollar volume (USD) over a RECENT TRAILING WINDOW (not
     full history -- same reasoning Ross already raised for the CRSP ADV
     case: an 80-100-year flat average blends incomparable liquidity
     regimes). Default: last 504 trading days (~2 years) of whatever's
     cached, or all available if shorter.
  5. Apply Config.DATA.MIN_DOLLAR_VOLUME (the SAME threshold the domestic
     universe already uses -- $1,000,000/day, see data.py's own illiquid-
     symbol filter) -- no separate, unexplained bar for international names.
  6. Output: output/research/international_liquidity_filter.parquet, every
     symbol with its computed USD ADV and a `passes_threshold` bool, plus
     output/research/international_liquid_universe.parquet, just the
     symbols that pass -- the "filtered list" Ross asked for.

This is a preliminary universe-inclusion filter (matches data_wrds.py's own
established convention for "is this worth including" administrative
decisions), NOT a point-in-time backtest gate -- a genuinely PIT-safe
rolling liquidity check (if these symbols get traded) is a separate,
later step, same distinction already established for the domestic
rolling_adv_comparison.py work.
"""
import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from config import Config
from data_wrds import _connect, _OUT_DIR

log = logging.getLogger("international_liquidity_filter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
# Persistent log file -- the 2026-08-12 run hung with zero observability
# (stdout only, no file, so nothing was inspectable without terminal access).
# Fixed same day, mirroring wrds_global_index_universe_fetch.py's own
# FileHandler convention.
_LOG_FILE_PATH = "latest_run_international_liquidity_filter.log"
_fh = logging.FileHandler(_LOG_FILE_PATH, mode="w", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
log.addHandler(_fh)

_MANIFEST_PATH = os.path.join(_OUT_DIR, "global_universe_manifest.parquet")
_OUT_ALL = os.path.join("output", "research", "international_liquidity_filter.parquet")
_OUT_LIQUID = os.path.join("output", "research", "international_liquid_universe.parquet")
_TRAILING_DAYS = 504  # ~2 years of trading days -- avoids the flat-multi-decade-average
                       # problem already raised for the domestic CRSP ADV case


def fetch_currency_codes(db_getter, gvkey_iid_pairs: list, max_retries: int = 20) -> dict:
    """One representative curcdd per (gvkey, iid) -- most recent row within a
    recent trailing window.

    SEQUENTIAL PER-PAIR queries, NOT batched -- real, measured evidence found
    2026-08-13 that batching is actually SLOWER here, not faster: a bare
    `where gvkey='X' and iid='Y' order by datadate desc limit 1` resolved in
    0.11s, while EVERY batched alternative tried -- `(gvkey,iid) IN (...)`
    with 500 tuples (original), the same IN-tuple form with a `datadate >=
    recent cutoff` bound added, and a `JOIN (VALUES ...) v ON s.gvkey=v.gvkey
    AND s.iid=v.iid` restructure -- measured a consistent ~0.55-0.65s/pair
    wall REGARDLESS of query shape (20 pairs: 11-13s either way; 500 pairs:
    still timed out at 120s). This points to `comp_global_daily.g_secd`
    lacking a composite index the planner can use for multi-tuple (gvkey,
    iid) matching, not to any one query phrasing being wrong -- single-
    equality lookups use whatever index exists per-gvkey cleanly; multi-
    tuple predicates apparently don't, for any of the 3 shapes tried. Real
    original bug this replaced: the un-bounded-date batched query hung the
    2026-08-12 run for 8+ hours with zero observability (root-caused and
    partially fixed same day via a statement_timeout + retry loop, but that
    only converted a silent hang into a LOUD, equally-doomed 20-retry loop
    that would still exhaust itself and fail, since the retries kept
    resending the same oversized, structurally-slow batch).

    Real, understood cost of this fix: ~0.15s/pair x 15,094 pairs =~ 38
    minutes, sequential -- same order of magnitude as this session's other
    real WRDS fetches, not a guess.

    RESUMABLE across connection drops: reconnects via `db_getter()` (a
    zero-arg callable, e.g. `_connect_with_retry`) on any single-pair query
    failure, retrying that one pair rather than restarting a whole batch.
    """
    out = {}
    db = db_getter()
    attempt = 0
    for i, (g, iid) in enumerate(gvkey_iid_pairs):
        q = f"""
            select curcdd
            from comp_global_daily.g_secd
            where gvkey = '{g}' and iid = '{iid}'
            and datadate >= current_date - interval '400 days'
            order by datadate desc
            limit 1
        """
        while True:
            try:
                row = db.raw_sql(q)
                break
            except Exception as e:
                attempt += 1
                log.warning(f"  currency lookup for ({g},{iid}) failed ({e}). "
                            f"{len(out)}/{len(gvkey_iid_pairs)} resolved so far. "
                            f"Reconnecting (attempt {attempt}/{max_retries})...")
                if attempt >= max_retries:
                    log.error(f"Giving up after {attempt} interrupted attempts.")
                    raise
                time.sleep(min(60.0, 10.0 * attempt))
                db = db_getter()
        if not row.empty:
            out[(g, iid)] = row.iloc[0]["curcdd"]
        if (i + 1) % 500 == 0:
            log.info(f"  currency lookup: {i + 1}/{len(gvkey_iid_pairs)} pairs checked, "
                     f"{len(out)} resolved")
    log.info(f"  currency lookup complete: {len(out)}/{len(gvkey_iid_pairs)} resolved")
    return out


def usd_conversion_rate(currency: str) -> float:
    """Returns the multiplier to convert 1 unit of `currency` to USD, using a
    recent yfinance snapshot (WRDS's own FX table is stale past 2025-02-07,
    see module docstring -- not usable for this fetch's 2026 price data).
    Tries the 'USD{ccy}=X' convention first (units of ccy per 1 USD -> invert),
    falls back to '{ccy}USD=X' (USD per unit) if that's empty. Prints the
    resolved rate so it can be eyeballed for sanity (e.g. JPY should land
    around 100-160, EUR around 0.85-0.95) before trusting the output."""
    if currency == "USD":
        return 1.0
    import yfinance as yf

    for ticker, invert in ((f"USD{currency}=X", True), (f"{currency}USD=X", False)):
        try:
            # 2026-08-12 real run: this call has no timeout by default and the
            # process hung indefinitely with zero CPU movement for 40+ minutes
            # -- an untimed network stall is the leading suspect (no other
            # blocking call in this script's main path lacks one). Explicit
            # timeout added so a stall fails loud and moves on, not hangs forever.
            hist = yf.Ticker(ticker).history(period="5d", timeout=30)
            if hist.empty:
                continue
            rate = float(hist["Close"].dropna().iloc[-1])
            mult = (1.0 / rate) if invert else rate
            log.info(f"  {currency}: resolved via {ticker} -> 1 {currency} = {mult:.6f} USD "
                      f"(raw rate {rate:.4f}, invert={invert}) -- SANITY CHECK THIS")
            return mult
        except Exception as e:
            log.warning(f"  {currency}: {ticker} failed ({e}), trying fallback")
            continue
    log.warning(f"  {currency}: could not resolve a USD conversion rate -- excluded from filter")
    return float("nan")


def main():
    p = argparse.ArgumentParser(description="Liquidity-filter the fetched international universe")
    p.add_argument("--trailing-days", type=int, default=_TRAILING_DAYS)
    p.add_argument("--min-dollar-volume", type=float, default=Config.DATA.MIN_DOLLAR_VOLUME)
    args = p.parse_args()

    if not os.path.exists(_MANIFEST_PATH):
        print(f"FATAL: {_MANIFEST_PATH} not found -- run wrds_global_index_universe_fetch.py first")
        sys.exit(1)
    manifest = pd.read_parquet(_MANIFEST_PATH)

    cached = manifest[manifest["label"].apply(
        lambda lbl: os.path.exists(os.path.join(_OUT_DIR, f"{lbl}_1D.parquet")))]
    log.info(f"{len(cached)}/{len(manifest)} manifest symbols currently cached "
             f"(safe to run against a partial fetch).")
    if cached.empty:
        print("No cached symbols yet -- nothing to filter.")
        return

    from research.wrds_global_index_universe_fetch import _connect_with_retry
    pairs = list(zip(cached["gvkey"], cached["iid"]))
    currency_by_pair = fetch_currency_codes(_connect_with_retry, pairs)

    # Real bug hit on the actual run (2026-08-13): some curcdd values come back
    # as float('nan') (pandas' missing-value representation), not None -- a
    # bare `- {None}` doesn't remove NaN (nan != None), so sorted() choked
    # comparing float against str. Filter to genuine, non-null strings only.
    currencies_needed = sorted({
        v for v in currency_by_pair.values() if isinstance(v, str) and v
    })
    log.info(f"Resolving USD conversion for {len(currencies_needed)} currencies: {currencies_needed}")
    usd_mult_by_ccy = {ccy: usd_conversion_rate(ccy) for ccy in currencies_needed}

    rows = []
    t0 = time.time()
    for i, (_, r) in enumerate(cached.iterrows()):
        if i > 0 and i % 500 == 0:
            log.info(f"  progress: {i}/{len(cached)} symbols evaluated ({(time.time()-t0)/60:.1f} min elapsed)")
        pair = (r["gvkey"], r["iid"])
        ccy = currency_by_pair.get(pair)
        # Real bug hit on the actual run (2026-08-14): `curcdd` can come back as
        # pandas nullable-string pd.NA (not None, not float NaN) -- `if ccy` on a
        # pd.NA raises `TypeError: boolean value of NA is ambiguous`, not a clean
        # falsy check. SAME bug class already found and fixed once this session in
        # data_wrds.py's build_full_market_label_map (BUG class: pandas pd.NA
        # round-trips inconsistently through dict conversion, defeating any
        # truthiness/`is not None`/`pd.notna()` check -- only a strict isinstance
        # check is reliable). Recurred independently here since this is a
        # different file/code path, not a fix that automatically propagated.
        mult = usd_mult_by_ccy.get(ccy, float("nan")) if isinstance(ccy, str) and ccy else float("nan")
        path = os.path.join(_OUT_DIR, f"{r['label']}_1D.parquet")
        try:
            df = pd.read_parquet(path)
        except Exception as e:
            log.warning(f"  {r['label']}: could not read {path} ({e})")
            continue
        if df.empty:
            continue
        recent = df.tail(args.trailing_days)
        dollar_vol_local = (recent["close"] * recent["volume"]).replace([np.inf, -np.inf], np.nan).dropna()
        if dollar_vol_local.empty or not np.isfinite(mult):
            avg_adv_usd = float("nan")
        else:
            avg_adv_usd = float(dollar_vol_local.mean()) * mult
        rows.append({
            "label": r["label"], "gvkey": r["gvkey"], "iid": r["iid"],
            "currency": ccy, "usd_conversion_rate": mult,
            "n_bars_used": len(recent), "avg_dollar_volume_usd": avg_adv_usd,
            "n_indices": r["n_indices"], "indices": r["indices"],
            "passes_threshold": bool(np.isfinite(avg_adv_usd) and avg_adv_usd >= args.min_dollar_volume),
        })

    out_df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(_OUT_ALL), exist_ok=True)
    out_df.to_parquet(_OUT_ALL, index=False)
    liquid_df = out_df[out_df["passes_threshold"]].sort_values("avg_dollar_volume_usd", ascending=False)
    liquid_df.to_parquet(_OUT_LIQUID, index=False)

    log.info(f"Filter complete: {len(out_df)} symbols evaluated, {len(liquid_df)} pass "
             f"MIN_DOLLAR_VOLUME=${args.min_dollar_volume:,.0f}/day "
             f"({100*len(liquid_df)/max(len(out_df),1):.1f}%).")
    log.info(f"All results -> {_OUT_ALL}")
    log.info(f"Filtered liquid universe -> {_OUT_LIQUID}")
    print(liquid_df.head(30).to_string(index=False))


if __name__ == "__main__":
    main()
