# =============================================================================
# Verify: BiasAuditLog.save and AnalysisPipeline._save_tf_results's
# confirmed_pairs_manifest.json write are now atomic (temp file + os.replace),
# not a direct open(path, "w") -- backlog item #5 (docs/HANDOFF.md, 2026-09-12
# overnight brainstorm), same non-atomic-write bug class found and fixed live
# in universe_loader.py's memo cache this session. Found via a grep-based
# audit of every open(path, "w")-style write to a file more than one script
# reads/writes.
#
# The manifest write's underlying read-modify-write RACE (two concurrent
# writers can still clobber each other's TF update) is NOT fixed here --
# that needs real file locking, disclosed as a known residual limitation in
# the code's own comment, not silently claimed as fully solved.
# =============================================================================
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import AnalysisPipeline, BiasAuditLog, FilterFunnel

checks = []


def check(name, cond, detail=""):
    checks.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


tmp = tempfile.mkdtemp(prefix="camarf_atomic_write_test_")
try:
    # --- BiasAuditLog.save ---
    audit_path = os.path.join(tmp, "bias_audit.json")
    orig_entries = list(BiasAuditLog._entries)
    try:
        BiasAuditLog._entries = []
        BiasAuditLog.record(
            bias_type="test", classification="test", mechanism="m", remedy="r",
            scope="s", residual_risk="rr",
        )
        BiasAuditLog.save(audit_path)
        check("bias_audit.file_written", os.path.exists(audit_path))
        with open(audit_path) as f:
            entries = json.load(f)
        check("bias_audit.content_correct", len(entries) == 1 and entries[0]["bias_type"] == "test",
              f"got {entries}")
        leftover = [f for f in os.listdir(tmp) if ".tmp." in f]
        check("bias_audit.no_leftover_tmp_file", not leftover, f"found {leftover}")
    finally:
        BiasAuditLog._entries = orig_entries

    # --- confirmed_pairs_manifest.json write (via _save_tf_results) ---
    manifest_path = os.path.join(tmp, "confirmed_pairs_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump({"AAPL": {"tfs": ["1h"], "added": "1h"}}, f)

    AnalysisPipeline._save_tf_results(
        tf_label="1D", pairs=[], trios=[], regimes=[], cross=[],
        calibration={}, per_bar_by_pair=None, funnel=FilterFunnel(tf_label="1D"),
        manifest_path_override=manifest_path,
    )
    with open(manifest_path) as f:
        manifest_after = json.load(f)
    check("manifest.preserves_other_tf_entry_on_empty_1D_run",
          manifest_after == {"AAPL": {"tfs": ["1h"], "added": "1h"}}, f"got {manifest_after}")
    leftover_manifest = [f for f in os.listdir(tmp) if ".tmp." in f]
    check("manifest.no_leftover_tmp_file", not leftover_manifest, f"found {leftover_manifest}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

n_pass = sum(1 for _, ok, _ in checks if ok)
print(f"\n{n_pass}/{len(checks)} checks passed")
sys.exit(0 if n_pass == len(checks) else 1)
