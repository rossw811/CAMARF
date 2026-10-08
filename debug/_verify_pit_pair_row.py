"""
Regression test for code review S4 (verified 2026-10-07, fixed the same day): pit_wfa's test-window backtest row
(pair_row) took coint_fraction_rolling / half_life_trend_slope / mean_reversion_speed / hurst_rs from the TRAIN-only
screen (BUG-D69) but hedge_ratio_ols and hedge_ratio_kalman_mean from the train+TEST refit. backtest.py reads those
scalars to SKIP a pair (non-positive hedge) and as the fallback where the rolling hedge is missing -- test-period
data deciding whether and how a pair trades out of sample. Fix: pit_wfa._pit_pair_row takes every summary field the
backtest reads from the train-only screen result.
Checks: hedge_ratio_ols and hedge_ratio_kalman_mean come from the train-only result; the four BUG-D69 fields too;
per-bar/other fields still come from the full refit; tf_label set.
Run: python debug/_verify_pit_pair_row.py
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    import pit_wfa
    if not hasattr(pit_wfa, "_pit_pair_row"):
        check("helper_exists", False); return finish()
    full = SimpleNamespace(symbol_a="A", symbol_b="B", hedge_ratio_ols=-0.5, hedge_ratio_kalman_mean=-0.4,
                           coint_fraction_rolling=0.9, half_life_trend_slope=0.1, mean_reversion_speed=9.0,
                           hurst_rs=0.7, n_bars=999)
    train = SimpleNamespace(symbol_a="A", symbol_b="B", hedge_ratio_ols=1.2, hedge_ratio_kalman_mean=1.1,
                            coint_fraction_rolling=0.5, half_life_trend_slope=-0.2, mean_reversion_speed=0.3,
                            hurst_rs=0.4, n_bars=500)
    row = pit_wfa._pit_pair_row(full, train, "1D")
    check("hedge_ols_train_only", row["hedge_ratio_ols"] == 1.2, row["hedge_ratio_ols"])
    check("hedge_kalman_train_only", row["hedge_ratio_kalman_mean"] == 1.1, row["hedge_ratio_kalman_mean"])
    check("bug_d69_fields_train_only", (row["coint_fraction_rolling"], row["half_life_trend_slope"],
                                       row["mean_reversion_speed"], row["hurst_rs"]) == (0.5, -0.2, 0.3, 0.4))
    check("other_fields_from_full_refit", row["n_bars"] == 999)
    check("tf_label", row["tf_label"] == "1D")
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
