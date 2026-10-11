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


def company_ids(labels, label_map: pd.DataFrame, master: pd.DataFrame, ccm_link: pd.DataFrame = None) -> dict:
    """label -> frozenset of company ids: 'permco:<n>' (CRSP: label map or PERMNO<n> label -> PERMNO -> PERMCO) and,
    when the CRSP-Compustat link is given (crsp.ccmxpf_lnkhist: permno -> gvkey, any link row of the PERMCO), the
    linked 'gvkey:<g>'; Compustat labels GVKEY<g>_<iid> -> {'gvkey:<g>'}; None when unmapped. Plan S36 (Ross
    2026-10-10). 2026-10-11: without the link a US ADR and the same company's home listing (ASML vs GVKEY061214_01W)
    were never matched. debug/_verify_same_company_pairs.py"""
    import re
    permno_by_label = dict(zip(label_map["label"].astype(str), label_map["permno"]))
    m_ = master.dropna(subset=["permno", "permco"])[["permno", "permco"]].astype(int).drop_duplicates()
    permco_by_permno = dict(m_.drop_duplicates("permno").itertuples(index=False, name=None))
    gvkeys_by_permco = {}
    if ccm_link is not None and len(ccm_link):
        L = ccm_link.dropna(subset=["permno", "gvkey"])[["permno", "gvkey"]].astype(int).merge(m_, on="permno")
        for pc, g in L[["permco", "gvkey"]].drop_duplicates().itertuples(index=False, name=None):
            gvkeys_by_permco.setdefault(pc, set()).add(g)
    out = {}
    for lab in labels:
        lab = str(lab)
        g = re.fullmatch(r"GVKEY(\d+)_\w+", lab)
        if g:
            out[lab] = frozenset({f"gvkey:{int(g.group(1))}"}); continue
        m = re.fullmatch(r"PERMNO(\d+)", lab)
        pn = int(m.group(1)) if m else permno_by_label.get(lab)
        pc = permco_by_permno.get(int(pn)) if pn is not None and pd.notna(pn) else None
        out[lab] = (frozenset({f"permco:{pc}"} | {f"gvkey:{x}" for x in gvkeys_by_permco.get(pc, ())})
                    if pc is not None else None)
    return out


def same_company(a: str, b: str, ids: dict) -> bool:
    ca, cb = ids.get(str(a)), ids.get(str(b))
    return bool(ca and cb and (ca & cb))


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
    _lm = pd.concat([pd.read_parquet(os.path.join(_w, "full_us_market_label_map.parquet"))]
                    + [pd.read_parquet(f)[["label", "permno"]] for f in sorted(
                        __import__("glob").glob(os.path.join(_w, "extra_permno_map_*.parquet")))], ignore_index=True)
    _master = pd.read_parquet(os.path.join(_w, "crsp_full_security_master_v2.parquet"), columns=["permno", "permco"])
    _link = pd.read_parquet(_CCM_LINK) if os.path.exists(_CCM_LINK) else None
    for k in (1, 2):
        P = pd.read_parquet(os.path.join(_R, f"purity_pairs_pit_k{k}.parquet"))
        require_link_for_mixed(zip(P["symbol_a"], P["symbol_b"]), _link)
        ids = company_ids(pd.concat([P["symbol_a"], P["symbol_b"]]).unique(), _lm, _master, _link)
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
            rows.append({"k": k, "symbol_a": r.symbol_a, "symbol_b": r.symbol_b, "identical_share": share,
                         "n_common": n, "identity": ident, "same_company": same})
            keep.append(not ident and not same)
        C = P[np.array(keep)].reset_index(drop=True)
        C.to_parquet(os.path.join(_R, f"purity_pairs_pit_k{k}_clean.parquet"))
        R = pd.DataFrame([x for x in rows if x["k"] == k])
        print(f"k={k}: {len(P)} -> {len(C)} (removed {int(R['identity'].sum())} identity pairs, "
              f"{int((R['same_company'] & ~R['identity']).sum())} further same-company pairs)")
    pd.DataFrame(rows).to_parquet(os.path.join(_R, "clean_pool_identity_pairs_report.parquet"))
    st.record()
    print("lineage: recorded 'clean_pools'")


if __name__ == "__main__":
    main()
