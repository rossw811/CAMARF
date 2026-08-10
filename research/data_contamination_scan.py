"""
Universe-wide data-contamination scan (task #51, 2026-07-13).

Read-only diagnostic. Detects unexplained single-bar price jumps across every
cached symbol/timeframe price series, generalizing BUG-D65's detection logic
(DataStore._reconcile_split_adjustment in data.py, which operates at one
known append seam) into a scan across every cached series for the same
signature, plus a broader "unexplained jump anywhere in the series" check in
case a second contamination mechanism exists that BUG-D65's specific root
cause (append-seam split-adjustment-basis mismatch) doesn't cover.

This script NEVER writes to output/cache/. It only reads and reports.

Usage: python research/data_contamination_scan.py [--limit-network N]
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CACHE_DIR = "output/cache"
OUT_PATH = "output/research/data_contamination_scan.parquet"
MANIFEST_PATH = "output/results/confirmed_pairs_manifest.json"

# Matches DataStore._SPLIT_GAP_TOLERANCE in data.py (BUG-D65) exactly.
JUMP_THRESHOLD = 0.15

# Matches the relative-error tolerance BUG-D65's own reconciliation function
# uses when validating an observed gap ratio against a recorded split factor.
SPLIT_MATCH_REL_TOL = 0.10

# Real cache-file timeframe suffixes as they actually exist on disk (checked
# directly via a filename survey, not assumed from config.py's comment).
REAL_TF_SUFFIXES = (
    "15min", "30min", "1min", "2min", "3min", "5min",
    "1hr", "4hr", "1day", "7day", "1mo", "3mo", "6mo",
)

# Known macro/crisis windows where a large single-bar move is a real market
# event, not contamination. Loosely bounded (multi-day) since a crash is not
# a single-tick event across all symbols at once. Confirmed against BUG-D65's
# own scan of DD's daily/weekly/monthly caches, which found exactly this
# class of legitimate large move (1987, 2008-2009, plus 2019 DowDuPont which
# is a real corporate action, not a macro window).
MACRO_WINDOWS = [
    ("1987-10-14", "1987-10-23"),  # Black Monday crash week
    ("2008-09-12", "2008-10-15"),  # Lehman + October 2008 crash
    ("2020-02-20", "2020-04-07"),  # COVID crash + initial snapback
]


def list_price_cache_files(cache_dir: str = CACHE_DIR):
    """Enumerate real SYMBOL_TF price cache files, excluding _meta files and
    macro/COT/FRED context series (cot_*, fred_*), which are not part of the
    equity/asset candidate universe this scan is auditing."""
    out = []
    for f in glob.glob(os.path.join(cache_dir, "*.parquet")):
        base = os.path.basename(f)[: -len(".parquet")]
        if base.endswith("_meta"):
            continue
        if base.startswith("cot_") or base.startswith("fred_"):
            continue
        for tf in REAL_TF_SUFFIXES:
            suffix = "_" + tf
            if base.endswith(suffix):
                symbol = base[: -len(suffix)]
                out.append((symbol, tf, f))
                break
    return out


def _macro_explained(ts: pd.Timestamp) -> bool:
    d = pd.Timestamp(ts)
    if d.tzinfo is not None:
        d = d.tz_localize(None)
    for start, end in MACRO_WINDOWS:
        if pd.Timestamp(start) <= d <= pd.Timestamp(end):
            return True
    return False


def scan_series_for_jumps(path: str, threshold: float = JUMP_THRESHOLD):
    """Returns a list of jump-event dicts (empty if none), or None + an error
    string on a read/shape failure."""
    try:
        df = pd.read_parquet(path)
    except Exception as e:  # pragma: no cover - real IO failures only
        return None, f"read_error: {e}"

    if df.empty:
        return [], None

    close_col = "close" if "close" in df.columns else None
    if close_col is None:
        candidates = [c for c in df.columns if "close" in c.lower()]
        if not candidates:
            return None, "no_close_column"
        close_col = candidates[0]

    df = df.copy()
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    close = pd.to_numeric(df[close_col], errors="coerce")
    raw_pct = close.pct_change()
    pct = raw_pct.abs()
    flagged = pct[pct > threshold]
    if flagged.empty:
        return [], None

    n = len(df)
    events = []
    for ts, mag in flagged.items():
        pos = df.index.get_loc(ts)
        if isinstance(pos, slice):
            pos = pos.start
        frac_pos = pos / max(n - 1, 1)
        shape = "append_seam" if (frac_pos < 0.02 or frac_pos > 0.98) else "mid_series"
        events.append(
            {
                "date": ts,
                "magnitude": float(mag),
                # Signed pct-change, kept alongside the abs-value "magnitude"
                # threshold/detection field (Tier 6 fix, Grand Sweep
                # 2026-07-20) -- the console print previously lost the sign
                # entirely (only magnitude=abs(pct_change) was tracked) and
                # showed an ambiguous "ratio=1+magnitude (or 1/(1+magnitude))"
                # dual interpretation instead of just reporting which
                # direction the jump actually went. Cosmetic-only: saved
                # parquet's "magnitude" column is unchanged.
                "signed_change": float(raw_pct.loc[ts]),
                "position_frac": float(frac_pos),
                "shape": shape,
                "n_rows": n,
            }
        )
    return events, None


def fetch_splits(symbol: str, retries: int = 2, sleep_s: float = 0.15):
    """Best-effort split-history fetch. Returns a pandas Series (date -> factor)
    or None on failure. Never raises."""
    import yfinance as yf

    for attempt in range(retries + 1):
        try:
            s = yf.Ticker(symbol).splits
            time.sleep(sleep_s)
            return s
        except Exception:
            if attempt < retries:
                time.sleep(sleep_s * (attempt + 2))
                continue
            return None
    return None


def split_explains_event(event_date: pd.Timestamp, ratio_needed_direction, splits) -> tuple:
    """Checks whether any recorded split within +/-5 calendar days of
    event_date validates the observed jump magnitude, in either multiply or
    reciprocal orientation (BUG-D65 found yfinance's split-factor convention
    is not reliably one direction — see Development.md BUG-D65). Returns
    (explained: bool, matched_factor: float|None, rel_err: float|None)."""
    if splits is None or splits.empty:
        return False, None, None

    d = pd.Timestamp(event_date)
    if d.tzinfo is not None:
        d = d.tz_localize(None)

    splits_idx = splits.index
    if splits_idx.tz is not None:
        splits_idx = splits_idx.tz_localize(None)

    window = splits[(splits_idx >= d - pd.Timedelta(days=5)) & (splits_idx <= d + pd.Timedelta(days=5))]
    if window.empty:
        return False, None, None

    cum = float(window.prod())
    # observed jump magnitude is a ratio away from 1.0; compare against the
    # split factor and its reciprocal, same dual-orientation check BUG-D65's
    # own reconciliation function uses.
    candidates = [cum, 1.0 / cum] if cum != 0 else []
    best_err = None
    for c in candidates:
        implied_ratio = c  # candidate ratio in "new/old" price-space sense
        err = abs(abs(implied_ratio - 1.0) - ratio_needed_direction) / max(abs(ratio_needed_direction), 1e-9)
        if best_err is None or err < best_err:
            best_err = err
    if best_err is not None and best_err <= SPLIT_MATCH_REL_TOL:
        return True, cum, best_err
    return False, cum, best_err


def main():
    parser = argparse.ArgumentParser(description="Universe-wide read-only data-contamination scan (task #51)")
    parser.add_argument("--limit-network", type=int, default=None,
                         help="Cap the number of unique symbols cross-validated against yfinance split history "
                              "(local jump-detection scan itself is never capped). Omit for no cap.")
    parser.add_argument("--pit-safe", action="store_true",
                         help="Cross-check unexplained-contamination symbols against research/"
                              "pit_pair_discovery.py's PIT-safe episodic screen instead of the "
                              "production confirmed_pairs_manifest.json (task #5). The universe-wide "
                              "jump-detection scan itself is unaffected either way -- this only "
                              "changes which symbol set the final cross-check highlights against.")
    args = parser.parse_args()

    files = list_price_cache_files()
    print(f"[scan] {len(files)} real symbol/timeframe price cache files found "
          f"(after excluding *_meta.parquet and cot_*/fred_* macro-context files)")

    t0 = time.time()
    all_events = []  # list of dict: symbol, tf, date, magnitude, position_frac, shape
    read_errors = []
    n_scanned = 0
    for symbol, tf, path in files:
        events, err = scan_series_for_jumps(path)
        n_scanned += 1
        if err is not None:
            read_errors.append({"symbol": symbol, "tf": tf, "path": path, "error": err})
            continue
        for e in events:
            e["symbol"] = symbol
            e["tf"] = tf
            all_events.append(e)
        if n_scanned % 5000 == 0:
            print(f"[scan] {n_scanned}/{len(files)} files scanned, "
                  f"{len(all_events)} raw jump events so far ({time.time()-t0:.0f}s elapsed)")

    print(f"[scan] local jump-detection pass complete: {n_scanned} files scanned, "
          f"{len(read_errors)} read errors, {len(all_events)} raw single-bar jump events >15% "
          f"({time.time()-t0:.0f}s elapsed)")

    unique_symbols = sorted({e["symbol"] for e in all_events})
    print(f"[scan] {len(unique_symbols)} unique symbols have at least one flagged jump; "
          f"cross-validating against recorded split history (network-bound step)")

    if args.limit_network is not None and len(unique_symbols) > args.limit_network:
        skipped = unique_symbols[args.limit_network:]
        unique_symbols = unique_symbols[: args.limit_network]
        print(f"[scan] EXPLICIT CAP APPLIED: --limit-network={args.limit_network}, "
              f"{len(skipped)} symbols NOT cross-validated (still reported as unexplained-pending-check, "
              f"not silently dropped): {skipped[:20]}{'...' if len(skipped) > 20 else ''}")
    else:
        skipped = []

    splits_cache = {}
    t1 = time.time()
    for i, sym in enumerate(unique_symbols):
        splits_cache[sym] = fetch_splits(sym)
        if (i + 1) % 100 == 0:
            print(f"[scan] split-history fetch: {i+1}/{len(unique_symbols)} symbols "
                  f"({time.time()-t1:.0f}s elapsed)")
    print(f"[scan] split-history fetch complete for {len(unique_symbols)} symbols "
          f"({time.time()-t1:.0f}s elapsed)")

    for e in all_events:
        sym = e["symbol"]
        if sym in skipped:
            e["explained"] = None
            e["explanation"] = "network_check_skipped_by_explicit_cap"
            continue
        if _macro_explained(e["date"]):
            e["explained"] = True
            e["explanation"] = "macro_crisis_window"
            continue
        splits = splits_cache.get(sym)
        explained, matched_factor, rel_err = split_explains_event(e["date"], e["magnitude"], splits)
        e["explained"] = explained
        e["explanation"] = (
            f"recorded_split(factor={matched_factor:.4f},rel_err={rel_err:.3f})" if explained
            else ("no_matching_split_or_macro_window" if splits is not None else "split_fetch_failed")
        )

    events_df = pd.DataFrame(all_events)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    events_df.to_parquet(OUT_PATH)
    print(f"[scan] wrote {len(events_df)} events to {OUT_PATH}")

    unexplained = events_df[events_df["explained"] == False] if not events_df.empty else events_df
    tier1 = unexplained[unexplained["shape"] == "append_seam"] if not unexplained.empty else unexplained
    tier2 = unexplained[unexplained["shape"] == "mid_series"] if not unexplained.empty else unexplained

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Files scanned:              {n_scanned}")
    print(f"Read errors:                {len(read_errors)}")
    print(f"Raw jump events (>15%):     {len(events_df)}")
    print(f"Unique symbols flagged:     {len(unique_symbols) + len(skipped)}")
    print(f"Explained (split/macro):    {int((events_df['explained'] == True).sum()) if not events_df.empty else 0}")
    print(f"UNEXPLAINED total:          {len(unexplained)}")
    print(f"  Tier 1 (append-seam-shaped, BUG-D65 signature): {len(tier1)}")
    print(f"  Tier 2 (mid-series, different/unknown mechanism): {len(tier2)}")
    print(f"Skipped by network cap:     {len(skipped)} symbols")

    if not tier1.empty:
        print("\nTier 1 (append-seam) unexplained symbols/timeframes:")
        for _, r in tier1.sort_values(["symbol", "tf"]).iterrows():
            signed = r.get("signed_change", r["magnitude"])
            print(f"  {r['symbol']:>10s} {r['tf']:>6s}  {r['date']}  "
                  f"{'+' if signed >= 0 else ''}{signed:.3%} ({1+signed:.3f}x) pos_frac={r['position_frac']:.3f}")

    if not tier2.empty:
        print("\nTier 2 (mid-series) unexplained symbols/timeframes:")
        for _, r in tier2.sort_values(["symbol", "tf"]).iterrows():
            signed = r.get("signed_change", r["magnitude"])
            print(f"  {r['symbol']:>10s} {r['tf']:>6s}  {r['date']}  "
                  f"{'+' if signed >= 0 else ''}{signed:.3%} ({1+signed:.3f}x) pos_frac={r['position_frac']:.3f}")

    # Cross-check against confirmed pairs (production manifest, or PIT-safe episodic set).
    try:
        if args.pit_safe:
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))
            from pit_pair_discovery import discover_pit_confirmed_pairs
            pit_pairs = discover_pit_confirmed_pairs()
            manifest_symbols = set(s for a, b, _tf in pit_pairs for s in (a, b))
            source_desc = f"PIT-safe episodic screen ({len(pit_pairs)} (pair,tf) combinations"
        else:
            import json
            with open(MANIFEST_PATH) as f:
                manifest = json.load(f)
            # Tier 6 fix (Grand Sweep 2026-07-20): the manifest's actual schema
            # (confirmed by reading output/results/confirmed_pairs_manifest.json
            # directly) is {symbol: {"tfs": [...], "added": ...}} -- each
            # TOP-LEVEL KEY IS ALREADY AN INDIVIDUAL SYMBOL, not a "SYMBOLA_
            # SYMBOLB" compound pair-key. The prior "_"-split logic was
            # currently inert (no real symbol here contains "_", so the else
            # branch always fired and happened to add the correct bare key
            # anyway) but reflected a wrong mental model of the schema -- e.g.
            # it would have silently mis-parsed a symbol like "BRK_B" had one
            # ever appeared. Manifest keys are used directly now, no split.
            manifest_symbols = set(manifest.keys())
            source_desc = f"production manifest ({len(manifest)} pairs"
        flagged_symbols_unexplained = set(unexplained["symbol"]) if not unexplained.empty else set()
        overlap = manifest_symbols & flagged_symbols_unexplained
        print(f"\nConfirmed-pairs cross-check, {source_desc}, "
              f"{len(manifest_symbols)} unique constituent symbols):")
        if overlap:
            print(f"  *** {len(overlap)} confirmed-pair symbol(s) have unexplained contamination: "
                  f"{sorted(overlap)} ***")
            for sym in sorted(overlap):
                affected_tfs = sorted(unexplained[unexplained["symbol"] == sym]["tf"].unique())
                print(f"      {sym}: affected timeframe(s) = {affected_tfs}")
        else:
            print("  No confirmed-pair symbol has unexplained contamination (checked directly, "
                  f"not assumed) — {len(manifest_symbols)} constituent symbols cross-referenced "
                  f"against {len(flagged_symbols_unexplained)} unexplained-flagged symbols.")
    except FileNotFoundError:
        print(f"\nConfirmed-pairs manifest not found at {MANIFEST_PATH} — skipped cross-check.")

    print(f"\nTotal runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
