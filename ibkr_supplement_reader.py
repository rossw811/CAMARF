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


def supplement_path(symbol: str, tf_label: str) -> str:
    """Absolute path to the deep-history parquet for this symbol-TF."""
    safe_tf = _TF_SAFE.get(tf_label, tf_label.replace(" ", ""))
    return os.path.join(SUPPLEMENT_DIR, f"{symbol}_{safe_tf}_deep.parquet")


def load_supplement(symbol: str, tf_label: str) -> Optional[pd.DataFrame]:
    """
    Load deep IBKR history for a symbol-TF if it exists.
    Returns None if no supplement exists — caller degrades gracefully.
    """
    p = supplement_path(symbol, tf_label)
    if not os.path.exists(p):
        return None
    try:
        df = pd.read_parquet(p)
        return df if not df.empty else None
    except Exception:
        return None
