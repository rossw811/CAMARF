"""
Regression test for code-review finding D6 (2026-09-26): DataAligner.align_daily measured the ">50% gap rate ->
exclude" quality gate AFTER forward-filling, so the rate was always ~0 and the gate never fired; and the master
calendar runs to the LATEST date of any asset, so a delisted stock kept a trailing block of forward-filled rows.
Now the gap rate uses the PRE-fill missing mask over the asset's real trading history, and the post-last-real-bar
tail is trimmed (mirroring the existing pre-IPO trim).
Checks: (1) an asset missing 60% of its sessions is excluded; (2) an asset missing ~10% is kept;
(3) a delisted asset's post-delisting tail rows are DATA_GAP (masked), not usable prices.
Run: python debug/_verify_align_daily_gap_gate.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from data import DataAligner

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    cal = DataAligner._get_nyse_calendar("2024-01-02", "2024-12-31")
    rng = np.random.default_rng(0)
    mk = lambda idx: pd.DataFrame({"open": 10.0, "high": 10.0, "low": 10.0, "close": 10 + rng.normal(0, 0.1, len(idx)),
                                   "volume": 1e5}, index=idx)
    sparse = cal[rng.random(len(cal)) > 0.60]          # ~60% of sessions missing
    ok = cal[rng.random(len(cal)) > 0.10]              # ~10% missing
    delisted = cal[cal <= "2024-06-28"]                # stops trading mid-year
    out = DataAligner.align_daily({"SPARSE": mk(sparse), "OK": mk(ok), "GONE": mk(delisted), "FULL": mk(cal)})
    check("sparse_excluded", "SPARSE" not in out, f"kept={sorted(out)}")
    check("ok_kept", "OK" in out)
    # Tail rows are KEPT (trimming would break positional right-alignment, code review A9) but must be
    # DATA_GAP so _clean_close masks them -- never usable as prices. (First draft asserted a trim; revised.)
    from data import GapFlag
    g = out.get("GONE")
    tail = g.loc[g.index > delisted.max()] if g is not None else None
    check("delisted_tail_masked_data_gap", tail is not None and len(tail) > 0 and (tail["gap_flag"] == GapFlag.DATA_GAP).all(),
          f"tail rows {0 if tail is None else len(tail)}, flags {None if tail is None else tail['gap_flag'].value_counts().to_dict()}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
