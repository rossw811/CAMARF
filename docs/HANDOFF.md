# CAMARF Handoff — Reconstructed from an Interrupted Session, 2026-07-27/28

---

**2026-08-08 update — "Verify polar-opposite angle invariant and correlation matrix scan",
reconstructed via the Chrome extension from the live browser session
`claude.ai/code/session_01EhHH5o2Y7WjLrJdzTLph4s` — full pass, start to finish.** This is a long
session (opens 2026-08-05, closes on a usage limit with the timestamp suggesting 2026-08-08) that was
still open, mid-response, when it ran out of usage. **I read the entire transcript this time**
(an earlier draft of this entry was based on a partial/sampled scroll-through and undersold both the
session's actual starting point and several major developments in the middle — this version replaces
it). Where possible I cross-checked claims against actual repo state (`git status`, file diffs) rather
than trusting the transcript's own narration, per this file's established practice.

### How the session actually started — not a continuation, a new request

The session opened with: *"use claude chrome extension to create a handoff document for
https://claude.ai/code/session_01Ea11b3ypmS4ZuvX7ytu68u"* — i.e., this session's first job was writing
the **2026-08-03 block already in this file** (the one just below this entry, "Session 30 handoff").
That work is already captured there and isn't repeated here.

After that, Ross said: *"Great, so carry on with what the old session could not finish and or had
planned. Instead of the 1 am runner, just run it now."* Claude built `run_session30.ps1` (a sequential,
lower-worker-count re-run of the full pipeline + all research scripts, deliberately throttled to 6
workers given ~3.5GB free RAM and unrelated jobs already competing for CPU/RAM on the machine). While
fixing a PowerShell parse error (an em dash breaking PS 5.1's UTF-8 read), Ross asked for a full restate
of the plan and then introduced the session's real starting idea — the thing everything else grew out
of:

> "i want to test for inverse variance/covariance/correlation/cointegration. by some metric i want to
> flatten an asset either to a table or a matrix between -1 and 1 to find whenever one's asset is 1 the
> others is -1 kind of like polar opposites? and then maybe have some sort of mean reversion or
> arbitrage based on this equilibrium"

`run_session30.ps1` was launched detached, and the session hit its **first** usage limit right after.
Everything below happened across multiple resume-after-limit cycles.

### Confirmed against repo state — none of this session's new code is committed

`git status` shows the following as untracked (never committed): `research/cross_timeframe_cointegration.py`,
`research/cross_tf_break_divergence.py`, `research/structural_break_onset_detection.py`,
`research/trig_convergence.py`, `research/inverse_polarity.py`, `research/pit_pair_discovery.py`,
`research/vix_crisis_hl_robustness_check.py`, `research/sensitivity_research.py`, matching
`debug/_verify_*.py` for each, and three PowerShell runners (`run_overnight_research.ps1`,
`run_episodic_scan_overnight.ps1`, `run_session30.ps1`). `ml.py` is modified but uncommitted.
`Development.md`, `docs/FINDINGS.md`, `PAPER.md`, and `CLAUDE.md` all show as modified but uncommitted.
**Nothing from this entire span of work has been committed to git** — it's all sitting in the working
tree.

### The polar-opposite idea, in full — this is the actual throughline of the session

Before building anything, Claude checked what already exists: candidate-pair screening already keeps
`abs(rho) >= threshold` (so strongly negative correlations already surface, aren't excluded), and
`backtest.py --neg-hedge` already handles pairs whose EG regression produces a negative hedge ratio.
Three scoping questions were asked and answered by Ross: what should the bounded [-1,1] per-asset score
be built from → **"lets try all 3 for comparison"**; should the anti-correlation search run on raw
returns, bounded scores, or both → **"Both"**; new module or extend existing → **"New research/*.py
module"**.

- **`research/inverse_polarity.py` (new, `docs/FINDINGS.md` §18).** Three bounded polarity metrics
  (`zscore_tanh`, `percentile_rank`, `eg_spread_zscore`, all causal), a two-stage screen (raw-return
  anti-correlation → an actual cointegration test on the negative-hedge spread, specifically to guard
  against "two anti-correlated assets that just drift apart forever with no real equilibrium").
  Synthetic verification caught two real issues before real data: the 8th check initially "passed" for
  the wrong reason (opposite-drift correlation washes out under Pearson's demeaning, so the
  cointegration guard was never even exercised) — rebuilt with the actual textbook spurious-correlation
  construction (correlated innovations, independent random walks) so it genuinely tests rejection.
  **Real result: an honest null** — all 3 currently-confirmed pairs (IQV/Q ρ=0.19, KVUE/KMB ρ=0.43,
  PNC/ZION ρ=0.81) are positively correlated, none anti-correlated — unsurprising since the existing EG
  screen finds same-sector pairs (regional banks, consumer staples) that tend to move together. Finding
  a real polar-opposite candidate needs a full ~1,660-asset correlation-matrix scan, not just the 3
  confirmed pairs — flagged as a materially heavier job requiring explicit go-ahead (later launched in
  the background once resources allowed; final result not confirmed in this reconstruction — check its
  completion status directly).
- **`research/trig_convergence.py`** (new, `docs/FINDINGS.md` §19 — this is where the session's title
  comes from). Prompted by Ross's follow-up: *"what about a concept where we flatten some metric that we
  already test for down to different trig identities and see if we can find convergence or divergence
  there?"* Claude's insight: Pearson correlation is literally `cos(θ)` between demeaned return vectors,
  and `cycle_detection.py`'s existing rolling PLV is already trig by construction — so this isn't adding
  a new capability, it's noticing an existing one differently. Mapped the bounded polarity scores onto
  angles via arccos/arcsin and used the sum-to-product identity
  `cos(θ_A) − cos(θ_B) = −2·sin((θ_A+θ_B)/2)·sin((θ_A−θ_B)/2)` to split joint dynamics into a
  co-movement term and a relative-divergence term. **Verification caught a real design error before it
  touched real data**: Claude initially claimed the angle *difference* was the polar-opposite invariant
  — algebra actually shows it's the angle *sum* that's constant (`θ_A+θ_B = π` for arccos, `=0` for
  arcsin), the difference just tracks cyclical position. Corrected, re-verified 5/5.
  - Ross's follow-up question — *"we could test if their divergence is significance between the arc cos
    and arc sin"* — led to a deeper, genuinely interesting investigation. Algebra predicts
    `arccos(p) = π/2 − arcsin(p)`, which forces `co_movement` to be bit-identical between the two
    mappings. The real-data output showed different numbers anyway (KVUE/KMB: 0.522 vs 0.476) — traced
    to a **real numerical bug**: the rolling z-score's std denominator, right in the exact regime this
    module is built to detect (`co_movement` pinned near-constant, i.e. a genuine polar-opposite pair),
    sits at or below float64 noise, so ~5e-16 rounding differences between mappings tipped the computed
    std to opposite sides of zero, producing different NaN patterns per mapping (12,343 vs 13,536 finite
    bars from the *same* input series). **Fixed with a documented 1e-6 floor**, added a 6th synthetic
    check, re-verified 6/6, re-ran on real data — every row now matches exactly between mappings.
    Correct final answer to Ross's question: **there is no real divergence to test for significance** —
    arcsin's output is a fully deterministic function of arccos's for this decomposition; testing it
    would measure floating-point noise, not an economic signal. Asking anyway was worth it — it surfaced
    the real bug.

### Structural-break / episodic-confirmation thread — the session's other major arc

Separately, Ross asked directly: *"we should make a test and i want to discuss. for what period of time
and to what degree should a relationship be cointegrated to consider arbitrage and exploit
inefficiencies? also i think it's more valuable to use assets for trading that have been coupled and
cointegrated rather than having been cointegrated its entire life. thoughts? we also need to wire all
the scripts for PIT, as if the strategy/analysis was actually run back then."* This is the single most
consequential message in the session — it's the direct origin of everything below.

- Claude found the episodic scan's actual design gap: a blind 10-year rolling window, stepped annually,
  can't distinguish "always cointegrated" from "recently coupled" — a pair that coupled 6 months ago is
  invisible inside 9.5 years of pre-coupling noise.
- **`research/structural_break_onset_detection.py`** built (256 lines + 121-line verify script), reusing
  `StrategyDecayDetector.zivot_andrews`'s Quandt-Andrews/Chow-test break-point detection rather than
  reimplementing it, as a universe-wide precomputation module reporting full break history (not just the
  first break). **Real result, with an honest caveat**: `PNC/ZION@4h` shows a clean, economically
  sensible pattern — one onset (2024-10-21) → one decoupling (2025-11-17), a 13-month coupled regime.
  But `KVUE/KMB@3m` shows 9 "breaks" in a couple months — **not genuine economic
  coupling/decoupling, an artifact of `min_segment_bars=200` being a bar count, not calendar time**: 200
  bars at 3m granularity is only a few days, so at fine intraday resolution the module is picking up
  short-term noise, not real regime change. **This is the specific "200 bars" hardcoded value Ross's
  final message (below) is referring to** — it isn't a vague ask, it names an exact, already-diagnosed
  parameter in an already-built module.
- Ross's next question — *"i think we also should test: is there an opportunity to arbitrage when on one
  tf there's a break but a relationship still exists on the other tf? what about cross asset cross
  timeframe?"* — led to **`research/cross_timeframe_cointegration.py`** (three methods, causal MIDAS-style
  aggregation, full-universe scan mode) and **`research/cross_tf_break_divergence.py`**. Verification
  caught a real design flaw in cross-timeframe Method C: it used ADF-on-residual against a forward
  cumulative return, which is close to stationary by construction regardless of any real relationship —
  a tautological pass, not a real cointegration test. Redesigned to actually discriminate. **Real result:
  `PNC/ZION` shows strong, consistent cross-timeframe cointegration in both directions** (Method A
  p≈1e-9/1e-10, Method B p≈5e-5/0.015) — a nice existence proof, but n=1 pair from the standard confirmed
  set. `cross_tf_break_divergence.py` found 159 events on the later PIT-safe run but with two open
  caveats: a possible pure statistical-power artifact (1h has far more bars/windows than 1D over the same
  span, so it has more chances to find *a* break independent of whether short-horizon relationships are
  actually less stable — not yet disentangled), and every event's "intact" side had broken at *some*
  point in its own history, just not concurrently with the flagged 1h break (the weaker-but-qualifying
  case per the module's own docstring, not a bug, but worth stating precisely).
- **Task #5 — PIT-safe wiring audit — completed.** All 12 research scripts that source confirmed pairs
  are now wired for `--pit-safe`: the 9 wired earlier, plus `stress_test_replication.py`,
  `data_contamination_scan.py`, and `coint_frac_window_grid.py` (three older scripts that read
  `confirmed_pairs_manifest.json` directly instead of calling `ml._discover_confirmed_pairs()`).
  `pit_pair_discovery.py` itself and `ml_lookahead_selftest.py` are the only deliberate exclusions
  (held for task #8). **This directly resolves the top-priority item from this file's own 2026-08-04
  block below** ("audit every research script for its actual pair source... rewire to the adapter").
  A real smoke-test finding along the way: `coint_frac_window_grid.py --pit-safe --tf 1D` at ~700 pairs
  drove free RAM to 1.4GB within 2 minutes and was proactively killed before it could starve the
  concurrently-running episodic scan — confirmed via `taskkill /PID <id> /T /F` that the episodic scan's
  own process was untouched and kept advancing normally afterward.
- **The episodic scan itself completed — ~26.6 hours, producing real, large numbers.** Final: **Tier 1:
  103 confirmed, Tier 2: 189 confirmed, Tier 3: 620 confirmed** (of 1,089,763 candidates tested),
  collapsing to **647 unique PIT-confirmed pairs** after dedup. Right after completion, a real bug was
  caught and fixed: `pit_pair_discovery.py` was pointing at the scan's in-progress checkpoint files,
  which get deleted on successful completion — it would have silently returned 0 pairs to every
  downstream script had this not been caught (re-verified 4/4 after the fix).
- **Task #9 — the three PIT-safe broad-scale re-runs — all completed successfully**, now against the
  full 647-pair (later described as 338/718-pair subsets depending on data-availability per script)
  episodic set:
  - `coint_frac_window_grid.py --pit-safe`: production's existing `window=252/threshold=0.70`
    cointegration default is **validated, not beaten** by a 338-pair grid search (ties the grid's raw
    winner at 88.76% accuracy); an overfitting guard (select on half A, score on held-out half B) found
    no gap (in fact held-out accuracy was slightly *better*, -0.024 gap — the opposite direction
    overfitting would produce).
  - `stress_test_replication.py --pit-safe`: at 1996/2028 testable pair-crisis combinations, a genuinely
    strong two-part result — **extreme dislocation rate is 65% crisis vs. 14% calm** (a real 51-point
    gap, strong evidence of crisis-period fragility) but **cointegration-holds rate is nearly identical,
    8% vs. 9%** — the formal EG test surviving a crisis is *not* meaningfully more likely to fail than in
    a calm control window of the same length. Honest, non-overclaimed, two-sided finding: crises look
    dangerous by one measure and not by another.
  - `cross_tf_break_divergence.py --pit-safe`: 159 events (see above), the two open caveats noted.
- **A structural, project-wide design decision was proposed by Claude and confirmed by Ross**: promote
  the **PIT-safe episodic screen to the primary live-trading pair-discovery gate**, demoting the
  existing full-history screen from sole gate to a secondary corroborating signal. Ross's exact answer:
  *"Yes, proceed — but only once the episodic scan is complete and the design is verified."* The episodic
  scan *did* subsequently complete with real numbers, but **there is no evidence in this reconstruction
  that the actual production cutover in `backtest.py`/`report.py` was implemented** — `git status` shows
  `backtest.py` unmodified. This is very likely still an open item, and is the most probable reading of
  Ross's final unanswered message (below) about "the 3 we now found as our only asset source" — the
  episodic scan found 647 statistically-confirmed pairs, but if the production cutover never happened,
  live trading is likely still gated on the original 3.
- **`ml.py` training-data redesign — direction agreed, only partly built.** Rather than a hard PIT-safe
  gate on training data, the direction is to feed the model **episodic cointegration significance as a
  feature** (`episodic_fraction_fdr`, `min_adjusted_pvalue`, break-onset classification), letting the
  model learn how much weight to give strong vs. weak statistical evidence instead of a pre-decided
  binary cutoff. The real scope turned out to be bigger than assumed: `ml.py`'s existing
  `_build_examples_for_pair` already accepts a pre-computed series, but the actual point-in-time series
  construction (hedge ratio, `coint_fraction_rolling`, etc.) lives entangled inside
  `analysis.py::_regime_worker`, a large multiprocessing function *also* fitting K-means/GMM/HMM regime
  models in the same pass — cleanly separating "build me a point-in-time series for any candidate pair"
  from the unrelated regime-fitting logic is real refactoring, not a quick reuse, and wasn't rushed.
  **Done tonight, low-risk**: `ml.py` now has the same `--pit-safe` flag as the other research arms
  (mechanical wiring only). The substantive redesign itself is scoped as a careful 5-step plan in
  `Development.md` under task #8, not yet built.
- Also surfaced along the way: `pit_wfa.py` currently runs with `MLConditioner(enabled=False)` —
  confirming "backtest PIT with ML" doesn't exist yet; this is a real, named gap, not a quick flag flip.

### PAPER.md restructuring discussion — a real, agreed pivot in direction

Ross asked to make sure `Development.md` and `PAPER.md` were fully current (*"it hasn't updated in a few
sessions but i want to make sure it's fully up to date, along with paper"*) — Claude found `PAPER.md`'s
content was 3 weeks / 4 full sessions stale and made substantive updates: §3 (Data and Universe)
rewritten with the current WRDS-primary snapshot, §5 got an honest second reconciliation-gap disclosure
(26→3 pairs, a methodology change not a data-quality regression), §7.3.1 updated with `pit_wfa`'s actual
4-fold results (see below), and a new §7.17 documenting the full Session 30 writeup.

Separately, once the episodic scan's scale became clear (3 standard-screen pairs vs. 189-620
episodically-confirmed), Claude proposed and Ross agreed to **repoint the paper's central thesis**:
instead of "N confirmed pairs, here's their backtest Sharpe" (a shrinking, fragile-looking number after
WRDS), the new central claim is **"static, full-history cointegration screening systematically
undercounts real arbitrage relationships — a point-in-time-safe episodic confirmation methodology
recovers most of what static screening misses, without lookahead bias."** Ross: *"i think it deserves
its own shorter paper but i like the novel angle."* The original 26/3-pair backtest work becomes its own
separate, more contained paper. Claude ranked candidate contributions for the new paper (strongest:
rigorous BH-FDR multiple-testing discipline at 1M+-hypothesis scale as a literature critique, and the
concrete before/after PIT-safety magnitude demonstration; weaker/needs more validation: cross-TF
cointegration, structural-break-as-economic-story; explicitly parked as scope creep: cross-TF break
divergence and regime-conditional episodic confirmation as independent pillars right now). Ross:
*"hold out - i love your perception on the ideas"* — validation-work sketch deferred until real backtest
numbers exist (task #8).

**Separately, Ross floated turning CAMARF into a general-purpose "platform for everyone to validate their
scripts" — Claude pushed back, directly, and Ross agreed to park it.** Reasoning given: it conflicts with
CLAUDE.md's own "no abstractions for single-use code" / "simplicity first" rules, it's real scope creep
against the actual MFE-application goal (the council-mfe-portfolio review already flagged that focus
reads better to admissions committees than breadth), and the NQ/ES futures system is already the
project's own precedent for "keep it separate, share conventions only." Noted as parked in
`Development.md`, not built, revisit later if there's a reason beyond MFE apps.

### Other real findings from this session

- **The long-standing WRDS-vs-yfinance comparison blocker — resolved.** This file's own 2026-08-03 block
  below flags this as "blocking across two consecutive handoffs." `run_session30.ps1` finally ran
  `analysis.py` to completion at full scale: **1,660-asset universe, BUG-D105's fix confirmed real** —
  3 confirmed pairs (`KVUE/KMB`@3m known since Session 21, `PNC/ZION`@4h new, `IQV/Q`@1D new, "gold
  tier").
- **`pit_wfa.py` — all 4 folds completed for the first time** (previously stuck at 2 of 4 across two
  handoffs). `rolling/fold2` found a new result: 1 pair, 5 trades, **Sharpe +0.2547** — doesn't overturn
  the already-disclosed §7.3.1 negative finding (3 of 4 folds are still zero/negative), but it's real and
  now in the record.
- **SVM meta-labeler re-ran for real** — still insufficient data (19 examples, need 30/class), but now
  for the honest underlying reason (thin pair history) rather than the prior session's collision bug.
- **Lévy jump-diffusion / GapFlag finding strengthened at real scale.** The original single-pair
  (KVUE/KMB) "0% overlap between statistically-detected jumps and GapFlag" finding was re-run
  `--pit-safe` across the full episodic universe: **206 symbols / 640 symbol-TF rows, 640/640 show
  exactly 0% overlap** — upgrades this from an interesting single-pair quirk to a systematic,
  production-scale property of the existing gap-handling machinery.
- **`fdr_method_comparison_summary`** (from the overnight pipeline's ~141 stages, sampled directly rather
  than trusted from narration): comparing correction methods across 34,593 tests, standard BH,
  Bonferroni, and two-stage BH all agree on the same 3 survivors (matching the confirmed set) — but
  **Benjamini-Yekutieli (the more conservative correction, accounts for test dependency) finds only 1
  survivor.** A real, honest, open robustness question about whether the current 3-pair confirmed set
  would hold up under the most conservative reasonable correction — worth writing up explicitly, not
  currently in `docs/FINDINGS.md`.
- **`eg_permutation_check`**: both `KVUE/KMB` and `PNC/ZION` pass the non-parametric permutation test too
  (not just the parametric EG p-value) — real p-values ~3e-6/2e-6, permutation p-values ~0.025/0.024,
  both under 0.05. `IQV/Q` doesn't appear in this table at all — worth checking why.
- **Sensitivity-research harness** (`research/sensitivity_research.py`, new) — Ross's request: *"i think
  it'd be valuable running a param sensitivity for all the research scripts."* Claude surveyed all 120
  research scripts and found only 46 have genuinely tunable CLI parameters (74 are fixed-logic
  diagnostics where sensitivity analysis doesn't apply) — scoped as real multi-session work, starting
  with the 7 scripts already fully understood this session (batch 1), then extended to 6 more core
  cointegration/lead-lag scripts (batch 2, `BATCH2_REGISTRY` merged into the same registry). Real
  findings, already in `docs/FINDINGS.md`: `cycle_detection` loses a pair from its sample as window grows
  past 60 (the minimum-bars requirement scales with window, silently shrinking `n`); `levy_jump_diffusion`
  is robust across the entire alpha grid; `rough_volatility` shows genuinely window-dependent
  disagreement between Hurst estimators (not just noise); `options_greeks_features`' effect size decays
  substantially with window length, consistent with the already-disclosed price-level-confound
  interpretation; the full-universe threshold sweep found **zero genuinely cointegrated pairs even at a
  loosened -0.30 threshold** — a robust null, not a default-parameter artifact; `eg_permutation_check`
  shows a mild real drift (null rate 0.045→0.062 as permutations increase); a real pyarrow float/string
  type bug was found and fixed (the harness's `value` column mixed types across arms); `threshold_cointegration`
  and `regime_cluster_robustness_check` both came back perfectly stable nulls across their full parameter
  ranges.
- **Overnight full-pipeline monitoring found and fixed two real infrastructure bugs, beyond what's
  already documented in this file's 2026-08-04 block.** (a) A `reproduce.py` incident spawned an
  unexpected `data.py` child process — a real gap in the runner's scoping (it was supposed to be excluded)
  — fixed by adding a `--verify-only` mode that checks existing outputs without re-running fetches. (b)
  **Root-caused, not just patched**: repeated orphaned-process-tree incidents (a `run_verify_suite.py`
  timeout at 02:02 leaving an `analysis.py` + ~20 workers running unsupervised for 4+ hours, consuming
  2.7GB+; a separate `reproduce.py`-spawned `analysis.py` orphan running unsupervised since 01:17) both
  trace to the same cause: **.NET Framework's `Process.Kill()` doesn't accept a tree-kill argument**, so
  timeout-triggered kills were silently failing to actually kill child process trees. This was properly
  fixed in `run_overnight_research.ps1` this session (not just documented) — the fix was verified by
  relaunching and confirming the runner resumes correctly from its last completed stage with no
  re-orphaning. **Data crypto backfill (`data_crypto.py`) finally completed cleanly for the first time in
  4 attempts** as the pipeline's final stage (15 symbols × 8 intervals, all confirmed done via
  checkpoint).
- **Ross asked about a remembered "bearish periods cointegrate at a higher rate" finding — it doesn't
  exist as stated.** Claude checked `Development.md`, `docs/FINDINGS.md`, and `PAPER.md` directly and
  found no such written finding — the closest related things are Session 13's VIX-crisis/calm *trade
  performance* effect (not cointegration formation rate) and a cited Longin & Solnik (2001) literature
  motivation (not a CAMARF-tested result). More directly, **this session's own `stress_test_replication.py
  --pit-safe` run is in tension with the premise as stated**: cointegration-holds rate was nearly
  identical crisis vs. calm. The underlying idea (does bear-period-specific cointegration strength carry
  incremental predictive information beyond overall strength) is still good and was scoped as a task #8
  feature spec, not built standalone — avoiding another parallel research thread.

### Where the session actually stopped (usage limit hit mid-response)

The final message in the transcript is from Ross, with **no assistant response** — the session hit its
usage limit immediately after:

> "we should change the 200 bars and run an actual test to see what value makes a valid relationship.
> that goes for any and all hardcoded values. i like your tiers. also is we have to discuss using the 3
> we now found as our only asset source because we need to accommodate for the PIT results and not be
> susceptible to any biases. go for it"

Both halves of this are now concretely traceable, not vague:

1. **"The 200 bars"** is `structural_break_onset_detection.py`'s `min_segment_bars=200` parameter,
   already diagnosed *in this same session* as a real bug: it's a bar count, not calendar time, so at 3m
   granularity it produces 9 spurious "breaks" on `KVUE/KMB` in a couple months instead of reflecting
   real regime change. Ross's "i like your tiers" most likely refers to some tiered-window design Claude
   proposed somewhere in this thread — this specific framing wasn't captured verbatim in this
   reconstruction; re-derive it directly from the transcript around the structural-break-detection design
   discussion before building against it. The ask is broader than this one parameter, though: audit
   *every* hardcoded window/threshold constant in the codebase and replace each with a value derived from
   an actual empirical test of what produces a valid relationship.
2. **"The 3 we now found as our only asset source"** almost certainly refers to the fact that, even
   though the episodic scan found 647 statistically PIT-confirmed pairs, the production pair source for
   live trading (`backtest.py`/`report.py`) very likely still reads the original 3-pair standard-screen
   set — the PIT-safe-as-primary-gate cutover was agreed to but not confirmed built (see above). Ross's
   framing ("accommodate for the PIT results and not be susceptible to any biases") reads as: don't keep
   training/trading on the same 3 pairs while treating 647 PIT-confirmed pairs as just a research
   side-finding — resolve this inconsistency directly.

### Immediate next steps for the next session

1. Verify whether the PIT-safe-episodic-as-primary-gate cutover was actually implemented in
   `backtest.py`/`report.py`, or only agreed to in principle — `git status` currently suggests the
   latter (`backtest.py` shows unmodified).
2. Directly answer Ross's two-part final message: audit hardcoded window/threshold constants
   (`min_segment_bars=200` is the concretely-identified starting point) and resolve the 3-pair-vs-647-pair
   asset-source inconsistency.
3. Check whether task #6 (the `cross_timeframe_cointegration.py --full-universe` scan, 1,301 candidates
   after tightening the correlation prefilter to 0.7) or `inverse_polarity.py`'s full-universe scan ever
   completed — both were running/pending as of the last sampled point in this reconstruction.
4. Write up the Benjamini-Yekutieli 1-survivor finding (a real, honest robustness question about the
   3-pair confirmed set) and the `eg_permutation_check` `IQV/Q` omission — both surfaced this session but
   aren't in `docs/FINDINGS.md` yet.
5. Sync `Development.md` and `docs/FINDINGS.md` with everything in this entry that isn't there yet —
   most of this session's work is currently only in the browser transcript and uncommitted working-tree
   files, not in the project's actual written record.
6. Once reviewed, commit this session's new research modules and doc updates — the entire span of work
   described above is currently uncommitted, including a real, agreed paper-thesis pivot that isn't
   reflected in any commit yet.

---
