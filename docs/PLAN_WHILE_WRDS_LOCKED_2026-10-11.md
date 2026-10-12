# Plan while the WRDS account is locked (2026-10-11)

Companion to `docs/PLAN_OF_ACTION_2026-10-07.md` (the goal plan; S1–S36 decided 2026-10-10). This file orders what can
run **without WRDS** until Ross's account is unlocked, and what runs the moment it is. Owners: **C** = Claude,
**J** = CachyOS job, **R** = Ross. Status: ⏳ waiting · ▶ running · ✅ done · ❓ needs Ross.

**Why WRDS is down:** unattended connection attempts (2026-10-10 17:46, 2026-10-11 15:19 and 15:2x) used a
`pgpass.conf` password WRDS no longer accepted; each counted as a failed login and the account locked. Ross is
unlocking it. Item A0 makes sure no unattended job can do this again.

**What is blocked on WRDS:** the CRSP–Compustat link (`crsp.ccmxpf_lnkhist`, queued as job 21), which the
same-company fix needs before the pools can be rebuilt → the second pre-registered pass → its report beside the
first (W2.3/W2.4). Also PAR_1M (job 20, S13) and the R1.12 total-return question for `pit_wfa_wrds_daily` (U4).

---

**Ross 2026-10-12: all of Tracks A–D and all 20 brainstorm items approved ("i like all those. let's do it"), plus
Track E (no arbitrary values; show why; account for overfitting).** Progress: A0 ✅ (0549c32d); A1 ▶ (CachyOS suite);
E1–E2 ✅ (4e0364a0).

## Track E — every value justified, overfitting accounted for (Ross 2026-10-12)

| # | Item | Owner | Done when |
|---|---|---|---|
| E1 | Registry of every tunable value (`docs/PARAMETER_REGISTRY.csv`, 337 on day one) | C | ✅ |
| E2 | Gate test: unregistered / drifted / reason-less values fail; unjustified backlog may only shrink (ratchet) | C | ✅ in the suite |
| E3 | Justify every value, headline-affecting first (BACKTEST, ANALYSIS, STATS, UNIVERSE, discovery-scan constants), from Development.md / git history / calibration scripts; where none exists, run the calibration or mark it for the specification curve | C | backlog 0 |
| E4 | Phase 2: register inline numeric literals used as thresholds (`p < 0.05`, 0.15 gaps, …) | C | scanner + gate cover them |
| E5 | Overfitting account (docs/PARAMETER_REGISTRY.md proposal: trial-count deflation, specification curves, placebo discovery, sealed holdout) | ❓ R | Ross adopts / modifies; then built as comparisons |

## Track A — now, no WRDS, no Ross decision needed

