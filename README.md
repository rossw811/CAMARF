# CAMARF — Cross-Asset Co-Movement Arbitrage Research Framework

**Author:** Ross W.
**Status:** Active research — full pipeline (data → analysis → ML → backtest → statistical
validation → walk-forward → report) built and run end-to-end; ML gate deferred pending
labeled-data accumulation.

---

## Overview

CAMARF is an institutional-grade statistical arbitrage research framework testing
whether cross-asset co-movement relationships exhibit regime-dependent,
volatility-normalized arbitrage structure predictable at statistically significant
rates using multiclass ML — and, more specifically, whether the standard way the
field screens for that structure (a single full-sample cointegration test) is itself
well-calibrated across time horizons.

The universe spans ~1,609 assets (S&P Composite 1500 + international equities/ADRs/FX
spots) across 13 timeframes, from 1-minute to 6-month bars. This project serves as a
primary portfolio piece for quantitative finance program applications.

---

## Headline Finding: The Strictness Paradox

The project's central, citable contribution is not the trading strategy itself but a
diagnosis of a failure mode in the standard cointegration-screening methodology every
prior pairs-trading paper relies on:

Full-sample Engle-Granger cointegration tests at long horizons (1D, 1M) reject
candidate pairs at rates **orders of magnitude below** their expected false-positive
rate under the null — not because no relationships exist, but because the test itself
becomes too strict to be decision-relevant at that horizon. Concretely: this project's
own original headline confirmed pairs, **NTRS/STT** and **SHW/UNP**, pass a full-sample
Engle-Granger test with p < 0.005 while *failing* the identical test restricted to just
the last five years. A full-sample screen over 40–60 years of history is effectively
testing whether two price levels stayed cointegrated across decades of M&A, sector
rotation, and business-model change — a bar a genuinely tradable relationship can fail
today while still reading "confirmed."

`coint_fraction_rolling` — a scalable rolling-window stability diagnostic — and a
secondary-evidence override (corroborating borderline cases against Zivot-Andrews and
CUSUM structural-break tests) operationalize, at the ~10⁶-pairwise-test scale this
project runs at, a question formal econometrics already has tools for at the
single-pair scale (Gregory & Hansen, 1996; Hansen, 1992; Quintos & Phillips, 1993).

See `PAPER.md` for the full argument, literature review, and empirical results.

---

## Current Results (Session 28, full pipeline rerun + 3 bug fixes, 2026-07-12)

**Confirmed pairs: 26** — 24 @1h (incl. 12 cross-asset), 1 @3m, 1 @1M (international,
7267.T/8058.T). The 30m/4h pairs present in the prior Session 22 snapshot are not in this
session's fresh confirmed set — a genuine change in what the current screen finds as data has
grown, not a bug.

| Metric | In-Sample | Out-of-Sample (20% holdout) |
|---|---|---|
| Portfolio Sharpe | **5.8044** | **5.2155** |
| Trades | 2,168 | 449 |

IS→OOS degradation is **10.2%** — up from the previously-reported 0.9% figure, reported honestly
rather than glossed over. This session found and fixed two real bugs affecting these numbers:
**BUG-D58** (a survivorship-exclusion false positive was silently zeroing out 7/24 confirmed
pairs — DD/NOV/FHN were flagged as "delisted" based on being demoted out of the S&P 500 index at
some point, not on actually ceasing to trade) and **BUG-D59** (the cointegration-vs-distance
portfolio comparison below was an unweighted mean of noisy per-pair Sharpes, not a real pooled
portfolio statistic). Full write-ups in `Development.md` and `BUG_LOG.md`.

- **Distance-method baseline comparison (Gatev, Goetzmann & Rouwenhorst 2006), BUG-D59 fix
  applied:** cointegration-based selection's correctly-pooled portfolio Sharpe is **8.542** vs.
  GGR's distance method at **7.865** on the same universe and window — a real but far more modest
  ~0.7 Sharpe-point advantage. The previously-reported "11.741 vs. −0.208" comparison was a
  measurement artifact (see `Development.md`, 2026-07-12) — the magnitude of this shift is still
  being investigated, not yet fully explained.
