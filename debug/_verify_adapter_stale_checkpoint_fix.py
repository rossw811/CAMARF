"""
Synthetic verification of episodic_pairs_adapter.py::build_adapter_rows'
stale-checkpoint-filtering fix (found live, 2026-08-12, while rebuilding the
adapter after BUG-D112 shrank the confirmed set from 647 to 326 pairs) --
run BEFORE trusting the real adapter rebuild.

The bug: a prior checkpoint (episodic_pairs_adapter_progress_{source}.parquet)
can contain rows for pairs no longer in the CURRENT confirmed set (`details`,
from discover_pit_confirmed_pairs_with_detail). The original code blindly
trusted every checkpointed row regardless of whether it was still current --
silently reintroducing stale, no-longer-confirmed pairs into supposedly-
current PIT-safe output.

Check: with a checkpoint containing 3 rows (A/B, C/D, E/F) but `details` only
listing A/B and G/H (i.e. C/D and E/F fell out of the confirmed set, G/H is
new), build_adapter_rows must return exactly {A/B (reused from checkpoint),
G/H (freshly built)} -- C/D and E/F must NOT appear in the output, and the
checkpoint file itself must be pruned to drop them too (not just filtered
in-memory for this one call).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import research.episodic_pairs_adapter as adapter_mod


def _fake_row(sym_a, sym_b, tf_label="1D"):
    return {
        "symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf_label, "source": "test",
        "as_of_date": pd.Timestamp("2026-08-12"), "n_windows_tested": 5, "n_windows_fdr_rejected": 2,
        "hedge_ratio_ols": 1.0, "hedge_ratio_kalman_mean": 1.0, "hurst_rs": 0.5,
        "coint_fraction_rolling": 0.5, "half_life_trend_slope": 0.0, "mean_reversion_speed": 0.1,
    }


def main():
    failures = []
    tmpdir = tempfile.mkdtemp()
    progress_path = os.path.join(tmpdir, "episodic_pairs_adapter_progress_test.parquet")

    # Old checkpoint: A/B, C/D, E/F all previously built.
    old_rows = [_fake_row("A", "B"), _fake_row("C", "D"), _fake_row("E", "F")]
    pd.DataFrame(old_rows).to_parquet(progress_path)

    # Current confirmed set (post-methodology-fix): only A/B survives, G/H is new.
    current_details = [
        {"symbol_a": "A", "symbol_b": "B", "n_windows_tested": 5, "n_windows_fdr_rejected": 2},
        {"symbol_a": "G", "symbol_b": "H", "n_windows_tested": 4, "n_windows_fdr_rejected": 2},
    ]

    # Monkeypatch: discover_pit_confirmed_pairs_with_detail -> current_details,
    # _resume_checkpoint_path -> our temp path, build_one_row -> a fake builder
    # for G/H only (A/B should be reused from checkpoint, never rebuilt).
    orig_discover = adapter_mod.discover_pit_confirmed_pairs_with_detail
    orig_resume_path = adapter_mod._resume_checkpoint_path
    orig_build_one_row = adapter_mod.build_one_row
    built_calls = []

    def fake_discover(**kwargs):
        return current_details

    def fake_resume_path(source):
        return progress_path

    def fake_build_one_row(sym_a, sym_b, tf_label, as_of_date, source, detail):
        built_calls.append((sym_a, sym_b))
        return _fake_row(sym_a, sym_b, tf_label)

    adapter_mod.discover_pit_confirmed_pairs_with_detail = fake_discover
    adapter_mod._resume_checkpoint_path = fake_resume_path
    adapter_mod.build_one_row = fake_build_one_row
    try:
        result = adapter_mod.build_adapter_rows("test", "1D", n_workers=1)
    finally:
        adapter_mod.discover_pit_confirmed_pairs_with_detail = orig_discover
        adapter_mod._resume_checkpoint_path = orig_resume_path
        adapter_mod.build_one_row = orig_build_one_row

    result_keys = set(zip(result["symbol_a"], result["symbol_b"]))
    expected_keys = {("A", "B"), ("G", "H")}
    if result_keys != expected_keys:
        failures.append(f"Output should be exactly {expected_keys}, got {result_keys}")
    if ("A", "B") in built_calls:
        failures.append(f"A/B should have been REUSED from checkpoint, not rebuilt -- "
                         f"build_one_row was called for it: {built_calls}")
    if ("G", "H") not in built_calls:
        failures.append(f"G/H is new (not in old checkpoint) -- should have been built, "
                         f"but build_one_row calls were: {built_calls}")

    # Checkpoint file itself should now be pruned (only A/B, since G/H gets
    # appended during the build loop too).
    pruned = pd.read_parquet(progress_path)
    pruned_keys = set(zip(pruned["symbol_a"], pruned["symbol_b"]))
    if ("C", "D") in pruned_keys or ("E", "F") in pruned_keys:
        failures.append(f"Checkpoint file itself should be pruned of stale C/D, E/F rows, "
                         f"got {pruned_keys}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All adapter stale-checkpoint-filtering checks passed.")
    print(f"  result keys: {result_keys}")
    print(f"  build_one_row was called for: {built_calls} (only G/H, A/B correctly reused)")
    print(f"  pruned checkpoint keys: {pruned_keys}")


if __name__ == "__main__":
    main()
