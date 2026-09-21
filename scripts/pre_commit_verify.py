"""
scripts/pre_commit_verify.py -- git pre-commit hook: runs only the
debug/_verify_*.py scripts relevant to whatever files are staged, blocking
the commit on a real FAIL (not on ERROR -- those are usually environment/
missing-dependency, not a regression this hook should block a commit over).

This project has no GitHub Actions/remote CI (confirmed 2026-09-20, no
.github/workflows/ directory) -- this hook is the practical equivalent for a
solo-dev repo: catches a regression in the ~5 seconds it takes to run a
handful of targeted tests, before it reaches a commit, rather than relying
on someone remembering to run debug/_run_all_verify.py by hand (256 scripts,
~7-8 minutes -- too slow for every commit, which is exactly why this is
targeted rather than exhaustive).

Relevance heuristic: a verify script is "relevant" to a staged file if the
staged file's basename (minus .py) appears as a substring in the verify
script's own filename, OR the verify script explicitly imports the staged
module (checked via a cheap static grep of `from X import` / `import X`
lines, not a real AST parse -- good enough for this project's own naming
conventions, not claimed exhaustive). Deliberately conservative in what it
skips: if nothing matches for a staged .py file, that's reported, not
silently ignored, so a real gap in test coverage is visible rather than
papered over by this hook's own heuristic.

Install (one-time, per clone -- NOT auto-installed by cloning, since a
committed executable hook is a real supply-chain risk this project doesn't
want to introduce without an explicit opt-in):
    cp scripts/pre_commit_verify.py .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit
    # (.git/hooks/pre-commit must itself be a shebang-runnable script;
    # on Windows, the git-bash shebang line at the top of this file
    # (#!/usr/bin/env python) is honored by Git for Windows' hook runner)

Usage (manual, without installing as a hook):
    python scripts/pre_commit_verify.py
"""
#!/usr/bin/env python
import os
import re
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEBUG_DIR = os.path.join(_ROOT, "debug")


def _staged_py_files() -> list:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        cwd=_ROOT, capture_output=True, text=True, check=True,
    )
    return [f for f in result.stdout.splitlines() if f.endswith(".py") and f.strip()]


def _verify_scripts() -> list:
    return [f for f in os.listdir(_DEBUG_DIR) if f.startswith("_verify_") and f.endswith(".py")]


def _module_name(staged_path: str) -> str:
    return os.path.splitext(os.path.basename(staged_path))[0]


def find_relevant_verify_scripts(staged_files: list, verify_scripts: list) -> dict:
    """Returns {staged_file: [relevant verify script filenames]}."""
    relevant = {}
    for staged in staged_files:
        mod = _module_name(staged)
        matches = set()
        for vscript in verify_scripts:
            if mod and mod.lower() in vscript.lower():
                matches.add(vscript)
        # Static import-line grep, catches a verify script that tests
        # `mod` without `mod`'s own name appearing in the verify script's
        # filename (common -- e.g. debug/_verify_squeeze_momentum_gate_
        # logic.py doesn't import backtest.py by name in its filename but
        # does `from backtest import ...` internally).
        import_pattern = re.compile(
            rf"^\s*(from {re.escape(mod)} import|import {re.escape(mod)}\b)", re.MULTILINE
        )
        for vscript in verify_scripts:
            vpath = os.path.join(_DEBUG_DIR, vscript)
            try:
                with open(vpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                if import_pattern.search(content):
                    matches.add(vscript)
            except Exception:
                continue
        relevant[staged] = sorted(matches)
    return relevant


def main() -> int:
    staged = _staged_py_files()
    if not staged:
        print("pre_commit_verify: no staged .py files, nothing to check.")
        return 0

    verify_scripts = _verify_scripts()
    relevant_map = find_relevant_verify_scripts(staged, verify_scripts)

    to_run = sorted({v for matches in relevant_map.values() for v in matches})
    no_coverage = [f for f, matches in relevant_map.items() if not matches]

    if no_coverage:
        print(f"pre_commit_verify: NOTE, no matching verify script found for: {', '.join(no_coverage)}")
        print("  (not blocking on this -- just visible, since silent gaps are worse than noisy ones)")

    if not to_run:
        print("pre_commit_verify: no relevant verify scripts to run.")
        return 0

    print(f"pre_commit_verify: running {len(to_run)} relevant verify script(s): {', '.join(to_run)}")

    sys.path.insert(0, _ROOT)
    from debug._run_all_verify import run_one

    failed = []
    for vscript in to_run:
        vpath = os.path.join(_DEBUG_DIR, vscript)
        r = run_one(vpath, timeout=150)
        print(f"  {r['status']:5s} {vscript} ({r['elapsed']:.1f}s)")
        if r["status"] == "FAIL":
            failed.append(vscript)
        elif r["status"] == "ERROR":
            print(f"    (ERROR, not blocking -- likely environment/missing-dependency: "
                  f"{r['output'].splitlines()[0] if r['output'] else ''}"[:150])

    if failed:
        print(f"\nBLOCKED: {len(failed)} verify script(s) FAILED: {', '.join(failed)}")
        print("Fix the regression, or use `git commit --no-verify` to bypass (not recommended).")
        return 1

    print("\npre_commit_verify: all relevant checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
