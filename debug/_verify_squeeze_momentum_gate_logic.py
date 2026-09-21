"""
Synthetic verification of backtest.py's squeeze_gate/momentum_gate/
squeeze_momentum_gate entry-condition logic (2026-09-15, Ross's direct
instruction). Mirrors the exact condition expressions from BacktestEngine.run()
rather than driving the full engine (no existing precedent in this codebase
for fixturing BacktestEngine.run() end-to-end for a single STORM gate; this
project's convention for STORM gates has been empirical real-run validation
instead -- see docs/HANDOFF.md for the real backtest run this accompanies).
Catches logic-only bugs (sign errors, threshold direction, NaN handling)
cheaply, before trusting a real multi-hour comparison-arm run.

Run: python debug/_verify_squeeze_momentum_gate_logic.py
"""
import sys

import numpy as np

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


_SQUEEZE_THRESHOLD = 1.0


def squeeze_gate_allows(sq_a: float, sq_b: float) -> bool:
    """Mirrors backtest.py's squeeze_gate condition exactly."""
    if not (np.isfinite(sq_a) and np.isfinite(sq_b)):
        return False
    return sq_a < _SQUEEZE_THRESHOLD and sq_b < _SQUEEZE_THRESHOLD


def momentum_gate_allows(z: float, rsi_diff_velocity: float) -> bool:
    """Mirrors backtest.py's momentum_gate condition exactly."""
    if not np.isfinite(rsi_diff_velocity):
        return False
    if z > 0 and rsi_diff_velocity >= 0:
        return False
    if z < 0 and rsi_diff_velocity <= 0:
        return False
    return True


def test_squeeze_gate_both_legs_squeezed_allows():
    check("squeeze_gate.both_legs_below_1.0_allows_entry",
          squeeze_gate_allows(0.6, 0.8) is True)


def test_squeeze_gate_one_leg_not_squeezed_blocks():
    check("squeeze_gate.one_leg_above_1.0_blocks_entry",
          squeeze_gate_allows(0.6, 1.2) is False)


def test_squeeze_gate_both_legs_not_squeezed_blocks():
    check("squeeze_gate.both_legs_above_1.0_blocks_entry",
          squeeze_gate_allows(1.3, 1.5) is False)


def test_squeeze_gate_exactly_at_threshold_blocks():
    # <1.0 is strict, per the standard TTM-squeeze convention -- exactly 1.0
    # is NOT a squeeze (BB width == Keltner width, the boundary case).
    check("squeeze_gate.exactly_1.0_is_not_a_squeeze_blocks",
          squeeze_gate_allows(1.0, 0.5) is False)


def test_squeeze_gate_nan_fails_closed():
    check("squeeze_gate.nan_leg_a_fails_closed",
          squeeze_gate_allows(float("nan"), 0.5) is False)
    check("squeeze_gate.nan_leg_b_fails_closed",
          squeeze_gate_allows(0.5, float("nan")) is False)


def test_momentum_gate_positive_z_negative_velocity_allows():
    # z>0: symbol_a relatively too high, short-A/long-B expected on reversion.
    # Momentum confirms when A's relative RSI momentum is COOLING (velocity<0).
    check("momentum_gate.z_positive_velocity_negative_allows",
          momentum_gate_allows(z=2.5, rsi_diff_velocity=-3.0) is True)


def test_momentum_gate_positive_z_positive_velocity_blocks():
    # Momentum still accelerating in A's favor -- contradicts the implied
    # short-A trade, should block.
    check("momentum_gate.z_positive_velocity_positive_blocks",
          momentum_gate_allows(z=2.5, rsi_diff_velocity=3.0) is False)


def test_momentum_gate_negative_z_positive_velocity_allows():
    check("momentum_gate.z_negative_velocity_positive_allows",
          momentum_gate_allows(z=-2.5, rsi_diff_velocity=3.0) is True)


def test_momentum_gate_negative_z_negative_velocity_blocks():
    check("momentum_gate.z_negative_velocity_negative_blocks",
          momentum_gate_allows(z=-2.5, rsi_diff_velocity=-3.0) is False)


def test_momentum_gate_zero_velocity_blocks_either_direction():
    # velocity==0 counts as "not confirming" for both z signs (>= / <=
    # boundary), not a silent pass.
    check("momentum_gate.zero_velocity_blocks_positive_z",
          momentum_gate_allows(z=2.5, rsi_diff_velocity=0.0) is False)
    check("momentum_gate.zero_velocity_blocks_negative_z",
          momentum_gate_allows(z=-2.5, rsi_diff_velocity=0.0) is False)


def test_momentum_gate_nan_fails_closed():
    check("momentum_gate.nan_velocity_fails_closed",
          momentum_gate_allows(z=2.5, rsi_diff_velocity=float("nan")) is False)


def test_combined_gate_requires_both():
    # squeeze_momentum_gate = squeeze_gate_allows AND momentum_gate_allows,
    # both evaluated independently -- confirms neither alone is sufficient.
    sq_ok = squeeze_gate_allows(0.6, 0.7)
    mom_ok = momentum_gate_allows(z=2.5, rsi_diff_velocity=-3.0)
    check("combined_gate.both_true_allows", sq_ok and mom_ok)

    sq_ok_only = squeeze_gate_allows(0.6, 0.7)
    mom_fail = momentum_gate_allows(z=2.5, rsi_diff_velocity=3.0)
    check("combined_gate.squeeze_true_momentum_false_blocks_combined",
          not (sq_ok_only and mom_fail))


if __name__ == "__main__":
    test_squeeze_gate_both_legs_squeezed_allows()
    test_squeeze_gate_one_leg_not_squeezed_blocks()
    test_squeeze_gate_both_legs_not_squeezed_blocks()
    test_squeeze_gate_exactly_at_threshold_blocks()
    test_squeeze_gate_nan_fails_closed()
    test_momentum_gate_positive_z_negative_velocity_allows()
    test_momentum_gate_positive_z_positive_velocity_blocks()
    test_momentum_gate_negative_z_positive_velocity_allows()
    test_momentum_gate_negative_z_negative_velocity_blocks()
    test_momentum_gate_zero_velocity_blocks_either_direction()
    test_momentum_gate_nan_fails_closed()
    test_combined_gate_requires_both()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
