"""
research/clean_pool_identity_pairs.py -- remove "pairs" that are one security against itself (2026-09-27).

Replaces the ad-hoc clean_pools.py that produced purity_pairs_pit_k{1,2}_clean.parquet from a side-effect file of the
spread regeneration (regen_failure_audit.parquet). Here identity is decided from the DATA: a pair is one security when
the two legs' daily log returns are identical (|diff| <= 1e-9) on >= 99% of their common days, over >= 60 common days.
Legs are loaded with episodic_pairs_adapter._load_symbol -- the same WRDS-first total-return series the spreads use.

Why a pair-level check is still needed after universe_loader.dedupe_identical_series: that dedupe buckets symbols by
their LAST 60 (date, return) values, so two labels of one security whose histories END on different dates (e.g. a
PERMNO alias with a shorter history) are never compared (inconsistency sweep, 2026-09-27).

Inputs: output/research/purity_pairs_pit_k{1,2}.parquet. Outputs: ..._clean.parquet and
output/research/clean_pool_identity_pairs_report.parquet. Lineage stage "clean_pools" (upstream "pit_eligibility").
Usage: python research/clean_pool_identity_pairs.py
"""
import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "research"))


_R = os.path.join(_ROOT, "output", "research")
MIN_COMMON, SHARE, TOL = 60, 0.99, 1e-9


_CCM_LINK = os.path.join(_ROOT, "output", "cache", "wrds", "crsp_ccm_link.parquet")


def identity_share(ra: pd.Series, rb: pd.Series):
    a, b = ra.align(rb, join="inner")
    ok = a.notna() & b.notna()
    a, b = a[ok], b[ok]
    if len(a) < MIN_COMMON:
        return np.nan, len(a)
    return float((np.abs(a.to_numpy() - b.to_numpy()) <= TOL).mean()), len(a)


def company_ids(labels, label_map: pd.DataFrame, master: pd.DataFrame, ccm_link: pd.DataFrame = None,
                ciq_gvkey: pd.DataFrame = None, ciq_cusip: pd.DataFrame = None, cusip_by_permno: dict = None) -> dict:
    """label -> frozenset of company ids; two labels are the same company when their sets intersect.
      CRSP label  (label map, or a PERMNO<n> label -> PERMNO -> PERMCO): 'permco:<n>'; every GVKEY linked to that
                  PERMCO in the CRSP-Compustat link (crsp.ccmxpf_lnkhist) -> 'gvkey:<g>'; and the Capital IQ company
                  of its CUSIP (ciq_common.wrds_cusip, 8-character match) or of a linked GVKEY -> 'ciq:<id>'
      Compustat GVKEY<g>_<iid>: 'gvkey:<g>' and its Capital IQ company (ciq_common.wrds_gvkey) -> 'ciq:<id>'
    None when unmapped. Plan S36 (Ross 2026-10-10). 2026-10-11: CCM link (ASML vs GVKEY061214_01W). 2026-10-12:
    Capital IQ, which keeps one companyid across all of a firm's listings -- Compustat files some ADRs under a
    different GVKEY than the home company. debug/_verify_same_company_pairs.py"""
    import re
    permno_by_label = dict(zip(label_map["label"].astype(str), label_map["permno"]))
    m_ = master.dropna(subset=["permno", "permco"])[["permno", "permco"]].astype(int).drop_duplicates()
    permco_by_permno = dict(m_.drop_duplicates("permno").itertuples(index=False, name=None))
    permnos_by_permco = m_.groupby("permco")["permno"].apply(set).to_dict()
    gvkeys_by_permco = {}
    if ccm_link is not None and len(ccm_link):
        L = ccm_link.dropna(subset=["permno", "gvkey"])[["permno", "gvkey"]].astype(int).merge(m_, on="permno")
        for pc, g in L[["permco", "gvkey"]].drop_duplicates().itertuples(index=False, name=None):
            gvkeys_by_permco.setdefault(pc, set()).add(g)
    ciq_by_gvkey = {}
    if ciq_gvkey is not None and len(ciq_gvkey):
        G = ciq_gvkey.dropna(subset=["gvkey", "companyid"])
        for g, c in zip(G["gvkey"].astype(int), G["companyid"].astype(int)):
            ciq_by_gvkey.setdefault(g, set()).add(c)
    ciq_by_c8 = {}
    if ciq_cusip is not None and len(ciq_cusip):
        C = ciq_cusip.dropna(subset=["cusip", "companyid"])
        for cu, c in zip(C["cusip"].astype(str).str[:8], C["companyid"].astype(int)):
            ciq_by_c8.setdefault(cu, set()).add(c)
    cusip_by_permno = cusip_by_permno or {}
    out = {}
    for lab in labels:
        lab = str(lab)
        g = re.fullmatch(r"GVKEY(\d+)_\w+", lab)
        if g:
            gv = int(g.group(1))
            out[lab] = frozenset({f"gvkey:{gv}"} | {f"ciq:{c}" for c in ciq_by_gvkey.get(gv, ())}); continue
        m = re.fullmatch(r"PERMNO(\d+)", lab)
        pn = int(m.group(1)) if m else permno_by_label.get(lab)
        pc = permco_by_permno.get(int(pn)) if pn is not None and pd.notna(pn) else None
        if pc is None:
            out[lab] = None; continue
        gvs = gvkeys_by_permco.get(pc, set())
        ids = {f"permco:{pc}"} | {f"gvkey:{x}" for x in gvs}
        ids |= {f"ciq:{c}" for x in gvs for c in ciq_by_gvkey.get(x, ())}
        for p in permnos_by_permco.get(pc, {int(pn)}):
            cu = cusip_by_permno.get(p)
            if cu:
                ids |= {f"ciq:{c}" for c in ciq_by_c8.get(str(cu)[:8], ())}
        out[lab] = frozenset(ids)
    return out


