"""
Crashed EG tests must stay in BH's m in the discovery scan (2026-10-10; found while re-deriving PAPER_MAGNITUDE M-039,
"both-directions max ... identical to CointScanner.scan"). Production's rule (analysis._combine_eg_directions, code
review A1/S2): a test that CRASHED was attempted, so it enters BH with p = 1.0; only "insufficient_overlap" (never a
real test) is excluded. research/wrds_deep_history_episodic_scan.py dropped both kinds on every path, so each crash
silently shrank m and loosened every BH threshold. Written failing-first. Checks:
  1. _window_row: ok -> its p; insufficient_overlap -> None; any other error -> p = 1.0 (flagged crashed)
  2. Tier 1 full-sample path combines directions with analysis._combine_eg_directions (source check)
  3. episodic_fraction counts a crashed window as a non-significant test (p = 1.0), not as no test
Run: python debug/_verify_episodic_crash_in_bh_m.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.argv = [sys.argv[0]]
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    import numpy as np
    import research.wrds_deep_history_episodic_scan as scan
    meta = ("A", "B", 0, "ab", "2000-01-01", "2010-01-01")
    wr = getattr(scan, "_window_row", None)
    check("window_row_exists", wr is not None)
    if wr is not None:
        ok = wr(meta, {"ok": True, "pvalue": 0.01, "error": ""})
        check("ok_keeps_p", ok is not None and ok["pvalue"] == 0.01 and not ok.get("crashed"), ok)
        ins = wr(meta, {"ok": False, "pvalue": np.nan, "error": "insufficient_overlap"})
        check("insufficient_excluded", ins is None, ins)
        cr = wr(meta, {"ok": False, "pvalue": np.nan, "error": "LinAlgError: SVD did not converge"})
        check("crash_counts_p1", cr is not None and cr["pvalue"] == 1.0 and cr.get("crashed") is True, cr)
        check("row_fields", cr is not None and (cr["symbol_a"], cr["symbol_b"], cr["window_start"], cr["direction"],
                                                cr["window_end_date"]) == ("A", "B", 0, "ab", "2010-01-01"))
    src = open(scan.__file__, encoding="utf-8").read()
    i = src.index('checkpoint_id="tier1_fullsample"')
    tier1 = src[i:i + 2500]
    check("tier1_uses_combine_eg_directions", "_combine_eg_directions(" in tier1)
    # 3. episodic_fraction with a worker that crashes on the second window
    calls = {"n": 0}
    real = scan._eg_worker

    def fake(task):
        calls["n"] += 1
        w = (calls["n"] + 1) // 2           # two calls (ab, ba) per window
        if w == 2:
            return {"ok": False, "pvalue": np.nan, "error": "ValueError: boom"}
        return {"ok": True, "pvalue": 0.01, "error": ""}
    scan._eg_worker = fake
    try:
        x = np.cumsum(np.random.default_rng(0).normal(size=40))
        frac, pv = scan.episodic_fraction(x, x + 0.1, 1, window=10, step=10)   # 4 windows
    finally:
        scan._eg_worker = real
    check("fraction_counts_crash", len(pv) == 4 and pv[1] == 1.0 and abs(frac - 0.75) < 1e-12, (frac, pv))
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
