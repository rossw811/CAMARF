"""
research/sector_fdr_random_null_comparison.py -- comparison/diagnostic script,
NOT part of the production pipeline (2026-09-01).

Motivated by docs/research/RQM_CONCEPTUAL_LENS_2026-09-01.md's RQM-3
("relations are intrinsic") reading of research/sector_restricted_fdr_rescan.py:
that script restricts the full-universe candidate pool to same-GICS-sector
pairs only, shrinking the multiple-testing burden m before applying one FDR
correction to the smaller pool. The open question this script answers: does
that restriction change which pairs survive FDR *because sector identity is
doing real work*, or would *any* equally-sized restriction of the candidate
pool -- chosen at random, with zero economic meaning -- produce a similarly
different survivor set purely from shrinking m?

Method: reuses sector_restricted_fdr_rescan.py's own
restrict_to_same_sector() and fdr_method_comparison.py's apply_all_methods()
UNCHANGED (no reimplementation) to get the real same-sector result and its
exact m. Then draws N_TRIALS random subsets of the SAME size m from the same
raw candidate pool (uniform sampling without replacement, no sector
information used), re-applies the same 4 FDR methods to each draw, and
reports where the real same-sector survivor count falls within that random
null's empirical distribution (percentile rank) per method.

Interpretation: if the real same-sector count sits comfortably inside the
random null's typical range (e.g. 5th-95th percentile), sector identity is
not doing anything sector-SPECIFIC beyond the m-reduction every restriction
would produce -- a real, honestly-reportable negative finding. If it sits
clearly outside that range, that is genuine evidence the sector grouping
carries real signal beyond mere pool-shrinkage.

Read-only. Reuses the exact same cached raw p-values sector_restricted_fdr_
rescan.py already reads (research/fdr_method_comparison_raw.parquet) -- no
new EG tests, no new data fetch.

Usage:
    python research/sector_fdr_random_null_comparison.py
    python research/sector_fdr_random_null_comparison.py --n-trials 500 --seed 7
"""
import argparse
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gics import load_gics_tags
from research.fdr_method_comparison import apply_all_methods
from research.sector_restricted_fdr_rescan import restrict_to_same_sector

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")
_RAW_PATH = os.path.join(_OUT_DIR, "fdr_method_comparison_raw.parquet")
ALPHA = 0.05
DEFAULT_N_TRIALS = 200

log = logging.getLogger("sector_fdr_random_null_comparison")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_sector_fdr_random_null_comparison.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def random_null_survivor_counts(all_pvals: np.ndarray, m: int, n_trials: int,
                                 alpha: float, rng: np.random.Generator) -> dict:
    """Pure, independently-testable core -- given the FULL raw p-value pool,
    the real same-sector restriction size m, and a trial count, draws
    n_trials random size-m subsets (no replacement) and applies the same 4
    FDR methods to each. Returns {method: np.ndarray of n_trials survivor
    counts}. Kept free of any I/O so debug/_verify_sector_fdr_random_null_
    comparison.py can exercise it directly on a small synthetic p-value pool
    with a known true rejection rate."""
    n_pool = len(all_pvals)
    if m > n_pool:
        raise ValueError(f"Requested subset size m={m} exceeds pool size {n_pool}")
    method_names = list(apply_all_methods(np.array([0.01]), alpha).keys())
    counts = {name: np.empty(n_trials, dtype=int) for name in method_names}
    for t in range(n_trials):
        idx = rng.choice(n_pool, size=m, replace=False)
        sample = all_pvals[idx]
        rejections = apply_all_methods(sample, alpha)
        for name, rej in rejections.items():
            counts[name][t] = int(rej.sum())
    return counts


def percentile_rank(value: int, null_distribution: np.ndarray) -> float:
    """Fraction of the null distribution <= value (0-100 scale) -- how
    extreme the real result looks against the random null."""
    if len(null_distribution) == 0:
        return float("nan")
    return 100.0 * float(np.mean(null_distribution <= value))


def main():
    _setup_logging()
    parser = argparse.ArgumentParser(
        description="Is sector-restricted FDR's effect sector-specific, or just an m-reduction artifact?"
    )
    parser.add_argument("--n-trials", type=int, default=DEFAULT_N_TRIALS)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    log.info("=== sector_fdr_random_null_comparison.py: is same-sector restriction's effect "
              "sector-specific, or just pool-shrinkage in disguise? ===")

    if not os.path.exists(_RAW_PATH):
        log.error("Missing %s -- run research/fdr_method_comparison.py first", _RAW_PATH)
        sys.exit(1)

    raw = pd.read_parquet(_RAW_PATH)
    log.info("Loaded %d candidate pairs from the full-universe EG run", len(raw))

    tags = load_gics_tags()
    sector_map = tags.dropna(subset=["sector"]).set_index("symbol")["sector"].to_dict()
    restricted = restrict_to_same_sector(raw, sector_map)
    m_real = len(restricted)
    log.info("Real same-sector restriction: m=%d (of %d total candidates)", m_real, len(raw))

    real_rejections = apply_all_methods(restricted["pvalue"].to_numpy(), ALPHA)
    real_counts = {name: int(rej.sum()) for name, rej in real_rejections.items()}
    log.info("Real same-sector survivor counts: %s", real_counts)

    all_pvals = raw["pvalue"].to_numpy()
    rng = np.random.default_rng(args.seed)
    log.info("Drawing %d random size-%d subsets from the full %d-candidate pool "
              "(no sector information used)...", args.n_trials, m_real, len(all_pvals))
    null_counts = random_null_survivor_counts(all_pvals, m_real, args.n_trials, ALPHA, rng)

    log.info("")
    log.info("=== Real same-sector result vs. random-restriction null (n_trials=%d) ===", args.n_trials)
    summary_rows = []
    for method, real_n in real_counts.items():
        null_dist = null_counts[method]
        pct = percentile_rank(real_n, null_dist)
        null_mean, null_std = float(null_dist.mean()), float(null_dist.std())
        extreme = pct <= 5.0 or pct >= 95.0
        verdict = "OUTSIDE typical random-null range -- sector identity may carry real signal" \
            if extreme else "INSIDE typical random-null range -- looks like pool-shrinkage, not sector-specific"
        log.info("  %-22s: real=%d  random-null mean=%.1f (std=%.1f, range=[%d,%d])  "
                  "percentile=%.1f%%  -> %s",
                  method, real_n, null_mean, null_std, int(null_dist.min()), int(null_dist.max()),
                  pct, verdict)
        summary_rows.append({
            "method": method, "real_survivor_count": real_n,
            "null_mean": null_mean, "null_std": null_std,
            "null_min": int(null_dist.min()), "null_max": int(null_dist.max()),
            "percentile_of_real_in_null": pct, "outside_typical_range": extreme,
        })

    os.makedirs(_OUT_DIR, exist_ok=True)
    pd.DataFrame(summary_rows).to_parquet(
        os.path.join(_OUT_DIR, "sector_fdr_random_null_comparison_summary.parquet"), index=False
    )
    log.info("Saved -> output/research/sector_fdr_random_null_comparison_summary.parquet")


if __name__ == "__main__":
    main()
