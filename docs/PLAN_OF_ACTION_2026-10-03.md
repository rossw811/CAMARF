# Plan of action — every thread to completion (2026-10-03)

Ross (2026-10-03): "make a plan of action for every thread to complete including any backlog items."
Rules that apply to every step: free data only (skip any test free data can't support); verification loop (failing
test first → real-data check → independent check for anything headline/paper-bound → evidence with the claim);
lineage records for every chain stage; every result registered in docs/CLAIMS_REGISTRY.md before it is cited;
holes found are fixed or disclosed and logged. Owner: **C** = Claude, **R** = Ross decision, **J** = unattended job.

Status legend: ✅ done · ▶ in progress · ⏳ waiting on a dependency · ❓ needs Ross · ✖ not run (free-data rule)

---

## T1 — Data layer to completion
| # | Step | Owner | Status / dependency | Done when |
|---|---|---|---|---|
| 1.1 | Compustat `trfd` fetch (15,195 listings) | J (CachyOS) | ▶ 10,681 done; restarted 13:12 | `JOB FINISHED` in latest_run_trfd_fetch.log |
| 1.2 | Apply USD total return to global listings | J | ⏳ 1.1 | apply report: 0 negative TR-over-price gaps; spot-check 3 listings vs ADR TR |
| 1.3 | Pre-1992 Nasdaq quote-only fetch (2,758) into `_quote_only/` | J | ⏳ 1.2 | ≥ 2,700 files; 5 spot checks vs dsf_v2 |
| 1.4 | Sync CachyOS → Surface (trfd TR, quote-only) | C | ⏳ 1.3 | size + hash parity |
| 1.5 | Futures roll adjustment | — | ✖ no free contract history (IBKR from 2025-09 only; yfinance none; WRDS 100-contract sample) | disclosed in paper limitations |
| 1.6 | B1 / B2 / B4 (legacy P&L, `--hedge both` duplicates, dead `data_gap` exit) | R → C | ❓ decide: retire legacy `pnl_net` mode + make OLS-only the default, or keep both as labelled arms | decision logged; code + tests |
| 1.7 | D11 tz redesign (`_standardize` + `snap_timestamps`, BUG-D57 interaction) | C | open; exposure nil today (intraday pool is US-only) | test across .L/.T/.HK + crypto |
| 1.8 | Silent handlers: data.py's 26; `_apply_research_screen_flags`; stats spread loaders; permutation default | C | open | each triaged: log, fail-loud, or justified |
| 1.9 | Unilever ADR ratio 1.089 vs 1.0 | C | open | explained (share line / ratio change) or disclosed |
| 1.10 | DEV-003 CRSP `dlyvol` share-count adjustment direction | C | open | checked against a known split |
| 1.11 | D18 sensitivity data (midpoint days, quote-only) | J | ▶ arms built (dacd3b07) | both arms' scans complete (T2) |

## T2 — Discovery → pools (the chain)
| # | Step | Owner | Status | Done when |
|---|---|---|---|---|
| 2.1 | Intraday discovery 1h/4h (no IBKR depth) | J | ✅ 1h 6 / 4h 0 confirmed | lineage recorded |
| 2.2 | 1D discovery PRIMARY `--fresh --d18 exclude` | J | ⏳ T1.1-1.3 (~20-27 h) | lineage `episodic_scan` recorded |
| 2.3 | 1D discovery SENSITIVITY `--fresh --d18 include` | J | ⏳ 2.2 | lineage `episodic_scan_d18incl` |
| 2.4 | D18 comparison report (pairs found, overlap, tier counts, which factor drives differences) | C | ⏳ 2.3 | report + registry entry; Ross decides the arm |
| 2.5 | Adapter `--fresh` → comparison arms → PIT eligibility → clean pools → spreads → squeeze | C/J | ⏳ 2.2 | `python research/pipeline_stages.py` all OK; `degenerate_column_audit` + `pipeline_contracts` pass |
| 2.6 | M-1: same-dates null alongside the date-scrambled null | C | ⏳ design approved | both nulls reported for the spurious-regression correction |
| 2.7 | DEV-013 end-of-run pair count printed pre-filter | C | open | count matches the saved pairs |

## T3 — Pre-registered strategy search, second labelled pass
| 3.1 | Dated addendum to Amendment 2 once trfd TR applied (drops the price-only disclosure) | C | ⏳ T1.2 | committed BEFORE the run |
| 3.2 | `strategy_search.py run` + `eval` on the rebuilt pools | J | ⏳ T2.5 | lineage `strategy_search` recorded |
| 3.3 | Report both passes side by side; adversarial review of the verdict | C + reviewer agent | ⏳ 3.2 | registry C-006 updated |

