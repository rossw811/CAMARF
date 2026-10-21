"""Sealed holdout at the data layer (Ross, DECISIONS_2026-10-12 E13; enforced for every source DECISIONS_2026-10-21 #2).

No CAMARF result may be computed on sealed data. Filtering in each reader would leave ~70 scripts that read price
caches directly (and every future one) to remember the rule, so sealed rows are kept OUT of the working caches:

  * `write_parquet` is the cache writers' path: the open part goes to the cache file, the sealed part is merged
    into the same relative path under `<CACHE_DIR>/_sealed_vault/`.
  * `sweep` moves sealed rows already in a cache directory to the vault (idempotent; any writer that bypassed
    `write_parquet` is caught here). `audit` counts what is left; pipeline chains call it as a gate.
  * `drop_sealed` is the shared readers' backstop.

Seal dates: daily-and-coarser data from `Config.DATA.SEALED_FROM` (2026-01-01); intraday from
`Config.DATA.SEALED_FROM_INTRADAY` (2026-10-21: the forward-recorded holdout). Reading the vault is explicit
(`read_full`) and reserved for data maintenance (repairs that must reach the sealed rows too) and the final
pre-registered test.
"""
from __future__ import annotations

import os
import re
from typing import Optional, Tuple

import pandas as pd

from config import Config

# Timeframe token (last "_" token of a cache filename, after an optional "_deep") -> kind. Case-sensitive on purpose:
# Binance "1m" is one minute, WRDS "1M" is one month.
_INTRADAY = {"1min", "2min", "3min", "5min", "15min", "30min", "1hr", "4hr",
             "1m", "2m", "3m", "5m", "15m", "30m", "1h", "4h"}
_DAILY = {"1day", "7day", "1mo", "3mo", "6mo", "1yr", "1D", "7D", "1W", "1M", "3M", "6M", "1Y", "1d", "1w",
          "daily", "weekly"}        # macro.py's FRED / COT caches (DataStore keys "daily" / "weekly"; review F7)
_TOKEN_RE = re.compile(r"_([0-9]*[A-Za-z]+)(?:_deep)?\.parquet$")

# Live price-cache directories, relative to Config.DATA.CACHE_DIR ("" is the yfinance cache itself). Backup
# directories (`_backup_*`, `_wrds_pre_sync_*`, ...) are not read by any pipeline and are not swept.
LIVE_CACHE_SUBDIRS = ("", "wrds", "binance", "ibkr_supplement")


def kind_of_path(path: str) -> Optional[str]:
    """'intraday', 'daily', or None for a file that is not a price series of a known timeframe."""
    m = _TOKEN_RE.search(os.path.basename(path))
    if not m:
        return None
    tok = m.group(1)
    if tok in _INTRADAY:
        return "intraday"
    if tok in _DAILY:
        return "daily"
    return None


def sealed_from(kind: str) -> pd.Timestamp:
    return pd.Timestamp(Config.DATA.SEALED_FROM_INTRADAY if kind == "intraday" else Config.DATA.SEALED_FROM)


