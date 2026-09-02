"""
research/johansen_basket_cointegration.py -- comparison/diagnostic script,
NOT part of the production pipeline (2026-09-01).

Scoped per docs/research/LIBRARY_SURVEY_2026-09-01.md's corrected finding:
CAMARF's cointegration methodology is pairwise-only (Engle-Granger via
statsmodels.tsa.stattools.coint, used everywhere). Johansen's test
(statsmodels.tsa.vector_ar.vecm.coint_johansen -- NOT arch, an earlier draft
of the survey wrongly attributed it there, corrected before anything was
built) tests the cointegrating RANK of a basket of 3+ series jointly. The
real question: does testing already-related symbols as a BASKET (a confirmed
pair plus a same-sector third leg) surface a genuine multi-asset
cointegrating relationship that pairwise EG, applied only to the two
sub-pairs never tested as a pair, would have missed entirely?

Scope, deliberately bounded (not an exhaustive basket search over the full
universe -- combinatorially infeasible and not the actual question):
starts from CAMARF's own already-confirmed pairs (real, validated pairwise
relationships), extends each with up to N_THIRD_LEGS same-GICS-sector
candidate third symbols, and tests THAT specific, economically-motivated
triple -- the same "pre-registered restriction" discipline
sector_restricted_fdr_rescan.py already uses, not an unprincipled trawl.

For each triple (A, B, C):
  1. Align the three close series onto a shared calendar (DataAligner,
     exactly matching every other script's alignment step -- see
     near_miss_lag_scan.py's own "BUG FOUND AND FIXED" account of what goes
     wrong skipping this).
  2. Log-transform, drop any row with a NaN in any of the three legs
     (Johansen requires a complete matrix; GapFlag-masked gaps are NEVER
     forward-filled here, matching CLAUDE.md rule 3 -- rows are dropped, not
     imputed).
  3. Run coint_johansen(matrix, det_order=0, k_ar_diff=1), determine the
     cointegrating rank via the standard trace-statistic procedure (reject
     r=0 if trace_stat[0] exceeds its 95% critical value, then r=1, stopping
     at the first non-rejection).
  4. Cross-check: was (A,C) or (B,C) ALREADY separately pairwise-EG-confirmed
     anywhere in CAMARF's existing candidate/confirmed-pairs record? If the
     basket finds rank>=1 while NEITHER sub-pair was ever separately
     confirmed, that's the genuinely new-information case this script exists
     to find.

Read-only. Reuses universe_loader.load_full_universe() (per Ross's 2026-09-01
"every script should use the 44,700" standing direction), pair_source.py's
confirmed/candidate pairs lists, and gics.py's sector tags -- no new fetch,
no new EG tests.

Usage:
    python research/johansen_basket_cointegration.py
    python research/johansen_basket_cointegration.py --tf 1D --third-legs 3
"""
import argparse
import logging
import os
import sys
import time

import numpy as np
import pandas as pd
from statsmodels.tsa.vector_ar.vecm import coint_johansen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import DataAligner
from gics import load_gics_tags
from research.pair_source import confirmed_pairs_list, candidate_pairs_list
from universe_loader import load_full_universe

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")
MIN_OVERLAP_BARS = 250
DEFAULT_THIRD_LEGS = 3
CRIT_VAL_95_COL = 1  # coint_johansen's trace_stat_crit_vals columns are [90%, 95%, 99%]

log = logging.getLogger("johansen_basket_cointegration")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_johansen_basket_cointegration.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def johansen_rank(log_price_matrix: np.ndarray, det_order: int = 0, k_ar_diff: int = 1) -> int:
    """Pure function -- given an (n_obs x n_vars) log-price matrix with NO
    NaNs, returns the Johansen cointegrating rank via the standard trace-
    statistic sequential-testing procedure at the 95% level. Kept free of
    any data loading so debug/_verify_johansen_basket_cointegration.py can
    exercise it directly on synthetic series with a known true rank
    (a random-walk basket -> rank 0; a basket with one genuine common
    stochastic trend -> rank >= 1)."""
    result = coint_johansen(log_price_matrix, det_order, k_ar_diff)
    n_vars = log_price_matrix.shape[1]
    rank = 0
    for i in range(n_vars):
        if result.trace_stat[i] > result.trace_stat_crit_vals[i, CRIT_VAL_95_COL]:
            rank = i + 1
        else:
            break
    return rank


def build_third_leg_candidates(confirmed_pairs: list, sector_map: dict,
                                universe_symbols: set, n_third_legs: int) -> list:
    """Pure function -- given confirmed pairs, a {symbol: sector} map, the
    set of symbols actually present in the loaded universe, and how many
    third legs to try per pair, returns a list of (a, b, c) triples. Only
    pairs where BOTH symbols have a known, matching sector are extended (an
    unmapped or cross-sector pair has no principled same-sector third-leg
    candidate set). Third legs are sorted alphabetically for determinism,
    capped at n_third_legs, and never equal to a or b."""
    triples = []
    for a, b in confirmed_pairs:
        if a not in universe_symbols or b not in universe_symbols:
            continue
        sec_a, sec_b = sector_map.get(a), sector_map.get(b)
        if sec_a is None or sec_a != sec_b:
            continue
        candidates = sorted(
            sym for sym, sec in sector_map.items()
            if sec == sec_a and sym not in (a, b) and sym in universe_symbols
        )[:n_third_legs]
        for c in candidates:
            triples.append((a, b, c))
    return triples


