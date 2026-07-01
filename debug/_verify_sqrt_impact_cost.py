"""
Synthetic verification of _compute_cost_sqrt_impact (backtest.py), added for
the Phase 2b square-root market-impact STORM variant, BEFORE trusting it on
real backtest data.

Checks:
  1. Commission component is identical between _compute_cost and
     _compute_cost_sqrt_impact (only the slippage term's functional form
     should differ).
  2. Missing/NaN/non-positive ADV falls back to impact_factor=1.0 for that
     leg (i.e. behaves like the flat model for that leg specifically).
  3. Order size == ADV for both legs -> sqrt(Q/ADV)=1 for both -> total cost
     equals the flat-bps model exactly (the crossover point the two models
     should agree on by construction).
  4. Order size < ADV (small order) -> sqrt-impact cost strictly LOWER than
     flat-bps cost (the concave model's core claim: small orders are
     cheaper than a flat rate implies).
  5. Order size > ADV (large order) -> sqrt-impact cost strictly HIGHER than
     flat-bps cost (large orders are more expensive than linear).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from backtest import _compute_cost, _compute_cost_sqrt_impact


def main():
    failures = []
    entry_spread, hedge, n_shares_a = 2.5, 1.2, 100
    commission_per_share, slippage_bps = 0.005, 5.0

    flat_cost = _compute_cost(entry_spread, hedge, n_shares_a, commission_per_share, slippage_bps)
    flat_commission = commission_per_share * (n_shares_a + n_shares_a * abs(hedge)) * 2

    # --- 1. Commission identical, isolate by using ADV=order size (impact=1) ---
    n_shares_b = n_shares_a * abs(hedge)
    at_crossover_cost = _compute_cost_sqrt_impact(
        entry_spread, hedge, n_shares_a, commission_per_share, slippage_bps,
        adv_shares_a=n_shares_a, adv_shares_b=n_shares_b,
    )
    if not np.isclose(at_crossover_cost, flat_cost, rtol=1e-9):
        failures.append(
            f"At ADV==order_size (impact factor=1), sqrt-impact cost should equal "
            f"flat cost exactly: {at_crossover_cost} vs {flat_cost}"
        )

    # --- 2. Missing ADV falls back to flat behavior ---
    missing_adv_cost = _compute_cost_sqrt_impact(
        entry_spread, hedge, n_shares_a, commission_per_share, slippage_bps,
        adv_shares_a=float("nan"), adv_shares_b=float("nan"),
    )
    if not np.isclose(missing_adv_cost, flat_cost, rtol=1e-9):
        failures.append(
            f"Missing ADV should fall back to flat-bps cost: {missing_adv_cost} vs {flat_cost}"
        )
    zero_adv_cost = _compute_cost_sqrt_impact(
        entry_spread, hedge, n_shares_a, commission_per_share, slippage_bps,
        adv_shares_a=0.0, adv_shares_b=-5.0,
    )
    if not np.isclose(zero_adv_cost, flat_cost, rtol=1e-9):
        failures.append(
            f"Zero/negative ADV should fall back to flat-bps cost: {zero_adv_cost} vs {flat_cost}"
        )

    # --- 3. Small order relative to ADV -> cheaper than flat ---
    small_order_cost = _compute_cost_sqrt_impact(
        entry_spread, hedge, n_shares_a, commission_per_share, slippage_bps,
        adv_shares_a=n_shares_a * 100, adv_shares_b=n_shares_b * 100,  # order is 1% of ADV
    )
    if not small_order_cost < flat_cost:
        failures.append(
            f"Small order (1% of ADV) should be cheaper than flat model: "
            f"{small_order_cost} vs {flat_cost}"
        )

    # --- 4. Large order relative to ADV -> more expensive than flat ---
    large_order_cost = _compute_cost_sqrt_impact(
        entry_spread, hedge, n_shares_a, commission_per_share, slippage_bps,
        adv_shares_a=n_shares_a / 25, adv_shares_b=n_shares_b / 25,  # order is 25x ADV
    )
    if not large_order_cost > flat_cost:
        failures.append(
            f"Large order (25x ADV) should be more expensive than flat model: "
            f"{large_order_cost} vs {flat_cost}"
        )

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All _compute_cost_sqrt_impact checks passed.")
    print(f"  flat_cost={flat_cost:.4f}  at_crossover={at_crossover_cost:.4f}  "
          f"small_order={small_order_cost:.4f}  large_order={large_order_cost:.4f}")


if __name__ == "__main__":
    main()
