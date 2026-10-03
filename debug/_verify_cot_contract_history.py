"""
Regression test for finding M13 (inconsistency sweep 2026-09-27; first labelled "M12", which was already the ID of a different review finding): COTFeed matched contracts by name PREFIX. CFTC renamed the
E-mini Nasdaq-100 contract ("E-MINI NASDAQ 100 STOCK INDEX" 1999, "NASDAQ-100 STOCK INDEX (MINI)" 1999-2022,
"NASDAQ MINI" 2022-), so the prefix "NASDAQ MINI" silently limited NQ positioning to 2022-02-08 onward (242 weeks
instead of ~1,420). Fix: exact chronological name lists per contract + a duplicate-report-date guard that fails loudly.
Checks:
  1. offline: the NQ where-clause includes the 2000-2022 CME name and all four names; ES all three;
  2. live (CFTC public API, force_refresh): NQ history starts in 1999 and ES in 1997, one row per report date,
     no gap longer than 2 weeks within +-2 months of the rename boundaries (2000-08, 2022-02). (A first draft
     required <= 3 weeks everywhere: ES has genuine 14-25 day gaps in 1998, the E-mini's first year of CFTC
     reporting -- source sparsity, not a seam.)
Run: python debug/_verify_cot_contract_history.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from macro import COTFeed

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    w = COTFeed._where_clause("NQ")
    check("nq_where_has_2000_2022_name", "NASDAQ-100 STOCK INDEX (MINI) - CHICAGO MERCANTILE EXCHANGE" in w
          and w.count("'") == 8, w[:120])
    check("es_where_three_names", COTFeed._where_clause("ES").count("'") == 6)
    for key, first_year in (("NQ", 1999), ("ES", 1997)):
        d = COTFeed.get_net_spec(key, force_refresh=True)
        ok = d is not None and len(d) > 0
        gaps = None
        if ok:
            g = d.index.to_series().diff().dt.days
            near = pd.Series(False, index=g.index)
            for b in ("2000-08-25", "2022-02-04"):
                near |= (g.index > pd.Timestamp(b) - pd.Timedelta(days=60)) & (g.index < pd.Timestamp(b) + pd.Timedelta(days=60))
            gaps = g[near].max()
        check(f"{key.lower()}_live_history", ok and d.index.min().year == first_year and not d.index.duplicated().any()
              and gaps <= 14, f"rows={0 if d is None else len(d)} first={None if d is None else d.index.min().date()} max_gap_near_renames={gaps}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
