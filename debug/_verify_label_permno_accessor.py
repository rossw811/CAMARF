"""
One label -> PERMNO map for every consumer (2026-10-12, label-map identity bug). Before: full_us_market_label_map
(wrong for 72 labels, e.g. TM -> Toastmaster) fed the volume restatement, universe_loader's PERMNO aliasing and the
same-company pool rule; symbol_permno_map (wrong for 2,122 labels, e.g. SNS Sundstrand -> Biglari) fed the discovery
scan's S&P membership gate. The content-verified map is output/cache/wrds/wrds_label_permno_final.parquet
(research/identify_wrds_files.py). Written failing-first. Checks:
  1. data_wrds.label_permno_map(path) returns {label: permno} for resolved rows only (unresolved -> absent)
  2. a missing map file raises (no silent fallback to an old map)
  3. the consumers read it: wrds_deep_history_episodic_scan.load_membership_gate, universe_loader (D17 aliasing),
     apply_crsp_volume_adjustment.main, clean_pool_identity_pairs.main -- and none of them reads the two old maps
Run: python debug/_verify_label_permno_accessor.py
"""
import os
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    import data_wrds as dw
    f = getattr(dw, "label_permno_map", None)
    check("accessor_exists", f is not None)
    if f is not None:
        d = tempfile.mkdtemp(); p = os.path.join(d, "m.parquet")
        pd.DataFrame({"label": ["TM", "BRK", "PERMNO5"], "permno": [76655, np.nan, 5],
                      "source": ["returns", "unresolved_none", "self"]}).to_parquet(p)
        m = f(p)
        check("resolved_only", m == {"TM": 76655, "PERMNO5": 5}, m)
        try:
            f(os.path.join(d, "missing.parquet")); check("missing_raises", False)
        except FileNotFoundError:
            check("missing_raises", True)
    files = {"research/wrds_deep_history_episodic_scan.py": "load_membership_gate",
             "universe_loader.py": None, "research/apply_crsp_volume_adjustment.py": "main",
             "research/clean_pool_identity_pairs.py": "build_company_ids"}   # main delegates to it (2026-10-20 refactor)
    for path, fn in files.items():
        s = open(os.path.join(ROOT, path), encoding="utf-8").read()
        body = s
        if fn:
            i = s.index(f"def {fn}(")
            j = s.find("\ndef ", i + 5)
            body = s[i: j if j > 0 else len(s)]
        uses = "label_permno_map(" in body
        old = ("full_us_market_label_map.parquet" in body) or ("symbol_permno_map.parquet" in body) or \
              ("_SYMBOL_PERMNO_MAP_PATH" in body) or ("LABEL_MAP_PATH" in body)
        check(f"consumer_{os.path.basename(path)}", uses and not old, f"uses={uses} reads_old_map={old}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
