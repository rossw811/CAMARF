"""
Synthetic verification for gpu_backend.should_use_gpu() (2026-09-21), the
auto-detection helper wired into analysis.py's correlation-matrix call sites
after a real benchmark confirmed GPU is 2-2.8x faster at N>=1000 on CachyOS's
RTX 4080 (debug/_bench_gpu_vs_cpu_correlation.py).

Mocks gpu_available()/gpu_has_headroom() -- no real GPU needed to verify the
threshold/fallback LOGIC itself; the real speedup numbers are already
verified separately by the benchmark script, this only checks should_use_gpu
combines its three inputs correctly.

Run: python debug/_verify_gpu_auto_threshold.py
"""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gpu_backend

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def test_below_threshold_always_false():
    with mock.patch("gpu_backend.gpu_available", return_value=True), \
         mock.patch("gpu_backend.gpu_has_headroom", return_value=True):
        check("below_threshold.n_500_false", gpu_backend.should_use_gpu(500) is False)
        check("below_threshold.n_1499_false", gpu_backend.should_use_gpu(1499) is False)


def test_at_or_above_threshold_with_gpu_and_headroom_true():
    with mock.patch("gpu_backend.gpu_available", return_value=True), \
         mock.patch("gpu_backend.gpu_has_headroom", return_value=True):
        check("above_threshold.n_1500_true", gpu_backend.should_use_gpu(1500) is True)
        check("above_threshold.n_44000_true", gpu_backend.should_use_gpu(44000) is True)


def test_no_gpu_available_false_even_above_threshold():
    with mock.patch("gpu_backend.gpu_available", return_value=False):
        check("no_gpu.large_n_still_false", gpu_backend.should_use_gpu(44000) is False)


def test_no_headroom_false_even_above_threshold():
    with mock.patch("gpu_backend.gpu_available", return_value=True), \
         mock.patch("gpu_backend.gpu_has_headroom", return_value=False):
        check("no_headroom.large_n_still_false", gpu_backend.should_use_gpu(44000) is False)


def test_never_raises_on_windows_box_no_gpu():
    # Real behavior on the actual local dev machine (no CUDA at all) -- no mocking,
    # exercises the real gpu_available() path end to end.
    try:
        result = gpu_backend.should_use_gpu(44000)
        check("no_crash.real_call_on_this_machine", result in (True, False), f"got {result}")
    except Exception as e:
        check("no_crash.real_call_on_this_machine", False, f"raised {type(e).__name__}: {e}")


def test_headroom_check_skipped_below_threshold():
    # gpu_has_headroom should not even be called for small N -- cheap short-circuit,
    # not just "returns False eventually."
    with mock.patch("gpu_backend.gpu_available", return_value=True), \
         mock.patch("gpu_backend.gpu_has_headroom") as mock_headroom:
        gpu_backend.should_use_gpu(100)
        check("short_circuit.headroom_not_checked_below_threshold",
              not mock_headroom.called)


if __name__ == "__main__":
    test_below_threshold_always_false()
    test_at_or_above_threshold_with_gpu_and_headroom_true()
    test_no_gpu_available_false_even_above_threshold()
    test_no_headroom_false_even_above_threshold()
    test_never_raises_on_windows_box_no_gpu()
    test_headroom_check_skipped_below_threshold()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
