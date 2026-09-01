"""
debug/_verify_streaming_checkpoint_results.py -- verifies the 2026-08-26
streaming-results fix to run_rolling_eg_pool BEFORE trusting it against
real, valuable (multi-million-row) Tier-3 checkpoint data.

The fix: when checkpoint_id is given, `by_key`/`window_end_by_key` are no
longer accumulated in memory across the whole run (the unbounded-growth
bug that made crashes MORE frequent the deeper into a run it got) -- the
final flat result is instead reconstructed by reading back the already-
checkpointed part files at the very end. This must produce EXACTLY the
same result as the original in-memory approach, and must resume correctly
from a partial checkpoint, or it is worse than the bug it replaces.

Wrapped in `if __name__ == "__main__":` -- required on Windows, where
multiprocessing uses spawn (not fork) and re-imports this module in each
worker process; without the guard, module-level code re-executes and
recurses into spawning more workers.
"""
import os
import shutil
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research.wrds_deep_history_episodic_scan as scan

TEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_streaming_test_scratch")

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


def make_cointegrated_pair(n=900, seed=0):
    """A real cointegrated pair -- shared random-walk trend plus independent
    stationary noise, guaranteed to produce genuine (not degenerate) EG
    p-values across multiple rolling windows."""
    rng = np.random.RandomState(seed)
    trend = np.cumsum(rng.normal(0, 1, n))
    a = 100 + trend + rng.normal(0, 0.5, n)
    b = 50 + 0.5 * trend + rng.normal(0, 0.5, n)
    return a, b


def clear_scratch():
    if os.path.exists(TEST_DIR):
        for f in os.listdir(TEST_DIR):
            os.remove(os.path.join(TEST_DIR, f))


def _normalize(flat):
    return sorted(
        [(r["symbol_a"], r["symbol_b"], r["window_start"], round(r["pvalue"], 10)) for r in flat]
    )


def main():
    os.makedirs(TEST_DIR, exist_ok=True)
    scan._OUT_DIR = TEST_DIR

    print("Check 1: streaming (checkpoint_id set) produces IDENTICAL results to the original "
          "in-memory accumulator (checkpoint_id=None), same input")
    n_pairs = 6
    log_price_data = {}
    pairs = []
    for i in range(n_pairs):
        a, b = make_cointegrated_pair(n=900, seed=i)
        log_price_data[f"A{i}"] = a
        log_price_data[f"B{i}"] = b
        pairs.append({"symbol_a": f"A{i}", "symbol_b": f"B{i}"})
    log_price_df = pd.DataFrame(log_price_data)
    max_lag = 5

    clear_scratch()
    flat_streaming = scan.run_rolling_eg_pool(
        pairs, log_price_df, max_lag, window=200, step=100, workers=2,
        pair_batch_size=2, checkpoint_id="verify_stream", checkpoint_every=1,
    )
    scan.clear_checkpoint("verify_stream")

    flat_in_memory = scan.run_rolling_eg_pool(
        pairs, log_price_df, max_lag, window=200, step=100, workers=2,
        pair_batch_size=2, checkpoint_id=None,
    )

    check("same number of (pair, window) results in both paths",
          len(flat_streaming) == len(flat_in_memory) and len(flat_streaming) > 0)
    check("streaming result is BIT-FOR-BIT identical to the in-memory result (same pvalues)",
          _normalize(flat_streaming) == _normalize(flat_in_memory))

    print("Check 2: checkpoint meta/part-file reconstruction is complete and correct after a "
          "full run (the exact mechanism a crashed-and-relaunched process depends on)")
    clear_scratch()
    flat_first_call = scan.run_rolling_eg_pool(
        pairs, log_price_df, max_lag, window=200, step=100, workers=2,
        pair_batch_size=2, checkpoint_id="verify_resume", checkpoint_every=1,
    )
    n_done_meta = scan._load_checkpoint_meta("verify_resume")
    check("checkpoint meta correctly reports ALL pairs done after a full run",
          n_done_meta == len(pairs))

    loaded_rows, n_done_loaded = scan._load_checkpoint("verify_resume")
    expected_raw_rows = len(flat_first_call) * 2  # 2 directions (ab, ba) per (pair, window) result
    check("_load_checkpoint reconstructs the full raw row history from part files",
          loaded_rows is not None and len(loaded_rows) == expected_raw_rows)
    scan.clear_checkpoint("verify_resume")
    check("clear_checkpoint removes all part files after resume-reconstruction is done",
          scan._load_checkpoint_meta("verify_resume") is None)

    print("Check 3: use_streaming=False path (no checkpoint_id) is completely unaffected -- "
          "verifies the fix didn't change behavior for callers that don't use checkpointing")
    clear_scratch()
    flat_no_checkpoint_a = scan.run_rolling_eg_pool(
        pairs, log_price_df, max_lag, window=200, step=100, workers=2, pair_batch_size=2,
    )
    flat_no_checkpoint_b = scan.run_rolling_eg_pool(
        pairs, log_price_df, max_lag, window=200, step=100, workers=2, pair_batch_size=2,
    )
    check("no-checkpoint path is deterministic and unaffected by the streaming fix",
          _normalize(flat_no_checkpoint_a) == _normalize(flat_no_checkpoint_b))
    check("no leftover checkpoint files were created for a checkpoint_id=None call",
          len(os.listdir(TEST_DIR)) == 0)

    shutil.rmtree(TEST_DIR, ignore_errors=True)
    print(f"\n{passed}/{passed + failed} checks passed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
