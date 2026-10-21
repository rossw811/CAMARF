# CAMARF master plan: every open item in one place (2026-10-20)

Consolidates: docs/PLAN_OF_ACTION_2026-10-07.md (S1-S36), docs/decisions/DECISIONS_2026-10-12.md (A/B/C/D/E/F
items), docs/drafts/CLAIMS_EVALUATION_2026-10-19.md, docs/drafts/NOTES_TRIAGE_2026-10-20.md, docs/HANDOFF.md
(current entries). Status: **DONE** · **NOW** (Claude, no input needed, in this order) · **ROSS** (needs your
decision) · **DATA** (needs data we do not have) · **LATER** (after a stated dependency) · **PARKED** / **DROPPED**
(with reason). Where an item is DONE the evidence is in Development.md under its ID.

## 0. Where things stand
- Re-run chain finished on CachyOS 2026-10-20 10:07 on the fixed code (PIT pools, PIT spread fix, strict engine);
  suite gate 403 tests, 0 unexplained failures.
- Pre-registered strategy search (Amendment 4): **no selection passes** (DSR 0.00-0.42, PBO 0.21-0.85, holdout
  capsim Sharpe -0.60..+0.42). "No robust signal" holds on the fixed pools.
- Papers: 60 claims-evaluation edits applied and reviewed (0ec68ff6). 150 central claims wait on re-derivation.

