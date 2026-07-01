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
