"""
research/descriptive_check_concordance.py -- comparison/diagnostic script,
NOT part of the production pipeline. Built 2026-07-21, completing the part
of the filter-relevance sweep the failed fork never reached ("Hurst/half-life/
ADF/permutation concordance testing... does each descriptive check's own
signal actually predict which pairs turn out tradeable, versus being
computed and reported with zero downstream consequence").

Motivation: the filter-relevance sweep (docs/GRAND_SWEEP.../dedicated_pass.md
task #4/section 11.2) confirmed Hurst/passes_ml_gate, the half-life ceiling,
and Johansen/KPSS/ADF/permutation tests are all DESCRIPTIVE in this pipeline
-- none of them currently GATE the confirmed-pair funnel (unlike Pearson,
EG+FDR, coint_frac, structural exclusion, which do). "Descriptive, not a
gate" leaves open a different, useful question: does each descriptive
check's own signal actually CORRELATE with which candidates end up
genuinely stable (coint_fraction_rolling clearing the production 0.70
threshold), or is it computed and reported with zero informational value
about what actually matters?

Population: every row across all 12 timeframes' output/results/*/
all_candidates.parquet (BUG-D95's fix means this now exists for every
timeframe, including ones whose funnel collapsed to zero final confirmed
pairs) -- the EG+FDR+price-degeneracy survivor set, BEFORE coint_frac/
structural filtering. This is deliberately the BROADER population, not just
the 2 final confirmed pairs, since a concordance test needs pairs that
SPAN both outcomes (stable and unstable) to say anything at all.

Honest scope note, stated up front: this population is n=20 pairs total
across all 12 timeframes (verified by reading the actual persisted files,
not assumed) -- genuinely thin for any concordance claim. Reported as
point estimates with the honest sample size attached, not oversold as a
definitive test. A null or weak result here is exactly as valid and
reportable as a strong one.

Checks tested against coint_fraction_rolling (the outcome proxy -- this IS
production's own downstream stability gate, so "does X correlate with
coint_fraction_rolling" is directly asking "does X predict what production
already decided matters"):
  - Hurst (hurst_rs, hurst_dfa): already persisted, no recomputation needed.
  - Half-life (half_life_rolling): already persisted.
  - ADF: research/adf_confirmatory_tier.py's run_adf_test(), reused
    directly, run fresh on each pair's persisted spread_series (BUG-D95's
    fix means this now exists for the full all_candidates population, not
    just the final confirmed set).
  - Permutation: the FIXED (BUG-D93) circular-shift null from
    research/eg_permutation_check.py, reused directly -- NOT the sparse
    pre-existing `permutation_robust` field (only populated for 2/20 pairs
    in the current persisted data, insufficient coverage), run fresh on
    every pair instead.

Read-only except for its own output. Never fetches.

Usage:
    python research/descriptive_check_concordance.py
"""
import glob
import logging
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis import Config
from adf_confirmatory_tier import run_adf_test
from eg_permutation_check import _circular_shift_null, _eg_pvalue, _gap_masked_log_price
from aligned_pair_loader import load_aligned_pair

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")
_OUT_DIR = os.path.join(_ROOT, "output", "research")

