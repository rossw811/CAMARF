# The Discovery Event: Causal Validity and Regime Information in
Statistical Arbitrage Pair Screening

*(Reframed 2026-09-02, narrowing from the 7-finding "Unwarranted
Confidence" draft below. Ross's direct approval: "i like the new rough
title and the paper stuff... let's change paper to reflect [it]."
Rationale: a paper built around two findings connected by one real
mechanism is a stronger, more citable contribution than seven co-equal
bug-fixes under a synthesis thesis, however honest that synthesis was.
The throughline: a cointegration screen's output — "pair X is confirmed"
— is conventionally treated as a static, timeless fact once a p-value
clears threshold. This paper shows that's wrong in two complementary
directions, on the same production-scale (~44,700-symbol) pipeline. §4
shows the discovery event's TEMPORAL DIRECTION (backward-looking
full-history vs. causal point-in-time) is a bias that must be corrected
— a full-history screen certifies pairs a causal re-screen would not
have found, and would not have profited from. §5 shows the discovery
event's REGIME CONTEXT (the market conditions a pair was first found in)
is a signal current practice discards — pairs first discovered in a
crisis-VIX regime confirm at a significantly higher rate and persist
across regime changes significantly more, not less, than calm-discovered
pairs. Same underlying object — the discovery event — audited for
causal validity in one case, mined for predictive information in the
other. That symmetry is the paper's actual contribution: pair discovery
is an event with a timestamp and a context, not a timeless fact, and
both what it costs you to ignore that and what it can buy you are
demonstrated on the same real pipeline. The other six findings from the
earlier draft (multiple-testing discipline, episodic cointegration, SPAC
contamination, jump-diffusion vs. data quality, the calendar-padding
artifact, and complexity-only-earns-its-keep-when-it-fixes-a-specific-
assumption) are real, verified, and kept — as supporting evidence that
this same pipeline demands rigor at every stage, not just at discovery —
see §7. See §1.4 for the two-pillar argument stated in full, and §6 for
the reframed synthesis.)*

*(Earlier titles, kept for provenance per this project's "document what
was tried and reverted" discipline, not live: "Unwarranted Confidence:
What You Were Entitled to Believe Less Than You Thought in
Production-Scale Statistical Arbitrage Research" (2026-09-01 title, the
7-co-equal-finding frame — see the archived structure notes throughout
this document for what changed and why) / "When Does the Market Actually
Cointegrate? A Point-in-Time-Safe, Multiple-Testing-Disciplined Account
of Cross-Asset Arbitrage Structure at Full-Universe Scale" / "Seven Ways
Naive Cointegration Screening Fails at Scale, and What Fixing Each One
Reveals About Market Structure" / "Artifact Management, Not Signal
Discovery: A Production-Scale Account of Statistical Arbitrage
Screening.")*

---

## Status of this document

This is a **living draft**, started 2026-08-24, following the same
three-state convention as `PAPER.md` ([DRAFTED] / [OUTLINED] / [TBD]).
Every numeric claim below is sourced to a specific `docs/FINDINGS.md` entry
or `Development.md` session log, cross-checked against the underlying
`output/research/*.parquet` file before being written here, not narrated
from memory. Where a number is known to be stale (superseded by a
same-session fix) or a re-run is still pending, that is stated explicitly
in place, not silently omitted.

---

## Relationship to `PAPER.md` (the companion paper), the pivot stated plainly

CAMARF's original single-paper plan centered a shrinking, increasingly
fragile headline number: "N confirmed pairs, here is their backtest
Sharpe." As the WRDS-primary universe correction and the episodic
point-in-time (PIT) confirmation methodology matured, two things became
clear. First, the confirmed-pair count is not a stable target: it moved
from 23 (yfinance-era) to 3 (post-WRDS reconciliation) to 2 (post-BUG-D105)
to 29 (post-full-universe promotion, this session) across the project's
history. Each move was a genuine methodology correction, not noise, but
still a bad foundation for a paper's single headline claim. Second, and
more important, the project's most defensible, exportable contribution was
never the specific pair set. It is the *methodology* for screening
honestly at real scale, and the specific, mechanistically-understood
ways naive screening fails that this methodology surfaced along the way.

**This paper is the lead paper.** `PAPER.md`, the original single-pair-set
backtest writeup (durability-vs-currency framing, §7's Layer 1/2
event-driven backtest, the 5.24 OOS Sharpe headline), becomes the
**companion, secondary paper**: a self-contained empirical demonstration
that the methodology developed here has teeth, scoped to CAMARF's own
confirmed set rather than claiming universe-wide generality. Shared
machinery (`UniverseFilter`, `CointScanner`, BH-FDR, the OU spread fit) is
cross-referenced, not duplicated. Ross's framing, stated directly: *"i
think it deserves its own shorter paper but i like the novel angle."*

---

## Abstract [DRAFTED, reframed 2026-09-02]

Cross-asset statistical arbitrage research typically screens for
cointegration using a single test and reports the surviving pair set as
"confirmed" — a static, timeless fact about the pair, independent of
when or how the screen was run. This paper argues that assumption is
wrong, and provides evidence for that in two directions, using the same
production screening methodology (a merged universe of ~44,700
US-equity, ETF, crypto, forex, commodity, and futures symbols;
correlation pre-filtering alone generates 638,095 candidate pairs across
5,003,637 (pair, window) cointegration tests in the larger of the two
runs). A pair's *discovery event* — the specific moment and market
context in which it first clears a screen — carries information a
binary confirmed/not-confirmed label discards, in two opposite practical
directions.

