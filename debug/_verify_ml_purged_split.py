"""
R2.3 (code review 2026-09-26, fixed 2026-10-20): ml.py split train/val/test by row position with no purge or embargo
while labels look forward and many pairs share dates. Checks:
  1. ml.purged_embargoed_split: membership by entry_time; train events whose label ends at/after the val boundary are
     purged (val likewise vs the test boundary); embargo drops val/test events right after each boundary;
  2. a label_end_time of NaT is purged from train/val (unknown horizon: never assumed safe);
  3. ml._chronological_split_impute with `times` applies that split and fits the median on train only;
  4. _train_and_validate passes the events' times (source check), and the research script reuses ml's split.
"""
import inspect
import os
import sys

import numpy as np
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
    split = ml.purged_embargoed_split
except AttributeError as e:
    print(f"[FAIL] ml.purged_embargoed_split exists: {e}\n\n0/1 checks passed")
    sys.exit(1)

t = pd.date_range("2020-01-01", periods=10, freq="D")
df = pd.DataFrame({"entry_time": t, "label_end_time": t + pd.Timedelta(days=3)})
df.loc[1, "label_end_time"] = pd.NaT
s = split(df, purge=True, embargo=pd.Timedelta(days=1), train_pct=0.6, val_pct=0.2)
bv, bt = s["boundary_val"], s["boundary_test"]
check("1a. boundaries at rows 6 and 8", bv == t[6] and bt == t[8], f"{bv} {bt}")
tr = df.loc[s["train"]]
check("1b. train labels end before the val boundary", (tr["label_end_time"] < bv).all() and len(tr) == 2,
      f"train rows {list(s['train'])}")
check("1c. embargo drops events right after each boundary", list(s["val"]) == [] and list(s["test"]) == [9],
      f"val {list(s['val'])} test {list(s['test'])}")
check("2. NaT label end purged", 1 not in set(s["train"]))

X = pd.DataFrame({"f": [1.0, np.nan, 3.0, np.nan, 5.0, 6.0, 7.0, 8.0, 9.0, 100.0]})
y = np.arange(10) % 2
out = ml._chronological_split_impute(X, y, 0.6, 0.2, times=df, embargo_pct=0.1)
X_tr, y_tr, X_va, y_va, X_te, y_te, med = out
check("3a. split applied (train = rows 0, 2)", list(X_tr.index) == [0, 2], f"{list(X_tr.index)}")
check("3b. median from the purged train rows only", float(med["f"]) == 2.0, f"{float(med['f'])}")
check("3c. labels follow the rows", list(y_tr) == [0, 0] and len(X_te) == len(y_te))

src = inspect.getsource(ml._train_and_validate)
check("4a. _train_and_validate passes times", "times=" in src)
import importlib  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "research"))
rs = importlib.import_module("research.ml_model_comparison_purged")
check("4b. research script reuses ml's split", rs.purged_embargoed_split is ml.purged_embargoed_split)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
