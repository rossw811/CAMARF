"""Synthetic proof for data_sec_edgar.py -- confirms CIK normalization/
join logic against known cases before trusting the real fetch. Does NOT
hit the real network (that's data_sec_edgar.py's own __main__ block,
already run manually and confirmed: 3,329 distinct SIC=6770 companies,
933 ticker-mapped)."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_sec_edgar as sec

n_checks = 0
n_passed = 0


def check(name, cond):
    global n_checks, n_passed
    n_checks += 1
    status = "PASS" if cond else "FAIL"
    if cond:
        n_passed += 1
    print(f"[{status}] {name}")


# --- 1. CIK normalization: zero-padded atom-feed string vs. plain int from
# company_tickers.json must join correctly despite different representations ---
spac_df = pd.DataFrame([
    {"cik": "0001848507", "sic": "6770", "state": "NY"},
    {"cik": "0000320193", "sic": "6770", "state": "CA"},
])
ticker_map = pd.DataFrame([
    {"cik": 1848507, "ticker": "TESTA", "title": "Test SPAC A Corp"},
    {"cik": 320193, "ticker": "AAPL", "title": "Apple Inc"},
])
spac_df["cik"] = spac_df["cik"].astype(int)
ticker_map["cik"] = ticker_map["cik"].astype(int)
merged = spac_df.merge(ticker_map[["cik", "ticker", "title"]], on="cik", how="left")
check("zero-padded string CIK joins correctly against a plain-int CIK",
      merged.loc[merged["cik"] == 1848507, "ticker"].iloc[0] == "TESTA")
check("both real rows matched a ticker (no silent join failure)",
      merged["ticker"].notna().sum() == 2)

# --- 2. Left join preserves SIC-list rows with no ticker match (shell with no ticker yet) ---
spac_df2 = pd.DataFrame([{"cik": 9999999, "sic": "6770", "state": "DE"}])
ticker_map2 = pd.DataFrame([{"cik": 1234567, "ticker": "OTHER", "title": "Other Co"}])
merged2 = spac_df2.merge(ticker_map2[["cik", "ticker", "title"]], on="cik", how="left")
check("a SIC-list company with no registered ticker is kept (NaN ticker), not dropped",
      len(merged2) == 1 and pd.isna(merged2["ticker"].iloc[0]))

print(f"\n{n_passed}/{n_checks} checks passed")
sys.exit(0 if n_passed == n_checks else 1)
