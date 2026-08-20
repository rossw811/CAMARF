# CAMARF — Cross-Asset Co-Movement Arbitrage Research Framework

**Author:** Ross W.
**Status:** Active research, mid-pivot. The production pipeline (data → analysis → ML →
backtest → statistical validation → walk-forward → report) runs end-to-end, but the
confirmed-pair universe underneath it changed materially in the last two sessions (see
"Current Results" below) and a genuinely new, more novel central thesis — point-in-time-safe
episodic cointegration confirmation vs. the standard static full-sample screen — is actively
being built and is not yet concluded. Read this file's status as "in motion," not settled.

---

## Overview

CAMARF is an institutional-grade quantitative research framework that systematically discovers,
characterizes, and models statistical co-movement relationships across a broad multi-asset
universe, spanning the full S&P Composite 1500, cryptocurrency, foreign exchange, commodities,
and futures markets simultaneously. (Corrected from "S&P 500" to "S&P Composite 1500" against
this file's own verified universe figures below — the broader 1500-constituent index, not just
the 500 large-caps, is what `config.py` actually screens.)

Concretely, the framework is built around two related, evolving questions: (1) whether
cross-asset co-movement relationships exhibit regime-dependent, volatility-normalized arbitrage
structure predictable at statistically significant rates, and (2) whether the standard way the
field screens for that structure — a single, static, full-sample cointegration test — is itself
well-calibrated across time and data depth. Question (2) has grown from a secondary finding (the "Strictness Paradox" below)
into the project's current main line of investigation: a **point-in-time-safe episodic
confirmation methodology** (rolling-window cointegration tests, joint BH-FDR corrected across
the full test family, filtered to only information a real deployment date would have had) is
being built and compared directly against the static screen, on the same universe, to measure
how much real structure the static approach misses. As of this writing that comparison is
**not yet complete** — see "Current Results" for exactly what's done vs. in progress.

Daily-and-coarser US equity/ETF data is now sourced primarily from WRDS (CRSP total-return-
adjusted, Compustat Global split-only as a disclosed fallback), which gives this project
decades of clean history instead of yfinance's comparatively short and noisier daily bars —
directly enabling the episodic methodology above. International equities and everything
intraday remain yfinance-sourced. This project serves as a primary portfolio piece for
quantitative finance program applications; the current expectation (see below) is that it
will produce two related but separate papers rather than one — the original cross-asset
backtest work, and the newer episodic-vs-static screening methodology finding.

---

## Headline Finding: The Strictness Paradox

The project's central, citable contribution is not the trading strategy itself but a
diagnosis of a failure mode in the standard cointegration-screening methodology every
prior pairs-trading paper relies on:

This project's own original headline confirmed pairs, **NTRS/STT** and **SHW/UNP**,
pass a full-sample Engle-Granger test with p < 0.005 while *failing* the identical test
restricted to just the last five years. A full-sample screen over 40–60 years of history
is effectively testing whether two price levels stayed cointegrated across decades of
M&A, sector rotation, and business-model change — a bar a genuinely tradable relationship
can fail today while still reading "confirmed." A companion observation — that full-sample
screens at long horizons (1D, 1M) reject candidate pairs at rates far below their expected
false-positive rate under the null — was initially read as evidence the EG test itself is
statistically over-conservative at those horizons. That reading was tested directly via a
Monte Carlo calibration study (`research/eg_null_calibration_montecarlo.py`) and **refuted**:
the empirical false-positive rate under a genuinely null, by-construction pairing is
*elevated*, not suppressed (7.75%–12.75% vs. nominal 5%), and grows with horizon — ordinary
spurious regression from shared market-wide drift, not test miscalibration. The full-sample
screen's near-total rejection rate at long horizons reflects the test correctly guarding
against exactly this risk. The durability-vs-currency conflation demonstrated by NTRS/STT
and SHW/UNP is the real, load-bearing failure mode and needed no such correction — reported
here alongside the refuted companion hypothesis rather than silently dropping it, per this
project's standing verify-before-trusting discipline.

`coint_fraction_rolling` — a scalable rolling-window stability diagnostic — and a
secondary-evidence override (corroborating borderline cases against Zivot-Andrews and
CUSUM structural-break tests) operationalize, at the ~10⁶-pairwise-test scale this
project runs at, a question formal econometrics already has tools for at the
single-pair scale (Gregory & Hansen, 1996; Hansen, 1992; Quintos & Phillips, 1993).

