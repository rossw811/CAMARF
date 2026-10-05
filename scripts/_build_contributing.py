"""
One-off generator for CONTRIBUTING.md. Not part of the production pipeline or a debug tool --
run once to assemble the doc from (a) hand-curated descriptions of the core pipeline scripts and
(b) programmatically-extracted module-docstring summaries for the ~290 research/debug scripts,
which are too numerous to hand-author without drift. Re-run after adding/removing scripts to
regenerate the auto tables; hand-edit CONTRIBUTING.md directly for anything else.

Usage: python scripts/_build_contributing.py
"""
import ast
import glob
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def summarize(path, maxlen=260):
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        doc = ast.get_docstring(tree)
        if not doc:
            return "(no module docstring)"
        first_para = doc.strip().split("\n\n")[0]
        text = " ".join(first_para.split())
        if len(text) > maxlen:
            text = text[: maxlen - 3] + "..."
        return text
    except Exception as e:
        return f"(could not parse: {e})"


def how_to_run(path, rel, maxlen=170):
    """The command to run a script (2026-10-05, Ross: "outline ... how to run each script"): the docstring's own
    'Usage:' / 'Run:' line when it has one; else built from its argparse block (positional choices + flag names);
    'import only' when it has no __main__ entry point."""
    try:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
    except Exception:
        return "(could not parse)"
    doc = ast.get_docstring(tree) or ""
    lines = doc.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"\s*(?:Usage|Run|USAGE|RUN)\s*:\s*(.+)", line)
        if m and "python" in m.group(1):
            cmds = [" ".join(m.group(1).split())]
            for nxt in lines[i + 1:]:                        # a Usage block with one command per line
                if nxt.strip().startswith("python"):
                    cmds.append(" ".join(nxt.split()))
                else:
                    break
            cmd = " ; ".join(c.split("#")[0].strip() for c in cmds)
            return cmd if len(cmd) <= maxlen else cmd[: maxlen - 3] + "..."
    if "__main__" not in src:
        return "import only (no CLI)"
    pos, flags = [], []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "add_argument" and n.args:
            first = n.args[0]
            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                continue
            kw = {k.arg: k.value for k in n.keywords}
            if first.value.startswith("-"):
                req = isinstance(kw.get("required"), ast.Constant) and kw["required"].value is True
                flags.append(first.value + " <value>" if req else first.value)
            else:
                ch = kw.get("choices")
                try:
                    vals = ast.literal_eval(ch) if ch is not None else None
                except Exception:
                    vals = None
                pos.append("{" + ",".join(map(str, vals)) + "}" if vals else f"<{first.value}>")
    # flags read straight from sys.argv (no argparse), e.g. `"--fresh" in sys.argv`, sys.argv.index("--d18")
    for f in re.findall(r'"(--[a-z0-9][a-z0-9-]*)"\s+(?:not\s+)?in\s+sys\.argv|sys\.argv\.index\("(--[a-z0-9-]+)"\)', src):
        name = f[0] or f[1]
        if name not in flags and name not in [x.split()[0] for x in flags]:
            flags.append(name)
    cmd = f"python {rel}" + "".join(" " + p for p in pos)
    if flags:
        cmd += " " + " ".join(f"[{f}]" for f in flags[:4])
        if len(flags) > 4:
            cmd += f" (+{len(flags) - 4} more flags, see --help)"
    return cmd


def table(rows, headers=("Script", "How to run", "What it does")):
    lines = [f"| {headers[0]} | {headers[1]} | {headers[2]} |", "|---|---|---|"]
    for name, run, doc in rows:
        doc = doc.replace("|", "\\|")
        run = run.replace("|", "\\|")
        lines.append(f"| `{name}` | `{run}` | {doc} |")
    return "\n".join(lines)


# =============================================================================
# CORE PRODUCTION PIPELINE -- hand-curated, full detail
# =============================================================================

