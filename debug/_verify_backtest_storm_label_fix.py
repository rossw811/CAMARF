"""
Synthetic verification that backtest.py's `_storm` label-suffix logic isn't
spuriously triggered by `storm_flags["decay_rate_gate_spec"]`, whose default
value is the non-empty string "coint_fraction:sma" -- truthy, so the old
`any(storm_flags.values())` check always evaluated True and every single
backtest.py run (including plain default runs with zero --storm-* flags)
got a spurious "_storm" suffix on ALL its output filenames. Discovered
2026-09-15 while trying to run debug/_verify_paper_claims.py, whose expected
filenames (no "_storm") never matched any real output file for exactly this
reason. Confirmed via live runs on CachyOS (backtest.py --tf nonexistent_tf)
that no actual STORM variant was silently active -- this was purely a
filename-labeling bug, not a behavior bug.

Run: python debug/_verify_backtest_storm_label_fix.py
"""
import sys

FAILURES = []


def _any_storm_active(storm_flags):
    """Mirrors backtest.py's fixed `elif` condition exactly."""
    return any(v for k, v in storm_flags.items() if k != "decay_rate_gate_spec")


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILURES.append(name)


def _default_storm_flags(**overrides):
    flags = {
        "coint_frac_sizing": False, "garch_stop": False, "session_edge": False,
        "session_edge_postopen": False, "mm_exec": False, "sqrt_impact": False,
        "continuous_forecast_carver": False, "continuous_forecast_linear": False,
        "earnings_blackout": False, "real_corr_exit": False,
        "regime_strength_gate": False, "decay_rate_gate": False,
        "decay_rate_gate_spec": "coint_fraction:sma",  # the always-truthy default string
        "decoupling_avoidance_exit": False, "max_half_life_filter": False,
        "liquidity_bar_filter": False,
    }
    flags.update(overrides)
    return flags


def test_no_flags_set_no_storm_suffix():
    flags = _default_storm_flags()
    check("plain_run.no_storm_flags.suffix_not_triggered", not _any_storm_active(flags))


def test_real_flag_still_triggers_suffix():
    flags = _default_storm_flags(garch_stop=True)
    check("real_storm_flag.garch_stop.suffix_triggered", _any_storm_active(flags))


def test_decay_rate_gate_itself_still_triggers_suffix():
    # The actual boolean gate (not just its spec string) must still work.
    flags = _default_storm_flags(decay_rate_gate=True)
    check("real_storm_flag.decay_rate_gate.suffix_triggered", _any_storm_active(flags))


def test_old_buggy_check_would_have_failed_this_case():
    # Documents exactly what was wrong: the naive any(dict.values()) always
    # returns True because of the spec string, even with every real flag off.
    flags = _default_storm_flags()
    old_buggy_result = any(flags.values())
    check("regression.old_check_was_always_true_bug_reproduced", old_buggy_result is True)


if __name__ == "__main__":
    test_no_flags_set_no_storm_suffix()
    test_real_flag_still_triggers_suffix()
    test_decay_rate_gate_itself_still_triggers_suffix()
    test_old_buggy_check_would_have_failed_this_case()

    print()
    n_fail = len(FAILURES)
    print(f"{4 - n_fail}/4 checks passed")
    if FAILURES:
        print("FAILED:", FAILURES)
        sys.exit(1)
    sys.exit(0)
