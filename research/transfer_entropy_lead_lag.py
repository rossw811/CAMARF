"""
Transfer entropy lead-lag detection -- PAPER.md §10 future-work candidate,
approved by Ross 2026-09-08 alongside sequential_bootstrap_ml_comparison.py
and the IBES price-target fetch. A nonlinear, information-theoretic
extension of this project's existing correlation-based lead-lag scan
(big_move_lead_lag.py, cross_tf_lead_lag_scan.py) -- gives a second,
independent signal for which leg of a confirmed pair leads, and a
robustness check on hedge-ratio direction.

Method (Schreiber 2000 bivariate transfer entropy, discretized via
quantile binning, embedding dimension 1 for both series -- the standard
simplest form, not the full k/l-history generalization; flagged as the
real scope limit of this build, not silently the "complete" version):

    TE_{Y->X}(lag) = sum p(x_t, x_{t-1}, y_{t-lag}) *
                     log2[ p(x_t | x_{t-1}, y_{t-lag}) / p(x_t | x_{t-1}) ]

measures how much knowing Y's value `lag` bars ago reduces uncertainty
about X's current value, BEYOND what X's own immediate past already
predicts -- directional (TE_{Y->X} != TE_{X->Y} in general), unlike
Pearson correlation.

Significance: permutation test via CIRCULAR shift of the Y series (not
i.i.d. shuffling) -- preserves Y's own autocorrelation structure while
destroying its specific temporal alignment with X, the standard, more
rigorous null for time-series transfer entropy (naive i.i.d. shuffling
would also destroy Y's autocorrelation, understating how much apparent
"coupling" could arise from shared smooth trends/autocorrelation alone,
not real information transfer). Same reused primitives as this project's
other lead-lag scripts (`aligned_pair_loader.load_aligned_pair`,
`data._gap_aware_returns` -- GapFlag-aware, per CLAUDE.md's non-negotiable
gap-handling rule).

Real cost disclosed up front (this is why sequential bootstrap, not this
script, was built first): binning introduces a real bias/variance
tradeoff (too few bins loses resolution, too many bins makes the joint
histogram sparse and TE estimates noisy) -- n_bins defaults to 4, a
disclosed choice, not tuned per pair. Finite-sample bias in TE estimates
is a known issue in the literature; the permutation-test null is this
script's mitigation (it estimates the SAME finite-sample bias under the
null and nets it out via the p-value), not a full bias-correction
estimator (e.g. Kraskov-Stogbauer-Grassberger).
"""
import argparse
import logging
import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_RESEARCH_DIR = os.path.dirname(os.path.abspath(__file__))
if _RESEARCH_DIR not in sys.path:
    sys.path.insert(0, _RESEARCH_DIR)

from data import _gap_aware_returns
from aligned_pair_loader import load_aligned_pair
from pair_source import confirmed_pairs_list

log = logging.getLogger(__name__)
_OUT_DIR = os.path.join(_ROOT, "output", "research")
_LOG_PATH = os.path.join(_ROOT, "latest_run_transfer_entropy_lead_lag.log")


def discretize(x: np.ndarray, n_bins: int) -> np.ndarray:
    """Quantile bins (equal-population, not equal-width -- robust to fat-
    tailed return distributions). Ties broken by rank so every bin gets a
    real, non-degenerate boundary even with repeated values."""
    ranks = pd.Series(x).rank(method="first").values
    return pd.qcut(ranks, n_bins, labels=False, duplicates="drop")


