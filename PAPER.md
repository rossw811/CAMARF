# Working Title

Cointegration Test Miscalibration Across Horizons: A Scalable Stability
Diagnostic for Cross-Asset Statistical Arbitrage Screening

*(Working title — revisit once backtest.py results exist. Candidate
alternates: "The Strictness Paradox: Horizon-Dependent Miscalibration in
Cointegration Screening" / a strategy-forward title if the empirical
results end up carrying the paper more than the methodology does.)*

---

## Status of this document

This is a **living draft**, started 2026-06-23, updated incrementally as
the project progresses — NOT a finished paper. Sections are in one of
three states, marked explicitly so nothing gets mistaken for a final
claim:

- **[DRAFTED]** — written from findings already verified against real
  code/data this session or documented with hard numbers in
  `Development.md`. Still needs prose polish, but the substance is real.
- **[OUTLINED]** — structure and argument decided, content not yet
  written (usually because it depends on a not-yet-built module).
- **[TBD]** — not yet decided; flagged with the open question.

Update this document alongside `Development.md` at the end of every
session that produces a citable finding. `Development.md` remains the
canonical bug-by-bug/session-by-session memory; this file is the
paper-shaped synthesis of the subset of that memory meant for an
external reader.

---

## Framing decision (locked in 2026-06-23, Ross + Claude discussion)

Ross's stated preference: the strategy itself matters to him personally,
but he's open to leading with methodology if the calibration finding is a
genuine, exportable contribution beyond CAMARF's own pairs. Resolution:
**lead with the methodology finding, structure the strategy chapter as
the empirical demonstration of that methodology, not a separate, weaker
pitch.** Concretely: contrast what naive full-sample EG alone would have
certified (this project's own former headline pairs, NTRS/STT and
SHW/UNP) against what survives the corrected, rolling-stability-aware
pipeline. The strategy doesn't disappear under this framing — it becomes
evidence the methodology has teeth. Eventual backtest.py results then
read as confirmation of a validated method, not the sole load-bearing
claim of the paper.

---

## Abstract [DRAFTED — needs prose polish]

Cointegration-based pairs trading conventionally screens candidate pairs
with a full-sample Engle-Granger test, a method that scales to
large-N candidate universes but cannot, by construction, distinguish a
durable economic relationship from one whose statistical significance is
borrowed from a regime that no longer holds. We document this failure
mode directly: across a 1,500+ asset, 14-timeframe universe, full-sample
cointegration screens at long horizons (1D, 1M) reject candidate pairs at
rates orders of magnitude below their expected false-positive rate under
the null — not because no relationships exist, but because the test
itself becomes too strict to be decision-relevant at that horizon. We
show concretely that this project's own original headline confirmed
pairs (NTRS/STT, SHW/UNP) pass a full-sample test with high significance
while failing the identical test restricted to the last five years alone.
We introduce a scalable rolling-stability diagnostic
(`coint_fraction_rolling`) that operationalizes, at the scale required for
large candidate universes, a question formal econometrics already has
tools for at the single-pair scale (Gregory & Hansen, 1996; Hansen, 1992;
Quintos & Phillips, 1993) but that does not scale to ~10⁶ pairwise tests.
Borderline cases are corroborated against the heavier structural-break
apparatus (Zivot-Andrews, CUSUM) via a documented secondary-evidence
override, illustrated on a real case where it overturns the primary
filter's decision. [PLACEHOLDER — one sentence on strategy/backtest
results once backtest.py exists.] We additionally document a generalizable
data-hygiene failure mode (calendar-padding artifacts in rolling-window
statistics on intraday data) likely present, unflagged, in other
published intraday pairs-trading work using fixed-window rolling
z-scores on calendar-padded series.

---

## 1. Introduction [OUTLINED]

