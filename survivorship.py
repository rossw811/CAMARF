"""
survivorship.py — S&P 500 historical constituent changes scraper

Builds survivorship_exclusions.csv from Wikipedia's S&P 500 changes table.
Each row is a stock that was removed (delisted, acquired, demoted), with the
date it was removed from the index.

Usage in the backtest pipeline:
  - For pairs involving a delisted symbol, set oos_end_date = removed_date
  - The pair is a legitimate OOS observation up to that date; excluded after
  - This converts survivorship bias from a binary block into a WFA-style boundary

Output: output/cache/survivorship_exclusions.csv
Columns: symbol, removed_date, reason, added_symbol (what replaced it)

Run: python survivorship.py
"""

import os
import sys
import logging
import time
import re
from io import StringIO
from typing import Optional

import pandas as pd
import requests

_ROOT = os.path.dirname(os.path.abspath(__file__))
_OUT_PATH = os.path.join(_ROOT, "output", "cache", "survivorship_exclusions.csv")
_ADDITIONS_OUT_PATH = os.path.join(_ROOT, "output", "cache", "index_additions.csv")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

log = logging.getLogger("survivorship")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")


def _clean_symbol(s: str) -> str:
    return str(s).strip().upper().replace(".", "-")


def _parse_date(s: str) -> Optional[str]:
    """Try to parse various date formats from Wikipedia tables."""
    s = str(s).strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y", "%d %B %Y"):
        try:
            return pd.to_datetime(s, format=fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    # Fallback: let pandas guess
    try:
        return pd.to_datetime(s).strftime("%Y-%m-%d")
    except Exception:
        return None


def fetch_changes_table() -> pd.DataFrame:
    """
    Scrape the S&P 500 Wikipedia page for historical changes.
    The changes table is titled 'Changes to the list' and has columns:
    Date, Added ticker, Added security, Removed ticker, Removed security, Reason
    """
    try:
        resp = requests.get(_URL, headers={"User-Agent": _UA}, timeout=20)
        if resp.status_code != 200:
            log.warning("HTTP %d from Wikipedia", resp.status_code)
            return pd.DataFrame()
        tables = pd.read_html(StringIO(resp.text))
    except Exception as e:
        log.error("Fetch failed: %s", e)
        return pd.DataFrame()

    log.info("Found %d tables on the page", len(tables))

    # The changes table has "Removed" and "Added" columns and "Date" column
    best: Optional[pd.DataFrame] = None
    best_score = 0
    for i, t in enumerate(tables):
        cols_lower = " ".join(str(c).lower() for c in t.columns)
        score = sum([
            "date" in cols_lower,
            "removed" in cols_lower,
            "added" in cols_lower,
            "reason" in cols_lower,
        ])
        if score > best_score:
            best_score = score
            best = t
            log.debug("Table[%d] score=%d cols=%s", i, score, list(t.columns))

    if best is None or best_score < 2:
        log.warning("Could not identify changes table (best score: %d)", best_score)
        return pd.DataFrame()

    log.info("Using changes table with %d rows, %d cols, score=%d", len(best), len(best.columns), best_score)
    log.info("Columns: %s", list(best.columns))

    # Normalize columns
    rename = {}
    for col in best.columns:
        cl = str(col).lower().strip()
        if cl == "date" or "date" in cl:
            rename[col] = "date"
        elif "removed" in cl and "ticker" in cl:
            rename[col] = "removed_ticker"
        elif "removed" in cl and ("security" in cl or "company" in cl or "name" in cl):
            rename[col] = "removed_name"
        elif "added" in cl and "ticker" in cl:
            rename[col] = "added_ticker"
        elif "added" in cl and ("security" in cl or "company" in cl or "name" in cl):
            rename[col] = "added_name"
        elif "reason" in cl:
            rename[col] = "reason"
    best = best.rename(columns=rename)
    return best


def build_exclusions(changes_df: pd.DataFrame) -> pd.DataFrame:
    """
    From the raw changes table, extract rows where a stock was REMOVED.
    Returns a clean DataFrame with: symbol, removed_date, reason, added_symbol.
    """
    if len(changes_df) == 0:
        return pd.DataFrame()

    # Identify the removed ticker column
    removed_col = None
    for col in ["removed_ticker", "removed_name"]:
        if col in changes_df.columns:
            removed_col = col
            break

    if removed_col is None:
        # Try to find it from available columns
        for col in changes_df.columns:
            if "removed" in str(col).lower():
                removed_col = col
                break

    if removed_col is None:
        log.warning("No 'removed ticker' column found in changes table. Columns: %s", list(changes_df.columns))
        return pd.DataFrame()

    date_col = "date" if "date" in changes_df.columns else None
    if date_col is None:
        for col in changes_df.columns:
            if "date" in str(col).lower():
                date_col = col
                break

    rows = []
    for _, row in changes_df.iterrows():
        removed_raw = str(row.get(removed_col, "")).strip()
        if not removed_raw or removed_raw.lower() in ("nan", "none", ""):
            continue

        symbol = _clean_symbol(removed_raw)
        if not symbol or len(symbol) > 10 or symbol in ("NAN", "NONE", "-"):
            continue

        date_raw = str(row.get(date_col, "")) if date_col else ""
        removed_date = _parse_date(date_raw)

        reason = str(row.get("reason", "")).strip()
        added_ticker = str(row.get("added_ticker", "")).strip()
        added_symbol = _clean_symbol(added_ticker) if added_ticker and added_ticker.lower() != "nan" else ""

        rows.append({
            "symbol": symbol,
            "removed_date": removed_date,
            "reason": reason,
            "added_symbol": added_symbol,
        })

    if not rows:
        log.warning("No removal rows extracted from changes table")
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    # Drop rows with unparseable dates or clearly bad symbols
    out = out.dropna(subset=["removed_date"])
    out = out[out["symbol"].str.match(r"^[A-Z][A-Z0-9\-\.]{0,8}$")]
    out = out.drop_duplicates(subset=["symbol", "removed_date"])
    out = out.sort_values("removed_date", ascending=False).reset_index(drop=True)

    log.info("Extracted %d removal events", len(out))
    return out


def fetch_current_constituents_with_dates() -> pd.DataFrame:
    """
    Fetches the S&P 500 Wikipedia page's CURRENT constituents table (table
    index 0), which carries a clean, ISO-formatted "Date added" column per
    symbol directly -- 0 missing values as of 2026-08-11's live check
    (503/503 symbols).

    REPLACES the original plan of parsing per-row additions out of a
    historical "Changes to the list" table: found live, 2026-08-11, that
    table NO LONGER EXISTS on this Wikipedia page (only 2 tables present now:
    the current constituents table, and a navigation template) -- a real
    Wikipedia page-structure change, not a scraper bug. This ALSO means
    fetch_changes_table()/build_exclusions() (the pre-existing removals
    scraper) is now broken the same way; NOT fixed here (separate scope) --
    the cached output/cache/survivorship_exclusions.csv from a prior
    successful run remains valid and in use, it just can no longer be
    refreshed by re-running this script until that scraper is separately
    fixed to find wherever Wikipedia moved the changes log, if anywhere.
    """
    try:
        resp = requests.get(_URL, headers={"User-Agent": _UA}, timeout=20)
        if resp.status_code != 200:
            log.warning("HTTP %d from Wikipedia", resp.status_code)
            return pd.DataFrame()
        tables = pd.read_html(StringIO(resp.text))
    except Exception as e:
        log.error("Fetch failed: %s", e)
        return pd.DataFrame()

    if not tables:
        return pd.DataFrame()
    t = tables[0]
    cols_lower = {str(c).lower(): c for c in t.columns}
    symbol_col = cols_lower.get("symbol")
    date_col = next((c for cl, c in cols_lower.items() if "date added" in cl), None)
    if symbol_col is None or date_col is None:
        log.warning("Current-constituents table missing Symbol/Date added columns: %s", list(t.columns))
        return pd.DataFrame()

    out = t[[symbol_col, date_col]].rename(columns={symbol_col: "symbol", date_col: "added_date"})
    out["symbol"] = out["symbol"].apply(_clean_symbol)
    out["added_date"] = out["added_date"].apply(_parse_date)
    out = out.dropna(subset=["added_date"])
    out = out[out["symbol"].str.match(r"^[A-Z][A-Z0-9\-\.]{0,8}$")]
    out = out.drop_duplicates(subset=["symbol"], keep="first").reset_index(drop=True)
    log.info("Extracted %d current-constituent addition dates", len(out))
    return out


def build_additions(constituents_df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalizes fetch_current_constituents_with_dates()' output to the
    (symbol, added_date) contract get_member_since_date() expects -- kept as
    a separate function (rather than inlining into the fetch) so
    debug/_verify_index_additions.py can test the cleaning/dedup logic
    against a synthetic DataFrame without a network call.

    Point-in-time index-membership gap this exists to close (found live,
    2026-08-11, Ross's direct observation): candidate-generation pipelines
    (e.g. wrds_deep_history_episodic_scan.py) load every symbol with cached
    price history regardless of when it actually ENTERED the S&P 500 -- a
    symbol added in 2022 still gets correlation/EG-tested against 2015-era
    windows, which a real deployment back then would never have screened
    (it wasn't in the investable universe yet). This function's output lets
    callers mask pre-membership history to NaN.

    DISCLOSED LIMITATION: only covers the S&P 500 slice of CAMARF's S&P
    Composite 1500 universe, and only CURRENTLY-listed S&P 500 members (a
    symbol removed from the index before this scrape ran won't appear at
    all -- irrelevant for gating CURRENT candidate generation, but not a
    complete historical membership register). A symbol absent from this
    table is NOT assumed ineligible -- it may be an S&P 400/600-only name
    outside this table's scope entirely, or a since-removed former member;
    callers must treat "no addition date found" as "no membership-date
    constraint available," never as "never eligible."
    """
    if len(constituents_df) == 0:
        return pd.DataFrame(columns=["symbol", "added_date"])
    out = constituents_df.copy()
    out["added_date"] = pd.to_datetime(out["added_date"], errors="coerce")
    out = out.dropna(subset=["added_date"])
    out = out[out["symbol"].astype(str).str.match(r"^[A-Z][A-Z0-9\-\.]{0,8}$")]
    # A symbol can appear more than once (defensive -- shouldn't happen in a
    # current-constituents table, but re-added-after-removal historically is
    # possible if this function is ever fed a richer source later): keep the
    # EARLIEST date (most conservative -- widest eligible window).
    out["added_date"] = out["added_date"].dt.strftime("%Y-%m-%d")
    out = out.sort_values("added_date").drop_duplicates(subset=["symbol"], keep="first")
    out = out.reset_index(drop=True)
    return out


def load_additions(path: str = _ADDITIONS_OUT_PATH) -> pd.DataFrame:
    """Load saved index-addition dates CSV. Returns empty DataFrame if not found."""
    if not os.path.exists(path):
        return pd.DataFrame(columns=["symbol", "added_date"])
    df = pd.read_csv(path, dtype=str)
    df["added_date"] = pd.to_datetime(df["added_date"], errors="coerce")
    return df


def get_member_since_date(symbol: str, additions: pd.DataFrame) -> Optional[pd.Timestamp]:
    """
    Return the date `symbol` first became an S&P 500 member per the scraped
    changes table, or None if no record exists (see build_additions'
    DISCLOSED LIMITATION -- None must be treated as "unconstrained," not
    "never eligible").
    """
    if len(additions) == 0:
        return None
    rows = additions[additions["symbol"] == symbol.upper()]
    if len(rows) == 0:
        return None
    dates = pd.to_datetime(rows["added_date"], errors="coerce").dropna()
    if len(dates) == 0:
        return None
    return dates.min()


def load_exclusions(path: str = _OUT_PATH) -> pd.DataFrame:
    """Load saved survivorship exclusions CSV. Returns empty DataFrame if not found."""
    if not os.path.exists(path):
        return pd.DataFrame(columns=["symbol", "removed_date", "reason", "added_symbol"])
    df = pd.read_csv(path, dtype=str)
    df["removed_date"] = pd.to_datetime(df["removed_date"], errors="coerce")
    return df


def get_oos_end_date(symbol: str, exclusions: pd.DataFrame) -> Optional[pd.Timestamp]:
    """
    Return the OOS end date for a symbol if it was delisted/removed.
    None means the symbol is still active — no truncation needed.
    If removed multiple times, returns the EARLIEST removal date (most conservative).
    """
    if len(exclusions) == 0:
        return None
    rows = exclusions[exclusions["symbol"] == symbol.upper()]
    if len(rows) == 0:
        return None
    dates = pd.to_datetime(rows["removed_date"], errors="coerce").dropna()
    if len(dates) == 0:
        return None
    return dates.min()


def main():
    os.makedirs(os.path.dirname(_OUT_PATH), exist_ok=True)
    log.info("Fetching S&P 500 historical changes from Wikipedia...")

    changes = fetch_changes_table()
    if len(changes) == 0:
        log.error("No changes table fetched — check network/Wikipedia structure")
        return

    exclusions = build_exclusions(changes)
    if len(exclusions) == 0:
        log.error("No exclusions built from changes table")
        return

    exclusions.to_csv(_OUT_PATH, index=False)
    log.info("Saved => %s (%d rows)", _OUT_PATH, len(exclusions))

    additions = build_additions(changes)
    if len(additions) > 0:
        additions.to_csv(_ADDITIONS_OUT_PATH, index=False)
        log.info("Saved => %s (%d rows)", _ADDITIONS_OUT_PATH, len(additions))
    else:
        log.warning("No additions extracted -- index_additions.csv not written")

    # Coverage check vs confirmed pairs
    tiers_path = os.path.join(_ROOT, "output", "stats", "cointegration_tiers.parquet")
    if os.path.exists(tiers_path):
        tiers = pd.read_parquet(tiers_path)
        syms = set(tiers.symbol_a) | set(tiers.symbol_b)
        excluded_syms = set(exclusions["symbol"])
        affected = syms & excluded_syms
        if affected:
            log.info("Confirmed-pair symbols with delist events: %s", sorted(affected))
            for sym in sorted(affected):
                oed = get_oos_end_date(sym, exclusions)
                log.info("  %s  OOS end date: %s", sym, oed)
        else:
            log.info("No confirmed-pair symbols appear in delist history (all currently active)")

    # Summary stats
    log.info("\n=== Survivorship summary ===")
    log.info("Total removal events: %d", len(exclusions))
    if "removed_date" in exclusions.columns:
        dates = pd.to_datetime(exclusions["removed_date"], errors="coerce").dropna()
        if len(dates) > 0:
            log.info("Date range: %s to %s", dates.min().date(), dates.max().date())
    if "reason" in exclusions.columns:
        top_reasons = exclusions["reason"].value_counts().head(5)
        log.info("Top removal reasons:\n%s", top_reasons.to_string())


if __name__ == "__main__":
    main()
