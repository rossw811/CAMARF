"""
Regression test for code-review B6 (confirmed 2026-09-26, fixed 2026-10-03, bug recheck T14.4): backtest.py built the
IS-only FITTING engine (sizing weights / P&L caps, BUG-D76) with raw Config.BACKTEST, and applied --entry-z,
--entry-z-max and --override only afterwards to the main engine -- weights were fitted under different trading rules
than the run they size. Fix: `_build_backtest_cfg(args)` builds the overridden config once, BEFORE both engines.
Checks: the helper applies --entry-z / --override (and refuses an unknown name); it does not mutate Config.BACKTEST;
the fitting engine and the main engine are both built with it (source check -- main() runs the whole pipeline).
Run: python debug/_verify_backtest_override_fit_engine.py
"""
import os
import re
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtest
from config import Config

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    if not hasattr(backtest, "_build_backtest_cfg"):
        check("helper_exists", False); return finish()
    before = Config.BACKTEST.ENTRY_ZSCORE
    cfg, sfx = backtest._build_backtest_cfg(SimpleNamespace(entry_z=1.75, entry_z_max=None,
                                                            override=["STOP_ZSCORE=4.5"]))
    check("applies_overrides", cfg.ENTRY_ZSCORE == 1.75 and cfg.STOP_ZSCORE == 4.5 and "_ovSTOP_ZSCORE4p5" in sfx,
          f"entry={cfg.ENTRY_ZSCORE} stop={cfg.STOP_ZSCORE} sfx={sfx}")
    check("config_not_mutated", Config.BACKTEST.ENTRY_ZSCORE == before)
    try:
        backtest._build_backtest_cfg(SimpleNamespace(entry_z=None, entry_z_max=None, override=["NOT_A_FIELD=1"]))
        check("unknown_name_refused", False)
    except ValueError:
        check("unknown_name_refused", True)
    src = open(backtest.__file__, encoding="utf-8").read()
    fit = re.search(r"_fitting_engine = BacktestEngine\(\s*cfg=(\w+)", src)
    main_e = re.search(r"\n    engine = BacktestEngine\(\s*cfg=(\w+)", src)
    check("both_engines_use_it", bool(fit and main_e) and fit.group(1) == main_e.group(1) == "_backtest_cfg",
          f"fit={fit.group(1) if fit else None} main={main_e.group(1) if main_e else None}")
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
