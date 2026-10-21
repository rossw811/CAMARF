"""
Sealed holdout in ml.build (E13; 2026-10-20). Pool spread series include Compustat Global bars dated 2026, so entry
events and their forward labels could fall on sealed dates. Checks: ml._seal_examples drops every example whose
entry or label end is on/after Config.DATA.SEALED_FROM, and examples with an unknown label end (NaT); ml.build calls it.
"""
import inspect
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import ml  # noqa: E402

try:
    df = pd.DataFrame({"entry_time": pd.to_datetime(["2025-06-01", "2025-12-20", "2026-02-01", "2025-05-01"]),
                       "label_end_time": pd.to_datetime(["2025-06-10", "2026-01-05", "2026-02-10", None])})
    out = ml._seal_examples(df)
    check("drops sealed entries/labels and NaT label ends", list(out.index) == [0], f"{list(out.index)}")
except AttributeError as e:
    check("ml._seal_examples exists", False, str(e))
check("ml.build calls _seal_examples", "_seal_examples(" in inspect.getsource(ml.build))
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
