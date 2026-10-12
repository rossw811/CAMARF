# Data Sources Survey (WRDS inventory + WSU resource list)

*Drafted 2026-10-12 by a Sonnet survey agent (read-only, from output/research/wrds_library_inventory_20260927.parquet + the WSU list); claims checked before use -- one correction made (B1, FX already done). Access marked FULL vs SAMPLE is from library names; confirm entitlement with a WRDS query before building on a source.*

Generated 2026-10-12. Read-only survey; no WRDS connection made (login guard respected — all
findings below come from `output/research/wrds_library_inventory_20260927.parquet`, a prior
offline inventory snapshot, plus static code grep). Sample/trial libraries (names ending
`samp`/`_samp`/`trial`/`smp`) give schema/table-name visibility only, not usable row counts or
full history — treat as "know it exists, can't use it for research without upgrading."

## A. Resource inventory

### A1. Resources on the WSU list

| Resource | Access path (library, n_tables) | Full/Sample | Contains | Relevance | Study it enables | Used in repo? | Redistribution note |
|---|---|---|---|---|---|---|---|
| Business Source Complete | Web only (EBSCO) — not a WRDS SQL library | N/A | Business/econ journal full text | Low — literature search tool, not data | Lit review for PAPER.md related-work section | No | N/A, no data redistribution issue |
| EconLit | Web only (EBSCO) | N/A | Econ literature abstracts/index | Low — same as above | Lit review | No | N/A |
| CCH AnswerConnect | Web only, tax research platform | N/A | Tax code/regulations | Low — no market data | None for this thesis | No | N/A |
| Checkpoint RIA | Web only, tax research platform | N/A | Tax/accounting research | Low | None | No | N/A |
| Audit Analytics | `audit` (388), `audit_audit_comp` (59), `audit_corp_legal` (86), `audit_common` (2) | FULL | Auditor changes, restatements, internal-control weaknesses, litigation | Med — restatements are a plausible pair-break event, like earnings surprises | Test whether a restatement/auditor-change event predicts a cointegration break | No | WRDS terms: no bulk redistribution of raw rows, aggregated outputs OK |
| Bank Regulatory | `bank` (43), `bank_all` (21) | FULL (`banksamp`/`bank_premium_samp` are the sample variants) | Call Report / FR Y-9C bank holding company financials | Low-Med — only relevant if a bank-sector basket is studied | Bank-sector regime/liquidity proxy | No | Same WRDS terms |
| Beta Suite | Not identified under an obvious library name in this inventory | Unclear | WRDS's pre-computed CAPM/market betas (if subscribed) | Med if present — would replace an in-house rolling-beta calc | Cross-check in-house beta/Hurst calcs against a vendor benchmark | No | Verify exact library name with WRDS support before relying on absence |
| Blockholders | `block` (3), `block_all` (3) | FULL | Large (>5%) shareholder stakes, Dlugosz/Fahlenbrach/Gompers/Metrick data | Med — overlapping large holders across two names is a concrete comovement-driver test | Does shared-blockholder overlap predict/explain confirmed-pair comovement strength? | No | Same WRDS terms |
| BoardEx | `boardex` (168), `boardex_na` (42) | FULL (`boardex_trial`/`boardsmp` are samples) | Director/officer bios, board composition, network/relationship data | High — director interlocks are a textbook economic-linkage channel, directly testable against confirmed pairs | Regress pair confirmation rate / spread half-life on shared-director count | No | WRDS terms; network-derived features (not raw person records) are fine to publish |
| Calcbench | `calcbnch` (26) | FULL (`calcbench_trial` is sample) | XBRL-tagged fundamentals, point-in-time as-reported financials, earnings call metadata | Med — point-in-time fundamentals (no restatement lookahead) complement Compustat's as-revised figures | PIT fundamental-divergence feature without Compustat's restatement bias | No | WRDS terms |
| CRSP | `crsp` (433), `crsp_a_stock` (95), `crsp_a_indexes` (113), `crsp_a_ccm` (12), `crsp_q_mutualfunds` (29) | FULL | US equity prices/returns, delisting, index membership, CRSP-Compustat link | High — this is the project's primary equity price source already | Already the backbone of `universe_loader`/cointegration screen | **Yes** — `data_wrds.py` (`dsf_v2`, `msf_v2`, `stocknames`, `dsp500list_v2`, `ccmxpf_lnkhist`) | WRDS terms; derived signals OK, raw CRSP rows not redistributable |
| Compustat | `comp` (293), `comp_global_daily` (125), `comp_na_daily_all` (206), `comp_bank_daily` (20), `comp_execucomp` (15)/`execcomp` (15), `compseg`/`comp_segments_hist_daily` (14) | FULL (`compsamp*` are samples) | Fundamentals (`funda`), global daily prices (`g_secd`), segment data, executive comp | High — international legs of the universe, and `rdq` (report dates) for earnings-event features | Already used for international equities; `rdq` could drive an earnings-divergence pair-break predictor (open item) | **Yes** — `data_wrds.py` (`comp.funda`, `comp.company`, `comp_global_daily.g_secd`/`g_company`/`g_idxcst_his`/`g_idx_index`) | Same; Global legs still local-currency pending R1.1 FX fix |
| DMEF | `dmef` (4), `dmef_all` (4) | FULL | Direct-marketing customer transaction data | Low — consumer marketing, no asset-pricing content | None identified | No | N/A |
| Dow Jones Averages | `djones` (2), `djones_all` (2) | FULL | DJIA/DJ Transportation/Utility historical index levels | Low — redundant with existing index data, occasionally useful as a long-history benchmark | Long-history regime benchmark predating CRSP coverage | No | Same WRDS terms |
| Efficient Frontier | Not identified under an obvious library name | Unclear | Possibly a WRDS portfolio-optimization web tool, not a queryable table | Low | N/A until confirmed | No | Verify with WRDS support |
| Event Study / Eventus | `eventus` (14), `evts_all` (14) | FULL | Event-study abnormal-return calculation engine/tables | Med — could replace ad hoc event-study code for the earnings/M&A break-cause tests | Standardized abnormal-return calc around confirmed pair-break dates | No | Same WRDS terms |
| Fama-French + Pastor-Stambaugh liquidity | `ff` (12), `ff_all` (12) | FULL | 3/5-factor daily/monthly factors, momentum | High for factor exposures | Already fetched; the Pastor-Stambaugh *liquidity* factor specifically was not confirmed as a distinct table in this inventory (not a separate library) — verify its exact table name inside `ff`/a WRDS "Liquidity Measures" page before citing it | **Yes** — `data_wrds.py` (`ff.factors_daily`, `ff.fivefactors_daily`) | Same WRDS terms |
| Federal Reserve Bank Reports | `frb` (4), `frb_all` (4) | FULL | H.10 FX rates, H.15 interest rates, regional Fed indexes | High — this is the direct fix for the open Compustat Global local-currency issue (R1.1) | FX-convert Compustat Global local-currency closes to USD | **Yes** — `data_wrds.py` (`frb_all.fx_daily`); `research/apply_fx_to_wrds_global.py` applies it, but CLAUDE.md still lists R1.1 as open — confirm whether that script's output is actually wired into the loader | Same WRDS terms |
| Financial Ratios Suite | `wrdsapps_finratio` (2), `wrdsapps_finratio_ccm` (2), `wrdsapps_finratio_ibes` (2), `wrdsapps_finratio_ibes_ccm` (2) | FULL | Pre-computed valuation/liquidity/profitability/solvency ratios, CRSP/IBES-linked | Med-High — removes a whole class of in-house ratio-calc bugs, and is a ready-made fundamental-divergence feature set | Fundamental-divergence-as-pair-break-predictor, without reimplementing ratio formulas | No | Same WRDS terms |
| Global Financial Development DB | Not identified under an obvious library name (checked `trsamp_db_wb`/`trdbwbsmp` — those look like a different Datastream/World-Bank sample, not confirmed as GFD) | Unclear | World Bank cross-country financial-development indicators | Low — macro/country-level, not asset-pricing | Country-level regime context, low priority | No | Verify with WRDS support |
| IBES | `ibes` (194), `tr_ibes` (166) | FULL | Analyst estimates, price targets, recommendations | Med-High — analyst coverage overlap and consensus-target divergence are plausible comovement/break features | Already used for price targets; extend to estimate-revision divergence as a break predictor | **Yes** — `data_wrds.py` (`ibes.ptgsum`), `research/price_target_pairs_overlay.py`, `research/build_wrds_supplementary_data.py` | Same WRDS terms |
| ISS (governance/voting) | Not found in this inventory under any obvious name (`iss`, `issgov`, etc. — no match) | Not confirmed accessible | Governance ratings, proxy voting records | Unclear until confirmed | Governance-quality control variable | No | Verify subscription with WRDS support — may simply not be entitled under this account |
| MSCI (KLD/GMI ESG) | Only sample libraries present: `mscicsmp` (16), `msciesmp` (18), `mscicoms` (3), `msci_climate_samp`/`msci_common_samp`/`msci_esg_samp` | **SAMPLE ONLY** | ESG ratings, governance scores | Low for this thesis, but flagged: the WSU list claims MSCI access and the inventory shows only samples — discrepancy to resolve before counting on it | ESG-overlap-as-comovement-driver, if full access is actually confirmed | No | Sample data not meaningfully usable for research; clarify entitlement |
| MSRB municipal trades | `msrb` (3), `msrb_all` (3) | FULL (`msrbsamp` is the sample) | Municipal bond trade reports | Low — munis are out of scope (equities/crypto/FX focus) unless scope expands | None currently | No | Same WRDS terms |
| Mutual Fund Links (MFLINKS) | `mfl` (3), `mflinks_all` (3) | FULL | CRSP mutual fund ↔ Thomson/CRSP security links | Med — mutual-fund common ownership is a comovement channel, similar rationale to 13F | Shared-fund-ownership overlap as a comovement/break feature | No | Same WRDS terms |
| OTC Markets | `otc` (1), `otc_endofday` (1) | FULL | OTC equity end-of-day quotes | Low-Med — could extend the ~44,700-symbol universe to OTC names not in CRSP/Compustat | Universe-coverage extension check | No | Same WRDS terms |
| Penn World Tables | `pwt` (7), `pwt_all` (7) | FULL | Cross-country macro (GDP, PPP, capital stock) | Low — country-macro, not security-level | Macro regime context, low priority | No | Same WRDS terms |
| Peters-Taylor Total Q | `totalq` (1), `totalq_all` (1) | FULL | Intangible-capital-adjusted Tobin's Q | Low-Med — a fundamental-divergence variable, niche | Alternate fundamental-divergence feature vs. standard Q | No | Same WRDS terms |
| PHLX currency options | `phlx` (2), `phlx_all` (2) | FULL | Philadelphia exchange FX option data | Low — niche, thin modern relevance (PHLX FX options largely legacy) | Historical FX-vol context only | No | Same WRDS terms |
| Research Quotient | `rq_all` (1) | FULL | Firm-level R&D-productivity measure (Knott) | Low | Possible fundamental-divergence control, low priority | No | Same WRDS terms |
| SEC Order Execution (Rule 605) | Not clearly identified — `secsamp`/`secsamp_all`/`wrdssec*`/`wrds_sec_search` present but none confirms Rule 605 execution-quality reports by name | Unclear | If present: broker/market-center execution-quality stats | High if confirmed — directly answers the project's own open execution-cost-realism gap in the backtest | Realistic slippage/fill-quality calibration for `backtest.py` | No | Verify exact library name with WRDS support before counting on it |
| Thomson Reuters 13F | `tr_13f` (7) | FULL | Institutional 13F equity holdings | High in concept, already investigated | Already explored (`research/thread_k_part2_fund_membership_fetch.py`, 2026-08-14) and **excluded**: `tr_13f.s34` is ticker-keyed and CAMARF's universe uses PERMNO/synthetic labels that can't reliably match it — would need a CRSP-CUSIP-to-13F link table first | No (deliberately, see above) | Same WRDS terms |
| TRACE corporate bonds | `trace` (32), `trace_enhanced` (14), `trace_standard` (23) | FULL | Corporate bond transaction-level trade reports | High — direct enabler of the open cross-asset bond-equity comovement extension | Bond-equity pair discovery for the same issuer/sector, parallel to the equity-equity screen | No | WRDS/FINRA terms restrict redistribution of raw TRACE records more tightly than most WRDS data — check the TRACE-specific agreement before any output sharing |
| Value Line | Not identified under an obvious library name (`shvlsamp`, 2 tables, might be a short-interest/Value-Line sample but unconfirmed) | Unclear | Value Line stock reports/estimates, current + historical PDF archive | Low-Med — PDF archive isn't SQL-queryable, limited automation value | Qualitative cross-check for the PAPER.md writeup only | No | Verify with WRDS support |
| World Indices | `wrdsapps_windices` (3) | FULL | Country total-return index series | Med — already covers international regime/benchmark context Compustat Global's price-only series doesn't | Country-index benchmark overlay for international regime analysis | No | Same WRDS terms |
| PitchBook | Web-only (PitchBook platform) + `pitchsmp` (71 tables) **sample** library on WRDS | SAMPLE ONLY on WRDS; full access only via the separate web platform | PE/VC deals, M&A, valuations | Med — M&A event dates are a plausible pair-break cause | M&A-event-as-break-cause test (pairs where one leg is acquired) | No | Web platform has its own ToS; WRDS sample not usable for real coverage |
| FactSet | `factsamp_all` (28), `factsamp_revere` (12) | **SAMPLE ONLY** on WRDS | Supply-chain/Revere relationship data, financials | Flag: WSU list claims FactSet access but inventory shows WRDS-side samples only — full FactSet (if it exists) is likely via a separate FactSet workstation license, not WRDS | Supply-chain-linkage-as-comovement-driver, if full access confirmed elsewhere | No | Sample not usable for real coverage; verify where full access actually lives |

