"""
run_overnight_research.py -- cross-platform (Windows + Linux) replacement for
run_overnight_research.ps1, built 2026-08-20 (software optimization audit
item 4, plus Ross's direct request that the project's orchestration be
usable on CachyOS, not just the Windows box).

WHY A NEW FILE, NOT AN EDIT TO THE .ps1: run_overnight_research.ps1 stays
exactly as-is -- the Windows box still uses it, and it has a real, hard-won
bug history (documented inline there: ExitCode misreporting, an async-read
deadlock, a .NET 5+-only Kill(true) overload that silently did nothing on
Windows PowerShell 5.1) that this file does NOT need to re-litigate, since
none of those failure modes are PowerShell-async-specific -- Python's
subprocess module with direct file-handle redirection (no manual event
pumping at all) sidesteps that entire class of bug by construction.

WHAT'S DIFFERENT FROM THE .ps1 VERSION (both verified via a dependency
audit, 2026-08-20 -- see docs/SOFTWARE_OPTIMIZATION_AUDIT.md and
Development.md for the full audit writeup, not repeated here):
  1. Cross-platform: uses sys.executable (not a hardcoded python.exe path),
     os.name-branched process-group kill (POSIX: os.killpg + SIGKILL: this
     project's own docs/HARDWARE_OPTIMIZATION_PLAN.md already established
     CachyOS as a real, actively-used second machine), pathlib-free but
     os.path.join throughout (already the existing codebase convention).
  2. Stage 00c (pit_wfa.py) now runs CONCURRENTLY with the 00/00a/00b chain
     instead of sequentially before it -- confirmed via the dependency
     audit that pit_wfa.py has zero read dependency on the episodic
     scan/adapter/ml.py --pit-safe outputs (grepped its full import list
     and body directly, not assumed).
  3. Stages 01-13 (the 13 backtest.py variants: plain, --holdout, all 9
     --storm-*/--hub-weight/--risk-parity/--pnl-cap/--neg-hedge combos, and
     the two --entry-z 1.5 IS/OOS runs) now run as ONE PARALLEL BATCH
     instead of 13 fully sequential stages -- confirmed via the audit that
     every variant's `label` suffix construction (backtest.py:1884-1902) is
     distinct, so all 13 write to disjoint output/backtest/*.parquet files
     with zero collision risk, and none of them touch output/cache/ (the
     shared source-data directory). This IS the safe-first parallelization
     step the audit explicitly recommended -- stages 14-31 and the 121
     research/*.py scripts stay SEQUENTIAL in this version, deliberately:
     the audit found gics.py/survivorship.py (27, 29) write into
     output/cache/ itself (a real race risk against anything else touching
     that directory), and ~90 of the 121 research scripts were not
     individually audited for cross-script output dependencies -- widening
     parallelization further needs that audit done first, not assumed safe
     by extension.
  4. Same log directory layout, same state-file format
     (logs/overnight/_completed_stages.txt, one completed stage name per
     line) as the .ps1 version -- a run started by one orchestrator can be
     resumed by the other without any format translation, since both are
     just plain-text stage-name lists.

Usage (from either machine, in the project's own Python environment):
    python run_overnight_research.py [--workers N] [--timeout-minutes N] [--fresh]
Or detached or on Windows:
    (Windows)  Start-Process python -ArgumentList "run_overnight_research.py" -WindowStyle Hidden
    (Linux)    nohup python run_overnight_research.py > /dev/null 2>&1 &
"""
import argparse
import glob
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import Config

_ROOT = os.path.dirname(os.path.abspath(__file__))
_LOG_DIR = os.path.join(_ROOT, "logs", "overnight")
_STATE_FILE = os.path.join(_LOG_DIR, "_completed_stages.txt")
_MASTER_LOG = os.path.join(_LOG_DIR, "_runner.log")


