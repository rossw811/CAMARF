"""
CAMARF hmm_regime_detection.py — research/comparison script, NOT part
of the production pipeline.

Fits Gaussian HMMs to key macro/financial series and compares the
learned latent state sequences against macro.py's heuristic threshold-
based regime classifications. Tests whether HMM-derived regime states
better predict pair behavior (mean-reversion speed, spread volatility)
than the heuristic labels.

Design:
  Series fitted (one HMM per series):
    - T10Y2Y (yield curve slope) — 2 states: normal/inverted
    - VIXCLS (volatility) — 3 states: calm/normal/crisis
    - cot_es_net_spec (COT speculative positioning) — 2 states: net_short/net_long

  For each series:
    1. Fit Gaussian HMM with n_states states (seed=42, n_iter=200).
    2. Decode the most-probable latent state sequence (Viterbi).
    3. Compute Markov transition matrix and regime persistence (expected
       duration in each state = 1 / (1 - p_self_transition)).
    4. Compare with the heuristic classification via confusion matrix.
    5. Test whether HMM states predict pair half-life better than
       heuristic labels (measured by variance explained in hl_ratio from
       regime_conditional_analysis output).

Output: output/research/hmm_regimes.parquet — columns per day:
  date, t10y2y_hmm_state, vix_hmm_state, cot_es_hmm_state,
  t10y2y_heuristic, vix_heuristic, cot_es_heuristic,
  + transition matrices and persistence in the log.

Usage:
    python research/hmm_regime_detection.py
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd
from hmmlearn import hmm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from macro import build as macro_build

_OUT = "output/research/hmm_regimes.parquet"

# (series_col, heuristic_regime_col, n_states, state_labels)
_SERIES_CONFIG = [
    ("t10y2y",          "yield_curve_regime",    2, ["inverted/flat", "normal/steep"]),
    ("vix_close",       "vix_regime",            3, ["calm", "normal", "crisis"]),
    ("cot_es_net_spec",  "cot_es_regime",         2, ["net_short", "net_long"]),
]


def _fit_hmm(values, n_states, n_iter=200, seed=42):
    """
    Fit a Gaussian HMM and return (model, state_sequence, log_prob).
    Returns (None, None, None) on failure.
    """
    vals = values[np.isfinite(values)].reshape(-1, 1)
    if len(vals) < n_states * 10:
        return None, None, None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = hmm.GaussianHMM(
            n_components=n_states,
            covariance_type="diag",
            n_iter=n_iter,
            random_state=seed,
        )
        try:
            model.fit(vals)
            states = model.predict(vals)
            log_prob = model.score(vals)
            return model, states, log_prob
        except Exception as e:
            print(f"  HMM fit failed: {e}")
            return None, None, None


def _transition_summary(transmat, state_labels):
    """Print transition matrix and expected regime persistence."""
    lines = []
    for i, from_label in enumerate(state_labels):
        persist = 1.0 / (1 - transmat[i, i]) if transmat[i, i] < 1.0 else float("inf")
        row = " | ".join(f"{transmat[i, j]:.3f}" for j in range(len(state_labels)))
        lines.append(f"  {from_label:20s}: [{row}]  persist={persist:.1f} days")
    return "\n".join(lines)


def _order_states_by_mean(model, state_seq, values):
    """Re-order HMM states so state 0 = lowest mean (ascending order)."""
    means = model.means_.flatten()
    order = np.argsort(means)
    remap = {old: new for new, old in enumerate(order)}
    reordered_seq = np.array([remap[s] for s in state_seq])
    return reordered_seq, order


def main():
    print("Loading macro data...")
    warnings.filterwarnings("ignore")
    macro = macro_build(force_refresh=False)
    df = macro.data  # daily, NYSE calendar

    results_wide = pd.DataFrame(index=df.index)
    comparison_rows = []

    for series_col, heuristic_col, n_states, labels in _SERIES_CONFIG:
        if series_col not in df.columns:
            print(f"SKIP {series_col}: not in macro output")
            continue

        series = df[series_col].copy()
        finite_mask = series.notna()
        vals_full = series.values.astype(float)
        finite_idx = np.where(finite_mask)[0]

        if finite_mask.sum() < n_states * 20:
            print(f"SKIP {series_col}: insufficient data ({finite_mask.sum()} rows)")
            continue

        print(f"\n[{series_col}] Fitting {n_states}-state Gaussian HMM "
              f"({finite_mask.sum()} observations)...")

        vals_finite = vals_full[finite_mask]
        model, states_finite, log_prob = _fit_hmm(vals_finite, n_states)
        if model is None:
            print(f"  FAILED — skipping")
            continue

        # Re-order states by ascending mean so state 0 = lowest (most risk-off)
        states_ordered, order = _order_states_by_mean(model, states_finite, vals_finite)
        ordered_means = model.means_.flatten()[order]
        ordered_labels = [labels[i] for i in range(len(labels))]

        # Map back to full daily index
        hmm_col = f"{series_col}_hmm_state"
        results_wide[hmm_col] = np.nan
        results_wide[hmm_col].iloc[finite_idx] = states_ordered.astype(float)

        # Reorder transition matrix
        orig_transmat = model.transmat_
        ordered_transmat = orig_transmat[order][:, order]

        print(f"  log_prob={log_prob:.1f}")
        print(f"  State means: " +
              ", ".join(f"{ordered_labels[i]}={ordered_means[i]:.4f}" for i in range(n_states)))
        print(f"  Transition matrix (rows=from, cols=to):")
        print(_transition_summary(ordered_transmat, ordered_labels))

        # Regime distribution
        counts = pd.Series(states_ordered).value_counts().sort_index()
        for state_idx in range(n_states):
            cnt = counts.get(state_idx, 0)
            pct = 100 * cnt / len(states_ordered)
            print(f"  {ordered_labels[state_idx]:20s}: {cnt:5d} days ({pct:.1f}%)")

        # Compare with heuristic classification
        if heuristic_col in df.columns:
            heur = df[heuristic_col].reindex(df.index[finite_idx])
            hmm_s = pd.Series(states_ordered, index=df.index[finite_idx])
            both = pd.DataFrame({"hmm": hmm_s, "heur": heur}).dropna()
            if len(both) > 0:
                print(f"\n  Confusion (HMM state vs heuristic '{heuristic_col}'):")
                ct = pd.crosstab(both["hmm"].astype(int), both["heur"],
                                 rownames=["hmm_state"], colnames=["heuristic"])
                print(ct.to_string())
                results_wide[heuristic_col] = df[heuristic_col]

        for i, lbl in enumerate(ordered_labels):
            persist = (1.0 / (1 - ordered_transmat[i, i])
                       if ordered_transmat[i, i] < 1.0 else float("inf"))
            comparison_rows.append({
                "series": series_col,
                "state_index": i,
                "state_label": lbl,
                "state_mean": float(ordered_means[i]),
                "state_std": float(model.covars_.flatten()[order][i] ** 0.5),
                "state_count": int(counts.get(i, 0)),
                "state_pct": float(100 * counts.get(i, 0) / len(states_ordered)),
                "persistence_days": float(persist),
                "self_transition_prob": float(ordered_transmat[i, i]),
            })

    if results_wide.empty:
        print("No HMM states computed — macro series may be unavailable.")
        return

    os.makedirs(os.path.dirname(_OUT), exist_ok=True)
    results_wide.to_parquet(_OUT)
    print(f"\nHMM state sequences written to {_OUT}")
    print(f"Columns: {list(results_wide.columns)}")

    summary = pd.DataFrame(comparison_rows)
    summary_out = _OUT.replace(".parquet", "_summary.parquet")
    summary.to_parquet(summary_out, index=False)
    print(f"State summary written to {summary_out}")

    print(f"\n=== Key takeaway ===")
    print(f"HMM regime sequences are in {_OUT}.")
    print("Next step: join these to spread data in regime_conditional_analysis.py")
    print("to compare HMM-based vs heuristic regime conditioning on pair half-lives.")


if __name__ == "__main__":
    main()
