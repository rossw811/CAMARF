"""
E1 score (research/placebo_discovery_e1.py score()): in a placebo universe the only true relationships are plants with
their OWN base; every other pair is null, including a plant paired with another symbol. V6 review 2026-11-11: such
pairs were neither counted as false positives nor as found (k2: 15 / 4 / 4 across the v2 seeds), and their windows
were left out of the null tail rates. Checks on a toy run (plant P on base A; pool = (P, A), (P, X), (Y, Z)):
  1. false_positives = 2 ((P, X) and (Y, Z)); null_with_plant = 1; pool_pairs = 3
  2. recovery: the plant is tested and found
  3. null windows behind placebo_rates include the (P, X) windows and exclude the (P, A) windows
Run: python debug/_verify_placebo_score_null_pairs.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import pandas as pd

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    from research import placebo_discovery_e1 as E
    d = tempfile.mkdtemp(prefix="e1score_")
    try:
        pd.DataFrame([{"plant": "P", "base": "A", "arm": "us", "half_life": 5, "spread_sd": 0.05}]).to_parquet(
            os.path.join(d, "_e1_plants.parquet"))
        # windows: (P, A) two strong windows; (P, X) one window at 1e-6 and one at 0.5; (Y, Z) one at 1e-6
        W = pd.DataFrame({"symbol_a": ["P", "P", "P", "P", "Y"], "symbol_b": ["A", "A", "X", "X", "Z"],
                          "pvalue": [1e-12, 1e-10, 1e-6, 0.5, 1e-6], "fdr_rejected": [True, True, True, False, True]})
        W.to_parquet(os.path.join(d, "wrds_deep_history_episodic_scan_tier3_windows.parquet"))
        for k in (1, 2):
            pd.DataFrame({"symbol_a": ["P", "P", "Y"], "symbol_b": ["A", "X", "Z"], "tf_label": ["1D"] * 3,
                          "arm": ["us_us_gated"] * 3}).to_parquet(os.path.join(d, f"purity_pairs_pit_k{k}_clean.parquet"))
        E._windows_by_arm = lambda path, cols=None: __import__("parquet_io").read_parquet(path).assign(arm="us_us_gated")
        out = E.score(d, d)
        row = out["pool"].query("pool == 'k2'").iloc[0]
        check("1 false positives count the plant-with-other pair", int(row["false_positives"]) == 2
              and int(row.get("null_with_plant", -1)) == 1 and int(row["pool_pairs"]) == 3, row.to_dict())
        rec = out["recovery"].query("pool == 'k2'").iloc[0]
        check("2 own-base plant tested and found", bool(rec["tested"]) and bool(rec["found"]), rec.to_dict())
        r = out["placebo_rates"].iloc[0]
        check("3 null windows = the 3 non-own windows", int(r["n_windows"]) == 3, r.to_dict())
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