### A2. Notable WRDS libraries in the inventory, not on the WSU list

| Resource | Access path | Full/Sample | Contains | Relevance | Study it enables | Used in repo? | Redistribution note |
|---|---|---|---|---|---|---|---|
| S&P Capital IQ (CIQ) | `ciq` (259), `ciq_capstrct` (44), `ciq_common` (59) | **FULL** (`ciqsamp*` are samples) — not on the WSU list at all but fully entitled | Capital structure, deals, key developments, transcripts, people intelligence | High — this is a major undisclosed asset: capital-structure and key-development event data overlapping with the M&A/break-cause and fundamentals use cases | Capital-structure-change or "key development" event as a pair-break cause, overlap with SDC for M&A | No | Same WRDS terms |
| SDC Platinum (M&A) | `sdc` (68) | **FULL** (`sdcsamp` is the sample, `tr_sdc_ma`/`tr_sdc_ni` also full) | Mergers & acquisitions, new issues, joint ventures | High — this already answers the M&A-event-as-break-cause item the PitchBook-sample gap leaves open; no need to chase PitchBook/web PitchBook for this | M&A-announcement-to-pair-break-date lag test, full history | No | Same WRDS terms |
| CBOE | `cboe` (90) | FULL-looking (90 tables; `cboe_all`/`cboe_sample`/`cboesamp` are much smaller) | Options/volatility data (exact table contents unclear from name alone) | Med — potential options-implied-vol source if OptionMetrics isn't available | Cross-check against yfinance-derived vol if table contents confirm usable options data | No | Same WRDS terms; verify table contents before relying on it |
| TAQ / TAQM (intraday) | `taqmsamp`/`taqmsamp_all` (58), `taqsamp`/`taqsamp_all` (14/64) | **SAMPLE ONLY** | Millisecond-level NBBO/trade data (sample days only) | High in concept, blocked in practice — full TAQ not in this inventory at all | Intraday/microstructure robustness check for execution-cost realism, if full TAQ is ever obtained | No | Samples cover a handful of sample days only — not usable for a real backtest |
| OptionMetrics (IvyDB) | Not present at all — only `optionmsamp_europe`/`optionmsamp_us` (12 each) | **SAMPLE ONLY** | Implied volatility surfaces, option greeks | High in concept for the option-implied-information shortlist item, blocked — full access not entitled | Option-implied skew/term-structure as a regime or break signal, if ever obtained | No | Sample only, not usable |
| RavenPack | `ravenpack_trial` (8) | **SAMPLE/TRIAL ONLY** | News sentiment/event scores | Low-Med, blocked by access | News-sentiment overlay on regime classification, if obtained | No | Trial only |
| WRDS linking tools (`wrdsapps_link_*`) | `wrdsapps_link_crsp_ibes`, `_link_crsp_comp_bdx`, `_link_crsp_taq`, `_link_crsp_bond`, `_link_crsp_factset`, `_link_supplychain`, `_link_comp_eushort`, `_plink_boardex_trinsider`, `_plink_exec_boardex`, `_plink_exec_trinsider` (1-2 tables each) | FULL | Pre-built WRDS crosswalks between CRSP/Compustat/IBES/TAQ/bond/BoardEx/insiders identifiers | High utility, low thesis-novelty — these are exactly the linking tables the 13F ticker-key mismatch (A1) needs; `_link_crsp_bond` would support the TRACE bond-equity extension; `_plink_*` support the BoardEx interlock study | Removes the manual-linking blocker found in `research/thread_k_part2_fund_membership_fetch.py` | No, but directly relevant to fixing that exclusion | Same WRDS terms |
| Contributed datasets (`contrib_*`) | `contrib_global_factor` (4), `contrib_patent_firm_link` (2), `contrib_intangible_value` (2), `contrib_char_returns` (1), `contrib_corporate_culture` (1), `contrib_ceo_turnover` (1), `contrib_kpss` (2), `contrib_bond_firm_link` (1), `contrib_corp_fed_litigation` (2), `contrib_liva` (1) | FULL | Academic-contributed factor/firm-characteristic panels (global factor zoo, patent-firm links, intangibles, corporate culture scores) | Med — `contrib_global_factor` is a ready factor-zoo panel that could stand in for custom-built factor exposures; `contrib_patent_firm_link` is relevant to a technology-linkage comovement channel | Factor-zoo robustness check against in-house factor construction | No | Same WRDS terms, these are academic contributions — check each one's specific citation requirement |
| Execucomp | `comp_execucomp`/`execcomp` (15) | FULL | Executive compensation | Low-Med | Executive-pay-structure as a governance control variable | No | Same WRDS terms |
| DealScan | `dealscan` (31) | FULL-looking | Syndicated loan data | Low — loans, not public equity/bond trading | None currently | No | Same WRDS terms |
| Macro-finance / commodity trade | `macrofin` (24), `macrofin_comm_trade` (24) | FULL | Macro-finance and commodity trade panels | Med — directly touches the "also spans commodities" scope line in CLAUDE.md | Commodity cross-asset regime context | No | Same WRDS terms |
| WRDS Public (BEA/BLS) | `public` (15), `public_all` (11) | FULL | BEA/BLS macro series | Low-Med — macro regime context, FRED (already used via `macro.py`) likely already covers most of this | Redundancy check against existing FRED-based `macro.py` regime features | No, but `macro.py` already covers FRED | Same WRDS terms |

