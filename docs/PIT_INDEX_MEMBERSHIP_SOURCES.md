# Point-in-time S&P MidCap 400 / SmallCap 600 membership: free sources (DEV-058, 2026-10-03)

Ross (2026-10-03): find a free source for historical (point-in-time) 400/600 membership; verify it; if none, disclose
and note for re-investigation. Our WRDS subscription does not include the S&P index-constituent tables.

## Found and verified: SEC EDGAR filings of the index-tracking ETFs (free, public, regulatory)

An index ETF must hold the index. Its holdings filings are therefore a dated, public record of membership.

**S&P MidCap 400 — SPDR S&P MidCap 400 ETF Trust (MDY), EDGAR CIK 936958.** A single-fund filer, so every filing
is one index's holdings:
- `N-30D` shareholder reports with the full schedule of investments: one per fiscal year (as of Sept 30), filed
  2001-12 → 2025-12 (earliest filed listing in the EDGAR index is 1996; the list from `data.sec.gov` starts 2001).
- `NPORT-P` quarterly holdings (machine-readable XML), from 2019-09-30 onward.

**Verification (2026-10-03).**
1. Parse check: NPORT 2019-09-30 → 401 holdings (400 index stocks + cash sweep). N-30D 2007-09-30 → 393 of 400 names
   parsed by a first-pass regex (a few names with unusual formatting still to handle).
2. Independent cross-check against S&P's own announcement (press.spglobal.com, 2019-09-06; effective before the open
   on 2019-09-23): all **9 of 9 additions** (SIGI, RGEN, FCFS, ETSY, PPC, KAR, AM, OC, PEN) are present in the
   2019-09-30 holdings and **0 of 9 deletions** (SIG, RRC, TUP, MIK, QEP, VAL, MDR, CARS, MNK) are. 18/18 agree.

**Limits (disclose when used).**
- Granularity: annual snapshots 2001-2019, quarterly after. Names that joined and left between snapshots are missed.
  The fix is S&P's dated press releases (press.spglobal.com), which list every change with its effective date: the
  plan is to rebuild membership by applying announcements between snapshots, and to use the snapshots as the check
  (any mismatch = a missed announcement).
- Identifiers: N-30D gives names only (match to CRSP by name and holdings date, then check by hand where ambiguous);
  NPORT gives CUSIPs (392 of 401 holdings carry one; matching to CRSP `ncusip` not yet done).
- ETF holdings can differ briefly from the index around change dates; the quarter-end snapshot is the record date.

## S&P SmallCap 600: iShares Core S&P Small-Cap ETF (IJR), EDGAR series S000004313 (iShares Trust, CIK 1100663)
Quarterly `NPORT-P` per series (28 filings, from 2019-09-30). Before 2019 the trust's N-Q / N-CSR filings cover all
iShares funds in one document (to be parsed). SPDR S&P 600 Small Cap (SLY, series S000006989) is a second source.

**Verification (2026-10-03).** 2019-09-30 holdings: 607 lines. Same S&P announcement (effective 2019-09-23): **10 of
10 additions** present (SIG, RRC, TUP, MIK, QEP, VAL, MDR, HCC, CADE, GCP); **9 of 10 deletions** absent. The
exception, Ascena (ASNA), is still held: a **$261k residual, 0.0006% of the fund**, in a sub-$1 stock the fund was
still selling. That is an ETF-vs-index difference, not a membership disagreement, and it sets the rule for building
membership from holdings: **S&P's dated announcements are the primary record; holdings are the cross-check, with a
minimum-weight cut so leftover positions are not counted as members.** Overall cross-check: 37 of 38 changes agree;
the 1 disagreement is explained.

## Checked and rejected
- yfiua/index-constituents (GitHub, Apache-2.0): no 400/600, history only from 2023-07.
- iShares dated-holdings download endpoint: returns a web page, not data, for past dates.
- EODHD membership history (400/600 from 2012-04): paid — excluded by the free-data rule.
- Wikipedia scrapers (already used for current constituents): current membership only.

## Status
Feasible and verified for both indices on one rebalance (38 changes; 37 agree, 1 explained). Next before use: check
more rebalances spread across 2001-2026 (annual N-30D era too), and the press-release archive's coverage back in time.
Not yet built into the pipeline: this would change the universe definition, a methodology decision, so it
enters as a comparison arm first (CLAUDE.md).
Until then the survivorship limit stays disclosed as is.
