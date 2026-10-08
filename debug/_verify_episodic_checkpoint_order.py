"""
Regression test for code review R1.7 (verified 2026-10-07, fixed the same day): wrds_deep_history_episodic_scan.py
deleted the Tier 2 / Tier 3 rolling-EG checkpoints BEFORE the windows file was written (Tier 3: also before the BH
step over ~7-9M rows), so a memory kill there lost the whole pass (~31 h for Tier 3) with nothing on disk to resume
from. Rule: a tier's checkpoint is cleared only after that tier's windows parquet has been written.
Check (source order inside main()): for tier 2 and tier 3, the clear_checkpoint("tierN_rolling"...) call comes after
the tierN windows .to_parquet(...) call.
Run: python debug/_verify_episodic_checkpoint_order.py
"""
import os
import re
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research",
                   "wrds_deep_history_episodic_scan.py")
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    lines = open(SRC, encoding="utf-8").read().splitlines()
    for t in (2, 3):
        clear = [i for i, l in enumerate(lines) if re.search(rf'clear_checkpoint\("tier{t}_rolling"', l)]
        save = [i for i, l in enumerate(lines) if re.search(rf"to_parquet\(_tier{t}_windows_path", l)]
        check(f"tier{t}_found", len(clear) == 1 and len(save) == 1, f"clear {clear} save {save}")
        if len(clear) == 1 and len(save) == 1:
            check(f"tier{t}_checkpoint_cleared_after_windows_saved", clear[0] > save[0],
                  f"clear line {clear[0] + 1}, save line {save[0] + 1}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
