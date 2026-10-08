"""
Synthetic check for scripts/build_bug_verdicts.py (T14.3-14.5 recheck, 2026-10-07; written before the script).
Merge rules: a manual verdict (docs/bug_recheck/manual_verdicts.csv) always wins; otherwise a bug with linked tests
(by name or content) gets "tests-pass" only if EVERY linked test passed in the suite log, "tests-fail" if any failed,
"tests-not-run" if a linked test is absent from the log; a bug with no linked test and no manual verdict is
"unchecked" -- never assumed fine.
Run: python debug/_verify_build_bug_verdicts.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    try:
        from scripts.build_bug_verdicts import merge, parse_suite_log
    except ImportError as e:
        check("module_exists", False, str(e)); return finish()
    log = ["[1/4] PASS  debug/_verify_a.py (1.0s)", "[2/4] FAIL  debug/_verify_b.py (2.0s)",
           "[3/4] PASS  debug/_verify_c.py (0.1s)", "[4/4] TIMEOUT  debug/_verify_d.py (300s)"]
    res = parse_suite_log(log)
    check("parse", res == {"_verify_a.py": "PASS", "_verify_b.py": "FAIL", "_verify_c.py": "PASS",
                           "_verify_d.py": "TIMEOUT"}, res)
    inv = pd.DataFrame({"id": ["X1", "X2", "X3", "X4", "X5", "X6"],
                        "verify_scripts": ["_verify_a.py", "_verify_a.py;_verify_b.py", None, "_verify_zzz.py",
                                           "_verify_b.py", None],
                        "verify_scripts_by_content": [None, None, "_verify_c.py", None, None, None]})
    manual = pd.DataFrame({"id": ["X5"], "verdict": ["holds"], "evidence": ["read code, commit abc"],
                           "date": ["2026-10-07"]})
    out = merge(inv, res, manual).set_index("id")
    check("all_pass", out.loc["X1", "verdict"] == "tests-pass")
    check("any_fail", out.loc["X2", "verdict"] == "tests-fail", out.loc["X2", "verdict"])
    check("content_match_counts", out.loc["X3", "verdict"] == "tests-pass")
    check("not_in_log", out.loc["X4", "verdict"] == "tests-not-run")
    check("manual_wins", out.loc["X5", "verdict"] == "holds" and out.loc["X5", "evidence"] == "read code, commit abc")
    check("no_test_unchecked", out.loc["X6", "verdict"] == "unchecked")
    check("evidence_names_tests", "_verify_b.py: FAIL" in out.loc["X2", "evidence"], out.loc["X2", "evidence"])
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