**First, the direction you look matters, and looking backward is a
liability.** A genuinely point-in-time (PIT) re-screen of the same
universe, using only data a live deployment would actually have had,
provides one directly-confirmed data point (a PIT-confirmed pair set that
traded and lost money, −1.0121 Sharpe on 32 trades) plus a smaller,
earlier, independently-run test finding zero overlap with the
full-history-confirmed set at every checkpoint tried (Sharpe range −0.72
to −1.04). A full-history screen — the field's standard practice —
silently certifies pairs whose apparent "confirmation" leaks information
from after the point a real decision would have been made. This is not a
claim that the pairs it finds are spurious; it is evidence that a
causally-constrained observer would not have found or profited from the
same pairs a backward-looking screen certifies. The canonical empirical
pairs-trading literature (e.g. Gatev, Goetzmann & Rouwenhorst, 2006 —
the field's seminal distance-method study, cited in full in
`PAPER.md`'s shared bibliography) validates its trading rule
out-of-sample but treats pair *selection* itself as a given input,
computed once over the full available history rather than causally
re-derived at each decision point — this paper tests discovery itself,
not just the rule applied to whatever pairs discovery already produced.
This specific result is at the current ~1,576-symbol WRDS-primary
universe; a second, corrected-scale re-run at the full ~43,883-symbol,
daily-bar universe (§4) reaches the same genuinely mixed conclusion, not
a scale-driven reversal in either direction.

**Second, the market regime a pair is first discovered in is
informative, not noise to be filtered out — real for one of two
sub-claims, once checked with the rigor the first pass of this analysis
lacked.** Among the full corrected-scale candidate pool, pairs whose
first qualifying rolling-correlation window falls in a crisis-VIX regime
are episodically BH-FDR-confirmed at roughly 1.7x the rate of
calm-discovered pairs by a naive pooled two-proportion z-test (0.248%
vs. 0.146%; z=2.77, p=0.0056) that treats each of 11,715 crisis-first
pairs as independent. **They are not**: crisis-VIX periods cluster into
just 12 distinct historical episodes, and a cluster-robust bootstrap
resampling at the episode level shows the true 95% confidence interval
([0.02%, 0.40%]) comfortably contains calm's rate — this specific claim
does not survive correct statistical treatment, even though the
underlying concentration (93.1% of confirmations from 2 of 12 episodes)
is independently confirmed real, not chance (binomial p=0.000006,
100,000-draw Monte Carlo p=0.00002): something genuinely unusual
happened in 2008-09 and 2011, but it does not generalize to "crisis
regime predicts confirmation." The second sub-claim fares better: pairs
*persist* as a candidate across later, different-regime windows
significantly more often than calm-discovered pairs (91.0% vs. 78.7%),
and this survives the same cluster-robust bootstrap (95% CI [77.5%,
96.3%], cluster-robust p=0.032) — weaker than the naive z=32.2 implied,
but genuinely significant, and — contrary to the natural "transient
panic correlation" null hypothesis — in the direction of persisting
MORE, not less. A third sub-question (does confirmation *strength*
differ by discovery regime) does not reach significance (Mann-Whitney
p=0.196, underpowered at only 29 crisis-confirmed pairs). The
confirmation-rate effect is also not a clean dose-response to market
stress: the "elevated" VIX bucket sits slightly *below* calm and normal,
with only the crisis extreme standing out. Of two named confounds for the persistence result that does survive, one
— crisis-era factor co-movement — is now directly tested (§5): residual-
izing each symbol's returns against SPY shows the effect is real in the
6.7% of pairs whose correlation survives factor-adjustment, but most of
the raw pooled effect sits in the factor-explained subset — the confound
is real, not total. The second — survivorship of crisis-discovered pairs
into the current-constituent universe — is not yet tested.

**The unifying claim**: a discovery event's timing and context are not
incidental metadata a confirmed-pair label can safely discard. One face
of this (temporal direction) is a bias current practice must correct
for; the other (regime context) is a signal current practice is leaving
on the table. Both are demonstrated using the same production screening
methodology and statistical discipline (Benjamini-Hochberg correction
across 10^5-10^6-scale hypothesis families, point-in-time-safe by
construction), though at different universe scales, disclosed directly
rather than implied to match (§1.2, §8). Six further findings from the
same pipeline (multiple-testing discipline at scale, episodic
cointegration as a market-structure property, SPAC microstructure
contamination, return-jump risk invisible to existing data-quality
checks, a purely mechanical 15.8σ artifact, and complexity earning its
keep only when it fixes a specific false assumption) are reported as
supporting evidence in §7 — real, verified findings from the same rigor
discipline, but not the paper's central contribution.

---

## 1. Introduction [DRAFTED]

**1.1 Motivating question.** A cointegration screen produces a binary
output per candidate pair: confirmed, or not. Conventional practice —
this project's own earlier practice included — treats that output as a
complete summary of what the screen found, discarding the *event* that
produced it: when, in absolute calendar time and in market-regime terms,
did this pair first clear the screen? This paper asks whether that
discarded information matters, and shows, on the same real production
pipeline, that it matters in two directions at once. Ignored in one
direction (the causal timing of discovery relative to when a trading
decision must actually be made), it is a source of bias serious enough
to overturn a pair set's profitability. Ignored in the other direction
(the market regime a pair was first discovered in), it is a real,
statistically significant predictive signal current practice simply
throws away. CAMARF's own confirmed-pair count changed by an order of
magnitude multiple times as successive rounds of methodology correction
were applied (§3 below) — evidence, independent of either finding here,
that "confirmed" was never as stable a label as it is normally treated.

**1.2 Why scale matters, and an honest caveat about which findings are
actually at corrected scale as of this writing.** Both of this paper's
central findings, and several of the six supporting ones (§7), are
scale-dependent — they either do not appear, or appear too rarely to
generalize from, at the ~1,500-2,000-symbol scale most of this project's
own earlier sessions worked at (a scale later found to itself be a bug;
see §2). §5's crisis-regime signal in particular only becomes visible
against a candidate pool run across ~640,000+ pairs; at smaller scale
the crisis-first subgroup (11,715 of 638,095 pairs, 1.8%) would be too
thin to test. **This is NOT true of every finding in this paper, and it
does not claim otherwise**: §7.6 (complexity comparisons) predates the
WRDS-primary universe entirely and runs on a 22-pair confirmed set;
§7.5 (calendar padding) is explicitly a single-pair, universe-scale-
independent artifact by construction (see §2's own scoping note). The
underlying candidate-pair count for §5 and for §7.2 (episodic
cointegration) **was** reported at a stale, pre-correction figure
(158,849 candidate pairs, dated 2026-08-13, eleven days before the
universe-undercount bug described in §2 was found and fixed on
2026-08-24) through most of this paper's drafting. **That re-run is now
complete (2026-09-02)**, after also fixing a second, real bug found in
the process: the corrected-scale run crashed ~90 consecutive times on an
unrelated memory bug in the episodic-scan checkpoint reconstruction (an
end-of-run step that held 2-3x redundant copies of the checkpoint data
in memory, never covered by an earlier, narrower fix to the same
function) — root-caused and fixed, not just retried past. §5 and §7.2
below now report the corrected-scale real numbers (638,095 candidate
pairs, 8.18% of regime spans ever cointegrated), not a placeholder; see
§8 for the same disclosure restated at each affected finding.

**1.3 Structure.** §2 establishes the real universe scale (and a real bug
in claiming it, found and fixed this session). §3 summarizes the shared
statistical machinery, reused from `analysis.py`, not reimplemented, per
this project's own working convention: every finding below runs
production code, not a parallel research-only reimplementation. §4
presents the causal-validity finding (discovery timing as a bias). §5
presents the regime-information finding (discovery context as a signal).
§6 synthesizes the two into the paper's central "discovery event" thesis.
§7 presents six further, supporting findings from the same pipeline,
each with its own honest scope/limitation statement inline. §8 states
biases and limitations directly, project-convention style, covering both
headline findings and the supporting six. §9 is the relationship to the
companion backtest paper. §10 is future work.

**1.4 The two-pillar argument, previewed.** It is worth stating the full
shape of the argument before the reader reaches either finding in detail,
rather than only in the synthesis (§6) at the end.

*The bias side (§4).* A full-history cointegration screen and a
genuinely point-in-time (PIT) re-screen of the *same* universe do not
just disagree at the margins. Across four historical folds, only one
provides direct evidence for the claim (a PIT-confirmed set that traded
and lost money); two find no PIT-confirmed pairs at all (inconclusive,
not evidence either way); the fourth (+0.25 Sharpe on 5 trades) is too
thin to overturn anything. Read this as a directional, qualitative
result, not a high-power statistical estimate — the honest claim is that
the PIT-discovered set did not resemble or outperform the full-history
set at any tested cutoff, not a precise magnitude, and a real part of
that claim's weight rests on a separate, earlier, independently-run test
(§4) rather than this one table alone. This is not a claim that CAMARF's
confirmed pairs are spurious. It is evidence that a screening process
run causally, the way any live deployment must run it, would not have
discovered and profitably traded the same pairs a backward-looking
screen certifies. The canonical pairs-trading literature (Gatev,
Goetzmann & Rouwenhorst, 2006, cited above) treats pair *selection* as
a given input, computed once over full available history, and validates
only the trading rule causally — §4 is this paper's case for why
discovery itself is worth testing the same way. This
result is at the current, smaller WRDS-primary universe scale; a second
run at the corrected, full ~43,883-symbol WRDS-primary universe §5 also
draws from (§4, §10) reaches the same genuinely mixed conclusion — 2 of 4
folds capital-constrained-positive, 2 negative, not a scale-driven
reversal in either direction, with the largest, most substantive fold
(1,533 raw trades) landing positive.

*The signal side (§5).* The same production screening methodology,
applied at corrected scale, asked a different question of the same
kind of discovery events: does the market regime a pair was *first
discovered in* predict anything about its future behavior? For one of
two sub-claims, yes, and only after correcting for a specific
statistical risk the first pass of this analysis got wrong: crisis-VIX
periods cluster into 12 real historical episodes, not 11,715
independent draws, and a cluster-robust bootstrap (resampling at the
episode level) shows the two sub-effects hold up very differently once
corrected. Persistence is the one that survives: crisis-discovered pairs
*persist* as a candidate across later, different-regime windows
significantly more often (91.0% vs. 78.7%; naive z=32.2 overstated it,
the honest cluster-robust p=0.032 still clears significance), a pattern
that replicates across nearly every distinct historical episode, not
just one. Confirmation rate (crisis-discovered pairs confirm at ~1.7x
the calm rate by a naive z=2.77, p=0.0056) does NOT survive the same
cluster-robust check (95% CI comfortably contains calm's rate) — even
though the underlying concentration (93.1% of confirmations from 2 of
12 episodes) is independently confirmed to be real and not chance
(binomial p=0.000006), that concentration is itself the reason the
pooled confirmation-rate test fails once corrected for it: something
genuinely unusual happened in 2008-09 and 2011, but it does not
generalize into a statistically supportable "crisis predicts
confirmation" claim. Of the two named confounds, one (crisis-era factor
co-movement) is now directly tested: residualizing each symbol's returns
against SPY shows the effect is real in the 6.7% of pairs whose
correlation survives factor-adjustment, but most of the raw pooled
effect sits in the factor-explained subset — the confound is real, not
total. The second (survivorship of crisis-discovered pairs) is not yet
ruled out for the persistence result that does hold up. Taken together, this is the
opposite practical implication of §4: where §4 shows discovery timing
must be corrected for, §5 shows discovery context is informative and
worth investigating further, not that it should already be acted on.

*Why one paper, not two.* Both findings interrogate the same object —
the discovery event, the specific moment and context in which a
candidate pair first clears a screen — and both show that current
practice's treatment of "confirmed" as a timeless, context-free label
throws away real information. §4 and §5 are not two unrelated results
placed in the same document; they are two tests of the same underlying
claim, using the same screening methodology, with opposite practical
prescriptions. That thematic symmetry is why this paper exists as one
contribution rather than two — it is not, and this paper does not claim
it to be, an empirically demonstrated interaction between the two
findings (§10 lists testing that interaction directly as future work);
the case for one paper rests on the shared underlying claim, not on
having shown the two findings affect each other.

---

## 2. Data and Universe [DRAFTED, 2026-08-24]

Full cross-reference: `PAPER.md` §3 for the complete data-source
description (yfinance primary daily/intraday, WRDS/CRSP primary for
daily-and-coarser US equity/ETF with Compustat Global fallback, IBKR
supplemental deep-history for confirmed pairs only). This section states
only what is specific to this paper's findings.

**The universe-undercount bug, disclosed rather than smoothed over.**
Several of the scripts producing findings in this paper, and separately
several unrelated "full universe" research scripts caught in the same
audit, were found this session to be silently sampling from an old,
narrow, yfinance-only cache directory (~1,566-1,730 symbols) while their
own docstrings and log messages claimed "full universe" coverage. The
real, current merged universe (yfinance + WRDS/CRSP + Compustat Global +
Binance + IBKR, deduplicated) is **~44,700 symbols**
(`universe_loader.load_full_universe()`, the single project-wide loader
all such scripts now call). This is stated here as a methodological
honesty point in its own right, not just a bug-log entry. A "full
universe" claim in statistical arbitrage research is only as strong as
the loader backing it, and this project shipped several such claims that
were quietly wrong by more than an order of magnitude before this
session's audit. **Not every "full universe" number in §4, §5, and §7
below postdates this fix, stated plainly, not smoothed over**: §7.1
(BH-FDR) and §7.2 (episodic cointegration)'s figure was originally
158,849 candidate pairs, dated 2026-08-13, predating this fix by eleven
days; the corrected-scale re-run has since completed (2026-09-02) and
both now report the real 638,095-candidate-pair figure (§1.2, §8). §5
(the crisis-regime finding) is built entirely on that same
corrected-scale run and never carried the stale figure. §7.6's complexity
comparisons predate the WRDS-primary universe entirely (22-pair confirmed
set, not full-universe scale by design). §7.5's calendar-padding
derivation is universe-scale-independent by construction. §4, §7.3, and
§7.4's underlying data are at the corrected, current universe scale.

**Scope of the WRDS-sourced findings specifically** (§4, §5, §7.1, §7.3):
limited to symbols with a fetched `output/cache/wrds/*_1D.parquet` file, currently
~43,662 of the ~44,700-symbol merged universe (1,032 files 0-byte or
corrupted from an earlier interrupted bulk fetch, skipped and logged, not
silently dropped; see Development.md). This is a daily-only scope.
WRDS/CRSP carries no intraday data, so these findings cannot speak to
intraday cointegration structure, only daily.

---

## 3. Shared Methodology [DRAFTED]

Every finding below reuses one or more of the following, unmodified,
production `analysis.py` components, stated once here rather than
re-derived per finding:

- **`UniverseFilter.correlation_matrix`/`candidate_pairs`**, the Pearson
  correlation pre-filter (|ρ| ≥ `Config.UNIVERSE.MIN_PEARSON_CORR`), and at
  full universe scale, the memory-bounded `chunked_pearson_candidate_pairs`
  variant (block-diagonal splitting, bit-exact equivalent to the direct
  call, built after a real OOM crash at ~18,283 symbols). That crash is
  itself an instructive small case of this paper's own §7.5-adjacent thesis:
  engineering detail, not statistics, determines whether a screen at scale
  runs at all.
- **`_eg_worker`**, the two-step Engle-Granger cointegration test,
  both-directions max-combination logic, identical to `CointScanner.scan`.
- **`_benjamini_hochberg`**, step-up Benjamini-Hochberg false-discovery-rate
  correction, `Config.STATS.FDR_ALPHA`.
- **Episodic/rolling confirmation.** A pair qualifies not on a single
  whole-history verdict but via a rolling window (`EPISODIC_WINDOW_BARS`
  = 2520 bars, ~10 trading years; `EPISODIC_STEP_BARS` = 252, ~annual
  re-evaluation), unioning each window's qualifying pairs across the full
  scan. This was built specifically because a fixed whole-history verdict
  cannot distinguish "cointegrated for 3 of the last 30 years" from
  "cointegrated throughout."
- **Regime-span hysteresis.** A state change (cointegrated vs. not)
  confirms only after persisting for at least 3 consecutive windows
  (`MIN_REGIME_WINDOWS=3`), preventing a single borderline p-value from
  fragmenting a real multi-year regime into noise.

No finding below introduces a new statistical test without disclosing it
as new (§5's crisis-vs-calm two-proportion z-tests and Mann-Whitney U
test, §7.4's Lee-Mykland jump test, and §7.2's regime-segmentation
hysteresis are the genuinely new machinery; all were verified against
synthetic ground truth before being run on real data, via
`debug/_verify_*.py` for each, referenced at the finding).

---

## 4. Finding 1: Discovery Timing Is a Causal Liability [DRAFTED, PAPER.md §7.3.1]

This is the bias side of the paper's central argument (§1.4). A
full-history cointegration screen looks backward across all available
data, including data that would not have existed at the moment a real
trading decision had to be made. If a pair's tradeable episode is itself
transient — §7.2's episodic-cointegration finding, reused here as
reinforcing context, not a prerequisite this section's own result
depends on — a backward-looking screen can certify a pair whose real
tradeable window has already closed, or has not yet opened. That is a
causal problem, not a statistical one, and it is the one this section
tests directly.

**The test.** At each of 4 historical fold cutoffs (2 expanding-window, 2
rolling-window), the full production screening pipeline (correlation
pre-filter, EG + BH-FDR, `coint_fraction_rolling`, structural-pair
exclusion, secondary-evidence override) is re-run using *only* data up
to that cutoff, exactly as a live deployment would have seen it, then
backtested forward through the fold's test window with the unmodified
`BacktestEngine`.

**Result — a real, disclosed scale caveat before the table: this specific
4-fold run is on the current WRDS-primary universe at 1,576 symbols, NOT
the corrected ~43,883-symbol scale §5 runs at (though not the same
candidate-pair COUNT even at matching universe scale — see the
corrected-scale re-run below for why). §4 and §5 share the same
methodology and screening pipeline, but this specific table is not (yet)
at the same universe scale — a corrected-scale re-run, once this paper's
single most important open item, now follows directly below this
paragraph, not a detail to gloss
over given how much §2 emphasizes exactly this kind of scale mismatch
elsewhere:**

| Fold | PIT-Confirmed Pairs | Trades | Portfolio Sharpe |
|---|---|---|---|
| expanding/fold1 | 0 | 0 | NaN |
| expanding/fold2 | 2 | 32 | **−1.0121** |
| rolling/fold1 | 0 | 0 | NaN |
| rolling/fold2 | 1 | 5 | **+0.2547** |

**Read the four folds as three different kinds of evidence, not one
"3 of 4" count — conflating them would overstate what's shown.** Two
folds (expanding/fold1, rolling/fold1) found zero PIT-confirmed pairs at
all: this is not evidence of lookahead bias costing money, it is an
inconclusive result — with too little pre-cutoff history accumulated by
those early folds, the pipeline may simply not have had enough data to
confirm anything yet, a data-availability limit, not a demonstration of
the paper's causal-validity claim. Exactly one fold (expanding/fold2)
provides real, direct evidence for that claim: a PIT-confirmed pair set
that actually traded and lost money (32 trades, −1.0121 Sharpe). The
fourth fold (rolling/fold2, +0.2547 Sharpe, 5 trades on `AUB/XHR@1h`) is
reported honestly rather than omitted, but 5 trades cannot overturn
anything either way. **The honest summary of this table alone: 1 of 4
folds is real supporting evidence, 2 are inconclusive, 1 is a thin
counter-example too small to weigh — a real but much thinner result than
"3 of 4 folds negative" implies**, which is why the earlier, independently-
run test below (pre-WRDS universe, a different and larger evidence base)
matters for this finding's overall weight, not just this one table.

**An earlier, more severe version of the same test** (pre-WRDS universe,
retained for provenance) found that at every one of 3 historical
checkpoints, the point-in-time screen discovered a *completely different*
pair set (19, 6, and 3 pairs) than the known full-history-confirmed set,
zero overlap, and that independently-discovered set lost money at every
fold (Sharpe range −0.72 to −1.04). Critically, **a real implementation
bug was caught and fixed before trusting this result**, and fixing it made
the finding *more* damning, not less: the uncorrected version showed
declining-but-positive Sharpes (an alignment-mode bug inflating bar counts
~5.85x), while the corrected version is uniformly negative. A separate
check confirmed the screening function itself is trustworthy (it
independently reproduces 16 of 17 known confirmed pairs when run on the
exact full-history window production itself uses), so the zero-overlap,
negative-Sharpe result at earlier cutoffs is a real property of the
*discovery process under causal constraints*, not a bug in the
diagnostic.

**What this tells us, and what it does not.** This is not evidence the
known confirmed pairs' cointegration is spurious. It is direct, quantified
evidence that a live, causally-run version of this pipeline would not
have discovered and profitably traded those same pairs at those points in
time. Combined with §7.2's episodic finding, the picture is coherent:
genuine cointegration is real but transient, and a screening process that
only looks backward over the full available history will systematically
certify relationships whose most recent episode has already ended, or has
not yet begun. Either way, not currently tradeable by a causal observer.
See §5 for this paper's complementary demonstration: where this section
shows discovery TIMING must be corrected for, §5 shows discovery REGIME
should be exploited, not discarded.

**A real reproducibility gap, found live and disclosed rather than
smoothed over: re-running this exact test today does not reproduce the
table above.** Attempting to bootstrap a confidence interval on the
existing point estimates (§8) by re-deriving each fold's confirmed-pair
set live (`research/pit_wfa_trade_bootstrap.py`) surfaced a large,
unexplained divergence: `expanding/fold2_exp` now finds 3 PIT-confirmed
pairs (not 2) and 28 trades at Sharpe +0.3486 (not 32 trades, −1.0121);
`rolling/fold2_roll` now finds 49 PIT-confirmed pairs (not 1) and 288
trades at Sharpe −0.4548 (not 5 trades, +0.2547) — the same DIRECTION of
finding (one fold negative, mixed results overall) but materially
different magnitudes. Checked directly before assuming either
explanation: the cached universe size is essentially unchanged (1,576
symbols at the original run vs. 1,579-1,580 today), and the fold cutoff
dates themselves are nearly identical (within about a week — `pit_
wfa.py`'s folds are computed as percentages of the cache's [min, max]
date range, which drifts slightly as new bars accumulate, but not nearly
enough to explain a 1-to-49-pair jump on its own); the re-run script's
own call to the shared screening function was checked line-for-line
against `run_fold`'s and matches exactly, ruling out a bug in the
re-derivation itself. **The most likely remaining explanation, not fully
isolated to a specific commit**: the shared screening pipeline
(`analysis.py`/`Config`) this test reuses has itself changed in the
weeks between the original run and this session's re-run — this project
has had substantial, ongoing development on exactly those shared
components in that window. This means §4's exact point estimates are not
currently reproducible by simply re-running the script; they are
historically-dated results, computed by a specific version of shared
production code against a specific cache state, not a fixed, re-derivable
fact. **The table above is left as originally reported, not replaced by
the new re-run's numbers, since the two are not answering the same
question** (a fold defined by percentage-of-cache-window, re-screened
under whatever the pipeline's code and cache happen to be on the day it's
run, is not a frozen historical artifact) — but this reproducibility gap
is itself now a disclosed, real limitation of this finding (§8), not a
silently-assumed non-issue.

**The corrected-scale re-run, completed 2026-09-03/04 — this paper's own
stated single most important open item.** `research/pit_wfa_wrds_daily.py`
(a new, standalone comparison-arm script; `pit_wfa.py` and the table above
are unmodified, still cited as-is) re-runs this exact causal-validity test
at the same ~43,883-symbol WRDS-primary, daily-bar universe §5 draws
from, closing the scale mismatch flagged above. A real, disclosed
difference from §5's own candidate-pair count worth naming precisely,
not glossed over: §5's 638,095-candidate-pair figure is a single,
full-history correlation-prefilter pass over that whole universe; each
PIT fold here necessarily screens a smaller, cutoff-specific candidate
pool instead — a genuinely point-in-time screen can only see the
universe as it existed up to that fold's own cutoff date, not the full
present-day one — so no single shared candidate-pair count applies
across both sections' methods, only the same underlying merged universe
source. Daily bars, not 1h, are the only way to reach this universe
scale at all: WRDS/CRSP carries zero intraday data, disclosed throughout
this paper (§2), so matching §5's scale requires a genuinely different
granularity, not a parameter change to the 1h script. Two real
production bugs were found and fixed before trusting the result, in the
same spirit as the alignment-mode bug caught earlier in this section: a
`None`-vs-`NaN` handling gap in the shared `BacktestEngine` (a Hurst
estimate that can legitimately fail to compute crashed the whole run
instead of falling back to a missing-value placeholder), and a wiring gap
in the capital-constrained replay engine (`portfolio_sim.py`) that
silently produced zero-value price/spread lookups for this new daily-bar
universe specifically, initially manifesting as an implausible 0-trades-
taken capital-constrained result before being traced and fixed. Both are
verified, disclosed engineering fixes to shared machinery, not changes to
this test's methodology.

Per this project's own standing convention (portfolio-level, capital-
constrained results are the reported headline over raw per-pair
backtests — a real position-sizing decision was needed here too:
uncapped risk-based sizing initially took zero trades at any fold,
a genuine capital-scale finding, not a bug — resolved by capping
per-position concentration at 20% of equity, this project's own
already-declared but previously-unenforced convention, not a newly
invented number):

| Fold | PIT-Confirmed Pairs | Raw Trades | Capital-Constrained Trades Taken | Capital-Constrained Sharpe |
|---|---|---|---|---|
| expanding/fold1 | 31 | 21 | 11 | **−0.4779** |
| expanding/fold2 | 110 | 50 | 25 | **+0.1918** |
| rolling/fold1 | 31 | 21 | 11 | **−0.4779** |
| rolling/fold2 | 303 | 1,533 | 309 | **+0.2175** |

(`rolling/fold1` matches `expanding/fold1` exactly by construction — both
variants share an identical fold-1 date range at this fold-fraction
definition, not a coincidence or a bug.)

**Read honestly, not resolved into a clean story either way**: at full
scale, the causal-validity finding remains genuinely mixed — 2 of 4 folds
capital-constrained-positive, 2 negative, the same qualitative pattern as
the smaller-scale table above, not a scale-driven reversal in either
direction. The one fold with a real, large sample (`rolling/fold2`,
1,533 raw trades, the single most statistically substantive result either
script has produced) is capital-constrained-positive, and notably the
concentration cap does more than filter trades there: it *flips* the
portfolio Sharpe's sign (−0.2589 raw → +0.2175 capital-constrained),
consistent with genuine downside-risk reduction rather than mere
position filtering. This corrected-scale result does not overturn §4's
central claim (a live, causal screen still would not have uniformly,
profitably traded the same pairs a backward-looking screen certifies —
half these folds are still net negative), but it also does not deepen it
into a stronger, more damning result than the smaller-scale table already
showed. **A pooled-across-folds headline Sharpe was built 2026-09-08**
(within each `wfa_variant` separately, not mixed across variants) via
real equity-curve splicing (chronological concatenation, inter-fold
calendar gap dropped rather than zero-filled) rather than a naive average
of already-annualized ratios. The calendar-day-weighted construction
gives +0.1845 rolling / +0.1285 expanding (both positive); an equally
defensible ALTERNATIVE construction — equal-weighting each fold's own
Sharpe regardless of its calendar span — gives −0.1302 / −0.1431 (both
negative), the opposite sign. **This is not a minor caveat: the pooled
headline's sign itself is not robust to which defensible weighting
scheme is used.** No single pooled number should be read as resolving
the underlying fold-to-fold sign disagreement — full account in §4/§10.

---

## 5. Finding 2: Discovery Regime Is an Exploitable Signal [DRAFTED, Finding #41, 2026-09-02]

This is the signal side of the paper's central argument (§1.4). If a
pair's discovery *timing* can be a causal liability (§4), can a pair's
discovery *context* — specifically, the market regime prevailing when it
was first discovered — instead be a source of real, exploitable
information? This section shows yes, in a specific, statistically
disciplined, and partially surprising way.

**Motivation.** During the overnight corrected-scale episodic scan
(§7.2), Tier 3's rolling-correlation prefilter showed qualifying-pair
counts holding in the 150,000-250,000 range for windows ending
1994-2008, then jumping 4-10x (to ~1M-2.3M) for windows spanning the
2008-2009 financial crisis and the 2020 COVID crash. Ross's framing,
verbatim: *"we have prior data showing stocks cointegrating or moving
together more often during VIX crisis times, so if we factor in entry
criteria or cointegration testing we should note that jump."* This
section is the diagnostic that had to come first, deliberately not "pick
a new correlation threshold and see if it helps" (which solves a
hypothesized problem before confirming one exists, and risks reading as
tuning the pipeline until an inconvenient finding goes away — the same
trap this project's own convention flags for backtest results): does the
crisis-era correlation surge translate into systematically different
downstream cointegration behavior at all?

**The test.** Using the same corrected-scale Tier 3 output (§7.2;
638,095 candidate pairs, 5,003,637 (pair, window) tests), each candidate
pair's EARLIEST qualifying window is dated, and the VIX regime
prevailing as of that date (calm <15 / normal [15,25) / elevated
[25,35) / crisis ≥35, an already-existing production classification,
`macro.py`'s `_classify_vix()`, not reinvented) is looked up
point-in-time-safe — never a later VIX value than the pair's own
discovery date. Three pre-registered sub-questions, reported regardless
of direction: (1) does confirmation RATE differ by first-discovery
regime; (2) does confirmation STRENGTH (among confirmed pairs, the
fraction of a pair's own tested windows that were FDR-rejected) differ;
(3) does a pair's PERSISTENCE (reappearing as a candidate in a later,
different-regime window) differ.

**Result:**

| first_regime | n_pairs | n_confirmed | confirmation_rate | reappearance_rate |
|---|---|---|---|---|
| calm | 281,654 | 412 | 0.146% | 78.65% |
| normal | 291,109 | 413 | 0.142% | 81.92% |
| elevated | 53,617 | 75 | 0.140% | 90.58% |
| crisis | 11,715 | 29 | 0.248% | 91.00% |

Confirmation counts sum exactly to the same 929 pairs Tier 3's own
headline (§7.2, Finding #41) reports — a real internal-consistency check
across two independently-run scripts sharing the same underlying data,
not assumed. **929 is the episodic-confirmation count at Tier 3's
correlation-prefilter scale, not the size of any deployable trading
set — do not read it as an opportunity-set estimate.** After the
identity/structural/SPAC contamination filtering §7.3 describes (which
excluded 23 of 78 raw whole-history candidates, ~29%, from a much
smaller starting pool), CAMARF's actual production confirmed-pair count
is 29 (§ Relationship to `PAPER.md`). The gap between 929 and 29 is
expected, not a discrepancy: 929 counts EVER episodically confirmed at
any point across full available history at the correlation-prefilter
stage, before any of the identity/contamination vetting a real
promotion requires.

1. **Confirmation rate — the naive pooled test is significant; the
   cluster-robust test is NOT. Reported at the resolution that actually
   matters, not the one that looks best.** The pooled two-proportion
   z-test (crisis-first pairs confirm at ~1.7x the calm rate: 0.248% vs.
   0.146%; z=2.77, p=0.0056) treats each of the 11,715 crisis-first pairs
   as an independent trial. That assumption is checked directly below,
   not assumed, via a cluster bootstrap resampling at the EPISODE level
   (the correct unit of independence: only 12 distinct historical
   episodes, not 11,715 pairs). **Result: the cluster-robust 95%
   confidence interval for the crisis confirmation rate is [0.022%,
   0.398%], which comfortably CONTAINS calm's observed 0.146% rate**
   (cluster-robust p-equivalent = 0.25 — 25% of episode-level bootstrap
   resamples show a crisis rate at or below calm's, far from
   significant). The naive p=0.0056 is a real artifact of pretending 12
   correlated episodes are 11,715 independent trials; once corrected,
   this specific sub-claim does not hold up.
2. **Persistence — significant under BOTH the naive and the
   cluster-robust test, though considerably weaker under the honest
   one.** Crisis-first pairs reappear as a candidate in a later,
   different-regime window far more often than calm-first pairs (91.0%
   vs. 78.7%). The naive pooled z-test (z=32.2, p≈0) overstates
   confidence the same way the confirmation-rate test did. The
   cluster-robust bootstrap (same episode-level resampling): 95% CI
   [77.5%, 96.3%], cluster-robust p-equivalent = 0.032 — still under the
   conventional 0.05 threshold, but only barely, and an order of
   magnitude weaker than the naive z≈32 suggested. This is the
   counter-intuitive result the paper leans on: the natural null
   hypothesis is that crisis-era comovement is a transient panic
   artifact that should FAIL to persist once the crisis ends; the data
   goes the other way, and — unlike confirmation rate — this survives
   proper cluster-level inference, even if only marginally.
3. **Confirmation strength — not significant, reported honestly.** Among
   confirmed pairs, crisis-first pairs show a higher mean per-pair
   FDR-rejection fraction (0.288 vs. 0.223 for calm), but a Mann-Whitney U
   test (the right choice for a bounded [0,1] fraction, not obviously
   normal) finds this is not statistically significant (U=5119, p=0.196)
   — almost certainly underpowered at only 29 crisis-confirmed pairs vs.
   412 calm-confirmed. This sub-question is reported as directional, not
   a third confirmed effect alongside the first two.

**A real nuance, disclosed rather than smoothed over: this is not a
dose-response relationship.** The 4-way confirmation-rate table is not a
clean calm→normal→elevated→crisis gradient. "Elevated" (0.140%) sits
slightly BELOW calm (0.146%) and normal (0.142%), with only the crisis
extreme standing out. A reader tempted to summarize this as "more market
stress produces more cointegration" would be overclaiming; the honest,
narrower reading is a crisis-extreme effect specifically, not a general
stress-response curve. The analysis script
(`research/crisis_regime_correlation_diagnostic.py`) checks and flags
this automatically rather than requiring a reader to notice it in the
raw table.

**Episode-clustering robustness check — the pooled p-values above almost
certainly overstate the effective sample size, and this section reports
exactly how much once checked, not just flags the risk.** The pooled
two-proportion z-tests treat each crisis-first pair as an independent
draw, but crisis-VIX periods are not spread uniformly through history —
they cluster into a handful of real historical episodes (2008-09 GFC,
2020 COVID, etc.), and pairs discovered within the same episode share a
common cause (the same market-wide shock), not independent discovery
events. `research/crisis_regime_episode_clustering_check.py` (verified
first, `debug/_verify_crisis_regime_episode_clustering_check.py`, 11/11
checks) groups the 11,715 crisis-first pairs into distinct episodes (a
new episode starts whenever 3+ consecutive months pass with no new
crisis-first pair — a fixed, disclosed rule, not tuned after seeing the
result) and re-examines both effects at the episode level:

| episode | dates | n_pairs | confirmation_rate | reappearance_rate |
|---|---|---|---|---|
| 1 (largest) | 2008-09 to 2009-05 | 4,084 | 0.490% | 94.6% |
| 3 | 2011-08 to 2011-11 | 2,253 | 0.311% | 90.5% |
| 7 | 2020-02 to 2020-06 (COVID) | 2,329 | 0.043% | 98.3% |
| 9 other episodes | various, 1998-2025 | 3,049 | 1 confirmation (episode 0, a trivial n=1 pair from 1998-09-14); 0 in the remaining 8 | 34.3%-99.0% |

**The 11,715 crisis-first pairs are really 12 distinct historical
episodes, not 11,715 independent trials.** Only 4 of those 12 episodes
produced ANY confirmed pair, and the top 2 (2008-09 GFC and the 2011
debt-ceiling/EU crisis) alone account for 27 of 29 crisis confirmations
(93.1%). Notably, the 2020 COVID crash — the other episode explicitly
named in this section's own motivating observation — produced 2,329
crisis-first candidate pairs but only 1 confirmation (0.04%), barely
above the calm-period rate.

**Is the top-2-of-12 concentration itself just what a small, right-skewed
count distribution produces by chance? Tested directly, not left as an
open question.** `research/crisis_regime_concentration_significance_test.py`
(verified first, `debug/_verify_crisis_regime_concentration_significance_
test.py`, 7/7 checks) runs two tests against the null that confirmation
probability is constant per pair regardless of episode (so confirmations
should land on episodes in proportion to each episode's PAIR-COUNT share,
not spread evenly across all 12): an exact binomial test (episodes 1+3
hold 54.1% of crisis-first pairs, so ~15.7 of the 29 confirmations would
be expected there by chance; 27 were observed, p=0.000006) and a 100,000-
draw Monte Carlo simulation of the same null (observed max-2-episode
share of 93.1% vs. a null mean of 59.4% and a null 95th percentile of
72.4%; p=0.00002). **Both reject the null decisively: the concentration
is real, not a chance artifact of a small episode count.** Something
specific to the 2008-09 and 2011 episodes — not merely "these episodes
happened to be large" — is driving the confirmation-rate pattern.

**But "the concentration is real" and "the pooled confirmation-rate test
is valid" are different claims, and only the first survives.** A
concentration this extreme is exactly what makes the pooled
two-proportion z-test's independence assumption fail hardest: with 12
real episodes and 93% of signal from 2, the pooled test above already
showed the honest cluster-robust confidence interval comfortably
contains calm's rate. **The confirmation-rate finding, at the resolution
that actually holds up, is: something genuinely unusual happened in
2008-09 and 2011 specifically (confirmed significant), but that does NOT
translate into a general, statistically supportable claim that
crisis-VIX discovery predicts confirmation (the cluster-robust test for
that broader claim is not significant).** These are not in tension —
they're answers to two different questions (episode-level: is 2008-09
special? vs. pooled-crisis-level: does crisis generally predict
confirmation?) that this paper originally conflated into one number.

The persistence/reappearance effect fares much better under the same
episode-level scrutiny: excluding the 2 most recent episodes (2024, 2025
— too little subsequent history has elapsed to observe reappearance
yet, a real right-censoring risk, not a weaker effect) reappearance rate
ranges 84%-100% (median 95.6%) across every remaining episode, including
ones with zero confirmations — a consistent, broadly-replicated pattern
across nearly the entire 1998-2022 span, not concentrated the way
confirmation rate is, and (above) the ONLY one of the two sub-effects
that survives a formal cluster-robust significance test, even if
marginally. **This is why §1.4/§6 lean on persistence, not confirmation
rate, as this finding's defensible pillar** — confirmation rate is now
reported as a real, statistically-confirmed episode-specific curiosity
(2008-09/2011), not as general evidence for the discovery-regime-as-
signal thesis this paper's throughline depends on.

**Confounds — one now decisively split (partly real, partly a factor
artifact), one still untested.** Two alternative explanations could
produce the same pooled pattern without requiring "discovery regime
carries information" specifically. First, market-wide factor
co-movement: crisis periods are exactly when idiosyncratic correlation
structure collapses toward a single dominant systemic-risk factor
(Forbes & Rigobon, 2002; Longin & Solnik, 2001), a well-documented
phenomenon that alone could explain both the 4-10x correlation-prefilter
surge motivating this section and elevated downstream correlation
persistence, independent of any genuine pairwise economic relationship.
**Directly tested** (`research/residual_correlation_factor_test.py`,
verified first, `debug/_verify_residual_correlation_factor_test.py`,
15/15 checks): each of 5,700 unique symbols across 638,095 candidate
pairs was regressed against SPY once, and correlation was recomputed on
the OLS residual — the direct version of the same-sector proxy test
below, isolating co-movement that survives removing the shared market
factor entirely rather than inferring it from sector membership. Result:
the crisis-regime reappearance gap is **real but only partly a factor
artifact**. Of the 638,095 pairs, 42,715 (6.7%) still clear
`|residual correlation| >= 0.4` after the factor is regressed out; in
that subset, crisis reappearance is still elevated (88.26% vs. calm's
78.41%, n=1,559 crisis / 14,555 calm, z=9.13). But most of the raw
effect by pair count and by z sits in the factor-explained subset
(91.42% vs. 78.67%, n=10,156 crisis / 267,099 calm, z=31.05) — the
Forbes-Rigobon confound is real, it just isn't the whole story. Both
z-tests here are naive pooled pair-level tests of the same kind
Finding #43's cluster-robust episode bootstrap showed overstates
significance for the confirmation-rate metric specifically (the
reappearance-rate metric measured here weakly survived that
cluster-robust test at p=0.032, not p≈0) — a cluster-robust rerun on
both subgroups is the natural next check before this split is treated
as more than preliminary. A second, independent proxy for the same
question (`research/crisis_regime_same_sector_test.py`, verified first,
`debug/_verify_crisis_regime_same_sector_test.py`, 7/7 checks) points
the same direction: if the persistence effect were purely a
systemic-risk-factor artifact, it should appear similarly for
same-sector pairs (which already have a real, disclosed economic reason
to co-move beyond a generic factor) and cross-sector pairs. It does not.
Restricted to the S&P 1500 (GICS tags cover only ~10% of Tier 3's full
candidate pool, a real, disclosed coverage limit) and excluding the 2
most recent episodes (2024/2025; GICS's current-constituent-snapshot
nature disproportionately captures recent, right-censored discoveries —
checked directly: 53% of GICS-tagged crisis-first pairs were from those
2 episodes alone before this exclusion, which flipped the result's
direction entirely until corrected for): same-sector pairs show NO
significant crisis-vs-calm reappearance gap (93.3% vs. 92.1%, n=75
crisis pairs, p=0.69), while cross-sector pairs show a real one (99.4%
vs. 94.1%, n=359, p=0.000018) — consistent with, not against, the
residual-correlation result above (cross-sector pairs picking up more
systemic co-movement during crisis; same-sector pairs already correlated
for real reasons, with less room for a factor to add anything). Second,
survivorship: a pair "discovered" in 2008 or 2020 necessarily
involves two symbols that both still exist in the current-constituent
universe this paper's data draws from (§8) — crisis-discovered pairs are
conditioned on having survived to today, a systematically different
population than an unconditional draw from that era's full universe.
This confound remains untested here (a delisted-securities fetch that
would partially address it was run this session, §8, but has not yet
been joined back into this specific analysis).

**Two further robustness checks, both run this session.** The
episode-clustering gap rule (3 consecutive months with no new crisis-
first pair starts a new episode) is a fixed, disclosed choice, not tuned
after seeing the result — checked directly by re-running the episode
count and top-2 concentration share at 1, 2, 4, and 6-month alternatives:
the concentration share is identical (0.931) at every choice, and the
episode count only varies mildly (11-13) — the finding does not depend
on the specific threshold chosen. Separately,
`research/regime_strength_vs_discovery_regime_test.py` (verified first,
`debug/_verify_regime_strength_vs_discovery_regime_test.py`, 8/8 checks)
tested a third possible throughline connection: does a pair's
cointegration-regime STRENGTH (strong/moderate/weak, §7.2) correlate with
its discovery regime? Across the 56,003 pairs with both a genuine coint
span and a recorded discovery regime, a chi-square test of independence
found no relationship (χ²=6.70, dof=6, p=0.349) — reported as a real,
tested null result, not a positive finding to force. Discovery regime
predicts a pair's PERSISTENCE as a candidate; it does not predict the
eventual STRENGTH of its cointegration once genuinely confirmed. These
are separate axes, and this section's claim is scoped to the one that
holds up.

**Verification.** All three sub-questions' statistical tests, the
point-in-time-safe regime lookup, and the per-pair table construction
(first window, confirmation, reappearance) are verified against
synthetic ground truth before being trusted on real data
(`debug/_verify_crisis_regime_correlation_diagnostic.py`, 21/21 checks),
as are the episode-clustering check
(`debug/_verify_crisis_regime_episode_clustering_check.py`, 11/11), the
concentration-significance test
(`debug/_verify_crisis_regime_concentration_significance_test.py`, 7/7),
and the cluster bootstrap
(`debug/_verify_crisis_regime_cluster_bootstrap_test.py`, 7/7) — every
number in this section traces to a script verified against synthetic
ground truth before being trusted on the real 638,095-pair data. A
related, prior finding (`research/stress_test_replication.py`,
`docs/HANDOFF.md`) asked a different, downstream question — "of pairs
ALREADY past screening, does an existing cointegration relationship
survive a crisis differently than a calm period" — and found no (~8% vs.
9%, roughly the same). This section asks the question upstream of that:
does the raw candidate-pool ENTRY POINT itself differ systematically by
discovery regime. The two results are not in tension; they describe
different pipeline stages.

**What this tells us, and what it does not.** This is not evidence that
crisis-VIX periods *cause* cointegration, and — after the episode-
clustering check above — the confirmation-rate half of this finding is
better read as "the 2008-09 and 2011 crises specifically produced
unusually durable candidate pairs" than "crisis conditions generally
predict confirmation." The persistence/reappearance half is the
stronger, more broadly-replicated claim. Taken together, conditional on
a pair having already cleared the correlation prefilter, the regime it
first cleared that filter in carries real predictive information about
its downstream behavior that current practice — treating "confirmed" as
a context-free label — simply discards, though the two confounds above
mean this should be read as suggestive evidence for that claim, not a
closed case. Whether this information should become a production
entry-criteria adjustment, a confidence-weighting signal, or is better
left as a descriptive fact is a separate, later decision this section
deliberately does not make (§10, future work), consistent with this
project's standing discipline of confirming a problem (or, here, an
opportunity) exists before tuning a fix for it.

