"""
CAMARF price_density_screen.py — candidate universe-construction screen,
NOT yet wired into the production pipeline. Comparison method per Ross's
request (2026-06-23): "daily liquidity does not equal intraday price-
discovery density" (BUG-D49) — this formalizes a concrete fix and shows
its effect, rather than just the diagnostic audit.

passes_price_density() is written to be a drop-in candidate predicate
for data.py's universe construction (alongside the existing
MIN_DOLLAR_VOLUME check) — same signature shape, same read-only
contract, intentionally NOT imported into data.py yet (that's a real
methodology decision pending Ross's sign-off, per this project's
standing buy-in rule, not something to silently wire in here).

Usage:
    python research/price_density_screen.py --tf 1m
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from data import DataStore

_DEFAULT_MIN_DISTINCT = 20
_DEFAULT_MIN_DISTINCT_RATIO = 0.02


def passes_price_density(
    symbol: str, tf_label: str,
    min_distinct: int = _DEFAULT_MIN_DISTINCT,
    min_distinct_ratio: float = _DEFAULT_MIN_DISTINCT_RATIO,
) -> bool:
    """
    True if `symbol` shows enough genuine intraday price variation at
    `tf_label` to be trustworthy for cointegration testing — independent
    of (and complementary to) MIN_DOLLAR_VOLUME's daily liquidity check.
    False (fails the screen) if cached data is missing entirely — same
    "can't confirm it's good, so don't admit it" posture as the existing
    liquidity check's missing-data handling.
    """
    df = DataStore.load(symbol, tf_label)
    if df is None or len(df) == 0:
        return False
    non_nan = df[df["close"].notna()]
    if len(non_nan) < 60:
        return False
    n_distinct = non_nan["close"].nunique()
    ratio = n_distinct / len(non_nan)
    return n_distinct >= min_distinct and ratio >= min_distinct_ratio


def main():
    p = argparse.ArgumentParser(description="Price-density screen — before/after comparison")
    p.add_argument("--tf", default="1m")
    args = p.parse_args()
    tf_label = args.tf

    # "Before": current universe admission rule is liquidity-only.
    safe_tf = DataStore._TF_SAFE.get(tf_label, tf_label.lower())
    suffix = f"_{safe_tf}"
    cached = [c[: -len(suffix)] for c in DataStore.list_cached() if c.endswith(suffix)]

    safe_path_dir = {"1m": "1min", "3m": "3min", "15m": "15min", "1h": "1hr", "4h": "4hr"}.get(tf_label, f"{tf_label}")
    pairs_path = f"output/results/{safe_path_dir}/pairs.parquet"
    if not os.path.exists(pairs_path):
        print(f"No confirmed pairs file at {pairs_path} — nothing to compare.")
        return
    pairs = pd.read_parquet(pairs_path)

    print(f"Applying price_density_screen to {len(cached)} symbols cached at {tf_label}...")
    screen_results = {sym: passes_price_density(sym, tf_label) for sym in cached}
    n_pass = sum(screen_results.values())
    print(f"{n_pass}/{len(cached)} symbols pass the price-density screen "
          f"({len(cached) - n_pass} would be excluded from universe construction "
          f"if this screen were adopted alongside MIN_DOLLAR_VOLUME).")

    print(f"\n=== Effect on the {len(pairs)} current {tf_label} confirmed pairs ===")
    survives, excluded = [], []
    for _, row in pairs.iterrows():
        a, b = row["symbol_a"], row["symbol_b"]
        a_ok = screen_results.get(a, False)
        b_ok = screen_results.get(b, False)
        if a_ok and b_ok:
            survives.append((a, b))
        else:
            excluded.append((a, b, a_ok, b_ok))

    print(f"Would SURVIVE (both legs pass): {len(survives)}/{len(pairs)}")
    for a, b in survives:
        print(f"  KEEP    {a}/{b}")
    print(f"Would be EXCLUDED (at least one leg fails): {len(excluded)}/{len(pairs)}")
    for a, b, a_ok, b_ok in excluded:
        reason = "both legs fail" if not a_ok and not b_ok else f"{a if not a_ok else b} fails"
        print(f"  EXCLUDE {a}/{b}  ({reason})")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"price_density_screen_effect_{tf_label}.csv")
    pd.DataFrame(
        [{"symbol_a": a, "symbol_b": b, "survives": True} for a, b in survives]
        + [{"symbol_a": a, "symbol_b": b, "survives": False} for a, b, *_ in excluded]
    ).to_csv(out_path, index=False)
    print(f"\nFull before/after table: {out_path}")


if __name__ == "__main__":
    main()
