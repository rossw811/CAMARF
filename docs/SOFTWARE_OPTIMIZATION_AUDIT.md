# CAMARF Software/Workflow Optimization Audit (2026-08-20)

**Status: FINDINGS ONLY — no code changed.** Complements `docs/HARDWARE_OPTIMIZATION_PLAN.md`
(hardware/GPU/storage). This covers everything else: code architecture, orchestration, testing,
config, tooling. Every finding below is grounded in real `grep`/`glob`/file counts against the
actual repo, not estimated.

---

## 1. Redundant/duplicated code across research/ scripts

**Real, quantified finding**: `_setup_logging()` is defined **30 separate times** across
`research/*.py`, and the 3 checked directly (`fdr_method_comparison.py`,
`pearson_threshold_sensitivity.py`, `tail_dependence_universe_screen.py`) are byte-identical
except the log filename string. This is pure boilerplate — same `Formatter`, same
`StreamHandler`+`FileHandler` setup, same levels — that could be one shared
`research/_logging_utils.py::setup_logging(log_name, extra_suffix=None)` call. **Value: real but
modest** — doesn't cause bugs (unlike the `load_full_universe` duplication this session already
fixed), just 30x maintenance surface for a 12-line function. Worth doing opportunistically
(next time a script in this list gets touched anyway), not a standalone priority.

**A second, still-live duplication of the exact same class already partially fixed this
session**: 5 more scripts (`coint_frac_window_grid.py`, `eg_null_calibration_montecarlo.py`,
`lag_aware_cointegration_discovery.py`, `near_miss_lag_scan.py`,
`ridge_hedge_ratio_comparison.py`) each carry their own local timeframe-suffix dict (the
`{"1h": "1hr", ...}` pattern), separate from the 4 scripts already rewired onto
`universe_loader.py`'s canonical loader this session. **Real risk, not just tidiness**: this is
the exact bug class (`_TF_SAFE`-style duplication) that caused k-BAHC to silently scope itself to
the wrong universe for weeks before this session caught it. **Value: real, same severity class as
the already-fixed bugs** — worth an explicit audit pass to confirm none of these 5 also have the
deeper "reads only the old yfinance cache" bug, not just the dict duplication itself.

**RESOLVED, 2026-08-20 -- checked each of the 5 directly.** 4 of 5 (`coint_frac_window_grid.py`,
`lag_aware_cointegration_discovery.py`, `near_miss_lag_scan.py`,
`ridge_hedge_ratio_comparison.py`) do NOT have the deeper bug -- they source data via
`aligned_pair_loader.load_aligned_pair` (a shared, canonical PER-PAIR loader) or call
`DataAligner.align_universe` directly, not a from-scratch universe-wide directory scan. The
`_TF_SAFE`-style dict duplication is real tidiness debt in these 4, but not the "silently wrong
universe scope" risk the audit worried about.

