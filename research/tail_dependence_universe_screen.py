"""
research/tail_dependence_universe_screen.py -- comparison/diagnostic
script, NOT part of the production pipeline. Built 2026-07-21 per Ross's
explicit direction ("push on the two [k-BAHC] follow ups and do copulas"),
continuing the "new application work" build sequence he set (k-BAHC -> copula
tail-dependence -> wavelet-scale cointegration/DCC-GARCH).

Motivation: same as k_bahc_candidate_discovery.py -- CAMARF's confirmed-pair
universe just collapsed to 2 pairs out of a ~1.5M-possible-pair universe.
The filter-relevance sweep confirmed this isn't a filter-tuning artifact;
k-BAHC confirmed (three independent variants: whole-universe silhouette-k=2,
whole-universe forced-k=20, sector-restricted silhouette-k=2) that denoised
LINEAR correlation doesn't surface hidden structure either. This script asks
a genuinely DIFFERENT question: do any NEAR-MISS pairs (correlation just
below the Pearson pre-filter threshold, so they never reach EG at all) show
real TAIL dependence -- joint-crash or joint-rally tendency -- that a
linear-correlation/EG-based pipeline structurally cannot see at all?

Existing research/tail_dependence.py already built the empirical
tail-dependence estimator and applies it to the tiny CONFIRMED-pair
population (currently 2 pairs) as an asymmetry gate before considering a
copula-based entry rule. This repurposes the SAME estimator (reused
directly, not reimplemented) as a DISCOVERY screen over the much larger
near-miss population, following research/near_miss_lag_scan.py's established
"cheap prefilter to a near-miss band, not blind universe-wide brute force"
architecture -- the same discipline this project already uses for exactly
this class of question (near_miss_lag_scan.py tests the same near-miss band
for LAGGED correlation; this tests it for TAIL dependence instead).

Method:
  1. Same near-miss band as near_miss_lag_scan.py: near_miss_low <= |corr| <
     Config.UNIVERSE.MIN_PEARSON_CORR (0.25 <= |corr| < 0.40 by default),
     computed from the real production UniverseFilter's own correlation
     matrix (reused directly via UniverseFilter.run(..., return_matrices=True),
     same pattern research/k_bahc_candidate_discovery.py already established).
  2. For each near-miss pair, gap-aware log returns (aligned_pair_loader +
     data.py's _gap_aware_returns, exactly research/tail_dependence.py's own
     loading convention), then tail_dependence.py's own
     _empirical_tail_dependence(ret_a, ret_b, q) (reused directly, not
     reimplemented) at q in {0.05, 0.10}.
  3. Significance: under independence, lambda_L/lambda_U's expected value is
     exactly q, and the underlying joint-tail-hit COUNT (out of n_L or n_U
     conditioning observations, each an independent Bernoulli(q) trial under
     the null) follows Binomial(n, q) exactly -- a closed-form null needing
     no permutation resampling. Reports a one-sided binomial p-value: "how
     likely is this many (or more) joint-tail hits, by chance alone, given
     this many conditioning observations." Chosen over a permutation test
     purely for compute reasons at this candidate-count scale -- verified
     directly against a Monte Carlo reference on synthetic INDEPENDENT data
     before trusting it on real data (debug/_verify_tail_dependence_universe_
     screen.py), not assumed correct by construction.
  4. Multiple-testing correction: Benjamini-Yekutieli (research/
     bh_fdr_dependence_check.py, dependence-robust -- near-miss pairs sharing
     a leg are not independent tests -- reused directly, not reimplemented)
     across every (pair, q, tail) test actually run.
  5. Any survivor is explicitly NOT automatically a finding: tail dependence
     and cointegration are different claims (a pair can show real crisis
     co-movement without a stable long-run linear relationship, or vice
     versa). Survivors get the real production EG+BH-FDR test
     (_eg_worker/_benjamini_hochberg, reused directly) as a SEPARATE,
     honestly-reported check -- passing the tail-dependence screen alone
     does not make a pair tradeable under this project's existing
     cointegration-based methodology.

Read-only except for its own output. Never fetches.

Usage:
    python research/tail_dependence_universe_screen.py --tf 1h
"""
import argparse
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd
from scipy.stats import binom

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from analysis import UniverseFilter, _eg_worker, _benjamini_hochberg, CointScanner
from tail_dependence import _empirical_tail_dependence
from bh_fdr_dependence_check import benjamini_yekutieli
from universe_loader import align_to_common_calendar, load_full_universe

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")

