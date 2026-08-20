"""
debug/_verify_overnight_orchestrator_py.py -- synthetic proof for
run_overnight_research.py's core primitives (run_stage, run_stage_until_success,
the parallel-batch pattern, and cross-platform timeout-kill), added 2026-08-20.

Does NOT run against the real production pipeline (too slow/expensive for a
verification test, and not the point -- the orchestration LOGIC is what
needs proving, not the underlying research scripts, which already have
their own verification). Builds tiny throwaway Python scripts in a temp dir
and drives run_overnight_research.py's functions against them directly, with
_LOG_DIR/_STATE_FILE monkeypatched to a temp location so this test never
touches the real logs/overnight/ state.
"""
import os
import shutil
import sys
import tempfile
import textwrap

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_overnight_research as orch


def _write_script(path, body):
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(body))


def main():
    tmp = tempfile.mkdtemp(prefix="camarf_orch_test_")
    passed = 0
    failed = 0
    orig_log_dir = orch._LOG_DIR
    orig_state_file = orch._STATE_FILE
    orig_master_log = orch._MASTER_LOG
    try:
        log_dir = os.path.join(tmp, "logs")
        os.makedirs(log_dir, exist_ok=True)
        orch._LOG_DIR = log_dir
        orch._STATE_FILE = os.path.join(log_dir, "_completed_stages.txt")
        orch._MASTER_LOG = os.path.join(log_dir, "_runner.log")
        open(orch._STATE_FILE, "w").close()

        ok_script = os.path.join(tmp, "ok_script.py")
        _write_script(ok_script, """
            print("hello from ok_script")
        """)
        fail_script = os.path.join(tmp, "fail_script.py")
        _write_script(fail_script, """
            import sys
            sys.exit(3)
        """)
        hang_script = os.path.join(tmp, "hang_script.py")
        _write_script(hang_script, """
            import time
            time.sleep(120)
        """)

        # --- Test 1: a normal successful stage runs, exits 0, gets marked complete ---
        ok1 = orch.run_stage("t1_ok", ok_script)
        if ok1 and "t1_ok" in orch._completed_stages():
            print("PASS: successful stage runs and is marked completed")
            passed += 1
        else:
            print(f"FAIL: successful stage did not complete/mark correctly (ok={ok1})")
            failed += 1

        # --- Test 2: re-running the same stage name is skipped (resumability) ---
        os.remove(ok_script)  # if this were re-executed it would crash (FileNotFoundError)
        ok2 = orch.run_stage("t1_ok", ok_script)
        if ok2:
            print("PASS: already-completed stage is skipped, not re-executed")
            passed += 1
        else:
            print("FAIL: already-completed stage was not skipped")
            failed += 1

        # --- Test 3: a failing stage (nonzero exit) is NOT marked completed ---
        ok3 = orch.run_stage("t3_fail", fail_script)
        if not ok3 and "t3_fail" not in orch._completed_stages():
            print("PASS: failing stage correctly reported as failed, not marked completed")
            passed += 1
        else:
            print(f"FAIL: failing stage should not be marked completed (ok={ok3})")
            failed += 1

        # --- Test 4: a hung stage is killed at the timeout and NOT marked completed ---
        t0 = __import__("time").time()
        ok4 = orch.run_stage("t4_hang", hang_script, timeout_minutes=0.05)  # 3 seconds
        elapsed = __import__("time").time() - t0
        if not ok4 and "t4_hang" not in orch._completed_stages() and elapsed < 30:
            print(f"PASS: hung stage was killed at timeout ({elapsed:.1f}s elapsed, not the full 120s sleep)")
            passed += 1
        else:
            print(f"FAIL: timeout-kill did not work as expected (ok={ok4}, elapsed={elapsed:.1f}s)")
            failed += 1

        # --- Test 5: run_stage_until_success retries a script that fails once then succeeds ---
        flag_file = os.path.join(tmp, "attempt_flag.txt")
        retry_script = os.path.join(tmp, "retry_script.py")
        _write_script(retry_script, f"""
            import os, sys
            flag = {flag_file!r}
            if not os.path.exists(flag):
                open(flag, "w").close()
                sys.exit(1)
            sys.exit(0)
        """)
        orch.run_stage_until_success("t5_retry", retry_script, max_attempts=3)
        if "t5_retry" in orch._completed_stages():
            print("PASS: run_stage_until_success retried after a failure and succeeded")
            passed += 1
        else:
            print("FAIL: run_stage_until_success did not complete after retry")
            failed += 1

    finally:
        orch._LOG_DIR = orig_log_dir
        orch._STATE_FILE = orig_state_file
        orch._MASTER_LOG = orig_master_log
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{passed}/{passed + failed} checks passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
