"""
research/pit_index_membership.py -- point-in-time S&P MidCap 400 / SmallCap 600 holdings from free SEC filings of
index ETFs (DEV-058; Ross 2026-10-03: "verify more, then a comparison arm"). Source rationale and the first check
(37/38 announced changes agree on the 2019-09-23 rebalance): docs/PIT_INDEX_MEMBERSHIP_SOURCES.md.

What it does
------------
  download  -- list and cache the holdings filings: SPDR S&P MidCap 400 ETF Trust (MDY, CIK 936958; N-30D annual
               shareholder reports with the full schedule of investments, NPORT-P quarterly from 2019) and iShares
               Core S&P Small-Cap (IJR, series S000004313 in iShares Trust CIK 1100663; NPORT-P quarterly).
               Raw files cached under output/research/pit_membership/raw/ (never re-downloaded).
  parse     -- one table, output/research/pit_membership/holdings.parquet:
               index, fund, form, accession, as_of, name, cusip (NPORT only), shares, value_usd, pct, asset_cat.
               Prints holdings per filing next to the index size, so a parse that misses rows is visible.

Limits (also in the doc): annual snapshots before 2019 (names that joined and left between snapshots are missed --
S&P's dated announcements are the primary record, holdings the cross-check); N-30D gives names only; an ETF can
briefly hold a deleted name (a minimum-weight cut is needed before treating holdings as membership).
SEC fair access: <= 10 requests/s with a contact User-Agent (Ross's chosen contact address).

Usage:  python research/pit_index_membership.py download
        python research/pit_index_membership.py parse
Synthetic check: debug/_verify_pit_index_membership.py
"""
import html
import os
import re
import sys
import time

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output", "research", "pit_membership")
RAW = os.path.join(OUT, "raw")
UA = "CAMARF research aflacgamer@outlook.com"
FUNDS = {
    "MDY": {"index": "SP400", "cik": 936958, "series": None, "forms": ("N-30D", "NPORT-P"), "index_size": 400},
    "IJR": {"index": "SP600", "cik": 1100663, "series": "S000004313", "forms": ("NPORT-P",), "index_size": 600},
}
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


# ----------------------------------------------------------------------------------------------------- parsers
def parse_nport(xml: str) -> pd.DataFrame:
    """NPORT-P primary_doc.xml -> one row per holding (name, cusip, balance, valUSD, pctVal, assetCat)."""
    rep = re.search(r"<repPdDate>([^<]+)</repPdDate>", xml)
    as_of = pd.Timestamp(rep.group(1)) if rep else pd.NaT
    rows = []
    for blk in re.findall(r"<invstOrSec>(.*?)</invstOrSec>", xml, re.S):
        g = lambda tag: (re.search(rf"<{tag}>([^<]*)</{tag}>", blk) or [None, None])[1]
        num = lambda v: float(v) if v not in (None, "") else float("nan")
        rows.append({"as_of": as_of, "name": html.unescape(g("name") or "").strip(),
                     "cusip": (g("cusip") or None), "shares": num(g("balance")), "value_usd": num(g("valUSD")),
                     "pct": num(g("pctVal")), "asset_cat": g("assetCat")})
    return pd.DataFrame(rows, columns=["as_of", "name", "cusip", "shares", "value_usd", "pct", "asset_cat"])


def _text(htm: str) -> str:
    t = re.sub(r"<[^>]+>", " ", htm)
    t = html.unescape(t.replace("&nbsp;", " ").replace("&#160;", " "))
    return " ".join(t.split())


_COLS = ["as_of", "name", "cusip", "shares", "value_usd", "pct", "asset_cat"]
# name ends at a dot leader, a "*" marker, or a run of 2+ spaces; then shares and value
_TXT_LINE = re.compile(r"^\s*(?P<name>\S.*?)\s*(?:\.{2,}|\*\s|\s{2,})[\s.*]*(?P<sh>\d{1,3}(?:,\d{3})+|\d+)\s+\$?\s*"
                       r"(?P<val>\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*$")


def _as_of(t: str):
    m = re.search(r"Schedule of Investments\s*(?:\(?Unaudited\)?\s*)?((?:" + _MONTHS + r") \d{1,2}, \d{4})", t, re.I)
    return pd.Timestamp(m.group(1).title()) if m else pd.NaT


