"""
scripts/build_bug_verdicts.py -- T14 bug recheck (plan W5.3): one verdict per logged bug, with evidence.
Inputs: docs/bug_recheck/inventory.csv (scripts/build_bug_inventory.py), a full-suite log
(debug/_run_all_verify.py output, default docs/bug_recheck/suite_20261007_cachyos.log) and the hand-made verdicts in
docs/bug_recheck/manual_verdicts.csv (id, verdict, evidence, date).
Rules: a manual verdict always wins; otherwise a bug with linked tests gets "tests-pass" only if EVERY linked test
passed, "tests-fail" if any failed, "tests-not-run" if a linked test is not in the log; no linked test and no
manual verdict -> "unchecked" (never assumed fine). "tests-pass" is weaker than a manual "holds": it says the linked
tests pass, not that they exercise this bug -- the independent sample check (W5.5) is what tests that.
Output: docs/bug_recheck/verdicts.csv; prints counts.
Usage: python scripts/build_bug_verdicts.py [suite_log]
Synthetic check: debug/_verify_build_bug_verdicts.py
"""
import os
import re
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "docs", "bug_recheck")
_LINE = re.compile(r"\]\s+(PASS|FAIL|TIMEOUT|ERROR)\s+\S*?(_verify_[^\s/\\]+\.py)")


def parse_suite_log(lines) -> dict:
    out = {}
    for ln in lines:
        m = _LINE.search(ln)
        if m:
            out[m.group(2)] = m.group(1)
    return out


def _tests(row) -> list:
    names = []
    for col in ("verify_scripts", "verify_scripts_by_content"):
        v = row.get(col)
        if isinstance(v, str) and v.strip():
            names += [x.strip() for x in v.split(";") if x.strip()]
    return sorted(set(names))


def merge(inventory: pd.DataFrame, results: dict, manual: pd.DataFrame) -> pd.DataFrame:
    man = {r["id"]: r for _, r in manual.iterrows()} if manual is not None and len(manual) else {}
    rows = []
    for _, r in inventory.iterrows():
        if r["id"] in man:
            m = man[r["id"]]
            rows.append({"id": r["id"], "verdict": m["verdict"], "evidence": m["evidence"], "date": m["date"],
                         "basis": "manual"})
            continue
        tests = _tests(r)
        if not tests:
            rows.append({"id": r["id"], "verdict": "unchecked", "evidence": "", "date": "", "basis": "none"})
            continue
        st = {t: results.get(t, "NOT-RUN") for t in tests}
        if any(v == "NOT-RUN" for v in st.values()):
            verdict = "tests-not-run"
        elif all(v == "PASS" for v in st.values()):
            verdict = "tests-pass"
        else:
            verdict = "tests-fail"
        rows.append({"id": r["id"], "verdict": verdict, "evidence": "; ".join(f"{t}: {v}" for t, v in st.items()),
                     "date": "", "basis": "suite"})
    return pd.DataFrame(rows)


def main():
    log = sys.argv[1] if len(sys.argv) > 1 else os.path.join(D, "suite_20261007_cachyos.log")
    inv = pd.read_csv(os.path.join(D, "inventory.csv"))
    mp = os.path.join(D, "manual_verdicts.csv")
    manual = pd.read_csv(mp) if os.path.exists(mp) else None
    res = parse_suite_log(open(log, encoding="utf-8", errors="replace").read().splitlines())
    out = merge(inv, res, manual)
    out["suite_log"] = os.path.basename(log)
    out.to_csv(os.path.join(D, "verdicts.csv"), index=False)
    print(f"{len(out)} bugs; suite log {os.path.basename(log)} ({len(res)} tests)")
    print(out["verdict"].value_counts().to_string())


if __name__ == "__main__":
    main()
