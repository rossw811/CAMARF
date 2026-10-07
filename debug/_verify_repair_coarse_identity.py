"""
Synthetic check for research/repair_coarse_identity.py (2026-10-07). Temp WRDS dir:
  GOOD: coarse files derived from its own daily file;
  BAD:  coarse files derived from a DIFFERENT security (closes x7, other volume) -- the PAR case.
Checks: only BAD is detected; its 5 coarse files move to the quarantine dir byte-for-byte (nothing deleted); 7D/3M/
6M/1Y are rebuilt from BAD's own daily file (closes agree 100%, volume = restated sum, volume_raw = raw sum), 1M is
not rebuilt; GOOD is untouched.
Run: python debug/_verify_repair_coarse_identity.py
"""
import filecmp
import os
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from period_bars import resample_to_period_end
import research.repair_coarse_identity as r

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def daily(seed, scale):
    idx = pd.bdate_range("2010-01-01", "2014-12-31")
    rng = np.random.default_rng(seed)
    close = scale * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx))))
    raw = rng.integers(1000, 5000, len(idx)).astype(float)
    fac = np.where(idx < pd.Timestamp("2012-06-01"), 2.0, 1.0)
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "close_total_return": close,
                         "volume": raw * fac, "volume_raw": raw, "volume_adj_factor": fac}, index=idx)


def main():
    d = tempfile.mkdtemp(prefix="coarse_ident_")
    try:
        good, bad, other = daily(1, 10.0), daily(1, 10.0), daily(2, 70.0)
        for lab, dd, src in (("GOOD", good, good), ("BAD", bad, other)):
            dd.to_parquet(os.path.join(d, f"{lab}_1D.parquet"))
            raw_src = src.assign(volume=src["volume_raw"])[["open", "high", "low", "close", "volume", "close_total_return"]]
            for tf in r.COARSE:
                resample_to_period_end(raw_src, tf).to_parquet(os.path.join(d, f"{lab}_{tf}.parquet"))
        keep = tempfile.mkdtemp(prefix="coarse_ident_orig_")
        for f in os.listdir(d):
            shutil.copy(os.path.join(d, f), keep)
        found = r.find_mismatched(d)
        check("only_bad_detected", [x[0] for x in found] == ["BAD"], found)
        q = os.path.join(d, "_q")
        res = r.rebuild(d, "BAD", q)
        check("all_five_quarantined", sorted(res["quarantined"]) == sorted(r.COARSE), res)
        check("quarantine_byte_identical", all(filecmp.cmp(os.path.join(q, f"BAD_{tf}.parquet"),
                                                           os.path.join(keep, f"BAD_{tf}.parquet"), shallow=False)
                                               for tf in r.COARSE))
        check("1M_not_rebuilt", not os.path.exists(os.path.join(d, "BAD_1M.parquet")))
        for tf in r.DERIVED:
            c = pd.read_parquet(os.path.join(d, f"BAD_{tf}.parquet"))
            agree = r.close_agreement(bad, c, tf)
            truth = resample_to_period_end(bad[["close", "volume"]], tf)["volume"]
            raw_truth = resample_to_period_end(bad.assign(volume=bad["volume_raw"])[["close", "volume"]], tf)["volume"]
            check(f"{tf}_rebuilt_from_own_daily", agree == 1.0 and np.allclose(c["volume"], truth)
                  and np.allclose(c["volume_raw"], raw_truth), f"agree={agree}")
        check("good_untouched", all(filecmp.cmp(os.path.join(d, f"GOOD_{tf}.parquet"),
                                                os.path.join(keep, f"GOOD_{tf}.parquet"), shallow=False)
                                    for tf in r.COARSE))
        shutil.rmtree(keep, ignore_errors=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
