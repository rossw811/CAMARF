# Errata and known limitations — one index

Last updated 2026-10-03. This page is the entry point for anyone checking this project's results. It does not repeat
the details; it says what is wrong, fixed, withdrawn or still open, and links to where the evidence lives.
**Found a hole?** Open an issue with `.github/ISSUE_TEMPLATE/find_a_hole.md`. Every report is verified, then fixed or
disclosed, and the outcome is logged here and on the affected claim.

## 1. What you can cite

Only claims marked **REPLICATED** in [`docs/CLAIMS_REGISTRY.md`](CLAIMS_REGISTRY.md). As of 2026-10-03:

| Claim | Status |
|---|---|
| C-001 full-sample cointegration can be stale (NTRS/STT) | CORRECTED → **REPLICATED** (sample size corrected to 10,098 days from 1985-12-03; p-values unchanged) |
| C-002 calendar-padding artifact in rolling z-scores | REGISTERED (not yet re-derived) |
| C-003 purged ML predicts z-convergence, not profitability | PENDING-DATA |
| C-004 the engine executes its rules; the rules are defective | PENDING-DATA |
| C-005 entry clustering | PENDING-DATA |
| C-006 pre-registered strategy search: no robust signal (first pass) | REGISTERED for the first pass; second pass pending rebuilt data |

**Every P&L-derived number published before 2026-10-03** (Sharpe, DSR, capital-sim, luck check, quality admission)
is withdrawn pending re-derivation — see §2 (B2/B3/B4). PAPER.md / PAPER_MAGNITUDE.md are being redrafted to cite
only REPLICATED claims ([`docs/PAPER_SCRUTINY_2026-09-27.md`](PAPER_SCRUTINY_2026-09-27.md): claim-by-claim verdicts).

## 2. Defects that changed results (fixed)

| ID | What was wrong | Status / evidence |
|---|---|---|
| B2/B3 | Backtest P&L in spread units with a hedge ratio re-estimated every bar (the drift was ALL positive gross P&L on 2,062 real trades), costs in dollars | Dollar P&L is the default everywhere since 2026-10-03; legacy only via `--legacy-pnl`, labelled known-wrong. On 143 real 1-day trades: +274.7 spread units vs −$1,809; 34% flip sign |
| B4 | `--hedge both` emitted near-duplicate OLS + Kalman trades treated as independent | Removed; OLS default, Kalman its own arm |
| D13–D19 | Data identity: ticker reuse assigned to the oldest holder (2,719 of 4,327 reused CRSP tickers), label collisions, local-currency Compustat legs, price-only series | Fixed; discovery re-running on corrected data (2026-10-03) |
| A6/S10 | Crashed or never-computed rolling cointegration tests passed the stability filter | Fixed 2026-09-28 |
| B5, B6, B7, B10, B13, B14, B15 | P&L-cap state carried across runs; overrides not reaching the in-sample fitting engine (and leaking into the global config); unflagged lookahead sizers; liquidity filter blocking every WRDS symbol (11 vs 75 of 143 trades); intraday regime lookahead; hub weights from the wrong pair set; survivorship end date | Fixed 2026-10-03, each with a failing-first test — [`docs/CODE_REVIEW_2026-09-26.md`](CODE_REVIEW_2026-09-26.md) |
| Tests touching real data | A test deleted real discovery outputs; three wrote fake symbols into real caches | Sandboxed 2026-10-03 |

Full registries: [`docs/CODE_REVIEW_2026-09-26.md`](CODE_REVIEW_2026-09-26.md) (175-row ledger, statuses with evidence),
[`docs/INCONSISTENCY_SWEEP_2026-09-27.md`](INCONSISTENCY_SWEEP_2026-09-27.md), [`Development.md`](../Development.md)
(126 BUG ids; index [`docs/BUG_LOG.md`](BUG_LOG.md)), [`docs/bug_recheck/inventory.csv`](bug_recheck/inventory.csv)
(every logged bug, its tests, its recheck status).

## 3. Open — known, not yet fixed

| ID | Issue | Effect |
|---|---|---|
| A2 / A3 | Where a rolling hedge ratio has no value, the spread uses the full-sample ratio (lookahead); hedge ratios are fitted on prices forward-filled through data outages | Causal comparison arm built (`Config.ANALYSIS.HEDGE_FALLBACK = "causal_expanding"`); default unchanged until the comparison on rebuilt pools |
| DEV-003 | CRSP volume was stored in pre-split share units against a split-adjusted price (19% of the discovery ADV gate's passes were reverse-split names; 1,103 split stocks wrongly excluded on some days) | FIXED 2026-10-03: cache restated (33,016 files; raw kept as `volume_raw`), fetches adjust at source; discovery stopped and re-run. Open: 67 files with no PERMNO mapping (ETFs, ADRs, a few REITs, FX) keep raw volume; coarser 7D/1M/3M/6M/1Y files not restated |
| B8 | Holdout = last 20% of each pair's own bars, not a common calendar date (cross-pair leakage into fitted weights) | Needs a decision on the holdout definition |
| B9 | Same-bar fill | Sensitivity study must be re-run on dollar P&L |
| A4 | Rolling z-score window derived from the full-sample half-life | Open |
| Unilever | UL ADR vs its London PLC line drifts 5–11% by year | Investigated, open (INCONSISTENCY_SWEEP) |
| Flaky tests | `_verify_pit_wfa`, `_verify_pit_wfa_wrds_daily_merge_and_save` failed once in full runs, pass alone | Suite now saves failing output to diagnose |

## 4. Standing limitations (disclosed, by design or by data access)

- **Survivorship in index-based universes:** our WRDS subscription has no S&P 400/600 point-in-time constituents. A free
  source (SEC filings of index ETFs + S&P announcements) is verified on 78 announced changes (76 agree, 2 explained) —
  [`docs/PIT_INDEX_MEMBERSHIP_SOURCES.md`](PIT_INDEX_MEMBERSHIP_SOURCES.md); not yet used as a universe filter.
- **Futures roll adjustment:** not done — no free contract history deep enough.
- **Intraday:** depth starts 2023-07; dollar P&L marks intraday trades at split-adjusted (not dividend-adjusted) prices.
- **Data licences:** CRSP / Compustat cannot be redistributed; code, queries and derived statistics are public.
- **AI assistance:** much of the code was written with an AI assistant; attribution in the git history is incomplete
  (many commits carry no model trailer). Failures it introduced or caught are being catalogued for the process paper
  ([`docs/PAPER_PROCESS_OUTLINE.md`](PAPER_PROCESS_OUTLINE.md)).
