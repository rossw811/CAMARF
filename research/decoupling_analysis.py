"""
CAMARF decoupling_analysis.py — exploratory diagnostic, NOT part of the
production pipeline.

Motivation (2026-06-30/07-01 design discussion with Ross): the existing
pipeline treats a decoupling event (a pair losing cointegration) purely as an
EXCLUSION signal — coint_fraction_rolling drops, Zivot-Andrews/CUSUM flag a
structural break, the pair fails passes_coint_frac_secondary_evidence() and
gets dropped from the confirmed set. The open question: is the decoupling
event ITSELF a tradeable signal, rather than just something to discard?
Before designing any entry/exit rule, this script answers the prior,
cheaper question: what actually happens to a pair's spread AFTER a real
detected break — does it keep diverging, settle into a new equilibrium
level, or turn out to have been a false alarm (reverts to the OLD
equilibrium, the break wasn't really structural)? This is a pure
description, not a strategy.

Detection trigger chosen and justified: the Zivot-Andrews break date
(`zivot_andrews_break`, already computed by StrategyDecayDetector and
persisted per-pair) — not coint_fraction_rolling crossing its threshold or a
half-life-trend-slope sign flip. Reasoning: ZA gives an actual point-in-time
break DATE (needed to split a series into before/after), while
coint_fraction_rolling and half-life trend slope are single scalars
summarizing the whole series with no specific event timestamp attached.

Method: for every pair with a non-null zivot_andrews_break (in
all_candidates.parquet — the broader pre-coint_frac/pre-structural set
persisted since the Phase 1 filter-ablation fix, not just the final
confirmed pairs, so this can include pairs that were excluded specifically
BECAUSE of this break), load its spread_series and:
  1. Compute the pre-break equilibrium: mean and std of the raw spread over
     the PRE_WINDOW bars immediately before the break date.
  2. Track the post-break spread's deviation from that pre-break mean,
     normalized by the pre-break std, over the available post-break history.
  3. Classify via a linear trend test (OLS slope) on |deviation| vs. time
     within the post-break window:
       - CONTINUED_DIVERGENCE: significant positive slope (deviation from
         the old equilibrium keeps growing)
       - REVERTED_TO_OLD_EQUILIBRIUM: significant negative slope AND the
         post-break window's late-period mean deviation is small (back
         near the pre-break level) — the "break" didn't stick; a false
         alarm relative to whatever ZA was reacting to
       - NEW_EQUILIBRIUM_SHIFT: no significant trend (deviation is flat,
         not growing or shrinking) but the average deviation level itself
         is materially non-zero (settled somewhere new, not oscillating
         back to the old mean)
       - INCONCLUSIVE: too little post-break history, or none of the above
         conditions are clearly met (near-zero deviation with no shift at
         all reads as "no material break occurred in practice" — also
         reported as INCONCLUSIVE rather than forced into a category)

Honest scope note: decoupling events are rare and this project's history
per pair is short (mostly 1-3 years, deepest at 10Y for IBKR-supplemented 1h
pairs) — this is necessarily a small-n descriptive study, not a
statistically powered test. Report the counts plainly; do not overstate
confidence from a handful of events.

Output:
  output/research/decoupling_analysis.parquet — per-event classification + stats
  latest_run_decoupling_analysis.log
"""
import logging
import os
import sys
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aligned_pair_loader import TF_DIRS as _TF_DIRS, resolve_tf_results_dir as _resolve_tf_results_dir

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")
_OUT_DIR = os.path.join(_ROOT, "output", "research")

_PRE_WINDOW = 60          # bars used to establish the pre-break equilibrium
_MIN_POST_BARS = 20       # minimum post-break bars required to classify at all
_TREND_ALPHA = 0.05       # significance level for the OLS trend slope test
_SHIFT_THRESHOLD_STD = 1.0  # |mean deviation| beyond this many pre-break stds
                            # counts as "settled somewhere new" for NEW_EQUILIBRIUM_SHIFT