**The 5th, `eg_null_calibration_montecarlo.py`, DOES have the real bug** -- `CACHE_DIR =
"output/cache"` (line 49), glob-scanning the old yfinance-only cache directly, confirmed via
`symbols_for_suffix()`/`load_log_close()`. **Higher stakes than the other fixes made this
session**: this script's own output is already cited as a headline, published result in
`PAPER.md` §4.2.1 (the Monte Carlo null-calibration finding -- "empirical false-positive rate
under a genuine null is elevated... 7.75%-12.75%"). Rewiring its universe source and re-running
would change an already-published number, not just fix a research tool. **Deliberately NOT
touched** -- flagged here for Ross's explicit decision (rewire + re-run, producing a new number
that would need to flow back into PAPER.md's own claim; or leave the published finding as-is,
scoped to the old universe, and disclose that scope explicitly if it isn't already) rather than
silently changed, per this project's own "new methodology / published-claim changes need
discussion first" rule.

**Thread O — DONE (2026-08-20).** Consolidated all 3 "strong candidate" WRDS scripts into
`data_wrds.py`, per that file's own scope statement ("ALL WRDS data sources live in this ONE
file, one file per external PROVIDER"). Purely mechanical, literal moves — no logic changed:
- `build_symbol_permno_map.py` → `cached_wrds_symbols()` + `build_symbol_permno_map()` moved in
  full; the research script is now a ~25-line thin CLI wrapper.
- `build_wrds_supplementary_data.py` → `fetch_fama_french()` + `fetch_compustat_fundamentals()`
  moved in full; the research script is now a thin CLI wrapper retaining its own scoping
  docstring.
- `wrds_global_index_universe_fetch.py` → only the 2 genuine fetch/connection-layer primitives
  moved (`discover_populated_indices()`, and `_connect_with_retry()` renamed
  `connect_with_retry_global()` since it's now a shared utility, not script-local).
  `discover_and_build_manifest()` and `main()` stayed in `research/` as orchestration/CLI, per
  this file's own "one file per external PROVIDER" scope — they aren't fetch logic.

None of the 3 could be live-tested (all require interactive WRDS Duo 2FA, an established
constraint of this project) — verified via `ast.parse` syntax check and a plain `import`
check on all 3 rewired scripts plus `data_wrds.py` itself; all pass. **Live functional
verification (that a real WRDS run still produces identical output) remains Ross's
responsibility**, same as before this move — nothing about that changed, only where the code
lives.

## 2. Script orchestration / workflow

`run_overnight_research.ps1` (and the other 6 `run_*.ps1` runners) sequence **47 script
references** and confirmed **zero real parallelism** — no `ForEach-Object -Parallel`, no
`Start-Job` fan-out found anywhere in the file; every stage runs strictly sequentially via
`Start-Process ... -Wait`-style invocation. On the OLD 16GB/limited-core Windows box this was a
defensible, conservative choice (this session's own OOM history shows why). **On CachyOS (8 real
cores, 46.9GB RAM) this is a real, quantifiable opportunity**: many of the ~120+ research scripts
in the overnight run have no data dependency on each other (they read the same cached universe,
run independent statistical tests, write independent output files) — running 4-6 independent,
memory-light research scripts concurrently instead of one-at-a-time could cut a multi-hour
overnight run to a fraction of that, bounded by whichever scripts are actually memory/CPU heavy
(k-BAHC-class scripts) which should stay solo.

**The operational fragility this project has repeatedly hit** (non-atomic checkpoint writes,
PowerShell async deadlocks, per-stage timeout issues, orphaned process trees — all documented in
`Development.md`'s "Late-night close-out"/"Overnight monitoring" entries) is a direct consequence
of hand-rolled sequential PowerShell orchestration with no real dependency graph, retry policy, or
process supervision. **Value: real and high** if the overnight-research workflow continues to be
a regular part of this project's cadence — a proper DAG-aware runner (even a simple Python one
using `concurrent.futures.ProcessPoolExecutor` with an explicit dependency list, replacing the
PowerShell orchestration entirely) would eliminate an entire class of bugs this project has paid
real debugging time for multiple times, not just speed things up.

## 3. Testing pattern

**Real, positive finding, not a gap**: `run_verify_suite.py` already exists (built 2026-07-01,
per its own docstring, from a STORM gap-analysis finding), and confirmed via direct read: it uses
`glob.glob(os.path.join(_DEBUG_DIR, "_verify_*.py"))` — **dynamic, not a hardcoded list** — so it
already automatically picks up all **176** current `debug/_verify_*.py` scripts (up from 18 when
built), not just the ones that existed when it was written. This is NOT stale infrastructure;
it's working as designed. **Value: no fix needed here** — but it's worth confirming this actually
gets RUN regularly (e.g. as a pre-commit step or before any full pipeline run), since its value is
zero if nobody invokes it. No evidence found either way from static inspection alone.

**Real gap**: no `pytest.ini`, no `pyproject.toml`, no CI config of any kind exists in the repo
root — `run_verify_suite.py`'s own docstring explicitly frames itself as "CI-lite, not a CI/CD
pipeline." Formalizing the 176 verify scripts as real pytest tests (parametrized, with fixtures
for the common synthetic-data-generation patterns many of them likely repeat) would enable
real per-test reporting, parallel test execution (`pytest -n auto`), and standard CI integration
if this project ever wants that. **Value: moderate, real but not urgent** — `run_verify_suite.py`
already delivers the core "did I break something" signal; pytest migration is a quality-of-life
upgrade, not a correctness fix.

## 4. Config management

`config.py` (1,086 lines) is well-organized into 11 logical namespace classes (`IBKRConfig`,
`DataConfig`, `UniverseConfig`, `AnalysisConfig`, `MLConfig`, `BacktestConfig`, `OptionsConfig`,
`StatsConfig`, `MacroConfig`, `ReportConfig`, `ResearchConfig`), aggregated under one `Config`
class — **not a flat mess**, a real, deliberate structure. No fix needed to the organization
itself.

**Real, quantified hardcoding gap, same pattern already found and partially fixed this session**:
`n_workers=12` (or `n_workers: int = 12`) is hardcoded as a **default parameter value in 8
separate locations inside `analysis.py` itself** (lines 1821, 2032, 4340, 4490, 4591, 4842, 5817,
6315) — this is in PRODUCTION code, not just the research/ scripts already fixed. None of these
derive from `os.cpu_count()` or a `Config`-level worker-count setting. On an 8-core machine (both
the old Windows box's usable core count under contention, AND CachyOS's real 8 cores with no
SMT), `n_workers=12` is a real, structural oversubscription every time one of these 8 call sites
runs at its default. **Value: real, moderate-to-high** — this is core production code, not a
one-off script; a single `Config.RUNTIME.N_WORKERS = max(1, os.cpu_count() - 1)` setting,
threaded through these 8 call sites, would fix the same class of bug already fixed in the
research/ scripts, at its actual point of highest leverage.

## 5. Existing plugin/tooling usage vs. gaps

Every tool CLAUDE.md's "Recommended Plugins/Tools" section lists as installed
(`council-*` subagents, `adversarial-reviewer`, `premortem`, `verify-new-module`,
`diagnose-run-log`, `guard_manifest.py` hook) has a real, checkable artifact in the repo
(`.claude/agents/council-*.md`, `.claude/skills/premortem/`, `.claude/hooks/`) — **not
installed-but-unused theater**, genuinely present.

**Confirmed gap, same as flagged in the hardware plan**: zero linter/formatter config anywhere
(`pyproject.toml`, `ruff.toml`, `.pre-commit-config.yaml`, `setup.cfg` — all absent). This is a
**pure `requirements.txt` project with no packaging metadata at all** — no `pyproject.toml`
means no standard place to declare `[tool.ruff]`, `[tool.pytest.ini_options]`, or even basic
project metadata (name/version). **Value: real, low-cost, high-leverage** — a single
`pyproject.toml` addition (even just holding `[tool.ruff]` config) would unlock Ruff, give
`run_verify_suite.py`'s eventual pytest migration (§3) a natural home, and cost nothing to add
incrementally (existing `requirements.txt`-based installs are unaffected).

## 6. Data/IO efficiency at the code level

`universe_loader.py`'s `load_full_universe()` already reads each source directory once per call
(via `_load_dir`'s `ThreadPoolExecutor`) — no redundant same-file re-reads found WITHIN one call.
**Real, cross-script redundancy exists at the pipeline level instead**: any overnight run
sequence that calls `load_full_universe()` from multiple independent scripts back-to-back (e.g.
the 4 rewired scripts, k-BAHC, the full-universe cascade drivers) re-reads the same ~45,000
parquet files from disk fresh, every single time, with no shared cache between script
invocations within one overnight run. Given tonight's own finding that this exact load phase
costs 2-4 minutes even in the fast case (and has hit multi-hour anomalies), and given the
column-pruning fix (`columns=["close"]`) already built this session, **the next real win here is
a simple on-disk memoization layer**: write the merged, column-pruned, calendar-aligned
`{symbol: DataFrame}` result to one consolidated parquet/feather file after the first load in an
overnight run, and have subsequent scripts in the same run check for and reuse that consolidated
file instead of re-globbing and re-reading 45,000 individual files. **Value: real, high** for the
overnight-multi-script-run use case specifically; zero value for a single standalone script run.

**DONE (2026-08-20)** — see the prioritized list item 3 below for the full implementation
detail. `load_full_universe(use_memo_cache=True)`, opt-in, verified with a 6-check synthetic
test.

---

## Prioritized list — most worth doing first, reasoned from actual impact

1. **DONE (2026-08-20, same night).** `n_workers=12` → derived from `os.cpu_count()` in
   `analysis.py`'s 8 hardcoded locations (§4). Added `Config.RUNTIME.N_WORKERS =
   max(1, os.cpu_count() - 1)` (`config.py`); all 8 call sites (7 signatures + 1 inline `min()`
   call) updated to resolve from it instead of the literal `12`. Verified: `analysis.py` imports
   cleanly, `Config.RUNTIME.N_WORKERS` resolves to 11 on the Windows box (12 logical cores) and
   would resolve to 7 on CachyOS (8 physical cores, no SMT) — exactly the oversubscription fix
   this finding called for.
2. **DONE (2026-08-20, same night).** Added `pyproject.toml` with `[tool.ruff]` (§5) — report-only
   rule set (`F` pyflakes + `E9` syntax errors) to start, deliberately not the full default rule
   set on a ~200-file established codebase (that's Ross's call, not a default). Verified working,
   not just written blind: `ruff check config.py analysis.py` found 23 real issues (unused
   imports etc.) on the first run. Fixes not applied yet — that's a separate, broader decision.
3. **DONE (2026-08-20).** Consolidated-load memoization for overnight multi-script runs (§6).
   Added an opt-in `use_memo_cache: bool = False` parameter to `load_full_universe()` — default
   unchanged, so every existing caller is unaffected unless it explicitly opts in. When True, the
   merged `{symbol: DataFrame}` result is cached to
   `output/cache/_universe_loader_memo/{tf_label}_{key}.pkl`, keyed by tf_label, the include_*
   flags, `columns`, and a cheap per-source-directory staleness signature (file count + max
   mtime, stat-only, no content hashing — `_dir_signature()`). A second call in the same run with
   an unchanged signature loads straight from the pickle instead of re-globbing/re-reading tens
   of thousands of parquet files; any new/changed source file changes the signature and
   transparently triggers a rebuild rather than serving stale data. Verified with a 6-check
   synthetic test (`debug/_verify_universe_loader_memo_cache.py`) against temp fixture
   directories, including proof the cache is genuinely reused (monkeypatched `_load_dir` to raise
   if called, second call still succeeds) and proof the default path never touches the memo cache
   dir at all. Not yet wired into any `run_*.ps1` orchestration script — that's item 4 below,
   deliberately separate since it needs its own dependency audit.
4. **DONE, first safe increment (2026-08-20).** A dependency audit (fork, 2026-08-20) confirmed
   the 13 `backtest.py` variant stages (01-13) write to disjoint output files (verified directly
   from `backtest.py`'s label-construction code, `backtest.py:1884-1902`) and none touch
   `output/cache/` — the safest, highest-value first parallelization target. Built
   `run_overnight_research.py`, a cross-platform (Windows + Linux) Python replacement for
   `run_overnight_research.ps1` — also closes the real gap that PowerShell doesn't exist on
   CachyOS at all, so the `.ps1` orchestrator couldn't run there regardless of parallelization.
   The 13 backtest variants now run as one `ThreadPoolExecutor` batch; stage 00c (`pit_wfa.py`,
   confirmed by the same audit to have zero read dependency on 00/00a/00b) now runs concurrently
   with that chain instead of before it. Stages 14-31 and all 121 `research/*.py` scripts stay
   SEQUENTIAL in this version, deliberately — the audit found `gics.py`/`survivorship.py` (27,
   29) write into `output/cache/` itself (a real race risk) and ~90 of the 121 research scripts
   were never individually checked for cross-script output dependencies. Verified with 2 new
   synthetic tests: `debug/_verify_overnight_orchestrator_py.py` (5 checks: successful-stage
   completion, resumability/skip, failure handling, timeout-kill with no orphaned process, and
   retry-until-success) and a direct concurrency proof (5×1.5s dummy stages completed in 1.6s via
   the real `ThreadPoolExecutor` code path, not just imported). The original `.ps1` file is
   UNCHANGED — the Windows box keeps using it; the two share the same log directory and
   plain-text state-file format, so a run started by either orchestrator can be resumed by the
   other. **Not yet run against the real production pipeline** — that's Ross's call on when to
   do a live overnight comparison run.
5. **DONE (2026-08-20).** Audited the 5 remaining scripts with local timeframe-suffix dicts (§1)
   for the deeper "reads only the old cache" bug. 4/5 confirmed fine on inspection; the 5th,
   `eg_null_calibration_montecarlo.py`, DOES have the real bug — deliberately left unfixed, see
   §1 above, since it affects a published `PAPER.md` §4.2.1 claim and needs Ross's explicit
   decision on whether to rewire + re-run (changing the published number) or disclose the scope
   limitation as-is.
6. **DONE (2026-08-20).** Executed Thread O's 3 "strong candidate" WRDS-script consolidations
   (§1) into `data_wrds.py` — mechanical moves, verified via syntax/import checks; live WRDS
   functional testing remains Ross's responsibility (2FA constraint).
7. **Confirm `run_verify_suite.py` is actually invoked regularly** (§3) — no code change needed,
   just a process/habit check; its value depends entirely on being run.
8. **pytest migration for the 176 verify scripts** (§3) — real quality-of-life upgrade, lowest
   urgency of this list since `run_verify_suite.py` already delivers the core safety signal.