CORE_PIPELINE = """
## Core production pipeline

Run in this order for a full refresh; see `README.md`'s "Pipeline" section for the canonical
ordered command sequence and expected runtimes. Everything below runs from the project root
(`python <script>.py`), through the pinned conda env (`C:\\Users\\RossW\\anaconda3\\envs\\trading\\
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
scriptable end-to-end). Volume is stored in today's share units (`volume`, raw in `volume_raw`) --
CRSP dlyvol x dlycumfacpr, Compustat cshtrd x ajexdi -- so close x volume is a correct dollar volume
(DEV-003; existing caches: `research/apply_crsp_volume_adjustment.py`). Fetches CRSP total-return-adjusted daily history for the whole US
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
incremental, whenever you edit `analysis.py` itself. Reads via `builder.build(connect=False, fetch=False)`,
never fetches and never mutates the cache (rule 1; since 2026-10-05 read-only mode also skips the cache
migration/cleanup steps that rename or delete files -- DEV-014). `latest_run_analysis.log` is the structured log to read first.

### `backtest.py` -- event-driven backtest engine, every comparison-arm variant
**Run:** `python backtest.py` (baseline) or with flags for any variant -- `--pairs-override
<path>` (test against a specific pair set instead of the production manifest), `--holdout` (OOS
split), `--capital-sim` (capital-constrained, mark-to-market replay -- **the project's designated
headline metric**, per pair backtests are diagnostic only), `--capital-sizing {fixed,
equity_proportional,flat_2pct,quarter_kelly,third_kelly,half_kelly,full_kelly}`,
`--capital-account-size <N>`, `--entry-z <N>`, `--hedge {ols,kalman}` (default ols; kalman is its own
arm with output label `_kalman` -- `both` was removed 2026-10-03, it double-counted near-duplicate trades),
`--holdout-mode {per_pair,common_date}` (common_date = one calendar cutoff per timeframe, comparison arm),
`--legacy-pnl` (KNOWN WRONG spread-unit P&L, only to reproduce old numbers; the default is dollar P&L from
`pnl_dollar.py`, and trades that cannot be priced are dropped and counted -- `--pnl-cap` requires it), `--override
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
**Run:** `python debug/_run_all_verify.py` (every `debug/_verify_*.py`, ~340 as of 2026-10; sequential by
default; on CachyOS `--workers 2 --timeout 300`; failing tests' full output goes to `--failure-dir`, default
`output/verify_runs/last_failures/`) or `--pattern <substring>` (subset) or `--workers N` (parallel -- **only on a machine
with real memory headroom**; running the full suite in parallel OOM-killed a 16GB machine twice
in one night, 2026-09-21 -- prefer CachyOS or sequential on a constrained machine). Classifies
PASS / FAIL (real check failure) / ERROR (crashed before any check ran, or timed out -- usually a
missing local-only dependency or file, not a logic bug). `_KNOWN_SLOW_TIMEOUTS` gives a handful of
legitimately-expensive scripts (real WRDS connection, thousands of real-file checks, permutation
draws) their own longer per-script timeout so they don't need re-investigating as false ERRORs
every run.
""".strip()


# =============================================================================
# MAIN
# =============================================================================

def build_table_section(title, intro, entries, run_note=None):
    rows = [(e["name"], e["run"], e["doc"] or "(no module docstring)") for e in entries]
    section = f"### {title}\n\n{intro}\n"
    if run_note:
        section += f"\n{run_note}\n"
    section += "\n" + table(rows) + "\n"
    return section


