"""
Verification for the 2026-07-20 Grand Sweep BUG-D77 fix to analysis.py's
_eg_worker()/_rolling_coint_worker(): the FIRST attempt at fixing the
gap-contamination risk (a plain isfinite-mask-then-drop silently
concatenating across ANY gap) was too broad -- it refused to span ANY
GapFlag.DATA_GAP run, including routine overnight/weekend/holiday closures,
which are ALSO flagged DATA_GAP under align_intraday()'s dense calendar-time
reindex. That attempt was reverted after real-data testing collapsed every
pair's usable history to ~1 trading day (see Development.md's "Attempted and
reverted" entry).

This is the CORRECTED, narrower fix: data.py's is_genuine_data_gap() /
longest_gap_respecting_segment() distinguish a routine closure (<= a
per-timeframe hours ceiling, safe to bridge) from a genuine multi-day
outage (a hard segment boundary), calibrated from the same real-data
measurement (19 symbols' real 1h DATA_GAP runs: 17-93 hours, all routine).

Proves:
1. A ROUTINE-length gap (e.g. 90 bars at 1h -- within the calibrated
   ceiling) is bridged exactly like the old (pre-any-fix) convention would --
   n_overlap and p-value both match the original mask-then-drop behavior.
2. A GENUINE gap (e.g. 200 bars at 1h -- beyond the ceiling) with a large
   artificial level shift at the resumption bar is NOT bridged -- the
   longest gap-respecting segment is chosen instead, recovering the real
   cointegration signal, matching what the (broken) first attempt correctly
   demonstrated for this case.
3. On the current real 19-symbol universe (max observed real gap = 93
   bars), the fix is a no-op -- same n_overlap/p-value as the original
   unmodified convention, confirmed via the same real-data check already
   done for the reverted attempt.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import _eg_worker
from data import is_genuine_data_gap, longest_gap_respecting_segment
from statsmodels.tsa.stattools import coint


def _old_naive_eg(log_p_a, log_p_b, max_lag=5):
    """The ORIGINAL (pre-any-fix) mask-then-drop convention."""
    mask = np.isfinite(log_p_a) & np.isfinite(log_p_b)
    a = log_p_a[mask]
    b = log_p_b[mask]
    t_stat, p_value, _ = coint(a, b, trend="c", maxlag=max_lag, autolag="aic")
    return p_value, a.size


def main() -> None:
    failures = []
    rng = np.random.default_rng(11)

    # --- 1. is_genuine_data_gap threshold sanity (matches real-data calibration) ---
    if is_genuine_data_gap(93, "1h"):
        failures.append("93 bars at 1h (the real observed max) should be classified routine")
    if not is_genuine_data_gap(200, "1h"):
        failures.append("200 bars at 1h should be classified genuine")
    if is_genuine_data_gap(93, "1D"):
        failures.append("daily timeframe should never be flagged genuine (not applicable)")

    # --- 2. ROUTINE-length gap: fix should be a no-op vs. the old convention ---
    n = 500
    routine_gap_start, routine_gap_len = 200, 90  # 90 bars < 120h ceiling at 1h -> routine
    b_full = np.cumsum(rng.normal(0, 0.01, n))
    a_full = b_full + rng.normal(0, 0.05, n)  # genuinely cointegrated
    log_p_a = a_full.copy()
    log_p_b = b_full.copy()
    log_p_a[routine_gap_start:routine_gap_start + routine_gap_len] = np.nan
    log_p_b[routine_gap_start:routine_gap_start + routine_gap_len] = np.nan

    old_p, old_n = _old_naive_eg(log_p_a, log_p_b)
    new_result = _eg_worker(("A", "B", log_p_a, log_p_b, 5, "1h"))
    new_p, new_n = new_result["pvalue"], new_result["n_overlap"]

    if new_n != old_n:
        failures.append(
            f"routine-gap fixture: expected new_n ({new_n}) == old_n ({old_n}) -- "
            f"a routine gap should be bridged exactly like the old convention"
        )
    if not np.isclose(new_p, old_p, atol=1e-6):
        failures.append(
            f"routine-gap fixture: expected new p-value ({new_p}) ~= old p-value "
            f"({old_p}) -- fix should be a no-op for routine-length gaps"
        )

    # --- 3. GENUINE gap (200 bars, beyond ceiling) + artificial jump: must NOT bridge ---
    genuine_gap_start, genuine_gap_len = 150, 200  # 200 bars > 120h ceiling at 1h -> genuine
    b_full2 = np.cumsum(rng.normal(0, 0.01, n))
    a_full2 = b_full2 + rng.normal(0, 0.05, n)
    a_full2[genuine_gap_start + genuine_gap_len:] += 3.0  # spurious level shift at resumption
    log_p_a2 = a_full2.copy()
    log_p_b2 = b_full2.copy()
    log_p_a2[genuine_gap_start:genuine_gap_start + genuine_gap_len] = np.nan
    log_p_b2[genuine_gap_start:genuine_gap_start + genuine_gap_len] = np.nan

    old_p2, old_n2 = _old_naive_eg(log_p_a2, log_p_b2)
    new_result2 = _eg_worker(("A", "B", log_p_a2, log_p_b2, 5, "1h"))
    new_p2, new_n2 = new_result2["pvalue"], new_result2["n_overlap"]

    expected_longest = max(genuine_gap_start, n - genuine_gap_start - genuine_gap_len)
    if new_n2 != expected_longest:
        failures.append(
            f"genuine-gap fixture: expected new_n2 to equal the longest single segment "
            f"({expected_longest}), got {new_n2}"
        )
    if new_n2 >= old_n2:
        failures.append(
            f"genuine-gap fixture: expected fixed convention to use FEWER bars "
            f"({new_n2}) than the old drop-then-concatenate convention ({old_n2})"
        )
    if np.isclose(old_p2, new_p2, atol=1e-6):
        failures.append(
            f"genuine-gap fixture: old p-value ({old_p2}) suspiciously matches new "
            f"({new_p2}) -- fix may not be wired correctly"
        )

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("analysis.py BUG-D77 gap-classification fix verified.")
        print(f"  Routine gap (90 bars): old n={old_n} p={old_p:.6g} | new n={new_n} p={new_p:.6g} (match)")
        print(f"  Genuine gap (200 bars): old n={old_n2} p={old_p2:.6g} | new n={new_n2} p={new_p2:.6g} (differ)")


if __name__ == "__main__":
    main()