def _log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}  {msg}"
    print(line, flush=True)
    with open(_MASTER_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _completed_stages() -> set:
    if not os.path.exists(_STATE_FILE):
        return set()
    with open(_STATE_FILE, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def _mark_completed(name: str):
    with open(_STATE_FILE, "a", encoding="utf-8") as f:
        f.write(name + "\n")


def _kill_process_tree(proc: subprocess.Popen):
    """Cross-platform tree-kill. POSIX: the child was started in its own
    process group (start_new_session=True below), so killing that group
    catches any grandchildren too, the same guarantee the .ps1 version's
    `taskkill /T /F` provides on Windows via CREATE_NEW_PROCESS_GROUP."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                            capture_output=True, timeout=10)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def _popen_kwargs():
    """OS-specific kwargs so _kill_process_tree can reliably catch children:
    POSIX gets its own process group (start_new_session), Windows gets its
    own process group flag (the same one the .ps1 orchestrator's raw
    ProcessStartInfo/taskkill combination already relies on)."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def run_stage(name: str, script: str, args=None, timeout_minutes: int = None,
              state: set = None) -> bool:
    """One-shot stage run: launch, redirect stdout/stderr straight to log
    files (no manual event pumping -- Python's subprocess handles this
    natively, unlike the .NET async-callback machinery the .ps1 version
    needs), wait up to timeout_minutes, kill-and-mark-FAILED on timeout.
    Returns True if the stage completed successfully (exit 0) or was
    already done; False otherwise. `state` lets a caller check completion
    without re-reading the state file from disk on every call (used by the
    parallel batch runner below)."""
    args = args or []
    if state is None:
        state = _completed_stages()
    if name in state:
        _log(f"SKIP    {name} (already completed)")
        return True

    out_log = os.path.join(_LOG_DIR, f"{name}.out.log")
    err_log = os.path.join(_LOG_DIR, f"{name}.err.log")
    arg_line = " ".join(args)
    _log(f"START   {name}  ->  {script} {arg_line}")
    t0 = time.time()

    cmd = [sys.executable, script] + args
    with open(out_log, "w", encoding="utf-8") as out_f, open(err_log, "w", encoding="utf-8") as err_f:
        proc = subprocess.Popen(cmd, stdout=out_f, stderr=err_f, cwd=_ROOT, **_popen_kwargs())
        try:
            timeout_s = timeout_minutes * 60 if timeout_minutes else None
            ret = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _log(f"TIMEOUT {name} after {timeout_minutes} min -- killing and moving on")
            _kill_process_tree(proc)
            return False

    dur = int((time.time() - t0) / 60)
    if ret == 0:
        _log(f"DONE    {name} in {dur} min (exit 0)")
        _mark_completed(name)
        return True
    else:
        _log(f"FAILED  {name} after {dur} min (exit {ret}) - see {err_log}")
        return False


def run_stage_until_success(name: str, script: str, args=None, max_attempts: int = 100):
    """Equivalent of the .ps1 version's Invoke-StageUntilSuccess -- for a
    genuinely long-running, self-checkpointing script (intraday_episodic_scan.py,
    BUG-D108's atomic per-tier checkpointing) where a single timeout would
    just discard partial progress. No per-attempt timeout by design -- the
    underlying script's own checkpoints make each relaunch cheap."""
    args = args or []
    state = _completed_stages()
    if name in state:
        _log(f"SKIP    {name} (already completed)")
        return

    for attempt in range(1, max_attempts + 1):
        out_log = os.path.join(_LOG_DIR, f"{name}.attempt{attempt}.out.log")
        err_log = os.path.join(_LOG_DIR, f"{name}.attempt{attempt}.err.log")
        arg_line = " ".join(args)
        _log(f"START   {name} attempt {attempt}/{max_attempts}  ->  {script} {arg_line}")
        t0 = time.time()

        cmd = [sys.executable, script] + args
        with open(out_log, "w", encoding="utf-8") as out_f, open(err_log, "w", encoding="utf-8") as err_f:
            proc = subprocess.Popen(cmd, stdout=out_f, stderr=err_f, cwd=_ROOT, **_popen_kwargs())
            ret = proc.wait()  # no timeout -- babysitting an unbounded-length run is the point

        dur = int((time.time() - t0) / 60)
        if ret == 0:
            _log(f"DONE    {name} in {dur} min on attempt {attempt} (exit 0)")
            _mark_completed(name)
            return
        else:
            _log(f"ENDED   {name} attempt {attempt} after {dur} min (exit {ret}) -- retrying (checkpoints make this cheap)")

    _log(f"GAVE UP on {name} after {max_attempts} attempts -- moving on without marking it complete")


# --- The 13 backtest.py variants (audit-verified: distinct output labels,
# zero collision, none touch output/cache/) -- run as one parallel batch. ---
_BACKTEST_VARIANTS = [
    ("01_backtest_is",                  []),
    ("02_backtest_oos",                 ["--holdout"]),
    ("03_storm_session_edge",           ["--holdout", "--storm-session-edge"]),
    ("04_storm_session_edge_postopen",  ["--holdout", "--storm-session-edge-postopen"]),
    ("05_storm_mm_exec",                ["--holdout", "--storm-mm-exec"]),
    ("06_storm_coint_frac",             ["--holdout", "--storm-coint-frac"]),
    ("07_storm_all",                    ["--holdout", "--storm-all"]),
    ("08_hub_weight",                   ["--holdout", "--hub-weight"]),
    ("09_risk_parity",                  ["--holdout", "--risk-parity"]),
    ("10_pnl_cap",                      ["--holdout", "--pnl-cap"]),
    ("11_neg_hedge",                    ["--holdout", "--neg-hedge"]),
    ("12_entryz15_is",                  ["--entry-z", "1.5"]),
    ("13_entryz15_oos",                 ["--holdout", "--entry-z", "1.5"]),
]

# --- Stages 14-31, unchanged order, sequential (report.py depends on 01-18's
# output existing; gics.py/survivorship.py write into output/cache/ itself,
# a real race risk if run concurrently with anything else touching that dir
# -- both flagged by the 2026-08-20 dependency audit, see module docstring). ---
_SEQUENTIAL_STAGES = [
    ("14_stats",                   "stats.py",             []),
    ("15_wfa",                     "wfa.py",                []),
    ("16_distance",                "distance.py",           []),
    ("17_sensitivity",             "sensitivity.py",        []),
    ("18_deflated_sharpe",         "deflated_sharpe.py",    []),
    ("19_report",                  "report.py",             []),
    ("20_ml",                      "ml.py",                 []),
    ("21_run_storm_grid",          "run_storm_grid.py",     []),
    ("22_fresh_holdout_compare",   "fresh_holdout_compare.py", []),
    ("23_absorption_ratio",        "absorption_ratio.py",   []),
    ("24_cvar",                    "cvar.py",               []),
    ("25_decay_proxy",             "decay_proxy.py",        []),
    ("26_portfolio_sim",           "portfolio_sim.py",      []),
    ("27_survivorship",            "survivorship.py",       []),
    ("28_options",                 "options.py",            []),
    ("29_gics",                    "gics.py",               []),
    ("30_reproduce",               "reproduce.py",          ["--verify-only"]),
    ("31_run_verify_suite",        "run_verify_suite.py",   []),
]


def _warm_cache(cache_dir: str, max_workers: int) -> None:
    """Sequentially-issued-but-thread-parallel read-and-discard pass over every
    file under `cache_dir`, added 2026-08-20 for CachyOS: `output/cache/` sits
    on a genuine spinning HDD there (confirmed via /sys/block/*/queue/rotational
    -- see docs/HARDWARE_OPTIMIZATION_PLAN.md item 1), but the whole cache
    (9.2GB as of this session's transfer) comfortably fits in that machine's
    46.9GB RAM. Once the OS page cache holds these files, every subsequent
    read across this run's ~150 script invocations is served from RAM, not
    disk -- this warms that up FRONT-LOADED, at the start of the run, instead
    of only benefiting re-runs (which would happen for free regardless, via
    the kernel's own page cache, with no code change at all). I/O-bound work,
    not CPU-bound -- threads, not processes, are the right tool (same
    reasoning universe_loader.py's own _load_dir already uses). Harmless on a
    machine where the cache is already on fast storage (e.g. the Windows dev
    box) -- just a redundant, cheap read pass there, not a behavior change."""
    if not os.path.isdir(cache_dir):
        return
    paths = []
    for root, _dirs, files in os.walk(cache_dir):
        for f in files:
            paths.append(os.path.join(root, f))
    if not paths:
        return
    t0 = time.time()
    total_bytes = 0

    def _read_one(p):
        with open(p, "rb") as f:
            return len(f.read())

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for n in pool.map(_read_one, paths):
            total_bytes += n
    dur = time.time() - t0
    _log(f"Cache warm-up: read {len(paths)} files ({total_bytes / 1e9:.2f} GB) from "
         f"{cache_dir} in {dur:.1f}s -- now resident in OS page cache for this run")


def main():
    p = argparse.ArgumentParser(description="CAMARF overnight research runner (cross-platform)")
    p.add_argument("--workers", type=int, default=Config.RUNTIME.N_WORKERS)
    p.add_argument("--timeout-minutes", type=int, default=45)
    p.add_argument("--fresh", action="store_true")
    p.add_argument("--skip-warm-cache", action="store_true",
                    help="Skip the startup page-cache warm-up pass over output/cache/.")
    args = p.parse_args()

    os.makedirs(_LOG_DIR, exist_ok=True)
    if args.fresh and os.path.exists(_STATE_FILE):
        os.remove(_STATE_FILE)
    if not os.path.exists(_STATE_FILE):
        open(_STATE_FILE, "w").close()

    _log(f"================ CAMARF overnight research runner started (workers={args.workers}, "
         f"timeout={args.timeout_minutes}min/stage, platform={sys.platform}) ================")

    if not args.skip_warm_cache:
        _warm_cache(os.path.join(_ROOT, "output", "cache"), max_workers=args.workers * 2)

    # --- 00/00a/00b hard chain, 00c concurrent (audit-confirmed no read
    # dependency on 00/00a/00b) ---
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_chain = pool.submit(run_stage_until_success, "00_intraday_episodic_scan",
                               os.path.join("research", "intraday_episodic_scan.py"),
                               ["--tf", "both", "--workers", str(args.workers)])
        f_00c = pool.submit(run_stage, "00c_pit_wfa", "pit_wfa.py",
                             ["--workers", str(args.workers)], timeout_minutes=180)
        f_chain.result()
        f_00c.result()

    run_stage("00a_episodic_adapter", os.path.join("research", "episodic_pairs_adapter.py"),
               timeout_minutes=240)
    run_stage("00b_ml_pit_safe", "ml.py", ["--pit-safe"], timeout_minutes=args.timeout_minutes)

    # --- Stages 01-13: the 13 backtest.py variants, parallel batch ---
    state = _completed_stages()
    pending = [(n, a) for n, a in _BACKTEST_VARIANTS if n not in state]
    if pending:
        _log(f"Launching {len(pending)} backtest.py variants in parallel "
             f"(up to {min(args.workers, len(pending))} concurrent)")
        with ThreadPoolExecutor(max_workers=min(args.workers, len(pending))) as pool:
            futures = {pool.submit(run_stage, n, "backtest.py", a,
                                    args.timeout_minutes, state): n for n, a in pending}
            for fut in as_completed(futures):
                fut.result()  # exceptions surface here rather than being silently swallowed
    else:
        _log("SKIP    all 13 backtest.py variants already completed")

    # --- Stages 14-31, sequential (unchanged order) ---
    for name, script, script_args in _SEQUENTIAL_STAGES:
        run_stage(name, script, script_args, args.timeout_minutes)

    # --- Every research/*.py script, discovered dynamically, sequential
    # (NOT parallelized in this version -- see module docstring: ~90/121
    # scripts remain unaudited for cross-script output dependencies) ---
    research_dir = os.path.join(_ROOT, "research")
    research_scripts = sorted(glob.glob(os.path.join(research_dir, "*.py")))
    for i, rs in enumerate(research_scripts, start=100):
        base = os.path.splitext(os.path.basename(rs))[0]
        stage_name = f"r{i:03d}_{base}"
        run_stage(stage_name, os.path.join("research", os.path.basename(rs)), [], args.timeout_minutes)

    _log("================ CAMARF overnight research runner finished ================")
    done_count = len(_completed_stages())
    _log(f"Stages completed: {done_count}")


if __name__ == "__main__":
    main()