log = logging.getLogger("decoupling_analysis")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_decoupling_analysis.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def classify_decoupling_event(
    spread: np.ndarray,
    break_idx: int,
    pre_window: int = _PRE_WINDOW,
    min_post_bars: int = _MIN_POST_BARS,
    trend_alpha: float = _TREND_ALPHA,
    shift_threshold_std: float = _SHIFT_THRESHOLD_STD,
) -> Dict:
    """
    Pure function, kept data-loading-free so debug/_verify_decoupling_analysis.py
    can call it directly on synthetic spread arrays. break_idx is the array
    index of the break bar (not a date — dates are resolved by the caller).

    Returns a dict: {classification, pre_break_mean, pre_break_std,
    post_break_mean_deviation, trend_slope, trend_pvalue, n_post_bars}.
    classification in {"CONTINUED_DIVERGENCE", "REVERTED_TO_OLD_EQUILIBRIUM",
    "NEW_EQUILIBRIUM_SHIFT", "INCONCLUSIVE"}.
    """
    if break_idx < pre_window or break_idx >= len(spread) - min_post_bars:
        return {"classification": "INCONCLUSIVE", "reason": "insufficient pre/post history"}

    pre = spread[break_idx - pre_window: break_idx]
    pre_mean = float(np.mean(pre))
    pre_std = float(np.std(pre, ddof=1))
    if not np.isfinite(pre_std) or pre_std <= 0:
        return {"classification": "INCONCLUSIVE", "reason": "degenerate pre-break std"}

    post = spread[break_idx:]
    n_post = len(post)
    deviation = (post - pre_mean) / pre_std
    abs_deviation = np.abs(deviation)

    t = np.arange(n_post)
    slope, intercept, r_value, p_value, std_err = sp_stats.linregress(t, abs_deviation)

    # Early/late-period windows (first/last third of the available post-break
    # history, or half the min-bars requirement if the window is small).
    # early/late ABSOLUTE deviation compares magnitude shrinkage (has it
    # meaningfully moved back toward the old equilibrium, even if not all
    # the way there yet within the observed window — a reversion in
    # progress still counts, it doesn't have to have fully arrived).
    # late SIGNED deviation checks for a genuine directional settle (a real
    # level shift oscillates around a new nonzero level, it doesn't average
    # out to zero the way noise around the old mean would).
    third = max(n_post // 3, max(min_post_bars // 2, 1))
    early_abs_mean_deviation = float(np.mean(abs_deviation[:third]))
    late_start = max(0, n_post - third)
    late_abs_mean_deviation = float(np.mean(abs_deviation[late_start:]))
    late_mean_deviation = float(np.mean(deviation[late_start:]))

    result = {
        "pre_break_mean": pre_mean,
        "pre_break_std": pre_std,
        "post_break_mean_deviation": float(np.mean(deviation)),
        "early_period_abs_deviation": early_abs_mean_deviation,
        "late_period_abs_deviation": late_abs_mean_deviation,
        "late_period_mean_deviation": late_mean_deviation,
        "trend_slope": float(slope),
        "trend_pvalue": float(p_value),
        "n_post_bars": int(n_post),
    }

    significant_trend = p_value < trend_alpha
    reverted_by_half = (
        early_abs_mean_deviation > 0
        and late_abs_mean_deviation < 0.5 * early_abs_mean_deviation
    )
    if significant_trend and slope > 0:
        result["classification"] = "CONTINUED_DIVERGENCE"
    elif significant_trend and slope < 0 and reverted_by_half:
        result["classification"] = "REVERTED_TO_OLD_EQUILIBRIUM"
    elif not significant_trend and abs(late_mean_deviation) >= shift_threshold_std:
        result["classification"] = "NEW_EQUILIBRIUM_SHIFT"
    else:
        result["classification"] = "INCONCLUSIVE"
    return result


def _load_spread_array(results_dir: str, sym_a: str, sym_b: str) -> Optional[pd.DataFrame]:
    path = os.path.join(results_dir, f"spread_series_{sym_a}_{sym_b}.parquet")
    if not os.path.exists(path):
        return None
    df = pd.read_parquet(path)
    # spread_series_*.parquet is persisted on the full calendar-padded grid —
    # DATA_GAP bars are forward-filled, not NaN, so they must be excluded by
    # gap_flag before any computation (same convention as threshold_cointegration.py/
    # variance_ratio_test.py; BUG-D54, found in this session's data-hygiene sweep).
    real_mask = (df["gap_flag_a"] != 4) & (df["gap_flag_b"] != 4)
    return df.loc[real_mask]


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== decoupling_analysis.py: descriptive study of post-decoupling behavior ===")
    log.info("SCOPE: pure description, not a trading rule. Small-n by nature — decoupling "
             "events are rare and CAMARF's per-pair history is short.")

    rows = []
    for tf_dir in _TF_DIRS:
        results_dir, is_stale = _resolve_tf_results_dir(tf_dir)
        cand_path = os.path.join(results_dir, "all_candidates.parquet")
        if not os.path.exists(cand_path):
            continue
        if is_stale:
            log.info("NOTE %s: no live output/results/%s, using archived %s instead",
                      tf_dir, tf_dir, results_dir)
        candidates = pd.read_parquet(cand_path)
        with_break = candidates[candidates["zivot_andrews_break"].notna()]
        log.info("[%s] %d/%d candidates have a detected Zivot-Andrews break",
                  tf_dir, len(with_break), len(candidates))

        for _, row in with_break.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            spread_df = _load_spread_array(results_dir, sym_a, sym_b)
            if spread_df is None or "spread" not in spread_df.columns:
                continue
            break_date = pd.Timestamp(row["zivot_andrews_break"])
            idx = spread_df.index.searchsorted(break_date)
            if idx >= len(spread_df):
                continue
            result = classify_decoupling_event(spread_df["spread"].values, int(idx))
            result.update({
                "tf_dir": tf_dir, "symbol_a": sym_a, "symbol_b": sym_b,
                "break_date": break_date,
                "was_confirmed": bool(pd.notna(row.get("coint_frac_secondary_override"))
                                       and row.get("coint_frac_secondary_override")),
            })
            rows.append(result)

    if not rows:
        log.warning("No decoupling events found — no all_candidates.parquet with "
                    "zivot_andrews_break populated. Run analysis.py first.")
        return

    result_df = pd.DataFrame(rows)
    counts = result_df["classification"].value_counts()
    total = len(result_df)
    log.info("\n--- Descriptive result across %d detected decoupling events ---", total)
    for cls, n in counts.items():
        log.info("  %-28s %4d  (%.1f%%)", cls, n, 100 * n / total)

    log.info("\nHonest scope note: n=%d events, drawn from CAMARF's available history per "
             "TF (deepest: 10Y IBKR-supplemented 1h pairs; most TFs much shorter). This is a "
             "descriptive result to inform signal design, not a statistically powered claim.", total)

    os.makedirs(_OUT_DIR, exist_ok=True)
    out_path = os.path.join(_OUT_DIR, "decoupling_analysis.parquet")
    result_df.to_parquet(out_path, index=False)
    log.info("Saved -> %s", out_path)

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("decoupling_analysis.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
