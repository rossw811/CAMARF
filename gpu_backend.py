"""
gpu_backend.py -- shared, opt-in GPU (CuPy) / CPU (NumPy) array-backend
selector. Added 2026-08-20, following Ross's direct request to identify and
GPU-accelerate every script "big enough" to benefit, now that CachyOS
(RTX 4080, 16GB VRAM) is a real second machine for this project.

A forked dependency audit (2026-08-20, see docs/SOFTWARE_OPTIMIZATION_AUDIT.md
and Development.md for the full writeup) found exactly one clear "easy,
high-value, no-methodology-change" GPU cluster in this ~150-script codebase:
dense linear algebra over universe-scale arrays (the masked-matmul
correlation-matrix core in analysis.py::_vectorized_pairwise_stats, and
EigenportfolioDecomposer's eigendecomposition). Everything else "heavy" in
this codebase is heavy from Python-level looping over thousands of
individual statsmodels/scipy calls (Engle-Granger, Johansen, ADF-per-pair)
-- those have NO simple CuPy swap (statsmodels has no CUDA backend); a GPU
port there would mean reimplementing the statistical test math itself from
scratch, a much bigger correctness risk this file deliberately does NOT
attempt -- see the audit's Tier 2 finding, flagged for Ross's explicit
sign-off before any of that is built, per this project's own "new
methodology needs discussion first" working-style rule.

CuPy was NOT previously installed anywhere in this project (confirmed
directly, 2026-08-20: `import cupy` failed on CachyOS before this session).
Installed via `uv pip install cupy-cuda12x` (matches the installed NVIDIA
driver 610.57.04, which supports CUDA 12.x) plus the pip-distributed CUDA
12 runtime libraries (nvidia-cublas-cu12 etc. -- CachyOS has no system CUDA
toolkit/nvcc installed, and cupy-cuda12x's wheel does not bundle these
itself; cuda-pathfinder, cupy's own dependency, locates them from the pip
packages). Verified working with a real matmul smoke test on the actual
RTX 4080 before this module was written.

Design principle: EVERY caller of this module must work identically on a
machine with no GPU at all (the Windows dev box) -- get_array_module()
NEVER raises just because a GPU was requested but isn't available; it warns
once and falls back to NumPy. use_gpu defaults to False everywhere it's
threaded through calling code, so no existing caller's behavior changes
unless it explicitly opts in.
"""
import contextlib
import warnings

import numpy as np

try:
    import cupy as _cupy
    _CUPY_IMPORTABLE = True
except ImportError:
    _cupy = None
    _CUPY_IMPORTABLE = False

_warned_no_gpu = False


def gpu_available() -> bool:
    """True only if cupy imports AND a real CUDA device answers back --
    a machine with cupy pip-installed but no GPU (or a broken CUDA runtime
    library setup, the exact failure mode found and fixed on CachyOS this
    session: cupy imported fine, but a real op failed with a missing
    libcublas.so.12 until the nvidia-*-cu12 runtime packages were also
    installed) must not be treated as GPU-available just because the
    import succeeded."""
    if not _CUPY_IMPORTABLE:
        return False
    try:
        _cupy.cuda.Device(0).compute_capability
        return True
    except Exception:
        return False


def get_array_module(use_gpu: bool = False):
    """Returns numpy or cupy -- both expose a (near-)identical ndarray API,
    the standard "xp" idiom this module and its callers use throughout.
    use_gpu=False (the default) always returns numpy, unconditionally --
    zero cost, zero import-time cupy dependency check, on any caller that
    never opts in. use_gpu=True returns cupy only if gpu_available();
    otherwise warns once per process and returns numpy."""
    global _warned_no_gpu
    if not use_gpu:
        return np
    if gpu_available():
        return _cupy
    if not _warned_no_gpu:
        warnings.warn(
            "use_gpu=True requested but CuPy/CUDA is not available on this machine -- "
            "falling back to NumPy (CPU). Expected on the Windows dev box; install "
            "cupy-cuda12x (+ the nvidia-*-cu12 runtime packages) on a CUDA-capable "
            "machine to actually use GPU acceleration.",
            stacklevel=2,
        )
        _warned_no_gpu = True
    return np


def to_numpy(arr):
    """Converts a cupy array back to plain numpy (cp.asnumpy); a no-op for
    anything that's already numpy (or None). Callers use this exactly once,
    right before returning, so a function's return type/contract is
    IDENTICAL regardless of which backend actually computed it -- downstream
    code never needs to know or care whether GPU was used."""
    if arr is None:
        return None
    if _CUPY_IMPORTABLE and isinstance(arr, _cupy.ndarray):
        return _cupy.asnumpy(arr)
    return arr


def errstate_ctx(xp, **kwargs):
    """xp.errstate(...) exists on numpy but NOT on cupy (confirmed directly,
    2026-08-20: AttributeError on CachyOS's real cupy 14.2.0) -- CuPy simply
    doesn't raise the same floating-point warnings numpy's errstate would
    suppress, so a no-op context is the correct equivalent, not a bug to
    work around differently."""
    if xp is np:
        return np.errstate(**kwargs)
    return contextlib.nullcontext()