## T4 — Claims registry and re-derivation
| 4.1 | C-001 durability (NTRS/STT) | C | ✅ CORRECTED → REPLICATED | — |
| 4.2 | Fix PAPER.md:130-137 sample statement (10,098 d from 1985) | C | open | committed |
| 4.3 | Register every number cited in PAPER.md / PAPER_MAGNITUDE.md (≈ 284 scrutiny rows → claims) | C | open | each claim has an entry + status |
| 4.4 | Re-derive C-002..C-006 on current data | C/J | ⏳ T2/T3 for C-003..C-006 | status REPLICATED / CORRECTED / WITHDRAWN |

## T5 — Process paper ("what it takes …")
| 5.1 | Outline | C | ✅ docs/PAPER_PROCESS_OUTLINE.md | Ross approves framing ❓ |
| 5.2 | Ledger reconciliation | C | ▶ 2026-10-03: 18 rows → FIXED with evidence; B1/B2/B4 ❓ | every row has an evidenced status |
| 5.3 | `docs/process_paper/failures.csv` (class, detection, check, before/after effect, evidence) | C | open | each row re-derived or cited to a commit+test |
| 5.4 | Attribution pass over git history (model trailers) | C | open | table with "unattributed" stated |
| 5.5 | Draft → adversarial review → council (5 lenses) at milestone | C | ⏳ 5.3-5.4 | review findings closed or disclosed |

## T6 — Thesis papers (PAPER.md, PAPER_MAGNITUDE.md) redraft
| 6.1 | Apply scrutiny verdicts (withdraw / qualify / replace) | C | ⏳ T3 (results) | only REPLICATED claims cited |
| 6.2 | Ross approval of revised abstracts | R | ⏳ 6.1 | — |

## T7 — Deep dives (order approved: 1 → 2 → 4, with 3 alongside, 5 optional)
| 7.1 | Durability-vs-currency gap universe-wide (power-matched windows; GH/ZA breaks) | C | ⏳ T2.2 | pre-registered, registry entries |
| 7.2 | Why convergence AUC 0.61 doesn't become profit (P&L decomposition; rules from the model's horizon) | C | ⏳ T3 | pre-registered comparison arms |
| 7.3 | Hawkes clustered null (entries/divergences/stop-outs; time-rescaling GOF) as comparison arm | C | ⏳ T2.5 | luck-check verdicts under iid vs Hawkes nulls |
| 7.4 | Identity-contamination note (old vs new discovery on corrected labels) | C | ⏳ T2.2 | numbers from the two runs |
| 7.5 | Calendar-padding artifact in published results | C | optional | — |

## T8 — Scrutiny infrastructure (repo is public)
| 8.1 | `find_a_hole` issue template | C | ✅ | — |
| 8.2 | Public errata / known-limitations page (one index into the ledgers) | C | open | linked from README |
| 8.3 | README: how to reproduce (lineage, WRDS licence note, free-data claims) | C | open | — |
| 8.4 | Intake triage routine (verify → fix/disclose → log on the claim) | C | open | first external report handled end to end |

## T9 — Execution realism (free data only)
| 9.1 | TAQ-sample feasibility: which symbols/dates the sample covers; cost model only if it overlaps the pools | C | ⏳ T2.5 | feasibility note; build only if usable |
| 9.2 | Paper trading (IBKR paper account) | C | only if T3 finds a robust signal | — |
| — | Options contracts, order books, order-book simulators | — | ✖ no free data (Ross 2026-10-02) | — |

