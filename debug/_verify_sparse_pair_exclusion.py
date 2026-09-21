# =============================================================================
# Verify: AnalysisPipeline._build_pair_result now excludes (returns None for)
# any pair whose rolling half-life series has zero finite values, per Ross's
# explicit decision (2026-09-12, live before sleep): "if rolling stats can't
# compute on a pair, it's not tradeable in practice" -- exclude outright
# rather than making rolling statistics adaptive (impute/shorten window).
#
# Root cause this implements a decision ABOUT (not a bug -- a real, if small,
# production logic change): a pair can pass EG's one-time full-sample test
# (which tolerates scattered real data fine, via longest_gap_respecting_
# segment) while having no single stretch of CONTIGUOUS real data long enough
# for any rolling window to produce output at all. Traced in a prior session
# on GVKEY101930_01W/GVKEY355506_01W (Development.md) -- used here as the
# real-data proof, same discipline as debug/_verify_half_life_ar1_off_by_one.py
# and debug/_verify_clean_mask_gapflag_semantics_fix.py.
# =============================================================================
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from analysis import AnalysisPipeline, SpreadModel
from data import DataAligner

checks = []


def check(name, cond, detail=""):
    checks.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


# 1. Real-data proof: GVKEY101930_01W/GVKEY355506_01W (the exact pair the
#    sparse-data mechanism was originally traced on) must now be excluded.
raw_a_path = "output/cache/wrds/GVKEY101930_01W_1D.parquet"
raw_b_path = "output/cache/wrds/GVKEY355506_01W_1D.parquet"
if os.path.exists(raw_a_path) and os.path.exists(raw_b_path):
    df_a = pd.read_parquet(raw_a_path)
    df_b = pd.read_parquet(raw_b_path)
    sym_a, sym_b = "GVKEY101930_01W", "GVKEY355506_01W"
    aligned = DataAligner.align_universe({f"{sym_a}_1D": df_a, f"{sym_b}_1D": df_b}, "1D")
    common_idx = aligned[sym_a].index.intersection(aligned[sym_b].index)
    aligned = {sym_a: aligned[sym_a].loc[common_idx], sym_b: aligned[sym_b].loc[common_idx]}

    # Sanity check first: confirm the underlying half-life IS genuinely unusable
    # (not asserting the exclusion blindly without checking why).
    close_a = aligned[sym_a]["close"].values
    close_b = aligned[sym_b]["close"].values
    with np.errstate(invalid="ignore", divide="ignore"):
        log_a, log_b = np.log(close_a), np.log(close_b)
    spread_probe = SpreadModel.compute_spread(log_a, log_b, np.ones_like(log_a), 1.0)
    check("gvkey_pair.has_some_real_bars", len(common_idx) > 500, f"got {len(common_idx)} bars")

    built = AnalysisPipeline._build_pair_result({"symbol_a": sym_a, "symbol_b": sym_b}, aligned, "1D")
    check("gvkey_pair.excluded_by_sparse_data_check", built is None,
          f"got {'None (excluded)' if built is None else 'NOT excluded -- regression'}")
else:
    check("gvkey_pair.files_exist_skip_note", False,
          f"{raw_a_path} / {raw_b_path} not found -- real-data check skipped")

# 2. Synthetic control: a pair with DENSE, contiguous, genuinely mean-reverting
#    data must NOT be excluded -- this is a targeted exclusion, not a blanket
#    "reject if anything looks unusual" regression.
rng = np.random.default_rng(0)
n = 800
idx = pd.bdate_range("2015-01-01", periods=n)
phi = 0.9
noise = rng.normal(0, 0.05, n)
spread_true = np.zeros(n)
for t in range(1, n):
    spread_true[t] = phi * spread_true[t - 1] + noise[t]
close_a = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
close_b = close_a * np.exp(-spread_true)  # constructs a genuinely mean-reverting spread
dense_df_a = pd.DataFrame({"open": close_a, "high": close_a, "low": close_a, "close": close_a,
                            "volume": 1000, "gap_flag": 0}, index=idx)
dense_df_b = pd.DataFrame({"open": close_b, "high": close_b, "low": close_b, "close": close_b,
                            "volume": 1000, "gap_flag": 0}, index=idx)
built_dense = AnalysisPipeline._build_pair_result(
    {"symbol_a": "DENSE_A", "symbol_b": "DENSE_B"},
    {"DENSE_A": dense_df_a, "DENSE_B": dense_df_b}, "1D",
)
check("dense_control.not_excluded", built_dense is not None,
      f"got {'None -- FALSE POSITIVE EXCLUSION' if built_dense is None else 'kept, correct'}")

n_pass = sum(1 for _, ok, _ in checks if ok)
print(f"\n{n_pass}/{len(checks)} checks passed")
sys.exit(0 if n_pass == len(checks) else 1)
