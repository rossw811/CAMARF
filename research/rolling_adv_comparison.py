"""
research/rolling_adv_comparison.py -- comparison arm testing whether a
FLAT, full-history average-daily-dollar-volume (ADV) liquidity filter (what
`analysis.py`'s existing `_compute_adv` does today, and what `data_wrds.py`'s
coarse fetch-pruning `compute_symbol_adv_wrds` does for a bounded recent
window) gives the SAME eligibility verdict as a proper ROLLING,
point-in-time ADV computed at specific historical dates.

Discussed directly with Ross (2026-07-27) before building: a flat/coarse ADV
is fine for `data_wrds.py`'s own fetch-scope-pruning decision ("is this
symbol worth re-fetching at all") -- that's a one-time administrative call,
not something a backtest trades off. It is NOT fine as an actual pair-
eligibility gate during analysis/backtesting, because liquidity is
regime-dependent (a stock illiquid in the 1980s and liquid by the 2010s, or
vice versa, gets ONE number under the flat approach, which can silently
mis-classify its eligibility at any specific historical date). This script
is standalone -- built and verified FIRST, per Ross's explicit direction,
before any integration into analysis.py's production filter or the Tier 2/3
episodic scan's per-window candidate filtering.

Causal correctness is the central claim to prove, not just describe: the
rolling ADV at any date T must depend ONLY on data up to and including T,
never on data after it -- the exact `center=True`-class lookahead bug this
project's own CLAUDE.md flags as a known failure pattern. Verified directly
in debug/_verify_rolling_adv_comparison.py by mutating post-T data and
confirming the value AT T does not change.

Window boundaries reuse research/wrds_deep_history_episodic_scan.py's own
EPISODIC_WINDOW_BARS/EPISODIC_STEP_BARS constants (~10yr windows, ~1yr step)
rather than inventing new ones -- this comparison is meant to answer the
question that matters for THAT script specifically: would gating each
episodic window by rolling (not flat) ADV change which windows are actually
eligible for a cointegration test.

Usage:
    python research/rolling_adv_comparison.py
"""
import glob
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WRDS_CACHE_DIR = os.path.join(_ROOT, "output", "cache", "wrds")
_OUT_DIR = os.path.join(_ROOT, "output", "research")

# Deliberately DUPLICATED, not imported, from wrds_deep_history_episodic_scan.py
# -- that script now imports rolling_adv/load_wrds_universe_ohlcv FROM this
# file (for the Tier 2/3 ADV-gate integration), so importing these constants
# the other direction would create a circular import. Values must stay in
# sync by hand; kept as plain module-level constants specifically so a diff
# in one file is easy to notice needs mirroring in the other.
EPISODIC_WINDOW_BARS = 2520   # ~10 trading years -- MUST match wrds_deep_history_episodic_scan.py's own constant
EPISODIC_STEP_BARS = 252      # ~1 trading year -- MUST match wrds_deep_history_episodic_scan.py's own constant

ROLLING_ADV_WINDOW = 252  # ~1 trading year, trailing only

