"""
BUG-D90 / X-C02 (bug recheck 2026-10-07: "fixed-untested"): fill_timing_sensitivity.py and breakout_vs_reversion.py
headline aggregates must pool trades across pairs before computing one Sharpe (BUG-D59 class), never average per-pair
ratios. Checks:
  1. breakout_vs_reversion.pooled_sharpe_like on two pairs = mean/s.d. of the concatenated trades, and differs from
     the per-pair average it replaced (a 2-trade noisy pair would otherwise dominate)
  2. degenerate inputs: < 2 trades or zero s.d. -> NaN
  3. fill_timing_sensitivity's headline Sharpes come from sharpe_from_trades on the pooled trade lists (source guard:
     the two calls exist and pct_degradation is computed from them, not from a per-pair column mean)
"""
import ast
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import breakout_vs_reversion as bvr  # noqa: E402

if not hasattr(bvr, "pooled_sharpe_like"):
    check("pooled_sharpe_like exists", False)
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1)
rng = np.random.default_rng(0)
p1 = [{"pnl_z": x} for x in rng.normal(0.1, 1.0, 200)]
p2 = [{"pnl_z": x} for x in (5.0, 5.1)]                    # 2 trades, tiny s.d.: huge per-pair ratio
allp = np.array([t["pnl_z"] for t in p1 + p2])
got = bvr.pooled_sharpe_like(p1 + p2)
per_pair = np.mean([bvr.pooled_sharpe_like(p1), bvr.pooled_sharpe_like(p2)])
check("1 pooled = mean/sd of concatenated trades, not the per-pair average",
      np.isclose(got, allp.mean() / allp.std()) and abs(per_pair - got) > 1.0, f"pooled {got:.3f} vs per-pair mean {per_pair:.3f}")
check("2 degenerate -> NaN", np.isnan(bvr.pooled_sharpe_like([])) and np.isnan(bvr.pooled_sharpe_like([{"pnl_z": 1.0}]))
      and np.isnan(bvr.pooled_sharpe_like([{"pnl_z": 1.0}, {"pnl_z": 1.0}])))

src = open(os.path.join(ROOT, "research", "fill_timing_sensitivity.py"), encoding="utf-8").read()
tree = ast.parse(src)
assigns = {}
for n in ast.walk(tree):
    if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
        assigns[n.targets[0].id] = ast.unparse(n.value)
ok = (assigns.get("pooled_sharpe_same_bar") == "sharpe_from_trades(trades_same_bar_df)"
      and assigns.get("pooled_sharpe_lagged") == "sharpe_from_trades(trades_lagged_df)"
      and "all_trades_same_bar" in assigns.get("trades_same_bar_df", "")
      and "pooled_sharpe_lagged" in assigns.get("pct_degradation", "")
      and "pooled_sharpe_same_bar" in assigns.get("pct_degradation", ""))
check("3 fill_timing headline = sharpe_from_trades on pooled trades", ok,
      str({k: assigns.get(k, "")[:70] for k in ("pooled_sharpe_same_bar", "trades_same_bar_df", "pct_degradation")}))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
