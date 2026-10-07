"""
Synthetic check for research/grid_phase_robustness.py (2026-10-07, written BEFORE the module). Pre-declared metric
(Ross approved the robustness arm 2026-10-07; definition fixed before any offset run finished): a pair is
GRID-ROBUST if the episodic scan confirms it under every window grid (offsets 0, 63, 126, 189 bars). Per tier the
report gives: per pair the grids that confirm it and their count; the offset-0 confirmed count and how many of those
are grid-robust; pairs confirmed ONLY by shifted grids; the distribution of the count.
Construction (4 grids): P1 in all 4; P2 in 0 and 63; P3 in 0 only; P4 in 63 and 126 (not 0); P5 in 189 only.
Pair order inside a file must not matter (B/A == A/B).
Expected: offset-0 confirmed 3 (P1-P3); grid-robust 1 (P1) -> share 1/3; shifted-only 2 (P4, P5);
counts {4: 1, 2: 2, 1: 2}; a missing offset file is an error, not a silent 3-grid result.
Run: python debug/_verify_grid_phase_robustness.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def df(pairs):
    return pd.DataFrame(pairs, columns=["symbol_a", "symbol_b"])


def main():
    try:
        import research.grid_phase_robustness as g
    except ImportError as e:
        check("module_exists", False, str(e)); return finish()
    conf = {0: df([("A", "B"), ("C", "D"), ("E", "F")]),
            63: df([("B", "A"), ("C", "D"), ("G", "H")]),
            126: df([("A", "B"), ("H", "G")]),
            189: df([("A", "B"), ("I", "J")])}
    per = g.count_grids(conf)
    k = {(r.symbol_a, r.symbol_b): (r.n_grids, tuple(r.confirmed_in)) for r in per.itertuples()}
    check("P1_all_grids", k.get(("A", "B")) == (4, (0, 63, 126, 189)), k.get(("A", "B")))
    check("P2_two_grids", k.get(("C", "D")) == (2, (0, 63)))
    check("P4_order_insensitive", k.get(("G", "H")) == (2, (63, 126)), k.get(("G", "H")))
    s = g.summary(per, offsets=(0, 63, 126, 189))
    check("offset0_confirmed", s["offset0_confirmed"] == 3, s)
    check("grid_robust", s["grid_robust"] == 1 and abs(s["grid_robust_share_of_offset0"] - 1 / 3) < 1e-12)
    check("shifted_only", s["shifted_only"] == 2)
    check("count_distribution", s["n_grids_distribution"] == {4: 1, 2: 2, 1: 2}, s["n_grids_distribution"])
    try:
        g.count_grids({0: conf[0], 63: conf[63], 126: None, 189: conf[189]})
        check("missing_offset_is_error", False)
    except (ValueError, TypeError):
        check("missing_offset_is_error", True)
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
