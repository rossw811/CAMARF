"""
dollar_volume.py -- USD dollar volume of a daily price frame, one rule for every liquidity gate (code review R1.2,
fixed 2026-10-07).

Price: `close_usd` where the frame has it (Compustat Global listings: `close` is LOCAL currency -- a yen close of 1694
is $10.66), else |close| (CRSP is USD; a negative close is CRSP's bid/ask-midpoint convention for a no-trade day).
Before this module, rolling_adv / flat_adv / data_wrds.compute_symbol_adv_wrds multiplied local `close` by volume
and compared it with a USD threshold (yen listings ~159x too liquid). yfinance non-US files carry no `close_usd`;
they still need FX conversion (research/international_liquidity_filter.py does it) -- not handled here.
debug/_verify_usd_dollar_volume.py
"""
import pandas as pd


def usd_price(df: pd.DataFrame) -> pd.Series:
    if "close_usd" in df.columns and df["close_usd"].notna().any():
        return pd.to_numeric(df["close_usd"], errors="coerce")
    return pd.to_numeric(df["close"], errors="coerce").abs()


def usd_dollar_volume(df: pd.DataFrame) -> pd.Series:
    return (usd_price(df) * pd.to_numeric(df["volume"], errors="coerce")).astype(float)
