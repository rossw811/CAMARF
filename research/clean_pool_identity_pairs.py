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

from lineage import Lineage

_R = os.path.join(_ROOT, "output", "research")
MIN_COMMON, SHARE, TOL = 60, 0.99, 1e-9


def identity_share(ra: pd.Series, rb: pd.Series):
    a, b = ra.align(rb, join="inner")
    ok = a.notna() & b.notna()
    a, b = a[ok], b[ok]
    if len(a) < MIN_COMMON:
        return np.nan, len(a)
    return float((np.abs(a.to_numpy() - b.to_numpy()) <= TOL).mean()), len(a)


def _log_returns(df):
    c = df["close"].astype(float)
    c = c[c > 0].dropna()
    return np.log(c).diff().dropna()


def main():
    from episodic_pairs_adapter import _load_symbol
    lin = Lineage()
    up = lin.stage("pit_eligibility", code=["research/purity_pit_eligibility.py"],
                   inputs=["output/research/purity_pairs.parquet"],
                   outputs=[f"output/research/purity_pairs_pit_k{k}.parquet" for k in (1, 2)])
    st = lin.stage("clean_pools", code=["research/clean_pool_identity_pairs.py", "research/episodic_pairs_adapter.py"],
                   inputs=["pit_eligibility"],
                   outputs=[f"output/research/purity_pairs_pit_k{k}_clean.parquet" for k in (1, 2)] +
                           ["output/research/clean_pool_identity_pairs_report.parquet"],
                   params={"min_common": MIN_COMMON, "share": SHARE, "tol": TOL})
    cache, rows = {}, []
    for k in (1, 2):
        P = pd.read_parquet(os.path.join(_R, f"purity_pairs_pit_k{k}.parquet"))
        keep = []
        for r in P.itertuples():
            for s in (r.symbol_a, r.symbol_b):
                if s not in cache:
                    df = _load_symbol(s, getattr(r, "tf_label", "1D"))
                    cache[s] = _log_returns(df) if df is not None and len(df) else None
            ra, rb = cache[r.symbol_a], cache[r.symbol_b]
            share, n = (np.nan, 0) if ra is None or rb is None else identity_share(ra, rb)
            ident = bool(np.isfinite(share) and share >= SHARE)
            rows.append({"k": k, "symbol_a": r.symbol_a, "symbol_b": r.symbol_b, "identical_share": share,
                         "n_common": n, "identity": ident})
            keep.append(not ident)
        C = P[np.array(keep)].reset_index(drop=True)
        C.to_parquet(os.path.join(_R, f"purity_pairs_pit_k{k}_clean.parquet"))
        print(f"k={k}: {len(P)} -> {len(C)} (removed {len(P) - len(C)} identity pairs)")
    pd.DataFrame(rows).to_parquet(os.path.join(_R, "clean_pool_identity_pairs_report.parquet"))
    st.record()
    print(f"lineage: recorded 'clean_pools' (upstream pit_eligibility up to date: {up.up_to_date})")


if __name__ == "__main__":
    main()
