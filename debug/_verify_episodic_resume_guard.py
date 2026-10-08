"""
Test for wrds_deep_history_episodic_scan._guard_stale_resume (code review R1.8 recheck, 2026-10-07): resume caches
were not keyed on inputs/params, so a relaunch could resume from outputs/checkpoints made on different data or code.
The 2026-09-27 lineage guard is the fix, but it had no test. Checks (temp output dir, a fake lineage stage):
  1. stale lineage + existing output, no --fresh -> SystemExit (refuses to resume), nothing moved;
  2. stale + --fresh -> every existing output/checkpoint MOVED (not deleted) into a timestamped backup dir;
  3. up-to-date lineage -> returns, files left in place;
  4. no existing outputs -> returns without consulting lineage.
Run: python debug/_verify_episodic_resume_guard.py
"""
import importlib
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


class Stage:
    def __init__(self, ok):
        self.ok, self.calls = ok, 0

    def status(self):
        self.calls += 1
        return {"up_to_date": self.ok, "reason": "code changed: research/wrds_deep_history_episodic_scan.py"}


def load(argv):
    old = sys.argv
    sys.argv = ["x"] + argv
    try:
        sys.modules.pop("research.wrds_deep_history_episodic_scan", None)
        return importlib.import_module("research.wrds_deep_history_episodic_scan")
    finally:
        sys.argv = old


def setup(m, d, with_files=True):
    m._OUT_DIR = d
    m._SCAN_OUTPUTS = [os.path.join(d, f"wrds_deep_history_episodic_scan_{n}.parquet") for n in ("tier1", "tier2_windows")]
    if with_files:
        open(m._SCAN_OUTPUTS[0], "w").close()
        open(os.path.join(d, "checkpoint_tier2_rolling_part000001.parquet"), "w").close()


def main():
    d = tempfile.mkdtemp(prefix="resume_guard_")
    try:
        m = load([])
        setup(m, d)
        old_argv = sys.argv
        sys.argv = ["x"]
        try:
            m._guard_stale_resume(Stage(False)); check("stale_refused", False, "returned")
        except SystemExit:
            check("stale_refused", True)
        finally:
            sys.argv = old_argv
        check("nothing_moved_when_refused", os.path.exists(m._SCAN_OUTPUTS[0]))
        sys.argv = ["x", "--fresh"]
        try:
            m._guard_stale_resume(Stage(False))
        finally:
            sys.argv = old_argv
        bk = [x for x in os.listdir(d) if x.startswith("_episodic_scan_backup_")]
        moved = os.listdir(os.path.join(d, bk[0])) if bk else []
        check("fresh_moves_to_backup", len(bk) == 1 and sorted(moved) == sorted(
            ["wrds_deep_history_episodic_scan_tier1.parquet", "checkpoint_tier2_rolling_part000001.parquet"]), moved)
        check("fresh_left_nothing_behind", not os.path.exists(m._SCAN_OUTPUTS[0]))
        setup(m, d)
        st = Stage(True)
        m._guard_stale_resume(st)
        check("up_to_date_resumes", os.path.exists(m._SCAN_OUTPUTS[0]) and st.calls == 1)
        e = tempfile.mkdtemp(prefix="resume_guard_empty_")
        try:
            setup(m, e, with_files=False)
            st = Stage(False)
            m._guard_stale_resume(st)
            check("no_outputs_no_lineage_check", st.calls == 0)
        finally:
            shutil.rmtree(e, ignore_errors=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
