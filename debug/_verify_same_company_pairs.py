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
    check("permno_label_resolves", "permco:400" in (ids.get("PERMNO4") or ()), ids.get("PERMNO4"))
    check("gvkey_listings_same", same_company("GVKEY001_01W", "GVKEY001_02W", ids))
    check("gvkey_different", not same_company("GVKEY001_01W", "GVKEY002_01W", ids))
    check("unmapped_not_same", not same_company("UNKNOWN", "UNKNOWN2", ids) and ids.get("UNKNOWN") is None)
    check("mixed_not_same_without_link", not same_company("Z", "GVKEY001_01W", ids))
    # 2026-10-11: a US ADR (CRSP) and the same company's home listing (Compustat Global GVKEY<g>_<iid>) reached the
    # pools (ASML/GVKEY061214_01W, VOD/GVKEY014894_01W, ...): PERMCO and GVKEY were never linked. With the CRSP-
    # Compustat link (crsp.ccmxpf_lnkhist: permno -> gvkey), a CRSP label also carries gvkey:<g>.
    link = pd.DataFrame({"permno": [1, 3], "gvkey": [1, 7]})
    ids2 = company_ids(["Z", "ZG", "AAPL", "GVKEY001_01W", "GVKEY002_01W", "GVKEY007_03W"], label_map, master, link)
    check("adr_vs_home_same", same_company("Z", "GVKEY001_01W", ids2), ids2.get("Z"))
    check("link_via_permco_sibling", same_company("ZG", "GVKEY001_01W", ids2), ids2.get("ZG"))
    check("adr_vs_other_gvkey_different", not same_company("Z", "GVKEY002_01W", ids2))
    check("second_link", same_company("AAPL", "GVKEY007_03W", ids2))
    # 2026-10-12: Compustat files some ADRs under a different GVKEY than the home company (Toyota ADR -> GVKEY 25015
    # in an old build; home GVKEY019661). Capital IQ keeps one companyid across a firm's listings: link CRSP legs by
    # CUSIP (ciq_common.wrds_cusip) and both legs' GVKEYs (ciq_common.wrds_gvkey) to it.
    ciq_g = pd.DataFrame({"gvkey": [19661, 25015, 5], "companyid": [319676, 319676, 999]})
    ciq_c = pd.DataFrame({"cusip": ["89233130"], "companyid": [319676]})
    cus = {10: "89233130"}
    lm3 = pd.DataFrame({"label": ["TMADR", "OTHER"], "permno": [10, 11]})
    ms3 = pd.DataFrame({"permno": [10, 11], "permco": [1000, 1100]})
    ids3 = company_ids(["TMADR", "OTHER", "GVKEY019661_01W", "GVKEY000005_01W"], lm3, ms3, None,
                       ciq_gvkey=ciq_g, ciq_cusip=ciq_c, cusip_by_permno=cus)
    check("ciq_cusip_links_adr_to_home", same_company("TMADR", "GVKEY019661_01W", ids3), ids3.get("TMADR"))
    check("ciq_other_company_different", not same_company("OTHER", "GVKEY019661_01W", ids3)
          and not same_company("TMADR", "GVKEY000005_01W", ids3))
    link3 = pd.DataFrame({"permno": [11], "gvkey": [25015]})
    ids4 = company_ids(["OTHER", "GVKEY019661_01W"], lm3, ms3, link3, ciq_gvkey=ciq_g)
    check("ciq_gvkey_bridge", same_company("OTHER", "GVKEY019661_01W", ids4), ids4.get("OTHER"))
    try:
        from research.clean_pool_identity_pairs import require_link_for_mixed
        try:
            require_link_for_mixed([("Z", "GVKEY001_01W")], None); check("mixed_without_link_refused", False)
        except SystemExit:
            check("mixed_without_link_refused", True)
        require_link_for_mixed([("Z", "ZG")], None); check("unmixed_without_link_ok", True)
    except ImportError as e:
        check("require_link_for_mixed_exists", False, str(e))
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
