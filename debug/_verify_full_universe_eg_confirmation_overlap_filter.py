"""
Synthetic verification for the minimum-overlap filter added to
research/full_universe_eg_confirmation.py (2026-09-10): confirmed pairs
below this project's own Config.STATS.MIN_OVERLAP_BY_TF standard must be
dropped, not silently accepted. Tests the filter LOGIC directly (inlined,
matching the script's own code exactly) rather than importing the script
as a module, since it's a __main__-driven CLI script, not a library.

Run: python debug/_verify_full_universe_eg_confirmation_overlap_filter.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def apply_overlap_filter(confirmed, tf):
    """Exact logic from research/full_universe_eg_confirmation.py."""
    min_overlap = Config.STATS.MIN_OVERLAP_BY_TF.get(tf, 252)
    thin = [c for c in confirmed if c.get("n_overlap", 0) < min_overlap]
    kept = [c for c in confirmed if c.get("n_overlap", 0) >= min_overlap]
    return kept, thin


def test_real_bug_case_AISP_GVKEY():
    # The exact real pair found 2026-09-10: 1D min overlap = 252, this pair had 123
    confirmed = [
        {"symbol_a": "AISP", "symbol_b": "GVKEY239599_01W", "n_overlap": 123},
        {"symbol_a": "AMP", "symbol_b": "RUSHA", "n_overlap": 7394},
    ]
    kept, thin = apply_overlap_filter(confirmed, "1D")
    check("real_case.thin_pair_dropped",
          "AISP" not in [c["symbol_a"] for c in kept], kept)
    check("real_case.healthy_pair_kept",
          "AMP" in [c["symbol_a"] for c in kept], kept)
    check("real_case.thin_pair_in_dropped_list",
          len(thin) == 1 and thin[0]["symbol_a"] == "AISP", thin)


def test_exactly_at_threshold_kept():
    confirmed = [{"symbol_a": "X", "symbol_b": "Y", "n_overlap": 252}]
    kept, thin = apply_overlap_filter(confirmed, "1D")
    check("boundary.exactly_at_threshold_kept", len(kept) == 1 and len(thin) == 0, kept)


def test_one_below_threshold_dropped():
    confirmed = [{"symbol_a": "X", "symbol_b": "Y", "n_overlap": 251}]
    kept, thin = apply_overlap_filter(confirmed, "1D")
    check("boundary.one_below_threshold_dropped", len(kept) == 0 and len(thin) == 1, thin)


def test_different_timeframes_use_different_thresholds():
    # 1h needs 756, 1D needs 252 -- same n_overlap, different outcome
    confirmed_1h = [{"symbol_a": "X", "symbol_b": "Y", "n_overlap": 300}]
    kept_1h, _ = apply_overlap_filter(confirmed_1h, "1h")
    kept_1d, _ = apply_overlap_filter(confirmed_1h, "1D")
    check("tf_specific.1h_drops_300_overlap", len(kept_1h) == 0, kept_1h)
    check("tf_specific.1D_keeps_300_overlap", len(kept_1d) == 1, kept_1d)


def test_missing_n_overlap_key_treated_as_zero_and_dropped():
    # Fail-closed, not fail-open: a pair missing n_overlap entirely should
    # be dropped (treated as 0 overlap), never silently kept.
    confirmed = [{"symbol_a": "X", "symbol_b": "Y"}]
    kept, thin = apply_overlap_filter(confirmed, "1D")
    check("missing_key.fails_closed_dropped", len(kept) == 0 and len(thin) == 1, thin)


def test_empty_confirmed_list():
    kept, thin = apply_overlap_filter([], "1D")
    check("empty.no_crash", kept == [] and thin == [])


if __name__ == "__main__":
    test_real_bug_case_AISP_GVKEY()
    test_exactly_at_threshold_kept()
    test_one_below_threshold_dropped()
    test_different_timeframes_use_different_thresholds()
    test_missing_n_overlap_key_treated_as_zero_and_dropped()
    test_empty_confirmed_list()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
