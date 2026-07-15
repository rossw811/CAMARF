"""
CAMARF research/midas_cross_asset_lead_lag.py — comparison/diagnostic
script, NOT part of the production pipeline (2026-07-14, task #56).

Extends midas_feature.py's existing MIDAS (Mixed Data Sampling) machinery
— reused directly (beta_weights, midas_aggregate), not reimplemented —
from a single-pair SAME-asset-class construction demo (SPY/VOO's log-
ratio, explicitly NOT a predictive test per that module's own docstring)
to a genuine CROSS-ASSET predictive question: does leg A's recent
intraday (1h) return history, MIDAS-aggregated with decay weighting,
predict leg B's NEXT daily return — beyond what a naive same-frequency
lagged correlation already captures?

This is the concrete "mixed-frequency cross-asset lead-lag" task #56
describes: combining MIDAS's fine-grained aggregation with a genuine
lead-lag (A's history -> B's future) test, on the 9 known-good pairs from
this session, rather than the single same-class demo the original module
scoped.

Method: for each pair, build A's 1h gap-aware returns and B's daily
returns. For each of B's daily timestamps, MIDAS-aggregate the trailing K
1h bars of A's returns (strictly before that day's close, no lookahead)
into one feature value. Correlate this feature against B's return on the
FOLLOWING trading day. Compare against two baselines: (1) a naive flat-
average aggregation (theta1=theta2=1) of the same window, and (2) a
same-frequency baseline — B's own lagged daily return correlated against
B's next-day return (does the MIDAS cross-asset feature add anything
beyond simple own-lag autocorrelation). Permutation-tested (circular
shift, same method as this session's other permutation checks) since a
single correlation coefficient with no correction is not evidence.

Honest scope note, inherited from midas_feature.py: this is a
correlation-based screen, not a full labeled-entry-event predictive
backtest — genuinely evaluating this as a tradeable signal would need far
more labeled outcomes than a correlation screen requires. This script
answers "is there any detectable linear predictive relationship worth
building that fuller evaluation for," not "is this profitable."

Usage:
    python research/midas_cross_asset_lead_lag.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from data import DataStore, _gap_aware_returns
from midas_feature import beta_weights, midas_aggregate

_DEFAULT_PAIRS = [
    ("LNT", "VTR"), ("LNT", "WELL"), ("AME", "MAR"), ("CMS", "DUK"),
    ("EG", "WRB"), ("HAL", "NOV"), ("MET", "TMHC"), ("PFG", "STLD"),
    ("UMBF", "FHB"),
]

K = 16          # trailing 1h bars (~2.5 trading days of intraday context)
N_PERM = 500


def _permutation_corr_pvalue(x: pd.Series, y: pd.Series, n_perm=N_PERM, seed=42):
    rng = np.random.default_rng(seed)
    joined = pd.concat([x, y], axis=1, join="inner").dropna()
    if len(joined) < 30:
        return None, len(joined)
    xv, yv = joined.iloc[:, 0].values, joined.iloc[:, 1].values
    real_corr = float(np.corrcoef(xv, yv)[0, 1])
    n = len(yv)
    null_corrs = []
    for _ in range(n_perm):
        shift = rng.integers(1, n)
        y_shifted = np.roll(yv, shift)
        null_corrs.append(float(np.corrcoef(xv, y_shifted)[0, 1]))
    null_corrs = np.array(null_corrs)
    p_value = float(np.mean(np.abs(null_corrs) >= abs(real_corr)))
    return {"corr": real_corr, "n": n, "perm_p": p_value}, n


def run_pair(symbol_a, symbol_b):
    df_a_1h = DataStore.load(symbol_a, "1hr")
    df_b_1d = DataStore.load(symbol_b, "1day")
    if df_a_1h is None or df_b_1d is None:
        return None

    ret_a_1h = pd.Series(_gap_aware_returns(df_a_1h), index=df_a_1h.index).dropna()
    ret_b_1d = pd.Series(_gap_aware_returns(df_b_1d), index=df_b_1d.index).dropna()
    # Restrict to the shared window both legs actually cover, avoiding
    # the same sample-period confound found and fixed in task #54.
    common_start = max(ret_a_1h.index.min(), ret_b_1d.index.min())
    ret_a_1h = ret_a_1h[ret_a_1h.index >= common_start]
    ret_b_1d = ret_b_1d[ret_b_1d.index >= common_start]
    if len(ret_b_1d) < 60:
        return None

    midas_decay = midas_aggregate(ret_a_1h, ret_b_1d.index, K, theta1=1.0, theta2=3.0)
    midas_flat = midas_aggregate(ret_a_1h, ret_b_1d.index, K, theta1=1.0, theta2=1.0)

    # Predict B's NEXT-day return (shift B's return series back by 1 so
    # today's feature aligns with tomorrow's outcome).
    b_next_return = ret_b_1d.shift(-1)
    b_own_lag = ret_b_1d  # same-frequency baseline: today's B return

    results = {}
    for name, feature in (("midas_decay", midas_decay), ("midas_flat", midas_flat),
                           ("b_own_lag_baseline", b_own_lag)):
        stat, n = _permutation_corr_pvalue(feature, b_next_return)
        results[name] = stat
    return results


def main():
    rows = []
    for sym_a, sym_b in _DEFAULT_PAIRS:
        result = run_pair(sym_a, sym_b)
        if result is None:
            print(f"{sym_a}/{sym_b}: insufficient data")
            continue
        row = {"symbol_a": sym_a, "symbol_b": sym_b}
        parts = []
        for name in ("midas_decay", "midas_flat", "b_own_lag_baseline"):
            stat = result[name]
            if stat is None:
                parts.append(f"{name}=N/A")
                row[f"{name}_corr"] = None
                row[f"{name}_perm_p"] = None
                continue
            row[f"{name}_corr"] = stat["corr"]
            row[f"{name}_perm_p"] = stat["perm_p"]
            sig = "*" if stat["perm_p"] < 0.05 else ""
            parts.append(f"{name}=corr={stat['corr']:.3f},p={stat['perm_p']:.3f}{sig}")
        rows.append(row)
        print(f"{sym_a}(1h)->{sym_b}(1D next-day): " + " | ".join(parts))

    df = pd.DataFrame(rows)
    if not df.empty:
        for name in ("midas_decay", "midas_flat", "b_own_lag_baseline"):
            col = f"{name}_perm_p"
            valid = df[col].dropna()
            n_sig = (valid < 0.05).sum()
            print(f"\n{name}: {n_sig}/{len(valid)} pairs with permutation-significant "
                  f"predictive correlation (p<0.05)")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "midas_cross_asset_lead_lag.parquet")
    df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
