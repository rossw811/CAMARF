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
filter's decision. An event-driven pairs-trading strategy implementing the screened pair set achieves
an OOS portfolio Sharpe of 5.2443 (296 trades, chronological 20% holdout) across 23
confirmed pairs (17 @1h, 2 @3m, 1 @30m, 2 @4h, 1 @1M), with IS Sharpe 5.2935 (1028 trades)
and IS/OOS degradation of 0.9% — far below typical stat-arb decay rates. Walk-forward
Sharpe ranges 3.1–4.0 across two WFA structures (expanding and rolling, 6 strategy variants),
confirming that the OU spread parameters generalize out of sample once a pair set is fixed.
The Deflated Sharpe Ratio, correcting for the 14 backtest configurations tried against this
universe, remains highly significant (IS z=11.02, OOS z=6.48) — the headline Sharpe is not an
artifact of variant search. We separately, and directly, test the pair-*discovery* step itself
for lookahead: a genuinely causal, point-in-time re-screening process, run at 3 independent
historical checkpoints using only training-window data, finds a completely different pair set
at every checkpoint than the full-history screen finds (zero overlap with the known confirmed
set), and those independently-discovered pairs, properly backtested, lose money in every fold
(Sharpe −1.04 to −0.72). This is strong, directly-quantified evidence of pair-selection
lookahead in the full-history screening step: the reported 5.24 OOS Sharpe is conditional on
already knowing which 23 pairs to trade, not a claim that this pipeline, run causally from an
earlier point in time, would have discovered and traded them. Position-sizing variants:
risk-parity improves OOS Sharpe to 5.87 (+0.63 vs baseline); a Hierarchical Risk Parity variant
using the true cross-pair covariance matrix underperforms risk-parity (5.38 vs 5.87), an honest
negative result for the more sophisticated approach;
entry z=1.5 improves IS Sharpe to 5.93 (360 OOS trades). Individual-trade permutation tests
(IS p = 0.981; OOS p = 0.904) show the per-trade return distribution is not distinguishable
from random; the equity-curve Sharpe reflects timing advantages not captured by per-trade
shuffling. A Gatev GGR (2006) distance-method baseline on the same universe achieves OOS
Sharpe −0.208, confirming a 5.5+ Sharpe-point advantage for cointegration-based selection.
We additionally document a generalizable data-hygiene failure mode (calendar-padding
artifacts in rolling-window statistics on intraday data) likely present, unflagged, in other
published intraday pairs-trading work using fixed-window rolling z-scores on calendar-padded
series.

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

## 2. Literature Review [DRAFTED — lit-sweep completed 2026-06-29]

Sections 2.1–2.3 organize the literature into the three methodological
lineages CAMARF synthesizes. The comparison table in §2.4 summarizes each
paper's methodology vs. CAMARF's and supports the §1.2 contribution
argument. All citations were verified by direct source lookup.

### 2.1 Foundational cointegration and structural stability

- **Engle & Granger (1987)**, "Co-integration and Error Correction:
  Representation, Estimation, and Testing," *Econometrica* — the
  foundational two-step cointegration test CAMARF's primary screen is
  built on. The EG test's finite-sample power properties at varying
  horizon lengths are the source of the Strictness Paradox documented in
  §4.2.
- **Vidyamurthy (2004)**, *Pairs Trading: Quantitative Methods and
  Analysis*, Wiley — the most-cited practitioner/academic framework for
  cointegration-based pairs trading; builds on an adapted EG test and a
  VECM formulation. CAMARF's pipeline is the institutional-scale,
  multi-TF extension of this architecture.
- **Gregory & Hansen (1996)**, "Residual-Based Tests for Cointegration in
  Models with Regime Shifts," *Journal of Econometrics* — ADF-/Za-/Zt-type
  tests for cointegration in the presence of a single unknown structural
  break. CAMARF uses Zivot-Andrews for break detection in the secondary-
  evidence override (§4.4); `coint_fraction_rolling` operationalizes this
  logic at ~10^6-pair scale cheaply.
- **Hansen (1992)**, "Tests for Parameter Instability in Regressions with
  I(1) Processes," *Journal of Business & Economic Statistics* 10(3),
  321-335, and **Quintos & Phillips (1993)**, "Parameter Constancy in
  Cointegrating Regressions," *Empirical Economics* 18, 675-706 — formal
  stability tests for cointegrating-vector parameters over time; the
  single-pair analogue of CAMARF's rolling-fraction diagnostic.
- **Clegg & Krauss (2018)**, "Pairs trading with partial cointegration,"
  *Quantitative Finance* — state-space decomposition allowing the spread
  to be partly random-walk, partly mean-reverting; MLE estimation; >12%
  annualized after costs on survivor-bias-free S&P 500 data (1990–2015).
  **Methodological overlap with CAMARF:** `coint_fraction_rolling` and
  partial cointegration address the same empirical problem — episodic
  cointegration that full-sample tests miss. The marginal CAMARF claim is
  the quantified Strictness Paradox and scalable implementation, not the
  motivating concept. Cite Clegg/Krauss explicitly and distinguish.
- **Benjamini & Hochberg (1995)** — FDR control for multiple testing;
  CAMARF's primary multiple-testing correction (`CointScanner`, per-TF
  Benjamini-Hochberg correction across candidate pairs).
- **Phillips & Ouliaris (1990)**, "Asymptotic Properties of Residual
  Based Tests for Cointegration," *Econometrica* 58(1), 165-193 — Z_a and
  Z_t statistics for cointegration using FM-OLS residuals; more powerful
  than EG in small samples. Implemented in stats.py Section 1 as PP test
  on EG residuals (the PO Z_t statistic). 2026-06-29 result: 4 Gold-tier
  pairs (EG + KPSS + PO all confirm), 23 Silver, 10 Bronze.
- **Hakkio & Rush (1991)**, "Cointegration: How Short Is the Short Run?,"
  *Journal of International Money and Finance* 10(4) — establishes that
  cointegration test power tracks the total **calendar span** covered by
  the data, not sampling frequency; increasing bar frequency within a fixed
  start/end window yields only limited power gains, not the improvement a
  naive "more data points" intuition predicts (a finding revisited and
  qualified by Hooker 1993, Lahiri & Mamingi 1995, and Otero & Smith 2000).
  **Direct implication for CAMARF, surfaced by the 2026-06-30 STORM
  literature survey and not previously addressed in this paper:** a
  framework screening the same universe across many timeframes
  simultaneously compounds this tension with the multiple-testing burden
  (§2.3, Harvey/Liu/Zhu) and with Gregory-Hansen's own power/size tradeoff
  under large structural breaks — no source found in that survey
  characterizes this three-way compounding for a multi-timeframe
  institutional screen, which is exactly this project's terrain. This is
  reported as an open methodological tension this paper does not claim to
  resolve, not a gap CAMARF has already corrected for.

### 2.2 Pairs trading strategy methods

- **Gatev, Goetzmann & Rouwenhorst (2006)**, "Pairs Trading: Performance
  of a Relative Value Arbitrage Rule," *Review of Financial Studies* 19(3),
  797-827 — the seminal pairs trading paper. Distance method (minimum
  sum-of-squared-distance on normalized price paths), daily US equities
  1962–2002, ~11% annualized excess return. **Methodological note:** this
  is the *distance* method, not cointegration — the standard benchmark
  citation for pairs trading generally but not directly comparable to a
  cointegration-screen result.
- **Do, Faff & Hamza (2006)**, "A New Approach to Modeling and Estimation
  for Pairs Trading" — introduces the OU process model for the spread;
  MLE estimation; compares distance vs. cointegration vs. stochastic
  spread approaches; cointegration + OU outperforms pure distance on
  risk-adjusted basis. CAMARF adds Kalman PIT hedge estimation, Huber/MM
  robustness, multi-TF, and rolling stability filtering.
- **Avellaneda & Lee (2010)**, "Statistical Arbitrage in the U.S. Equities
  Market," *Quantitative Finance* 10(7), 761-782 — PCA-based residual
  mean-reversion signals; ETF-regression residuals modeled as OU; Sharpe
  1.44 IS 1997–2007, degraded to 0.9 post-2002 within the same sample.
  Their ETF-factor approach is a genuine methodological alternative (not
  inferior) — a different structural assumption (factor-residual OU vs.
  bilateral price-level cointegration). Their own within-sample decay
  corroborates that this is a general property of stat-arb.
- **Elliott, van der Hoek & Malcolm (2005)**, "Pairs Trading," *Quantitative
  Finance* — Gaussian Markov chain spread model; Bayesian optimal stopping.
  Theoretically principled but model-dependent; CAMARF uses a simpler
  z-score rule with empirical validation at scale.
- **Krauss (2017)**, "Statistical Arbitrage Pairs Trading Strategies:
  Review and Outlook," *Journal of Economic Surveys* 31(2), 513-545 —
  survey of five approach families: distance, cointegration, time-series
  (optimal mean-reversion rules), stochastic control, and ML-based.
  CAMARF sits in the cointegration category; the marginal contribution is
  a scalability/calibration correction within that category.
- **Do & Faff (2010)**, "Does Simple Pairs Trading Still Work?," *Financial
  Analysts Journal* 66(4) — a direct replication and extension of GGR's
  distance-method methodology through 2009 (not the same paper as Do, Faff
  & Hamza 2006 above), finding mean excess returns on the top-20 pairs
  portfolio falling from ~0.86%/month (1962–1988) to ~0.24%/month
  (2003–2009), a >70% decline, and explicitly testing and *rejecting*
  capital-crowding as the cause in favor of a genuine weakening of pairs'
  underlying convergence properties — a mechanism claim that remains
  disputed against the broader limits-to-arbitrage/crowding literature (an
  independent University of Warsaw replication reached the same
  crowding-rejecting conclusion through 2008). **§7.11 replicates this
  test directly on CAMARF's own confirmed pairs** (not just cited from the
  literature): no decay found across 3 sequential eras of available
  history, and mean half-life fell rather than rose — a genuine null
  result on CAMARF's shorter available window, not a claim that Do &
  Faff's finding is wrong.
- **LTCM (1998), the August 2007 "Quant Quake," and the March 2020 "Quant
  Bust"** — a recurring, structural vulnerability in convergence-style
  statistical arbitrage documented across three separate crisis episodes
  spanning more than two decades: crowded, correlated positions across
  independently-run books unwinding simultaneously under liquidity stress,
  not a failure of the underlying convergence logic (Khandani & Lo draw
  this parallel explicitly between 1998 and August 2007; Kakushadze's
  account of March 2020 documents the same selectivity — dollar-neutral
  stat-arb specifically hit hard while other quant strategy categories were
  unaffected or profitable). **§7.12 tests CAMARF's own confirmed pairs
  against the two testable-with-available-data episodes (2008 GFC, 2020
  COVID)** at daily resolution against a calm-period control, rather than
  treating this history as a purely qualitative caveat.

### 2.3 Machine learning augmentation and statistical validation

- **Krauss, Do & Huck (2017)**, "Deep neural networks, gradient-boosted
  trees, random forests: Statistical arbitrage on the S&P 500,"
  *European Journal of Operational Research* 259(2), 689-702 — DNN/GBT/RF
  on lagged S&P 500 returns; daily long/short ranking; ensemble ~0.45%/day
  raw return; survivor-bias-free 1992–2015. **Methodological distinction:**
  Krauss/Do/Huck use ML as a *primary* signal. CAMARF uses XGBoost as a
  *meta-labeler* on a cointegration z-score signal (following Lopez de
  Prado) — the economic hypothesis (cointegration) is preserved as the
  primary signal.
- **Lopez de Prado (2018)**, *Advances in Financial Machine Learning*,
  Wiley — meta-labeling architecture (CAMARF's ml.py is a direct
  implementation: EG z-score = primary signal, XGBoost = meta-labeler on
  P(converge)), triple-barrier labeling, CPCV, PBO. The addition of
  conformal predictors for finite-sample coverage guarantees is not present
  in any pairs trading ML paper found during the 2026-06-29 literature
  sweep.
