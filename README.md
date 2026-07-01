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

## Current Results (Session 22, full pipeline run 2026-06-30)

**Confirmed pairs: 23** across 5 timeframes — 17 @1h (including a 5-pair DD-hub
cluster), 2 @3m, 1 @30m, 2 @4h, 1 international (7267.T/8058.T).

| Metric | In-Sample | Out-of-Sample (20% holdout) |
|---|---|---|
| Portfolio Sharpe | **5.2935** | **5.2443** |
| Trades | 1,028 | 296 |
| Total P&L | $264,926 | $73,596 |

IS→OOS degradation is **0.9%** — far below typical stat-arb decay (Do & Faff 2010
document ~70%+ decay for the classical GGR distance method over multi-decade samples).

- **Best position-sizing variant:** inverse-volatility risk-parity, OOS Sharpe **5.8689**
- **Walk-forward robustness:** baseline expanding/rolling Sharpe 3.13/3.27; best variant
  (mm_exec, MM-robust hedge ratio) 3.82/3.96
- **Distance-method baseline comparison (Gatev, Goetzmann & Rouwenhorst 2006):**
  CAMARF's cointegration-based selection achieves mean per-pair Sharpe **11.741** vs.
  GGR's distance method at **−0.208** on the same universe and window
- **Statistical validation stack:** EG+KPSS+Phillips-Ouliaris confirmatory tiers (13
  gold / 9 silver of 22 testable pairs), EVT/GPD tail risk (16/23 pairs fat-tailed),
  DCC-GARCH concentration monitoring, portfolio-level permutation tests (reported
  honestly — not significant at conventional levels; see PAPER.md §6.6 for why)
- **Deflated Sharpe Ratio** (correcting for 14 backtest variants tried, non-normal
  daily P&L, small sample size): IS z=11.02, OOS z=6.48 — decisively clears the
  "no genuine skill" null even after this correction
- **Filter-ablation:** the coint_frac threshold filter's 297 excluded @1h candidates
  would have produced OOS Sharpe 3.67 on their own — lower than the confirmed set's
  5.24, so the filter is net-positive, though the excluded set isn't worthless either
- **Absorption Ratio** (Kritzman, Li, Page & Rigobon 2011, rolling systemic-risk
  measure): mean 0.427, range 0.205–0.847 across the confirmed-pair universe
- **HRP vs. risk-parity:** Hierarchical Risk Parity (true cross-pair covariance)
  OOS Sharpe 5.3752 — better than baseline but below risk-parity's simpler
  per-pair-volatility approach for this pair set
- **Square-root market impact** (vs. flat-bps slippage): OOS Sharpe 5.2591 —
  slightly better than baseline, consistent with position sizes being small
  relative to these liquid names' ADV

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

- `CLAUDE.md` — fast-orientation project context (architecture rules, working style,
  data test range)
- `DEVELOPMENT.md` — canonical project memory: full bug registry, session-by-session log
- `PAPER.md` — living draft of the actual paper/thesis
- `CONTRIBUTING.md` — how to run, modify, and validate this project
- `latest_run_*.log` — auto-generated structured run summaries, one per script

---

## Dependencies

See `requirements.txt` for exact pinned versions. Core stack: `yfinance`, `ib_insync`
(supplemental only), `pandas`/`numpy`, `statsmodels` (EG/Johansen/KPSS), `scikit-learn`,
`hmmlearn`, `scipy`, `pyarrow==24.0.0`, `arch` (GARCH), `xgboost`.
