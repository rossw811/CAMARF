# Paper Scrutiny — PAPER.md and PAPER_MAGNITUDE.md, section by section (2026-09-27)

**Status: PROPOSED CHANGES for Ross's approval. Nothing in either paper has been edited.** Read-only on every
existing file; this is the only file written.

Builds on (does not redo): `docs/CONSISTENCY_AUDIT_2026-09-26.md` (claim IDs P-1..P-34, M-1..M-20, H-*, N-*),
`docs/CITATION_AUDIT_2026-09-26.md` (citation rows #1-#74, cited here as "cit#N"), `docs/CODE_REVIEW_2026-09-26.md`
(finding IDs B*, A*, D*, S*, U*, M*, C*, R*, P1, plus its "Post-review updates" section), and the
`Development.md` session entry "2026-09-26/27" (Development.md:28490-28572).

Line numbers are `file:line` in the working tree at HEAD 8bb2bf0a. Both papers gained a 12-line
"RESULTS UNDER REVISION" banner on 09-26, so PAPER.md lines are ~13 higher and PAPER_MAGNITUDE.md lines ~14
higher than the line numbers in the 09-26 consistency audit.

## Verdict key

| Verdict | Meaning |
|---|---|
| **STANDS** | Checked; no confirmed finding bears on it. Wording may stay. |
| **QUALIFY** | Can stay only with the caveat or re-derivation note given. Used when the only findings behind the problem are UNVERIFIED leads, or the claim is directionally right but overstated. |
| **WITHDRAW** | Cannot stand as written: the number or conclusion comes from a CONFIRMED defect, a confirmed misattribution, or is contradicted by a corrected result. |
| **REPLACE** | Short for REPLACE-WITH-CORRECTED-VALUE: a corrected value is already committed and can be cited now (with the stated scope). |
| **UNVERIFIED** | Cannot be checked from the committed code, outputs or audits; needs a source or a run before it is cited. |

"Corrected results" used in this document are only these, all committed (CODE_REVIEW:427-528,
Development.md:28490-28572). No other number is introduced.

| Tag | Corrected result | Scope that must travel with it |
|---|---|---|
| **CR-1** | Dollar P&L (`pnl_dollar.py`), net / gross business-day Sharpe: momentum IS −0.408 / −0.191; squeeze IS −0.386 / −0.227; combined IS −0.354 / −0.248; momentum OOS −0.296 / −0.125; squeeze OOS −0.078 / +0.003; combined OOS −0.005 / +0.048. Gross excluding immediate stop-outs: −0.119 / −0.191 / −0.219 IS, −0.157 / +0.031 / +0.079 OOS. Old `pnl_net` Sharpes on the same trades: +0.132 / +0.474 / +0.721 IS, −0.184 / +0.667 / +0.601 OOS. | Hedge fixed at entry, real (total-return) leg prices, fixed dollar notional, OLS trades only, 1D, USD-only legs (~31% of trades), unconstrained (NOT capital-sim), the six current gate trade files. |
| **CR-2** | Purged + 1% embargo 8-model comparison (16 trials; "9-model" in the prompt this was built from was wrong), 74,732 events / 1,301 pairs, TE features excluded: RF 0.6085 [0.6001, 0.6164], XGBoost 0.6067 [0.5983, 0.6153], MLP 0.6033, LightGBM 0.6024 (tied with XGBoost); RBF-SVM 0.5744, KNN 0.5709, L1/L2 logistic 0.557 (significantly worse). XGBoost positional 0.6062 → purged 0.6067. Balanced accuracy at 0.5 vs Youden threshold: 57.72% vs 57.64%. | Label = z-convergence after a |z| = 1.5 crossing (ml.py events), NOT the strategy's 3.0 entries and NOT profitability. ml.py itself still splits positionally and still includes TE features (ml.py:711-724). |
| **CR-3** | Meta-labeling the strategy's own trades (label = dollar-profitable): AUC 0.47-0.54 across 24 (gate, model) trials; capital-sim Sharpe differences −0.19 to +0.59 in both directions. | OLS, 1D, USD-only, gate IS trade files; consistent with noise. |
| **CR-4** | Distribution fits: entries per business day negative binomial (mean 1.90, var 5.15; r ≈ 1.05), so an iid same-size null is misspecified; hold time and half-life lognormal; horizon z-change Student-t (df ≈ 7.3); per-pair convergence beta-binomial (LR 495; genuine heterogeneity). | Momentum-gate 1D OLS trades; ML events. Rankings informative, absolute GOF rejected at n = 5,000. |
| **CR-5** | Rule-invariant audit, 101,700 trades: every rule and gate decision executes as coded (0 violations; 47,628 gate decisions re-checked). Design defects: 54-68% of entries at or past the stop; 32-40% stopped after a favourable move; 19-38% re-entry within 1 bar of a stop; `corr_exit` and `data_gap` exits never fire. | ENTRY 3.0, STOP 3.5, EXIT 0.0, MAX_HOLD 2.0×HL, MIN_HL 5 bars. |
| **CR-6** | Quality-admission lookahead fixed: momentum IS 0.2337 → 0.1499, combined IS 0.1000 → 0.0357; the 09-22 luck-check verdicts do not survive (taken_better_than_skipped False in all 6). | Still on the old P&L; not final. |
| **CR-7** | Data-layer fixes: D1 liquidity-filter fabrication removed; yfinance DAILY cache regenerated (equity median flat days 10.8% → 2.9%; forex restored; history to 2026-09-27); D3/D4 snapping lookahead fixed (intraday caches on disk NOT regenerated); A1 fixed in `analysis._run_one_tf` and `pit_wfa` (EG now runs on pairs with different start dates); BH denominator fixed (crashed tests kept in m); D2, D14, C13, S7, D15, D16 fixed. | Nothing downstream has been re-run on the fixed code except the items above. |

---

## (1) Summary counts

| Paper | Rows | STANDS | QUALIFY | WITHDRAW | REPLACE | UNVERIFIED |
|---|---|---|---|---|---|---|
| PAPER.md | 196 | 30 | 71 | 81 | 8 | 6 |
| PAPER_MAGNITUDE.md | 88 | 14 | 38 | 34 | 0 | 2 |
| **Total** | **284** | **44** | **109** | **115** | **8** | **8** |

(Counts are of the rows in the tables below; each row is one claim or one tightly bound group of numbers
from the same run. PAPER_MAGNITUDE has no REPLACE rows because none of its results is covered by CR-1..CR-7:
its P&L numbers come from `pit_wfa*.py` fold backtests and its statistics from the Tier-3 scan, neither
re-run.)

What the counts say in one line: almost everything that is a P&L number, a significance claim built on P&L,
or a "PIT-safe" label must go; the durability-vs-currency demonstration (NTRS/STT), the calendar-padding
derivation, the SPAC mechanism, the multiple-testing arithmetic and the purged ML AUC survive; the paper's
current headline (the strategy "loses money, robustly") can be partly restated now on the dollar accounting
(REPLACE rows) but not in the form written.

---

## (2) Headline and abstract (both papers first)

### PAPER.md — title block, throughline, framing, abstract

| ID | Location | Claim (short quote) | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-001 | PAPER.md:16-17 | Title "…and the Honest Cost of Applying It" | QUALIFY | B2, B3, B4, S3; CR-1 | Keep the first half. Second half → "…and What Applying It to a Real Strategy Does and Does Not Show" until the P&L rebuild (FX, capital-sim) is complete. |
| P-002 | PAPER.md:19-26 | Retitled after "the genuinely point-in-time-safe 182-pair backtest result became the paper's obvious missing conclusion" | WITHDRAW | S3, B2-B4, P-2 | "(Retitled 2026-09-10 around a backtest of an episodically-confirmed pair pool; that backtest's P&L and its point-in-time status were both found defective on 2026-09-26 — see §7.20.)" |
| P-003 | PAPER.md:33-35 | apply the diagnostic "to a genuinely point-in-time-safe (not merely out-of-sample-backtested) version of the full production strategy" | WITHDRAW | S3 | "…to an episodically-confirmed pair pool whose individual confirmation windows are point-in-time, but whose pair set was assembled from all windows up to the build date (so it is not point-in-time relative to the backtest's trading dates)." |
| P-004 | PAPER.md:36-39 | "The answer is that it loses money, both in-sample and out-of-sample, robustly across a parameter sweep. That result … is this paper's headline." | REPLACE | B2, B3, B4, P1, R2.2; CR-1, CR-5 | "On dollar P&L with the hedge held at entry (OLS, USD-only legs, ~31% of trades, unconstrained), every entry-gate variant loses money in-sample (net Sharpe −0.354 to −0.408; gross −0.191 to −0.248). Out-of-sample, the momentum gate loses (−0.296) and the squeeze and combined gates are indistinguishable from zero (−0.078, −0.005). The parameter sweep, the ungated arm, the capital-constrained replay and the 69% of trades with a non-USD leg have not been re-derived." |
| P-005 | PAPER.md:43-55 | Two-paper split; PAPER_MAGNITUDE is the lead paper | STANDS | — | no change |
| P-006 | PAPER.md:88-93 | Original framing: backward-looking pair set, "Sharpe 5.2155 OOS", "meant to read as confirmation the methodology has teeth" | QUALIFY | B2, B3, B4, B11, P-14 | Append: "That Sharpe was produced by the pre-2026-09-26 P&L accounting (B2 rolling-hedge drift, B3 unit mixing, B4 OLS/Kalman duplicates), which turned losing gate strategies into +0.13 to +0.72 Sharpes on the corrected comparison (§7.21); it is kept only as provenance and is not evidence of anything." |
| P-007 | PAPER.md:102-109 | "genuinely point-in-time-safe (episodic, causally-gated) discovery … It loses money (§7.20): −0.679 IS / −0.834 OOS … robust across a full parameter sweep" | WITHDRAW | S3, B2-B4, P1, R2.2, P-1 | Replace with the P-004 text. |
| P-008 | PAPER.md:110-114 | "NTRS/STT and SHW/UNP's durability-vs-currency conflation is real regardless of what happens next" | QUALIFY | internal (§4.2 at PAPER.md:653-671), N-12 | "…NTRS/STT's durability-vs-currency conflation is real regardless of what happens next (SHW/UNP does not replicate on CRSP data, §4.2)…" |
| P-009 | PAPER.md:130-137 | Abstract: NTRS/STT full-sample EG p≈0.00005, 13,373 daily obs since 1972, last-5y p=0.561, on WRDS/CRSP | STANDS | P-18 (UNAFFECTED; `durability_vs_currency_wrds.py` reads `close_total_return`, aligns legs, `_eg_worker` unchanged by the A1 fix) | Optional precision (R8.12, UNVERIFIED): add "; the 5-year test has ~1,260 observations versus 13,373, so the recent-window failure is partly a power difference." |
| P-010 | PAPER.md:139-145 | SHW/UNP does not replicate as cleanly on WRDS; NTRS/STT plus three negative controls sufficient | STANDS | — | no change |
| P-011 | PAPER.md:145-157 | Companion observation refuted by Monte Carlo: FP rate 7.75%-12.75% vs 5%, rising with horizon, "ordinary spurious regression" | QUALIFY | R6.3, R6.4 (UNVERIFIED), P-16 | "…a Monte Carlo study using a one-direction EG call (not the production both-directions call), on pre-WRDS yfinance series, found an empirical false-positive rate of 7.75%-12.75%…; this has not been re-run with the production test or on WRDS data." |
| P-012 | PAPER.md:157-160 | Calibration study "still runs on pre-WRDS data … flagged … not silently carried forward" | STANDS | — | no change |
| P-013 | PAPER.md:160-164 | "The full-sample screen's near-total rejection rate at long horizons in production reflects the test correctly guarding against exactly this risk, not a defect" | WITHDRAW | A1 (CONFIRMED on the production path; fixed 8bb2bf0a), S2, P-17 | "The near-zero production rejection rate at 1D is now known to be at least partly a defect: until 2026-09-27, `analysis.py` silently failed to run EG on any pair whose two histories start on different dates, and dropped those pairs from BH's denominator. The rate must be re-derived on the fixed code before any reading of it is offered." |
| P-014 | PAPER.md:165-173 | `coint_fraction_rolling` introduced; override "illustrated on a real case where it overturns the primary filter's decision" | QUALIFY | A5 (UNVERIFIED), D1 (the FANG/OXY example is 1m yfinance data) | Keep the diagnostic sentence. For the override: "…illustrated on a 1-minute example (§4.4) whose data came from a cache later found to contain fabricated bars (D1); the example is illustrative until re-run." |
| P-015 | PAPER.md:175-188 | Backward-looking pair set "achieved an OOS portfolio Sharpe of 5.2155 (449 trades…) … IS Sharpe 5.8044 … a real result, cross-checked twice more" | WITHDRAW | B2, B3, B4, B11, D3/D4 (1h snapping lookahead), P-14 | "An earlier backtest on a backward-looking-discovered pair set reported an OOS Sharpe of 5.2155; that number was produced by P&L accounting later found to manufacture positive Sharpes (§7.21) and by an hourly cache with up to 90 minutes of timestamp lookahead (D4). It is retained only as provenance." |
| P-016 | PAPER.md:190-199 | Headline: PIT-safe discovery → loses money; 182 pairs; IS −0.679, OOS −0.834; "every out-of-sample cell negative (range −1.150 to −0.179)" | WITHDRAW | S3, B2-B4, P1, R2.2, P-1, P-3 | Replace with P-004 text plus: "The pair pool (1,375 pairs, rebuilt 2026-09-14) is episodically confirmed but, as built, selected with windows up to its build date (S3); a rebuild with an explicit as-of cutoff is pending." |
| P-017 | PAPER.md:199-204 | Tiered = Baseline positive Sharpe "a disclosed capital-efficiency artifact of which pairs happen to trade" | WITHDRAW | B2-B4 (numbers), A1 (the 3 standard-screen pairs came from the A1-affected screen) | Delete; the arm is superseded (§7.20 note) and its Sharpe is on the invalid accounting. |
| P-018 | PAPER.md:204-209 | "a screening process that can see its own future certifies pairs, and produces backtest results, a causally-constrained observer would not have had" | QUALIFY | S3, S1/A1, B2-B4, M-1, M-2 | "…is the hypothesis this paper tests; the evidence previously offered for it (§7.3.1, PAPER_MAGNITUDE §4) rests on backtests whose P&L and, for the 1h screen, whose EG alignment were defective, and is being re-derived." |
| P-019 | PAPER.md:211-226 | §5-§7.19 pre-WRDS, not used as evidence; §4.5 exception survives | STANDS | — | Add one sentence: "They also predate the 2026-09-26 P&L correction, so their P&L numbers are invalid, not merely pre-WRDS." |

### PAPER_MAGNITUDE.md — opening paragraph, status, relationship, abstract

| ID | Location | Claim (short quote) | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| M-001 | PAPER_MAGNITUDE.md:17-23 | "primary contribution (§4) is a causal-validity result: a full-history screen certifies pairs a genuinely point-in-time (PIT) re-screen would not have found or profited from" | QUALIFY | B2-B4, P1, S1/A1 (1h fold screen), R5.1, M-1, M-2 | "…is a causal-validity question: does a full-history screen certify pairs a point-in-time re-screen would not have found? The profitability half of the earlier answer is withdrawn pending re-derivation (P&L accounting defects; the 1h re-screen ran before the A1 alignment fix)." |
| M-002 | PAPER_MAGNITUDE.md:23-26 | Regime finding "is [informative], for one of two sub-claims, once checked with cluster-robust rigor" | WITHDRAW | R3.1 (CONFIRMED), R6.9 | "…a secondary, exploratory question (§5): neither sub-claim currently survives — the confirmation-rate effect is not significant under an episode-clustered bootstrap, and the persistence effect is withdrawn because 'reappears' was coded in a way that makes crisis-first reappearance nearly automatic." |
| M-003 | PAPER_MAGNITUDE.md:42-47 | "Every numeric claim below is … cross-checked against the underlying `output/research/*.parquet` file" | WITHDRAW | H-15, N-3, N-4, N-8 | "Every numeric claim below is sourced to a named script and FINDINGS/Development entry; the 2026-09-26 audit found several were not cross-checked (e.g. the 1,576-symbol 1h cache described as 'WRDS-primary', the stale '29' production count), and those are marked in place." |
| M-004 | PAPER_MAGNITUDE.md:56-60 | Confirmed-pair count moved 23 → 3 → 2 → 29, "each move a genuine methodology correction, not noise" | QUALIFY | A1, N-4 | "…23 → 3 → 2 → 29 → 17…; at least part of the collapse to 2-3 coincided with a since-fixed defect (A1: EG silently skipped every pair whose legs start on different dates), so not every move was a methodology correction." |
| M-005 | PAPER_MAGNITUDE.md:67-72 | Companion paper's "5.24 OOS Sharpe headline" | WITHDRAW | B2-B4, B11, M-18, N-7 | "…(`PAPER.md`, whose headline is being re-derived after the 2026-09-26 P&L correction)…" |
| M-006 | PAPER_MAGNITUDE.md:85-90 | Universe "~44,700 US-equity, ETF, crypto, forex, commodity, and futures symbols"; 638,095 candidate pairs across 5,003,637 (pair, window) tests | QUALIFY | N-1, D1 (forex was 100% NaN until 09-27), M:395-401 | "…a merged universe of ~44,700 symbols, of which the daily-bar episodic scan uses the ~43,662 with a WRDS daily file (US equities/ETFs from CRSP; international listings from Compustat Global in local currency, no FX conversion); correlation pre-filtering generates 638,095 candidate pairs across 5,003,637 (pair, window) tests." |
| M-007 | PAPER_MAGNITUDE.md:96-101 | "one directly-confirmed data point (a PIT-confirmed pair set that traded and lost money, −1.0121 Sharpe on 32 trades)" | WITHDRAW | B2, B3, B4, P1, S1/A1, D3/D4, D1 (1h cache), M-1 | "An earlier 4-fold point-in-time re-screen on the 1h cache produced pair sets whose backtests are being re-derived (P&L accounting, hourly timestamp lookahead and EG-alignment defects were found in the code that produced them)." |
| M-008 | PAPER_MAGNITUDE.md:99-102 | "earlier, independently-run test finding zero overlap … at every checkpoint (Sharpe range −0.72 to −1.04)" | WITHDRAW | BUG-D68 (BL:85: 95.6% of PIT pairs passed only via the short-window override; fix not re-tested), B2-B4, M-2 | Delete from the abstract. |
| M-009 | PAPER_MAGNITUDE.md:107-114 | GGR "treats pair selection itself as a given input, computed once over the full available history" | WITHDRAW | cit#9 (MISATTRIBUTED), M-15 | "The canonical distance-method study (Gatev, Goetzmann & Rouwenhorst, 2006) already selects pairs point-in-time, on a 12-month formation window before each 6-month trading window; this paper asks whether the same discipline changes the result for cointegration screens with multi-decade formation histories." (Confirm against the RFS full text first, per cit#9.) |
| M-010 | PAPER_MAGNITUDE.md:115-118 | "at the current ~1,576-symbol WRDS-primary universe"; corrected-scale re-run "reaches the same genuinely mixed conclusion" | WITHDRAW | N-3 (the 1,576 symbols are the 1h cache; WRDS has no intraday), R5.1, B2-B4, R1.12 | "…on the 1,576-symbol hourly (yfinance/IBKR) cache; a daily re-run on the WRDS universe also exists but its fold Sharpes are on the invalid P&L accounting and are withdrawn." |
| M-011 | PAPER_MAGNITUDE.md:127-133 | Naive crisis confirmation rate 0.248% vs 0.146%, z=2.77, p=0.0056, 11,715 crisis-first pairs | QUALIFY | R3.2, R3.4 (UNVERIFIED), R1.6, R1.1 | Keep, and add: "(naive; confirmation is 'any window', so pairs tested in more windows have more chances — crisis-first pairs average 9.52 windows tested vs 7.34 — an exposure difference not yet stratified)." |
| M-012 | PAPER_MAGNITUDE.md:133-137 | Cluster-robust CI [0.02%, 0.40%] contains calm's rate | QUALIFY | R6.9 (UNVERIFIED: bootstrap not null-centred; 12 very unequal clusters) | "…an episode-level cluster bootstrap (12 clusters, 93% of signal in 2 — a regime in which cluster bootstraps are unreliable) gives a 95% interval of [0.02%, 0.40%], containing calm's rate: no evidence of a general crisis effect." |
| M-013 | PAPER_MAGNITUDE.md:137-141 | "93.1% of confirmations from 2 of 12 episodes is independently confirmed real, not chance (binomial p=0.000006, … p=0.00002)" | QUALIFY | R3.3, R3.4 (UNVERIFIED; top-2 chosen post hoc; confirmations share legs) | "27 of 29 crisis confirmations fall in the 2008-09 and 2011 episodes (descriptive; the binomial test on the two largest episodes is post hoc and treats confirmations sharing legs as independent, so no p-value is reported)." |
| M-014 | PAPER_MAGNITUDE.md:141-148 | Persistence 91.0% vs 78.7%, cluster-robust p=0.032, "in the direction of persisting MORE" | WITHDRAW | R3.1 (CONFIRMED: 'reappears' = any later window in a regime ≠ first; docstring says non-crisis), M-5, H-9 | Delete; replace with: "A persistence comparison is being recoded: as implemented, a crisis-first pair 'reappears' whenever any later window is non-crisis, which is nearly automatic because crisis windows are rare." |
| M-015 | PAPER_MAGNITUDE.md:148-151 | Strength Mann-Whitney p=0.196, underpowered at 29 | STANDS | — | no change |
| M-016 | PAPER_MAGNITUDE.md:151-153 | Not a dose-response; "elevated" slightly below calm | STANDS | — | no change |
| M-017 | PAPER_MAGNITUDE.md:153-159 | SPY-residual test: effect "real in the 6.7% of pairs … the confound is real, not total" | QUALIFY | R4.3 (UNVERIFIED: full-history single beta, not crisis-window), R3.1 (the effect measured is the recoded-away persistence metric), cit#70 | "…a full-history SPY-residual check (one beta per symbol, which does not capture crisis-time beta increases) was run on the persistence metric now being recoded; it is not currently evidence either way." |
| M-018 | PAPER_MAGNITUDE.md:159-165 | Survivorship: 0.34% vs 0.30%, z=1.26, p=0.21, within 20.6% of universe | QUALIFY | R3.10, R3.11 (UNVERIFIED) | "…a survivorship comparison within the 20.6% of pairs whose legs are S&P-500-trackable (not filtered to crisis-first pairs, and unable to detect pairs excluded by survivorship) finds 0.34% vs 0.30% (z=1.26); this does not establish the absence of a survivorship confound." |
| M-019 | PAPER_MAGNITUDE.md:167-169 | "This is the paper's primary, best-evidenced contribution (§4)" | QUALIFY | M-1, M-2, R5.1 | "§4 is the paper's primary question; its evidence is being re-derived (§4)." |
| M-020 | PAPER_MAGNITUDE.md:172-177 | Interaction (Finding #65): §4 and §5 overlap "far more than chance would predict" | QUALIFY | R4.2 (CONFIRMED: pooled normal z at x=2 and x=16), M-10 | "…16 of 929 §5-confirmed pairs are PIT-reconfirmed versus 2 of 637,166 others (exact test pending; shared legs and repeated pairs across cutoffs make the counts non-independent)…" |
| M-021 | PAPER_MAGNITUDE.md:178-181 | "Benjamini-Hochberg correction across 10^5-10^6-scale hypothesis families, point-in-time-safe by construction" | WITHDRAW | S3, R1.6, M-9 | "…Benjamini-Hochberg across 10^5-10^6-scale families of (pair, window) tests (which bounds the pair-level false-discovery rate at ~9.1%, not 5%, because 81% of confirmed pairs rest on one window); the pair sets are not point-in-time relative to later trading dates." |
| M-022 | PAPER_MAGNITUDE.md:182-189 | Six supporting findings "real, verified" | QUALIFY | R6.2, R6.4, cit#70, levy-overlap observation (see M-064), M:§7.6 rows | "…six supporting findings, each with its own status in §7 (two are withdrawn and two qualified after the 2026-09-26 audit)." |

---

## (3) Section-by-section tables

### PAPER.md §1 Introduction

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-020 | PAPER.md:232-235 | Vidyamurthy (2004), "the most cited work on cointegration-based pairs trading" in quotation marks | QUALIFY | cit#2 | Remove the quotation marks, or cite the source of the phrase (likely Krauss 2017) after checking its wording. |
| P-021 | PAPER.md:236-239 | "ml.py/backtest.py results are still too early/small to carry a strategy-first paper" | QUALIFY | CR-2 (74,732 events now) | "…the strategy's own P&L is being rebuilt after the 2026-09-26 audit, so a strategy-first paper is not supportable…" |
| P-022 | PAPER.md:244-250 | Contribution 1: demonstration (§4.2) + Monte Carlo refutation (§4.2.1) | QUALIFY | R6.3, A1 | Keep the §4.2 half; the §4.2.1 half → "…plus a Monte Carlo check of a companion hypothesis, pending re-run with the production two-direction test on WRDS data." |
| P-023 | PAPER.md:251-256 | Contribution 3: calendar-padding methods note | STANDS | — | no change |
| P-024 | PAPER.md:257-258 | Contribution 4 placeholder "once backtest.py exists" | QUALIFY | stale | "4. An end-to-end test of whether the production strategy, applied to an episodically-confirmed pool, makes money (§7.20-§7.21; partially re-derived)." |

### PAPER.md §2 Literature review (claim fidelity from CITATION_AUDIT; bibliography fixes in §2 rows only where they change meaning)

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-025 | PAPER.md:264-265 | "All citations were verified by direct source lookup." | WITHDRAW | H-1, cit structural #1 | "Citations were checked against Crossref/OpenAlex on 2026-09-26 (docs/CITATION_AUDIT_2026-09-26.md); items marked there as CANNOT-ASSESS have not been verified against the full text." |
| P-026 | PAPER.md:269-277 | Engle & Granger (1987); issue is what question a full-sample application answers | STANDS | cit#1 | no change |
| P-027 | PAPER.md:278-282 | Vidyamurthy "most-cited"; "CAMARF's pipeline is the institutional-scale, multi-TF extension of this architecture" | QUALIFY | cit#2 | "…a widely cited practitioner framework…; CAMARF extends its screening step to many timeframes and a large universe." |
| P-028 | PAPER.md:283-288 | Gregory & Hansen (1996) description | STANDS | cit#3 | no change |
| P-029 | PAPER.md:289-294 | Hansen (1992), Quintos & Phillips (1993) | STANDS | cit#4, #5 | no change |
| P-030 | PAPER.md:295-303 | Clegg & Krauss (2018) ">12% annualized after costs … (1990–2015)"; overlap with coint_fraction_rolling | STANDS | cit#39 | no change (add reference entry) |
| P-031 | PAPER.md:304-306 | BH (1995) as CointScanner's per-TF correction | STANDS | cit#6; CR-7 (BH denominator now counts crashed tests) | no change |
| P-032 | PAPER.md:307-312 | Phillips & Ouliaris: "FM-OLS residuals; more powerful than EG in small samples"; "2026-06-29 result: 4 Gold, 23 Silver, 10 Bronze" | WITHDRAW | cit#40 (MISATTRIBUTED), S6 (UNVERIFIED: PO proxy uses univariate DF critical values) | "Phillips & Ouliaris (1990): residual-based Z_α/Z_t tests on OLS cointegrating residuals. Implemented in stats.py as a Phillips-Perron test on EG residuals (an approximation using univariate critical values; see CODE_REVIEW S6)." Drop the tier counts. |
| P-033 | PAPER.md:313-319 | Hakkio & Rush title "How Short Is the Short Run?"; power tracks span | QUALIFY | cit#41 | Title → "Cointegration: How Short Is the Long Run?", add pages 571-581. Substance unchanged. |
| P-034 | PAPER.md:320-329 | Three-way power/multiple-testing/break compounding "an open methodological tension" | STANDS | — | no change |
| P-035 | PAPER.md:333-340 | GGR distance method, 1962-2002, "~11% annualized excess return" | QUALIFY | cit#9 | "…up to 11% annualized excess return…" |
| P-036 | PAPER.md:341-346 | Do, Faff & Hamza "introduces the OU process model"; "cointegration + OU outperforms pure distance on risk-adjusted basis" | UNVERIFIED | cit#45 (CANNOT-ASSESS, high priority; Elliott et al. 2005 predates) | "…proposes a stochastic residual spread model in state-space form (Do, Faff & Hamza, 2006, FMA European Conference)." Drop the outperformance clause until checked against the paper. |
| P-037 | PAPER.md:347-354 | Avellaneda & Lee: "Sharpe 1.44 IS 1997–2007, degraded to 0.9 post-2002" | QUALIFY | cit#10 | "…backtest Sharpe 1.44 over 1997-2007, 0.9 after 2002…" (drop "IS"). |
| P-038 | PAPER.md:355-358 | Elliott et al.: "Gaussian Markov chain spread model; Bayesian optimal stopping" | WITHDRAW | cit#46 (MISATTRIBUTED) | "…mean-reverting Gaussian Markov chain observed in noise, calibrated by Kalman filter/EM; trades set by comparing model predictions with observations." |
| P-039 | PAPER.md:359-364 | Krauss (2017) five families incl. "ML-based" | QUALIFY | cit#11 | "…and other approaches (including ML)." |
| P-040 | PAPER.md:365-375 | Do & Faff (2010): 0.86%→0.24%/month; "explicitly testing and rejecting capital-crowding" | UNVERIFIED | cit#47 | Keep the downward-trend statement (abstract-confirmed); mark the figures and the crowding claim as to be checked against the full text. Add that the abstract reports strong performance in prolonged turbulence. |
| P-041 | PAPER.md:375-380 | "§7.11 replicates this test directly on CAMARF's own confirmed pairs … no decay found … mean half-life fell" | WITHDRAW | B2, B3, B4, B11 (era Sharpes), D3/D4 (1h) | "§7.11 attempted a replication on pre-WRDS hourly pairs; its Sharpe comparison used the invalid P&L accounting and is withdrawn." |
| P-042 | PAPER.md:381-390 | LTCM/Quant Quake/Quant Bust parallel; Khandani & Lo; Kakushadze "other quant categories unaffected or profitable" | UNVERIFIED | cit#48, #49 | Keep the Khandani-Lo parallel with a year/venue; drop "while other quant strategy categories were unaffected or profitable" until checked. |
| P-043 | PAPER.md:390-393 | "§7.12 tests CAMARF's own confirmed pairs against … GFC, COVID" | QUALIFY | R5.5-R5.7, H-10 | Add "(see §7.12 for the scope and the control-window caveats)". |
| P-044 | PAPER.md:397-405 | Krauss, Do & Huck ~0.45%/day raw; CAMARF uses XGBoost as meta-labeler on the cointegration z-score | QUALIFY | cit#50; CR-2, CR-3 | "…CAMARF's ml.py meta-labels z-score crossing events (|z| = 1.5), which are not the strategy's own entries (|z| ≥ 3.0); meta-labeling the strategy's own trades is reported in §7.10." |
| P-045 | PAPER.md:406-412 | AFML: "ml.py is a direct implementation: EG z-score = primary signal, XGBoost = meta-labeler"; conformal predictors novel | QUALIFY | CR-2, CR-3, R2.3 (ml.py still splits positionally; purged CV = AFML Ch. 7 not implemented in ml.py) | "…ml.py follows the meta-labeling architecture on z-score crossing events; purged/embargoed CV (AFML Ch. 7) is implemented in the comparison script, not yet in ml.py." Conformal: see P-060. |
| P-046 | PAPER.md:413-425 | Bailey & López de Prado (2014); "52 trials as of the current registry" | QUALIFY | R2.1, cit#51 | Keep the description; "52 trials" → "the trial registry (whose merged copy was found double-counted, 1,150 records / 570 unique; §6.7)". Name "False Strategy Theorem" as López de Prado's later term (cit#51). |
| P-047 | PAPER.md:426-437 | Harvey, Liu & Zhu t > 3.0; "factor zoo" | QUALIFY | cit#53 | Attribute "factor zoo" to Cochrane (2011) or drop the quotation marks. |
| P-048 | PAPER.md:438-443 | Engle (2002) DCC; "2026-06-29 result: peak correlation > 0.70 = 0 pairs" | WITHDRAW | internal (§6.4 at PAPER.md:1225-1233 reports 13 of 210), B2-B4 (P&L streams) | Drop the result sentence; keep the method description. |
| P-049 | PAPER.md:444-455 | White (2000) Reality Check; "IS p = 0.559, OOS p = 0.546" | WITHDRAW | S5 (CONFIRMED), cit#55, P-11 | "CAMARF's §6.6 test is a circular block bootstrap (Politis & Romano, 1992) of the daily P&L; it is not White's Reality Check (no benchmark, no best-of-N, no demeaning), and because the null is not demeaned its p-value is ≈0.5 regardless of skill. No p-value from it is reported." |
| P-050 | PAPER.md:461 (table) | GGR row "~11% ann. excess return" | QUALIFY | cit#9 | "up to 11%" |
| P-051 | PAPER.md:462 (table) | DFH row "Cointegration + OU outperforms distance risk-adjusted" | UNVERIFIED | cit#45 | "State-space stochastic spread model" in Key Result until verified. |
| P-052 | PAPER.md:463 (table) | A&L row "ETF Sharpe 1.1 (1997-2007)" | STANDS | cit#10 | no change |
| P-053 | PAPER.md:464 (table) | Elliott row "Bayesian optimal stopping … Theoretically optimal stopping rule" | WITHDRAW | cit#46 | Method: "Gaussian Markov chain spread observed in noise; Kalman/EM calibration". Key result: "Model-based entry/exit". |
| P-054 | PAPER.md:465-470 (table) | Krauss, Clegg/Krauss, Gregory/Hansen, KDH, LdP, Engle rows | QUALIFY | cit#11, #50; P-044/P-045 | LdP row CAMARF-difference: "meta-labeling on z-crossing events; conformal calibration prototype" (drop "direct implementation"). Others no change. |
| P-055 | PAPER.md:471 (table) | White row "Correct p-value under multiple testing … IS p=0.559; OOS p=0.546" | WITHDRAW | S5, cit#55 | Remove the row, or: "Method: best-of-N bootstrap vs benchmark. CAMARF: circular block bootstrap of one P&L series (not a Reality Check); no valid p-value reported." |
| P-056 | PAPER.md:477-482 | "CAMARF scans 14 timeframes (1m-1M) simultaneously across 1,500+ instruments … EG + KPSS + PO … No found paper does this" | QUALIFY | internal (§3 says 13 TFs; 8h removed), N-1, S6 | "…scans up to 13 timeframes (1m-6M) across a merged universe of ~44,700 symbols (daily research scripts) …" Keep the novelty claim as "no paper found in our search". |
| P-057 | PAPER.md:484-496 | Contribution 2: durability-vs-currency not documented in any found paper; companion hypothesis refuted | QUALIFY | R6.3 | Keep the first sentence; "…was tested by Monte Carlo and not supported (pending re-run with the production test on WRDS data)…" |
| P-058 | PAPER.md:498-505 | Contribution 3: meta-labeling with conformal calibration; "training data is insufficient" | QUALIFY | CR-2, CR-3 | "…Training data is now sufficient (74,732 events); a purged comparison gives AUC ≈ 0.61 for z-convergence, but meta-labeling the strategy's own trades on dollar profitability gives AUC 0.47-0.54 (§7.10). Conformal coverage has not been re-derived on the new data." |
| P-059 | PAPER.md:507-511 | Contribution 4: stack includes "(e) White's permutation test … with honest power reporting" | WITHDRAW | S5, cit#55 | "(e) a circular block bootstrap of portfolio P&L (not White's Reality Check; see §6.6)". |
| P-060 | PAPER.md:518-519 | "ML evidence is preliminary (40 labeled examples, 5 in minority class)" | REPLACE | CR-2, CR-3 | "ML evidence: purged AUC 0.6067 (XGBoost) / 0.6085 (RF) for z-convergence on 74,732 events; no ranking power for the dollar profitability of the strategy's own trades (AUC 0.47-0.54)." |
| P-061 | PAPER.md:520-521 | "No papers found applying EVT/GPD specifically to pairs trading spread tails" | STANDS | — | no change |

### PAPER.md §3 Data and Universe

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-062 | PAPER.md:529-537 | "3-pair WRDS-static-screen set … ZERO overlap with a genuinely PIT-safe re-screen"; "182-pair PIT-safe episodic-confirmed universe" | WITHDRAW | S3, A1, N-5 | "…the 3-pair static-screen set (produced while A1 prevented EG on pairs with unequal start dates) has no overlap with the episodically-confirmed pool, now 1,375 pairs (rebuilt 2026-09-14), which is not point-in-time at the pair level (S3)." |
| P-063 | PAPER.md:537-538 | Pointer to "`CLAUDE.md`'s 'Current canonical data footprint' section" | WITHDRAW | S-5 (section does not exist) | Replace with a data-range block in this paper (rule 7): IS/OOS calendar ranges, universe snapshot, cache end dates. |
| P-064 | PAPER.md:544-546 | "1,730 symbols … 1,660 assets passed" (2026-08-03 run) | QUALIFY | N-2 | Prefix "As of the 2026-08-03 run (superseded; the standing research universe is ~44,700 symbols)". |
| P-065 | PAPER.md:546-551 | WRDS primary: "CRSP (total-return-adjusted) … Compustat Global (split-only-adjusted, disclosed) as fallback" | QUALIFY | U4 (CONFIRMED: `universe_loader` reads price-only `close`), R1.1 (CONFIRMED: local currency, no FX), R1.4 | "…CRSP (the episodic discovery scan reads total-return closes; `universe_loader` and the traded spreads use price-only closes) and Compustat Global (split-adjusted, in local currency, with no FX conversion — 498 of 929 confirmed pairs in the 2026-09-02 scan have such a leg)…" |
| P-066 | PAPER.md:553-557 | "International equities and everything intraday remain yfinance-sourced; forex intraday remains IBKR" | QUALIFY | V-3, CLAUDE.md rule 2 contradiction | State one consistent source table (yfinance intraday primary; IBKR supplemental intraday for confirmed pairs; forex daily from yfinance, restored 2026-09-27). |
| P-067 | PAPER.md:559-563 | 2026-08-03 run: 3 confirmed pairs (KVUE/KMB@3m, PNC/ZION@4h, IQV/Q@1D) with tiers | QUALIFY | A1, D1 (3m), D3/D4 (4h), S6 | Add: "(produced before the A1 and D1/D3/D4 fixes; to be re-run)". |
| P-068 | PAPER.md:563-571 | Reduction 26 → 3 "is not evidence of a data-quality regression … it reflects that WRDS-primary sourcing changes the underlying … price series" | WITHDRAW | A1 (CONFIRMED; CODE_REVIEW: "plausibly explains the standard screen confirming only 3 pairs"; latest standard run confirmed 0 pairs at 1D) | "The cause of the reduction is not established: a defect confirmed 2026-09-26 (A1) silently skipped EG for every pair whose legs start on different dates in `analysis.py`'s main path. A1 is fixed; the screen must be re-run before the reduction is attributed to sourcing." |
| P-069 | PAPER.md:573-592 | Prior pre-WRDS snapshots: 1,691 assets, 13 TFs; 1,608 symbols (hash 0c0e67a6); 26 pairs (24@1h, 1@3m, 1@1M) | QUALIFY | A1 (offset intraday arrays misalign silently), D1, D3/D4 | Add: "(historical; produced by code with the since-fixed alignment, liquidity-filter and snapping defects)". |
| P-070 | PAPER.md:594-603 | Binance.US: 2,460 overlapping days, median 0.075% difference; USDT switch | STANDS | — | no change |
| P-071 | PAPER.md:605-613 | Corporate-actions spot-check: 4 splits smooth (max return < 6%) | STANDS | (U4 concerns dividend treatment, not splits) | no change |

### PAPER.md §4 Methodology

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-072 | PAPER.md:617-624 | §4.1 pipeline overview | QUALIFY | CR-7 (A1 fix, BH denominator) | Append: "Since 2026-09-27 each timeframe's aligned frames are reindexed onto a common timestamp index before EG (A1 fix), and tests that crash are kept in BH's denominator with p=1." |
| P-073 | PAPER.md:628-631 | Re-run on "CRSP total-return-adjusted daily closes … reusing `analysis.py`'s own production `_eg_worker` unmodified" | STANDS | P-18; `_eg_worker` untouched by 8bb2bf0a | no change |
| P-074 | PAPER.md:634-640 | Table: XOM/CVX, JPM/BAC, KO/PEP, NTRS/STT, SHW/UNP p-values and n | STANDS | P-18 | no change |
| P-075 | PAPER.md:642-651 | NTRS/STT "passes … overwhelming significance … failing the identical test on just the last five years"; "nothing in a full-sample test can distinguish" | QUALIFY | R8.12 (UNVERIFIED: 5y test has ~10× fewer observations) | Add: "The recent-window test has far less power (≈1,260 vs 13,373 observations), so its non-rejection is weaker evidence of a break than the full-sample rejection is of cointegration; a same-length rolling comparison (§4.3) addresses this." |
| P-076 | PAPER.md:653-671 | SHW/UNP does not replicate (0.061 / 0.054); adjustment-convention sensitivity; negative controls | STANDS | — | no change |
| P-077 | PAPER.md:671-677 | coint_fraction_rolling is a secondary filter on pairs that already pass the full-sample screen | STANDS | — | no change |
| P-078 | PAPER.md:679-693 | §4.2.1 flagged pre-WRDS, "historically informative, not current evidence" | STANDS | — | Add "and the harness uses a one-direction EG call (R6.3)". |
| P-079 | PAPER.md:701-706 | Rejection table: 1D 2 of 122,082 (0.0016%, "~3,000x below chance"); 1M 9 of 34,263 | WITHDRAW | A1 (CONFIRMED), S2 (failed tests excluded from m) | Delete the table until re-derived on the A1-fixed code; if kept: "(counts from code that silently failed EG on pairs with unequal start dates; not interpretable)". |
| P-080 | PAPER.md:708-712 | Initial "over-conservative test" reading was never validated | STANDS | — | no change |
| P-081 | PAPER.md:714-715 | MC harness "runs the production EG-test code itself" | WITHDRAW | R6.3 (CONFIRMED: single one-direction `coint`, no max over directions, no gap-respecting segment) | "…runs a one-direction Engle-Granger test (statsmodels `coint(a, b)`), not the production two-direction call…" |
| P-082 | PAPER.md:716-721 | 400 null pairs per TF, re-paired real series; synthetic check ~5-6% | QUALIFY | R6.4 (UNVERIFIED: no calendar alignment; yfinance cache) | Add: "Null pairs use each series' last n bars without calendar alignment, sampled from the ~1,500-symbol yfinance cache." |
| P-083 | PAPER.md:723-733 | FP rates 7.75% / 7.75% / 9.00% / 12.75% with Clopper-Pearson CIs | QUALIFY | R6.3 (one-direction test overstates the production Type-I rate) | Keep the numbers, labelled "one-direction EG, pre-WRDS". |
| P-084 | PAPER.md:734-742 | Mechanism is "ordinary spurious regression … quantified directly against this project's own production test code" | WITHDRAW | R6.3 | "…a plausible mechanism is shared drift (Granger & Newbold, 1974); quantified against a one-direction variant of the test, not the production call." |
| P-085 | PAPER.md:742-746 | "Corrected conclusion: the full-sample screen's near-total rejection rate … reflects the test correctly guarding" | WITHDRAW | A1, R6.3 | Same text as P-013. |
| P-086 | PAPER.md:746-755 | Actionable failure mode is §4.2's; reported as refuted rather than dropped | QUALIFY | R6.3, A1 | "…reported as not supported (pending re-run), rather than dropped." |
| P-087 | PAPER.md:759-764 | coint_fraction_rolling = fraction of 252-bar windows with EG p < 0.05; MIN_COINT_FRAC = 0.70 | STANDS | N-16 (config.py:509 = 0.70); A6/S10 (UNVERIFIED: NaN fraction may pass) | no change (note A6/S10 in §8 once verified). |
| P-088 | PAPER.md:768-772 | Override: kept if HL trend ≤ 0 and neither ZA nor CUSUM detects a break | QUALIFY | A5 (UNVERIFIED: ZA/CUSUM return None on short series, read as "no break"), A8 (UNVERIFIED) | Add: "(pending a check that a test which fails to run is not read as 'no break')". |
| P-089 | PAPER.md:775-788 | Worked example: D/NEE, SPY/VOO excluded; FANG/OXY@1m kept (0.27, −0.617) | QUALIFY | D1 (1m yfinance bars were ~entirely NaN-and-forward-filled for mid-caps) | Add: "(1-minute data from the pre-fix cache; illustrative until re-run on a re-fetched intraday cache)". |
| P-090 | PAPER.md:792-801 | Calendar-padding mechanism | STANDS | — | no change |
| P-091 | PAPER.md:803-812 | Exact artifact (n−1)/√n = 15.8115 at n=252; 4 of 32 examples |z|>10 at market open | STANDS | — | no change |
| P-092 | PAPER.md:814-829 | Generalizes; candidate explanation for other published fat tails (flagged as hypothesis) | STANDS | — | no change |
| P-093 | PAPER.md:831-836 | Fix: compacted real-bars-only sub-series, scatter back | QUALIFY | B1 (no DATA_GAP flag survives into persisted spreads), D1, D5 (UNVERIFIED) | Add: "The fix depends on gaps being flagged; the 2026-09-26 audit found gaps were forward-filled at cache time and flagged NONE (D1, now removed), so this protection was largely inactive until the caches are re-fetched." |
| P-094 | PAPER.md:840-862 | Decoupled-window negative result; CRWD/DDOG mean −1.50, std 7.13, 12.3% |z|>10; re-verified on 3 pairs | QUALIFY | D1 (1m/3m/1h yfinance data) | Keep the mechanism argument; label the numbers "pre-D1-fix intraday data". |
| P-095 | PAPER.md:864-895 | Correlation is a pre-filter; nine industry pairs, corr 0.49-0.63, EG p 0.06-0.89 | STANDS | — (conceptual; numbers not affected by a confirmed finding) | no change |
| P-096 | PAPER.md:897-906 | Honest methodological note on the misalignment bug | STANDS | — | no change |
| P-097 | PAPER.md:908-915 | "that section [§4.2] is about cointegration testing being too STRICT at long horizons (false negatives: real relationships rejected)" | WITHDRAW | internal (§4.2 and §4.2.1 reframe away from "too strict"), A1 | "…§4.2 is about a full-sample test answering 'ever cointegrated' rather than 'cointegrated now'; this section is about correlation being too loose…" |

### PAPER.md §5 Empirical Findings (pre-WRDS)

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-098 | PAPER.md:917-954 | Reconciliation notices; "§7.20 is the paper's actual current empirical reality … a real, robust, negative result" | WITHDRAW | S3, B2-B4, P-1 | Last paragraph → "§7.20-§7.21 report the current, partially re-derived result (dollar P&L); read them for the bottom line." |
| P-099 | PAPER.md:956-965 | 23 pairs across 5 TFs (2026-06-30) | QUALIFY | A1, D1, D3/D4 | "(historical; pre-fix alignment and intraday cache)". |
| P-100 | PAPER.md:967-973 | All 17 @1h pass via the override; "the intended functioning of the two-stage design" | QUALIFY | A5 (UNVERIFIED), BUG-D68 (95.6% of PIT pairs passed only via the override) | "…all 17 pass only via the override; whether the override's break tests actually ran on these series is unverified (A5)." |
| P-101 | PAPER.md:975-977 | Tiering: 13 gold, 9 silver, 0 bronze of 22 | QUALIFY | internal (§6.1 at PAPER.md:1145-1146 quotes the old result as 17 gold/8 silver), S6 | Reconcile the two figures; label S6 (PO proxy critical values) as open. |
| P-102 | PAPER.md:979-984 | Price-degeneracy filter active; zero effect at 1h | STANDS | — | no change |
| P-103 | PAPER.md:986-990 | SPY/VOO trivial pair flag | STANDS | — | no change |
| P-104 | PAPER.md:992-998 | APAM/INVX, AZTA/INVX 2-7 distinct closes on liquid names; "independently corroborated against IBKR … real market data, not a fetch defect" | WITHDRAW | D1 (CONFIRMED: per-bar $1M threshold NaN'd and forward-filled almost all 1m bars of mid-caps; CODE_REVIEW:372-379 names `audit_price_degeneracy.py` as flagging this symptom) | "…showed only 2-7 distinct 1-minute closes. A cache-time liquidity filter found 2026-09-26 (D1) produces exactly this symptom; whether IBKR's copy was independent of that filter has not been re-checked, so this is not currently established as real market data." |
| P-105 | PAPER.md:999-1014 | Step 6d structurally drops price-degenerate pairs | STANDS | — | no change (method exists; its trigger is now suspect, see P-106) |
| P-106 | PAPER.md:1016-1024 | Universe-wide: 432 of 1,354 1m symbols (31.9%) flagged; 2m 24.6%, 3m 30.4%, 5m 10.0%; 10 of 12 confirmed 1m pairs | QUALIFY | D1 | Keep the counts, labelled "measured on the pre-D1-fix yfinance intraday cache; the D1 filter fabricates repeated closes at exactly these frequencies". |
| P-107 | PAPER.md:1026-1043 | "Root cause characterized": market cap dominant (median $3.0B vs $17.3B, MWU p=1.82e-145, quintile dose-response 88.5% → 0.0%) | WITHDRAW | D1 (a per-bar dollar-volume threshold mechanically NaNs more bars for smaller-cap names, producing the same monotone cap gradient) | "The flagged rate falls monotonically with market cap (88.5% → 0.0% by quintile). This gradient is also what the since-removed per-bar liquidity filter (D1) would produce, so it cannot currently be attributed to market microstructure; re-measure after re-fetching the intraday cache." |
| P-108 | PAPER.md:1045-1062 | Sector an independent second factor (REIT/Fin/Util 38.6% vs 8.1% within the middle cap quintile) | WITHDRAW | D1 | Same treatment as P-107 ("…not currently attributable…"). |
| P-109 | PAPER.md:1064-1079 | "real, well-characterized, citable finding … this paper's third pillar … daily dollar-volume liquidity screening silently admits ~32%…" | WITHDRAW | D1 | "A candidate third finding, currently suspended: the symptom coincides with a confirmed cache-time defect (D1) and must be re-measured on a re-fetched intraday cache before it can be reported." |
| P-110 | PAPER.md:1081-1097 | Visibility-only predictive gate `_predict_degeneracy_risk` live; price-density screen kept as comparison arm | QUALIFY | D1 | Add: "(the gate's model was fit to D1-affected labels; to be refit after re-fetch)". |

### PAPER.md §6 Statistical Validation

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-111 | PAPER.md:1101-1106 | Six-section stack "to corroborate or challenge the backtest results" | STANDS | — | no change |
| P-112 | PAPER.md:1108-1125 | STALE notice: 29 → 17 pairs; §6.2 cache-path gap fixed; not re-run | QUALIFY | A1 (the 17-/29-pair manifest came from an A1-era screen), CR-7 | Add: "…and the manifest itself predates the A1 fix, so it must be regenerated before §6.1-§6.3 are re-run." |
| P-113 | PAPER.md:1129-1133 | Three-test tiering definition incl. "PO Z_t (PP test on EG residuals)" | QUALIFY | S6 (UNVERIFIED: univariate DF critical values; reviewer sim 25.7% rejection at nominal 10%) | Add: "(PO approximated by Phillips-Perron with univariate critical values; this inflates confirmations — S6, being checked)". |
| P-114 | PAPER.md:1135-1143 | 29-pair result: 0 gold, 2 silver, 27 bronze, 2 conflicts | QUALIFY | P-112, S6 | Label as "2026-09-10, superseded manifest, pre-A1 screen". |
| P-115 | PAPER.md:1145-1160 | "real, disclosed reversal … not a data-quality regression"; daily-noise mechanism "plausible" | QUALIFY | A1, internal (17 gold/8 silver here vs 13/9 in §5) | "…not directly comparable; whether the shift reflects sourcing, A1, or both is not established." |
| P-116 | PAPER.md:1164-1167 | Five hedge estimators (OLS/TLS/Kalman/Huber/MM) | STANDS | — | no change |
| P-117 | PAPER.md:1169-1189 | Cache-path gap found; KVUE/KMB, PNC/ZION max 1.70% divergence; not replicated | QUALIFY | stale (gap fixed 2026-09-12/13, per PAPER.md:1115-1118) | "The cache-path gap was fixed 2026-09-12/13; the comparison has not been re-run." |
| P-118 | PAPER.md:1196-1204 | Only 12 of 29 pairs trade; 290 trades; "IS Sharpe 0.2389" | WITHDRAW | B2, B3, B4, B11/P1 (Sharpe); CR-5 (trade counts dominated by immediate stop-outs) | "…only 12 of 29 pairs generate any trade (290 trades; Sharpe not reported — computed with the invalid P&L accounting)." |
| P-119 | PAPER.md:1204-1215 | Only KVUE/KMB and PNC/ZION have enough exceedances; both fat-tailed | QUALIFY | D1 (3m), D3/D4 (4h), B2-B3 (tail of P&L-derived losses) | Label "3m/4h pre-fix intraday caches; GPD on spread losses, not dollar P&L". |
| P-120 | PAPER.md:1219-1223 | DCC method (manual two-step) | STANDS | — | no change |
| P-121 | PAPER.md:1225-1235 | 210 pair-pairs fitted; 13 with peak ρ > 0.70 on pair P&L streams | WITHDRAW | B2, B3, B4 (the P&L streams) | "Not reported: the P&L streams were built with the invalid accounting." |
| P-122 | PAPER.md:1239-1248 | MC: GARCH AIC 476 vs 11,222; "Sharpe remains positive at 0-20 bps slippage: strategy is not sensitive to transaction costs" | WITHDRAW | B2, B3 (cost in dollars vs gross in log units — slippage was mis-scaled), S9/S13 (UNVERIFIED) | Delete the results; keep the four-phase description as method. |
| P-123 | PAPER.md:1251-1268 | Trade-shuffle permutation destroyed cross-pair exit-timing correlation; synthetic 4.59 vs 9.71 | STANDS | — (the diagnosis of the old test's defect is correct) | no change |
| P-124 | PAPER.md:1270-1277 | Fix: circular block bootstrap "correctly centers the null near the realized statistic (4.59 vs 4.71, p=0.51)" | WITHDRAW | S5 (CONFIRMED), H-3 | "…replaced by a circular block bootstrap of daily P&L. Because the resampled series is not demeaned, the null is centred on the realized Sharpe and p ≈ 0.5 by construction; the synthetic 4.59 vs 4.71 result shows this defect, not a correct fix. A valid test must demean the series (or use White's best-of-N form over the trial registry)." |
| P-125 | PAPER.md:1285-1290 | OOS p=0.546 (Sharpe 5.2155), IS p=0.559 (5.8044) | WITHDRAW | S5, B2-B4 | Delete. |
| P-126 | PAPER.md:1292-1301 | "a fair comparison … holdout not yet long enough … not that the strategy lacks edge" | WITHDRAW | S5, CR-1 | Delete. |
| P-127 | PAPER.md:1301-1309 | "positive per-pair total P&L and win rates (60-84%) … argue for real per-pair skill … win rate and total P&L, unaffected by the bug, carry this claim" | WITHDRAW | B2 (CONFIRMED: win rate 21.2% → 45.6% and 49% of trade signs flip when the hedge is held at entry), P-12 | Delete. |
| P-128 | PAPER.md:1313-1321 | STORM survey challenge; False Strategy Theorem | QUALIFY | cit#51 | Credit the theorem's name to López de Prado's later work. |
| P-129 | PAPER.md:1323-1329 | deflated_sharpe.py builds per-period Sharpe from daily closed-trade P&L | QUALIFY | B11/P1 (calendar-day resample fixed to business days in 85e766fb), S11, S12 (UNVERIFIED) | Method text: "…from the business-day P&L series (calendar-day weekends removed 2026-09-27)…" |
| P-130 | PAPER.md:1331-1347 | N=52; IS z=9.52, OOS z=2.90; "does not explain away the headline result" | WITHDRAW | B2-B4, B11, P-13 | "DSR values computed before 2026-09-26 are withdrawn: the Sharpes they deflate were produced by invalid accounting." |
| P-131 | PAPER.md:1348-1352 | DSR vs pair-selection lookahead distinction | STANDS | — | no change |
| P-132 | PAPER.md:1354-1358 | Units bug caught (annualized vs per-period variance) | STANDS | — | no change |
| P-133 | PAPER.md:1362-1370 | Historical CVaR rationale; "skew 2.4–2.9, kurtosis 14.2–14.3" | QUALIFY | internal (§6.7 reports skew 0.916 / −0.834, kurtosis 12.1 / 14.6) | Remove the skew/kurtosis cross-reference. |
| P-134 | PAPER.md:1372-1386 | VaR/CVaR table ($489.27 … $1,198.80); "IS and OOS tail-loss magnitudes consistent" | WITHDRAW | B3 (dollar figures are log-units × shares minus dollar costs), B2, B4 | Delete the table; keep "risk measurement, not a limit". |
| P-135 | PAPER.md:1388-1399 | Kupiec/Christoffersen: "CAMARF's historical VaR is well-calibrated" | WITHDRAW | B2, B3 | "The exceedance tests are implemented (`cvar.py`) and will be re-run on dollar P&L." |

### PAPER.md §7.1-§7.9 (pre-WRDS Layer 1 results)

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-136 | PAPER.md:1403-1405 | "this chapter demonstrates the methodology … has practical teeth. The strategy is the empirical proof" | WITHDRAW | B2-B4, CR-1 | "…this chapter records the strategy results; those before §7.20 used invalid P&L accounting and are provenance only." |
| P-137 | PAPER.md:1418-1420 | Layer 1: "enter when |z_rolling| ≥ 2.0σ, exit … 0.0, stop at 3.5σ, max hold 2× half-life" | QUALIFY | config.py:742 (ENTRY_ZSCORE = 3.0 since 2026-08-17), CR-5 | "…entry at |z| ≥ 2.0 for the runs in §7.1-§7.19 (3.0 since 2026-08-17, used in §7.20-§7.22), no upper bound on entry |z| (so 54-68% of current entries are at or past the 3.5 stop), stop on |z| ≥ 3.5 regardless of direction…" |
| P-138 | PAPER.md:1419-1422 | "Fixed leg sizing, both OLS and Kalman … in parallel … All hedge ratios are point-in-time causal series … no hedge-ratio lookahead bias" | WITHDRAW | B2 (P&L re-marks the spread with each bar's β), B4 (OLS/Kalman duplicates pooled), A2 (warm-up bars use full-sample β; 0.02% of trades) | "…OLS and Kalman runs are reported separately (they were pooled as independent trades before 2026-09-26). The hedge ratio used for signals is causal except on warm-up bars (A2); the legacy P&L re-marked each position with the current bar's β, which a held position does not earn (B2)." |
| P-139 | PAPER.md:1424-1427 | 26 pairs; SPY/VOO excluded by `_is_index_tracking_pair` | STANDS | — | no change |
| P-140 | PAPER.md:1429-1440 | IS 2168 trades Sharpe 5.8044; OOS 449 trades Sharpe 5.2155; max concentration 19.9%; win rates 18.2%-100% | WITHDRAW | B2, B3, B4, B11, D3/D4 | Delete numbers (provenance note only). |
| P-141 | PAPER.md:1442-1447 | IS/OOS degradation 0.9% "a primary empirical finding"; Gatev "substantial OOS decay" | WITHDRAW | B2-B4, cit#9 (GGR measure time decay, not IS/OOS) | Delete. |
| P-142 | PAPER.md:1451-1462 | DD hub 5 of 17 @1h pairs; zero OOS trades; TMHC/WAL 9.97% of OOS P&L ($7,332) | QUALIFY | B2-B4 (P&L shares) | Keep the structural DD-hub count; drop the P&L figures. |
| P-143 | PAPER.md:1464-1473 | Six-variant concentration table (Sharpe 5.02-5.87, P&L) | WITHDRAW | B2-B4, B5 (P&L-cap lookahead with --hedge both), B14 (hub weights ignore --pairs-override) | Delete. |
| P-144 | PAPER.md:1477-1481 | "Risk-parity is the recommended default for production" | WITHDRAW | B2-B4 | Delete. |
| P-145 | PAPER.md:1483-1495 | Neg-hedge, P&L-cap "no effect", hub-weight findings | WITHDRAW | B2-B4, B5, B14 | Delete. |
| P-146 | PAPER.md:1497-1505 | HRP 5.3752 < risk-parity 5.8689; "should not be adopted, at least not on this evidence"; DeMiguel et al. | WITHDRAW | B2-B4 | "HRP vs risk-parity will be re-compared on dollar P&L." |
| P-147 | PAPER.md:1507-1513 | Absorption Ratio mean 0.427 (0.205-0.847), 39 symbols, k=8 | STANDS | cit#30 (add reference entry) | no change |
| P-148 | PAPER.md:1515-1525 | Ledoit-Wolf arm uninformative (clipping); "Ledoit & Wolf 2004, via `sklearn.covariance.ledoit_wolf`" | QUALIFY | cit#23 (MISATTRIBUTED: sklearn implements the JMVA 2004 estimator) | Cite Ledoit & Wolf (2004), *J. Multivariate Analysis* 88(2), 365-411. |
| P-149 | PAPER.md:1527-1537 | DD-hub effective bets: ρ̄=0.282, BR_eff 2.35, ENB 1.14, IDM 1.53 (z-score-delta correlations) | QUALIFY | cit#20 (GK breadth formula source), R7.12 (UNVERIFIED: signed ρ̄ averaging) | Keep; name the formula "equicorrelation effective breadth" unless the Grinold-Kahn source is confirmed. |
| P-150 | PAPER.md:1539-1560 | Portfolio-wide: pair daily P&L, ρ̄=0.0039, BR_eff 19.5/21, ENB 9.78, IDM 4.41 | WITHDRAW | B2-B4 (the P&L series), P1 | "Re-derive on dollar P&L." |
| P-151 | PAPER.md:1562-1564 | Recommended production configuration: --risk-parity, --neg-hedge | WITHDRAW | B2-B4 | Delete. |
| P-152 | PAPER.md:1566-1575 | Five-way complexity pattern ("four lose, one wins") | WITHDRAW | B2-B4, B3 (see M-071), R5.2 | "Pending re-derivation; four of the five comparisons were scored on invalid P&L." |
| P-153 | PAPER.md:1579-1587 | Semi-WFA definition (fixed pair set; OU params re-estimated) | STANDS | — | no change |
| P-154 | PAPER.md:1589-1598 | WFA table (mm_exec 3.816/3.964 … cfrac_sizing) | WITHDRAW | B2-B4, B11 | Delete. |
| P-155 | PAPER.md:1600-1604 | "each fold is a strict chronological sub-sample with zero lookahead"; IS/WFA ratio 1.69 "modest overfitting" | WITHDRAW | D3/D4 (1h/4h timestamp lookahead up to 90 min in the cache), A2, B2 | "…each fold is chronological; the hourly cache carried a timestamp-snapping lookahead (fixed 2026-09-27, caches not yet regenerated)." Drop the ratio. |
| P-156 | PAPER.md:1606-1610 | mm_exec trade inflation "not a bug" (ladder fills) | UNVERIFIED | — | Keep as "not investigated since". |

### PAPER.md §7.3.1 Point-in-time walk-forward (1h)

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-157 | PAPER.md:1614-1618 | Run 2026-08-03, "universe 1,576 symbols with cached 1h data", window [2023-07-13, 2026-07-31] | STANDS | — | no change (this is the correct label; PAPER_MAGNITUDE mislabels it, M-010) |
| P-158 | PAPER.md:1619-1624 | Fold table: 0/2/0/1 PIT pairs; −1.0121 (32 trades); +0.2547 (5 trades) | WITHDRAW | S1/A1 (the fold screen used `align_universe` without a common index; fixed 8bb2bf0a), B2-B4, D3/D4, D1 | "Pending re-run on the A1-fixed screen with dollar P&L; the 2026-08-03 pair counts and Sharpes came from code with an EG alignment defect and invalid P&L accounting." |
| P-159 | PAPER.md:1626-1638 | "core finding … still holds directionally"; bit-for-bit reproduction of −1.0121 confirms "that number was already real"; 1,576 confirms BUG-D105 fix | WITHDRAW | same as P-158 | Delete "already real" and "still holds"; keep the BUG-D105 universe-size note. |
| P-160 | PAPER.md:1643-1647 | Why a PIT test is needed (semi-WFA cannot detect selection lookahead) | STANDS | — | no change |
| P-161 | PAPER.md:1649-1655 | Method: full screening re-run using only data up to each cutoff | QUALIFY | S1/A1 (fixed), S4, S14 (UNVERIFIED: override leaves train+test hedge ratios; no embargo), BUG-D68 | Add: "(the override path and the hedge-ratio fallback are being checked for post-cutoff information — S4)". |
| P-162 | PAPER.md:1657-1664 | Synthetic verification of pit_wfa (with the spurious-regression fixture correction) | STANDS | — | no change |
| P-163 | PAPER.md:1666-1677 | Original result: zero overlap at 3 checkpoints; −1.0432/−0.7873/−1.0432/−0.7176 | WITHDRAW | BUG-D68 (BL:85; not re-tested), B2-B4, M-2 | Delete (provenance note only). |
| P-164 | PAPER.md:1679-1686 | Alignment-mode bug flipped every fold from positive to negative | QUALIFY | B2-B4 (both before and after numbers on invalid P&L) | Keep as a bug-history note without Sharpe values. |
| P-165 | PAPER.md:1688-1694 | "Decisive check … screening function is trustworthy" (16 of 17 reproduced) | WITHDRAW | A1/S1 (CONFIRMED later on the same function's alignment path) | "A reproduction check recovered 16 of 17 known pairs on the full window; a later audit found the same function could not EG-test pairs whose legs start on different dates (A1/S1), so the check did not establish that the function was trustworthy at earlier cutoffs." |
| P-166 | PAPER.md:1696-1708 | "strong evidence of pair-selection lookahead"; "the 5.24 OOS Sharpe is real for the pair set as given, well short of being explained away" | WITHDRAW | B2-B4, S1, BUG-D68 | "…the hypothesis of pair-selection lookahead is untested until the re-run; no Sharpe from this period is cited." |

### PAPER.md §7.4-§7.9

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-167 | PAPER.md:1715-1724 | STORM factor definitions (session_edge, garch_stop, mm_exec, coint_frac_threshold) | STANDS | — | no change |
| P-168 | PAPER.md:1726-1767 | Variant table and findings (session_edge −0.04, coint_frac_sizing 5.46 "low-denominator artifact", mm_exec +0.002) | WITHDRAW | B2-B4 | Delete numbers; keep "garch_stop never triggered on the 5-pair set" as a code-path observation. |
| P-169 | PAPER.md:1771-1802 | coint_frac vs OOS P&L table (TMHC/WAL $7,332 etc.) | WITHDRAW | B2-B4 | Delete P&L column. |
| P-170 | PAPER.md:1804-1812 | "noisy but directionally informative signal" | WITHDRAW | B2-B4 | Delete. |
| P-171 | PAPER.md:1814-1841 | Low-power hypothesis for 252-bar windows, flagged unverified | STANDS | — | no change |
| P-172 | PAPER.md:1843-1853 | coint_frac should not be used as a multiplier "in either direction" | QUALIFY | B2-B4 | "…no evidence either way (the comparisons used invalid P&L)." |
| P-173 | PAPER.md:1857-1880 | S7 method: AR(1) on half_life_rolling + Zivot-Andrews | QUALIFY | S8 (UNVERIFIED: AR(1) on an overlapping, forward-filled rolling series gives ρ≈1 by construction), S7 (FIXED 002d7070) | Add: "(the break index was read from the wrong tuple position until 2026-09-27; the AR(1) on an overlapping rolling series is not inferential)". |
| P-174 | PAPER.md:1884-1888 | 20/23 pass; "September 2023 break-date clustering … most common break date" | WITHDRAW | S7 (CONFIRMED: `hl_za_breakdate` was the lag count's position) | Delete the break-date sentence; keep "20/23 reject a unit root (ZA p < 0.10)" with the S8 caveat. |
| P-175 | PAPER.md:1890-1894 | AR(1) ρ 0.95-0.97; "ZA confirms no unit root for 20/23" | QUALIFY | S8 | As P-173. |
| P-176 | PAPER.md:1898-1913 | GGR protocol description | STANDS | cit#9 | no change |
| P-177 | PAPER.md:1915-1925 | Window-mismatch bug found and closed (≤ 5 days residual) | STANDS | — | no change |
| P-178 | PAPER.md:1932-1949 | Cointegration pooled OOS Sharpe 8.542 "the trustworthy number"; distance 16 trades, CI 26-86; direction "supported … consistent with Do, Faff & Hamza" | WITHDRAW | B2-B4, cit#45 | "Not reported: the cointegration side used invalid P&L; the distance side had 16 trades." |
| P-179 | PAPER.md:1953-1976 | Entry × exit grid (Sharpe 7.36-10.59); "No parameter choice delivers a negative Sharpe, confirming genuine strategy robustness"; "production setting (entry = 2.0)" | WITHDRAW | B2-B4, B6, config.py:742 | Delete. |
| P-180 | PAPER.md:1978-1991 | ADV sweep; $25M "Pareto-optimal" | WITHDRAW | B2-B4, A14 (UNVERIFIED: full-history ADV) | Delete Sharpes; keep pair counts per threshold. |
| P-181 | PAPER.md:1993-2005 | HL ceiling sweep; 12.42 on 16 trades | WITHDRAW | B2-B4 | Delete Sharpes. |
| P-182 | PAPER.md:2007-2023 | Bertram MC: optimum entry 0.75-1.25; PNC/ZION at grid ceiling via §7.13's grid-bootstrap CI | QUALIFY | R7.14 (UNVERIFIED), R6.5 (the cross-reference is a grid-edge artifact) | Drop the PNC/ZION cross-reference; keep "directional check with a placeholder cost". |
| P-183 | PAPER.md:2030-2048 | Risk-parity +0.63 OOS; "recommended production sizing method" | WITHDRAW | B2-B4 | Delete. |
| P-184 | PAPER.md:2050-2068 | z=1.5 vs 2.0 table; "Retain z=2.0 as production default" | WITHDRAW | B2-B4, config.py:742 (now 3.0) | Delete; state the current default (3.0) and that entry-z sweeps are pending on dollar P&L. |

### PAPER.md §7.10 Layer 2 ML

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-185 | PAPER.md:2072-2084 | P(converge) ≥ 0.60 gate; training "cannot proceed" as of 2026-06-30 | QUALIFY | stale; CR-2 | Mark as historical ("as of 2026-06-30"). |
| P-186 | PAPER.md:2086-2097 | RMT feature redundancy on 24 examples; "ml.py's own 8-feature set" | QUALIFY | ml.py:711-724 (12 features now, incl. 2 TE and 2 squeeze/momentum) | "…the then 8-feature set (now 12; the purged comparison uses 10, excluding the TE features)…" |
| P-187 | PAPER.md:2099-2106 | 74,732 events, 1,301 pairs; "chronological 60/20/20 split"; accuracy 54.49% vs 58.98% baseline; "AUC-ROC … 0.6075" | REPLACE | R2.3, R4.10; CR-2 | "…74,732 labeled events across 1,301 pairs. Under a purged, 1%-embargoed chronological split with the transfer-entropy features removed (they are computed over each pair's full history, R4.10), test AUC is 0.6085 for a random forest [90% CI 0.6001-0.6164] and 0.6067 for XGBoost [0.5983-0.6153] (0.6062 without purging, so label overlap did not inflate it)." |
| P-188 | PAPER.md:2107-2108 | "The model has real, if modest, ranking power" | REPLACE | CR-2, CR-3 | "The model has modest ranking power for z-convergence after a 1.5 crossing; tree ensembles and an MLP are statistically tied (LightGBM 0.6024, MLP 0.6033), while SVM (0.5744), KNN (0.5709) and logistic regression (0.557) are significantly worse, so the signal is in nonlinear interactions." |
| P-189 | PAPER.md:2108-2113 | LSTM AUC 0.5897, attention 0.5516; sequence models do not beat XGBoost | QUALIFY | R2.3 (CONFIRMED in `lstm_attention_training.py`: no purging), R2.9, R2.11 (UNVERIFIED) | "…(positional split, not purged; not re-derived)…" |
| P-190 | PAPER.md:2113-2116 | Youden recalibration "53.45% vs 54.49%" does not help | REPLACE | Group 1 #3 (FIXED); CR-2 | "…balanced accuracy 57.64% at the Youden threshold vs 57.72% at 0.5: recalibration does not help." |
| P-191 | PAPER.md:2116-2120 | "real, non-trivial predictive signal … not yet shown to make the capital-constrained strategy more profitable" | REPLACE | CR-3 | "…The z-convergence signal does not transfer to the strategy's own trades: meta-labeling those trades on dollar profitability gives AUC 0.47-0.54 across 24 (gate, model) trials, and capital-sim Sharpe changes of −0.19 to +0.59 in both directions — consistent with noise (OLS, 1D, USD-only trades)." |

### PAPER.md §7.11-§7.13

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-192 | PAPER.md:2130-2144 | Filter funnel @1h: 1,162,050 → 70,251 → 314 → 17; spread_series gap fixed | QUALIFY | A1 (EG+BH stage), D1/D3/D4 | "(1h, 2026-06-30, pre-A1-fix; counts to be re-derived)". |
| P-193 | PAPER.md:2146-2152 | Counterfactual: excluded pairs IS 4.3526 / OOS 3.6682; "The filter is net-positive" | WITHDRAW | B2-B4 | Delete. |
| P-194 | PAPER.md:2154-2160 | Do & Faff description; crowding side untestable | QUALIFY | cit#47 | As P-040. |
| P-195 | PAPER.md:2162-2169 | Era Sharpes 5.05 → 5.18 → 5.21; half-life 38.6 → 39.7 → 31.0; "no decay" | WITHDRAW | B2-B4 (Sharpes); D3/D4 (half-lives on 1h cache) | Keep only the half-life sequence labelled "pre-fix 1h cache"; delete the Sharpe sequence and the "no decay" conclusion. |
| P-196 | PAPER.md:2173-2183 | Stress-test scope: daily resolution, 2-year pre-crisis baseline, no intraday replay | STANDS | — | no change |
| P-197 | PAPER.md:2185-2190 | Calm controls "were run through the identical test before drawing any conclusion" | QUALIFY | H-10, R5.6 (UNVERIFIED: controls added after the first run; 2018-02→04 follows the Feb-2018 VIX spike) | "…three calm controls, chosen after the first crisis run (2015-08, 2016-09→2017-03, 2018-02→04, the last following the February 2018 volatility spike)…" |
| P-198 | PAPER.md:2192-2201 | Dislocation 62% (29/47) vs 20% (11/55), "a 3× rate difference, supporting a genuine … crisis-specific effect" | QUALIFY | R5.5, R5.7 (UNVERIFIED: no test, non-independent pair-windows) | "…29/47 vs 11/55 pair-window tests (not independent; no significance test)…" and drop "supporting a genuine". |
| P-199 | PAPER.md:2203-2210 | Interpretation scoped: not a claim the strategy would lose in 2007/2008/2020 | STANDS | — | no change |
| P-200 | PAPER.md:2214-2218 | Six diagnostics synthetically verified | STANDS | — | no change |
| P-201 | PAPER.md:2220-2227 | Threshold cointegration: 1 of 22 nominally significant; "the linear model already in production is adequate" | QUALIFY | R6.7, R6.8 (UNVERIFIED: one-sided threshold, not a symmetric band) | "…no pair shows a one-sided threshold effect after BH; a symmetric-band (transaction-cost) specification has not been tested." |
| P-202 | PAPER.md:2229-2235 | Variance ratio: VR < 1 at 2-4× HL (0.35-0.52); "Strong, independent confirmation" | QUALIFY | R6.12 (UNVERIFIED: q/n bias, no joint test), R6.8 | "…consistent with mean reversion (individual VR tests, no Chow-Denning joint test; the pairs were selected by EG on the same series, so this is not independent confirmation)." |
| P-203 | PAPER.md:2237-2242 | News impact: clean null; "`garch_stop`'s symmetric design is validated" | WITHDRAW | R8.1 (CONFIRMED), cit#24 | "Withdrawn: 'narrowing' was coded as dz_{t−1} < 0 rather than sign(dz) = −sign(z), which pulls the ratio to 1 by construction." |
| P-204 | PAPER.md:2244-2249 | AFML Ch. 15: CVX/OXY, KVUE/KMB win rates 42.9%, 43.8%; edge "must rest on payoff asymmetry" | WITHDRAW | B2 (win rates move 21% → 46% under fixed-entry β), R5.3 (CONFIRMED: OLS+Kalman duplicates double the frequency) | "Re-derive per hedge method on dollar P&L." |
| P-205 | PAPER.md:2251-2258 | Reimers: 0/502 trios flip; 2/502 trace vs max-eig disagree | QUALIFY | R8.8 (UNVERIFIED), cit#25 | "…0/502 flip, which is guaranteed at these sample sizes (correction factor ≈ 0.997), so this is not evidence of robustness." |
| P-206 | PAPER.md:2260-2267 | Grid bootstrap: coverage 14/15; "Every confirmed pair's CI sits comfortably below 1"; PNC/ZION [0.9990, 0.9990] | WITHDRAW | R6.5 (CONFIRMED: grid capped at ±0.999 and ρ̂±0.15, so the set can never contain 1), cit#26 | "Withdrawn until the grid can include values ≥ 1; as implemented the upper bound cannot exceed 0.999." |
| P-207 | PAPER.md:2269-2273 | Return smoothing: 9 of 10 near 1.0; EG/WRB 0.711 | WITHDRAW | B2, B3 (daily P&L), R7.13 (UNVERIFIED: irregular exit-date series) | "Re-run on dollar, business-day P&L." |
| P-208 | PAPER.md:2275-2282 | Fill timing: lagged variant marginally better (26.96 vs 26.47); "same-bar convention is not inflating reported performance" | WITHDRAW | B9 (KNOWN; study computed on B2/B3 P&L), CR-5 | "Re-run on dollar P&L; the same-bar fill remains a known open bias." |
| P-209 | PAPER.md:2284-2289 | Jumps: 1-2% of bars carry ~72-76% of delta variance (AMD/DD@1h 76.2% / 71.8%) | QUALIFY | D1, D3/D4 (1h cache) | Label "pre-fix 1h cache". Fix the cross-reference ("§6.8: 19/26 pairs fat-tailed" — §6.8 is CVaR; §6.3 reports a different count). |
| P-210 | PAPER.md:2290-2293 | Win rate near jumps 65.8% / $274.69 vs 63.6% / $304.69; "doesn't meaningfully hurt" | WITHDRAW | B2, B3 | Delete. |

### PAPER.md §7.14 Backlog clear-out

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-211 | PAPER.md:2300-2303 | Weak exogeneity: 14/20 symbol_a leads | QUALIFY | A11 (UNVERIFIED: Johansen across gaps) | Label "pre-WRDS, 20-pair set". |
| P-212 | PAPER.md:2305-2307 | Turbulence index: 15,381 days; 90th pct 57.70 | QUALIFY | R7.9, R7.10 (UNVERIFIED: fillna(0), full-sample threshold) | Add "(returns zero-filled across gaps; full-sample threshold — descriptive only)". |
| P-213 | PAPER.md:2309-2312 | CAViaR $354.64-$966.47 vs static $732.38: "real time-varying risk that a constant VaR misses" | WITHDRAW | cit#31, R7.6 (UNVERIFIED), B3 (dollar units) | "A CAViaR model was fitted; its adequacy (DQ test) was not tested and it was fit on the invalid P&L; no conclusion drawn." |
| P-214 | PAPER.md:2314-2316 | QRF "predicting continuous z_future rather than ml.py's 4-class label"; 13 examples | QUALIFY | S-6 (LABEL_SCHEME = "binary", config.py:602), R4.4 (CONFIRMED: coverage in-sample only) | "…rather than ml.py's binary label…; coverage was evaluated in-sample only." |
| P-215 | PAPER.md:2318-2320 | Graphical lasso inconclusive (silhouette 0.055) | STANDS | — | no change |
| P-216 | PAPER.md:2322-2326 | MSE: entropy 0.21 → 0.79 "rising toward the white-noise level", every pair "simple/regular" | WITHDRAW | R8.4 (CONFIRMED), cit#34 | "…per-scale-renormalized sample entropy (not Costa et al.'s MSE, which fixes r from the original series); the white-noise interpretation does not apply." |
| P-217 | PAPER.md:2328-2335 | Bias budget: "DSR says the OOS Sharpe is likely genuine (z=2.90)"; permutation p=0.546; 10.2% gap; holdout examined 29 times | WITHDRAW | B2-B4, S5, B11, P-32 | Keep only "holdout examined 29 times across 14 labels". |
| P-218 | PAPER.md:2337-2340 | Convex portfolio: max-Sharpe +0.08-0.09; max-Sortino +3.27 | WITHDRAW | B2-B4 | Delete. |
| P-219 | PAPER.md:2342-2346 | Carver forecast scaling: 5.40 vs 5.32 vs 5.29; $216K vs $151K | WITHDRAW | B2-B4 | Delete numbers; keep that the flags exist. |
| P-220 | PAPER.md:2348-2351 | Inverse-cluster-size wins (0.7216 vs 0.7154, ERC 0.6933) | WITHDRAW | R5.2 (CONFIRMED: cluster labels use test-window correlation), B2-B4 | Delete. |
| P-221 | PAPER.md:2353-2357 | Network momentum: +0.036 vs −0.010; "a genuine +0.046 incremental edge"; "the paper's full graph neural network" | WITHDRAW | R8.3 (CONFIRMED: signal and target share r_j[t+1]), cit#37 | "A simplified lead-lag spillover signal built from full-sample correlations of r_i[t] with r_j[t+1] correlates with r_j[t+1] by construction (+0.036); no edge is claimed. (Pu et al. use a linear graph-learning model, not a GNN.)" |
| P-222 | PAPER.md:2359-2362 | Short-term factor: reversal corr 0.018; "day-of-week seasonality negligible (0.004) … consistent with the literature's own characterization" | WITHDRAW | cit#38 (MISATTRIBUTED: Blitz et al.'s seasonality is monthly), R8.6 (UNVERIFIED: Monday dummy tests Tuesday) | "…reversal corr 0.018 (full-sample z-scoring, R8.7); a weekday dummy (possibly shifted, R8.6) shows corr 0.004. Day-of-week tests follow French (1980), not Blitz et al." |
| P-223 | PAPER.md:2364-2372 | options.py: RV as IV proxy; BS verified; put/call overlay raises max DD ($5,946.56 vs $2,106.82) | QUALIFY | B2, B3 (the unhedged drawdown is on the invalid P&L) | Keep the capability and the "premium exceeded payoff; 5.6% of trades had any payoff" observation; drop the drawdown comparison. |

### PAPER.md §7.15-§7.19

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-224 | PAPER.md:2381-2384 | 7267.T/8058.T@1M: full-sample p=0.0001 vs 5y p=0.19 | STANDS | — | no change |
| P-225 | PAPER.md:2385-2387 | PairCharacteristicsAnalyzer: 6/24 holdout-confirmed, exploratory | STANDS | — | no change |
| P-226 | PAPER.md:2388-2390 | Regime gate: trending + widening entries underperform | QUALIFY | B2-B4 | "…(performance measured on invalid P&L; re-derive)". |
| P-227 | PAPER.md:2391-2392 | Earnings blackout: −16.3% trades, 5.30 vs 5.40, −48% max DD | WITHDRAW | B2-B4 | Keep the trade-count change only. |
| P-228 | PAPER.md:2393-2394 | ML Stage 2 blocked by data volume | QUALIFY | stale (74,732 events) | "Stage 2 was blocked as of 2026-07-11; not re-run on the 74,732-event set." |
| P-229 | PAPER.md:2395-2398 | Price-degeneracy "durable" (31.4%/23.5%/23.4%) | QUALIFY | D1 | Same caveat as P-106. |
| P-230 | PAPER.md:2406-2418 | Capsim convention mismatch; "the other (behind every headline Sharpe) zero-fills them"; residual effect via chronological admission | QUALIFY | P1 (both conventions superseded: business-day zero-fill since 85e766fb), B2-B4 | "…both tools now use a business-day series; the size of the residual admission effect must be re-derived on dollar P&L." |
| P-231 | PAPER.md:2419-2430 | Fresh-holdout conventions; combined-split Sharpe 13.32 on 28 trades | QUALIFY | B2-B4 | Keep the convention discussion; drop the Sharpe. |
| P-232 | PAPER.md:2431-2444 | Cross-session lead-lag null; Tokyo→ADR one-day lead | STANDS | — | no change |
| P-233 | PAPER.md:2445-2454 | Window × threshold grid: no advantage, zero generalization gap (24 pairs) | STANDS | — | no change |
| P-234 | PAPER.md:2466-2467 | Cycle detection null | STANDS | — | no change |
| P-235 | PAPER.md:2468-2472 | Lévy jumps "0% overlap with GapFlag-flagged bars … robust across alpha" | QUALIFY | see M-064 (verified by code this scrutiny: `levy_jump_diffusion.py:160-167` drops DATA_GAP-masked bars via `_clean_close` before the overlap is computed, and missing `gap_flag` defaults to all-NONE); B1, D1 | "…0% overlap between detected jumps and the non-NONE GapFlag bars that remain after DATA_GAP bars are masked out; because gaps were largely forward-filled and flagged NONE at cache time (D1, B1), this comparison could not have found overlap and is not evidence that the two systems measure different things." |
| P-236 | PAPER.md:2473-2476 | Rough volatility: mixed, window-dependent | STANDS | — | no change |
| P-237 | PAPER.md:2477-2480 | Options Greeks: significant but likely a price-level confound | STANDS | — | no change |
| P-238 | PAPER.md:2481-2483 | SVM meta-labeler blocked (19 examples) | QUALIFY | stale; CR-2 (RBF-SVM 0.5744 in the purged comparison) | "…superseded by the purged comparison (RBF-SVM AUC 0.5744)." |
| P-239 | PAPER.md:2484-2489 | Inverse polarity: 2 candidates, neither cointegrated (1,697 assets, 1.4M pairs) | QUALIFY | D1 (yfinance cache), A1 (EG on unequal-start pairs) | Add "(yfinance cache pre-D1-fix; EG pre-A1-fix)". |
| P-240 | PAPER.md:2490-2494 | Trig-identity design error caught | STANDS | — | no change |
| P-241 | PAPER.md:2496-2504 | PIT-safety gap: all seven arms source from the full-history set | STANDS | — | no change |
| P-242 | PAPER.md:2506-2514 | `episodic_bhfdr_confirm_asof` "causal-safe … a real, previously-flagged design gap now closed" | WITHDRAW | S3 (CONFIRMED: `episodic_pairs_adapter.main()` never passes `as_of_date`) | "…built and verified, but the adapter that produced the Purity pool never passes an as-of date, so the gap was not closed in practice (S3)." |
| P-243 | PAPER.md:2516-2522 | Research-layer sensitivity: 12 arms; 34 of 46 unswept | STANDS | — | no change |
| P-244 | PAPER.md:2534-2554 | Greeks verified; RND extractor; yfinance IV unreliable deep-ITM; SPY ~47% more near-term vol | QUALIFY | R7.8, R8.13 (UNVERIFIED) | Rename "backtest-overfitting detector" to "risk-neutral vs realized distribution comparison" (it computes no PBO). |
| P-245 | PAPER.md:2556-2567 | Beta hedging makes every metric WORSE (Sharpe 6.0581 → 0.5019) | WITHDRAW | R7.3 (CONFIRMED: unhedged P&L booked at exit vs daily-MTM hedge), B2-B4 | "Withdrawn: the comparison set exit-booked unhedged P&L against a daily marked-to-market hedge, which lowers the hedged Sharpe by construction." |
| P-246 | PAPER.md:2569-2581 | Confidence score: filtering worse (6.06 → 1.14); reversion-speed category dominant (−0.20) | WITHDRAW | R7.1 (CONFIRMED: ~25% of the score is a constant full-history lookahead), R7.2, B2-B4 | "The score included a lookahead component (R7.1) and was evaluated on invalid P&L; no conclusion is drawn." |
| P-247 | PAPER.md:2582-2586 | `load_price_series` never read WRDS; fixed | STANDS | — | no change |
| P-248 | PAPER.md:2596-2609 | Sequential bootstrap design: per-pair overlap; duration-weighting bug fixed | QUALIFY | R4.6 (UNVERIFIED: uniqueness vs all n labels, not drawn set) | Add: "(the 'full sequential bootstrap' arm may reduce to uniqueness-weighted resampling — R4.6, being checked)". |
| P-249 | PAPER.md:2611-2615 | 237 examples unblocked by syncing spread files | STANDS | — | no change |
| P-250 | PAPER.md:2615-2621 | Average uniqueness 0.457; effective n ~65 of 142; 10 seeds 47.9-72.9%, mean 59.4%, +3.1pp | QUALIFY | R4.6, R4.7 (UNVERIFIED: seed hardcoded to 42 — not reproducible from the script), R2.3 | Keep 0.457; mark the seed range as "not reproducible from the committed script" until R4.7 is resolved. |
| P-251 | PAPER.md:2623-2634 | TE method; off-by-one bug caught | STANDS | — | no change |
| P-252 | PAPER.md:2636-2642 | AMP/RUSHA RUSHA→AMP lag 3, TE 0.0101 bits, "permutation p=0.000" | QUALIFY | R4.9, R4.8 (UNVERIFIED) | "…p < 1/(N+1) (the script's p-value omits the +1 correction and the minimum over 10 tests is unadjusted)". |

### PAPER.md §7.20-§7.22 (current headline sections)

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-253 | PAPER.md:2650-2657 | §7.17's gap is closed here; backtest "extensively cross-validated at the time" | WITHDRAW | S3, B2-B4 | "…This section attempts to close that gap; the 2026-08-14 backtest behind it was later found to rest on defective P&L accounting and a pair set assembled with post-cutoff windows." |
| P-254 | PAPER.md:2659-2665 | "made genuinely point-in-time-safe … gated so that no window's confirmation can see data from after its own as-of date" | QUALIFY | S3, P-2 | "Each window's confirmation uses only data inside that window (point-in-time per window); the pair set, however, is the union of all windows confirmed up to the build date, and the backtest then trades those pairs over their full history, including the holdout. A rebuild with an explicit as-of cutoff is pending." |
| P-255 | PAPER.md:2663-2669 | 182-pair set (170/6/6); Purity/Hybrid/Tiered/Baseline arms | QUALIFY | N-5 | Mark "superseded by the 1,375-pair rebuild". |
| P-256 | PAPER.md:2671-2679 | Capital-constrained table: Purity −0.679/−0.834, Hybrid −0.442/−1.125, Tiered = Baseline +1.417/+0.630 | WITHDRAW | B2, B3, B4, P1, S3, B10 (liquidity bar filter blocks WRDS symbols if used) | Delete the table. |
| P-257 | PAPER.md:2681-2689 | Tiered = Baseline because all 3 standard pairs share one tier; "Both [PIT arms] are negative, both in-sample and out-of-sample" | WITHDRAW | B2-B4, S3 | Keep the one-tier degeneracy explanation; delete the conclusion. |
| P-258 | PAPER.md:2691-2708 | Parameter sweep: every OOS cell negative (−1.150 to −0.179); IS entry-z max +0.146; "loses under essentially every parameterization" | WITHDRAW | B2-B4, P1, R2.2, B6 | "The parameter sweep will be re-run on dollar P&L; its earlier values are withdrawn." |
| P-259 | PAPER.md:2710-2719 | "What this does and does not show … loses money … changes whether you'd trade at all" | REPLACE | CR-1, CR-5, S3 | "On dollar P&L with the hedge fixed at entry (OLS trades with USD-only legs, ~31% of trades; unconstrained), every gate variant loses in-sample (net −0.354 to −0.408, gross −0.191 to −0.248; gross still negative, −0.119 to −0.219, after excluding immediate stop-outs), and out-of-sample the momentum gate loses (−0.296) while squeeze and combined are ≈ 0 (−0.078, −0.005). This is consistent with the strategy not making money on this pool, but it does not yet isolate discovery as the cause: 54-68% of entries open at or past the stop and are stopped next bar (an entry-rule design defect, CR-5), 69% of trades are not yet valued, and the pool is not point-in-time at the pair level (S3)." |
| P-260 | PAPER.md:2721-2725 | Files and "Full account" pointers | STANDS | — | no change |
| P-261 | PAPER.md:2727-2738 | Superseded note: 2,211 of 6,844 PERMNO aliases (32%); 7,834,906 candidates; 1,382 → 1,375 pairs | STANDS | N-8 (the 1,382 run is the 09-14 run; 929 is the 09-02 run) | no change |
| P-262 | PAPER.md:2732-2738 | "same Tier-3-only, causally point-in-time-safe methodology throughout" | WITHDRAW | S3 | "…same Tier-3-only episodic methodology (per-window point-in-time; pair set not point-in-time — S3)…" |
| P-263 | PAPER.md:2738-2743 | "a scale correction, not a methodology change — the causal-validity argument this section makes is unaffected"; −0.218 / −0.7584 current authoritative | WITHDRAW | S3, B2-B4, P1 | "…a scale correction. The unconstrained (−0.218) and capital-constrained (−0.7584) Purity Sharpes quoted from §7.21 are withdrawn (invalid accounting)." |
| P-264 | PAPER.md:2746-2751 | §7.21 title: "Validated with the Project's Strongest Statistical Evidence to Date" | WITHDRAW | B2-B4, CR-1 | Title → "Squeeze/Momentum Entry Confirmation: a Found Methodology Gap, and What the Corrected Accounting Shows". |
| P-265 | PAPER.md:2753-2758 | Entry gate was purely |z| ≥ ENTRY; squeeze/RSI computed but never reached entry logic or ml.py | STANDS | CR-5 (gates now execute as coded, 0 violations over 47,628 decisions) | Add: "A rule-invariant audit confirms the three gates execute exactly as coded." |
| P-266 | PAPER.md:2760-2763 | "All 3 flip the unconstrained Sharpe from −0.218 to +0.35/+0.39/+0.43 (IS) and +0.45/+0.24/+0.50 (OOS) — real, out-of-sample-confirmed" | REPLACE | B2, B3, B4; CR-1 | "On the corrected dollar accounting (OLS, USD-only legs, business-day, unconstrained), none of the gates is profitable: in-sample net Sharpe is −0.408 (momentum), −0.386 (squeeze), −0.354 (combined); out-of-sample −0.296, −0.078, −0.005. On the same trades the old accounting gave +0.132/+0.474/+0.721 IS and −0.184/+0.667/+0.601 OOS: the positive values were produced by rolling-hedge drift and unit mixing." |
| P-267 | PAPER.md:2763-2766 | Random-subsample control: "all 3 gates' real Sharpe landed at the 100th percentile, p≈0.0000 — the strongest statistical confirmation this project has produced" | WITHDRAW | B2 (the drift term was the whole of the sampled positive P&L), CR-4 (iid same-size null misspecified: entries overdispersed, NB r ≈ 1.05) | "The random-subsample control was run on the old P&L and against an iid same-size null that ignores the overdispersion of entries; it is withdrawn." |
| P-268 | PAPER.md:2767-2770 | Capital-constrained metric doesn't track; next steps | QUALIFY | CR-3 (dollar-mode capital replay exists), CR-6 | "The capital-constrained replay now exists in dollar mode (`portfolio_sim.replay_portfolio(pnl_mode='dollar')`) but has not yet been run on the gate arms." |
| P-269 | PAPER.md:2778-2786 | (1) Luck check: taken −0.27 vs skipped +0.40, 0.7th percentile; key-collision bug fixed | WITHDRAW | B2-B4, R2.7 (UNVERIFIED: Sharpe comparison favours the larger set), R2.6, CR-4, CR-6 | "Withdrawn: computed on the old P&L; the re-run after the admission-lookahead fix (taken_better_than_skipped False in all 6 cases) is also on the old P&L, and the iid same-size null is misspecified for overdispersed entries (CR-4). A constraint-respecting null is pending." |
| P-270 | PAPER.md:2786-2795 | (2) Hierarchical DSR: 20 families; squeeze/momentum family DSR 0.9676 (z=1.85) at n=39 vs pooled 0.0000 (z=−37.94) | WITHDRAW | R2.1 (CONFIRMED: 1,150 records, 570 unique), B2-B4, R2.4, R2.5 | "Withdrawn: the trial registry was double-merged and every Sharpe in it is on the invalid accounting." |
| P-271 | PAPER.md:2796-2799 | "this says the gate's unconstrained trade-selection edge is statistically real" | WITHDRAW | CR-1 (the unconstrained edge is negative on dollar P&L) | Delete. |
| P-272 | PAPER.md:2799-2807 | (3) Tier 2 grid: every Sharpe negative; 4 of 5 zero-effect constants gated behind a flag; `corr_exit_window` dead config; "once genuinely active, the correlation-exit mechanism makes results dramatically WORSE" | QUALIFY | B2-B4 (Sharpes), R2.2 (KNOWN + CONFIRMED dead-config family still counted), CR-5 (`corr_exit` never fires at default settings: needs |z| > 2|entry_z| after the 3.5 stop) | Keep the sweep-script bug history; replace the result clause with: "The grid's Sharpes are on the invalid accounting and are withdrawn; at default settings the correlation exit is structurally unable to fire (it requires |z| > 6 and is checked after the 3.5 stop)." |
| P-273 | PAPER.md:2811-2814 | α=0.01 pool: 598 pairs "down from 1,375 … a real, substantial 61% shrinkage" | REPLACE | N-9 (arithmetic) | "…598 pairs, down from 1,375 (a 56.5% reduction; 598/1,375 = 43.5% retained)…" |
| P-274 | PAPER.md:2814-2818 | Unconstrained −0.203 vs −0.218; capsim −1.4682 vs −0.7584; "ruling out 'too many marginal pairs'" | WITHDRAW | B2-B4, P1 | Delete the Sharpes and the conclusion. |
| P-275 | PAPER.md:2820-2828 | Quality-ranked admission beats FIFO 6/6; "rank candidate trades within each day"; "a real, repeatable effect" | WITHDRAW | Group 1 #1-#2 (FIXED lookahead: within-day re-ranking let later trades take capital before it existed), CR-6, H-6 | "Withdrawn: within-day ranking introduced a lookahead (fixed 2026-09-26: re-ranking now only among identical entry times). After the fix, momentum IS fell 0.2337 → 0.1499 and combined IS 0.1000 → 0.0357, still on the old P&L; the ranking direction had been chosen after testing both." |

### PAPER.md §8 Bias Documentation

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-276 | PAPER.md:2832-2838 | BiasAuditLog, 62 entries, incl. "survivorship from current-constituent-only universe" | QUALIFY | H-17 | Replace the survivorship phrase with one accurate statement of what the PIT path uses (WRDS incl. delisted CRSP names for S&P 500 history; current constituents for S&P 400/600; no delisting consumer — DEV-001). |
| P-277 | PAPER.md:2840-2854 | Label-overlap bias "(12-32 labeled examples to date)"; sequential bootstrap "not-yet-built remedy" | REPLACE | stale; CR-2 (purging measured: 0.6062 → 0.6067) | "…74,732 labeled events. Purging with a 1% embargo changes XGBoost's test AUC from 0.6062 to 0.6067, so label overlap does not inflate the AUC measurably; ml.py itself still splits positionally (R2.3 open). Sequential bootstrap was built as a comparison arm (§7.19)." |
| P-278 | PAPER.md:2856-2873 | Pair-selection lookahead: "26 as of the current headline run"; PIT re-screen "lost money in every backtested fold (Sharpe −1.04 to −0.72)" | WITHDRAW | BUG-D68, B2-B4, S1 | "…quantified by a point-in-time re-screen that is being re-run (the earlier fold results rest on an override-dominated screen, defective P&L and an EG alignment defect)." |
| P-279 | PAPER.md:2873-2877 | "the paper's headline 5.24 OOS Sharpe is a real, correctly computed number conditional on the pair set" | WITHDRAW | B2-B4, B11, P-15, N-7 | Delete. |

### PAPER.md §9 AI-Tool Disclosure

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-280 | PAPER.md:2881-2894 | AI used throughout; disclosure as evidence of catching incorrect output | STANDS | — | no change |
| P-281 | PAPER.md:2896-2963 | Five worked examples of caught errors | STANDS | — | Consider adding a sixth: the 2026-09-26 audit (a verify fixture that asserted a lookahead as correct; P&L accounting defects that survived months of "cross-checks"). |
| P-282 | PAPER.md:2979-2982 | "~28 sessions (June-July 2026) … this session ran on Claude Sonnet 5" | QUALIFY | stale | "Model versions varied across the project (June-September 2026); record the model per session in Development.md." |
| P-283 | PAPER.md:2984-2995 | Conceptualization/methodology not AI-led; every technique approved before implementation | STANDS | — | no change |
| P-284 | PAPER.md:2997-3001 | Information collection: web search this session (2026-07-11) is "the clearest example" | QUALIFY | internal (PAPER.md:1313 cites a 2026-06-30 STORM literature survey) | State the STORM surveys and the 2026-09-26 Crossref/OpenAlex citation checks explicitly. |
| P-285 | PAPER.md:3003-3008 | Data collection: "every real data-fetching run (yfinance, and … IBKR)"; AI never selected a data source | QUALIFY | WRDS omitted | Add WRDS/CRSP/Compustat/IBES and Binance.US to the list. |
| P-286 | PAPER.md:3031-3034 | "every new analytical method was tested against a synthetic ground-truth case … before being trusted on real data" | QUALIFY | Group 1 #1 (the Case N fixture asserted the lookahead as correct), R3.1, R6.2, R6.5 | "…was paired with a synthetic test; the 2026-09-26 audit found several such tests encoded the defect they were meant to catch, so a passing verify script is necessary, not sufficient." |
| P-287 | PAPER.md:3070-3077 | "Every quantitative result in this paper traces to a specific script and a specific run date" | QUALIFY | H-16, V-16 | "…is intended to trace…; the 2026-09-26 audit found headline claims without IS/OOS ranges, hedge method, entry/stop z or pool snapshot, which are being added." |
| P-288 | PAPER.md:3108-3113 | "`Development.md`, now exceeding 10,000 lines across 28 sessions" | REPLACE | `wc -l Development.md` = 28,572 | "…now exceeding 28,000 lines…" (session count to be re-counted). |
| P-289 | PAPER.md:3130-3138 | No multi-agent orchestration through 2026-07-12 | UNVERIFIED | — | Keep only if confirmed from session logs. |
| P-290 | PAPER.md:3152-3154 | "No comparison arm or figure in this paper rests on an unverified subagent report: every one was independently re-run or diffed" | UNVERIFIED | — | "…was intended to be…"; cite the verification record per arm or drop. |
| P-291 | PAPER.md:3158-3167 | Web search "used exactly once … never to source … any … literature-review citation" | QUALIFY | internal (PAPER.md:320, 1313: STORM literature surveys informed §2) | Re-state after checking whether the STORM surveys used web search; if so, list them. |
| P-292 | PAPER.md:3171-3184 | Data sources: yfinance "primary", IBKR, FRED, CFTC; "No paid data vendor" | WITHDRAW | WRDS is a paid institutional subscription (PAPER_MAGNITUDE.md:1703-1704 says so); S-5 | "…Real data sources: WRDS (CRSP, Compustat Global, IBES) via Baruch's institutional subscription — primary for daily-and-coarser US equities/ETFs and all headline results; yfinance (intraday, international, crypto, forex); IBKR (supplemental intraday); Binance.US; FRED; CFTC." |
| P-293 | PAPER.md:3176-3178 | Documented in "CLAUDE.md's 'Data Test Range & Reproducibility' section" | WITHDRAW | S-5 (section does not exist) | Point to a data-range appendix in this paper. |

### PAPER.md §10 Future Work

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-294 | PAPER.md:3196-3200 | "Large pieces still to come: … stats.py … backtest.py, report.py" | QUALIFY | stale | Replace with the current open list: GVKEY FX conversion, Purity rebuild with as-of cutoff, capital-sim on dollar P&L, intraday cache re-fetch, churn-loop comparison arms. |
| P-295 | PAPER.md:3208-3218 | Sequential bootstrap DONE: +3.1pp, 2/10 seeds worse | QUALIFY | R4.6, R4.7 | As P-250. |
| P-296 | PAPER.md:3219-3232 | TE "wired into ml.py as a genuine feature" | WITHDRAW | R4.10 (CONFIRMED: full-history, pair-level TE attached to every event; still in ml.py:720-721) | "…wired into ml.py; it is computed over each pair's full history and therefore leaks future information into every event. It is excluded from the purged comparison and should be made causal or removed from ml.py." |
| P-297 | PAPER.md:3234-3256 | Price-target overlay: 1,191/1,340 trades; Welch t=−0.33, p=0.74 | QUALIFY | R8.9, R8.10 (UNVERIFIED: entry-day close used for 09:30 entries; TR vs price targets), B2 (trade P&L) | "…a null on the old P&L; the overlay may read the entry day's close for intraday entries (R8.9), being checked." |
| P-298 | PAPER.md:3228 (Da & Schaumburg framing) | Brav & Lehavy; Da & Schaumburg "STANDALONE single-name signal" | UNVERIFIED | cit#61 | Check whether Da & Schaumburg is a within-industry relative design before contrasting. |
| P-299 | PAPER.md:3262-3268 | Louvain clustering recovers oil & gas cluster | STANDS | — | no change |
| P-300 | PAPER.md:3269-3273 | Tail dependence: CCL/NCLH@3m λ_U≈0.5 vs λ_L≈0.32 | QUALIFY | D1 (3m cache) | Label "pre-D1-fix 3m cache". |
| P-301 | PAPER.md:3274-3286 | Conformal: 125 events, 68% accuracy, 88% coverage | QUALIFY | stale; CR-2 | Label "2026-06-27, 125 events; not re-derived on 74,732 events". |
| P-302 | PAPER.md:3287-3304 | Permutation check: 38 of 79 flagged; null_frac 0.230 vs 0.05 | QUALIFY | A1 (79-pair set from the A1-era screen), D1 | Label "historical, pre-fix". |
| P-303 | PAPER.md:3305-3310 | MIDAS math verified, deferred | STANDS | — | no change |
| P-304 | PAPER.md:3311-3361 | Box-Tiao / CCP variants: OOS advantage −0.466; OLS 3.698 vs 4.130/3.821/4.199 | STANDS | — (predictability ratios, not P&L) | no change |
| P-305 | PAPER.md:3363-3368 | LinAlgError on HRMY, PRDO…; "~32% of the 1m universe" | QUALIFY | D1 | Same caveat as P-106. |
| P-306 | PAPER.md:3370-3379 | HMM regimes: durations 539-621 days; crisis 23.6% of history | QUALIFY | M9, M11 (UNVERIFIED: vintage/lag issues in FRED/VIX inputs) | Label "latest-vintage macro series". |
| P-307 | PAPER.md:3381-3389 | Sample entropy 1h range 0.024-0.378 | QUALIFY | D1, D3/D4 | Label "pre-fix 1h cache". |
| P-308 | PAPER.md:3391-3412 | Regime-conditional hl_ratio table; "the clearest empirical support yet for the thesis's regime-conditioning hypothesis" | WITHDRAW | D1, D3/D4 (1h); own caveats (1m/3m single regime; crisis n 30-40 bars; raw-level confound untested) | "…a preliminary table (pre-fix 1h data, crisis n of 30-40 bars per pair, raw-level volatility confound untested); not evidence for the thesis until re-run." |
| P-309 | PAPER.md:3414-3424 | Comomentum 0.090 vs 0.048; P75 0.113 | QUALIFY | D1, D3/D4 | Label "pre-fix 1h cache". |
| P-310 | PAPER.md:3426-3432 | Class weighting: accuracy 68% → 56% | QUALIFY | stale; CR-2 | Label "125-event era". |
| P-311 | PAPER.md:3434-3462 | Stability selection, NCO, RL, DL stat-arb: deferred | STANDS | — | no change |

### PAPER.md References (PAPER.md:3464-3648)

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-312 | PAPER.md:3466-3470 | Entries "[VERIFIED 2026-06-23] … confirmed via direct source lookup" alongside Ref#15-#32 [TBD] | QUALIFY | cit structural #1 | Upgrade the [TBD] entries the citation audit confirmed; keep [TBD] only for Meucci, Carver, Hooker, Grinold-Kahn 2nd-ed. year. |
| P-313 | PAPER.md:3464-3648 | Reference list completeness | WITHDRAW | cit structural #2-#4 (31 in-text works without entries; 5 uncited entries; AFML listed twice; Ref#19 wrong L&W paper; Ref#32 wrong pages 74-95 → 96-117; Ref#31 "GNN"; Ref#14 claims Engle 2002 "already cited above") | Apply CITATION_AUDIT "Required corrections" 1-21. |

### PAPER_MAGNITUDE.md §1 Introduction

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| M-023 | PAPER_MAGNITUDE.md:195-203 | Motivating question: does discarded discovery-event information matter | STANDS | — | no change |
| M-024 | PAPER_MAGNITUDE.md:203-208 | Timing bias "serious enough to overturn a pair set's profitability"; regime "a real, statistically significant predictive signal current practice simply throws away" | WITHDRAW | B2-B4 (profitability), R3.1 (persistence), own §5 (confirmation rate not significant) | "…ignored in one direction it may be a source of selection bias; ignored in the other it may carry information. Both are tested below; neither is currently established." |
| M-025 | PAPER_MAGNITUDE.md:208-211 | Confirmed-pair count changed by an order of magnitude multiple times | QUALIFY | A1 | Add "(partly through since-fixed defects, not only methodology corrections)". |
| M-026 | PAPER_MAGNITUDE.md:213-240 | Scale caveats; 638,095 candidate pairs; 8.18%; ~90 crash-restarts fixed | QUALIFY | R6.2 (8.18%), D16 (CachyOS runs used ~2.8% fewer WRDS files until 09-27) | Add: "The 2026-09-02 scan ran on CachyOS, where 1,647 WRDS files were truncated and silently skipped (D16, restored 2026-09-27)." |
| M-027 | PAPER_MAGNITUDE.md:243-247 | "every finding below runs production code, not a parallel research-only reimplementation" | QUALIFY | R1.11 (UNVERIFIED: bh_vs_by_full_universe_1d uses one-direction EG), `pit_wfa_wrds_daily.py` is a standalone script (M:570-572) | "…most findings reuse production components; exceptions are named at each finding." |
| M-028 | PAPER_MAGNITUDE.md:263-275 | §4 fold reading: 1 fold real evidence, 2 inconclusive, 1 too thin | WITHDRAW | S1/A1, B2-B4, D3/D4 | "The 1h fold results are being re-derived; they came from a screen with an EG alignment defect and from invalid P&L." |
| M-029 | PAPER_MAGNITUDE.md:278-282 | GGR "treats pair selection as a given input, computed once over full available history, and validates only the trading rule causally" | WITHDRAW | cit#9, M-15 | As M-009. |
| M-030 | PAPER_MAGNITUDE.md:282-291 | Mechanistic link to PBO (Bailey, Borwein, López de Prado & Zhu, "2014/2016") | QUALIFY | cit#52 | Keep the analogy; single year (2016), confirm vol./pages. |
| M-031 | PAPER_MAGNITUDE.md:291-297 | Full-scale re-run "2 of 4 folds capital-constrained-positive … largest fold (1,533 raw trades) landing positive" | WITHDRAW | B2-B4, P1, R1.12, R1.13, R5.1 | Delete. |
| M-032 | PAPER_MAGNITUDE.md:299-334 | §5 preview: persistence survives (91.0% vs 78.7%, p=0.032); confirmation rate does not; SPY residual; survivorship | WITHDRAW | R3.1 (persistence), R4.3, R3.10-R3.11 | "§5 asks whether the regime at discovery predicts anything. The confirmation-rate difference is not significant once crisis episodes are treated as clusters; the persistence comparison is being recoded (R3.1); confound checks are preliminary." |
| M-033 | PAPER_MAGNITUDE.md:336-356 | Interaction test: 1.72% (16/929) vs 0.0003% (2/637,166), z=98.7; 18 of 320 PIT pairs overlap | QUALIFY | R4.2 (CONFIRMED: invalid pooled z at x=2/x=16), S3/S1 (PIT pair set) | Keep the counts; drop z=98.7; add "(exact test pending; PIT pair set from the pre-A1-fix daily re-screen)". |

### PAPER_MAGNITUDE.md §2 Data and Universe

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| M-034 | PAPER_MAGNITUDE.md:362-366 | "yfinance primary daily/intraday, WRDS/CRSP primary for daily-and-coarser US equity/ETF with Compustat Global fallback" | QUALIFY | U4, R1.1, S-1 | "…WRDS primary for daily-and-coarser US equities/ETFs (CRSP; price-only in `universe_loader`, total-return in the episodic scan) and Compustat Global for international listings (local currency, no FX conversion)…" |
| M-035 | PAPER_MAGNITUDE.md:368-381 | Universe-undercount bug disclosed; ~44,700 merged universe via `load_full_universe()` | STANDS | N-1 (figure should carry a date) | Add the date and the 43,883 / 44,840 reconciliation. |
| M-036 | PAPER_MAGNITUDE.md:382-393 | Which sections are at corrected scale | STANDS | — | no change |
| M-037 | PAPER_MAGNITUDE.md:395-401 | "~43,662 of ~44,700 … (1,032 files 0-byte or corrupted …, skipped and logged, not silently dropped)"; WRDS daily-only | QUALIFY | U1, D16 (CONFIRMED: `universe_loader._read_one` returned None with no count or log; 1,647 zero-byte files on CachyOS, 0 on the Surface; restored 2026-09-27) | "…WRDS daily files for ~43,662 symbols. Until 2026-09-27, unreadable files were dropped without a count (U1); CachyOS runs silently skipped 1,647 truncated files (D16, since restored). Daily-only scope: WRDS carries no intraday data." |

### PAPER_MAGNITUDE.md §3 Shared Methodology

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| M-038 | PAPER_MAGNITUDE.md:411-418 | Pearson pre-filter; chunked variant bit-exact | STANDS | — | no change |
| M-039 | PAPER_MAGNITUDE.md:419-420 | `_eg_worker` both-directions max, "identical to `CointScanner.scan`" | QUALIFY | S2 (episodic path UNVERIFIED: failed/one-direction tests dropped before BH), CR-7 (production path now keeps crashed tests in m) | Add: "(in `analysis.py`, crashed tests are kept in BH's denominator since 2026-09-27; whether the episodic scan does the same is being checked — S2)". |
| M-040 | PAPER_MAGNITUDE.md:421-422 | `_benjamini_hochberg`, FDR_ALPHA | STANDS | — | no change |
| M-041 | PAPER_MAGNITUDE.md:423-429 | Episodic window 2,520 bars / step 252; "unioning each window's qualifying pairs across the full scan" | QUALIFY | R1.6 (CONFIRMED: min_windows_confirmed = 1), S3 | Add: "Because a pair is confirmed if any one window passes, the pair-level FDR is bounded at ~9.1% (0.05 × 1,699/929), not 5%; 750 of 929 confirmed pairs rest on exactly one window." |
| M-042 | PAPER_MAGNITUDE.md:430-433 | Hysteresis: state change confirms only after 3 consecutive windows | WITHDRAW | R6.2 (CONFIRMED by code: `or boot_idx == 0` accepts the first raw run regardless of length) | "Intended rule: 3 consecutive windows. As implemented, the first run of every pair's history bypasses it (fix pending); 46% of cointegrated spans are shorter than 3 windows." |
| M-043 | PAPER_MAGNITUDE.md:435-440 | New machinery verified against synthetic ground truth | QUALIFY | R3.1, R6.2 (the verified scripts still carried these defects) | Add: "Two defects in this machinery (R3.1 reappearance coding, R6.2 hysteresis bypass) passed their synthetic tests." |

### PAPER_MAGNITUDE.md §4 Finding 1

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| M-044 | PAPER_MAGNITUDE.md:446-455 | Causal argument for why a backward-looking screen can mis-certify transient pairs | STANDS | — (argument, not result) | no change |
| M-045 | PAPER_MAGNITUDE.md:457-463 | Test design: 4 cutoffs, full pipeline on pre-cutoff data, unmodified BacktestEngine | QUALIFY | S1/A1 (fixed), S4, S14 | Add: "(screen alignment fixed 2026-09-27; hedge-ratio fallback and missing embargo under review)". |
| M-046 | PAPER_MAGNITUDE.md:465-475 | Scale caveat: "current WRDS-primary universe at 1,576 symbols" | WITHDRAW | N-3 | "…the 1,576-symbol hourly (yfinance/IBKR) cache (WRDS carries no intraday data)…" |
| M-047 | PAPER_MAGNITUDE.md:477-482 | Fold table 0/2/0/1; −1.0121; +0.2547 | WITHDRAW | S1/A1, B2-B4, D3/D4, D1 | As P-158. |
| M-048 | PAPER_MAGNITUDE.md:484-501 | "1 of 4 folds is real supporting evidence, 2 are inconclusive, 1 is a thin counter-example" | WITHDRAW | same | Delete. |
| M-049 | PAPER_MAGNITUDE.md:503-518 | Earlier test: zero overlap, −0.72 to −1.04; "screening function itself is trustworthy"; "a real property of the discovery process … not a bug in the diagnostic" | WITHDRAW | BUG-D68 (BL:85: root cause = 95.6% override passes; not re-tested), A1/S1, B2-B4, M-2, X-3 | "An earlier pre-WRDS test found no overlap at three checkpoints; that result was later traced largely to an unreliable short-window override (BUG-D68, not yet re-tested) and its fold P&L used the invalid accounting. It is withdrawn as evidence." |
| M-050 | PAPER_MAGNITUDE.md:520-531 | "genuine cointegration is real but transient … coherent picture"; §5 "should be exploited" | QUALIFY | R6.2, R3.1 | "…consistent with cointegration being episodic (§7.2, pending the hysteresis fix); §5 asks whether discovery regime carries information." |
| M-051 | PAPER_MAGNITUDE.md:533-567 | Reproducibility gap: re-derivation gives 3 pairs / +0.3486 and 49 pairs / −0.4548; "most likely" cause is pipeline change | QUALIFY | B2-B4 (Sharpes), S1/A1 (a concrete candidate cause: alignment), D2 (cache frozen at 2026-06-17 from mid-June) | Keep the pair counts; drop the Sharpes; add A1/S1 and the frozen daily cache as concrete candidate causes. |
| M-052 | PAPER_MAGNITUDE.md:569-597 | Corrected-scale re-run design (`pit_wfa_wrds_daily.py`); two BacktestEngine/portfolio_sim bugs fixed | QUALIFY | R1.12 (UNVERIFIED: price-only / local-currency closes vs TR discovery), R1.13 (train+test hedge ratios as skip gate) | Add these two open items. |
| M-053 | PAPER_MAGNITUDE.md:599-606 | 20% concentration cap as "already-declared" convention | STANDS | — | no change |
| M-054 | PAPER_MAGNITUDE.md:608-617 | Corrected-scale fold table: 31/110/31/303 pairs; capsim −0.4779/+0.1918/−0.4779/+0.2175 | WITHDRAW | B2-B4, P1, R1.12, R1.1 | Keep the pair counts with "(pre-A1-fix screen? to be confirmed)"; delete the Sharpes. |
| M-055 | PAPER_MAGNITUDE.md:619-633 | "genuinely mixed"; cap "flips the portfolio Sharpe's sign (−0.2589 raw → +0.2175) … genuine downside-risk reduction" | WITHDRAW | B2-B4, R5.1 | Delete. |
| M-056 | PAPER_MAGNITUDE.md:634-645 | Pooled Sharpe +0.1845 / +0.1285 (calendar-day) vs −0.1302 / −0.1431 (equal-weight); "inter-fold calendar gap dropped" | WITHDRAW | R5.1 (CONFIRMED: fold P&L spans first→last exit, not the fold window), P1 (construction now business-day, 85e766fb), B2-B4 | "Withdrawn: each fold's daily series spanned only its first to last exit (dropping years of no-trade days), and the P&L itself is invalid." |

### PAPER_MAGNITUDE.md §5 Finding 2

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| M-057 | PAPER_MAGNITUDE.md:651-656 | "This section shows yes, in a specific, statistically disciplined … way" | WITHDRAW | R3.1, own cluster-robust result | "This section asks whether it can; the answer is not yet established." |
| M-058 | PAPER_MAGNITUDE.md:658-672 | Motivation: Tier-3 prefilter counts jump 4-10× in 2008-09 and 2020 windows | STANDS | — | no change |
| M-059 | PAPER_MAGNITUDE.md:674-686 | Test design; VIX regime looked up "point-in-time-safe"; three pre-registered sub-questions | QUALIFY | R3.13 (UNVERIFIED: single-day VIX at window end), R3.1 | "…regime = the VIX close on the pair's first qualifying window's end date…; sub-question (3) as coded counts any later window whose regime differs from the first (docstring: 'later non-crisis window')." |
| M-060 | PAPER_MAGNITUDE.md:690-695 | Regime table: n_pairs, n_confirmed, rates by regime | QUALIFY | R3.1 (reappearance column), R3.2, R1.6, R1.1 | Keep n and confirmation columns; drop the reappearance column until recoded. |
| M-061 | PAPER_MAGNITUDE.md:697-710 | Counts sum to 929 (internal consistency); production count "is 29" | QUALIFY | N-4 (17 since 2026-09-13), N-8 | "…production count is 17 (after the 2026-09-13 alias/SPAC cleanup)…" |
| M-062 | PAPER_MAGNITUDE.md:712-727 | Confirmation rate: naive p=0.0056; cluster-robust CI [0.022%, 0.398%], "p-equivalent = 0.25" | QUALIFY | R6.9 (UNVERIFIED: 'fraction ≤ calm' is not a p-value; 12 unequal clusters) | "…the fraction of episode-level resamples at or below calm's rate is 0.25 (not a formal p-value)…" |
| M-063 | PAPER_MAGNITUDE.md:728-742 | Persistence 91.0% vs 78.7%, cluster-robust p=0.032, "the counter-intuitive result the paper leans on" | WITHDRAW | R3.1 (CONFIRMED), H-9 | As M-014. |
| M-064 | PAPER_MAGNITUDE.md:743-750 | Strength: 0.288 vs 0.223, U=5119, p=0.196 | STANDS | — | no change |
| M-065 | PAPER_MAGNITUDE.md:752-762 | Non-monotonic across regimes | STANDS | — | no change |
| M-066 | PAPER_MAGNITUDE.md:764-793 | Episode table (12 episodes; top 2 hold 27 of 29 confirmations; COVID 1 of 2,329) | STANDS | — (descriptive counts) | no change (drop the reappearance column per R3.1). |
| M-067 | PAPER_MAGNITUDE.md:795-810 | Concentration "real, not a chance artifact" (binomial p=0.000006; MC p=0.00002) | QUALIFY | R3.3, R3.4 (UNVERIFIED) | As M-013. |
| M-068 | PAPER_MAGNITUDE.md:812-826 | Episode-level vs pooled questions distinguished | STANDS | — | no change |
| M-069 | PAPER_MAGNITUDE.md:828-841 | Reappearance 84%-100% across episodes; "why §1.4/§6 lean on persistence" | WITHDRAW | R3.1 | Delete. |
| M-070 | PAPER_MAGNITUDE.md:843-852 | Factor confound described as "idiosyncratic correlation structure collapses toward a single dominant systemic-risk factor (Forbes & Rigobon, 2002; Longin & Solnik, 2001)" | WITHDRAW | cit#70 (MISATTRIBUTED), cit#71 | "…a market-factor co-movement confound (crisis periods raise common-factor exposure); separately, Forbes & Rigobon (2002) show that correlation coefficients are biased upward in high-volatility periods, which would inflate a correlation prefilter in crisis windows — a bias the SPY-residual test below does not address. Longin & Solnik (2001) document higher correlation in bear markets." |
| M-071 | PAPER_MAGNITUDE.md:853-873 | SPY residual: 6.7% subset 88.26% vs 78.41% (z=9.13); factor subset 91.42% vs 78.67% (z=31.05); "the Forbes-Rigobon confound is real, it just isn't the whole story" | WITHDRAW | R3.1 (metric), R4.3 (UNVERIFIED), cit#70 | "Pending: the metric tested is the persistence measure being recoded, and the full-history SPY beta does not capture crisis-window factor exposure." |
| M-072 | PAPER_MAGNITUDE.md:874-893 | Same-sector 93.3% vs 92.1% (p=0.69); cross-sector 99.4% vs 94.1% (p=0.000018); exclusion of 2024/2025 episodes "flipped the result's direction … until corrected for" | WITHDRAW | R3.7 (CONFIRMED: filter drops only crisis-first pairs after a hardcoded 2022-06-01, keeps all calm pairs; added after an opposite first result), R3.1, R3.8, H-8 | "Withdrawn: the censoring filter was one-sided (applied only to crisis-first pairs) and was added after a first run gave the opposite, significant result; a symmetric re-run on the recoded metric is pending." |
| M-073 | PAPER_MAGNITUDE.md:894-909 | Survivorship: 20.6%; 0.34% vs 0.30%, z=1.26, p=0.21 | QUALIFY | R3.10, R3.11 | As M-018. |
| M-074 | PAPER_MAGNITUDE.md:911-918 | Gap-rule sensitivity: top-2 share 0.931 at every choice; 11-13 episodes | QUALIFY | R3.6 (UNVERIFIED: no null per gap) | Keep; add "(descriptive)". |
| M-075 | PAPER_MAGNITUDE.md:918-930 | Strength vs discovery regime: χ²=6.70, dof 6, p=0.349 on 56,003 pairs | QUALIFY | R6.2 (strength terciles skewed by the hysteresis bypass), R4.11 (UNVERIFIED: reversed-order pairs dropped) | Add "(pending the hysteresis fix)". |
| M-076 | PAPER_MAGNITUDE.md:932-944 | "every number in this section traces to a script verified against synthetic ground truth" (21/21, 11/11, 7/7, 7/7) | QUALIFY | R3.1 (the 21/21 script carries the reappearance defect) | "…each script has a synthetic test; the reappearance definition passed its test while contradicting its own docstring (R3.1)." |
| M-077 | PAPER_MAGNITUDE.md:944-952 | Stress test found ~8% vs 9% cointegration-holds | QUALIFY | R5.5-R5.7 | Add the P-197/P-198 caveats. |
| M-078 | PAPER_MAGNITUDE.md:954-971 | "the regime it first cleared that filter in carries real predictive information … current practice simply discards" | WITHDRAW | R3.1, own cluster-robust result | "…whether the regime carries information is open: the confirmation-rate difference is not significant under clustering and the persistence measure is being recoded." |

### PAPER_MAGNITUDE.md §6 Synthesis

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| M-079 | PAPER_MAGNITUDE.md:987-995 | §4 "determines whether the certified pair set would actually have been discoverable, and profitable … the paper's best-evidenced, central contribution" | QUALIFY | M-1, M-2 | "…is the paper's central question; its evidence is being re-derived." |
| M-080 | PAPER_MAGNITUDE.md:997-1006 | §5 "informative about a pair's future persistence, confirmed under a cluster-robust test" | WITHDRAW | R3.1 | Delete "confirmed". |
| M-081 | PAPER_MAGNITUDE.md:1011-1026 | Interaction: 1.72% (16/929) vs 0.0003% (2/637,166), "z=98.7, p≈0" | QUALIFY | R4.2, R4.1 | Keep counts; drop z and p; "exact test pending". |
| M-082 | PAPER_MAGNITUDE.md:1027-1032 | §7.7: all 16 overlapping pairs "strong", z=3.98, p=0.0001, "a second, independent confirmation" | WITHDRAW | R4.1/R6 (CONFIRMED circular: strength terciles fit on full-history windows incl. post-cutoff data), R4.2, M-11, H-11 | Delete. |
| M-083 | PAPER_MAGNITUDE.md:1038-1056 | Beyond CAMARF: GGR "treats pair discovery as a preprocessing step"; claims framed as testable hypotheses | QUALIFY | cit#9 | Remove the GGR characterization (M-009); keep the hypothesis framing. |
| M-084 | PAPER_MAGNITUDE.md:1058-1072 | Six supporting findings "real, verified, and load-bearing" | QUALIFY | see §7 rows | "…each with its own current status (§7)." |
| M-085 | PAPER_MAGNITUDE.md:1074-1089 | Thesis restated: timing "directly demonstrated on one fold"; regime "predict[s] something real about … persistence" | WITHDRAW | M-047, R3.1 | "A 'confirmed' label is a fact about a test run at a time, on a pool, in a regime. Whether timing and regime change what a causal observer would have earned is the question this paper sets up; the re-derivation of both is in progress." |

### PAPER_MAGNITUDE.md §7 Supporting Findings

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| M-086 | PAPER_MAGNITUDE.md:1095-1103 | "a pipeline this thoroughly audited is trustworthy specifically because every stage … has been checked this way" | WITHDRAW | ~60 CONFIRMED findings in CODE_REVIEW | "…reported because each shows a stage where naive screening goes wrong; the 2026-09-26 audit found further defects in this same pipeline, listed in §8." |
| M-087 | PAPER_MAGNITUDE.md:1107-1120 | 638,095 pairs; 5,003,637 tests; 5,003,637 × 0.05 ≈ 250,182 expected false positives | STANDS | — (arithmetic checked: 250,181.85) | no change |
| M-088 | PAPER_MAGNITUDE.md:1113-1116 | 78 raw whole-history candidates from the full-sample cascade | QUALIFY | U4 (price-only closes), A1 status of `full_universe_eg_confirmation.py` not checked | Add "(A1 exposure of this script not yet checked)". |
| M-089 | PAPER_MAGNITUDE.md:1122-1132 | BH controls the expected proportion of false discoveries among rejections; BY makes no dependence assumption | QUALIFY | R1.6 | Add: "At the pair level (any-of-K windows), the bound is ~9.1%, not α." |
| M-090 | PAPER_MAGNITUDE.md:1133-1148 | Full-scale BH vs BY; two bugs fixed incl. per-symbol-length arrays swallowed as "not ok" — "a fix this project had already diagnosed once before" | QUALIFY | A1 (the same mechanism in `analysis.py`'s main path was not checked then; fixed 2026-09-27), X-3 | Add: "The same silent failure existed in `analysis.py`'s main screen and `pit_wfa`'s fold screen (A1/S1); fixed 2026-09-27." |
| M-091 | PAPER_MAGNITUDE.md:1149-1154 | 29,890/30,000 usable; 2,518 raw; BH 35, BY 23; BY ~66% of BH | QUALIFY | R1.11 (UNVERIFIED: one-direction EG), U4/R1.1 (price-only / local currency), own stale-pool note (997,024 → 723,753) | Add "(one-direction EG; pre-alias-cleanup pool; to be re-run)". |
| M-092 | PAPER_MAGNITUDE.md:1156-1166 | Stale-pool disclosure: 2,211 of 6,844 aliases; corrected pool 723,753; not re-run | STANDS | — | no change |
| M-093 | PAPER_MAGNITUDE.md:1168-1177 | Literature critique: undisclosed pool size / correction overstates reliability | STANDS | — | no change |
| M-094 | PAPER_MAGNITUDE.md:1179-1213 | DSR: 990 trials; pooled DSR 0.0000 (z to −63.99); ~250 grid-sweep trials; family 0.9676 (z=1.85, n=39); "edge is statistically real" | WITHDRAW | R2.1 (CONFIRMED: 1,150 records / 570 unique), R2.2, B2-B4, CR-1 | "Withdrawn: the registry was double-merged and its Sharpes are on the invalid accounting; on the corrected accounting the gate family's unconstrained Sharpe is negative in-sample (§PAPER.md 7.21)." |
| M-095 | PAPER_MAGNITUDE.md:1217-1226 | §7.2 scale disclosure; re-run completed 2026-09-02 | STANDS | D16 note as M-026 | no change |
| M-096 | PAPER_MAGNITUDE.md:1228-1246 | 56,536 coint of 691,213 spans = 8.18%; strong/moderate/weak 18,827/18,883/18,826; global terciles | QUALIFY | R6.2 (CONFIRMED by code; 26,044 of 56,536 coint spans < 3 windows, all leading, 9,120 labelled strong — reviewer-computed) | "…8.18% before correcting a hysteresis bypass that affects up to 46% of cointegrated spans; the share and the tercile cutoffs will change." |
| M-097 | PAPER_MAGNITUDE.md:1248-1255 | "A pair passing a whole-history cointegration test is not evidence of a stable, ongoing relationship … usually a minority" | STANDS | — (holds even if the fraction moves; NTRS/STT is independent evidence) | no change |
| M-098 | PAPER_MAGNITUDE.md:1257-1276 | SPAC NAV-clustering mechanism | STANDS | — | no change |
| M-099 | PAPER_MAGNITUDE.md:1278-1298 | Detection via CRSP `comnam` regex; 22 SPACs by name; BRIV manual catch; Hedosophia gap | STANDS | — | no change |
| M-100 | PAPER_MAGNITUDE.md:1300-1315 | 23 of 78 SPAC-excluded; 22 GVKEY duplicates; 6 alias collisions; 27 survive; 27+1+1 = 29 | QUALIFY | N-4 (production count now 17) | Add: "(the 29 was reduced to 17 on 2026-09-13)". |
| M-101 | PAPER_MAGNITUDE.md:1317-1328 | ~29% of confirmed cointegration from one microstructure mechanism; generalizes to NAV-anchored classes | STANDS | — | no change |
| M-102 | PAPER_MAGNITUDE.md:1332-1343 | Lee-Mykland method; square-root bug caught; 0/5000 FP, 5/5 jumps recovered | STANDS | — | no change |
| M-103 | PAPER_MAGNITUDE.md:1345-1353 | "Real-data result at production scale, PIT-safe … 0.0% overlap … in all 640 of 640 rows"; jump frequency 0.51%; vol 5.8-7.3% lower | QUALIFY | Verified by code this scrutiny: `research/levy_jump_diffusion.py:160-167` computes returns on `_gap_masked_log_price` (`research/lead_lag_scan.py:91-96`, which NaNs DATA_GAP bars via `_clean_close`), drops non-finite returns, then compares jumps only with the flags of the surviving bars, and sets all flags to NONE when a frame has no `gap_flag` column; B1, D1 (flags largely NONE at cache time); U3; S3 ("PIT-safe") | "…Jump frequency: mean 0.51%, median 0.47% of bars; jump-adjusted volatility 5.8-7.3% below naive. The overlap with GapFlag is 0% by construction: DATA_GAP bars are removed before the comparison and, in the caches used, gaps had been forward-filled and flagged NONE. The pairs come from the episodic pool, which is not point-in-time at the pair level." |
| M-104 | PAPER_MAGNITUDE.md:1355-1368 | "GapFlag and jump-diffusion detection are not two views of the same phenomenon … replicates exactly … across 206 symbols" | WITHDRAW | same as M-103 | "Clean-continuity and well-behaved-returns are different properties in principle; this comparison could not test whether GapFlag captures jumps, because its flags were largely absent." |
| M-105 | PAPER_MAGNITUDE.md:1370-1399 | 15.8σ calendar-padding derivation; generalization as hypothesis | STANDS | — | no change |
| M-106 | PAPER_MAGNITUDE.md:1401-1405 | Fix: compact real bars, scatter back | QUALIFY | B1, D1 | As P-093. |
| M-107 | PAPER_MAGNITUDE.md:1407-1417 | Only exact derivation distinguishes artifact from structure | STANDS | — | no change |
| M-108 | PAPER_MAGNITUDE.md:1426-1428 | HRP 5.3752 vs risk-parity 5.8689 "HRP loses" | WITHDRAW | B2-B4 | Delete. |
| M-109 | PAPER_MAGNITUDE.md:1429-1436 | Kalman 2-state: fixed-share Sharpe 2.35 vs OLS 12.28; "fixed per-share commission costs are invariant to spread scale, so a tighter spread's smaller gross P&L is disproportionately eaten by cost" | WITHDRAW | B3 (CONFIRMED: gross in log units × shares, cost in dollars — the stated mechanism is the unit mix itself), B2 | "Withdrawn: the mechanism described is the log-unit-vs-dollar-cost mixing found 2026-09-26 (B3), not a property of the hedge model." |
| M-110 | PAPER_MAGNITUDE.md:1437-1440 | ERC 0.6933 vs inverse-cluster-size 0.7216; ERC concentrates up to 27% | WITHDRAW | R5.2 (CONFIRMED lookahead in cluster labels), B2-B4 | Keep "ERC concentrated up to 27% in one pair" as a weight observation; delete Sharpes. |
| M-111 | PAPER_MAGNITUDE.md:1441-1447 | Eigenvalue-penalized weighting loses (0.65-0.69 vs 0.7216) | WITHDRAW | R5.2, R5.4 (UNVERIFIED), B2-B4 | Delete Sharpes; keep the MP-adaptive stability fix as a verification note. |
| M-112 | PAPER_MAGNITUDE.md:1448-1456 | Meucci ENB 9.78 vs GK BR_eff 19.5/21 on ρ̄=0.0039 | QUALIFY | B2-B4 (correlations of invalid P&L), cit#20 | "…on pair P&L correlations from the pre-2026-09-26 accounting; the qualitative point (clustered correlation lowers eigenvalue-based bets below equicorrelation breadth) is a property of the methods and stands." |
| M-113 | PAPER_MAGNITUDE.md:1458-1470 | "Complexity pays off specifically when it corrects an identified false assumption" as a decision rule | WITHDRAW | M-108 to M-111 | "Pending: four of the five comparisons behind this rule were scored on invalid P&L; the rule is a hypothesis." |
| M-114 | PAPER_MAGNITUDE.md:1472-1494 | §7.7: all 16 overlap pairs "strong", z=3.98, p=0.0001, "Real, decisive result … methodologically independent" | WITHDRAW | R4.1/R6 (CONFIRMED circular), R4.2 (CONFIRMED), H-11 | Delete the section or restate: "All 16 overlapping pairs fall in the 'strong' tercile; because the terciles were fit on windows that include the PIT cutoffs' own post-cutoff data, this is not independent evidence." |

### PAPER_MAGNITUDE.md §8 Limitations

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| M-115 | PAPER_MAGNITUDE.md:1504-1520 | §4 limitations: 1h result directional; corrected-scale "2 capital-constrained-positive, 2 negative … largest fold positive" | WITHDRAW | B2-B4, S1, R5.1 | "§4's fold results (1h and daily) are withdrawn pending re-derivation with the A1-fixed screen and dollar P&L." |
| M-116 | PAPER_MAGNITUDE.md:1520-1554 | Pooled Sharpe construction: "inter-fold calendar gap dropped, not zero-filled"; "weights by calendar days present in each fold's own daily-zero-filled series"; "a real, correctly-computed consequence … not an artifact of a coding error" | WITHDRAW | R5.1 (CONFIRMED coding error in exactly this construction), P1 (now business days), H-5 | Delete, per M-056. |
| M-117 | PAPER_MAGNITUDE.md:1555-1575 | Survivorship: delisted S&P 500 members recovered (1,956 vs 503 permnos, ~74%); S&P 400/600 current-constituents only | STANDS | — | no change |
| M-118 | PAPER_MAGNITUDE.md:1575-1591 | `pit_wfa.py` draws from a present-day 1h cache glob; true gap could be larger | STANDS | — | no change |
| M-119 | PAPER_MAGNITUDE.md:1591-1599 | Second reproducibility gap attributed to pipeline change | QUALIFY | A1/S1, D2 | As M-051. |
| M-120 | PAPER_MAGNITUDE.md:1600-1646 | §5 limitations restated (clustering; persistence p=0.032; residual test; survivorship; interaction z=98.7, z=3.98) | WITHDRAW | R3.1, R4.1, R4.2, R3.7 | Rewrite to the M-002/M-032 position; drop z=98.7 and z=3.98. |
| M-121 | PAPER_MAGNITUDE.md:1647-1651 | Credit proxy: 0.2038% vs 0.0922%, z=7.45, "same direction, more significantly … a real robustness win" | WITHDRAW | R3.12 (UNVERIFIED), internal (the same naive pooled z-test was shown invalid for confirmation rate in §5: cluster-robust fraction 0.25 vs naive p=0.0056) | "A credit-spread regime proxy gives the same direction (0.2038% vs 0.0922%) on a naive pooled test, which this paper's own §5 shows overstates significance; no robustness claim is made until an episode-clustered test is run." |
| M-122 | PAPER_MAGNITUDE.md:1652-1661 | Not dose-response; observational only | STANDS | — | no change |
| M-123 | PAPER_MAGNITUDE.md:1662-1668 | §7.1 BH-vs-BY full-scale: 35 vs 23 "closes the item" | QUALIFY | R1.11, stale pool | As M-091. |
| M-124 | PAPER_MAGNITUDE.md:1669-1681 | §7.2/§4 scale notes | STANDS | — | no change |
| M-125 | PAPER_MAGNITUDE.md:1682-1688 | SPAC regex non-exhaustive; promotion skipped coint_fraction_rolling | STANDS | — | no change |
| M-126 | PAPER_MAGNITUDE.md:1689-1694 | Jump result 1D-only; intraday effect may be larger (26-42%) | QUALIFY | M-103 | Add the M-103 by-construction caveat. |
| M-127 | PAPER_MAGNITUDE.md:1699-1701 | "the equity/ETF universe remains a current-constituent snapshot … for all findings in this paper" | QUALIFY | H-17; internal (M-117 says S&P 500 delisted members are recovered) | "…survivorship is reduced for the S&P 500 layer (delisted members recovered) and not for S&P 400/600 or international listings." |
| M-128 | PAPER_MAGNITUDE.md:1702-1712 | Reproducibility: §7.4 jump result and §7.5 are reproducible on free data | QUALIFY | internal (M-103: the PIT jump result is on WRDS 1D) | "…only §7.5's derivation and the original single-pair jump result are reproducible on free data; the PIT jump result uses WRDS." |
| M-129 | PAPER_MAGNITUDE.md:1713-1715 | AI disclosure cross-reference | STANDS | — | no change (inherits P-282 to P-293 changes). |

### PAPER_MAGNITUDE.md §9-§10 and References

| ID | Location | Claim | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| M-130 | PAPER_MAGNITUDE.md:1721-1729 | PAPER.md "produces a real, disclosed, non-overclaimed backtest result (its own 5.24 OOS Sharpe headline…)" | WITHDRAW | B2-B4, B11, N-7 | "`PAPER.md` reports the application of this methodology to a strategy; its P&L results are being re-derived after the 2026-09-26 accounting correction." |
| M-131 | PAPER_MAGNITUDE.md:1735-1738 | DONE: BH-vs-BY full scale (35/23) | QUALIFY | as M-091 | Add "(to be re-run on the alias-cleaned pool with both-direction EG)". |
| M-132 | PAPER_MAGNITUDE.md:1739-1748 | DONE: fold2_exp +0.3486 (3 pairs, 28 trades), fold2_roll −0.4548 (49 pairs, 288 trades) "stable under a second, independent re-run" | WITHDRAW | B2-B4, S1/A1 (both runs pre-fix) | Keep pair/trade counts only, labelled "pre-A1-fix". |
| M-133 | PAPER_MAGNITUDE.md:1755-1761 | DONE: strength vs PIT, "Real, decisive result", z=3.98 | WITHDRAW | R4.1/R6, R4.2 | Delete. |
| M-134 | PAPER_MAGNITUDE.md:1762-1770 | DONE: credit proxy "Real robustness win … even more statistically significant" | WITHDRAW | as M-121 | As M-121. |
| M-135 | PAPER_MAGNITUDE.md:1776-1786 | DONE: factor confound "Real, decisive answer" | WITHDRAW | R3.1, R4.3 | "Open: re-run on the recoded persistence metric with crisis-window betas." |
| M-136 | PAPER_MAGNITUDE.md:1787-1809 | DONE: corrected-scale PIT re-run; survivorship half; pooled-Sharpe half | WITHDRAW | B2-B4, R5.1, P1 | Keep the survivorship half; withdraw the Sharpe halves. |
| M-137 | PAPER_MAGNITUDE.md:1810-1825 | DONE: interaction test z=98.7 | QUALIFY | R4.2 | Counts only; exact test pending. |
| M-138 | PAPER_MAGNITUDE.md:1829-1833 | "Shared bibliography with PAPER.md … (… Benjamini-Hochberg/Yekutieli, Lee & Mykland 2008 …)" | WITHDRAW | cit#7, #69 (neither BY 2001 nor Lee & Mykland 2008 is in PAPER.md's list) | Add both entries to PAPER.md's list, or list them here. |
| M-139 | PAPER_MAGNITUDE.md:1835-1843 | "A third citation added": PBO, "(2014/2016)", 20(4) 39-69 | QUALIFY | cit#52 | Single year (2016); confirm volume/pages; fix "third" wording. |
| M-140 | PAPER_MAGNITUDE.md:1845-1855 | F&R and Longin & Solnik cited "as named confounds" | QUALIFY | cit#70, #71 | Re-describe per M-070. |
| M-141 | PAPER_MAGNITUDE.md:1857-1871 | Rovelli (1996) kept under References though cut | QUALIFY | cit#72 | Move to Appendix A. |
| M-142 | PAPER_MAGNITUDE.md:1890-1918 | Appendix A: the 2026-09-02 reframing text says crisis pairs "confirm at a significantly higher rate and persist … significantly more" | QUALIFY | own §5, R3.1 | Mark the quoted throughline as superseded (it is provenance, but it states withdrawn results as findings). |

---

## (4) Method descriptions that no longer match the code (after this session's fixes)

| # | Paper text | What the code does now | Source |
|---|---|---|---|
| 1 | PAPER.md:1418-1420 "enter when |z_rolling| ≥ 2.0σ"; PAPER.md:1967, 2065 "production entry = 2.0" | `ENTRY_ZSCORE = 3.0` since 2026-08-17 (config.py:742); the backtest.py module docstring and `--entry-z` help still say 2.0 (CR-5). §7.20 (run 08-14) used 2.0; §7.21-§7.22 (09-15+) used 3.0 — neither section states which. | config.py:742; CODE_REVIEW:487 |
| 2 | PAPER.md:1418-1420 entry/stop/exit rule as a complete description | Entry has no upper |z| bound; stop fires on |z| ≥ 3.5 regardless of direction; `corr_exit` cannot fire at defaults; the `data_gap` force-close is dead code. New opt-in arms: `--storm-directional-stop`, `--storm-reentry-rearm`, existing `--entry-z-max`. | CR-5; B1; 8bb2bf0a |
| 3 | PAPER.md:1419-1422 "Fixed leg sizing … no hedge-ratio lookahead"; every "$" P&L figure in §6-§7 | `backtest.py` still books gross P&L as Δ(log_a − β_t·log_b) × shares with β re-estimated each bar, minus dollar costs (B2/B3 are NOT fixed in backtest.py). The corrected dollar P&L exists only as the comparison module `pnl_dollar.py` (hedge fixed at entry, real total-return leg prices, fixed notional, non-USD legs → `non_usd_leg`). `portfolio_sim.replay_portfolio(pnl_mode="dollar")` adds a dollar-mode capital replay. | 85e766fb, a6a846a7 |
| 4 | PAPER.md:1420, 1430 "both OLS and Kalman hedge ratios run in parallel" (results pooled) | `--hedge both` is still the default (backtest.py:2217) and still emits near-duplicate trades (B4); corrected results use OLS only. | backtest.py:2217 |
| 5 | PAPER.md:1323-1329 (DSR per-period Sharpe), 1368-1370 (CVaR exit-date grouping), 2409-2412 ("the other … zero-fills them"); PAPER_MAGNITUDE.md:1520-1554 (pooled Sharpe "calendar days present", "calendar gap dropped") | `portfolio_math` (the shared daily-P&L source) now builds a business-day series, and callers (portfolio_sim, sensitivity, wfa, pit_wfa pooled test, several research scripts) were switched (P1 fix). R5.1's first→last-exit span problem in `pit_wfa_pooled_equity_curve.py` is not described as fixed. | 85e766fb |
| 6 | PAPER_MAGNITUDE.md:1143-1148 (align fix "reused" only in `bh_vs_by_full_universe_1d.py`); PAPER.md:1649-1655, 1688-1694 (pit_wfa screen "trustworthy") | `analysis.align_to_common_index()` now reindexes aligned frames onto a union index before EG in `analysis._run_one_tf` and `pit_wfa`'s screen (A1/S1 fixed). ~20 research-script `align_universe` call sites unchanged. | 8bb2bf0a |
| 7 | PAPER.md:304-306, PAPER_MAGNITUDE.md:421-422, 1122-1132 (BH per timeframe) | `_combine_eg_directions` keeps crashed tests in BH's m with p = 1 and logs insufficient-overlap pairs. | 8bb2bf0a |
| 8 | PAPER.md:714-715 ("runs the production EG-test code itself") | `eg_null_calibration_montecarlo.py` runs one-direction `coint(a, b)` (R6.3); unchanged. | CODE_REVIEW R6.3 |
| 9 | PAPER.md:1249-1277, 444-455, 471, 510 ("White permutation test", "Reality Check", "correctly centers the null") | `stats.py:1054` is a non-demeaned circular block bootstrap (S5); unchanged. | CODE_REVIEW S5 |
| 10 | PAPER.md:546-551, 568; PAPER_MAGNITUDE.md:362-366 ("CRSP total-return-adjusted") | `universe_loader` reads price-only WRDS `close`; the episodic scan reads `close_total_return`; Compustat Global in local currency, no FX (U4, R1.1, R1.4); unchanged. | CODE_REVIEW U4, R1.1 |
| 11 | PAPER.md:831-836; PAPER_MAGNITUDE.md:1401-1405 (GapFlag masking protects rolling stats) | `DataCleaner._liquidity_filter` removed (D1 fixed), so `clean()` no longer rewrites prices; yfinance daily cache regenerated. Intraday caches still carry the old fabricated bars and old snapping. DATA_GAP flags still do not survive into persisted spread files (B1). | 361aa83f, 8bb2bf0a |
| 12 | CLAUDE.md-style 4h description implied throughout (session-aligned 4h bars) | `snap_timestamps` now ceils onto the session grid, keeps the partial last slot (1h 09:30-15:30; 4h 09:30 and 13:30) and merges collisions (D3/D4 fixed). On-disk intraday caches not regenerated. | 9109d99f |
| 13 | PAPER.md:1868-1871, 1884-1888 (ZA break date) | ZA break index now read from tuple index 4 (S7 fixed); all earlier break dates were the lag count's position. | 002d7070 |
| 14 | PAPER.md:2406-2418, 2820-2828 (quality-ranked admission "within each day") | Re-ranking only among identical `entry_time`; `--quality-admission-batch-freq` removed. | 54102af4 |
| 15 | PAPER.md:2099-2116, 406-412 (ml.py "chronological 60/20/20 split"; meta-labeler on the primary signal) | ml.py still splits positionally without purging (R2.3 open) and still includes the full-history TE features (ml.py:720-721, R4.10 open); its events are |z| = 1.5 crossings, not the strategy's 3.0 entries. Purged CV and TE exclusion exist only in `research/ml_model_comparison_purged.py`. Balanced accuracy is now reported for both thresholds. | ml.py:711-724; 361aa83f |
| 16 | PAPER.md:2314-2316 ("ml.py's 4-class label") | `Config.ML.LABEL_SCHEME = "binary"` (config.py:602). | config.py:602 |
| 17 | PAPER.md:2506-2514 (`episodic_bhfdr_confirm_asof` closes the PIT gap) | `episodic_pairs_adapter.main()` never passes `as_of_date` (S3); unchanged. | CODE_REVIEW S3 |
| 18 | PAPER_MAGNITUDE.md:430-433 (3-window hysteresis) | `cointegration_regime_segmentation.py:108` `or boot_idx == 0` bypass (R6.2); unchanged. | CODE_REVIEW R6.2 |
| 19 | PAPER_MAGNITUDE.md:684-686 (reappearance = "later, different-regime window") | `crisis_regime_correlation_diagnostic.py:191` codes any later regime ≠ first (R3.1); unchanged. | CODE_REVIEW R3.1 |
| 20 | PAPER_MAGNITUDE.md:395-401 ("skipped and logged, not silently dropped") | Unreadable-file drop was silent (U1); the CachyOS files were restored (D16 fixed); whether `load_full_universe` now counts/logs drops is not stated in the fix note. | CODE_REVIEW D16 |
| 21 | Any MIN_BARS statement for 3M/6M/1Y | `clean()` derives missing MIN_BARS entries from MIN_OVERLAP_BY_TF (3M/6M/1Y: 8/4/10) instead of a flat 100 (C13 fixed). | 002d7070 |
| 22 | Daily-refresh statements ("appends daily") | The incremental refresh now actually downloads and merges via `DataStore.append`; before 2026-09-27 227/300 sampled daily files had ended 2026-06-17 (D2 fixed). | 396b601f |

---

## (5) What can be re-stated now vs what must wait

### Claims that can be re-stated now with corrected numbers

| Claim (where) | Corrected statement (scope attached) | Source |
|---|---|---|
| Gate Sharpes (PAPER.md:2760-2763, 2796-2799; PAPER_MAGNITUDE.md:1201-1207) | Net / gross business-day Sharpe on dollar P&L: momentum IS −0.408 / −0.191, squeeze IS −0.386 / −0.227, combined IS −0.354 / −0.248; OOS −0.296 / −0.125, −0.078 / +0.003, −0.005 / +0.048. Old accounting on the same trades: +0.132 / +0.474 / +0.721 IS, −0.184 / +0.667 / +0.601 OOS. | CR-1 |
| "The strategy loses money" (PAPER.md:36-39, 190-199, 2710-2719) | Loses in-sample for every gate, before and after costs, and after excluding immediate stop-outs (gross −0.119 to −0.219); out-of-sample momentum loses, squeeze/combined ≈ 0. OLS, USD-only legs (~31% of trades), unconstrained. | CR-1 |
| "The rules are implemented correctly" (new; supports PAPER.md:2753-2758) | 0 rule or gate violations over 101,700 trades; design defects: 54-68% of entries at/past the stop, 32-40% stopped after a favourable move, 19-38% re-entered within 1 bar, `corr_exit`/`data_gap` never fire. | CR-5 |
| ML AUC (PAPER.md:2099-2108, 518-519, 498-505) | Purged/embargoed test AUC: RF 0.6085, XGBoost 0.6067, MLP 0.6033, LightGBM 0.6024 (tied); SVM 0.574, KNN 0.571, logistic 0.557 (worse). Purging changed XGBoost 0.6062 → 0.6067. Predicts z-convergence after a 1.5 crossing, not profitability. | CR-2 |
| Threshold recalibration (PAPER.md:2113-2116) | Balanced accuracy 57.72% (0.5) vs 57.64% (Youden). | CR-2 |
| "ML not yet shown to improve the strategy" (PAPER.md:2116-2120) | Meta-labeling the strategy's own trades on dollar profitability: AUC 0.47-0.54 over 24 trials; capital-sim differences −0.19 to +0.59 both directions; consistent with noise. | CR-3 |
| Label-overlap bias size (PAPER.md:2840-2854) | Purging moves AUC by +0.0005; overlap does not inflate the AUC measurably. | CR-2 |
| Luck-check null design (PAPER.md:2778-2786; PAPER.md:2763-2766) | Entries per business day are overdispersed (mean 1.90, var 5.15; negative binomial r ≈ 1.05), so an iid same-size random-draw null is misspecified. | CR-4 |
| Distribution facts (new, e.g. for §6/§7 method text) | Hold time and half-life at entry lognormal; horizon z-change Student-t (df ≈ 7.3); per-pair convergence beta-binomial (genuine pair heterogeneity; mean 0.40). | CR-4 |
| Quality-admission effect (PAPER.md:2820-2828) | After removing the lookahead: momentum IS 0.2337 → 0.1499, combined IS 0.1000 → 0.0357; taken-better-than-skipped False in all six luck checks (still old P&L — can be cited only as "the lookahead inflated it", not as a level). | CR-6 |
| α=0.01 shrinkage (PAPER.md:2811-2814) | 598 of 1,375 retained = 56.5% reduction (the "61%" is 360/929 from the 09-02 scan). | N-9 arithmetic |
| Data-layer status (PAPER.md §3; PAPER_MAGNITUDE §2) | yfinance daily cache regenerated 2026-09-27 (equity median flat days 10.8% → 2.9%; forex restored); A1/BH-denominator/D2/D3/D4/D14/D15/D16/C13/S7 fixed; intraday caches not regenerated. | CR-7 |
| `Development.md` size (PAPER.md:3111) | >28,000 lines. | `wc -l` |

### Claims that must wait for re-derivation

| Blocked on | Claims that must wait (IDs in the tables above) |
|---|---|
| **USD conversion of Compustat Global (GVKEY) legs** (R1.1; 69% of gate trades; 498/929 confirmed pairs) | Any full-pool P&L or Sharpe (P-004, P-259, P-266 beyond the USD subset); cross-currency cointegration results in the Tier-3 scan and everything built on 929/1,375 (M-006, M-011, M-060, M-087-M-091); the ADV gate for GVKEY symbols (R1.2). |
| **Purity rebuild with an explicit as-of cutoff** (S3) and a min-windows rule (R1.6) | Any "point-in-time-safe" wording (P-003, P-016, P-254, P-262, M-021); the holdout being a real out-of-sample test for §7.20-§7.22; the pair-level FDR (M-041, M-089); the §4 × §5 interaction and §7.7 (M-033, M-081, M-114). |
| **Capital-constrained replay on dollar P&L** (dollar mode built, not run on the gate arms) | The portfolio-level headline required by the project's own rule (P-256, P-258, P-268, P-274); luck check with a constraint-respecting null (P-269, R2.6); quality admission level (P-275); pit_wfa fold capsim Sharpes (M-054, M-056). |
| **Re-running the standard screen and pit_wfa on the A1-fixed code** | The 1D rejection-rate table and "test correctly guarding" (P-013, P-079, P-085); the 26 → 3 reduction's cause (P-068); 1h and daily PIT fold pair counts (P-158, M-047, M-054, M-132); the 17-pair manifest and §6.1-§6.3 (P-112-P-119). |
| **Intraday cache re-fetch** (D1 fabricated bars, D3/D4 snapping — intraday caches untouched) | Price-degeneracy "third pillar" and root cause (P-104-P-110, P-229, P-305); every 1m/3m/1h/4h diagnostic (P-089, P-094, P-119, P-192, P-195, P-209, P-300, P-307-P-309). |
| **Recode of crisis "reappearance" + symmetric censoring** (R3.1, R3.7) and **hysteresis fix** (R6.2) | Persistence (M-014, M-063, M-069), same-sector (M-072), SPY residual (M-071), 8.18% and strength terciles (M-096, M-075). |
| **Exact / clustered tests** (R4.2, R3.3, R3.4, R3.12, R6.9) | z=98.7 and z=3.98 (M-081, M-114); concentration p-values (M-013, M-067); credit proxy (M-121). |
| **Demeaned bootstrap or real White RC over the de-duplicated registry** (S5, R2.1) | Any significance statement for a portfolio Sharpe (P-049, P-124-P-126); any DSR (P-130, P-270, M-094). |
| **Pooled-WFA construction fix** (R5.1) | M-056, M-116. |
| **Production-call EG null on WRDS** (R6.3, R6.4) | §4.2.1 calibration (P-011, P-083). |
| **Full-text citation checks** (cit#9, #45, #47-#50, #61) | GGR contrast (M-009), DFH claims (P-036, P-051), Do & Faff figures (P-040), Kakushadze/Khandani-Lo (P-042), Da & Schaumburg (P-298). |

---

## (6) Proposed revised abstracts

### PROPOSED — PAPER.md abstract (replaces PAPER.md:125-226)

> **PROPOSED (2026-09-27), for Ross's approval. Every number below is from committed code and output; the
> scope of each is stated where it is used.**
>
> Cointegration-based pairs trading usually screens candidate pairs with one full-sample Engle-Granger test.
> Such a test answers "was this relationship ever cointegrated?", not "is it cointegrated now?". We show the
> difference on real CRSP total-return data. NTRS/STT, the project's original headline pair, rejects the
> no-cointegration null over its full history (p ≈ 0.00005, 13,373 daily observations since 1972) but not over
> the last five years (p = 0.561). Three negative-control pairs show the pattern on neither window. A second
> original pair, SHW/UNP, does not replicate on CRSP data (p = 0.061 full sample, 0.054 last five years), and
> we report that too. The recent-window test has about a tenth of the observations, so part of the contrast is
> a power difference. That limitation motivates the scalable rolling-window diagnostic we introduce
> (`coint_fraction_rolling`): the share of fixed-length windows in which the pair is cointegrated, cheap
> enough for 10^6 candidate pairs.
>
> We then apply the production mean-reversion strategy to an episodically confirmed pool of 1,375 daily
> pairs. Each pair was confirmed in a rolling window that uses only data up to that window's end. The pool
> as a whole, however, was assembled with windows up to its build date, so it is not point-in-time with
> respect to the backtest. An audit of our own code (2026-09-26) found that the earlier profit and loss
> accounting re-marked each position with the current bar's hedge ratio and mixed log-spread units with
> dollar costs. On a corrected dollar accounting (hedge ratio fixed at entry, real leg prices, fixed
> notional, business-day Sharpe, OLS hedge, trades whose legs are both USD-denominated, about 31% of the
> total), the strategy loses money in-sample under every entry gate we built: net Sharpe −0.354 to −0.408,
> gross −0.191 to −0.248. Out of sample, the momentum gate loses (−0.296) and the squeeze and combined gates
> are indistinguishable from zero (−0.078 and −0.005). The earlier accounting reported +0.13 to +0.72 for the
> same trades.
>
> A rule-by-rule audit of 101,700 trades finds that every rule executes as coded. It also finds a design
> defect: 54-68% of entries open at or beyond the stop-loss level and are stopped out on the next bar. In
> sample, gross Sharpe stays negative after those trades are excluded.
>
> A gradient-boosted meta-labeler predicts z-score convergence with a purged, embargoed test AUC of 0.607, and
> a random forest reaches 0.609. Neither signal transfers to the strategy's own trades: relabelled by dollar
> profitability, meta-labeling reaches an AUC of only 0.47-0.54.
>
> Not yet established:
> - results for the 69% of trades with a non-USD leg (FX conversion pending);
> - a capital-constrained replay on the corrected accounting;
> - a pair pool rebuilt with an explicit point-in-time cutoff.
>
> Until these are done, we do not attribute the losses to pair discovery. Separately, we derive an exact
> artifact that affects any fixed-window rolling z-score computed on a calendar-padded intraday series: it
> equals (n − 1)/√n, or 15.81σ at n = 252.

### PROPOSED — PAPER_MAGNITUDE.md abstract (replaces PAPER_MAGNITUDE.md:79-189)

> **PROPOSED (2026-09-27), for Ross's approval. Every number below is from committed code and output. The
> two central questions are posed, not answered, until the re-derivations listed at the end are complete.**
>
> A cointegration screen reports a pair as "confirmed" as if that were a timeless property. In fact the label
> records a test run at a particular time, on a particular candidate pool, in a particular market regime. We
> study this *discovery event* on a production screen over a merged universe of ~44,700 symbols. Its daily
> episodic scan covers the ~43,700 symbols with WRDS daily files: CRSP for US listings, and Compustat Global
> in local currency for international ones. Correlation pre-filtering yields 638,095 candidate pairs, which
> are tested in 5,003,637 rolling (pair, window) Engle-Granger tests.
>
> At that scale, multiple-testing discipline decides the result. Uncorrected, the tests would produce about
> 250,000 false positives under the global null. Benjamini-Hochberg across windows confirms 929 pairs. Because
> 81% of those rest on a single window, the pair-level false-discovery rate is bounded at about 9.1%, not the
> nominal 5%. On a 30,000-pair daily sample, Benjamini-Yekutieli confirms 23 pairs where Benjamini-Hochberg
> confirms 35.
>
> Cointegration is episodic. Only a small minority of detected regime spans are cointegrated (8.18%, before
> a pending correction to the span-segmentation rule). Separately, 23 of 78 raw whole-history candidates
> (29%) turn out to be special-purpose acquisition companies whose prices sit on a shared ~$10 trust value.
> This spurious cointegration is visible only through company-identity data. We also derive an exact 15.8σ
> artifact from calendar padding.
>
> Our two central questions:
> 1. Does a full-history screen certify pairs that a point-in-time re-screen would not have found?
> 2. Does the regime at discovery carry information?
>
> Neither is answered here. The earlier evidence for (1) came from fold backtests that used P&L accounting
> later found defective, and the hourly re-screen ran before an alignment defect was fixed. For (2), crisis-
> regime pairs are confirmed more often on a naive pooled test (0.248% vs 0.146%). The difference is not
> significant once crisis periods are treated as 12 clustered episodes, and 27 of the 29 crisis
> confirmations come from the 2008-09 and 2011 episodes. A persistence comparison is withdrawn pending a
> recode.
>
> Still to do:
> - re-run the point-in-time screen on the fixed code with dollar P&L;
> - convert the Compustat Global legs to USD;
> - apply exact or clustered tests to the interaction between (1) and (2).

---

## Notes on method

- Every row was checked against the current text of both papers; line numbers are current at HEAD 8bb2bf0a.
- New observation from this scrutiny, verified by reading code (not in the 09-26 audits): the GapFlag-vs-jump
  "0% overlap" (PAPER.md:2468-2472, PAPER_MAGNITUDE.md:1345-1368) is produced by construction.
  `research/levy_jump_diffusion.py:160-167` masks DATA_GAP bars before the comparison (via
  `research/lead_lag_scan.py:91-96` → `_clean_close`), keeps only the surviving bars' flags, and sets every flag
  to NONE when a frame lacks a `gap_flag` column. Combined with B1/D1 (flags largely NONE at cache time), the
  comparison could not show overlap. Rows P-235, M-103, M-104.
- Inferences not verified by a run, flagged as such in their rows: that D1 produces the price-degeneracy
  market-cap and sector gradients (P-107, P-108; mechanism match only), that the Kalman-vs-OLS "fixed commission"
  mechanism is B3 itself (M-109; follows directly from B3's definition), and the stale-code impact of A1 on the
  26 → 3 reduction (P-068; CODE_REVIEW says "plausibly explains").
- No number outside CR-1..CR-7, the two papers, and the three 09-26 audits was introduced, except two checked by
  arithmetic (598/1,375; 5,003,637 × 0.05) and `wc -l Development.md` (28,572).