def transfer_entropy(x: np.ndarray, y: np.ndarray, lag: int, n_bins: int = 4) -> float:
    """TE_{Y->X} at the given lag (bars), embedding dim 1. Returns bits.
    x, y must be equal-length, already return-aligned series (same index,
    gap-masked NaN already dropped by the caller)."""
    n = len(x)
    if lag < 1 or n - lag - 1 < n_bins ** 3 * 2:
        return float("nan")  # not enough rows for a non-degenerate 3-way histogram

    # t ranges over [lag+1, n-1]: x_future[i]=x[t], x_past[i]=x[t-1],
    # y_past[i]=y[t-lag], all length n-lag-1, i indexed from t=lag+1.
    # (An earlier version had y_past off by one -- y[0:n-lag-1] gives
    # y[t-lag-1], not y[t-lag] -- silently testing lag+1 under the "lag"
    # label. Caught by debug/_verify_transfer_entropy_lead_lag.py's
    # known-lag synthetic check, which peaked at the wrong reported lag.)
    x_future = x[lag + 1:]        # x_t
    x_past = x[lag:n - 1]         # x_{t-1}
    y_past = y[1:n - lag]         # y_{t-lag}

    xb_future = discretize(x_future, n_bins)
    xb_past = discretize(x_past, n_bins)
    yb_past = discretize(y_past, n_bins)

    valid = ~(pd.isna(xb_future) | pd.isna(xb_past) | pd.isna(yb_past))
    xb_future, xb_past, yb_past = xb_future[valid], xb_past[valid], yb_past[valid]
    if len(xb_future) < n_bins ** 3 * 2:
        return float("nan")

    df = pd.DataFrame({"xf": xb_future, "xp": xb_past, "yp": yb_past})
    n_total = len(df)

    joint_xfp_yp = df.groupby(["xf", "xp", "yp"]).size() / n_total
    joint_xp_yp = df.groupby(["xp", "yp"]).size() / n_total
    joint_xf_xp = df.groupby(["xf", "xp"]).size() / n_total
    marg_xp = df.groupby(["xp"]).size() / n_total

    te = 0.0
    for (xf, xp, yp), p_xfp_yp in joint_xfp_yp.items():
        p_cond_xy = p_xfp_yp / joint_xp_yp[(xp, yp)]
        p_cond_x = joint_xf_xp[(xf, xp)] / marg_xp[xp]
        if p_cond_x <= 0 or p_cond_xy <= 0:
            continue
        te += p_xfp_yp * np.log2(p_cond_xy / p_cond_x)
    return float(max(te, 0.0))  # TE is non-negative in population; clip finite-sample negative noise


def circular_shift(y: np.ndarray, shift: int) -> np.ndarray:
    return np.roll(y, shift)


def te_with_significance(x: np.ndarray, y: np.ndarray, lag: int, n_bins: int,
                          n_perm: int, rng: np.random.Generator) -> dict:
    real_te = transfer_entropy(x, y, lag, n_bins)
    if not np.isfinite(real_te):
        return {"lag": lag, "te": float("nan"), "status": "insufficient_data"}

    n = len(y)
    null_tes = []
    for _ in range(n_perm):
        shift = int(rng.integers(1, n))  # any nonzero circular shift breaks the real x/y alignment
        y_shifted = circular_shift(y, shift)
        null_te = transfer_entropy(x, y_shifted, lag, n_bins)
        if np.isfinite(null_te):
            null_tes.append(null_te)

    if not null_tes:
        return {"lag": lag, "te": real_te, "status": "permutation_failed"}

    null_tes = np.array(null_tes)
    p_value = float(np.mean(null_tes >= real_te))
    return {
        "lag": lag, "te": real_te, "status": "ok",
        "null_mean_te": float(null_tes.mean()), "null_p95_te": float(np.percentile(null_tes, 95)),
        "p_value": p_value, "n_perm_used": len(null_tes),
    }


