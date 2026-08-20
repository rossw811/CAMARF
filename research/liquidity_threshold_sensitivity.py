"""
research/liquidity_threshold_sensitivity.py -- Thread I follow-up (Ross,
2026-08-14): "let's do a test to see what level actually filters out the
proper amount of assets, ensuring liquid stocks."

Two real questions, both answered here: (1) how does the PASS RATE change
across a grid of MIN_DOLLAR_VOLUME thresholds (a pure descriptive sweep --
already-fetched data, no new WRDS query needed), and (2) what threshold is
actually DEFENSIBLE from a real trading-feasibility standpoint, not just a
round number picked by convention.

For (2): the standard market-impact rule of thumb (don't be more than a few
percent of a day's dollar volume in a single trade, or the trade itself
moves the price against you) gives a real, checkable answer -- read
CAMARF's own REALIZED position notional sizes (Step 5's real trades,
`actual_notional` column) and compute what ADV each position size implies
at a target max-participation-rate (e.g. 5%). A threshold below that implied
ADV means CAMARF's own typical position size would represent an
uncomfortably large fraction of that day's volume -- a real, not arbitrary,
lower bound.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIQ_PATH = os.path.join(_ROOT, "output", "research", "international_liquidity_filter.parquet")
_STEP5_DIR = os.path.join(_ROOT, "output", "research", "step5_arm_results")
_OUT_PATH = os.path.join(_ROOT, "output", "research", "liquidity_threshold_sensitivity.parquet")

_THRESHOLD_GRID = [50_000, 100_000, 250_000, 500_000, 1_000_000, 2_000_000,
                    5_000_000, 10_000_000, 25_000_000]
_MAX_PARTICIPATION_RATE = 0.05  # don't be more than 5% of a day's dollar volume in one trade


def threshold_pass_rates(liq_df: pd.DataFrame, thresholds: list) -> pd.DataFrame:
    valid = liq_df["avg_dollar_volume_usd"].notna()
    n_valid = int(valid.sum())
    rows = []
    for t in thresholds:
        n_pass = int((liq_df.loc[valid, "avg_dollar_volume_usd"] >= t).sum())
        rows.append({
            "threshold_usd": t, "n_pass": n_pass, "n_valid": n_valid,
            "pass_rate": n_pass / n_valid if n_valid > 0 else np.nan,
        })
    return pd.DataFrame(rows)


def implied_min_adv_from_position_sizes(trades_notional: pd.Series,
                                         max_participation_rate: float) -> dict:
    """A position of notional N should represent at most
    max_participation_rate of that day's dollar volume -- so the MINIMUM
    ADV that comfortably supports a position of size N is N /
    max_participation_rate. Reports this at CAMARF's own realized
    percentiles (median/75th/90th position size), not just the mean, since
    a threshold needs to cover the LARGER end of realized sizes, not just
    the typical one."""
    out = {}
    for pct, label in [(50, "median"), (75, "p75"), (90, "p90"), (100, "max")]:
        notional_at_pct = float(np.percentile(trades_notional, pct))
        out[f"{label}_notional"] = notional_at_pct
        out[f"{label}_implied_min_adv"] = notional_at_pct / max_participation_rate
    return out


def main():
    if not os.path.exists(_LIQ_PATH):
        print(f"FATAL: {_LIQ_PATH} not found -- run international_liquidity_filter.py first")
        sys.exit(1)
    liq_df = pd.read_parquet(_LIQ_PATH)

    print(f"=== Pass-rate sensitivity across MIN_DOLLAR_VOLUME thresholds "
          f"({liq_df['avg_dollar_volume_usd'].notna().sum()} symbols with a valid ADV) ===")
    sensitivity = threshold_pass_rates(liq_df, _THRESHOLD_GRID)
    print(sensitivity.to_string(index=False))

    # Real, trading-feasibility-grounded lower bound, from CAMARF's own realized position sizes.
    all_notionals = []
    for arm in ["baseline", "hybrid", "purity", "tiered"]:
        for split in ["is", "oos"]:
            path = os.path.join(_STEP5_DIR, f"real_{arm}_{split}_trades_capsim.parquet")
            if os.path.exists(path):
                df = pd.read_parquet(path)
                if "actual_notional" in df.columns and not df.empty:
                    all_notionals.append(df["actual_notional"])
    if all_notionals:
        notionals = pd.concat(all_notionals, ignore_index=True)
        implied = implied_min_adv_from_position_sizes(notionals, _MAX_PARTICIPATION_RATE)
        print(f"\n=== Trading-feasibility-grounded lower bound "
              f"(max {_MAX_PARTICIPATION_RATE:.0%} of ADV per position, "
              f"n={len(notionals)} real realized CAMARF positions) ===")
        for k, v in implied.items():
            print(f"  {k}: ${v:,.0f}")
        print(f"\n  Current MIN_DOLLAR_VOLUME default: $1,000,000")
        p90_bound = implied["p90_implied_min_adv"]
        if p90_bound > 1_000_000:
            print(f"  ** Current default is BELOW the p90-implied lower bound (${p90_bound:,.0f}) "
                  f"-- the largest ~10% of CAMARF's real positions would represent MORE than "
                  f"{_MAX_PARTICIPATION_RATE:.0%} of daily volume at a $1M-ADV name. Real, "
                  f"disclosed finding, not a recommendation to change the default unilaterally. **")
        else:
            print(f"  Current $1M default is comfortably ABOVE the p90-implied lower bound "
                  f"(${p90_bound:,.0f}) -- defensible at this position-sizing regime.")
    else:
        print("\nNo real Step 5 trades found -- skipping trading-feasibility bound.")
        implied = {}

    out = {"pass_rate_sensitivity": sensitivity.to_dict("records"), "implied_bounds": implied}
    pd.DataFrame(sensitivity).to_parquet(_OUT_PATH, index=False)
    print(f"\nSaved -> {_OUT_PATH}")


if __name__ == "__main__":
    main()