def _parse_n30d_text(raw: str) -> pd.DataFrame:
    """Plain-text reports (2001-2005): one holding per line ("Name ...... shares $ value" or "Name  *  shares
    $value"); only lines between a "Common Stock ... Shares ... Value" header and the next line starting "Total"."""
    as_of = _as_of(" ".join(re.sub(r"<[^>]+>", " ", raw).split()))
    rows, inside = [], False
    for line in re.sub(r"<[^>]+>", "", raw).splitlines():
        if re.search(r"common stocks?\s+shares\s+value", line, re.I):
            inside = True; continue
        if not inside:
            continue
        if re.match(r"\s*total", line, re.I):
            inside = False; continue
        m = _TXT_LINE.match(line)
        if m:
            nm = re.sub(r"\s*\.{2,}.*$", "", m.group("name"))      # cut at the dot leader, keep "Corp."
            nm = nm.strip().rstrip("*").strip()
            rows.append({"as_of": as_of, "name": nm, "cusip": None, "shares": float(m.group("sh").replace(",", "")),
                         "value_usd": float(m.group("val").replace(",", "")), "pct": float("nan"), "asset_cat": "EC"})
    return pd.DataFrame(rows, columns=_COLS)


def parse_n30d(htm: str) -> pd.DataFrame:
    """N-30D (annual report) -> holdings from the schedule of investments. HTML reports (2006+): the text between
    the "Common Stock Shares Value" header and the first "Total(s)" line, page footers removed; each holding is
    "<name> <shares> [$] <value>". Plain-text reports (2001-2005): _parse_n30d_text. The as-of date is the date that
    follows "Schedule of Investments"."""
    if not re.search(r"<td", htm, re.I):
        return _parse_n30d_text(htm)
    t = _text(htm)
    as_of = _as_of(t)
    # page-break footers inside the schedule (2026-10-03: read as 10 fake holdings per report, shares=30, value=2017)
    t = re.sub(r"The accompanying notes are an integral part of these financial statements\.?.{0,200}?"
               r"Schedule of Investments \(continued\)\s*(?:" + _MONTHS + r") \d{1,2}, \d{4}", " ", t, flags=re.I)
    start = re.search(r"Common Stocks?\s+Shares\s+Value", t, re.I)
    if start:   # any other page header inside the schedule ("MidCap SPDR Trust, Series 1 Schedule of Investments
        # September 30, 2008", 2007-2010 reports) -- from the trust name to the date
        body = re.sub(r"(?:MidCap SPDR Trust.{0,40}?)?Schedule of Investments(?:\s*\(continued\))?\s*(?:"
                      + _MONTHS + r") \d{1,2}, \d{4}", " ", t[start.end():], flags=re.I)
        # rest of a page break (2009/2010 reports: footer + page number, then the column header repeated) -- left in,
        # it merged into the next holding's name and that holding was dropped (10 per report)
        body = re.sub(r"The accompanying notes are an integral part of these financial statements\.?\s*\d*", " ", body,
                      flags=re.I)
        body = re.sub(r"Common Stocks?(?:\s*\(continued\))?\s+Shares\s+Value", " ", body, flags=re.I)
        t = t[:start.end()] + body
    if not start:
        return pd.DataFrame(columns=["as_of", "name", "cusip", "shares", "value_usd", "pct", "asset_cat"])
    end = re.search(r"\bTotals?\b", t[start.end():])
    seg = t[start.end(): start.end() + end.start()] if end else t[start.end():]
    rows = []
    for nm, sh, val in re.findall(r"([A-Z][A-Za-z0-9&.,'\-/() ]*?)\*?\s+([\d,]{2,})\s+\$?\s?([\d,]{3,})(?=\s|$)", seg):
        nm = nm.strip().rstrip("*").strip()
        if re.search(r"schedule of investments|accompanying notes", nm, re.I):
            continue                                    # last guard against a page header/footer read as a holding
        rows.append({"as_of": as_of, "name": nm, "cusip": None, "shares": float(sh.replace(",", "")),
                     "value_usd": float(val.replace(",", "")), "pct": float("nan"), "asset_cat": "EC"})
    return pd.DataFrame(rows, columns=["as_of", "name", "cusip", "shares", "value_usd", "pct", "asset_cat"])


# ------------------------------------------------------------------------------------------------- download
def _get(url: str) -> bytes:
    import requests
    for attempt in range(4):
        r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
        time.sleep(0.2)                                   # SEC fair access: well under 10 requests/s
        if r.status_code == 200:
            return r.content
        if r.status_code in (429, 503):
            time.sleep(5 * (attempt + 1)); continue
        raise RuntimeError(f"{url}: HTTP {r.status_code}")
    raise RuntimeError(f"{url}: gave up after retries")


