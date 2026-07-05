"""
CAMARF reimers_trio_correction.py — comparison/diagnostic method, NOT part
of the production pipeline.

Reimers (1992), "Comparisons of Tests for Multivariate Cointegration,"
Statistical Papers 33(1) — a small-sample degrees-of-freedom correction
for Johansen's trace/max-eigenvalue test, which is known to over-reject
(find spurious cointegration) in finite samples relative to its own
asymptotic critical values. The correction rescales the trace statistic:

    LR_corrected = LR_trace * (T - n*k) / T

where T = sample size, n = number of variables (3 for a trio), k = the lag
order (VECM's k_ar_diff). The corrected statistic is compared against the
SAME asymptotic critical values Johansen's test already uses — this is a
statistic-side correction, not a different critical-value table.

Applied here to TrioBuilder's own already-persisted candidate trio list
(output/results/*/trios.parquet) — re-running coint_johansen directly on
each trio's log-prices (not re-deriving candidates from scratch) to get
the critical-value array (cvt), which trios.parquet's persisted output
doesn't retain, only the derived p-value approximation.

Read-only. Never fetches, never recomputes hedge ratios.

Usage:
    python research/reimers_trio_correction.py
"""
import glob
import os
import sys

import numpy as np
import pandas as pd
from statsmodels.tsa.vector_ar.vecm import coint_johansen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from data import DataStore

_TF_DIRS = ["1hr", "3min", "4hr"]  # the only TFs with a persisted trios.parquet
_DIR_TO_LABEL = {"1hr": "1h", "3min": "3m", "4hr": "4h"}


def _resolve_tf_results_dir(tf_dir):
    live = os.path.join("output", "results", tf_dir)
    if os.path.isdir(live):
        return live, False
    candidates = sorted(glob.glob(os.path.join("output", "results", f"{tf_dir}_stale_*")))
    return (candidates[-1], True) if candidates else (live, False)


def reimers_correction(trace_stat, cvt, n_bars, n_vars=3, k=None):
    """Returns (corrected_stat, raw_rejects_at_5pct, corrected_rejects_at_5pct)."""
    if k is None:
        k = Config.ANALYSIS.JOHANSEN_K_AR_DIFF
    factor = (n_bars - n_vars * k) / n_bars
    corrected_stat = trace_stat * factor
    crit_5pct = cvt[1]  # cvt columns are [10%, 5%, 1%]
    return corrected_stat, bool(trace_stat > crit_5pct), bool(corrected_stat > crit_5pct)


def main():
    rows = []
    for tf_dir in _TF_DIRS:
        results_dir, is_stale = _resolve_tf_results_dir(tf_dir)
        trios_path = os.path.join(results_dir, "trios.parquet")
        if not os.path.exists(trios_path):
            continue
        if is_stale:
            print(f"NOTE {tf_dir}: using archived {results_dir}")
        tf_label = _DIR_TO_LABEL[tf_dir]
        trios_df = pd.read_parquet(trios_path)

        for _, row in trios_df.iterrows():
            sym_a, sym_b, sym_c = row["symbol_a"], row["symbol_b"], row["symbol_c"]
            try:
                df_a = DataStore.load(sym_a, tf_label)
                df_b = DataStore.load(sym_b, tf_label)
                df_c = DataStore.load(sym_c, tf_label)
                if df_a is None or df_b is None or df_c is None:
                    continue
                la = np.log(df_a["close"].to_numpy(dtype=float))
                lb = np.log(df_b["close"].to_numpy(dtype=float))
                lc = np.log(df_c["close"].to_numpy(dtype=float))
                n = min(len(la), len(lb), len(lc))
                la, lb, lc = la[-n:], lb[-n:], lc[-n:]
                mask = np.isfinite(la) & np.isfinite(lb) & np.isfinite(lc)
                X = np.column_stack([la[mask], lb[mask], lc[mask]])
                if X.shape[0] < 60:
                    continue
                r = coint_johansen(X, det_order=Config.ANALYSIS.JOHANSEN_DET_ORDER,
                                    k_ar_diff=Config.ANALYSIS.JOHANSEN_K_AR_DIFF)
                trace_stat = float(r.lr1[0])
                cvt = r.cvt[0]
                corrected_stat, raw_rejects, corrected_rejects = reimers_correction(
                    trace_stat, cvt, X.shape[0]
                )
                # Max-eigenvalue test (r.lr2/r.cvm), run alongside trace at no
                # extra data cost (same coint_johansen call already computes
                # both) — trace and max-eigenvalue have different power
                # profiles against different alternatives and can disagree;
                # flagging that disagreement is itself informative, not
                # just a formality.
                max_eig_stat = float(r.lr2[0])
                cvm = r.cvm[0]
                max_eig_rejects = max_eig_stat > cvm[1]
                rows.append({
                    "symbol_a": sym_a, "symbol_b": sym_b, "symbol_c": sym_c, "tf_label": tf_label,
                    "n_bars": X.shape[0], "trace_stat": trace_stat, "corrected_stat": corrected_stat,
                    "crit_5pct": float(cvt[1]),
                    "raw_rejects_5pct": raw_rejects, "corrected_rejects_5pct": corrected_rejects,
                    "decision_flipped": raw_rejects and not corrected_rejects,
                    "max_eig_stat": max_eig_stat, "max_eig_crit_5pct": float(cvm[1]),
                    "max_eig_rejects_5pct": max_eig_rejects,
                    "trace_vs_maxeig_disagree": raw_rejects != max_eig_rejects,
                })
            except Exception as e:
                print(f"SKIP {sym_a}/{sym_b}/{sym_c}@{tf_label}: {type(e).__name__}: {e}")
                continue

    out_df = pd.DataFrame(rows)
    os.makedirs("output/research", exist_ok=True)
    out_df.to_parquet("output/research/reimers_trio_correction.parquet")
    n_flipped = int(out_df["decision_flipped"].sum()) if len(out_df) else 0
    print(f"\nWrote output/research/reimers_trio_correction.parquet: {len(out_df)} trios re-tested, "
          f"{n_flipped} flip from 'cointegrated' to 'not cointegrated' under the small-sample correction")


if __name__ == "__main__":
    main()