## B. Top ~12 highest-value additions (ranked)

1. ~~`frb_all.fx_daily` → finish wiring the FX conversion for Compustat Global~~ **[Corrected 2026-10-12 on review: already done.** R1.1 was fixed 2026-09-27 -- `research/apply_fx_to_wrds_global.py` wrote `close_usd` to 15,093 global files from Compustat's own daily rates (`g_exrt_dly`), and `universe_loader.py:299-306`, the discovery scan and the adapter read it. Only CLAUDE.md's wording was stale. H.10 remains useful as an independent cross-check of Compustat's rates.]
2. **`wrdsapps_link_crsp_bond` + TRACE (`trace_enhanced`/`trace_standard`)** — enables the
   cross-asset bond-equity comovement extension on the shortlist, and the link table removes the
   identifier-matching blocker that killed the 13F idea.
3. **SDC (`sdc`, full 68 tables) for M&A-event-as-break-cause** — already fully entitled,
   undisclosed in the WSU list, and directly answers the M&A break-cause shortlist item without
   waiting on PitchBook (WRDS-side PitchBook is sample-only).
4. **BoardEx (`boardex`, full 168 tables) for board-interlock comovement** — matches the WSU list
   and the shortlist's interlock-as-linkage item; `wrdsapps_plink_exec_boardex`/
   `_plink_boardex_trinsider` are the ready-made crosswalks.
5. **Financial Ratios Suite (`wrdsapps_finratio*`) for fundamental-divergence features** —
   removes a class of in-house-ratio-calc risk and is a direct earnings/fundamental-divergence
   pair-break predictor, same rationale as Compustat `rdq`/IBES.
6. **IBES estimate revisions (beyond the existing `ptgsum` price-target use)** — extend
   `fetch_ibes_price_targets`-style usage to consensus-revision divergence as a second
   fundamental-divergence feature; already a proven integration path.
7. **`wrdsapps_windices` (World Indices) for international regime benchmarking** — a direct,
   cheap fix for the fact that Compustat Global gives price-only local-currency series; total-return
   country indices are a better regime/benchmark series than what's currently derived.
8. **Thomson Reuters 13F, retried via `wrdsapps_link_crsp_ibes`/a CRSP-CUSIP link instead of
   `tr_13f.s34`'s raw ticker key** — the common-ownership-as-comovement-driver idea (Anton & Polk
   "Connected Stocks") is sound; the 2026-08-14 exclusion was a linking problem, not a conceptual
   one, and #2's linking tables suggest the fix.