def _naive(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx


def sealed_mask(df: pd.DataFrame, kind: str):
    """Boolean array, True for rows dated on/after the seal. None when the index is not a DatetimeIndex."""
    if not isinstance(df.index, pd.DatetimeIndex):
        return None
    return _naive(df.index) >= sealed_from(kind)


def split(df: pd.DataFrame, kind: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    m = sealed_mask(df, kind)
    if m is None:
        return df, df.iloc[0:0]
    return df[~m], df[m]


def drop_sealed(df: Optional[pd.DataFrame], kind: Optional[str]) -> Optional[pd.DataFrame]:
    """Readers' backstop: the frame without sealed rows (unchanged if kind is unknown or the index is not dated)."""
    if df is None or kind is None:
        return df
    m = sealed_mask(df, kind)
    return df if m is None or not m.any() else df[~m]


VAULT_SUBDIR = "_sealed_vault"


def vault_root() -> str:
    """Inside the cache directory, so a redirected CACHE_DIR (tests) carries its own vault; "_"-prefixed
    subdirectories are not data by project convention (no reader lists them; lineage skips them)."""
    return os.path.join(Config.DATA.CACHE_DIR, VAULT_SUBDIR)


def vault_path(cache_path: str) -> str:
    rel = os.path.relpath(os.path.abspath(cache_path), os.path.abspath(Config.DATA.CACHE_DIR))
    if rel.startswith(".."):
        raise ValueError(f"{cache_path} is not under {Config.DATA.CACHE_DIR}")
    return os.path.join(vault_root(), rel)


def _atomic_write(df: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".sealtmp"
    df.to_parquet(tmp)
    os.replace(tmp, path)


def _merge_into_vault(sealed: pd.DataFrame, vpath: str) -> None:
    if os.path.exists(vpath):
        old = pd.read_parquet(vpath)
        sealed = pd.concat([old, sealed])
        sealed = sealed[~sealed.index.duplicated(keep="last")].sort_index()
    _atomic_write(sealed, vpath)


def write_parquet(df: pd.DataFrame, path: str, kind: Optional[str] = None) -> Tuple[int, int]:
    """Cache writers' path. Returns (open rows written, sealed rows moved to the vault). The vault is written first,
    so an interruption never loses sealed rows. A file whose kind is unknown is written unchanged."""
    kind = kind or kind_of_path(path)
    if kind is None:
        _atomic_write(df, path)
        return len(df), 0
    open_part, sealed_part = split(df, kind)
    if len(sealed_part):
        _merge_into_vault(sealed_part, vault_path(path))
    if len(open_part):
        _atomic_write(open_part, path)
    elif os.path.exists(path):
        os.remove(path)          # everything this file holds is sealed
    return len(open_part), len(sealed_part)


def read_full(path: str) -> Optional[pd.DataFrame]:
    """Cache file plus its vault rows. Data maintenance and the final pre-registered test only."""
    parts = [pd.read_parquet(p) for p in (path, vault_path(path)) if os.path.exists(p)]
    if not parts:
        return None
    df = pd.concat(parts)
    return df[~df.index.duplicated(keep="last")].sort_index()


def last_bar_including_vault(path: str) -> Optional[pd.Timestamp]:
    """Latest timestamp across cache and vault (fetchers' staleness checks must not re-fetch sealed rows forever)."""
    last = None
    for p in (path, vault_path(path)):
        if os.path.exists(p):
            idx = pd.read_parquet(p, columns=[]).index
            if len(idx) and isinstance(idx, pd.DatetimeIndex):
                t = _naive(idx).max()
                last = t if last is None or t > last else last
    return last


def _price_files(cache_root: str):
    for sub in LIVE_CACHE_SUBDIRS:
        d = os.path.join(cache_root, sub)
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name.endswith(".parquet"):
                p = os.path.join(d, name)
                k = kind_of_path(p)
                if k is not None:
                    yield p, k


def _max_date(path: str) -> Optional[pd.Timestamp]:
    """Last index timestamp (index-only read)."""
    try:
        idx = pd.read_parquet(path, columns=[]).index
    except Exception:
        return None
    if not isinstance(idx, pd.DatetimeIndex) or not len(idx):
        return None
    return _naive(idx).max()


def audit(cache_root: Optional[str] = None) -> dict:
    """Counts of live cache files still holding sealed rows, by kind. Pipeline chains refuse to run unless both are 0."""
    cache_root = cache_root or Config.DATA.CACHE_DIR
    out = {"daily": 0, "intraday": 0, "files_checked": 0, "unreadable": 0, "examples": []}
    for p, k in _price_files(cache_root):
        out["files_checked"] += 1
        try:
            pd.read_parquet(p, columns=[])
        except Exception:   # counted, never silently passed (review F8)
            out["unreadable"] += 1
            continue
        t = _max_date(p)
        if t is not None and t >= sealed_from(k):
            out[k] += 1
            if len(out["examples"]) < 5:
                out["examples"].append(p)
    return out


def sweep(cache_root: Optional[str] = None, dry_run: bool = False) -> dict:
    """Move sealed rows from every live cache file to the vault. Idempotent."""
    cache_root = cache_root or Config.DATA.CACHE_DIR
    out = {"files_moved": 0, "rows_moved": 0, "files_emptied": 0, "by_kind": {"daily": 0, "intraday": 0}}
    for p, k in _price_files(cache_root):
        t = _max_date(p)
        if t is None or t < sealed_from(k):
            continue
        df = pd.read_parquet(p)
        _, sealed_part = split(df, k)
        if not len(sealed_part):
            continue
        out["files_moved"] += 1
        out["rows_moved"] += len(sealed_part)
        out["by_kind"][k] += 1
        if len(sealed_part) == len(df):
            out["files_emptied"] += 1
        if not dry_run:
            write_parquet(df, p, k)
    return out


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Sealed-holdout sweep / audit of the live price caches.")
    ap.add_argument("--audit", action="store_true", help="count only; exit 1 if any live file holds sealed rows")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.audit:
        r = audit()
        print(json.dumps(r, indent=1))
        raise SystemExit(1 if r["daily"] or r["intraday"] else 0)
    print(json.dumps(sweep(dry_run=a.dry_run), indent=1))
