"""
CAMARF adf_confirmatory_tier.py — comparison/diagnostic method, NOT part of the
production pipeline (research/ convention: reads existing spread_series_*.parquet,
never fetches, never recomputes hedge ratios).

Ross's question (2026-07-13): should a standalone Augmented Dickey-Fuller (ADF) test
be integrated into stats.py's existing EG+KPSS+PO confirmatory tiering (Section 1)?

Context, established before building this: CAMARF already relies on ADF-family logic
pervasively without ever running a *standalone* ADF directly on the spread — EG's own
second step is itself an ADF-type test on the cointegrating residual; Zivot-Andrews
(used in the secondary-evidence override, analysis.py) is literally "ADF with one
structural break"; Phillips-Ouliaris's Z_t (already the third of stats.py's three
existing tiers, implemented there as Phillips-Perron on OLS residuals per Phillips &
Ouliaris 1990) is a closely related residual unit-root test. The expectation stated to
Ross before this was built: a standalone ADF run directly on the spread is cheap to
add but likely highly correlated with the existing PO test specifically, since both are
residual/spread unit-root tests from the same statistical family — this module measures
that agreement rate directly rather than assuming it.

ADF null hypothesis: unit root (non-stationary). Rejecting the null (low p-value) means
the spread IS stationary -> confirms cointegration. This is the SAME direction as PO
(also a unit-root test), and the OPPOSITE direction from KPSS (whose null is
"stationary" -- KPSS confirms via FAILING to reject). Convention here matches PO's
threshold (p < 0.10) for consistency, since both are the same test family; see
debug/_verify_adf_confirmatory_tier.py Case 3 for the explicit direction check.

Usage:
    python research/adf_confirmatory_tier.py
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from aligned_pair_loader import (
    TF_DIRS as _TF_DIRS,
    DIR_TO_LABEL as _DIR_TO_LABEL,
    resolve_tf_results_dir as _resolve_tf_results_dir,
)

_ADF_ALPHA = 0.10  # matches stats.py's PO threshold — same test family, same bar


def run_adf_test(spread: np.ndarray) -> dict:
    """Standalone ADF on a clean (NaN-free, gap-masked) 1-D spread array.
    Returns adf_stat, adf_pval, adf_confirms (True = rejects unit-root null =
    stationary = cointegration-consistent, matching PO's convention)."""
    spread = np.asarray(spread, dtype=float)
    spread = spread[np.isfinite(spread)]
    # Tier 6 fix (Grand Sweep 2026-07-20): `status` now explicitly
    # distinguishes "insufficient_data" (< 20 clean bars, never even
    # attempted), "error" (adfuller raised), and "ok" (ran successfully,
    # adf_pval is a real, possibly-non-significant number) -- previously
    # the exception text was captured into a dict key ("error") that
    # main() never actually included in the saved row, so all three cases
    # collapsed into an indistinguishable NaN adf_pval in the output
    # parquet.
    result = {"adf_stat": np.nan, "adf_pval": np.nan, "adf_confirms": False,
              "n_obs": int(spread.size), "status": "insufficient_data"}
    if spread.size < 20:
        return result
    try:
        stat, pval, _usedlag, _nobs, _crit, _icbest = adfuller(spread, regression="c", autolag="AIC")
        result["adf_stat"] = float(stat)
        result["adf_pval"] = float(pval)
        result["adf_confirms"] = bool(pval < _ADF_ALPHA)
        result["status"] = "ok"
    except Exception as e:
        result["status"] = f"error: {e}"
    return result


def _kpss_po(spread: np.ndarray) -> dict:
    """Reuse stats.py's own KPSS+PO implementation directly (not a reimplementation)
    so the agreement comparison is apples-to-apples against what production actually
    computes."""
    import stats as _stats_module
    return _stats_module._run_coint_tests(pd.Series(spread), eg_pval=0.0)
    # eg_pval=0.0 forces eg_ok=True unconditionally here -- we only want this
    # helper's kpss/po numbers, not its n_confirm/tier (computed fresh below using
    # the real eg_pval from pairs.parquet).


def main():
    p = argparse.ArgumentParser(description="Standalone ADF confirmatory-tier comparison against existing EG+KPSS+PO")
    args = p.parse_args()

    rows = []
    for tf_dir in _TF_DIRS:
        results_dir, is_stale = _resolve_tf_results_dir(tf_dir)
        pairs_path = os.path.join(results_dir, "pairs.parquet")
        if not os.path.exists(pairs_path):
            continue
        tf_label = _DIR_TO_LABEL[tf_dir]
        pairs_df = pd.read_parquet(pairs_path)
        for _, row in pairs_df.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            series_path = os.path.join(results_dir, f"spread_series_{sym_a}_{sym_b}.parquet")
            if not os.path.exists(series_path):
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: no spread_series file")
                continue
            series_df = pd.read_parquet(series_path)
            real_bar_mask = (series_df["gap_flag_a"] != 4) & (series_df["gap_flag_b"] != 4)
            spread = series_df.loc[real_bar_mask, "spread"].to_numpy(dtype=float)
            spread = spread[np.isfinite(spread)]
            if spread.size < 20:
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: only {spread.size} clean bars")
                continue

            eg_pval = float(row.get("coint_pvalue_adjusted", 1.0))
            eg_ok = eg_pval < 0.05
            kp = _kpss_po(spread)
            kpss_ok = not np.isnan(kp["kpss_pval"]) and kp["kpss_pval"] > 0.05
            po_ok = not np.isnan(kp["po_pval"]) and kp["po_pval"] < 0.10

            adf = run_adf_test(spread)
            adf_ok = adf["adf_confirms"]

            n_confirm_existing = int(eg_ok) + int(kpss_ok) + int(po_ok)
            tier_existing = "gold" if n_confirm_existing == 3 else ("silver" if n_confirm_existing == 2 else "bronze")
            n_confirm_with_adf = n_confirm_existing + int(adf_ok)
            tier_with_adf = "gold" if n_confirm_with_adf >= 4 else ("gold" if n_confirm_with_adf == 3 else ("silver" if n_confirm_with_adf == 2 else "bronze"))

            rows.append({
                "symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf_label,
                "eg_ok": eg_ok, "kpss_ok": kpss_ok, "po_ok": po_ok, "adf_ok": adf_ok,
                "adf_pval": adf["adf_pval"], "adf_status": adf["status"], "po_pval": kp["po_pval"],
                "n_confirm_existing": n_confirm_existing, "tier_existing": tier_existing,
                "n_confirm_with_adf": n_confirm_with_adf, "tier_with_adf": tier_with_adf,
                "adf_po_agree": adf_ok == po_ok,
            })
            print(f"{sym_a}/{sym_b}@{tf_label}: EG={eg_ok} KPSS={kpss_ok} PO={po_ok} "
                  f"ADF={adf_ok} (p={adf['adf_pval']:.4f})  "
                  f"tier {tier_existing}->{tier_with_adf}"
                  f"{'  [TIER SHIFT]' if tier_existing != tier_with_adf else ''}")

    if not rows:
        print("No pairs with spread data found.")
        return

    out_df = pd.DataFrame(rows)
    os.makedirs("output/research", exist_ok=True)
    out_path = "output/research/adf_confirmatory_tier.parquet"
    out_df.to_parquet(out_path, index=False)

    n = len(out_df)
    agree_rate = out_df["adf_po_agree"].mean()
    n_shift = (out_df["tier_existing"] != out_df["tier_with_adf"]).sum()
    print(f"\n=== Summary ({n} pairs) ===")
    print(f"ADF/PO agreement rate: {agree_rate:.1%}")
    print(f"Pairs that would shift tier if ADF added as a 4th confirmatory test: {n_shift}/{n}")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