9. **Eventus (`eventus`, full) to standardize abnormal-return calculations** around confirmed
   pair-break dates — replaces ad hoc event-study code with a WRDS-maintained, citable
   methodology, which matters for the project's reproducibility-by-outsiders goal.
10. **MFLINKS (`mfl`) for shared mutual-fund-ownership overlap** — a lower-friction parallel to
    the 13F idea (no ticker-key problem), same "common ownership drives comovement" hypothesis.
11. **CIQ capital structure / key developments (`ciq`, full 259 tables)** — undisclosed in the
    WSU list, fully entitled, and overlaps the M&A/fundamental-event use cases; worth a scoping
    pass before building anything new on SDC alone.
12. **Calcbench (`calcbnch`, full) for point-in-time-as-reported fundamentals** — avoids
    Compustat's restated-figures lookahead risk for any fundamental-divergence feature that must
    be genuinely point-in-time, which matters given this project's PIT discipline.

Deliberately NOT shortlisted despite thesis relevance: OptionMetrics, full TAQ, RavenPack, ISS,
full MSCI, full FactSet — all confirmed sample/trial-only or unconfirmed-access in this
inventory; see Part C.

## C. Ask the library about

Resources commonly available to WSU students that are NOT on the provided list, with what this
survey could confirm from the WRDS inventory vs. what's a guess to verify in person/by email.

