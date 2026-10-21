"""
X-C17 (2026-10-20): the "flaky" _verify_manifest_lock failure (saved output, output/verify_runs/last_failures) was a
real bug in file_lock.exclusive_lock: on Windows, os.open(O_CREAT|O_EXCL) on a lock file that another process is
deleting raises PermissionError (delete pending), not FileExistsError; the lock let it propagate and the caller crashed
instead of waiting. Checks (os.open patched): a transient PermissionError is retried and the lock is then acquired;
a PermissionError that persists past the timeout raises TimeoutError, never an unlocked write.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import file_lock  # noqa: E402

real_open = os.open
with tempfile.TemporaryDirectory() as td:
    path = os.path.join(td, "m.json")
    calls = {"n": 0}

    def flaky_open(p, flags, *a):
        if p.endswith(".lock") and calls["n"] < 3:
            calls["n"] += 1
            raise PermissionError(13, "Permission denied (delete pending)", p)
        return real_open(p, flags, *a)

    file_lock.os.open = flaky_open
    try:
        with file_lock.exclusive_lock(path, timeout=5, poll=0.001):
            ok = os.path.exists(path + ".lock")
        check("transient PermissionError retried, lock acquired", ok and calls["n"] == 3, f"attempts {calls['n']}")
    except Exception as e:  # noqa: BLE001
        check("transient PermissionError retried, lock acquired", False, f"{type(e).__name__}: {e}")

    def always_denied(p, flags, *a):
        if p.endswith(".lock"):
            raise PermissionError(13, "Permission denied", p)
        return real_open(p, flags, *a)

    file_lock.os.open = always_denied
    try:
        with file_lock.exclusive_lock(path, timeout=0.05, poll=0.001):
            pass
        check("persistent PermissionError -> TimeoutError", False, "entered the lock")
    except TimeoutError:
        check("persistent PermissionError -> TimeoutError", True)
    except Exception as e:  # noqa: BLE001
        check("persistent PermissionError -> TimeoutError", False, f"{type(e).__name__}")
    finally:
        file_lock.os.open = real_open
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(1 if failed else 0)
