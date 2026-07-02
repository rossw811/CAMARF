"""
run_verify_suite.py — runs every debug/_verify_*.py synthetic verification
test and reports a pass/fail summary. One command in place of manually
running each script whenever a statistical computation changes.

Motivation (STORM infrastructure gap analysis, 2026-07-01): CONTRIBUTING.md
already documents debug/_verify_*.py as this project's test suite ("write or
update the corresponding synthetic test... before trusting the change on
real data"), but nothing previously ran the whole suite in one command —
each script had to be remembered and run individually. This is CI-lite, not
a CI/CD pipeline: no separate runner infra, just this project's existing
sys.exit(1)-on-failure convention (confirmed identical across all 18
existing debug/_verify_*.py scripts) collected into one summary.

Usage:
  C:\\Users\\RossW\\anaconda3\\envs\\trading\\python.exe run_verify_suite.py
  (add --fast to skip scripts tagged slow in _SLOW_SCRIPTS below)

Exit code: 0 if every script passed, 1 if any failed (so this can be used
as a pass/fail gate, e.g. before committing a change to a statistical
computation).
"""
import argparse
import glob
import os
import subprocess
import sys
import time

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DEBUG_DIR = os.path.join(_ROOT, "debug")

# Scripts known to take non-trivial time (real-data I/O, not just synthetic
# arithmetic) — skippable via --fast for a quick pre-commit check.
_SLOW_SCRIPTS = {"_verify_lead_lag_permutation_check.py", "_verify_macro_regimes.py"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", action="store_true",
                         help="Skip scripts in _SLOW_SCRIPTS")
    args = parser.parse_args()

    scripts = sorted(glob.glob(os.path.join(_DEBUG_DIR, "_verify_*.py")))
    if args.fast:
        scripts = [s for s in scripts if os.path.basename(s) not in _SLOW_SCRIPTS]

    results = []
    for script in scripts:
        name = os.path.relpath(script, _ROOT)
        t0 = time.time()
        proc = subprocess.run(
            [sys.executable, script], cwd=_ROOT,
            capture_output=True, text=True,
        )
        elapsed = time.time() - t0
        passed = proc.returncode == 0
        results.append((name, passed, elapsed, proc.stdout, proc.stderr))
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name} ({elapsed:.1f}s)")
        if not passed:
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-15:]
            for line in tail:
                print(f"    {line}")

    n_pass = sum(1 for _, p, *_ in results if p)
    n_fail = len(results) - n_pass
    print("=" * 60)
    print(f"{n_pass}/{len(results)} passed" + (f", {n_fail} FAILED" if n_fail else ""))

    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