log = logging.getLogger("rolling_adv_comparison")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(os.path.join(_ROOT, "latest_run_rolling_adv_comparison.log"),
                              mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def flat_adv(df: pd.DataFrame) -> float:
    """The COARSE baseline being tested against: a single average-daily-
    dollar-volume number over the symbol's ENTIRE available history --
    matches analysis.py's existing `_compute_adv` methodology (close *
    volume, then mean over whatever's in the cache)."""
    if "close" not in df.columns or "volume" not in df.columns or df.empty:
        return float("nan")
    dollar_volume = pd.to_numeric(df["close"], errors="coerce") * pd.to_numeric(df["volume"], errors="coerce")
    result = dollar_volume.mean()
    # Some WRDS symbols carry nullable-dtype columns (or are entirely null,
    # e.g. a degenerate history) -- .mean() over an all-NA nullable Series
    # returns pandas' own pd.NA rather than np.nan or a plain float, and
    # float(pd.NA) raises TypeError. Found directly running this against the
    # real 2,846-symbol WRDS cache (crashed on the very first such symbol).
    return float("nan") if pd.isna(result) else float(result)


def rolling_adv(df: pd.DataFrame, window: int = ROLLING_ADV_WINDOW) -> pd.Series:
    """
    Trailing (NOT centered) rolling average daily dollar volume, indexed by
    date. The value at date T is computed using ONLY rows up to and
    including T -- pandas' own `.rolling()` is trailing by construction (no
    `center=True` passed here), so this is causally correct by default, not
    by an extra correction step -- but this is exactly the kind of claim
    this project requires PROVING with a synthetic test, not just asserting
    from pandas' documented default (see debug/_verify_rolling_adv_
    comparison.py's causality check).
    """
    if "close" not in df.columns or "volume" not in df.columns:
        return pd.Series(dtype=float)
    dollar_volume = pd.to_numeric(df["close"], errors="coerce") * pd.to_numeric(df["volume"], errors="coerce")
    return dollar_volume.astype(float).rolling(window=window, min_periods=window).mean()


def load_wrds_universe_ohlcv():
    """Loads every fetched output/cache/wrds/*_1D.parquet file's close+volume
    columns (needed for ADV; NOT the log-price/returns loading the episodic
    scan script uses, since this comparison only needs dollar volume)."""
    out = {}
    for f in sorted(glob.glob(os.path.join(_WRDS_CACHE_DIR, "*_1D.parquet"))):
        sym = os.path.basename(f)[: -len("_1D.parquet")]
        df = pd.read_parquet(f)
        if "close" in df.columns and "volume" in df.columns:
            out[sym] = df
    log.info(f"Loaded {len(out)} symbols with close+volume from output/cache/wrds/")
    return out


def compare_symbol(sym: str, df: pd.DataFrame, threshold: float,
                    window_bars: int = EPISODIC_WINDOW_BARS, step_bars: int = EPISODIC_STEP_BARS,
                    rolling_window: int = ROLLING_ADV_WINDOW):
    """
    For one symbol: computes the flat (whole-history) ADV eligibility once,
    then checks rolling ADV eligibility AT each episodic-window START DATE
    across the symbol's history (same window/step convention the episodic
    scan itself uses). Returns one row per window checked, flagging
    disagreement between the flat and rolling verdicts.

    `rolling_window` is exposed (not hardcoded to ROLLING_ADV_WINDOW)
    specifically so callers (including tests) can use a shorter trailing
    window when working with shorter series -- found directly while writing
    debug/_verify_rolling_adv_comparison.py: a synthetic 300-day series
    produced ZERO rows when this was hardcoded to 252 with min_periods=252,
    since fewer than 252 trailing bars ever existed before day 251,
    silently skipping every window via the NaN check below. Real WRDS
    symbols span thousands of days so the production default is fine there,
    but the hardcoding itself was a real gap, not just a test-scale mismatch.
    """
    flat_val = flat_adv(df)
    flat_eligible = bool(flat_val >= threshold) if np.isfinite(flat_val) else False
    roll = rolling_adv(df, window=rolling_window)

    n = len(df)
    rows = []
    for start in range(0, n - window_bars + 1, step_bars):
        window_start_idx = start
        if window_start_idx >= len(roll):
            continue
        roll_val = roll.iloc[window_start_idx]
        if pd.isna(roll_val):
            continue
        roll_eligible = bool(roll_val >= threshold)
        rows.append({
            "symbol": sym,
            "window_start_idx": window_start_idx,
            "flat_adv": flat_val,
            "flat_eligible": flat_eligible,
            "rolling_adv": roll_val,
            "rolling_eligible": roll_eligible,
            "disagree": flat_eligible != roll_eligible,
            "false_liquid": flat_eligible and not roll_eligible,   # flat says OK, this window wasn't
            "false_illiquid": (not flat_eligible) and roll_eligible,  # flat says NO, this window was actually OK
        })
    return rows


def main():
    _setup_logging()
    log.info("=== rolling_adv_comparison.py: flat (whole-history) ADV vs. rolling, "
             "point-in-time ADV -- do they give the same eligibility verdict? ===")

    universe = load_wrds_universe_ohlcv()
    if len(universe) < 5:
        log.warning("Fewer than 5 symbols loaded -- aborting. Run data_wrds.py's fetch first.")
        return

    threshold = Config.STATS.ADV_FILTER_USD
    log.info(f"Threshold: ${threshold/1e6:.0f}M ADV, episodic window={EPISODIC_WINDOW_BARS} bars "
             f"(~{EPISODIC_WINDOW_BARS/252:.0f}yr), step={EPISODIC_STEP_BARS} bars, "
             f"rolling window={ROLLING_ADV_WINDOW} bars (~1yr)")

    all_rows = []
    for sym, df in universe.items():
        all_rows.extend(compare_symbol(sym, df, threshold))

    if not all_rows:
        log.warning("No (symbol, window) combinations produced -- likely too little history per symbol.")
        return

    result = pd.DataFrame(all_rows)
    n_total = len(result)
    n_disagree = int(result["disagree"].sum())
    n_false_liquid = int(result["false_liquid"].sum())
    n_false_illiquid = int(result["false_illiquid"].sum())

    log.info(f"=== {n_total} (symbol, window) combinations checked across {result['symbol'].nunique()} symbols ===")
    log.info(f"Disagreements: {n_disagree}/{n_total} ({100*n_disagree/n_total:.1f}%)")
    log.info(f"  FALSE LIQUID (flat says OK, this specific window actually wasn't): "
             f"{n_false_liquid} ({100*n_false_liquid/n_total:.1f}%) -- the dangerous case, "
             f"a pair could be accepted as tradable using overall-average liquidity when it "
             f"was actually untradeable during the specific historical regime being tested")
    log.info(f"  false illiquid (flat says NO, this window actually was liquid): "
             f"{n_false_illiquid} ({100*n_false_illiquid/n_total:.1f}%) -- a missed-opportunity "
             f"case, less dangerous but still a real difference in which pairs get considered")

    os.makedirs(_OUT_DIR, exist_ok=True)
    result.to_parquet(os.path.join(_OUT_DIR, "rolling_adv_comparison.parquet"), index=False)
    log.info("Saved -> output/research/rolling_adv_comparison.parquet")
    log.info("rolling_adv_comparison.py complete. NOT yet wired into analysis.py's production "
             "filter or the Tier 2/3 episodic scan -- standalone comparison arm only, per Ross's "
             "explicit direction to build and verify this first.")


if __name__ == "__main__":
    main()