def run_pair(symbol_a: str, symbol_b: str, tf_label: str, max_lag: int, n_bins: int,
             n_perm: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    df_a, df_b = load_aligned_pair(symbol_a, symbol_b, tf_label)
    if df_a is None or df_b is None or df_a.empty or df_b.empty:
        return {"symbol_a": symbol_a, "symbol_b": symbol_b, "tf_label": tf_label, "status": "no_data"}

    ret_a = pd.Series(_gap_aware_returns(df_a), index=df_a.index)
    ret_b = pd.Series(_gap_aware_returns(df_b), index=df_b.index)
    common_idx = ret_a.index.intersection(ret_b.index)
    ret_a, ret_b = ret_a.reindex(common_idx).dropna(), ret_b.reindex(common_idx).dropna()
    common_idx = ret_a.index.intersection(ret_b.index)
    ret_a, ret_b = ret_a.reindex(common_idx).values, ret_b.reindex(common_idx).values

    if len(ret_a) < n_bins ** 3 * 4:
        return {"symbol_a": symbol_a, "symbol_b": symbol_b, "tf_label": tf_label,
                "status": "insufficient_bars", "n_bars": len(ret_a)}

    rows = []
    for lag in range(1, max_lag + 1):
        b_to_a = te_with_significance(ret_a, ret_b, lag, n_bins, n_perm, rng)
        a_to_b = te_with_significance(ret_b, ret_a, lag, n_bins, n_perm, rng)
        rows.append({"symbol_a": symbol_a, "symbol_b": symbol_b, "tf_label": tf_label,
                     "direction": f"{symbol_b}->{symbol_a}", "n_bars": len(ret_a), **b_to_a})
        rows.append({"symbol_a": symbol_a, "symbol_b": symbol_b, "tf_label": tf_label,
                     "direction": f"{symbol_a}->{symbol_b}", "n_bars": len(ret_a), **a_to_b})
    return {"symbol_a": symbol_a, "symbol_b": symbol_b, "tf_label": tf_label,
            "status": "ok", "rows": rows}


def summarize_pair_for_ml(result: dict) -> dict:
    """Reduces run_pair()'s full per-lag/per-direction row set to a single,
    FIXED-ORIENTATION (symbol_a/symbol_b, not "whichever leg happened to
    win") scalar summary suitable as an ml.py feature -- added 2026-09-08,
    Ross approved wiring transfer entropy into ml.py as the candidate
    feature PAPER.md §10 originally named. Picks the lag with the single
    strongest (lowest p-value) result across BOTH directions, then reports
    the SIGNED difference TE(b->a) - TE(a->b) at that lag -- positive means
    symbol_b's past predicts symbol_a's future more than the reverse,
    consistent in sign across every pair regardless of which leg happens
    to be called symbol_a. `te_significance` = 1 - min(p_value) at that
    lag (both directions), so higher is more significant -- easier for a
    tree model to split on than a raw p-value clustered near 0."""
    if result["status"] != "ok" or not result["rows"]:
        return {"symbol_a": result["symbol_a"], "symbol_b": result["symbol_b"],
                "tf_label": result["tf_label"], "te_directional_diff": float("nan"),
                "te_significance": float("nan"), "te_best_lag": None}

    ok_rows = [r for r in result["rows"] if r["status"] == "ok"]
    if not ok_rows:
        return {"symbol_a": result["symbol_a"], "symbol_b": result["symbol_b"],
                "tf_label": result["tf_label"], "te_directional_diff": float("nan"),
                "te_significance": float("nan"), "te_best_lag": None}

    best = min(ok_rows, key=lambda r: r["p_value"])
    best_lag = best["lag"]
    symbol_a, symbol_b = result["symbol_a"], result["symbol_b"]
    b_to_a = next((r for r in ok_rows if r["lag"] == best_lag
                   and r["direction"] == f"{symbol_b}->{symbol_a}"), None)
    a_to_b = next((r for r in ok_rows if r["lag"] == best_lag
                   and r["direction"] == f"{symbol_a}->{symbol_b}"), None)
    te_diff = (b_to_a["te"] if b_to_a else 0.0) - (a_to_b["te"] if a_to_b else 0.0)
    min_p = min(r["p_value"] for r in ok_rows if r["lag"] == best_lag)

    return {"symbol_a": symbol_a, "symbol_b": symbol_b, "tf_label": result["tf_label"],
            "te_directional_diff": float(te_diff), "te_significance": float(1.0 - min_p),
            "te_best_lag": int(best_lag)}


def main():
    p = argparse.ArgumentParser(description="Transfer entropy lead-lag scan over confirmed pairs")
    p.add_argument("--tf", default="1D")
    p.add_argument("--max-lag", type=int, default=5)
    p.add_argument("--n-bins", type=int, default=4)
    p.add_argument("--n-perm", type=int, default=200)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                         format="%(asctime)s  %(levelname)-8s  %(message)s",
                         datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(_LOG_PATH, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    log.addHandler(fh)
    log.info(f"=== transfer_entropy_lead_lag.py: tf={args.tf}, max_lag={args.max_lag}, "
             f"n_bins={args.n_bins}, n_perm={args.n_perm} ===")

    pairs = confirmed_pairs_list(tf_label=args.tf)
    log.info(f"{len(pairs)} confirmed pairs at tf={args.tf}")

    all_rows = []
    summary_rows = []
    for symbol_a, symbol_b in pairs:
        result = run_pair(symbol_a, symbol_b, args.tf, args.max_lag, args.n_bins, args.n_perm, args.seed)
        if result["status"] == "ok":
            all_rows.extend(result["rows"])
            best = min((r for r in result["rows"] if r["status"] == "ok"),
                       key=lambda r: r.get("p_value", 1.0), default=None)
            if best:
                log.info(f"  {symbol_a}/{symbol_b}: best {best['direction']} lag={best['lag']} "
                         f"TE={best['te']:.4f} bits, p={best['p_value']:.3f}")
        else:
            log.info(f"  {symbol_a}/{symbol_b}: {result['status']}")
        summary_rows.append(summarize_pair_for_ml(result))

    if all_rows:
        os.makedirs(_OUT_DIR, exist_ok=True)
        out_df = pd.DataFrame(all_rows)
        out_df.to_parquet(os.path.join(_OUT_DIR, "transfer_entropy_lead_lag.parquet"))
        log.info(f"Saved {len(out_df)} rows to output/research/transfer_entropy_lead_lag.parquet")
    else:
        log.warning("No pairs produced results.")

    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        summary_df.to_parquet(os.path.join(_OUT_DIR, "transfer_entropy_pair_summary.parquet"))
        log.info(f"Saved {len(summary_df)}-pair ml.py-ready summary to "
                 f"output/research/transfer_entropy_pair_summary.parquet")


if __name__ == "__main__":
    main()
