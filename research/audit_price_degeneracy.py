"""
CAMARF audit_price_degeneracy.py — universe-wide scan for BUG-D49's
thin-information-content pattern (Development.md, found 2026-06-23).

BUG-D49: APAM/AZTA/INVX/NBHC's 1-minute price data shows only 2-7
distinct close values across hundreds-to-thousands of bars, despite
being genuinely liquid ($11-27M/day) — corroborated against IBKR's own
feed, so it's real market data, not a fetch defect. The open question
this audit answers: how many MORE symbols in the universe show this
same pattern? (Independent evidence this is broader than 4 symbols
already surfaced while building predictability_optimizer.py — many
LinAlgError-on-ill-conditioned-covariance failures on names beyond the
original 4.)

Flag condition: a symbol is flagged if BOTH
  (a) genuinely liquid at the daily level (avg daily dollar volume over
      the trailing 60 days >= Config.DATA.MIN_DOLLAR_VOLUME), AND
  (b) the number of DISTINCT close prices over its cached intraday
      history is implausibly low relative to its bar count (default:
      fewer than 20 distinct values, or distinct/non-NaN-bar ratio
      below 2% — whichever is the binding constraint at low bar counts).

Read-only. Scans whatever is in output/cache/ already — never fetches.

Usage:
    python research/audit_price_degeneracy.py --tf 1m
    python research/audit_price_degeneracy.py --tf 1m --min-distinct 20
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from data import DataStore


def _daily_dollar_volume(symbol: str) -> float:
    df = DataStore.load(symbol, "1D")
    if df is None or len(df) == 0:
        return np.nan
    recent = df.tail(60)
    return float((recent["close"] * recent["volume"]).mean())


def audit_symbol(symbol: str, tf_label: str) -> dict:
    df = DataStore.load(symbol, tf_label)
    if df is None or len(df) == 0:
        return None
    n_total = len(df)
    non_nan = df[df["close"].notna()]
    n_non_nan = len(non_nan)
    if n_non_nan == 0:
        return {
            "symbol": symbol, "n_total": n_total, "n_non_nan": 0,
            "n_distinct_close": 0, "flat_ohlc_frac": np.nan,
            "zero_volume_frac": float((df["volume"] == 0).mean()),
        }
    n_distinct = int(non_nan["close"].nunique())
    flat = (
        (non_nan["open"] == non_nan["high"])
        & (non_nan["high"] == non_nan["low"])
        & (non_nan["low"] == non_nan["close"])
    )
    return {
        "symbol": symbol, "n_total": n_total, "n_non_nan": n_non_nan,
        "n_distinct_close": n_distinct, "flat_ohlc_frac": float(flat.mean()),
        "zero_volume_frac": float((df["volume"] == 0).mean()),
    }


def main():
    p = argparse.ArgumentParser(description="Universe-wide BUG-D49 price-degeneracy audit")
    p.add_argument("--tf", default="1m")
    p.add_argument("--min-distinct", type=int, default=20,
                    help="Flag if fewer than this many distinct close prices over the whole cached history")
    p.add_argument("--min-distinct-ratio", type=float, default=0.02,
                    help="Flag if distinct/non-NaN-bar ratio is below this")
    args = p.parse_args()

    safe_tf = DataStore._TF_SAFE.get(args.tf, args.tf.lower())
    suffix = f"_{safe_tf}"
    cached = [c[: -len(suffix)] for c in DataStore.list_cached() if c.endswith(suffix)]
    print(f"Scanning {len(cached)} symbols cached at {args.tf}...")

    rows = []
    for i, sym in enumerate(cached):
        if i % 200 == 0 and i > 0:
            print(f"  {i}/{len(cached)}...")
        stats = audit_symbol(sym, args.tf)
        if stats is None:
            continue
        if stats["n_non_nan"] < 60:
            continue  # too little data either way, not informative
        rows.append(stats)

    df = pd.DataFrame(rows)
    print(f"\n{len(df)} symbols had enough {args.tf} data to evaluate.")

    df["distinct_ratio"] = df["n_distinct_close"] / df["n_non_nan"]
    degenerate = df[
        (df["n_distinct_close"] < args.min_distinct)
        | (df["distinct_ratio"] < args.min_distinct_ratio)
    ].copy()
    print(f"{len(degenerate)}/{len(df)} symbols show the degenerate-price pattern "
          f"(< {args.min_distinct} distinct closes OR distinct ratio < "
          f"{args.min_distinct_ratio:.0%}), before checking daily liquidity.")

    print("\nChecking daily dollar volume for degenerate-flagged symbols "
          "(this is the slow step — one 1D cache load per flagged symbol)...")
    degenerate["daily_dollar_volume"] = degenerate["symbol"].apply(_daily_dollar_volume)
    liquid_floor = Config.DATA.MIN_DOLLAR_VOLUME
    degenerate["genuinely_liquid"] = degenerate["daily_dollar_volume"] >= liquid_floor

    flagged = degenerate[degenerate["genuinely_liquid"]].sort_values(
        "daily_dollar_volume", ascending=False
    )
    print(f"\n=== {len(flagged)} symbols flagged: genuinely liquid "
          f"(>=${liquid_floor:,.0f}/day) BUT degenerate {args.tf} price data ===")
    if not flagged.empty:
        print(flagged[["symbol", "n_total", "n_non_nan", "n_distinct_close",
                        "distinct_ratio", "flat_ohlc_frac", "zero_volume_frac",
                        "daily_dollar_volume"]].to_string(index=False))
    else:
        print("(none)")

    n_illiquid_degenerate = len(degenerate) - len(flagged)
    print(f"\n{n_illiquid_degenerate} more symbols show degenerate {args.tf} prices "
          f"but ALSO fail the daily liquidity floor — for those, thin trading is "
          f"the more mundane, expected explanation (genuinely illiquid stock), "
          f"not the BUG-D49 anomaly (liquid daily, degenerate intraday).")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"price_degeneracy_audit_{args.tf}.parquet")
    df.to_parquet(out_path)
    flagged_path = os.path.join(out_dir, f"price_degeneracy_flagged_{args.tf}.parquet")
    flagged.to_parquet(flagged_path)
    print(f"\nFull audit: {out_path}")
    print(f"Flagged (liquid-but-degenerate) subset: {flagged_path}")


if __name__ == "__main__":
    main()
