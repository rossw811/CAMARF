"""
PIT-pool default for ml.py (Ross 2026-10-16; the backtest.py half is debug/_verify_backtest_pit_pool_default.py).
Before: ml.py trained on output/results/*/pairs.parquet (pairs selected on their whole history) and, wherever a per-bar
value was missing, used the pair's whole-history scalar (Hurst, coint fraction, half-life slope, mean-reversion speed,
hedge drift; half-life for the label horizon); transfer entropy was always the whole-history pair statistic.
Checks:
  1. strict (default): missing per-bar features are NaN (the train-median imputer fills them), never the scalar;
  2. strict: no per-bar hedge series -> hedge drift NaN, not the whole-history OLS/Kalman gap;
  3. strict: no per-bar half-life at the entry -> example dropped (the horizon would come from the whole history);
  4. strict: transfer entropy (a whole-history pair statistic) is NaN;
  5. descriptive (strict=False) keeps the old fallbacks -- the comparison arm stays reproducible;
  6. pair source: default k2 pool, --pool k1, --full-sample-descriptive -> pairs.parquet with a NON-canonical model
     directory, so a descriptive model can never become the backtest's Layer-2 gate.
Run: python debug/_verify_ml_pit_pool_default.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import ml
from config import Config

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def series(hl_nan_at_entry=False):
    n = 400
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    z = np.full(n, 0.3)
    z[100] = 2.0
    hl = np.full(n, 20.0)
    if hl_nan_at_entry:
        hl[100] = np.nan
    return pd.DataFrame({"z_rolling": z, "spread": np.zeros(n), "half_life_rolling": hl}, index=idx)


ROW = pd.Series({"hurst_rs": 0.4, "coint_fraction_rolling": 0.8, "half_life_trend_slope": 0.01,
                 "mean_reversion_speed": 0.1, "hedge_ratio_ols": 1.0, "hedge_ratio_kalman_mean": 1.5,
                 "half_life_rolling": 20.0, "te_directional_diff": 0.2, "te_significance": 0.9})


def build(strict, **kw):
    return ml._build_examples_for_pair("A", "B", "1h", ROW, ml.MLRunSummary(), series=series(**kw), strict=strict)


def main():
    try:
        ev = build(True)
        e = ev[0] if ev else None
        check("strict_features_nan_not_scalar", e is not None and all(
            pd.isna(getattr(e, f)) for f in ("hurst_exponent", "coint_fraction_rolling", "half_life_trend_slope",
                                              "mean_reversion_speed")),
              "" if e is None else f"hurst={e.hurst_exponent} cfrac={e.coint_fraction_rolling}")
        check("strict_hedge_drift_nan", e is not None and pd.isna(e.hedge_ratio_drift),
              "" if e is None else f"{e.hedge_ratio_drift}")
        check("strict_transfer_entropy_nan", e is not None and pd.isna(e.te_directional_diff)
              and pd.isna(e.te_significance))
        check("strict_drops_example_without_pit_half_life", len(build(True, hl_nan_at_entry=True)) == 0)
        d = build(False)
        d0 = d[0] if d else None
        check("descriptive_keeps_old_fallbacks", d0 is not None and d0.hurst_exponent == 0.4
              and abs(d0.hedge_ratio_drift - 0.5) < 1e-12 and len(build(False, hl_nan_at_entry=True)) == 1)
    except TypeError as e:
        check("build_examples_accepts_strict", False, str(e))

    try:
        row_late = ROW.copy()
        row_late["eligible_from"] = pd.Timestamp("2024-01-10")    # after the only entry (2024-01-05 04:00)
        ev_s = ml._build_examples_for_pair("A", "B", "1h", row_late, ml.MLRunSummary(), series=series(), strict=True)
        ev_d = ml._build_examples_for_pair("A", "B", "1h", row_late, ml.MLRunSummary(), series=series(), strict=False)
        check("strict_no_example_before_eligible_from", len(ev_s) == 0 and len(ev_d) == 1,
              f"strict {len(ev_s)}, descriptive {len(ev_d)}")
    except TypeError as e:
        check("eligible_from_supported", False, str(e))
    try:
        s = ml.resolve_pair_source(pool="k2", full_sample_descriptive=False, pit_safe=False)
        check("default_k2_pool", s["path"] == Config.DATA.PIT_POOL_PATHS["k2"] and s["strict"] and s["canonical_model"],
              f"{s}")
        from config import resolve_pit_pair_source
        check("ml_uses_shared_resolver", ml.resolve_pair_source(pool="k1") == resolve_pit_pair_source(pool="k1"))
        s = ml.resolve_pair_source(pool="k1", full_sample_descriptive=False, pit_safe=False)
        check("k1_pool", s["path"] == Config.DATA.PIT_POOL_PATHS["k1"] and s["strict"], f"{s}")
        s = ml.resolve_pair_source(pool="k2", full_sample_descriptive=True, pit_safe=False)
        check("descriptive_non_canonical_model", s["path"] is None and not s["strict"] and not s["canonical_model"],
              f"{s}")
        d_dir = ml.model_dir_for(ml.resolve_pair_source(full_sample_descriptive=True))
        k_dir = ml.model_dir_for(ml.resolve_pair_source())
        check("descriptive_model_saved_away_from_gate", d_dir.endswith(os.path.join("ml", "descriptive"))
              and k_dir.endswith(os.path.join("output", "ml")), f"{d_dir} | {k_dir}")
    except AttributeError as e:
        check("resolve_pair_source_exists", False, str(e))

    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
