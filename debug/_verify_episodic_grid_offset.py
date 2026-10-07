"""
Test for the episodic-scan window-grid offset (Ross approved 2026-10-07: grid-phase robustness arm). The D18 report
found 57 of 60 one-arm pairs differ only by where the 10-year windows fall (windows are counted in bars from the
pair's first common date). The robustness arm re-runs Tier 2/3's rolling EG with the grid started at offsets
pipeline_stages.GRID_OFFSETS = (63, 126, 189) bars -- quarter steps of EPISODIC_STEP_BARS (252) -- and counts how many
grids confirm each pair. Tier 1 (full-sample) and Tier 3's candidate list do not depend on the grid and are reused
from the arm's offset-0 run; only the window tests are recomputed, into _gridN outputs.
Checks:
  1. build_rolling_eg_tasks(offset=k): windows start at k, k+step, ...; offset 0 unchanged
  2. run_rolling_eg_pool accepts and forwards offset
  3. `--grid-offset 63` -> suffix _grid63 (exclude arm only -- D18 adopted "exclude"; include + offset is refused,
     no lineage stage is declared for it); outputs = the 4 window files only
     (an offset run must never move/overwrite the shared tier1 / tier3_pairs files); per-run log file name
  4. an undeclared offset (50) or offset >= step is refused; GRID_OFFSETS == step*k//4, each declared as a lineage
     stage
  5. no checkpoint cleanup ignores the run suffix; the lineage log line names the real stage (2026-10-07: both did)
Run: python debug/_verify_episodic_grid_offset.py
"""
import importlib
import inspect
import os
import re
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SRC = os.path.join(ROOT, "research", "wrds_deep_history_episodic_scan.py")
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def load(argv):
    old = sys.argv
    sys.argv = ["x"] + argv
    try:
        sys.modules.pop("research.wrds_deep_history_episodic_scan", None)
        return importlib.import_module("research.wrds_deep_history_episodic_scan")
    finally:
        sys.argv = old


def main():
    m = load([])
    idx = pd.bdate_range("2000-01-03", periods=300)
    rng = np.random.default_rng(0)
    lp = pd.DataFrame({"A": np.cumsum(rng.normal(0, .01, 300)), "B": np.cumsum(rng.normal(0, .01, 300))}, index=idx)
    pairs = [{"symbol_a": "A", "symbol_b": "B"}]
    sig = inspect.signature(m.build_rolling_eg_tasks).parameters
    if "offset" not in sig:
        check("build_tasks_has_offset", False)
    else:
        _, meta0 = m.build_rolling_eg_tasks(pairs, lp, 1, window=100, step=40)
        _, meta15 = m.build_rolling_eg_tasks(pairs, lp, 1, window=100, step=40, offset=15)
        s0 = sorted({t[2] for t in meta0}); s15 = sorted({t[2] for t in meta15})
        check("offset0_unchanged", s0 == [0, 40, 80, 120, 160, 200], s0)
        check("offset15_starts", s15 == [15, 55, 95, 135, 175], s15)
        check("offset15_dates", {t[5] for t in meta15} == {idx[s + 99] for s in s15})
    check("pool_forwards_offset", "offset" in inspect.signature(m.run_rolling_eg_pool).parameters
          and re.search(r"build_rolling_eg_tasks\([^)]*offset=offset", open(SRC, encoding="utf-8").read(), re.S)
          is not None)
    try:
        g = load(["--grid-offset", "63"])
    except SystemExit as e:
        check("grid_offset_accepted", False, str(e)); return finish()
    check("suffix_grid63", getattr(g, "_RUN_SUFFIX", None) == "_grid63", getattr(g, "_RUN_SUFFIX", None))
    try:
        load(["--d18", "include", "--grid-offset", "63"]); check("include_plus_offset_refused", False)
    except SystemExit:
        check("include_plus_offset_refused", True)
    outs = sorted(os.path.basename(p) for p in g._SCAN_OUTPUTS)
    want = sorted(f"wrds_deep_history_episodic_scan_{n}_grid63.parquet"
                  for n in ("tier2_windows", "tier2_confirmed", "tier3_windows", "tier3_confirmed"))
    check("grid_outputs_only_window_files", outs == want, outs)
    check("grid_log_file", os.path.basename(g._log_path()) == "latest_run_wrds_deep_history_episodic_scan_grid63.log")
    for bad in ("50", "252"):
        try:
            load(["--grid-offset", bad]); check(f"offset_{bad}_refused", False)
        except SystemExit:
            check(f"offset_{bad}_refused", True)
    from research import pipeline_stages as ps
    check("grid_offsets_derived", tuple(ps.GRID_OFFSETS) == tuple(m.EPISODIC_STEP_BARS * k // 4 for k in (1, 2, 3)),
          getattr(ps, "GRID_OFFSETS", None))
    stages = ps.pipeline()._stages
    check("grid_stages_declared", all(f"episodic_scan_grid{o}" in stages for o in getattr(ps, "GRID_OFFSETS", ())))
    src = open(SRC, encoding="utf-8").read()
    bare = re.findall(r'clear_checkpoint\("[a-z0-9_]+"\)', src)
    check("checkpoint_cleanup_uses_suffix", not bare, bare)
    check("lineage_log_names_real_stage", "recorded stage 'episodic_scan'\")" not in src)
    # 6. --fresh must only collect THIS run's checkpoints (2026-10-07: the primary's glob checkpoint_tier2_rolling*
    #    also caught checkpoint_tier2_rolling_d18incl_* and moved them into the primary's backup)
    import tempfile, shutil
    d = tempfile.mkdtemp(prefix="ckpt_")
    try:
        names = ["checkpoint_tier2_rolling.parquet", "checkpoint_tier2_rolling.meta",
                 "checkpoint_tier2_rolling_part000001.parquet", "checkpoint_tier2_rolling_d18incl_part000001.parquet",
                 "checkpoint_tier2_rolling_grid63_part000001.parquet", "checkpoint_tier1_fullsample_d18incl.parquet"]
        for n in names:
            open(os.path.join(d, n), "w").close()
        got = {}
        for mod in (m, g):
            mod._OUT_DIR = d
            got[mod._RUN_SUFFIX] = sorted(os.path.basename(p) for p in mod._run_checkpoint_files()) \
                if hasattr(mod, "_run_checkpoint_files") else None
        check("primary_collects_only_its_checkpoints", got[""] == sorted(names[:3]), got[""])
        check("grid_collects_only_its_checkpoints", got["_grid63"] == [names[4]], got["_grid63"])
    finally:
        shutil.rmtree(d, ignore_errors=True)
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
