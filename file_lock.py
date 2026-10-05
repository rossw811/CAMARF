"""
file_lock.py -- a minimal cross-platform exclusive lock for read-modify-write of small shared files (DEV-008,
2026-10-05: confirmed_pairs_manifest.json lost concurrent timeframe updates).

The lock is a sibling file `<path>.lock` created with O_CREAT | O_EXCL (atomic on Windows and POSIX). A lock older
than `stale_after` seconds is assumed abandoned by a crashed process and removed (logged). Waiting is bounded by
`timeout`; on timeout a TimeoutError is raised -- never a silent unlocked write.

    from file_lock import exclusive_lock
    with exclusive_lock(path):
        ...read, modify, write path...
"""
import contextlib
import logging
import os
import time

log = logging.getLogger("file_lock")


@contextlib.contextmanager
def exclusive_lock(path: str, timeout: float = 120.0, stale_after: float = 600.0, poll: float = 0.02):
    lock = f"{path}.lock"
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {time.time():.3f}".encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(lock)
            except OSError:
                continue                                    # released between our attempts
            if age > stale_after:
                log.warning("file_lock: removing stale lock %s (%.0fs old)", lock, age)
                with contextlib.suppress(OSError):
                    os.remove(lock)
                continue
            if time.time() > deadline:
                raise TimeoutError(f"could not lock {path} within {timeout:.0f}s ({lock} held)")
            time.sleep(poll)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            os.remove(lock)
