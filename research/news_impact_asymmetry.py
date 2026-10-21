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
dz_t (bar-to-bar change in z_rolling) into two groups by the DIRECTION of the
prior move relative to zero — "after narrowing" (|z_{t-1}| < |z_{t-2}|) vs. "after widening"
(otherwise; R8.1, corrected 2026-10-20: this used to be the sign of dz_{t-1}) — and test whether Var(dz_t | after narrowing) differs from
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
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # for aligned_pair_loader

from aligned_pair_loader import (
    TF_DIRS as _TF_DIRS,
    DIR_TO_LABEL as _DIR_TO_LABEL,
    resolve_tf_results_dir as _resolve_tf_results_dir,
)


def news_impact_asymmetry_test(z, n_perm=1000, rng=None):
    """
    z: 1-D LEVEL series (e.g. z_rolling), NaN at every masked bar (DATA_GAP, non-finite). R8.1 (fixed 2026-10-20,
    debug/_verify_news_impact_narrowing_r81.py): "after narrowing" is a prior move TOWARD zero, |z_{t-1}| < |z_{t-2}|
    (was dz_{t-1} < 0, which with z on both sides of 0 mixes narrowing and widening half and half and pulls the ratio
    to 1 by construction). Only rows whose z_t, z_{t-1}, z_{t-2} are all finite are used, so no lag spans a mask (the
    caller used to compact the deltas first).

    Returns var_after_narrow, var_after_widen, variance_ratio (narrow/widen),
    and a two-sided permutation p-value for the ratio departing from 1.0.
    """
    if rng is None:
        rng = np.random.default_rng(0)
    z = np.asarray(z, dtype=float)
    if z.size < 62:
        return {"ok": False, "error": "insufficient_obs"}
    z0, z1, z2 = z[2:], z[1:-1], z[:-2]              # z_t, z_{t-1}, z_{t-2}
    valid = np.isfinite(z0) & np.isfinite(z1) & np.isfinite(z2)
    dz_t = (z0 - z1)[valid]
    after_narrow = (np.abs(z1) < np.abs(z2))[valid]
    n = dz_t.size
    if n < 60:
        return {"ok": False, "error": "insufficient_obs"}
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
            # Tier 2.11 fix (Grand Sweep 2026-07-20): the prior version
            # borrowed threshold_cointegration.py's gap-masking
            # justification, but that script's rationale is specifically
            # about a LEVEL-based test (bridging a routine closure is fine
            # there) -- it does not transfer to this dz_t (diff-based,
            # lag-sensitive) asymmetry test, per the refined risk
            # classification (docs/archive/audits/GRAND_SWEEP_BUG_AUDIT_2026-07-20.md).
            # Dropping gap rows BEFORE np.diff() silently concatenates
            # positions spanning any gap as if one bar apart. Fixed by
            # diffing the full series first, then masking any diff whose
            # start or end bar is DATA_GAP-flagged, mirroring
            # data.py::_gap_aware_returns' convention.
            # R8.1 (2026-10-20): pass the LEVEL series with NaN at DATA_GAP bars; the test itself uses only rows whose
            # z_t, z_{t-1}, z_{t-2} are all present, so no move or lag spans a gap (no compaction here).
            z_raw = df["z_rolling"].to_numpy(dtype=float)
            gap_bad = ((df["gap_flag_a"].to_numpy() == 4) | (df["gap_flag_b"].to_numpy() == 4))
            r = news_impact_asymmetry_test(np.where(gap_bad, np.nan, z_raw), n_perm=1000, rng=rng)
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
