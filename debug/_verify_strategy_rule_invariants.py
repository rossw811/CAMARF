"""
Synthetic checks for research/strategy_rule_invariants.py (2026-09-27, Ross: "make sure all the rules
are happening as they actually should"). A hand-built trade log with exactly one planted violation per
rule; every invariant must count exactly the planted cases -- no more, no fewer.

Run: python debug/_verify_strategy_rule_invariants.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from research.strategy_rule_invariants import check_trade_invariants

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


P = dict(ENTRY_ZSCORE=3.0, STOP_ZSCORE=3.5, EXIT_ZSCORE=0.0, MAX_HOLD_MULTIPLIER=3.0, MIN_HALF_LIFE_BARS=2)


def t(i, entry_z, side, exit_z, reason, hold, hl=10.0, pair=("A", "B"), day=0, exit_day=None):
    e = pd.Timestamp("2026-01-05") + pd.Timedelta(days=day)
    x = e + pd.Timedelta(days=exit_day if exit_day is not None else max(hold, 1))
    return dict(symbol_a=pair[0], symbol_b=pair[1], tf="1D", hedge_method="ols", entry_time=e, exit_time=x,
                entry_z=entry_z, side=side, exit_z=exit_z, exit_reason=reason, hold_bars=hold,
                half_life_at_entry=hl)


def main():
    rows = [
        t(0, 3.2, "short", -0.1, "signal_exit", 5, pair=("P0", "Q")),            # clean
        t(1, 2.5, "short", -0.1, "signal_exit", 5, pair=("P1", "Q")),            # I1 entry below threshold
        t(2, 4.0, "short", 3.9, "stop", 1, pair=("P2", "Q")),                    # I2 entry past stop + favorable stop
        t(3, 3.2, "long", -3.6, "stop", 3, pair=("P3", "Q")),                    # I3 side wrong (z>0 must be short)
        t(4, 3.2, "short", 2.0, "stop", 3, pair=("P4", "Q")),                    # I4 stop w/o reaching stop level
        t(5, 3.2, "short", 1.0, "signal_exit", 3, pair=("P5", "Q")),             # I5 signal exit not crossed
        t(6, 3.2, "short", 1.0, "max_hold", 10, hl=10.0, pair=("P6", "Q")),      # I6 max_hold before limit 30
        t(7, 3.2, "short", -3.7, "stop", 4, pair=("P7", "Q")),                   # overshoot stop (sign flipped)
        t(8, 3.2, "short", -0.2, "signal_exit", 5, hl=1.0, pair=("P8", "Q")),    # I10 half-life below floor
        t(9, 3.2, "short", -0.1, "signal_exit", 10, pair=("P9", "Q"), day=0, exit_day=10),
        t(10, -3.3, "long", 0.1, "signal_exit", 3, pair=("P9", "Q"), day=5),     # I8 overlaps previous P9 trade
    ]
    r = check_trade_invariants(pd.DataFrame(rows), P)
    c = r["counts"]
    check("I1_entry_below_threshold", c["I1_entry_below_threshold"] == 1, f"{c['I1_entry_below_threshold']}")
    check("I2_entry_at_or_past_stop", c["I2_entry_at_or_past_stop"] == 1, f"{c['I2_entry_at_or_past_stop']}")
    check("I3_side_sign_mismatch", c["I3_side_sign_mismatch"] == 1, f"{c['I3_side_sign_mismatch']}")
    check("I4_stop_without_stop_level", c["I4_stop_without_stop_level"] == 1, f"{c['I4_stop_without_stop_level']}")
    check("I5_signal_exit_not_crossed", c["I5_signal_exit_not_crossed"] == 1, f"{c['I5_signal_exit_not_crossed']}")
    check("I6_max_hold_before_limit", c["I6_max_hold_before_limit"] == 1, f"{c['I6_max_hold_before_limit']}")
    check("I8_overlapping_positions", c["I8_overlapping_positions"] == 1, f"{c['I8_overlapping_positions']}")
    check("I10_half_life_below_floor", c["I10_half_life_below_floor"] == 1, f"{c['I10_half_life_below_floor']}")
    check("S1_favorable_move_stops", c["S1_stop_after_favorable_move"] == 1, f"{c['S1_stop_after_favorable_move']}")
    check("S2_overshoot_stops", c["S2_stop_on_overshoot_through_zero"] == 2, f"{c['S2_stop_on_overshoot_through_zero']}")
    check("dead_rules_listed", "corr_exit" in r["never_fired"], f"{r['never_fired']}")

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
