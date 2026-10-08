# Goal plan — everything to completion, with a sign-off sheet (2026-10-07)

Ross (2026-10-07): "make a /goal plan for everything including the whole backlog and every concept and idea for me to
sign off on". Supersedes docs/PLAN_OF_ACTION_2026-10-03.md (kept for history). Sources: that plan (T1–T14), the DEV
ledger (docs/DEV_OPEN_ITEMS_LEDGER_2026-09-26.md: 56 OPEN + 13 NEEDS-ROSS), the claims registry (C-001..C-006), the
bug-recheck inventory (docs/bug_recheck/inventory.csv: 310 logged bugs), docs/ERRATA.md, and today's findings.

Rules for every step: free data only; verification loop (failing test first → real-data check → independent check
for anything paper-bound → evidence with the claim); new methodology enters as a labelled comparison arm; lineage
for every chain stage; every cited number registered first; never delete data; RAM-heavy work on CachyOS; one agent
at a time. Owners: **C** Claude · **R** Ross · **J** unattended job (CachyOS).

## The goal (paste into /goal)

> Every thread in docs/PLAN_OF_ACTION_2026-10-07.md reaches its "done when" or is closed with a recorded reason; every
> sign-off item S1–S30 has Ross's decision recorded in this file; the second pre-registered strategy-search pass is
> run and reported beside the first; every claim cited in PAPER.md / PAPER_MAGNITUDE.md is REPLICATED, CORRECTED or
> WITHDRAWN in docs/CLAIMS_REGISTRY.md; every logged bug has a recheck verdict with evidence; the full verify suite
> passes (or each failure is explained); and Development.md / HANDOFF / README / ERRATA match the final state.

---

## Part A — Sign-off sheet

Mark each: ✅ approve as recommended · ✏️ change (say how) · ✖ drop. Items already decided are listed at the end for
completeness, not for re-decision.

### A1. Before the second pre-registered pass (blocking)
| # | Decision | Recommendation | Why |
|---|---|---|---|
| S1 | Commit the **Amendment 2 addendum** (drafted, uncommitted, in docs/PREREGISTRATION_STRATEGY_SEARCH_2026-09-27.md) | ✅ commit as drafted | Fixes the second pass's terms before any result exists |
| S2 | **Multiple-testing count** with the grid-robust arms: success judged at N = 864 (4 pool arms × 216) | ✅ N = 864 for all arms; primary also shown at the declared 432, labelled | Counting every trial run; judging at 432 after adding arms would understate it |
| S3 | **Grid-robust pools** stay a comparison arm until the robustness report; then you decide whether they replace the offset-0 pools downstream | ✅ | Pre-declared metric; no switch after seeing results |
| S4 | **A2/A3 hedge fallback** (full-sample ratio where the rolling one is missing = lookahead): adopt the causal expanding-OLS arm as the default once its comparison run shows it works mechanically (spreads build, no degenerate columns), *whatever its Sharpe* | ✅ | A lookahead fix is a correctness choice; choosing it by performance would be selection |
| S5 | **A4** rolling z-score window derived from the full-sample half-life: build a causal (expanding) half-life arm, same adoption rule as S4 | ✅ | Same lookahead class as A2 |
| S6 | **B8** common holdout date: adopt (already decided "arm first, then adopt"); accept that pairs whose data end before the cutoff have no holdout (1D, cutoff 2023-12-26: 19 of 26 pairs) and report that count | ✅ | One cutoff removes cross-pair leakage; the lost pairs are reported, not hidden |
| S7 | **B9** same-bar fills: re-run the fill sensitivity on dollar P&L; make next-bar fill the default if it changes any reported number | ✅ | Conservative execution assumption |
| S8 | Do A2/A4/B8/B9 changes enter **this** second pass, or the one after? | Run the second pass as drafted (carrying them, disclosed), then a third labelled pass with the adopted fixes | Changing them now would rewrite a pass whose terms are being fixed; a third labelled pass keeps both honest |