---

## 6. Synthesis: The Discovery Event [DRAFTED, reframed 2026-09-02]

§4 and §5 ask two different questions of the same underlying object: the
DISCOVERY EVENT, the specific moment and market context in which a
candidate pair first clears a cointegration screen. Read separately,
they are two unrelated findings that happen to share a data pipeline.
Read together, against the question that motivates this whole paper
(does a screen's "confirmed" output mean what a naive reading assumes it
means?), they support one claim from two directions at once.

**The unifying claim.** A discovery event carries information a binary
confirmed/not-confirmed test outcome discards, and current practice —
including this project's own earlier practice — discards it by treating
"confirmed" as a static, timeless label rather than a dated,
context-bearing event. §4 shows this in the direction of BIAS: discovery's
TEMPORAL relationship to the moment a real decision must be made
(backward-looking vs. causal) determines whether the certified pair set
would actually have been discoverable, and profitable, by a live
deployment. §5 shows this in the direction of SIGNAL: discovery's
MARKET-REGIME context is informative about a pair's future persistence
— confirmed under a cluster-robust test that properly accounts for
crisis-VIX periods clustering into a handful of real historical episodes
rather than thousands of independent draws; a related sub-claim
(confirmation rate) does NOT survive the same cluster-robust check, even
though the underlying episode concentration behind it is independently
confirmed real, not chance. Neither finding is a restatement of the
other, and the two point in opposite practical directions — one says
"subtract this," the other says
"investigate this further" — which is what makes them one contribution:
both are instances of the same missing variable (discovery context),
using the same production screening methodology and statistical
discipline throughout, though §4 and §5 are run at different universe
scales (§1.2, §8) and the two findings' interaction has not itself been
empirically tested (§10).

