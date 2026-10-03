"""
Regression test for code-review B4 (fixed 2026-10-03, Ross-approved): `--hedge both` was the default and emitted
near-duplicate OLS and Kalman copies of every trade (momgate IS: 95,485 rows, 50,896 distinct) that the portfolio,
trial registry and capital-sim treated as independent. Now: OLS is the default, "both" is gone, and a Kalman run
writes under its own `_kalman` label (and --legacy-pnl under `_legacypnl`) so arms are never pooled or overwritten.
Checks: backtest.py --help lists `--hedge {ols,kalman}` with default ols and no "both"; the label code appends
`_kalman` / `_legacypnl`.
Run: python debug/_verify_backtest_hedge_default.py
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    out = subprocess.run([sys.executable, os.path.join(ROOT, "backtest.py"), "--help"], capture_output=True,
                         text=True, encoding="utf-8", env=env, cwd=ROOT).stdout
    m = re.search(r"--hedge \{([^}]*)\}\s+(.*?)\n\s+--", out, re.S)
    check("help_parses", bool(m), "" if m else out[-300:])
    if m:
        check("choices_ols_kalman_only", m.group(1) == "ols,kalman", m.group(1))
        check("default_ols", "default: ols" in " ".join(m.group(2).split()), " ".join(m.group(2).split())[:80])
    src = open(os.path.join(ROOT, "backtest.py"), encoding="utf-8").read()
    check("kalman_label", 'label += "_kalman"' in src)
    check("legacy_label", 'label += "_legacypnl"' in src)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
