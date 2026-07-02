# CAMARF vs. Institutional-Grade Quant Infrastructure — STORM-Grounded Gap Analysis

**Method:** 6 parallel STORM research interviews (Basic fact writer, Practitioner,
Academic, Skeptic, Economist/Incentives, Historian), 3 rounds each, ~45 unique
grounded sources, run 2026-07-01. Used here as an external yardstick — not
CAMARF's own opinion of itself — to rate every part of the project and locate
real gaps. Ratings follow CLAUDE.md rule 7: honest, not inflated, and every
"Strong" or "Missing" below is argued from evidence, not asserted.

**Rating scale:** `Missing` (doesn't exist) · `Partial` (exists but with a
material, named limitation) · `Adequate` (does its job, matches practitioner
norms for a project this size) · `Strong` (matches or exceeds what real funds
do, with evidence).

**Correction (2026-07-01, post-review):** the ratings below for DSR, HRP,
Absorption Ratio, sqrt-impact, filter-ablation funnel, era-decay replication,
and reproduce.py provenance were written without first checking the repo —
all of these were already built, verified, and run for real in the 6/30
evening session (commit `7a85220f`), before this document's own STORM
research was dispatched. Rows below are corrected inline rather than
rewritten wholesale, so the original (wrong) reasoning stays visible as a
record of the mistake. See §3 for the corrected, current gap list.

---

## 1. What the research actually established (condensed)

**Universal agreement across all 6 personas:** naive backtesting (single-path
walk-forward, uncorrected Sharpe ratios, k-fold CV on time series) is
*statistically invalid* for financial data because it ignores label overlap,
non-stationarity, and multiple-testing inflation — this is not contested by
anyone, including the Skeptic. The corrective toolkit (purged/embargoed CV,
CPCV, Deflated Sharpe Ratio, PBO) is peer-reviewed and mathematically
specified, chiefly by Bailey, Borwein, López de Prado & Zhu (2014–2018).