def same_company(a: str, b: str, ids: dict) -> bool:
    ca, cb = ids.get(str(a)), ids.get(str(b))
    return bool(ca and cb and (ca & cb))


_DLC_IDS = os.path.join(_ROOT, "research", "dual_listed_companies_ids.csv")


def load_dlc_sides(path: str = _DLC_IDS) -> dict:
    """D14 (Ross 2026-10-12): {dlc_name: (side A ids, side B ids)} for the dual-listed structures in
    research/dual_listed_companies.csv (de Jong, Rosenthal & van Dijk 2009 Table I and later sources) whose two
    parents both exist in our data; identifiers mapped by name in research/dual_listed_companies_ids.csv."""
    d = pd.read_csv(path)
    out = {}
    for name, g in d.groupby("dlc_name"):
        sides = {r.side: set(str(r.ids).split(";")) for r in g.itertuples()}
        if "A" in sides and "B" in sides:
            out[name] = (sides["A"], sides["B"])
    return out


def dlc_twin(a: str, b: str, ids: dict, sides: dict) -> bool:
    """True when one leg belongs to side A and the other to side B of the same dual-listed company (D14)."""
    ia, ib = ids.get(str(a)) or frozenset(), ids.get(str(b)) or frozenset()
    return any((ia & A and ib & B) or (ia & B and ib & A) for A, B in sides.values())


def unverified_labels(final_map: pd.DataFrame) -> set:
    """D15 (Ross 2026-10-12): labels whose CRSP file could not be identified (research/identify_wrds_files.py,
    source 'unresolved_*' -- too short to test, or no candidate's returns matched). Pairs with such a leg are
    dropped at the pool step; unresolved != eligible."""
    m = final_map[final_map["permno"].isna()]
    return set(m["label"].astype(str))


def require_link_for_mixed(pairs, ccm_link):
    """A pool with CRSP-vs-Compustat pairs cannot be checked for same company without the CCM link: refuse rather
    than silently pass them (2026-10-11)."""
    mixed = [(a, b) for a, b in pairs if str(a).startswith("GVKEY") != str(b).startswith("GVKEY")]
    if mixed and (ccm_link is None or len(ccm_link) == 0):
        raise SystemExit(f"{len(mixed)} CRSP-vs-Compustat pairs (e.g. {mixed[:3]}) need the CRSP-Compustat link "
                         f"({_CCM_LINK}) to apply the same-company rule -- fetch it first (WRDS job 21_fetch_ccm_link)")


def _log_returns(df):
    c = df["close"].astype(float)
    c = c[c > 0].dropna()
    return np.log(c).diff().dropna()


