"""
Synthetic check for the point-in-time pair-eligibility gate (2026-09-27, Design 2; fixes the pair-level
selection lookahead in code review S3). A pairs-override row may carry `eligible_from` (the end date of the
window that confirmed the pair); BacktestEngine must refuse every entry before that timestamp and behave
exactly as before when the column is absent or NaT.

Fixture: z crosses the entry band twice (bars 60 and 120). With eligible_from between them, only the second
entry may trade; without it, both trade.

Run: python debug/_verify_eligible_from_gate.py
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from backtest import BacktestEngine, MLConditioner, RegimeConditioner
from config import Config

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    z = np.zeros(200)
    z[60:66] = [3.2, 2.5, 1.5, 0.8, 0.2, -0.1]
    z[120:126] = [3.2, 2.5, 1.5, 0.8, 0.2, -0.1]
    idx = pd.date_range("2020-01-01", periods=len(z), freq="1D")
    sp = pd.DataFrame({"z_rolling": z, "spread": z * 0.01, "half_life_rolling": 20.0, "gap_flag_a": 0,
                       "gap_flag_b": 0, "hedge_ratio_ols_t": 1.0, "hedge_ratio_kalman_t": 1.0}, index=idx)
    cfg = copy.copy(Config.BACKTEST)
    cfg.ENTRY_ZSCORE, cfg.STOP_ZSCORE, cfg.EXIT_ZSCORE = 3.0, 3.5, 0.0
    eng = BacktestEngine(cfg=cfg, regime_cond=RegimeConditioner(enabled=False), ml_cond=MLConditioner(enabled=False),
                         layer2_enabled=False)
    base = {"symbol_a": "A", "symbol_b": "B", "tf_label": "1D", "hedge_ratio_ols": 1.0,
            "hedge_ratio_kalman_mean": 1.0, "hurst_rs": 0.3}
    ent = lambda tr: [idx.get_loc(t.entry_time) for t in tr]
    no_col = ent(eng.run(pd.Series(base), sp, "ols"))
    nat = ent(eng.run(pd.Series({**base, "eligible_from": pd.NaT}), sp, "ols"))
    gated = ent(eng.run(pd.Series({**base, "eligible_from": idx[90]}), sp, "ols"))
    on_day = ent(eng.run(pd.Series({**base, "eligible_from": idx[120]}), sp, "ols"))
    check("no_column_unchanged", no_col == [60, 120], f"{no_col}")
    check("nat_unchanged", nat == [60, 120], f"{nat}")
    check("entries_before_eligible_from_blocked", gated == [120], f"{gated}")
    check("entry_on_eligible_date_allowed", on_day == [120], f"{on_day}")
    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
