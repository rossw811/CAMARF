"""
Synthetic verification for debug/_run_all_verify.py -- the verify-suite
runner. Builds tiny fixture scripts (a real PASS, a real FAIL, a real
pre-check crash/ERROR) in a temp dir and confirms run_one() classifies each
correctly, plus discover_verify_scripts()'s filtering.

Run: python debug/_verify_run_all_verify.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from debug._run_all_verify import run_one, discover_verify_scripts, _looks_like_pre_check_crash

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


_PASS_SCRIPT = '''
print("[PASS] fixture check")
print("1/1 checks passed")
import sys
sys.exit(0)
'''

_FAIL_SCRIPT = '''
print("[PASS] first check")
print("[FAIL] second check")
print("1/2 checks passed")
import sys
sys.exit(1)
'''

_ERROR_SCRIPT = '''
import sys
raise RuntimeError("simulated missing dependency, e.g. a data file only on CachyOS")
'''

_TIMEOUT_SCRIPT = '''
import time
time.sleep(30)
'''


def _write_and_run(tmpdir, content):
    path = os.path.join(tmpdir, "_verify_fixture.py")
    with open(path, "w") as f:
        f.write(content)
    return run_one(path, timeout=10)


def test_pass_classified_correctly():
    tmpdir = tempfile.mkdtemp()
    try:
        r = _write_and_run(tmpdir, _PASS_SCRIPT)
        check("classify.pass_script_is_PASS", r["status"] == "PASS", r["status"])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_fail_classified_correctly():
    tmpdir = tempfile.mkdtemp()
    try:
        r = _write_and_run(tmpdir, _FAIL_SCRIPT)
        check("classify.fail_script_is_FAIL", r["status"] == "FAIL", r["status"])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_error_classified_correctly():
    tmpdir = tempfile.mkdtemp()
    try:
        r = _write_and_run(tmpdir, _ERROR_SCRIPT)
        check("classify.crash_before_any_check_is_ERROR", r["status"] == "ERROR", r["status"])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_timeout_classified_as_error():
    tmpdir = tempfile.mkdtemp()
    try:
        path = os.path.join(tmpdir, "_verify_fixture.py")
        with open(path, "w") as f:
            f.write(_TIMEOUT_SCRIPT)
        r = run_one(path, timeout=1)
        check("classify.timeout_is_ERROR", r["status"] == "ERROR", r["status"])
        check("classify.timeout_message_mentions_timeout", "TIMEOUT" in r["output"])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_pre_check_crash_heuristic():
    check("heuristic.no_markers_before_traceback_is_crash",
          _looks_like_pre_check_crash("Traceback (most recent call last)\n...error...") is True)
    check("heuristic.markers_before_traceback_is_not_pre_check_crash",
          _looks_like_pre_check_crash(
              "[PASS] a\n[FAIL] b\nTraceback (most recent call last)\n...") is False)
    check("heuristic.no_traceback_at_all_is_false",
          _looks_like_pre_check_crash("no traceback here") is False)


def test_discover_filters_by_pattern():
    tmpdir = tempfile.mkdtemp()
    try:
        for name in ["_verify_apple.py", "_verify_banana.py", "_verify_apple_pie.py", "not_a_verify.py"]:
            open(os.path.join(tmpdir, name), "w").close()
        import debug._run_all_verify as mod
        old_dir = mod._DEBUG_DIR
        mod._DEBUG_DIR = tmpdir
        try:
            all_found = discover_verify_scripts()
            apple_found = discover_verify_scripts(pattern="apple")
        finally:
            mod._DEBUG_DIR = old_dir
        check("discover.finds_only_verify_prefixed", len(all_found) == 3, len(all_found))
        check("discover.pattern_filters_correctly", len(apple_found) == 2, len(apple_found))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    test_pass_classified_correctly()
    test_fail_classified_correctly()
    test_error_classified_correctly()
    test_timeout_classified_as_error()
    test_pre_check_crash_heuristic()
    test_discover_filters_by_pattern()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
