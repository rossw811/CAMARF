"""
ibkr_supplement_reader.py — Parquet-only reader for IBKR deep-history supplements.

Exists as a standalone module (no ib_insync dependency) so that analysis.py
can load supplement files without importing data_ibkr.py's full fetch
machinery. data_ibkr.py also imports from here for path/load consistency.

Architectural boundary:
  data_ibkr.py  → writes supplement parquets (requires ib_insync + IB Gateway)
  this file      → reads supplement parquets (os + pandas only)
  analysis.py   → imports from here, never from data_ibkr directly
"""

import os
from typing import Optional

import pandas as pd

# Mirror of DataStore._TF_SAFE — kept in sync manually, not imported from
# data.py, to avoid pulling in ib_insync (which data.py imports at top level).
_TF_SAFE: dict = {
    "1m": "1min",
    "2m": "2min",
    "3m": "3min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1hr",
    "4h": "4hr",
    "1D": "1day",
    "7D": "7day",
    "1M": "1mo",
    "3M": "3mo",
    "6M": "6mo",
}

SUPPLEMENT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "output", "cache", "ibkr_supplement"
)

# data_ibkr.py only ever fetches IBKR's NATIVE bar sizes (4h/1h/30m/15m/5m/1m
# intraday, 1D daily — see data.py's IBKRFeed.INTRADAY_TFS) — 2m/3m/7D/1M are
# always DERIVED (resampled) in the main pipeline, so no "{symbol}_{tf}_deep.
# parquet" file for those ever gets written by data_ibkr.py. Added 2026-07-21:
# a confirmed pair landing on one of these derived TFs (e.g. KVUE/KMB@2m/3m,
# 7267.T/8058.T@1M — today's ENTIRE confirmed set, as it happens) previously
# got zero deep-history episodic-cointegration coverage at all, purely
# because load_supplement() only ever checked for the literal derived-TF
# filename. Mirrors data.py's IBKRFeed.RESAMPLED_FROM_1M / the 7D-W-FRI,
# 1M-1ME daily derivation exactly (same resample rules, same "no depth lost"
# property) — resampled on load from the NATIVE base supplement file,
# not persisted as a separate derived deep parquet.
_DERIVED_FROM: dict = {
    "2m": ("1m", "2min"),
    "3m": ("1m", "3min"),
    "7D": ("1D", "W-FRI"),
    "1M": ("1D", "1ME"),
}


def supplement_path(symbol: str, tf_label: str) -> str:
    """Absolute path to the deep-history parquet for this symbol-TF."""
    safe_tf = _TF_SAFE.get(tf_label, tf_label.replace(" ", ""))
    return os.path.join(SUPPLEMENT_DIR, f"{symbol}_{safe_tf}_deep.parquet")


def _resample(df: pd.DataFrame, rule: str) -> Optional[pd.DataFrame]:
    """Mirrors data.py's IBKRFeed._resample exactly (OHLCV aggregation,
    dropna on open/close, minimum 2 rows) — duplicated rather than imported
    to preserve this module's ib_insync-free architectural boundary (see
    module docstring)."""
    try:
        agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
        if "volume" in df.columns:
            agg["volume"] = "sum"
        resampled = df.resample(rule).agg(agg).dropna(subset=["open", "close"])
        return resampled if len(resampled) >= 2 else None
    except Exception:
        return None


def load_supplement(symbol: str, tf_label: str) -> Optional[pd.DataFrame]:
    """
    Load deep IBKR history for a symbol-TF if it exists.
    Returns None if no supplement exists — caller degrades gracefully.

    For derived TFs (2m/3m/7D/1M) with no native supplement file, falls back
    to resampling the NATIVE base TF's own supplement file on the fly (see
    _DERIVED_FROM) — this is what lets the episodic deep-history re-test
    cover a confirmed pair at a derived TF at all, rather than silently
    no-op'ing for every such pair.
    """
    p = supplement_path(symbol, tf_label)
    if os.path.exists(p):
        try:
            df = pd.read_parquet(p)
            return df if not df.empty else None
        except Exception:
            return None

    derived = _DERIVED_FROM.get(tf_label)
    if derived is None:
        return None
    base_tf, rule = derived
    base_df = load_supplement(symbol, base_tf)
    if base_df is None:
        return None
    return _resample(base_df, rule)