## T10 — Research-script findings (R-series: 21 confirmed, 80 unverified)
Rule: an R-finding is fixed and its script re-derived **when that script's result is cited or re-run**; scripts
whose results are not cited are marked "not cited — finding unresolved" in the errata (honest, not silent).
| 10.1 | Map every R-finding to the PAPER/MAGNITUDE claims that depend on it (scrutiny rows already cite them) | C | open |
| 10.2 | Fix the cited ones first: R6.3 (EG null one-direction), R6.5 (CI grid can't contain 1), R8.x, R3.1/R3.7, R4.x, R5.x, R7.x — each with a failing-first test | C | open |
| 10.3 | C4-2: research EG p-values via `analysis.eg_pvalue_pair` (non-permutation callers) / production segment then real + null (permutation callers) | C | plan written |
| 10.4 | DEV-011 re-run the 5 scripts whose "full universe" was the yfinance glob | C | ⏳ T2 |

## T11 — Infrastructure backlog (DEV ledger OPEN-infrastructure)
DEV-008 manifest write race · DEV-014 read-only gate for analysis.py · DEV-016 mem_guard tree-kill re-test ·
DEV-017 CachyOS NTFS mounts in fstab · **DEV-018 memtest86+ / RAM speed on CachyOS** (hard hangs recurred
2026-10-02/03 — moved up) · DEV-023 config-drift guard beyond wfa/sensitivity · DEV-024 CachyOS optimisation
leftovers · `intraday_episodic_scan --workers` hardcoded 6 · Windows CRLF / PowerShell BOM hazards in tooling.
Owner C (DEV-018, DEV-019 need Ross at the machine). Done when each is fixed or closed with a reason.

## T12 — Research-extension backlog (DEV ledger OPEN nice-to-have, 30+ items)
Not scheduled until T3 reports. Then triaged against the deep dives: items that feed T7 are pulled in (e.g. DEV-035
comomentum, DEV-044 usable-not-just-significant, DEV-069 shared-leg hub risk, DEV-060 factor-level cointegration);
the rest are recorded as "deferred — not run" with the reason. Free-data rule applies (e.g. DEV-033 CBOE SKEW /
put-call / Google Trends are free → eligible; DEV-042 extra WRDS tiers only if in the subscription).

## T14 — Recheck of every logged bug (Ross, 2026-10-03)
Scope: every logged defect, whoever logged it and whatever its "FIXED" label says (Ross's standing rule: treat every
earlier claim as unverified until re-checked). Sources: Development.md's bug registry (125 distinct BUG-* IDs; the
docs/BUG_LOG.md index covers only 48 — itself stale), the code-review ledger (175 rows), the inconsistency sweep
(~20 findings), and the D/M/U/S/C/A/B series.
| # | Step | Owner | Done when |
|---|---|---|---|
| 14.1 | One inventory of every logged bug: id, source line, claimed status, affected code (file:function) → `docs/bug_recheck/inventory.csv` | C | every BUG-*/ledger/sweep id present once |
| 14.2 | Map each bug to its regression test(s) (`debug/_verify_*.py` docstrings/ids) → coverage % | C | mapping in the inventory |
| 14.3 | ✅ 2026-10-03: 310/319 → 8 failures triaged (3 stale P1 fixtures fixed, 3 tests updated to new rules, 1 data-deleting test sandboxed, paper_claims → T6; data_wrds needs live WRDS). **Standing rule from now: run the full suite before committing a change to a core module** (P1 broke 3 tests unnoticed for a week). Original step: run the full verify suite against current code (`debug/_run_all_verify.py`, 319 scripts) on CachyOS + the Surface | C/J | every FAIL triaged: regression (fix) vs stale fixture (fix the fixture only with evidence, as with _verify_pdr_calmar) |
| 14.4 | Bugs in live code with no test: write a reproduce-first regression test; dead-code bugs → "obsolete" with the commit that removed the code | C | no live-code bug without a test or a stated reason |
| 14.5 | Real-data recheck for bugs that touch a headline number (re-derive the effect; record before/after) | C | effect recorded in the inventory and, if cited, in the claims registry |
| 14.6 | Rebuild docs/BUG_LOG.md from the inventory (all ids, current status: holds / regressed / obsolete / untested) | C | index covers 100% |
| 14.7 | Independent check: adversarial-reviewer agent re-verifies a random sample (≥ 10%) of "holds" verdicts | C + agent | disagreements resolved |
Runs alongside T2/T3 (needs no new data); a regression found here pre-empts everything downstream it touches.

## T13 — Decisions needed from Ross (consolidated)
1. Process-paper framing (T5.1).
2. B1/B2/B4: retire the legacy P&L mode and `--hedge both` default, or keep as labelled arms (T1.6).
3. D18 arm choice after the comparison (T2.4).
4. DEV ledger NEEDS-ROSS items still open: DEV-055 holdout convention (fresh holdout per evaluation), DEV-056
   MIN_OVERLAP_BY_TF provisional values, DEV-057 flagged-pair policy (exclude / downweight / flag), DEV-058 S&P
   400/600 point-in-time membership not in the subscription (disclose as survivorship, or partial fix), DEV-061
   implied-correlation divergence (needs options data → ✖ under the free rule unless CBOE free data suffices),
   DEV-064 momentum overlay design, DEV-066 (now the process paper), DEV-067 DFA/wavelet Hurst arm.

## Sequencing (critical path)
T1.1-1.3 (≈ today) → T2.2 (≈ 1 day) → T2.3 (≈ 1 day) and in parallel T2.5 on the primary → T3 (≈ 1 day) →
T6 + T7. While jobs run: T14 (bug recheck), T4, T5, T8, T10, T11, T1.6-1.10. CachyOS stability (DEV-018) first, because a hang
mid-discovery costs a day.
