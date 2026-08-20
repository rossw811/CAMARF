"""
Synthetic verification of portfolio_sim.py::replay_portfolio's new
`flat_risk_pct` parameter (fix, 2026-08-13) -- real bug found during Thread
G-Full Tier 2 investigation: backtest.py's `--override FLAT_RISK_PCT=X`
mutated a per-run COPY of Config.BACKTEST, but portfolio_sim.py read a
module-level constant frozen at IMPORT time from the ORIGINAL Config.BACKTEST
-- the override could never reach it, regardless of import order, since the
override target and the read target were two different objects entirely.

Verifies the FIX (an explicit `flat_risk_pct` parameter now threaded through
to the flat_2pct sizing branch), not the original sizing math itself (already
covered elsewhere) -- monkeypatches `stop_distance_dollars_per_share` and
`get_price_at` to fixed values so the test is isolated from real cached
price/spread data, and checks that DIFFERENT explicit flat_risk_pct values
produce PROPORTIONALLY different position sizes for sizing_method="flat_2pct".

Checks:
  1. Passing flat_risk_pct=0.04 sizes a position at roughly 2x the notional
     of flat_risk_pct=0.02, all else equal (risk_fraction directly scales
     target_shares_a = (risk_fraction * equity) / risk_per_share).
  2. Omitting flat_risk_pct (default None) falls back to the module-level
     _FLAT_RISK_PCT default -- unchanged behavior for every other existing
     caller that doesn't pass this new parameter.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import portfolio_sim


def _make_single_trade():
    return pd.DataFrame([{
        "symbol_a": "AAA", "symbol_b": "BBB", "tf": "1D",
        "entry_time": pd.Timestamp("2020-01-02"), "exit_time": pd.Timestamp("2020-01-10"),
        "entry_spread": 1.0, "entry_z": 2.0, "side": "long",
        "half_life_at_entry": 10.0,
        "n_shares_a": 100, "n_shares_b": 100, "pnl_net": 500.0,
    }])


def main(monkeypatch_module=portfolio_sim):
    failures = []

    # Fix risk_per_share and prices to known constants so target_notional is
    # a deterministic, directly-computable function of risk_fraction alone.
    monkeypatch_module.stop_distance_dollars_per_share = lambda *a, **k: 100.0  # $100/share risk --
    # deliberately large relative to price so target_notional stays well below available capital at
    # BOTH tested risk_fraction levels (a too-small risk_per_share made the first version of this
    # test saturate the capital constraint identically for both cases, masking the real difference).
    monkeypatch_module.get_price_at = lambda symbol, ts: 50.0  # both legs at $50
    monkeypatch_module.get_spread_at = lambda *a, **k: 1.0

    trades = _make_single_trade()

    # --- Check 1: explicit flat_risk_pct scales target notional proportionally ---
    result_low = portfolio_sim.replay_portfolio(
        trades.copy(), starting_capital=10_000_000, sizing_method="flat_2pct", flat_risk_pct=0.02
    )
    result_high = portfolio_sim.replay_portfolio(
        trades.copy(), starting_capital=10_000_000, sizing_method="flat_2pct", flat_risk_pct=0.04
    )
    low_notional = result_low["peak_concurrent_notional"]
    high_notional = result_high["peak_concurrent_notional"]
    if low_notional <= 0 or high_notional <= 0:
        failures.append(f"Check 1: expected nonzero notional for both runs, "
                         f"got low={low_notional} high={high_notional}")
    else:
        ratio = high_notional / low_notional
        if abs(ratio - 2.0) > 0.05:
            failures.append(f"Check 1: doubling flat_risk_pct (0.02->0.04) should ~double target "
                             f"notional, got ratio {ratio:.3f} (low={low_notional:.2f}, "
                             f"high={high_notional:.2f})")

    # --- Check 2: omitting flat_risk_pct falls back to the module-level default ---
    original_default = portfolio_sim._FLAT_RISK_PCT
    portfolio_sim._FLAT_RISK_PCT = 0.02
    result_default = portfolio_sim.replay_portfolio(
        trades.copy(), starting_capital=10_000_000, sizing_method="flat_2pct"
    )
    portfolio_sim._FLAT_RISK_PCT = original_default
    default_notional = result_default["peak_concurrent_notional"]
    if low_notional > 0 and abs(default_notional - low_notional) / low_notional > 0.01:
        failures.append(f"Check 2: omitting flat_risk_pct should match the module-level default "
                         f"(0.02, same as Check 1's explicit low case) -- got default={default_notional:.2f} "
                         f"vs explicit-0.02={low_notional:.2f}")

    # --- Check 3: concentration_cap caps a single position's notional at a fraction of
    # CURRENT equity (added 2026-08-14, Thread G-Full follow-up -- MAX_CONCENTRATION_PCT was a
    # declared-but-dead config constant, now really enforced here). ---
    result_uncapped = portfolio_sim.replay_portfolio(
        trades.copy(), starting_capital=10_000_000, sizing_method="flat_2pct", flat_risk_pct=0.15
    )
    result_capped = portfolio_sim.replay_portfolio(
        trades.copy(), starting_capital=10_000_000, sizing_method="flat_2pct", flat_risk_pct=0.15,
        concentration_cap=0.10,  # 10% of equity max per position
    )
    uncapped_notional = result_uncapped["peak_concurrent_notional"]
    capped_notional = result_capped["peak_concurrent_notional"]
    expected_cap = 10_000_000 * 0.10
    if uncapped_notional <= expected_cap:
        failures.append(f"Check 3: test setup invalid -- uncapped notional ({uncapped_notional:.2f}) "
                         f"should exceed the 10% cap ({expected_cap:.2f}) for this check to be meaningful")
    if abs(capped_notional - expected_cap) > 1.0:
        failures.append(f"Check 3: expected capped notional to hit exactly the 10% cap "
                         f"({expected_cap:.2f}), got {capped_notional:.2f}")
    if capped_notional >= uncapped_notional:
        failures.append(f"Check 3: capped notional ({capped_notional:.2f}) should be strictly less "
                         f"than uncapped ({uncapped_notional:.2f})")

    # --- Check 4: leverage_cap (Thread N #2, 2026-08-14) caps TOTAL gross exposure across
    # multiple simultaneously-open positions, not a single position's own notional. Two
    # overlapping trades, each individually under any per-position cap, but combined they
    # should be clamped to leverage_cap * equity. ---
    two_trades = pd.DataFrame([
        {
            "symbol_a": "AAA", "symbol_b": "BBB", "tf": "1D",
            "entry_time": pd.Timestamp("2020-01-02"), "exit_time": pd.Timestamp("2020-01-20"),
            "entry_spread": 1.0, "entry_z": 2.0, "side": "long",
            "half_life_at_entry": 10.0, "n_shares_a": 100, "n_shares_b": 100, "pnl_net": 500.0,
        },
        {
            "symbol_a": "CCC", "symbol_b": "DDD", "tf": "1D",
            "entry_time": pd.Timestamp("2020-01-05"), "exit_time": pd.Timestamp("2020-01-20"),
            "entry_spread": 1.0, "entry_z": 2.0, "side": "long",
            "half_life_at_entry": 10.0, "n_shares_a": 100, "n_shares_b": 100, "pnl_net": 500.0,
        },
    ])
    # Real property found while writing this test, not a bug: portfolio_sim.py's EXISTING
    # capital-availability constraint (`available = current_equity - committed_now`) already
    # implicitly enforces a de facto leverage_cap=1.0 by construction -- positions can never be
    # sized beyond available cash regardless of leverage_cap, since there is no borrowing/margin
    # mechanism anywhere in this engine. leverage_cap=1.0 is therefore ALWAYS a no-op; the
    # parameter only has a genuinely distinct effect for values < 1.0 (a TIGHTER-than-default
    # constraint), which is what this check actually verifies.
    result_unlevered = portfolio_sim.replay_portfolio(
        two_trades.copy(), starting_capital=10_000_000, sizing_method="flat_2pct", flat_risk_pct=0.6
    )
    result_levcapped = portfolio_sim.replay_portfolio(
        two_trades.copy(), starting_capital=10_000_000, sizing_method="flat_2pct", flat_risk_pct=0.6,
        leverage_cap=0.5,  # gross exposure never exceeds 50% of equity -- a real, tighter constraint
    )
    peak_unlevered = result_unlevered["peak_concurrent_notional"]
    peak_levcapped = result_levcapped["peak_concurrent_notional"]
    if peak_unlevered < 10_000_000 * 0.99:
        failures.append(f"Check 4: test setup invalid -- unlevered peak notional "
                         f"({peak_unlevered:.2f}) should reach close to 100% of equity (the "
                         f"existing implicit cap) for this check to be meaningful")
    if peak_levcapped > 10_000_000 * 0.5 * 1.001:  # tiny tolerance for float rounding
        failures.append(f"Check 4: leverage_cap=0.5 should keep peak gross exposure at or below "
                         f"50% of equity ($5,000,000), got {peak_levcapped:.2f}")
    if peak_levcapped >= peak_unlevered:
        failures.append(f"Check 4: levered-capped peak ({peak_levcapped:.2f}) should be strictly "
                         f"less than unlevered peak ({peak_unlevered:.2f})")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All flat_risk_pct override checks passed.")
    print(f"  Check 3: concentration_cap -- uncapped={uncapped_notional:.2f}, "
          f"capped={capped_notional:.2f} (10% cap={expected_cap:.2f})")
    print(f"  Check 4: leverage_cap -- unlevered peak={peak_unlevered:.2f}, "
          f"leverage_cap=0.5 peak={peak_levcapped:.2f}")
    print(f"  Check 1: flat_risk_pct=0.02 -> notional={low_notional:.2f}, "
          f"flat_risk_pct=0.04 -> notional={high_notional:.2f} (ratio {high_notional/low_notional:.3f})")
    print(f"  Check 2: omitted flat_risk_pct matches module-level default "
          f"({default_notional:.2f} vs {low_notional:.2f})")


if __name__ == "__main__":
    main()
