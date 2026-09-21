"""
Synthetic verification for scripts/pre_commit_verify.py -- fabricated staged
files and verify scripts, no real git state, no real subprocess calls to
_verify_*.py scripts themselves (that's what debug/_verify_run_all_verify.py
already covers for run_one() itself; this tests the RELEVANCE-MATCHING
logic specifically).

Run: python debug/_verify_pre_commit_verify.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.pre_commit_verify import find_relevant_verify_scripts, _module_name

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def test_module_name_extraction():
    check("module_name.strips_dir_and_ext",
          _module_name("research/squeeze_momentum_features.py") == "squeeze_momentum_features")
    check("module_name.plain_filename",
          _module_name("backtest.py") == "backtest")


def test_filename_substring_match():
    tmpdir = tempfile.mkdtemp()
    try:
        debug_dir = os.path.join(tmpdir, "debug")
        os.makedirs(debug_dir)
        for name in ["_verify_backtest_storm_label_fix.py", "_verify_ml_feature_lag.py",
                     "_verify_unrelated_thing.py"]:
            open(os.path.join(debug_dir, name), "w").close()

        import scripts.pre_commit_verify as m
        old_debug_dir = m._DEBUG_DIR
        m._DEBUG_DIR = debug_dir
        try:
            relevant = find_relevant_verify_scripts(
                ["backtest.py"],
                ["_verify_backtest_storm_label_fix.py", "_verify_ml_feature_lag.py",
                 "_verify_unrelated_thing.py"],
            )
        finally:
            m._DEBUG_DIR = old_debug_dir

        check("filename_match.finds_backtest_verify_script",
              "_verify_backtest_storm_label_fix.py" in relevant["backtest.py"])
        check("filename_match.excludes_unrelated_script",
              "_verify_unrelated_thing.py" not in relevant["backtest.py"])
        check("filename_match.excludes_ml_script",
              "_verify_ml_feature_lag.py" not in relevant["backtest.py"])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_import_line_match():
    tmpdir = tempfile.mkdtemp()
    try:
        debug_dir = os.path.join(tmpdir, "debug")
        os.makedirs(debug_dir)
        vscript_path = os.path.join(debug_dir, "_verify_something_else.py")
        with open(vscript_path, "w") as f:
            f.write("from mymodule import some_function\n\nprint('test')\n")

        import scripts.pre_commit_verify as m
        old_debug_dir = m._DEBUG_DIR
        m._DEBUG_DIR = debug_dir
        try:
            relevant = find_relevant_verify_scripts(
                ["mymodule.py"], ["_verify_something_else.py"]
            )
        finally:
            m._DEBUG_DIR = old_debug_dir

        check("import_match.finds_script_via_import_line",
              "_verify_something_else.py" in relevant["mymodule.py"])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_no_coverage_reported_not_crashed():
    tmpdir = tempfile.mkdtemp()
    try:
        debug_dir = os.path.join(tmpdir, "debug")
        os.makedirs(debug_dir)
        open(os.path.join(debug_dir, "_verify_totally_unrelated.py"), "w").close()

        import scripts.pre_commit_verify as m
        old_debug_dir = m._DEBUG_DIR
        m._DEBUG_DIR = debug_dir
        try:
            relevant = find_relevant_verify_scripts(
                ["some_brand_new_module.py"], ["_verify_totally_unrelated.py"]
            )
        finally:
            m._DEBUG_DIR = old_debug_dir

        check("no_coverage.returns_empty_list_not_crash",
              relevant["some_brand_new_module.py"] == [])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    test_module_name_extraction()
    test_filename_substring_match()
    test_import_line_match()
    test_no_coverage_reported_not_crashed()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