See `PAPER.md` for the full argument, literature review, and empirical results. **Note:** the
episodic-vs-static methodology finding described above (currently the project's most novel
direction, per its own owner's stated preference) is NOT yet in `PAPER.md` — it's real, in-progress
work, tracked in `Development.md`'s Session 30/31 entries and `docs/HANDOFF.md`, not yet promoted
to a citable claim.

---

## Current Results

**Superseded, kept for provenance:** an earlier snapshot (Session 28, 2026-07-12) reported 26
confirmed pairs (mostly @1h) and a 5.80/5.22 IS/OOS portfolio Sharpe under a yfinance-primary
daily-and-coarser data source. That entire snapshot is now **stale in a specific, disclosed way**:
switching WRDS to primary for daily-and-coarser US equity/ETF data (Session 29-30) changed the
underlying price series for a large fraction of the universe, not just added coverage, and the
confirmed-pair set it produces is materially different — this is a genuine methodology-driven
change, not a regression, but headline numbers from before this switch should not be quoted as
current. Full historical detail in `Development.md`.

**The static full-history screen's output (as of Session 30, 2026-08-03/04) was 3 pairs** —
`KVUE/KMB@3m`, `PNC/ZION@4h`, `IQV/Q@1D` — a real, large reduction from the pre-WRDS 23-26 pair
sets (PAPER.md §3/§5 carry the full accounting of why: WRDS/CRSP's cleaner, longer daily history
changes which pairs a static full-sample screen confirms, not a data-quality regression). **These 3
pairs are no longer this project's reference set, reframed 2026-08-11 (Session 31)**: they have
ZERO overlap with the PIT-safe episodic-confirmation methodology below, and real, capital-
constrained backtests (`backtest.py --capital-sim`) on them are honestly poor — `IQV/Q@1D`: 40
trades, WR=0%, Sharpe=-13986.57 (BUG-D107's 1D-timeframe fix verified this is a real result, not a
bug — the pair genuinely underperforms at 1D once actually backtestable). Full historical detail
preserved in `Development.md`/`docs/BUG_LOG.md`, not restated as current here.

**Current reference set: the point-in-time-safe episodic confirmation methodology** (WRDS
daily-and-coarser + intraday 1h/4h extensions, rolling windows, joint BH-FDR across the whole test
family) — **182 PIT-safe confirmed pairs** as of the BUG-D112-fixed adapter run, 2026-08-12 (170
WRDS/1D, 6 intraday/1h, 6 intraday/4h; `output/research/episodic_confirmed_pairs_adapter_output.parquet`).
This supersedes an earlier 454-pair count (338 WRDS/1D, 76 intraday/1h, 40 intraday/4h) that was
found to be contaminated by a candidate-generation lookahead bug (BUG-D112 — pairs could be tested,
and flagged FDR-significant, on dates before they would have genuinely qualified as a candidate;
see `docs/BUG_LOG.md`). A static full-history test structurally can't distinguish "cointegrated its
entire life" from "recently coupled" — this is the empirical basis for the episodic-vs-static
methodology thesis described above. A real, capital-constrained portfolio backtest of this
genuinely PIT-safe 182-pair set (`--capital-sim`, $100k fixed sizing): **Purity arm IS Sharpe
-0.679, OOS Sharpe -0.834** — the honest, uncontaminated result is that this universe loses money
under realistic capital constraints, both in- and out-of-sample. The Hybrid arm (mixes in the 3
non-PIT-safe standard pairs) is similarly negative (IS -0.442, OOS -1.125); the Tiered and Baseline
arms both post +1.417 IS / +0.630 OOS, but that outperformance is a capital-efficiency artifact of
which pairs trade at all, not evidence PIT-confidence tier-weighting adds risk-adjusted value (all
3 standard pairs share one tier weight at this snapshot). See `Development.md`'s Session 31
redo-execution entry and `docs/FINDINGS.md` for the full writeup.

**Backtest/statistical-validation numbers from the pre-WRDS 23-26 pair era (IS Sharpe ~5.8-8.5
depending on variant, OOS ~5.2, deflated Sharpe z~9.5 IS/2.9 OOS, distance-method comparison, tail
risk, permutation tests, capital-constrained backtesting) are preserved in full historical detail
in `Development.md` and `docs/BUG_LOG.md` (BUG-D58/59/61/62 and others) but are **not restated
here as current** — they describe a confirmed-pair universe this project no longer uses as its
production default. A fresh backtest re-run against the corrected 3-pair (or eventually
episodic/hybrid/tiered) set, once `backtest.py`'s 1D gap and the pair-source decision above are
both resolved, is the next real "current results" entry for this section — not yet available.

`Development.md`, `docs/FINDINGS.md`, and `docs/HANDOFF.md` are the sources of truth for exact
current numbers, not this file, more so now than usual given how much is actively in flux.

---

## Architecture — Non-Negotiable Rules

1. **`data.py` fetches, `analysis.py` analyzes — never the reverse.** `analysis.py`
   always calls `builder.build(connect=False)` and never touches yfinance or IBKR
   directly.
2. **WRDS is primary for daily-and-coarser US equity/ETF data; yfinance covers everything
   else (intraday, international) and is the fallback.** `data_wrds.py` (manual, separate)
   fetches CRSP total-return-adjusted daily history for the whole US equity/ETF universe —
   decades deep, directly enabling the episodic PIT-safe confirmation methodology described
   above. `data.py` remains yfinance-only for intraday and international data, ~30–40 minutes.
   IBKR is a further, separate supplemental script: `data_ibkr.py` fetches 10-year deep history
   for *confirmed pairs only* (read from `confirmed_pairs_manifest.json`).
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
python data.py                    # yfinance fetch, ~1,691 configured assets × 13 TFs, ~30-40 min
python data_wrds.py                # manual, separate: WRDS/CRSP daily-and-coarser US equity/ETF bulk fetch, primary source
python data_ibkr.py                # manual, separate: 10Y deep history for confirmed pairs only
python analysis.py                 # correlation, EG+BH-FDR, hedge ratio, OU spread,
                                    #   eigenportfolio, coint_fraction_rolling + override
python research/wrds_deep_history_episodic_scan.py   # PIT-safe episodic confirmation (WRDS daily+coarser), decades-deep rolling windows
python research/intraday_episodic_scan.py --tf both  # same methodology extended to 1h/4h (Session 31, in progress)
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

- **Universe snapshot:** current canonical daily-and-coarser universe is WRDS-primary as of
  Session 30 (2026-08-03), ~1,730 symbols with cached daily data, 1,660 passing the full
  screening funnel — see `CLAUDE.md`'s "Data Test Range & Reproducibility" section for the
  exact, kept-current figures (this file's own copy of that table drifts faster than `CLAUDE.md`'s
  does). International equities and intraday timeframes remain yfinance-sourced against the
  ~1,608-1,691-symbol universe from the pre-WRDS snapshot below, kept for provenance.
  Pre-WRDS snapshot: 1,608 candidate symbols (S&P Composite 1500 + international), completed
  **2026-06-30** in 5.6 minutes; `config.py` specifies ~1,691 assets as of 2026-07-13 — not yet
  exercised by a full yfinance-side run.
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
- **Point-in-time (PIT) safety of the production pair source — the current headline
  disclosure.** The confirmed-pair set `backtest.py`/`report.py` actually trade is still sourced
  from the standard full-history screen, which is NOT point-in-time-safe (a real deployment at
  any past date would not have discovered or traded that same pair set — a direct PIT re-screen
  found zero pair overlap with the standing set and negative OOS Sharpe in every fold, see
  `PAPER.md` §7.3.1). A genuinely PIT-safe episodic alternative exists and finds far more real
  structure (647 pairs vs. 3), but is not yet wired into production — see "Current Results" above.
  Every research comparison arm built in Session 30 was also found to inherit this same bias
  (sourcing pairs from the same non-PIT screen), disclosed in `docs/FINDINGS.md`.
- **Kelly-sizing lookahead** and **in-sample stop comparison:** flagged explicitly in
  `bias_audit.json`, not corrected away.
- **Small-n filtering** at short timeframes (1m/3m) where limited history constrains
  statistical power — now compounded by `KVUE/KMB@3m`'s cached history being only ~7 weeks deep
  (Yahoo's 1m fetch has a hard 8-day limit; 3m is derived by resampling, so more history can only
  accumulate over real calendar time, not be fetched around).
- **No unified re-audit yet** combining a survivorship-bias-free universe, a properly
  deflated Sharpe ratio (correcting for the number of backtest variants actually run),
  and structural-break-robust cointegration testing simultaneously — an open item, see
  `Development.md`.

---

## File Map

**Production pipeline (root):**
- `data.py` — yfinance fetch pipeline (intraday + international; primary for those, fallback for US daily-and-coarser)
- `data_wrds.py` — WRDS/CRSP bulk fetch, primary source for daily-and-coarser US equity/ETF data (manual, separate)
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
- `cvar.py` — historical CVaR/Expected Shortfall on portfolio-level daily P&L
- `pit_wfa.py` — point-in-time, portfolio-wide walk-forward analysis
- `portfolio_sim.py` — capital-constrained, mark-to-market portfolio replay; wired into
  `backtest.py` via the opt-in `--capital-sim` flag
- `fresh_holdout_compare.py` — compares candidate mechanisms for a genuinely fresh,
  never-re-examined holdout slice (time-based, pair-based, and combined)
- `survivorship.py` — S&P 500 historical constituent-change scraper
- `gics.py` — GICS sector tag builder
- `earnings.py` — earnings-date fetch/cache for `backtest.py --storm-earnings-blackout`
- `options.py` — options-overlay comparison arm (not part of the core production pipeline)
- `run_storm_grid.py` — full 2⁴ factorial grid over the STORM variant flags
- `run_verify_suite.py` — runs every `debug/_verify_*.py` synthetic test, one pass/fail summary

**`research/`** — standalone diagnostic/comparison scripts, not part of the production
pipeline; each tests exactly one claim with its own synthetic verification under `debug/`.
Includes `filter_ablation.py` (counterfactual backtest of pairs each pipeline filter
excludes, via `backtest.py --pairs-override`), `era_decay_replication.py` (Do & Faff
2010-style era-split replication on CAMARF's own confirmed pairs),
`coint_frac_window_grid.py` (window-length and joint window/threshold grid search over the
rolling-stability diagnostic, with an out-of-sample overfitting guard), and
`cross_session_leadlag.py` (overnight-gap and cross-timezone lead-lag, distinct from the
already-tested and rejected same-session case).

**PIT-safe episodic confirmation family** (Sessions 30-31, the project's current main line of
work — see "Overview"/"Current Results" above): `wrds_deep_history_episodic_scan.py` (WRDS
daily-and-coarser, decades-deep rolling-window EG+joint-BH-FDR confirmation, causal
`episodic_bhfdr_confirm_asof` variant), `intraday_episodic_scan.py` (same methodology extended
to 1h/4h, in progress as of this writing), `intraday_episodic_window_sensitivity.py` (empirical
test of window/step sizing — see `docs/FINDINGS.md` #22 — rather than a guessed constant),
`pit_pair_discovery.py` (drop-in PIT-safe replacement for `ml._discover_confirmed_pairs()`),
`episodic_pairs_adapter.py` (builds `backtest.py --pairs-override`-compatible rows from the
episodic-confirmed set, respecting the same train-only-scalar PIT discipline as `pit_wfa.py`),
`structural_break_onset_detection.py` (per-pair coupling/decoupling onset dates via
Quandt-Andrews/Chow-test break detection, the mechanism behind "recently coupled vs. always
cointegrated").

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
| **`PAPER.md`** | The actual paper draft — the three headline pillars (Strictness Paradox, pair-selection lookahead, price-degeneracy), the full methodology, and a tight "Robustness and Comparison Arms" section (§7.15) that summarizes and points to `docs/FINDINGS.md` for depth. Kept deliberately focused — not every verified finding this project has produced lives here, by design. | Updated when a finding is verified and belongs in the core narrative |
| **`docs/FINDINGS.md`** | Full-depth writeups of every OTHER verified, honest finding — comparison arms, robustness checks, negative results — that isn't load-bearing for `PAPER.md`'s central claims but is still real, checked work worth citing. Nothing here is hidden; it's organized by relevance to the thesis, not by confidence or quality. | Updated alongside `PAPER.md` §7.15 |
| **`Development.md`** | The canonical, full project memory — every session's log, the complete `BUG-D` registry, design rationale, and the honest record of what was tried and reverted (not just what was kept). The place to look if you need to know *why* something is built the way it is, or whether an idea was already tried and abandoned. | Append-only, every session |
| **`docs/BUG_LOG.md`** | A one-line-per-entry index into `Development.md`'s full bug registry — find a specific `BUG-D`/`BUG-A` number's summary and exact line pointer without reading the full narrative. Pure index; every write-up still lives only in `Development.md`. | Updated alongside each new bug entry |
| **`docs/HANDOFF.md`** | A point-in-time directive written at the end of a specific session, addressed to whichever session picks the project up next — a punch list of what to verify, not a reference document. Expect it to describe a specific past moment, not the current state. | Written once per handoff, not maintained afterward |
| **`CONTRIBUTING.md`** | How to actually run, modify, and validate the codebase — environment setup, the pipeline command sequence, the "STORM variant" pattern for adding a new backtest comparison arm, where bias documentation and synthetic verification tests live. | Updated when the development workflow itself changes |

If you're only reading one file to get oriented: `CLAUDE.md`. If you're trying to understand
a specific number in `PAPER.md`: `reproduce.py --list` maps it to the script that generated
it; if that number isn't in `PAPER.md` at all, check `docs/FINDINGS.md` before assuming it doesn't
exist.

---

## Dependencies

See `requirements.txt` for exact pinned versions. Core stack: `yfinance`, `wrds` (primary
source for daily-and-coarser US equity/ETF data, Session 29+ — was missing from
`requirements.txt` entirely until 2026-08-08 despite being an active import in
`data_wrds.py`, found and fixed while updating this file), `ib_insync` (supplemental only),
`pandas`/`numpy`, `statsmodels` (EG/Johansen/KPSS), `scikit-learn`, `hmmlearn`, `scipy`,
`pyarrow==24.0.0`, `arch` (GARCH), `xgboost`.
