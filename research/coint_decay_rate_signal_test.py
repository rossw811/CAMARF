"""
research/coint_decay_rate_signal_test.py -- Phase 2 of the discovery-event research program
(Ross, 2026-09-03): does a pair's continuous cointegration-strength trajectory -- built in Phase
1b (research/coint_strength_series_builder.py, output/research/coint_strength_series.parquet) --
predict anything, tested via WITH/WITHOUT comparison arms rather than a single fixed design
("it's meant to be for comparison first with and without... to figure out optimal figures").

Target tested: does the pair's cointegration state PERSIST into the next rolling window
(next-window p-value < 0.05, i.e. still "coint")? Two candidate predictors, each swept across
several parameter choices rather than one fixed guess:

  1. coint_strength_z (the causal rolling z-score Phase 1b already builds) -- swept across
     z_window in {5, 10, 15, 20} and a z_threshold in {1.0, 1.5, 2.0}. "WITH signal" = rows where
     z_score >= threshold (an unusually strong-for-this-pair window); "WITHOUT" = the baseline
     unconditional next-window persistence rate across every row with a defined next observation,
     not a cherry-picked comparison group.
  2. coint_decay_rate (window-over-window first difference, Phase 1b) -- WITH = decay_rate < 0
     (weakening trend) vs WITHOUT = decay_rate >= 0 (strengthening/stable trend), same baseline
     convention.

z_window is recomputed here directly from the already-built coint_strength column (cheap --
Phase 1b's own expensive step, the per-window EG scan itself, is NOT redone) rather than re-
running coint_strength_series_builder.py once per z_window value.

Verified against synthetic ground truth first: debug/_verify_coint_decay_rate_signal_test.py.

Usage:
    python research/coint_decay_rate_signal_test.py
"""
import logging
import os

import numpy as np
import pandas as pd
from scipy import stats

log = logging.getLogger("coint_decay_rate_signal_test")

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SERIES_PATH = os.path.join(os.path.dirname(_ROOT), "output", "research", "coint_strength_series.parquet")
_OUT_PATH = os.path.join(os.path.dirname(_ROOT), "output", "research", "coint_decay_rate_signal_test.parquet")

Z_WINDOWS = [5, 10, 15, 20]
Z_THRESHOLDS = [1.0, 1.5, 2.0]
PVALUE_COINT_CUTOFF = 0.05


def _setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")


def two_proportion_z_test(x1: int, n1: int, x2: int, n2: int) -> dict:
    """Standard two-proportion z-test, the same formula used throughout this project's
    discovery-event work (crisis_regime_correlation_diagnostic.py,
    residual_correlation_factor_test.py), reused here rather than reimplemented differently."""
    if n1 == 0 or n2 == 0:
        return {"z_stat": None, "p_value": None}
    p_pool = (x1 + x2) / (n1 + n2)
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)) if p_pool not in (0, 1) else np.nan
    z = (x1 / n1 - x2 / n2) / se if se and np.isfinite(se) and se > 0 else np.nan
    p = 2 * (1 - stats.norm.cdf(abs(z))) if np.isfinite(z) else np.nan
    return {"z_stat": float(z) if np.isfinite(z) else None, "p_value": float(p) if np.isfinite(p) else None}


def add_next_window_persists(df: pd.DataFrame) -> pd.DataFrame:
    """Adds `persists_next` = whether THIS pair's NEXT rolling window (chronologically, by
    window_start) still has pvalue < PVALUE_COINT_CUTOFF -- the outcome every predictor below is
    tested against. Rows for a pair's LAST window (no next observation) get NaN and must be
    dropped before testing, not treated as a negative outcome. Causal by construction: only ever
    looks at whether a FUTURE window persists, given information available at the CURRENT window
    -- exactly the shape a live trading signal would need, not a lookahead artifact."""
    df = df.sort_values(["symbol_a", "symbol_b", "window_start"]).copy()
    g = df.groupby(["symbol_a", "symbol_b"], sort=False)
    next_pvalue = g["pvalue"].shift(-1)
    # Stored as float (1.0/0.0/NaN), not bool -- a bool dtype column can't hold NaN for the
    # last-window-per-pair case (real bug hit live: assigning np.nan into a bool Series raises
    # TypeError), and downstream .sum()/.notna() both work identically on float 1.0/0.0/NaN.
    df["persists_next"] = np.where(next_pvalue.isna(), np.nan,
                                    (next_pvalue < PVALUE_COINT_CUTOFF).astype(float))
    return df


