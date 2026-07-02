"""
data_ibkr.py — IBKR Supplemental Deep-History Pipeline
=======================================================
SEPARATE SCRIPT from data.py. Run manually, after analysis.py has
confirmed pairs. Never interferes with the yfinance primary cache.

Purpose
-------
For every confirmed pair or trio symbol, fetch the MAXIMUM available
history from IBKR across ALL intraday TFs. This enables:

  1. Episodic cointegration testing: run EG on rolling 252-day windows
     over 10-30 years to classify the relationship as stable-current,
     recovered, historical-episode, or episodic.

  2. Cross-TF cointegration: a pair confirmed at 15m may also cointegrate
     at 1h or 4h historically. The stability profile differs by TF.

  3. Survivorship bias stress test: explicitly test pairs that had
     cointegration in the past but may have lost it, using the full
     history to see when and why the relationship changed.

IBKR maximum history per TF (hard limits):
  1m  → 7 days      (microstructure, recent only)
  5m  → 1 year
  15m → 2 years
  30m → 2 years
  1h  → 10 years    (primary episodic cointegration window)
  4h  → 10 years
  1D  → 30 years    (full macro regime context)

Usage
-----
    python data_ibkr.py                          # all confirmed pairs
    python data_ibkr.py --manifest path/to.json  # custom manifest path
    python data_ibkr.py --symbols NTRS STT AAPL  # specific symbols
    python data_ibkr.py --dry-run                # preview without IBKR
    python data_ibkr.py --force                  # re-fetch all, ignore cache
    python data_ibkr.py --tfs 1h 4h 1D          # specific TFs only

Output
------
  output/cache/ibkr_supplement/{SYMBOL}_{TF}_deep.parquet
  - Merged series: IBKR deep history + yfinance recent overlap
  - yfinance overrides IBKR for the recent period (cleaner adj. prices)
  - analysis.py loads these via load_supplement(symbol, tf)

Architecture
------------
  data.py      → yfinance only, 30-40 min, always stable
  data_ibkr.py → IBKR only, runs after confirmed pairs exist, optional
  analysis.py  → loads yfinance primary + supplement if available
"""

import os
import sys
import json
import time
import logging
import argparse
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd
import numpy as np

from data import (
    Config,
    DataStore,
    IBKRFeed,
    ConIdCache,
    snap_timestamps,
    truncate_to_cutoff,
    compute_canonical_cutoff,
)

# ---------------------------------------------------------------------------
log = logging.getLogger("CAMARF")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
from ibkr_supplement_reader import (
    SUPPLEMENT_DIR,
    supplement_path,
    load_supplement,
)

MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "output",
    "results",
    "confirmed_pairs_manifest.json",
)

# ---------------------------------------------------------------------------
# Full TF set with IBKR maximum history depth
# Every confirmed pair symbol is fetched at ALL of these TFs.
# 1m is included for microstructure context even though depth is only 7 days.
# ---------------------------------------------------------------------------
ALL_SUPPLEMENT_TFS: List[Tuple[str, str, str]] = [
    # (tf_label, ibkr_bar_size, max_depth)
    ("1m", "1 min", "7 D"),
    ("5m", "5 mins", "1 Y"),
    ("15m", "15 mins", "2 Y"),
    ("30m", "30 mins", "2 Y"),
    ("1h", "1 hour", "10 Y"),
    ("4h", "4 hours", "10 Y"),
    ("1D", "1 day", "30 Y"),
]

# Supplement file is considered fresh for 7 days (re-fetch weekly)
_SUPPLEMENT_FRESHNESS_DAYS = 7


# ---------------------------------------------------------------------------
# Supplement I/O helpers
# supplement_path and load_supplement are imported from ibkr_supplement_reader
# ---------------------------------------------------------------------------


def is_supplemented(symbol: str, tf_label: str) -> bool:
    """True if fresh supplement exists (< _SUPPLEMENT_FRESHNESS_DAYS old)."""
    p = supplement_path(symbol, tf_label)
    if not os.path.exists(p):
        return False
    age_days = (time.time() - os.path.getmtime(p)) / 86400
    return age_days < _SUPPLEMENT_FRESHNESS_DAYS


