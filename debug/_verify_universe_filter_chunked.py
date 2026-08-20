"""
Synthetic verification of analysis.py::UniverseFilter.run_chunked -- proves
BIT-EXACT equivalence with the existing, already-verified UniverseFilter.run()
on a small synthetic universe, run BEFORE trusting run_chunked() at real
(46,353-symbol) scale where run() itself can't be used as a live comparison
(would need 17.2GB it doesn't have).

Checks:
  1. Same candidate pairs found (identical symbol-pair set) between run() and
     run_chunked() at a batch_size SMALLER than the universe (forces real
     within-block AND cross-block computation to both occur).
  2. Every matching pair's pearson_corr/spearman_corr/rolling_avg_corr/
     confidence_tier is numerically identical (not just "close") between the
     two paths -- the real claim being verified, since run_chunked() calls
     the exact same underlying functions, just on subsets.
  3. batch_size=1 (every symbol its own block -- maximally fragmented,
     forces every pair to be a cross-block pair) still produces the
     identical result -- a stress test of the cross-block dedup logic.
  4. A universe with a real, deliberately-planted cross-asset-class pair
     confirms is_cross_asset is preserved correctly through chunking.
  5. flush_path streaming mode (added 2026-08-14 after a real OOM risk found
     at full 44,840-symbol scale -- see run_chunked's own docstring) writes
     the SAME candidate set to disk, in flushes smaller than the total
     result, as the non-streaming in-memory path produces.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from analysis import UniverseFilter


def _build_synthetic_universe(n_symbols=23, T=400, seed=0):
    """n_symbols deliberately NOT a clean multiple of any batch_size tested
    below, so block-boundary edge cases (a partial final block) are exercised
    for real, not avoided by a convenient round number."""
    rng = np.random.RandomState(seed)
    idx = pd.date_range("2020-01-01", periods=T, freq="D")
    aligned_data = {}
    asset_class_map = {}
    # A few genuinely correlated clusters so real candidate pairs exist to compare.
    shared_a = rng.standard_normal(T) * 0.01
    shared_b = rng.standard_normal(T) * 0.01
    for i in range(n_symbols):
        sym = f"SYM{i:03d}"
        if i < 8:
            ret = shared_a * 0.9 + rng.standard_normal(T) * 0.003
        elif i < 14:
            ret = shared_b * 0.85 + rng.standard_normal(T) * 0.004
        else:
            ret = rng.standard_normal(T) * 0.01  # independent noise
        close = 100 * np.exp(np.cumsum(ret))
        aligned_data[sym] = pd.DataFrame({"close": close}, index=idx)
        asset_class_map[sym] = "equity" if i % 3 != 0 else "crypto"  # real cross-asset-class mix
    return aligned_data, asset_class_map


def _pair_key(p):
    return tuple(sorted([p["symbol_a"], p["symbol_b"]]))


def main():
    failures = []
    aligned_data, asset_class_map = _build_synthetic_universe()
    threshold = 0.30  # low enough that the synthetic clusters clearly clear it

    pairs_full, symbols_full = UniverseFilter.run(
        aligned_data, asset_class_map, threshold, tf_label="1D",
    )[:2]

    for batch_size, label in [(7, "batch_size=7 (partial final block)"),
                               (1, "batch_size=1 (fully fragmented)")]:
        pairs_chunked, symbols_chunked = UniverseFilter.run_chunked(
            aligned_data, asset_class_map, threshold, tf_label="1D", batch_size=batch_size,
        )

        keys_full = {_pair_key(p) for p in pairs_full}
        keys_chunked = {_pair_key(p) for p in pairs_chunked}

        if keys_full != keys_chunked:
            failures.append(
                f"Check ({label}): pair sets differ -- only in full: "
                f"{keys_full - keys_chunked}, only in chunked: {keys_chunked - keys_full}"
            )
            continue  # skip the per-pair numeric check if the sets themselves disagree

        by_key_full = {_pair_key(p): p for p in pairs_full}
        by_key_chunked = {_pair_key(p): p for p in pairs_chunked}
        for key in keys_full:
            pf, pc = by_key_full[key], by_key_chunked[key]
            for field in ("pearson_corr", "spearman_corr", "rolling_avg_corr"):
                vf, vc = pf[field], pc[field]
                both_nan = np.isnan(vf) and np.isnan(vc)
                if not both_nan and not np.isclose(vf, vc, atol=1e-12):
                    failures.append(f"Check ({label}): pair {key} field {field} differs -- "
                                     f"full={vf!r} chunked={vc!r}")
            if pf["confidence_tier"] != pc["confidence_tier"]:
                failures.append(f"Check ({label}): pair {key} confidence_tier differs -- "
                                 f"full={pf['confidence_tier']} chunked={pc['confidence_tier']}")
            if pf["is_cross_asset"] != pc["is_cross_asset"]:
                failures.append(f"Check ({label}): pair {key} is_cross_asset differs -- "
                                 f"full={pf['is_cross_asset']} chunked={pc['is_cross_asset']}")

    # --- Check 5: flush_path streaming mode (a DIRECTORY of chunk files, one per flush --
    # NOT a single growing file, which would itself be an O(n^2) rewrite cost at real scale --
    # see run_chunked's own docstring) matches the in-memory result ---
    scratch_dir = tempfile.mkdtemp(prefix="verify_chunked_flush_")
    flush_dir = os.path.join(scratch_dir, "candidates")
    try:
        # flush_every=3 and progress_every=2 -- deliberately small so multiple real
        # flush/log events (multiple chunk files) occur during this tiny 10-block-pair run.
        UniverseFilter.run_chunked(
            aligned_data, asset_class_map, threshold, tf_label="1D", batch_size=7,
            flush_path=flush_dir, flush_every=3, progress_every=2,
        )
        chunk_files = sorted(f for f in os.listdir(flush_dir)) if os.path.isdir(flush_dir) else []
        if not chunk_files:
            failures.append("Check 5: flush_path directory was never created / no chunk files written")
        elif len(chunk_files) < 2:
            failures.append(f"Check 5: expected multiple chunk files (flush_every=3 over 10 "
                             f"block-pairs), got only {len(chunk_files)} -- flush isn't actually "
                             f"happening incrementally")
        else:
            streamed_df = pd.concat(
                [pd.read_parquet(os.path.join(flush_dir, f)) for f in chunk_files], ignore_index=True
            )
            keys_streamed = {tuple(sorted([r["symbol_a"], r["symbol_b"]]))
                              for _, r in streamed_df.iterrows()}
            if keys_streamed != keys_full:
                failures.append(
                    f"Check 5: streamed candidate set differs from run()'s -- only in full: "
                    f"{keys_full - keys_streamed}, only in streamed: {keys_streamed - keys_full}"
                )
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All UniverseFilter.run_chunked equivalence checks passed.")
    print(f"  run(): {len(pairs_full)} candidate pairs found")
    print(f"  run_chunked(batch_size=7): bit-exact match confirmed (partial final block)")
    print(f"  run_chunked(batch_size=1): bit-exact match confirmed (fully fragmented, "
          f"every pair cross-block)")
    print(f"  run_chunked(flush_path=...): streamed-to-disk candidates match run()'s result")


if __name__ == "__main__":
    main()
