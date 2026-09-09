"""
research/coint_strength_bar_system.py -- Phase 2b of the discovery-event research program
(Ross: "a coint-% bar system with entry/exit rules mirroring price-bar convention"), building
directly on Phase 2's confirmed signal (Finding #49: elevated coint_strength_z predicts 1.4x-3.0x
baseline next-window persistence; coint_decay_rate<0 predicts materially lower persistence).

Mirrors this project's own existing price-bar entry/exit convention (config.py's
ENTRY_ZSCORE=3.0/EXIT_ZSCORE=0.0 for spread mean-reversion trading), but INVERTED in spirit: a
price-bar system enters on a DEVIATION (high |z|) and exits on reversion to the mean; here, a
HIGH coint_strength_z is itself the desirable state (Phase 2's own confirmed signal), so:
  - ENTRY: the first window where coint_strength_z crosses ABOVE `entry_threshold` from below --
    marks the pair's cointegration as having crossed into an unusually-strong-for-this-pair
    regime, the "bar" opens.
  - EXIT: the first SUBSEQUENT window where EITHER coint_strength_z crosses back below
    `exit_threshold`, OR coint_decay_rate turns negative (whichever comes first) -- mirroring
    price-bar's own dual EXIT_ZSCORE/STOP_ZSCORE exit convention (a soft reversion exit and a
    hard deteriorating-trend exit).

This is a diagnostic MEASUREMENT of the bar system's real properties (episode length, in-episode
persistence rate vs. baseline), not a live trading recommendation -- matches this project's own
established "build as a comparison arm/diagnostic first, discuss, then decide" convention
(CLAUDE.md) for every phase built this session so far.

Swept, per Ross's own with/without comparison-arm instruction, across entry_threshold in
{1.0, 1.5, 2.0} x exit_threshold in {0.0, 0.5, 1.0} -- mirrors config.py's own
COARSE_ENTRY_ZSCORE/COARSE_EXIT_ZSCORE sweep convention. z_window fixed at 20 (Phase 2's
strongest observed ratio, 3.0x at threshold=1.0), not re-swept here -- z_window sensitivity is
already fully characterized in Finding #49.

Verified against synthetic ground truth first: debug/_verify_coint_strength_bar_system.py.

Usage:
    python research/coint_strength_bar_system.py
"""
import logging
import os

import numpy as np
import pandas as pd

log = logging.getLogger("coint_strength_bar_system")

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SERIES_PATH = os.path.join(os.path.dirname(_ROOT), "output", "research", "coint_strength_series.parquet")
_OUT_PATH = os.path.join(os.path.dirname(_ROOT), "output", "research", "coint_strength_bar_system.parquet")

Z_WINDOW = 20  # Finding #49's strongest observed signal-vs-baseline ratio (3.0x at threshold=1.0)
ENTRY_THRESHOLDS = [1.0, 1.5, 2.0]
EXIT_THRESHOLDS = [0.0, 0.5, 1.0]
PVALUE_COINT_CUTOFF = 0.05


def _setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")