def main():
    from episodic_pairs_adapter import _load_symbol
    from pipeline_stages import stage
    st = stage("clean_pools")
    cache, rows = {}, []
    # S36 (Ross 2026-10-10): same-company pairs (share classes, Compustat listings of one GVKEY) are removed and counted
    _w = os.path.join(_ROOT, "output", "cache", "wrds")
    # 2026-10-12: the content-verified label -> PERMNO map (full_us_market_label_map named reused tickers' old holders:
    # TM -> Toastmaster), PERMCO/CUSIP from the FULL CRSP names history (the v2 master has no ADRs), Capital IQ links
    from data_wrds import label_permno_map
    _lmap = label_permno_map()
    _lm = pd.DataFrame({"label": list(_lmap), "permno": list(_lmap.values())})
    _names = pd.read_parquet(os.path.join(_w, "crsp_stocknames_all.parquet"))
    _master = pd.concat([_names[["permno", "permco"]],
                         pd.read_parquet(os.path.join(_w, "crsp_full_security_master_v2.parquet"), columns=["permno", "permco"])])
    _cus = dict(_names.sort_values("nameenddt").dropna(subset=["ncusip"]).groupby("permno")["ncusip"].last())
    _link = pd.read_parquet(_CCM_LINK) if os.path.exists(_CCM_LINK) else None
    _cg = os.path.join(_w, "ciq_link_gvkey.parquet"); _cc = os.path.join(_w, "ciq_link_cusip.parquet")
    _ciq_g = pd.read_parquet(_cg, columns=["gvkey", "companyid"]) if os.path.exists(_cg) else None
    _ciq_c = pd.read_parquet(_cc, columns=["cusip", "companyid"]) if os.path.exists(_cc) else None
    from data_wrds import LABEL_PERMNO_MAP_PATH
    _unverified = unverified_labels(pd.read_parquet(LABEL_PERMNO_MAP_PATH))   # D15
    _dlc = load_dlc_sides()                                                      # D14
    for k in (1, 2):
        P = pd.read_parquet(os.path.join(_R, f"purity_pairs_pit_k{k}.parquet"))
        require_link_for_mixed(zip(P["symbol_a"], P["symbol_b"]), _link)
        if _ciq_g is None or _ciq_c is None:
            raise SystemExit("Capital IQ link files missing (output/cache/wrds/ciq_link_gvkey/cusip.parquet; WRDS job "
                             "24_fetch_ciq_company_links) -- ADR-vs-home-listing pairs cannot be checked")
        ids = company_ids(pd.concat([P["symbol_a"], P["symbol_b"]]).unique(), _lm, _master, _link,
                          ciq_gvkey=_ciq_g, ciq_cusip=_ciq_c, cusip_by_permno=_cus)
        keep = []
        for r in P.itertuples():
            for s in (r.symbol_a, r.symbol_b):
                if s not in cache:
                    df = _load_symbol(s, getattr(r, "tf_label", "1D"))
                    cache[s] = _log_returns(df) if df is not None and len(df) else None
            ra, rb = cache[r.symbol_a], cache[r.symbol_b]
            share, n = (np.nan, 0) if ra is None or rb is None else identity_share(ra, rb)
            ident = bool(np.isfinite(share) and share >= SHARE)
            same = same_company(r.symbol_a, r.symbol_b, ids)
            unver = r.symbol_a in _unverified or r.symbol_b in _unverified
            twin = dlc_twin(r.symbol_a, r.symbol_b, ids, _dlc)
            rows.append({"k": k, "symbol_a": r.symbol_a, "symbol_b": r.symbol_b, "identical_share": share,
                         "n_common": n, "identity": ident, "same_company": same, "unverified_leg": unver, "dlc_twin": twin})
            keep.append(not ident and not same and not unver and not twin)
        C = P[np.array(keep)].reset_index(drop=True)
        C.to_parquet(os.path.join(_R, f"purity_pairs_pit_k{k}_clean.parquet"))
        R = pd.DataFrame([x for x in rows if x["k"] == k])
        print(f"k={k}: {len(P)} -> {len(C)} (removed {int(R['identity'].sum())} identity pairs, "
              f"{int((R['same_company'] & ~R['identity']).sum())} further same-company pairs, "
              f"{int((R['unverified_leg'] & ~R['same_company'] & ~R['identity']).sum())} further pairs with an "
              f"unverified leg (D15), {int((R['dlc_twin'] & ~R['unverified_leg'] & ~R['same_company'] & ~R['identity']).sum())} "
              f"further dual-listed twins (D14))")
    pd.DataFrame(rows).to_parquet(os.path.join(_R, "clean_pool_identity_pairs_report.parquet"))
    st.record()
    print("lineage: recorded 'clean_pools'")


if __name__ == "__main__":
    main()