### A2. Discovery and data
| # | Decision | Recommendation |
|---|---|---|
| S9 | **Intraday discovery (1h/4h)**: check whether its liquidity gate reads WRDS daily volume (B10 made it WRDS-first); if so, re-run it on the restated volume | ✅ check first, re-run only if it reads it |
| S10 | **Grid-phase check for intraday windows** too, if the 1D report shows confirmations depend on grid placement | ✅ conditional |
| S11 | **PIT S&P 400/600 membership** (SEC ETF filings + S&P releases): finish verification (≥ 10 rebalances 2001–2026, matched to CRSP), then a membership-filtered universe as a comparison arm; if verification fails, disclose and stop | ✅ |
| S12 | **DEV-001/002 survivorship**: rebuild the PIT screen's universe from CRSP's point-in-time security master (incl. delisted history) as a comparison arm after the second pass | ✅ |
| S13 | **PAR_1M**: refetch CRSP monthly for PERMNO 61146 at your next WRDS (Duo) session | ✅ needs your Duo approval |
| S14 | **DEV-059 IBKR deep history at scale** | ✖ drop: the standing rule keeps IBKR out of discovery; side arms only on pre-declared symbols |
| S15 | **DEV-054 universe expansion** | ✖ close: the ~44,700-symbol WRDS universe is already the scope |
| S16 | **Futures roll adjustment (T1.5)** | ✖ not run (no free contract history) — disclosed |
| S17 | **Unilever ADR drift** | close as disclosed (unexplained UL vs London PLC drift stays in the errata) |

### A3. Claims and papers
| # | Decision | Recommendation |
|---|---|---|
| S18 | **Act 3 claims** (Purity IS −0.679 / OOS −0.834 / "all sizing variants negative OOS") differ by machine and predate dollar P&L: re-derive on current code; withdraw any that don't reproduce | ✅ |
| S19 | Re-derive **C-003..C-006** on the rebuilt pools (PENDING-DATA now) | ✅ |
| S20 | Register **every number cited** in PAPER.md / PAPER_MAGNITUDE.md (≈ 284 scrutiny rows, 2026-10-03 count) before redrafting | ✅ |
| S21 | **Process paper**: draft now from failures.csv + attribution (inputs done); adversarial review, then council | ✅ |
| S22 | **Council (5 lenses)** at the milestone "second pass reported + claims re-derived", not before | ✅ |
| S23 | Thesis papers redraft (T6) only after S18–S20; revised abstracts come back to you | ✅ |

### A4. Research extensions (T7 deep dives + T12 backlog)
| # | Item | Recommendation |
|---|---|---|
| S24 | **T7 deep dives** in the approved order 1 → 2 → 4 (3 alongside, 5 optional), each pre-registered | ✅ unchanged |
| S25 | **Pull into T7**: DEV-035 comomentum entries, DEV-044 "usable, not just significant", DEV-069 shared-leg hub risk, DEV-060 factor-level cointegration/lead-lag (your idea — a design session with you first) | ✅ |
| S26 | **Free data never added** (DEV-033): CBOE SKEW, CBOE put/call, Google Trends — eligible under the free rule; add only when a deep dive needs them | ✅ conditional |
| S27 | **Defer with a recorded reason** (not run): DEV-027 EGARCH feature, DEV-028 SHAP, DEV-029 vol-regime feature, DEV-030 cvd_proxy audit, DEV-031 copula signal, DEV-032 crowding, DEV-034 absorption sizing, DEV-036 Merton MLE, DEV-037 KO/PEP Kalman, DEV-038 GPC/ZION, DEV-039/040 break clustering, DEV-041 wavelet coint, DEV-042 other WRDS tiers, DEV-043 cross-TF Tier 2/3, DEV-045 ridge hedge, DEV-046 EWMA vs rolling z, DEV-047 JKP regression, DEV-048 macro-transition framing, DEV-050 CVSA example, DEV-052 arXiv passes, DEV-053 relational sweep | ✅ defer; any of them is pulled in only when a deep dive or a paper claim needs it |
| S28 | **DEV-063 GPU EG implementation** | ✖ drop: a new numerical procedure for speed only; CPU runs finish |
| S29 | **DEV-062 "Singha" hidden-order paper** | yours to locate, or ✖ drop |
| S30 | **Paper trading (T9.2)** only if a pass finds a robust signal; **TAQ-sample cost model (T9.1)** only if the sample overlaps the pools | ✅ |

### Already decided (recorded, not for re-decision)
D18 = exclude (2026-10-07) · grid-phase arm approved (2026-10-07) · dollar P&L default, `--legacy-pnl` labelled
known-wrong, OLS default with Kalman a separate arm, B1 gap exit (2026-10-03) · DEV-055 fresh holdout per evaluation
· DEV-056 keep values + pilot-values arm · DEV-057 flag-and-include + exclude-flagged sensitivity · DEV-061 dropped
(options data) · DEV-064 deferred to after the second pass · DEV-066 process paper · DEV-067 DFA/wavelet Hurst arm
after the deep dives · A2 causal arm built · daily gap breaks · intraday dollar marking built · PIT membership
"verify, then arm" · B8 common-date arm built.

