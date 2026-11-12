> **STATUS (2026-11-12): UNVERIFIED -- do not use as an exclusion list.** Compiled by a search subagent largely from
> recall (11 high / 34 medium / 17 low confidence of 62 rows; no SEC full-text check; the papers' issuer appendices
> not retrieved). P2 instead classifies only the 22 share-class pairs that pass its ADV gate, each against a source
> (Development.md 2026-11-12). Kept as a starting point for any wider use.

# US tracking stocks 1984-2024: notes

## Method / sources
Web fetches that returned usable content: Wikipedia "Tracking stock" (mainly Liberty, Applera, Quantum, Disney, AT&T/Sprint), CFO.com "Making Tracks" (2000; issue dates for GM Hughes, CMS, Sprint PCS, AT&T Liberty, Perkin-Elmer, Fletcher Challenge, Circuit City, Ziff-Davis, DLJdirect, Snyder/Circle.com), Journal of Accountancy 1999 (GM, USX, DuPont, DLJ, Georgia-Pacific, US West, Pittston, Ralston), Iowa working paper abstract (Billett & Vijh). Claremont thesis says 41 issuances 1984-2009; J. of Accountancy 1999 says 15 companies / 37 trackers by mid-1999. Neither full sample list was retrievable (paywalled/binary PDF).
Most tickers, dates and end events in the CSV are from the agent's background knowledge, NOT verified against SEC filings. Where unsure the field is blank. source_url is the best reference page consulted or relevant, not always a page that confirms every field.

## Confidence
high = 11, medium = 34, low = 17 (62 rows including parent-class counterpart rows, which are marked as such). Confidence "high" rows are well-known with consistent recollection plus Wikipedia coverage; still treat dates as year-month approximate.

## Known gaps / unverified
- The population is likely 41+ issuances; this list is not proven complete. Unreached: full D'Souza & Jacob (2000), Billett & Vijh (2004), Chemmanur & Paeglis appendices. Needs SEC EDGAR full-text / those appendices.
- Not verified: USX Marathon ticker, Delhi Group end, CMS Gas/Panhandle group names and dates, Ralston Purina groups, Pittston group dates, Fletcher Challenge ADR tickers (several divisional ADRs likely missing), Cablevision RMG dates, Staples.com dates, Cendant Move.com (may never have traded), Qurate/QVC ticker renames (QVCA vs QVCGA).
- Probably missing issuers (unchecked): DuPont life sciences (announced 1999, apparently never issued), NY Times Digital (vote scheduled 2000, outcome unverified), small-cap Internet-era trackers, Sony Communication Network (Japan-listed, out of scope), Alcatel (not US-listed tracker).
- NBCi (GE) was a separate company, not a tracker; excluded. Prudential Class B (Closed Block) was not exchange-listed.
- Also check: Nasdaq 5th-letter variants (e.g. Liberty K shares) were included where known; TCI/Liberty B-series tickers are inferred by pattern.
- Parent-like counterpart classes (GM common, USW, FON, GP, CC, CVC, WCOM, FNF) are listed because exclusion of pairs needs both legs.

## Second list: NOT tracking stocks, but structurally different economic claims (unverified, from memory, medium/low)
- Hershey: Common vs Class B; Class B dividend fixed in charter at 110% (approx.) / common per charter terms; Class B convertible 1:1 (verify direction).
- Constellation Brands (Class A vs B, until 2022): Class B convertible 1:1 with dividend differential in charter.
- Greif: Class A vs Class B dividend ratio fixed by charter (B receives 1.5x A per recollection).
- Berkshire Hathaway A vs B: A converts to 1,500 B; economic claim is 1:1500, not 1:1 (price ratio structural, not a tracking relationship).
- Dual-listed companies with fixed equalization ratios: Royal Dutch / Shell Transport (60/40), Unilever NV/PLC, BHP Ltd/Plc, Carnival Corp/plc, Reed Elsevier; ADR ratios generally.
- Classes with equal economics but different votes (Alphabet GOOG/GOOGL, Comcast CMCSA/CMCSK, Fox/News Corp, Brown-Forman): economically identical, the control case, not exclusions.
- Prudential Class B (Closed Block Business): not exchange-listed.
- Preferred or non-1:1 convertibles (e.g. Qurate preferred) behave like different claims; not enumerated.
