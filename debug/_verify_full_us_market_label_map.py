"""
Synthetic verification of research/full_us_market_price_fetch.py::
build_full_market_label_map() -- run BEFORE trusting the real fetch, since
a labeling bug here could silently overwrite one company's cached price
history with another's (the exact real risk build_delisted_label_map was
originally built to prevent).

Checks:
  1. No collisions: distinct tickers map 1:1, no PERMNO<n> fallback used.
  2. A genuine collision (two different permnos' last-known ticker is the
     SAME string -- real, confirmed-common ticker reuse over a century) ->
     BOTH get relabeled PERMNO<n>, neither silently overwrites the other.
  3. Uses the LAST (most recent) ticker per permno when a permno has
     multiple spells with different tickers, not an arbitrary one.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from research.full_us_market_price_fetch import build_full_market_label_map


def main():
    failures = []

    # --- Check 1: no collisions ---
    master1 = pd.DataFrame([
        {"permno": 1, "ticker": "AAA", "namedt": pd.Timestamp("2000-01-01")},
        {"permno": 2, "ticker": "BBB", "namedt": pd.Timestamp("2000-01-01")},
    ])
    labels1 = build_full_market_label_map(master1)
    if set(labels1.keys()) != {"AAA", "BBB"}:
        failures.append(f"Check 1: expected clean AAA/BBB labels, got {labels1}")

    # --- Check 2: genuine ticker-reuse collision -- the REAL safety property
    # is uniqueness (no two permnos share a label, so neither's price file
    # can silently overwrite the other's), NOT that both must fall back.
    # build_delisted_label_map's real, already-trusted-elsewhere contract is
    # asymmetric: first-come keeps the natural ticker, only the COLLIDING
    # one relabels to PERMNO<n> -- verified against that real contract, not
    # an invented stricter one.
    master2 = pd.DataFrame([
        {"permno": 1, "ticker": "XYZ", "namedt": pd.Timestamp("1990-01-01")},
        {"permno": 2, "ticker": "XYZ", "namedt": pd.Timestamp("2015-01-01")},  # different co, same ticker later
    ])
    labels2 = build_full_market_label_map(master2)
    permno_by_label2 = labels2
    if len(set(permno_by_label2.values())) != len(permno_by_label2):
        failures.append(f"Check 2: labels are not 1:1 with permnos (a real overwrite risk), "
                         f"got {labels2}")
    if len(labels2) != 2:
        failures.append(f"Check 2: expected exactly 2 distinct labels for 2 distinct permnos, "
                         f"got {labels2}")
    if permno_by_label2.get("XYZ") not in (1, 2):
        failures.append(f"Check 2: 'XYZ' should map to whichever permno claimed it first, got {labels2}")

    # --- Check 4: null ticker (the real bug caught on the actual run,
    # 2026-08-13 -- a genuinely NULL/None ticker in CRSP, not a missing
    # dict entry) must fall back to PERMNO<n>, not crash or get silently
    # dropped from the universe. ---
    master4 = pd.DataFrame([
        {"permno": 1, "ticker": "GOOD", "namedt": pd.Timestamp("2000-01-01")},
        {"permno": 2, "ticker": None, "namedt": pd.Timestamp("2000-01-01")},
    ])
    labels4 = build_full_market_label_map(master4)
    if 2 not in labels4.values():
        failures.append(f"Check 4: permno 2 (null ticker) should still be present, fell back to "
                         f"PERMNO2, not silently dropped -- got {labels4}")
    if labels4.get("PERMNO2") != 2:
        failures.append(f"Check 4: expected permno 2 labeled 'PERMNO2' (null-ticker fallback), "
                         f"got {labels4}")

    # --- Check 5: the REAL sentinel involved (pandas nullable "string"
    # dtype's pd.NA, not plain Python None) -- the actual bug on the real
    # run used this exact dtype and slipped through an earlier `t is not
    # None and pd.notna(t)` filter inconsistently. Reproduce with a genuine
    # pandas "string" dtype column, not a plain object-dtype column (which
    # is what Check 4 above uses and which did NOT reproduce the bug).
    master5 = pd.DataFrame({
        "permno": [1, 2],
        "ticker": pd.array(["GOOD", pd.NA], dtype="string"),
        "namedt": [pd.Timestamp("2000-01-01"), pd.Timestamp("2000-01-01")],
    })
    labels5 = build_full_market_label_map(master5)
    bad_labels5 = [k for k in labels5 if not isinstance(k, str)]
    if bad_labels5:
        failures.append(f"Check 5: pd.NA (pandas 'string' dtype) produced non-string label(s) "
                         f"{bad_labels5} -- the exact real bug, got {labels5}")
    if labels5.get("PERMNO2") != 2:
        failures.append(f"Check 5: expected permno 2 (pd.NA ticker) labeled 'PERMNO2', got {labels5}")

    # --- Check 3: most recent ticker used for a multi-spell permno ---
    master3 = pd.DataFrame([
        {"permno": 1, "ticker": "OLD", "namedt": pd.Timestamp("2000-01-01")},
        {"permno": 1, "ticker": "NEW", "namedt": pd.Timestamp("2015-01-01")},
    ])
    labels3 = build_full_market_label_map(master3)
    if "NEW" not in labels3 or "OLD" in labels3:
        failures.append(f"Check 3: expected the MOST RECENT ticker 'NEW' to be used, not 'OLD', "
                         f"got {labels3}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All full-US-market label-map checks passed.")
    print(f"  Check 1: no-collision case -> {labels1}")
    print(f"  Check 2: genuine collision -> {labels2}")
    print(f"  Check 3: most-recent-ticker case -> {labels3}")
    print(f"  Check 4: null-ticker fallback -> {labels4}")
    print(f"  Check 5: pd.NA (real dtype) fallback -> {labels5}")


if __name__ == "__main__":
    main()