**The load-bearing contradiction:** the Academic and Basic-fact lenses treat
CPCV/DSR as the correctness standard; the Practitioner and Skeptic push back
hard — real fund engineering time is dominated by unglamorous data-pipeline
work (point-in-time joins, corporate actions, identifier mastering — reported
at ~80% of a quant developer's real time [Practitioner:1]), and even
CPCV/DSR-disciplined shops still get blindsided by *regime-dependent* failures
(Aug. 2007 Quant Quake, 2008 VaR failures) that no amount of additional
statistical correction would have caught, because the anomalous regime simply
wasn't in the calibration window [Skeptic:5,6,7]. **Both are right, and they
are not actually in conflict — DSR/CPCV fix a static-model-validity problem;
regime risk is a different, dynamic problem CAMARF already partially
addresses via HMM regime detection and structural-break testing.**

**The Historian's key finding, directly relevant to CAMARF's process:** every
item on the "institutional checklist" was added reactively after a named
failure exposed its absence (LTCM 1998 → stress testing/liquidity risk;
Aug. 2007 → crowding/capacity monitoring; Flash Crash 2010 → execution risk
limits; Knight Capital 2012 → kill switches/deployment discipline). None of it
was designed proactively. This matters for prioritization below: CAMARF
should adopt the *statistical-validity* half of the checklist now (it's cheap
and already argued-for by the pit_wfa.py finding), and can legitimately defer
the *operational* half (real-time monitoring, kill switches, compliance) since
those exist to solve problems — client capital, live execution, career risk —
that a solo research project doesn't yet have [Skeptic:9].

**The Economist's key finding:** "institutional-grade" operational
infrastructure (formal risk departments, compliance, model governance under
SR 11-7) exists at funds almost entirely because of *regulatory or
LP-due-diligence pressure*, not because it improves research validity — hedge
funds face no SR 11-7-style mandate at all [Economist:12,14]. This directly
supports treating compliance/governance/live-monitoring as **out of scope**
for CAMARF, not merely deferred — building them would be cargo-culting a
fund's incentive structure onto a project that has none of the underlying
pressures.

**The Skeptic's sharpest, most CAMARF-relevant finding:** DeMiguel, Garlappi &
Uppal (2009) — across 14 optimized portfolio models and 7 real datasets, *none*
consistently beat naive 1/N equal-weight out-of-sample, and the estimation
window needed for mean-variance optimization to reliably beat 1/N is
~3,000–6,000 months of data, longer than available market history
[Skeptic:10]. This is a direct caution against over-investing in
Black-Litterman/HRP sophistication expecting a free lunch — any such addition
to CAMARF needs to be benchmarked honestly against equal-weight and
risk_parity, not assumed superior.

---

## 2. Component-by-component rating

### Data & universe infrastructure

| Component | Rating | Reasoning |
|---|---|---|
| Point-in-time data discipline (general) | **Partial** | `data.py` fetches current yfinance history; there is no point-in-time *fundamentals* layer (N/A — CAMARF doesn't trade on fundamentals) but the **pit_wfa.py finding is direct, quantified evidence CAMARF's pair-selection process itself has point-in-time lookahead** — the exact failure mode the Academic/Basic lenses flag as the field's core validity problem. This is the single most important, already-discovered gap in this whole exercise. |
| Survivorship-bias handling | **Partial** | Universe is current-constituent-only (documented bias, per rule 6) — matches the "~75% of delisted North American names missing" pattern the Practitioner cites [2] as a known, common, *not uniquely CAMARF* limitation. Handled honestly (disclosed), not handled structurally (not fixed). |
| Corporate actions handling | **Partial** | yfinance auto-adjusts splits/dividends at the source, so the naive-adjustment failure mode the Basic-fact lens describes [3] doesn't bite directly — but there's no dedicated reconciliation/audit layer confirming yfinance's adjustment is correct, and `corporate_actions.py` is already on CAMARF's own backlog as "planned, not built." |
| Data quality / gap handling (GapFlag) | **Strong** | Six-code GapFlag system with DATA_GAP masking in EG/correlation is more granular than what most of the retrieved sources describe as standard practice — this is a genuine CAMARF strength, not just adequate. |
| Universe construction robustness | **Adequate** | Retry logic for flaky scrapers, cache-empty-write guard, size sanity-check guard — matches the "validation layers" pattern the Practitioner describes as necessary [1] (cross-source consistency, spike detection equivalents exist in spirit via the guards). |

### Statistical methodology

| Component | Rating | Reasoning |
|---|---|---|
| Pair discovery (correlation + EG cointegration) | **Adequate** | Standard, correctly-implemented methodology; not novel but not wrong. |
| Multiple-testing correction within a TF run (BH-FDR) | **Adequate** | Applied at the per-run pair-confirmation stage — good — but this is a *narrower* correction than the field's real ask (see DSR gap below). |
| Structural break / regime detection (Zivot-Andrews, HMM) | **Adequate** | Directly addresses the Historian's and Skeptic's "regime-dependent failure" concern (Aug 2007, 2008 VaR) better than most retrieved sources describe smaller shops doing. |
| Factor risk decomposition | **Partial** | `EigenportfolioDecomposer` (PCA) + DCC-GARCH rolling correlation exist and are genuinely useful, but this is not a full Barra-style attributed factor model (style/industry/country exposures) — that's a legitimate gap, though the Economist confirms building one from scratch is *not* worth it even for real funds below mega-fund scale [Economist:6] (buy-not-build category). Recommendation below is *not* "build a Barra clone." |
| **Combinatorial Purged CV / DSR / PBO across the many STORM variants and grid runs** | **CORRECTED: Adequate, already built** (was wrongly marked Missing) | `deflated_sharpe.py` + `trial_registry.py` already exist and were run for real on 6/30: IS z=11.02, OOS z=6.48 after correcting for 14 backtest configurations. Both remain highly significant post-correction. Now written into PAPER.md §6.7. No CPCV/PBO estimate exists yet — that narrower piece is a legitimate, lower-priority remaining gap. |
| True point-in-time walk-forward (vs. semi-WFA) | **Partial → now Adequate-in-diagnosis** | `wfa.py`'s pair-selection lookahead is real (already quantified via `pit_wfa.py`: zero pair overlap across 3 independent point-in-time checkpoints, backtested negative). The diagnostic tool now exists and is verified; what's missing is a decision on how this reshapes the headline claim (separate pending item, not a new gap this exercise surfaces). |

### Portfolio construction

| Component | Rating | Reasoning |
|---|---|---|
| Position sizing (equal-weight, risk_parity) | **Adequate** | risk_parity's +0.63 OOS Sharpe improvement is a real, tested result. |
| Kelly sizing | **Partial** | Documented lookahead bias (rule 6) — honestly disclosed, not structurally fixed; this is the correct interim state per CLAUDE.md's bias-documentation rule, not a defect. |
| Advanced portfolio construction (HRP / Black-Litterman) | **CORRECTED: Adequate, already built and honestly benchmarked** (was wrongly marked Missing) | `compute_hrp_weights()` + `--hrp-weight` CLI flag already exist and were run for real: OOS Sharpe 5.3752, beats plain baseline (5.2443) but loses to risk-parity (5.8689) — reported as an honest negative result, not suppressed, now in PAPER.md §7.2. This independently validates the Skeptic's DeMiguel et al. caution: the more sophisticated covariance-based approach did not beat the simpler one here. Black-Litterman remains genuinely unbuilt, but is lower-priority than this exercise assumed given HRP's own result. |

### Execution & risk

| Component | Rating | Reasoning |
|---|---|---|
| Transaction cost / slippage modeling | **CORRECTED: Adequate, sqrt-impact already built** (was wrongly marked as needing Phase 2b) | Flat-bps linear cost model remains the default, but a square-root/Almgren-Chriss-style concave impact variant (`backtest.py --storm-sqrt-impact`) already exists and is synthetically verified (`debug/_verify_sqrt_impact_cost.py`). No live TCA feedback loop — correctly out of scope, this project doesn't route real orders. |
| VaR/CVaR reporting | **Missing** | No portfolio-level VaR/CVaR is computed anywhere in the pipeline. Given the Skeptic's own finding that VaR badly failed institutions in 2008 due to normal-distribution/tail-risk assumptions [Skeptic:7], this is a **legitimately low-priority gap** — CVaR/Expected Shortfall would be more defensible than VaR if built, but neither is urgent for a backtest-only project without live capital at risk. |
| Capacity / crowding analysis | **Missing (correctly deferred)** | Already logged as a design-only backlog item (existing plan Phase 6) pending a methodology discussion. This STORM pass reinforces that the *external* half (detecting rival positioning) is fundamentally infeasible per the Historian/Economist (13F filings too lagged, prime-broker data unavailable to a solo researcher) — only an internal decay-vs-baseline proxy is buildable, which is already the scoped plan. |
| Stress testing / scenario analysis | **Missing** | No formal historical-scenario replay (1987 crash, 2007 quant quake analog, 2020 COVID vol) against CAMARF's own confirmed pairs. Partially substituted by regime detection + structural-break testing, but not the same thing — a real, if lower-urgency, gap. |
| Live/paper trading infrastructure, real-time monitoring, kill switches | **Out of scope, correctly** | CAMARF is explicitly a research framework, not a live trading system (separate futures project is the live system). Building this would solve a problem CAMARF doesn't have — direct Economist/Skeptic conclusion. |
| Model risk governance (SR 11-7-style independent validation) | **Out of scope, correctly** | No regulatory or LP pressure exists for a solo research project; CLAUDE.md's own verify-before-claiming-done discipline already substitutes for this at the appropriate scale. |
| Compliance / audit trails | **Out of scope, correctly** | Same reasoning — this exists at funds because of client capital and regulation, neither of which applies here. |

### Process, ML, and documentation

| Component | Rating | Reasoning |
|---|---|---|
| ML / feature engineering (ml.py) | **Partial** | Stage 1 meta-labeler exists; Stage 2 + SHAP explicitly pending — self-identified, accurately tracked. |
| Reproducibility (reproduce.py, Data Test Range section) | **Strong** | The 30-step finding→script registry plus the CLAUDE.md "Data Test Range & Reproducibility" section, plus `reproduce.py --show-provenance` (already built, prints universe snapshot/fetch windows/pinned versions), is **more rigorous than most of what the retrieved sources describe as typical practice** — most quant infra discussions treat reproducibility as an afterthought; CAMARF treats it as a first-class, audited requirement. |
| Documentation discipline (Development.md, PAPER.md, CLAUDE.md) | **Strong** | The bug-postmortem registry and "known-resolved issues, do not re-suggest" pattern is unusually disciplined — this is arguably ahead of typical solo/small-team practice. |
| Bias documentation & honesty discipline (rule 6/7) | **Strong** | Directly matches the Academic/Skeptic's core demand (report the real number, disclose the real limitation) better than the "publish only the best p-value" failure mode López de Prado himself describes as endemic even at real funds [Practitioner:8]. |
| CI/CD, automated test suite, code review process | **Partial** | `debug/_verify_*.py` synthetic tests are genuinely good practice (caught 2 real calendar-alignment bugs this session alone) but are ad hoc, not wired into a CI runner, and there's no formalized code-review process (N/A for a solo project, but a test *runner* — even a simple `pytest` collection + a pre-commit hook running the debug/_verify_*.py suite — is a cheap, real gap). |
| Alternative data integration | **Out of scope, correctly** | Costs $1.6M+/year average at real funds [Economist:9] — clearly disproportionate to project scale; no STORM lens argues this is worth pursuing for CAMARF. |

---

## 3. Gap list, ranked by priority — CORRECTED 2026-07-01

Original Tier 1/2/3 below is struck through where the item turned out to
already be built (see §2 corrections). What actually remains:

**Done, not originally credited:** DSR + trial registry (§6.7), pit_wfa.py
PAPER.md framing (§7.3.1, §8 bias entry, abstract), sqrt-impact cost model,
filter-ablation funnel + counterfactual (§7.11), HRP + Absorption Ratio
(§7.2), era-decay replication (§7.11), reproduce.py provenance.

**Genuinely still open, ranked:**
1. **Lightweight CI test runner for `debug/_verify_*.py`** (18 scripts exist,
   none wired to run automatically) — near-zero cost, converts ad hoc
   verification into an enforced gate.
2. **Stress-test / historical-scenario replay** against confirmed pairs
   (2007 quant-quake analog, 2020 COVID vol, using already-fetched history)
   — cheap since the data already exists; answers the Historian's
   "regime risk isn't caught by more CV folds" concern in a way DSR alone
   can't.
3. **Corporate-actions reconciliation audit** — lower urgency since yfinance
   already adjusts at the source; worth a cheap spot-check, not a full
   module.
4. **CVaR (not VaR) portfolio-level reporting** — legitimate but not urgent
   without live capital at risk.
5. **§2 lit-review citations** (Do & Faff, Hakkio & Rush, Bailey & López de
   Prado DSR, Harvey/Liu/Zhu, LTCM/Aug 2007/Mar 2020 crisis episodes) — data
   already exists in `storm-statistical-arbitrage-pairs-trading.md`, this is
   a writing task, not new research.

**Correctly out of scope, do not build:** live trading infra/kill switches,
formal compliance/audit trails, SR 11-7-style model governance, alternative
data integration, real-time external crowding surveillance, CPCV/PBO (DSR
already covers the same multiple-testing concern at lower implementation
cost — CPCV would be a refinement, not a gap). Each is excluded for an
evidenced reason, not by omission.

---

## 4. Bottom line

**Original conclusion (wrong, written without checking the repo):** claimed
DSR, HRP, sqrt-impact, filter-ablation, and era-decay were all missing gaps.
They were already built, verified, and run for real the prior session.

**Corrected conclusion:** CAMARF's statistical-validity infrastructure is in
genuinely good shape for a project at this scale — DSR, honest HRP/risk-parity
benchmarking, filter-ablation, and era-decay replication are all done and now
written into PAPER.md. What remained open after this correction was small and
mostly mechanical (CI test runner, stress-test replay, corp-actions audit,
CVaR, lit-review citations) — not a new architecture gap. The one substantive
finding that survives this correction intact is the **pit_wfa.py pair-
selection lookahead result**, which was never claimed to be "missing
infrastructure" — it was always a finding requiring a framing decision, now
resolved and written into PAPER.md §7.3.1.
