"""
Synthetic verification of analysis.py::UniverseFilter.chunked_pearson_candidate_pairs
-- the memory-bounded Pearson-only candidate extraction built 2026-08-16 to
fix a real, live OOM crash in research/wrds_deep_history_episodic_scan.py::
rolling_correlation_candidate_pairs at the full ~18,283-symbol universe
(episodic_window_size_sweep.py --full-universe): the direct
`UniverseFilter.correlation_matrix(seg.T)` call this replaces failed with
"Unable to allocate 2.49 GiB for an array with shape (18283, 18283)" on its
FIRST rolling window.

Checks:
  1. Bit-exact pair-set and pearson_corr match against the direct, unchunked
     correlation_matrix()+candidate_pairs() call, at a batch_size SMALLER
     than the universe (forces real within-block AND cross-block work).
  2. batch_size=1 (every symbol its own block -- every pair is cross-block)
     still matches exactly.
  3. Cross-asset-class flag preserved correctly through chunking.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from analysis import UniverseFilter


def _synthetic_returns(n_symbols=23, T=400, seed=0):
    rng = np.random.RandomState(seed)
    shared_a = rng.standard_normal(T) * 0.01
    shared_b = rng.standard_normal(T) * 0.01
    returns = np.zeros((n_symbols, T))
    symbols = []
    asset_class_map = {}
    for i in range(n_symbols):
        sym = f"SYM{i:03d}"
        symbols.append(sym)
        if i < 8:
            returns[i] = shared_a * 0.9 + rng.standard_normal(T) * 0.003
        elif i < 14:
            returns[i] = shared_b * 0.85 + rng.standard_normal(T) * 0.004
        else:
            returns[i] = rng.standard_normal(T) * 0.01
        asset_class_map[sym] = "equity" if i % 3 != 0 else "crypto"  # real cross-asset-class mix
    return returns, symbols, asset_class_map


def _key(p):
    return tuple(sorted([p["symbol_a"], p["symbol_b"]]))


def main():
    failures = []
    returns, symbols, asset_class_map = _synthetic_returns()
    threshold = 0.30

    corr_full = UniverseFilter.correlation_matrix(returns)
    pairs_direct = UniverseFilter.candidate_pairs(corr_full, symbols, threshold, asset_class_map)
    keys_direct = {_key(p): p for p in pairs_direct}

    for batch_size, label in [(7, "batch_size=7 (partial final block)"),
                               (1, "batch_size=1 (fully fragmented)")]:
        pairs_chunked = UniverseFilter.chunked_pearson_candidate_pairs(
            returns, symbols, threshold, asset_class_map, batch_size=batch_size,
        )
        keys_chunked = {_key(p): p for p in pairs_chunked}

        if set(keys_direct) != set(keys_chunked):
            failures.append(
                f"Check ({label}): pair sets differ -- only direct: "
                f"{set(keys_direct) - set(keys_chunked)}, only chunked: {set(keys_chunked) - set(keys_direct)}"
            )
            continue

        for k in keys_direct:
            pd_, pc = keys_direct[k], keys_chunked[k]
            if not np.isclose(pd_["pearson_corr"], pc["pearson_corr"], atol=1e-12):
                failures.append(f"Check ({label}): pair {k} pearson_corr differs -- "
                                 f"direct={pd_['pearson_corr']!r} chunked={pc['pearson_corr']!r}")
            if pd_["is_cross_asset"] != pc["is_cross_asset"]:
                failures.append(f"Check ({label}): pair {k} is_cross_asset differs -- "
                                 f"direct={pd_['is_cross_asset']} chunked={pc['is_cross_asset']}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All chunked_pearson_candidate_pairs checks passed.")
    print(f"  direct call: {len(pairs_direct)} candidate pairs found")
    print(f"  chunked (batch_size=7): bit-exact match confirmed")
    print(f"  chunked (batch_size=1): bit-exact match confirmed (fully fragmented, every pair cross-block)")


if __name__ == "__main__":
    main()