def merge_with_yfinance(
    ibkr_deep: pd.DataFrame,
    symbol: str,
    tf_label: str,
) -> pd.DataFrame:
    """
    Merge IBKR deep history with yfinance recent data.

    yfinance has cleaner corporate-action adjustments for recent bars.
    IBKR provides history beyond yfinance's lookback limit.

    Merge strategy:
    - Pre-yfinance window: use IBKR exclusively
    - Overlap window: use yfinance (overrides IBKR)
    - Post-IBKR window (rare): use yfinance
    """
    yf_df = DataStore.load(symbol, tf_label)
    if yf_df is None or yf_df.empty:
        return ibkr_deep  # no yfinance data — use IBKR as-is

    def _normalize_tz(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        if hasattr(df.index, "tz") and df.index.tz is not None:
            df.index = df.index.tz_convert("America/New_York").tz_localize(None)
        return df

    ibkr_deep = _normalize_tz(ibkr_deep)
    yf_df = _normalize_tz(yf_df)

    # IBKR provides the historical backbone; yfinance handles recent
    yf_start = yf_df.index.min()
    ibkr_hist = ibkr_deep[ibkr_deep.index < yf_start]

    merged = pd.concat([ibkr_hist, yf_df]).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    merged.sort_index(inplace=True)
    return merged


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def load_manifest(path: str) -> Dict[str, Any]:
    """Load the confirmed pairs manifest written by analysis.py."""
    if not os.path.exists(path):
        log.warning(f"Manifest not found: {path}")
        log.warning(
            "Run analysis.py first to generate confirmed pairs, "
            "then re-run data_ibkr.py."
        )
        return {}
    with open(path) as f:
        manifest = json.load(f)
    log.info(f"Manifest: {len(manifest)} confirmed pair/trio symbols " f"from {path}")
    return manifest


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


class IBKRSupplementPipeline:
    """
    Fetches maximum-depth IBKR history for all confirmed pair symbols
    across all intraday TFs. Saves to ibkr_supplement/ directory.
    """

    def __init__(self):
        self._ibkr = IBKRFeed()

    def _connected(self) -> bool:
        return getattr(self._ibkr, "_connected", False) and not getattr(
            self._ibkr, "_session_dead", False
        )

    def run(
        self,
        symbols: List[str],
        tfs: List[Tuple[str, str, str]] = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, int]:
        """
        Fetch deep history for the given symbols.

        Parameters
        ----------
        symbols : confirmed pair/trio symbols to supplement
        tfs     : list of (tf_label, ibkr_bar_size, depth) — defaults to ALL_SUPPLEMENT_TFS
        force   : re-fetch even if supplement already exists
        dry_run : log what would be fetched without connecting

        Returns {symbol: n_tfs_saved}
        """
        if tfs is None:
            tfs = ALL_SUPPLEMENT_TFS

        os.makedirs(SUPPLEMENT_DIR, exist_ok=True)
        ConIdCache.load()

        # Build todo list: all symbol × TF combos that need fetching
        todo: List[Tuple[str, str, str, str]] = []  # (sym, tf_label, bar_size, depth)
        skipped = 0
        for sym in symbols:
            for tf_label, bar_size, depth in tfs:
                if not force and is_supplemented(sym, tf_label):
                    skipped += 1
                else:
                    todo.append((sym, tf_label, bar_size, depth))

        log.info(
            f"IBKR Supplement: {len(symbols)} symbols × {len(tfs)} TFs "
            f"= {len(todo)} fetches needed "
            f"({skipped} already fresh, skipped)"
        )

        if not todo:
            log.info("Nothing to fetch — all symbols already supplemented.")
            return {}

        if dry_run:
            log.info("DRY RUN — no IBKR connection made:")
            for sym, tf_label, bar_size, depth in todo:
                log.info(
                    f"  would fetch: {sym} {tf_label} ({depth} of {bar_size} bars)"
                )
            return {}

        # Connect to IBKR
        if not self._ibkr.connect():
            log.error("IBKR connection failed — exiting")
            return {}

        results: Dict[str, int] = {}
        n_saved = 0
        n_failed = 0
        n_skipped = 0  # session-killed mid-run

        # Group by symbol for cleaner logging and pacing
        from itertools import groupby

        todo_by_sym: Dict[str, List] = {}
        for sym, tf_label, bar_size, depth in todo:
            todo_by_sym.setdefault(sym, []).append((tf_label, bar_size, depth))

        for sym_idx, (sym, sym_tfs) in enumerate(todo_by_sym.items()):
            # Session kill switch — stop immediately if TWS crashed
            if getattr(self._ibkr, "_session_dead", False):
                remaining = len(todo_by_sym) - sym_idx
                log.warning(
                    f"IBKR session dead after {sym_idx} symbols. "
                    f"{remaining} symbols skipped. "
                    f"Re-run data_ibkr.py when TWS is stable — "
                    f"already-saved supplements are preserved."
                )
                n_skipped += sum(len(t) for t in list(todo_by_sym.values())[sym_idx:])
                break

            if sym_idx > 0 and sym_idx % 10 == 0:
                log.info(
                    f"  [{sym_idx}/{len(todo_by_sym)}] "
                    f"{n_saved} saved, {n_failed} failed"
                )

            sym_saved = 0
            for tf_label, bar_size, depth in sym_tfs:
                # Inner session check per TF
                if getattr(self._ibkr, "_session_dead", False):
                    break

                try:
                    df = self._ibkr.get_bars(sym, "equity", bar_size, tf_label, depth)
                except Exception as e:
                    log.debug(f"  {sym} {tf_label}: exception — {e}")
                    df = None

                if df is None or df.empty:
                    log.debug(f"  {sym} {tf_label}: no data returned")
                    n_failed += 1
                    continue

                # Align timestamps and truncate to last complete bar
                df = snap_timestamps(df, tf_label, source="ibkr")
                df = truncate_to_cutoff(df, compute_canonical_cutoff(tf_label))

                if df is None or df.empty:
                    n_failed += 1
                    continue

                # Merge with yfinance (yfinance overrides recent overlap)
                merged = merge_with_yfinance(df, sym, tf_label)

                # Save
                out_path = supplement_path(sym, tf_label)
                try:
                    merged.to_parquet(out_path)
                    sym_saved += 1
                    n_saved += 1
                    date_range = (
                        f"{merged.index.min().date()} → " f"{merged.index.max().date()}"
                    )
                    log.debug(
                        f"  ✓ {sym} {tf_label}: {len(merged)} bars ({date_range})"
                    )
                except Exception as e:
                    log.warning(f"  {sym} {tf_label}: save failed — {e}")
                    n_failed += 1

            if sym_saved > 0:
                results[sym] = sym_saved
                log.info(
                    f"  {sym}: {sym_saved}/{len(sym_tfs)} TFs saved "
                    f"({', '.join(t for t, _, _ in sym_tfs[:sym_saved])})"
                )

        # Save conId cache (new resolutions from this run)
        ConIdCache.save()

        try:
            self._ibkr.disconnect()
        except Exception:
            pass

        total_symbols = len(results)
        log.info("=" * 70)
        log.info(
            f"IBKR Supplement complete: "
            f"{n_saved} TF-fetches saved across {total_symbols} symbols | "
            f"{n_failed} failed | {n_skipped} skipped (session killed)"
        )
        if n_skipped:
            log.info(
                "Re-run data_ibkr.py to fetch skipped symbols. "
                "Already-saved supplements are preserved."
            )
        log.info(
            f"Re-run analysis.py to use deep history for episodic "
            f"cointegration analysis."
        )
        log.info("=" * 70)

        return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Fetch maximum-depth IBKR history for confirmed pair symbols. "
            "Run after analysis.py has produced confirmed pairs."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--manifest",
        default=MANIFEST_PATH,
        help=f"Path to confirmed_pairs_manifest.json (default: output/results/)",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="Specific symbols to supplement (overrides manifest)",
    )
    parser.add_argument(
        "--tfs",
        nargs="+",
        default=None,
        choices=["1m", "5m", "15m", "30m", "1h", "4h", "1D"],
        help="Specific TFs to fetch (default: all TFs)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be fetched without connecting to IBKR",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch even if supplement file already exists",
    )
    parser.add_argument(
        "--list-supplements",
        action="store_true",
        help="List existing supplement files and exit",
    )
    parser.add_argument(
        "--client-id",
        type=int,
        default=None,
        help="Override Config.IBKR.CLIENT_ID for this run only (process-local, not "
             "persisted) — use when the default client ID (shared with data.py) is "
             "already held by a stale/orphaned Gateway API connection.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.client_id is not None:
        Config.IBKR.CLIENT_ID = args.client_id
        log.info("Client ID override: using %d for this run only", args.client_id)

    if args.list_supplements:
        if not os.path.exists(SUPPLEMENT_DIR):
            print("No supplement directory found.")
            return
        files = sorted(os.listdir(SUPPLEMENT_DIR))
        print(f"Supplement files in {SUPPLEMENT_DIR} ({len(files)} files):")
        for f in files:
            size_mb = os.path.getsize(os.path.join(SUPPLEMENT_DIR, f)) / 1e6
            print(f"  {f}  ({size_mb:.1f} MB)")
        return

    log.info("CAMARF  —  data_ibkr.py  —  IBKR Supplemental Pipeline")
    log.info("Primary yfinance cache is untouched by this script.")

    # Resolve symbols
    if args.symbols:
        symbols = args.symbols
        log.info(f"User-specified symbols: {symbols}")
    else:
        manifest = load_manifest(args.manifest)
        if not manifest:
            sys.exit(1)
        symbols = list(manifest.keys())

    if not symbols:
        log.error("No symbols to process.")
        sys.exit(1)

    # Resolve TF set
    if args.tfs:
        tf_map = {t: (b, d) for t, b, d in ALL_SUPPLEMENT_TFS}
        tfs = [(tf, tf_map[tf][0], tf_map[tf][1]) for tf in args.tfs if tf in tf_map]
        log.info(f"Fetching TFs: {[t for t, _, _ in tfs]}")
    else:
        tfs = ALL_SUPPLEMENT_TFS
        log.info(f"Fetching all TFs: {[t for t, _, _ in tfs]}")

    # Run
    pipeline = IBKRSupplementPipeline()
    pipeline.run(
        symbols=symbols,
        tfs=tfs,
        force=args.force,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
