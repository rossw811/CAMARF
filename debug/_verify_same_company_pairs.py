"""
Test for plan S36 (Ross 2026-10-10; written before the code): share-class pairs (Z/ZG, LBRDA/LBRDK, FWONA/FWONK) reached
the pools -- the A3 exclusion is a hardcoded 8-pair list and clean_pool_identity_pairs only removes IDENTICAL return
series. Rule: a pair whose legs belong to the same company is removed at the pool step and counted: CRSP labels map
label -> PERMNO (label map, or a PERMNO<n> label) -> PERMCO (crsp_full_security_master_v2); Compustat labels
GVKEY<g>_<iid> map to gvkey:<g>. Mixed CRSP/Compustat pairs and unmapped labels are never called the same company.
Checks: Z/ZG (two PERMNOs, one PERMCO) same; two unrelated PERMCOs different; PERMNO<n> labels resolve; GVKEY001_01W
vs GVKEY001_02W same, vs GVKEY002_01W different; an unmapped label -> not same.
Run: python debug/_verify_same_company_pairs.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    try:
        from research.clean_pool_identity_pairs import company_ids, same_company
    except ImportError as e:
        check("functions_exist", False, str(e)); return finish()
    label_map = pd.DataFrame({"label": ["Z", "ZG", "AAPL"], "permno": [1, 2, 3]})
    master = pd.DataFrame({"permno": [1, 2, 3, 4, 4], "permco": [100, 100, 300, 400, 400]})
    ids = company_ids(["Z", "ZG", "AAPL", "PERMNO4", "GVKEY001_01W", "GVKEY001_02W", "GVKEY002_01W", "UNKNOWN"],
                      label_map, master)
    check("share_class_same", same_company("Z", "ZG", ids), ids.get("Z"))
    check("unrelated_different", not same_company("Z", "AAPL", ids))
    check("permno_label_resolves", ids.get("PERMNO4") == "permco:400", ids.get("PERMNO4"))
    check("gvkey_listings_same", same_company("GVKEY001_01W", "GVKEY001_02W", ids))
    check("gvkey_different", not same_company("GVKEY001_01W", "GVKEY002_01W", ids))
    check("unmapped_not_same", not same_company("UNKNOWN", "UNKNOWN2", ids) and ids.get("UNKNOWN") is None)
    check("mixed_not_same", not same_company("Z", "GVKEY001_01W", ids))
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
