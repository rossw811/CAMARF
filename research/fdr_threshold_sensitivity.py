"""
research/fdr_threshold_sensitivity.py -- backlog item #3 (2026-09-15 20:14 entry): "Test whether
tightening the episodic-confirmation FDR threshold shrinks the 1,375-pair Purity pool toward the
Baseline/Tiered set's positive result." Two independent literature threads (GT-Score paper,
2025 e-value FDR papers) converged on this exact question per that entry.

Deliberately does NOT re-run the ~25-hour Tier 3 rolling-window EG scan
(wrds_deep_history_episodic_scan.py) -- the expensive step (candidate generation + per-window EG
p-value computation) is already done and saved (output/research/
wrds_deep_history_episodic_scan_tier3_windows.parquet, 5,003,637 rows). Only the FINAL BH-FDR
confirmation step (episodic_bhfdr_confirm) actually depends on alpha, and it's a cheap,
independent function over already-computed p-values -- re-running the whole 25-hour scan just to
test a different alpha would be pure waste. Reuses that function directly, not reimplemented.

Usage:
    python research/fdr_threshold_sensitivity.py
    python research/fdr_threshold_sensitivity.py --alphas 0.05 0.01 0.005 0.001
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from research.wrds_deep_history_episodic_scan import episodic_bhfdr_confirm

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WINDOWS_PATH = os.path.join(_ROOT, "output", "research",
                              "wrds_deep_history_episodic_scan_tier3_windows.parquet")


def main():
    p = argparse.ArgumentParser(description="FDR-threshold sensitivity of the episodic Purity pool")
    p.add_argument("--alphas", type=float, nargs="+", default=[0.05, 0.02, 0.01, 0.005, 0.001])
    p.add_argument("--min-windows-confirmed", type=int, default=1)
    args = p.parse_args()

    if not os.path.exists(_WINDOWS_PATH):
        print(f"FATAL: {_WINDOWS_PATH} not found -- the Tier 3 scan must be run at least once first.")
        sys.exit(1)

    print(f"Loading {_WINDOWS_PATH} ...")
    df = pd.read_parquet(_WINDOWS_PATH)
    print(f"{len(df)} (pair, window) rows loaded")

    # Fresh rows per alpha -- episodic_bhfdr_confirm mutates its input dicts in place
    # (adds fdr_rejected/fdr_adjusted_pvalue), so each alpha needs its own copy.
    base_rows = df[["symbol_a", "symbol_b", "pvalue"]].to_dict("records")

    results = []
    for alpha in sorted(args.alphas, reverse=True):
        rows = [dict(r) for r in base_rows]
        confirmed = episodic_bhfdr_confirm(rows, alpha, args.min_windows_confirmed)
        results.append({"alpha": alpha, "n_confirmed_pairs": len(confirmed)})
        print(f"  alpha={alpha}: {len(confirmed)} confirmed pairs")

    out = pd.DataFrame(results)
    out_path = os.path.join(_ROOT, "output", "research", "fdr_threshold_sensitivity.parquet")
    out.to_parquet(out_path)
    print(f"\nSaved => {out_path}")
    print(out.to_string(index=False))

    baseline_n = next((r["n_confirmed_pairs"] for r in results if r["alpha"] == 0.05), None)
    if baseline_n:
        print(f"\nBaseline (alpha=0.05, current production default): {baseline_n} confirmed pairs")
        for r in results:
            if r["alpha"] != 0.05:
                pct = 100 * (1 - r["n_confirmed_pairs"] / baseline_n) if baseline_n else float("nan")
                print(f"  alpha={r['alpha']}: {r['n_confirmed_pairs']} pairs "
                      f"({pct:.1f}% shrinkage vs baseline)")


if __name__ == "__main__":
    main()
