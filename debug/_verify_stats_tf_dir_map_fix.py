# =============================================================================
# Verify: stats.py's _TF_DIR_MAP is a single source of truth (DataStore._TF_SAFE),
# not two independently-drifted copies (found 2026-09-12 timeframe-label audit).
#
# Before the fix: _TF_DIR_MAP keyed "1d" (lowercase) instead of WRDS's real "1D"
# label, and mapped "1W"->"1W"/"1M"->"1M" instead of the real on-disk "7D"->
# "7day"/"1M"->"1mo", with "3M"/"6M" missing entirely -- run_robust_hedge_ratios()
# silently returned NaN beta_huber/beta_mm for every "1D"/"7D"/"3M"/"6M" pair
# because _load_spread_series()'s dir_prefix lookup missed the real
# output/results/{1day,7day,3mo,6mo}/ directories.
#
# This is a real-data regression check, not a synthetic one: run_robust_hedge_
# ratios needs an actual spread_series_*.parquet on disk, which only exists
# post-analysis.py run. Synthetic ground truth would need to fake that file
# structure without proving anything about the real on-disk convention this
# bug was about.
# =============================================================================
import glob
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import DataStore
import stats

checks = []


def check(name, cond, detail=""):
    checks.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


# 1. Single source of truth, no drift possible.
check("tf_dir_map.is_datastore_tf_safe", stats._TF_DIR_MAP is DataStore._TF_SAFE)

# 2. Every canonical WRDS-primary-or-coarser label resolves to the real,
#    already-confirmed-to-exist output/results/ directory name.
expected = {"1D": "1day", "7D": "7day", "1M": "1mo", "3M": "3mo", "6M": "6mo"}
for tf, want in expected.items():
    got = stats._TF_DIR_MAP.get(tf)
    check(f"tf_dir_map[{tf!r}]", got == want, f"got={got!r} want={want!r}")

# 3. Real-data regression: pick any real 1D pair with a cached spread series
#    and confirm run_robust_hedge_ratios() no longer returns NaN purely from a
#    directory-resolution miss (some NaN is expected on genuinely thin data --
#    the check is that it's not NaN FOR THE MECHANICAL REASON this bug caused,
#    i.e. that the spread file is actually found and read at all).
# Before the fix, EVERY "1D" pair's spread file lookup missed (dir_prefix
# resolved to the literal string "1D", but the real directory is "1day"),
# so beta_huber/beta_mm were NaN for 100% of WRDS-daily pairs regardless of
# the underlying data. Post-fix, the file is found and read -- beta_huber may
# still legitimately be NaN for some individual pairs for unrelated numerical
# reasons (HuberRegressor non-convergence, degenerate spread variance), but
# it must not be NaN for ALL of them purely from a missing file.
found_and_read = False
pairs_1d = pd.read_parquet("output/results/1day/pairs.parquet")
for _, row in pairs_1d.head(15).iterrows():
    pairs_df = pd.DataFrame([{"symbol_a": row["symbol_a"], "symbol_b": row["symbol_b"], "tf_label": "1D"}])
    result = stats.run_robust_hedge_ratios(pairs_df)
    if len(result) and pd.notna(result.iloc[0].get("beta_huber", float("nan"))):
        found_and_read = True
        break

check("real_1D_pair.spread_series_found_and_readable", found_and_read,
      "(no real 1D manifest pair with a readable spread_series file was found "
      "to test against -- inconclusive, not a failure of the fix itself)" if not found_and_read else "")

n_pass = sum(1 for _, ok, _ in checks if ok)
print(f"\n{n_pass}/{len(checks)} checks passed")
sys.exit(0 if n_pass == len(checks) else 1)
