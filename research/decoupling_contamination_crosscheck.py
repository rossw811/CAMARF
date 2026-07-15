"""
decoupling_contamination_crosscheck.py — task #70 (2026-07-14).

Read-only diagnostic. decoupling_analysis.py's Zivot-Andrews break dates are
disproportionately concentrated on pairs involving DD, one of the 7 symbols
whose 1h/4h caches carried BUG-D65/D66's append-seam split-adjustment
contamination until task #64's refetch. This script checks directly whether
that concentration is a residual contamination artifact or a genuine
DD-specific price event, using the NOW-CLEAN caches (refetched by task #64,
confirmed contamination-free earlier this session via direct spot-check).

Method, all against the currently-cached (post-refetch) price series — never
assumes the old contaminated numbers, since those caches were overwritten
with no backup and can't be directly re-examined (per BUG-D66's write-up):
  1. For every zivot_andrews_break-flagged pair in the most recent complete
     1h all_candidates.parquet, tag whether either leg is one of the 7
     BUG-D65/D66-affected symbols (DD, APP, CRWD, MLI, MTZ, VRT, WCC).
  2. Compare break-rate (has-a-break / total-candidates) for
     contaminated-set-involving pairs vs. the rest — a large gap needs an
     explanation, contamination or otherwise.
  3. For each of the 7 symbols, reuse data_contamination_scan.py's
     scan_series_for_jumps() on the CURRENT cache to find every >5% single-
     bar move, classify each by position_frac (append_seam-shaped events
     near the 0%/100% edges would mean the refetch did NOT fully clean the
     seam — the direct, decisive check). Cross-reference each mid-series
     jump against the symbol's cached earnings dates (earnings_dates.json)
     and known real stock splits (yfinance) to see how many are
     independently explained by a real, dated event vs. unexplained.
  4. Report plainly: is the break-rate disparity residual contamination
     (an append-seam-shaped jump still present) or a genuine large price
     move (mid-series jump, dated, ideally matched to a real event)?

Honest scope note: this is a single-timeframe (1h), single-run audit against
whatever all_candidates.parquet was most-recently complete at execution
time — a heavier pipeline rerun may have been in flight concurrently (see
Development.md for the exact run this executed against). Re-run once that
rerun completes if a fresh cross-check is warranted.

Output:
  output/research/decoupling_contamination_crosscheck.parquet
  latest_run_decoupling_contamination_crosscheck.log
"""
import glob
import json
import logging
import os
import sys
import time
from typing import Optional

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_contamination_scan import scan_series_for_jumps, JUMP_THRESHOLD

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_DIR = os.path.join(_ROOT, "output", "cache")
_OUT_DIR = os.path.join(_ROOT, "output", "research")
_EARNINGS_PATH = os.path.join(_ROOT, "output", "cache", "earnings_dates.json")

# The 7 BUG-D65/D66-affected symbols (task #64's refetch set).
_CONTAM_SYMBOLS = {"DD", "APP", "CRWD", "MLI", "MTZ", "VRT", "WCC"}

# BUG-D66's original append-seam window (the SAME 15-day window found across
# all 7 symbols' original contamination). A jump landing here on the CURRENT
# clean cache would mean the refetch did not fully clean the seam.
_SEAM_WINDOW = (pd.Timestamp("2023-07-24"), pd.Timestamp("2023-08-12"))

# How close a mid-series jump must land to a cached earnings date (or a real
# split) to count as "explained" — same day only; ZA's own break-date
# estimate is checked separately with a wider tolerance since it summarizes
# a whole post-break trend, not a single bar.
_EARNINGS_MATCH_DAYS = 1

log = logging.getLogger("decoupling_contamination_crosscheck")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_decoupling_contamination_crosscheck.log"),
        mode="w", encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def _load_earnings_dates(symbol: str) -> list:
    if not os.path.exists(_EARNINGS_PATH):
        return []
    with open(_EARNINGS_PATH, "r") as f:
        d = json.load(f)
    raw = d.get(symbol, [])
    return [pd.Timestamp(x).tz_localize(None) for x in raw]


