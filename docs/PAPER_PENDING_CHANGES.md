# PAPER.md / README.md — Pending Changes (drafted, not applied)

**Status: DRAFT ONLY.** Per Ross's explicit instruction (2026-07-14, overnight autonomous session):
draft everything from Phases 12-18 that would touch PAPER.md or README.md here — do NOT edit those
files directly until Ross reviews and approves. Everything else (code fixes, Development.md entries,
new research scripts, re-run analyses) proceeds directly as normal; this file exists ONLY for the
subset of work that would otherwise have gone straight into PAPER.md/README.md.

Each entry below: which section it targets, the current text/number (if replacing something), the
proposed new text/number, and the source (which script/run produced it, so Ross can verify before
merging). Organized in the order phases produced them, not by PAPER.md section — a table of contents
will be added once there's enough content to need one.

---

## 1. §4.2.1 — add a methodological caveat to the Monte Carlo null-construction (Phase 12, STORM perspective 1/4)

**Target**: PAPER.md §4.2.1 (currently ends "...including, concretely, one drawn in an earlier draft of
this project's own headline finding.")

**Why**: STORM's econometrician-lens research (Development.md, "Phase 12, perspective 1/4") confirms
§4.2.1's CURRENT conclusion is well-supported — "EG is over-conservative" is not a real literature
finding, and §4.2.1 already correctly refutes it as "appropriately strict, not miscalibrated." No
change needed to that core claim. But the research surfaced ONE real, unaddressed vulnerability in the
Monte Carlo's own null-construction methodology: Richards (1998) found major equity indices share a
single dominant common stochastic trend (via Johansen tests) — meaning randomly re-paired real equity
series may retain residual common-factor co-movement even after the true bilateral pairing is
destroyed, which could bias the measured 7.75%-12.75% empirical rejection rate in either direction
relative to a genuinely factor-free null. This is a real, citable, currently-unaddressed limitation of
the Monte Carlo's design worth disclosing explicitly (matches this project's own §9 standard).