log = logging.getLogger("tail_dependence_universe_screen")


def _setup_logging(tf_label):
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, f"latest_run_tail_dependence_universe_screen_{tf_label}.log"),
        mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def binomial_tail_pvalue(hit_count: int, n: int, q: float) -> float:
    """One-sided p-value: P(X >= hit_count) under X ~ Binomial(n, q), the
    null distribution of a joint-tail-hit count when the two legs are
    genuinely independent (each conditioning-set member has an independent
    q probability of also landing in the partner's same tail, by
    definition of q as the marginal tail probability)."""
    if n <= 0:
        return float("nan")
    return float(binom.sf(hit_count - 1, n, q))


def find_near_miss_pairs(pearson, symbols, near_miss_low, near_miss_high):
    n = len(symbols)
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            c = pearson[i, j]
            if np.isfinite(c) and near_miss_low <= abs(c) < near_miss_high:
                pairs.append((symbols[i], symbols[j], float(c)))
    return pairs


def screen_pair_tail_dependence(sym_a, sym_b, a_vals, b_vals, q_values):
    """Runs the tail-dependence estimator + binomial significance test at
    each q for one pair, given ALREADY gap-aware, ALREADY aligned return
    arrays (Tier-perf fix, 2026-07-21: originally called load_aligned_pair()
    per pair, which re-runs DataAligner.align_universe() from scratch for
    just 2 symbols each time -- at 320,070 near-miss pairs this was
    estimated at several hours. UniverseFilter.run(..., return_matrices=True)
    already builds and returns a full (T, n_symbols) returns matrix via
    build_returns_matrix(), which internally calls the SAME gap_aware_returns
    function load_aligned_pair's own callers use (analysis.py:673-681) --
    slicing two columns out of that already-computed matrix is
    behaviorally identical to load_aligned_pair's own gap-aware-returns
    output, just without the redundant per-pair reload/realignment).
    Returns a list of result dicts, one per q, or None if the pair's
    overlap is too short."""
    mask = np.isfinite(a_vals) & np.isfinite(b_vals)
    n_overlap = int(mask.sum())
    if n_overlap < 60:
        return None
    a_clean, b_clean = a_vals[mask], b_vals[mask]

    rows = []
    for q in q_values:
        result = _empirical_tail_dependence(a_clean, b_clean, q)
        if result is None:
            continue
        lam_l, lam_u, n_l, n_u = result
        p_lower = binomial_tail_pvalue(int(round(lam_l * n_l)), n_l, q) if (lam_l is not None and n_l > 0) else None
        p_upper = binomial_tail_pvalue(int(round(lam_u * n_u)), n_u, q) if (lam_u is not None and n_u > 0) else None
        rows.append({
            "symbol_a": sym_a, "symbol_b": sym_b, "q": q, "n_obs": n_overlap,
            "lambda_L": lam_l, "lambda_U": lam_u, "n_L": n_l, "n_U": n_u,
            "p_lower": p_lower, "p_upper": p_upper,
        })
    return rows if rows else None


def run_eg_fdr(candidates, aligned, retained_symbols, tf_label, alpha=None):
    """Runs the real production EG test + BH-FDR on a candidate list.
    Reuses _eg_worker/_benjamini_hochberg directly, same pattern as
    research/k_bahc_candidate_discovery.py and research/fdr_method_comparison.py."""
    if not candidates:
        return pd.DataFrame()
    alpha = alpha if alpha is not None else Config.STATS.FDR_ALPHA
    log_prices = CointScanner._build_log_price_map(aligned, retained_symbols)
    tasks = []
    for sym_a, sym_b in candidates:
        lp_a = log_prices.get(sym_a)
        lp_b = log_prices.get(sym_b)
        if lp_a is None or lp_b is None:
            continue
        tasks.append((sym_a, sym_b, lp_a, lp_b, Config.ANALYSIS.EG_MAX_LAG, tf_label))
    if not tasks:
        return pd.DataFrame()
    results = []
    with ProcessPoolExecutor(max_workers=12) as pool:
        for r in pool.map(_eg_worker, tasks, chunksize=25):
            results.append(r)
    ok = [r for r in results if r.get("ok")]
    if not ok:
        return pd.DataFrame(results)
    df = pd.DataFrame(ok)
    rejected, _ = _benjamini_hochberg(df["pvalue"].to_numpy(), alpha)
    df["confirmed_bh"] = rejected
    return df