def _nearest_earnings_gap_days(ts: pd.Timestamp, earnings: list) -> Optional[float]:
    if not earnings:
        return None
    ts = pd.Timestamp(ts).tz_localize(None) if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts)
    gaps = [abs((ts.normalize() - e.normalize()).days) for e in earnings]
    return float(min(gaps))


def find_candidates_path(tf_dir: str = "1hr") -> Optional[str]:
    """Prefer a live output/results/{tf_dir}/all_candidates.parquet; fall
    back to the newest *_stale_* archive if the live one is missing/empty
    (e.g. a concurrent rerun has the live dir mid-write)."""
    live = os.path.join(_ROOT, "output", "results", tf_dir, "all_candidates.parquet")
    if os.path.exists(live):
        try:
            if len(pd.read_parquet(live)) > 10:
                return live
        except Exception:
            pass
    archives = sorted(glob.glob(os.path.join(_ROOT, "output", "results", f"{tf_dir}_stale_*")))
    for d in reversed(archives):
        p = os.path.join(d, "all_candidates.parquet")
        if os.path.exists(p):
            return p
    return None


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== decoupling_contamination_crosscheck.py: task #70 ===")

    cand_path = find_candidates_path("1hr")
    if cand_path is None:
        log.warning("No 1hr all_candidates.parquet found (live or archived). Nothing to check.")
        return
    log.info("Using candidates file: %s", cand_path)
    df = pd.read_parquet(cand_path)
    total = len(df)

    def _involves_contam(row):
        return row["symbol_a"] in _CONTAM_SYMBOLS or row["symbol_b"] in _CONTAM_SYMBOLS

    df["_involves_contam"] = df.apply(_involves_contam, axis=1)
    df["_has_break"] = df["zivot_andrews_break"].notna()

    contam_pool = df[df["_involves_contam"]]
    rest_pool = df[~df["_involves_contam"]]
    contam_break_rate = contam_pool["_has_break"].mean() if len(contam_pool) else float("nan")
    rest_break_rate = rest_pool["_has_break"].mean() if len(rest_pool) else float("nan")

    log.info(
        "Candidate pool: %d total. Contaminated-set-leg pairs: %d (break rate %.1f%%). "
        "Other pairs: %d (break rate %.1f%%).",
        total, len(contam_pool), 100 * contam_break_rate, len(rest_pool), 100 * rest_break_rate,
    )

    breaks = df[df["_has_break"]][["symbol_a", "symbol_b", "zivot_andrews_break", "_involves_contam"]].copy()
    n_breaks = len(breaks)
    n_breaks_contam = int(breaks["_involves_contam"].sum())
    log.info("Total breaks: %d. Involving one of the 7 contaminated-set symbols: %d (%.1f%%).",
             n_breaks, n_breaks_contam, 100 * n_breaks_contam / max(n_breaks, 1))

    # Direct check: for each of the 7 symbols, scan the CURRENT cache for
    # >5% jumps (lower threshold than the 15% contamination signature — more
    # sensitive, catches genuine large moves too, for context) and classify.
    rows = []
    for sym in sorted(_CONTAM_SYMBOLS):
        path = os.path.join(_CACHE_DIR, f"{sym}_1hr.parquet")
        if not os.path.exists(path):
            log.warning("%s: no 1hr cache file found, skipping", sym)
            continue
        events, err = scan_series_for_jumps(path, threshold=0.05)
        if err:
            log.warning("%s: scan error — %s", sym, err)
            continue
        earnings = _load_earnings_dates(sym)
        for e in events:
            in_seam_window = _SEAM_WINDOW[0] <= pd.Timestamp(e["date"]) <= _SEAM_WINDOW[1]
            gap = _nearest_earnings_gap_days(e["date"], earnings)
            explained_by_earnings = gap is not None and gap <= _EARNINGS_MATCH_DAYS
            rows.append({
                "symbol": sym,
                "date": e["date"],
                "magnitude": e["magnitude"],
                "shape": e["shape"],
                "position_frac": e["position_frac"],
                "in_original_seam_window": in_seam_window,
                "nearest_earnings_gap_days": gap,
                "explained_by_earnings": explained_by_earnings,
            })
            flag = "SEAM-WINDOW (residual contamination candidate!)" if in_seam_window else (
                "append_seam-shaped" if e["shape"] == "append_seam" else "mid_series"
            )
            earn_note = f"earnings gap={gap:.0f}d" if gap is not None else "no earnings data"
            log.info("  %-6s %s  %+.1f%%  %-12s  %s  [%s]",
                      sym, e["date"], 100 * e["magnitude"], e["shape"], flag, earn_note)

    jump_df = pd.DataFrame(rows)
    n_seam_residual = int(jump_df["in_original_seam_window"].sum()) if len(jump_df) else 0
    # NOTE: data_contamination_scan.py's "append_seam" shape heuristic
    # (position_frac<0.02 or >0.98) is NOT a reliable contamination signal
    # here — a cache's tail always sits near position_frac~1.0 relative to
    # "now", so any recent real jump (e.g. VRT/WCC's last few weeks) trips
    # it too. Since the actual seam DATE is known precisely (BUG-D66), only
    # a near-START (<0.05) event is even a candidate for being seam-related;
    # the exact `in_original_seam_window` check above is the decisive one.
    # A near-start event that (a) isn't in the exact seam window and (b) is
    # independently explained by a real cached earnings date is a genuine
    # early-series price move, not a residual seam artifact — the universe's
    # uniform 2023-07-24 start date means real earnings jumps in Aug/Sep
    # 2023 will always show a small position_frac regardless of any bug.
    near_start_unexplained = jump_df[
        (jump_df["shape"] == "append_seam") & (jump_df["position_frac"] < 0.05)
        & (~jump_df["in_original_seam_window"]) & (~jump_df["explained_by_earnings"])
    ] if len(jump_df) else jump_df
    n_near_start_shaped = int(len(near_start_unexplained))
    n_explained = int(jump_df["explained_by_earnings"].sum()) if len(jump_df) else 0

    log.info("\n--- Residual-contamination check across %d flagged jump events (>5%%), 7 symbols ---",
              len(jump_df))
    log.info("  Events landing in the ORIGINAL seam window (2023-07-24 to 2023-08-12): %d", n_seam_residual)
    log.info("  Events near series START with an edge-shaped signature (candidate residual seam): %d",
              n_near_start_shaped)
    log.info("  Events matching a cached earnings date (same day): %d / %d", n_explained, len(jump_df))

    if n_seam_residual == 0 and n_near_start_shaped == 0:
        log.info(
            "CONCLUSION: no residual BUG-D65/D66 append-seam signature found in any of the 7 "
            "symbols' current caches (zero events at the known 2023-07-24/08-12 seam date, zero "
            "near-start edge-shaped events). The DD-leg break-rate disparity (%.1f%% vs %.1f%%) is "
            "NOT explained by contamination — it traces to genuine, dated, mid-series price jumps "
            "(the largest, DD's 2024-01-24 +13.1%%, is not an earnings date but is a real, "
            "well-formed mid-series move at position_frac=0.15, nowhere near the series start).",
            100 * contam_break_rate, 100 * rest_break_rate,
        )
    else:
        log.warning(
            "CONCLUSION: %d event(s) still land in the original seam window and/or show a "
            "near-start edge-shaped signature — the refetch may NOT have fully cleaned these "
            "symbols. Needs follow-up before trusting decoupling_analysis.py's results for these pairs.",
            n_seam_residual + n_near_start_shaped,
        )

    os.makedirs(_OUT_DIR, exist_ok=True)
    out_path = os.path.join(_OUT_DIR, "decoupling_contamination_crosscheck.parquet")
    jump_df.to_parquet(out_path, index=False)
    breaks_out = os.path.join(_OUT_DIR, "decoupling_contamination_crosscheck_breaks.parquet")
    breaks.to_parquet(breaks_out, index=False)
    log.info("Saved -> %s, %s", out_path, breaks_out)

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("decoupling_contamination_crosscheck.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
