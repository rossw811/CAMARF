"""
research/grid_phase_robustness.py -- the grid-phase robustness arm's report (Ross approved 2026-10-07).

Why: the D18 comparison (research/d18_arm_comparison.py) found 57 of 60 one-arm pairs differ only by where the
episodic scan's 10-year windows fall -- windows are counted in bars from each pair's first common date, so any
change in a pair's aligned history shifts every window. A single-window confirmation can hinge on that placement
(CMA/ZION: p 8.6e-10 at the window ending 2018-12-07, 0.045 four months earlier).

Arm: the D18-exclude scan (adopted 2026-10-07) re-run with the window grid started 63, 126 and 189 bars later
(`--grid-offset`, research/pipeline_stages.GRID_OFFSETS); Tier 1 and Tier 3's candidate list are shared with the
offset-0 run. Each grid is a complete scan with its own BH-FDR family.

PRE-DECLARED metric (fixed 2026-10-07, before any offset run finished): a pair is GRID-ROBUST if it is confirmed
under every grid (offsets 0, 63, 126, 189). Reported per tier: offset-0 confirmed count; how many of those are
grid-robust (and the share); pairs confirmed only by shifted grids; distribution of the number of confirming grids;
per pair, which grids confirm it. Whether the grid-robust set replaces the offset-0 set downstream is Ross's call
after this report -- until then it is a comparison arm.
Usage:  python research/grid_phase_robustness.py      (after all three offset runs)
Output: output/research/grid_phase_robustness.parquet (one row per pair per tier)
Synthetic check: debug/_verify_grid_phase_robustness.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_RES = os.path.join("output", "research")
OUT = os.path.join(_RES, "grid_phase_robustness.parquet")


def count_grids(confirmed_by_offset: dict) -> pd.DataFrame:
    """{offset: confirmed DataFrame (symbol_a, symbol_b)} -> one row per pair: confirmed_in (sorted offsets), n_grids."""
    seen = {}
    for off in sorted(confirmed_by_offset):
        c = confirmed_by_offset[off]
        if c is None:
            raise ValueError(f"no confirmed set for grid offset {off}")
        for a, b in zip(c["symbol_a"], c["symbol_b"]):
            seen.setdefault(tuple(sorted((a, b))), set()).add(off)
    rows = [{"symbol_a": k[0], "symbol_b": k[1], "confirmed_in": sorted(v), "n_grids": len(v)}
            for k, v in sorted(seen.items())]
    return pd.DataFrame(rows, columns=["symbol_a", "symbol_b", "confirmed_in", "n_grids"])


def summary(per_pair: pd.DataFrame, offsets) -> dict:
    offsets = tuple(sorted(offsets))
    base = offsets[0]
    in0 = per_pair["confirmed_in"].apply(lambda v: base in v)
    robust = per_pair["n_grids"] == len(offsets)
    n0 = int(in0.sum())
    return {"offset0_confirmed": n0, "grid_robust": int((robust & in0).sum()),
            "grid_robust_share_of_offset0": float((robust & in0).sum() / n0) if n0 else float("nan"),
            "shifted_only": int((~in0).sum()),
            "n_grids_distribution": {int(k): int(v) for k, v in per_pair["n_grids"].value_counts().sort_index(
                ascending=False).items()}}


def main():
    from research.pipeline_stages import GRID_OFFSETS
    offsets = (0,) + tuple(GRID_OFFSETS)
    out = []
    for tier in (2, 3):
        conf = {}
        for off in offsets:
            p = os.path.join(_RES, f"wrds_deep_history_episodic_scan_tier{tier}_confirmed"
                                   f"{'' if off == 0 else f'_grid{off}'}.parquet")
            if not os.path.exists(p):
                raise SystemExit(f"missing {p} -- run the scan with --grid-offset {off} first")
            conf[off] = pd.read_parquet(p, columns=["symbol_a", "symbol_b"])
        per = count_grids(conf).assign(tier=tier)
        s = summary(per, offsets)
        print(f"Tier {tier}: offset-0 confirmed {s['offset0_confirmed']}; grid-robust {s['grid_robust']} "
              f"({s['grid_robust_share_of_offset0']:.1%}); confirmed only by shifted grids {s['shifted_only']}; "
              f"pairs by number of confirming grids {s['n_grids_distribution']}")
        out.append(per)
    rep = pd.concat(out, ignore_index=True)
    rep["confirmed_in"] = rep["confirmed_in"].apply(lambda v: ",".join(map(str, v)))
    rep.to_parquet(OUT)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