**Proposed addition** (new paragraph, end of §4.2.1, before the "Reported here, refuted rather than
quietly dropped" sentence):

> **A caveat on the null construction itself, not yet resolved**: the randomly-re-paired "null" pairs
> above preserve each series' own real volatility and autocorrelation, but do not explicitly control
> for residual common-factor exposure — major equity indices are documented to share a single dominant
> common stochastic trend (Richards 1998, *Journal of International Money and Finance*), so two
> randomly-paired real equities may retain some genuine co-movement even after their true economic
> relationship (if any) is destroyed by the shuffle. Whether this inflates the 7.75%-12.75% empirical
> rate above relative to a genuinely factor-free null — and if so, by how much — is not established
> here; a market-beta-demeaned or sector-neutral version of this same calibration would settle it and
> is noted as a natural follow-up, not yet run.

**Source**: `debug/_ibkr...` — no, source is the STORM research fork itself (Development.md, Phase 12
perspective 1/4 entry, 2026-07-14), citing Richards, A., "Stochastic trends and cointegration in the
market for equities," https://www.sciencedirect.com/science/article/abs/pii/S0148619598000319.

**Status**: drafted, not applied. Low-risk, additive-only change (doesn't alter any existing number or
conclusion) — reasonable to merge as-is once reviewed, or hold pending the suggested follow-up
calibration run if Ross wants the caveat resolved rather than just disclosed.

---

## 2. §7.5 — correct the "fast reversion → harder to detect" causal claim (Phase 12, STORM perspective 2/4)

**Target**: PAPER.md §7.5, the paragraph beginning "A candidate explanation, distinct from §4.2/§4.2.1
and not independently tested the way those were... a pair that barely clears 3-8% of 252-bar rolling
windows might not be a borderline cointegrator so much as an established relationship tested at a
resolution where even strong cointegrators fail most individual windows, if the short-window EG test
has low power at n=252 specifically."

**Why**: STORM's market-microstructure research (Development.md, "Phase 12, perspective 2/4") found the
literature supports the GENERAL "short window → low power" framing (four converging sources: Hakkio &
Rush 1991, Pierse & Snell, Otero & Smith, Shiller & Perron — power is span-driven, and 252 bars of 1h
data is only ~10.5 trading days, a real span mismatch relative to CAMARF's own multi-year full-sample
tests). BUT the current text doesn't specify a direction, and if a future draft were to add "fast
reversion is harder to detect than slow reversion" (a natural-sounding elaboration), that would be
WRONG per classical AR-root power theory — power is low when the true root is close to unity (slow
reversion) and RISES as reversion speeds up. This is a preemptive correction/clarification, not a fix
to an existing wrong claim (current text doesn't state a direction) — but worth adding explicitly so a
future editing pass doesn't introduce the wrong-direction version, which would look plausible but isn't.

**Proposed addition** (append to the existing paragraph, after "...if the short-window EG test has low
power at n=252 specifically."):

> Note the direction this predicts: classical AR-root power theory (power rises as the true root moves
> further from unity) implies FASTER-reverting relationships should be, if anything, EASIER for a
> short-window EG test to detect, not harder — so this hypothesis, if correct, would not explain a
> "strong pair looks weak because it reverts fast" story; it would instead explain a uniform, half-life-
> independent power deficit at n=252 relative to CAMARF's own much longer full-sample tests, most
> directly attributable to n=252 bars (~10.5 trading days) being a real span mismatch against the
> multi-year spans this test's own asymptotic theory and critical values were built for. No study
> calibrating a ROLLING pass-rate diagnostic (as opposed to a single full-sample test) at a short window
> was found in the literature — this remains untested territory, not confirmed by the citations above.

**Status**: drafted, not applied. This is a clarifying/correcting addition to an already-hedged,
already-honest paragraph — low risk, but touches the paper's interpretation of its own coint_frac
inversion finding, worth Ross's explicit read before merging.

---

## 3. §7.2 — add a literature-grounded mechanism for why risk-parity beats HRP (Phase 12, STORM perspective 3/4)

**Target**: PAPER.md §7.2, line ~1319: "HRP was evaluated and is not recommended — it underperforms
risk-parity on this pair set." (currently states the result with no explanation)

**Why**: STORM's systematic-fund-practitioner research (Development.md, "Phase 12, perspective 3/4")
found this result is consistent with, not surprising relative to, the literature — and identified the
likely mechanism. Adds real explanatory content the current text lacks.

**Proposed addition** (append after the existing sentence):

> This is consistent with, rather than surprising relative to, the portfolio-construction literature.
> HRP's advantage over simpler risk-based methods is conditional on a stable, well-estimated
> correlation structure for its hierarchical-clustering step to exploit — a condition that is worst-met
> precisely under small-N, short-history covariance estimation (Jain & Jain 2019 find inverse-
> volatility-style risk-parity weighting is the MOST robust method under crude covariance estimation,
> with HRP in between and less robust than simple risk-parity in that specific regime — directly
> predicting the ranking observed here). Separately, HRP's documented Sharpe advantage over competing
> methods has been shown to concentrate in the n≈20-50 constituent range; this project's confirmed-pair
> count (2-30 pairs depending on point-in-time snapshot) sits at or below the bottom edge of that range,
> not comfortably inside it. The broader literature on hierarchical-clustering portfolio methods is
> itself described as "inconclusive" on outperformance versus traditional risk-based portfolios,
> consistently flagging sensitivity to covariance-estimation quality as the reason (Trucíos 2026) — so
> this result is a specific instance of an already-documented boundary condition, not an anomaly.
> **Open question, not resolved here**: neither HRP nor risk-parity literature treats shared-leg hub
> concentration (the same underlying name appearing as a leg in multiple pairs, §7.2's own DD-hub
> analysis above) as a distinct risk category separate from ordinary return correlation — a genuine gap
> in both methods' design, not just in this comparison.

**Source**: Development.md, Phase 12 perspective 3/4, citing Jain & Jain (2019, *Risks*, MDPI,
https://www.mdpi.com/2227-9091/7/3/74), Trucíos (2026, *Empirical Economics*), and a Network Risk
Parity study (2024, *Journal of Asset Management*) on HRP's size-dependent Sharpe advantage.

**Status**: drafted, not applied. One source citation (on shrinkage estimators specifically) could not
be independently re-verified during STORM's research pass and was deliberately left OUT of this draft
for that reason — only re-confirmed claims are included above, per this project's citation-verification
standard.

---

## 4. §7.3.1 — replace stale point-in-time checkpoint numbers with the fresh 3-checkpoint rerun (Phase 13 §7.3.1)

**Target**: PAPER.md §7.3.1 (lines ~1367-1434), the "Method" paragraph and "Result" table/interpretation.
This section is the paper's own designated highest-priority deferred item (marked [DRAFTED —
2026-07-01], predating this session's universe refetch/expansion and the BUG-D68/D69 lookahead fixes).

**Real internal inconsistency found while reading the current text, worth fixing regardless of the
numeric refresh**: the current "Method" paragraph describes "4 fold cutoffs (2 expanding, 2 rolling,
matching §7.3's fractions)" and the Result table has 4 rows (expanding/fold1, fold2, rolling/fold1,
fold2) — but the Result paragraph's own PROSE says "At every one of 3 independent historical
checkpoints (2024-02, 2025-01, 2025-08)," which doesn't match the 4-row expanding/rolling table above
it. This session's rerun used exactly those 3 named calendar checkpoints the prose already promised —
so this update resolves a real, pre-existing method/table mismatch, not just refreshes stale numbers.

**Proposed replacement for the "Method" paragraph**:

> **Method (`pit_wfa.py`, `--variant checkpoint_sweep`):** at 3 explicit calendar checkpoints
> (2024-02-01, 2025-01-01, 2025-08-01), the full confirmed-pair screening pipeline — `UniverseFilter`
> correlation pre-filter, `CointScanner` EG + BH-FDR, `coint_fraction_rolling`, structural-pair
> exclusion, and the secondary-evidence override — is re-run using **only** data up to that
> checkpoint, exactly as a live deployment would have seen it at that point in time. The resulting
> point-in-time confirmed pairs are then traded forward from the checkpoint to the end of the
> currently-available history (2026-07-14), with the same, unmodified `BacktestEngine` every other
> result in this paper uses.

**Proposed replacement for the "Result" table and interpretation** (verification-history paragraphs
about the synthetic test and the alignment-mode bug fix stay as-is — both are still true and still
apply, since this rerun reuses the same `screen_universe_at_cutoff`/`backtest_pair_on_test_window`
functions):

> **Result: pair counts collapse sharply as more training history accumulates, and the OOS outcome
> swings from strongly negative to modestly positive across the 3 checkpoints — reported together, no
> cherry-picking:**
>
> | Checkpoint | Train window | Pairs confirmed | Pairs traded | Trades | OOS Sharpe |
> |---|---|---|---|---|---|
> | 2024-02-01 | ~7 months | 30 | 27 | 1,234 | **-1.9037** |
> | 2025-01-01 | ~18 months | 3 | 3 | 79 | +0.4241 |
> | 2025-08-01 | ~25 months | 1 | 1 | 11 | +1.0050 |
>
> None of the pairs found at any checkpoint (e.g. ACN/FFIV, AMG/AXP, FNF/SPGI, ORI/PPL) match this
> project's currently-known full-history confirmed set — the same zero-overlap finding as the original
> 2026-07-01 run, now confirmed again on the current, post-refetch universe.
>
> **Two findings, both consequential:** (1) confirmed-pair count collapses hard as training history
> grows (30 → 3 → 1) — consistent with this session's independently-established finding that more/
> cleaner training data tightens BH-FDR's admission threshold rather than loosening it (task #71). (2)
> The single most statistically meaningful result — by far the largest trade count (1,234) — is the
> earliest checkpoint's **-1.9037 Sharpe**: the checkpoint that most closely resembles what a real,
> newly-launched live system would have faced in early 2024, with only ~7 months of training history
> available. That point-in-time-confirmed 30-pair set would have gone on to LOSE significantly over the
> following ~2.5 years. The later checkpoints' positive Sharpes (0.42, 1.01) rest on only 79 and 11
> trades respectively — real, but far too thin to read as a genuine improving trend rather than noise on
> a shrinking sample.
>
> **Honest headline conclusion, replacing the prior interpretation**: this is not just evidence that a
> causally-run screen would have found a different, non-overlapping pair set (already established) — it
> is direct evidence that a live deployment starting from a realistic, short initial training window
> would have gone through a materially unprofitable early period. This is a genuine, sobering caveat
> about this system's live-deployment readiness starting from any realistic point, not fully answered
> by "more data resolves it," since every new live system necessarily starts in the short-training-
> window condition that produced the worst result here.

**Source**: Development.md, "Phase 13, §7.3.1 complete" entry, 2026-07-14; `output/backtest/pit_wfa_
{fold_comparison,portfolio,pair_sets}.parquet`; `pit_wfa.py`'s `build_checkpoint_specs()`.

**Status**: drafted, not applied. This is the single most consequential draft change in this file —
it materially changes the paper's own honest assessment of live-deployment readiness. Needs Ross's
explicit review before merging, not a routine number refresh.

---

## 5. §7.11 — deepen the Do & Faff crowding-vs-decay discussion with real literature grounding (Phase 12, STORM perspective 4/4)

**Target**: PAPER.md §7.11, "Era-decay replication (Do & Faff 2010)" paragraph, specifically "CAMARF's
own data cannot test the crowding side of that dispute... explicitly scoped out, not silently ignored."

**Why**: STORM's research (Development.md, "Phase 12, perspective 4/4") confirms this is a genuinely
unresolved literature dispute, not a gap in CAMARF's own reading — worth strengthening with real
citations rather than leaving as an assertion. Also found: Do & Faff's own paper leans structural/risk-
based (fundamental risk, noise-trader risk, synchronization risk), not explicitly "crowding" — the
current text's framing ("attributing it to weakening convergence properties... rather than crowding")
is accurate but can be sharpened with the actual mechanism Do & Faff propose.

**Proposed addition** (insert after "...explicitly scoped out, not silently ignored."):

> This dispute remains genuinely unresolved in the broader literature, not just in this project's own
> data: Do & Faff's own explanation is structural/risk-based (fundamental risk, noise-trader risk, and
> synchronization risk driving an increasing share of non-converging pairs), while a separate literature
> on anomaly-return decay finds real, quantified capital-crowding effects elsewhere in equity markets —
> McLean & Pontiff (2016) find 97 documented return predictors show 26% lower returns out-of-sample and
> 58% lower post-publication, consistent with capital chasing away documented mispricing; Khandani & Lo
> (2007) show statistical-arbitrage strategies specifically become highly correlated during forced-
> deleveraging events, direct evidence crowding is a real structural feature of this trading space. No
> study has directly decomposed crowding versus structural decay for pairs trading specifically using
> capital-flow data — one recent industry discussion states plainly this decomposition "is not
> quantifiable from public data." CAMARF's inability to test the crowding side is therefore consistent
> with a genuine open question in the field, not a project-specific data limitation alone.

**Source**: Development.md, Phase 12 perspective 4/4, citing Do & Faff (2010), McLean & Pontiff (2016,
*Journal of Finance*), and Khandani & Lo (2007, NBER working paper).

**Status**: drafted, not applied. Additive-only, strengthens an existing honest caveat with real
citations — low risk, reasonable to merge once reviewed.

---

## 6. §4.1 or new subsection — name the multi-timeframe FDR/power tension explicitly (Phase 12, STORM perspective 4/4)

**Target**: no single current PAPER.md section addresses this directly — candidate location is a new
paragraph near §4.1 (Screening Pipeline Overview) or wherever BH-FDR's cross-timeframe application is
first described, TBD by Ross since this is genuinely new content, not a correction to existing text.

**Why**: STORM's research confirms CAMARF scanning 14 timeframes simultaneously, each contributing
"discoveries" to a shared BH-FDR correction, is a genuinely under-addressed methodological question in
the literature — not something CAMARF is behind on, but something worth naming explicitly as an
acknowledged limitation, matching this paper's own standard of disclosing known-but-unresolved issues.

**Proposed new paragraph** (exact placement TBD by Ross):

> **A related, currently unaddressed methodological question**: CAMARF's BH-FDR correction is applied
> to candidates pooled across all 14 scanned timeframes. Benjamini & Yekutieli (2001) proved BH-FDR
> remains formally valid under positive regression dependence (a condition plausibly met here, since a
> genuinely cointegrated pair's test statistics across correlated timeframes should be positively, not
> arbitrarily, correlated) — but no literature was found addressing the specific case of the SAME
> underlying economic relationship contributing correlated "discoveries" at multiple simultaneously-
> scanned frequencies, as opposed to testing genuinely independent hypotheses. Separately, the
> span-vs-frequency power result (Hakkio & Rush 1991; independently reconfirmed by Otero & Smith 2000
> and Haug 2002 using different test frameworks) means CAMARF's shortest-span timeframes (1m/2m/3m,
> many bars but short calendar coverage) are systematically underpowered relative to 1D/1M scans — a
> real, literature-supported asymmetry across this project's own multi-timeframe design, not previously
> named explicitly. Building a proper correction for this (e.g., adapting Harvey & Liu's 2015 effective-
> independent-trials Sharpe-haircut methodology from the backtest-overfitting literature to a multi-
> timeframe cointegration screen) would be genuinely new methodology, not an existing fix to apply —
> noted here as an open limitation, not attempted in this version of the paper.

