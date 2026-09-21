# =============================================================================
# Verify: SpreadModel.half_life_ar1's redundant post-slice length check was an
# off-by-one bug, silently requiring 31 real points instead of the documented/
# intended minimum of 30 (Config.ANALYSIS.OU_WINDOW_MIN_BARS) -- found
# 2026-09-12 while root-causing the disclosed half_life_rolling-100%-NaN bug.
#
# Real-data proof: KVUE/KMB at 3m (output/results/3min/spread_series_KVUE_
# KMB.parquet) is a genuinely strong, currently-confirmed pair (coint_pvalue_
# adjusted=0.0023, coint_fraction_rolling=0.877, half_life_expanding=2.75
# finite/real) with 4,781 real (clean_mask-passing) bars -- clean_mask makes
# ZERO difference here (this pair has only NONE/DATA_GAP flags, no FILL/
# NO_ACTIVITY/HALT/SPARSE to differ on), yet half_life_rolling was 100% NaN.
# _adaptive_window(hl_full=2.75, mult=8, min_bars=30, max_bars=252) clips to
# exactly 30 (8*2.75=22, floored up to 30) -- the off-by-one bug guarantees
# NaN at exactly this window size, independent of clean_mask, independent of
# data sparsity, independent of the true AR(1) coefficient.
# =============================================================================
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from analysis import SpreadModel

checks = []


def check(name, cond, detail=""):
    checks.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


# 1. Synthetic ground truth: a clean AR(1) process with a KNOWN phi, exactly
#    30 points -- half_life_ar1 must return a finite, correct half-life, not
#    NaN, at exactly the documented minimum window size.
rng = np.random.default_rng(0)
phi_true = 0.85
n = 30
s = np.zeros(n)
for t in range(1, n):
    s[t] = phi_true * s[t - 1] + rng.normal(0, 0.1)
hl = SpreadModel.half_life_ar1(s)
expected_hl = -np.log(2) / np.log(phi_true)
check("synthetic.exactly_30_points_not_nan", np.isfinite(hl), f"got {hl}")
check("synthetic.exactly_30_points_reasonably_close",
      np.isfinite(hl) and abs(hl - expected_hl) < 3.0,
      f"got {hl}, expected ~{expected_hl:.2f} (noisy single-draw, loose tolerance)")

# 2. 29 points (genuinely below the documented floor) must still correctly
#    return NaN -- the fix must not simply delete the length guard entirely.
hl_29 = SpreadModel.half_life_ar1(s[:29])
check("synthetic.29_points_still_nan", np.isnan(hl_29), f"got {hl_29}")

# 3. Real-data regression: KVUE/KMB's rolling_half_life at the real window
#    size (30) production would actually use must produce SOME finite values,
#    not 100% NaN, given 4,781 real compacted bars and a clearly mean-
#    reverting process (hl_full=2.75, phi values sampled directly in the
#    investigation were 0.56-1.04, mostly well inside (0,1)).
path = "output/results/3min/spread_series_KVUE_KMB.parquet"
if os.path.exists(path):
    df = pd.read_parquet(path)
    spread = df["spread"].values
    clean_mask = (df["gap_flag_a"].values == 0) & (df["gap_flag_b"].values == 0)
    real_pos = np.flatnonzero(clean_mask & np.isfinite(spread))
    spread_real = spread[real_pos]
    hl_full = SpreadModel.half_life_ar1(spread_real)
    check("kvue_kmb.hl_full_is_finite", np.isfinite(hl_full), f"got {hl_full}")
    hl_roll = SpreadModel.rolling_half_life(spread_real, window=30, step=21)
    n_finite = np.isfinite(hl_roll).sum()
    check("kvue_kmb.rolling_half_life_not_100pct_nan", n_finite > 0,
          f"{n_finite}/{len(hl_roll)} finite")
else:
    check("kvue_kmb.file_exists_skip_note", False,
          f"{path} not found -- real-data check skipped, only synthetic checks ran")

n_pass = sum(1 for _, ok, _ in checks if ok)
print(f"\n{n_pass}/{len(checks)} checks passed")
sys.exit(0 if n_pass == len(checks) else 1)
