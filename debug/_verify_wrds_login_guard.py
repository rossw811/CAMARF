"""
WRDS login guard (2026-10-11/12): unattended connection attempts with a stale pgpass.conf password counted as failed
logins and locked Ross's WRDS account (2026-10-10 17:46 and two attempts 2026-10-11, with no one there to approve or
re-enter a password). Written failing-first. Checks:
  1. data_wrds._connect() refuses (RuntimeError, before importing/calling wrds) when stdin is not a terminal and
     CAMARF_WRDS_UNATTENDED != "1"
  2. with CAMARF_WRDS_UNATTENDED=1 it proceeds to wrds.Connection (stubbed here -- no network)
  3. with a terminal it proceeds (stubbed)
  4. the session server never reconnects on its own: no _connect() call inside the keepalive loop
Run: python debug/_verify_wrds_login_guard.py
"""
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


class _TTY:
    def __init__(self, tty): self._t = tty
    def isatty(self): return self._t


def main():
    import data_wrds as dw
    calls = []
    fake = types.ModuleType("wrds")
    fake.Connection = lambda **kw: calls.append(kw) or "conn"
    sys.modules["wrds"] = fake
    real_stdin = sys.stdin
    os.environ.pop("CAMARF_WRDS_UNATTENDED", None)
    try:
        sys.stdin = _TTY(False)
        try:
            dw._connect(); check("refuses_unattended", False, "connected")
        except RuntimeError as e:
            check("refuses_unattended", not calls, str(e)[:80])
        os.environ["CAMARF_WRDS_UNATTENDED"] = "1"
        check("override_allows", dw._connect() == "conn" and len(calls) == 1)
        os.environ.pop("CAMARF_WRDS_UNATTENDED")
        sys.stdin = _TTY(True)
        check("terminal_allows", dw._connect() == "conn" and len(calls) == 2)
    finally:
        sys.stdin = real_stdin
    src = open(os.path.join(ROOT, "research", "wrds_session_server.py"), encoding="utf-8").read()
    loop = src[src.index("while not os.path.exists"):]
    loop = loop[:loop.index("name = jobs[0]")]
    check("server_no_auto_reconnect", "_connect()" not in loop)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
