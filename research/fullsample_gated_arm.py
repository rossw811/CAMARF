"""
research/fullsample_gated_arm.py -- N2 comparison arm (Ross 2026-11-04): the full-sample screen run under the SAME gates
and cleaning as the point-in-time pools, so any remaining disagreement is discovery timing / windowing, not the gates.

Why: Tier 1 (full-sample EG, BH-FDR) confirms 925 pairs on the A7 outputs and only 6 reach the PIT k1 pool, but 842 of
the 925 never have a window that passes the point-in-time gates (ADV, PIT S&P 500 membership for CRSP legs, causal
candidacy, history length), and 30 of the 36 that reach the raw PIT pool are one company listed twice (Development.md
2026-11-04, N2 first cut). The papers' claim "a full-history screen certifies pairs a point-in-time screen would not
find" needs the like-for-like comparison.

Arm (descriptive; no decision input):
  family  = Tier 1's tested pairs (one max-over-directions p per pair, production's _combine_eg_directions output),
            restricted to pairs with >= 1 window that passed every gate in Tier 2 (Tier 2 tests exactly Tier 1's
            candidate list, so this restriction uses the gates only, never an outcome);
            sensitivity: >= 1 gated window in Tier 2 or Tier 3 (Tier 3 candidacy is a rolling-correlation screen).
  screen  = analysis._benjamini_hochberg at Config.STATS.FDR_ALPHA over that family (what a full-sample screen under the
            gates would do); the original Tier 1 flags restricted to the family are reported beside it.
  cleaning= clean_pool_identity_pairs.clean_pool (identity, same company, unverified leg, DLC twin, structural).
  compare = clean PIT pools k1 / k2 restricted to the same family: overlap both ways, and eligible_from of shared pairs
            (the full-sample screen certifies with data to the end of the sample).
Pairs are matched as unordered label pairs, exactly as labelled in the scan outputs (segment labels kept).

Run (CachyOS, read-only on the A7 outputs):  python research/fullsample_gated_arm.py
Outputs: output/research/fullsample_gated_arm_pairs.parquet (one row per pair in any screen or pool, with flags),
         output/research/fullsample_gated_arm_summary.parquet; printed summary.
Check: debug/_verify_fullsample_gated_arm.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "research")]

import numpy as np
import pandas as pd

import parquet_io
from config import Config

R_DIR = os.path.join(ROOT, "output", "research")
SCAN = "wrds_deep_history_episodic_scan"


def pkey(a, b) -> frozenset:
    return frozenset((str(a), str(b)))


def tested_keys(windows: pd.DataFrame) -> set:
    """Unordered pairs with >= 1 row in a tier windows file (a window is written only if it passed every gate)."""
    w = windows[["symbol_a", "symbol_b"]].drop_duplicates()
    return {pkey(a, b) for a, b in zip(w["symbol_a"], w["symbol_b"])}


def gated_screen(tier1: pd.DataFrame, family: set, alpha: float, bh=None):
    """BH over Tier 1's p-values restricted to `family`. Returns (frame of the family with `fs_gated` = BH rejection
    and `fs_orig` = Tier 1's own flag) -- tier1 needs symbol_a, symbol_b, pvalue, fdr_confirmed."""
    if bh is None:
        from analysis import _benjamini_hochberg as bh
    keys = [pkey(a, b) for a, b in zip(tier1["symbol_a"], tier1["symbol_b"])]
    F = tier1[np.array([k in family for k in keys], dtype=bool)].reset_index(drop=True)
    if len(F):
        rej, adj = bh(F["pvalue"].to_numpy(dtype=float), alpha)
    else:
        rej, adj = np.zeros(0, bool), np.zeros(0)
    F["fs_gated"] = np.asarray(rej, dtype=bool)
    F["fs_gated_adj_p"] = np.asarray(adj, dtype=float)
    F["fs_orig"] = F["fdr_confirmed"].astype(bool)
    return F


def overlap(a: set, b: set) -> dict:
    return {"n_a": len(a), "n_b": len(b), "both": len(a & b), "a_only": len(a - b), "b_only": len(b - a)}


