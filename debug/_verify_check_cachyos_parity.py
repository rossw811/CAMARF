"""
Synthetic verification for debug/_check_cachyos_parity.py -- mocks the SSH
call entirely (no network, no real CachyOS needed to verify this script's
own comparison logic).

Run: python debug/_verify_check_cachyos_parity.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from debug._check_cachyos_parity import check_parity, _local_hash

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _mock_ssh_result(stdout_text):
    m = mock.Mock()
    m.stdout = stdout_text
    m.stderr = ""
    return m


def test_local_hash_ignores_line_endings():
    tmpdir = tempfile.mkdtemp()
    try:
        p_lf = os.path.join(tmpdir, "a.py")
        p_crlf = os.path.join(tmpdir, "b.py")
        with open(p_lf, "wb") as f:
            f.write(b"line1\nline2\n")
        with open(p_crlf, "wb") as f:
            f.write(b"line1\r\nline2\r\n")
        check("hash.crlf_and_lf_same_content_hash_equal",
              _local_hash(p_lf) == _local_hash(p_crlf))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_check_parity_classifies_in_sync_diverged_missing():
    tmpdir = tempfile.mkdtemp()
    try:
        paths = []
        for name, content in [("same.py", b"identical content\n"),
                               ("diff.py", b"local version\n"),
                               ("gone.py", b"exists only locally\n")]:
            p = os.path.join(tmpdir, name)
            with open(p, "wb") as f:
                f.write(content)
            paths.append(p)

        same_hash = _local_hash(paths[0])
        fake_remote_stdout = (
            f"{paths[0]} {same_hash}\n"
            f"{paths[1]} 0000000000000000000000000000000000000000000000000000000000000000\n"
            f"{paths[2]} MISSING\n"
        )
        with mock.patch("debug._check_cachyos_parity.subprocess.run",
                         return_value=_mock_ssh_result(fake_remote_stdout)):
            result = check_parity(paths)

        check("parity.identical_file_in_sync", paths[0] in result["in_sync"])
        check("parity.different_content_diverged", paths[1] in result["diverged"])
        check("parity.missing_remote_flagged", paths[2] in result["missing_remote"])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_check_parity_handles_local_read_error():
    with mock.patch("debug._check_cachyos_parity.subprocess.run",
                     return_value=_mock_ssh_result("")):
        result = check_parity(["/nonexistent/path/does_not_exist.py"])
    check("parity.local_read_error_captured", len(result["local_error"]) == 1)


if __name__ == "__main__":
    test_local_hash_ignores_line_endings()
    test_check_parity_classifies_in_sync_diverged_missing()
    test_check_parity_handles_local_read_error()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
