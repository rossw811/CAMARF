"""
Synthetic verification for portfolio_sim.py's max_drawdown_pct/profit_factor_from_replay/
pdr_from_replay/calmar_from_replay (task #49, 2026-07-14).

Same monkeypatch pattern as debug/_verify_portfolio_sim.py: fixed $100/share prices, small
non-overlapping share counts so every trade is taken at full size (size_scale=1.0) with no
capital-constraint downscaling, making the resulting equity curve and every ratio hand-computable
exactly, not just "did it run."
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import portfolio_sim
from portfolio_sim import (
    replay_portfolio, max_drawdown_pct, profit_factor_from_replay,
    pdr_from_replay, calmar_from_replay,
)

portfolio_sim.get_price_at = lambda symbol, ts: 100.0
portfolio_sim.get_spread_at = lambda symbol_a, symbol_b, tf, ts: 10.0


def trade(symbol_a, symbol_b, entry, exit_, n_shares_a, n_shares_b, pnl_net,
          entry_spread=10.0, side="long", tf="1h", entry_z=2.0, half_life_at_entry=20.0):
    return {
        "symbol_a": symbol_a, "symbol_b": symbol_b, "tf": tf,
        "entry_time": pd.Timestamp(entry), "exit_time": pd.Timestamp(exit_),
        "entry_z": entry_z, "half_life_at_entry": half_life_at_entry,
        "n_shares_a": n_shares_a, "n_shares_b": n_shares_b, "pnl_net": pnl_net,
        "entry_spread": entry_spread, "side": side,
    }


def main():
    failures = []

    # --- Case 1: known equity path, hand-computed drawdown/PF/PDR/Calmar ---
    # 5 non-overlapping trades, $100/share, 50 shares/leg -> notional $10,000/trade, well within
    # $100,000 starting capital -- every trade taken at size_scale=1.0, actual_pnl == pnl_net exactly.
    # Equity path: 100000 -> 110000 -> 115000(peak) -> 107000 -> 104000(trough) -> 116000(final)
    trades1 = pd.DataFrame([
        trade("A", "B", "2026-01-01", "2026-01-02", 50, 50, 10_000.0),
        trade("C", "D", "2026-01-03", "2026-01-04", 50, 50, 5_000.0),
        trade("E", "F", "2026-01-05", "2026-01-06", 50, 50, -8_000.0),
        trade("G", "H", "2026-01-07", "2026-01-08", 50, 50, -3_000.0),
        trade("I", "J", "2026-01-09", "2026-01-10", 50, 50, 12_000.0),
    ])
    r1 = replay_portfolio(trades1, starting_capital=100_000, sizing_method="fixed")
    if r1["n_taken"] != 5 or r1["skipped_count"] != 0:
        failures.append(f"Case 1: expected all 5 trades taken at full size, got "
                         f"n_taken={r1['n_taken']}, skipped={r1['skipped_count']}")

    expected_dd = 11_000 / 115_000  # (peak 115000 - trough 104000) / peak
    dd1 = max_drawdown_pct(r1["equity_curve"])
    if abs(dd1 - expected_dd) > 1e-9:
        failures.append(f"Case 1: expected max_drawdown_pct={expected_dd:.6f}, got {dd1:.6f}")

    expected_pf = 27_000 / 11_000  # (10000+5000+12000) / (8000+3000)
    pf1 = profit_factor_from_replay(r1)
    if abs(pf1 - expected_pf) > 1e-9:
        failures.append(f"Case 1: expected profit_factor={expected_pf:.6f}, got {pf1:.6f}")

    expected_pdr = expected_pf / expected_dd
    pdr1 = pdr_from_replay(r1)
    if abs(pdr1 - expected_pdr) > 1e-6:
        failures.append(f"Case 1: expected PDR={expected_pdr:.6f}, got {pdr1:.6f}")

    # Calmar reference computed independently via the same formula, not by calling the function
    # under test -- daily P&L series spans 2026-01-02 (first exit) to 2026-01-10 (last exit) = 9
    # calendar days once resampled; annualizing a 16% total return over a 9-day window produces a
    # large number by construction (compounding), not a bug -- this case verifies the FORMULA is
    # implemented correctly, not that the resulting magnitude "looks realistic."
    total_return = 116_000 / 100_000 - 1.0  # 0.16
    n_years = 9 / 252.0
    expected_ann_return = (1.0 + total_return) ** (1.0 / n_years) - 1.0
    expected_calmar = expected_ann_return / expected_dd
    calmar1 = calmar_from_replay(r1)
    if not np.isfinite(calmar1) or abs(calmar1 - expected_calmar) / abs(expected_calmar) > 1e-6:
        failures.append(f"Case 1: expected Calmar={expected_calmar:.4f}, got {calmar1}")

    print(f"Case 1 (known equity path): max_dd={dd1:.6f} (expected {expected_dd:.6f}), "
          f"PF={pf1:.4f} (expected {expected_pf:.4f}), PDR={pdr1:.4f} (expected {expected_pdr:.4f}), "
          f"Calmar={calmar1:.2f} (expected {expected_calmar:.2f})")

    # --- Case 2: zero drawdown (monotonically increasing equity) -> PDR/Calmar must return NaN,
    # not divide-by-zero or inf silently treated as a real ratio. ---
    trades2 = pd.DataFrame([
        trade("A", "B", "2026-01-01", "2026-01-02", 50, 50, 5_000.0),
        trade("C", "D", "2026-01-03", "2026-01-04", 50, 50, 3_000.0),
        trade("E", "F", "2026-01-05", "2026-01-06", 50, 50, 2_000.0),
    ])
    r2 = replay_portfolio(trades2, starting_capital=100_000, sizing_method="fixed")
    dd2 = max_drawdown_pct(r2["equity_curve"])
    if abs(dd2 - 0.0) > 1e-9:
        failures.append(f"Case 2: expected max_drawdown_pct=0.0 (monotonic equity), got {dd2}")
    pdr2 = pdr_from_replay(r2)
    calmar2 = calmar_from_replay(r2)
    if np.isfinite(pdr2) or np.isfinite(calmar2):
        failures.append(f"Case 2: expected NaN for both PDR and Calmar with zero drawdown, "
                         f"got PDR={pdr2}, Calmar={calmar2}")
    print(f"Case 2 (zero drawdown, monotonic equity): dd={dd2}, PDR={pdr2}, Calmar={calmar2} "
          f"(all correctly NaN/zero, no divide-by-zero)")

    # --- Case 3: all-loss trade set -> profit_factor must be 0.0 (zero gross profit), not NaN/inf,
    # and PDR must be 0.0 (a real, meaningfully bad ratio), not NaN (which would hide a real result
    # behind a missing-data code). ---
    trades3 = pd.DataFrame([
        trade("A", "B", "2026-01-01", "2026-01-02", 50, 50, -5_000.0),
        trade("C", "D", "2026-01-03", "2026-01-04", 50, 50, -3_000.0),
    ])
    r3 = replay_portfolio(trades3, starting_capital=100_000, sizing_method="fixed")
    pf3 = profit_factor_from_replay(r3)
    if abs(pf3 - 0.0) > 1e-9:
        failures.append(f"Case 3: expected profit_factor=0.0 (all losses, zero gross profit), got {pf3}")
    pdr3 = pdr_from_replay(r3)
    if abs(pdr3 - 0.0) > 1e-9:
        failures.append(f"Case 3: expected PDR=0.0 (zero profit factor, real drawdown), got {pdr3}")
    print(f"Case 3 (all-loss trades): PF={pf3} (expected 0.0), PDR={pdr3} (expected 0.0)")

    print()
    if failures:
        print(f"FAILED: {len(failures)} case(s)")
        for f in failures:
            print(" -", f)
        sys.exit(1)
    print("All PDR/Calmar verification cases passed.")


if __name__ == "__main__":
    main()
