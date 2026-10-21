"""
X-M09 / code review S12 (FIX 2026-10-20): deflated_sharpe.py took N and Var[SR] over every registry entry -- identical
reruns counted as new trials, and in-sample and holdout Sharpes pooled into one family. Checks for
deflated_sharpe.trial_family(trials, holdout): identical reruns (same label, Sharpe and trade count) count once; a
genuinely different result under the same label counts; IS and holdout families are separate; main() uses the
family per suffix.
"""
import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import deflated_sharpe as d  # noqa: E402

T = [{"label": "layer1", "sharpe": 1.0, "n_trades": 100}, {"label": "layer1", "sharpe": 1.0, "n_trades": 100},
     {"label": "layer1", "sharpe": 1.2, "n_trades": 110}, {"label": "storm_x", "sharpe": 0.5, "n_trades": 90},
     {"label": "layer1_holdout", "sharpe": 0.3, "n_trades": 20}, {"label": "layer1_holdout", "sharpe": 0.3, "n_trades": 20},
     {"label": "storm_x_holdout", "sharpe": -0.1, "n_trades": 15}]
try:
    is_f = d.trial_family(T, holdout=False)
    ho_f = d.trial_family(T, holdout=True)
    check("identical reruns once; different results kept; IS only", len(is_f) == 3, f"{len(is_f)}")
    check("holdout family separate and deduplicated", len(ho_f) == 2, f"{len(ho_f)}")
except AttributeError as e:
    check("deflated_sharpe.trial_family exists", False, str(e))
check("main() uses trial_family per suffix", "trial_family(" in inspect.getsource(d.main))
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