| Resource | Confirmed from inventory? | Note |
|---|---|---|
| Full OptionMetrics (IvyDB US/Europe) | **No** — only `optionmsamp_europe`/`optionmsamp_us` samples found | Guess to verify: ask WRDS support directly whether OptionMetrics is subscribed; the option-implied-info shortlist item depends on this |
| Full TAQ/TAQM (intraday NBBO) | **No** — only `taqsamp*`/`taqmsamp*` sample libraries found | Guess to verify: ask whether a full TAQ subscription exists; if not, intraday stays yfinance/IBKR-only per existing architecture rules |
| ISS governance/voting | **No** — no `iss*` library found at all | Verify whether ISS is actually subscribed under this account; WSU list claims it but inventory shows nothing |
| Full MSCI ESG (KLD/GMI) | **No** — only `msci*samp` sample libraries found | WSU list claims MSCI access; inventory disagrees — resolve before using in research |
| Full FactSet | **No** — only `factsamp_all`/`factsamp_revere` sample libraries found | Likely a separate FactSet workstation license, not WRDS-hosted; verify where (if anywhere) full access lives |
| Bloomberg Terminal lab | Not checked (not a WRDS library) | Guess — ask the WSU library/finance department whether a Bloomberg terminal lab exists on campus |
| LSEG/Refinitiv Workspace or Datastream | Not checked | Guess — WSU business school may have a separate Refinitiv subscription outside WRDS |
| S&P Capital IQ Pro (web UI, vs. the WRDS `ciq` SQL library confirmed in A2) | `ciq` SQL access confirmed; the web Pro UI is separate | Verify whether the web front-end is also licensed (useful for manual lookups, not bulk research) |
| Morningstar Direct | Not checked | Guess — common at business schools, ask library |
| Mergent (Intellect / Online) | Not checked | Guess — common bond/company-data product at university libraries, ask library |
| WSU Kamiak HPC cluster | Not checked (infra, not data) | Guess to verify — relevant for scaling the full-universe correlation matrix beyond the Surface's 16GB RAM constraint noted in CLAUDE.md; ask WSU research computing for an account |
| Cloud/education credits (AWS/Azure/GCP academic) | Not checked | Guess — ask WSU IT or check for a standing academic credit program |
| GitHub Student Developer Pack | Not checked | Guess — free, easy to confirm independently at education.github.com, not library-gated |

