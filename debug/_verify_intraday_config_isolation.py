"""
Regression test for code review R1.9 (verified 2026-10-07, fixed the same day): research/intraday_episodic_scan.py
named outputs and checkpoints by timeframe only and SKIPS a tier whose output exists, while its lineage stage records
only the timeframe -- so a run with a different --window-config or --tier3-threshold silently reused the default
run's tiers. Fix: a non-default config gets its own suffix on outputs and checkpoints (_config_suffix); the default
keeps the original names; the stale guard only sees its own run's files (exact patterns) and, for a non-default
config (no lineage stage), refuses to resume from existing outputs unless --fresh.
Checks: default config -> "" suffix; other configs -> distinct suffixes; the default guard ignores a suffixed run's
files and vice versa; a non-default run with existing outputs and no --fresh is refused; --fresh moves only its own
files; run_scan builds its paths and checkpoint ids with the suffix (source check).
Run: python debug/_verify_intraday_config_isolation.py
"""
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    import research.intraday_episodic_scan as m
    if not hasattr(m, "_config_suffix"):
        check("suffix_helper_exists", False); return finish()
    s0 = m._config_suffix("fixed_min_overlap_2x", 0.80)
    s1 = m._config_suffix("fixed_min_overlap_1x", 0.80)
    s2 = m._config_suffix("fixed_min_overlap_2x", 0.70)
    check("default_no_suffix", s0 == "", s0)
    check("non_default_distinct", s1 and s2 and s1 != s2, (s1, s2))
    d = tempfile.mkdtemp(prefix="intraday_iso_")
    try:
        m._OUT_DIR = d
        default_files = ["intraday_episodic_scan_1h_tier2_windows.parquet", "checkpoint_intraday_1h_tier2_part000001.parquet"]
        other_files = [f"intraday_episodic_scan_1h{s1}_tier2_windows.parquet",
                       f"checkpoint_intraday_1h{s1}_tier2_part000001.parquet"]
        for f in default_files + other_files:
            open(os.path.join(d, f), "w").close()
        own0 = sorted(os.path.basename(p) for p in m._run_files("1h", s0))
        own1 = sorted(os.path.basename(p) for p in m._run_files("1h", s1))
        check("default_sees_only_its_files", own0 == sorted(default_files), own0)
        check("suffixed_sees_only_its_files", own1 == sorted(other_files), own1)
        old = sys.argv
        sys.argv = ["x"]
        try:
            m._guard_stale_resume("1h", s1); check("non_default_refused_without_fresh", False)
        except SystemExit:
            check("non_default_refused_without_fresh", True)
        sys.argv = ["x", "--fresh"]
        try:
            m._guard_stale_resume("1h", s1)
        finally:
            sys.argv = old
        left = sorted(x for x in os.listdir(d) if not x.startswith("_intraday"))
        check("fresh_moves_only_own_files", left == sorted(default_files), left)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    src = open(os.path.join(ROOT, "research", "intraday_episodic_scan.py"), encoding="utf-8").read()
    check("paths_use_suffix", re.search(r"intraday_episodic_scan_\{tf_label\}\{suffix\}_\{k\}", src) is not None)
    check("checkpoints_use_suffix", 'checkpoint_id=f"intraday_{tf_label}{suffix}_tier2"' in src
          and 'checkpoint_id=f"intraday_{tf_label}{suffix}_tier3"' in src)
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