---

## Part B — Workstreams (status · owner · done when)

Legend: ✅ done · ▶ running · ⏳ waiting · ❓ sign-off · ✖ not run (free-data rule)

### W1 — Discovery re-run + grid-phase robustness (critical path)
| # | Step | Owner | Status | Done when |
|---|---|---|---|---|
| 1.1 | Primary 1D scan on restated volume (`--fresh --d18 exclude`) | J | ▶ started 16:49, ~38 h | lineage `episodic_scan` recorded; counts in HANDOFF |
| 1.2 | Grid offsets 63 / 126 / 189 | J | ⏳ 1.1, ~34 h each | lineage `episodic_scan_grid{N}` |
| 1.3 | `research/grid_phase_robustness.py` report | J/C | ⏳ 1.2 | registry entry; S3 decision |
| 1.4 | Intraday gate check / re-run (S9), intraday grid check (S10) | C/J | ❓ | — |
| 1.5 | Identity-contamination note: old vs new discovery (T7.4) | C | ⏳ 1.1 | numbers from both runs |

### W2 — Pools → spreads → second pre-registered pass
| # | Step | Owner | Status | Done when |
|---|---|---|---|---|
| 2.1 | Commit the addendum (S1, S2) | C | ❓ | committed before 2.2 |
| 2.2 | Adapter `--fresh` → PIT eligibility → clean pools → spreads → squeeze, for offset-0 and grid-robust pools | C/J | ⏳ 1.1 / 1.3 | `pipeline_stages.py` all OK; `degenerate_column_audit` + `pipeline_contracts` pass |
| 2.3 | `strategy_search.py run` + `eval` (4 pool arms × 216) | J | ⏳ 2.2 | lineage `strategy_search` |
| 2.4 | Both passes side by side; adversarial review of the verdict; C-006 updated | C + agent | ⏳ 2.3 | registry updated |
| 2.5 | Third labelled pass with the adopted A2/A4/B8/B9 fixes (S4–S8) | C/J | ⏳ 2.4 + comparisons | reported beside passes 1–2 |

### W3 — Lookahead / execution comparison arms
| # | Step | Owner | Status | Done when |
|---|---|---|---|---|
| 3.1 | A2/A3 causal hedge arm vs current, on the rebuilt pools | C/J | built; ⏳ 2.2 | comparison note; S4 applied |
| 3.2 | A4 causal half-life arm | C | ❓ S5 | failing-first test, comparison |
| 3.3 | B8 common-date holdout arm vs per-pair | C/J | built; ⏳ 2.2 | S6 applied |
| 3.4 | B9 next-bar vs same-bar fills on dollar P&L | C/J | ❓ S7 | sensitivity table |
| 3.5 | PIT S&P 400/600: ≥ 10 more rebalances verified, CRSP match, membership arm | C | ▶ 1 rebalance verified (37/38) | S11 outcome |
| 3.6 | DEV-001/002 survivorship arm (CRSP security master incl. delisted) | C | ❓ S12 | comparison note |
| 3.7 | DEV-056 MIN_OVERLAP pilot-values arm; DEV-057 exclude-flagged sensitivity; DEV-055 fresh holdout | C | decided, not built | each reported |

### W4 — Claims and papers
| # | Step | Owner | Status | Done when |
|---|---|---|---|---|
| 4.1 | Act 3 re-derivation (S18) | C | ❓ | REPLICATED / CORRECTED / WITHDRAWN |
| 4.2 | C-003..C-006 re-derived on rebuilt pools (S19) | C/J | ⏳ 2.2 | statuses updated |
| 4.3 | Register every cited number (S20) | C | open | each has an entry |
| 4.4 | Process paper draft → adversarial review → council (S21, S22) | C | inputs ✅ | review findings closed or disclosed |
| 4.5 | Thesis papers redraft; abstracts to Ross (S23) | C/R | ⏳ 4.1–4.3 | only REPLICATED claims cited |
| 4.6 | T7 deep dives 1 → 2 → 4 (+3), with S25 items | C | ⏳ 2.4 | each pre-registered + registered |

