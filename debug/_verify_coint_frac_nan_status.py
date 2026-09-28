"""
Regression test for code-review finding A6/S10 (confirmed 2026-09-28, inconsistency sweep C6): the coint_fraction
filter kept every pair whose fraction was NaN (`not np.isfinite(cf) or cf >= MIN_COINT_FRAC`), and NaN had three
meanings -- too little history for one window (untestable), a CRASHED rolling test (the worker turned any exception
into NaN), or a pair never computed (its log prices could not be built). A crashed test therefore passed the
stability filter. The same filter was duplicated in analysis.py and pit_wfa.py with a silent getattr default of
0.40 (config value 0.70).
Fix: _rolling_coint_worker reports a status; one shared decision function (AnalysisPipeline.coint_frac_decision)
used by both call sites: pass (fraction >= threshold), override (secondary evidence), untestable_kept (insufficient
history -- kept, counted), excluded (below threshold, crashed, no valid windows, not computed).
Checks:
  1. worker: a normal pair -> status ok; too-short history -> insufficient_history; forced exception -> error;
  2. decision: 0.8 pass; 0.3 excluded (no override); NaN+error excluded; NaN+insufficient_history kept;
     NaN+not_computed excluded; NaN with no status (legacy object) excluded;
  3. the threshold is read from Config.UNIVERSE.MIN_COINT_FRAC directly (no silent default).
Run: python debug/_verify_coint_frac_nan_status.py
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

import analysis
from analysis import AnalysisPipeline, _rolling_coint_worker
from config import Config

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    rng = np.random.default_rng(0)
    x = np.cumsum(rng.normal(0, 0.01, 1500)) + 4
    y = 0.8 * x + rng.normal(0, 0.005, 1500)
    ok = _rolling_coint_worker(("A", "B", x, y, 252, 63, "1D"))
    short = _rolling_coint_worker(("A", "B", x[:200], y[:200], 252, 63, "1D"))
    bad = _rolling_coint_worker(("A", "B", x, None, 252, 63, "1D"))
    check("worker_status_ok", ok.get("status") == "ok" and np.isfinite(ok["fraction"]), f"{ok.get('status')}")
    check("worker_status_insufficient", short.get("status") == "insufficient_history", f"{short.get('status')}")
    check("worker_status_error", str(bad.get("status", "")).startswith("error"), f"{bad.get('status')}")

    thr = Config.UNIVERSE.MIN_COINT_FRAC
    mk = lambda cf, st=None: SimpleNamespace(coint_fraction_rolling=cf, coint_fraction_status=st)
    orig = AnalysisPipeline.passes_coint_frac_secondary_evidence
    AnalysisPipeline.passes_coint_frac_secondary_evidence = staticmethod(lambda p: False)
    try:
        d = AnalysisPipeline.coint_frac_decision
        check("decision_pass", d(mk(thr + 0.1, "ok")) == "pass")
        check("decision_below_excluded", d(mk(thr - 0.3, "ok")) == "excluded")
        check("decision_crash_excluded", d(mk(np.nan, "error: boom")) == "excluded")
        check("decision_untestable_kept", d(mk(np.nan, "insufficient_history")) == "untestable_kept")
        check("decision_not_computed_excluded", d(mk(np.nan, "not_computed")) == "excluded")
        check("decision_no_status_nan_excluded", d(SimpleNamespace(coint_fraction_rolling=np.nan)) == "excluded")
    finally:
        AnalysisPipeline.passes_coint_frac_secondary_evidence = orig
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "analysis.py"),
               encoding="utf-8").read()
    check("no_silent_threshold_default", 'getattr(Config.UNIVERSE, "MIN_COINT_FRAC", 0.40)' not in src)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
