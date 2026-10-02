"""
Regression test (2026-10-02) for research/wrds_deep_history_episodic_scan.load_wrds_universe:
  (1) price basis: Compustat Global listings were loaded as split-only LOCAL-currency `close`, while spreads and P&L
      use USD (and universe_loader prefers close_total_return > close_usd > close) -- discovery tested a USD stock
      against a yen/pound series. Now the same priority as the shared loader.
  (2) D18 arms (Ross 2026-10-02: test both, he leans "use neither"): arm "exclude" masks CRSP no-trade days (close
      NaN while close_total_return moved -- a bid/ask-midpoint return) to NaN; arm "include" keeps them and also
      admits quote-only files (no close at all, built from |dlyprc|) that "exclude" drops.
Checks (temp WRDS dir):
  1. global file with close (local) + close_usd -> close_usd is used;
  2. global file with close_total_return (USD, from trfd) -> close_total_return is used;
  3. exclude arm: a CRSP file's TR on no-trade days becomes NaN; traded days unchanged;
  4. include arm: TR kept on no-trade days; a quote-only file (flag column quote_only=True) is loaded;
     exclude arm drops that file.
Run: python debug/_verify_scan_price_basis_d18.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import research.wrds_deep_history_episodic_scan as scan

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    root = tempfile.mkdtemp(prefix="verify_scan_d18_")
    orig = scan._WRDS_CACHE_DIR
    scan._WRDS_CACHE_DIR = root
    try:
        idx = pd.bdate_range("2020-01-01", periods=300)
        rng = np.random.default_rng(0)
        base = 50 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
        pd.DataFrame({"close": base * 150.0, "close_usd": base}, index=idx).to_parquet(
            os.path.join(root, "GVKEY000001_01W_1D.parquet"))
        base2 = 30 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))   # independent path (identical returns would be deduped)
        pd.DataFrame({"close": base2 * 7.0, "close_usd": base2 * 1.1, "close_total_return": base2 * 1.2}, index=idx).to_parquet(
            os.path.join(root, "GVKEY000002_01W_1D.parquet"))
        base3 = 80 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
        crsp = pd.DataFrame({"close": base3 * 2.0, "close_total_return": base3 * 2.0 * 1.01}, index=idx)
        no_trade = idx[50:60]
        crsp.loc[no_trade, "close"] = np.nan
        crsp.to_parquet(os.path.join(root, "ILLQ_1D.parquet"))
        base4 = 20 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
        q = pd.DataFrame({"close": np.nan, "close_total_return": base4 * 3.0, "quote_only": True}, index=idx)
        os.makedirs(os.path.join(root, "_quote_only"))
        q.to_parquet(os.path.join(root, "_quote_only", "PERMNO99999_1D.parquet"))

        ex, _ = scan.load_wrds_universe(d18_arm="exclude")
        inc, _ = scan.load_wrds_universe(d18_arm="include")
        check("global_close_usd_used", np.allclose(ex["GVKEY000001_01W"].to_numpy(), base))
        check("global_total_return_used", np.allclose(ex["GVKEY000002_01W"].to_numpy(), base2 * 1.2))
        e = ex["ILLQ"]
        check("exclude_masks_no_trade_days", bool(e.loc[no_trade].isna().all()) and
              np.allclose(e.drop(no_trade).to_numpy(), (base3 * 2.02)[~idx.isin(no_trade)]))
        check("include_keeps_no_trade_days", bool(inc["ILLQ"].loc[no_trade].notna().all()))
        check("quote_only_file_arms", "PERMNO99999" in inc and "PERMNO99999" not in ex, f"inc={'PERMNO99999' in inc} ex={'PERMNO99999' in ex}")
    finally:
        scan._WRDS_CACHE_DIR = orig
        shutil.rmtree(root, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