**Why this matters beyond CAMARF, stated as a testable hypothesis, not
an established fact.** The canonical pairs-trading literature (Gatev,
Goetzmann & Rouwenhorst, 2006) treats pair discovery as a preprocessing
step, reported as a static candidate count, then moves on to backtest
methodology as the object of scrutiny; this paper does not claim every
paper in the field does the same, only that the field's most-cited
foundational study does. §4 shows that discovery itself needs the same
causal discipline normally reserved for the trading rule.
§5 shows that discovery, treated as a dated event rather than a
filtered-out preprocessing artifact, is a plausible source of real
signal most pipelines never look for because they never retain the
information needed to look — plausible, not proven beyond this
pipeline, since the episode-clustering and confound checks in §5 mean
the signal claim is narrower than a first read of the headline p-values
suggests. Both claims are testable in principle on any pipeline that
logs a discovery timestamp and has access to a market-regime proxy at
that timestamp; this paper demonstrates them on one such pipeline, not
on a second, independent one, so generalization beyond CAMARF is a
hypothesis this paper motivates, not a result it has shown.

**Six further findings, reinforcing but not part of the core claim.**
§7 reports six additional, independently-verified findings from the same
production pipeline (multiple-testing discipline at 10^5-10^6-hypothesis
scale, episodic cointegration as a market-structure property, SPAC
microstructure contamination, return-jump risk invisible to existing
data-quality checks, a purely mechanical 15.8σ artifact, and complexity
earning its keep only when it corrects a specific false assumption).
None of the six is about the discovery event specifically — they are
evidence that this same pipeline demands rigor at every OTHER stage too,
not just at discovery, and one in particular (§7.2's episodic-
cointegration finding) directly motivates why §4's causal-validity
concern exists in the first place. They are real, verified, and
load-bearing for this paper's broader credibility, but they are
supporting evidence for a project-wide rigor claim, not part of the
two-finding discovery-event thesis this paper is centrally built around.

