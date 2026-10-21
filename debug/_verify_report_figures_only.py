"""
report.py retired to figures only (Ross, DECISIONS_2026-10-21 #4): its generated LaTeX paper (main.tex, references.bib)
carried frozen narrative that still stated withdrawn results. PAPER.md / PAPER_MAGNITUDE.md are the papers. Checks:
  1. no narrative/table builders remain (build_main_tex, build_bib, table_*, _booktabs_table)
  2. main() on an empty output tree writes no .tex / .bib / compile.bat, and does not crash
"""
import ast
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


src = open(os.path.join(ROOT, "report.py"), encoding="utf-8").read()
names = {n.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)}
left = sorted(n for n in names if n in ("build_main_tex", "build_bib", "_booktabs_table") or n.startswith("table_"))
check("1 no narrative or LaTeX-table builders", not left, str(left))

import report  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    for attr in ("_STATS_DIR", "_BACKTEST_DIR", "_RESULTS_DIR"):
        setattr(report, attr, os.path.join(td, "empty"))
    report._REPORT_DIR = os.path.join(td, "report")
    report._FIG_DIR = os.path.join(report._REPORT_DIR, "figures")
    ok = True
    try:
        report.main()
    except Exception as e:  # noqa: BLE001
        ok = False
        print(type(e).__name__, e)
    written = [os.path.join(dp, f) for dp, _, fs in os.walk(td) for f in fs]
    bad = [f for f in written if f.endswith((".tex", ".bib", ".bat"))]
    check("2 main() runs and writes no .tex/.bib/.bat", ok and not bad, str(bad))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
