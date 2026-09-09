"""
debug/_verify_crisis_regime_correlation_diagnostic.py -- synthetic checks
for research/crisis_regime_correlation_diagnostic.py, run BEFORE trusting
it against real Tier 3 data (per this project's standing convention).

episodic_bhfdr_confirm() itself is already verified elsewhere and reused,
not reimplemented, here. These checks target this script's own new logic:
point-in-time-safe regime lookup, per-pair table construction (first
window, confirmation, reappearance-in-a-different-regime), and the
two-proportion z-test.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.crisis_regime_correlation_diagnostic import (
    _nearest_regime, build_pair_level_table, summarize,
)

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


print("Check 1: _nearest_regime never uses a value from AFTER the query date (PIT safety)")
vix_regime = pd.Series(
    ["calm", "crisis", "calm"],
    index=pd.DatetimeIndex(["2020-01-01", "2020-03-01", "2020-06-01"]),
)
# Query a date between the crisis point and the later calm point -- must
# return "crisis" (the most recent value ON OR BEFORE the query date), NOT
# "calm" (which would require looking into the future).
result = _nearest_regime(vix_regime, pd.Timestamp("2020-04-15"))
check("returns the most recent PAST regime, not a future one", result == "crisis")

result_before_any_data = _nearest_regime(vix_regime, pd.Timestamp("2019-01-01"))
check("returns NaN when queried before any VIX data exists (no fabricated regime)",
      pd.isna(result_before_any_data))

print("Check 2: build_pair_level_table -- first window, confirmation, and reappearance logic")
# Pair AAA/BBB: qualifies in 3 windows, all crisis-dated, 2/3 FDR-rejected (should confirm).
# Pair CCC/DDD: qualifies in 1 window only, calm-dated, not rejected (should not confirm,
#   and by construction cannot "reappear in a different regime" -- only 1 window ever).
# Pair EEE/FFF: qualifies first in a crisis window, then again later in a calm window --
#   should show reappears_in_different_regime=True regardless of confirmation outcome.
windows_df = pd.DataFrame([
    {"symbol_a": "AAA", "symbol_b": "BBB", "window_start": pd.Timestamp("2007-01-01"),
     "pvalue": 0.0001, "window_end_date": pd.Timestamp("2008-06-01")},
    {"symbol_a": "AAA", "symbol_b": "BBB", "window_start": pd.Timestamp("2008-01-01"),
     "pvalue": 0.0002, "window_end_date": pd.Timestamp("2009-06-01")},
    {"symbol_a": "AAA", "symbol_b": "BBB", "window_start": pd.Timestamp("2008-06-01"),
     "pvalue": 0.9, "window_end_date": pd.Timestamp("2009-12-01")},
    {"symbol_a": "CCC", "symbol_b": "DDD", "window_start": pd.Timestamp("2015-01-01"),
     "pvalue": 0.8, "window_end_date": pd.Timestamp("2016-01-01")},
    {"symbol_a": "EEE", "symbol_b": "FFF", "window_start": pd.Timestamp("2008-01-01"),
     "pvalue": 0.0001, "window_end_date": pd.Timestamp("2008-09-01")},
    {"symbol_a": "EEE", "symbol_b": "FFF", "window_start": pd.Timestamp("2014-01-01"),
     "pvalue": 0.9, "window_end_date": pd.Timestamp("2015-01-01")},
])
vix_lookup = pd.Series(
    ["crisis", "crisis", "calm", "calm"],
    index=pd.DatetimeIndex(["2008-01-01", "2009-01-01", "2013-01-01", "2016-01-01"]),
)
table = build_pair_level_table(windows_df, vix_lookup, alpha=0.10)
table_by_pair = {frozenset((r.symbol_a, r.symbol_b)): r for r in table.itertuples()}

r_ab = table_by_pair[frozenset(("AAA", "BBB"))]
check("AAA/BBB first_window_end_date is the EARLIEST of its 3 windows",
      r_ab.first_window_end_date == pd.Timestamp("2008-06-01"))
check("AAA/BBB first_regime is crisis (VIX as-of 2008-06-01)", r_ab.first_regime == "crisis")
check("AAA/BBB is confirmed (2/3 windows FDR-rejected at alpha=0.10)", r_ab.confirmed == True)

r_cd = table_by_pair[frozenset(("CCC", "DDD"))]
check("CCC/DDD is NOT confirmed (single non-significant window)", r_cd.confirmed == False)
check("CCC/DDD does not reappear in a different regime (only 1 window ever)",
      r_cd.reappears_in_different_regime == False)

r_ef = table_by_pair[frozenset(("EEE", "FFF"))]
check("EEE/FFF first_regime is crisis", r_ef.first_regime == "crisis")
check("EEE/FFF DOES reappear in a different (calm) regime later",
      r_ef.reappears_in_different_regime == True)

print("Check 3: summarize() two-proportion z-test on a known synthetic split")
# 10 crisis-first pairs, 8 confirmed; 10 calm-first pairs, 2 confirmed -- a real, large gap
# that should register as statistically significant (p < 0.05).
synthetic_table = pd.DataFrame({
    "first_regime": ["crisis"] * 10 + ["calm"] * 10,
    "confirmed": [True] * 8 + [False] * 2 + [True] * 2 + [False] * 8,
    "episodic_fraction_fdr": [0.5] * 20,
    "reappears_in_different_regime": [False] * 20,
})
summary = summarize(synthetic_table)
cvc = summary["crisis_vs_calm_confirmation_rate"]
check("crisis rate computed correctly (8/10 = 0.8)", abs(cvc["crisis_rate"] - 0.8) < 1e-9)
check("calm rate computed correctly (2/10 = 0.2)", abs(cvc["calm_rate"] - 0.2) < 1e-9)
check("a real 0.6 rate gap registers as statistically significant (p < 0.05)",
      cvc["p_value"] is not None and cvc["p_value"] < 0.05)

print("Check 4: summarize() handles the degenerate case (no crisis or no calm pairs) without crashing")
degenerate_table = pd.DataFrame({
    "first_regime": ["calm"] * 5,
    "confirmed": [True, False, True, False, True],
    "episodic_fraction_fdr": [0.5] * 5,
    "reappears_in_different_regime": [False] * 5,
})
degenerate_summary = summarize(degenerate_table)
check("no crash, and crisis_vs_calm comparison is explicitly None (not a fabricated result)",
      degenerate_summary["crisis_vs_calm_confirmation_rate"] is None)

print("Check 5: summarize() reappearance-rate two-proportion z-test (added 2026-09-02, "
      "was previously descriptive-only)")
# 10 crisis-first pairs, 9 reappear in a different regime; 10 calm-first, 2 reappear -- a real
# gap that should register as statistically significant, mirroring check 3's confirmation-rate
# test but on the reappearance column instead.
reappear_table = pd.DataFrame({
    "first_regime": ["crisis"] * 10 + ["calm"] * 10,
    "confirmed": [False] * 20,
    "episodic_fraction_fdr": [0.0] * 20,
    "reappears_in_different_regime": [True] * 9 + [False] * 1 + [True] * 2 + [False] * 8,
})
reappear_summary = summarize(reappear_table)
rvc = reappear_summary["crisis_vs_calm_reappearance_rate"]
check("crisis reappearance rate computed correctly (9/10 = 0.9)",
      abs(rvc["crisis_reappearance_rate"] - 0.9) < 1e-9)
check("calm reappearance rate computed correctly (2/10 = 0.2)",
      abs(rvc["calm_reappearance_rate"] - 0.2) < 1e-9)
check("a real 0.7 reappearance-rate gap registers as statistically significant (p < 0.05)",
      rvc["p_value"] is not None and rvc["p_value"] < 0.05)

print("Check 6: summarize() episodic_fraction_fdr Mann-Whitney U test (added 2026-09-02, "
      "was previously descriptive-only)")
# Among CONFIRMED pairs only: crisis-confirmed pairs cluster high (0.7-0.9), calm-confirmed
# pairs cluster low (0.1-0.3) -- a real separation a rank test should catch as significant.
strength_table = pd.DataFrame({
    "first_regime": ["crisis"] * 8 + ["calm"] * 8,
    "confirmed": [True] * 8 + [True] * 8,
    "episodic_fraction_fdr": [0.7, 0.75, 0.8, 0.85, 0.9, 0.72, 0.78, 0.88]
                            + [0.1, 0.15, 0.2, 0.25, 0.3, 0.12, 0.18, 0.28],
    "reappears_in_different_regime": [False] * 16,
})
strength_summary = summarize(strength_table)
evc = strength_summary["crisis_vs_calm_episodic_fraction_fdr"]
check("crisis_n_confirmed/calm_n_confirmed counted correctly (8 and 8)",
      evc["crisis_n_confirmed"] == 8 and evc["calm_n_confirmed"] == 8)
check("crisis mean episodic_fraction_fdr is higher than calm's, matching the constructed gap",
      evc["crisis_mean"] > evc["calm_mean"])
check("a real, total separation between groups registers as statistically significant (p < 0.05)",
      evc["p_value"] is not None and evc["p_value"] < 0.05)

print("Check 7: summarize() non-monotonicity disclosure across calm->normal->elevated->crisis")
# Deliberately non-monotonic: elevated's confirmation rate dips BELOW calm's, matching the
# real 2026-09-02 corrected-scale pattern this check is guarding against silently smoothing over.
non_monotonic_table = pd.DataFrame({
    "first_regime": ["calm"] * 100 + ["normal"] * 100 + ["elevated"] * 100 + ["crisis"] * 100,
    "confirmed": ([True] * 15 + [False] * 85)      # calm: 15%
               + ([True] * 14 + [False] * 86)      # normal: 14%
               + ([True] * 10 + [False] * 90)      # elevated: 10% -- DIPS below calm/normal
               + ([True] * 25 + [False] * 75),     # crisis: 25%
    "episodic_fraction_fdr": [0.0] * 400,
    "reappears_in_different_regime": [False] * 400,
})
non_monotonic_summary = summarize(non_monotonic_table)
check("non-monotonic confirmation-rate pattern is correctly flagged as NOT monotonic",
      non_monotonic_summary["confirmation_rate_monotonic_across_regime_severity"] is False)

monotonic_table = pd.DataFrame({
    "first_regime": ["calm"] * 100 + ["normal"] * 100 + ["elevated"] * 100 + ["crisis"] * 100,
    "confirmed": ([True] * 10 + [False] * 90)
               + ([True] * 15 + [False] * 85)
               + ([True] * 20 + [False] * 80)
               + ([True] * 25 + [False] * 75),     # a genuine clean gradient, for contrast
    "episodic_fraction_fdr": [0.0] * 400,
    "reappears_in_different_regime": [False] * 400,
})
monotonic_summary = summarize(monotonic_table)
check("a genuine clean gradient is correctly flagged as monotonic",
      monotonic_summary["confirmation_rate_monotonic_across_regime_severity"] is True)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