**The thesis restated, plainly.** A cointegration screen's "confirmed"
output is not a fact about the pair. It is a fact about a specific test,
run at a specific time, against a specific candidate pool, in a specific
market regime. §4 and §5 provide evidence that two of those specifics —
WHEN the test was run relative to a real decision, and WHAT REGIME
prevailed when the pair first qualified — are not incidental. They
change whether the "confirmed" label would have been earned by a causal
observer (§4, directly demonstrated on one fold, suggestively on more),
and, once checked with cluster-robust rigor rather than a naive pooled
test, they predict something real about a pair's future persistence
specifically (§5, confirmed under episode-level resampling); a related
confirmation-rate claim does not survive the same scrutiny, disclosed as
such rather than left standing on a naive p-value. A practitioner who
discards a pair's discovery event once it clears a threshold is
discarding information this paper provides real, if not yet exhaustive,
evidence to be load-bearing in both directions.

---

## 7. Supporting Findings: Further Evidence of Rigor Required at Every Pipeline Stage [DRAFTED]

The two findings above (§4, §5) are this paper's central contribution.
The six findings below are real, independently-verified results from the
same production pipeline, reported because they reinforce the paper's
broader credibility claim (a pipeline this thoroughly audited is
trustworthy specifically because every stage, not just discovery, has
been checked this way) — not because each is individually as novel as
§4 or §5. Each retains its own honest scope/limitation statement inline,
per this project's standing discipline of never deferring a caveat to a
single catch-all section.

