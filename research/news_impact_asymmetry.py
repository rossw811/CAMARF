"""
CAMARF news_impact_asymmetry.py — comparison/diagnostic method, NOT part
of the production pipeline.

Engle & Ng (1993), "Measuring and Testing the Impact of News on
Volatility," Journal of Finance 48(5) — tests whether spread volatility
responds asymmetrically to widening vs. narrowing moves (the "leverage
effect" applied to a mean-reverting spread instead of an equity return).
Directly testable against backtest.py's `garch_stop` variant, which uses a
SYMMETRIC rolling-std trigger — if this test finds real asymmetry, that
trigger is mis-specified.

Method actually implemented (a permutation-based two-group variance
comparison, NOT the textbook multi-term sign-bias regression): split
dz_t (bar-to-bar change in z_rolling) into two groups by the SIGN of the
prior move, dz_{t-1} — "after narrowing" (dz_{t-1}<0) vs. "after widening"
(dz_{t-1}>=0) — and test whether Var(dz_t | after narrowing) differs from
Var(dz_t | after widening) via a label-permutation test on the variance
ratio. This directly answers CAMARF's actual question ("does volatility
spike more after widening than after narrowing") without regression
machinery.

A regression-based version (Engle-Ng's actual multi-term specification,
dz_t^2 ~ ARCH-control + sign/size-bias interaction terms) was built and
verified FIRST and rejected after three fix attempts (an explicit ARCH
control term, then a log-variance transform) all left a badly inflated
false-rejection rate (75-90% instead of the nominal 5%) on genuinely
symmetric synthetic GARCH(1,1) data — traced to severe multicollinearity
among the sign/size-interaction terms plus non-negativity issues in a
squared/log-squared dependent variable under an additive wild bootstrap.
Rather than keep patching an increasingly complex regression, this
permutation-based two-group comparison is used instead: simpler, avoids
all of the above problems by construction (no regression, no dependent-
variable transform, exact under permutation), and answers the same
substantive question CAMARF actually needs answered.

Applied to each confirmed pair's z_rolling (the entry-signal series
itself, not the raw dollar spread) so units are comparable across pairs.

Read-only. Excludes DATA_GAP-flagged padding on both legs (see
threshold_cointegration.py's docstring for the full explanation of why).

Usage:
    python research/news_impact_asymmetry.py
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TF_DIRS = [
    "1min", "2min", "3min", "5min", "15min", "30min", "1hr", "4hr",
    "7day", "1mo", "3mo", "6mo",
]
_DIR_TO_LABEL = {
    "1min": "1m", "2min": "2m", "3min": "3m", "5min": "5m", "15min": "15m",
    "30min": "30m", "1hr": "1h", "4hr": "4h", "7day": "7D", "1mo": "1M",
    "3mo": "3M", "6mo": "6M",
}


def _resolve_tf_results_dir(tf_dir):
    live = os.path.join("output", "results", tf_dir)
    if os.path.isdir(live):
        return live, False
    candidates = sorted(glob.glob(os.path.join("output", "results", f"{tf_dir}_stale_*")))
    return (candidates[-1], True) if candidates else (live, False)


def news_impact_asymmetry_test(z, n_perm=1000, rng=None):
    """
    z: 1-D array of the entry-signal series (e.g. z_rolling), real bars only.

    Returns var_after_narrow, var_after_widen, variance_ratio (narrow/widen),
    and a two-sided permutation p-value for the ratio departing from 1.0.
    """
    if rng is None:
        rng = np.random.default_rng(0)
    z = np.asarray(z, dtype=float)
    dz = np.diff(z)
    n = dz.size
    if n < 60:
        return {"ok": False, "error": "insufficient_obs"}

    dz_t = dz[1:]
    dz_lag = dz[:-1]
    after_narrow = dz_lag < 0
    n_narrow, n_widen = int(after_narrow.sum()), int((~after_narrow).sum())
    if min(n_narrow, n_widen) < 20:
        return {"ok": False, "error": "insufficient_obs_per_group"}

    var_narrow = float(np.var(dz_t[after_narrow], ddof=1))
    var_widen = float(np.var(dz_t[~after_narrow], ddof=1))
    if var_widen <= 0:
        return {"ok": False, "error": "zero_variance_widen_group"}
    observed_ratio = var_narrow / var_widen
    observed_stat = abs(np.log(observed_ratio))  # symmetric around 0 under H0: ratio=1

    perm_stats = np.empty(n_perm)
    for p in range(n_perm):
        shuffled = rng.permutation(after_narrow)
        v1 = np.var(dz_t[shuffled], ddof=1)
        v2 = np.var(dz_t[~shuffled], ddof=1)
        if v2 <= 0 or v1 <= 0:
            perm_stats[p] = 0.0
            continue
        perm_stats[p] = abs(np.log(v1 / v2))
    pvalue = float(np.mean(perm_stats >= observed_stat))

    return {
        "ok": True, "n_narrow": n_narrow, "n_widen": n_widen,
        "var_after_narrow": var_narrow, "var_after_widen": var_widen,
        "variance_ratio_narrow_over_widen": observed_ratio,
        "narrow_higher_vol": bool(observed_ratio > 1.0),
        "pvalue": pvalue,
    }


def main():
    rng = np.random.default_rng(0)
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
            series_path = os.path.join(results_dir, f"spread_series_{sym_a}_{sym_b}.parquet")
            if not os.path.exists(series_path):
                continue
            df = pd.read_parquet(series_path)
            real_mask = (df["gap_flag_a"] != 4) & (df["gap_flag_b"] != 4)
            z = df.loc[real_mask, "z_rolling"].to_numpy(dtype=float)
            z = z[np.isfinite(z)]
            r = news_impact_asymmetry_test(z, n_perm=1000, rng=rng)
            r.update({"symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf_label})
            rows.append(r)
            if r["ok"]:
                print(f"{sym_a}/{sym_b}@{tf_label}: var_ratio(narrow/widen)="
                      f"{r['variance_ratio_narrow_over_widen']:.3f} "
                      f"narrow_higher_vol={r['narrow_higher_vol']} p={r['pvalue']:.3f}")

    out_df = pd.DataFrame(rows)
    os.makedirs("output/research", exist_ok=True)
    out_df.to_parquet("output/research/news_impact_asymmetry.parquet")
    ok = out_df[out_df.get("ok", False) == True] if "ok" in out_df.columns else pd.DataFrame()
    n_sig = int((ok["pvalue"] < 0.05).sum()) if len(ok) else 0
    n_narrow_higher = int((ok["narrow_higher_vol"] & (ok["pvalue"] < 0.05)).sum()) if len(ok) else 0
    print(f"\nWrote output/research/news_impact_asymmetry.parquet: {len(ok)} valid pairs, "
          f"{n_sig} with significant asymmetric volatility (p<0.05), "
          f"{n_narrow_higher} of those showing HIGHER vol after narrowing (vs. after widening)")


if __name__ == "__main__":
    main()
