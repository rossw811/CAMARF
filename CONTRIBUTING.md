# Contributing to / Modifying CAMARF

This is a solo research project (Ross W.), but this doc exists so anyone -- human or an AI
assistant picking up the project cold -- can find, understand, and run any script in this
codebase without re-deriving context from scratch or reading `Development.md`'s full session
history first. Read `CLAUDE.md` first for the project's non-negotiable architecture rules and
working-style conventions; `Development.md` is the canonical full session-by-session memory (bug
registry, design rationale) if you need more depth than this file provides; `docs/HANDOFF.md` is
the current-state/open-items log.

**How this file is organized**: the core production pipeline (below) gets full hand-written
detail -- what each script does, exactly how to run it, its real gotchas. Everything else
(`research/`, `debug/`, supporting root-level modules) is far too numerous (490+ scripts as of
this writing) for that treatment without the doc itself becoming stale reading; those sections are
one-line-per-script tables, auto-generated from each script's own module docstring by
`scripts/_build_contributing.py` -- re-run that generator after adding/removing scripts rather
than hand-editing the tables. Every script in this codebase has a real, specific module docstring
(project convention, not optional) -- when a table row here is too terse, `Read` the script's own
top-of-file docstring directly; it is the authoritative, current source, this file is a fast index
into it.

---

## Environment setup

Run everything through the project's pinned conda environment (Windows: `C:\Users\RossW\
anaconda3\envs\trading\python.exe`) or the CachyOS `.venv` (`.venv/bin/python`) -- never a bare
`python` on PATH:

```bash
conda env create -f environment.yml   # if provided, else:
pip install -r requirements.txt       # into a dedicated env (see below)
```

`pyarrow==24.0.0` is specifically pinned -- installing into a different environment (or letting a
bare `pip install` elsewhere touch your base Python) can silently downgrade pyarrow and make every
parquet file this project writes look corrupted to the older version (`Repetition level histogram
size mismatch`). Always verify `python -c "import pyarrow; print(pyarrow.__version__)"` reports
`24.0.0` in whatever environment you run scripts from.

Second machine, CachyOS (Tailscale `rw@100.64.64.126`), used for RAM-heavy work (46GB vs. the
Surface's 16GB) and long unattended runs -- **use it for RAM-heavy work, never the Surface, even
if the Surface looks free**; a full parallel verify-suite run OOM-killed the Surface twice in one
night before this was consistently applied. **CachyOS's default shell is fish, not bash** --
inline `for`/`if`/`do` bash syntax sent over SSH breaks; write the script to a file and
`scp`+`ssh host bash /path/script.sh` instead of inlining a command string, every time, no
exceptions (this has recurred 5+ times across this project's history whenever it wasn't followed).
Only ever run ONE CachyOS job at a time -- check `ps aux` before launching anything new.

---

## Running the pipeline

See `README.md`'s "Pipeline" section for the full ordered command sequence and expected
runtimes; the **Core production pipeline** section below documents each stage script
individually. Two things worth knowing before you run anything:

- **`data.py` is yfinance-only and safe to run repeatedly** -- it appends new bars incrementally
  rather than re-fetching full history. `data_ibkr.py` is a *separate*, manually-run script that
  requires a live IB Gateway connection and only fetches deep history for pairs already listed in
  the confirmed manifest -- don't try to merge it back into the main `data.py` path (tried before,
  source of weeks of instability; see `Development.md` Session 5-7).
- **`analysis.py` clears `output/results/` when its own script hash (or `config.py`'s) changes**,
  so results always correspond to the code that produced them. If you're iterating on
  `analysis.py` itself, expect a full re-run each time you change it, not an incremental one.

For a single-timeframe debug run instead of the full ~13-timeframe sweep:

```bash
python analysis.py --timeframes 1h
```

**Running the full non-fetch pipeline unattended (overnight/multi-script):** two orchestrators
exist, both write to the same `logs/overnight/` layout and share the same plain-text
`_completed_stages.txt` state file, so a run started by one can be resumed by the other --
`run_overnight_research.ps1` (Windows/PowerShell, the original) and `run_overnight_research.py`
(cross-platform, works on CachyOS/Linux where PowerShell doesn't exist at all; also parallelizes
the 13 `backtest.py` variant stages as one batch instead of running them sequentially). Use
whichever matches your OS; `python run_overnight_research.py --help` for flags.

**Linting:** `pyproject.toml`/`[tool.ruff]` is currently a report-only pyflakes+syntax-error
check, not enforced automatically -- `ruff check .` from the project root to see current findings.
Not wired into CI; run it manually before a nontrivial change if you want the signal.

---

## Core production pipeline

Run in this order for a full refresh; see `README.md`'s "Pipeline" section for the canonical
ordered command sequence and expected runtimes. Everything below runs from the project root
(`python <script>.py`), through the pinned conda env (`C:\Users\RossW\anaconda3\envs\trading\
python.exe` on Windows, `.venv/bin/python` on CachyOS) -- never a bare `python`.

### `data.py` -- primary daily/intraday fetch (yfinance)
**Run:** `python data.py` (full sweep) or `python data.py --timeframes 1h` (single TF, for
iterating on `analysis.py` without waiting on every TF). **Safe to re-run repeatedly** -- appends
new bars incrementally, never re-fetches full history. Writes `output/cache/{tf}/{symbol}.parquet`
and `latest_run_data.log` (read this first when diagnosing a fetch issue -- structured, written
automatically every run). Never calls `analysis.py`'s logic and never touches IBKR directly (rule
1 in `CLAUDE.md`).

### `data_wrds.py` -- WRDS/CRSP fetch (manual, primary for daily-and-coarser US equity/ETF)
**Run:** `python data_wrds.py` (needs an active WRDS session -- interactive login/Duo, not
scriptable end-to-end). Fetches CRSP total-return-adjusted daily history for the whole US
equity/ETF universe, decades deep -- the data source the episodic PIT-safe confirmation
methodology depends on. Also home to Compustat Global (international `GVKEY_IID` constituents),
Compustat fundamentals (CCM-linked), Fama-French factors, IBES price targets, FX
(`frb_all.fx_daily`), and the WRDS connection retry logic (`connect_with_retry_global`) other
scripts import. ALL WRDS data sources live in this one file, one file per external provider --
don't add a WRDS fetch anywhere else.

### `data_ibkr.py` / `ibkr_supplement_reader.py` -- IBKR supplemental intraday (manual, confirmed pairs only)
**Run:** `python data_ibkr.py` (needs a live IB Gateway connection). Deep-history intraday
(1m-4h) fetch for pairs already in the confirmed manifest -- never merged into `data.py`'s own
path (tried before, caused weeks of instability, see `Development.md` Session 5-7). Other scripts
read IBKR's cache via `ibkr_supplement_reader.py` (read-only, no `ib_insync` dependency), never
`data_ibkr.py` directly.

