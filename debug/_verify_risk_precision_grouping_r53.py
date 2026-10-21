"""
R5.3 (code review 2026-09-26, CONFIRMED; fixed 2026-10-20): strategy_risk_precision grouped trades by symbol pair only,
so OLS and Kalman copies of the same pair's trades (B4) were pooled: frequency doubled (implied annual Sharpe x sqrt 2)
and a pair with 5 trades per method passed the n >= 10 gate only through duplication. Checks for
precision_table(trades): one row per (pair, tf, hedge_method); 5 + 5 trades -> both skipped; frequency is per method.
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import strategy_risk_precision as m  # noqa: E402


def trades(sym_b, n, method, tf="1D"):
    t = pd.date_range("2020-01-01", periods=n, freq="30D")
    return pd.DataFrame({"symbol_a": "A", "symbol_b": sym_b, "tf": tf, "hedge_method": method, "entry_time": t,
                         "exit_time": t + pd.Timedelta(days=5), "pnl_net": [1.0 if i % 3 else -1.0 for i in range(n)]})


T = pd.concat([trades("B", 20, "ols"), trades("B", 20, "kalman"), trades("C", 5, "ols"), trades("C", 5, "kalman")])
try:
    out = m.precision_table(T)
    keys = sorted(zip(out["pair_key"], out["hedge_method"]))
    check("one row per (pair, tf, method); 5+5 pair skipped", keys == [("A/B", "kalman"), ("A/B", "ols")], f"{keys}")
    f = out["frequency_per_year"].iloc[0]
    ref = 20 / (((T[T.hedge_method == "ols"].exit_time.max() - T.entry_time.min()).days) / 365.25)
    check("frequency counts one method's trades", abs(f - ref) / ref < 0.05, f"{f:.2f} vs {ref:.2f}")
except AttributeError as e:
    check("precision_table exists", False, str(e))
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
