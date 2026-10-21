# Every deferred / later / open item: a decision now (2026-10-20)

Ross, 2026-10-20: "read through anything that mentions deferred or later; let's make decisions now". Source: a
read-only sweep of all plans, decisions, drafts, ledgers, papers, FINDINGS, ERRATA, HANDOFF, Development.md (grep)
and code comments -- 241 rows, de-duplicated (raw table in the session; IDs as in the source docs). Below, every row
has ONE recommendation. Codes: **DO-Q** = re-derivation queue now (feeds a paper claim) · **FIX** = correctness fix
now, failing test first · **DO-L** = do, after the stated step · **CLOSE** = not pursued, reason recorded (reopen
only if a claim needs it) · **ROSS** = your call · **DISCLOSE** = keep as a published limitation, no work.

## Rules behind the decisions (approve these and the rows follow)
1. Anything a paper claim rests on is re-derived now (DO-Q); nothing is cited until registered.
2. Correctness defects in code that runs (rule violations, wrong statistics) are fixed now, failing test first (FIX),
   even if no current claim cites them -- they would otherwise contaminate the next one.
3. Defects in dormant code nothing calls or cites: disclosed, not fixed (DISCLOSE); the code is labelled dormant.
4. S27's deferred DEV ideas are closed with their reason unless a deep dive or claim needs them (CLOSE).
5. Approved explorations keep their order: E1 first (it is the reference point for every discovery claim), then
   E3-E8, E10-E12, E18. Off-thesis items are closed.
6. Data we do not have: one librarian email (your earlier "yes", never sent); no paid data.

## Corrections to the master plan from this sweep
- B1 memtest and B4 Bloomberg checklist: you said **no** on 2026-10-12 (DECISIONS round 2) -- CLOSED; my master plan
  wrongly listed them as open. B3 Kamiak: "maybe, via your linear-algebra instructor" -- ROSS.
- N12 BUG-D115: ERRATA says measured zero on the 10-12 re-run; CLAIMS_REGISTRY M-039 still says "not measured" --
  reconcile the registry to the ERRATA measurement (FIX, wording).