### `analysis.py` -- correlation / cointegration / discovery pipeline
**Run:** `python analysis.py` (full ~13-timeframe sweep) or `python analysis.py --timeframes 1h`
(single TF). Pearson/Spearman/rolling-avg correlation prefilter -> Engle-Granger cointegration
(both regression directions, max-combined) -> BH-FDR correction -> rolling coint_fraction ->
per-pair modeling (hedge ratio, half-life, Hurst) -> eigenportfolio decomposition -> regime
classification -> structural-exclusion tagging (forex triangles, share classes, index-tracking,
SPAC NAV-clustering). Clears `output/results/` whenever its own script hash (or `config.py`'s)
changes, so results always correspond to the code that produced them -- expect a full re-run, not
incremental, whenever you edit `analysis.py` itself. Reads via `builder.build(connect=False)`,
never fetches (rule 1). `latest_run_analysis.log` is the structured log to read first.

### `backtest.py` -- event-driven backtest engine, every comparison-arm variant
**Run:** `python backtest.py` (baseline) or with flags for any variant -- `--pairs-override
<path>` (test against a specific pair set instead of the production manifest), `--holdout` (OOS
split), `--capital-sim` (capital-constrained, mark-to-market replay -- **the project's designated
headline metric**, per pair backtests are diagnostic only), `--capital-sizing {fixed,
equity_proportional,flat_2pct,quarter_kelly,third_kelly,half_kelly,full_kelly}`,
`--capital-account-size <N>`, `--entry-z <N>`, `--hedge {both,ols,kalman}`, `--override
NAME=VALUE` (generic `Config.BACKTEST` constant override, e.g. `--override
STOP_ZSCORE=4.0 CORR_EXIT_THRESHOLD=0.15`), plus ~15 `--storm-*` flags (see "Adding a new
backtest variant" below) each gated behind their own flag -- **a swept `Config.BACKTEST` constant
that's gated behind a flag you didn't also pass is a silent no-op**, confirmed the hard way
2026-09-21 (5 of `parameter_sensitivity_screen.py`'s Tier2 dimensions initially showed a false
zero-effect result this exact way). Writes `trades_<label>.parquet` (the full unconstrained trade
population -- gets OVERWRITTEN by the next run with a different label, archive before re-running
if you need it), `portfolio_<label>.parquet` (aggregate stats), and under `--capital-sim` also
`portfolio_<label>_capsim_<method>_<size>.parquet` + a capsim-scoped `trades_..._capsim_....
parquet`. Every real run should also call `trial_registry.record_trial()` (already wired) so
`deflated_sharpe.py`/`research/hierarchical_dsr.py` can correct for how many configurations have
been tried.

### `ml.py` -- meta-labeler (Layer 2)
**Run:** `python ml.py` (or `--pit-safe` to source pairs from the episodic-confirmed pool instead
of the standard full-history screen). Trains a classifier on top of Layer 1's confirmed pairs to
predict which trade signals are worth taking. Needs `Config.ML.MIN_CLASS_SAMPLES` (>=30 per
class) labeled examples to train meaningfully -- historically often deferred/insufficient-data
status; check the most recent run before trusting its output.

### `macro.py` -- FRED regime context
**Run:** `python -c "import macro; macro.build()"` (no standalone CLI -- imported by
`analysis.py`/`backtest.py` for regime features) or run `debug/_verify_macro_regimes.py` to see
its output shape directly. Fetches FRED series (yield curve, credit spreads, VIX, unemployment
Sahm Rule, Fed funds, CPI, COT positioning) via the keyless `fredgraph.csv` endpoint, derives
regime labels (`recession_state`, `recession_state_realtime`, `vix_regime`, etc.), all with
disclosed real-world reporting lag (`*_days_stale` columns) -- a regime label is only as
point-in-time-safe as its own release lag, not the calendar date.

### `config.py` -- single source of truth for every tunable constant
Not runnable directly. `Config.DATA` / `Config.ANALYSIS` / `Config.STATS` / `Config.BACKTEST` /
`Config.ML` / `Config.RUNTIME` / `Config.UNIVERSE`. Grep here FIRST before assuming a constant is
hardcoded somewhere else -- a value fixed in one place has recurred as a stale duplicate elsewhere
multiple times this project's history (see `Development.md`'s `N_WORKERS` example). Values here
are "current best guess, not empirically re-derived," disclosed as such in nearby comments where
that matters (e.g. `MIN_OVERLAP_BY_TF` -- do not touch without an explicit empirical study, per
standing project instruction).

### `universe_loader.py` -- THE universe loader
**Run:** not standalone; `from universe_loader import load_full_universe`. Any script claiming
universe-wide/"full universe" coverage MUST load via this (the real ~44,700-symbol WRDS-merged
universe), never a private glob of the older ~1,700-symbol yfinance-only cache or any bespoke
loader -- this exact bug (a script quietly reinventing its own smaller-scope loader) has recurred
independently 13+ times across this project's history.

### `stats.py` / `portfolio_math.py` / `portfolio_sim.py` -- shared statistical/portfolio machinery
Not standalone entry points. `stats.py`: permutation tests, hedge-ratio estimators (OLS/Kalman/
Huber/MM), rolling half-life, variance-ratio, tail-dependence. `portfolio_math.py`:
`daily_pnl_from_trades` (the zero-filled daily P&L convention every Sharpe calculation in this
project must use -- a plain `groupby(exit_date)` silently drops zero-P&L calendar days), Sharpe/
skew/kurtosis helpers. `portfolio_sim.py`: `replay_portfolio()`, the actual capital-constrained,
mark-to-market event replay `backtest.py --capital-sim` calls -- sizing methods, Kelly-fraction
estimation (needs 60+ portfolio-wide closed trades before it activates; fewer than that and every
Kelly variant silently collapses to the same flat-2% fallback, confirmed real 2026-09-21, not a
bug), concentration cap, leverage cap.

### `survivorship.py` -- point-in-time index-membership gate
**Run:** not standalone; `build_additions()`/`get_member_since_date()` importable, or run
`debug/_verify_index_additions.py` to see it exercised directly. Scrapes the S&P 500 Wikipedia
page's CURRENT constituents table (with its own "Date added" column) so candidate-generation
pipelines can mask pre-membership history to NaN -- a symbol added in 2022 shouldn't be
correlation/EG-tested against 2015-era windows. Disclosed limitation: only the S&P 500 slice, only
currently-listed members; absence from this table means "no constraint available," never "never
eligible."

### `deflated_sharpe.py` / `trial_registry.py` -- multiple-testing correction for the headline Sharpe
**Run:** `python deflated_sharpe.py` (reads `trial_registry.json`, computes DSR for the current
`layer1`/`layer1_holdout` labels). `trial_registry.py` has no standalone entry point --
`record_trial()` is called by `backtest.py` after every run, append-only, no dedup (a re-run with
the same flags is a genuine additional trial in the overfitting-correction sense). See also
`research/hierarchical_dsr.py` below for the family-scoped variant of this same correction.

### `gpu_backend.py` -- CuPy GPU acceleration, auto-detected
Not standalone. `gpu_backend.should_use_gpu(n)` -- auto-enables GPU correlation-matrix
computation above `n=1500` when CUDA is available with sufficient free VRAM headroom, falls back
to CPU silently otherwise. Confirmed real 2-2.8x speedup at N>=1000 on CachyOS's RTX 4080
(2026-09-21 benchmark); wired into every large one-shot correlation call, deliberately NOT into
per-block calls inside chunked-correlation inner loops (different, unbenchmarked overhead
profile).

### `reproduce.py` -- claim-to-command mapping
**Run:** `python reproduce.py --list` (see every `PAPER.md` finding mapped to the exact script/
flags that generated it) or `python reproduce.py --verify-only` (confirm outputs still exist
without re-running anything). The reproducibility chain -- use this before citing any `PAPER.md`
number to confirm it's still backed by a real, current output file.

### `run_overnight_research.py` / `run_overnight_research.ps1` -- unattended multi-script orchestration
**Run:** `python run_overnight_research.py --help` for flags (cross-platform, works on CachyOS/
Linux where PowerShell doesn't exist) or the `.ps1` version on Windows. Both write to the same
`logs/overnight/` layout and share the same `_completed_stages.txt` state file, so a run started
by one can be resumed by the other. Parallelizes the ~13 `backtest.py` variant stages as one batch
(`.py` version only).

### `scripts/pre_commit_verify.py` -- targeted pre-commit verify-suite gate
**Run:** wired as a git pre-commit hook; standalone via `python scripts/pre_commit_verify.py`.
Finds `debug/_verify_*.py` scripts relevant to staged files (filename-substring + static
import-line grep) and runs only those, blocking the commit on a real FAIL (not ERROR/environment
issues). Confirms itself against real staged changes before trusting it, not a synthetic-only
test.

### `debug/_run_all_verify.py` -- the full verify-suite runner
**Run:** `python debug/_run_all_verify.py` (all ~265 scripts, sequential, ~13-25 min depending on
machine) or `--pattern <substring>` (subset) or `--workers N` (parallel -- **only on a machine
with real memory headroom**; running the full suite in parallel OOM-killed a 16GB machine twice
in one night, 2026-09-21 -- prefer CachyOS or sequential on a constrained machine). Classifies
PASS / FAIL (real check failure) / ERROR (crashed before any check ran, or timed out -- usually a
missing local-only dependency or file, not a logic bug). `_KNOWN_SLOW_TIMEOUTS` gives a handful of
legitimately-expensive scripts (real WRDS connection, thousands of real-file checks, permutation
draws) their own longer per-script timeout so they don't need re-investigating as false ERRORs
every run.

---

## Adding a new backtest variant (the "STORM variant" pattern)

Every existing position-sizing/execution variant in `backtest.py` (`--risk-parity`,
`--storm-mm-exec`, `--storm-session-edge`, `--entry-z`, etc.) follows the same four-stage pattern.
To add a new one:

1. **CLI flag** -- add an `argparse` flag near the other `--storm-*` / `--risk-parity`
   definitions.
2. **Config override / precompute** -- if the variant needs a precomputed input (e.g.
   `compute_risk_parity_weights()` reads `trades_layer1.parquet` for per-pair volatility), compute
   it once in `main()` before constructing the engine, and pass it through as a `BacktestEngine`
   constructor argument. Never mutate global `Config` state directly -- pass overrides explicitly
   (see `--entry-z`'s `copy.copy()` pattern rather than mutating `Config.BACKTEST.ENTRY_ZSCORE` in
   place).
3. **Apply in the engine** -- the actual sizing/execution logic change goes in `BacktestEngine`'s
   position-sizing loop or cost function, gated on whether the new variant's flag/weights dict was
   passed in.
4. **Output naming** -- append a suffix to the output label (e.g. `_riskparity`) so the variant's
   `trades_*`/`summary_*`/`portfolio_*` parquet files never collide with the baseline or other
   variants.

**A swept `Config.BACKTEST` constant that's gated behind a separate CLI flag is a silent no-op if
you don't also pass that flag** -- confirmed the hard way 2026-09-21: `research/
parameter_sensitivity_screen.py`'s Tier2 sweep initially reported an exact-zero effect size for 5
of 12 constants because each one's consuming code required its own `--storm-*`/`--concentration-
cap` flag or a specific `--capital-sizing` mode that the sweep never passed. Before trusting a
sweep or comparison-arm result showing "no effect," grep the constant's actual consuming code and
confirm nothing gates it behind a flag you forgot.

Once built, add the variant to the comparison table in `PAPER.md` §7 with honest OOS numbers --
don't cherry-pick only favorable variants into the paper. If the variant is a genuine, verified
result but doesn't belong in `PAPER.md`'s tight core narrative (most won't -- see `README.md`'s
Documentation Map), it still belongs somewhere: add it to `docs/FINDINGS.md` and a one-line
pointer in `PAPER.md` §7, not silently left undocumented.

---

## `research/` scripts -- comparison arms, diagnostics, one-off investigations

**NOT part of the production pipeline.** Each tests one claim, reads existing `output/*` files
(never fetches, per the `data.py`/`analysis.py` fetch/analyze split), and typically has a matching
`debug/_verify_<name>.py` synthetic proof backing its claims. Run from the project root
(`python research/<name>.py`), not from inside `research/`. Most accept no required CLI arguments
and default to reading the current production output files; a handful take real flags (e.g.
`parameter_sensitivity_screen.py --tier2 --only <name>`, `capital_constraint_luck_check.py
--full-trades <path> --taken-trades <path>`, `fdr_threshold_sensitivity.py --alphas <floats>`) --
run `python research/<name>.py --help` or read its own argparse block to check.

| Script | What it does |
|---|---|
| `_regime_features.py` | CAMARF _regime_features.py — shared utility, NOT part of the production pipeline. Used by both research/pair_characteristics_analyzer.py and research/regime_conditional_entry_gate.py (Development.md's "Rich Regime Classification" / "PairCharacteristicsAnaly... |
| `_verify_coint_strength_series_builder.py` | debug/_verify_coint_strength_series_builder.py -- synthetic checks for research/coint_strength_series_builder.py, run BEFORE trusting it against real Tier 3 windows data. Also a real timing check against a large, many-small-groups synthetic dataset shaped l... |
| `_verify_regime_strength_vs_discovery_regime_test.py` | debug/_verify_regime_strength_vs_discovery_regime_test.py -- synthetic checks for research/regime_strength_vs_discovery_regime_test.py, run BEFORE trusting it against real segmentation/discovery data. |
| `adf_confirmatory_tier.py` | CAMARF adf_confirmatory_tier.py — comparison/diagnostic method, NOT part of the production pipeline (research/ convention: reads existing spread_series_*.parquet, never fetches, never recomputes hedge ratios). |
| `aligned_pair_loader.py` | CAMARF aligned_pair_loader.py — shared utility, NOT part of the production pipeline (but exists specifically to make exploratory/ comparison scripts match production's convention). |
| `annotate_symbol_metadata.py` | CAMARF annotate_symbol_metadata.py — reproducibility utility, NOT part of the production pipeline. |
| `archetype_conditional_sizing.py` | CAMARF research/archetype_conditional_sizing.py — comparison/diagnostic script, NOT part of the production pipeline (2026-07-14, task #45). |
| `asset_volatility_profile.py` | research/asset_volatility_profile.py -- per-asset historical-volatility profile (Ross's queued item: "historical volatility of asset for asset profile... maybe average daily volatility"). |
| `audit_price_degeneracy.py` | CAMARF audit_price_degeneracy.py — universe-wide scan for BUG-D49's thin-information-content pattern (Development.md, found 2026-06-23). |
| `backtest_overfitting_detector.py` | research/backtest_overfitting_detector.py -- the backtest-overfitting-detector application flagged (not built) in Finding #55, per Ross's own notes on Breeden-Litzenberger: "and also a backtest overfitting detector." |
| `bayesian_pair_confirmation.py` | research/bayesian_pair_confirmation.py -- Ross's direct request (2026-07-22): "add the bayesian confirmation as comparison" (dedicated_pass.md sec 11.5). |
| `bertram_ou_thresholds.py` | CAMARF bertram_ou_thresholds.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `beta_weighted_portfolio.py` | research/beta_weighted_portfolio.py -- Phase 3 of the new backlog (Ross: "for the beta weighting let's use SPY and compare both hedge and report only"). |
| `bh_fdr_dependence_check.py` | research/bh_fdr_dependence_check.py -- tests whether CAMARF's per-timeframe Benjamini-Hochberg (1995) FDR correction (analysis.py's `_benjamini_hochberg`, applied once per timeframe across all correlation-pre-filtered candidate pairs) has its independence/P... |
| `bh_vs_by_full_universe.py` | research/bh_vs_by_full_universe.py -- completes the BH-vs-Benjamini-Yekutieli comparison that research/bh_fdr_dependence_check.py could not finish, because the only persisted candidate file (output/results/1hr/all_candidates.parquet) already contains only B... |
| `bh_vs_by_full_universe_1d.py` | research/bh_vs_by_full_universe_1d.py -- the corrected-scale re-run PAPER_MAGNITUDE.md §10 flagged as "the single most important item" before §7.1's BH-vs-Benjamini-Yekutieli claim is scale-complete. Ross approved building this 2026-09-08. |
| `bias_budget.py` | research/bias_budget.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `big_move_lead_lag.py` | CAMARF research/big_move_lead_lag.py — comparison/diagnostic script, NOT part of the production pipeline (2026-07-14, task #69 Piece C, built per Ross's direction: generalize earnings_lead_lag.py's earnings-window conditioning to ANY large, volatility-stand... |
| `bounded_lookback_primary_screen.py` | CAMARF bounded_lookback_primary_screen.py — research script, NOT part of the production pipeline. |
| `breakout_vs_reversion.py` | CAMARF research/breakout_vs_reversion.py — comparison/diagnostic script, NOT part of the production pipeline (2026-07-14, task #55). |
| `bug_d45_decoupled_std_retest.py` | research/bug_d45_decoupled_std_retest.py -- Ross's direct request (2026-08-13): "the bug d45 is a single case and should be retested." BUG-D45 (Development.md) found that decoupling the z-score's std window (shorter, more vol-responsive: OU_WINDOW_HALFLIFE_... |
| `build_comparison_arm_pairs.py` | research/build_comparison_arm_pairs.py -- Thread A Step 4 of the PIT-safe episodic pair-confirmation comparison-arm plan (C:\Users\RossW\.claude\plans\ancient-mixing-feather.md). |
| `build_symbol_permno_map.py` | research/build_symbol_permno_map.py -- thin CLI wrapper. The actual logic (cached_wrds_symbols, build_symbol_permno_map) was consolidated into data_wrds.py on 2026-08-20 (Thread O software optimization audit) per that file's own scope statement ("ALL WRDS d... |
| `build_wrds_supplementary_data.py` | research/build_wrds_supplementary_data.py -- thin CLI wrapper. The actual fetch logic (fetch_fama_french, fetch_compustat_fundamentals) was consolidated into data_wrds.py on 2026-08-20 (Thread O software optimization audit) per that file's own scope stateme... |
| `capital_constraint_luck_check.py` | research/capital_constraint_luck_check.py -- tests whether a `--capital-sim` run's TAKEN trade subset is a meaningfully different (better/worse) population than what got SKIPPED for lack of capital, or than a random same-size draw from the full unconstraine... |
| `capital_sim_selection_mechanism.py` | capital_sim_selection_mechanism.py — root-causes why capital-constrained backtests (portfolio_sim.py's replay_portfolio(), "fixed" sizing) report a HIGHER Sharpe than the unconstrained headline (5.80 IS), across every account tier tested (7.19-10.44). |
| `capital_size_sweep.py` | research/capital_size_sweep.py -- systematic sweep of backtest.py's --capital-account-size against a fixed pairs-override/gate combination, to properly characterize the capital_sim headline-metric question flagged repeatedly during the 2026-09-15/16 squeeze... |
| `caviar_dynamic_var.py` | research/caviar_dynamic_var.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `ccp_variants.py` | CAMARF ccp_variants.py — three constrained extensions to idea #3's basket-weight optimizer (Development.md Session 10, 2026-06-23 follow-up), compared against each other and the existing OLS baseline via the same strict walk-forward protocol as predictabili... |
| `coint_decay_rate_signal_test.py` | research/coint_decay_rate_signal_test.py -- Phase 2 of the discovery-event research program (Ross, 2026-09-03): does a pair's continuous cointegration-strength trajectory -- built in Phase 1b (research/coint_strength_series_builder.py, output/research/coint... |
| `coint_frac_window_grid.py` | CAMARF coint_frac_window_grid.py — exploratory diagnostic, NOT part of the production pipeline. |
| `coint_strength_bar_system.py` | research/coint_strength_bar_system.py -- Phase 2b of the discovery-event research program (Ross: "a coint-% bar system with entry/exit rules mirroring price-bar convention"), building directly on Phase 2's confirmed signal (Finding #49: elevated coint_stren... |
| `coint_strength_series_builder.py` | research/coint_strength_series_builder.py -- Phase 1b of the discovery- event/correlation-transition research program (2026-09-03, Ross: "instead of coint and not_coint we measure it as a %... systems just like how we use for bars, but applied to coint % fo... |
| `cointegration_regime_segmentation.py` | research/cointegration_regime_segmentation.py -- Thread J Test 2 (regime segmentation), the piece explicitly flagged in the master plan file as needing a concrete design pass before implementation, per Ross's own "if something hasn't been scoped, scope it f... |
| `comomentum.py` | CAMARF comomentum.py — research/comparison script, NOT part of the production pipeline. |
| `comparison_arm_scaffold.py` | research/comparison_arm_scaffold.py — mandatory walk-forward scaffold for research/ comparison-arm scripts that FIT something (weights, a model, a threshold) and then SCORE its performance. |
| `confidence_score_allocation.py` | research/confidence_score_allocation.py -- Phase 4 (the last, most architecturally significant item) of the new backlog: "confidence score as filter, then position allocation. max points in each category = 100%." |
| `confirmatory_cointegration_check.py` | research/confirmatory_cointegration_check.py -- Ross's direct request (2026-07-20), following the 4-method FDR comparison (research/fdr_method_comparison.py) which showed NONE of the 8 previously-flagged non-DD pairs survive ANY of 4 multiple- testing corre... |
| `confirmed_pairs_contamination_followup.py` | research/confirmed_pairs_contamination_followup.py -- targeted follow-up, NOT part of the production pipeline (2026-09-01). |
| `convex_portfolio_construction.py` | research/convex_portfolio_construction.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `copula_pairs.py` | CAMARF copula_pairs.py — comparison/diagnostic, NOT part of the production pipeline. |
| `corporate_actions_audit.py` | research/corporate_actions_audit.py — spot-check that data.py's corporate- actions handling (yfinance auto_adjust=True, set at data.py:1698,1782,1994) is actually behaving correctly on real data, not just requested. |
| `correlation_transition_detector.py` | research/correlation_transition_detector.py -- Phase 1 of the discovery- event/no-correlation-signal research program (2026-09-03, scoped with Ross: "combine no-correlations for a signal" / "combine with correlated for signals", both selected as "extend the... |
| `crisis_regime_cluster_bootstrap_test.py` | research/crisis_regime_cluster_bootstrap_test.py -- does the crisis-vs-calm confirmation-rate gap (0.248% vs 0.146%, pooled two-proportion z=2.77, p=0.0056) survive once crisis-first pairs' episode-clustering is accounted for properly, via a cluster bootstr... |
| `crisis_regime_concentration_significance_test.py` | research/crisis_regime_concentration_significance_test.py -- is the "top 2 of 12 crisis episodes carry 93.1% of confirmations" concentration itself just what a small, right-skewed count distribution produces by chance, or is it genuinely surprising given ea... |
| `crisis_regime_correlation_diagnostic.py` | research/crisis_regime_correlation_diagnostic.py -- does a candidate pair's FIRST qualifying correlation window falling in a high-VIX regime predict anything different about its downstream cointegration behavior? |
| `crisis_regime_credit_proxy_comparison.py` | Tier B item #9 of the 2026-09-08 caveat/limitation search: does §5's regime-conditional confirmation pattern hold under a DIFFERENT regime classifier (BAA10Y credit-spread proxy) instead of VIX alone? The paper's own §10 named this explicitly: "test whether... |
| `crisis_regime_episode_clustering_check.py` | research/crisis_regime_episode_clustering_check.py -- does the crisis-vs-calm confirmation-rate and reappearance-rate result from crisis_regime_correlation_ diagnostic.py survive once crisis-first pairs are grouped into distinct historical EPISODES instead ... |
| `crisis_regime_same_sector_test.py` | research/crisis_regime_same_sector_test.py -- does the crisis-regime persistence effect (§5) hold up similarly for SAME-SECTOR pairs as for CROSS-SECTOR pairs? A same-sector-only restriction is one way to partially address the factor-co-movement confound §5... |
| `crisis_regime_survivorship_confound_test.py` | §5's survivorship-of-crisis-discovered-pairs confound — Tier A item #2 of the 2026-09-08 caveat/limitation search. Real, disclosed scope limit BEFORE running anything: this project's WRDS subscription only has a point-in-time membership product for the S&P ... |
| `cross_listing_lead_lag.py` | research/cross_listing_lead_lag.py -- tests whether the SAME underlying company's price on one exchange listing predicts its own price on a DIFFERENT exchange listing, added 2026-07-27 per Ross's direct request: "i also want to test if assets on one exchang... |
| `cross_session_leadlag.py` | CAMARF cross_session_leadlag.py — exploratory diagnostic, NOT part of the production pipeline. |
| `cross_tf_break_divergence.py` | CAMARF research/cross_tf_break_divergence.py -- comparison/diagnostic script, NOT part of the production pipeline (2026-08-04). |
| `cross_tf_lead_lag_scan.py` | research/cross_tf_lead_lag_scan.py -- combined lead-lag + cross-timeframe pair-discovery methodology (built 2026-08-11, Ross's direct request: "there should already be methodology built for combined lead lag and cross tf, if not let's build it. the test sho... |
| `cross_timeframe_cointegration.py` | CAMARF research/cross_timeframe_cointegration.py -- comparison/diagnostic script, NOT part of the production pipeline (2026-08-04). |
| `cross_timeframe_divergence.py` | CAMARF research/cross_timeframe_divergence.py — comparison/diagnostic script, NOT part of the production pipeline (2026-07-14, task #54). |
| `cycle_detection.py` | CAMARF research/cycle_detection.py — comparison/diagnostic script, NOT part of the production pipeline (2026-08-02). |
| `data_contamination_scan.py` | Universe-wide data-contamination scan (task #51, 2026-07-13). |
| `dcc_garch_pymgarch_comparison.py` | research/dcc_garch_pymgarch_comparison.py -- comparison/diagnostic script, NOT part of the production pipeline (2026-09-01). |
| `dd_hub_effective_bets.py` | CAMARF dd_hub_effective_bets.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `decay_rate_at_entry_diagnostic.py` | research/decay_rate_at_entry_diagnostic.py -- Thread Q decay-rate path, step 1 (scoped 2026-08-24 in Development.md): does a decay-rate signal AT TRADE ENTRY correlate with real trade outcome? Answered BEFORE building the sizing/gating mechanism around it, ... |
| `decay_rate_signals.py` | research/decay_rate_signals.py -- Thread Q new path: cointegration decay-RATE signals (2026-08-24 scoping, see Development.md). Not the LEVEL of a relationship (coint_fraction_rolling_t itself, or age since onset -- Thread Q Idea 1's compute_regime_age_weig... |
| `decoupling_analysis.py` | CAMARF decoupling_analysis.py — exploratory diagnostic, NOT part of the production pipeline. |
| `decoupling_backtest.py` | CAMARF decoupling_backtest.py — exploratory diagnostic, NOT part of the production pipeline. |
| `decoupling_contamination_crosscheck.py` | decoupling_contamination_crosscheck.py — task #70 (2026-07-14). |
| `decoupling_meta_analysis.py` | research/decoupling_meta_analysis.py -- Phase 3 of the discovery-event research program (Ross: "run a properly-scoped meta-analysis of related null results"). Targets the existing decoupling chain (decoupling_analysis.py -> decoupling_requalification.py -> ... |
| `decoupling_requalification.py` | CAMARF decoupling_requalification.py — exploratory diagnostic, NOT part of the production pipeline. |
| `degenerate_column_audit.py` | research/degenerate_column_audit.py -- Scans real output parquet files for degenerate numeric columns (100% NaN, all-zero, zero-variance, or suspiciously high NaN rate) that silently produce wrong-looking-right results downstream, the exact failure shape th... |
| `descriptive_check_concordance.py` | research/descriptive_check_concordance.py -- comparison/diagnostic script, NOT part of the production pipeline. Built 2026-07-21, completing the part of the filter-relevance sweep the failed fork never reached ("Hurst/half-life/ ADF/permutation concordance ... |
| `diversification_basket_test.py` | research/diversification_basket_test.py -- Phase 4 (part A) of the discovery-event research program (Ross: build a "diversification-basket signal" from currently-uncorrelated pairs, tested with/without comparison arms against a correlated basket and a rando... |
| `durability_vs_currency_wrds.py` | research/durability_vs_currency_wrds.py -- Re-derives PAPER.md §4.2's durability-vs-currency demonstration (NTRS/STT, SHW/UNP: full-sample EG significance vs. last-5-years-only EG significance) on real WRDS/CRSP data, replacing the original pre-WRDS (yfinan... |
| `earnings_lead_lag.py` | CAMARF research/earnings_lead_lag.py — comparison/diagnostic script, NOT part of the production pipeline (2026-07-14, task #69 Piece B, built per Ross's explicit direction: "earnings as a lead-lag arbitrage signal between legs"). |
| `earnings_structural_break_correlation.py` | CAMARF research/earnings_structural_break_correlation.py — comparison/ diagnostic script, NOT part of the production pipeline (2026-07-14, task #69 Piece A, built alongside Piece B per Ross's explicit request "let's also do A for comparison"). |
| `eg_null_calibration_montecarlo.py` | CAMARF eg_null_calibration_montecarlo.py — exploratory diagnostic, NOT part of the production pipeline. |
| `eg_permutation_check.py` | CAMARF eg_permutation_check.py — comparison/robustness method, NOT part of the production pipeline. |
| `eigenvalue_weighted_position_sizing.py` | CAMARF eigenvalue_weighted_position_sizing.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `episodic_duration_degree_usability.py` | research/episodic_duration_degree_usability.py -- Thread B of the CAMARF master plan (C:\Users\RossW\.claude\plans\ancient-mixing-feather.md). |
| `episodic_pairs_adapter.py` | research/episodic_pairs_adapter.py -- Step 3 of the PIT-safe episodic pair-confirmation comparison-arm plan (C:\Users\RossW\.claude\plans\ancient-mixing-feather.md). |
| `episodic_window_size_sweep.py` | research/episodic_window_size_sweep.py -- Thread J Test 1 / Thread G-Full Tier 4: sweeps EPISODIC_WINDOW_BARS (Ross's concern, 2026-08-13: "i'm not sure the 10 year equivalent of bars is the best target for cointegration because different assets will be coi... |
| `era_decay_replication.py` | CAMARF era_decay_replication.py — exploratory diagnostic, NOT part of the production pipeline. |
| `event_study_framework.py` | research/event_study_framework.py -- Thread L: local event-study framework, mirroring gs-quant's timeseries.event_study pattern (frame_timeseries_around_ events / event_impact_analysis: "detect event dates, frame a series' response around them") but using C... |
| `ewma_zscore_comparison.py` | research/ewma_zscore_comparison.py -- comparison arm testing an EWMA-based alternative to SpreadModel.rolling_zscore's flat-rolling-window z-score, inspired by gs_quant.timeseries.technicals.exponential_spread_volatility (2026-08-13, Ross: "let's implement ... |
| `fama_french_risk_decomposition.py` | research/fama_french_risk_decomposition.py -- Thread F Part A of the WRDS supplementary data integration plan (C:\Users\RossW\.claude\plans\ancient-mixing-feather.md). |
| `fdr_method_comparison.py` | research/fdr_method_comparison.py -- Ross's direct request (2026-07-16), after the confirmed-pair-set bug sweep proved the current step-up BH-FDR procedure is correctly implemented but mechanically sensitive to a supporting-chain gap (Development.md, "Ross ... |
| `fdr_threshold_sensitivity.py` | research/fdr_threshold_sensitivity.py -- backlog item #3 (2026-09-15 20:14 entry): "Test whether tightening the episodic-confirmation FDR threshold shrinks the 1,375-pair Purity pool toward the Baseline/Tiered set's positive result." Two independent literat... |
| `fill_timing_sensitivity.py` | research/fill_timing_sensitivity.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `filter_ablation.py` | CAMARF filter_ablation.py — exploratory diagnostic, NOT part of the production pipeline. |
| `filter_relevance_sweep_1h.py` | research/filter_relevance_sweep_1h.py — comparison/diagnostic script, NOT part of the production pipeline. |
| `financial_turbulence_index.py` | research/financial_turbulence_index.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `follower_direction_validation.py` | CAMARF follower_direction_validation.py — research/comparison script, NOT part of the production pipeline. |
| `full_universe_correlation_prefilter.py` | research/full_universe_correlation_prefilter.py -- Thread P / Ross's "go for it" (2026-08-14): runs the memory-bounded UniverseFilter.run_chunked() against the FULL merged universe (universe_loader.py: yfinance + WRDS US + WRDS international + Binance + IBK... |
| `full_universe_eg_confirmation.py` | research/full_universe_eg_confirmation.py -- Thread P / pipeline cascade stage 2: runs the EXISTING, fully-rigorous EG-cointegration + BH-FDR pipeline (analysis.py::CointScanner.scan(), unmodified) against the 18,450 candidates surviving the full-universe c... |
| `full_us_market_price_fetch.py` | research/full_us_market_price_fetch.py -- Thread K Part 1: full daily price history for CRSP's ENTIRE historical US common-stock universe (2026-08-13, Ross: "let's make sure we also get the entire US market and all what assets we're when and where at what t... |
| `fundamental_pair_tagger.py` | research/fundamental_pair_tagger.py -- Thread F Part B of the WRDS supplementary data integration plan (C:\Users\RossW\.claude\plans\ancient-mixing-feather.md). |
| `gpu_batched_eg_fixed_lag.py` | research/gpu_batched_eg_fixed_lag.py -- benchmark/comparison-arm script, NOT the production implementation (that lives in analysis.py::_batched_eg_fixed_lag_tstat, wired into _rolling_coint_worker and expanding_coint_fraction, 2026-08-23). This script exist... |
| `graph_clustering.py` | CAMARF graph_clustering.py — comparison method, NOT part of the production pipeline. |
| `graphical_lasso_clusters.py` | research/graphical_lasso_clusters.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `grid_bootstrap_ar_ci.py` | CAMARF grid_bootstrap_ar_ci.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `hedge_blend_test.py` | research/hedge_blend_test.py -- Phase 4 (part B) of the discovery-event research program (Ross: "blend correlated-pair trades with uncorrelated-asset hedging", tested with/without comparison arms to find optimal parameters, not a single fixed design). |
| `hierarchical_dsr.py` | research/hierarchical_dsr.py -- Hierarchical / family-based Deflated Sharpe Ratio correction. |
| `hmm_gmm_regime_trade_features.py` | CAMARF hmm_gmm_regime_trade_features.py -- research/comparison script, NOT part of the production pipeline. |
| `hmm_regime_detection.py` | CAMARF hmm_regime_detection.py — research/comparison script, NOT part of the production pipeline. |
| `hub_leg_stop_conditioning.py` | CAMARF research/hub_leg_stop_conditioning.py — comparison/diagnostic script, NOT part of the production pipeline (2026-07-14, task #62). |
| `international_liquidity_filter.py` | research/international_liquidity_filter.py -- Step 2 of Ross's request (2026-08-12): "run a test to see which tickers have actually liquid values and then use those. we run it once entirely then we have a filtered list." |
| `intraday_episodic_scan.py` | research/intraday_episodic_scan.py -- Step 2 of the PIT-safe episodic pair-confirmation comparison-arm plan (C:\Users\RossW\.claude\plans\ancient-mixing-feather.md). |
| `intraday_episodic_window_sensitivity.py` | research/intraday_episodic_window_sensitivity.py -- Step 1 of the PIT-safe episodic pair-confirmation comparison-arm plan (C:\Users\RossW\.claude\plans\ancient-mixing-feather.md). |
| `inverse_polarity.py` | CAMARF research/inverse_polarity.py -- comparison/diagnostic script, NOT part of the production pipeline (2026-08-03). |
| `investigate_price_degeneracy_cause.py` | CAMARF investigate_price_degeneracy_cause.py — research script, NOT part of the production pipeline. |
| `jkp_factor_portfolio_construction.py` | research/jkp_factor_portfolio_construction.py -- Thread M Option A: builds real long-short factor-mimicking portfolios from `contrib_global_factor. global_factor` (the published Jensen/Kelly/Pedersen global factor dataset, confirmed real and comprehensive, ... |
| `jkp_raw_characteristic_regression.py` | research/jkp_raw_characteristic_regression.py -- Thread M Option B: simpler raw-characteristic regression, built alongside Option A (jkp_factor_ portfolio_construction.py) per Ross's explicit request (2026-08-13): "A stands out more to me but B is also ok, ... |
| `jkp_thread_m_driver.py` | research/jkp_thread_m_driver.py -- Thread M's actual purpose: regress CAMARF's real, realized Step 5 backtest-arm returns (output/research/step5_arm_results/ real_*_trades_capsim.parquet) against both Option A's long-short JKP factor portfolios and Option B... |
| `johansen_basket_cointegration.py` | research/johansen_basket_cointegration.py -- comparison/diagnostic script, NOT part of the production pipeline (2026-09-01). |
| `jump_diffusion_parameter_fit.py` | research/jump_diffusion_parameter_fit.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `jump_diffusion_spread_analysis.py` | research/jump_diffusion_spread_analysis.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `k_bahc_candidate_discovery.py` | research/k_bahc_candidate_discovery.py -- comparison/diagnostic script, NOT part of the production pipeline. Built 2026-07-21 per Ross's explicit direction ("let's aim them toward building new application work... start work on k-bahc"), motivated by the pai... |
| `k_bahc_covariance_cleaning.py` | CAMARF research/k_bahc_covariance_cleaning.py — comparison/diagnostic script, NOT part of the production pipeline (2026-07-14, task #58). |
| `kalman_slope_intercept.py` | CAMARF kalman_slope_intercept.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `lag_aware_cointegration_discovery.py` | CAMARF lag_aware_cointegration_discovery.py -- exploratory diagnostic, NOT part of the production pipeline. |
| `lag_sweep_validation.py` | CAMARF lag_sweep_validation.py — methodology validation, NOT part of the production pipeline. Task #52 (2026-07-13). |
| `lead_lag_cointegration_rate.py` | CAMARF research/lead_lag_cointegration_rate.py -- exploratory diagnostic, NOT part of the production pipeline. |
| `lead_lag_permutation_check.py` | CAMARF lead_lag_permutation_check.py — comparison/robustness method, NOT part of the production pipeline. |
| `lead_lag_scan.py` | CAMARF lead_lag_scan.py — exploratory diagnostic, NOT part of the production pipeline. |
| `leg_level_early_exit.py` | CAMARF research/leg_level_early_exit.py — comparison/diagnostic script, NOT part of the production pipeline (2026-07-14, task #60). |
| `levy_jump_diffusion.py` | CAMARF research/levy_jump_diffusion.py — comparison/diagnostic script, NOT part of the production pipeline (2026-08-02). |
| `liquidity_bar_masking.py` | research/liquidity_bar_masking.py -- shared bar-level liquidity utility, per Ross's direct request (2026-08-14): "skip trades and avoid use of illiquid bars. counting illiquid bars will falsely spike our cointegration number." |
| `liquidity_bar_vs_symbol_comparison.py` | research/liquidity_bar_vs_symbol_comparison.py -- Thread I follow-up (Ross, 2026-08-14): "run a test comparing just dropping illiquid bars vs all bars (if it's above ADV)." |
| `liquidity_threshold_sensitivity.py` | research/liquidity_threshold_sensitivity.py -- Thread I follow-up (Ross, 2026-08-14): "let's do a test to see what level actually filters out the proper amount of assets, ensuring liquid stocks." |
| `lit_search_tools.py` | research/lit_search_tools.py -- Reusable literature-search library for the Scope 2 citation-graph-driven research methodology (see docs/HANDOFF.md's 2026-09-10 entry for the design rationale and Development.md Session 26, 2026-07-02, for the original web-se... |
| `lo2002_sharpe_correction.py` | Applies the verified Lo (2002) Sharpe-autocorrelation correction to CAMARF's actual reported portfolio Sharpe ratios, using the real daily P&L series from `output/backtest/trades_layer1*.parquet` -- not a synthetic replication (that already exists and passe... |
| `lstm_attention_architecture.py` | research/lstm_attention_architecture.py -- Ross's direct request (2026-07-22): "add the architecture for LSTM/attention but don't use it in actual backtesting" (dedicated_pass.md sec 11.8). |
| `lstm_attention_training.py` | research/lstm_attention_training.py -- the real training run `research/lstm_attention_ architecture.py` was deliberately built to wait for. That module's own docstring (2026-07-22, Ross: "add the architecture for LSTM/attention but don't use it in actual ba... |
| `market_wide_cointegration_decay.py` | research/market_wide_cointegration_decay.py -- Scope 2 from Ross's 2026-08-23 request: is the RATE/DENSITY of cointegration across the whole universe declining over calendar time? A genuine gap, distinct from the already-done Do & Faff (2010) era-decay repl... |
| `midas_cross_asset_lead_lag.py` | CAMARF research/midas_cross_asset_lead_lag.py — comparison/diagnostic script, NOT part of the production pipeline (2026-07-14, task #56). |
| `midas_feature.py` | CAMARF midas_feature.py — comparison method, NOT part of the production pipeline. |
| `ml_lookahead_selftest.py` | Mechanical lookahead self-test for ml.py's meta-labeler (Development.md second-pass triage item #5, flagged Session 27 bias-literature review, reconfirmed still absent Session 28: "lag every feature by one bar, confirm performance degrades"). |
| `ml_model_comparison.py` | research/ml_model_comparison.py -- Ross's direct request (2026-07-22): "let's add all the ML things as comparison and only for comparison until enough data is found" (dedicated_pass.md sec 11.7). |
| `ml_stage2_ablation.py` | CAMARF ml_stage2_ablation.py — research script, NOT part of the production pipeline. |
| `multiscale_entropy.py` | research/multiscale_entropy.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `multivariate_pit_predictors.py` | (no module docstring) |
| `near_miss_lag_scan.py` | CAMARF near_miss_lag_scan.py — exploratory diagnostic, NOT part of the production pipeline. |
| `network_momentum.py` | research/network_momentum.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `news_impact_asymmetry.py` | CAMARF news_impact_asymmetry.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `options_greeks_features.py` | CAMARF research/options_greeks_features.py — comparison/diagnostic script, NOT part of the production pipeline (2026-08-02). |
| `overlap_threshold_pit_test.py` | (no module docstring) |
| `pair_characteristics_analyzer.py` | CAMARF pair_characteristics_analyzer.py — research script, NOT part of the production pipeline. |
| `pair_source.py` | research/pair_source.py -- single source of truth for "which pairs should a research/diagnostic script run against," replacing per-script hardcoded ticker lists (Ross's direction 2026-08-24: "we shouldn't be hardcoding anything... everything should be using... |
| `parameter_sensitivity_phase2_interaction.py` | research/parameter_sensitivity_phase2_interaction.py -- Thread G Phase 2: interaction study on Phase 1's real survivors (entry_zscore, hedge_method; capital_sizing_method excluded -- Phase 1 found it untestable at this universe's trade volume, see docs/FIND... |
| `parameter_sensitivity_screen.py` | research/parameter_sensitivity_screen.py -- Thread G Phase 1: one-at-a-time (OAT) sensitivity screening of backtest.py-level design parameters against the real, BUG-D112-fixed 182-pair PIT-safe Purity universe (output/research/purity_pairs.parquet). |
| `pdr_calmar_comparison.py` | research/pdr_calmar_comparison.py -- comparison/diagnostic method, NOT part of the production pipeline (task #49, 2026-07-13/14). |
| `pearson_threshold_sensitivity.py` | research/pearson_threshold_sensitivity.py -- Ross's direct request (2026-07-21, following the filter-relevance/"exogeneity" sweep): does loosening the Pearson pre-filter threshold (Config.UNIVERSE.MIN_PEARSON_CORR, currently 0.40) recover any additional con... |
| `peer_correlation_contamination_check.py` | CAMARF research/peer_correlation_contamination_check.py — comparison/ diagnostic script, NOT part of the production pipeline (2026-07-14, task #59). |
| `pipeline_contracts.py` | research/pipeline_contracts.py -- Schema/contract validation for the major intermediate artifacts scripts pass between each other. Item #2 of the 5-part bug-catching plan (docs/HANDOFF.md 2026-09-10 entry). |
| `pit_confirmation_vs_regime_interaction.py` | Does a pair's regime-context signal (§5, crisis-vs-calm discovery regime / crisis-reappearance confirmation) predict whether it survives a genuine point-in-time re-screen (§4)? PAPER.md §10's third recorded future-work candidate, approved by Ross 2026-09-08... |
| `pit_pair_discovery.py` | CAMARF research/pit_pair_discovery.py -- shared utility, NOT part of the production pipeline (2026-08-04, task #5). |
| `pit_precision_by_regime_strength.py` | research/pit_precision_by_regime_strength.py -- Thread J follow-up: does PIT confirmation's precision (Finding #23) differ by regime STRENGTH (Finding #28), not just regime presence/absence? Confirmed independent of Thread J Test 1 (window-size sweep) -- us... |
| `pit_wfa_episodic.py` | research/pit_wfa_episodic.py -- comparison arm to pit_wfa.py's negative finding (PAPER.md Section 7.3.1 / PAPER_MAGNITUDE.md Section 6): does swapping the STATIC full-history + fixed-252-bar-rolling-fraction pair- discovery method for the EPISODIC, regime-a... |
| `pit_wfa_pooled_equity_curve.py` | Pooled-across-folds headline Sharpe for pit_wfa_wrds_daily.py's corrected- scale PIT result -- PAPER_MAGNITUDE.md §4/§10's last open item on this finding. Ross approved the splicing design 2026-09-08 after an explicit methodology discussion (three real choi... |
| `pit_wfa_trade_bootstrap.py` | research/pit_wfa_trade_bootstrap.py -- bootstrap confidence interval on pit_wfa.py's fold2_exp/fold2_roll portfolio Sharpe (the real evidence behind PAPER_MAGNITUDE.md §4), which currently rests on a bare point estimate from 32 and 5 raw trades respectively. |
| `pit_wfa_wrds_daily.py` | research/pit_wfa_wrds_daily.py -- Point-In-Time Portfolio-Wide Walk-Forward Analysis on WRDS DAILY bars, full ~44,840-symbol merged universe. |
| `portfolio_effective_bets.py` | CAMARF portfolio_effective_bets.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `portfolio_position_sizing_correction.py` | research/portfolio_position_sizing_correction.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `predictability_optimizer.py` | CAMARF predictability_optimizer.py — comparison method, NOT part of the production pipeline. |
| `price_degeneracy_root_cause.py` | CAMARF price_degeneracy_root_cause.py — research script, NOT part of the production pipeline. |
| `price_density_screen.py` | CAMARF price_density_screen.py — candidate universe-construction screen, NOT yet wired into the production pipeline. Comparison method per Ross's request (2026-06-23): "daily liquidity does not equal intraday price- discovery density" (BUG-D49) — this forma... |
| `price_target_convergence_timing_test.py` | Tier B item #13 of the 2026-09-08 caveat/limitation search: the pairs- relative price-target overlay (`price_target_pairs_overlay.py`) tested one specific hypothesis -- does agreement with the analyst-implied direction predict trade P&L -- and found an hone... |
| `price_target_pairs_overlay.py` | Analyst consensus price-target overlay -- pairs-relative design, Ross approved 2026-09-08 over the literature's standalone single-name framing (Brav & Lehavy 2003, Da & Schaumburg 2011), specifically to keep this inside CAMARF's existing co-movement/pairs a... |
| `promote_full_universe_pairs.py` | research/promote_full_universe_pairs.py -- promotes research/full_universe_ eg_confirmation.py's candidate-list output (correlation+EG p-values only, 19 columns) into the PRODUCTION output/results/{tf_dir}/pairs.parquet manifest (41 columns: full per-bar sp... |
| `quantile_regression_forest.py` | research/quantile_regression_forest.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `regenerate_summary_layer1_sharpe_fix.py` | research/regenerate_summary_layer1_sharpe_fix.py -- one-time regeneration of every output/backtest/*summary*.parquet file using the corrected Sharpe annualization (backtest.py:compute_metrics, fixed 2026-09-04 -- see docs/FINDINGS.md Finding #51). |
| `regime_age_at_entry_diagnostic.py` | research/regime_age_at_entry_diagnostic.py -- Thread Q Idea 1, Path D (docs/HANDOFF.md's one-line "bullish/quick cointegration-regime timing" idea, expanded 2026-08-23 into a real menu of paths, see Development.md's Thread Q scoping entry for the other 3). |
| `regime_capital_reallocation_diagnostic.py` | research/regime_capital_reallocation_diagnostic.py -- Thread Q Idea 2, Path C (docs/HANDOFF.md's one-line "exploiting the ~90.8% non-cointegrated majority" idea, expanded 2026-08-23 into a real menu of paths, see Development.md's Thread Q scoping entry for ... |
| `regime_cluster_robustness_check.py` | CAMARF research/regime_cluster_robustness_check.py — comparison/ diagnostic script, NOT part of the production pipeline (2026-07-14, task #47). |
| `regime_conditional_analysis.py` | CAMARF regime_conditional_analysis.py — research/comparison script, NOT part of the production pipeline. |
| `regime_conditional_entry_gate.py` | CAMARF regime_conditional_entry_gate.py — research script, NOT part of the production pipeline. |
| `regime_strength_vs_discovery_regime_test.py` | research/regime_strength_vs_discovery_regime_test.py -- does a pair's cointegration-regime STRENGTH (strong/moderate/weak, from §7.2's cointegration_regime_segmentation.py) correlate with the VIX regime it was FIRST DISCOVERED in (§5's crisis_regime_correla... |
| `regime_strength_vs_pit_confirmation.py` | §4's regime-strength segmentation vs. PIT-confirmation precision -- Tier A item #7 of the 2026-09-08 caveat/limitation search. "Does a pair's regime strength (strong/moderate/weak, §7.2) predict whether it survives a genuine point-in-time re-screen?" -- PAP... |
| `reimers_trio_correction.py` | CAMARF reimers_trio_correction.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `relational_regime_indicator.py` | CAMARF research/relational_regime_indicator.py — comparison/diagnostic script, NOT part of the production pipeline (2026-07-14, task #61: CAMARF-native relational regime indicator). |
| `residual_correlation_cluster_bootstrap_test.py` | Tier A item #1 of the 2026-09-08 caveat/limitation search: does the residual-correlation-factor split (6.7% of §5-confirmed crisis-first pairs survive factor-adjustment) hold up under the SAME cluster-robust treatment already applied to the parent crisis-vs... |
| `residual_correlation_factor_test.py` | research/residual_correlation_factor_test.py -- does the crisis-regime persistence effect (Finding #41/#44, PAPER_MAGNITUDE.md §5) survive once market-wide factor co-movement is regressed out of the correlation prefilter, or is it explained away once idiosy... |
| `return_smoothing_audit.py` | CAMARF return_smoothing_audit.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `ridge_hedge_ratio_comparison.py` | research/ridge_hedge_ratio_comparison.py -- comparison arm, NOT part of the production pipeline. |
| `risk_neutral_density.py` | research/risk_neutral_density.py -- Breeden-Litzenberger risk-neutral density extraction from a LIVE option chain (Ross's request: "option prices secretly encode what the market thinks the future price will be... q(K) = e^{rT} * d2C/dK2"). |
| `rmt_feature_denoising.py` | CAMARF rmt_feature_denoising.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `rolling_adv_comparison.py` | research/rolling_adv_comparison.py -- comparison arm testing whether a FLAT, full-history average-daily-dollar-volume (ADV) liquidity filter (what `analysis.py`'s existing `_compute_adv` does today, and what `data_wrds.py`'s coarse fetch-pruning `compute_sy... |
| `rough_volatility.py` | CAMARF research/rough_volatility.py — comparison/diagnostic script, NOT part of the production pipeline (2026-08-02). |
| `sample_entropy_spreads.py` | CAMARF sample_entropy_spreads.py — research/comparison script, NOT part of the production pipeline. |
| `sector_fdr_random_null_comparison.py` | research/sector_fdr_random_null_comparison.py -- comparison/diagnostic script, NOT part of the production pipeline (2026-09-01). |
| `sector_restricted_fdr_rescan.py` | research/sector_restricted_fdr_rescan.py -- Ross's direct request (2026-07-20), the second of two follow-ups to the 4-method FDR comparison (research/fdr_method_comparison.py). Tests whether a PRE-REGISTERED, economically motivated restriction of the candid... |
| `sensitivity_research.py` | research/sensitivity_research.py -- parameter sensitivity for CAMARF's research/*.py comparison arms, matching the project's existing sensitivity.py pattern (parameter grid -> headline metric, does the finding hold or is it fragile) but applied to the resea... |
| `sequential_bootstrap_ml_comparison.py` | Comparison arm to ml.py's `_train_and_validate` baseline training scheme (sklearn's class-"balanced" sample_weight only, no overlap correction). Tests Lopez de Prado's (AFML Ch. 4) average-uniqueness weighting and sequential-bootstrap resampling on the SAME... |
| `short_term_factor_alpha.py` | research/short_term_factor_alpha.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `smoothing_comparison.py` | CAMARF research/smoothing_comparison.py — comparison/diagnostic script, NOT part of the production pipeline (2026-07-14). Built per Ross's direction: test smoothing/denoising the price series before cointegration testing, purely for comparison — not a produ... |
| `spread_construction.py` | research/spread_construction.py — shared full-sample OLS spread/z-score construction for research/ comparison scripts. |
| `squeeze_momentum_features.py` | research/squeeze_momentum_features.py -- augments existing spread_series_*.parquet files with causal squeeze_indicator and RSI-momentum columns per leg, computed fresh from the current DataStore OHLCV cache. VolumeStructure.compute_features (analysis.py) is... |
| `squeeze_momentum_signal_validation.py` | research/squeeze_momentum_signal_validation.py -- validates that the 3 squeeze/momentum STORM gates (2026-09-15) are doing something real, not just benefiting from sample-size variance. |
| `stop_loss_correlation_caps.py` | stop_loss_correlation_caps.py — two portfolio risk-management comparison arms: |
| `strategy_risk_precision.py` | CAMARF strategy_risk_precision.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `strategy_variation_comparison.py` | research/strategy_variation_comparison.py -- Ross's direct request (2026-07-21): does the stat-arb (cointegrated-spread) structure itself carry the edge, or would the SAME entry/exit/risk-management engine produce comparable risk-adjusted returns applied to... |
| `stress_test_replication.py` | research/stress_test_replication.py — honest-scope historical crisis stress test for CAMARF's confirmed pairs. |
| `structural_break_onset_detection.py` | CAMARF research/structural_break_onset_detection.py -- comparison/ diagnostic script, NOT part of the production pipeline (2026-08-04). |
| `svm_gradient_descent_classifier.py` | CAMARF research/svm_gradient_descent_classifier.py — comparison/diagnostic script, NOT part of the production pipeline (2026-08-02). |
| `tail_dependence.py` | CAMARF tail_dependence.py — gating diagnostic, NOT part of the production pipeline. |
| `tail_dependence_deep.py` | CAMARF tail_dependence_deep.py — comparison/diagnostic, NOT part of the production pipeline. |
| `tail_dependence_universe_screen.py` | research/tail_dependence_universe_screen.py -- comparison/diagnostic script, NOT part of the production pipeline. Built 2026-07-21 per Ross's explicit direction ("push on the two [k-BAHC] follow ups and do copulas"), continuing the "new application work" bu... |
| `thread_k_part2_fund_membership_fetch.py` | research/thread_k_part2_fund_membership_fetch.py -- Thread K Part 2: fund- membership fetch, run against Thread K Part 1's full US market universe (29,366 symbols, `output/cache/wrds/full_us_market_label_map.parquet`), satisfying Ross's "run thread K after ... |
| `threshold_cointegration.py` | CAMARF threshold_cointegration.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `threshold_relevance_pit_test.py` | (no module docstring) |
| `transfer_entropy_lead_lag.py` | Transfer entropy lead-lag detection -- PAPER.md §10 future-work candidate, approved by Ross 2026-09-08 alongside sequential_bootstrap_ml_comparison.py and the IBES price-target fetch. A nonlinear, information-theoretic extension of this project's existing c... |
| `trend_dominance_diagnostic.py` | CAMARF trend_dominance_diagnostic.py -- exploratory diagnostic, NOT part of the production pipeline (candidate for promotion into analysis.py's CointScanner pre-filter stage; not wired in yet, pending Ross's review of these results). |
| `trig_convergence.py` | CAMARF research/trig_convergence.py -- comparison/diagnostic script, NOT part of the production pipeline (2026-08-03). |
| `var_backtest_calibration.py` | research/var_backtest_calibration.py -- Thread N #5: VaR model backtesting/ calibration check, the first sub-arm of the regulatory-risk-convention comparison arm (ancient-mixing-feather.md Thread N). Sequenced first per that thread's own design: answers "is... |
| `variance_ratio_test.py` | CAMARF variance_ratio_test.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `vix_crisis_hl_robustness_check.py` | CAMARF research/vix_crisis_hl_robustness_check.py -- comparison/diagnostic script, NOT part of the production pipeline (2026-08-05). |
| `vol_swap_style_risk_estimate_comparison.py` | research/vol_swap_style_risk_estimate_comparison.py -- comparison arm testing a vol-swap-style (zero-mean, return-based) volatility estimator against portfolio_sim.py's current causal_rolling_std_at_entry, inspired by gs_quant.timeseries.econometrics.vol_sw... |
| `vol_targeting_and_drawdown_derisking.py` | CAMARF research/vol_targeting_and_drawdown_derisking.py — comparison/ diagnostic script, NOT part of the production pipeline (2026-07-14, task #48). |
| `wavelet_hurst_comparison.py` | CAMARF research/wavelet_hurst_comparison.py — comparison/diagnostic script, NOT part of the production pipeline (2026-07-14, task #43: a third Hurst estimator alongside analysis.py's existing R/S and DFA). |
| `weak_exogeneity_test.py` | research/weak_exogeneity_test.py — comparison/diagnostic method, NOT part of the production pipeline. |
| `wrds_capability_audit.py` | research/wrds_capability_audit.py -- one-shot, run-once-yourself script (2026-08-11, Ross: "let's also integrate the other useful data from WRDS... do a check on everything WRDS can provide me"). |
| `wrds_deep_history_episodic_scan.py` | research/wrds_deep_history_episodic_scan.py -- Ross's direct request (2026-07-27): "I refuse to believe that our current confirmed sets are correct. I believe we have way more episodic connections I want to test." |
| `wrds_global_index_universe_fetch.py` | research/wrds_global_index_universe_fetch.py -- fetch ALL populated Compustat Global national/index constituents' full historical OHLCV, per Ross's direct request (2026-08-12): "i want all of them - then we run a test to see which tickers have actually liqu... |
| `wrds_lead_lag_scan.py` | research/wrds_lead_lag_scan.py -- lead-lag scan extended to WRDS-confirmed pairs (the Tier 1/2/3 episodic scan's own output), added 2026-07-27 per Ross's direct request: "as for the international symbols we do want to do the lead lag tests we currently have." |
| `wrds_universal_lead_lag_scan.py` | research/wrds_universal_lead_lag_scan.py -- lead-lag correlation used as its OWN pair-DISCOVERY methodology across the ENTIRE WRDS universe, added 2026-07-27 per Ross's direct correction to the narrower wrds_lead_lag_scan.py build: "the lead lag should also... |

---

## `debug/_verify_*.py` -- synthetic proofs, not scratch files

One per research claim or production-code fix, run BEFORE trusting the corresponding script/
change on real data -- this project's own history is that code presented without this
verification step has had bugs, and code verified this way has not. Convention: build a synthetic
input with a KNOWN ground truth (use `debug/synthetic_pair_factory.py`'s `make_synthetic_pair` for
anything needing a synthetic cointegration/lead-lag/gap/contamination/PIT-membership/liquidity
pair -- it covers 12 independently-togglable factors and is the shared foundation this convention
is meant to build on, not a per-script bespoke generator), assert against the known answer, print
`[PASS]`/`[FAIL]` per check plus a final count, exit nonzero on any failure.

**Don't enumerate all ~265 individually here** -- each one's own module docstring states exactly
what it verifies and why, and `research/<name>.py`'s own docstring cross-references its
`debug/_verify_<name>.py` counterpart. To run one: `python debug/_verify_<name>.py`. To run
everything: `python debug/_run_all_verify.py` (see its entry in Core production pipeline above).
To find the verify script for a script you're about to modify: `python
scripts/pre_commit_verify.py` (git-staged-file-aware) or just grep `debug/` for the target
script's own filename.

---

## `debug/` -- other utility/investigation scripts (not `_verify_*`)

One-off diagnostic tools, benchmarks, and investigation scripts -- not synthetic proofs, not part
of any automated suite.

| Script | What it does |
|---|---|
| `_bench_cachy_vs_windows.py` | Cross-machine benchmark: identical CAMARF-representative compute run on Windows and CachyOS. Not a synthetic microbenchmark -- exercises the actual production functions (chunked_pearson_matrix, _batched_eg_fixed_lag_tstat) at fixed, reproducible scale. |
| `_bench_gpu_vs_cpu_correlation.py` | debug/_bench_gpu_vs_cpu_correlation.py -- real GPU-vs-CPU benchmark of UniverseFilter.chunked_pearson_matrix at multiple N, re-confirming (per Ross's direct instruction, 2026-09-20: "always test the gpu if it's better wire it in") the guidance already docum... |
| `_categorize_full_universe_window_cascade.py` | debug/_categorize_full_universe_window_cascade.py |
| `_check_cachyos_parity.py` | debug/_check_cachyos_parity.py -- reports every tracked .py file whose content differs between the local working tree and CachyOS's checkout, in one pass. Replaces the manual `scp`+`diff` ritual this project has relied on all session (found stale copies of ... |
| `_check_deep_history_eg.py` | Ad-hoc check (task #71 follow-up, 2026-07-14): does IBKR 10-year deep history restore/strengthen EG cointegration significance for the 9 formerly-confirmed 1h pairs that do NOT involve the BUG-D65/D66-contaminated symbols? |
| `_check_fele_mas_full_eg_fdr.py` | debug/_check_fele_mas_full_eg_fdr.py -- decisive final test closing out the FELE/MAS root-cause investigation. Prior steps this session established: - FELE and MAS both survive the REAL production universe-build path (UniverseBuilder().build(connect=False, ... |
| `_check_fele_mas_production_path.py` | debug/_check_fele_mas_production_path.py -- one-shot diagnostic, NOT a comparison-arm script. Reproduces the EXACT production path (UniverseBuilder().build(connect=False, fetch=False) -> _run_one_tf's own universe/exclusion/frequency-validation logic -> Dat... |
| `_check_fele_mas_universe.py` | (no module docstring) |
| `_check_ibkr_raw_depth.py` | Ad-hoc check (task #71 follow-up, 2026-07-14): what does IBKR's raw reqHistoricalData response actually contain for a 1h-bar equity request, BEFORE data_ibkr.py's merge_with_yfinance() truncates it to bars older than yfinance's own window? Settles whether t... |
| `_check_intraday_cache_coverage.py` | debug/_check_intraday_cache_coverage.py -- Step 0 of the PIT-safe episodic pair-confirmation comparison-arm plan (ancient-mixing-feather.md). |
| `_coint_frac_threshold_sensitivity.py` | Reproducible regeneration of the coint_fraction_rolling threshold sensitivity table behind config.py's Config.UNIVERSE.MIN_COINT_FRAC = 0.70 decision (see Development.md's coint_fraction_rolling section, 2026-06-22). Pulls real values from the currently-per... |
| `_exercise_bug_d57_production_fetch.py` | Real production-equivalent exercise of the BUG-D57 fix (Development.md, 2026-07-12): runs the EXACT same call sequence data.py's own main loop uses for an intraday yfinance fallback fetch -- YFinanceFeed.get_intraday_fallback() -> snap_timestamps(symbol=...... |
| `_ibkr_depth_sweep.py` | Quick live sweep (2026-07-14, Ross's request): what is IBKR's real single- request historical-data depth ceiling for IBM, PER TIMEFRAME? Task #71 only swept this for 1h equity bars (ceiling: 21-30 days, not the "10 Y confirmed" _MAX_DURATION claims). This g... |
| `_ibkr_depth_symbol_compare.py` | Follow-up to _ibkr_depth_sweep.py (2026-07-14): IBM's 1h depth sweep just found single-request success all the way to 1 Y (3906 bars), directly contradicting task #71's earlier LNT sweep (21D max, everything from 1M up timed out identically). Implausible vs... |
| `_investigate_5m_30m_gap.py` | Standalone, read-only investigation: why do 5m and 30m yield ZERO confirmed pairs while neighboring TFs (1m/3m/15m/1h) don't, even though their raw EG pass rates aren't obviously lower (see Development.md's "TF-Level Funnel Analysis" section)? Recomputes th... |
| `_live_test_ibkr_pagination.py` | Live (non-mocked) test of IBKRFeed.get_bars_paginated() (task #72, 2026-07-14). Synthetic mocks already verified the chunking/dedup/stop- condition logic (debug/_verify_ibkr_pagination.py, 4/4 pass) — this confirms the real IB Gateway round-trip actually ac... |
| `_measure_bug_d61_cutoff_gap.py` | _measure_bug_d61_cutoff_gap.py — BUG-D61 follow-up instrumentation (2026-07-12) |
| `_perf_test_universefilter.py` | Standalone verification harness for UniverseFilter correlation pre-filter optimization. READ-ONLY against output/cache/*.parquet. Does not modify analysis.py or data.py. Does not fetch any data. |
| `_rebacktest_pit_wfa.py` | One-off recovery: re-runs ONLY the backtest step of pit_wfa.py's already- completed run, reusing the point-in-time confirmed pair sets already saved in output/backtest/pit_wfa_pair_sets.parquet, after fixing backtest_pair_on_test_window's calendar-padding b... |
| `_replicate_benjamini_hochberg_fdr_control.py` | Synthetic replication of Benjamini & Hochberg (1995), "Controlling the False Discovery Rate" (JRSSB 57(1), 289-300) -- BEFORE trusting that CAMARF's own per-timeframe BH-FDR correction (`Config.STATS.FDR_ALPHA`, applied in CointScanner after every batch of ... |
| `_replicate_granger_newbold_spurious_regression.py` | Synthetic replication of Granger & Newbold (1974), "Spurious Regressions in Econometrics" (J. of Econometrics 2(2), 111-120) -- BEFORE trusting that this project's entire premise (raw OLS on nonstationary price levels is invalid, EG-style residual cointegra... |
| `_replicate_lo2002_sharpe_autocorrelation_correction.py` | Synthetic replication of Lo (2002), "The Statistics of Sharpe Ratios" (Financial Analysts Journal 58(4), 36-52) -- BEFORE using this as a basis for evaluating CAMARF's own reported Sharpe ratios (backtest.py:740, :804, both currently plain sqrt(N)-annualize... |
| `_rerun_permutation_bug_gap.py` | Re-run stats.py Section 6 (permutation test) against the CURRENT trades_layer1.parquet / trades_layer1_holdout.parquet (post BUG-D58/D59/D62 fixes, 2026-07-12), to get a fresh, traceable p-value replacing PAPER.md's untraceable Abstract figure and the stale... |
| `_run_all_verify.py` | debug/_run_all_verify.py -- runs every debug/_verify_*.py script and reports a single pass/fail/error summary, instead of the manual one-at-a-time invocation this project has relied on all along (256 verify scripts as of 2026-09-20, none previously run auto... |
| `clear.py` | (no module docstring) |
| `debug_intraday.py` | (no module docstring) |
| `debug_single.py` | (no module docstring) |
| `diagnosis.py` | (no module docstring) |
| `results.py` | (no module docstring) |
| `synthetic_diagnostics.py` | CAMARF debug/synthetic_diagnostics.py — reusable synthetic-data generator + invariant-checker library for testing pipeline and research-script methodology with KNOWN-ground-truth data (2026-07-14). |
| `synthetic_pair_factory.py` | CAMARF debug/synthetic_pair_factory.py — parameterized synthetic PAIR generator + permutation-sweep runner (2026-07-14), extending debug/synthetic_diagnostics.py's single-series generators to full PAIRS with independently-togglable, KNOWN ground-truth prope... |
| `test_sp600_isolated.py` | Fetches S&P MidCap 400 and SmallCap 600 constituent lists and seeds the cache files data.py expects. Includes retry logic: the underlying fetch logic is confirmed correct (isolated test succeeded with 579/603 tickers), but Wikipedia/network conditions have ... |

---

## Other root-level supporting modules

Not part of the "core pipeline" run sequence above, but not `research/`-scoped either --
importable utilities, one-off/legacy scripts, and secondary analysis modules living at the
project root.

| Script | What it does |
|---|---|
| `_verify_streaming_checkpoint_results.py` | debug/_verify_streaming_checkpoint_results.py -- verifies the 2026-08-26 streaming-results fix to run_rolling_eg_pool BEFORE trusting it against real, valuable (multi-million-row) Tier-3 checkpoint data. |
| `absorption_ratio.py` | absorption_ratio.py — Kritzman, Li, Page & Rigobon (2011), "Principal Components as a Measure of Systemic Risk," Journal of Portfolio Management. |
| `cvar.py` | cvar.py — Historical (non-parametric) Conditional Value at Risk / Expected Shortfall on CAMARF's portfolio-level daily P&L. |
| `data_crypto.py` | data_crypto.py — Binance.US supplemental/deep-intraday-history data pipeline for CAMARF's crypto universe (2026-08-02). ================================================================================ SEPARATE SCRIPT from data.py, mirroring data_ibkr.py/dat... |
| `data_finra.py` | CAMARF data_finra.py -- ALL FINRA data sources live in this ONE file, one file per external PROVIDER (same convention as data_wrds.py's own docstring). Free, public, no authentication -- FINRA is required by regulation to publish this, not a paid vendor. |
| `data_sec_edgar.py` | CAMARF data_sec_edgar.py -- ALL SEC EDGAR data sources live in this ONE file, one file per external PROVIDER (same convention as data_wrds.py's own docstring). Free, public, no authentication, no paywall -- SEC EDGAR is a US government disclosure system, no... |
| `decay_proxy.py` | decay_proxy.py — per-pair decay z-score, a per-run diagnostic (not live/streaming — recomputed whenever backtest.py's IS trades are refreshed, matching CAMARF's current capability; no live-trading infrastructure exists yet for true real-time monitoring). |
| `distance.py` | distance.py — Gatev-style distance method baseline |
| `earnings.py` | CAMARF earnings.py — standalone module, fetch + cache earnings announcement dates per symbol, for backtest.py's --storm-earnings-blackout STORM variant. |
| `fresh_holdout_compare.py` | fresh_holdout_compare.py — compares two candidate mechanisms for a genuinely fresh (never re-examined) holdout, per Ross's direction (2026-07-12): "For the holdout i think we should compare both and see what happens." |
| `gics.py` | gics.py — GICS sector tag builder |
| `options.py` | options.py — options-overlay comparison arm, NOT part of the core production pipeline (parallel status to distance.py/sensitivity.py: reads existing backtest output, never fetches or changes core position sizing). |
| `pit_wfa.py` | pit_wfa.py — Point-In-Time Portfolio-Wide Walk-Forward Analysis. |
| `report.py` | (no module docstring) |
| `run_storm_grid.py` | STORM factor grid: all 2^4 combinations of session_edge, garch_stop, mm_exec, and coint_frac_threshold (0.0 = off, 0.10 = filter pairs with coint_frac < 0.10). |
| `run_verify_suite.py` | run_verify_suite.py — runs every debug/_verify_*.py synthetic verification test and reports a pass/fail summary. One command in place of manually running each script whenever a statistical computation changes. |
| `seed_sp_caches.py` | Fetches S&P MidCap 400 and SmallCap 600 constituent lists directly and seeds the cache files that data.py expects, bypassing the full pipeline. |
| `sensitivity.py` | sensitivity.py — Parameter sensitivity / stability test |
| `wfa.py` | CAMARF wfa.py — Walk-Forward Analysis (semi-WFA). |

---

## Where things are validated / where biases live

- **Bias documentation:** `output/results/bias_audit.json`. Every known bias (survivorship, Kelly
  lookahead, in-sample stop comparison, small-n filtering) has a mechanism/remedy/residual-risk
  entry. If you find a new one, add an entry -- don't silently correct it away in the code without
  documenting what was there before and why it changed.
- **Synthetic verification tests:** `debug/_verify_*.py`, see above.
- **Reproducibility chain:** `reproduce.py` maps every `PAPER.md` finding to the exact
  script/flags that generated it (`--list` to see the mapping, `--verify-only` to confirm outputs
  still exist without re-running anything).

---

## Standing project principles (see `CLAUDE.md` for the full statement)

- **Any script claiming universe-wide/"full universe" coverage must load via `universe_loader.
  py`'s `load_full_universe()`** (the real ~44,700-symbol WRDS-merged universe), never a private
  glob of `Config.DATA.CACHE_DIR` (the old ~1,700-symbol yfinance-only cache) or any other bespoke
  loader. This exact bug -- a script quietly reinventing its own smaller-scope universe loader --
  has recurred independently at least 13 times across this project's history (see
  `Development.md`'s 2026-08-24 and 2026-09-01 entries); check `docs/HANDOFF.md`'s most recent
  universe-consistency audit before assuming a new script is exempt.
- No bandaid fixes -- find the single correct root-cause fix, verified with a synthetic
  reproduction, not the first thing that makes a symptom go away.
- New methodology/design ideas get discussed (what it is, why it's relevant, the tradeoffs)
  before being built -- this project is a learn-as-you-go research thesis, not a black-box
  execution exercise.
- Confidence scores, Sharpe ratios, and reliability ratings are never inflated to make a result
  look stronger than the evidence supports. If a finding is genuinely contested in the literature
  or the data, report that honestly rather than engineering around it.
- **One CachyOS job at a time, always check `ps aux` first.** RAM-heavy work belongs on CachyOS,
  never the Surface. CachyOS's default shell is fish -- write multi-line/loop commands to a file
  and `scp`+`ssh host bash script.sh`, never inline a bash `for`/`if` block over SSH.
