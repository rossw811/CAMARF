"""
CAMARF data_finra.py -- ALL FINRA data sources live in this ONE file,
one file per external PROVIDER (same convention as data_wrds.py's own
docstring). Free, public, no authentication -- FINRA is required by
regulation to publish this, not a paid vendor.

Built 2026-09-09, Ross: "let's research ways we can do things if we
can't [use paywalled data]." Answers PAPER.md's crowding/capacity-decay
limitation (the original caveat search flagged this as needing "paid
flow data, real acquisition cost") -- confirmed this session that a
real, free crowding proxy exists: FINRA's biweekly equity short
interest file, per-security, covering ALL exchanges (NYSE/Nasdaq/etc,
not just OTC despite the URL's "otcmarket" path component -- confirmed
directly against a live file: NYSE-listed "A" (Agilent) and "AA"
(Alcoa) both present with real short-interest figures).

URL pattern confirmed by direct fetch, not assumed from documentation
alone: https://cdn.finra.org/equity/otcmarket/biweekly/shrt{YYYYMMDD}.csv
-- settlement dates are specific biweekly reporting dates (roughly the
15th and end of each month, shifted for weekends/holidays), not every
calendar date. Callers must pass a real settlement date; there is no
"latest" alias endpoint.
"""
import logging
import os

import pandas as pd
import requests

log = logging.getLogger("data_finra")

_OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "cache", "finra")
_URL_TEMPLATE = "https://cdn.finra.org/equity/otcmarket/biweekly/shrt{date_str}.csv"


def fetch_short_interest(settlement_date: str) -> "pd.DataFrame | None":
    """settlement_date: 'YYYY-MM-DD' or 'YYYYMMDD'. Returns None (not an
    exception) if that exact date has no published file -- short
    interest is reported on specific biweekly settlement dates only,
    a caller passing an arbitrary date should expect this, not treat it
    as an error."""
    date_str = settlement_date.replace("-", "")
    url = _URL_TEMPLATE.format(date_str=date_str)
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        log.warning(f"No short interest file for {settlement_date} (HTTP {resp.status_code}) -- "
                    f"not every calendar date has a settlement report.")
        return None
    from io import StringIO
    df = pd.read_csv(StringIO(resp.text), sep="|")
    log.info(f"Short interest {settlement_date}: {len(df)} securities")
    return df


def cache_short_interest(settlement_date: str) -> "pd.DataFrame | None":
    """Same as fetch_short_interest, but caches to disk (one file per
    settlement date) and reads from cache on a repeat call, matching
    this project's other data_*.py providers' own caching convention."""
    date_str = settlement_date.replace("-", "")
    cache_path = os.path.join(_OUT_DIR, f"short_interest_{date_str}.parquet")
    if os.path.exists(cache_path):
        return pd.read_parquet(cache_path)
    df = fetch_short_interest(settlement_date)
    if df is None:
        return None
    os.makedirs(_OUT_DIR, exist_ok=True)
    df.to_parquet(cache_path, index=False)
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    df = cache_short_interest("2026-08-14")
    if df is not None:
        print(df.head())
        print(f"{len(df)} securities, columns: {df.columns.tolist()}")
