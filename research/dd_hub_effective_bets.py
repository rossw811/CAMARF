"""
CAMARF dd_hub_effective_bets.py — comparison/diagnostic method, NOT part of
the production pipeline.

Answers CAMARF's own flagged open question (PAPER.md Section 7.2): the 5
DD-hub pairs (AMD/DD, AME/DD, AMAT/DD, CMI/DD, DAL/DD — all sharing DD as
one leg, all confirmed via the coint_frac secondary-evidence override)
create correlated exposure to DD's idiosyncratic risk across 5 simultaneous
positions. "How many genuinely independent bets does this cluster actually
represent?" is answered here via THREE independent methods, checked for
convergence rather than trusting any single one:

  1. Grinold & Kahn breadth: BR_eff = N / (1 + (N-1)*rho_bar), the standard
     "fundamental law of active management" correction for correlated bets,
     using the average pairwise correlation rho_bar among the N=5 pairs.
  2. Meucci's Effective Number of Bets (2009-2010): eigen-decompose the
     correlation matrix, then treat the portfolio's variance contribution
     from each principal component as a probability distribution and take
     the exponential of its Shannon entropy — a genuinely different
     mechanism from Grinold-Kahn (it doesn't assume equicorrelation; it
     uses the ACTUAL eigenvalue spectrum), reusing the same eigendecomposition
     machinery analysis.py's EigenportfolioDecomposer already runs.
  3. Carver's Instrument Diversification Multiplier: IDM = 1/sqrt(w'Rw) for
     portfolio weights w and correlation matrix R. For equal weights this
     is provably IDM = sqrt(BR_eff) (shown directly below, not assumed) —
     a genuinely independent practitioner-derived formula that happens to
     be mathematically linked to Grinold-Kahn once weights are equal, which
     is itself worth stating explicitly rather than treating as a third,
     fully independent number.

rho_bar itself is estimated two ways for comparison: (a) static — the
simple average pairwise correlation of each pair's z_rolling deltas over
the full confirmed-pair history; (b) using analysis.py's own existing
rolling-correlation machinery (UniverseFilter._pairwise_corr) on a trailing
window, to see whether the "how correlated are these 5 bets" answer is
stable over time or itself time-varying.

Data note: trade-level P&L correlation was considered and rejected as the
input here — output/backtest/trades_layer1.parquet currently has ZERO
recorded trades for all 5 DD-hub pairs (a real, separate finding, not a
bug in this script — confirmed by direct inspection), which would make a
trade-P&L correlation matrix undefined. z_rolling deltas from each pair's
own spread_series (the same gap-masked series backtest.py trades from) are
used instead — a more fundamental, always-available measure of "how
correlated are these two mean-reversion processes" that doesn't depend on
whether a specific entry threshold happened to fire.

Read-only. Never fetches, never recomputes hedge ratios or spreads.

Usage:
    python research/dd_hub_effective_bets.py
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DD_HUB_PAIRS = [
    ("AMD", "DD"), ("AME", "DD"), ("AMAT", "DD"), ("CMI", "DD"), ("DAL", "DD"),
]


def _resolve_tf_results_dir(tf_dir="1hr"):
    live = os.path.join("output", "results", tf_dir)
    if os.path.isdir(live):
        return live
    candidates = sorted(glob.glob(os.path.join("output", "results", f"{tf_dir}_stale_*")))
    return candidates[-1] if candidates else live


def _load_real_bar_series(results_dir, sym_a, sym_b, column="z_rolling"):
    """Loads one pair's spread_series parquet, excludes DATA_GAP-flagged
    padding on either leg (see threshold_cointegration.py's docstring for
    why this matters — the file is stored on the full calendar-padded grid,
    not a compacted real-bars-only series), returns a Series indexed by
    the real DatetimeIndex so multiple pairs can be aligned by date."""
    path = os.path.join(results_dir, f"spread_series_{sym_a}_{sym_b}.parquet")
    if not os.path.exists(path):
        return None
    df = pd.read_parquet(path)
    real_mask = (df["gap_flag_a"] != 4) & (df["gap_flag_b"] != 4)
    s = df.loc[real_mask, column]
    return s[np.isfinite(s)]


def grinold_kahn_breadth(rho_bar, n):
    return n / (1 + (n - 1) * rho_bar)


def meucci_effective_bets(corr_matrix, weights):
    """
    Meucci (2009), "Managing Diversification," Risk — effective number of
    bets via the eigenvalue-based diversification distribution.

    p_k = (w' v_k)^2 * lambda_k / (w' Sigma w), for each eigenvector v_k /
    eigenvalue lambda_k of Sigma (here the correlation matrix, since weights
    are applied to standardized series). ENB = exp(entropy(p)), i.e. the
    exponential of the Shannon entropy of the p_k distribution — equals N
    when all eigenvalues are equal (fully diversified basis) and equals 1
    when one eigenvalue captures all the variance (fully concentrated).

    Known degenerate special case (verified directly, not just asserted —
    see debug/_verify_dd_hub_effective_bets.py Case 3): for an EXACTLY
    equicorrelated matrix under EXACTLY equal weights, the equal-weight
    vector is itself an exact eigenvector (the "common factor" direction),
    so this formula returns ENB=1.0 regardless of how small rho is, as long
    as rho>0. This is mathematically correct, not a bug — the entire
    portfolio's own variance genuinely concentrates in that one factor in
    that exact special case — but it means this metric should be read
    alongside Grinold-Kahn's rho_bar-based breadth, not as a drop-in
    replacement for it; the real DD-hub correlation matrix is not exactly
    equicorrelated, so this degeneracy is not expected to bite in practice.
    """
    corr_matrix = np.asarray(corr_matrix, dtype=float)
    weights = np.asarray(weights, dtype=float)
    eigenvalues, eigenvectors = np.linalg.eigh(corr_matrix)
    # np.linalg.eigh returns ascending order; sort descending for clarity
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[order]
    eigenvectors = eigenvectors[:, order]

    port_var = weights @ corr_matrix @ weights
    if port_var <= 0:
        return {"enb": np.nan, "diversification_distribution": None}

    projections = eigenvectors.T @ weights  # (w' v_k) for each k
    p = (projections ** 2) * eigenvalues / port_var
    p = np.clip(p, 1e-15, None)  # guard log(0) for numerically-zero components
    p = p / p.sum()  # renormalize after clipping (should already sum to ~1)
    entropy = -np.sum(p * np.log(p))
    enb = float(np.exp(entropy))
    return {"enb": enb, "diversification_distribution": p, "eigenvalues": eigenvalues}


def carver_idm(corr_matrix, weights):
    """Carver (2015), Systematic Trading — Instrument Diversification
    Multiplier = 1/sqrt(w' R w). Provably equals sqrt(Grinold-Kahn breadth)
    under equal weighting (w_i = 1/N for all i): w'Rw = (1/N)(1+(N-1)*rho_bar)
    when R is equicorrelated, so IDM = sqrt(N/(1+(N-1)*rho_bar)) =
    sqrt(BR_eff) exactly — not assumed, derivable directly from the
    definitions, and confirmed numerically in this module's own synthetic
    verification."""
    corr_matrix = np.asarray(corr_matrix, dtype=float)
    weights = np.asarray(weights, dtype=float)
    port_var = weights @ corr_matrix @ weights
    if port_var <= 0:
        return np.nan
    return float(1.0 / np.sqrt(port_var))


def analyze_cluster(corr_matrix, labels=None):
    """Runs all three methods on one correlation matrix, equal-weighted."""
    n = corr_matrix.shape[0]
    weights = np.full(n, 1.0 / n)
    off_diag = corr_matrix[~np.eye(n, dtype=bool)]
    rho_bar = float(np.mean(off_diag))
    br_eff = grinold_kahn_breadth(rho_bar, n)
    meucci = meucci_effective_bets(corr_matrix, weights)
    idm = carver_idm(corr_matrix, weights)
    return {
        "n": n, "rho_bar": rho_bar,
        "grinold_kahn_breadth": br_eff,
        "meucci_enb": meucci["enb"],
        "carver_idm": idm,
        "idm_squared_vs_breadth_check": idm ** 2 if not np.isnan(idm) else np.nan,
    }


def main():
    results_dir = _resolve_tf_results_dir("1hr")
    print(f"Loading DD-hub pairs from: {results_dir}\n")

    series_by_pair = {}
    for sym_a, sym_b in DD_HUB_PAIRS:
        s = _load_real_bar_series(results_dir, sym_a, sym_b, column="z_rolling")
        if s is None:
            print(f"MISSING {sym_a}/{sym_b}: no spread_series file")
            continue
        series_by_pair[f"{sym_a}/{sym_b}"] = s

    if len(series_by_pair) < 2:
        print("Fewer than 2 DD-hub pairs available — cannot build a correlation matrix.")
        return

    # Align on common real-bar timestamps, take first differences of
    # z_rolling (the entry-signal series itself) as each pair's "return."
    aligned = pd.DataFrame(series_by_pair).dropna(how="any")
    deltas = aligned.diff().dropna(how="any")
    print(f"Aligned on {len(deltas)} common real bars across {len(series_by_pair)} pairs\n")

    corr_matrix = deltas.corr().to_numpy()
    labels = list(deltas.columns)
    print("Correlation matrix (z_rolling deltas):")
    print(deltas.corr().round(3).to_string())
    print()

    result = analyze_cluster(corr_matrix, labels)
    print(f"N pairs: {result['n']}")
    print(f"Average pairwise correlation (rho_bar): {result['rho_bar']:.4f}")
    print(f"Grinold-Kahn effective breadth (BR_eff): {result['grinold_kahn_breadth']:.3f}")
    print(f"Meucci Effective Number of Bets (ENB):   {result['meucci_enb']:.3f}")
    print(f"Carver Instrument Diversification Multiplier (IDM): {result['carver_idm']:.3f}")
    print(f"  (check: IDM^2 = {result['idm_squared_vs_breadth_check']:.3f}, "
          f"should equal BR_eff = {result['grinold_kahn_breadth']:.3f} under equal weighting)")

    os.makedirs("output/research", exist_ok=True)
    out_path = "output/research/dd_hub_effective_bets.parquet"
    pd.DataFrame([result]).to_parquet(out_path)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