def main():
    p = argparse.ArgumentParser(description="Universe-wide near-miss tail-dependence screen (2026-07-21)")
    p.add_argument("--tf", default="1h")
    p.add_argument("--near-miss-low", type=float, default=0.25)
    p.add_argument("--near-miss-high", type=float, default=None,
                    help="Defaults to Config.UNIVERSE.MIN_PEARSON_CORR")
    p.add_argument("--q", type=float, nargs="+", default=[0.05, 0.10])
    p.add_argument("--alpha", type=float, default=0.05)
    args = p.parse_args()
    tf_label = args.tf
    _setup_logging(tf_label)
    near_miss_high = args.near_miss_high if args.near_miss_high is not None else Config.UNIVERSE.MIN_PEARSON_CORR

    t0 = time.time()
    log.info("=== tail_dependence_universe_screen.py: does REAL TAIL dependence exist in the "
              "near-miss band (%.2f<=|corr|<%.2f) the linear pre-filter misses? (tf=%s) ===",
              args.near_miss_low, near_miss_high, tf_label)

    # REWIRED 2026-08-17 (methodology audit, Ross: "rewire them"): dropped this script's own
    # local load_full_universe() (old yfinance-only cache, same duplicated-loader bug class
    # as k_bahc_candidate_discovery.py) for the canonical universe_loader.py merge. WRDS is
    # daily-only, so at tf != "1D" this is not meaningfully larger than the old scope --
    # disclosed, not hidden.
    tf_data_raw = load_full_universe(tf_label, columns=["close"])
    log.info("Loaded %d symbols from the merged yfinance+WRDS+Binance+IBKR universe (tf=%s)",
             len(tf_data_raw), tf_label)
    if len(tf_data_raw) < 10:
        log.warning("Fewer than 10 symbols -- aborting.")
        return

    log.info("Aligning to a shared calendar (align_to_common_calendar, lookback_years=10)...")
    aligned = align_to_common_calendar(tf_data_raw, lookback_years=10)
    log.info("Aligned: %d symbols", len(aligned))

    asset_class_map = {sym: "equity" for sym in aligned}
    log.info("Running real production UniverseFilter (Pearson pre-filter, threshold=%.2f)...",
              near_miss_high)
    pairs, symbols, returns, pearson, symbol_order = UniverseFilter.run(
        aligned, asset_class_map, threshold=near_miss_high, tf_label=tf_label, return_matrices=True,
    )
    near_miss = find_near_miss_pairs(pearson, symbols, args.near_miss_low, near_miss_high)
    log.info("Near-miss pairs (%.2f<=|corr|<%.2f): %d", args.near_miss_low, near_miss_high, len(near_miss))
    if not near_miss:
        log.info("No near-miss pairs at this band -- nothing to screen.")
        return

    log.info("Screening %d near-miss pairs for tail dependence at q=%s (using the already-aligned "
              "returns matrix in memory, not per-pair reload)...", len(near_miss), args.q)
    sym_to_idx = {s: i for i, s in enumerate(symbols)}
    t_screen = time.time()
    all_rows = []
    for sym_a, sym_b, corr in near_miss:
        rows = screen_pair_tail_dependence(
            sym_a, sym_b, returns[:, sym_to_idx[sym_a]], returns[:, sym_to_idx[sym_b]], args.q
        )
        if rows is None:
            continue
        for r in rows:
            r["near_miss_corr"] = corr
        all_rows.extend(rows)
    log.info("Screening done in %.1fs", time.time() - t_screen)
    if not all_rows:
        log.info("No near-miss pair produced a usable tail-dependence estimate. Nothing to correct/report.")
        return

    result_df = pd.DataFrame(all_rows)
    log.info("Usable tail-dependence estimates: %d (pair, q) combinations", len(result_df))

    # BY-FDR across every one-sided p-value actually computed (lower and
    # upper treated as separate tests, same convention tail_dependence.py's
    # own per-tail reporting already uses).
    p_lower_valid = result_df["p_lower"].notna()
    p_upper_valid = result_df["p_upper"].notna()
    if p_lower_valid.any():
        rej_l, adj_l = benjamini_yekutieli(result_df.loc[p_lower_valid, "p_lower"].to_numpy(), args.alpha)
        result_df.loc[p_lower_valid, "p_lower_by_adjusted"] = adj_l
        result_df.loc[p_lower_valid, "significant_lower_by"] = rej_l
    if p_upper_valid.any():
        rej_u, adj_u = benjamini_yekutieli(result_df.loc[p_upper_valid, "p_upper"].to_numpy(), args.alpha)
        result_df.loc[p_upper_valid, "p_upper_by_adjusted"] = adj_u
        result_df.loc[p_upper_valid, "significant_upper_by"] = rej_u

    sig_mask = result_df.get("significant_lower_by", False) | result_df.get("significant_upper_by", False)
    survivors = result_df[sig_mask.fillna(False)] if isinstance(sig_mask, pd.Series) else result_df[[]]
    log.info("")
    log.info("=== BY-FDR-corrected tail-dependence survivors: %d/%d (pair, q) combinations ===",
              len(survivors), len(result_df))
    if survivors.empty:
        log.info("HONEST NULL RESULT: no near-miss pair shows tail dependence beyond what independence "
                  "alone would produce, after BY-FDR correction. This is a genuine, informative negative "
                  "result, not a failed search -- the near-miss population's weak linear correlation "
                  "does not hide a strong tail-dependence relationship either.")
        eg_results = pd.DataFrame()
    else:
        for _, row in survivors.sort_values(
            by=[c for c in ["p_lower_by_adjusted", "p_upper_by_adjusted"] if c in survivors.columns][:1]
        ).iterrows():
            log.info("  %s/%s q=%.2f: lambda_L=%s lambda_U=%s near_miss_corr=%.3f",
                      row["symbol_a"], row["symbol_b"], row["q"], row["lambda_L"], row["lambda_U"],
                      row["near_miss_corr"])
        survivor_pairs = sorted(set(zip(survivors["symbol_a"], survivors["symbol_b"])))
        log.info("")
        log.info("%d distinct surviving pair(s) -- running the REAL production EG+BH-FDR test "
                  "(tail dependence and cointegration are DIFFERENT claims; passing this screen alone "
                  "does not make a pair tradeable under this project's methodology)...", len(survivor_pairs))
        eg_results = run_eg_fdr(survivor_pairs, aligned, symbols, tf_label)
        if not eg_results.empty:
            n_confirmed = int(eg_results["confirmed_bh"].sum()) if "confirmed_bh" in eg_results.columns else 0
            log.info("EG+BH-FDR on tail-dependence survivors: %d/%d usable, %d cointegration-confirmed",
                      len(eg_results), len(survivor_pairs), n_confirmed)
            for _, row in eg_results.sort_values("pvalue").iterrows():
                log.info("  %s/%s: eg_pvalue=%.4f confirmed_bh=%s",
                          row["symbol_a"], row["symbol_b"], row["pvalue"], row.get("confirmed_bh"))
        else:
            log.info("No usable EG results for tail-dependence survivors.")

    os.makedirs(_OUT_DIR, exist_ok=True)
    result_df.to_parquet(os.path.join(_OUT_DIR, f"tail_dependence_universe_screen_{suffix}.parquet"), index=False)
    if not eg_results.empty:
        eg_results.to_parquet(
            os.path.join(_OUT_DIR, f"tail_dependence_universe_screen_eg_{suffix}.parquet"), index=False
        )
    log.info("Saved -> output/research/tail_dependence_universe_screen_{,eg_}%s.parquet", suffix)

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("tail_dependence_universe_screen.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