- **Statistical validation stack:** EG+KPSS+Phillips-Ouliaris confirmatory tiers (17
  gold / 8 silver of 25 testable pairs, unchanged by this session's fixes), EVT/GPD tail risk
  (17/26 pairs fat-tailed, up from 16/26 — several previously-truncated pairs now have real
  P&L-based tail estimates), DCC-GARCH concentration monitoring, portfolio-level permutation
  tests (IS p=0.546, OOS p=0.559 — not significant at conventional levels; see PAPER.md §6.6)
- **Deflated Sharpe Ratio** (correcting for 49 backtest variants tried, non-normal daily P&L,
  small sample size): **IS z=9.53, OOS z=2.91** — strengthened, not weakened, by the BUG-D58 fix
  (more real trade data gives a cleaner signal). 29 evaluations have now examined the same OOS
  holdout window — reserving a genuinely fresh holdout slice is an agreed next step, not yet
  implemented (see `Development.md`'s Garden-of-Forking-Paths caveat).
- **Not yet re-verified against this session's fixes** (flagged explicitly rather than silently
  left stale): best position-sizing variant (risk-parity, previously 5.8689), walk-forward
  robustness range (previously 3.13/3.27 baseline — note `wfa.py` doesn't apply survivorship
  truncation so is unaffected by BUG-D58, but hasn't been rechecked against this exact write-up),
  filter-ablation, Absorption Ratio, HRP comparison, square-root market impact. These all need a
  dedicated re-run pass before being restated as current.

Numbers update as the pipeline reruns; `PAPER.md` and `Development.md` are the sources
of truth, not this file.

---

## Architecture — Non-Negotiable Rules

1. **`data.py` fetches, `analysis.py` analyzes — never the reverse.** `analysis.py`
   always calls `builder.build(connect=False)` and never touches yfinance or IBKR
   directly.
2. **yfinance is primary; IBKR is a separate, supplemental script.** `data.py` is
   yfinance-only and completes in ~30–40 minutes. `data_ibkr.py` is run manually to
   fetch 10-year deep history for *confirmed pairs only* (read from
   `confirmed_pairs_manifest.json`), enabling the episodic-cointegration test.
   `ibkr_supplement_reader.py` is a parquet-only reader shared by `data_ibkr.py` and
   `analysis.py` with zero `ib_insync` dependency — this keeps the IBKR fetch boundary
   fully decoupled from the core pipeline.
3. **A six-code `GapFlag` system governs all gap handling** (`NONE, FILL, NO_ACTIVITY,
   HALT, DATA_GAP, SPARSE`). `DATA_GAP` bars are masked to NaN in every downstream
   correlation/cointegration calculation, never silently forward-filled.
4. **Every rolling-window calculation is strictly causal.** All `.rolling()` windows
   across the codebase use pandas' default trailing/right-aligned convention — no
   `center=True` anywhere — so a "252-bar window" always means the 252 bars leading up
   to and including the current point, never bars centered around it.
5. **Known biases are documented, never silently corrected away.** Current-constituent
   survivorship bias (universe is not point-in-time delisting-inclusive), Kelly-sizing
   lookahead, in-sample stop comparison, and small-n filtering are all logged to
   `output/results/bias_audit.json` with mechanism/remedy/residual-risk fields, not
   quietly patched out of the results.

---

## Pipeline

Run in this order (each stage writes its own `latest_run_*.log`):

```bash
python data.py                    # yfinance fetch, ~1,609 assets × 13 TFs, ~30-40 min
python data_ibkr.py                # manual, separate: 10Y deep history for confirmed pairs only
python analysis.py                 # correlation, EG+BH-FDR, hedge ratio, OU spread,
                                    #   eigenportfolio, coint_fraction_rolling + override
python ml.py                       # meta-labeling Stage 1 (Stage 2 + SHAP deferred)
python backtest.py --holdout       # event-driven Layer 1 baseline
python backtest.py --holdout --risk-parity   # best position-sizing variant
python stats.py                    # 6-section confirmatory validation stack
python wfa.py                      # walk-forward analysis, expanding + rolling
python distance.py                 # Gatev-Goetzmann-Rouwenhorst baseline comparison
python sensitivity.py              # parameter sensitivity grids
python macro.py                    # FRED macro regime context
python report.py                   # LaTeX report generator (main.tex + figures)
python reproduce.py --verify-only  # confirm every PAPER.md finding's output still exists
```

All scripts run via the project's pinned conda environment (`trading`) — see
`requirements.txt` for exact versions (pyarrow 24.0.0 specifically pinned; see
"Reproducibility" below for why this matters).

---

## Reproducibility

This run's exact data footprint (see `CLAUDE.md`'s "Data Test Range & Reproducibility"
section for the canonical, kept-current version of this table):

- **Universe snapshot:** 1,608 candidate symbols (S&P Composite 1500 + international),
  full pipeline run **2026-06-30**, `data.py` completed in 5.6 minutes
- **Per-timeframe fetch windows (yfinance):** 1m/3m → 5 calendar days (3m derived by
  resampling 1m — Yahoo's 1m hard limit is 8 days), 2m → 55 days, 5m/15m/30m → 60 days,
  1h/4h → 730 days (4h derived by resampling 1h with session-aligned bins), 1D/1M → full
  available history
- **Package versions:** see `requirements.txt`, in particular `pyarrow==24.0.0` (pinned
  — cross-version pyarrow reads can misreport valid parquet files as corrupted)

An independent party can re-fetch statistically equivalent data by running `data.py`
against the same universe source and date parameters above, without needing this
repo's cached `output/cache/` directory. `reproduce.py` maps every `PAPER.md` finding
to the exact script/flags that generated it.

---

## Known Biases and Limitations (documented, not hidden)

- **Survivorship bias:** the universe is built from *current* S&P Composite 1500
  constituents, not a point-in-time, delisting-inclusive historical universe.
- **Kelly-sizing lookahead** and **in-sample stop comparison:** flagged explicitly in
  `bias_audit.json`, not corrected away.
- **Small-n filtering** at short timeframes (1m/3m) where limited history constrains
  statistical power.
- **No unified re-audit yet** combining a survivorship-bias-free universe, a properly
  deflated Sharpe ratio (correcting for the number of backtest variants actually run),
  and structural-break-robust cointegration testing simultaneously — an open item, see
  `Development.md`.

---

## File Map

**Production pipeline (root):**
- `data.py` — yfinance-primary fetch pipeline
- `data_ibkr.py` / `ibkr_supplement_reader.py` — supplemental IBKR deep-history fetch
  (manual, separate) and its parquet-only reader
- `analysis.py` — full co-movement/cointegration analysis pipeline
- `ml.py` — meta-labeling spread-resolution classifier (Stage 1)
- `backtest.py` — event-driven backtest engine, Layer 1 baseline + STORM variants
- `stats.py` — six-section statistical validation stack
- `wfa.py` — walk-forward analysis
- `distance.py` — Gatev-Goetzmann-Rouwenhorst distance-method baseline
- `sensitivity.py` — parameter sensitivity grids
- `macro.py` — FRED macro regime context
- `report.py` — LaTeX report generator
- `reproduce.py` — maps every `PAPER.md` finding to its generating script;
  `--show-provenance` prints the data test range this run's numbers are drawn from
- `config.py` — all configuration parameters
- `seed_sp_caches.py` — standalone S&P 400/600 constituent cache seeder
- `deflated_sharpe.py` — Deflated Sharpe Ratio (Bailey & López de Prado 2014),
  correcting the headline Sharpe for the number of backtest variants actually tried
- `absorption_ratio.py` — Kritzman-Li-Page-Rigobon (2011) rolling systemic-risk
  measure, reusing the eigenportfolio/PCA machinery already built for pair confirmation
- `trial_registry.py` — shared append-only trial log `deflated_sharpe.py` reads from;
  every `backtest.py` run records its own Sharpe here automatically

**`research/`** — standalone diagnostic/comparison scripts, not part of the production
pipeline; each tests exactly one claim with its own synthetic verification under `debug/`.
Includes `filter_ablation.py` (counterfactual backtest of pairs each pipeline filter
excludes, via `backtest.py --pairs-override`) and `era_decay_replication.py` (Do & Faff
2010-style era-split replication on CAMARF's own confirmed pairs).

**`debug/`** — ad-hoc scratch utilities plus `_verify_*.py` synthetic proofs cited
throughout `Development.md`.

- `latest_run_*.log` — auto-generated structured run summaries, one per script

---

## Documentation Map — which file to read for what

This project keeps several documents with deliberately different jobs. Reading the wrong
one for what you're trying to do is the most common way to end up with a stale or
misleadingly-narrow picture — use this table to pick the right one first:

| Document | Read this when you want... | Kept current how |
|---|---|---|
| **`README.md`** (this file) | A first-pass overview: what the project is, the headline finding, how to run the pipeline. Not the source of truth for exact current numbers — those drift between pipeline runs faster than this file gets touched. | Spot-checked each session, not rewritten each run |
| **`CLAUDE.md`** | Fast orientation for picking the project back up: non-negotiable architecture rules, known-resolved issues (don't re-suggest these), working-style conventions, and a condensed "Current State" pointer to the latest full session in `Development.md`. The file every session should read FIRST. | Updated every session |
| **`PAPER.md`** | The actual paper draft — the three headline pillars (Strictness Paradox, pair-selection lookahead, price-degeneracy), the full methodology, and a tight "Robustness and Comparison Arms" section (§7.15) that summarizes and points to `FINDINGS.md` for depth. Kept deliberately focused — not every verified finding this project has produced lives here, by design. | Updated when a finding is verified and belongs in the core narrative |
| **`FINDINGS.md`** | Full-depth writeups of every OTHER verified, honest finding — comparison arms, robustness checks, negative results — that isn't load-bearing for `PAPER.md`'s central claims but is still real, checked work worth citing. Nothing here is hidden; it's organized by relevance to the thesis, not by confidence or quality. | Updated alongside `PAPER.md` §7.15 |
| **`Development.md`** | The canonical, full project memory — every session's log, the complete `BUG-D` registry, design rationale, and the honest record of what was tried and reverted (not just what was kept). The place to look if you need to know *why* something is built the way it is, or whether an idea was already tried and abandoned. | Append-only, every session |
| **`HANDOFF.md`** | A point-in-time directive written at the end of a specific session, addressed to whichever session picks the project up next — a punch list of what to verify, not a reference document. Expect it to describe a specific past moment, not the current state. | Written once per handoff, not maintained afterward |
| **`CONTRIBUTING.md`** | How to actually run, modify, and validate the codebase — environment setup, the pipeline command sequence, the "STORM variant" pattern for adding a new backtest comparison arm, where bias documentation and synthetic verification tests live. | Updated when the development workflow itself changes |

If you're only reading one file to get oriented: `CLAUDE.md`. If you're trying to understand
a specific number in `PAPER.md`: `reproduce.py --list` maps it to the script that generated
it; if that number isn't in `PAPER.md` at all, check `FINDINGS.md` before assuming it doesn't
exist.

---

## Dependencies

See `requirements.txt` for exact pinned versions. Core stack: `yfinance`, `ib_insync`
(supplemental only), `pandas`/`numpy`, `statsmodels` (EG/Johansen/KPSS), `scikit-learn`,
`hmmlearn`, `scipy`, `pyarrow==24.0.0`, `arch` (GARCH), `xgboost`.
