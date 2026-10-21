"""
D14 positive controls (Ross 2026-10-12: dual-listed twins are excluded from pools as one economic entity and KEPT as
positive controls). The classic Froot-Dabora pairs (Royal Dutch/Shell, Unilever NV/plc, Rio Tinto plc/Ltd, BHP,
Carnival ...) share one set of cash flows, so a working discovery screen should find them. This reads what the 1D
discovery did with every twin pair it could see:

  Tier 1  (full-history EG on correlation-prefiltered pairs): tested? p, FDR-confirmed?
  Tier 3  (episodic windows): did the pair pass the per-window correlation prefilter, how many windows were tested,
          how many were BH-rejected, first rejection date.

Descriptive only (a power check on known pairs): nothing here selects or trades. Twins are matched with the clean
step's company ids (clean_pool_identity_pairs.build_company_ids, dlc_twin). A twin can be missing from discovery
because a side has no WRDS file, its history is too short, or it failed the correlation prefilter -- reported per pair.
Inputs: output/research/wrds_deep_history_episodic_scan_{tier1,tier3_pairs,tier3_windows}.parquet, the WRDS 1D
labels, research/dual_listed_companies_ids.csv. Output: output/research/dlc_positive_controls_d14.parquet.
Check: debug/_verify_dlc_positive_controls_d14.py.
"""
import os
import sys

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "research"))

_R = os.path.join(_ROOT, "output", "research")
_OUT = os.path.join(_R, "dlc_positive_controls_d14.parquet")


def twin_label_pairs(ids: dict, sides: dict) -> pd.DataFrame:
    """Every (label on side A, label on side B) of each dual-listed company; one row per unordered label pair."""
    rows = []
    for name, (A, B) in sides.items():
        la = sorted(l for l, s in ids.items() if s and s & A)
        lb = sorted(l for l, s in ids.items() if s and s & B)
        for a in la:
            for b in lb:
                if a != b:
                    x, y = sorted((a, b))
                    rows.append({"dlc_name": name, "symbol_a": x, "symbol_b": y})
    return pd.DataFrame(rows, columns=["dlc_name", "symbol_a", "symbol_b"]).drop_duplicates(["symbol_a", "symbol_b"])


def _key(df):
    a, b = df["symbol_a"].astype(str), df["symbol_b"].astype(str)
    return pd.Series([tuple(sorted(t)) for t in zip(a, b)], index=df.index)


def discovery_record(twins: pd.DataFrame, tier1: pd.DataFrame, tier3_pairs: pd.DataFrame,
                     tier3_windows: pd.DataFrame) -> pd.DataFrame:
    out = twins.copy()
    k = _key(out)
    t1 = tier1.assign(_k=_key(tier1)).drop_duplicates("_k").set_index("_k")
    out["tier1_tested"] = k.isin(t1.index).to_numpy()
    out["tier1_pvalue"] = [t1["pvalue"].get(x) for x in k]
    out["tier1_fdr_confirmed"] = [bool(t1["fdr_confirmed"].get(x, False)) for x in k]
    out["tier3_prefilter_passed"] = k.isin(set(_key(tier3_pairs))).to_numpy()
    w = tier3_windows.assign(_k=_key(tier3_windows))
    w = w[w["_k"].isin(set(k))]
    rej = w[w["fdr_rejected"].astype(bool)]
    out["tier3_windows_tested"] = [int((w["_k"] == x).sum()) for x in k]
    out["tier3_windows_rejected"] = [int((rej["_k"] == x).sum()) for x in k]
    first = rej.groupby("_k")["window_end_date"].min()
    out["tier3_first_rejection"] = [first.get(x) for x in k]
    out["found_by_discovery"] = out["tier1_fdr_confirmed"] | (out["tier3_windows_rejected"] > 0)
    return out


def main():
    from clean_pool_identity_pairs import build_company_ids, load_dlc_sides
    labels = sorted(f[:-len("_1D.parquet")] for f in os.listdir(os.path.join(_ROOT, "output", "cache", "wrds"))
                    if f.endswith("_1D.parquet"))
    ids = build_company_ids(labels)
    sides = load_dlc_sides()
    twins = twin_label_pairs(ids, sides)
    print(f"{len(sides)} dual-listed companies with both sides in the data; {len(twins)} twin label pairs")
    tier1 = pd.read_parquet(os.path.join(_R, "wrds_deep_history_episodic_scan_tier1.parquet"),
                            columns=["symbol_a", "symbol_b", "pvalue", "fdr_confirmed"])
    t3p = pd.read_parquet(os.path.join(_R, "wrds_deep_history_episodic_scan_tier3_pairs.parquet"),
                          columns=["symbol_a", "symbol_b"])
    names = set(twins["symbol_a"]) | set(twins["symbol_b"])
    t3w = pd.read_parquet(os.path.join(_R, "wrds_deep_history_episodic_scan_tier3_windows.parquet"),
                          columns=["symbol_a", "symbol_b", "window_end_date", "fdr_rejected"])
    t3w = t3w[t3w["symbol_a"].isin(names) & t3w["symbol_b"].isin(names)]
    rec = discovery_record(twins, tier1, t3p, t3w)
    rec.to_parquet(_OUT, index=False)
    pd.set_option("display.width", 250)
    print(rec.to_string(index=False))
    print(f"found by discovery: {int(rec.found_by_discovery.sum())} of {len(rec)} twin label pairs; "
          f"{rec.groupby('dlc_name').found_by_discovery.any().sum()} of {rec.dlc_name.nunique()} companies\n-> {_OUT}")


if __name__ == "__main__":
    main()
