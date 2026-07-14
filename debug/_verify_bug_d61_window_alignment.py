"""
debug/_verify_bug_d61_window_alignment.py — BUG-D61 regression test (2026-07-12)

BUG-D61: distance.py's comparison has two sides that determine their trading-window
cutoff by two STRUCTURALLY DIFFERENT mechanisms:

  - Cointegration side (backtest.py's BacktestEngine.run(..., holdout_only=True)):
    cutoff = int(len(df) * (1 - HOLDOUT_PCT)) -- a BAR-COUNT fraction of that pair's
    OWN gap/NaN-filtered spread series. Two pairs with identical calendar range but
    different bar density (gaps, missing bars) can land on different calendar dates.

  - Distance side (distance.py main()): a single CALENDAR-DATE cutoff
    (formation_end = full_start + (full_end - full_start) * _FORMATION_FRAC) computed
    once from spread files' min/max timestamps and applied uniformly to every pair,
    regardless of that pair's own bar density.

The 2026-07-12 fix aligned _FORMATION_FRAC (0.5 -> 0.8) to match HOLDOUT_PCT (0.20)
exactly, and real-data instrumentation (debug/_measure_bug_d61_cutoff_gap.py, all 24
confirmed 1h pairs) measured the residual per-pair-cutoff-date vs. global-cutoff-date
gap at max 5 days / median 4 days -- trivial, well under the >14-day "material" bar
used to judge this. Per that finding, NO further code change (e.g. a shared explicit
`holdout_start_date` passed into both sides) was made -- see Development.md's 2026-07-12
entry for the full closure writeup.

THIS test's purpose: confirm that conclusion holds even under a synthetic STRESS case
(50% of bars missing, uniformly at random -- the realistic shape of CAMARF's own
DATA_GAP masking, which scatters missing bars rather than concentrating them in one
block) rather than relying on real data alone. It calls the REAL production functions
(BacktestEngine.run, distance.run_distance_trades) -- not a reimplementation of their
cutoff logic.

Honesty note (deliberate, not an oversight): this test asserts the two sides' selected
trade-date-ranges fall within a TOLERANCE (10 days, matching the existing ">14 days =
material" bar already established for this bug), not bit-identical dates. Bit-identical
dates would require the additive `holdout_start_date` fix that was evaluated and found
unnecessary given real measured gaps were trivial (5 days max). Asserting literal
identity here would misrepresent what was actually fixed and would require an
unneeded production code change just to satisfy the letter of a stress test -- exactly
the kind of overclaim CLAUDE.md rule 7 prohibits.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shutil
import tempfile

import numpy as np
import pandas as pd

from config import Config
from backtest import BacktestEngine, RegimeConditioner, MLConditioner
import distance as dist_mod

TOLERANCE_DAYS = 10  # matches the ">14 days = material" bar used in Development.md's BUG-D61 writeup


def build_calendar(n_days: int = 400) -> pd.DatetimeIndex:
    """Business days, 7 hourly bars/day 9:30-15:30 -- mirrors real 1h spread_series shape."""
    days = pd.bdate_range("2024-01-02", periods=n_days)
    hours = ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"]
    ts = pd.DatetimeIndex(sorted(pd.Timestamp(f"{d.date()} {h}") for d in days for h in hours))
    return ts


def make_spread_df(timestamps: pd.DatetimeIndex, z_signal: np.ndarray,
                    missing_mask: np.ndarray = None) -> pd.DataFrame:
    n = len(timestamps)
    df = pd.DataFrame({
        "spread": z_signal * 0.5,
        "z_rolling": z_signal,
        "z_expanding": z_signal,
        "half_life_rolling": np.full(n, 20.0),
        "gap_flag_a": np.zeros(n, dtype="int8"),
        "gap_flag_b": np.zeros(n, dtype="int8"),
        "hedge_ratio_ols_t": np.ones(n),
        "hedge_ratio_kalman_t": np.ones(n),
    }, index=timestamps)
    if missing_mask is not None:
        # Simulate missing bars exactly the way real DATA_GAP-affected bars show up to
        # BacktestEngine.run(): NaN'd out, then dropped by its own
        # df.dropna(subset=["z_rolling", "spread"]) filter -- same code path as real data.
        df.loc[missing_mask, ["z_rolling", "spread"]] = np.nan
    return df


def triangle_wave(n: int, period: int, amplitude) -> np.ndarray:
    """Clean triangle wave: guarantees regular +-amplitude crossings and zero-crossings,
    independent of any formation-window statistics (needed for the cointegration side,
    which trades directly off z_rolling as given -- no re-estimation). `amplitude` may be
    a scalar or a per-point array (used to give the distance side's OOS window a much
    larger swing than its formation window, so entries reliably cross the formation-
    period-estimated z-score threshold)."""
    t = np.arange(n) % period
    half = period / 2.0
    tri = np.where(t < half, -1 + 2 * t / half, 3 - 2 * t / half)  # ramps -1..1..-1
    return tri * amplitude


def main():
    timestamps = build_calendar()
    n = len(timestamps)
    full_start, full_end = timestamps[0], timestamps[-1]

    formation_frac = 1.0 - Config.BACKTEST.HOLDOUT_PCT  # matches distance.py's fixed _FORMATION_FRAC
    assert abs(formation_frac - dist_mod._FORMATION_FRAC) < 1e-9, (
        "distance.py's _FORMATION_FRAC has drifted from Config.BACKTEST.HOLDOUT_PCT -- "
        "re-check the BUG-D61 fix is still in place before trusting this test."
    )
    ground_truth_cutoff = full_start + (full_end - full_start) * formation_frac

    # --- Cointegration side: real BacktestEngine.run(), holdout_only=True ---
    z_signal = triangle_wave(n, period=40, amplitude=2.5)  # crosses ENTRY_ZSCORE=2.0 and EXIT_ZSCORE=0.0
    pair_row = pd.Series({
        "symbol_a": "SYNA", "symbol_b": "SYNB", "tf_label": "1h",
        "hedge_ratio_ols": 1.0, "hedge_ratio_kalman_mean": 1.0,
        "hurst_rs": 0.4, "coint_fraction_rolling": 0.5,
        "half_life_trend_slope": 0.0, "mean_reversion_speed": 0.1,
    })
    engine = BacktestEngine(
        cfg=Config.BACKTEST,
        regime_cond=RegimeConditioner(enabled=False),
        ml_cond=MLConditioner(enabled=False),
        storm_flags={}, mm_hedge_map={},
    )

    df_dense = make_spread_df(timestamps, z_signal)
    trades_dense = engine.run(pair_row, df_dense, hedge_method="ols", holdout_only=True)
    assert len(trades_dense) > 0, "Synthetic dense pair produced no trades -- signal construction bug"

    rng = np.random.RandomState(123)
    missing_mask = rng.rand(n) < 0.5  # 50% of bars missing, UNIFORMLY at random
    df_sparse = make_spread_df(timestamps, z_signal, missing_mask=missing_mask)
    trades_sparse = engine.run(pair_row, df_sparse, hedge_method="ols", holdout_only=True)
    assert len(trades_sparse) > 0, "Synthetic 50%-missing pair produced no trades -- signal construction bug"

    coint_dense_start = min(t.entry_time for t in trades_dense)
    coint_sparse_start = min(t.entry_time for t in trades_sparse)

    # --- Distance side: real distance.run_distance_trades(), reading from a temp cache dir ---
    tmp_cache = tempfile.mkdtemp(prefix="bug_d61_verify_")
    orig_cache_dir = dist_mod._CACHE_DIR
    try:
        dist_mod._CACHE_DIR = tmp_cache

        # Price series whose normalized spread swings gently in "formation" (small std,
        # used to calibrate the entry z-score) and much more widely in "trading" --
        # guarantees the OOS swings cross the formation-calibrated entry threshold.
        amp_array = np.where(timestamps > ground_truth_cutoff, 6.0, 0.5)
        price_wave = triangle_wave(n, period=40, amplitude=amp_array)
        pa = pd.Series(100.0 + price_wave, index=timestamps, name="close")
        pb = pd.Series(100.0 - price_wave, index=timestamps, name="close")
        for sym, s in (("SYNA", pa), ("SYNB", pb)):
            pd.DataFrame({"close": s}).to_parquet(os.path.join(tmp_cache, f"{sym}_1hr.parquet"))

        dist_trades = dist_mod.run_distance_trades("SYNA", "SYNB", "1hr", ground_truth_cutoff)
        assert len(dist_trades) > 0, "Synthetic distance-side pair produced no trades -- signal construction bug"

        # Regression guard: distance side must never select a trade before the cutoff it was given
        assert all(t["entry_time"] > ground_truth_cutoff for t in dist_trades), (
            "run_distance_trades selected a trade before its own formation_end cutoff -- "
            "this would be a NEW bug, not BUG-D61."
        )
        dist_start = min(t["entry_time"] for t in dist_trades)
    finally:
        dist_mod._CACHE_DIR = orig_cache_dir
        shutil.rmtree(tmp_cache, ignore_errors=True)

    gap_dense_days = abs((coint_dense_start - dist_start).days)
    gap_sparse_days = abs((coint_sparse_start - dist_start).days)

    print(f"Ground-truth calendar cutoff (80% of range):     {ground_truth_cutoff.date()}")
    print(f"Distance-side first trade (calendar-cutoff-based): {dist_start.date()}")
    print(f"Cointegration-side (dense) first trade:            {coint_dense_start.date()}  "
          f"(gap vs. distance: {gap_dense_days} days)")
    print(f"Cointegration-side (50% missing) first trade:      {coint_sparse_start.date()}  "
          f"(gap vs. distance: {gap_sparse_days} days)")

    assert gap_dense_days <= TOLERANCE_DAYS, (
        f"Dense-pair cutoff gap {gap_dense_days}d exceeds {TOLERANCE_DAYS}d tolerance"
    )
    assert gap_sparse_days <= TOLERANCE_DAYS, (
        f"50%-missing-bar pair cutoff gap {gap_sparse_days}d exceeds {TOLERANCE_DAYS}d tolerance -- "
        f"this WOULD indicate BUG-D61 is not adequately closed and the additive "
        f"holdout_start_date fix should be implemented."
    )

    print(f"\nPASS: both cointegration-side variants (dense and 50%-missing-bar) select "
          f"trades within {TOLERANCE_DAYS} days of the distance side's calendar cutoff, "
          f"consistent with real-data measurement (max 5 days across all 24 confirmed pairs).")


if __name__ == "__main__":
    main()