def main():
    research = []
    debug_util = []
    root_supporting = []

    CORE_NAMES = {
        "data.py", "data_wrds.py", "data_ibkr.py", "ibkr_supplement_reader.py", "analysis.py",
        "backtest.py", "ml.py", "macro.py", "config.py", "universe_loader.py", "stats.py",
        "portfolio_math.py", "portfolio_sim.py", "survivorship.py", "deflated_sharpe.py",
        "trial_registry.py", "gpu_backend.py", "reproduce.py", "run_overnight_research.py",
    }

    for path in sorted(glob.glob(os.path.join(_ROOT, "research", "*.py"))):
        name = os.path.basename(path)
        research.append({"name": name, "run": how_to_run(path, f"research/{name}"), "doc": summarize(path)})

    for path in sorted(glob.glob(os.path.join(_ROOT, "debug", "*.py"))):
        name = os.path.basename(path)
        if name.startswith("_verify_"):
            continue
        debug_util.append({"name": name, "run": how_to_run(path, f"debug/{name}"), "doc": summarize(path)})

    for path in sorted(glob.glob(os.path.join(_ROOT, "*.py"))):
        name = os.path.basename(path)
        if name in CORE_NAMES:
            continue
        root_supporting.append({"name": name, "run": how_to_run(path, name), "doc": summarize(path)})

    scripts_dir = []
    for path in sorted(glob.glob(os.path.join(_ROOT, "scripts", "*.py"))):
        name = os.path.basename(path)
        scripts_dir.append({"name": name, "run": how_to_run(path, f"scripts/{name}"), "doc": summarize(path)})

    n_verify = len(glob.glob(os.path.join(_ROOT, "debug", "_verify_*.py")))
    n_total = len(research) + len(debug_util) + len(root_supporting) + len(scripts_dir) + n_verify
    doc = f"""# Contributing to / Modifying CAMARF

This is a solo research project (Ross W.), but this doc exists so anyone -- human or an AI
assistant picking up the project cold -- can find, understand, and run any script in this
codebase without re-deriving context from scratch or reading `Development.md`'s full session
history first. Read `CLAUDE.md` first for the project's non-negotiable architecture rules and
working-style conventions; `Development.md` is the canonical full session-by-session memory (bug
registry, design rationale) if you need more depth than this file provides; `docs/HANDOFF.md` is
the current-state/open-items log.

**How this file is organized**: the core production pipeline (below) gets full hand-written
detail -- what each script does, exactly how to run it, its real gotchas. Everything else
(`research/`, `debug/`, `scripts/`, supporting root-level modules) is far too numerous ({n_total} scripts at
the last regeneration) for that treatment without the doc itself becoming stale reading; those sections are
one-line-per-script tables -- **how to run it** (from the script's own `Usage:`/`Run:` docstring line, else its
argparse flags) and **what it does** (its docstring's first paragraph) -- auto-generated by
`scripts/_build_contributing.py` -- re-run that generator after adding/removing scripts rather
than hand-editing the tables. Every script in this codebase has a real, specific module docstring
(project convention, not optional) -- when a table row here is too terse, `Read` the script's own
top-of-file docstring directly; it is the authoritative, current source, this file is a fast index
into it.

---

## How to contribute -- the workflow every change follows

The project is public and built to be checked: anyone may attack any result, and every hole found is verified,
fixed or disclosed, and logged. A change is "done" only when it has passed all of the steps below.

1. **Start from the open work.** `docs/ERRATA.md` (what is fixed, withdrawn, open -- the public index),
   `docs/HANDOFF.md` (current state), `docs/PLAN_OF_ACTION_2026-10-03.md` (every thread and its done-criteria),
   `docs/CLAIMS_REGISTRY.md` (only REPLICATED claims are citable). Outside reports come in through
   `.github/ISSUE_TEMPLATE/find_a_hole.md`.
2. **Reproduce first.** Write `debug/_verify_<name>.py` that FAILS on the current code, run it and keep the
   output, then fix, then run it again (passes). Build synthetic input with a known answer; print `[PASS]`/`[FAIL]`
   per check and exit non-zero on failure. **Tests must never write to or delete from `output/`** -- use a temp
   directory and monkeypatch paths (a test once deleted real discovery outputs; three others wrote fake symbols into
   the real caches).
3. **Check on real data.** Re-derive the effect on real outputs and record the before/after numbers (a synthetic
   test proves the code; only real data proves the effect -- several fixes changed nothing on real data, others
   changed a headline).
4. **Full suite before committing a change to a core module** (`data.py`, `data_wrds.py`, `analysis.py`,
   `backtest.py`, `portfolio_sim.py`, `pnl_dollar.py`, `ml.py`, `stats.py`, `config.py`, `universe_loader.py`):
   `python debug/_run_all_verify.py --workers 2 --timeout 300` (on CachyOS). A failing test's full output is saved
   to `output/verify_runs/last_failures/`. A change once broke three tests unnoticed for a week because this step
   was skipped.
5. **Independent check for anything headline-level** -- a separate reviewer (e.g. the `adversarial-reviewer`
   agent) tries to break the claim; it checks, it does not do the work. Independent review has found real bugs
   in fixes that had passed their own tests.
6. **Record it.** Update the finding's status with evidence (file:line, commit, test, output path) in the ledger it
   came from (`docs/CODE_REVIEW_2026-09-26.md`, `docs/INCONSISTENCY_SWEEP_2026-09-27.md`, `Development.md`); register
   any number you will cite in `docs/CLAIMS_REGISTRY.md` with a reproduce command; update `docs/ERRATA.md`. Document
   what was tried and reverted, not only what was kept.

**Rules that every change follows (from `CLAUDE.md`):** free data only (WRDS subscription + free sources);
`data.py` fetches and `analysis.py` analyzes, never reversed (`build(fetch=False)` never touches the cache); WRDS
wins symbol collisions for daily-and-coarser data; DATA_GAP bars are never forward-filled into a statistic;
constants come from `config.py` (`debug/_verify_config_drift_guard.py` fails on a duplicated literal); the universe
comes from `universe_loader.load_full_universe()`; a new method enters as a comparison arm next to the current one
and needs Ross's approval before it replaces anything; known biases are disclosed, never silently corrected; data
is never deleted (back it up); numbers are never inflated.

**Adding a research script:** module docstring stating the claim it tests, with a `Usage: python research/<name>.py
...` line (this file's How-to-run column reads it); a `debug/_verify_<name>.py`; outputs under
`output/research/*.parquet`; if it is part of the discovery -> pools -> search chain, a lineage stage in
`research/pipeline_stages.py`. Then regenerate this file: `python scripts/_build_contributing.py`.

---

## Environment setup

Run everything through the project's pinned conda environment (Windows: `C:\\Users\\RossW\\
anaconda3\\envs\\trading\\python.exe`) or the CachyOS `.venv` (`.venv/bin/python`) -- never a bare
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

{CORE_PIPELINE}

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
   constructor argument. Never mutate global `Config` state -- build a real copy with
   `config.section_copy(Config.BACKTEST)` (`_build_backtest_cfg`). **Not `copy.copy`:** Config sections are classes,
   so `copy.copy` returns the original and every override silently became global (found 2026-10-03, code review
   B6). Anything that must see the override has to receive the engine's cfg (the regime conditioner and the
   capital simulation's `stop_zscore` do).
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

{table([(e["name"], e["run"], e["doc"]) for e in research])}

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

**Don't enumerate all {n_verify} individually here** -- each one's own module docstring states exactly
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

{table([(e["name"], e["run"], e["doc"]) for e in debug_util])}

---

## Other root-level supporting modules

Not part of the "core pipeline" run sequence above, but not `research/`-scoped either --
importable utilities, one-off/legacy scripts, and secondary analysis modules living at the
project root.

{table([(e["name"], e["run"], e["doc"]) for e in root_supporting])}

---

## `scripts/` -- project maintenance tools (inventories, documentation generators, hooks)

{table([(e["name"], e["run"], e["doc"]) for e in scripts_dir])}

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
"""

    out_path = os.path.join(_ROOT, "CONTRIBUTING.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"Wrote {out_path} ({len(doc)} chars, {len(research)} research + {len(debug_util)} "
          f"debug-util + {len(root_supporting)} root-supporting entries)")


if __name__ == "__main__":
    main()
