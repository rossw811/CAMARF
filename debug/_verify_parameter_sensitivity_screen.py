"""
Synthetic verification for research/parameter_sensitivity_screen.py's
`build_cmd()` -- no live backtest.py execution, just confirms the CLI
command it constructs actually carries the flags each TIER2_REGISTRY entry
depends on. Root-cause fix, 2026-09-21: Tier2's first real run showed EXACT
0.000000 effect-size for corr_exit_threshold/corr_exit_window/max_half_life/
flat_risk_pct/max_concentration_pct -- traced to each parameter's consuming
code in backtest.py/portfolio_sim.py being gated behind a flag or sizing
mode this screen's build_cmd() never passed, so the override was a genuine
no-op regardless of the swept value. This test locks in that every affected
TIER2_REGISTRY entry now requests its enabling flag/mode.

Run: python debug/_verify_parameter_sensitivity_screen.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.parameter_sensitivity_screen import build_cmd, TIER2_REGISTRY

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def test_extra_flags_appear_in_built_command():
    cmd = build_cmd(extra_flags=["--storm-real-corr-exit"])
    check("build_cmd.extra_flags_included", "--storm-real-corr-exit" in cmd, cmd)


def test_no_extra_flags_by_default():
    cmd = build_cmd()
    check("build_cmd.no_spurious_flags_by_default",
          "--storm-real-corr-exit" not in cmd and "--concentration-cap" not in cmd)


def test_capital_sizing_propagates():
    cmd = build_cmd(capital_sizing="flat_2pct")
    idx = cmd.index("--capital-sizing")
    check("build_cmd.capital_sizing_value_propagates", cmd[idx + 1] == "flat_2pct", cmd)


def test_tier2_registry_gated_entries_declare_their_requirement():
    # Every entry below was confirmed (by reading backtest.py/portfolio_sim.py directly,
    # not guessed) to be a structural no-op without the named requirement.
    expectations = {
        "corr_exit_threshold": {"extra_flags": ["--storm-real-corr-exit"]},
        "corr_exit_window": {"extra_flags": ["--storm-real-corr-exit"]},
        "max_half_life": {"extra_flags": ["--storm-max-half-life-filter"]},
        "flat_risk_pct": {"capital_sizing": "flat_2pct"},
        "max_concentration_pct": {"extra_flags": ["--concentration-cap"]},
    }
    by_name = {e["name"]: e for e in TIER2_REGISTRY}
    all_ok = True
    for name, expected in expectations.items():
        entry = by_name.get(name)
        if entry is None:
            all_ok = False
            print(f"    MISSING registry entry: {name}")
            continue
        for key, expected_val in expected.items():
            actual = entry.get(key)
            if actual != expected_val:
                all_ok = False
                print(f"    MISMATCH {name}.{key}: got {actual!r}, expected {expected_val!r}")
    check("tier2_registry.gated_entries_declare_requirement", all_ok)

    # Params that were NEVER gated (confirmed unconditional consumers) should NOT have
    # gained a spurious extra_flags/capital_sizing override -- this test would catch an
    # over-broad fix applied to the wrong entries too.
    unaffected = ["stop_zscore", "exit_zscore", "max_hold_multiplier", "min_half_life_bars",
                  "n_shares_per_trade", "commission_per_share", "slippage_bps"]
    all_clean = True
    for name in unaffected:
        entry = by_name.get(name)
        if entry is None:
            all_clean = False
            continue
        if entry.get("extra_flags") or entry.get("capital_sizing", "fixed") != "fixed":
            all_clean = False
            print(f"    UNEXPECTED override on {name}: {entry}")
    check("tier2_registry.unaffected_entries_unchanged", all_clean)


if __name__ == "__main__":
    test_extra_flags_appear_in_built_command()
    test_no_extra_flags_by_default()
    test_capital_sizing_propagates()
    test_tier2_registry_gated_entries_declare_their_requirement()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
