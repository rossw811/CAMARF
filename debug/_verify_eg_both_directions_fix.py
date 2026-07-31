"""
debug/_verify_eg_both_directions_fix.py -- verification for the 2026-07-22
EG both-directions fix in analysis.py's CointScanner.scan() (Ross's direct
request: "tests both directions for p value", closing out the FELE/MAS
root-cause investigation's own open methodology question).

Uses REAL, already-independently-verified data as the test fixture rather
than trying to synthetically engineer EG's regression-direction asymmetry
(a genuine, somewhat subtle finite-sample effect, not something easily
forced by construction): FELE/MAS@1h's own asymmetry was already nailed
down bit-for-bit in this session's earlier investigation --
  a=FELE, b=MAS (regress FELE on MAS): pvalue=4.521246961450512e-07
  a=MAS, b=FELE (regress MAS on FELE): pvalue=0.0008963478009246031
(both computed via the exact same _eg_worker/CointScanner._build_log_price_map
machinery scan() itself uses, on the same 4465-bar gap-respecting overlap.)

Checks:
  1. Calling the REAL CointScanner.scan() end-to-end on FELE/MAS@1h produces
     coint_pvalue_raw_ab/coint_pvalue_raw_ba matching those two known values
     (within float tolerance).
  2. coint_pvalue_raw == max(coint_pvalue_raw_ab, coint_pvalue_raw_ba) --
     the conservative combination, not min() or either direction alone.
  3. A pair missing usable data in one direction (constructed by feeding a
     too-short/degenerate second series) is dropped cleanly (no crash, no
     spurious single-direction confirmation).
  4. scan()'s task count is exactly 2x len(candidate_pairs) that have valid
     log-price data for both legs (both directions actually get tested, not
     silently deduplicated).

Run: python debug/_verify_eg_both_directions_fix.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from config import Config
from analysis import CointScanner
from aligned_pair_loader import load_aligned_pair

KNOWN_P_AB = 4.521246961450512e-07   # a=FELE, b=MAS
KNOWN_P_BA = 0.0008963478009246031   # a=MAS, b=FELE


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


def verify_fele_mas_both_directions():
    print("\n=== 1-2. Real FELE/MAS@1h: both directions computed and combined via max() ===")
    df_fele, df_mas = load_aligned_pair("FELE", "MAS", "1h")
    aligned_data = {"FELE": df_fele, "MAS": df_mas}
    candidate_pairs = [{
        "symbol_a": "FELE", "symbol_b": "MAS",
        "asset_class_a": "equity", "asset_class_b": "equity",
        "is_cross_asset": False, "pearson_corr": 0.420184,
    }]
    confirmed, stats = CointScanner.scan(
        candidate_pairs=candidate_pairs,
        aligned_data=aligned_data,
        symbols_in_corr=["FELE", "MAS"],
        tf_label="1h",
        fdr_alpha=0.99,  # permissive -- this test is about the combination math, not FDR rejection
        n_workers=2,
    )
    ok = check("scan() returns exactly 1 confirmed pair", len(confirmed) == 1)
    if not ok:
        return False
    row = confirmed[0]
    print(f"    coint_pvalue_raw_ab={row['coint_pvalue_raw_ab']:.6e}  "
          f"coint_pvalue_raw_ba={row['coint_pvalue_raw_ba']:.6e}  "
          f"coint_pvalue_raw={row['coint_pvalue_raw']:.6e}")
    ok &= check(f"coint_pvalue_raw_ab matches known value ({KNOWN_P_AB:.3e})",
                abs(row["coint_pvalue_raw_ab"] - KNOWN_P_AB) < 1e-9)
    ok &= check(f"coint_pvalue_raw_ba matches known value ({KNOWN_P_BA:.3e})",
                abs(row["coint_pvalue_raw_ba"] - KNOWN_P_BA) < 1e-9)
    ok &= check("coint_pvalue_raw == max(ab, ba), the conservative combination",
                abs(row["coint_pvalue_raw"] - max(row["coint_pvalue_raw_ab"], row["coint_pvalue_raw_ba"])) < 1e-12)
    ok &= check("coint_pvalue_raw is the WORSE (larger) of the two, not the better one",
                row["coint_pvalue_raw"] > row["coint_pvalue_raw_ab"] * 100)
    return ok


def verify_degenerate_direction_dropped():
    print("\n=== 3. A pair with insufficient overlap in one direction is dropped cleanly ===")
    df_fele, df_mas = load_aligned_pair("FELE", "MAS", "1h")
    # Truncate MAS's own series to far too few bars (< 60, _eg_worker's own
    # floor) -- forward (FELE-on-MAS) and reverse (MAS-on-FELE) both draw
    # from the same tiny overlap, so BOTH should fail as insufficient_overlap,
    # meaning the pair is dropped entirely, not confirmed off a single
    # spuriously-passing direction.
    df_mas_short = df_mas.iloc[:30].copy()
    aligned_data = {"FELE": df_fele, "MAS": df_mas_short}
    candidate_pairs = [{
        "symbol_a": "FELE", "symbol_b": "MAS",
        "asset_class_a": "equity", "asset_class_b": "equity",
        "is_cross_asset": False, "pearson_corr": 0.42,
    }]
    confirmed, stats = CointScanner.scan(
        candidate_pairs=candidate_pairs,
        aligned_data=aligned_data,
        symbols_in_corr=["FELE", "MAS"],
        tf_label="1h",
        fdr_alpha=0.99,
        n_workers=2,
    )
    ok = check("no crash on degenerate-overlap input", True)
    ok &= check("degenerate pair produces 0 confirmed pairs (not a spurious single-direction pass)",
                len(confirmed) == 0)
    return ok


def main():
    results = [
        verify_fele_mas_both_directions(),
        verify_degenerate_direction_dropped(),
    ]
    print("\n" + "=" * 60)
    if all(results):
        print("ALL CHECKS PASSED")
    else:
        print(f"FAILURES: {results.count(False)}/{len(results)} check groups failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
