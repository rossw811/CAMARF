"""
research/bh_fdr_dependence_check.py -- tests whether CAMARF's per-timeframe
Benjamini-Hochberg (1995) FDR correction (analysis.py's `_benjamini_hochberg`,
applied once per timeframe across all correlation-pre-filtered candidate
pairs) has its independence/PRDS assumption violated in practice, and
whether a dependency-robust alternative (Benjamini-Yekutieli 2001, valid
under arbitrary dependence) changes the confirmed-pair count materially.

Motivated directly by the Monte Carlo EG-calibration study
(research/eg_null_calibration_montecarlo.py), which found randomly-paired
real equities show elevated, horizon-growing false-positive rates from
shared market-wide drift -- raising the question of whether candidate
pairs' EG p-values are independent draws, as BH's original guarantee
assumes, or share dependence structure that only the weaker
Benjamini-Yekutieli guarantee (valid under arbitrary dependence) covers.

Not part of the production pipeline -- standalone diagnostic, matching this
project's research/ convention. Reuses analysis.py's real
`_benjamini_hochberg` implementation directly for the BH baseline (not a
reimplementation), and the real 1h `all_candidates.parquet` production
output (353 candidate pairs, pre-FDR) for the real-data test.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import _benjamini_hochberg


def benjamini_yekutieli(pvalues: np.ndarray, alpha: float):
    """
    Benjamini-Yekutieli (2001) FDR correction -- same procedure as BH (1995)
    but with the rank threshold divided by c(m) = sum_{i=1}^m 1/i, the
    harmonic number, which extends the FDR-control guarantee to hold under
    ARBITRARY dependence among the test statistics (not just independence
    or positive regression dependency, which is all BH's own 1995 proof
    covers). Always at least as conservative as plain BH on the same data.
    """
    p = np.asarray(pvalues, dtype=float)
    n = p.size
    if n == 0:
        return np.array([], dtype=bool), np.array([], dtype=float)

    c_m = np.sum(1.0 / np.arange(1, n + 1))
    order = np.argsort(p)
    p_sorted = p[order]
    ranks = np.arange(1, n + 1)
    threshold = ranks * alpha / (n * c_m)

    below = p_sorted <= threshold
    if not np.any(below):
        k = 0
    else:
        k = np.max(np.where(below)[0]) + 1

    rejected_sorted = np.zeros(n, dtype=bool)
    rejected_sorted[:k] = True
    rejected = np.zeros(n, dtype=bool)
    rejected[order] = rejected_sorted

    # Adjusted p-values (monotone, min over j>=k of (m*c_m/j)*p(j), capped at 1)
    adj_sorted = np.minimum.accumulate((n * c_m / ranks * p_sorted)[::-1])[::-1]
    adj_sorted = np.clip(adj_sorted, 0, 1)
    adjusted = np.empty(n)
    adjusted[order] = adj_sorted

    return rejected, adjusted


def characterize_dd_hub_dominance(candidates_path: str = "output/results/1hr/all_candidates.parquet"):
    """Quantify the DD-leg dominance in the real 1h candidate set."""
    df = pd.read_parquet(candidates_path)
    dd_mask = (df.symbol_a == "DD") | (df.symbol_b == "DD")
    dd_rows = df[dd_mask]
    non_dd = df[~dd_mask]

    result = {
        "n_total_candidates": len(df),
        "n_dd_leg_candidates": len(dd_rows),
        "dd_leg_fraction": len(dd_rows) / len(df),
        "dd_pearson_corr_median": float(dd_rows.pearson_corr.median()),
        "dd_pearson_corr_min": float(dd_rows.pearson_corr.min()),
        "dd_pearson_corr_max": float(dd_rows.pearson_corr.max()),
        "non_dd_pearson_corr_median": float(non_dd.pearson_corr.median()),
        "dd_pvalue_median": float(dd_rows.coint_pvalue_raw.median()),
        "non_dd_pvalue_median": float(non_dd.coint_pvalue_raw.median()),
        "dd_thin_info_content_any_true": bool(dd_rows["thin_info_content"].any())
        if "thin_info_content" in df.columns
        else None,
    }
    return result, df


def compare_bh_vs_by(df: pd.DataFrame, alpha: float = 0.05):
    """
    Real-data comparison: current production BH result vs. dependency-robust
    Benjamini-Yekutieli, on the same real 1h candidate p-values. Also runs a
    third variant -- BH applied only to the non-DD-leg subset (94 pairs),
    treating the 259 DD-leg candidates as effectively one shared-factor
    cluster rather than 259 independent tests -- as a direct test of how
    much the DD-hub's raw dominance is inflating the correction's effective
    m.
    """
    pvals = df["coint_pvalue_raw"].to_numpy()
    dd_mask = ((df.symbol_a == "DD") | (df.symbol_b == "DD")).to_numpy()

    bh_rejected, _ = _benjamini_hochberg(pvals, alpha)
    by_rejected, _ = benjamini_yekutieli(pvals, alpha)

    # Non-DD-only BH: correct only the 94 pairs not involving DD, on their own.
    non_dd_pvals = pvals[~dd_mask]
    bh_nondd_rejected, _ = _benjamini_hochberg(non_dd_pvals, alpha)

    return {
        "m_total": len(pvals),
        "bh_confirmed": int(bh_rejected.sum()),
        "by_confirmed": int(by_rejected.sum()),
        "by_confirmed_dd_leg": int(by_rejected[dd_mask].sum()),
        "by_confirmed_non_dd": int(by_rejected[~dd_mask].sum()),
        "bh_confirmed_dd_leg": int(bh_rejected[dd_mask].sum()),
        "bh_confirmed_non_dd": int(bh_rejected[~dd_mask].sum()),
        "m_non_dd_only": len(non_dd_pvals),
        "bh_non_dd_only_confirmed": int(bh_nondd_rejected.sum()),
        "bh_non_dd_only_confirmed_of_non_dd_candidates": int(bh_nondd_rejected.sum()),
    }


if __name__ == "__main__":
    dom, df = characterize_dd_hub_dominance()
    print("=== DD-hub raw candidate dominance (1h) ===")
    for k, v in dom.items():
        print(f"  {k}: {v}")

    print("\n=== BH vs. Benjamini-Yekutieli comparison (real 1h candidates) ===")
    cmp = compare_bh_vs_by(df)
    for k, v in cmp.items():
        print(f"  {k}: {v}")

    out = pd.DataFrame([{**dom, **cmp}])
    out = out.drop(columns=["n_dd_leg_candidates"], errors="ignore")  # already in dom, avoid dup key issue
    out.to_parquet("output/research/bh_fdr_dependence_check.parquet")
    print("\nSaved: output/research/bh_fdr_dependence_check.parquet")
