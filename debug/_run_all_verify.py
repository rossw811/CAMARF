"""
debug/_run_all_verify.py -- runs every debug/_verify_*.py script and reports
a single pass/fail/error summary, instead of the manual one-at-a-time
invocation this project has relied on all along (256 verify scripts as of
2026-09-20, none previously run automatically). Intended as the CI entry
point (a single command a git hook / GitHub Action can call) and as a fast
local sanity sweep before trusting a real run.

Classification, not just exit code, because a verify script can fail for
reasons that are NOT "the code is broken":
  PASS  -- exit 0
  FAIL  -- exit nonzero, ran to completion (a real check failed)
  ERROR -- exit nonzero via exception/traceback before any check ran, OR
           timed out. Usually a missing local dependency (a data file that
           only exists on CachyOS, a package not installed in this env) --
           reported separately from FAIL so a real logic failure doesn't
           get lost in a pile of environment-only noise.

Each script runs in its own subprocess (matches this project's existing
"python debug/_verify_X.py" convention exactly -- no import-time side
effects from one script's module-level code leaking into another's run).

Usage:
    python debug/_run_all_verify.py                    # run everything
    python debug/_run_all_verify.py --pattern hedge     # only matching scripts
    python debug/_run_all_verify.py --timeout 60        # per-script timeout (default 120s)
    python debug/_run_all_verify.py --workers 4         # parallel (default: sequential, 1)
"""
import argparse
import glob
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEBUG_DIR = os.path.join(_ROOT, "debug")


def discover_verify_scripts(pattern: str = None) -> list:
    files = sorted(glob.glob(os.path.join(_DEBUG_DIR, "_verify_*.py")))
    if pattern:
        files = [f for f in files if pattern.lower() in os.path.basename(f).lower()]
    return files


def run_one(path: str, timeout: int) -> dict:
    name = os.path.relpath(path, _ROOT)
    t0 = time.time()
    try:
        result = subprocess.run(
            [sys.executable, path], cwd=_ROOT, capture_output=True, text=True, timeout=timeout,
        )
        elapsed = time.time() - t0
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0:
            status = "PASS"
        elif "Traceback (most recent call last)" in output and _looks_like_pre_check_crash(output):
            status = "ERROR"
        else:
            status = "FAIL"
        return {"name": name, "status": status, "elapsed": elapsed,
                "returncode": result.returncode, "output": output}
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        return {"name": name, "status": "ERROR", "elapsed": elapsed,
                "returncode": None, "output": f"TIMEOUT after {timeout}s"}
    except Exception as e:
        elapsed = time.time() - t0
        return {"name": name, "status": "ERROR", "elapsed": elapsed,
                "returncode": None, "output": f"{type(e).__name__}: {e}"}


def _looks_like_pre_check_crash(output: str) -> bool:
    """Heuristic: if the script's own PASS/FAIL check markers never printed
    at all before the traceback, this is an environment/import-time crash
    (ERROR), not a real check failure (FAIL) -- e.g. a missing data file
    causing FileNotFoundError before any assertion runs. Scripts vary in
    their own print conventions ([PASS]/[FAIL], ALL CHECKS PASSED, etc.) so
    this checks for the traceback appearing with NO check-marker text
    anywhere before it, a reasonably robust signal across this project's
    inconsistent-but-real conventions."""
    idx = output.find("Traceback (most recent call last)")
    if idx == -1:
        return False
    before = output[:idx]
    markers = ("[PASS]", "[FAIL]", "PASSED", "FAILED", "checks passed")
    return not any(m in before for m in markers)


def main():
    p = argparse.ArgumentParser(description="Run every debug/_verify_*.py and summarize")
    p.add_argument("--pattern", default=None, help="Only run scripts whose filename contains this substring")
    p.add_argument("--timeout", type=int, default=120, help="Per-script timeout in seconds (default 120)")
    p.add_argument("--workers", type=int, default=1, help="Parallel workers (default 1, sequential)")
    args = p.parse_args()

    scripts = discover_verify_scripts(args.pattern)
    if not scripts:
        print("No matching debug/_verify_*.py scripts found.")
        sys.exit(1)

    print(f"Running {len(scripts)} verify scripts (timeout={args.timeout}s, workers={args.workers})...\n")

    results = []
    t0 = time.time()
    if args.workers <= 1:
        for i, path in enumerate(scripts, 1):
            r = run_one(path, args.timeout)
            results.append(r)
            print(f"[{i}/{len(scripts)}] {r['status']:5s} {r['name']} ({r['elapsed']:.1f}s)")
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(run_one, path, args.timeout): path for path in scripts}
            for i, fut in enumerate(as_completed(futures), 1):
                r = fut.result()
                results.append(r)
                print(f"[{i}/{len(scripts)}] {r['status']:5s} {r['name']} ({r['elapsed']:.1f}s)")

    total_elapsed = time.time() - t0
    passed = [r for r in results if r["status"] == "PASS"]
    failed = [r for r in results if r["status"] == "FAIL"]
    errored = [r for r in results if r["status"] == "ERROR"]

    print(f"\n{'='*70}")
    print(f"SUMMARY: {len(passed)} passed, {len(failed)} FAILED, {len(errored)} errored "
          f"(of {len(results)} total, {total_elapsed:.1f}s)")
    print(f"{'='*70}")

    if failed:
        print(f"\n--- FAILED ({len(failed)}, real check failures) ---")
        for r in failed:
            print(f"  {r['name']}")

    if errored:
        print(f"\n--- ERRORED ({len(errored)}, likely environment/missing-dependency, "
              f"not necessarily a real bug) ---")
        for r in errored:
            first_line = next((l for l in r["output"].splitlines() if l.strip()), "")
            print(f"  {r['name']}: {first_line[:100]}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