## Methodology / statistics
| ID | Decision | Note |
|---|---|---|
| N1-N11, N13, N14, N16, N17 | DO-Q | the re-derivation queue (master plan section 1), in order |
| N12 | FIX (wording) | registry M-039 to the ERRATA measurement |
| D6, D14/D15 check, D17 | DO-Q | D6 redesign; confirm pools exclude twins and the 85 labels (discovery still loads them -> exclude at load, FIX) |
| D16 + A7 | DO-Q | total-return P&L re-runs of pit_wfa / wrds_daily / distance / sensitivity (12 spread-unit callers) |
| D18 | ROSS | I propose specification-curve ranges per outcome-informed value with the registry work |
| S6 | DO-Q | adopt the common holdout date; report pairs with no holdout |
| S7/B9 | DO-Q | next-bar fill sensitivity on dollar P&L; next-bar becomes default if any number moves |
| S9/S10 | DO-L | check intraday liquidity gate vs WRDS volume; grid-phase check only if the check fails |
| S11 | DO-L | finish PIT S&P 400/600 verification (>= 10 rebalances), then the membership-filtered arm |
| S12 | merge into D6 | same CRSP point-in-time universe |
| S31/R1.3 | FIX | option (c): gated arm US-US only, international reported separately |
| S33 (tiers) | FIX | replace the mis-sized PO proxy with arch's Phillips-Ouliaris; drop KPSS from the tier; re-derive tier counts, or withdraw tiers if they change materially |
| S18, C-003, C-004, C-005, S19 | DO-Q | re-derive on the new pools |
| A5 | DO-L | grid-offset robustness after N2 |
| A6 | CLOSE | this re-run chain is the third labelled pass -- record it as such |
| E1 | DO-L | first after the queue |
| E3 | ROSS | approve the written TRACE design |
| E4, E5, E6, E7, E8, E10/E11, E12, E18 | DO-L | after E1, in this order: E7, E4, E5, E8, E6, E12, E18, E10/E11 |
| E9 | merged into N4 | |
| X-M01 jump-model regimes | ROSS | recommend yes, as a comparison arm vs HMM labels |
| X-M02 Hawkes clustered null | DO-L | after C-005 re-derived |
| X-M03 break-rule 3x/10x sensitivity | DO-Q | cheap; with N9 |
| X-M04 arm (c) inclusion DiD real run | DO-Q | data fetched (job 29) |
| X-M05 DEV-055 fresh holdout per evaluation | CLOSE | superseded by the sealed 2026-01-01 holdout (E13) |
| X-M06 DEV-056 MIN_OVERLAP pilot arm | CLOSE | folded into D18's specification curve |
| X-M07 DEV-057 flag-and-include sensitivity | DO-L | with D18 |
| X-M08 R2.3 ml purge/embargo | FIX | N10 depends on it (ML gate on PIT pools) |
| X-M09 S11/S12 trial registry counts | FIX | count all trial sources, de-duplicate reruns, keep IS and holdout separate |
| X-M10 14 reviewer findings not re-read | DO-Q | re-read each when its claim is registered (T10 rule) |
| X-M11 R5.3, X-M12 R6.5, X-M13 R8.1, X-M14 R4.11/R5.10 | FIX | mechanical fixes; R8.1 claim withdrawn until re-run |
| X-M15 SWEEP-C4-2 route research EG through eg_pvalue_pair | FIX | one production test everywhere |
| X-M16 R1.6 one-window confirmations | DISCLOSE | + report the share resting on one window in the registry |
| X-M17 252-bar window power | DO-L | with N14's power code |
| X-M18 A12/A13 eigenportfolio label, X-M19 S8, X-M20 M10-M12 macro lags | DISCLOSE | dormant / label-only; mark dormant in code |
| X-M21 JOHANSEN_DET_ORDER = -1 | FIX | price-level series need a constant: det_order 0, as arm (a)'s comparison; re-run arm (a) |
| X-M22 291 unjustified values | DO-L | with D18 (specification curves for the outcome-informed ones first) |
| X-M23 DEV-026 sensitivity leftovers | CLOSE | except values a cited result depends on (they go to D18) |
| DEV-009, DEV-010, DEV-011, DEV-012 | CLOSE | old arms (cut in the claims evaluation); reopen only if re-cited |
| DEV-006 ML on full correlation-screened universe | CLOSE | superseded by the PIT-pool ML gate (N10) |
| DEV-007 ml_lookahead_selftest on real data | DO-Q | with N10 |
| DEV-004 contamination-scan peer corroboration | CLOSE | superseded by BUG-D117's content-verified map |
| DEV-064, DEV-065, DEV-067 | CLOSE | DEV-065 subsumed by N4/N8; the others old-arm ideas |
| S24 deep dives / S25a-d | DO-L | after the redraft; S25d (factor-level cointegration, your idea) needs a design session with you |
| S27 rows DEV-027, 029, 031, 032, 034, 036, 037, 038, 039, 040, 041, 043, 045, 046, 047, 048, 053 | CLOSE | reasons as recorded in POA S27; none feeds a current claim |
| X-M24 Thread R purged-CV utility | CLOSE | purge/embargo fix lands in ml.py (X-M08) |
| X-M25 PAPER §10 leftovers, X-M26 FINDINGS follow-ups, X-M27 "not built" ideas, X-M28 superseded-by-audit set | CLOSE | rewrite §10 at the redraft from what remains open here |

## Data
| ID | Decision | Note |
|---|---|---|
| C1 full TAQ, C2 full OptionMetrics, C3 Capital IQ events | ROSS | send the librarian email (I redraft it); C1/C2 unlock E16/E17 and the options/TAQ notes items |
| C4, C5, C6 | CLOSE | low value for the thesis |
| E16, E17, X-D01 | DO-L | only if C1/C2 granted |
| X-D02 synthetic fill of sample gaps | CLOSE | you approved it as a labelled curiosity; it cannot support a finding, so no time on it now |
| S13 PAR_1M refetch | DO-L | at the next Duo session (job queued) |
| A1 ciq_link copy, A4 graphify-out | DO-Q | check, mechanical |
| A3 | CLOSE | CachyOS cache is canonical |
| X-D03 DEV-003 leftovers, X-D04 coarse Compustat files + Surface re-sync | FIX | coarse files re-derived from repaired daily files (N13 depends on it) |
| X-D05 stale KVUE/KMB, PNC/ZION spreads | CLOSE | old arms, IBKR off |
| X-D06 BUG-D38 yfinance fallback recurrence | FIX | guard + test |
| X-D07 Binance.US wiring | CLOSE | crypto stays a labelled side universe |
| X-D08 WRDS-vs-yfinance writeup | DO-L | one paragraph at the redraft (which old pairs fail under WRDS pricing) |
| DEV-042 other WRDS tiers | CLOSE | E3 covers TRACE; others not needed |
| S26/DEV-033 CBOE SKEW, put/call, Trends | CLOSE | reopen only when a deep dive needs them |
| DEV-058 | merged into S11 | |

