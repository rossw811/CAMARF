"""
research/liquidity_bar_vs_symbol_comparison.py -- Thread I follow-up (Ross,
2026-08-14): "run a test comparing just dropping illiquid bars vs all bars
(if it's above ADV)."

Two genuinely different liquidity-filtering designs, compared directly:

  A. SYMBOL-LEVEL (the current convention, international_liquidity_filter.py):
     compute ONE flat average dollar volume over the whole trailing window,
     exclude the ENTIRE symbol if that average is below MIN_DOLLAR_VOLUME.
     All-or-nothing: a symbol with 95% liquid days and a few illiquid ones
     either passes or fails as a WHOLE based on its average.

  B. BAR-LEVEL: keep every symbol in the universe regardless of its average,
     but mask INDIVIDUAL DAYS where that day's OWN dollar volume falls below
     the threshold (the illiquid bar becomes untradeable that day, same
     concept as this project's existing GapFlag system -- a day-level
     exclusion, not a symbol-level one).

Real question this answers: does the current symbol-level convention throw
away genuinely USABLE trading days from otherwise-decent symbols (a symbol
whose average sits just below threshold, dragged down by a handful of bad
days, but is liquid enough most of the time) -- or does it correctly protect
against symbols that LOOK liquid on average but have a meaningful fraction of
genuinely illiquid days hiding inside a good average?

Reuses international_liquidity_filter.py's own fetch_currency_codes/
usd_conversion_rate for USD dollar-volume conversion -- not reimplemented.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from config import Config
from data_wrds import _OUT_DIR
from research.international_liquidity_filter import usd_conversion_rate

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIQ_PATH = os.path.join(_ROOT, "output", "research", "international_liquidity_filter.parquet")
_OUT_PATH = os.path.join(_ROOT, "output", "research", "liquidity_bar_vs_symbol_comparison.parquet")

_TRAILING_DAYS = 504  # matches international_liquidity_filter.py's own window


def compare_bar_vs_symbol(label: str, currency: str, usd_mult: float,
                           threshold: float, trailing_days: int = _TRAILING_DAYS) -> dict:
    """For one symbol: compute symbol-level (flat average) pass/fail AND
    bar-level (per-day) pass rate, from the SAME underlying price file."""
    path = os.path.join(_OUT_DIR, f"{label}_1D.parquet")
    if not os.path.exists(path):
        return None
    df = pd.read_parquet(path)
    if df.empty:
        return None
    recent = df.tail(trailing_days)
    dollar_vol_local = (recent["close"] * recent["volume"]).replace([np.inf, -np.inf], np.nan).dropna()
    if dollar_vol_local.empty or not np.isfinite(usd_mult):
        return None
    dollar_vol_usd = dollar_vol_local * usd_mult

    symbol_level_avg = float(dollar_vol_usd.mean())
    symbol_level_pass = symbol_level_avg >= threshold

    bar_level_pass_mask = dollar_vol_usd >= threshold
    bar_level_pass_rate = float(bar_level_pass_mask.mean())
    n_bars = len(dollar_vol_usd)
    n_liquid_bars = int(bar_level_pass_mask.sum())

    return {
        "label": label, "symbol_level_avg_usd": symbol_level_avg,
        "symbol_level_pass": symbol_level_pass,
        "bar_level_pass_rate": bar_level_pass_rate,
        "n_bars": n_bars, "n_liquid_bars": n_liquid_bars,
    }


def main():
    threshold = Config.DATA.MIN_DOLLAR_VOLUME
    liq_df = pd.read_parquet(_LIQ_PATH)
    valid = liq_df.dropna(subset=["avg_dollar_volume_usd", "currency", "usd_conversion_rate"])
    print(f"Comparing bar-level vs symbol-level liquidity filtering for "
          f"{len(valid)} symbols at threshold=${threshold:,.0f}")

    results = []
    for _, row in valid.iterrows():
        r = compare_bar_vs_symbol(row["label"], row["currency"], row["usd_conversion_rate"], threshold)
        if r is not None:
            results.append(r)

    out = pd.DataFrame(results)
    out["bar_would_include_more_days"] = out["bar_level_pass_rate"] > 0  # any tradeable days at all

    # Case 1: symbol-level FAILS, but has a real fraction of liquid bars -- days being
    # thrown away entirely that a bar-level approach would have kept usable.
    rescued = out[(~out["symbol_level_pass"]) & (out["bar_level_pass_rate"] >= 0.20)]
    # Case 2: symbol-level PASSES, but a meaningful fraction of its OWN bars are illiquid --
    # days that symbol-level inclusion would silently let through as if liquid.
    hidden_illiquid = out[(out["symbol_level_pass"]) & (out["bar_level_pass_rate"] < 0.80)]

    print(f"\n=== Case 1: symbol-level EXCLUDED, but >=20% of bars are individually liquid "
          f"(days a bar-level filter would have kept usable) ===")
    print(f"  {len(rescued)}/{len(out)} symbols ({len(rescued)/len(out)*100:.1f}%)")
    if len(rescued) > 0:
        print(f"  median bar_level_pass_rate among these: {rescued['bar_level_pass_rate'].median():.2f}")

    print(f"\n=== Case 2: symbol-level INCLUDED, but <80% of its own bars are individually liquid "
          f"(days a symbol-level filter silently lets through as if they were all liquid) ===")
    print(f"  {len(hidden_illiquid)}/{len(out)} symbols ({len(hidden_illiquid)/len(out)*100:.1f}%)")
    if len(hidden_illiquid) > 0:
        print(f"  median bar_level_pass_rate among these: {hidden_illiquid['bar_level_pass_rate'].median():.2f}")

    n_agree = ((out["symbol_level_pass"]) == (out["bar_level_pass_rate"] >= 0.80)).sum()
    print(f"\n=== Overall agreement (symbol-level pass == bar-level pass_rate>=80%): "
          f"{n_agree}/{len(out)} ({n_agree/len(out)*100:.1f}%) ===")

    out.to_parquet(_OUT_PATH, index=False)
    print(f"\nSaved {len(out)} per-symbol comparisons -> {_OUT_PATH}")


if __name__ == "__main__":
    main()
