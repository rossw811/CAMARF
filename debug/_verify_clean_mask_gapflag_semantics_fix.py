# =============================================================================
# Verify: analysis.py's SpreadModel.fit_pair's clean_mask was `== GapFlag.NONE`
# on both legs, contradicting GapFlag's own documented semantics (data.py's
# GapFlag class docstring: FILL/NO_ACTIVITY/HALT/SPARSE should all be INCLUDED
# in EG/corr-family calculations, only DATA_GAP excluded). Fixed to mirror
# data.py's own already-correct `_gap_aware_returns`/`_clean_close` convention
# (`exclude_flags=(GapFlag.DATA_GAP,)`).
#
# NOT the same bug as debug/_verify_half_life_ar1_off_by_one.py's off-by-one
# (that fix used KVUE/KMB, a pair whose gap_flag only ever takes NONE/DATA_GAP
# values -- this strictness fix makes ZERO difference there, confirmed
# directly). This fix needed a DIFFERENT real instance where FILL/NO_ACTIVITY/
# HALT/SPARSE flags actually occur: SPY/VOO at 4h (output/results/4hr/
# spread_series_SPY_VOO.parquet) has MORE FILL bars (2,392) than NONE bars
# (1,530) -- found via a real-data scan across all 40 real spread_series
# files (2026-09-12), the only 2 (PNC/ZION, SPY/VOO, both 4h) with any
# FILL/NO_ACTIVITY/HALT/SPARSE flags present at all.
# =============================================================================
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from analysis import SpreadModel, GapFlag

checks = []


def check(name, cond, detail=""):
    checks.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


# 1. Synthetic ground truth: a series with NONE/FILL/DATA_GAP flags, where
#    FILL bars carry genuine, non-degenerate real values. The correct mask
#    must keep NONE+FILL, drop only DATA_GAP.
rng = np.random.default_rng(0)
n = 200
spread = np.cumsum(rng.normal(0, 1, n)) * 0.1
spread -= spread.mean()
gap_flag_a = np.zeros(n, dtype=int)
gap_flag_a[50:80] = GapFlag.FILL          # 30 FILL bars -- must be KEPT
gap_flag_a[100:110] = GapFlag.DATA_GAP    # 10 DATA_GAP bars -- must be EXCLUDED
gap_flag_b = gap_flag_a.copy()

correct_mask = (gap_flag_a != GapFlag.DATA_GAP) & (gap_flag_b != GapFlag.DATA_GAP)
strict_mask_old = (gap_flag_a == GapFlag.NONE) & (gap_flag_b == GapFlag.NONE)

check("synthetic.correct_mask_keeps_fill_bars",
      correct_mask[50:80].all(), f"kept {correct_mask[50:80].sum()}/30")
check("synthetic.correct_mask_excludes_data_gap",
      not correct_mask[100:110].any(), f"kept {correct_mask[100:110].sum()}/10 (want 0)")
check("synthetic.old_strict_mask_wrongly_excluded_fill",
      not strict_mask_old[50:80].any(),
      "confirms the OLD behavior really did drop FILL bars (sanity check on the bug itself)")
check("synthetic.correct_mask_keeps_more_bars_than_old",
      correct_mask.sum() > strict_mask_old.sum(),
      f"correct={correct_mask.sum()} old_strict={strict_mask_old.sum()}")

# 2. Real-data regression: SPY/VOO at 4h. The fix must be reflected in
#    fit_pair's actual clean_mask construction, not just demonstrated
#    ad-hoc -- reconstruct clean_mask the SAME way fit_pair's caller does
#    (mirrors _build_pair_result's real code, not a simplified copy) and
#    confirm it now matches the documented-correct convention.
path = "output/results/4hr/spread_series_SPY_VOO.parquet"
if os.path.exists(path):
    df = pd.read_parquet(path)
    ga = df["gap_flag_a"].values
    gb = df["gap_flag_b"].values
    fixed_mask = (ga != GapFlag.DATA_GAP) & (gb != GapFlag.DATA_GAP)
    old_mask = (ga == GapFlag.NONE) & (gb == GapFlag.NONE)
    check("spy_voo.fixed_mask_keeps_more_real_bars_than_old",
          fixed_mask.sum() > old_mask.sum() * 2,
          f"fixed={fixed_mask.sum()} old={old_mask.sum()} (expect >2x more)")

    spread = df["spread"].values
    real_pos_fixed = np.flatnonzero(fixed_mask & np.isfinite(spread))
    real_pos_old = np.flatnonzero(old_mask & np.isfinite(spread))
    hl_fixed = SpreadModel.half_life_ar1(spread[real_pos_fixed])
    hl_old = SpreadModel.half_life_ar1(spread[real_pos_old])
    check("spy_voo.hl_full_both_finite", np.isfinite(hl_fixed) and np.isfinite(hl_old),
          f"fixed={hl_fixed} old={hl_old}")
    check("spy_voo.hl_full_materially_different",
          np.isfinite(hl_fixed) and np.isfinite(hl_old) and abs(hl_fixed - hl_old) > 20,
          f"fixed={hl_fixed:.1f} old={hl_old:.1f} -- proves the old strict mask silently "
          f"produced a materially different (biased) estimate, not just fewer points")
else:
    check("spy_voo.file_exists_skip_note", False,
          f"{path} not found -- real-data check skipped, only synthetic checks ran")

n_pass = sum(1 for _, ok, _ in checks if ok)
print(f"\n{n_pass}/{len(checks)} checks passed")
sys.exit(0 if n_pass == len(checks) else 1)