def add_rolling_z(df: pd.DataFrame, z_window: int) -> pd.Series:
    """Causal rolling z-score of coint_strength at a given window size -- same
    GroupBy.rolling() convention Phase 1b's builder uses (not .transform(lambda...), the
    anti-pattern class that has bitten this project's own scripts twice already), recomputed
    here per z_window value since only z_window=10 is baked into the on-disk series."""
    g = df.groupby(["symbol_a", "symbol_b"], sort=False)["coint_strength"]
    roll = g.rolling(z_window, min_periods=max(2, z_window // 2))
    mean = roll.mean().reset_index(level=[0, 1], drop=True)
    std = roll.std(ddof=1).reset_index(level=[0, 1], drop=True)
    return (df["coint_strength"] - mean) / std


def evaluate_z_signal(df: pd.DataFrame, z_window: int, z_threshold: float) -> dict:
    z = add_rolling_z(df, z_window)
    valid = df["persists_next"].notna() & z.notna()
    signal_on = valid & (z >= z_threshold)
    baseline = valid  # unconditional rate across every row with a defined outcome, not a
    # hand-picked "off" group -- WITH vs. the true population baseline, not WITH vs. WITHOUT-
    # cherry-picked, avoiding an inflated apparent effect from a biased comparison group.
    n_signal, x_signal = int(signal_on.sum()), int(df.loc[signal_on, "persists_next"].sum())
    n_base, x_base = int(baseline.sum()), int(df.loc[baseline, "persists_next"].sum())
    test = two_proportion_z_test(x_signal, n_signal, x_base, n_base)
    return {
        "predictor": "coint_strength_z", "z_window": z_window, "threshold": z_threshold,
        "n_signal": n_signal, "signal_persist_rate": x_signal / n_signal if n_signal else np.nan,
        "n_baseline": n_base, "baseline_persist_rate": x_base / n_base if n_base else np.nan,
        **test,
    }


def evaluate_decay_signal(df: pd.DataFrame) -> dict:
    valid = df["persists_next"].notna() & df["coint_decay_rate"].notna()
    weakening = valid & (df["coint_decay_rate"] < 0)
    baseline = valid
    n_weak, x_weak = int(weakening.sum()), int(df.loc[weakening, "persists_next"].sum())
    n_base, x_base = int(baseline.sum()), int(df.loc[baseline, "persists_next"].sum())
    test = two_proportion_z_test(x_weak, n_weak, x_base, n_base)
    return {
        "predictor": "coint_decay_rate<0", "z_window": None, "threshold": None,
        "n_signal": n_weak, "signal_persist_rate": x_weak / n_weak if n_weak else np.nan,
        "n_baseline": n_base, "baseline_persist_rate": x_base / n_base if n_base else np.nan,
        **test,
    }


def main():
    _setup_logging()
    log.info("=== coint_decay_rate_signal_test.py: does coint_strength_z / coint_decay_rate "
              "predict next-window cointegration persistence? WITH/WITHOUT comparison arms, "
              "not a single fixed design ===")
    df = pd.read_parquet(_SERIES_PATH)
    log.info(f"Loaded {len(df)} rows, {df.groupby(['symbol_a', 'symbol_b']).ngroups} pairs.")
    df = add_next_window_persists(df)
    n_defined = int(df["persists_next"].notna().sum())
    log.info(f"{n_defined} rows have a defined next-window outcome "
             f"(excludes each pair's last window, which has no next observation).")

    rows = []
    for zw in Z_WINDOWS:
        for thr in Z_THRESHOLDS:
            r = evaluate_z_signal(df, zw, thr)
            rows.append(r)
            log.info(f"  z_window={zw:>2} threshold={thr:>3.1f}: n_signal={r['n_signal']:>7} "
                      f"persist_rate={r['signal_persist_rate']:.4f} vs baseline "
                      f"{r['baseline_persist_rate']:.4f} (n={r['n_baseline']}), "
                      f"z={r['z_stat']}, p={r['p_value']}")

    r_decay = evaluate_decay_signal(df)
    rows.append(r_decay)
    log.info(f"  decay_rate<0: n_signal={r_decay['n_signal']:>7} "
              f"persist_rate={r_decay['signal_persist_rate']:.4f} vs baseline "
              f"{r_decay['baseline_persist_rate']:.4f} (n={r_decay['n_baseline']}), "
              f"z={r_decay['z_stat']}, p={r_decay['p_value']}")

    out = pd.DataFrame(rows)
    out.to_parquet(_OUT_PATH)
    log.info(f"Saved -> {_OUT_PATH}")
    log.info("coint_decay_rate_signal_test.py complete")


if __name__ == "__main__":
    main()
