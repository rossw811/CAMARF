"""
Regression test for DEV-008 (open since 2026-06; fixed 2026-10-05, plan T11): confirmed_pairs_manifest.json is
updated read-modify-write. Writes were atomic, but two concurrent analysis.py runs (e.g. two --timeframes-scoped
runs) could each read the same starting state and the later write silently dropped the other's timeframe update.
Fix: analysis._update_confirmed_manifest does the read-modify-write under an exclusive file lock (file_lock.py:
O_CREAT|O_EXCL lock file, works on Windows and Linux, stale locks broken after a timeout).
Checks (temp dir): 6 processes x 15 rounds, each process owning its own timeframe and writing its symbols; at the end
every timeframe must be present for its symbols. Without the lock the race loses updates (shown by an unlocked
control run); with it none are lost.
Run: python debug/_verify_manifest_lock.py
"""
import json
import multiprocessing as mp
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []
N_PROC, N_ROUNDS = 6, 15


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _worker(args):
    path, k, locked = args
    import time
    import analysis
    for r in range(N_ROUNDS):
        syms = [f"S{k}_{j}" for j in range(3)]
        if locked:
            analysis._update_confirmed_manifest(path, f"TF{k}", syms)
        else:                                   # the old unlocked read-modify-write, for the control
            # unlocked: on Windows the race can also make os.replace / the read fail outright (file open in another
            # process) -- the old code logged that at debug level and lost the update, so count it as lost here too
            try:
                with open(path) as fh:
                    m = json.load(fh)
            except (FileNotFoundError, json.JSONDecodeError, PermissionError):
                m = {}
            for e in m.values():
                if f"TF{k}" in e["tfs"]:
                    e["tfs"].remove(f"TF{k}")
            time.sleep(0.002)                   # widen the race window like a slow disk
            for s in syms:
                m.setdefault(s, {"tfs": [], "added": f"TF{k}"})["tfs"].append(f"TF{k}")
            tmp = f"{path}.tmp.{os.getpid()}"
            with open(tmp, "w") as fh:
                json.dump(m, fh)
            try:
                os.replace(tmp, path)
            except PermissionError:
                pass
    return True


def run(locked):
    d = tempfile.mkdtemp(prefix="manifest_lock_")
    path = os.path.join(d, "confirmed_pairs_manifest.json")
    try:
        with mp.get_context("spawn").Pool(N_PROC) as pool:
            pool.map(_worker, [(path, k, locked) for k in range(N_PROC)])
        m = json.load(open(path))
        missing = [k for k in range(N_PROC) if any(f"TF{k}" not in m.get(f"S{k}_{j}", {}).get("tfs", []) for j in range(3))]
        return missing
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    import analysis
    if not hasattr(analysis, "_update_confirmed_manifest"):
        check("function_exists", False); return finish()
    # The unlocked control is timing-dependent; one attempt missed the race in 2 of 3 full-suite runs (2026-10-07),
    # failing the suite on a non-defect. Retry up to 5 attempts; failing only if the race never shows keeps the
    # evidence that the lock matters without the flake.
    for attempt in range(1, 6):
        lost_unlocked = run(False)
        print(f"control (no lock), attempt {attempt}: timeframes lost = {lost_unlocked}")
        if lost_unlocked:
            break
    lost_locked = run(True)
    check("no_update_lost_with_lock", lost_locked == [], f"lost = {lost_locked}")
    check("control_shows_the_race", len(lost_unlocked) > 0,
          f"(race shown on attempt {attempt} of 5; failing means it never triggered in 5 attempts)")
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
