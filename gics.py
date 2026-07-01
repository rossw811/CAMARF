"""
gics.py — GICS sector tag builder

Scrapes GICS sector/sub-industry data for S&P 500/400/600 constituents from
Wikipedia and saves to output/cache/gics_tags.csv.

Columns: symbol, sector, industry_group, industry, sub_industry

Run: python gics.py
"""

import os
import sys
import logging
import time
from io import StringIO
from typing import Dict, List, Optional

import pandas as pd
import requests

_ROOT = os.path.dirname(os.path.abspath(__file__))
_OUT_PATH = os.path.join(_ROOT, "output", "cache", "gics_tags.csv")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

log = logging.getLogger("gics")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")


# ---------------------------------------------------------------------------
# Wikipedia scraper — returns DataFrame with symbol + GICS columns
# ---------------------------------------------------------------------------

_INDEX_URLS = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "sp400": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "sp600": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
}

# Wikipedia S&P 500 historical changes — for survivorship context
_SP500_CHANGES_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

_GICS_COL_ALIASES = {
    "gics sector": "sector",
    "sector": "sector",
    "gics sub-industry": "sub_industry",
    "sub-industry": "sub_industry",
    "gics industry": "industry",
    "industry": "industry",
    "gics industry group": "industry_group",
    "industry group": "industry_group",
    "security": "name",
    "company": "name",
}


def _fetch_index_table(url: str, index_name: str) -> Optional[pd.DataFrame]:
    """Fetch the constituent table from Wikipedia for one S&P index."""
    try:
        resp = requests.get(url, headers={"User-Agent": _UA}, timeout=20)
        if resp.status_code != 200:
            log.warning("%s: HTTP %d", index_name, resp.status_code)
            return None
        tables = pd.read_html(StringIO(resp.text))
    except Exception as e:
        log.warning("%s: fetch failed: %s", index_name, e)
        return None

    best: Optional[pd.DataFrame] = None
    best_score = 0
    for t in tables:
        cols_lower = {str(c).lower().strip() for c in t.columns}
        # Must have a ticker/symbol column
        has_ticker = any("symbol" in c or "ticker" in c for c in cols_lower)
        if not has_ticker:
            continue
        # Score by how many GICS columns are present
        score = sum(1 for alias in _GICS_COL_ALIASES if alias in cols_lower)
        if score > best_score:
            best_score = score
            best = t

    if best is None:
        log.warning("%s: no suitable table found", index_name)
        return None

    # Normalize column names
    best = best.copy()
    rename_map = {}
    for col in best.columns:
        cl = str(col).lower().strip()
        if "symbol" in cl or "ticker" in cl:
            rename_map[col] = "symbol"
        elif cl in _GICS_COL_ALIASES:
            rename_map[col] = _GICS_COL_ALIASES[cl]
    best = best.rename(columns=rename_map)

    if "symbol" not in best.columns:
        log.warning("%s: no symbol column after rename", index_name)
        return None

    # Clean symbol
    best["symbol"] = best["symbol"].astype(str).str.strip().str.upper().str.replace(".", "-", regex=False)
    best = best[best["symbol"].str.len() <= 6]
    best = best[best["symbol"].str[0].str.isalpha()]
    best["index"] = index_name

    log.info("%s: %d symbols, columns: %s", index_name, len(best), list(best.columns))
    return best


def build_gics_tags() -> pd.DataFrame:
    """Scrape all three S&P indices and merge into a unified GICS tag table."""
    frames = []
    for name, url in _INDEX_URLS.items():
        log.info("Fetching %s...", name)
        df = _fetch_index_table(url, name)
        if df is not None and len(df) > 0:
            frames.append(df)
        time.sleep(1.5)  # be polite to Wikipedia

    if not frames:
        log.error("No data fetched from any index")
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)

    # Keep only the needed columns, fill missing
    keep = ["symbol", "sector", "industry_group", "industry", "sub_industry", "name", "index"]
    for col in keep:
        if col not in combined.columns:
            combined[col] = ""
    combined = combined[keep].copy()

    # De-duplicate: S&P 500 takes precedence over 400/600 for same symbol
    priority = {"sp500": 0, "sp400": 1, "sp600": 2}
    combined["_pri"] = combined["index"].map(priority).fillna(9)
    combined = combined.sort_values("_pri").drop_duplicates(subset=["symbol"], keep="first")
    combined = combined.drop(columns=["_pri"]).reset_index(drop=True)

    # Fill empty strings with NaN
    for col in ["sector", "industry_group", "industry", "sub_industry"]:
        if col in combined.columns:
            combined[col] = combined[col].replace("", pd.NA).replace("nan", pd.NA)

    log.info("GICS tags built: %d symbols", len(combined))
    return combined


def load_gics_tags(path: str = _OUT_PATH) -> pd.DataFrame:
    """Load saved GICS tags CSV. Returns empty DataFrame if not found."""
    if not os.path.exists(path):
        return pd.DataFrame(columns=["symbol", "sector", "industry_group", "industry", "sub_industry"])
    return pd.read_csv(path, dtype=str)


def main():
    os.makedirs(os.path.dirname(_OUT_PATH), exist_ok=True)
    log.info("Building GICS tags from Wikipedia...")
    tags = build_gics_tags()
    if len(tags) == 0:
        log.error("No tags built — check network and Wikipedia structure")
        return

    tags.to_csv(_OUT_PATH, index=False)
    log.info("Saved => %s (%d rows)", _OUT_PATH, len(tags))

    # Quick coverage check vs confirmed pairs
    tiers_path = os.path.join(_ROOT, "output", "stats", "cointegration_tiers.parquet")
    if os.path.exists(tiers_path):
        tiers = pd.read_parquet(tiers_path)
        syms = set(tiers.symbol_a) | set(tiers.symbol_b)
        covered = syms & set(tags["symbol"])
        missing = syms - covered
        log.info("Coverage: %d/%d confirmed-pair symbols have GICS tags", len(covered), len(syms))
        if missing:
            log.info("Missing GICS tags: %s", sorted(missing))


if __name__ == "__main__":
    main()