### 7.1 Multiple-Testing Discipline Is Load-Bearing, Not Optional, at Real Scale

**The scale.** After the Pearson correlation pre-filter, the full-universe
episodic scan (§7.2 below, same underlying data; Tier 3 of `wrds_deep_
history_episodic_scan.py`, corrected-scale run completed 2026-09-02)
produces **638,095 candidate pairs**, tested across a rolling window for
a total of **5,003,637 individual (pair, window) Engle-Granger tests**
(`wrds_deep_history_episodic_scan_tier3_windows.parquet`, Finding #28,
Finding #41). Separately, a full-sample (single-window) EG cascade across
the corrected full universe produced 78 raw whole-history-significant
candidates before any structural/identity/SPAC contamination filtering
(§7.3). At either scale, running these tests at a nominal α=0.05 with no
correction would be expected to certify thousands of false positives by
chance alone. This is not a hypothetical: 5,003,637 tests × 0.05 ≈
250,182 expected false positives under the global null, dwarfing any
plausible true-positive count.

**What BH-FDR buys, and what it doesn't.** Benjamini-Hochberg step-up
correction, applied per timeframe (matching `Config.STATS.FDR_ALPHA`),
controls the *expected proportion* of false discoveries among rejections,
not the count, and not with certainty for any single rejected hypothesis.
A direct robustness check against the more conservative
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
named, tracked pending task (§10), not a silently-abandoned one. This
paper does not report a full-scale BH-vs-BY split until that re-run
exists.

**What this pillar contributes as a literature critique, stated plainly.**
Cross-asset cointegration papers that report "N significant pairs" from a
correlation-prefiltered candidate pool without disclosing (a) the
candidate pool size and (b) the multiple-testing correction applied are,
at this project's demonstrated scale, almost certainly overstating the
reliability of their headline pair set. This is not a claim about any
specific published paper, which this project cannot verify without
access to that paper's own candidate-pool accounting. It is a testable,
quantified standard this project proposes and holds itself to, stated as
a methodological recommendation rather than an accusation.

### 7.2 Cointegration Is Episodic, Not a Persistent Property

**Scale disclosure, stated here rather than only in §1.2/§8**: this
finding was originally reported at a stale 158,849-candidate-pair figure,
dated 2026-08-13, eleven days before the §2 universe-undercount fix.
**The corrected-scale re-run (same script, `wrds_deep_history_episodic_
scan.py`, plus `research/cointegration_regime_segmentation.py` for the
span segmentation itself) completed 2026-09-02**, after also fixing a
second, unrelated bug that had caused ~90 consecutive crash-restarts (a
2-3x memory-redundant checkpoint reconstruction step, root-caused and
fixed, not just retried past — see Finding #41). The numbers below are
the real, corrected-scale result.

Segmenting each of the 638,095 candidate pairs' full available history
into contiguous cointegrated/non-cointegrated regime spans (via the
hysteresis rule in §3) produces:

| state | n_spans |
|---|---|
| not_coint | 634,677 |
| coint | 56,536 |

**Only 8.18% of all detected regime spans across the full candidate
universe are ever genuinely cointegrated** (56,536 of 691,213 total
spans) at any point in their history — close to, but a real, measured
change from, the earlier stale-scale figure of 9.2%, not simply
reconfirmed. Of the cointegrated spans, strength splits almost exactly
evenly by construction: strong=18,827, moderate=18,883, weak=18,826. This
uses global cross-pair terciles, not per-pair terciles. A per-pair split
was tried first and found statistically meaningless at ~0.1 spans/pair
average, a real design bug caught by running against real data rather
than assumed correct from the synthetic test alone.

**What this tells us about market structure.** A pair passing a
whole-history cointegration test is not evidence of a stable, ongoing
economic relationship. It is evidence that the relationship held during
*some* sub-period of the tested history, usually a minority of it. This
directly motivates §4's negative-backtest finding: if genuine
cointegration is this episodic, a full-history screen's implicit
assumption (a certified pair remains tradeable going forward) is exactly
the assumption most likely to fail.

### 7.3 SPAC NAV-Clustering, A Corporate-Action Microstructure Source of Spurious Cointegration at Scale

**Context.** A full-universe EG+FDR cascade (`full_universe_eg_confirmation.py`)
found 78 raw whole-history-significant candidate pairs. Promoting these
into CAMARF's production confirmed-pair set required a real, multi-round
data-integrity vetting, not a rubber stamp, that surfaced four distinct
contamination classes. Three were identity/structural bugs (already-known
filter gaps, applied but not previously wired into this specific script's
driver), and one was genuinely new: **SPAC NAV-clustering**.

**The mechanism.** Blank-check (SPAC) companies trade near a shared ~$10
trust-account NAV in the period before a merger is announced or
completed. Two economically *unrelated* SPACs, both sitting near $10 with
low volatility, will show a strong, statistically significant
cointegration relationship purely from this shared, mechanical price
anchor, not from any real co-movement in the underlying businesses (which,
pre-merger, do not yet exist as operating companies at all in most cases).
This is not a data-quality bug; it is a real, if spurious, statistical
property of an entire class of securities, invisible to any purely
price-based filter.

**Detection.** No existing structural/identity filter catches this. SPACs
are not duplicate tickers, not cross-listings, not share classes; they
are genuinely distinct legal entities that happen to share a price
regime. Detection required cross-referencing CRSP's `comnam` (company
name field) against SPAC naming conventions (`ACQUISITION CORP`/`ACQ
CORP`/`MERGER CORP`, case-insensitive regex), resolved through the same
unambiguous permno lookup used for the identity-alias check elsewhere in
this promotion. This confirmed **22 real SPACs by name** among the 78
candidates. For example, `ALTU` in this dataset is "Altitude Acquisition
Corp," not the unrelated pharmaceutical company that has historically
shared that ticker, resolved definitively via the permno-level lookup,
not ticker matching alone.

**Disclosed non-exhaustiveness.** The regex is a real, working heuristic,
not a complete SPAC taxonomy. One SPAC (`BRIV` = "B Riley Principal 250
Merger") slipped through because its name ends in "Merger" rather than
"Merger Corp," caught only in manual dry-run review before the real
(non-dry-run) write. A known further gap: the "Social Capital Hedosophia"
SPAC family uses no Acquisition/Acq/Merger token in its name at all and
would not be caught by this regex. Stated here as a known limitation, not
silently assumed solved.

**Net effect on the promotion**: of the 78 raw candidates, 23 were
excluded as SPAC-contaminated (22 by regex + 1 manual catch), alongside
22 same-GVKEY-number duplicates and 6 WRDS ticker/PERMNO alias or
self-pair collisions (0 caught by the pre-existing structural-pair
filter, since this specific candidate set happened not to contain that
particular contamination class). 27 of 78 candidates survived to
production. **Reconciling this with the "29" figure cited elsewhere in
this paper (e.g. §Relationship to `PAPER.md`, §8, §10)**: 27 is this
specific 1-day-timeframe SPAC/duplicate/alias-filtered promotion; the
paper's other references to "29" are CAMARF's TOTAL confirmed-pair count
across all timeframes (`output/results/{1day,4hr,3min}/pairs.parquet`:
27 + 1 + 1 = 29), from two additional, separately-run promotions
(4hr and 3min) this section does not itself describe. Stated explicitly
here because a paper built around tracking a confirmed-pair count
precisely (§1: 23→3→2→29) should not leave its own two live numbers
(27, 29) unreconciled for a reader to notice on their own.

**What this tells us about market structure.** At full-universe scale, a
meaningful fraction of "statistically confirmed" cointegration (23 of 78
raw candidates here, ~29%) is attributable to a single, specific
corporate-action microstructure mechanism that requires real-world
company-identity knowledge to detect. Pure statistical machinery, however
rigorous, cannot see it. This generalizes as a methodological warning
beyond SPACs specifically: any security class with a mechanically shared
near-constant price anchor (money-market-adjacent ETFs, certain
closed-end funds trading near NAV, warrants near expiry) is a candidate
for the same failure mode, and a production screening pipeline operating
at real universe scale needs an explicit taxonomy of these mechanisms,
not just a statistical significance threshold.

### 7.4 Return Jumps Are Invisible to Existing Data-Quality Machinery

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
206 unique symbols (all at 1D; intraday history for most PIT-safe pairs
is too short/gappy to pass at this scale, a disclosed data-availability
constraint). **0.0% overlap between statistically-detected jumps and
non-NONE GapFlag bars, in all 640 of 640 rows.** Jump frequency: mean
0.51%, median 0.47% of bars. Jump-adjusted (continuous-only) volatility
is 5.8-7.3% lower on average than naive full-sample volatility.

**What this tells us about market structure.** GapFlag and jump-diffusion
detection are not two views of the same phenomenon, and this is not a
one-pair idiosyncrasy. It replicates exactly (0% overlap, at scale) across
206 symbols. A price series can be perfectly clean by every data-continuity
measure this project's own infrastructure checks for, and still carry
real, economically material jump risk that infrastructure has no
mechanism to see, because gap-continuity and jump-magnitude are answering
different questions about the same series. This is a real, disclosed
candidate for a volatility-estimator refinement (not yet wired into
production risk/stop logic, a deliberate v1 research-only scope), and a
broader methodological point: "clean data" (no missing bars, no halts)
and "well-behaved returns" (no large discontinuous moves) are
independent properties that a rigorous pipeline needs to check
separately, not treat as a single data-quality gate.

### 7.5 A Purely Mechanical Artifact Can Produce an Exact 15.8-Sigma False Anomaly

**The mechanism.** Reindexing intraday bars onto a continuous calendar and
forward-filling non-trading minutes (a common, often-default convenience
in time-series tooling, e.g. `reindex().ffill()`) silently contaminates
any fixed-width rolling-window statistic computed downstream. When a
rolling window straddles a forward-filled run, it contains `(n-1)`
identical padded values and exactly 1 real value.

**The exact, derived artifact.** For a rolling z-score over a window of
`n` points with `(n-1)` identical values and 1 differing, the result is
*exactly* `(n-1)/√n`, pure arithmetic, not a statistical approximation.
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
without being traced to this specific mechanical cause. Stated as a
testable hypothesis for a reader to check against their own pipeline, not
an accusation against any specific published study.

**The fix, briefly** (full account: `Development.md` BUG-D45): compute
rolling statistics on a compacted, real-bars-only sub-series (gap-flag
excluded), then scatter results back onto the full-length index with
padded positions left missing. Never feed a padded value into any
entry-signal computation or training label.

**What this tells us, as the odd one out among the six.** The rest of
§7 (and §4/§5 above) are about the market's actual statistical structure
(or a real data-generating mechanism the market exhibits). This one is
not. It is a pure engineering artifact, entirely independent of any real
price dynamics, that is nonetheless capable of producing a numerically
enormous, suspiciously anomaly-shaped signal. Its inclusion here is
deliberate: production-scale statistical arbitrage research cannot
distinguish "real market structure" from "a bug in how the calendar was
handled" without this kind of exact, closed-form derivation. A purely
empirical anomaly hunt, however careful, would have reported this as a
genuine finding.

### 7.6 Complexity Earns Its Keep Only When It Corrects a Specific False Assumption

Five independent method-sophistication comparisons across this project,
spanning position sizing, hedge-ratio estimation, and portfolio
concentration, each pit a more sophisticated method against a simpler
alternative on the same real production data:

- **Loss**: Hierarchical Risk Parity (true cross-pair covariance,
  hierarchical clustering) vs. simple risk-parity (per-pair volatility
  only). HRP OOS Sharpe 5.3752 vs. 5.8689: HRP loses.
- **Loss**: Kalman slope+intercept hedge ratio vs. origin-only Kalman.
  The 2-state version is *provably* better-specified statistically
  (tighter, more stationary spread on every one of 22 pairs, ADF
  improves on 15/22) but produces a *worse* trading signal (fixed-share
  Sharpe 2.35 vs. OLS's 12.28). This traces to a mechanistic cause: fixed
  per-share commission costs are invariant to spread scale, so a
  tighter spread's smaller gross P&L is disproportionately eaten by
  cost, not merely "Kalman lost."
- **Loss**: Equal Risk Contribution (constrained variance-of-contribution
  optimization) vs. simple inverse-cluster-size sizing. Simple sizing
  wins on Sharpe (0.7216 vs. 0.6933) and avoids ERC's real cost of
  concentrating up to 27% of the portfolio into 1-2 low-variance pairs.
- **Loss**: continuous eigenvalue-penalized position weighting vs. the
  same simple inverse-cluster-size scheme. Every variant tested
  underperforms (best 0.65-0.69 vs. simple's 0.7216), including a
  Marchenko-Pastur-adaptive version built specifically to fix an
  eigenvalue-degeneracy instability caught during verification, not real
  data. The fix was necessary for correctness but did not change the
  outcome ranking.
- **Win**: Meucci's eigenvalue-based Effective Number of Bets vs.
  Grinold-Kahn's equicorrelation breadth. Grinold-Kahn assumes uniform
  correlation and, given this portfolio's near-zero *average* pairwise
  correlation (ρ̄=0.0039), reports almost no diversification loss
  (BR_eff=19.5 of 21). Meucci's eigen-decomposition detects that the
  real correlation structure is *clustered* (specific pair-pairs at
  0.29-0.31, most at ~0) and correctly reports a materially lower
  ENB=9.78. The simpler method's uniform-correlation assumption is
  actively wrong for this portfolio, not merely less refined.

**The pattern, read honestly rather than resolved into a false moral.**
"Simple beats complex" would overstate four losses into a rule the fifth
result directly contradicts. What actually distinguishes the win: in the
four losses, the simpler method makes a *different, adequate* simplifying
assumption that happens to interact better with a downstream cost or
noise factor the complex method ignores. In the win, the simpler method's
specific assumption (uniform correlation) is demonstrably false for this
data. **Complexity pays off specifically when it corrects an identified
false assumption in the simpler alternative, not whenever it adds more
parameters.** This is itself a decision rule with predictive value: before
building a more complex method, the diagnostic question is "does the
simpler version's specific assumption actually hold here," not "is the
simpler version too crude" in the abstract.

---

## 8. Honest Limitations and Biases, Stated Directly [DRAFTED]

Following this project's own stated discipline (never silently correct
away a known bias), restated per finding here rather than left to a
single catch-all section, since each has a different scope:

- **§4 (PIT discovery, causal-validity finding)**: the original 1,576-
  symbol/1h result is directional/qualitative (4 folds, only 2 with any
  trades, ~37 trades total), not a high-power estimate. **Now re-run at
  the corrected ~43,883-symbol WRDS-primary universe** (`research/
  pit_wfa_wrds_daily.py`, §4's own text) — each PIT fold's own candidate-
  pair count is smaller and cutoff-specific, not a single shared figure
  with §5's full-history 638,095-pair count (§4 itself states this
  precisely) — necessarily at
  daily, not 1h, granularity, since WRDS/CRSP carries no intraday data at
  all (§2); this was checked directly, not assumed, before building the
  new script. The corrected-scale result is likewise directional (4
  folds, 2 capital-constrained-positive, 2 negative) and does not resolve
  the causal-validity question into either a cleaner confirmation or a
  cleaner refutation than the original table already showed — the largest,
  most statistically substantive fold (1,533 raw trades) is positive, but
  half of all four folds across both the original and corrected-scale
  tables remain net negative. **Pooled headline Sharpe built 2026-09-08**
  (design agreed with Ross beforehand — arithmetic-pooled across the fold
  boundary, no capital compounding; the inter-fold calendar gap dropped,
  not zero-filled, since zero-filling untested time would dilute
  volatility with days this project has zero evidence about;
  annualization keyed to the spliced series' own actual daily-observation
  count, per `research/pit_wfa_pooled_equity_curve.py`,
  `debug/_verify_pit_wfa_pooled_equity_curve.py`, 6/6 checks): pooled
  Sharpe is **+0.1845** (rolling variant, fold1_roll→fold2_roll spliced)
  and **+0.1285** (expanding variant, fold1_exp→fold2_exp spliced) — both
  positive. **Read with real caution, not as a clean resolution**: the
  synthetic verification suite also confirmed a genuine, disclosed
  property of this pooling method — it weights by **calendar days
  present in each fold's own daily-zero-filled series, not by trade
  count**. Fold1 (11 trades) spans 1946–1957 (4,018 daily observations);
  fold2_roll (309 trades) spans 1996–2026 (10,988 daily observations) —
  fold2's ~3× longer daily-observation count means it dominates the
  pooled mean/std regardless of the two folds' opposite signs
  (fold1 Sharpe −0.4779, fold2_roll Sharpe +0.2175). The positive pooled
  number is a real, correctly-computed consequence of this weighting, not
  an artifact of a coding error. **Confirmed decisively 2026-09-08 that
  this is not just a caveat but a load-bearing choice**: an equally
  defensible ALTERNATIVE construction — equal-weighting each fold's own
  Sharpe regardless of its calendar span, via
  `pool_variant_equal_weighted()` in the same script — gives **−0.1302**
  (rolling) and **−0.1431** (expanding), the OPPOSITE SIGN from the
  calendar-day-weighted figure above. The pooled headline's sign is not
  robust to which defensible weighting scheme is chosen — this is not
  "the strategy is unambiguously positive across history" under any
  honest reading, since two reasonable pooling methods disagree on the
  sign itself. The fold-to-fold sign disagreement this section already
  reports remains the single most honest headline — the "positive pooled
  Sharpe" number above should be read as one specific construction's
  output, presented alongside its equal-weighted counterpart, never
  alone.
  **Checked directly this session (2026-09-08), resolving
  the earlier "unverified" flag on this point**: the corrected-scale
  universe's WRDS core is NOT a raw present-day cache glob the way the
  original 1h table's universe is (below) — `data_wrds.py`'s
  `_get_universe_us_equity_etf_symbols()` starts from `UniverseBuilder`'s
  current S&P 1500 + ETF constituent list (survivorship-biased on its
  own), but a dedicated pass then fetches every historically-delisted
  S&P 500 member CRSP's own point-in-time membership table
  (`crsp_a_indexes.dsp500list_v2`) names and today's Wikipedia-scraped
  table misses — 1,956 permnos have EVER been S&P 500 members against
  503 today, so this recovers roughly 74% of the large-cap layer's
  historical membership that a naive current-constituents scrape would
  silently drop. The fix is real but explicitly partial, disclosed in
  `data_wrds.py`'s own comment: **S&P 400/600 have no equivalent
  point-in-time membership product in this WRDS subscription**, so the
  mid-cap and small-cap layers of the corrected-scale universe remain on
  the same current-constituents-only Wikipedia-scrape approach as
  before, with the same survivorship bias, undiminished. Net effect:
  survivorship bias in the corrected-scale universe is reduced, not
  eliminated, and reduced unevenly across cap tiers — large-cap history
  is mostly recovered, mid/small-cap history is not. **A sharper
  version of the "Universe-wide" survivorship disclosure below, specific
  to this finding, not just generic**: `pit_wfa.py`'s PIT re-screen at
  each historical cutoff draws its candidate pool from every symbol with
  a currently-cached `output/cache/*_1hr.parquet` file — a direct,
  present-day cache glob, not a reconstructed as-of-that-date universe
  (confirmed by reading the code directly this session, correcting an
  earlier, inaccurate draft of this disclosure that named
  `universe_loader.load_full_universe()` instead). A symbol that existed
  and would have been screenable at a 2015 cutoff but is no longer
  cached today is invisible to every one of the 4 folds. This means even
  the "causally-constrained" screen in §4 still benefits from hindsight
  about which symbols mattered enough to still be cached today — the
  true live-deployment gap between a full-history screen and a genuinely
  causal one could be larger than this section reports, not smaller,
  since a fully PIT-safe universe reconstruction would remove even more
  information §4's test currently still has access to. **A second,
  separate reproducibility gap, found live this session**: re-deriving
  each fold's confirmed-pair set today does not reproduce the original
  table's counts (§4's own text) — the cached universe size and fold
  cutoff dates are both nearly unchanged, so the most likely explanation
  is that the shared screening pipeline (`analysis.py`/`Config`) itself
  has changed in the weeks since the original run. §4's point estimates
  are historically-dated results tied to a specific code version and
  cache state, not a fixed fact re-derivable on demand.
- **§5 (crisis-regime, signal finding)**: the pooled two-proportion
  z-tests treat each crisis-first pair as an independent trial; checked
  directly (`research/crisis_regime_episode_clustering_check.py` plus a
  cluster bootstrap, `research/crisis_regime_cluster_bootstrap_test.py`),
  this does not hold — the 11,715 crisis-first pairs cluster into just 12
  distinct historical episodes. The confirmation-rate claim does NOT
  survive cluster-robust re-testing (95% CI comfortably contains calm's
  rate, cluster-robust p=0.25) even though the underlying 2-of-12-episode
  concentration behind it is independently confirmed real, not chance
  (`research/crisis_regime_concentration_significance_test.py`; binomial
  p=0.000006, Monte Carlo p=0.00002) — something genuinely unusual
  happened in 2008-09 and 2011, but it is not evidence that crisis
  conditions generally predict confirmation. Persistence DOES survive
  cluster-robust re-testing (95% CI [77.5%, 96.3%], cluster-robust
  p=0.032 — significant, but an order of magnitude weaker than the naive
  z=32.2 implied) and is not immune to two named confounds, one now
  directly tested. Crisis-era factor co-movement (Forbes & Rigobon,
  2002; Longin & Solnik, 2001) was tested directly via residualized
  correlation (`research/residual_correlation_factor_test.py`): the
  reappearance gap survives factor-adjustment in the 6.7% of pairs whose
  correlation is genuinely not factor-driven (88.26% vs. 78.41%, z=9.13),
  but most of the raw pooled effect sits in the factor-explained subset
  (91.42% vs. 78.67%, z=31.05) — the confound is real, not total; these
  z-values are naive pooled tests, not yet re-verified cluster-robust.
  Survivorship of crisis-discovered pairs into the current-constituent
  universe remains untested. Confirmation STRENGTH is not statistically significant at
  all (Mann-Whitney p=0.196, underpowered at only 29 crisis-confirmed
  pairs) — reported as directional, not folded into the headline claim.
  The regime classification uses VIX alone (`macro.py`'s existing
  calm/normal/elevated/crisis buckets); this paper does not claim the
  same pattern would hold under a different regime proxy (credit
  spreads, realized-vol regime, etc.) — untested, a named future-work
  item (§10). The confirmation-rate effect is NOT a clean dose-response
  across regime severity (§5's own disclosed non-monotonicity) — the
  finding is specifically a crisis-extreme effect, and should not be
  generalized to "more stress predicts more cointegration." This finding
  is observational/descriptive; it does not test whether acting on it
  (e.g. regime-conditional entry-criteria weighting) would improve any
  downstream trading outcome — a deliberate, disclosed scope boundary
  (§10), not yet crossed into "pick a new threshold" territory this
  project's own convention flags as risky before confirming the
  underlying pattern is real.
- **§7.1 (BH-FDR)**: the BH-vs-BY comparison's most current numbers are
  from a disclosed N=300 sample of a since-corrected universe loader, not
  yet re-run at full ~44,700-symbol scale. This paper does not claim a
  resolved BH-vs-BY verdict until that re-run exists (tracked, §10).
- **§7.2 (episodic cointegration)**: this finding, along with §7.1's
  candidate-pair count, was originally reported at a stale
  158,849-candidate-pair figure, dated 2026-08-13, predating the §2
  universe-undercount fix (found and fixed 2026-08-24) by eleven days.
  **The corrected-scale re-run completed 2026-09-02** (638,095 candidate
  pairs; see Finding #41 for the real root-cause fix that unblocked it)
  — §7.1 and §7.2 now report that real, corrected-scale result, not a
  placeholder.
- **§7.2/§4 (regime segmentation / negative backtest)**: both are
  daily/hourly-scale findings on the current WRDS-primary or
  yfinance-cached universe respectively; neither has been extended to
  the full intraday-timeframe granularity CAMARF's production pipeline
  also screens.
- **§7.3 (SPAC taxonomy)**: the regex-based detector is disclosed as
  non-exhaustive (the Social Capital Hedosophia SPAC family is a known,
  named gap). The 27-of-78 promotion also does not re-apply the
  `coint_fraction_rolling` stability threshold production's normal
  pipeline applies later. This is an inclusion-looseness choice, not an
  identity-correctness bug, disclosed in the promotion script's own
  runtime output.
- **§7.4 (jump-diffusion)**: PIT-safe result is 1D-only by data
  availability (intraday history for most PIT-safe pairs fails the
  200-clean-returns filter). The 5.8-7.3% vol reduction at 1D should
  not be assumed to hold at intraday granularity, where the original
  single-pair result (26-42% reduction) suggests the effect may be
  considerably larger, not smaller, at finer granularity.
- **§7.5 (calendar padding)**: the claim about *other* published research
  inheriting this exact failure mode is explicitly stated as an
  unverified, testable hypothesis, not a checked fact about any specific
  external paper.
- **Universe-wide**: the equity/ETF universe remains a current-constituent
  snapshot (survivorship bias, disclosed per this project's standing
  convention, not corrected away) for all findings in this paper.
- **Reproducibility, a real practical barrier not previously stated**:
  §4, §5, and §7.1-§7.3 depend on WRDS/CRSP data, a paywalled
  institutional subscription — an independent researcher without WRDS
  access cannot reproduce those sections from the data sources named
  here, only the yfinance-sourced portions of the pipeline (§7.4's
  jump-diffusion result, §7.5's calendar-padding derivation) are
  reproducible on freely-available data. This paper's verification
  discipline (every finding backed by a named `debug/_verify_*.py`
  synthetic-ground-truth test, referenced at each finding) is
  independently checkable without WRDS access; the real-data results
  themselves are not.
- **AI-tool disclosure**: full cross-reference to `PAPER.md` §9's AID
  Framework role taxonomy and tool-transparency sections, unchanged,
  applies identically to this paper's own production.

---

## 9. Relationship to the Companion Backtest Paper [DRAFTED]

`PAPER.md` remains the empirical demonstration that this paper's
methodology, applied end-to-end to CAMARF's own confirmed pair set,
produces a real, disclosed, non-overclaimed backtest result (its own
5.24 OOS Sharpe headline, itself qualified directly by this paper's §4
negative-backtest finding, which `PAPER.md` §7.3.1 already houses and
this paper reproduces and foregrounds). The two papers share
infrastructure (§3 above) and a bibliography; they differ in scope and
headline claim, per the framing decision stated at the top of this
document.

---

## 10. Future Work [OUTLINED]

- Re-run `bh_vs_by_full_universe.py` against the corrected
  ~44,700-symbol universe (§7.1's disclosed pending item). This is the
  single most important open item before this paper's §7.1 claim can be
  considered scale-complete.
- Extend §4's negative-backtest test to the current 29-pair confirmed set
  (post-§7.3 promotion); the existing result predates this session's
  full-universe promotion.
- Extend §7.4's jump-diffusion PIT-safe result to intraday granularity,
  once enough PIT-safe intraday pairs exist to clear the
  200-clean-returns filter.
- A more exhaustive SPAC/NAV-clustering taxonomy (§7.3), covering naming
  conventions the current regex misses (e.g. the Social Capital
  Hedosophia family).
- Connect §7.2's regime-strength segmentation to §4's PIT-confirmation
  precision: does a pair's regime strength (strong/moderate/weak,
  §7.2) predict whether it survives a genuine point-in-time re-screen?
  Not yet asked of the data.
- Test whether §5's regime-conditional confirmation/persistence pattern
  holds under a different regime proxy (credit spreads, realized-
  volatility regime) rather than VIX alone — would strengthen the claim
  beyond a single macro indicator.
- Test whether §5's finding, if acted on (e.g. as a regime-conditional
  confidence weight on newly-discovered candidates), actually improves
  any downstream trading outcome — deliberately not attempted in this
  paper (§8), the natural next step once the descriptive pattern itself
  is established, which is this paper's own contribution.
- **DONE** — the market-wide-factor-co-movement confound named in §5's
  episode-clustering robustness check: `research/residual_correlation_
  factor_test.py` regressed each of 5,700 unique symbols against SPY and
  tested crisis-vs-calm reappearance on the residual (factor-adjusted)
  correlation. Real, decisive answer (§5, §8): the effect is real in the
  6.7% of pairs whose correlation survives factor-adjustment, but most
  of the raw pooled effect sits in the factor-explained subset — the
  confound is real, not total. Still open: whether it holds on a
  look-back-limited universe snapshot that does not condition on
  surviving to the present (mitigating, not eliminating, the
  survivorship concern) — not yet tested.
- **DONE** — re-running §4's PIT-lookahead test at the corrected
  ~43,883-symbol WRDS-primary universe §5 also draws from (each PIT
  fold's own candidate-pair count is smaller and cutoff-specific, not
  §5's shared 638,095-pair full-history figure — §4 states this
  precisely): `research/pit_wfa_wrds_daily.py`, at daily (not 1h)
  granularity since WRDS/CRSP has no intraday data. Real result (§4):
  still genuinely
  mixed (2 of 4 folds capital-constrained-positive, 2 negative), the
  same qualitative pattern the original 1,576-symbol/1h table already
  showed — corrected scale did not resolve the causal-validity finding
  into a cleaner story either way. **DONE (survivorship half)** — checked
  directly (§4): the corrected-scale universe's survivorship bias is
  reduced but not eliminated, and unevenly across cap tiers (large-cap
  history ~74% recovered via a dedicated delisted-S&P-500 fetch pass,
  mid/small-cap still current-constituents-only — no equivalent
  point-in-time product exists for S&P 400/600 in this WRDS
  subscription). **DONE (pooled-Sharpe half), 2026-09-08** — see §4 for
  the full result. Two defensible pooling constructions disagree even on
  SIGN: calendar-day-weighted gives +0.1845 rolling / +0.1285 expanding;
  equal-weighted-per-fold gives −0.1302 / −0.1431. Not a clean resolution
  of the underlying sign disagreement — the opposite: direct confirmation
  that no single pooled number should be trusted over the fold-to-fold
  disagreement itself.
- **DONE, 2026-09-08** — does a pair's regime-context signal (§5) predict
  whether it survives a genuine PIT re-screen (§4)?
  `research/pit_confirmation_vs_regime_interaction.py`
  (`debug/_verify_pit_confirmation_vs_regime_interaction.py`, 8/8) joins
  the two directly. Real result, striking but genuinely ambiguous: §5's
  statistically-confirmed crisis-reappearance pairs are PIT-confirmed at
  1.72% vs. 0.0003% for everything else (z=98.7, p≈0). Checked and
  disclosed before trusting it: only 18 of §4's 320 PIT-confirmed pairs
  even appear in §5's 638,095-pair universe (a real, low-power
  constraint on the test, not hidden), and both screens likely select for
  the SAME underlying property (genuine correlation/cointegration
  strength) — so this may be two tests detecting one signal, not a novel
  regime-conditioning insight. Read as real and positive, not as a clean
  empirical demonstration of "why one paper, not two" — the honest next
  step (not built) is testing whether the effect survives controlling for
  raw correlation strength directly. Full account: Finding #65.

---

## References

Shared bibliography with `PAPER.md` §2; see that section for full
sourcing status of each citation (Engle-Granger, Benjamini-Hochberg/
Yekutieli, Lee & Mykland 2008, Meucci, Grinold-Kahn).

**Two citations added 2026-09-02, not shared with `PAPER.md`**, both cited
in §5 as named confounds for the crisis-regime finding (one, factor
co-movement, since directly tested — §5; the other, survivorship, still
open), per an adversarial review of this paper that found the original
draft engaged
with none of the correlation-breakdown-in-crises literature despite
motivating §5 with exactly that phenomenon: Forbes, K. J., & Rigobon, R.
(2002). "No Contagion, Only Interdependence: Measuring Stock Market
Comovements." *The Journal of Finance*, 57(5), 2223-2261. Longin, F., &
Solnik, B. (2001). "Extreme Correlation of International Equity
Markets." *The Journal of Finance*, 56(2), 649-676.

**A citation considered and cut, kept here for provenance per this
project's "document what was tried and reverted" discipline**: Rovelli,
C. (1996). "Relational Quantum Mechanics." *International Journal of
Theoretical Physics*, 35(8), 1637-1678 (arXiv:quant-ph/9609002). Added
2026-09-01 as a naming analogy for the earlier "Unwarranted Confidence"
seven-finding thesis (a fact holding only relative to a specific frame
of reference, not absolutely); already reduced to footnote weight after
two independent council reviewers confirmed that draft's thesis read no
weaker without it. Cut entirely in the 2026-09-02 narrowing to the
discovery-event thesis: the new frame is about causal validity and
regime information carried by a specific discovery event, a narrower and
more concrete claim the analogy does not add precision to. Verified
against the actual paper, not a secondary summary, before it was ever
cited; see `docs/research/RQM_CONCEPTUAL_LENS_2026-09-01.md` for the
full verification.
