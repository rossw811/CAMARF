"""
Regression test (2026-10-07): "dollar P&L the default everywhere" (Ross, 2026-10-03) was applied only where a caller
invoked backtest.apply_pnl_basis after BacktestEngine.run -- backtest.py's main path and pit_wfa_wrds_daily. Twelve
other callers (pit_wfa.py, distance.py, sensitivity.py, run_storm_grid.py and 8 research scripts) used the engine's
retired spread-unit P&L (B2/B3: hedge drift = all positive gross P&L on 2,062 real trades). Found while checking an
independent-check side note on run_storm_grid. Fix at the shared point: BacktestEngine.run applies the dollar basis
to every trade it returns (legacy only with BacktestEngine(legacy_pnl=True), labelled known-wrong) and records the
unpriceable drops in engine.last_pnl_dropped; apply_pnl_basis is idempotent (already-dollar trades pass through, so
the existing post-run calls do not overwrite pnl_legacy_* with dollar values).
Checks (a real saved 1D spread series + its pairs.parquet row; prices from the WRDS cache):
  1. engine.run's trades are all pnl_basis == "dollar" (and pnl_legacy_net kept);
  2. BacktestEngine(legacy_pnl=True).run -> "legacy_known_wrong", spread-unit values;
  3. apply_pnl_basis on already-dollar trades changes nothing (pnl_net and pnl_legacy_net identical);
  4. engine.last_pnl_dropped is a dict of drop counts.
Run: python debug/_verify_engine_dollar_default.py
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    import backtest
    from config import Config
    pairs = pd.read_parquet("output/results/1day/pairs.parquet")
    found = None
    for _, row in pairs.iterrows():
        p = f"output/results/1day/spread_series_{row['symbol_a']}_{row['symbol_b']}.parquet"
        if not os.path.exists(p):
            continue
        sp = pd.read_parquet(p)
        eng = backtest.BacktestEngine(cfg=Config.BACKTEST, regime_cond=backtest.RegimeConditioner(enabled=False),
                                      ml_cond=backtest.MLConditioner(enabled=False))
        tr = eng.run(row, sp, hedge_method="ols", holdout_only=False)
        if tr:
            found = (row, sp, eng, tr)
            break
    if found is None:
        check("a_real_pair_trades", False, "no saved 1D pair produced trades"); return finish()
    row, sp, eng, tr = found
    print(f"pair {row['symbol_a']}/{row['symbol_b']}: {len(tr)} trades")
    check("1.run_returns_dollar", all(getattr(t, "pnl_basis", None) == "dollar" for t in tr),
          sorted({getattr(t, "pnl_basis", None) for t in tr}, key=str))
    check("1b.legacy_values_kept", all(getattr(t, "pnl_legacy_net", None) is not None for t in tr))
    try:
        leg = backtest.BacktestEngine(cfg=Config.BACKTEST, regime_cond=backtest.RegimeConditioner(enabled=False),
                                      ml_cond=backtest.MLConditioner(enabled=False), legacy_pnl=True)
        lt = leg.run(row, sp, hedge_method="ols", holdout_only=False)
        check("2.legacy_engine_labelled", lt and all(t.pnl_basis == "legacy_known_wrong" for t in lt))
    except TypeError as e:
        check("2.legacy_engine_labelled", False, str(e))
    before = [(t.pnl_net, getattr(t, "pnl_legacy_net", None)) for t in tr]
    again, _ = backtest.apply_pnl_basis(list(tr), cfg=eng.cfg)
    after = [(t.pnl_net, getattr(t, "pnl_legacy_net", None)) for t in again]
    check("3.apply_idempotent", before == after and len(again) == len(tr), f"{before[:2]} vs {after[:2]}")
    check("4.drops_recorded", isinstance(getattr(eng, "last_pnl_dropped", None), dict))
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
