"""
Regression test for the D18-arm logging bug in research/wrds_deep_history_episodic_scan.py (found 2026-10-07 on the
CachyOS chain run): (1) the log file name ignored the arm, so the `--d18 include` run's FileHandler (mode="w")
overwrote the primary run's latest_run_wrds_deep_history_episodic_scan.log -- the primary run's full log was lost;
(2) the "Saved ->" lines printed hard-coded paths without the `_d18incl` suffix, so the sensitivity log named the
primary arm's files. The parquet outputs themselves were always written to the correct suffixed paths.
Checks: under each arm the log file name carries the arm suffix (primary keeps the original name), and every
"Saved ->" message in the source is built from the arm-aware output path, not a literal file name.
Run: python debug/_verify_episodic_scan_arm_logging.py
"""
import importlib
import logging
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SRC = os.path.join(ROOT, "research", "wrds_deep_history_episodic_scan.py")
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def log_file_for(arm):
    argv = sys.argv
    sys.argv = ["x", "--d18", arm]
    try:
        sys.modules.pop("research.wrds_deep_history_episodic_scan", None)
        m = importlib.import_module("research.wrds_deep_history_episodic_scan")
        if hasattr(m, "_log_path"):
            return os.path.basename(m._log_path())
        # old code: no helper -- read what _setup_logging would attach, without writing the real file
        before = list(m.log.handlers)
        orig = logging.FileHandler
        seen = []

        class _Spy(logging.NullHandler):
            def __init__(self, path, *a, **k):
                super().__init__(); seen.append(os.path.basename(path))
        logging.FileHandler = _Spy
        try:
            m._setup_logging()
        finally:
            logging.FileHandler = orig
            m.log.handlers = before
        return seen[0] if seen else None
    finally:
        sys.argv = argv


def main():
    ex, inc = log_file_for("exclude"), log_file_for("include")
    check("primary_log_keeps_name", ex == "latest_run_wrds_deep_history_episodic_scan.log", ex)
    check("sensitivity_log_has_suffix", inc == "latest_run_wrds_deep_history_episodic_scan_d18incl.log", inc)
    check("arms_never_share_a_log", ex != inc, f"{ex} vs {inc}")
    src = open(SRC, encoding="utf-8").read()
    saved = [ln.strip() for ln in src.splitlines() if "Saved ->" in ln]
    literal = [ln for ln in saved if re.search(r"wrds_deep_history_episodic_scan_tier", ln)]
    check("saved_messages_found", len(saved) >= 3, f"{len(saved)}")
    check("no_saved_message_hardcodes_a_file_name", not literal, literal)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
