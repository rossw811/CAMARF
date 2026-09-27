"""
Synthetic checks for the churn-loop comparison arms (2026-09-27, code review B16 + rule-invariant audit:
54-68% of real trades open at/past STOP_ZSCORE, 32-40% are stopped after a FAVORABLE move because the
stop is abs(z) >= STOP, and 19-38% re-enter within 1 bar of a stop).

New storm flags (default OFF -- legacy behaviour unchanged):
  directional_stop : stop only when |z| >= STOP_ZSCORE AND |z| has widened beyond |entry_z|
                     (the spread moved AGAINST the position), not merely "still above the stop".
  reentry_rearm    : after a stop exit, no new entry on the pair until |z| has first dropped back
                     below ENTRY_ZSCORE (hysteresis), breaking the enter -> stop -> re-enter loop.

Hand-built z path (ENTRY 3.0, STOP 3.5, EXIT 0.0):
  bars 0-79   : 0 (warm-up)
  bars 80-85  : 4.4, 4.3, 4.2, 4.1, 4.0, 3.9 (above the stop but moving FAVORABLY)
  bars 86-92  : 3.4 -> 0.4 (reversion)
  bars 93-99  : 0
  bars 100-104: 3.2, 3.6, 3.7, 3.8, 3.9 (a genuine ADVERSE widening from a normal entry)
  bars 105+   : 0
Expected:
  legacy          : >= 3 trades in bars 80-92, all "stop" (churn)
  directional     : 1 signal_exit trade from bar 80; the bar-100 trade is still stopped (at bar 101)
  rearm (legacy stop): exactly 1 trade in bars 80-92 (stop), no re-entry until |z| < 3
  entry cap 3.5   : no trade at bar 80 at all
Run: python debug/_verify_churn_fix_arms.py
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


def _spread_df():
    z = np.zeros(160)
    # First draft used linspace(4.4, 0.4, 13): z fell below the stop by bar 83, leaving room for only
    # one stop/re-enter cycle, so the fixture could not show repeated churn. Six bars above the stop:
    z[80:86] = [4.4, 4.3, 4.2, 4.1, 4.0, 3.9]
    z[86:93] = np.linspace(3.4, 0.4, 7)
    z[100:105] = [3.2, 3.6, 3.7, 3.8, 3.9]
    idx = pd.date_range("2024-01-02", periods=len(z), freq="1D")
    return pd.DataFrame({"z_rolling": z, "spread": z * 0.01, "half_life_rolling": np.full(len(z), 20.0),
                         "gap_flag_a": 0, "gap_flag_b": 0, "hedge_ratio_ols_t": 1.0,
                         "hedge_ratio_kalman_t": 1.0}, index=idx)


def _run(flags, cfg=None):
    cfg = cfg or copy.copy(Config.BACKTEST)
    cfg.ENTRY_ZSCORE, cfg.STOP_ZSCORE, cfg.EXIT_ZSCORE = 3.0, 3.5, 0.0
    row = pd.Series({"symbol_a": "A", "symbol_b": "B", "tf_label": "1D", "hedge_ratio_ols": 1.0,
                     "hedge_ratio_kalman_mean": 1.0, "hurst_rs": 0.3})
    eng = BacktestEngine(cfg=cfg, regime_cond=RegimeConditioner(enabled=False), ml_cond=MLConditioner(enabled=False),
                         layer2_enabled=False, storm_flags=flags)
    idx = _spread_df().index
    tr = eng.run(row, _spread_df(), "ols")
    return [(idx.get_loc(t.entry_time), idx.get_loc(t.exit_time), t.exit_reason) for t in tr]


def main():
    leg = _run({})
    first = [t for t in leg if 80 <= t[0] <= 92]
    stops = [x for x in first if x[2] == "stop" and x[1] - x[0] <= 1]
    check("legacy.churn", len(stops) >= 3, f"{len(stops)} immediate stop-outs: {first}")

    d = _run({"directional_stop": True})
    d1 = [t for t in d if 80 <= t[0] <= 92]
    check("directional.single_signal_exit", len(d1) == 1 and d1[0][2] == "signal_exit", f"{d1}")
    d2 = [t for t in d if t[0] == 100]
    check("directional.adverse_still_stopped", len(d2) == 1 and d2[0][2] == "stop" and d2[0][1] == 101, f"{d2}")

    r = _run({"reentry_rearm": True})
    r1 = [t for t in r if 80 <= t[0] <= 92]
    check("rearm.no_reentry_until_reset", len(r1) == 1 and r1[0][2] == "stop", f"{r1}")

    cfg = copy.copy(Config.BACKTEST)
    cfg.ENTRY_ZSCORE_MAX = 3.5
    c = _run({}, cfg)
    check("entry_cap.no_entry_past_stop", not any(t[0] == 80 for t in c), f"{c}")
    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
