"""
research/wrds_session_server.py -- hold ONE WRDS connection open and run queued job scripts against it.

Why: every new WRDS connection may need a Duo approval. Running this once while someone can approve lets later WRDS
work proceed unattended on the same connection.

Protocol: drop a Python file into output/wrds_jobs/queue/. It is exec'd with `db` (the open wrds.Connection),
`log` (a function that appends to the job's log) and `ROOT` (project root) in scope. Its stdout/stderr and a final
status line go to output/wrds_jobs/done/<name>.log, and the script moves to done/ (or failed/ on exception).
Every KEEPALIVE_SEC with no job running, `select 1` keeps the connection alive; if that fails, one silent reconnect
is attempted (works only while the Duo "remember this device" window is valid) and the outcome is logged.
Status: output/wrds_jobs/server.log. Stop: create output/wrds_jobs/STOP.
Usage: python research/wrds_session_server.py
"""
import contextlib
import io
import os
import shutil
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import data_wrds as dw

_BASE = os.path.join(ROOT, "output", "wrds_jobs")
_Q, _DONE, _FAIL = (os.path.join(_BASE, d) for d in ("queue", "done", "failed"))
KEEPALIVE_SEC = 240


def _slog(msg):
    with open(os.path.join(_BASE, "server.log"), "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    print(msg, flush=True)


def _connect():
    db = dw._connect()
    db.connection.exec_driver_sql("SET statement_timeout = 0")
    return db


def main():
    for d in (_Q, _DONE, _FAIL):
        os.makedirs(d, exist_ok=True)
    _slog("connecting to WRDS (approve the Duo push if prompted)...")
    db = _connect()
    _slog("CONNECTED")
    last_ping = time.time()
    while not os.path.exists(os.path.join(_BASE, "STOP")):
        jobs = sorted(f for f in os.listdir(_Q) if f.endswith(".py"))
        if not jobs:
            if time.time() - last_ping > KEEPALIVE_SEC:
                try:
                    db.raw_sql("select 1 as ok")
                except Exception as e:
                    _slog(f"keepalive failed ({e}); trying one reconnect")
                    try:
                        db = _connect(); _slog("RECONNECTED")
                    except Exception as e2:
                        _slog(f"RECONNECT FAILED ({e2}) -- a new Duo approval is needed; server stopping")
                        return
                last_ping = time.time()
            time.sleep(5)
            continue
        name = jobs[0]
        src = os.path.join(_Q, name)
        out = io.StringIO()
        _slog(f"job start {name}")
        t0 = time.time()
        ok = True
        with open(src, encoding="utf-8") as f:
            code = f.read()

        def log(msg, _out=out):
            _out.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
            with open(os.path.join(_DONE, name + ".progress"), "a", encoding="utf-8") as pf:
                pf.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                exec(compile(code, src, "exec"), {"db": db, "log": log, "ROOT": ROOT, "__name__": "__wrds_job__"})
        except Exception:
            ok = False
            out.write(traceback.format_exc())
        dest = _DONE if ok else _FAIL
        with open(os.path.join(dest, name + ".log"), "w", encoding="utf-8") as f:
            f.write(out.getvalue())
            f.write(f"\n=== {'OK' if ok else 'FAILED'} in {time.time() - t0:.0f}s ===\n")
        shutil.move(src, os.path.join(dest, name))
        _slog(f"job {'OK' if ok else 'FAILED'} {name} ({time.time() - t0:.0f}s)")
        last_ping = time.time()
    _slog("STOP file found -- exiting")


if __name__ == "__main__":
    main()
