# Working Title

When Does the Market Actually Cointegrate? A Point-in-Time-Safe, Multiple-
Testing-Disciplined Account of Cross-Asset Arbitrage Structure at
Full-Universe Scale

*(Working title. Candidate alternates: "Seven Ways Naive Cointegration
Screening Fails at Scale, and What Fixing Each One Reveals About Market
Structure" / "Artifact Management, Not Signal Discovery: A Production-Scale
Account of Statistical Arbitrage Screening.")*

---

## Status of this document

This is a **living draft**, started 2026-08-24, following the same
three-state convention as `PAPER.md` ([DRAFTED] / [OUTLINED] / [TBD]).
Every numeric claim below is sourced to a specific `docs/FINDINGS.md` entry
or `Development.md` session log, cross-checked against the underlying
`output/research/*.parquet` file before being written here — not narrated
from memory. Where a number is known to be stale (superseded by a
same-session fix) or a re-run is still pending, that is stated explicitly
in place, not silently omitted.

---

## Relationship to `PAPER.md` (the companion paper) — the pivot, stated plainly

CAMARF's original single-paper plan centered a shrinking, increasingly
fragile headline number: "N confirmed pairs, here is their backtest
Sharpe." As the WRDS-primary universe correction and the episodic
point-in-time (PIT) confirmation methodology matured, two things became
clear. First, the confirmed-pair count is not a stable target — it moved
from 23 (yfinance-era) to 3 (post-WRDS reconciliation) to 2 (post-BUG-D105)
to 29 (post-full-universe promotion, this session) across the project's
history, each move a genuine methodology correction, not noise, but a bad
foundation for a paper's single headline claim. Second, and more important:
the project's most defensible, exportable contribution was never the
specific pair set — it is the *methodology* for screening honestly at real
scale, and the seven specific, mechanistically-understood ways naive
screening fails that this methodology surfaced along the way.

**This paper is the lead paper.** `PAPER.md` — the original single-pair-set
backtest writeup (durability-vs-currency framing, §7's Layer 1/2 event-
driven backtest, the 5.24 OOS Sharpe headline) — becomes the **companion,
secondary paper**: a self-contained empirical demonstration that the
methodology developed here has teeth, scoped to CAMARF's own confirmed set
rather than claiming universe-wide generality. Shared machinery
(`UniverseFilter`, `CointScanner`, BH-FDR, the OU spread fit) is
cross-referenced, not duplicated. Ross's framing, stated directly: *"i
think it deserves its own shorter paper but i like the novel angle."*

---

## Abstract [DRAFTED — needs prose polish]

Cross-asset statistical arbitrage research typically screens for
cointegration using a single full-sample test and reports the surviving
pair set as "confirmed." This paper asks a narrower, more falsifiable
question: at real production scale — a merged universe of ~44,700
US-equity, ETF, crypto, forex, commodity, and futures symbols, with
correlation pre-filtering alone generating on the order of 10^5 candidate
pairs — does that naive screening procedure hold up? We find seven
specific, independently-verified ways it does not, each with a
mechanistic explanation rather than a bare statistical anomaly: (1)
uncorrected multiple testing at 10^5-10^6-hypothesis scale would certify
thousands of false positives; rigorous Benjamini-Hochberg discipline is
not optional at this scale, it is load-bearing. (2) Cointegration itself
is episodic, not a stable property — across 158,849 candidate pairs'
full available history, only 9.2% of detected regime-spans are ever
genuinely cointegrated. (3) A genuinely point-in-time re-screen of the
same universe finds a *completely different* pair set than the
full-history screen at every tested historical cutoff, and that
independently-discovered set is not profitable — direct evidence that
pair *discovery*, not just position sizing or backtest overfitting,
carries lookahead bias. (4) At full-universe scale, spurious cointegration
has an identifiable microstructure source beyond statistical coincidence:
blank-check (SPAC) companies trading near a shared $10 trust NAV
pre-merger produce 23 economically meaningless "confirmed" pairs, caught
only by cross-referencing CRSP company names, not by any purely
statistical filter. (5) A Lee-Mykland jump-diffusion test finds real,
economically material return jumps (0.04%-1.64% of bars, 206 symbols)
that share zero overlap with the project's own existing data-quality gap
system — jump risk and data-quality risk are answering different
questions entirely. (6) A purely mechanical implementation choice
(forward-filling non-trading calendar gaps) produces an exact, closed-form
15.8-standard-deviation artifact in rolling z-scores that is
indistinguishable from a genuine statistical anomaly unless traced to its
arithmetic source. (7) Across five independent method-sophistication
comparisons on CAMARF's own production data, added complexity improves
outcomes in exactly one case — and that case is distinguished not by
being "more complex" but by correcting a specific, identifiable false
assumption the simpler alternative depends on. Read together, these
seven findings support a single thesis: production-scale statistical
arbitrage research is dominated by artifact management, not signal
discovery, and the artifacts are neither rare nor random — they recur by
construction, at each stage of the pipeline, for identifiable reasons.

---

## 1. Introduction [OUTLINED]

**1.1 Motivating question.** Does cross-asset cointegration, confirmed via
the standard full-sample Engle-Granger procedure, reflect a real, stable,
tradeable market property — or does it reflect an artifact of how the
screen was run? This is not a rhetorical question in this project's own
history: CAMARF's confirmed-pair count changed by an order of magnitude
multiple times as successive rounds of methodology correction were
applied (§3 below), each time for a *specific, diagnosable* reason. This
paper's contribution is cataloguing those reasons.

**1.2 Why scale matters — and an honest caveat about which findings are
actually at corrected scale as of this writing.** Several of the seven
findings below are scale-dependent — they either do not appear, or appear
too rarely to generalize from, at the ~1,500-2,000-symbol scale most of
this project's own earlier sessions worked at (a scale later found to
itself be a bug — see §2). The largest-scale findings (§4, §5) turn "an
interesting quirk" into "a systematic property of the screening pipeline"
specifically because they run across ~150,000+ candidate pairs. **This
is NOT true of all seven, and this paper does not claim otherwise**: §7
(complexity comparisons) predates the WRDS-primary universe entirely and
runs on a 22-pair confirmed set; §9 (calendar padding) is explicitly a
single-pair, universe-scale-independent artifact by construction (see
§2's own scoping note); and, most importantly, **§4 and §5's own
158,849-candidate-pair number is dated 2026-08-13 — eleven days before
the universe-undercount bug described in §2 was found and fixed on
2026-08-24.** The corrected-scale re-run of the exact script producing
that number was still in progress (crashed twice from separate OOM causes,
both fixed, third attempt running) as of this writing. §4 and §5 are
reported here as the best currently-available real numbers, not as
already-verified-at-corrected-scale — see §12 for the same disclosure
restated at each affected finding, and §14 for the pending re-run.

**1.3 Structure.** §2 establishes the real universe scale (and a real bug
in claiming it, found and fixed this session). §3 summarizes the shared
statistical machinery (reused from `analysis.py`, not reimplemented, per
this project's own working convention — every finding below runs
production code, not a parallel research-only reimplementation). §4-§10
present the seven findings, each with its own honest scope/limitation
statement inline, not deferred to a single limitations section. §11
synthesizes them into the paper's central thesis. §12 states biases and
limitations directly, project-convention style. §13 is the relationship
to the companion backtest paper. §14 is future work.

---

## 2. Data and Universe [DRAFTED — 2026-08-24]

Full cross-reference: `PAPER.md` §3 for the complete data-source
description (yfinance primary daily/intraday, WRDS/CRSP primary for
daily-and-coarser US equity/ETF with Compustat Global fallback, IBKR
supplemental deep-history for confirmed pairs only). This section states
only what is specific to this paper's findings.

**The universe-undercount bug, disclosed rather than smoothed over.**
Several of the scripts producing findings in this paper (and, separately,
several unrelated "full universe" research scripts caught in the same
audit) were found this session to be silently sampling from an old,
narrow, yfinance-only cache directory (~1,566-1,730 symbols) while their
own docstrings and log messages claimed "full universe" coverage. The
real, current merged universe — yfinance + WRDS/CRSP + Compustat Global +
Binance + IBKR, deduplicated — is **~44,700 symbols**
(`universe_loader.load_full_universe()`, the single project-wide loader
all such scripts now call). This is stated here as a methodological
honesty point in its own right, not just a bug-log entry: a "full
universe" claim in statistical arbitrage research is only as strong as
the loader backing it, and this project shipped several such claims that
were quietly wrong by more than an order of magnitude before this
session's audit. **Not every "full universe" number in §4-§10 below
postdates this fix — stated plainly, not smoothed over**: §4 and §5's
158,849-candidate-pair figure is dated 2026-08-13, predating this fix by
eleven days; the corrected-scale re-run was still in progress as of this
writing (§1.2, §12). §10's complexity comparisons predate the WRDS-primary
universe entirely (22-pair confirmed set, not full-universe scale by
design). §9's calendar-padding derivation is universe-scale-independent
by construction. §6, §7, and §8's underlying data ARE at the corrected,
current universe scale.

**Scope of the WRDS-sourced findings specifically** (§4, §6, §7): limited
to symbols with a fetched `output/cache/wrds/*_1D.parquet` file —
currently ~43,662 of the ~44,700-symbol merged universe (1,032 files
0-byte/corrupted from an earlier interrupted bulk fetch, skipped and
logged, not silently dropped — see Development.md). This is a daily-only
scope; WRDS/CRSP carries no intraday data, so these findings cannot speak
to intraday cointegration structure, only daily.

---

## 3. Shared Methodology [DRAFTED]

Every finding below reuses one or more of the following, unmodified,
production `analysis.py` components — stated once here rather than
re-derived per finding:

- **`UniverseFilter.correlation_matrix`/`candidate_pairs`** (and, at full
  universe scale, the memory-bounded `chunked_pearson_candidate_pairs`
  variant — block-diagonal splitting, bit-exact equivalent to the direct
  call, built after a real OOM crash at ~18,283 symbols, itself an
  instructive small case of this paper's own §9-adjacent thesis: engineering
  detail, not statistics, determines whether a screen at scale runs at
  all) — the Pearson correlation pre-filter, |ρ| ≥
  `Config.UNIVERSE.MIN_PEARSON_CORR`.
- **`_eg_worker`** — the two-step Engle-Granger cointegration test,
  both-directions max-combination logic, identical to `CointScanner.scan`.
- **`_benjamini_hochberg`** — step-up Benjamini-Hochberg false-discovery-rate
  correction, `Config.STATS.FDR_ALPHA`.
- **Episodic/rolling confirmation** — a pair qualifies not on a single
  whole-history verdict but via a rolling window (`EPISODIC_WINDOW_BARS`
  = 2520 bars, ~10 trading years; `EPISODIC_STEP_BARS` = 252, ~annual
  re-evaluation), unioning each window's qualifying pairs across the full
  scan — built specifically because a fixed whole-history verdict cannot
  distinguish "cointegrated for 3 of the last 30 years" from "cointegrated
  throughout."
- **Regime-span hysteresis** — a state change (cointegrated <-> not)
  confirms only after persisting ≥3 consecutive windows
  (`MIN_REGIME_WINDOWS=3`), preventing a single borderline p-value from
  fragmenting a real multi-year regime into noise.

No finding below introduces a new statistical test without disclosing it
as new (only §8's Lee-Mykland jump test and §10's regime-segmentation
hysteresis are genuinely new machinery; both were verified against
synthetic ground truth before being run on real data — `debug/_verify_*.py`
for each, referenced at the finding).

---

## 4. Finding 1 — Multiple-Testing Discipline Is Load-Bearing, Not Optional, at Real Scale [DRAFTED]

**The scale.** After the Pearson correlation pre-filter, the full-universe
episodic scan (§6 below, same underlying data) produces **158,849
candidate pairs**, tested across a rolling window for a total of
**1,197,576 individual (pair, window) Engle-Granger tests**
(`wrds_deep_history_episodic_scan_tier3_windows.parquet`, Finding #28).
Separately, a full-sample (single-window) EG cascade across the corrected
full universe produced 78 raw whole-history-significant candidates before
any structural/identity/SPAC contamination filtering (§7). At either
scale, running these tests at a nominal α=0.05 with no correction would
be expected to certify thousands of false positives by chance alone —
this is not a hypothetical: 1,197,576 tests × 0.05 ≈ 59,879 expected false
positives under the global null, dwarfing any plausible true-positive
count.

**What BH-FDR buys, and what it doesn't.** Benjamini-Hochberg step-up
correction, applied per timeframe (matching `Config.STATS.FDR_ALPHA`),
controls the *expected proportion* of false discoveries among rejections
— not the count, and not with certainty for any single rejected
hypothesis. A direct robustness check against the more conservative
Benjamini-Yekutieli correction (`research/bh_fdr_dependence_check.py`,
extended in `research/bh_vs_by_full_universe.py`) is the honest test of
whether BH's independence-ish assumption is doing real work here: BY
makes no assumption about dependence structure among the tests (a
real concern for cointegration tests on overlapping windows and
correlated assets) and is provably more conservative. **Disclosed
incompleteness, stated directly rather than smoothed over**: the most
recent run of this specific comparison (`bh_vs_by_full_universe.py`) used
a disclosed N=300-symbol random sample from a since-corrected loader (the
§2 universe-undercount bug applied to this script too, fixed this
session but not yet re-run against the real ~44,700-symbol population as
of this writing). Re-running it against the corrected universe is a
named, tracked pending task (§14), not a silently-abandoned one — this
paper does not report a full-scale BH-vs-BY split until that re-run
exists.

**What this pillar contributes as a literature critique, stated plainly.**
Cross-asset cointegration papers that report "N significant pairs" from a
correlation-prefiltered candidate pool without disclosing (a) the
candidate pool size and (b) the multiple-testing correction applied are,
at this project's demonstrated scale, almost certainly overstating the
reliability of their headline pair set. This is not a claim about any
specific published paper (which this project cannot verify without
access to that paper's own candidate-pool accounting) — it is a testable,
quantified standard this project proposes and holds itself to, stated as
a methodological recommendation rather than an accusation.

---

## 5. Finding 2 — Cointegration Is Episodic, Not a Persistent Property [DRAFTED, Finding #28]

**Scale disclosure, stated here rather than only in §1.2/§12**: the
158,849-candidate-pair figure below is dated 2026-08-13 — eleven days
before the §2 universe-undercount fix. The corrected-scale re-run (same
script, `wrds_deep_history_episodic_scan.py`) was still in progress as of
this writing (two OOM crashes diagnosed and fixed, third attempt
running). This finding is reported as the best currently-available real
number, not as already re-verified at the corrected ~44,700-symbol scale
— see §14.

Segmenting each of the 158,849 candidate pairs' full available history
into contiguous cointegrated/non-cointegrated regime spans (via the
hysteresis rule in §3) produces:

| state | n_spans |
|---|---|
| not_coint | 158,011 |
| coint | 16,064 |

**Only 9.2% of all detected regime spans across the full candidate
universe are ever genuinely cointegrated** at any point in their history.
Of the cointegrated spans, strength splits almost exactly evenly by
construction (global cross-pair terciles, not per-pair — a per-pair
tercile split was tried first and found statistically meaningless at
~0.1 spans/pair average, a real design bug caught by running against
real data rather than assumed correct from the synthetic test alone):
strong=5,349, moderate=5,366, weak=5,349.

**What this tells us about market structure.** A pair passing a
whole-history cointegration test is not evidence of a stable, ongoing
economic relationship — it is evidence that the relationship held during
*some* sub-period of the tested history, usually a minority of it. This
directly motivates §6's negative-backtest finding: if genuine
cointegration is this episodic, a full-history screen's implicit
assumption (a certified pair remains tradeable going forward) is exactly
the assumption most likely to fail.

---

## 6. Finding 3 — Pair Discovery Itself Carries Lookahead Bias [DRAFTED, PAPER.md §7.3.1]

**The test.** At each of 4 historical fold cutoffs (2 expanding-window, 2
rolling-window), the full production screening pipeline — correlation
pre-filter, EG + BH-FDR, `coint_fraction_rolling`, structural-pair
exclusion, secondary-evidence override — is re-run using *only* data up
to that cutoff, exactly as a live deployment would have seen it, then
backtested forward through the fold's test window with the unmodified
`BacktestEngine`.

**Result (current WRDS-primary universe, 1,576 symbols, post-BUG-D99/
BUG-D105 fixes):**

| Fold | PIT-Confirmed Pairs | Trades | Portfolio Sharpe |
|---|---|---|---|
| expanding/fold1 | 0 | 0 | NaN |
| expanding/fold2 | 2 | 32 | **−1.0121** |
| rolling/fold1 | 0 | 0 | NaN |
| rolling/fold2 | 1 | 5 | **+0.2547** |

3 of 4 folds find zero pairs or a negative Sharpe. The single positive
data point (`rolling/fold2`, +0.2547 Sharpe, 5 trades on `AUB/XHR@1h`) is
reported honestly rather than omitted — but 5 trades cannot overturn the
aggregate negative finding.

**An earlier, more severe version of the same test** (pre-WRDS universe,
retained for provenance) found that at every one of 3 historical
checkpoints, the point-in-time screen discovered a *completely different*
pair set (19, 6, and 3 pairs) than the known full-history-confirmed set —
zero overlap — and that independently-discovered set lost money at every
fold (Sharpe range −0.72 to −1.04). Critically: **a real implementation
bug was caught and fixed before trusting this result**, and fixing it made
the finding *more* damning, not less — the uncorrected version showed
declining-but-positive Sharpes (an alignment-mode bug inflating bar counts
~5.85x); the corrected version is uniformly negative. A separate check
confirmed the screening function itself is trustworthy (it independently
reproduces 16 of 17 known confirmed pairs when run on the exact
full-history window production itself uses) — the zero-overlap,
negative-Sharpe result at earlier cutoffs is a real property of the
*discovery process under causal constraints*, not a bug in the
diagnostic.

**What this tells us, and what it does not.** This is not evidence the
known confirmed pairs' cointegration is spurious — it is direct,
quantified evidence that a live, causally-run version of this pipeline
would not have discovered and profitably traded those same pairs at those
points in time. Combined with §5's episodic finding, the picture is
coherent: genuine cointegration is real but transient, and a screening
process that only looks backward over the full available history will
systematically certify relationships whose most recent episode has
already ended, or has not yet begun — either way, not currently
tradeable by a causal observer.

---

## 7. Finding 4 — SPAC NAV-Clustering: A Corporate-Action Microstructure Source of Spurious Cointegration at Scale [DRAFTED, 2026-08-24, this session]

**Context.** A full-universe EG+FDR cascade (`full_universe_eg_confirmation.py`)
found 78 raw whole-history-significant candidate pairs. Promoting these
into CAMARF's production confirmed-pair set required a real, multi-round
data-integrity vetting — not a rubber stamp — that surfaced four distinct
contamination classes, three of them identity/structural bugs (already-
known filter gaps, applied but not previously wired into this specific
script's driver) and one genuinely new: **SPAC NAV-clustering**.

**The mechanism.** Blank-check (SPAC) companies trade near a shared ~$10
trust-account NAV in the period before a merger is announced or
completed. Two economically *unrelated* SPACs, both sitting near $10 with
low volatility, will show a strong, statistically significant
cointegration relationship purely from this shared, mechanical price
anchor — not from any real co-movement in the underlying businesses
(which, pre-merger, do not yet exist as operating companies at all in
most cases). This is not a data-quality bug; it is a real, if spurious,
statistical property of an entire class of securities, invisible to any
purely price-based filter.

**Detection.** No existing structural/identity filter catches this (SPACs
are not duplicate tickers, not cross-listings, not share classes — they
are genuinely distinct legal entities that happen to share a price
regime). Detection required cross-referencing CRSP's `comnam` (company
name field) against SPAC naming conventions (`ACQUISITION CORP`/`ACQ
CORP`/`MERGER CORP`, case-insensitive regex), resolved through the same
unambiguous permno lookup used for the identity-alias check elsewhere in
this promotion. This confirmed **22 real SPACs by name** among the 78
candidates (e.g. `ALTU` in this dataset is "Altitude Acquisition Corp,"
not the unrelated pharmaceutical company that has historically shared
that ticker — resolved definitively via the permno-level lookup, not
ticker matching alone).

**Disclosed non-exhaustiveness.** The regex is a real, working heuristic,
not a complete SPAC taxonomy. One SPAC (`BRIV` = "B Riley Principal 250
Merger") slipped through because its name ends in "Merger" rather than
"Merger Corp," caught only in manual dry-run review before the real
(non-dry-run) write. A known further gap: the "Social Capital Hedosophia"
SPAC family uses no Acquisition/Acq/Merger token in its name at all and
would not be caught by this regex — stated here as a known limitation,
not silently assumed solved.

**Net effect on the promotion**: of the 78 raw candidates, 23 were
excluded as SPAC-contaminated (22 by regex + 1 manual catch), alongside
22 same-GVKEY-number duplicates and 6 WRDS ticker/PERMNO alias or
self-pair collisions (0 caught by the pre-existing structural-pair
filter, since this specific candidate set happened not to contain that
particular contamination class) — 27 of 78 candidates survived to
production.

**What this tells us about market structure.** At full-universe scale, a
meaningful fraction of "statistically confirmed" cointegration (23 of 78
raw candidates here, ~29%) is attributable to a single, specific
corporate-action microstructure mechanism that requires real-world
company-identity knowledge to detect — pure statistical machinery, however
rigorous, cannot see it. This generalizes as a methodological warning
beyond SPACs specifically: any security class with a mechanically shared
near-constant price anchor (money-market-adjacent ETFs, certain
closed-end funds trading near NAV, warrants near expiry) is a candidate
for the same failure mode, and a production screening pipeline operating
at real universe scale needs an explicit taxonomy of these mechanisms,
not just a statistical significance threshold.

---

## 8. Finding 5 — Return Jumps Are Invisible to Existing Data-Quality Machinery [DRAFTED, Finding #14]

**The test.** A Lee & Mykland (2008) jump-diffusion test (bipower-variation
local volatility estimator, robust to jumps by construction, flagged
against the test's exact asymptotic critical value) is compared against
CAMARF's existing `GapFlag` system (NONE/FILL/NO_ACTIVITY/HALT/DATA_GAP/
SPARSE), which tracks provider-side data continuity, not price dynamics.

**Verification caught a real implementation bug before trusting any real
result**: an early version misplaced a square root (bipower variation
estimates variance, so the square root must wrap the entire product, not
just one term), flagging 95.5% of a pure-diffusion synthetic series as
jumps against a 1% nominal rate. Post-fix: 0/5000 false positives on pure
diffusion, 5/5 injected jumps recovered exactly.

**Real-data result at production scale, PIT-safe.** Run against all 707
PIT-safe (pair, timeframe) combinations discovered by the episodic screen,
640 symbol@TF rows survived the alignment/clean-returns filter, spanning
206 unique symbols (all at 1D — intraday history for most PIT-safe pairs
is too short/gappy to pass at this scale, a disclosed data-availability
constraint). **0.0% overlap between statistically-detected jumps and
non-NONE GapFlag bars, in all 640 of 640 rows.** Jump frequency: mean
0.51%, median 0.47% of bars. Jump-adjusted (continuous-only) volatility
is 5.8-7.3% lower on average than naive full-sample volatility.

**What this tells us about market structure.** GapFlag and jump-diffusion
detection are not two views of the same phenomenon, and this is not a
one-pair idiosyncrasy — it replicates exactly (0% overlap, at scale) across
206 symbols. A price series can be perfectly clean by every data-continuity
measure this project's own infrastructure checks for, and still carry
real, economically material jump risk that infrastructure has no
mechanism to see, because gap-continuity and jump-magnitude are answering
different questions about the same series. This is a real, disclosed
candidate for a volatility-estimator refinement (not yet wired into
production risk/stop logic — a deliberate v1 research-only scope), and a
broader methodological point: "clean data" (no missing bars, no halts)
and "well-behaved returns" (no large discontinuous moves) are
independent properties that a rigorous pipeline needs to check
separately, not treat as a single data-quality gate.

---

## 9. Finding 6 — A Purely Mechanical Artifact Can Produce an Exact 15.8-Sigma False Anomaly [DRAFTED, PAPER.md §4.5]

**The mechanism.** Reindexing intraday bars onto a continuous calendar and
forward-filling non-trading minutes (a common, often-default convenience
in time-series tooling, e.g. `reindex().ffill()`) silently contaminates
any fixed-width rolling-window statistic computed downstream. When a
rolling window straddles a forward-filled run, it contains `(n-1)`
identical padded values and exactly 1 real value.

**The exact, derived artifact.** For a rolling z-score over a window of
`n` points with `(n-1)` identical values and 1 differing, the result is
*exactly* `(n-1)/√n` — pure arithmetic, not a statistical approximation.
For `n=252`: `251/√252 = 15.8115...`. This exact value was observed,
matched to 10 significant digits, in real entry-signal output before
diagnosis: 4 of an early 32-example labeled training set (12.5%) had
`|z_entry| > 10`, all firing at exactly market open, all on the
calendar-padding day boundary.

**Why this generalizes beyond CAMARF.** This is a standard, often-default
convenience in general time-series tooling, not a CAMARF-specific
choice. Any intraday pairs-trading or stat-arb research using fixed-window
rolling z-scores on a calendar-padded series inherits this exact failure
mode at every session boundary, for every asset, by construction. The
artifact's size (15.8σ) and mathematical cleanness (an exact closed form,
not a plausible-but-fat-tailed outlier) make it a strong, testable
candidate explanation for anomalously fat-tailed entry-signal
distributions reported elsewhere in intraday mean-reversion research
without being traced to this specific mechanical cause — stated as a
testable hypothesis for a reader to check against their own pipeline, not
an accusation against any specific published study.

**The fix, briefly** (full account: `Development.md` BUG-D45): compute
rolling statistics on a compacted, real-bars-only sub-series (gap-flag
excluded), then scatter results back onto the full-length index with
padded positions left missing — never feeding a padded value into any
entry-signal computation or training label.

**What this tells us, as the odd one out among the seven.** Findings §4-§8
and §10 are about the market's actual statistical structure (or a real
data-generating mechanism the market exhibits). This one is not — it is a
pure engineering artifact, entirely independent of any real price
dynamics, that is nonetheless capable of producing a numerically enormous,
suspiciously anomaly-shaped signal. Its inclusion here is deliberate:
production-scale statistical arbitrage research cannot distinguish "real
market structure" from "a bug in how the calendar was handled" without
this kind of exact, closed-form derivation — a purely empirical anomaly
hunt, however careful, would have reported this as a genuine finding.

---

## 10. Finding 7 — Complexity Earns Its Keep Only When It Corrects a Specific False Assumption [DRAFTED, Finding #1]

Five independent method-sophistication comparisons across this project —
position sizing, hedge-ratio estimation, portfolio concentration — each
pit a more sophisticated method against a simpler alternative on the same
real production data:

- **Loss**: Hierarchical Risk Parity (true cross-pair covariance,
  hierarchical clustering) vs. simple risk-parity (per-pair volatility
  only). HRP OOS Sharpe 5.3752 vs. 5.8689 — HRP loses.
- **Loss**: Kalman slope+intercept hedge ratio vs. origin-only Kalman.
  The 2-state version is *provably* better-specified statistically
  (tighter, more stationary spread on every one of 22 pairs, ADF
  improves on 15/22) but produces a *worse* trading signal (fixed-share
  Sharpe 2.35 vs. OLS's 12.28) — traced to a mechanistic cause (fixed
  per-share commission costs are invariant to spread scale, so a
  tighter spread's smaller gross P&L is disproportionately eaten by
  cost), not merely "Kalman lost."
- **Loss**: Equal Risk Contribution (constrained variance-of-contribution
  optimization) vs. simple inverse-cluster-size sizing. Simple sizing
  wins on Sharpe (0.7216 vs. 0.6933) and avoids ERC's real cost of
  concentrating up to 27% of the portfolio into 1-2 low-variance pairs.
- **Loss**: continuous eigenvalue-penalized position weighting vs. the
  same simple inverse-cluster-size scheme. Every variant tested
  underperforms (best 0.65-0.69 vs. simple's 0.7216), including a
  Marchenko-Pastur-adaptive version built specifically to fix an
  eigenvalue-degeneracy instability caught during verification (not real
  data) — the fix was necessary for correctness but did not change the
  outcome ranking.
- **Win**: Meucci's eigenvalue-based Effective Number of Bets vs.
  Grinold-Kahn's equicorrelation breadth. Grinold-Kahn assumes uniform
  correlation and, given this portfolio's near-zero *average* pairwise
  correlation (ρ̄=0.0039), reports almost no diversification loss
  (BR_eff=19.5 of 21). Meucci's eigen-decomposition detects that the
  real correlation structure is *clustered* (specific pair-pairs at
  0.29-0.31, most at ~0) and correctly reports a materially lower
  ENB=9.78 — the simpler method's uniform-correlation assumption is
  actively wrong for this portfolio, not merely less refined.

**The pattern, read honestly rather than resolved into a false moral.**
"Simple beats complex" would overstate four losses into a rule the fifth
result directly contradicts. What actually distinguishes the win: in the
four losses, the simpler method makes a *different, adequate* simplifying
assumption that happens to interact better with a downstream cost or
noise factor the complex method ignores. In the win, the simpler method's
specific assumption (uniform correlation) is demonstrably false for this
data. **Complexity pays off specifically when it corrects an identified
false assumption in the simpler alternative — not whenever it adds more
parameters.** This is itself a decision rule with predictive value: before
building a more complex method, the diagnostic question is "does the
simpler version's specific assumption actually hold here," not "is the
simpler version too crude" in the abstract.

---

## 11. Synthesis: What Seven Failure Modes Say About Market Structure [DRAFTED]

Read individually, §4-§10 are seven separate bug-fixes and diagnostics.
Read together, against Ross's own framing question — *what does BH-FDR
discipline at scale tell us about the structure, macro and microstructure
of the market, and how does it tie into regime segmentation, the negative
backtest, SPAC taxonomy, jump-diffusion, complexity, and calendar
padding?* — a single thesis emerges:

**Production-scale statistical arbitrage research is dominated by
artifact management, not signal discovery, and the artifacts are neither
rare nor random — each recurs by construction, at a specific pipeline
stage, for an identifiable reason.**

Concretely, laid out as a pipeline-stage map:

1. **Before any test is run at all**, the sheer scale of the candidate
   pool (§4: 10^5-10^6 hypotheses) means uncorrected significance testing
   would certify a false-discovery flood by pure combinatorics — this is
   the foundational artifact every later finding is built on top of, and
   the reason this paper insists on disclosing candidate-pool size and
   correction method as a minimum bar for any cointegration claim.

2. **Even after correction, a "confirmed" pair is not a stable object**
   (§5): genuine cointegration occupies a minority (9.2%) of a pair's own
   history. This is a real, quantified property of *market structure
   itself*, not a screening artifact — it says cross-asset relationships
   that matter for arbitrage are transient regimes, not persistent
   equilibria, a finding with real implications for how any static
   confirmed-pair list should be treated in production (as a
   time-decaying credential, not a permanent certificate).

3. **That transience has a direct, causal consequence for discovery
   itself** (§6): a screening process that only looks backward will
   systematically certify pairs whose tradeable episode has already
   ended or has not yet begun. This is the paper's single most severe
   finding — it means the failure mode is not confined to backtest
   overfitting (§6.7's DSR-style variant search) but reaches the pair
   *selection* step, which most published pairs-trading work treats as
   a given input, not something requiring its own causal validation.

4. **Some of what a static screen certifies is not "transient real
   cointegration" at all but a specific, nameable corporate-action
   mechanism** (§7: SPAC NAV-clustering, 29% of one candidate batch).
   This is a microstructure-level finding: certain security classes
   share mechanical price anchors unrelated to their underlying
   businesses, and no purely statistical filter — however well-corrected
   for multiple testing — can distinguish this from genuine
   co-movement without real-world identity knowledge layered on top.

5. **Separately from cointegration entirely, the underlying return
   process itself carries structure invisible to standard data-quality
   checks** (§8: jump risk, 0% overlap with gap-continuity flags across
   206 symbols). This generalizes the paper's core caution beyond
   cointegration screening specifically: "the data looks clean" and "the
   return process is well-behaved" are independent claims, and conflating
   them is itself a scale-invisible artifact until tested broadly enough
   to see it replicate.

6. **Not every apparent anomaly is market structure at all** (§9: the
   15.8σ calendar-padding artifact). A purely mechanical implementation
   choice, entirely disconnected from real prices, can mimic a
   statistically enormous "finding" with mathematical exactness. This is
   the paper's methodological control case: without deriving the exact
   closed form and matching it digit-for-digit to observed output, this
   artifact would have been reported, in good faith, as a real result.

7. **And finally, once all six of the above are correctly diagnosed and
   handled, adding more sophisticated modeling on top is not free** (§10):
   it helps only when it targets a specific, identified false assumption,
   which is itself a research-methodology finding as much as a strategy
   one — it argues for diagnosing *why* a simpler baseline might fail
   before reaching for a more complex replacement, the same discipline
   this paper applies to the six market-structure findings above it.

**The thesis restated, plainly**: none of these seven findings is
surprising in isolation — multiple-testing correction, lookahead bias,
corporate-action contamination, and implementation bugs are each,
individually, well-known concerns in the quantitative-research literature.
What this paper contributes is running all seven checks, disclosed and
verified, against the *same* real, full-scale (~44,700-symbol) production
pipeline, and showing that at real scale every one of them is not a
theoretical caveat but an active, quantified, currently-occurring failure
mode — which is a different and stronger claim than citing each concern
individually the way most applied papers do.

---

## 12. Honest Limitations and Biases, Stated Directly [DRAFTED]

Following this project's own stated discipline (never silently correct
away a known bias) — restated per finding here rather than left to a
single catch-all section, since each has a different scope:

- **§4 (BH-FDR)**: the BH-vs-BY comparison's most current numbers are
  from a disclosed N=300 sample of a since-corrected universe loader, not
  yet re-run at full ~44,700-symbol scale. This paper does not claim a
  resolved BH-vs-BY verdict until that re-run exists (tracked, §14).
- **§4/§5 (BH-FDR scale claim / regime segmentation)**: the underlying
  158,849-candidate-pair number for both is dated 2026-08-13, predating
  the §2 universe-undercount fix (found and fixed 2026-08-24) by eleven
  days. Both findings are reported as the best currently-available real
  numbers; neither is claimed to already reflect the corrected
  ~44,700-symbol universe. The corrected-scale re-run was in progress as
  of this writing (§14).
- **§5/§6 (regime segmentation / negative backtest)**: both are daily/
  hourly-scale findings on the current WRDS-primary or yfinance-cached
  universe respectively; neither has been extended to the full
  intraday-timeframe granularity CAMARF's production pipeline also
  screens.
- **§7 (SPAC taxonomy)**: the regex-based detector is disclosed as
  non-exhaustive (the Social Capital Hedosophia SPAC family is a known,
  named gap). The 27-of-78 promotion also does not re-apply the
  `coint_fraction_rolling` stability threshold production's normal
  pipeline applies later — an inclusion-looseness choice, not an
  identity-correctness bug, disclosed in the promotion script's own
  runtime output.
- **§8 (jump-diffusion)**: PIT-safe result is 1D-only by data
  availability (intraday history for most PIT-safe pairs fails the
  200-clean-returns filter) — the 5.8-7.3% vol reduction at 1D should
  not be assumed to hold at intraday granularity, where the original
  single-pair result (26-42% reduction) suggests the effect may be
  considerably larger, not smaller, at finer granularity.
- **§9 (calendar padding)**: the claim about *other* published research
  inheriting this exact failure mode is explicitly stated as an
  unverified, testable hypothesis, not a checked fact about any specific
  external paper.
- **Universe-wide**: the equity/ETF universe remains a current-constituent
  snapshot (survivorship bias, disclosed per this project's standing
  convention, not corrected away) for all findings in this paper.
- **AI-tool disclosure**: full cross-reference to `PAPER.md` §9's AID
  Framework role taxonomy and tool-transparency sections — unchanged,
  applies identically to this paper's own production.

---

## 13. Relationship to the Companion Backtest Paper [DRAFTED]

`PAPER.md` remains the empirical demonstration that this paper's
methodology, applied end-to-end to CAMARF's own confirmed pair set,
produces a real, disclosed, non-overclaimed backtest result (its own
5.24 OOS Sharpe headline, itself qualified directly by this paper's §6
negative-backtest finding, which `PAPER.md` §7.3.1 already houses and
this paper reproduces and foregrounds). The two papers share
infrastructure (§3 above) and a bibliography; they differ in scope and
headline claim, per the framing decision stated at the top of this
document.

---

## 14. Future Work [OUTLINED]

- Re-run `bh_vs_by_full_universe.py` against the corrected
  ~44,700-symbol universe (§4's disclosed pending item) — the single
  most important open item before this paper's §4 claim can be
  considered scale-complete.
- Extend §6's negative-backtest test to the current 29-pair confirmed set
  (post-§7 promotion) — the existing result predates this session's
  full-universe promotion.
- Extend §8's jump-diffusion PIT-safe result to intraday granularity, once
  enough PIT-safe intraday pairs exist to clear the 200-clean-returns
  filter.
- A more exhaustive SPAC/NAV-clustering taxonomy (§7), covering naming
  conventions the current regex misses (e.g. the Social Capital
  Hedosophia family).
- Connect §5's regime-strength segmentation to §6's PIT-confirmation
  precision — does a pair's regime strength (strong/moderate/weak,
  §5) predict whether it survives a genuine point-in-time re-screen? Not
  yet asked of the data.

---

## References

Shared bibliography with `PAPER.md` §2 — see that section for full
sourcing status of each citation. This paper adds no new external
citations beyond what §2 already covers (Engle-Granger, Benjamini-
Hochberg/Yekutieli, Lee & Mykland 2008, Meucci, Grinold-Kahn).