**Source**: Development.md, Phase 12 perspective 4/4, citing Hakkio & Rush (1991), Otero & Smith (2000),
Haug (2002), Benjamini & Yekutieli (2001), Harvey & Liu (2015).

**Status**: drafted, not applied. This is new content (not a correction), touches the paper's own
methodology-limitations framing — needs Ross's decision on exact placement and whether to include at
all in this version, not just a merge-or-not call.

---

## 7. §8 — update the pair-selection-lookahead bias entry with tonight's definitive finding (HIGHEST PRIORITY IN THIS FILE)

**Target**: PAPER.md §8, the "second entry" (the one starting "A second entry, drafted in equal
depth — the most material entry in this audit..."), specifically: "The confirmed pair set (26 as of
the current headline run)..." and "...§7.3.1 reports that a genuinely causal, point-in-time re-screen
at 3 independent historical checkpoints found a completely different pair set at every checkpoint
(zero overlap with the known confirmed set) and that those independently-discovered pairs lost money
in every backtested fold (Sharpe −1.04 to −0.72)."

**Why this is the most important entry in this whole file**: tonight's session found something more
severe than what this entry currently describes. The entry currently frames the risk as "the headline
pair set was found via a lookahead-contaminated screen, and a causal re-screen finds different,
unprofitable pairs" — serious, but still describes a WORLD WHERE A CONFIRMED PAIR SET EXISTS. Tonight's
fresh, definitive `analysis.py --timeframes 1h` rerun (Development.md, "Confirmed-pair-set blocker
RESOLVED") found **0 confirmed 1h pairs on current, clean data** — not a different pair set, no pair
set at all. This is categorically more severe than what §8 currently documents.

**Proposed replacement** for the entry's final two sentences (everything up through "...is not
evidence that a live, causally-run version of this pipeline would have discovered and traded it."):

> Unlike every other entry in this audit, this one has no remedy applied — it is quantified, not
> corrected. §7.3.1 reports that a genuinely causal, point-in-time re-screen at 3 fixed calendar
> checkpoints (2024-02-01, 2025-01-01, 2025-08-01) found completely different, non-overlapping pair
> sets at every checkpoint (30, 3, and 1 pairs respectively — zero overlap with each other or with the
> historically-known confirmed set), and that the largest and most statistically meaningful of these
> (the earliest checkpoint, 1,234 trades) lost significantly out-of-sample (Sharpe −1.9037). **A
> second, independent, and more severe check — a fresh, current, clean-data full-history 1h screen run
> the same night — found the historically-reported confirmed pair set does not currently exist at
> all: 0 pairs survive the full screening funnel (2 raw EG survivors out of 68,685 tested; neither
> cleared the structural-exclusion/coint_frac-threshold stages).** The residual risk here is therefore
> not merely high, as originally assessed — it is now the paper's single most consequential open
> finding: the headline pair-selection methodology, run cleanly and currently rather than on the
> original, since-corrected contaminated cache, does not currently reproduce a tradeable pair set at
> this timeframe. Every downstream headline number in this paper computed on the historical confirmed
> set (pair count, IS/OOS Sharpe, DSR, every §7 table) needs to be read in light of this finding, not
> alongside it as a separate caveat.

**Source**: Development.md, "Confirmed-pair-set blocker RESOLVED — the definitive answer is 0
confirmed 1h pairs on current, clean data" (2026-07-14); `latest_run_analysis.log`;
`analysis_1h_resolve_pairset_out.log`/`_err.log`.

**Status**: drafted, not applied. **This is not a routine update — it is the headline finding of the
entire overnight session and needs Ross's explicit, direct review before any merge.** Everything else
in this file is secondary to this entry. If Ross wants PAPER.md to lead with this finding rather than
bury it in §8, that's a structural decision (Abstract/Introduction framing) beyond what this file
should decide unilaterally — flagged here, not resolved.

**UPDATE (2026-07-15, after Ross explicitly requested a full bug sweep on this exact finding)**: the
"0 confirmed pairs" result is no longer just an observation — it now has a PROVEN mechanism, not a
hypothesis. Verified directly: BH-FDR is bit-for-bit correct (tested against `statsmodels.multipletests`
on both a textbook example and a synthetic 68,685-p-value array); the EG test is a standard,
unmodified `statsmodels.coint()` call. The actual cause: DD's confirmed BUG-D65 contamination produced
raw EG p-values with a median of ~1e-8 and a minimum of 2.3e-25 (for comparison, SPY/VOO — the most
mechanically-certain "cointegrated" pair in the entire market, two ETFs tracking the identical index —
only reaches 1.5e-14; DD's contaminated pairs beat that by 11 orders of magnitude). Literature
corroboration (MacKinnon's response-surface p-value approximation is a polynomial fit that is being
extrapolated far outside its validated range at this magnitude; the structural-break literature
independently documents unmodeled level shifts causing spurious stationarity rejections) confirms this
is a numerical artifact, not genuine economic significance. BH-FDR's step-up procedure needs an
UNBROKEN CHAIN of increasingly-significant p-values from rank 1 upward — DD's ~259 artificially tiny
p-values supplied that chain, letting the old run's cutoff extend to rank 314; removing them creates a
gap that the genuinely-real but "merely small" pairs (LNT/VTR etc., p≈2e-4) can't bridge, so the
procedure now terminates at rank 2. **This means the proposed replacement text above should be
strengthened, not softened**: this isn't an unexplained collapse to flag as concerning — it's a fully
understood, literature-grounded, mechanically PROVEN consequence of removing real data contamination
from a rank-dependent multiple-testing correction. See Development.md, "Ross explicitly distrusted the
0-confirmed-pairs finding — full bug sweep, root cause now PROVEN" for the complete investigation and
citations. **A new, separate, genuinely open methodological question this investigation surfaced**:
is a step-up FDR procedure this sensitive to supporting-chain gaps the right choice at CAMARF's
candidate-pool scale (tens of thousands of pairs), or does this fragility argue for a different
correction (Benjamini-Yekutieli, a two-stage procedure, or a fixed-threshold approach less dependent
on rank continuity)? Worth its own paragraph in §8 or §4.1, not resolved here — Ross's call.

**Status**: still needs Ross's review before merging, but now with a complete, proven, cited
explanation rather than an open question — the finding is stronger and better-grounded than it was
when originally drafted, not less.

**UPDATE (2026-07-20, the "genuinely open methodological question" above is now closed)**: built and
ran a 4-method FDR comparison (step-up BH, Benjamini-Yekutieli, two-stage TSBH, fixed Bonferroni) on
the full current 1h universe's real raw EG p-values (m=36,753), plus two further recovery attempts —
an independent Johansen+KPSS confirmatory check, and a same-GICS-sector-restricted rescan reusing the
same raw p-values under a smaller m. **None of the 4 correction methods — including Bonferroni, which
has no rank-chain dependency at all — recovers any of the 8 previously-flagged real-but-moderate pairs
(LNT/VTR, LNT/WELL, CMS/DUK, EG/WRB, HAL/NOV, MET/TMHC, PFG/STLD, UMBF/FHB).** This settles the question
definitively: the exclusion is not a BH-specific rank-chain artifact — a chain-independent method draws
the identical line. The real cause is scale: m≈36,753 simultaneous tests is a genuinely severe
multiple-testing burden, and these pairs' raw p-values (best case 5.3e-5) are 40-400× too large for any
defensible correction at this m. The sector-restricted rescan (shrinks m to 13,799, a legitimate,
literature-standard convention per Gatev/Goetzmann/Rouwenhorst 2006) narrows m nowhere near enough
(~2.7× vs. the ~26-100× these p-values would need) and cannot even test 4 of the 8 pairs since they are
cross-sector by construction. The confirmatory check does add one genuinely new, worth-keeping finding
though: Johansen (a fully independent test family, VECM-rank-based rather than EG's OLS-residual-ADF)
corroborates a cointegrating relationship in all 8/8 target pairs and correctly finds nothing in 4/4
known-null negative controls — real evidence these pairs are not pure noise, just evidence that does
not survive multiple-testing correction at this candidate-pool scale. **Recommend §8's proposed
replacement text above stand as-is** — the correction-method and universe-restriction questions this
entry raised are now closed with a definitive negative, not an open item requiring further hedging
language. See Development.md, "Both remaining 'recover the pairs, scientifically' avenues built and
run — honest, converged negative result" (2026-07-20) for the complete methodology and numbers.

**Status**: still needs Ross's review before merging into PAPER.md itself; the underlying investigation
is now fully closed out, not pending further diagnostic work.

---

## 8. §8 or §10 — persistence-filter comparison-arm result, a candidate mitigation for the pair-selection-lookahead risk (Ross's direct request)

**Target**: PAPER.md §10 (Future Work) is the most natural home — this is a tested MITIGATION for the
risk entry #7 above updates, not a correction to existing text. Could also be appended as a follow-up
paragraph directly after entry #7's §8 update, at Ross's discretion.

**Why**: Ross saw the checkpoint_sweep result live and asked directly what could be done about it, then
asked to build and test it immediately. This is a real, decisive, already-completed answer — worth
including regardless of which section it lands in.

**Proposed new paragraph**:

> **A tested candidate mitigation: requiring persistence across two point-in-time screens before
> trading.** Rather than trusting a single point-in-time confirmed-pair snapshot, a persistence filter
> was tested: a pair must be independently re-confirmed at both a checkpoint and 90 days earlier before
> becoming tradeable. Result, tested at the same 3 checkpoints as §7.3.1/§8: the filter completely
> eliminates checkpoint 2024-02-01's disastrous -1.9037 Sharpe (0/30 pairs survive being re-confirmed),
> but at a real cost reported honestly rather than only the upside — it ALSO eliminates
> checkpoint 2025-01-01's modest +0.4241 Sharpe (0/3 survive), and the net effect is zero trades for
> the first ~18 months of a hypothetical live deployment, only beginning to trade around the
> ~25-month mark (checkpoint 2025-08-01, unaffected since its single pair happened to already be
> persistent). This is not a clean win: the filter avoids catastrophic early loss but at the cost of
> also avoiding the one early period that would have been profitable, and of a long initial period
> with no trading activity or track record at all. It is also a further, independent confirmation of
> §8's headline finding — literally zero pairs survived being re-confirmed 90 days later at either of
> the first two checkpoints, underscoring how unstable this timeframe's point-in-time screening
> currently is, consistent with (not contradicting) the 0-confirmed-pairs full-history result above.

> **A second tested candidate mitigation: a minimum-training-history gate.** Requiring a full year of
> training history (vs. the ~7 months available at the earliest checkpoint) before a live deployment's
> first trade reduces the checkpoint 2024-02-01 scenario's severity substantially — Sharpe -0.2594 on
> 31 trades (1 pair, AMG/COF) vs. the original -1.9037 on 1,234 trades (30 pairs) — but does not
> eliminate the loss; the 12-month checkpoint is still net-negative. **Neither mitigation solves the
> early-period problem outright**: the persistence filter trades away ALL early activity (including the
> one profitable window) for zero exposure; the minimum-history gate trades away most volume for a
> smaller, still-negative loss. Both are genuine, quantified improvements over an unmitigated launch,
> with different, honestly-reported tradeoffs — a combined approach (both filters together) was not
> tested and is a natural next comparison.

**Source**: Development.md, "Comparison arm 1 complete: persistence filter" and "Comparison arm 2
complete: minimum-training-history gate" (2026-07-14);
`output/backtest/pit_wfa_{fold_comparison,portfolio,pair_sets}.parquet`; `pit_wfa.py`'s
`run_persistence_fold()` and `min_history_sweep` variant.

**Status**: drafted, not applied. Real, tested results Ross explicitly commissioned — should be
straightforward to merge once reviewed, though placement (§8 risk entry vs. §10 future work vs. both)
is Ross's call.

---

## 9. §4.1 — flesh out the Screening Pipeline Overview (Phase 15)

**Target**: PAPER.md §4.1, currently a bare bullet-fragment: "Correlation pre-filter (Pearson/
Spearman/rolling-average, confidence-tier tagged) → Engle-Granger + Benjamini-Hochberg FDR (per
timeframe) → hedge-ratio estimation (OLS/TLS/Kalman) → OU spread fit → eigenportfolio decomposition
(Marchenko-Pastur factor removal, Gold/Silver confidence tier) → `coint_fraction_rolling` stability
filter with secondary-evidence override → cross-asset structural exclusion (forex triangles, share
classes)."

**Why safe to flesh out now, despite tonight's 0-confirmed-pairs finding**: this section describes
PIPELINE MECHANICS — what each stage does and why — not results or pair counts. It doesn't need to wait
on Ross's reconciliation decision; the mechanics themselves are unaffected by how many pairs currently
survive them, and every claim below is grounded in code read/verified directly this session (most
recently: `analysis.py`'s own filter-funnel log output from tonight's 1h rerun, which enumerates
exactly this stage sequence with real stage-by-stage counts).

**Proposed expanded prose** (replacing the bullet fragment):

> The screening pipeline runs as a fixed sequence of stages, each a hard filter — a pair that fails any
> stage is dropped before the next, so the funnel narrows monotonically (see §5/§8's stage-by-stage
> counts for a concrete instance). **Stage 1, correlation pre-filter**: Pearson and Spearman correlation
> plus a rolling-average correlation are computed for every candidate pair in the universe; pairs are
> tagged into Gold/Silver/Bronze confidence tiers by correlation strength and consistency, and only
> pairs clearing a minimum absolute correlation threshold (|ρ| ≥ 0.40) proceed — this stage exists purely
> for computational tractability, since the full pairwise combinatorics of a 1,500+-asset universe (over
> a million candidate pairs) makes running a cointegration test on every pair infeasible at scale.
> **Stage 2, Engle-Granger + Benjamini-Hochberg FDR**: the surviving candidates are tested for
> cointegration via the two-step Engle-Granger procedure, with Benjamini-Hochberg false-discovery-rate
> correction applied per timeframe to control the expected proportion of false positives among the
> (potentially tens of thousands of) simultaneous tests this stage runs. **Stage 3, hedge-ratio
> estimation**: for each EG-significant pair, a hedge ratio is estimated three ways — ordinary least
> squares (OLS), total least squares (TLS, symmetric-error-robust), and a Kalman filter (time-varying) —
> reported independently rather than collapsed to one method by default (§7's `HEDGE_METHOD` config).
> **Stage 4, OU spread fit**: the hedge-ratio-implied spread is fit to an Ornstein-Uhlenbeck
> mean-reversion model, yielding half-life and mean-reversion-speed estimates used both for downstream
> filtering and for backtest position-sizing/exit logic. **Stage 5, eigenportfolio decomposition**:
> systematic (market-wide) factors are removed via Marchenko-Pastur random-matrix-theory eigenvalue
> thresholding, and each surviving pair is tagged Gold (idiosyncratic, factor-independent relationship)
> or Silver (partially factor-driven) tier based on how much of its co-movement survives factor removal.
> **Stage 6, `coint_fraction_rolling` stability filter**: a cheap, scalable rolling-window recency
> diagnostic (§4.3) — the fraction of rolling 252-bar windows in which the pair independently clears
> EG significance — screens out pairs whose full-sample significance rests on a relationship that no
> longer holds recently, with a secondary-evidence override (Zivot-Andrews/CUSUM structural-break
> corroboration) for pairs with a low rolling fraction but no detected structural break, gated by a
> minimum-training-history requirement (`_MIN_BARS_FOR_SECONDARY_EVIDENCE`, added this session — BUG-D68)
> since the override's break-detection tests need real sample size to have power. **Stage 7, cross-asset
> structural exclusion**: pairs whose apparent relationship is structural rather than economic
> (forex triangular-arbitrage relationships, dual-share-class pairs of the same company, index-tracking
> ETF pairs) are excluded even if statistically significant, since these relationships are mechanical,
> not tradeable mean-reversion.

**Source**: `analysis.py` (`UniverseFilter`, `CointScanner`, hedge-ratio/OU-fit/eigenportfolio/
`coint_fraction_rolling`/`CrossAssetTagger` classes, all read and verified directly multiple times this
session), tonight's `analysis_1h_resolve_pairset_err.log` filter-funnel output (confirms the exact
stage sequence and naming: `pearson_prefilter_pairs` → `eg_bh_fdr_pairs` → `price_degeneracy_pairs` →
`structural_exclusion_pairs` → `coint_frac_threshold_pairs`).

**Status**: drafted, not applied. Pure methodology description, doesn't depend on the pair-count
reconciliation — safe to merge independently of that decision. Low risk.

---