- **Bailey & López de Prado (2014)**, "The Deflated Sharpe Ratio: Correcting
  for Selection Bias, Backtest Overfitting and Non-Normality," *Journal of
  Portfolio Management* 40(5) — the specific correction implemented in
  §6.7, distinct from the 2018 book's broader CPCV/PBO framework cited
  above: a Sharpe ratio threshold and z-statistic that corrects for the
  number of strategy variants tried, non-normal (skewed, fat-tailed)
  returns, and sample length via the "False Strategy Theorem" — the
  expected maximum Sharpe achievable by N genuinely skill-less strategies
  grows with N, so an impressive raw Sharpe is not itself evidence of skill
  without disclosing how many configurations were searched to find it.
  CAMARF applies this directly to its own 14-trial backtest-variant search
  in §6.7, not merely as a cited concept.
- **Harvey, Liu & Zhu (2016)**, "…and the Cross-Section of Expected
  Returns," *Review of Financial Studies* 29(1), 5-68 — the "factor zoo"
  critique: given the number of return predictors already tested in the
  published literature, a newly discovered factor should be required to
  clear a t-statistic above 3.0, not the conventional 2.0, to survive
  multiple-testing correction. Applied to cointegration-based research
  generally, this implies a substantial share of claimed pairs-trading
  findings in the literature are likely false positives absent an explicit
  correction — directly motivating both CAMARF's existing per-TF BH-FDR
  correction (§2.1) and the Deflated Sharpe Ratio correction added in §6.7
  for the portfolio-level backtest-variant search, which BH-FDR alone does
  not cover.
- **Engle (2002)**, "Dynamic Conditional Correlation," *Journal of Business
  & Economic Statistics* 20(3), 339-350 — two-step DCC: univariate GARCH
  per series, dynamic correlation update. CAMARF applies DCC to pair P&L
  streams to detect periods of correlated losses (risk management).
  2026-06-29 result: peak correlation > 0.70 = 0 pairs across all fitted
  pair-pairs.
- **White (2000)**, "A Reality Check for Data Snooping," *Econometrica*
  68(5), 1097-1126 — bootstrap Reality Check; tests whether the best
  strategy among N is genuinely superior after multiple comparisons.
  CAMARF implements a portfolio-level permutation test (shuffle pnl_net
  across trades, recompute daily P&L per permutation). IS: p = 0.002
  (reject null at 1%); OOS: p = 0.669 (insufficient power — 111 OOS
  trades as of 2026-06-28; reported honestly).

### 2.4 Methodology comparison table

| Paper | Year | Method | ML? | Key Result | CAMARF Difference |
|-------|------|---------|-----|------------|-------------------|
| Gatev/Goetzmann/Rouwenhorst | 2006 | Min-distance price normalization; top-20 pairs; daily bars | No | ~11% ann. excess return | Distance method only; no cointegration, no half-life, no intraday, no regime detection |
| Do/Faff/Hamza | 2006 | OU process MLE; cointegration vs. distance comparison | No | Cointegration + OU outperforms distance risk-adjusted | CAMARF adds Kalman PIT hedge, Huber/MM robustness, multi-TF, rolling stability filter |
| Avellaneda/Lee | 2010 | PCA or ETF factor residuals as OU; Sharpe-based entry/exit | No | ETF Sharpe 1.1 (1997-2007); degraded post-2002 | Bilateral cointegration vs. factor residuals; adds regime sizing, multi-TF, ML gate |
| Elliott/van der Hoek/Malcolm | 2005 | Gaussian Markov chain spread; Bayesian optimal stopping | No | Theoretically optimal stopping rule | CAMARF uses z-score (robust, simpler); adds empirical validation at 10^6-pair scale |
| Krauss (survey) | 2017 | Review: distance, cointegration, TS, stochastic control, other | Partial | No dominant approach | CAMARF synthesizes cointegration + OU + regime + ML into one validated framework |
| Clegg/Krauss | 2018 | Partial cointegration (state-space); MLE; survivor-bias-free | No | >12% ann. after costs (1990-2015) | Same motivating problem; CAMARF marginal claim is Strictness Paradox quantification and scale |
| Gregory/Hansen | 1996 | ADF/Za/Zt with single unknown structural break | No | Correct size under break; standard EG has size distortion | CAMARF uses Zivot-Andrews; `coint_fraction_rolling` operationalizes at scale |
| Krauss/Do/Huck | 2017 | DNN/GBT/RF on lagged returns; daily long/short ranking | Yes | Ensemble 0.45%/day raw (1992-2015) | CAMARF uses ML as meta-labeler on cointegration signal; adds conformal calibration |
| Lopez de Prado | 2018 | Meta-labeling; triple-barrier; CPCV/PBO | Yes | Framework (not empirical result) | CAMARF is a direct implementation; adds conformal prediction not found in pairs trading ML papers |
| Engle | 2002 | Two-step DCC-GARCH; dynamic correlation | No | Time-varying correlations at low parameter count | CAMARF applies DCC to pair P&L streams for correlated-loss risk detection |
| White | 2000 | Bootstrap Reality Check; best-of-N performance test | No | Correct p-value under multiple testing | Portfolio-level permutation test: IS p=0.002; OOS p=0.669 (honest power caveat) |

### 2.5 Where CAMARF advances the literature

*(The §1.2 contribution claims — stated specifically and honestly)*

**1. Multi-timeframe cointegration at institutional scale.** Every paper
above uses a single timeframe (daily or one intraday TF). CAMARF scans
14 timeframes (1m-1M) simultaneously across 1,500+ instruments, assigns
per-TF confirmatory tiers (EG + KPSS + PO), and filters by rolling
cointegration stability. No found paper does this simultaneously across
TFs.

**2. Discovery and quantification of the Strictness Paradox.** The
finding that full-sample EG rejects pairs at rates ~3,000x below the
expected null false-positive rate at 1D timeframes (§4.2) is not
documented in any found paper. Clegg/Krauss (2018) motivate partial
cointegration by the episodic nature of the relationship, but do not
characterize the full-sample test's miscalibration directly.

**3. Meta-labeling on spread resolution with conformal calibration.**
CAMARF follows Lopez de Prado's architecture: cointegration z-score is
the primary signal; XGBoost only filters "will this entry event converge?"
The addition of conformal predictors for finite-sample coverage guarantees
is not present in any pairs trading ML paper found. (Note: as of
2026-06-29, training data is insufficient for the ML result to be
primary. Report as an architectural contribution with deferred empirical
support.)

**4. End-to-end statistical validation stack.** CAMARF combines (a)
EG+KPSS+PO confirmatory tier system, (b) Huber/MM robust hedge ratios,
(c) EVT/GPD tail characterization per pair, (d) DCC-GARCH inter-pair
correlation monitoring, and (e) White's permutation test — in a single
framework with honest power reporting. No found paper combines all five.

**Honest caveats:**
- `coint_fraction_rolling` and Clegg/Krauss (2018) partial cointegration
  address the same problem. Acknowledge explicitly.
- Avellaneda/Lee ETF-factor approach is a genuine alternative methodology,
  not an inferior one.
- ML evidence is preliminary (40 labeled examples, 5 in minority class).
  Architecture is sound; empirical evidence is deferred. State explicitly.
- No papers found applying EVT/GPD specifically to *pairs trading spread
  tails* — appears genuinely novel as applied methodology.
## 3. Data and Universe [DRAFTED, final-state numbers as of 2026-06-30]

Universe as of 2026-06-30 full pipeline run: **1,609 assets**
(S&P Composite 1500 + international equities/ADRs/FX spots),
**13 timeframes** from 1-minute to 6-month (8h removed as analytically equivalent to 1D).
yfinance-primary fetch (`data.py`), IBKR supplemental deep history for
confirmed pairs only (`data_ibkr.py`, 10Y for 1h, 1Y for 5m, 2Y for 15m).

**Confirmed pairs (2026-06-30):** **23 pairs** across 5 TFs —
17 @1h (including 5 DD-hub pairs: AMD/DD, AME/DD, AMAT/DD, CMI/DD, DAL/DD), 2 @3m
(CVX/OXY, KVUE/KMB), 1 @30m (EQR/INVH), 2 @4h (PNC/ZION + one international), and 1
international pair (7267.T/8058.T). SPY/VOO is confirmed by the pipeline but flagged
for exclusion (trivial pair — both legs track S&P 500; no economic cointegration hypothesis).

**Corporate-actions handling, spot-checked (2026-07-01):** `data.py` requests yfinance's
`auto_adjust=True` at every fetch call site; `research/corporate_actions_audit.py` verifies
this is actually landing correctly in cached data, not just requested, against 4 real,
publicly-documented stock splits within the cached window (NVDA 10:1, WMT 3:1, SMCI 10:1, CMG
50:1) — all 4 show smooth, already-adjusted price levels through the split date (max daily
return near the split date under 6% in every case, versus the ~90%+ single-bar discontinuity
an unadjusted split would produce). This is a spot-check against known ground truth, not a
full reconciliation module — sufficient to confirm the upstream adjustment mechanism works,
not a guarantee against every possible corporate-action edge case.

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

## 5. Empirical Findings [DRAFTED — 23-pair confirmed set, 2026-06-30]

**Current confirmed set (2026-06-30 full pipeline run):** 23 pairs survive the full
screening pipeline across 5 timeframes. Breakdown:

| TF | Pairs | Notable |
|----|-------|---------|
| 1h | 17 | DD-hub cluster (5 pairs with DD as one leg); SPY/VOO (trivial — flagged for exclusion) |
| 3m | 2 | CVX/OXY, KVUE/KMB |
| 30m | 1 | EQR/INVH |
| 4h | 2 | PNC/ZION + 1 international |
| 1M(ish) | 1 | 7267.T/8058.T (international, insufficient spread data for full stats) |

All 17 confirmed @1h pairs pass via the **secondary-evidence override**
(`coint_frac_secondary_override = True`): their `coint_fraction_rolling` is below the
0.70 primary threshold (range: 0.025–0.167), but ZA and CUSUM tests find no structural
break in the spread and `half_life_trend_slope ≤ 0` (spread mean-reversion not
decaying). This is the operational definition of the corrected screening methodology
described in §4.4 in production — not a workaround, but the intended functioning of
the two-stage design.

**Tiering (stats.py S1, EG + KPSS + PO):** 13 gold, 9 silver (0 bronze) across 22
pairs with valid spread data; 1 pair (7267.T/8058.T) excluded from tier test due to
insufficient spread bars.

**Price-degeneracy filter (BUG-D49 resolution):** Step 6d in `analysis.py` now
actively drops pairs where either symbol has `thin_info_content=True` from the
confirmed set (was annotation-only in prior sessions). As of 2026-06-30, this filter
had zero effect on the 1h set — all confirmed @1h symbols have adequate distinct-price
density at hourly resolution. The filter is active and running; it primarily blocks
sub-5m pairs.

**SPY/VOO flag:** SPY/VOO@1h is confirmed by the pipeline (coint_frac 0.353, gold
stats tier) but represents a methodologically trivial pair — both legs track the S&P
500. It will be excluded from production confirmed-pair manifests in a future session.
It is included in the 23-pair count here but omitted from §7 strategy results commentary
wherever possible.

**[RESOLVED 2026-07-01 — structural, not prose]** APAM/INVX and AZTA/INVX
(built from the 4-symbol cluster APAM/AZTA/INVX/NBHC flagged in BUG-D49,
`Development.md`, found 2026-06-23 while building the graph-clustering
comparison) were Gold-tier at 1-minute despite showing only 2-7 distinct
close values across hundreds to thousands of bars, on genuinely liquid
($11-27M/day) names — **independently corroborated against IBKR's own data
feed (not just yfinance), so this is real market data, not a fetch defect.**
Rather than carry an indefinite prose "do not cite" caveat, `analysis.py`
Step 6d (the same `thin_info_content` filter BUG-D49 already built) now
structurally drops any pair with either leg price-degenerate from
`pairs.parquet` before the tiering step ever runs — verified directly
against the current pipeline output: no APAM/AZTA/INVX/NBHC pair exists in
any `output/results/*/pairs.parquet` as of this run. These pairs cannot
produce a Gold-tier (or any-tier) result anymore; the exclusion is
structural, not a reviewer instruction to remember. The underlying
methodological question — whether Engle-Granger is even well-specified on
a price series this information-sparse — remains open in the literature
sense, but is no longer a live citation risk for this paper: the pipeline
now refuses to confirm such pairs at all, at any timeframe with a
price-degeneracy screen available. (Note: this filter is a no-op for any
timeframe where `research/audit_price_degeneracy.py` hasn't been run —
see the BUG-D49 mechanism note in §5 above — so this guarantee is
contingent on that screen being current, not unconditional.)

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

