"""
CAMARF research/smoothing_comparison.py — comparison/diagnostic script,
NOT part of the production pipeline (2026-07-14). Built per Ross's
direction: test smoothing/denoising the price series before cointegration
testing, purely for comparison — not a production change.

Question: does smoothing the price series (causal EMA or rolling median)
before running the Engle-Granger test change which pairs clear
significance, in a way that's a GENUINE improvement (real relationship
revealed once microstructure noise is reduced) rather than a statistical
ARTIFACT (smoothing induces its own serial correlation, which can make
ADF/EG-family tests anti-conservative — spuriously significant — even
with no real strengthening of the underlying relationship; a known
pitfall of testing cointegration on filtered data, not specific to this
project).

Method:
  1. EG p-value on raw (gap-masked) log price — baseline, matches
     production's own methodology (research/lead_lag_scan.py's
     _gap_masked_log_price / _eg_pvalue).
  2. EG p-value on the SAME log price after each smoothing variant:
     causal EMA(span=3), causal EMA(span=10), causal rolling median(5).
     All three are strictly causal (pandas .ewm()/.rolling() only use
     past+current bars) — no lookahead.
  3. For any pair where smoothing appears to CREATE new significance
     (raw p >= 0.05 but smoothed p < 0.05), run a circular-shift
     permutation check on the SMOOTHED series itself (same method as
     eg_permutation_check.py) — this is the decisive check for whether
     the apparent gain is real or a smoothing-induced artifact. A pair
     that only "passes" on the naive smoothed p-value but fails the
     permutation-corrected version is exactly the false-positive pattern
     this script exists to catch, not produce.

Sample: the 9 stable, already-vetted pairs (task #71's investigation —
sanity check that smoothing doesn't destroy known-real signal) plus a
random sample of pairs from near_miss_lag_scan_1h.parquet (moderate raw
correlation, 0.25-0.40 range — a plausible, non-random candidate pool,
not full-universe, scope stated honestly).

Usage:
    python research/smoothing_comparison.py --n-sample 300 --tf 1h
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from aligned_pair_loader import load_aligned_pair
from lead_lag_scan import _gap_masked_log_price

_DEFAULT_PAIRS = [
    ("LNT", "VTR"), ("LNT", "WELL"), ("AME", "MAR"), ("CMS", "DUK"),
    ("EG", "WRB"), ("HAL", "NOV"), ("MET", "TMHC"), ("PFG", "STLD"),
    ("UMBF", "FHB"),
]

_MIN_EG_N = 60

_SMOOTHERS = {
    "ema3": lambda s: s.ewm(span=3, adjust=False).mean(),
    "ema10": lambda s: s.ewm(span=10, adjust=False).mean(),
    "median5": lambda s: s.rolling(5).median(),
}


def _eg_pvalue(a, b, max_eg_lag=5):
    mask = np.isfinite(a) & np.isfinite(b)
    a_, b_ = a[mask], b[mask]
    if a_.size < _MIN_EG_N:
        return None, a_.size
    try:
        _, pval, _ = coint(a_, b_, trend="c", maxlag=max_eg_lag, autolag="aic")
        return float(pval), a_.size
    except Exception:
        return None, a_.size


def _permutation_check(a, b, n_perm=200, max_eg_lag=5, seed=42):
    """Circular-shift null on the (already smoothed) series — same method
    as eg_permutation_check.py. Returns the permutation p-value."""
    rng = np.random.default_rng(seed)
    mask = np.isfinite(a) & np.isfinite(b)
    a_, b_ = a[mask], b[mask]
    if a_.size < _MIN_EG_N:
        return None
    real_p, _ = _eg_pvalue(a_, b_, max_eg_lag)
    if real_p is None:
        return None
    n = a_.size
    null_ps = []
    for _ in range(n_perm):
        shift = rng.integers(1, n)
        b_shifted = np.roll(b_, shift)
        p, _ = _eg_pvalue(a_, b_shifted, max_eg_lag)
        if p is not None:
            null_ps.append(p)
    if not null_ps:
        return None
    null_ps = np.array(null_ps)
    return float(np.mean(null_ps <= real_p))


def run_pair(symbol_a, symbol_b, tf_label):
    df_a, df_b = load_aligned_pair(symbol_a, symbol_b, tf_label)
    if df_a is None or df_b is None or df_a.empty or df_b.empty:
        return None
    log_a = pd.Series(_gap_masked_log_price(df_a), index=df_a.index)
    log_b = pd.Series(_gap_masked_log_price(df_b), index=df_b.index)
    common_idx = log_a.index.intersection(log_b.index)
    log_a, log_b = log_a.reindex(common_idx), log_b.reindex(common_idx)

    row = {"symbol_a": symbol_a, "symbol_b": symbol_b}
    raw_p, raw_n = _eg_pvalue(log_a.values, log_b.values)
    row["raw_p"] = raw_p
    row["raw_n"] = raw_n

    for name, smoother in _SMOOTHERS.items():
        sm_a = smoother(log_a)
        sm_b = smoother(log_b)
        sm_p, sm_n = _eg_pvalue(sm_a.values, sm_b.values)
        row[f"{name}_p"] = sm_p
        row[f"{name}_n"] = sm_n

        # Decisive check: did smoothing CREATE new significance? Only
        # meaningful if raw wasn't already significant.
        newly_significant = (
            raw_p is not None and sm_p is not None
            and raw_p >= 0.05 and sm_p < 0.05
        )
        row[f"{name}_newly_significant"] = newly_significant
        if newly_significant:
            perm_p = _permutation_check(sm_a.values, sm_b.values)
            row[f"{name}_perm_p"] = perm_p
            row[f"{name}_survives_permutation"] = (
                perm_p is not None and perm_p < 0.05
            )
        else:
            row[f"{name}_perm_p"] = None
            row[f"{name}_survives_permutation"] = None
    return row


def main():
    p = argparse.ArgumentParser(description="Smoothing/standardization comparison for EG cointegration (2026-07-14)")
    p.add_argument("--tf", default="1h")
    p.add_argument("--n-sample", type=int, default=300)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    near_miss_path = os.path.join(root, "output", "research", f"near_miss_lag_scan_{args.tf}.parquet")
    pairs = list(_DEFAULT_PAIRS)
    if os.path.exists(near_miss_path):
        nm = pd.read_parquet(near_miss_path, columns=["symbol_a", "symbol_b"])
        sample = nm.sample(n=min(args.n_sample, len(nm)), random_state=args.seed)
        pairs.extend(list(zip(sample["symbol_a"], sample["symbol_b"])))
    else:
        print(f"WARNING: {near_miss_path} not found — using only the {len(pairs)} default pairs.")

    print(f"Testing {len(pairs)} pairs at {args.tf} "
          f"({len(_DEFAULT_PAIRS)} known-good sanity-check pairs + "
          f"{len(pairs) - len(_DEFAULT_PAIRS)} sampled near-miss candidates)...")

    rows = []
    for sym_a, sym_b in pairs:
        r = run_pair(sym_a, sym_b, args.tf)
        if r is not None:
            rows.append(r)

    if not rows:
        print("No results.")
        return
    df = pd.DataFrame(rows)

    print(f"\n{len(df)} pairs tested.")
    for col in ["raw"] + list(_SMOOTHERS.keys()):
        n_sig = (df[f"{col}_p"] < 0.05).sum()
        print(f"  {col}: {n_sig}/{len(df)} pairs with p<0.05")

    for name in _SMOOTHERS:
        newly_sig = df[df[f"{name}_newly_significant"] == True]
        if newly_sig.empty:
            print(f"\n{name}: 0 pairs where smoothing created NEW significance "
                  f"(raw p>=0.05 -> smoothed p<0.05).")
            continue
        survives = newly_sig[newly_sig[f"{name}_survives_permutation"] == True]
        print(f"\n{name}: {len(newly_sig)} pairs newly significant after smoothing, "
              f"{len(survives)} survive a circular-shift permutation check "
              f"(the rest are smoothing-induced false positives, not real findings).")
        if not survives.empty:
            print(survives[["symbol_a", "symbol_b", "raw_p", f"{name}_p", f"{name}_perm_p"]].to_string(index=False))

    out_dir = os.path.join(root, "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"smoothing_comparison_{args.tf}.parquet")
    df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
