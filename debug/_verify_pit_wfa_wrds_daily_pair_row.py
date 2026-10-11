"""
Code review R1.13 (confirmed 2026-10-10): research/pit_wfa_wrds_daily.py built the engine's pair row from
**vars(full_pair_result) -- a _build_pair_result fitted on the aligned train_start..test_end window -- and overrode
only four filter scalars with the train-only values. The hedge ratios (hedge_ratio_ols, hedge_ratio_kalman_mean) that
the backtest's skip/fallback logic reads therefore came from train+test data: the S4 leak, fixed in pit_wfa.py
(pit_wfa._pit_pair_row / _TRAIN_ONLY_FIELDS, debug/_verify_pit_pair_row.py) but not in this script.
Written failing-first. Checks:
  1. pit_wfa_wrds_daily exposes _pair_row(full, train, tf_label) and it takes every _TRAIN_ONLY_FIELDS value
     (including both hedge ratios) from the train-only result
  2. per-bar fields not in _TRAIN_ONLY_FIELDS still come from the full result
  3. backtest_pair_on_test_window builds its row through _pair_row (no hand-built copy left)
Run: python debug/_verify_pit_wfa_wrds_daily_pair_row.py
"""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.argv = [sys.argv[0]]
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    import pit_wfa
    import pit_wfa_wrds_daily as m
    pr = getattr(m, "_pair_row", None)
    check("pair_row_exists", pr is not None)
    if pr is not None:
        full = SimpleNamespace(symbol_a="A", symbol_b="B", hedge_ratio_ols=9.0, hedge_ratio_kalman_mean=9.5,
                               coint_fraction_rolling=0.9, half_life_trend_slope=1.0, mean_reversion_speed=0.9,
                               hurst_rs=0.9, half_life=99.0)
        train = SimpleNamespace(symbol_a="A", symbol_b="B", hedge_ratio_ols=1.0, hedge_ratio_kalman_mean=1.5,
                                coint_fraction_rolling=0.1, half_life_trend_slope=-1.0, mean_reversion_speed=0.1,
                                hurst_rs=0.1, half_life=5.0)
        row = pr(full, train, "1D")
        bad = [f for f in pit_wfa._TRAIN_ONLY_FIELDS if row[f] != getattr(train, f)]
        check("train_only_fields_from_train", not bad, bad)
        check("hedge_ratios_from_train", row["hedge_ratio_ols"] == 1.0 and row["hedge_ratio_kalman_mean"] == 1.5,
              (row["hedge_ratio_ols"], row["hedge_ratio_kalman_mean"]))
        check("other_fields_from_full", row["half_life"] == 99.0 and row["tf_label"] == "1D")
    src = open(m.__file__, encoding="utf-8").read()
    body = src[src.index("def backtest_pair_on_test_window("):]
    body = body[:body.index("\ndef ", 10)]
    check("backtest_uses_pair_row", "_pair_row(full_pair_result, pair_result" in body
          and "**vars(full_pair_result)" not in body)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