## D. Exploratory / adjacent uses

Per scope update: every source below is worth exploring for ANY quant/financial research
question, not only this thesis's cointegration/comovement focus. These are off-thesis candidate
directions, not commitments — each would need its own buy-in discussion before building, per
this project's "new methodology/data source → discuss first" rule.

**Private markets — PitchBook (web + `pitchsmp` sample, 71 tables), CIQ private-company/
key-developments data (visible inside `ciq`/`ciq_capstrct`/`ciq_common`, full 259+44+59 tables),
SDC (`sdc`, full 68 tables), DealScan (`tr_dealscan`/`dealscan`, full 31 tables)**

- *PitchBook (`pitchsmp`) / CIQ key-developments*: PE/VC deal flow (round count, round size,
  sector concentration) as a leading sector-sentiment or regime signal for public peers in the
  same sector — does a VC funding surge in a sector precede a shift in that sector's public
  comovement structure? Data path: `pitchsmp` deal tables (sample scope only) or CIQ
  "key developments" event feed for financing rounds, joined to Compustat/CRSP by sector (GICS).
- *PitchBook / CIQ private-company financials*: private-round valuations vs. public comps
  ("marks lag") — do late-stage private marks systematically lag or lead public-market repricing
  of the same sector, and is the lag itself tradeable or just a measurement-timing artifact?
  Data path: CIQ private-company valuation/round tables vs. sector ETF or peer-basket price
  series already in the universe loader.