| # | Item | Owner | Done when |
|---|---|---|---|
| A0 | **WRDS login guard.** `data_wrds._connect()` refuses to connect unless stdin is a terminal or `CAMARF_WRDS_UNATTENDED=1` is set; the session server prints a pre-flight message. Failing-first test. | C | test fails on old code, passes on new; no script can attempt an unattended login by default |
| A1 | **Full verify suite on CachyOS** (the chain is finished; machine free). Every failure explained. Closes the goal's suite clause. | J | suite log committed under `docs/bug_recheck/`; each failure explained |
| A2 | **BUG-D115 impact.** Rebuild the 10-08 discovery task lists (primary + grids), count tests absent from the windows files that are not `insufficient_overlap` (= dropped crashes), re-run BH with them at p = 1 and diff the confirmed sets. | C/J | crash count per tier/run; confirmed-set diff (expected: 0 or a handful); ERRATA row updated |
| A3 | **Post-link rerun script, ready to fire.** clean_pools → pool_spreads → squeeze → both audits → `strategy_search run --fresh` → guard (216 fresh files per pool, run time sane) → eval. Plus a run-time sanity guard inside the chain script itself (a 432-backtest run that finishes in seconds stops the chain — the BUG-D116 lesson). | C | dry-run on CachyOS stops at the missing link file with the expected message |
| A4 | **Mechanical review fixes** still open: R5.10 (stress-test log prints N/N), R4.11 (orientation-independent merge in `regime_strength_vs_discovery_regime_test`), stale "0.40" comments in `analysis.py` (6323, 6368). Failing-first where behaviour changes. | C | each fixed + verdict updated |
| A5 | **W5.6b** — yfinance ADV paths (`analysis._compute_adv`, `sensitivity.py:124`) multiply local-currency close by volume against a USD threshold; reuse `dollar_volume.usd_dollar_volume`. | C | failing-first test; real-data count of names whose gate decision changes |
| A6 | **W6.4** — remaining silent exception handlers (stats spread loaders, permutation default). | C | each fails loud or logs; tests |
| A7 | **W3.2 A4 causal half-life arm** and **W3.4 B9 next-bar fills** — both approved as comparison arms (S5/S7); build failing-first now so they run on the rebuilt pools. | C | arms built + tested; run after the pools |
| A8 | **W4.4 process-paper draft** (inputs ready: bug registry, verdicts, errata, this week's D115/D116/S36-gap cases). Adversarial review, then the council. | C | draft committed; review findings closed or disclosed |
| A9 | **DEV-016 mem_guard tree-kill re-test** on CachyOS (needs an idle machine — after A1/A2). | C/J | real breach kills the whole tree; recorded |
| A10 | **P-089 FANG/OXY worked example** re-checked against the 756-bar override rule (BUG-D68/A5) on cached 1m data. | C | REPLICATED / CORRECTED in C-007 |

## Track B — needs Ross's decisions (proposals written now, nothing run before buy-in)

| # | Item | Owner | Done when |
|---|---|---|---|
| B1 | **Proposals for the 16 confirmed methodology findings** behind the PAPER_MAGNITUDE regime/episode claims (R3.3 post-hoc top-2 binomial; R3.4 independence; R3.5 missing episode-level test; R3.6 gap rule without a null; R3.10/R3.11 survivorship scope and design; R5.5–R5.7 stress test; R5.8 day-vs-trade bootstrap; R6.4 unaligned null pairs; R6.9 non-null-centred cluster bootstrap; R8.12 power on the recent window). One page each: the problem, the proposed test (comparison-arm form), what result would change the claim. | C → R | Ross marks each adopt / modify / drop |
| B2 | **Re-derive the ~20 regime/episode claims** (M-058…M-077) on the new discovery output (687 Tier-3 pairs, not 29), using the adopted tests. Old and new side by side. | C/J | each REPLICATED / CORRECTED / WITHDRAWN |
| B3 | **Act 3 re-derivation (S18)** on dollar P&L, using the Surface/CachyOS machine-difference finding. | C/J | registry status |

## Track C — the moment WRDS is back (R logs in once, interactively)

1. R runs `research/wrds_session_server.py`, approves Duo, recreates `.pgpass` → jobs 21 (CCM link) and 20 (PAR_1M) run.
2. A3's script fires on CachyOS: pools rebuilt with the linked same-company rule (91 mixed pairs re-checked),
   audits, second pre-registered pass (~3 h), eval.
3. Report the second pass beside the first (C-006), adversarial review of the verdict, registry + ERRATA updated.
4. R1.12: present the total-return vs price-only choice for `pit_wfa_wrds_daily` (U4) with numbers from both; then the
   dollar-P&L re-runs of pit_wfa / distance / sensitivity (W2.5 inputs).

## Track D — Ross at the machine (whenever convenient)

- DEV-018 memtest86+ on CachyOS (recurring hard hangs). DEV-019 Windows admin fix.

## Order

A0 → (A1 ∥ draft B1) → A2 → A3 → A4–A6 → A7 → A10 → A8; A9 when CachyOS is idle. Track C pre-empts everything once
WRDS is back. One sub-agent at a time; every fix failing-first; every paper-bound result independently reviewed.

---

## Brainstorm — 20 new items (for Ross to pick from; none started)

Grouped by what they would add. Each is free-data and would enter as a comparison arm or a pre-registered study.

**Calibrating the discovery machine itself**
1. **End-to-end placebo discovery.** Run the full episodic pipeline on a synthetic universe of independent random
   walks with the real universe's size, history lengths and missingness pattern. The confirmed count is the
   pipeline's true end-to-end false-discovery rate — the number every discovery claim should be read against.
2. **Detection power curves.** Plant cointegration of known half-life and duration (e.g. 1–15 years) into real
   series and measure the probability the scan confirms it. Answers "what kind of relationship can this method even
   see?" — the missing half of every null result.
3. **Null baseline for grid-robustness.** The 21%/18% grid-robust share needs a reference: the share expected under
   no cointegration, from (1). The independent reviewer flagged its absence.
4. **ADR/home-listing pairs as positive controls.** The pairs this week's S36 gap let in are cointegrated by
   construction (same cash flows, FX-adjusted). Kept out of the pools, they are an ideal labelled test set for
   sensitivity: what share does the pipeline confirm, how fast does it re-confirm after a break?
5. **Leg-order-free test arm.** Johansen (or Phillips-Ouliaris) beside EG-max-of-directions, on the same windows; C-007
   showed borderline pairs can depend on leg order.

**Understanding what is found**
6. **Survival analysis of cointegration.** Kaplan–Meier / Cox hazards for "time until a confirmed pair stops
   confirming", by sector, size, regime of discovery. Turns the durability-vs-currency point into a measured
   half-life of relationships.
7. **Window-to-window transition matrix.** P(confirmed in w+1 | confirmed in w) against the base rate — the cleanest
   measure of whether episodic confirmation predicts anything.
8. **Economic-linkage model.** Do confirmed pairs share SIC/GICS, index membership, or customer/supplier links
   disclosed in SEC filings (free EDGAR)? A logistic model of "confirmed" on linkage features tests whether
   discovery finds economics or noise.
9. **Factor-neutral spreads.** Regress spreads on the Fama-French 5 factors (cached) and re-test mean reversion of the
   residual — is the "pair" just shared factor exposure?
10. **Regime definition robustness.** Re-run the regime findings with an HMM on market volatility instead of the VIX
    threshold; a finding that only holds for one regime definition is not a regime finding.
11. **Half-life estimation bias.** Small-sample AR(1) bias (Kendall) on short windows understates half-lives;
    bias-corrected estimator as a comparison arm, with the effect on holding periods and trades.

**Trading-relevance (honestly bounded)**
12. **Break-even cost frontier.** For each pool, the round-trip cost at which the gross edge reaches zero, against
    measured spreads/ADV — reports "how far from tradable" instead of a single Sharpe.
13. **Capacity curve.** Capital-sim Sharpe vs capital deployed with ADV participation limits — where any edge dies.
14. **Sealed holdout.** Declare 2024-07 → present untouched now (pre-registered), for a single final test of whatever
    survives the second and third passes.
15. **Forward paper-trading record.** Free live data (yfinance/Binance) recording the second pass's selected
    configuration forward from a committed date — the only truly out-of-sample test available.

**Process and reproducibility (the scrutiny-first story)**
16. **Project-wide trial ledger.** Count every specification ever run (backtests, arms, sweeps) from logs and
    lineage; report a project-level deflated Sharpe — the honest multiple-testing denominator for the whole
    research history.
17. **Verification-layer yield study.** From the bug registry: which layer caught each bug (synthetic test, real-data
    check, adversarial review, audit, outside reviewer), how late, and how much each would have changed a headline.
    Core quantitative content for the process paper.
18. **One-command reproduction.** A locked environment plus `make reproduce-<claim>` for every REPLICATED claim, and
    the verify suite in CI on every push — turns "invited to attack" into "can re-run in one line".
19. **Public claims dashboard.** A page generated from `claims_table.csv` + the registry showing each claim's status,
    evidence and reproduce command; updated on every commit.
20. **External red-team round.** Package three headline claims with data access instructions and invite one or two
    outside quants/academics to try to break them; log every reported hole through the W8 intake routine.