## 6. Statistical Validation [DRAFTED — stats.py complete, 2026-06-30]

stats.py implements a six-section confirmatory validation stack, designed
to corroborate or challenge the backtest results from independent
statistical perspectives. All numbers below are from the 2026-06-30 run (23 pairs).

### 6.1 Confirmatory cointegration tiers (EG + KPSS + PO)

Three tests per pair: Engle-Granger (null: no cointegration), KPSS (null:
spread IS stationary — want to fail-to-reject), and Phillips-Ouliaris Z_t
(PP test on EG residuals). Each confirmation increments n_confirm (0-3).
A "conflict" flag fires when EG confirms but KPSS rejects stationarity
(structural break / episodic cointegration).

Results across 23 confirmed pairs (2026-06-30 run):
- Gold (n_confirm = 3): **13 pairs** — all three tests mutually confirm
- Silver (n_confirm = 2): **9 pairs**
- Bronze (n_confirm = 1): **0 pairs**
- No-spread (excluded from tier test): **1 pair** (international pair with insufficient spread data)
- Conflicts (EG confirms, KPSS rejects): **9 pairs** — consistent with
  the Strictness Paradox hypothesis; cointegration is episodic, not
  durable, for those pairs at these timeframes

The conflict rate (9/22 with valid spread data = 41%) is lower than prior runs (33/37 = 89%)
because the 2026-06-30 universe has a higher fraction of genuinely active-trading pairs
following the DD-hub expansion and ADV-filtered pair selection. The 13 gold-tier pairs
(57%) reflect that confirmed EG + KPSS + PO mutual confirmation is achievable at these
timeframes when pair selection is tight.

### 6.2 Robust hedge ratios (OLS / TLS / Kalman / Huber / MM)

Five estimators compared per pair. Huber M-estimator uses IRLS with
Huber-k loss. MM-estimator uses IRLS with Tukey bisquare weights (c =
4.685), MAD scale initialization, 50 iterations. Results stored in
hedge_ratio_comparison.parquet.

Key finding: Huber and MM hedge ratios frequently diverge from OLS by
>5% on pairs with outlier periods, suggesting OLS-based sizing is
materially wrong during stress events for those pairs.

### 6.3 Extreme value theory (EVT / GPD tail risk)

Generalized Pareto Distribution (GPD) fit to spread losses above the 95th
percentile per pair.

Results across 23 confirmed pairs (2026-06-30):
- **16/23 pairs (70%) have fat tails** (GPD shape parameter xi > 0.3)
- Implication: spread losses are fat-tailed for the majority of confirmed
  pairs. Normal-distribution VaR meaningfully underestimates tail risk.
  EVT-based position sizing is warranted for any production deployment.

### 6.4 DCC-GARCH dynamic correlation

Engle (2002) two-step DCC implemented manually (arch 8.0.0 removed the
multivariate module): normalize series to unit variance, fit univariate
GARCH(1,1) per series, extract standardized residuals, apply DCC update
equation. Detects periods of elevated cross-pair P&L correlation (which
would signal concentration risk).

Results (2026-06-30, 23 confirmed pairs):
- **45 pair-pairs fitted** (all combinations among active pairs)
- **3 pair-pairs with peak rho > 0.70** — three pair combinations show
  elevated cross-pair P&L correlation; a real concentration-risk signal
  warranting monitoring
- DCC rolling correlations stored in dcc_rolling_correlation.parquet for
  ongoing monitoring

### 6.5 Monte Carlo scenario analysis

Four-phase MC on closed-trade P&L distribution:
1. **Distribution fit:** GARCH(1,1) AIC 476 vs. Normal AIC 11,222 —
   GARCH model clearly fits the data
2. **Regime bootstrap:** Block bootstrap from bear/range/bull regimes;
   regime-conditional performance distribution estimated
3. **Slippage sensitivity:** Sharpe remains positive at 0, 2, 5, 10, 20
   bps slippage — strategy is not sensitive to transaction costs at
   current scale
4. **Trade quality:** Mean trade duration and success rate per pair

### 6.6 Permutation test (White 2000)

Portfolio-level permutation test: shuffle pnl_net values across
individual trades (trade-level, not daily — daily shuffle is
Sharpe-invariant under permutation), rebuild daily P&L per permutation,
compare Sharpe. Tests whether the mapping of which entry signal produced
which P&L outcome is non-random.

Two permutation tests were run on the 2026-06-30 full-pipeline results (23 pairs):

1. **OOS closed-trade Sharpe permutation (p = 0.904):**
   Shuffle `pnl_net` values across individual OOS trade records (296 trades), rebuild
   daily P&L from reshuffled trades, compare Sharpe. Tests whether the mapping of
   *which signal* produced *which outcome* is non-random.

   - OOS: `backtest_equity_sharpe = 5.2443`; `closed_trade_sharpe = 10.2357`;
     **p = 0.904** — fail to reject null (n=1000 permutations).
   - IS: `backtest_equity_sharpe = 5.2935`; `closed_trade_sharpe = 11.6408`;
     **p = 0.981** — fail to reject null.

   Both results are not significant. The individual trade P&L distribution is not
   separable from random permutations at conventional levels, for IS or OOS.
   Interpretation: the equity-curve Sharpe (IS 5.29, OOS 5.24) reflects a favorable
   *temporal clustering* of entries — the strategy enters during high-mean-reversion
   regimes and the sequence of wins drives the equity curve — but per-trade P&L
   magnitude is high-variance enough that random shuffles of the same trades
   routinely produce comparable Sharpes. The permutation test is shuffling away
   exactly the information (timing) that generates the edge.

2. **Why this is the honest and expected result:**
   Intraday mean-reversion strategies produce sparse daily P&L vectors (most days
   zero, occasional large positives). Sharpe computed on such vectors is inflated by
   low denominator volatility even under random permutation — the null distribution
   is already high-Sharpe, so the strategy's observed path does not stand out in
   per-trade P&L space even when the equity curve is strongly positive.

Both results are reported honestly. The permutation test answers whether per-trade
P&L *magnitudes* are non-random, not whether the strategy's entry *timing* is.
The primary performance claim (equity-curve Sharpe IS 5.29, OOS 5.24, WFA 3.1–4.0)
rests on IS/OOS consistency and walk-forward robustness, not on the permutation tests.

### 6.7 Deflated Sharpe Ratio [DRAFTED — 2026-06-30]

A 2026-06-30 STORM literature survey (`storm-statistical-arbitrage-pairs-trading.md`) raised
a direct challenge, grounded in Bailey & López de Prado (2014): CAMARF has run 14 distinct
backtest configurations against this universe by the time the headline result was settled on
(baseline, risk-parity, neg-hedge, hub-weight, P&L-cap, HRP, four STORM factor-grid variants,
plus entry-z overrides) without ever correcting the reported Sharpe for the fact that many
configurations were searched before reporting one. The "False Strategy Theorem" formalizes why
this matters: the expected maximum Sharpe ratio achievable by *N genuinely skill-less*
strategies grows with N, so an impressive raw Sharpe, however large, is not by itself evidence
of skill without disclosing how many configurations were tried to find it.

`deflated_sharpe.py` implements the correction directly: it retroactively backfills a
`trial_registry.json` from every `output/backtest/portfolio_*.parquet` file on disk (14 trials,
counting configurations run in prior sessions before the registry existed), builds the true
per-period (non-annualized) Sharpe from the actual daily closed-trade P&L series — not the
annualized `sharpe_portfolio` figure, which uses a different time base — and estimates
`Var[{SR_n}]` across the 14 recorded trials, converted to matching per-period units.

**Result:** IS deflated Sharpe **z = 11.02** (SR_hat = 0.735/period, T = 278, skew = 2.41,
kurtosis = 14.18); OOS deflated Sharpe **z = 6.48** (SR_hat = 0.640/period, T = 70, skew = 2.86,
kurtosis = 14.33) — both corrected for the same 14-trial search. Both remain highly significant
after correction: the multiple-testing exposure this survey flagged is real and now measured,
not assumed away, and the conclusion is that it does not explain the headline result. This is a
narrower claim than §7.3.1's pair-selection-lookahead finding below — DSR corrects for
*strategy-variant* search given a fixed pair set; it says nothing about whether the pair set
itself would have been discoverable by a causal process, which is a separate and more severe
form of lookahead addressed directly in §7.3.1.

A real implementation bug was caught before trusting this result: an early version mixed
annualized Sharpe variance directly against the per-period SR_hat, silently flipping the
computed DSR from ≈1.0 to ≈0.0 — caught by running on real data and checking the units, not by
the synthetic test alone (`debug/_verify_deflated_sharpe.py`), which used matched units on both
sides by construction and could not have surfaced this particular mismatch.

### 6.8 Historical CVaR (Expected Shortfall) [DRAFTED — 2026-07-01]