### W5 — Bug recheck (T14) — runs alongside everything
| # | Step | Owner | Status | Done when |
|---|---|---|---|---|
| 5.1 | Inventory + index | C | ✅ 310 ids, index 126/126 | — |
| 5.2 | Full suite | J | ✅ 346/348 today (2 explained: manifest-lock race control; act3 machine difference → 4.1) | each failure explained |
| 5.3 | Verdict per bug (holds / regressed / obsolete / untested), live-code bugs without a test get a reproduce-first test — order: touches a headline number → live core module → research script → dead code | C | open: 0/310 verdicts; 241 have no test matched by name | no live-code bug without a test or a reason |
| 5.4 | Real-data re-derivation for headline-touching bugs | C | open | before/after recorded |
| 5.5 | Independent check of ≥ 10% of "holds" verdicts (adversarial-reviewer, one at a time) | C + agent | ⏳ 5.3 | disagreements resolved |
| 5.6 | R-series findings (21 confirmed, 80 unverified as of 2026-10-03): fix each when a claim depending on it is registered (T10 rule); C4-2 EG p-value routing | C | open | errata marks the rest "not cited — unresolved" |
| 5.7 | DEV-011 re-run the 5 yfinance-glob scripts; DEV-004/005/007/009/010/012 correctness items | C/J | open | each fixed or closed with a reason |

### W6 — Data layer leftovers
| # | Step | Owner | Status |
|---|---|---|---|
| 6.1 | Volume restated everywhere, Surface synced, period_bars NaN fix, PAR repair | C | ✅ 2026-10-07 |
| 6.2 | PAR_1M refetch (S13) | C+R | ❓ Duo |
| 6.3 | D11 timezone redesign (exposure nil while the intraday pool is US-only) | C | open |
| 6.4 | T1.8 remaining silent handlers (`_apply_research_screen_flags`, stats spread loaders, permutation default) | C | open |
| 6.5 | DEV-015 BUG-D73 split-seam fix against a real IBKR refresh | C | open |

### W7 — Infrastructure (T11)
| # | Step | Owner | Status |
|---|---|---|---|
| 7.1 | DEV-008 manifest lock, DEV-014 read-only build, DEV-023 config-drift guard | C | ✅ |
| 7.2 | DEV-016 mem_guard tree-kill re-test on a real breach | C | open (after the chain) |
| 7.3 | DEV-018 memtest86+ / RAM speed on CachyOS — needs Ross at the machine (reboot into memtest) | R | open; hangs recur |
| 7.4 | DEV-019 Windows admin fix — Ross | R | open |
| 7.5 | DEV-017 fstab NTFS mounts, DEV-020/021/022/024/025/026 tooling items, CRLF/BOM hazards | C | open |
| 7.6 | Leftover sensitivity checkpoints: now inside `_episodic_scan_backup_20261007_165003` (kept, not deleted) | — | recorded |
| 7.7 | `--fresh` checkpoint-glob fix (8cb7e7ae) pulled onto CachyOS after the chain | C | ⏳ 1.2 |

### W8 — Scrutiny / public repo
| # | Step | Owner | Status |
|---|---|---|---|
| 8.1 | Issue template, ERRATA, README reproducibility, CONTRIBUTING | C | ✅ |
| 8.2 | Intake triage routine exercised on a first external report | C | open (needs a report) |
| 8.3 | Keep ERRATA/README/Development/HANDOFF current at each milestone | C | ongoing |

---

## Part C — Sequencing and time (estimates, CachyOS-bound)
1. **Now → ~6 days (J):** W1.1 → W1.2 → W1.3 on CachyOS. Meanwhile (C, Surface): S1/S2 commit, W5 bug recheck,
   W4.1 Act 3, W4.3 claim registration, W4.4 process-paper draft, W3.2/3.4 test-first builds, W6.3/6.4.
2. **After W1.1 (~day 2):** W2.2 on the offset-0 pools can start while the offsets run (shares CachyOS — run between
   offsets, never concurrently with a Tier 3 pass).
3. **After W1.3:** grid-robust pools (W2.2), then W2.3 second pass (~1 day), W2.4 report + review.
4. **Then:** comparisons W3 → third labelled pass W2.5 → W4.2 claims → council → W4.5 papers → W4.6 deep dives.
Risk: CachyOS hard hangs (DEV-018) — each costs up to a day; the chain resumes from checkpoints.

## Part D — Not run (free-data rule or out of scope), recorded
Futures roll adjustment; options contracts, order books, implied correlation (DEV-061); paid data subscriptions;
IBKR deep history in discovery (S14); GPU EG (S28).