def list_filings(fund: str) -> pd.DataFrame:
    f = FUNDS[fund]
    rows = []
    if f["series"] is None:
        import json
        d = json.loads(_get(f"https://data.sec.gov/submissions/CIK{f['cik']:010d}.json"))
        blocks = [d["filings"]["recent"]] + [json.loads(_get(f"https://data.sec.gov/submissions/{x['name']}"))
                                             for x in d["filings"].get("files", [])]
        for r in blocks:
            for i, form in enumerate(r["form"]):
                if form in f["forms"]:
                    rows.append({"form": form, "filed": r["filingDate"][i], "accession": r["accessionNumber"][i],
                                 "doc": r["primaryDocument"][i]})
    else:
        start = 0
        while True:
            atom = _get(f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={f['series']}&type=NPORT-P"
                        f"&dateb=&owner=include&count=100&start={start}&output=atom").decode("utf-8", "replace")
            # one <entry> at a time (2026-10-03: matching date-then-accession across the whole feed paired each date
            # with the NEXT entry's accession and dropped the earliest filing)
            ents = []
            for e in re.findall(r"<entry>(.*?)</entry>", atom, re.S):
                fd, ac = re.search(r"<filing-date>([^<]+)<", e), re.search(r"<accession-number>([^<]+)<", e)
                if fd and ac:
                    ents.append((fd.group(1), ac.group(1)))
            for filed, acc in ents:
                rows.append({"form": "NPORT-P", "filed": filed, "accession": acc, "doc": "primary_doc.xml"})
            if len(ents) < 100:
                break
            start += 100
    out = pd.DataFrame(rows).drop_duplicates("accession")
    out["fund"] = fund
    return out.sort_values("filed").reset_index(drop=True)


def _doc_url(fund: str, row) -> str:
    acc = row.accession.replace("-", "")
    doc = "primary_doc.xml" if row.form == "NPORT-P" else row.doc
    return f"https://www.sec.gov/Archives/edgar/data/{FUNDS[fund]['cik']}/{acc}/{doc}"


def download():
    os.makedirs(RAW, exist_ok=True)
    allf = []
    for fund in FUNDS:
        fl = list_filings(fund)
        allf.append(fl)
        for row in fl.itertuples():
            path = os.path.join(RAW, f"{fund}_{row.accession}{'.xml' if row.form == 'NPORT-P' else '.htm'}")
            if os.path.exists(path) and os.path.getsize(path) > 0:
                continue
            data = _get(_doc_url(fund, row))
            with open(path + ".tmp", "wb") as fh:
                fh.write(data)
            os.replace(path + ".tmp", path)
        print(f"{fund}: {len(fl)} filings ({fl['form'].value_counts().to_dict()}), cached in {RAW}", flush=True)
    pd.concat(allf).to_parquet(os.path.join(OUT, "filings.parquet"))


def parse():
    fl = pd.read_parquet(os.path.join(OUT, "filings.parquet"))
    parts, summary = [], []
    for row in fl.itertuples():
        path = os.path.join(RAW, f"{row.fund}_{row.accession}{'.xml' if row.form == 'NPORT-P' else '.htm'}")
        if not os.path.exists(path):
            continue
        txt = open(path, encoding="utf-8", errors="replace").read()
        h = parse_nport(txt) if row.form == "NPORT-P" else parse_n30d(txt)
        h["fund"], h["index"], h["form"], h["accession"] = row.fund, FUNDS[row.fund]["index"], row.form, row.accession
        parts.append(h)
        n_eq = int((h["asset_cat"] == "EC").sum())
        summary.append((row.fund, row.form, row.filed, h["as_of"].iloc[0] if len(h) else pd.NaT, len(h), n_eq,
                        FUNDS[row.fund]["index_size"]))
    hold = pd.concat(parts, ignore_index=True)
    hold.to_parquet(os.path.join(OUT, "holdings.parquet"))
    s = pd.DataFrame(summary, columns=["fund", "form", "filed", "as_of", "rows", "equity_rows", "index_size"])
    s.to_parquet(os.path.join(OUT, "parse_summary.parquet"))
    print(s.to_string())
    print(f"\n{len(hold):,} holding rows from {len(s)} filings -> {os.path.join(OUT, 'holdings.parquet')}")


# ---------------------------------------------------------------------------------------------- verification
_DROP = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "plc", "the", "holdings", "holding",
         "group", "class", "cl", "a", "b", "and", "of", "trust", "nv", "sa", "lp", "llc", "new"}


