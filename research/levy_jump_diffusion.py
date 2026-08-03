"""
CAMARF research/levy_jump_diffusion.py — comparison/diagnostic script, NOT
part of the production pipeline (2026-08-02).

Ross's framing: test whether modeling gaps as a principled jump process
(Lévy/jump-diffusion) adds anything over treating them as noise, using the
existing GapFlag system as the natural tie-in — CAMARF already flags gaps
(NONE/FILL/NO_ACTIVITY/HALT/DATA_GAP/SPARSE, see data.py's GapFlag class),
this asks whether GapFlag's flagged bars actually line up with statistically
detected discontinuities, or whether real jumps are hiding at GapFlag=NONE
bars the existing system has no way to see.

Method: Lee & Mykland (2008) jump test — a bipower-variation-based local
volatility estimator (robust to jumps, since it multiplies ADJACENT absolute
returns rather than squaring one) gives a jump statistic L_i = r_i / sigma_hat_i
at every bar; bars with |L_i| exceeding the test's asymptotic critical value
(computed exactly per the paper, not a rule-of-thumb threshold) are flagged
as statistically detected jumps. No new dependency -- pure numpy, same
"implement directly" convention as wavelet_hurst_comparison.py.

Reports, per pair leg: (1) how many bars are flagged as jumps, (2) what
fraction of jump-flagged bars coincide with a non-NONE GapFlag (validates
whether the existing gap system already captures real discontinuities),
(3) the continuous-only (jump-excluded) realized volatility vs. the standard
full-sample volatility wfa.py's garch_stop baseline currently uses -- does
excluding statistically-detected jumps materially change the vol estimate.

DISCLOSED LIMITATION: this is a diagnostic-only comparison (Ross's "research/
comparison sake first" framing) -- it does NOT wire a jump-adjusted
volatility into wfa.py/backtest.py. Whether to do that is a separate,
later decision once this shows the adjustment matters.

Usage:
    python research/levy_jump_diffusion.py
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from aligned_pair_loader import load_aligned_pair
from lead_lag_scan import _gap_masked_log_price

_CONFIRMED_PAIRS = [("KVUE", "KMB")]
_CONFIRMED_TFS = ["2min", "3min"]


def lee_mykland_critical_value(n: int, alpha: float = 0.01) -> float:
    """Exact asymptotic critical value from Lee & Mykland (2008), eq. 9.
    n is the number of returns the test statistic's extreme-value
    approximation is calibrated over (here: the full sample size)."""
    c = np.sqrt(2 / np.pi)
    log_n = np.log(n)
    Cn = np.sqrt(2 * log_n) / c - (np.log(np.pi) + np.log(log_n)) / (2 * c * np.sqrt(2 * log_n))
    Sn = 1 / (c * np.sqrt(2 * log_n))
    beta_star = -np.log(-np.log(1 - alpha))
    return Cn + Sn * beta_star


def lee_mykland_jump_test(returns: np.ndarray, window: int = None, alpha: float = 0.01) -> dict:
    """
    Bipower-variation local vol: sigma_hat_i^2 = (1/(k-2)) * sum_{j in trailing window,
    excluding i} |r_j| * |r_{j-1}| -- a product of ADJACENT absolute returns, which stays
    bounded even when one return in the window IS a jump (a squared-return estimator
    would not). L_i = r_i / sigma_hat_i. Bars with |L_i| > critical value are flagged jumps.

    window default: max(10, int(sqrt(n))) if not given -- no universally "correct" choice
    in the literature, this is a reasonable default for the sample sizes CAMARF has.
    """
    r = np.asarray(returns, dtype=float)
    n = len(r)
    if window is None:
        window = max(10, int(np.sqrt(n)))
    k = window
    abs_r = np.abs(r)
    sigma_hat = np.full(n, np.nan)
    for i in range(k, n):
        lo = i - k
        # bipower variation over [lo, i) using adjacent products, excluding r_i itself
        prod = abs_r[lo + 1:i] * abs_r[lo:i - 1]
        sigma_hat[i] = np.sqrt(np.pi / 2 * np.mean(prod)) if len(prod) > 0 else np.nan

    with np.errstate(invalid="ignore", divide="ignore"):
        L = r / sigma_hat
    crit = lee_mykland_critical_value(n, alpha)
    is_jump = np.abs(L) > crit
    is_jump[:k] = False  # insufficient history for the local vol estimate

    return {
        "L": L,
        "is_jump": is_jump,
        "critical_value": crit,
        "n_jumps": int(np.nansum(is_jump)),
        "jump_frac": float(np.nansum(is_jump) / n),
    }


def continuous_vs_total_vol(returns: np.ndarray, is_jump: np.ndarray) -> dict:
    """Realized vol including everything (what garch_stop's baseline uses
    today) vs. jump-excluded ("continuous component only") vol."""
    r = np.asarray(returns, dtype=float)
    total_vol = float(np.nanstd(r))
    continuous_vol = float(np.nanstd(r[~is_jump])) if (~is_jump).sum() > 1 else np.nan
    return {
        "total_vol": total_vol,
        "continuous_vol": continuous_vol,
        "pct_change": float((continuous_vol - total_vol) / total_vol * 100) if total_vol else np.nan,
    }


def gap_flag_overlap(gap_flags: np.ndarray, is_jump: np.ndarray) -> dict:
    """What fraction of statistically-detected jumps coincide with a
    non-NONE GapFlag, and vice versa -- does GapFlag already "see" these,
    or are real jumps hiding at GapFlag=NONE bars."""
    non_none = gap_flags != 0  # GapFlag.NONE == 0
    n_jumps = int(is_jump.sum())
    n_jumps_flagged = int((is_jump & non_none).sum())
    n_flagged = int(non_none.sum())
    n_flagged_are_jumps = int((non_none & is_jump).sum())
    return {
        "n_jumps_detected": n_jumps,
        "jumps_with_nonnone_gapflag": n_jumps_flagged,
        "jumps_with_nonnone_gapflag_pct": float(n_jumps_flagged / n_jumps * 100) if n_jumps else np.nan,
        "n_nonnone_gapflag_bars": n_flagged,
        "gapflag_bars_that_are_jumps_pct": float(n_flagged_are_jumps / n_flagged * 100) if n_flagged else np.nan,
    }


def main():
    ap = argparse.ArgumentParser(description="Lévy jump-diffusion diagnostic (2026-08-02)")
    ap.add_argument("--alpha", type=float, default=0.01)
    args = ap.parse_args()

    rows = []
    for sym_a, sym_b in _CONFIRMED_PAIRS:
        for tf in _CONFIRMED_TFS:
            df_a, df_b = load_aligned_pair(sym_a, sym_b, tf)
            if df_a is None or df_b is None or df_a.empty or df_b.empty:
                print(f"skip {sym_a}/{sym_b}@{tf}: no aligned data")
                continue
            for sym, df in ((sym_a, df_a), (sym_b, df_b)):
                log_p = _gap_masked_log_price(df)
                r = np.diff(log_p)
                mask = np.isfinite(r)
                r_f = r[mask]
                if len(r_f) < 200:
                    print(f"skip {sym}@{tf}: only {len(r_f)} clean returns")
                    continue
                gap_flags = df["gap_flag"].values[1:][mask] if "gap_flag" in df.columns else np.zeros(len(r_f))

                jump_result = lee_mykland_jump_test(r_f, alpha=args.alpha)
                vol_result = continuous_vs_total_vol(r_f, jump_result["is_jump"])
                overlap_result = gap_flag_overlap(gap_flags, jump_result["is_jump"])

                print(f"\n{sym}@{tf}: n={len(r_f)}, critical_value={jump_result['critical_value']:.2f}")
                print(f"  jumps detected: {jump_result['n_jumps']} ({jump_result['jump_frac']*100:.2f}% of bars)")
                print(f"  total_vol={vol_result['total_vol']:.6f}  continuous_vol={vol_result['continuous_vol']:.6f}  "
                      f"({vol_result['pct_change']:+.2f}%)")
                print(f"  of detected jumps, {overlap_result['jumps_with_nonnone_gapflag_pct']:.1f}% already had a non-NONE GapFlag")
                print(f"  of non-NONE GapFlag bars, {overlap_result['gapflag_bars_that_are_jumps_pct']:.1f}% are statistically detected jumps")

                rows.append({
                    "symbol": sym, "tf": tf, "n_bars": len(r_f),
                    **{k: v for k, v in jump_result.items() if k not in ("L", "is_jump")},
                    **vol_result, **overlap_result,
                })

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    if rows:
        pd.DataFrame(rows).to_parquet(os.path.join(out_dir, "levy_jump_diffusion.parquet"))
        print(f"\nResults written to output/research/levy_jump_diffusion.parquet")
    else:
        print("\nNo usable output — nothing written.")


if __name__ == "__main__":
    main()
