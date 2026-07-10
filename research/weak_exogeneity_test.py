"""
research/weak_exogeneity_test.py — comparison/diagnostic method, NOT part of
the production pipeline.

Weak exogeneity in a bivariate cointegrating relationship (A, B): does leg A
itself adjust to restore equilibrium when the spread deviates (alpha_A != 0
in the VECM error-correction term), or does all the adjustment happen on
leg B's side (alpha_A == 0, A is weakly exogenous w.r.t. the cointegrating
relation — B "leads," A merely gets dragged along)? CAMARF's existing hedge-
ratio/spread machinery treats both legs symmetrically (spread = log_a -
beta*log_b); this answers a genuinely different question the OLS/Kalman/TLS
hedge-ratio estimation never asks: WHICH leg actually does the reverting.

Method: fit an unrestricted VECM (statsmodels, same det_order/k_ar_diff as
analysis.py's own Johansen calls, Config.ANALYSIS.JOHANSEN_*) on each
confirmed pair's log-prices, and read off `pvalues_alpha` directly — no need
for a hand-rolled restricted-VECM refit; statsmodels already reports the
per-coefficient significance test for each leg's own alpha (error-correction
loading). p > 0.05 for a leg's alpha = fail to reject weak exogeneity for
that leg. Four possible outcomes per pair: A leads (B adjusts, A weakly
exogenous), B leads (A adjusts, B weakly exogenous), both adjust (bidirectional
error correction, genuinely mutual), or neither adjusts at the 5% level
(unusual — would cast doubt on the pair's own cointegration, worth flagging).

Read-only. Never fetches, never recomputes hedge ratios.

Usage:
    python research/weak_exogeneity_test.py
"""
import os
import sys

import numpy as np
import pandas as pd
from statsmodels.tsa.vector_ar.vecm import VECM

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # for aligned_pair_loader

from aligned_pair_loader import (
    TF_DIRS as _TF_DIRS,
    DIR_TO_LABEL as _DIR_TO_LABEL,
    resolve_tf_results_dir as _resolve_tf_results_dir,
    load_aligned_pair,
)
from config import Config


def test_weak_exogeneity(log_a: np.ndarray, log_b: np.ndarray) -> dict:
    X = np.column_stack([log_a, log_b])
    mask = np.all(np.isfinite(X), axis=1)
    X = X[mask]
    if X.shape[0] < 60:
        return {}
    model = VECM(
        X, k_ar_diff=Config.ANALYSIS.JOHANSEN_K_AR_DIFF,
        deterministic="n" if Config.ANALYSIS.JOHANSEN_DET_ORDER == -1 else "co",
        coint_rank=1,
    )
    res = model.fit()
    p_alpha_a = float(res.pvalues_alpha[0, 0])
    p_alpha_b = float(res.pvalues_alpha[1, 0])
    a_exogenous = p_alpha_a > 0.05
    b_exogenous = p_alpha_b > 0.05

    if a_exogenous and not b_exogenous:
        # A doesn't respond to disequilibrium (weakly exogenous) -> A leads,
        # B is the one adjusting/following to restore the relationship.
        verdict = "A_leads"
    elif b_exogenous and not a_exogenous:
        verdict = "B_leads"
    elif not a_exogenous and not b_exogenous:
        verdict = "both_adjust"
    else:
        verdict = "neither_adjusts"

    return {
        "p_alpha_a": p_alpha_a, "p_alpha_b": p_alpha_b,
        "alpha_a": float(res.alpha[0, 0]), "alpha_b": float(res.alpha[1, 0]),
        "a_weakly_exogenous": a_exogenous, "b_weakly_exogenous": b_exogenous,
        "verdict": verdict,
    }


def main():
    rows = []
    for tf_dir in _TF_DIRS:
        results_dir, is_stale = _resolve_tf_results_dir(tf_dir)
        pairs_path = os.path.join(results_dir, "pairs.parquet")
        if not os.path.exists(pairs_path):
            continue
        if is_stale:
            print(f"NOTE {tf_dir}: using archived {results_dir}")
        tf_label = _DIR_TO_LABEL[tf_dir]
        pairs_df = pd.read_parquet(pairs_path)
        for _, row in pairs_df.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            df_a, df_b = load_aligned_pair(sym_a, sym_b, tf_label)
            if df_a is None or df_b is None:
                continue
            gap_a = df_a.get("gap_flag")
            gap_b = df_b.get("gap_flag")
            real_bars = (
                (gap_a.to_numpy() != 4) & (gap_b.to_numpy() != 4)
                if gap_a is not None and gap_b is not None
                else np.ones(len(df_a), dtype=bool)
            )
            log_a = np.log(df_a["close"].to_numpy(dtype=float))
            log_b = np.log(df_b["close"].to_numpy(dtype=float))
            finite = np.isfinite(log_a) & np.isfinite(log_b) & real_bars
            try:
                result = test_weak_exogeneity(log_a[finite], log_b[finite])
            except Exception as e:
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: {type(e).__name__}: {e}")
                continue
            if not result:
                continue
            result.update({"symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf_label})
            rows.append(result)
            print(f"{sym_a}/{sym_b}@{tf_label}: alpha_A={result['alpha_a']:.4f} (p={result['p_alpha_a']:.3f})  "
                  f"alpha_B={result['alpha_b']:.4f} (p={result['p_alpha_b']:.3f})  -> {result['verdict']}")

    if not rows:
        print("No confirmed pairs testable.")
        return

    out_df = pd.DataFrame(rows)
    os.makedirs("output/research", exist_ok=True)
    out_df.to_parquet("output/research/weak_exogeneity_test.parquet")
    print(f"\n=== Summary across {len(out_df)} pairs ===")
    print(out_df["verdict"].value_counts().to_string())
    print("\nWrote output/research/weak_exogeneity_test.parquet")


if __name__ == "__main__":
    main()