def norm_tokens(name: str) -> list:
    """Lower-case name tokens without punctuation and corporate suffixes ("R.R. Donnelley & Sons Co." ->
    ['rr', 'donnelley', 'sons']); "'s" kept as part of the word ("snyders", "pilgrims")."""
    s = re.sub(r"[’']", "", str(name).lower()).replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s.replace(".", ""))
    syn = {"companies": "cos", "bancorporation": "bancorp"}          # filing abbreviations (2026-10-03)
    return [syn.get(t, t) for t in s.split() if t not in _DROP]


def name_match(announced: str, held: str) -> bool:
    """Announced name's leading significant tokens (up to 2) equal the held name's leading tokens."""
    a, h = norm_tokens(announced), norm_tokens(held)
    k = min(2, len(a))
    return k > 0 and h[:k] == a[:k]


MIN_REL_WEIGHT = 0.001


def members(hold: pd.DataFrame, index_size: int) -> pd.DataFrame:
    """Index members of ONE snapshot = equity holdings worth >= MIN_REL_WEIGHT x the snapshot's median holding.
    Derived from all 80 snapshots (2026-10-03): 33 rows sit at ~0 (written off / being wound down) -- excluded. A
    fixed top-`index_size` cut was tried first and REJECTED: MDY held 401 normal-weight names on 2022-06-30 and the
    cut dropped a real member (Mercury General, 0.27 x median). Between 0.002 and 0.05 x median, ETF leftovers
    (Ascena 0.004, post-bankruptcy Unit Corp / Frontier, acquisition stubs) and genuinely tiny members (KLX Energy,
    HighPoint, CBL in March 2020; Wolfspeed 2025) OVERLAP -- 18 of 38,402 rows; no weight separates them, so they
    count as members here and the ambiguity is reported (S&P's announcements are the primary record).
    `index_size` is kept for the report only."""
    eq = hold[hold["asset_cat"].fillna("EC") == "EC"]
    med = eq["value_usd"].median()
    return eq[eq["value_usd"] >= MIN_REL_WEIGHT * med]


def check_announcements(hold: pd.DataFrame, ann: pd.DataFrame, index_sizes: dict) -> pd.DataFrame:
    """For each announced change at effective date E: the snapshot BEFORE (latest as_of < E) and AFTER (earliest
    as_of >= E) of that index. add: absent before, present after. delete: present before, absent after."""
    out = []
    for r in ann.itertuples():
        H = hold[hold["index"] == r.index]
        eff = pd.Timestamp(r.effective)
        before_d = H.loc[H["as_of"] < eff, "as_of"].max()
        after_d = H.loc[H["as_of"] >= eff, "as_of"].min()
        res = {"effective": eff.date(), "index": r.index, "action": r.action, "name": r.name, "ticker": r.ticker,
               "snapshot_before": before_d, "snapshot_after": after_d}
        for tag, d in (("before", before_d), ("after", after_d)):
            if pd.isna(d):
                res[f"in_{tag}"] = None; continue
            snap = H[H["as_of"] == d]
            snap = snap[snap["form"] == ("NPORT-P" if (snap["form"] == "NPORT-P").any() else snap["form"].iloc[0])]
            m = members(snap, index_sizes[r.index])
            hits = [n for n in m["name"] if name_match(r.name, n)]
            res[f"in_{tag}"] = bool(hits)
            res[f"match_{tag}"] = hits[0] if hits else ""
        exp_b, exp_a = (False, True) if r.action == "add" else (True, False)
        res["agrees"] = (res.get("in_before") in (exp_b, None)) and (res.get("in_after") in (exp_a, None)) and \
            not (res.get("in_before") is None and res.get("in_after") is None)
        out.append(res)
    return pd.DataFrame(out)


def check():
    hold = pd.read_parquet(os.path.join(OUT, "holdings.parquet"))
    ann = pd.read_csv(os.path.join(ROOT, "docs", "pit_membership", "announcements.csv"))
    sizes = {f["index"]: f["index_size"] for f in FUNDS.values()}
    res = check_announcements(hold, ann, sizes)
    res.to_parquet(os.path.join(OUT, "announcement_check.parquet"))
    pd.set_option("display.width", 220)
    print(res[["effective", "index", "action", "name", "snapshot_before", "snapshot_after", "in_before", "in_after",
               "agrees"]].to_string())
    print(f"\nagree: {int(res['agrees'].sum())}/{len(res)} announced changes; by rebalance:")
    print(res.groupby(["effective", "index"])["agrees"].agg(["sum", "count"]).to_string())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "download":
        download()
    elif cmd == "parse":
        parse()
    elif cmd == "check":
        check()
    else:
        print(__doc__); sys.exit(2)