- *SDC (`sdc`, `tr_sdc_ma`)*: IPO and lockup-expiry event studies — abnormal
  volume/volatility/comovement-with-sector around lockup expiry, a cleaner, better-dated event
  than earnings for testing the project's event-based break-cause framework; SPAC-specific events
  (de-SPAC announcement, redemption deadlines) as a related, higher-volatility variant. Data
  path: SDC new-issues/IPO tables for issue date + lockup length, joined to CRSP daily returns.
- *SDC (`sdc`, `tr_sdc_ma`)*: M&A announcement effects on public pairs — already in Part B (#3)
  for the break-cause angle; the adjacent, lower-stakes version is LBO targets' pre-deal
  comovement with sector peers (does a stock quietly decouple from its usual comovement partners
  before an LBO announcement — a detectable pre-announcement drift distinct from insider-trading
  enforcement data)? Data path: SDC M&A deal-type flag for LBO, joined to the existing episodic
  cointegration-confirmation pipeline on the target's confirmed pairs.
- *DealScan (`tr_dealscan`)*: syndicated-loan lender networks as a credit-linkage channel
  between borrowers — two firms sharing a lead arranger or loan syndicate is a different
  "connectedness" mechanism than common ownership (13F/MFLINKS) or board interlocks (BoardEx);
  worth a comparison of which linkage type best predicts comovement strength, as its own small
  methods paper rather than a CAMARF production feature. Data path: DealScan
  lender/borrower/syndicate tables, built into a bipartite graph, projected to a borrower-borrower
  "shared lender" adjacency matrix for comparison against BoardEx/MFLINKS-derived adjacency.

**Bloomberg Terminal** (confirmed by Ross to exist somewhere accessible, not found in this
WRDS inventory — it's a separate platform)

- Unique value-add over WRDS/yfinance: BQL (Bloomberg Query Language) and the Excel add-in for
  fast ad hoc cross-checks; BVAL evaluated pricing for bonds/illiquid instruments (a plausible
  source of independent marks to validate TRACE-derived bond prices against); ownership data
  with different coverage/timeliness than 13F; SPLC (supply-chain linkage) data as yet another
  comovement-channel candidate alongside BoardEx interlocks and DealScan credit links; real-time
  news with sentiment tagging.
- Licence limits matter here: Bloomberg's terminal agreement does not permit bulk export or
  redistribution of its data — this makes it unsuitable as a bulk research data source for a
  public, reproducible-by-outsiders repo (this project's own stated scrutiny-first goal), but
  well suited for one-off validation/spot-checks (e.g. manually verify a sample of TRACE bond
  prices or 13F holdings against the terminal) and for checking facts that don't need to be
  redistributed, like confirming a ticker or event date.

**WSU Kamiak HPC cluster**

- What it is: Washington State University's shared research-computing cluster (compute nodes
  well beyond the Surface's 16GB RAM / ARM64-emulation constraints noted in CLAUDE.md).
- Typical access model at research-computing clusters like this: usually requires a faculty
  sponsor/PI account, not a general student account — Ross would need to confirm the exact
  WSU Kamiak policy (this wasn't verifiable from the repo; flagged as a guess to confirm, same
  as the Part C items).
- CAMARF workloads that would benefit: the full ~44,700-symbol universe correlation matrix
  (explicitly called out in CLAUDE.md as RAM-constrained on the Surface and only sent to CachyOS
  today); the episodic rolling-window cointegration screen across the full universe (currently
  presumably chunked/sequential to fit in 16GB); placebo/null-distribution discovery runs (the
  BH-FDR confirmation step's honesty depends on a well-powered placebo/null run across the full
  universe, which is exactly the kind of large, parallel, one-off batch job a cluster queue is
  for, rather than tying up the Surface or CachyOS for hours); statistical-power curves (how
  many PIT walk-forward windows / how much history is needed to detect a given effect size at
  the project's FDR threshold — an embarrassingly parallel sweep over simulated/null data); and
  any RMT/eigenportfolio decomposition over the full correlation matrix — all memory-bound or
  trivially parallel in ways a real HPC allocation would remove as a bottleneck, as a third
  option alongside the Surface and CachyOS.

**Off-thesis ideas from other already-covered WRDS resources**

- *TRACE (`trace_enhanced`/`trace_standard`)*: beyond the on-thesis bond-equity comovement use
  (Part B #2), a pure fixed-income study — corporate bond liquidity (bid-ask proxies from trade
  reports) as its own regime-dependent phenomenon, independent of any equity leg.
- *MSRB (`msrb`)*: municipal bond market microstructure/liquidity study, or a muni-vs-Treasury
  spread regime classifier — a different asset class entirely from CAMARF's current scope, but
  the same regime-detection methodology could transfer.
- *Bank Regulatory (`bank`/`bank_all`)*: bank holding company balance-sheet stress indicators
  (e.g. Call Report leverage/liquidity ratios) as an early-warning regime signal tested against
  the existing macro regime classifier in `macro.py`.
- *Audit Analytics (`audit`/`audit_corp_legal`)*: restatement/going-concern-opinion timing as a
  standalone event-study subject (abnormal returns around restatement disclosure), independent
  of any pair-trading application — a clean, well-trodden accounting-event-study exercise.
- *ISS/BoardEx governance*: a pure governance-quality factor study — does a governance-score
  factor (if ISS access is ever confirmed) or a BoardEx-derived board-independence measure earn
  a return premium independent of the comovement work, a classic corporate-finance question.
- *Value Line archive (if access confirmed)*: a historical-forecast-accuracy study — compare
  Value Line's own analyst projections (available back to 1998) against realized outcomes, as an
  analyst-forecast-bias paper distinct from the IBES-based work already planned.
- *World Indices (`wrdsapps_windices`)*: international regime synchronization — do country
  total-return indices show the same regime-dependent comovement structure CAMARF finds in US
  equities, a direct cross-market replication test of the thesis's core claim.
- *Penn World Tables (`pwt`)*: a macro-finance side project relating cross-country capital-stock/
  productivity growth to the long-run level of cross-asset comovement — more development
  economics than market microstructure, genuinely off-thesis but publishable as its own small
  study.
- *SEC Order Execution (Rule 605, library unconfirmed)*: if ever located, a pure execution-
  quality/market-structure paper — broker/venue fill-quality comparison, independent of any
  specific trading strategy, valuable for anyone studying market microstructure generally.

## Summary notes

- WRDS entitlement facts above come solely from a single prior offline inventory snapshot
  (`output/research/wrds_library_inventory_20260927.parquet`, dated 2026-09-27); it could be stale
  if entitlements changed since. Re-run `research/wrds_capability_audit.py` interactively to
  refresh when next doing a live WRDS session.
- Three resources on the WSU list (MSCI, FactSet, and to a lesser extent PitchBook) show up in
  the WRDS inventory as sample-only, contradicting the "have access" framing of the resource list
  as given — flagged in Part A/C rather than silently assumed resolved.
- `tr_13f` (13F) is fully entitled but was already deliberately excluded from use
  (`research/thread_k_part2_fund_membership_fetch.py`, 2026-08-14) for a ticker-key mismatch, not
  for lack of access — Part B's #8 proposes revisiting that exclusion via a link table rather than
  re-litigating the original decision.
