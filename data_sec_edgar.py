"""
CAMARF data_sec_edgar.py -- ALL SEC EDGAR data sources live in this ONE
file, one file per external PROVIDER (same convention as data_wrds.py's
own docstring). Free, public, no authentication, no paywall -- SEC EDGAR
is a US government disclosure system, not a paid vendor.

Built 2026-09-09, Ross: "let's research ways we can do things if we
can't [use paywalled data] -- can we scrape data or use related data?"
Answers PAPER.md §7.3's SPAC-regex-non-exhaustive limitation (a
structured SIC=6770 "Blank Checks" company list, not a naming-pattern
regex that misses conventions like the Social Capital Hedosophia
family) -- confirmed via direct search this session that a paid SPAC
tracker is NOT needed: SEC EDGAR's own company-search endpoint filters
by SIC code directly and is completely free.

Rate limit / access convention (confirmed via web search this session,
not assumed): SEC EDGAR requires a descriptive `User-Agent` header
(app name + contact email) on every request -- omitting it returns 403.
Documented fair-use limit is 10 requests/second per IP; this module
stays well under that (_MIN_REQUEST_INTERVAL_SEC below) and there is no
daily cap.
"""
import logging
import os
import time
import xml.etree.ElementTree as ET

import pandas as pd
import requests

log = logging.getLogger("data_sec_edgar")

_OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "cache", "sec_edgar")
_USER_AGENT = "CAMARF-research ross.winnemore@icloud.com"
_MIN_REQUEST_INTERVAL_SEC = 0.3  # well under the documented 10 req/sec fair-use limit
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

_last_request_time = [0.0]


def _rate_limited_get(url: str, params: dict = None) -> requests.Response:
    elapsed = time.time() - _last_request_time[0]
    if elapsed < _MIN_REQUEST_INTERVAL_SEC:
        time.sleep(_MIN_REQUEST_INTERVAL_SEC - elapsed)
    resp = requests.get(url, params=params, headers={"User-Agent": _USER_AGENT}, timeout=30)
    _last_request_time[0] = time.time()
    resp.raise_for_status()
    return resp


def fetch_sic_company_list(sic: str, entity_type: str = "") -> pd.DataFrame:
    """Full, paginated list of CIKs registered under a given SIC code,
    via SEC EDGAR's free company-search atom feed
    (browse-edgar?action=getcompany&SIC=...). Returns one row per
    company: cik, sic, state.

    Real, CONFIRMED bug in SEC's own legacy CGI endpoint (checked
    directly against a raw response, not assumed): this endpoint's atom
    `<entry title="...">` and `<company-info name="...">` attributes are
    both broken, containing the literal Perl stringification
    `ARRAY(0x...)` instead of the real company name -- a known issue in
    SEC's own legacy browse-edgar output=atom format, not a parsing bug
    on this project's side. The `<cik>` element is unaffected and
    reliable. Consequence: this function does NOT return company names
    at all -- see build_spac_universe(), which gets real names from the
    separate, reliable company_tickers.json endpoint instead (ticker-
    registered companies only; non-ticker-mapped shells will have no
    name, disclosed via n_ticker_mapped there, not silently dropped).

    sic="6770" (Blank Checks) is this module's primary use case
    (PAPER.md §7.3's SPAC universe gap), but the function itself is
    generic -- any SIC code works the same way."""
    base_url = "https://www.sec.gov/cgi-bin/browse-edgar"
    rows = []
    start = 0
    count = 100
    while True:
        params = {
            "action": "getcompany", "SIC": sic, "type": entity_type,
            "dateb": "", "owner": "include", "count": count, "start": start,
            "output": "atom",
        }
        resp = _rate_limited_get(base_url, params=params)
        root = ET.fromstring(resp.content)
        entries = root.findall("atom:entry", _ATOM_NS)
        if not entries:
            break
        for entry in entries:
            content = entry.find("atom:content", _ATOM_NS)
            if content is None:
                continue
            # The root <feed xmlns="..."> default-namespace declaration
            # applies to EVERY descendant element, including <company-info>
            # nested inside <content> -- not just elements with an
            # explicit atom: prefix. Caught live: `content.find(
            # "company-info")` (no namespace) silently returned None for
            # every entry, verified via a raw small-sample fetch before
            # trusting the full paginated run.
            company_info = content.find("atom:company-info", _ATOM_NS)
            if company_info is None:
                continue
            cik_el = company_info.find("atom:cik", _ATOM_NS)
            state_el = company_info.find("atom:state", _ATOM_NS)
            cik = cik_el.text.strip() if cik_el is not None and cik_el.text else None
            state = state_el.text.strip() if state_el is not None and state_el.text else None
            if cik:
                rows.append({"cik": cik, "sic": sic, "state": state})
        log.info(f"  SIC={sic}: fetched {len(entries)} entries at start={start} "
                 f"({len(rows)} total so far)")
        if len(entries) < count:
            break
        start += count
    df = pd.DataFrame(rows).drop_duplicates(subset=["cik"])
    log.info(f"SIC={sic}: {len(df)} distinct companies total")
    return df


def fetch_cik_ticker_map() -> pd.DataFrame:
    """SEC's own free CIK->ticker mapping
    (https://www.sec.gov/files/company_tickers.json), covering every
    SEC filer with a registered ticker. Returns cik, ticker, title
    (company name as SEC has it -- may differ slightly from the SIC
    list's title, e.g. punctuation/casing)."""
    resp = _rate_limited_get("https://www.sec.gov/files/company_tickers.json")
    data = resp.json()
    rows = [{"cik": str(v["cik_str"]), "ticker": v["ticker"], "title": v["title"]}
            for v in data.values()]
    df = pd.DataFrame(rows)
    log.info(f"CIK->ticker map: {len(df)} entries")
    return df


def build_spac_universe() -> pd.DataFrame:
    """The real deliverable: every SIC=6770 (Blank Checks) company,
    ticker-mapped where SEC has a registered ticker for it (pre-IPO
    shells and some post-de-SPAC entities that changed SIC code won't
    have one -- left NaN, not silently dropped, since a symbol-less row
    is still real evidence the company exists / existed as a
    blank-check entity)."""
    spac_df = fetch_sic_company_list("6770")
    ticker_map = fetch_cik_ticker_map()
    # CIK representations differ between sources (zero-padded 10-digit
    # string from the atom feed vs. plain int from company_tickers.json)
    # -- normalize both to int before joining, or every row silently
    # fails to match.
    spac_df["cik"] = spac_df["cik"].astype(int)
    ticker_map["cik"] = ticker_map["cik"].astype(int)
    merged = spac_df.merge(ticker_map[["cik", "ticker", "title"]], on="cik", how="left")
    n_ticker_mapped = merged["ticker"].notna().sum()
    log.info(f"SPAC universe: {len(merged)} companies, {n_ticker_mapped} with a "
             f"registered ticker ({n_ticker_mapped/len(merged):.1%})")

    os.makedirs(_OUT_DIR, exist_ok=True)
    out_path = os.path.join(_OUT_DIR, "spac_universe_sic6770.parquet")
    merged.to_parquet(out_path, index=False)
    log.info(f"Saved -> {out_path}")
    return merged


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    build_spac_universe()