def add_rolling_z(df: pd.DataFrame, z_window: int) -> pd.Series:
    """Identical convention to coint_decay_rate_signal_test.py's own add_rolling_z -- causal
    GroupBy.rolling(), not .transform(lambda...)."""
    g = df.groupby(["symbol_a", "symbol_b"], sort=False)["coint_strength"]
    roll = g.rolling(z_window, min_periods=max(2, z_window // 2))
    mean = roll.mean().reset_index(level=[0, 1], drop=True)
    std = roll.std(ddof=1).reset_index(level=[0, 1], drop=True)
    return (df["coint_strength"] - mean) / std


def detect_bars(df: pd.DataFrame, entry_threshold: float, exit_threshold: float) -> pd.DataFrame:
    """Walks the FULL window sequence chronologically in a single flat pass over plain numpy
    arrays (sorted by pair then window_start), resetting entry/exit state whenever the
    (symbol_a, symbol_b) pair changes -- NOT a `df.groupby(...)` Python-level loop over 638,095
    pairs. Real performance bug caught live before this was ever run at full scale (2026-09-04):
    a first version DID loop via `for (sym_a, sym_b), g in df.groupby(...)`, timed on a 5,000-pair
    subset, and still hadn't finished after 2+ minutes -- the exact anti-pattern class (Python-
    level iteration over hundreds of thousands of small pandas groups, each carrying real
    per-group DataFrame-slicing overhead) already fixed twice earlier this session in
    correlation_transition_detector.py and avoided proactively in coint_strength_series_builder.py.
    Entry/exit logic is inherently sequential/stateful, so SOME Python-level loop is unavoidable,
    but looping once over ~5M plain numpy array elements (with a cheap group-boundary check) is
    dramatically faster than looping over 638,095 separate pandas group objects."""
    df = df.sort_values(["symbol_a", "symbol_b", "window_start"])
    sym_a_arr = df["symbol_a"].to_numpy()
    sym_b_arr = df["symbol_b"].to_numpy()
    z = df["coint_strength_z_fixed"].to_numpy()
    pv = df["pvalue"].to_numpy()
    decay = df["coint_decay_rate"].to_numpy()
    ws = df["window_start"].to_numpy()
    n = len(df)

    entry_signal = np.isfinite(z) & (z >= entry_threshold)
    exit_by_z = np.isfinite(z) & (z < exit_threshold)
    exit_by_decay = np.isfinite(decay) & (decay < 0)
    exit_signal = exit_by_z | exit_by_decay
    persists = pv < PVALUE_COINT_CUTOFF
    is_new_pair = np.empty(n, dtype=bool)
    is_new_pair[0] = True
    is_new_pair[1:] = (sym_a_arr[1:] != sym_a_arr[:-1]) | (sym_b_arr[1:] != sym_b_arr[:-1])

    bars = []
    in_bar = False
    entry_idx = 0
    n_persist_in_bar = 0
    n_windows_in_bar = 0
    for i in range(n):
        if is_new_pair[i] and in_bar:
            # Prior pair's series ended while still in a bar -- close it as still-open, same
            # convention as reaching the actual series end.
            bars.append((sym_a_arr[i - 1], sym_b_arr[i - 1], ws[entry_idx], ws[i - 1],
                         n_windows_in_bar, n_persist_in_bar / n_windows_in_bar,
                         False, False, True))
            in_bar = False
        if not in_bar:
            if entry_signal[i]:
                in_bar = True
                entry_idx = i
                n_windows_in_bar = 1
                n_persist_in_bar = 1 if persists[i] else 0
        else:
            n_windows_in_bar += 1
            n_persist_in_bar += 1 if persists[i] else 0
            at_series_or_pair_end = (i == n - 1) or is_new_pair[i + 1]
            if exit_signal[i] or at_series_or_pair_end:
                bars.append((sym_a_arr[i], sym_b_arr[i], ws[entry_idx], ws[i],
                             n_windows_in_bar, n_persist_in_bar / n_windows_in_bar,
                             bool(exit_by_z[i]), bool(exit_by_decay[i]),
                             (not exit_signal[i]) and at_series_or_pair_end))
                in_bar = False

    return pd.DataFrame(bars, columns=[
        "symbol_a", "symbol_b", "entry_window_start", "exit_window_start", "n_windows_in_bar",
        "persist_rate_in_bar", "exited_by_z_reversion", "exited_by_decay", "exited_at_series_end",
    ])


def main():
    _setup_logging()
    log.info("=== coint_strength_bar_system.py: entry/exit 'bar' system on coint_strength_z, "
              "mirroring this project's own price-bar ENTRY_ZSCORE/EXIT_ZSCORE convention ===")
    df = pd.read_parquet(_SERIES_PATH)
    log.info(f"Loaded {len(df)} rows, {df.groupby(['symbol_a', 'symbol_b']).ngroups} pairs.")
    df["coint_strength_z_fixed"] = add_rolling_z(df, Z_WINDOW)
    baseline_persist_rate = float((df["pvalue"] < PVALUE_COINT_CUTOFF).mean())
    log.info(f"Unconditional (all-windows) persist rate: {baseline_persist_rate:.4f}")

    rows = []
    for entry_thr in ENTRY_THRESHOLDS:
        for exit_thr in EXIT_THRESHOLDS:
            bars = detect_bars(df, entry_thr, exit_thr)
            if len(bars) == 0:
                log.info(f"  entry={entry_thr} exit={exit_thr}: 0 bars detected")
                continue
            summary = {
                "entry_threshold": entry_thr, "exit_threshold": exit_thr,
                "n_bars": len(bars),
                "n_pairs_with_a_bar": bars["symbol_a"].str.cat(bars["symbol_b"], sep="/").nunique(),
                "mean_bar_length_windows": float(bars["n_windows_in_bar"].mean()),
                "median_bar_length_windows": float(bars["n_windows_in_bar"].median()),
                "mean_in_bar_persist_rate": float(bars["persist_rate_in_bar"].mean()),
                "baseline_persist_rate": baseline_persist_rate,
                "pct_exited_by_decay": float(bars["exited_by_decay"].mean()),
                "pct_exited_by_z_reversion": float(bars["exited_by_z_reversion"].mean()),
                "pct_still_open_at_series_end": float(bars["exited_at_series_end"].mean()),
            }
            rows.append(summary)
            log.info(f"  entry={entry_thr} exit={exit_thr}: {summary['n_bars']} bars across "
                      f"{summary['n_pairs_with_a_bar']} pairs, mean length="
                      f"{summary['mean_bar_length_windows']:.2f} windows, in-bar persist rate="
                      f"{summary['mean_in_bar_persist_rate']:.4f} vs baseline "
                      f"{baseline_persist_rate:.4f}")

    out = pd.DataFrame(rows)
    out.to_parquet(_OUT_PATH)
    log.info(f"Saved -> {_OUT_PATH}")
    log.info("coint_strength_bar_system.py complete")


if __name__ == "__main__":
    main()