## 1. NOW: re-derivation on the new chain (Claude, in order, on CachyOS)
| # | Item | Done when |
|---|---|---|
| N1 | Register C-006 with the Amendment-4 search numbers (pools, N = 1,728 trials, DSR, PBO) | CLAIMS_REGISTRY entry + paper wording drafted |
| N2 | Pool sizes, PIT vs full-history discovery counts (README-001/047, PM-004, PM-051..053) | numbers re-derived from the new pool files |
| N3 | Degenerate-column audit + pipeline contracts outputs read (run by the chain) | any non-clean column explained or fixed |
| N4 | Arm (a) on the new pools; regime scripts (D3 table), then D12 within-year CI real run | outputs + review |
| N5 | D10 real run (stationary block bootstrap; ~1.5 h of 1h re-screens) | output + review |
| N6 | Arm (b) on Tier-3 windows (D8 calm reference) | output + review |
| N7 | D5 survivorship rows (paper_magnitude test's 5 failing rows) on the new discovery output | test passes or claim corrected |
| N8 | D6 redesign: per window date, discovery's post-filter set vs CRSP stocks with a trade price but no usable series; CIZ outcomes; D18-include arm alongside; planted-effect test on the primary path | output + review |
| N9 | Stress test (PAPER-169/170) under Andrews-Kim on the new pools | output + review |
| N10 | ML gate on the PIT pools (PAPER-161..163) | output + review |
| N11 | Large-n persistence, multivariate PIT results (FINDINGS-098/099/140) | output + review |
| N12 | BUG-D115 effect on existing runs (crashed tests dropped from BH's m) | measured |
| N13 | Coarse timeframes 1M/3M check after the loader weekend fix | outputs checked |
| N14 | Correlation-matched D11 null (size on |corr| >= 0.6 candidates) + power | output + review |
| N15 | `aligned_pair_loader` loads yfinance first (rule 2 violation) | failing test -> fix |
| N16 | D11 check: assert the one-direction random-walk rate (review finding) | test updated |
| N17 | Register every re-derived number (S20) before any paper redraft; council (S22) at that milestone | registry complete |
| N18 | CONTRIB-032 fixed at its source docstring on the next CONTRIBUTING regeneration | regenerated |

## 2. Decision items D1-D18 (2026-10-12/18/19)
| ID | Item | Status |
|---|---|---|
| D1-D4 | Drop top-2 binomial; episode-level permutation; episode-level crisis-vs-calm test; placebo dates for the gap rule | DONE (code); real numbers in N4 |
| D5 | Survivorship test filtered to crisis-first pairs | DONE (code); N7 |
| D6 | Survivorship: included vs excluded universes | first cut WITHDRAWN on review (D18 rule, not survivorship); N8 |
| D7-D9 | Andrews-Kim P-test + baseline precondition; calm-control rule (same month, then day-of-month); formal two-proportion test | DONE (code); N9 |
| D10 | Stationary block bootstrap of daily P&L | DONE (code); N5 |
| D11 | Calendar-aligned full-universe nulls | DONE (C-008); N14 extends it |
| D12 | Within-year crisis-vs-calm, sign-flip CI | DONE (code); N4 |
| D13 | MC power of the 5-year test | DONE (in papers) |
| D14 | Dual-listed twins out of pools, kept as positive controls | check in N2 that the new pools exclude them |
| D15 | 85 unresolved CRSP labels out of gate-dependent tiers | check in N2 / N8 (review found discovery still loads them) |
| D16 | Total return for signals and P&L in pit_wfa_wrds_daily | LATER: A7 re-runs |
| D17 | FANG/OXY worked example re-check vs the 756-bar rule | NOW (small; before the redraft) |
| D18 | Specification-curve ranges per outcome-informed value | ROSS: I propose ranges with the registry work, you approve |

## 3. Plan of action S1-S36 (decided 2026-10-10, all as recommended)
- DONE: S1, S2/S3 (k = 2, N = 432 for the second pass; 1,728 trials counted in Amendment 4), S4/S5 (A2/A3/A4 fixed
  89ececc4), S8, S14, S15, S20 partially (claims evaluation), S28 (dropped), S34 (triage), S35 (no-trade mask in
  traded series; D13 found and fixed one script that skipped it).
- NOW / LATER: S6 common holdout date (report the count of pairs with no holdout), S7 next-bar fill sensitivity on
  dollar P&L, S9/S10 intraday liquidity gate + grid phase, S11 PIT S&P 400/600 membership verification, S12
  survivorship universe from the CRSP point-in-time master (overlaps N8), S18 Act 3 claims re-derived, S19 C-003..C-006
  (N1), S21 process paper draft, S22 council, S23 papers redraft after S18-S20, S31 international pairs and the S&P
  gate, S32 PIT FDR family for pool eligibility, S33 mis-sized tier tests (PO proxy) -- fix or withdraw the tiers,
  S36 share-class pairs by PERMCO.
- ROSS: S13 PAR_1M refetch (Duo session), S29 Singha paper (locate or drop).
- DROPPED/CLOSED with reason: S14 IBKR at scale, S15 universe expansion (done by WRDS), S16 futures roll (no free
  contract history), S17 Unilever drift (disclosed), S28 GPU EG.
- PARKED by rule: S24/S25 T7 deep dives (approved order 1 -> 2 -> 4), S26 CBOE SKEW / put-call / Google Trends (only
  when a deep dive needs them), S27 deferred DEV items, S30 paper trading only if a pass finds a robust signal (it did
  not).

## 4. Operations and data (A, B, C)
| ID | Item | Status |
|---|---|---|
| A1 | Re-copy ciq_link_cusip to CachyOS | check; NOW if still truncated |
| A3 | Volume re-restatement on the Surface cache | PARKED (CachyOS is canonical) |
| A4 | Remove graphify-out from the tree | check |
| A5 | Grid-offset re-runs 63/126/189 on corrected code | LATER: robustness check after N2 |
| A6 | Third labelled pass with A2/A4/B8/B9 | this re-run chain is that pass; record it as such |
| A7 | Dollar-P&L re-runs (pit_wfa, wrds_daily, distance, sensitivity) | LATER, with D16 |
| B1 | CachyOS memtest86+ | CLOSED: Ross said no (2026-10-12, DECISIONS round 2) |
| B2 | Windows admin fix | ROSS, when convenient |
| B3 | Kamiak HPC sponsor request | ROSS: maybe, via the linear-algebra instructor (2026-10-12) |
| B4 | Bloomberg spot-check protocol | CLOSED: Ross said no (2026-10-12) |
| C1-C6 | Full TAQ, full OptionMetrics, Capital IQ events, CIQ Pro, FactSet/MSCI/ISS, PitchBook | DATA: confirmed 2026-10-20 (job 34) only samples readable; ask the library |

## 5. Explorations E1-E21 (approved list, 2026-10-12)
| ID | Item | Status |
|---|---|---|
| E1 | End-to-end placebo discovery + power curves + grid null | LATER, after N1-N14 (reference point for every discovery claim; Kamiak ideal) |
| E2 | Verification-layer yield -> process paper | NOW-able (no compute) with S21 |
| E3 | Bond/credit cross-asset (TRACE) | proposal written; ROSS approval of the design |
| E4 | Pair-break causes: earnings dates, M&A, restatements | LATER (after break set settles) |
| E5 | Fundamental divergence -> break prediction | LATER |
| E6 | Economic linkage: 13F owners, board interlocks, lenders, supply chain (placebo pairs, endogeneity rules) | LATER |
| E7 | Survival analysis + transition matrix of pairs | LATER |
| E8 | Factor-neutral spreads (FF5 + liquidity) | LATER |
| E9 | Regime robustness, half-life bias (errors-in-variables) | folds into N4 |
| E10/E11 | TimesFM vs own forecaster vs AR/OU (post-cutoff data only) | LATER, small |
| E12 | Break-even cost frontier, capacity, SEC 605 execution | LATER |
| E13 | Sealed holdout 2024-07 -> | DONE (declared) |
| E14 | Forward paper-trading record | DROPPED for now (no robust signal) |
| E15 | Private markets | PARKED (exploratory) |
| E16/E17 | Option-implied stress; intraday microstructure of breaks | DATA (C2 / C1) |
| E18 | International regimes; ADR-home controls | LATER |
| E19 | Literature pass with EconLit (citation refresh) | with the redraft; 13 citations still unread in the original |
| E20 | Off-thesis explorations | PARKED |
| E21 | Trial ledger, one-command reproduction + CI, claims dashboard, external red team | ledger + CI NOW-able; dashboard after claims settle; red team after redraft |

## 6. Papers and claims (F1-F3 + claims evaluation)
- F1 lead paper = a calibrated discovery paper (FDR and power of the screen measured, E1). F2 process paper (S21,
  E2). F3 withdrawn peripheral claims stay withdrawn.
- 150 PENDING_CHAIN claims -> N1-N17. 69 QUALIFY items: refresh at the redraft. 13 citations to read in the original.
- Redraft rules (from your notes): impersonal academic style (no "Ross", no "Option A", no first/second person;
  PAPER.md has 13 "Ross"); a section comparing each finding with the literature; buy-and-hold S&P 500 benchmark with
  alpha/beta in report.py; one sizing-method heat map.

## 7. From your notes (triage 2026-10-20) -- open, after section 1
- Do after the chain: literature-comparison section; impersonal style; buy-and-hold benchmark; sizing heat map;
  jump-model regimes vs HMM (ROSS: yes/no); Hawkes clustered null; TimesFM (E10).
- Skipped with reasons (triage file): Heikin-Ashi, synthetic MC bars, apply-every-concept-to-every-metric,
  prime brokerage, real-time standing, autoresearch, graph workflows, textbook MC/frontier, the tooling repos,
  Donchian features before the ML gate shows signal.
- Blocked on data: options surface / OI / dealer gamma / vanna-charm / TAQ intraday (C1/C2).

## 8. Questions batch (your answers unblock these)
1. HLPPL model and "Singha" paper: citations? (else drop, S29)
2. Jump-model regimes as a comparison arm against the HMM labels?
3. Claims registry gets a "market-structure reading" field per claim (instead of a paragraph per claim)?
4. GitHub About text (in the triage file): set it?
5. Keep Opus for this project, searches on Sonnet?
6. TAQ: does your WRDS account page show a full TAQ entitlement (only samples read)?
7. D18 specification-curve ranges: OK for me to propose them with the registry work?
8. E3 bond/credit design: approve the written proposal?
9. (withdrawn: memtest was already a no on 2026-10-12)

Every deferred/later item (241 rows) now has a decision: docs/DEFERRED_DECISIONS_2026-10-20.md.