- Motivation: stat-arb / pairs trading practice and the bulk of the
  academic literature screens for cointegration with a single full-sample
  test (Vidyamurthy, 2004 — "the most cited work on cointegration-based
  pairs trading," built on an adapted Engle-Granger test).
- The conventional framing of "does cross-asset cointegration predict
  outcomes" is the wrong question to lead with at this stage of the
  project (ml.py/backtest.py results are still too early/small to carry a
  strategy-first paper — see §6). The sharper, already-supported question:
  **at what point does a cointegration test's strictness, calibrated
  implicitly for one horizon, stop being decision-relevant for that
  horizon?**
- Contribution claims (each maps to a methodology section below):
  1. Direct empirical demonstration of horizon-dependent EG test
     miscalibration on a controlled, large-N sweep (§4.2).
  2. A two-tier, scalable stability-screening design — cheap rolling
     diagnostic at scale, formal structural-break corroboration at the
     margin — that makes existing-but-impractical-at-scale econometric
     theory usable on a 10⁶-pair candidate universe (§4.3-4.4).
  3. A generalizable methods note on calendar-padding contamination in
     rolling-window statistics on intraday financial time series (§4.5).
  4. [PLACEHOLDER] A candidate trading strategy validated through (1)-(3),
     once backtest.py exists.

## 2. Literature Review [OUTLINED — citations gathered, prose not written]

Gathered so far, verified via direct source lookup (not from memory
alone) on 2026-06-23:

- **Engle & Granger (1987)**, "Co-integration and Error Correction:
  Representation, Estimation, and Testing," *Econometrica* — the
  foundational two-step cointegration test this entire project's primary
  screen is built on.
- **Vidyamurthy (2004)**, *Pairs Trading: Quantitative Methods and
  Analysis*, Wiley — described as the most-cited work on
  cointegration-based pairs trading; builds the standard
  practitioner/academic framework on an adapted Engle-Granger test and a
  VECM formulation. [Source: ResearchGate listing, confirmed 2026-06-23.]
- **Gregory & Hansen (1996)**, "Residual-Based Tests for Cointegration in
  Models with Regime Shifts," *Journal of Econometrics* — ADF-/Zα-/Zt-type
  tests for cointegration in the presence of a single structural regime
  shift (level shift, regime shift, or regime+trend shift). The formal
  tool for exactly the question `coint_fraction_rolling` answers cheaply
  at scale. [Source: ScienceDirect/Semantic Scholar, confirmed 2026-06-23.]
- **Hansen (1992)**, "Tests for Parameter Instability in Regressions with
  I(1) Processes," *Journal of Business & Economic Statistics* 10(3),
  321-335, and **Quintos & Phillips (1993)**, "Parameter Constancy in
  Cointegrating Regressions," *Empirical Economics* 18, 675-706 — test
  statistics for the stability of cointegrating-vector parameters over
  time; the single-pair-scale formal analogue to this project's
  rolling-fraction diagnostic. [Full bibliographic detail confirmed via
  direct source lookup 2026-06-23 — see References §7 for links.]
- **Benjamini & Hochberg (1995)** — FDR control for multiple testing;
  already the project's primary multiple-testing correction
  (`CointScanner`, per-TF).
- **Lopez de Prado (2018)**, *Advances in Financial Machine Learning* —
  meta-labeling (this project's ml.py IS a meta-labeler on the
  cointegration z-score signal, framed this way already in
  `Development.md`), CPCV, PBO, triple-barrier labeling. Already the
  project's primary ML-methodology reference; see `Development.md`
  "Reference Authors" section for full detail.
- **Gatev, Goetzmann & Rouwenhorst (2006)** — *Review of Financial
  Studies* 19(3), 797-827. Average annualized excess returns up to 11%
  for self-financing pairs portfolios, 1962-2002 daily US equity data.
  **Important distinction for this paper's own positioning**: this is the
  *distance* method (minimum sum-of-squared-distance on normalized price
  paths), not cointegration — it's the standard benchmark citation for
  pairs trading generally, but it is not directly comparable to a
  cointegration-screen result and should not be cited as if it were.
- **Avellaneda & Lee (2010)** — *Quantitative Finance* 10(7), 761-782.
  PCA-based residual mean-reversion signals: average annual Sharpe 1.44
  over 1997-2007, but only 0.9 over 2003-2007 specifically — the
  strategy's own performance degraded by roughly a third within the
  sample period. ETF-residual signals: Sharpe 1.1 over 1997-2007 with a
  similar post-2002 degradation. **Worth drawing out explicitly in this
  paper's own narrative**: even a well-cited, methodologically careful
  stat-arb result shows the same kind of within-sample regime sensitivity
  this paper's central finding is about — Avellaneda-Lee's own numbers
  are a small piece of corroborating evidence that "a method calibrated
  on one period decays out-of-period" is a general property of this
  research area, not unique to CAMARF's full-sample EG critique.
- **Krauss (2017)** — *Journal of Economic Surveys* 31(2), 513-545.
  Survey categorizing the field into five approaches: distance,
  cointegration, time-series (optimal mean-reversion trading rules),
  stochastic control, and other (incl. ML-based) methods. Useful as the
  paper's literature-review organizing citation — CAMARF sits in the
  cointegration category, with this paper's contribution being a
  scalability/calibration correction *within* that category.

## 3. Data and Universe [DRAFTED, needs final-state numbers]

Universe as of the most recent full run (2026-06-23): 1,521 assets
(S&P Composite 1500 + crypto/forex/commodities/futures/ETFs), 19,356
symbol-timeframe keys, 14 timeframes from 1-minute to 6-month.
yfinance-primary fetch (`data.py`), IBKR supplemental deep history for
confirmed pairs only (`data_ibkr.py`, episodic-cointegration re-test).
[Update this section's numbers at final submission — universe size grows
session to session as intraday history accumulates.]

## 4. Methodology [mixed — see per-subsection status]

### 4.1 Screening pipeline overview [OUTLINED]
Correlation pre-filter (Pearson/Spearman/rolling-average, confidence-tier
tagged) → Engle-Granger + Benjamini-Hochberg FDR (per timeframe) →
hedge-ratio estimation (OLS/TLS/Kalman) → OU spread fit → eigenportfolio
decomposition (Marchenko-Pastur factor removal, Gold/Silver confidence
tier) → `coint_fraction_rolling` stability filter with secondary-evidence
override → cross-asset structural exclusion (forex triangles, share
classes).

### 4.2 The Strictness Paradox: horizon-dependent test miscalibration [DRAFTED — hard numbers from Development.md, already verified]

Raw (pre-FDR) significance rates by timeframe, full pipeline run:

| TF | tested | raw p<0.05 | raw rate | vs. ~5% expected under H₀ |
|----|--------|-----------|----------|---------------------------|
| 15m | 14,412 | 585 | 4.06% | close to chance — consistent with real signal |
| 1h | 65,721 | 2,335 | 3.55% | close to chance — consistent with real signal |
| 1D | 122,082 | 2 | 0.0016% | ~3,000x *below* chance |
| 1M | 34,263 | 9 | 0.026% | ~190x below chance |

A rate far *below* the chance rate under the null isn't an absence of
signal — it's direct evidence the test itself is unusually strict at
that horizon. Direct demonstration, full-sample EG p-value vs. the
identical test restricted to the last 5 years alone:

| Pair | Full-sample EG p | Last-5y EG p | Full-sample n (days) |
|------|------------------|--------------|----------------------|
| XOM/CVX | 0.436 | 0.408 | 14,546 (since 1968) |
| JPM/BAC | 0.911 | 0.753 | 11,571 (since 1980) |
| KO/PEP | 0.114 | 0.916 | 13,423 (since 1973) |
| **NTRS/STT** | **0.000** | 0.345 | 10,939 (since 1983) |
| **SHW/UNP** | **0.004** | 0.265 | 11,548 (since 1980) |

NTRS/STT and SHW/UNP — this project's own original headline confirmed
pairs — pass full-sample EG with overwhelming significance while failing
the identical test on just the last five years. The full-sample screen at
1D is effectively testing whether two price levels stayed cointegrated
across 40-60+ years of M&A, business-model change, and sector rotation —
a relationship can fail that bar today while still showing up as
"confirmed" if the test only looks at the full sample. **Why this is a
structural limitation, not just an explanation:** `coint_fraction_rolling`
is a secondary filter applied only to pairs that already pass the primary
full-sample screen. At long horizons the primary screen is so strict that
almost nothing reaches the secondary filter at all — the two defenses
operate at the wrong stage for this specific failure mode.

### 4.3 `coint_fraction_rolling`: a scalable stability diagnostic [DRAFTED]

Defined as the fraction of rolling 252-bar windows in which the
Engle-Granger p-value clears 0.05 — a cheap, per-pair-scalar proxy for
the same underlying question Gregory-Hansen and Quintos-Phillips answer
formally but at real per-pair computational cost. `Config.UNIVERSE.MIN_COINT_FRAC
= 0.70` (restored from an undocumented 0.40 drift found during this
session's bug hunt — see `Development.md` Session 10).

### 4.4 Secondary-evidence override: corroborating borderline cases against the formal apparatus [DRAFTED — worked example verified 2026-06-23]

A pair below the 0.70 threshold is kept anyway if `half_life_trend_slope
≤ 0` (the spread's mean-reversion speed is improving, not decaying) AND
neither Zivot-Andrews nor CUSUM detects a structural break in the spread
— i.e., corroboration against the two single-pair structural-break tests
already in the pipeline, not a softer threshold. Real worked example,
verified directly against the persisted post-fix data this session:

| Pair | coint_fraction_rolling | half_life_trend_slope | Zivot-Andrews break | CUSUM excursion | Decision |
|------|------------------------|------------------------|----------------------|------------------|----------|
| D/NEE | 0.41 | (decaying) | detected | detected | **Excluded** — no override |
| SPY/VOO (1h) | 0.45 | (decaying) | detected | detected | **Excluded** — no override |
| FANG/OXY (1m) | 0.27 | -0.617 (improving) | none | none | **Kept** — override applies |

Earlier framing of this worked example (overnight, pre-fix) used
CRWD/DDOG as the surviving case. That no longer holds: a separate bug
fix this session (BUG-D45 extended to `HurstEstimator`/
`StrategyDecayDetector` — both were computing structural-break inputs on
calendar-padding-contaminated data) changed the actual structural-break
result for CRWD/DDOG. **FANG/OXY is the current, verified example** — see
`Development.md` Session 10 for the full account, including the explicit
caution about citing the right one.

### 4.5 A general hazard for intraday statistical arbitrage research: calendar-padding artifacts in rolling-window statistics [DRAFTED]

**The mechanism.** Aligning intraday bars onto a continuous trading-time
grid requires deciding what to do with non-trading minutes (overnight,
weekend). A common, seemingly innocuous choice — reindex onto a
continuous calendar and forward-fill the gaps so every asset shares a
common index — silently contaminates any rolling-window statistic
computed downstream. Forward-filling means a long run of *identical*
values sits in the series wherever the market was closed. The instant a
fixed-width rolling window (e.g. 252 bars) straddles one of these runs,
the window contains `(n-1)` identical padded values and exactly 1 real
value once the market reopens.

**The exact, derivable artifact.** For a rolling z-score
`(x - mean) / std` computed over a window of `n` points where `(n-1)` of
them are identical and 1 differs, the result at that point is *exactly*
`(n-1)/√n`, independent of the actual price move that produced the
differing value. This is pure arithmetic, not a statistical
approximation — substitute `n=252` and the result is `251/√252 =
15.8115...`. We observed this exact value, matched to 10 significant
digits, in real entry-signal output before diagnosis: 4 of an early
32-example labeled training set (12.5%) had `|z_entry| > 10`, all firing
at exactly market open, all on the calendar-padding day boundary.

**Why this generalizes beyond CAMARF.** Forward-filling non-trading
periods onto a continuous calendar is a standard, often default,
convenience in time-series tooling (e.g. pandas `reindex().ffill()` on a
calendar-frequency index) — not a CAMARF-specific design choice. Any
intraday pairs-trading or stat-arb research using fixed-window rolling
z-scores on a calendar-padded series inherits this exact failure mode,
recurring at every session boundary, for every asset, by construction.
The artifact is large enough (15.8 standard deviations) and
mathematically clean enough (an exact closed form, not a fat-tailed-but-
plausible outlier) that it is a strong candidate explanation for
anomalously fat-tailed entry-signal distributions reported elsewhere in
intraday mean-reversion research without being traced to this specific
cause — though that claim about *other* published work is speculative
and not something this project can verify directly; framed here as a
testable hypothesis for a reader to check against their own pipeline,
not an accusation against any specific prior study.

**The fix, briefly** (full derivation and code-level account in
`Development.md`'s BUG-D45 entry): compute rolling statistics on a
compacted, real-bars-only sub-series (excluding padded positions via a
gap flag), then scatter the result back onto the full-length index with
the padded positions left as missing — never feeding a padded value into
either the entry-signal computation or any downstream training label.

### 4.6 A second negative result: a volatility-decoupled rolling window was tried and reverted [DRAFTED]

Worth one paragraph as a second, smaller negative result — most reported
pairs-trading work shows only the version that worked; the version that
didn't, and why, is informative in its own right. The natural-seeming
refinement to §4.5's fix: use a *shorter* rolling window for the
standard deviation (so the entry z-score responds quickly to current
volatility) while keeping a longer window for the mean (so the
equilibrium estimate stays stable). Measured directly on one real pair
(CRWD/DDOG): mean=-1.50, std=7.13, 12.3% of bars with `|z|>10` — *worse*
than the original flat-window version, not better. Mechanism: decoupling
the two windows breaks the z-score's own mean=0/std=1-over-its-window
guarantee. If the spread drifts at all within the longer mean window, a
fast-shrinking std denominator from the shorter window amplifies that
drift into a systematic bias rather than tracking genuine current
volatility. Reverted to a single shared, half-life-adaptive window for
both mean and std (the version described in §4.5); re-verified across
three pairs spanning very different history depths: CRWD/DDOG (1m,
~4.7 days of real history) mean=-0.28, std=1.59, 0.16% of bars `|z|>10`;
ORCL/SPY (3m) mean=0.10, std=1.47, 0% `|z|>10`; SPY/VOO (1h, ~3 years of
history) mean=0.11, std=1.54, 0.16% `|z|>10`. The two originally-flagged
CRWD/DDOG entries dropped from the mathematically-forced ±15.8115 to
-7.65 and +12.99 — still large, but now genuine, consistent with real
overnight gap risk on a pair with under a week of trading history, not a
guaranteed artifact of the computation itself.

### 4.7 Correlation is a pre-filter, not a confirmatory test — a worked example [DRAFTED — numbers verified 2026-06-24]

§4.1 already states that the Pearson correlation step is a cheap
pre-filter, not a confirmatory criterion — Engle-Granger cointegration on
price levels is what actually decides a pair. This section gives the
claim a concrete, real worked example rather than leaving it asserted.

**The mechanism.** Correlation measures whether *returns* move together
— two stocks sharing sector or market beta will rally and sell off
together on the same macro news. Cointegration measures something
categorically different: whether *price levels* stay anchored to a
stable long-run relationship that reverts when it diverges. A pair can
satisfy the first while completely lacking the second. Trading such a
pair as a spread-reversion strategy has no statistical basis — the
position is an unhedged directional bet on relative re-rating, dressed
up as market-neutral, because nothing requires the price levels to ever
come back together.

**The worked example.** A universe-wide scan for lagged correlation
structure (testing whether some pairs are missed by the lag-0-only
correlation pre-filter because the true relationship is time-shifted)
surfaced nine real, named pairs clustered tightly by industry: five
regional banks (CATY, FIBK, SBCF, TCBI, UMBF) each correlating most
strongly with United Community Banks (UCB); Blackstone and Ares
Management each correlating with StepStone Group; two semiconductor
pairs (DIOD/VSH, AEIS/MKSI). Correlations of 0.49–0.63 — real,
substantial, and (confirmed via sector/industry metadata, not assumed)
entirely explained by shared-industry beta. **Engle-Granger p-values for
all nine: 0.06–0.89 — nowhere near significant.** A correlation-only
screen would have waved every one of these through as "related." The
actual confirmatory test correctly says no, for the ordinary and
expected reason: correlated returns, no cointegrated price levels.

**Honest methodological note.** These nine pairs were originally
mis-measured by a data-alignment bug (overnight/weekend-spanning returns
incorrectly included in a correlation calculation, inflating the
apparent relationship — full account in Development.md) and the
*lagged* relationship they were first reported to show was a complete
artifact of that bug. The corrected computation is what produced the
*correlated-but-not-cointegrated* finding used here — itself a small
illustration of this project's standing discipline (§9): a result was
checked against an independently-built computation, found to disagree,
and traced to a specific, fixable cause before being trusted.

This is a different failure mode than the Strictness Paradox (§4.2):
that section is about cointegration testing being too STRICT at long
horizons (false negatives — real relationships rejected). This section
is about correlation alone being too LOOSE (false positives — unrelated-
at-the-cointegration-level pairs that look related). Both point to the
same conclusion: the multi-stage pipeline's calibration matters at every
stage, not just one, and no single metric — correlation or a single
full-sample cointegration test — is sufficient on its own.

## 5. Empirical Findings [PLACEHOLDER — fill in as confirmed-pair set stabilizes]

Current state (2026-06-23, will change as intraday history accumulates):
16 confirmed pairs survive the full pipeline (post coint_frac filtering)
across 1m (7), 3m (5), 15m (3), 4h (1). 2 of 16 achieve Gold confidence
tier (APAM/INVX, AZTA/INVX — survive both the raw EG screen and the
eigenportfolio-residual re-test, i.e. not just shared-factor-driven). Do
not treat this list as final — it is expected to keep changing session to
session as `data.py`'s intraday accumulation (BUG-D46 fix, this session)
takes effect. Lock this section only once the universe's intraday history
depth has stabilized enough that the confirmed-pair set isn't visibly
churning between consecutive runs.

**[FLAG — do not cite either Gold-tier pair below without resolving
this first]** Both current Gold-tier pairs (APAM/INVX, AZTA/INVX) are
built from the same 4-symbol cluster (APAM/AZTA/INVX/NBHC) flagged in
BUG-D49 (`Development.md`, found 2026-06-23 while building the graph-
clustering comparison): their 1-minute price data shows only 2-7
distinct close values across hundreds to thousands of bars, despite
being genuinely liquid ($11-27M/day) names. **Independently corroborated
against IBKR's own data feed (not just yfinance) — same exact price
levels on both providers — so this is real market data, not a fetch
defect.** The open question is now whether Engle-Granger cointegration
is even well-specified on a price series this information-sparse (2-7
distinct values over multiple days), not whether the data is corrupted.
Do not use either pair as a worked example anywhere in this paper until
that methodological question is resolved.

**Scope confirmed universe-wide (2026-06-23)**: a full audit
(`audit_price_degeneracy.py`) across all 1,354 evaluated 1m symbols
found **432 (31.9%) flagged** — genuinely liquid by daily dollar volume
but with implausibly few distinct intraday prices (median 14 distinct
closes across the entire cached history). Same pattern confirmed at
2m (24.6%) and 3m (30.4%), falling off sharply by 5m (10.0%) and rare
beyond 15m/30m (1.3%/0.3%) — a well-bounded, sub-5-minute phenomenon,
not a uniform artifact. Cross-referenced against current 1m confirmed
pairs: **10 of 12 (83%) have both legs flagged.**

**Root cause characterized, not just observed (2026-06-23, later same
session)**: tested exchange tier, float ratio, sector, and market
capitalization directly against metadata for all 1,354 symbols.
Exchange tier explains nothing (NYSE is 64.0% of both groups,
identically). Float ratio is weak (0.955 vs 0.988). Sector shows a
real but likely secondary skew (Financial Services/Real Estate
over-represented, Technology/Industrials under-represented — plausibly
downstream of market cap rather than independent). **Market
capitalization is the dominant, statistically overwhelming
explanation**: flagged median $3.0B vs. clean median $17.3B, almost 6x
smaller (Mann-Whitney U test p = 1.82e-145; correlation between
log(market cap) and flagged status = -0.629). Mechanism: smaller-cap
names can clear a *dollar-volume* liquidity floor via a handful of
larger, sporadic trades without trading *frequently* at the tick level
the way mega-caps do via continuous small-lot order flow — trade size
and trade frequency are different dimensions of liquidity, and
screening on dollar volume alone conflates them.

**This is now a real, well-characterized, citable finding, not an
unexplained anomaly** — a third distinct mechanism alongside the
Strictness Paradox (§4.2, full-sample test power borrowed from a dead
regime) and the calendar-padding artifact (§4.5, an exact derivable
arithmetic artifact): daily dollar-volume liquidity screening silently
admits ~32% of a nominally-liquid universe into intraday cointegration
testing on trade-frequency-starved data. Whether this becomes a formal
third pillar in this paper's structure is still Ross's call — he was
explicitly unsure when asked (2026-06-23) — but the open question has
shifted from "is there even a real phenomenon" (yes, conclusively) to
"how to frame it." A candidate fix (a price-density screen,
`price_density_screen.py`) was built and shown to keep 2/12 and exclude
10/12 of the current 1m pairs if adopted — kept as a comparison arm,
not wired into the real pipeline, per Ross's explicit instruction:
these are ranking/selection decisions that should be evaluated against
actual backtest performance once that exists, not decided on
intermediate statistical grounds alone.

## 6. Statistical Validation [OUTLINED — depends on stats.py, not built]

[PLACEHOLDER]

## 7. Strategy / Backtest Results [OUTLINED — depends on backtest.py, not built]

Per the framing decision above: this chapter's job is to demonstrate the
methodology from §4 has practical teeth, not to be the sole basis for the
paper's contribution claim. [PLACEHOLDER until backtest.py exists.]

## 8. Bias Documentation [OUTLINED, one bias drafted in detail]

Pull directly from `BiasAuditLog` (`output/results/bias_audit.json`,
62 entries as of the latest run) — Kelly lookahead, in-sample stop
comparison, survivorship from current-constituent-only universe,
small-n filtering, reproducibility conditioned on intraday-accumulation
state at run time. Each entry already has mechanism/remedy/residual-risk
fields — most of this section is faithful transcription + framing, not
new analysis.

**One entry drafted in more depth, since it connects directly to §10's
future-work discussion:** rolling-window overlap in ml.py's training
labels. Each labeled entry event's outcome window spans `2 × half_life`
bars from entry; consecutive entry events for the same pair routinely
fall within `2 × half_life` bars of each other, so their outcome windows
overlap substantially. Standard sampling (bootstrap, k-fold) treats these
as independent observations, which overstates effective sample size —
material here because the project is already sample-constrained (12-32
labeled examples to date) and `Config.ML.MIN_CLASS_SAMPLES`'s
≥30-per-class threshold is itself a count of *nominal*, not
*independence-adjusted*, examples. Currently undocumented as a numerical
correction (only the rolling-window-overlap *mechanism* itself is
captured in the bias audit's existing prose); §10 below proposes
sequential bootstrap (Lopez de Prado, *AFML* Ch. 4) as the not-yet-built
remedy.

## 9. AI-Tool Disclosure [OUTLINED, three concrete examples drafted]

This project used Claude Code (Anthropic) as an implementation/research
partner throughout. The disclosure's value, beyond compliance, is as
falsifiable evidence of a specific research skill — catching incorrect
output (the AI's own or a summary of it) by checking it against raw
evidence rather than trusting the written record. Three concrete,
real examples, kept specific rather than genericized:

1. **A prior session's "fixed" claim was false, caught by re-testing
   live code.** An earlier session's write-up stated two bugs (BUG-D31,
   a shared-yfinance-session fix; BUG-D32, a 4h session-aligned resample
   fix) were resolved. The next session tested both directly against the
   live code rather than trusting the documented claim, and found
   neither fix was actually present in the code — the documentation and
   the implementation had silently diverged. From that point, every
   "documented as fixed" claim in this project's session log is treated
   as a hypothesis to verify, not a fact, *including this paper's own
   claims about itself* — a standing methodological commitment, not a
   one-time fix.
2. **A third-party AI tool's summary of diagnostic output contained a
   logical contradiction**, asserted during investigation of an
   intermittent Wikipedia-scraper failure. Caught by requesting the
   literal, unsummarized raw text instead of continuing to reason from
   the summary — the contradiction was visible immediately once the raw
   output was in hand.
3. **This project's own most recent session**: a debug script written to
   verify a bug fix (`debug/_verify_save_tf_results_return.py`)
   inadvertently wrote 6 fake placeholder symbols into a shared,
   production artifact (`confirmed_pairs_manifest.json`) as a side
   effect of exercising the code path under test. Caught before the
   manifest was used for a real downstream fetch, by inspecting the
   manifest's actual contents rather than assuming the test's own
   cleanup step (which only removed its own throwaway output directory)
   had been sufficient. The fix script was itself corrected to back up
   and restore shared state around itself, the same discipline now
   documented as a standing convention for any future debug script that
   touches shared project artifacts.

**[TODO before finalizing]**: verify each target program's
(Baruch/Berkeley/Columbia) specific required AI-disclosure format and
scope separately — this section's content is ready, its presentation
format is not yet confirmed against any specific program's requirements.

## 10. Future Work [OUTLINED, two candidates discussed in depth]

Large pieces still to come: ml.py Stage 2 (macro/characteristics/regime
context), stats.py (EVT/GPD, DCC-GARCH, confirmatory PO+KPSS),
backtest.py, options overlay, report.py. Cross-reference
`Development.md`'s Session 10 ideas backlog (~60 ideas across
architecture, academic, ML, portfolio, and narrative lenses) for the
full candidate list — none actioned yet, each needs explicit discussion
before being built per this project's standing methodology-buy-in rule.
Two candidates discussed in enough depth as of this session to record
the actual reasoning, not just the name:

- **Sequential bootstrap / sample-uniqueness weighting** (Lopez de
  Prado, *AFML* Ch. 4) — direct remedy for the rolling-window-overlap
  bias documented in §8. Highest value-to-effort candidate identified so
  far: it targets a bias this project already documents as a limitation
  rather than introducing a new one, requires no new infrastructure
  (just a different sampling scheme inside ml.py's existing training
  loop), and is most useful exactly where the project is currently most
  constrained — small labeled-example counts (12-32 to date), where
  overstated effective sample size from overlapping labels matters most.
- **Transfer entropy for lead-lag detection** — a nonlinear,
  information-theoretic extension of the still-unbuilt Granger-causality
  backlog item (Session 6). Maps directly onto the ES↔utility-sector
  framing already in this project's design outline, and would give a
  second, independent signal for which leg of a pair leads — useful both
  as a candidate ml.py feature and as a robustness check on hedge-ratio
  direction. Real implementation cost: needs careful binning/embedding-
  dimension choices and permutation-based significance testing to avoid
  finite-sample bias — flagged as needing care, not a quick add.

Ross reviewed the remaining academic-lens backlog (2026-06-23) and
approved most of it. Status, updated same day after building and
running four of them for real:

- **Idea #2 (graph clustering) — built, real comparison run.** Louvain
  community detection on the same correlation matrix the pairwise
  pipeline uses recovers genuine structure with zero supervision (OXY
  lands in a clean 6-member oil & gas cluster with COP/CVX/DVN/EOG/XOM).
  Several confirmed-pair symbols (APAM/AZTA/INVX) showed NaN pairwise
  correlation against nearly the whole universe, including each other —
  tracing this down led directly to BUG-D49 below.
- **Idea #8 (tail-dependence gate) — built, ran clean.** One pair
  (CCL/NCLH @3m) shows real, reliability-screened tail asymmetry
  (λ_U≈0.5 vs λ_L≈0.32). Everything else either shows no material
  asymmetry or too little data to trust yet. Gate result: not (yet) a
  green light for building an asymmetric copula entry rule broadly.
- **Idea #9 (conformal prediction) — built, integrated into ml.py
  directly** (`ConformalPredictor`, calibrated on the validation slice
  the existing 60/20/20 split already carved out but never used).
  Verified with a synthetic test; real evaluation waits on more labeled
  examples, same as the rest of ml.py.
- **Idea #4 (BH-FDR robustness check), reframed** — knockoff filters
  don't transplant cleanly onto pairwise hypothesis testing on time
  series (they're built for regression variable selection). Built a
  circular-shift permutation check instead (`eg_permutation_check.py`),
  run alongside production BH-FDR, not replacing it. **Real result: 12 of
  30 confirmed pairs flagged** (real EG significant, permutation-based
  check not); mean "null also looks significant" rate across all 30 is
  14.6% vs. an expected ~5%. MTDR/MGY@3m is a clean case: p=0.000022 on
  real data, 86% of random circular shifts also significant — that
  pair's apparent cointegration is very likely driven by each leg's own
  trend, not real co-movement. **Policy for a flagged pair (exclude /
  downweight / require corroboration) is a separate decision from the
  diagnostic itself — discussed with Ross 2026-06-23, leaning toward
  "require corroboration" to stay consistent with the coint_frac
  override's own precedent, not yet finalized.**
- **Idea #11 (MIDAS) — math verified, evaluation correctly deferred.**
  Beta-polynomial lag weighting confirmed correct via synthetic checks
  and demonstrated on real SPY/VOO 1h data. Evaluating whether it
  actually helps prediction needs labeled 4h entry-event outcomes, and
  SPY/VOO@4h has exactly 1 right now — not enough for any real
  comparison. Machinery is ready; the comparison waits for more data.
- **Idea #3 (moving-band/predictability-optimized basket weights) —
  built, ran with strict walk-forward, got a clean negative result.**
  Implemented the general Box-Tiao/Bewley predictability-portfolio
  formulation (minimize the lag-1 predictability ratio w'Aw/w'Bw) — for
  a 2-asset basket this has an exact closed-form solution via generalized
  eigendecomposition, no CCP solver needed at this size. Verified the
  math with a synthetic test (recovered a known mean-reverting
  combination to within 0.04%) before trusting it on real data. **Strict
  walk-forward (4 expanding folds) across every confirmed pair: in-sample
  advantage +0.136 (as expected — it's optimizing directly for that
  window), but out-of-sample advantage -0.466 — the optimized weights
  are WORSE than plain OLS out-of-sample on average, and only 19% of
  pairs still favor it out-of-sample.** Textbook overfitting signature,
  exactly the risk flagged before any code was written. **Conclusion:
  the naive, unconstrained version should not replace OLS/Kalman.** A
  real, useful negative result, not a dead end — it specifically
  motivates the planned extension below.

  **All three follow-up extensions built and run** (`ccp_variants.py`,
  2026-06-23) — shrinkage toward OLS, sparsity (exact enumeration on
  real confirmed trios), and the actual moving-band mechanism
  (Johansson, Schmelzer & Boyd, arXiv:2402.08108, *Optimization and
  Engineering*, Oct 2024 — verified via direct source lookup before
  implementing: maximize portfolio variance subject to a band + leverage
  constraint via CCP, a genuinely different objective from this
  session's earlier Box-Tiao-ratio build, not the same method renamed).
  Building these caught two real, generalizable bugs via synthetic
  tests before any result was trusted — both worth keeping in mind for
  future optimization work, not just this build: (1) testing sparsity's
  benefit via in-sample fit is circular, since an unconstrained larger
  model always looks at least as good in-sample by construction —
  structure selection needs its own internal validation split; (2) a
  pure i.i.d.-noise leg trivially minimizes the raw Box-Tiao
  predictability ratio (≈-0.018, near the theoretical floor) simply by
  being unpredictable white noise, with zero genuine mean-reversion
  content — a real limitation of that objective worth a footnote
  wherever it's cited, and a point in favor of the moving-band
  formulation's variance-maximization-subject-to-a-band framing, which
  doesn't reward "just be noise" the same way.

  **Result: strict walk-forward across 33 pairs, mean out-of-sample
  predictability ratio (lower=better) — OLS 3.698, unconstrained
  predictability 4.130, shrinkage (α=0.5) 3.821, moving-band 4.199.
  None of the three extensions improves on plain OLS out-of-sample.**
  Three independently-built, independently-verified mechanisms all point
  the same direction: simple OLS remains the more robust choice for this
  project's pairs at current sample sizes. A genuine, three-times-
  replicated negative result, not a dead end — directly supports keeping
  OLS/Kalman as the production hedge-ratio method for now, with this
  comparison as the evidence trail for why. Full results:
  `output/research/ccp_variants_comparison.parquet`.

  Side finding from this build (and the earlier unconstrained build):
  the same `LinAlgError: not positive definite` failure that BUG-D49
  predicts showed up on a much longer symbol list than the original 4 —
  HRMY, PRDO, TILE, WS, EIG, ACT, CTKB, PRAA, UHT also hit it, motivating
  the universe-wide audit below, which confirmed the pattern affects
  ~32% of the 1m universe, not a handful of names.

- **Approved, but logically blocked on something else being decided
  first — not rejected, just not buildable yet:**
  - **Stability selection** (idea #7, Meinshausen & Bühlmann) — the
    planned replacement for ml.py Stage 2's flat 0.85-correlation
    feature-drop rule. Stage 2's feature set itself isn't decided yet
    (deliberately deferred per the staged-build discipline — Stage 1
    validates core spread-level features alone first). Planned
    application: once Stage 2 features are chosen, use repeated
    subsample-and-refit selection instead of one static correlation
    threshold, given this project's small, regime-heterogeneous
    training set makes a single static threshold fragile.
  - **Nested Clustered Optimization** (idea #12, Lopez de Prado) — fills
    the gap between HRP (no return info) and unconstrained MV (fragile)
    on the fragile→robust portfolio-construction spectrum already
    designed for backtest.py, which doesn't exist yet. Planned
    application: add as a named method alongside the other 8 already-
    designed portfolio-construction options once backtest.py's
    portfolio layer is actually built — same author/toolset already in
    use elsewhere in this project (Lopez de Prado), low-friction once
    the surrounding infrastructure exists.
- **Reinforcement learning as a 4th model class** (idea #10) — approved
  in principle but explicitly gated on a dedicated discussion before any
  code, per both the original backlog flag and Ross's own confirmation.
  Not scheduled yet.
- **Deep Learning Statistical Arbitrage** (idea #1, Guijarro-Ordoñez/
  Pelger/Zanotti) — citation only, no build; positions this paper's
  simpler two-stage approach relative to the modern academic
  state-of-the-art. Add to §2's literature review once that section gets
  a full pass.

## References [running list — see §2 for sourcing status of each]

All entries below marked **[VERIFIED 2026-06-23]** were confirmed via
direct source lookup this session (title, venue, volume/pages, and a
working link all cross-checked) — not cited from memory alone. Entries
marked **[TBD]** have the author/year/concept right (used correctly
elsewhere in this project) but specific figures or exact bibliographic
detail not yet confirmed; do not cite numbers from these until verified.

1. **[VERIFIED 2026-06-23]** Engle, R. F., & Granger, C. W. J. (1987).
   Co-integration and error correction: Representation, estimation, and
   testing. *Econometrica*, 55(2), 251-276.
   [Econometric Society](https://www.econometricsociety.org/publications/econometrica/1987/03/01/co-integration-and-error-correction-representation-estimation) ·
   [JSTOR](https://www.jstor.org/stable/1913236) ·
   [IDEAS/RePEc](https://ideas.repec.org/a/ecm/emetrp/v55y1987i2p251-76.html)
2. **[VERIFIED 2026-06-23]** Vidyamurthy, G. (2004). *Pairs Trading:
   Quantitative Methods and Analysis*. Wiley. Described independently as
   the most-cited work on cointegration-based pairs trading; builds the
   standard framework on an adapted Engle-Granger test and a VECM
   formulation.
   [ResearchGate](https://www.researchgate.net/publication/47801548_Pairs_Trading_Quantitative_Methods_and_Analysis_G_Vidyamurthy)
3. **[VERIFIED 2026-06-23]** Gregory, A. W., & Hansen, B. E. (1996).
   Residual-based tests for cointegration in models with regime shifts.
   *Journal of Econometrics*, 70(1), 99-126.
   [ScienceDirect](https://www.sciencedirect.com/science/article/pii/0304407669416857) ·
   [Semantic Scholar (PDF)](https://www.semanticscholar.org/paper/Residual-based-tests-for-cointegration-in-models-Gregory-Hansen/df7feebfbe82f664457ef80078c688f35749bdb3)
4. **[VERIFIED 2026-06-23]** Hansen, B. E. (1992). Tests for parameter
   instability in regressions with I(1) processes. *Journal of Business
   & Economic Statistics*, 10(3), 321-335.
   [Taylor & Francis](https://www.tandfonline.com/doi/abs/10.1080/07350015.1992.10509908) ·
   [IDEAS/RePEc](https://ideas.repec.org/a/bes/jnlbes/v10y1992i3p321-35.html)
5. **[VERIFIED 2026-06-23]** Quintos, C. E., & Phillips, P. C. B. (1993).
   Parameter constancy in cointegrating regressions. *Empirical
   Economics*, 18, 675-706.
   [Springer](https://link.springer.com/article/10.1007/BF01205416)
6. **[VERIFIED 2026-06-23]** Benjamini, Y., & Hochberg, Y. (1995).
   Controlling the false discovery rate: A practical and powerful
   approach to multiple testing. *Journal of the Royal Statistical
   Society, Series B*, 57(1), 289-300.
   [Wiley](https://rss.onlinelibrary.wiley.com/doi/10.1111/j.2517-6161.1995.tb02031.x) ·
   [Oxford Academic](https://academic.oup.com/jrsssb/article/57/1/289/7035855)
7. Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*.
   Wiley. (Not re-verified this session — already this project's primary
   ML-methodology reference, see `Development.md`'s "Reference Authors"
   section for extensive prior detail.)
   [Wiley](https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086)
8. **[VERIFIED 2026-06-23]** Gatev, E., Goetzmann, W. N., & Rouwenhorst,
   K. G. (2006). Pairs trading: Performance of a relative-value
   arbitrage rule. *The Review of Financial Studies*, 19(3), 797-827.
   Distance method (not cointegration) — see §2 for why this matters for
   how this paper cites it.
   [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=141615) ·
   [NBER](https://www.nber.org/papers/w7032) ·
   [Oxford Academic](https://academic.oup.com/rfs/article-abstract/19/3/797/1646694)
9. **[VERIFIED 2026-06-23]** Avellaneda, M., & Lee, J. (2010).
   Statistical arbitrage in the U.S. equities market. *Quantitative
   Finance*, 10(7), 761-782.
   [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1153505) ·
   [Taylor & Francis](https://www.tandfonline.com/doi/abs/10.1080/14697680903124632)
10. **[VERIFIED 2026-06-23]** Krauss, C. (2017). Statistical arbitrage
    pairs trading strategies: Review and outlook. *Journal of Economic
    Surveys*, 31(2), 513-545.
    [Wiley](https://onlinelibrary.wiley.com/doi/abs/10.1111/joes.12153)