def main():
    _setup_logging()
    parser = argparse.ArgumentParser(
        description="Does Johansen basket cointegration find relationships pairwise EG misses?"
    )
    parser.add_argument("--tf", default="1D")
    parser.add_argument("--third-legs", type=int, default=DEFAULT_THIRD_LEGS)
    args = parser.parse_args()

    log.info("=== johansen_basket_cointegration.py: basket (3-asset) vs. pairwise (EG) "
              "cointegration comparison, tf=%s ===", args.tf)

    t0 = time.time()
    universe = load_full_universe(args.tf, columns=["close"])
    log.info("Loaded %d symbols from the merged yfinance+WRDS+Binance+IBKR universe "
              "(tf=%s) in %.1fs", len(universe), args.tf, time.time() - t0)

    confirmed = confirmed_pairs_list(args.tf if args.tf != "1D" else None)
    if not confirmed:
        confirmed = confirmed_pairs_list()
    log.info("Loaded %d confirmed pairs", len(confirmed))

    tags = load_gics_tags()
    sector_map = tags.dropna(subset=["sector"]).set_index("symbol")["sector"].to_dict()
    log.info("GICS sector tags loaded for %d symbols", len(sector_map))

    candidate_pool_pairs = set(candidate_pairs_list())
    confirmed_pool_pairs = set(confirmed)

    triples = build_third_leg_candidates(confirmed, sector_map, set(universe.keys()), args.third_legs)
    log.info("Built %d (A,B,C) triples from %d confirmed pairs (up to %d same-sector third legs each)",
              len(triples), len(confirmed), args.third_legs)

    rows = []
    t_johansen_start = time.time()
    for a, b, c in triples:
        aligned = DataAligner.align_universe(
            {f"{a}_{args.tf}": universe[a], f"{b}_{args.tf}": universe[b], f"{c}_{args.tf}": universe[c]},
            args.tf,
        )
        # BUG FOUND AND FIXED 2026-09-01: align_universe's OUTPUT dict is keyed by bare
        # symbol name (e.g. "KVUE"), NOT the f"{sym}_{tf}" label used for the INPUT dict
        # -- confirmed directly against real data (a real 3-symbol call returned
        # aligned.keys() == ['KVUE','KMB','ACI'], not the '_1D'-suffixed labels passed
        # in). The original f"{sym}_{tf}" lookup silently failed for every triple,
        # `continue`-ing before ever reaching the overlap check -- a real 0-triples-
        # tested run was actually this bug, not a genuine data-overlap shortage.
        if not all(sym in aligned for sym in (a, b, c)):
            continue
        closes = pd.concat([aligned[sym]["close"].rename(sym) for sym in (a, b, c)], axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            log_prices = np.log(closes.to_numpy())
        log_prices[~np.isfinite(log_prices)] = np.nan
        complete = log_prices[~np.isnan(log_prices).any(axis=1)]
        if len(complete) < MIN_OVERLAP_BARS:
            continue

        try:
            rank = johansen_rank(complete)
        except Exception as e:
            log.debug("  %s/%s/%s: Johansen failed (%s), skipping", a, b, c, e)
            continue

        ac_confirmed = (a, c) in confirmed_pool_pairs or (c, a) in confirmed_pool_pairs
        bc_confirmed = (b, c) in confirmed_pool_pairs or (c, b) in confirmed_pool_pairs
        ac_candidate = (a, c) in candidate_pool_pairs or (c, a) in candidate_pool_pairs
        bc_candidate = (b, c) in candidate_pool_pairs or (c, b) in candidate_pool_pairs
        novel = rank >= 1 and not ac_confirmed and not bc_confirmed

        rows.append({
            "symbol_a": a, "symbol_b": b, "symbol_c": c, "n_obs": len(complete),
            "johansen_rank": rank, "ac_pairwise_confirmed": ac_confirmed,
            "bc_pairwise_confirmed": bc_confirmed, "ac_pairwise_candidate": ac_candidate,
            "bc_pairwise_candidate": bc_candidate, "novel_basket_finding": novel,
        })
        if novel:
            log.info("  NOVEL: %s/%s/%s basket rank=%d, but neither %s/%s nor %s/%s was ever "
                      "separately pairwise-confirmed", a, b, c, rank, a, c, b, c)

    johansen_elapsed = time.time() - t_johansen_start
    df = pd.DataFrame(rows)
    n_tested = len(df)
    n_rank_ge1 = int((df["johansen_rank"] >= 1).sum()) if n_tested else 0
    n_novel = int(df["novel_basket_finding"].sum()) if n_tested else 0

    log.info("")
    log.info("=== Summary ===")
    log.info("Triples tested (enough overlapping data): %d / %d built", n_tested, len(triples))
    log.info("Johansen rank >= 1 (some cointegration found): %d/%d (%.1f%%)",
              n_rank_ge1, n_tested, 100.0 * n_rank_ge1 / n_tested if n_tested else 0.0)
    log.info("NOVEL (rank>=1 AND neither sub-pair ever pairwise-confirmed): %d/%d (%.1f%%)",
              n_novel, n_tested, 100.0 * n_novel / n_tested if n_tested else 0.0)
    log.info("Johansen testing wall time: %.2fs for %d triples (%.3fs/triple)",
              johansen_elapsed, n_tested, johansen_elapsed / n_tested if n_tested else 0.0)

    os.makedirs(_OUT_DIR, exist_ok=True)
    df.to_parquet(os.path.join(_OUT_DIR, "johansen_basket_cointegration_summary.parquet"), index=False)
    log.info("Saved -> output/research/johansen_basket_cointegration_summary.parquet")


if __name__ == "__main__":
    main()
