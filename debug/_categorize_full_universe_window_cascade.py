"""
debug/_categorize_full_universe_window_cascade.py

Applies the same honest artifact/dedup categorization already done manually
for the 10y full-universe cascade (see output/research/full_universe_eg_confirmed_pairs_CLEAN.parquet,
2026-08-16 session) to the 5y and 3y cascades run the same session, so all three
can be compared on equal footing. Read-only analysis script, writes one summary
parquet + prints the comparison table -- does not modify the underlying confirmed-pair
files.

Categories, in priority order (a pair is assigned to the first category it matches):
  1. index_tracking   -- CrossAssetTagger._is_index_tracking_pair (e.g. SPY/VOO)
  2. share_class_known -- CrossAssetTagger._is_share_class_pair (small hardcoded whitelist)
  3. share_class_heuristic -- same ticker root + single trailing letter differs
                              (e.g. LBRDA/LBRDK, WLY/WLYB) -- NOT in analysis.py's
                              whitelist, flagged for manual confirmation, not auto-trusted
  4. permno_fallback  -- either leg is a PERMNO<n> fallback label (Thread K collision
                          naming) -- near-zero expected here since filter_exact_correlation_
                          duplicates() already dropped |corr|>=0.999999 candidates upstream,
                          but residual cases can still exist per the 10y investigation
                          (MKC/PERMNO89155 etc. had non-1.0 but still-suspicious correlation)
  5. novel            -- did not match any of the above; still not proof of genuine novelty,
                          just "not caught by these specific heuristics"
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from analysis import CrossAssetTagger

_OUT_DIR = os.path.join("output", "research")

SHARE_CLASS_SUFFIX_RE = re.compile(r"^([A-Z0-9\.]+?)([A-Z])$")
GVKEY_ROOT_RE = re.compile(r"^(GVKEY\d+)_\d+W$")

# High-correlation cutoff for flagging likely same-underlying-security duplicates
# that filter_exact_correlation_duplicates() (>=0.999999) didn't catch -- e.g.
# a ticker and its own GVKEY-labeled cross-source twin at corr=0.9988, not exactly
# 1.0 (different adjustment/source), but nowhere near the 0.60-0.80 range every
# confirmed genuinely-novel pair in this dataset actually falls in. Not a proof of
# duplication on its own, just a strong prior worth separating from "novel" -- see
# the corr distribution printed by this script before trusting the cutoff blindly.
HIGH_CORR_DUPLICATE_CUTOFF = 0.95


def _share_class_heuristic(sym_a, sym_b):
    """Same root ticker, differing only in a single trailing letter (A/B/K/etc)."""
    ma = SHARE_CLASS_SUFFIX_RE.match(sym_a)
    mb = SHARE_CLASS_SUFFIX_RE.match(sym_b)
    if not (ma and mb):
        return False
    return ma.group(1) == mb.group(1) and ma.group(2) != mb.group(2)


def _same_gvkey_root(sym_a, sym_b):
    """Same GVKEY, different security-ID suffix (_NNW) -- same company, different listing."""
    ma = GVKEY_ROOT_RE.match(sym_a)
    mb = GVKEY_ROOT_RE.match(sym_b)
    if not (ma and mb):
        return False
    return ma.group(1) == mb.group(1)


def categorize(df):
    cats = []
    for _, row in df.iterrows():
        a, b = row["symbol_a"], row["symbol_b"]
        if CrossAssetTagger._is_index_tracking_pair(a, b):
            cats.append("index_tracking")
        elif CrossAssetTagger._is_share_class_pair(a, b):
            cats.append("share_class_known")
        elif _share_class_heuristic(a, b):
            cats.append("share_class_heuristic")
        elif _same_gvkey_root(a, b):
            cats.append("same_gvkey_root")
        elif a.startswith("PERMNO") or b.startswith("PERMNO"):
            cats.append("permno_fallback")
        elif abs(row["pearson_corr"]) >= HIGH_CORR_DUPLICATE_CUTOFF:
            cats.append("high_corr_likely_duplicate")
        else:
            cats.append("novel")
    out = df.copy()
    out["category"] = cats
    return out


def main():
    summary_rows = []
    all_novel = {}
    for window in ["3y", "5y", "10y"]:
        path = os.path.join(_OUT_DIR, f"full_universe_eg_confirmed_pairs_{window}.parquet")
        df = pd.read_parquet(path)
        cat_df = categorize(df)
        counts = cat_df["category"].value_counts().to_dict()
        novel = cat_df[cat_df["category"] == "novel"]
        all_novel[window] = set(zip(novel["symbol_a"], novel["symbol_b"]))
        summary_rows.append({
            "window": window,
            "n_confirmed": len(df),
            "index_tracking": counts.get("index_tracking", 0),
            "share_class_known": counts.get("share_class_known", 0),
            "share_class_heuristic": counts.get("share_class_heuristic", 0),
            "same_gvkey_root": counts.get("same_gvkey_root", 0),
            "permno_fallback": counts.get("permno_fallback", 0),
            "high_corr_likely_duplicate": counts.get("high_corr_likely_duplicate", 0),
            "novel": counts.get("novel", 0),
        })
        cat_df.to_parquet(os.path.join(_OUT_DIR, f"full_universe_eg_confirmed_pairs_{window}_categorized.parquet"), index=False)
        print(f"\n=== {window} novel candidates ({len(novel)}) ===")
        print(novel[["symbol_a", "symbol_b", "pearson_corr", "coint_pvalue_adjusted", "n_overlap"]].to_string(index=False))

    summary_df = pd.DataFrame(summary_rows)
    print("\n=== Summary ===")
    print(summary_df.to_string(index=False))
    summary_df.to_parquet(os.path.join(_OUT_DIR, "full_universe_window_cascade_comparison.parquet"), index=False)

    # Overlap of novel candidates across windows (unordered pair identity)
    def norm(pairs):
        return {frozenset(p) for p in pairs}

    n3, n5, n10 = norm(all_novel["3y"]), norm(all_novel["5y"]), norm(all_novel["10y"])
    print(f"\n=== Novel-pair overlap across windows ===")
    print(f"3y AND 5y: {sorted(n3 & n5)}")
    print(f"3y AND 10y: {sorted(n3 & n10)}")
    print(f"5y AND 10y: {sorted(n5 & n10)}")
    print(f"3y AND 5y AND 10y: {sorted(n3 & n5 & n10)}")
    print(f"3y only: {sorted(n3 - n5 - n10)}")
    print(f"5y only: {sorted(n5 - n3 - n10)}")
    print(f"10y only: {sorted(n10 - n3 - n5)}")


if __name__ == "__main__":
    main()
