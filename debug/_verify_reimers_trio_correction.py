"""
Synthetic verification for research/reimers_trio_correction.py's
reimers_correction() function.

Case 1: the correction factor (T - n*k)/T should be exactly computable by
hand for known T, n, k — check the arithmetic directly, not just that the
function runs.

Case 2: correction factor must be strictly less than 1 (the whole point
of the small-sample correction is to SHRINK the trace statistic, making
the test more conservative, not less) for any realistic T > n*k.

Case 3: a trace statistic just barely above the critical value should
correctly flip to "does not reject" once corrected (since the corrected
stat is strictly smaller) — and a trace statistic far above the critical
value should NOT flip (correction isn't strong enough to overturn an
overwhelming result).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.reimers_trio_correction import reimers_correction

failures = []

# --- Case 1: exact arithmetic check ---
T, n, k = 1000, 3, 1
expected_factor = (T - n * k) / T  # (1000-3)/1000 = 0.997
corrected, _, _ = reimers_correction(trace_stat=100.0, cvt=[25.0, 29.68, 35.65], n_bars=T, n_vars=n, k=k)
expected_corrected = 100.0 * expected_factor
print(f"Case 1: expected corrected={expected_corrected:.4f}, got {corrected:.4f}")
if abs(corrected - expected_corrected) > 1e-9:
    failures.append(f"Case 1: arithmetic mismatch, expected {expected_corrected}, got {corrected}")

# --- Case 2: correction factor always < 1 for realistic T ---
for T_test in [100, 500, 4000]:
    corrected, _, _ = reimers_correction(trace_stat=50.0, cvt=[25.0, 29.68, 35.65], n_bars=T_test, n_vars=3, k=1)
    if not (corrected < 50.0):
        failures.append(f"Case 2: correction should shrink the stat (T={T_test}): 50.0 -> {corrected}")

# --- Case 3: decision-flip logic ---
# Just above critical value (29.68) -> should flip to non-rejection once corrected
corrected_a, raw_a, corr_a = reimers_correction(trace_stat=29.9, cvt=[25.0, 29.68, 35.65], n_bars=200, n_vars=3, k=1)
print(f"Case 3a (barely-significant raw stat=29.9, crit=29.68): corrected={corrected_a:.4f}, "
      f"raw_rejects={raw_a}, corrected_rejects={corr_a}")
if not raw_a:
    failures.append("Case 3a: raw stat 29.9 > crit 29.68 should reject (raw_rejects should be True)")
if corr_a:
    failures.append(f"Case 3a: expected the correction to flip a barely-significant result to non-rejection, "
                    f"corrected stat {corrected_a:.4f} still exceeds crit 29.68")

# Overwhelmingly significant -> should NOT flip
corrected_b, raw_b, corr_b = reimers_correction(trace_stat=200.0, cvt=[25.0, 29.68, 35.65], n_bars=200, n_vars=3, k=1)
print(f"Case 3b (overwhelming raw stat=200.0, crit=29.68): corrected={corrected_b:.4f}, "
      f"raw_rejects={raw_b}, corrected_rejects={corr_b}")
if not (raw_b and corr_b):
    failures.append(f"Case 3b: an overwhelming trace stat should reject both raw and corrected")

print()
if failures:
    print(f"FAILED ({len(failures)} issue(s)):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)