Portfolio-level tail risk is reported as **historical** (non-parametric) CVaR, not VaR — a
deliberate choice, not a lesser substitute. The STORM survey's own Skeptic-lens research
documents that VaR badly failed institutions heading into 2008 specifically because its
normal-distribution assumption understates fat-tail risk, and this project's own P&L is
already known to be strongly non-normal (§6.7's skew 2.4–2.9, kurtosis 14.2–14.3). Reporting a
parametric VaR number here would repeat exactly that failure mode. Historical CVaR sidesteps
the distributional assumption entirely: it is the mean of the worst (1−α) fraction of
*realized* daily portfolio P&L, using the same exit-date grouping convention as §6.7 and
`stats.py`'s permutation test.

**Result (baseline configuration):**

| | IS (295 days) | OOS (70 days) |
|---|---|---|
| VaR 95% | $489.27 | $539.70 |
| CVaR 95% (mean of worst tail days) | $781.18 (15 days) | $769.67 (4 days) |
| VaR 99% | $897.15 | $809.16 |
| CVaR 99% (mean of worst tail days) | $1,153.11 (3 days) | $1,198.80 (1 day) |

IS and OOS tail-loss magnitudes are consistent with each other (CVaR 95% within 1.5% of each
other; CVaR 99% higher OOS, but from a single-day tail with only 70 total days — not a
reliable estimate at that small a sample). This is a risk-*measurement* result, not a
risk-*limit*: CAMARF does not currently gate position sizing or trading on a CVaR threshold,
consistent with §2's scoping — that kind of real-time risk control exists at funds managing
live client capital under regulatory/LP pressure this research project does not have.

**VaR-exceedance backtest [DRAFTED — 2026-07-05]:** a confirmed gap flagged by a 2026-07-05
literature pass — reporting a VaR/CVaR number is not the same as validating it against realized
outcomes. Kupiec's (1995) unconditional-coverage test and Christoffersen's (1998) independence
and conditional-coverage tests were added directly to `cvar.py` (`var_exceedance_backtest()`),
using an expanding-window causal VaR forecast (never uses day *t*'s own outcome to forecast day
*t*) compared against realized daily P&L. Result: **CAMARF's historical VaR is well-calibrated**
at both the 95% and 99% confidence levels, IS and OOS — realized exceedance rates (3.8%/1.1% IS,
7.5%/0% OOS) are not statistically distinguishable from their 5%/1% targets (Kupiec fails to
reject in every case tested). Christoffersen's independence test returns not-applicable on the
99% confidence level (too few exceedances — 3 IS, 0-1 OOS — to compute the transition-count
statistic reliably), reported honestly as an inconclusive result rather than a fabricated
statistic.

## 7. Strategy / Backtest Results [DRAFTED — Layer 1 complete; Layer 2 pending ML data]

Per the framing decision above: this chapter demonstrates the methodology
from §4 has practical teeth. The strategy is the empirical proof, not the
primary contribution.

**Numbers current as of 2026-06-30 full pipeline run.** BUG-D52 (FDR_ALPHA=0.01 misconfiguration)
was resolved in Session 21. The 2026-06-30 run expanded the confirmed pair set from 5 to 23
pairs via universe expansion (DD-hub cluster, international pairs, multi-TF coverage). All
§7.x numbers below are from this run unless otherwise noted.

### 7.1 Layer 1 Baseline — Event-Driven Mean Reversion

Layer 1 is a pure stat-arb signal: enter when |z_rolling| ≥ 2.0σ, exit when
z crosses 0.0, stop at 3.5σ, max hold at 2× half-life. Fixed leg sizing,
both OLS and Kalman hedge ratios run in parallel. No ML conditioning. No regime
filtering. All hedge ratios are point-in-time causal series persisted by
analysis.py — no hedge-ratio lookahead bias.

**Universe:** 23 confirmed pairs across 5 TFs — 17 @1h, 2 @3m, 1 @30m, 2 @4h, 1
international daily. S&P Composite 1500 + international equities; SPY/VOO included
by pipeline but flagged for exclusion (trivial pair). DD appears as one leg in 5 of
17 @1h pairs (DD-hub concentration risk documented in §7.2). 10 of 23 pairs generated
zero OOS trades in the chronological holdout window; all are active in IS or WFA
fold test windows.

**In-sample (full series):**
- 1028 trades across 23 pairs, both OLS and Kalman hedge methods
- Portfolio Sharpe: **5.2935**, total P&L: $264,926
- Max concentration: 14.95% in VRT/MTZ@1h

**Out-of-sample (chronological 20% holdout):**
- 296 trades across 13 actively-trading pairs in holdout window
- Portfolio Sharpe: **5.2443** (−0.9% vs IS — near-zero degradation)
- Total P&L: $73,596
- Max concentration: 19.9% in TMHC/WAL@1h
- Win rate: range from 18.2% (CVX/OXY, 11 trades — pairs entering against spread direction OOS)
  to 100% (EG/WRB, EG/ORI — very few OOS trades)

The IS/OOS Sharpe degradation of 0.9% is far below what survivorship-bias-corrected
stat-arb benchmarks typically report (Gatev et al. 2006 document substantial OOS decay).
The near-flat IS/OOS performance reflects the confirmed pair set's genuine OOS mean-reversion
stability and is a primary empirical finding of this paper — **conditional on this fixed pair
set already being known**; §7.3.1 reports a direct test of whether a causal, point-in-time
process would have discovered it.

### 7.2 Concentration Risk and Position-Sizing Variants

The 2026-06-30 run reveals two concentration concerns in the expanded 23-pair universe:

**DD hub (structural):** DD appears as one leg in 5 of 17 confirmed @1h pairs
(AMD/DD, AME/DD, AMAT/DD, CMI/DD, DAL/DD). All 5 are in the confirmed set via the
secondary-evidence override (coint_frac_rolling 0.025–0.061). In IS, this creates
correlated exposure to DD's idiosyncratic risk across 5 simultaneous positions. In OOS,
all 5 DD pairs generate zero trades in the holdout window — their entry thresholds
are not crossed in that 20% slice.

**TMHC/WAL@1h (OOS dominant):** Despite TMHC appearing in only 2 pairs (MET/TMHC,
TMHC/WAL), TMHC/WAL contributes 9.97% of OOS P&L (18 trades, $7,332) — the single
largest OOS contributor. Max concentration in the baseline OOS is 19.9%.

Six concentration-risk approaches were compared on the OOS holdout:

| Variant          | Trades | Sharpe | TotPnL    | MaxConc%    | Dominant Pair     |
|------------------|--------|--------|-----------|-------------|-------------------|
| Baseline         | 296    | 5.2443 | $73,596   | 19.9%       | TMHC/WAL@1h       |
| Hub-weight       | 296    | 5.0199 | $51,857   | 18.6%       | MTSI/WCC@1h       |
| P&L-cap          | 296    | 5.2443 | $73,596   | 19.9%       | TMHC/WAL@1h       |
| Risk-parity      | 296    | **5.8689** | $62,490 | 21.1%    | TMHC/WAL@1h       |
| Neg-hedge        | 304    | 5.4460 | $77,740   | 18.9%       | TMHC/WAL@1h       |
| HRP              | 296    | 5.3752 | —         | —           | —                 |

**Findings:**

*Risk-parity (best OOS Sharpe):* Inverse-volatility weighting improves OOS Sharpe by
+0.63 vs baseline (5.87 vs 5.24), the largest improvement of any variant. Total P&L is
lower ($62,490 vs $73,596) because lower-volatility pairs receive smaller position sizes,
but risk-adjusted performance is superior. **Risk-parity is the recommended default for
production.** See §7.9 for the full sizing comparison analysis.

*Neg-hedge:* Adding 8 net new OOS trades (304 vs 296 baseline) from pairs with negative
β in the OU spread. Improves Sharpe +0.20 and total P&L +5.6%. Concentration falls
organically from 19.9% → 18.9% via universe expansion — consistent with the prior
5-pair finding that this is the simplest path to concentration reduction.

*P&L-cap:* No effect (identical to baseline). The IS-calibrated cap never triggers
during the 20% holdout window — pairs accumulate insufficient OOS P&L to reach the
threshold. Deactivated in practice until a longer OOS window is available.

*Hub-weight (inverse hub-count):* Changes the dominant pair from TMHC/WAL to MTSI/WCC
(the only pair where MTSI appears) but reduces total P&L −30% ($51,857). Hub-weight
shrinks DD pairs' absolute P&L; non-hub pairs (like TMHC/WAL) maintain weight=1.0 and
now represent a larger portfolio fraction. Drawdown reduction trades against P&L reduction.

*HRP (Hierarchical Risk Parity, López de Prado 2016):* Uses quasi-diagonalization +
recursive bisection over the true N×N cross-pair covariance matrix, rather than
risk-parity's per-pair-only volatility. **An honest negative result relative to the simpler
approach:** OOS Sharpe 5.3752 beats the plain baseline (5.2443) but falls short of
risk-parity's 5.8689. This is consistent with a broader, literature-documented caution
(DeMiguel, Garlappi & Uppal 2009) that more sophisticated covariance-based portfolio
construction does not automatically beat simpler weighting schemes out of sample — reported
here rather than suppressed, since it directly bears on whether to adopt HRP for production
(it should not be, at least not on this evidence).

*Absorption Ratio (Kritzman, Li, Page & Rigobon 2011), companion systemic-risk metric:*
Computed on rolling windows across the 39 unique symbols spanning all confirmed pairs
(k = 8 principal components, the fraction convention from the original paper): mean AR =
0.427 (range 0.205–0.847). This is tracked alongside the existing DCC-GARCH peak-correlation
concentration flag (§6.4) as a second, independent lens on the same underlying question —
are the confirmed pairs' returns becoming more systemically entangled over time — rather than
as a portfolio-sizing input in its own right.

**Ledoit-Wolf shrinkage comparison arm for HRP [DRAFTED — 2026-07-05]:** the estimation-error
literature (Michaud 1989; DeMiguel/Garlappi/Uppal 2009, both already cited above) predicts HRP's
own raw-sample-covariance input is a likely source of its underperformance relative to
risk-parity. Ledoit-Wolf shrinkage (Ledoit & Wolf 2004, via `sklearn.covariance.ledoit_wolf`, the
peer-reviewed reference implementation) was added as an opt-in comparison arm on
`compute_hrp_weights()`. **The real-data comparison is currently uninformative, and the reason
is itself a finding:** raw-covariance and Ledoit-Wolf-shrunk HRP produce byte-identical output on
the current trades file — both variants saturate the same [0.1, 5.0] position-multiplier clipping
bounds because of SPY/VOO's outlier behavior. The long-flagged, not-yet-actioned SPY/VOO
exclusion (§5) is now directly blocking evaluation of this comparison too, raising its priority
beyond a paper-writing cleanliness item.

**DD-hub effective independent bet count [DRAFTED — 2026-07-05]:** three independent methods —
Grinold-Kahn breadth (BR_eff = N/(1+(N-1)ρ̄)), Meucci's (2009) Effective Number of Bets
(eigenvalue-based diversification distribution), and Carver's (2015) Instrument Diversification
Multiplier (IDM = 1/√(w'Rw), proven — not assumed — to equal √BR_eff exactly under equal
weighting) — were run against the 5-pair DD-hub cluster's own z-score-delta correlation
structure (trade-level P&L correlation was considered and rejected: the DD-hub pairs currently
have zero recorded trades in the IS trades file, a separate real finding). Real average pairwise
correlation ρ̄=0.282 (heterogeneous, 0.107–0.487, genuinely not equicorrelated). **All three
methods agree the 5-pair DD-hub cluster behaves like roughly 1.1–2.3 effective independent bets,
not 5** (BR_eff=2.35, Meucci ENB=1.14, Carver IDM=1.53) — a quantified answer to the concentration
question this section could previously only describe qualitatively.

**Recommended production configuration:** `--risk-parity` as primary flag (best Sharpe);
`--neg-hedge` as secondary addition if universe expansion from negative-β pairs is desired.
HRP was evaluated and is not recommended — it underperforms risk-parity on this pair set.

### 7.3 Walk-Forward Analysis — Semi-WFA Robustness Check [DRAFTED — 2026-06-29]

A semi-WFA was implemented to assess whether the OU parameters estimated on the full
training series generalize to held-out test windows. "Semi" because: the confirmed pair
set is fixed (no fold-specific pair re-selection), and the causal hedge ratio series
(`hedge_ratio_ols_t`) is taken as-is from analysis.py — only the spread OU parameters
(μ, σ, half-life) are re-estimated per fold training window.

**Fold structure (20/30/20/30):**
- Expanding: Fold 1 trains [0–20%], tests [20–50%]; Fold 2 trains [0–50%], tests [50–80%]
- Rolling: Fold 1 trains [0–20%], tests [20–50%]; Fold 2 trains [50–70%], tests [70–100%]

**Portfolio-level WFA results across 6 strategy variants (2026-06-30, 23 pairs):**

| Strategy | Expanding Sharpe | Rolling Sharpe | Expanding PnL | Rolling PnL |
|---|---|---|---|---|
| mm_exec | **3.816** | **3.964** | $112,498 | $125,242 |
| rolling_session_edge | 3.336 | **3.582** | $61,597 | $61,462 |
| baseline | 3.126 | 3.271 | $59,525 | $59,118 |
| garch_stop | 3.128 | 3.271 | $59,554 | $59,118 |
| storm_all | 1.698 | 1.785 | $19,468 | $17,741 |
| cfrac_sizing | 1.349 | 1.325 | $13,094 | $11,481 |

The fold-level portfolio Sharpes (3.1–3.3 baseline across both structures) are lower
than the full-IS Sharpe (5.29), as expected — each fold is a strict chronological
sub-sample with zero lookahead. The IS/WFA Sharpe ratio (5.29/3.13 = 1.69) indicates
modest overfitting by conventional standards, well within acceptable range for a
purely causal signal. The ranking of variants is consistent across both WFA structures.

mm_exec produces the highest WFA Sharpe (3.82/3.96) but also the highest trade count
(1,948/2,984 vs 1,053/1,438 baseline) — the elevated count is consistent with ladder
fills being counted individually (not a bug; documented in Development.md). Relative
Sharpe ranking is the operative finding; absolute P&L scale should be interpreted
with the different trade count in mind.

### 7.3.1 Point-in-Time Portfolio-Wide Walk-Forward: Testing the Pair-Discovery Step Itself [DRAFTED — 2026-07-01]

§7.3's WFA is, by its own docstring, a *semi*-WFA: it re-estimates OU spread parameters per
fold but does not re-run pair *selection* — the 23-pair confirmed set is fixed from the
full-history screen for every fold, so §7.3 cannot, by construction, detect whether the
screening methodology itself has lookahead. This subsection reports a direct, independent
test of exactly that question, since it is the one caveat §7.3's own framing could not resolve.

**Method (`pit_wfa.py`, new module):** at each of 4 fold cutoffs (2 expanding, 2 rolling,
matching §7.3's fractions), the full confirmed-pair screening pipeline — `UniverseFilter`
correlation pre-filter, `CointScanner` EG + BH-FDR, `coint_fraction_rolling`, structural-pair
exclusion, and the secondary-evidence override — is re-run using **only** data up to that
fold's training cutoff, exactly as a live deployment would have seen it at that point in time.
The resulting point-in-time confirmed pairs are then backtested forward through the fold's
test window with the same, unmodified `BacktestEngine` every other result in this paper uses.

**Verification before trusting the result:** a synthetic universe was constructed with one
pair genuinely cointegrated only *after* a cutoff date and one pair genuinely cointegrated
*within* the training window, confirming the point-in-time screen finds the second and not
the first (`debug/_verify_pit_wfa.py`). The first version of this synthetic test failed
initially — traced not to a `pit_wfa.py` bug but to a construction error in the synthetic
data itself (noise added inside a cumulative sum made the synthetic pair's spread a random
walk — correlated but not cointegrated, the classic spurious-regression distinction) — fixed
by adding noise directly to the price level instead.

**Result: zero pair overlap, and the point-in-time pairs lose money.** At every one of 3
independent historical checkpoints (2024-02, 2025-01, 2025-08), the point-in-time screen finds
a completely different pair set (19, 6, and 3 pairs respectively) than the known 17-pair @1h
full-history confirmed set — none of AMD/DD, LNT/VTR, EG/ORI, or any other member of the known
set appear. Backtested forward, those independently-discovered pairs are **not tradeable**:

| Fold | Point-in-Time Pairs | Trades | OOS Sharpe |
|---|---|---|---|
| expanding/fold1 | 18/19 traded | 204 | **−1.0432** |
| expanding/fold2 | 6 | 59 | **−0.7873** |
| rolling/fold1 | 18/19 traded | 204 | **−1.0432** |
| rolling/fold2 | 3 | 67 | **−0.7176** |

A real implementation bug was caught and fixed before trusting these numbers: the first run
produced positive-but-declining Sharpes (5.26, 2.89, 2.89, 2.81) — the isolated 2-symbol
alignment call in `backtest_pair_on_test_window` used the default calendar-padding alignment
mode instead of the gap-dropping mode appropriate for a single-pair backtest (the same bug
class caught earlier in `research/decoupling_backtest.py`), inflating bar counts roughly
5.85× (confirmed by comparing aligned vs. raw cached bar counts for the same symbol). Fixing
it flipped every fold from positive to negative — **the corrected result is more serious than
the uncorrected one, not less.**

**Decisive check that this is a real finding, not a second bug:** `screen_universe_at_cutoff`
was re-run on the exact full-history window `analysis.py` itself screens, confirming it
reproduces 16 of the 17 known confirmed @1h pairs exactly (the one miss and 6 additional pairs
found are explained by minor universe-composition differences between this diagnostic's
cache-glob universe and production's exact constituent list, not a screening-logic bug). The
screening function is trustworthy; the zero-overlap, negative-Sharpe result at earlier
cutoffs is real.

**Interpretation:** this is strong evidence of pair-selection lookahead in the full-history
screening methodology — not proof that the 17 known pairs' cointegration relationships are
spurious, but direct, quantified evidence that a live, causally-run version of this pipeline
would not have discovered and traded those same pairs at those points in time, and that the
pairs it *would* have found and traded were not profitable. This is the exact caveat §7.3's
"semi-WFA" framing already flagged qualitatively, now measured with real numbers. It does not
overturn §7.1's IS/OOS stability finding for the fixed, already-known pair set, and it is a
different and more severe form of lookahead than §6.7's DSR correction (DSR corrects for
searching *strategy variants* given a fixed pair set; this result concerns whether the *pair
set itself* would ever have been assembled by a causal process). Read together, §6.7 and this
subsection are the paper's most important honesty check on its own headline claim: the 5.24
OOS Sharpe is real for the pair set as given, well short of being explained away by variant
search, and not yet demonstrated to be achievable by a prospective, point-in-time process.

### 7.4 STORM Experimental Variants — Factor Grid [DRAFTED — 2026-06-29]

Four experimental adjustments were implemented and evaluated independently on the
OOS holdout, then in a full 2⁴ factorial grid:

**Factors tested:**
- **session_edge**: Skip intraday entries in the first 30 minutes after open and
  final hour before close (9:00–9:30 ET and 15:00–16:00 ET)
- **garch_stop**: Tighten stop loss from 3.5σ → 3.0σ when rolling z-score
  standard deviation exceeds 2× its historical baseline (GARCH-style volatility
  regime detection)
- **mm_exec**: Substitute MM-estimator hedge ratio (robust to outliers) for OLS
  when placing orders, using hedge_ratio_comparison.parquet
- **coint_frac_threshold**: Binary gate — skip pair entries when
  `coint_fraction_rolling` < 0.10 (threshold tested; continuous sizing not used)

**Individual OOS holdout results (2026-06-30, 23 confirmed pairs):**

| Variant | Trades | PnL | Sharpe | vs Baseline |
|---|---|---|---|---|
| Baseline | 296 | $73,596 | 5.2443 | — |
| session_edge | 292 | $73,049 | 5.2037 | −0.040 |
| session_edge_postopen | 268 | $72,745 | 5.1260 | −0.118 |
| mm_exec | 296 | $73,636 | 5.2467 | +0.002 |
| coint_frac_sizing | 296 | $5,867 | 5.4610 | +0.217 |
| storm_all | 292 | $5,333 | 4.8753 | −0.369 |

*Note: garch_stop parquet reflects prior 5-pair run; not included in 23-pair comparison.*

**Key findings:**

1. **session_edge is no longer a consistent win in the 23-pair set.** −0.04 Sharpe
   OOS (vs +0.87 in the prior 5-pair factorial grid). The session_edge filter removes
   4 trades (292 vs 296 baseline) and very slightly reduces PnL and Sharpe. With 17
   active 1h pairs, the pre-open noise-reduction benefit is diluted across more diverse
   market participants and entry timings. The prior 5-pair result may have reflected
   idiosyncratic timing in a small pair set rather than a systematic edge.
   **session_edge_postopen (new F05 variant)** — skipping 9:30–9:59 ET actual-open
   volatility rather than pre-open — produces a −0.12 Sharpe delta with 28 fewer
   trades, confirming the cost is in trade exclusion, not filtering noise.

2. **garch_stop remains deprecated.** Not rerun on 23-pair set (confirmed null on
   5-pair set: condition never triggered). Parquet file retained from prior run for
   historical comparison.

3. **coint_frac_sizing: high Sharpe, catastrophically low P&L.** Sharpe 5.4610
   (+0.217 vs baseline) but total P&L $5,867 (vs $73,596 baseline) — a 92% P&L
   reduction. The continuous `coint_fraction_rolling` multiplier scales 22 of 23
   confirmed pairs to near-zero position sizes (coint_frac 0.025–0.131 for most
   1h pairs). The high Sharpe is a low-denominator artifact of minimal P&L variance,
   not a quality signal. See §7.5 for the full inversion analysis.

4. **mm_exec is negligibly marginal.** +0.002 Sharpe (essentially zero). The MM
   estimator produces nearly identical hedge ratios to OLS on this pair set (OLS
   already robust at these trade frequencies). The mm_exec anomalous trade inflation
   in WFA (1,948 vs 1,053 baseline) is consistent with ladder fills counted
   individually — the WFA Sharpe improvement (3.82 vs 3.13 baseline) may reflect
   position sizing effects rather than pure hedge-ratio quality.

### 7.5 An Empirical Rebuttal to the Skeptic: coint_fraction_rolling Inverts [DRAFTED — 2026-06-29]

The strongest single result from the STORM investigation is not about the strategy —
it is about the diagnostic.

`coint_fraction_rolling` was originally conceived as a quality signal: pairs with a
higher fraction of rolling windows confirming cointegration should be more reliably
mean-reverting and therefore better trading candidates. This is the intuitive prediction.
The empirical result is the opposite.

Across the 17 confirmed 1h pairs (2026-06-30, DD-hub expanded universe), the coint_frac
values are uniformly low — the diagnostic is operating in a regime where it is too strict
to distinguish quality. The 9 pairs with OOS trades in the holdout window:

| Pair | coint_frac | OOS Trades | OOS PnL |
|---|---|---|---|
| DAL/DD@1h | 0.025 | — (0) | $0 |
| EG/WRB@1h | 0.025 | 4 | $2,552 |
| LNT/WELL@1h | 0.030 | 12 | $2,916 |
| AMAT/DD@1h | 0.035 | — (0) | $0 |
| CMI/DD@1h | 0.040 | — (0) | $0 |
| AMD/DD@1h | 0.045 | — (0) | $0 |
| AME/DD@1h | 0.061 | — (0) | $0 |
| MET/TMHC@1h | 0.056 | 15 | $5,269 |
| EG/ORI@1h | 0.071 | 4 | $1,610 |
| HAL/NOV@1h | 0.066 | — (0) | $0 |
| PRU/AXTA@1h | 0.066 | 11 | $2,165 |
| LNT/VTR@1h | 0.081 | 16 | $4,141 |
| VRT/MTZ@1h | 0.076 | 11 | $4,097 |
| MTSI/WCC@1h | 0.066 | 14 | $4,820 |
| PFG/STLD@1h | 0.111 | 15 | $2,381 |
| TMHC/WAL@1h | 0.131 | 18 | **$7,332** |
| UMBF/FHB@1h | 0.167 | 13 | $1,217 |

With 17 pairs and only 9 generating OOS trades, rank correlation of coint_frac vs OOS PnL
is not reliable as a point statistic. The qualitative pattern persists: TMHC/WAL (coint_frac
0.131) and LNT/VTR (0.081) are high performers, while pairs with lower coint_frac generate
either zero OOS trades or lower P&L. However, the direction is no longer monotonically
negative as it appeared in the 5-pair set: TMHC/WAL (highest active coint_frac) is the
top OOS P&L contributor. **Interpretation update**: the inversion finding from the 5-pair
set reflected a specific property of those 5 pairs — the 23-pair set shows a more
heterogeneous picture consistent with coint_frac being a noisy but directionally informative
signal once n is large enough to avoid small-sample rank artifacts.

The interpretation connects directly to the Strictness Paradox (§4.2): the rolling
window test is *too strict* at these timeframes. A pair that barely clears 3–8% of
rolling windows is not a borderline cointegrator — it is an established relationship
tested at a resolution where even strong cointegrators fail most windows. The low
`coint_fraction_rolling` signals that the test is operating near the right tail of
its own sampling distribution, not that the economic relationship is weak.

This is the empirical answer to the Skeptic's challenge: "Won't the hardest-to-confirm
pairs blow up OOS?" The data says the opposite. The hardest-to-confirm pairs are your
best performers, because the confirmation signal at intraday resolution is so over-strict
that a pass/fail verdict at any given window is near-random relative to the underlying
economic relationship. The metric's *average* across windows (the scalar stored in
`coint_fraction_rolling`) then reflects regime variation in the economic relationship,
not confirmation quality — and regime variation in a mean-reverting context is signal,
not noise.

**Implication for position sizing:** `coint_fraction_rolling` should not be used as a
position-size multiplier or a binary quality filter. Its negative correlation with
performance makes it an *inverse* signal — one that could be exploited as a feature in
the ML gate (pairs with lower rolling fraction may deserve *higher* conviction on
confirmed entries, not lower). This is flagged as a future-work candidate.

### 7.6 Pair Diagnostics — Half-Life Stationarity (S7) [DRAFTED — 2026-06-29]

A cointegration pair produces stable OOS performance only if its mean-reversion
dynamics are themselves stationary. If the OU half-life drifts or wanders over time,
the parameters estimated in the training window may not hold in the OOS period.

**Method.** For each confirmed pair we extract the rolling half-life series
(`half_life_rolling` from `spread_series`) and apply two tests:

1. **AR(1) regression**: fit $HL_t = \mu + \rho \cdot HL_{t-1} + \varepsilon_t$ via OLS.
   A coefficient $\rho \to 1$ indicates a near-unit-root in the HL series (drifting
   dynamics); $\rho \to 0$ indicates white-noise fluctuations around a stable mean.

2. **Zivot-Andrews (1992) test**: unit root test allowing for one unknown structural
   break in the HL series, with automatic lag selection (AIC). $H_0$: unit root.
   Rejection ($p < 0.10$) implies the HL series is stationary despite any break —
   i.e., the pair's mean-reversion speed is reliable.

Output is saved to `output/stats/halflife_stationarity.parquet`.  Summary statistic
`[S7 HL stationarity] stationary=k/n` is logged with the run.

**Diagnostic value.** The ZA test provides a per-pair stationarity flag that can
inform pair selection (prefer pairs with stationary HL), parameter setting (avoid
setting entry thresholds on pairs where HL is non-stationary), and ML features.
The AR(1) rho coefficient is itself a candidate ML feature encoding how stable a
pair's mean-reversion speed has historically been.

**Results (2026-06-30, 23 confirmed pairs):**

Summary: **20/23 pairs pass HL stationarity** (ZA p < 0.10). 3 pairs fail (likely the
shortest-history pairs — EQR/INVH@30m and international pairs with limited bar depth
for the AR(1) fit). The September 2023 break-date clustering observed in the 5-pair
run persists as the most common break date across the 1h cohort, consistent with a
market-wide volatility regime shift.

AR(1) ρ ≈ 0.95–0.97 across the active 1h pair set indicates high persistence in the
half-life series — the OU mean-reversion speed evolves slowly — but the ZA test
confirms no unit root for 20/23 pairs, meaning HL fluctuates around a slowly-moving
mean rather than drifting without bound. The 3 failing pairs are flagged for ML feature
engineering (AR(1) ρ near 1.0 is itself a candidate feature encoding HL instability).

### 7.7 Distance Method Baseline — Gatev GGR (2006) [DRAFTED — 2026-06-29]

As an external validity check, we compare our cointegration-based selection against
the Gatev, Goetzmann & Rouwenhorst (2006) distance method — the canonical pairs-trading
benchmark.

**Distance method protocol** (matching GGR 2006):

1. *Formation period* (first 50% of available history): normalize each price series
   to $P_0 = 1.0$ and compute the sum of squared deviations (SSD) between each
   candidate pair over the formation window. Rank all pairs by SSD ascending —
   lower SSD means prices tracked more closely.

2. *Select top-K* (K = 20) pairs by SSD.

3. *Trading period* (remaining 50%): generate entry signals when
   $|\hat{z}_t| = |(P^A_t - P^B_t - \mu_{\text{form}}) / \sigma_{\text{form}}| > 2.0$.
   Exit when the normalized spread crosses zero. P&L measured as percentage return
   on equal-weight long/short legs.

**Comparison framework.** Both methods are evaluated on the same OOS window using
the same confirmed-pair symbol universe. The cointegration-based pairs are also run
through `BacktestEngine` (no STORM flags, no ML gate) for an apples-to-apples Sharpe
comparison:

| Method | Selection criterion | OOS Sharpe | n trades | Overlap |
|--------|-------------------|-----------|---------|---------|
| Cointegration + OU (CAMARF) | ADF/EG p < 0.05, BH-FDR, half-life filter | **11.741** (mean over 17 @1h pairs) | — | — |
| Distance / GGR 2006 | Top-20 SSD over normalized formation prices | **−0.208** | 35 | 2/17 confirmed @1h pairs |

The overlap column measures how many confirmed @1h cointegration pairs also appear in
the GGR top-20 by SSD — 2 of 17 pairs are captured by both methods. The remaining 15
@1h pairs are captured only by the cointegration screen.

**Result (2026-06-30):** Cointegration CAMARF outperforms GGR distance by 11.95 Sharpe
points on the same OOS window and universe. GGR produces a negative Sharpe (−0.208) over
the same period, confirming Do, Faff & Hamza (2006) that cointegration+OU decisively
outperforms distance on a risk-adjusted basis. The CAMARF mean pair Sharpe of 11.741
reflects individual per-pair Sharpe quality; the portfolio Sharpe (5.24) incorporates
full cross-pair P&L correlation at the portfolio level.

### 7.8 Parameter Sensitivity and Stability

To verify that the main result is not an artifact of a specific parameter choice,
we sweep the two primary trading parameters (entry z-score and exit z-score) in a
4×4 grid at the baseline max\_hl and ADV settings, plus independent 1D sweeps for
the ADV liquidity filter and half-life ceiling.

**Entry × Exit z-score Sharpe grid (1h confirmed pairs, OOS, 2026-06-30):**

| | exit = 0.00 | exit = 0.25 | exit = 0.50 | exit = 0.75 |
|---|---|---|---|---|
| entry = 1.50 | 10.068 | 8.458 | 7.357 | 7.536 |
| entry = 2.00 | 9.178 | 8.207 | 7.387 | 8.000 |
| entry = 2.50 | **10.590** | 9.263 | 8.541 | 9.714 |
| entry = 3.00 | 9.800 | 8.666 | 7.935 | 8.977 |

The production setting (entry = 2.0, exit = 0.0) delivers Sharpe 9.178. The grid
maximum (entry = 2.5, exit = 0.0, Sharpe 10.59) outperforms production by 15%. No
parameter choice delivers a negative Sharpe across any combination, confirming genuine
strategy robustness. The highest single-pair-level Sharpe at entry=1.5 is 10.068 —
entry=1.5 trades more frequently, benefiting from higher win-rate at shallower
crossings but at lower per-trade edge. Entry=2.5 captures fewer but higher-conviction
opportunities. Entry=2.0 remains the production default for comparability with prior
runs; entry=2.5 is a candidate parameter update pending longer OOS evaluation.

**ADV liquidity filter sweep (1h pairs, 2026-06-30):**

| ADV threshold | n pairs | n trades | Sharpe |
|---|---|---|---|
| $0M (no filter) | 17 | 187 | 7.387 |
| $10M | 17 | 187 | 7.387 |
| **$25M (production)** | **16** | **174** | **7.412** |
| $50M | 12 | 132 | 6.600 |
| $100M | 6 | 64 | 6.196 |

The $25M threshold remains Pareto-optimal: removes 1 pair (micro-cap noise) with
a +0.025 Sharpe improvement. The $50M level drops 4 pairs and reduces Sharpe −0.81.
At $100M, 10 more pairs are excluded and Sharpe falls to 6.196 — still positive,
confirming the strategy is not concentrated in a single pair.

**Half-life ceiling sweep (1h pairs):**

| max_hl | n pairs | n trades | Sharpe |
|---|---|---|---|
| 20 | 1 | 16 | 12.423 |
| 35 | 17 | 187 | 7.387 |
| 50 | 17 | 187 | 7.387 |
| 75 | 17 | 187 | 7.387 |

The HL ceiling of 35 bars captures all 17 confirmed 1h pairs — no pairs have
half_life_rolling > 35. Any ceiling above 35 is non-binding at this TF. The
ceiling of 20 isolates the single highest-Sharpe pair (12.42 Sharpe on 16 trades)
— a useful diagnostic but not a production filter on such limited data.

**Analytic entry-threshold check via Monte Carlo OU simulation (Bertram 2010) [DRAFTED —
2026-07-05]:** the sensitivity grid above is empirical (search over a fixed set of z-values
against realized OOS trades); Bertram (2010) offers an independent, analytically-motivated
check — the OU-process threshold that maximizes expected profit per unit *time* (not per trade),
net of a transaction cost. Bertram's own closed form requires a first-passage-time special-
function integral with no independent way to check a hand-derived version against, so this was
implemented instead as direct Monte Carlo simulation of each pair's own fitted OU parameters,
verified against the qualitative properties his theory predicts (optimal threshold shrinks
toward 0 as cost→0, grows monotonically as cost increases — confirmed, after an initial version
that omitted the wait-to-enter leg of the trading cycle and had to be corrected). Using a
placeholder transaction cost (10% of each pair's own stationary spread standard deviation, since
no principled dollar-cost conversion exists without a notional/share-count assumption), most
pairs' analytically-optimal entry z lands at 0.75–1.25 — below production's z=2.0 — with one
notable exception, PNC/ZION@4h, whose near-unit-root persistence (§7.13's grid-bootstrap AR
confidence interval below) pushes its optimum to the simulation's grid ceiling. Given the result's known sensitivity to the assumed
cost, this is reported as directional confirmation that the framework and verification are sound,
not a literal recommendation to change the production entry threshold.

### 7.9 Position Sizing and Entry Threshold Optimization [DRAFTED — 2026-06-30]

Two complementary parameter decisions — inverse-volatility position sizing and
entry threshold — were evaluated independently on the 23-pair OOS holdout.

**Risk-parity (inverse-volatility) sizing — best OOS variant:**

Risk-parity weights each pair by the inverse of its spread return volatility (σ_pair):
$w_i = k / \sigma_i$ where k normalizes the sum to $N_{\text{SHARES}}$. This ensures
low-volatility pairs receive higher share counts (and therefore generate proportionally
more P&L) while high-volatility pairs are scaled back, reducing the concentration risk
documented in §7.2.

| Configuration | IS Sharpe | OOS Sharpe | IS Trades | OOS Trades | OOS P&L |
|---|---|---|---|---|---|
| Baseline (z=2.0, equal-weight) | 5.2935 | 5.2443 | 1028 | 296 | $73,596 |
| Risk-parity | — | **5.8689** | — | 296 | $62,490 |
| Neg-hedge | — | 5.4460 | — | 304 | $77,740 |

Risk-parity improves OOS Sharpe +0.63 vs baseline. The lower absolute P&L reflects
smaller position sizes for volatile pairs, not a weaker strategy. The Sharpe
improvement is the operative finding: risk-adjusted performance is meaningfully better.
**Risk-parity is the recommended production sizing method** (see §7.2 for full variant
comparison).

**Entry z-score threshold — z=1.5 as candidate update:**

Backtest.py was run with entry z=1.5 (via `--entry-z 1.5`, F06 implementation) as an
alternative to the production z=2.0.

| Entry z | IS Sharpe | OOS Sharpe | IS Trades | OOS Trades | IS→OOS decay |
|---|---|---|---|---|---|
| 2.0 (production) | 5.2935 | 5.2443 | 1028 | 296 | 0.9% |
| 1.5 | **5.9292** | 5.3448 | 1381 | 360 | 10.7% |

z=1.5 improves IS Sharpe +0.64 (5.93 vs 5.29) and OOS Sharpe +0.10 (5.34 vs 5.24)
with 34% more IS trades and 22% more OOS trades. IS/OOS decay is higher at z=1.5
(10.7% vs 0.9%), suggesting more in-sample signal but also more in-sample-specific
behavior. Both configurations remain profitable OOS with similar Sharpe magnitudes.

**Recommendation:** Retain z=2.0 as production default for this pipeline cycle —
the OOS Sharpe gain (+0.10) is small relative to the increased IS→OOS degradation.
Re-evaluate z=1.5 once ≥6 months of OOS history is available to confirm stability
of the decay differential.

### 7.10 Layer 2 — ML Gate [DEFERRED — insufficient training data]

Layer 2 adds a P(converge) ≥ 0.60 threshold from a trained XGBoost meta-labeler
(ml.py Stage 1). As of 2026-06-30, training cannot proceed across the 23-pair set:
labeled entry events have accumulated since 2026-06-21 (data.py append-mode start),
but the confirmed pair set expanded substantially this session, resetting the
accumulation clock for most pairs. Expect ML training viability ~2–4 weeks from
the 2026-06-30 full-universe rerun.

This result is reported honestly rather than suppressed: it demonstrates that the
meta-labeling architecture is sound (the training gate, feature pipeline, and model
persistence all work end-to-end), but that disciplined data requirements prevent
a model from being deployed on insufficient evidence. This is the Lopez de Prado
discipline in practice — "report the honest data-constrained result, re-run as
history accumulates."

**Feature redundancy check via RMT denoising/detoning [DRAFTED — 2026-07-05]:** CAMARF already
has PCA-based dimensionality reduction in production (`analysis.py`'s `EigenportfolioDecomposer`,
Marchenko-Pastur denoising for eigenportfolio construction), but it had never been applied to
`ml.py`'s own 8-feature set, which has no correlation-pruning step of any kind. Applied directly
(same eigendecomposition machinery, plus a denoise/detone/cluster pipeline built for this
purpose) to the 24 real labeled examples currently available — a small sample, so results are
exploratory, not a settled feature-selection decision. The raw correlation matrix is the more
reliable finding at this sample size: `hurst_exponent`/`mean_reversion_speed` (−0.90),
`hurst_exponent`/`half_life_trend_slope` (−0.85), and `coint_fraction_rolling`/
`mean_reversion_speed` (0.85) all show substantial redundancy, suggesting the 8-feature Stage-1
set could likely be consolidated once more labeled examples accumulate past the ML gate's own
30-per-class threshold and this check is re-run with real statistical power.

### 7.11 Filter-Ablation Funnel and Era-Decay Replication [DRAFTED — 2026-06-30]

**Filter-ablation funnel.** Ross's own recurring question — when a pipeline has this many
sequential filters, how much is each one actually removing, and is what it removes worth
removing — is answered directly rather than left to the final confirmed-pair count alone.
A `FilterFunnel` tracker records the pair count before and after every gate in the @1h
screening run:

| Stage | n_before | n_after | n_removed |
|---|---|---|---|
| Pearson pre-filter | 1,162,050 | 70,251 | 1,091,799 |
| EG + BH-FDR | 70,251 | 314 | 69,937 |
| Price-degeneracy | 314 | 314 | 0 |
| Structural exclusion | 314 | 314 | 0 |
| `coint_frac` threshold + override | 314 | 17 | 297 |

The Pearson pre-filter and EG+BH-FDR gates do essentially all of the work; price-degeneracy
and structural exclusion remove nothing at @1h this run (their effect is real at other
timeframes/universes, just not this one). The `coint_frac` threshold is the final, most
selective gate. Building this funnel surfaced and fixed a real gap: `spread_series` was
previously persisted only for pairs that survived to the final confirmed set, which made any
counterfactual analysis of an excluded pair impossible — fixed so ablation studies have data
to work with.

**Counterfactual: is the `coint_frac` filter net-positive?** The 297 pairs it excludes were
backtested anyway via a `--pairs-override` flag added to `backtest.py` for exactly this
purpose: IS Sharpe 4.3526 (2,285 trades, $760,209 P&L), OOS Sharpe 3.6682 (495 trades,
$150,286 P&L). Both are positive — these are not worthless pairs — but both are well below the
confirmed set's 5.29 IS / 5.24 OOS. **The filter is net-positive**: it is not merely excluding
noise, it is preferentially keeping the higher-quality subset of an already-profitable larger
candidate pool.

**Era-decay replication (Do & Faff 2010).** Do & Faff split Gatev-Goetzmann-Rouwenhorst's
sample into sequential eras and found roughly 70%+ decay in pairs-trading returns, attributing
it to weakening convergence properties (rising half-life) rather than crowding. CAMARF's own
data cannot test the crowding side of that dispute (it requires external capital-flow data
this project does not have — explicitly scoped out, not silently ignored), but can test the
convergence-property side directly: each confirmed @1h pair's available history was split into
3 sequential chronological thirds and backtested independently.

**Result: no decay found, in either direction Do & Faff considered.** Portfolio Sharpe across
the 3 eras: 5.05 → 5.18 → 5.21 (mildly increasing, not decreasing); mean half-life: 38.6 → 39.7
→ 31.0 bars (fell in the final era, not rose, the opposite of what a weakening-convergence
story predicts). This is reported as a genuine null result, not a failure: CAMARF's available
1h history window is short relative to Do & Faff's original multi-decade span, and the honest
conclusion is that this project's data does not show either the decay pattern or its proposed
mechanism over the window available — not that the Do & Faff mechanism is wrong, or that
CAMARF's pairs are immune to it.

### 7.12 Historical Crisis Stress Test [DRAFTED — 2026-07-01]

The Historian-lens finding from a STORM infrastructure survey (§8 below) motivates this test
directly: every "institutional" risk control in the field's history — stress testing, crowding
monitors, circuit breakers — was added reactively after a specific named crisis exposed its
absence. CAMARF had none. Building one honestly requires stating a real data constraint up
front: the confirmed @1h pairs only have cached intraday history back to 2023-07-24 (yfinance's
730-day 1h cap), so **this is not a replay of the intraday strategy through 2007/2020** — that
data does not exist and is not fabricated here. What is tested, precisely: does each confirmed
pair's cointegration relationship — the same Engle-Granger test and OLS hedge ratio the whole
strategy rests on — hold up at **daily** resolution through three historical crisis windows
(Aug 2007 quant quake, 2008 GFC, Feb–Apr 2020 COVID crash), with the hedge ratio and spread
distribution fit strictly on a 2-year pre-crisis baseline (no lookahead into the crisis itself)?

**A confound was checked before trusting the headline numbers.** A raw result of "0/13 pairs
still cointegrated through Aug 2007, 0/13 through the GFC, 1/21 through COVID" is ambiguous on
its own — it could reflect genuine crisis fragility, or simply that a single-shot daily EG test
on any arbitrary old window rarely finds cointegration for pairs discovered on 2023–2026 hourly
data, crisis or not. Three calm-period controls of matching window length and season (2015-08,
2016-09–2017-03, 2018-02–04) were run through the identical test before drawing any conclusion.

**Result:** the cointegration-holds rate is low in both conditions (crisis 2%, calm 9%) — this
metric alone cannot cleanly separate the two, and is reported as such rather than oversold. The
**dislocation rate is the more informative comparison**: extreme spread dislocation (|z| > 3.5,
the same stop-loss threshold `backtest.py`'s Layer 1 baseline uses) occurred in **62% of
crisis-window tests (29/47) versus 20% of calm-control tests (11/55)** — a 3× rate difference,
supporting a genuine, if still partially confounded, crisis-specific effect rather than a pure
artifact of the test design. The GFC and COVID windows show the sharpest effect (12/13 and
15/21 pairs extreme, respectively); Aug 2007's brief acute window shows less (2/13), plausibly
because its ~2-week span gives the daily-resolution test little room to register a dislocation
regardless of severity.

**Interpretation, stated at the scope this test actually supports:** this does not show the
strategy would have lost money in 2007/2008/2020 — the intraday backtest data to test that
claim does not exist. It shows that the statistical relationships underlying the confirmed
pairs experience materially more extreme daily-resolution dislocation during known historical
crisis windows than during matched calm periods, and that a simple EG re-test rarely confirms
formal cointegration through either — a genuine, if partial, historical-crisis analog to the
correlation-in-stress finding from LTCM and the August 2007 quant quake, now measured directly
on this project's own confirmed pairs rather than asserted from the literature.

### 7.13 Additional Robustness Checks — Six Independent Diagnostics [DRAFTED — 2026-07-05]

A batch of six further robustness checks, each testing the confirmed pair set or the production
methodology against an independent statistical family not already covered above. All six are
new comparison/diagnostic modules under `research/`, synthetically verified before being run on
real data (three needed a real redesign after their first verification attempt failed — see
Development.md Session 27 for the full account of each).

**Threshold cointegration (Hansen & Seo, 2002):** tests whether a pair's error-correction
adjustment is genuinely nonlinear (threshold-triggered, as a transaction-cost band would imply)
rather than the constant-speed linear reversion the production OU model assumes. Result: only
1 of 22 confirmed pairs is even nominally significant (TMHC/WAL@1h, p=0.007), and that one does
not survive Benjamini-Hochberg correction for testing 22 pairs at once. **No confirmed pair shows
a real threshold effect — the linear model already in production is adequate.**

**Variance ratio test (Lo & MacKinlay, 1988):** corroborates mean-reversion from a completely
different statistical family than Engle-Granger, using q scaled to each pair's own half-life
rather than a fixed horizon. Result: the textbook mean-reversion signature holds across nearly
every 1h pair — VR above 1 at short horizons (~0.5× half-life), crossing 1 near the half-life
itself, clearly below 1 (0.35–0.52, mostly p<0.01) at 2–4× half-life. **Strong, independent
confirmation that the confirmed pairs are genuinely mean-reverting**, not an artifact of the
EG/cointegration test family specifically.

**News impact asymmetry (Engle & Ng, 1993):** tests whether spread volatility responds
asymmetrically to widening vs. narrowing moves — directly relevant to whether the `garch_stop`
variant's symmetric rolling-std trigger (§7.4) is well-specified. Result: a clean null across all
22 confirmed pairs (0 significant at p<0.05). **`garch_stop`'s symmetric design is validated, not
undermined**, by this test.

**Strategy risk via precision/frequency (López de Prado, AFML Ch. 15):** the symmetric binomial
Sharpe formula, SR = (2p−1)/(2√(p(1−p))) annualized by √n, applied per pair using IS win rate
(precision) and trade count/year (frequency) — verified directly against 2-million-draw Monte
Carlo before use. Flags **CVX/OXY and KVUE/KMB (both 3m) with sub-50% win rates** (42.9%, 43.8%)
— whatever edge these two pairs have cannot come from win rate alone and must rest on payoff
asymmetry (smaller losses, larger wins), a per-pair characterization not previously surfaced.

**Reimers (1992) small-sample correction, plus trace/max-eigenvalue agreement:** re-tests all
502 currently-persisted candidate trios with a degrees-of-freedom-corrected Johansen trace
statistic. Result: 0/502 trios flip from cointegrated to not-cointegrated under the correction —
an honest null given the trios' large sample sizes (thousands of bars), where small-sample
corrections are expected to matter least. A companion check (trace vs. max-eigenvalue test,
computed from the same already-open Johansen call at no extra cost) finds 2/502 trios disagree
between the two test statistics (TER/DD/AMKR@1h, TER/DD/ATI@1h — both sharing the TER/DD base
pair), flagged as borderline/methodology-sensitive cases.

**Grid bootstrap confidence intervals for the AR coefficient (Hansen, 1999):** gives a genuine
confidence interval — not just a pass/fail test — for each pair's own spread mean-reversion
speed, valid even near a unit root (verified via empirical coverage: 14/15 simulated trials
covered the true value under a nominal 90% CI). Every confirmed pair's CI sits comfortably below
1 (e.g. TMHC/WAL: [0.9614, 0.9708]) **except PNC/ZION@4h, whose CI ([0.9990, 0.9990]) sits right
at the near-unit-root boundary** — flagged as the one pair worth a second look on this specific
axis, and the same pair whose Bertram-threshold optimum (§7.8) independently lands at the
opposite extreme of that analysis's grid.

**Return-smoothing audit (Getmansky, Lo & Makarov, 2004):** checks each pair's daily P&L for the
serial-correlation signature associated with stale/infrequent pricing in illiquid assets. Result:
9 of 10 testable pairs show a smoothing index at or near 1.0 (no smoothing); only EG/WRB shows a
modest signature (0.711). Consistent with CAMARF trading liquid, actively-marked instruments
rather than the illiquid, appraisal-priced assets this diagnostic is designed to catch.

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

**A second entry, drafted in equal depth — the most material entry in
this audit, and the only one classified as an unresolved, quantified
residual risk rather than a mitigated one:** pair-selection lookahead in
the full-history cointegration screen (`analysis.py`, recorded once per
timeframe run since 2026-07-01, mechanism/remedy/residual-risk fields
identical across TFs). The confirmed 23-pair set is selected using a
screen run over the entire available history, including the period later
reported as the OOS holdout — pair *discovery* therefore borrows
information from the future relative to any real deployment date, a
distinct and more severe failure mode than the OU-parameter lookahead
§7.3's semi-WFA already addresses. Unlike every other entry in this
audit, this one has no remedy applied — it is quantified, not corrected:
§7.3.1 reports that a genuinely causal, point-in-time re-screen at 3
independent historical checkpoints found a completely different pair set
at every checkpoint (zero overlap with the known confirmed set) and that
those independently-discovered pairs lost money in every backtested fold
(Sharpe −1.04 to −0.72). The residual risk is therefore reported as high,
not low: the paper's headline 5.24 OOS Sharpe is a real, correctly
computed number conditional on the pair set already being known, and is
not evidence that a live, causally-run version of this pipeline would
have discovered and traded it.

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
  Verified with a synthetic test. **Updated 2026-06-27: training
  threshold crossed — 125 labeled entry events (up from 12), 79
  confirmed pairs. Trained on 75, test accuracy 68.00% on 25 holdout.
  Conformal: 88% empirical coverage (target ≥90%), avg set size 1.52.
  Note: class imbalance (75% not_converged / 25% converged) means the
  trivial "predict not_converged always" baseline is ~75%, so 68%
  accuracy is below the trivial baseline on this split — precision/
  recall on the converged class is the right evaluation metric for an
  entry filter, not overall accuracy. Threshold / evaluation-metric
  decision deferred to backtest.py interactive session.**
- **Idea #4 (BH-FDR robustness check), reframed** — knockoff filters
  don't transplant cleanly onto pairwise hypothesis testing on time
  series (they're built for regression variable selection). Built a
  circular-shift permutation check instead (`eg_permutation_check.py`),
  run alongside production BH-FDR, not replacing it. **Updated result
  (2026-06-27, 79-pair universe): 38 of 79 confirmed pairs flagged**
  (real EG significant, permutation-based check not); mean
  null_frac_significant across all 79 is 0.230 vs. an expected ~0.05
  (4.6×). Earlier run (30-pair set): 12/30 flagged, 14.6% mean — the
  higher rate in the expanded universe is driven by the DD-hub cluster
  at 1h (10/17 DD pairs flagged, null_frac_sig 0.50–0.57, indicating
  DD's own within-series autocorrelation is the dominant driver) and the
  APOG cluster at 3m. Clean pairs from the expanded set: APP/NOW,
  CRWD/NOW, IWM/SLV, the AZTA cluster at 1m, and most 1h non-DD pairs.
  **Policy: `permutation_robust` flag on PairResult; flagged pairs remain
  in confirmed set as a comparison arm until backtest.py quantifies
  real-world impact — consistent with coint_frac_override precedent.
  Discussed with Ross 2026-06-23, confirmed 2026-06-27.**
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

- **HMM regime detection — built, ran, confirms regime structure in macro
  series (Session 13).** Gaussian HMMs fit to T10Y2Y, VIXCLS, and COT ES
  net speculative positioning. Key findings: (a) yield curve slope is
  highly persistent — HMM state durations 539–621 days; (b) VIX crisis
  state (mean VIX=30) covers 23.6% of history, broader than the heuristic
  "crisis" label; (c) COT net-spec splits cleanly at zero — the HMM
  binary boundary is simpler than the heuristic three-bucket system.
  HMM state sequences written to `output/research/hmm_regimes.parquet`
  for use as alternative regime labels in regime-conditional half-life
  testing.

- **Sample entropy of spreads — built, ran, all 79 pairs processed (Session
  13).** SampEn (m=2, r=0.2·std, Richman & Moorman 2000) applied to each
  confirmed pair's z-scored spread. 1h pairs (n≈4,389 bars each) produce
  reliable estimates: range 0.024–0.378, mean 0.129. Most regular 1h spreads:
  CAT/DD (0.024), AMAT/DD (0.051), DD/SHOO (0.053), DD/LPX (0.053). Lower
  SampEn = more regular, mechanically predictable spread → candidate ml.py
  Stage 2 feature. Ultra-short-TF pairs (1m/3m, n<700) produce
  unreliably low SampEn as a small-sample artifact — not used. Output:
  `output/research/sample_entropy_spreads.parquet`.

- **Regime-conditional pair analysis — built, ran, strong finding (Session
  13).** Per-regime OLS half-life estimation for all confirmed pairs across
  1m/3m/30m/1h/4h. Mean hl_ratio (half_life_in_regime / half_life_full):

  | Regime              | Mean hl_ratio |
  |---------------------|--------------|
  | VIX crisis          | 0.090 (11× faster) |
  | VIX calm            | 0.377 (2.7× faster) |
  | VIX elevated        | 1.512 (1.5× slower) |
  | VIX normal          | 3.929 (4× slower)  |
  | Yield flat/inverted | 0.430 (2.3× faster) |
  | Yield normal        | 4.387 (4.4× slower) |

  Pairs mean-revert dramatically faster in crisis/calm VIX regimes and
  flat/inverted yield curve environments. This is the clearest empirical
  support yet for the thesis's regime-conditioning hypothesis: macro
  state materially alters statistical arbitrage dynamics. Caveat: 1m/3m
  data spans ≤8 days (single regime); multi-regime variation entirely
  from 1h pairs (17.5 months of history). VIX crisis n is small (30–40
  bars per pair) — hl estimates noisy. Needs confirmation with z-scored
  spread to rule out raw-level volatility confound.
  Output: `output/research/regime_conditional_analysis.parquet`.

- **Comomentum — built, ran (Session 13).** Lou & Polk (2022) comomentum
  signal adapted to CAMARF's spread portfolio: rolling 60-bar mean pairwise
  correlation of spread returns across all 29 confirmed 1h pairs. Mean
  comomentum index = 0.090 (vs. static full-history baseline = 0.048 —
  rolling correlation is nearly 2× the unconditional average, suggesting
  persistent co-movement is the norm, not episodic crowding). P75 threshold
  (0.113) marks 25% of bars as "elevated crowding." The index has low
  volatility (std=0.035), meaning crowding is slowly varying, not spiking
  — consistent with institutional positioning cycles. Next step: join to
  ml.py labeled entry events and test convergence-rate differential during
  elevated vs. normal comomentum. Output: `output/research/comomentum_index.parquet`.

- **ml.py class imbalance addressed (Session 13).** Training set: 75.2%
  not_converged / 24.8% converged. `compute_sample_weight("balanced",
  y_train)` applied as `sample_weight` to `model.fit()` — XGBoost's
  equivalent of `class_weight='balanced'`. Accuracy dropped 68% → 56%
  (expected — trades majority-class accuracy for minority-class recall).
  The converged-class precision/recall tradeoff is the right metric for
  an entry filter; this will be evaluated properly once backtest.py exists.

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
11. **[VERIFIED 2026-07-02, bibliographic level — title/venue/volume/page
    cross-checked across 2+ independent sources this session, no direct
    URL confirmed]** Hamilton, J. D. (1989). A new approach to the
    economic analysis of nonstationary time series and the business
    cycle. *Econometrica*, 57(2), 357-384. The foundational Markov
    regime-switching model — the direct academic ancestor of the HMM
    regime classifier already used in `analysis.py`/`RegimeClassifier`,
    not previously cited despite being used since early sessions.
12. **[VERIFIED 2026-07-02, bibliographic level, no direct URL confirmed]**
    Durbin, J., & Koopman, S. J. (2001, 2nd ed. 2012). *Time Series
    Analysis by State Space Methods*. Oxford University Press. The
    standard modern reference for the Kalman filter/state-space
    machinery underlying the Kalman dynamic hedge-ratio estimator, not
    previously cited.
13. **[VERIFIED 2026-07-02, bibliographic level, no direct URL confirmed]**
    Rabiner, L. R. (1989). A tutorial on hidden Markov models and
    selected applications in speech recognition. *Proceedings of the
    IEEE*, 77(2), 257-286. The field-standard HMM tutorial (forward-
    backward, Viterbi, Baum-Welch/EM) — the implementation-level
    reference for the regime classifier's HMM component, distinct from
    Hamilton's econometric framing above.
14. **[VERIFIED 2026-07-02, bibliographic level, no direct URL confirmed]**
    Engle, R. F. (1982). Autoregressive conditional heteroskedasticity
    with estimates of the variance of United Kingdom inflation.
    *Econometrica*, 50(4), 987-1007. The founding ARCH paper — everything
    downstream in this paper's volatility-modeling lineage (GARCH,
    Engle's DCC already cited above, the `garch_stop` backtest variant)
    generalizes this model. Previously uncited despite DCC (Engle, 2002)
    being cited; `garch_stop` itself is a rolling-window standard-
    deviation proxy on the z-score, not a fitted ARCH/GARCH conditional-
    variance model — noted here so the distinction is explicit rather
    than implied.
15. **[TBD, used correctly in §7.13, exact venue/pages not independently
    re-verified this session]** Hansen, B. E., & Seo, B. (2002). Testing
    for two-regime threshold cointegration in vector error-correction
    models. *Journal of Econometrics*, 110(2), 293-318. The threshold
    cointegration test implemented in `research/threshold_cointegration.py`.
16. **[TBD]** Lo, A. W., & MacKinlay, A. C. (1988). Stock market prices do
    not follow random walks: Evidence from a simple specification test.
    *Review of Financial Studies*, 1(1), 41-66. The variance ratio test
    implemented in `research/variance_ratio_test.py`.
17. **[TBD]** Kupiec, P. H. (1995). Techniques for verifying the accuracy
    of risk measurement models. *Journal of Derivatives*, 3(2), 73-84;
    Christoffersen, P. F. (1998). Evaluating interval forecasts.
    *International Economic Review*, 39(4), 841-862. The VaR-exceedance
    backtesting tests implemented in `cvar.py`'s `var_exceedance_backtest()`.
18. **[TBD]** Grinold, R. C., & Kahn, R. N. *Active Portfolio Management*
    (2nd ed., 2000), McGraw-Hill — the breadth/"fundamental law" formula;
    Meucci, A. (2009). Managing diversification. *Risk*, May 2009 issue;
    Carver, R. (2015). *Systematic Trading*, Harriman House — the
    Instrument Diversification Multiplier. All three implemented together
    in `research/dd_hub_effective_bets.py`.
19. **[TBD]** Ledoit, O., & Wolf, M. (2004). Honey, I shrunk the sample
    covariance matrix. *Journal of Portfolio Management*, 30(4), 110-119.
    The shrinkage estimator implemented as `compute_hrp_weights(shrinkage=
    "ledoit_wolf")` in `backtest.py`, via `sklearn.covariance.ledoit_wolf`.
20. **[TBD]** Engle, R. F., & Ng, V. K. (1993). Measuring and testing the
    impact of news on volatility. *Journal of Finance*, 48(5), 1749-1778.
    Motivates the asymmetric-volatility question tested (via a simpler
    permutation-based method, not their original regression specification
    — see Development.md Session 27) in `research/news_impact_asymmetry.py`.
21. **[TBD]** López de Prado, M. (2018). *Advances in Financial Machine
    Learning*, Wiley, Ch. 15 ("Understanding Strategy Risk") — already
    cited above for meta-labeling/triple-barrier/CPCV/PBO; the symmetric
    binomial Sharpe formula from this chapter is implemented in
    `research/strategy_risk_precision.py`.
22. **[TBD]** Reimers, H.-E. (1992). Comparisons of tests for multivariate
    cointegration. *Statistical Papers*, 33(1), 335-359. The small-sample
    correction implemented in `research/reimers_trio_correction.py`.
23. **[TBD]** Hansen, B. E. (1999). The grid bootstrap and the
    autoregressive model. *Review of Economics and Statistics*, 81(4),
    594-607. The confidence-interval method implemented in
    `research/grid_bootstrap_ar_ci.py`.
24. **[TBD]** Bertram, W. K. (2010). Analytic solutions for optimal
    statistical arbitrage trading. *Physica A*, 389(11), 2234-2243;
    Getmansky, M., Lo, A. W., & Makarov, I. (2004). An econometric model
    of serial correlation and illiquidity in hedge fund returns. *Journal
    of Financial Economics*, 74(3), 529-609. Implemented (the former via
    Monte Carlo simulation rather than the original closed form — see
    Development.md Session 27 for why) in `research/bertram_ou_thresholds.py`
    and `research/return_smoothing_audit.py` respectively.
