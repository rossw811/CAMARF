"""
Synthetic verification of research/build_comparison_arm_pairs.py's
build_hybrid/build_purity/build_tiered BEFORE trusting them on real data.

Checks (using small synthetic standard_df/episodic_df, no real files
touched):
  1. Purity == episodic_df exactly (same rows, same columns).
  2. Hybrid = all episodic rows + standard rows NOT in episodic, tagged
     full_history_fallback; row count = len(episodic) + n_standard_only.
  3. Hybrid never duplicates a pair that exists in BOTH sets (the
     episodic version wins, standard version is dropped, not appended).
  4. Tiered has exactly len(standard_df) rows (no rows dropped, no rows
     added) regardless of overlap.
  5. Tiered's pit_confidence_tier is "full_episodic" for a standard pair
     that has an episodic match at that exact tf_label, and
     "full_history_only" for one that doesn't.
  6. Tiered does NOT tag a standard pair "full_episodic" just because the
     SAME symbol pair has an episodic match at a DIFFERENT tf_label (the
     tier check must be tf-label-specific, not symbol-pair-only).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.build_comparison_arm_pairs import build_hybrid, build_purity, build_tiered, _SHARED_SCALAR_FIELDS


def _scalar_row(**overrides):
    row = {f: 1.0 for f in _SHARED_SCALAR_FIELDS}
    row.update(overrides)
    return row


def main():
    failures = []

    # AAA/BBB@1D confirmed by BOTH standard and episodic screens.
    # CCC/DDD@1D confirmed ONLY by standard (fallback case).
    # EEE/FFF@1h confirmed ONLY by episodic (Purity-only case).
    # AAA/BBB@4h: same symbols as the overlap pair but a DIFFERENT tf --
    #   standard-confirms this one too, episodic does NOT -- tests that
    #   Tiered's tier check is tf-specific, not symbol-pair-only.
    standard_df = pd.DataFrame([
        {"symbol_a": "AAA", "symbol_b": "BBB", "tf_label": "1D", **_scalar_row()},
        {"symbol_a": "CCC", "symbol_b": "DDD", "tf_label": "1D", **_scalar_row()},
        {"symbol_a": "AAA", "symbol_b": "BBB", "tf_label": "4h", **_scalar_row()},
    ])
    episodic_df = pd.DataFrame([
        {"symbol_a": "AAA", "symbol_b": "BBB", "tf_label": "1D", "source": "wrds_1D",
         "as_of_date": pd.Timestamp("2026-08-01"), "n_windows_tested": 10,
         "n_windows_fdr_rejected": 3, **_scalar_row(hedge_ratio_ols=2.0)},
        {"symbol_a": "EEE", "symbol_b": "FFF", "tf_label": "1h", "source": "intraday_1h",
         "as_of_date": pd.Timestamp("2026-08-01"), "n_windows_tested": 5,
         "n_windows_fdr_rejected": 2, **_scalar_row()},
    ])

    # --- 1: Purity == episodic_df exactly ---
    purity = build_purity(episodic_df)
    if not purity.equals(episodic_df):
        failures.append("Purity should equal episodic_df exactly")

    # --- 2 & 3: Hybrid row count and no duplication of the overlap pair ---
    hybrid = build_hybrid(standard_df, episodic_df)
    expected_hybrid_len = len(episodic_df) + 2  # CCC/DDD@1D + AAA/BBB@4h are standard-only
    if len(hybrid) != expected_hybrid_len:
        failures.append(f"Hybrid row count: got {len(hybrid)}, expected {expected_hybrid_len}")
    aaa_bbb_1d_rows = hybrid[(hybrid.symbol_a == "AAA") & (hybrid.symbol_b == "BBB") & (hybrid.tf_label == "1D")]
    if len(aaa_bbb_1d_rows) != 1:
        failures.append(f"AAA/BBB@1D should appear exactly once in Hybrid, got {len(aaa_bbb_1d_rows)}")
    elif aaa_bbb_1d_rows.iloc[0]["source"] != "wrds_1D" or aaa_bbb_1d_rows.iloc[0]["hedge_ratio_ols"] != 2.0:
        failures.append("AAA/BBB@1D in Hybrid should be the EPISODIC version (source=wrds_1D, "
                         f"hedge_ratio_ols=2.0), got {aaa_bbb_1d_rows.iloc[0].to_dict()}")
    ccc_ddd_rows = hybrid[(hybrid.symbol_a == "CCC") & (hybrid.symbol_b == "DDD")]
    if len(ccc_ddd_rows) != 1 or ccc_ddd_rows.iloc[0]["source"] != "full_history_fallback":
        failures.append(f"CCC/DDD@1D should appear once, tagged full_history_fallback: {ccc_ddd_rows}")

    # --- 4: Tiered row count == len(standard_df), no drops/adds ---
    tiered = build_tiered(standard_df, episodic_df)
    if len(tiered) != len(standard_df):
        failures.append(f"Tiered row count should equal standard_df ({len(standard_df)}), got {len(tiered)}")

    # --- 5 & 6: tier assignment is tf-specific ---
    aaa_1d_tier = tiered[(tiered.symbol_a == "AAA") & (tiered.tf_label == "1D")]["pit_confidence_tier"].iloc[0]
    aaa_4h_tier = tiered[(tiered.symbol_a == "AAA") & (tiered.tf_label == "4h")]["pit_confidence_tier"].iloc[0]
    ccc_tier = tiered[(tiered.symbol_a == "CCC")]["pit_confidence_tier"].iloc[0]
    if aaa_1d_tier != "full_episodic":
        failures.append(f"AAA/BBB@1D should be full_episodic (has episodic match), got {aaa_1d_tier}")
    if aaa_4h_tier != "full_history_only":
        failures.append(f"AAA/BBB@4h should be full_history_only (episodic match is at 1D, not 4h "
                         f"-- tier check must be tf-specific), got {aaa_4h_tier}")
    if ccc_tier != "full_history_only":
        failures.append(f"CCC/DDD@1D should be full_history_only (no episodic match at all), got {ccc_tier}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All build_comparison_arm_pairs checks passed.")
    print(f"  Hybrid: {len(hybrid)} rows")
    print(f"  Purity: {len(purity)} rows")
    print(f"  Tiered: {len(tiered)} rows, tiers: {tiered['pit_confidence_tier'].tolist()}")


if __name__ == "__main__":
    main()
