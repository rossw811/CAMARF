"""
research/coint_strength_series_builder.py -- Phase 1b of the discovery-
event/correlation-transition research program (2026-09-03, Ross: "instead
of coint and not_coint we measure it as a %... systems just like how we
use for bars, but applied to coint % for arbitrage based").

Converts Tier 3's raw per-window EG p-values (`wrds_deep_history_
episodic_scan_tier3_windows.parquet`, already-computed, no new statistical
test introduced) into a CONTINUOUS per-pair cointegration-strength time
series, treated as a first-class series in its own right -- the same
status a price-spread series has in the existing BacktestEngine -- rather
than only the binary coint/not_coint state §7.2's hysteresis segmentation
discretizes into.

Three columns per (pair, window):
  - coint_strength: 1 - pvalue, bounded [0, 1], higher = more cointegrated.
    Deliberately the simplest possible monotonic transform of the already-
    trusted EG p-value -- no new statistical machinery, easy to audit.
  - coint_strength_z: rolling z-score of coint_strength within the pair's
    own history (COINT_Z_WINDOW windows, matching the spirit of the
    existing price-spread z-score convention `analysis.py`/`backtest.py`
    already use -- reused as a design pattern, not reimplemented, since
    this is a genuinely different underlying series).
  - coint_decay_rate: first difference of coint_strength (window-over-
    window change) -- a NEGATIVE value means cointegration is weakening
    ("decaying") right now, a POSITIVE value means it's strengthening.
    This is the literal "coint or corr decay proxy" Ross named.

All three are computed CAUSALLY (rolling, trailing-window only, matching
this project's PIT-safety convention throughout) -- no centered windows,
no lookahead into a pair's own future windows.

Verified against synthetic ground truth first:
debug/_verify_coint_strength_series_builder.py.

Usage:
    python research/coint_strength_series_builder.py
"""
import logging
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WINDOWS_PATH = os.path.join(_ROOT, "output", "research",
                              "wrds_deep_history_episodic_scan_tier3_windows.parquet")
_OUT_PATH = os.path.join(_ROOT, "output", "research", "coint_strength_series.parquet")

COINT_Z_WINDOW = 10  # rolling windows for the z-score, matching MIN_REGIME_WINDOWS-scale
                      # reasoning already used elsewhere in this project (§7.2's own
                      # MIN_REGIME_WINDOWS=3 is a MINIMUM persistence bar, not a z-score
                      # lookback -- 10 chosen as a first, disclosed default, not yet swept
                      # for an optimal value; see the with/without comparison plan).

log = logging.getLogger("coint_strength_series_builder")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)


def build_coint_strength_series(windows: pd.DataFrame, z_window: int = COINT_Z_WINDOW) -> pd.DataFrame:
    """Given Tier 3's raw (symbol_a, symbol_b, window_end_date, pvalue)
    rows, returns one row per (pair, window) with coint_strength,
    coint_strength_z, and coint_decay_rate added -- all causal (rolling,
    trailing-only, `min_periods` guards so an early window with
    insufficient history gets NaN, not a fabricated value from a
    too-small sample)."""
    # VECTORIZED (2026-09-03, avoided proactively -- this session already hit and fixed the
    # same anti-pattern twice: `.transform(lambda ...)` on a groupby with ~638,095 small
    # groups is still a per-group Python callback under the hood, not a true C-level
    # vectorized op, and would be exactly as slow as the Python-loop version of
    # detect_transitions killed earlier today. Using pandas' BUILT-IN grouped-rolling/diff
    # methods instead (`GroupBy.rolling()`/`GroupBy.diff()`, not a lambda passed through
    # `.transform()`) -- these ARE implemented at the Cython level for grouped data,
    # the actual idiomatic-and-fast way to do this, not just a syntax preference.
    df = windows.sort_values(["symbol_a", "symbol_b", "window_end_date"]).reset_index(drop=True)
    df["coint_strength"] = 1.0 - df["pvalue"]

    grp = df.groupby(["symbol_a", "symbol_b"], sort=False)
    rolling = grp["coint_strength"].rolling(z_window, min_periods=z_window)
    rolling_mean = rolling.mean().reset_index(level=[0, 1], drop=True)
    rolling_std = rolling.std().reset_index(level=[0, 1], drop=True)
    df["coint_strength_z"] = (df["coint_strength"] - rolling_mean) / rolling_std

    df["coint_decay_rate"] = grp["coint_strength"].diff()

    return df[["symbol_a", "symbol_b", "window_start", "window_end_date", "pvalue",
               "coint_strength", "coint_strength_z", "coint_decay_rate"]]


def main():
    _setup_logging()
    log.info("=== coint_strength_series_builder.py: continuous cointegration-strength series, "
             "treated as a first-class series like a price bar ===")

    if not os.path.exists(_WINDOWS_PATH):
        log.error(f"{_WINDOWS_PATH} does not exist -- run "
                  f"research/wrds_deep_history_episodic_scan.py first.")
        sys.exit(1)

    windows = pd.read_parquet(_WINDOWS_PATH)
    log.info(f"Loaded {len(windows)} (pair, window) rows across "
             f"{windows[['symbol_a','symbol_b']].drop_duplicates().shape[0]} pairs.")

    series = build_coint_strength_series(windows)
    series.to_parquet(_OUT_PATH, index=False)
    log.info(f"Saved -> {_OUT_PATH}")
    log.info(f"coint_strength: mean={series['coint_strength'].mean():.4f}, "
             f"coint_strength_z non-null rows={series['coint_strength_z'].notna().sum()} "
             f"of {len(series)} (rest are pairs' first {COINT_Z_WINDOW}-1 windows, "
             f"correctly NaN, not fabricated)")
    log.info("coint_strength_series_builder.py complete")


if __name__ == "__main__":
    main()
