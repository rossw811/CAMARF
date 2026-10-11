# Errata and known limitations — one index

Last updated 2026-10-05. This page is the entry point for anyone checking this project's results. It does not repeat
the details; it says what is wrong, fixed, withdrawn or still open, and links to where the evidence lives.
**Found a hole?** Open an issue with `.github/ISSUE_TEMPLATE/find_a_hole.md`. Every report is verified, then fixed or
disclosed, and the outcome is logged here and on the affected claim.

## 1. What you can cite

Only claims marked **REPLICATED** in [`docs/CLAIMS_REGISTRY.md`](CLAIMS_REGISTRY.md). As of 2026-10-03:

| Claim | Status |
|---|---|
| C-001 full-sample cointegration can be stale (NTRS/STT) | CORRECTED → **REPLICATED** (sample size corrected to 10,098 days from 1985-12-03; p-values unchanged) |
| C-002 calendar-padding artifact in rolling z-scores | analytic bound **REPLICATED** 2026-10-05 (= Samuelson's inequality, attained by padding); empirical "4 of 32" part REGISTERED |
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
| B2/B3 | Backtest P&L in spread units with a hedge ratio re-estimated every bar (the drift was ALL positive gross P&L on 2,062 real trades), costs in dollars | Dollar P&L is the default everywhere since 2026-10-03; legacy only via `--legacy-pnl`, labelled known-wrong. On 143 real 1-day trades: +274.7 spread units vs −$1,809; 34% flip sign **Correction 2026-10-07:** 'everywhere' was not true -- 12 callers of BacktestEngine.run (pit_wfa.py, distance.py, sensitivity.py, run_storm_grid.py and 8 research scripts) never applied the dollar basis and kept reporting spread-unit P&L; the engine now converts every trade itself (`_verify_engine_dollar_default.py`), so their earlier outputs are spread-unit results until re-run |
| B4 | `--hedge both` emitted near-duplicate OLS + Kalman trades treated as independent | Removed; OLS default, Kalman its own arm |
| D13–D19 | Data identity: ticker reuse assigned to the oldest holder (2,719 of 4,327 reused CRSP tickers), label collisions, local-currency Compustat legs, price-only series | Fixed; discovery re-running on corrected data (2026-10-03) |
| A6/S10 | Crashed or never-computed rolling cointegration tests passed the stability filter | Fixed 2026-09-28 |
| B5, B6, B7, B10, B13, B14, B15 | P&L-cap state carried across runs; overrides not reaching the in-sample fitting engine (and leaking into the global config); unflagged lookahead sizers; liquidity filter blocking every WRDS symbol (11 vs 75 of 143 trades); intraday regime lookahead; hub weights from the wrong pair set; survivorship end date | Fixed 2026-10-03, each with a failing-first test — [`docs/CODE_REVIEW_2026-09-26.md`](CODE_REVIEW_2026-09-26.md) |
| R1.2 (2026-10-07) | The 1D discovery scan's liquidity gate multiplied Compustat Global's LOCAL-currency close by volume against a USD threshold (yen listings ~159x too liquid): it passed 45.0% of international symbol-days at $25M instead of 9.0% (listings ever passing 5,734 vs 1,458). Every 1D discovery run before 2026-10-07 had the gate effectively off for international listings | Fixed (`dollar_volume.py`, `_verify_usd_dollar_volume.py`); discovery re-run started 2026-10-07 |
| DEV-003 follow-ups (2026-10-07) | Coarse (7D-1Y) WRDS volume was raw shares; `period_bars` summed missing volume to 0; PAR's coarse files were another security | Fixed (`rederive_coarse_volume.py`, `_verify_period_bars_volume_nan.py`, `repair_coarse_identity.py`); PAR_1M needs a refetch |
| S5 (2026-10-07) | The "White Reality Check" (`stats.run_permutation_test`) bootstrapped undemeaned P&L, so p ~ 0.5 whatever the skill; PAPER.md's IS p=0.559 / OOS p=0.546 are that artifact | Fixed (`_verify_reality_check_null.py`); the cited p-values are withdrawn pending re-derivation |
| S9 / S13 (2026-10-07) | `stats` Phase 2/3 Sharpes: exit-days-only daily series (synthetic: 44.6 vs 4.93) and per-trade P&L annualized by sqrt(252) | Fixed (`_verify_stats_daily_pnl_calendar.py`, `_verify_stats_trade_bootstrap_scale.py`) |
| A5 / A7 / A8 (2026-10-07) | The coint-fraction "secondary evidence" override trusted break tests with too little real data (n_bars counted NaN bars), a sup-F test with 0.7% real size, and a CUSUM band with 20-34% false alarms | Fixed (`_verify_secondary_evidence_overlap.py`, `_verify_break_tests_size.py`); production pairs change on the next analysis.py run |
| A10 + rule 2 (2026-10-07) | analysis.py replaced production spreads with IBKR-extended series by default (KVUE/KMB@3min, PNC/ZION@4hr) and misaligned shared legs | Fixed: off by default (`Config.ANALYSIS.IBKR_DEEP_HISTORY_ENRICH`), per-pair keys (`_verify_deep_history_enrich.py`) |
| S4 / S14 (2026-10-07) | pit_wfa's out-of-sample test used train+test hedge ratios to skip/fallback, and the boundary bar was in both train and test | Fixed (`_verify_pit_pair_row.py`, `_verify_pit_wfa_train_test_boundary.py`); pit_wfa numbers change on re-run |
| A11, U6, R1.7, R1.9 (2026-10-07) | Johansen trios stitched across outages and ignored the configured level; loader memos survived code changes; scan checkpoints cleared before saves; intraday configs reused each other's outputs | Fixed, each with a failing-first test (docs/bug_recheck/manual_verdicts.csv) |
| Tests touching real data | A test deleted real discovery outputs; three wrote fake symbols into real caches | Sandboxed 2026-10-03 |

Full registries: [`docs/CODE_REVIEW_2026-09-26.md`](CODE_REVIEW_2026-09-26.md) (175-row ledger, statuses with evidence),
[`docs/INCONSISTENCY_SWEEP_2026-09-27.md`](INCONSISTENCY_SWEEP_2026-09-27.md), [`Development.md`](../Development.md)
(126 BUG ids; index [`docs/BUG_LOG.md`](BUG_LOG.md)), [`docs/bug_recheck/inventory.csv`](bug_recheck/inventory.csv)
(every logged bug, its tests, its recheck status).

## 3. Open — known, not yet fixed

| ID | Issue | Effect |
|---|---|---|
| A2 / A3 | Where a rolling hedge ratio has no value, the spread uses the full-sample ratio (lookahead); hedge ratios are fitted on prices forward-filled through data outages | Causal comparison arm built (`Config.ANALYSIS.HEDGE_FALLBACK = "causal_expanding"`); default unchanged until the comparison on rebuilt pools |
| DEV-003 | CRSP volume was stored in pre-split share units against a split-adjusted price (19% of the discovery ADV gate's passes were reverse-split names; 1,103 split stocks wrongly excluded on some days) | FIXED 2026-10-03: cache restated (33,016 files; raw kept as `volume_raw`), fetches adjust at source; discovery stopped and re-run. Open: Compustat Global files had the same bias (found 2026-10-04 by independent review; code fixed, cache restated after the running scans -- which used raw Compustat volume); 37 ETF/ADR/REIT files get identity-verified PERMNOs (also after the scans); FX files have no volume; coarser 7D/1M/3M/6M/1Y files not restated |
| B8 | Holdout = last 20% of each pair's own bars, not a common calendar date (cross-pair leakage into fitted weights) | Needs a decision on the holdout definition |
| B9 | Same-bar fill | Sensitivity study must be re-run on dollar P&L |
| BUG-D115 (2026-10-10) | The discovery scan dropped crashed EG tests from BH's m (production keeps them at p = 1.0) | Fixed in code (`_verify_episodic_crash_in_bh_m`); effect on the existing discovery runs not yet measured -- zero crashes means no change, any crash means BH was slightly too loose |
| A4 | Rolling z-score window derived from the full-sample half-life | Open |
| Unilever | UL ADR vs its London PLC line drifts 5–11% by year | Investigated, open (INCONSISTENCY_SWEEP) |
| S6 (verified 2026-10-07) | Gold/Silver/Bronze confirmatory tiers: the "Phillips-Ouliaris proxy" rejects 27.3% of independent random walks at nominal 10% (arch's real PO: 11.2%); KPSS on residuals same class | PAPER.md's tier counts not citable until re-derived (plan S33) |
| S11 / S12 | The deflated-Sharpe trial registry counts only backtest.py runs, counts identical reruns, pools IS and holdout | Registry-based DSR claims: fix or withdraw (plan W4.3); the pre-registered search has its own DSR |
| Act 3 (2026-10-07) | PAPER.md's Act 3 numbers match the Surface's 2026-08-14 backtest files; CachyOS's 2026-09-21 rerun differs (IS -1.468 vs -0.679) and both predate dollar P&L | Re-derive or withdraw (plan S18) |
| Research scripts (bug recheck) | 81 open review findings sit in scripts the papers name (17 confirmed by code, 64 reviewer claims not yet checked); 8 more in scripts no paper names (disclosed, unresolved) | Plan S34: fix the central claims, withdraw the rest |
| Dormant | Macro release lags/vintages (M10-M12), eigenportfolio gold/silver label (A12/A13), half-life stationarity test (S8) | Not used by any reported result; disclosed |
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
