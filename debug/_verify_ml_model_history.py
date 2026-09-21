"""
Synthetic verification for ml.py's _persist_model_with_history (2026-09-20):
canonical model_stage1.pkl path/behavior stays exactly as before (MLConditioner
._load depends on it, never renamed), and a new, purely-additive timestamped
copy lands under model_dir/history/.

Run: python debug/_verify_ml_model_history.py
"""
import os
import pickle
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ml import _persist_model_with_history

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def test_canonical_path_unchanged():
    tmpdir = tempfile.mkdtemp()
    try:
        payload = {"model": "fake_model_object", "feature_names": ["a", "b"]}
        pkl_path, archive_path = _persist_model_with_history(payload, tmpdir)

        check("canonical.path_is_model_stage1_pkl",
              os.path.basename(pkl_path) == "model_stage1.pkl")
        check("canonical.file_exists", os.path.exists(pkl_path))
        with open(pkl_path, "rb") as f:
            loaded = pickle.load(f)
        check("canonical.content_matches_payload", loaded == payload)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_archive_copy_created():
    tmpdir = tempfile.mkdtemp()
    try:
        payload = {"model": "fake_model_object", "feature_names": ["a", "b"]}
        pkl_path, archive_path = _persist_model_with_history(payload, tmpdir)

        check("archive.path_under_history_subdir",
              os.path.dirname(archive_path) == os.path.join(tmpdir, "history"))
        check("archive.file_exists", os.path.exists(archive_path))
        with open(archive_path, "rb") as f:
            loaded = pickle.load(f)
        check("archive.content_matches_payload", loaded == payload)
        check("archive.filename_has_timestamp",
              "model_stage1_" in os.path.basename(archive_path)
              and os.path.basename(archive_path) != "model_stage1.pkl")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_multiple_calls_do_not_overwrite_history():
    tmpdir = tempfile.mkdtemp()
    try:
        payload1 = {"model": "v1"}
        _, archive1 = _persist_model_with_history(payload1, tmpdir)
        time.sleep(1.1)  # ensure a distinct second-resolution timestamp
        payload2 = {"model": "v2"}
        pkl_path2, archive2 = _persist_model_with_history(payload2, tmpdir)

        check("multi_call.two_distinct_archive_files", archive1 != archive2)
        check("multi_call.both_archive_files_still_exist",
              os.path.exists(archive1) and os.path.exists(archive2))
        with open(pkl_path2, "rb") as f:
            canonical_content = pickle.load(f)
        check("multi_call.canonical_reflects_latest_call", canonical_content == payload2)
        with open(archive1, "rb") as f:
            check("multi_call.first_archive_still_has_v1", pickle.load(f) == payload1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    test_canonical_path_unchanged()
    test_archive_copy_created()
    test_multiple_calls_do_not_overwrite_history()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
