"""
Synthetic verification of research/fundamental_pair_tagger.py's
tag_fundamental_similarity BEFORE trusting it on real Compustat data.

Checks:
  1. Two symbols with identical GICS sector and similar book equity tag
     same_gics_sector=True with a size_ratio close to 1.0.
  2. Two cross-sector symbols with very different book equity tag
     same_gics_sector=False with a small size_ratio.
  3. PIT-SAFETY (the critical check): a fundamentals row dated AFTER
     as_of_date -- even considering the reporting lag -- must NEVER be
     used. Constructed so the ONLY row that would give the "right" answer
     is not yet available as of as_of_date; the tagger must fall back to
     an OLDER (or no) row instead, never peek at the future one.
  4. A symbol with no permno resolution returns None fields, not a crash
     or a spurious False/0 result (unresolved != dissimilar).
  5. Negative/zero book equity is excluded from the size ratio (not a
     nonsensical negative or >1 ratio).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from research.fundamental_pair_tagger import tag_fundamental_similarity, _REPORTING_LAG_DAYS


def _row(gvkey, permno, datadate, ceq):
    return {"gvkey": gvkey, "permno": permno, "datadate": pd.Timestamp(datadate),
            "available_date": pd.Timestamp(datadate) + pd.Timedelta(days=_REPORTING_LAG_DAYS),
            "fyear": pd.Timestamp(datadate).year, "at": ceq * 1.5, "sale": ceq, "revt": ceq,
            "ni": ceq * 0.1, "ceq": ceq, "csho": 10.0}


def main():
    failures = []

    permno_by_symbol = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4, "EEE": 5}
    funda_df = pd.DataFrame([
        _row("G001", 1, "2022-12-31", 1000.0),
        _row("G002", 2, "2022-12-31", 900.0),
        _row("G003", 3, "2022-12-31", 50.0),
        _row("G004", 4, "2022-12-31", 1000.0),
        # EEE: an OLDER, PIT-eligible row, and a NEWER row that would flip the
        # sector match but is NOT yet available as of the test's as_of_date.
        _row("G005a", 5, "2020-01-01", 500.0),
        _row("G005b", 5, "2023-06-01", 500.0),
    ])
    company_by_gvkey = {
        "G001": {"sic": "1000", "gsector": "20", "gind": "201010", "conm": "AAA CORP"},
        "G002": {"sic": "1001", "gsector": "20", "gind": "201020", "conm": "BBB CORP"},
        "G003": {"sic": "2000", "gsector": "45", "gind": "451010", "conm": "CCC CORP"},
        "G004": {"sic": "1000", "gsector": "20", "gind": "201010", "conm": "DDD CORP"},
        "G005a": {"sic": "1000", "gsector": "20", "gind": "201010", "conm": "EEE CORP (OLD)"},
        "G005b": {"sic": "9999", "gsector": "60", "gind": "601010", "conm": "EEE CORP (NEW)"},
    }

    as_of = pd.Timestamp("2023-06-01")  # AAA/BBB's data: available_date = 2022-12-31 + 90d ~ 2023-03-31, before as_of

    # --- 1: same sector, similar size ---
    t_ab = tag_fundamental_similarity("AAA", "BBB", as_of, permno_by_symbol, funda_df, company_by_gvkey)
    if t_ab["same_gics_sector"] is not True:
        failures.append(f"AAA/BBB should tag same_gics_sector=True, got {t_ab['same_gics_sector']}")
    if t_ab["size_ratio"] is None or not (0.85 <= t_ab["size_ratio"] <= 1.0):
        failures.append(f"AAA/BBB should have size_ratio near 0.9, got {t_ab['size_ratio']}")

    # --- 2: cross-sector, very different size ---
    t_ac = tag_fundamental_similarity("AAA", "CCC", as_of, permno_by_symbol, funda_df, company_by_gvkey)
    if t_ac["same_gics_sector"] is not False:
        failures.append(f"AAA/CCC should tag same_gics_sector=False, got {t_ac['same_gics_sector']}")
    if t_ac["size_ratio"] is None or t_ac["size_ratio"] > 0.1:
        failures.append(f"AAA/CCC should have a small size_ratio (~0.05), got {t_ac['size_ratio']}")

    # --- 3: PIT-safety -- the critical check ---
    # As of 2023-06-01, EEE's NEWER row (datadate 2023-06-01, available_date
    # ~2023-08-30) is NOT yet available -- only the OLDER row (gsector=20,
    # matching AAA/DDD) should be used. If the tagger wrongly used the newer
    # row, it would report same_gics_sector=False (gsector 60 != 20).
    t_ae = tag_fundamental_similarity("AAA", "EEE", as_of, permno_by_symbol, funda_df, company_by_gvkey)
    if t_ae["same_gics_sector"] is not True:
        failures.append(f"PIT-SAFETY VIOLATION: AAA/EEE used a fundamentals row not yet available "
                         f"as of {as_of} (got same_gics_sector={t_ae['same_gics_sector']}, expected "
                         f"True from the OLDER, PIT-eligible row only)")
    if t_ae["fundamentals_date_b"] != pd.Timestamp("2020-01-01"):
        failures.append(f"AAA/EEE should have used EEE's 2020-01-01 row (the only PIT-eligible one "
                         f"as of {as_of}), got {t_ae['fundamentals_date_b']}")

    # --- 4: unresolved symbol ---
    t_unresolved = tag_fundamental_similarity("AAA", "ZZZZ", as_of, permno_by_symbol, funda_df, company_by_gvkey)
    if t_unresolved["same_gics_sector"] is not None or t_unresolved["size_ratio"] is not None:
        failures.append(f"Unresolved symbol should return None fields, got {t_unresolved}")

    # --- 5: negative book equity excluded ---
    funda_neg = pd.concat([funda_df, pd.DataFrame([_row("G006", 6, "2022-12-31", -50.0)])], ignore_index=True)
    permno_by_symbol_neg = dict(permno_by_symbol, FFF=6)
    company_by_gvkey["G006"] = {"sic": "1000", "gsector": "20", "gind": "201010", "conm": "FFF CORP"}
    t_af = tag_fundamental_similarity("AAA", "FFF", as_of, permno_by_symbol_neg, funda_neg, company_by_gvkey)
    if t_af["size_ratio"] is not None:
        failures.append(f"Negative book equity should exclude size_ratio (None), got {t_af['size_ratio']}")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All fundamental pair-tagger checks passed.")
    print(f"  AAA/BBB: same_sector={t_ab['same_gics_sector']}, size_ratio={t_ab['size_ratio']:.3f}")
    print(f"  AAA/CCC: same_sector={t_ac['same_gics_sector']}, size_ratio={t_ac['size_ratio']:.3f}")
    print(f"  AAA/EEE (PIT-safety): same_sector={t_ae['same_gics_sector']}, "
          f"used_date={t_ae['fundamentals_date_b']}")
    print(f"  AAA/ZZZZ (unresolved): {t_unresolved}")
    print(f"  AAA/FFF (negative equity): size_ratio={t_af['size_ratio']}")


if __name__ == "__main__":
    main()
