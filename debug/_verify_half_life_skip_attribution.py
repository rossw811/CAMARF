"""
Regression test (2026-09-27): backtest.py counted a FINITE half-life below MIN_HALF_LIFE_BARS and a NaN
half-life as the same skip and warned "non-finite half-life" for both -- the real case was two share
classes of one company (GVKEY031142_01W/_03W: 33 entry bars, half-lives 0.19-3.97 days, none NaN).
Checks the engine now attributes each skip correctly and only emits the upstream-bug WARNING for NaN.
Run: python debug/_verify_half_life_skip_attribution.py
"""
import copy, logging, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
import backtest as bt
from config import Config

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


class Cap(logging.Handler):
    def __init__(self):
        super().__init__(); self.recs = []
    def emit(self, r):
        self.recs.append((r.levelno, r.getMessage()))


def run(hl_value):
    z = np.zeros(120); z[70:74] = [3.2, 2.0, 1.0, -0.1]
    idx = pd.date_range("2020-01-01", periods=len(z), freq="1D")
    sp = pd.DataFrame({"z_rolling": z, "spread": z * 0.01, "half_life_rolling": hl_value, "gap_flag_a": 0,
                       "gap_flag_b": 0, "hedge_ratio_ols_t": 1.0, "hedge_ratio_kalman_t": 1.0}, index=idx)
    cfg = copy.copy(Config.BACKTEST); cfg.ENTRY_ZSCORE = 3.0; cfg.MIN_HALF_LIFE_BARS = 5
    eng = bt.BacktestEngine(cfg=cfg, regime_cond=bt.RegimeConditioner(enabled=False),
                            ml_cond=bt.MLConditioner(enabled=False), layer2_enabled=False)
    h = Cap(); bt.log.addHandler(h)
    try:
        tr = eng.run(pd.Series({"symbol_a": "A", "symbol_b": "B", "tf_label": "1D", "hedge_ratio_ols": 1.0,
                                "hedge_ratio_kalman_mean": 1.0, "hurst_rs": 0.3}), sp, "ols")
    finally:
        bt.log.removeHandler(h)
    return tr, h.recs


def main():
    tr, recs = run(0.5)
    warn = [m for lv, m in recs if lv >= logging.WARNING and "half-life" in m]
    info = [m for lv, m in recs if lv == logging.INFO and "below MIN_HALF_LIFE_BARS" in m]
    check("fast_reverting.no_trades", len(tr) == 0)
    check("fast_reverting.no_upstream_bug_warning", not warn, f"{warn}")
    check("fast_reverting.reported_as_below_floor", len(info) == 1, f"{info}")
    tr2, recs2 = run(np.nan)
    warn2 = [m for lv, m in recs2 if lv >= logging.WARNING and "NaN half-life" in m]
    check("nan_half_life.still_warns", len(tr2) == 0 and len(warn2) == 1, f"{warn2}")
    tr3, _ = run(20.0)
    check("normal_half_life.trades", len(tr3) == 1, f"{len(tr3)}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
