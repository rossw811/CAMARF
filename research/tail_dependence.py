"""
CAMARF tail_dependence.py — gating diagnostic, NOT part of the production
pipeline.

Idea #8 from Development.md's Session 10 academic backlog: before
building any copula-based entry rule (which would address the Gaussian-
symmetry assumption the existing z-score/OU approach makes), first check
whether confirmed pairs actually show tail-dependence asymmetry at all —
gate on evidence, don't assume universal value.

For each confirmed pair, computes a standard nonparametric tail-
dependence estimator (Frahm, Junker & Schmidt 2005-style empirical chi
estimator) on the two legs' gap-aware log returns:
    lambda_L(q) = P(rank_a <= q | rank_b <= q)   (joint-crash tendency)
    lambda_U(q) = P(rank_a >= 1-q | rank_b >= 1-q)  (joint-rally tendency)
A symmetric (e.g. Gaussian) dependence structure implies lambda_L ~ lambda_U.
A material, well-supported gap between them is the actual gate condition
for considering an asymmetric copula.

Read-only. Loads cached price data via aligned_pair_loader.load_aligned_pair
(fixed 2026-06-24 — raw DataStore.load() output has no gap_flag column at
all, so _gap_aware_returns was NOT actually gap-aware as the name and the
original docstring claimed; see Development.md Session 11) rather than
reimplementing gap-handling logic.

Usage:
    python research/tail_dependence.py
    python research/tail_dependence.py --q 0.05 0.10
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aligned_pair_loader import load_aligned_pair
from data import _gap_aware_returns

_TF_DIRS = [
    "1min", "2min", "3min", "5min", "15min", "30min", "1hr", "4hr",
    "7day", "1mo", "3mo", "6mo",
]
_DIR_TO_LABEL = {
    "1min": "1m", "2min": "2m", "3min": "3m", "5min": "5m", "15min": "15m",
    "30min": "30m", "1hr": "1h", "4hr": "4h", "7day": "7D", "1mo": "1M",
    "3mo": "3M", "6mo": "6M",
}

# Minimum conditioning-set size before trusting an empirical tail estimate —
# below this, lambda_L/lambda_U are too noisy to draw any conclusion from.
_MIN_TAIL_N = 10


def _empirical_tail_dependence(ret_a, ret_b, q):
    """Nonparametric chi estimator. Returns (lambda_L, lambda_U, n_L, n_U)
    where n_L/n_U are the conditioning-set sizes (for honesty about
    estimate reliability)."""
    mask = np.isfinite(ret_a) & np.isfinite(ret_b)
    a, b = ret_a[mask], ret_b[mask]
    n = len(a)
    if n < 30:
        return None
    # Empirical CDF via rank (no parametric assumption)
    rank_a = pd.Series(a).rank(pct=True).values
    rank_b = pd.Series(b).rank(pct=True).values

    lower_a = rank_a <= q
    lower_b = rank_b <= q
    n_L = int(lower_b.sum())
    lambda_L = float((lower_a & lower_b).sum() / n_L) if n_L > 0 else None

    upper_a = rank_a >= (1 - q)
    upper_b = rank_b >= (1 - q)
    n_U = int(upper_b.sum())
    lambda_U = float((upper_a & upper_b).sum() / n_U) if n_U > 0 else None

    return lambda_L, lambda_U, n_L, n_U


def main():
    p = argparse.ArgumentParser(description="Tail-dependence asymmetry gate (idea #8)")
    p.add_argument("--q", type=float, nargs="+", default=[0.05, 0.10])
    p.add_argument("--asymmetry-threshold", type=float, default=0.15,
                    help="Minimum |lambda_U - lambda_L| to flag as material")
    args = p.parse_args()

    rows = []
    for tf_dir in _TF_DIRS:
        path = f"output/results/{tf_dir}/pairs.parquet"
        if not os.path.exists(path):
            continue
        tf_label = _DIR_TO_LABEL[tf_dir]
        df = pd.read_parquet(path)
        for _, row in df.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            df_a, df_b = load_aligned_pair(sym_a, sym_b, tf_label)
            if df_a is None or df_b is None:
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: cache missing for one leg")
                continue
            ret_a = pd.Series(_gap_aware_returns(df_a), index=df_a.index)
            ret_b = pd.Series(_gap_aware_returns(df_b), index=df_b.index)
            joined = pd.concat([ret_a, ret_b], axis=1, join="inner").dropna()
            if len(joined) < 30:
                print(f"SKIP {sym_a}/{sym_b}@{tf_label}: only {len(joined)} "
                      f"overlapping clean return bars (<30)")
                continue
            a_vals, b_vals = joined.iloc[:, 0].values, joined.iloc[:, 1].values

            for q in args.q:
                result = _empirical_tail_dependence(a_vals, b_vals, q)
                if result is None:
                    continue
                lam_l, lam_u, n_l, n_u = result
                reliable = n_l >= _MIN_TAIL_N and n_u >= _MIN_TAIL_N
                gap = abs(lam_u - lam_l) if (lam_l is not None and lam_u is not None) else None
                flagged = reliable and gap is not None and gap >= args.asymmetry_threshold
                rows.append({
                    "tf": tf_label, "symbol_a": sym_a, "symbol_b": sym_b, "q": q,
                    "lambda_L": lam_l, "lambda_U": lam_u, "n_L": n_l, "n_U": n_u,
                    "n_obs": len(joined), "reliable": reliable, "gap": gap,
                    "flagged_asymmetric": flagged,
                })

    if not rows:
        print("No confirmed pairs with sufficient overlapping data found.")
        return

    result_df = pd.DataFrame(rows)
    pd.set_option("display.width", 140)
    print(result_df.to_string(index=False))

    flagged = result_df[result_df["flagged_asymmetric"]]
    print(f"\n{len(flagged)}/{len(result_df)} (pair, q) combinations flagged as "
          f"materially asymmetric (|gap| >= {args.asymmetry_threshold}, "
          f"both tails have >= {_MIN_TAIL_N} conditioning observations).")
    if flagged.empty:
        print("GATE RESULT: no evidence of tail asymmetry in current confirmed "
              "pairs at current history depth — do not build a copula-based "
              "entry rule on this evidence. Re-run as more history accumulates "
              "(small-N tails are inherently noisy; revisit once n_obs grows).")
    else:
        print("GATE RESULT: at least one pair shows material, "
              "reliability-screened tail asymmetry — worth a closer look "
              "before deciding whether to build an asymmetric copula entry rule.")
        print(flagged[["tf", "symbol_a", "symbol_b", "q", "lambda_L", "lambda_U",
                        "n_L", "n_U", "n_obs"]].to_string(index=False))

    out_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research"
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "tail_dependence_summary.parquet")
    result_df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