log = logging.getLogger("descriptive_check_concordance")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_descriptive_check_concordance.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def load_all_candidates():
    frames = []
    for f in sorted(glob.glob(os.path.join(_RESULTS_DIR, "*", "all_candidates.parquet"))):
        if "_stale_" in f:
            continue
        df = pd.read_parquet(f)
        df["_source_dir"] = os.path.basename(os.path.dirname(f))
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _load_spread(tf_dir, sym_a, sym_b):
    path = os.path.join(_RESULTS_DIR, tf_dir, f"spread_series_{sym_a}_{sym_b}.parquet")
    if not os.path.exists(path):
        return None
    return pd.read_parquet(path)


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== descriptive_check_concordance.py: do Hurst/half-life/ADF/permutation "
              "actually predict coint_fraction_rolling (production's own stability gate)? ===")

    candidates = load_all_candidates()
    log.info("Loaded %d (pair, tf) rows across all 12 timeframes' all_candidates.parquet "
              "(BUG-D95 fix makes this the full EG+FDR+price-degeneracy survivor population, "
              "not just the 2 final confirmed pairs)", len(candidates))
    if len(candidates) < 5:
        log.warning("Fewer than 5 rows -- concordance testing not meaningful. Aborting.")
        return

    rows = []
    for _, row in candidates.iterrows():
        sym_a, sym_b, tf_label = row["symbol_a"], row["symbol_b"], row["tf_label"]
        tf_dir = row["_source_dir"]

        # --- ADF: reuse research/adf_confirmatory_tier.py's run_adf_test()
        # directly on this pair's persisted spread (BUG-D95 fix means this
        # file exists for the full all_candidates population). ---
        spread_df = _load_spread(tf_dir, sym_a, sym_b)
        adf_status, adf_pval, adf_confirms = "no_spread_file", np.nan, None
        if spread_df is not None:
            real_mask = (spread_df["gap_flag_a"] != 4) & (spread_df["gap_flag_b"] != 4)
            spread = spread_df.loc[real_mask, "spread"].to_numpy(dtype=float)
            spread = spread[np.isfinite(spread)]
            adf = run_adf_test(spread)
            adf_status, adf_pval, adf_confirms = adf["status"], adf["adf_pval"], adf["adf_confirms"]

        # --- Permutation: genuine two-series EG circular-shift null, the
        # SAME mechanism research/eg_permutation_check.py uses (BUG-D93-fixed
        # version -- compacts to the fixed real-data overlap mask first,
        # then rolls only the fully-finite compacted array). Reloads the
        # pair's own two legs via aligned_pair_loader (not derivable from
        # spread_series alone, which only persists the combined spread, not
        # each leg's own log-price series). ---
        perm_status, perm_pvalue = "cache_missing", np.nan
        df_a, df_b = load_aligned_pair(sym_a, sym_b, tf_label)
        if df_a is not None and df_b is not None:
            log_a = _gap_masked_log_price(df_a)
            log_b = _gap_masked_log_price(df_b)
            real_p = _eg_pvalue(log_a, log_b, Config.ANALYSIS.EG_MAX_LAG)
            if real_p is None:
                perm_status = "eg_failed"
            else:
                null_pvals = _circular_shift_null(log_a, log_b, Config.ANALYSIS.EG_MAX_LAG, 200,
                                                    np.random.default_rng(42))
                if len(null_pvals) == 0:
                    perm_status = "insufficient_overlap_for_permutation"
                else:
                    perm_status = "computed"
                    perm_pvalue = float((1 + np.sum(null_pvals <= real_p)) / (len(null_pvals) + 1))

        rows.append({
            "symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf_label,
            "coint_fraction_rolling": row["coint_fraction_rolling"],
            "clears_coint_frac_070": bool(row["coint_fraction_rolling"] >= 0.70) if pd.notna(row["coint_fraction_rolling"]) else None,
            "hurst_rs": row["hurst_rs"], "hurst_dfa": row["hurst_dfa"],
            "half_life_rolling": row["half_life_rolling"],
            "adf_status": adf_status, "adf_pval": adf_pval, "adf_confirms": adf_confirms,
            "permutation_status": perm_status, "permutation_pvalue": perm_pvalue,
        })
        log.info("  %s/%s@%s: coint_frac=%.3f hurst_rs=%.3f half_life=%s adf_pval=%s "
                  "perm_pvalue=%s (%s)",
                  sym_a, sym_b, tf_label, row["coint_fraction_rolling"],
                  row["hurst_rs"], row["half_life_rolling"], adf_pval, perm_pvalue, perm_status)

    result_df = pd.DataFrame(rows)

    log.info("")
    log.info("=== Concordance (Spearman rank correlation vs. coint_fraction_rolling, n=%d) ===",
              len(result_df))
    log.info("HONEST SCOPE: n=%d is thin -- point estimates only, no significance claims implied.",
              len(result_df))
    outcome = result_df["coint_fraction_rolling"]
    for check_col in ["hurst_rs", "hurst_dfa", "half_life_rolling", "adf_pval", "permutation_pvalue"]:
        valid = result_df[check_col].notna() & outcome.notna()
        n_valid = int(valid.sum())
        if n_valid < 5:
            log.info("  %-22s: n=%d usable -- too few for a meaningful correlation", check_col, n_valid)
            continue
        rho, pval = spearmanr(result_df.loc[valid, check_col], outcome[valid])
        log.info("  %-22s: n=%d  spearman_rho=%.3f  p=%.3f", check_col, n_valid, rho, pval)

    os.makedirs(_OUT_DIR, exist_ok=True)
    result_df.to_parquet(os.path.join(_OUT_DIR, "descriptive_check_concordance.parquet"), index=False)
    log.info("Saved -> output/research/descriptive_check_concordance.parquet")

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("descriptive_check_concordance.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
