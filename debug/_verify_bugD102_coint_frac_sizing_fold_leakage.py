"""
Synthetic verification of BUG-D102: wfa.py::run_wfa's coint_frac_sizing
variant read `pair_row["coint_fraction_rolling"]` -- a static, whole-history
scalar from output/stats/cointegration_tiers.parquet computed OUTSIDE the
fold loop -- so every fold of every variant sized its test-window trades
using the SAME fraction, regardless of that fold's own train/test boundary.
An early fold's trades were sized using a fraction informed by cointegration
windows from later folds, including future ones relative to that fold's own
cutoff.

Fix: read the causal per-bar coint_fraction_rolling_t series (BUG-D101) at
each fold's OWN train-window end bar, falling back to the static scalar only
when the causal column is absent.

Verifies: two folds with well-separated train-window end bars, and a
synthetic coint_fraction_rolling_t series with DISTINCT known values at
each fold's own train-end bar (both different from the static scalar
fallback), produce DIFFERENT `_cfrac` values passed to _run_fold_backtest --
matching each fold's own bar, not the shared static scalar.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import wfa

rng = np.random.default_rng(102)


def main():
    failures = []

    n = 1000
    idx = pd.bdate_range("2018-01-02", periods=n, freq="B")

    # Two folds, expanding-style: fold1 train=[0.00,0.20) test=[0.20,0.50);
    # fold2 train=[0.00,0.50) test=[0.50,0.80) -- matches wfa.py's own
    # FOLD_EXPANDING convention shape, distinct train_e fractions so ti_e
    # differs meaningfully between folds.
    folds = [
        (0.00, 0.20, 0.20, 0.50, "fold1_exp"),
        (0.00, 0.50, 0.50, 0.80, "fold2_exp"),
    ]
    ti_e_fold1 = int(n * 0.20)  # 200
    ti_e_fold2 = int(n * 0.50)  # 500

    cfrac_t = np.full(n, np.nan)
    cfrac_t[:] = np.nan
    # Forward-filled step-style series, like the real expanding_coint_fraction
    # output: distinct plateau values bracketing each fold's own train-end bar.
    cfrac_t[100:ti_e_fold1 + 1] = 0.75
    cfrac_t[ti_e_fold1 + 1:ti_e_fold2 + 1] = 0.30

    spread_df = pd.DataFrame(
        {
            "spread": rng.normal(size=n),
            "coint_fraction_rolling_t": cfrac_t,
        },
        index=idx,
    )

    STATIC_SCALAR = 0.55  # deliberately different from both 0.75 and 0.30

    tiers = pd.DataFrame([{
        "symbol_a": "SYNA", "symbol_b": "SYNB", "tf_label": "1D",
        "coint_fraction_rolling": STATIC_SCALAR,
    }])

    captured = []
    real_run_fold = wfa._run_fold_backtest

    def _capture_run_fold(*args, **kwargs):
        captured.append(kwargs.get("coint_frac"))
        return []

    wfa._load_spread = lambda sym_a, sym_b, tf_label: spread_df
    wfa._run_fold_backtest = _capture_run_fold
    try:
        wfa.run_wfa(folds, "expanding", tiers, storm_flags={"coint_frac_sizing": True})
    finally:
        wfa._run_fold_backtest = real_run_fold

    if len(captured) != 2:
        failures.append(f"expected 2 fold calls, got {len(captured)} — test construction issue")
    else:
        cfrac_fold1, cfrac_fold2 = captured
        if cfrac_fold1 is None or abs(cfrac_fold1 - 0.75) > 1e-9:
            failures.append(f"fold1: coint_frac={cfrac_fold1}, expected 0.75 (fold1's own train-end bar value)")
        if cfrac_fold2 is None or abs(cfrac_fold2 - 0.30) > 1e-9:
            failures.append(f"fold2: coint_frac={cfrac_fold2}, expected 0.30 (fold2's own train-end bar value)")
        if cfrac_fold1 is not None and cfrac_fold2 is not None and abs(cfrac_fold1 - cfrac_fold2) < 1e-9:
            failures.append(f"LEAKAGE BUG: both folds got the SAME coint_frac ({cfrac_fold1}) — not reading per-fold causal value")
        if cfrac_fold1 is not None and abs(cfrac_fold1 - STATIC_SCALAR) < 1e-9:
            failures.append(f"fold1 got the static whole-history scalar ({STATIC_SCALAR}) instead of its own per-bar value")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("BUG-D102 verification passed.")
    print(f"  fold1 (train_end=bar {ti_e_fold1}) coint_frac = {captured[0]:.3f} (expected 0.75)")
    print(f"  fold2 (train_end=bar {ti_e_fold2}) coint_frac = {captured[1]:.3f} (expected 0.30)")
    print(f"  static whole-history scalar (would-be leaked value) = {STATIC_SCALAR}, correctly NOT used for either fold")


if __name__ == "__main__":
    main()
