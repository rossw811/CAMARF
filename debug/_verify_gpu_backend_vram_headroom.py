"""Synthetic verification for gpu_backend.py's VRAM-headroom check, added 2026-08-23 after a
real CachyOS crash (GPU benchmark collided with ollama's own VRAM usage, hung the machine --
see docs/HANDOFF.md). Runs on any machine (no GPU required) via monkeypatching.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gpu_backend


def _fake_module(free_gb, available=True):
    """Builds a throwaway module standing in for cupy, with mem_info reporting a controlled
    free-VRAM value, so this test doesn't depend on real GPU hardware or contention state."""
    fake = types.SimpleNamespace()

    class _Device:
        def __init__(self, idx):
            pass

        @property
        def compute_capability(self):
            if not available:
                raise RuntimeError("no device")
            return "89"

        @property
        def mem_info(self):
            return (int(free_gb * 1024 ** 3), 16 * 1024 ** 3)

    fake.cuda = types.SimpleNamespace(Device=_Device)
    return fake


def check_1_headroom_below_floor_falls_back_to_cpu():
    gpu_backend._cupy = _fake_module(free_gb=0.5)
    gpu_backend._CUPY_IMPORTABLE = True
    xp = gpu_backend.get_array_module(use_gpu=True, min_free_gb=3.0)
    assert xp is gpu_backend.np, "expected CPU fallback when VRAM headroom is below the floor"
    print("PASS: check_1_headroom_below_floor_falls_back_to_cpu")


def check_2_headroom_above_floor_returns_gpu():
    gpu_backend._cupy = _fake_module(free_gb=10.0)
    gpu_backend._CUPY_IMPORTABLE = True
    xp = gpu_backend.get_array_module(use_gpu=True, min_free_gb=3.0)
    assert xp is gpu_backend._cupy, "expected GPU when real headroom exceeds the floor"
    print("PASS: check_2_headroom_above_floor_returns_gpu")


def check_3_use_gpu_false_never_touches_headroom_check():
    gpu_backend._cupy = _fake_module(free_gb=0.0)
    gpu_backend._CUPY_IMPORTABLE = True
    xp = gpu_backend.get_array_module(use_gpu=False)
    assert xp is gpu_backend.np, "use_gpu=False must always return numpy regardless of VRAM"
    print("PASS: check_3_use_gpu_false_never_touches_headroom_check")


def check_4_no_gpu_at_all_falls_back_cleanly():
    gpu_backend._cupy = _fake_module(free_gb=10.0, available=False)
    gpu_backend._CUPY_IMPORTABLE = True
    xp = gpu_backend.get_array_module(use_gpu=True, min_free_gb=3.0)
    assert xp is gpu_backend.np, "expected CPU fallback when no CUDA device answers at all"
    print("PASS: check_4_no_gpu_at_all_falls_back_cleanly")


def check_5_gpu_free_vram_gb_matches_fake_mem_info():
    gpu_backend._cupy = _fake_module(free_gb=7.5)
    gpu_backend._CUPY_IMPORTABLE = True
    val = gpu_backend.gpu_free_vram_gb()
    assert abs(val - 7.5) < 0.01, f"expected ~7.5GB, got {val}"
    print("PASS: check_5_gpu_free_vram_gb_matches_fake_mem_info")


if __name__ == "__main__":
    _orig_cupy, _orig_importable = gpu_backend._cupy, gpu_backend._CUPY_IMPORTABLE
    try:
        check_1_headroom_below_floor_falls_back_to_cpu()
        check_2_headroom_above_floor_returns_gpu()
        check_3_use_gpu_false_never_touches_headroom_check()
        check_4_no_gpu_at_all_falls_back_cleanly()
        check_5_gpu_free_vram_gb_matches_fake_mem_info()
        print("\nALL 5 CHECKS PASSED")
    finally:
        gpu_backend._cupy, gpu_backend._CUPY_IMPORTABLE = _orig_cupy, _orig_importable