def compare(tier1, t2_keys, t3_keys, pit_pools: dict, alpha, cleaner, bh=None):
    """The whole arm on in-memory inputs (testable without files). `cleaner(frame) -> cleaned frame` removes the pool
    cleaning rules' pairs; `pit_pools` {k: clean PIT pool frame with symbol_a, symbol_b, eligible_from}.
    Returns (summary rows, per-pair membership frame)."""
    all_keys = {pkey(a, b) for a, b in zip(tier1["symbol_a"], tier1["symbol_b"])}
    ungated = tier1[tier1["fdr_confirmed"].astype(bool)][["symbol_a", "symbol_b"]]
    U = {pkey(a, b) for a, b in zip(ungated["symbol_a"], ungated["symbol_b"])}
    Uc_f = cleaner(ungated)
    Uc = {pkey(a, b) for a, b in zip(Uc_f["symbol_a"], Uc_f["symbol_b"])}
    rows, member = [], {}
    pit = {k: {pkey(a, b): e for a, b, e in zip(P["symbol_a"], P["symbol_b"], P["eligible_from"])}
           for k, P in pit_pools.items()}
    for fam_name, fam in (("tier2", t2_keys & all_keys), ("tier2_or_3", (t2_keys | t3_keys) & all_keys)):
        F = gated_screen(tier1, fam, alpha, bh)
        G_f = F[F["fs_gated"]][["symbol_a", "symbol_b"]]
        G = {pkey(a, b) for a, b in zip(G_f["symbol_a"], G_f["symbol_b"])}
        Gc_f = cleaner(G_f)
        Gc = {pkey(a, b) for a, b in zip(Gc_f["symbol_a"], Gc_f["symbol_b"])}
        O = {pkey(a, b) for a, b, c in zip(F["symbol_a"], F["symbol_b"], F["fs_orig"]) if c}
        base = dict(family=fam_name, m_family=len(F), m_tier1=len(tier1), ungated_confirmed=len(U),
                    ungated_confirmed_clean=len(Uc), orig_flags_in_family=len(O), gated_confirmed=len(G),
                    gated_confirmed_clean=len(Gc))
        for k, pk in pit.items():
            pit_fam = {x for x in pk if x in fam}
            ov = overlap(Gc, pit_fam)
            shared = sorted(Gc & pit_fam, key=lambda x: tuple(sorted(x)))
            ef = pd.to_datetime(pd.Series([pk[x] for x in shared]), errors="coerce")
            rows.append({**base, "k": k, "pit_pool": len(pk), "pit_in_family": len(pit_fam),
                         "fs_clean_and_pit": ov["both"], "fs_clean_only": ov["a_only"], "pit_only": ov["b_only"],
                         "share_fs_found_by_pit": ov["both"] / len(Gc) if Gc else np.nan,
                         "share_pit_found_by_fs": ov["both"] / len(pit_fam) if pit_fam else np.nan,
                         "shared_eligible_from_median": ef.median() if len(ef) else pd.NaT,
                         "shared_eligible_from_min": ef.min() if len(ef) else pd.NaT,
                         "shared_eligible_from_max": ef.max() if len(ef) else pd.NaT})
        for x in G | O:
            member.setdefault(x, {})[f"fs_gated_{fam_name}"] = x in G
            member[x][f"fs_gated_clean_{fam_name}"] = x in Gc
            member[x][f"in_family_{fam_name}"] = True
        for x in fam:
            if x in member:
                member[x][f"in_family_{fam_name}"] = True
    for x in U:
        member.setdefault(x, {})["fs_ungated"] = True
        member[x]["fs_ungated_clean"] = x in Uc
    for k, pk in pit.items():
        for x, e in pk.items():
            member.setdefault(x, {})[f"pit_k{k}"] = True
            member[x][f"pit_k{k}_eligible_from"] = e
    M = pd.DataFrame([{"symbol_a": sorted(x)[0], "symbol_b": sorted(x)[-1], **v} for x, v in member.items()])
    for c in M.columns:
        if c not in ("symbol_a", "symbol_b") and not c.endswith("eligible_from"):
            M[c] = M[c].fillna(False).astype(bool)
    return pd.DataFrame(rows), M


def _real_cleaner():
    import clean_pool_identity_pairs as cpi
    cache = {}

    def clean(frame):
        if len(frame) == 0:
            return frame
        P = frame.assign(tf_label="1D").reset_index(drop=True)
        C, _ = cpi.clean_pool(P, "fs", cache)
        return C
    return clean


def main():
    rd = lambda n, cols=None: parquet_io.read_parquet(os.path.join(R_DIR, n), columns=cols)
    tier1 = rd(f"{SCAN}_tier1.parquet", ["symbol_a", "symbol_b", "pvalue", "fdr_confirmed"])
    t2 = tested_keys(rd(f"{SCAN}_tier2_windows.parquet", ["symbol_a", "symbol_b"]))
    t3 = tested_keys(rd(f"{SCAN}_tier3_windows.parquet", ["symbol_a", "symbol_b"]))
    pools = {k: rd(f"purity_pairs_pit_k{k}_clean.parquet") for k in (1, 2)}
    print(f"tier1 m={len(tier1):,} (confirmed {int(tier1['fdr_confirmed'].sum())}); pairs with a gated window: "
          f"tier2 {len(t2):,}, tier3 {len(t3):,}; alpha {Config.STATS.FDR_ALPHA}", flush=True)
    S, M = compare(tier1, t2, t3, pools, Config.STATS.FDR_ALPHA, _real_cleaner())
    S.to_parquet(os.path.join(R_DIR, "fullsample_gated_arm_summary.parquet"), index=False)
    M.to_parquet(os.path.join(R_DIR, "fullsample_gated_arm_pairs.parquet"), index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 40):
        print(S.T.to_string())
    for k in (1, 2):
        c = "fs_gated_clean_tier2"
        if c in M and f"pit_k{k}" in M:
            sh = M[M[c] & M[f"pit_k{k}"]]
            print(f"\nshared pairs, gated full-sample (tier2 family, clean) and PIT k{k}: {len(sh)}")
            if len(sh):
                print(sh[["symbol_a", "symbol_b", f"pit_k{k}_eligible_from"]].to_string(index=False))


if __name__ == "__main__":
    main()