## Code / engineering
| ID | Decision | Note |
|---|---|---|
| N15 aligned_pair_loader yfinance-first | FIX | rule 2; 50 importers |
| N18 CONTRIB-032 | FIX | at the docstring |
| W5.6b ADV in local currency (analysis._compute_adv, sensitivity.py:124) | FIX | use usd_dollar_volume |
| W6.3 tz to ET in data._standardize | DISCLOSE | intraday pool is US-only; fix if an international intraday claim appears |
| W6.4 silent handlers | FIX | make loud |
| DEV-015 BUG-D73 IBKR refresh test | CLOSE | IBKR off by default |
| DEV-016 mem_guard re-test | DO-L | next deliberate breach test on CachyOS |
| DEV-017 NTFS fstab, DEV-019 Windows admin | ROSS | machine admin |
| DEV-018 memtest | CLOSE | your "no" (2026-10-12) |
| DEV-020, DEV-021, DEV-022, DEV-024, DEV-025 | CLOSE except DEV-022 FIX (delete the unused .ps1 runner) and DEV-025 FIX (two config annotations) | |
| X-C01 --fresh glob fix on CachyOS | DO-Q | pull now that the chain is done |
| X-C02 BUG-A6 test, BUG-D90 pooled-trade Sharpe, BUG-D15/D44 partial | FIX | |
| X-C03 weekend exits on Friday | DISCLOSE | Sharpe unaffected |
| X-C04 unenforced DAILY_LOSS_LIMIT / CONSECUTIVE_LOSS_LIMIT | FIX | remove the dead config (a stated limit that is not enforced misleads) |
| X-C05 portfolio_sim sizing docstring | FIX | make docstring match code |
| X-C06 analysis.py deferred notes | CLOSE | except "RegimeClassifier labels not persisted" -> DO-L with N4 if regime labels are cited |
| X-C07, X-C08, X-C09, X-C11, X-C12, X-C13, X-C16 | CLOSE | |
| X-C10 distribution_fits P&L fits | DO-L | now unblocked by dollar P&L; small |
| X-C14 stale "ML gate DEFERRED" strings in report.py / reproduce.py | FIX | |
| X-C15 full-universe prefilter queue | CLOSE | superseded by the chain |
| X-C17 flaky tests | FIX | find the nondeterminism |
| X-C18 strict-default changes unlabelled outputs | DISCLOSE | label when cited |

## Papers / claims
| ID | Decision |
|---|---|
| N17, X-P01, S19, X-P16, X-P17, X-P18 | DO-Q (registry + disclosure with each claim) |
| X-P02 13 unverified citations | DO-L with E19 at the redraft; not cited until read |
| S23 redraft, X-P03 literature comparison section, X-P04 buy-and-hold benchmark, X-P05 sizing heat map, X-P08 reconcile to the PIT pivot, X-P10, X-P11, X-P13, X-P14, X-P15 | DO-L at the redraft (after the registry) |
| F1 lead paper, F2/S21 process paper, S22 council | DO-L (process paper can start now: E2 needs no compute) |
| X-P06 market-structure field | ROSS |
| X-P07 PAPER_PENDING_CHANGES 1-9 | CLOSE: retire the file into the redraft (each still-valid point re-checked then) |
| X-P09 target programs' AI-disclosure format | ROSS (or I look it up: Baruch, Berkeley, Columbia) |
| X-P12 graphical abstract, arXiv passes | CLOSE |

## Process / tools
| ID | Decision |
|---|---|
| B1 memtest, B4 Bloomberg | CLOSE (your no) |
| B2 Windows admin | ROSS |
| B3 Kamiak | ROSS (via your instructor) |
| X-T01 librarian email | ROSS (= C1-C3) |
| X-T02 E2, X-T04 failures/attribution | DO-L now-able (no compute), with the process paper |
| E21 trial ledger + one-command reproduction + CI | FIX: add a GitHub Actions workflow running the fast synthetic verify subset; dashboard after claims settle; red team after the redraft |
| X-T03 intake triage | waits for a first external report |
| X-T05 GitHub cached-data removal request | ROSS |
| X-T06 About text, X-T07 model choice | ROSS |
| S29/DEV-062 Singha + HLPPL | ROSS (citations or drop) |
| DEV-049, DEV-068 | CLOSE / DO-L (use the synthetic checkers in new scripts from now on) |
| S30, S27 umbrella, X-T08 | as above (parked by rule / closed / disclosed) |

## Off-thesis
E15, E20, X-O01, X-O02, DEV-061: **CLOSE**. E14: **CLOSE** (revive only if a pass finds a robust signal). X-O03 (the
notes skips): closed with reasons as in NOTES_TRIAGE_2026-10-20.md.
