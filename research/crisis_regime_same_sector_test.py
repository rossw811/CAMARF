"""
research/crisis_regime_same_sector_test.py -- does the crisis-regime
persistence effect (§5) hold up similarly for SAME-SECTOR pairs as for
CROSS-SECTOR pairs? A same-sector-only restriction is one way to partially
address the factor-co-movement confound §5 names but does not test:
same-sector pairs have a real, disclosed economic reason to co-move beyond
a generic systemic-risk factor (Forbes & Rigobon, 2002; Longin & Solnik,
2001), so if the crisis-regime persistence advantage is similar for both
same-sector and cross-sector pairs, that is evidence AGAINST "it's just a
common market factor" as the sole explanation.

Motivation (2026-09-02, Ross: broader brainstorm item, confound-countering
menu): a same-sector restriction is the cheap, immediately-testable half of
the two confound-countering ideas proposed (the other, residual-correlation
factor-adjustment, is a bigger lift, not attempted here).

Real, disclosed coverage limitation, checked directly not assumed: GICS
tags (gics.py) cover only the S&P 1500 (~1,506 symbols, Wikipedia-scraped),
a small fraction of Tier 3's full candidate universe (638,095 pairs, most
symbols GVKEY/PERMNO-labeled international/smaller names never in the S&P
1500). This test's sample is therefore a SUBSET of §5's already-small
crisis-first pool, disclosed in the output, not hidden.

Verified against synthetic ground truth first:
debug/_verify_crisis_regime_same_sector_test.py.

Usage:
    python research/crisis_regime_same_sector_test.py
"""
import logging
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PAIRS_PATH = os.path.join(_ROOT, "output", "research", "crisis_regime_correlation_diagnostic_pairs.parquet")
_OUT_PATH = os.path.join(_ROOT, "output", "research", "crisis_regime_same_sector_test.parquet")

log = logging.getLogger("crisis_regime_same_sector_test")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)


def tag_same_sector(pairs: pd.DataFrame, gics_tags: pd.DataFrame) -> pd.DataFrame:
    """Adds a `same_sector` boolean column (NaN/None if either symbol isn't
    GICS-tagged, i.e. outside the S&P 1500 -- an explicit "unknown", not
    silently coerced to False). Only rows with BOTH symbols tagged get a
    real True/False; the caller is responsible for filtering those out
    before treating same_sector as a clean binary split."""
    sector_by_symbol = gics_tags.set_index("symbol")["sector"]
    out = pairs.copy()
    out["sector_a"] = out["symbol_a"].map(sector_by_symbol)
    out["sector_b"] = out["symbol_b"].map(sector_by_symbol)
    both_tagged = out["sector_a"].notna() & out["sector_b"].notna()
    out["same_sector"] = np.where(both_tagged, out["sector_a"] == out["sector_b"], np.nan)
    return out


def crisis_vs_calm_reappearance_by_sector_match(tagged_pairs: pd.DataFrame) -> dict:
    """For same-sector pairs and cross-sector pairs SEPARATELY, computes the
    crisis-vs-calm reappearance-rate gap and a two-proportion z-test. If
    the crisis-first reappearance advantage is similar in both subsets, that
    argues against a pure common-factor explanation (which would predict
    the effect concentrates in cross-sector pairs specifically, since
    same-sector pairs already have a real fundamental reason to co-move)."""
    results = {}
    for label, subset_mask in [("same_sector", tagged_pairs["same_sector"] == True),
                                ("cross_sector", tagged_pairs["same_sector"] == False)]:
        subset = tagged_pairs[subset_mask]
        crisis = subset[subset["first_regime"] == "crisis"]
        calm = subset[subset["first_regime"] == "calm"]
        if len(crisis) < 5 or len(calm) < 5:
            results[label] = {"n_crisis": len(crisis), "n_calm": len(calm), "insufficient_n": True}
            continue
        n1, n2 = len(crisis), len(calm)
        x1 = crisis["reappears_in_different_regime"].sum()
        x2 = calm["reappears_in_different_regime"].sum()
        p_pool = (x1 + x2) / (n1 + n2)
        se = np.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)) if p_pool not in (0, 1) else np.nan
        z = (x1 / n1 - x2 / n2) / se if se and np.isfinite(se) and se > 0 else np.nan
        p_value = 2 * (1 - stats.norm.cdf(abs(z))) if np.isfinite(z) else np.nan
        results[label] = {
            "n_crisis": n1, "crisis_rate": x1 / n1, "n_calm": n2, "calm_rate": x2 / n2,
            "z_stat": z, "p_value": p_value, "insufficient_n": False,
        }
    return results


def main():
    _setup_logging()
    log.info("=== crisis_regime_same_sector_test.py: does the crisis-regime persistence "
             "effect hold for same-sector pairs too, or only cross-sector (factor-driven)? ===")

    if not os.path.exists(_PAIRS_PATH):
        log.error(f"{_PAIRS_PATH} does not exist -- run "
                  f"research/crisis_regime_correlation_diagnostic.py first.")
        sys.exit(1)

    import gics
    gics_tags = gics.load_gics_tags()
    pairs = pd.read_parquet(_PAIRS_PATH)
    log.info(f"Loaded {len(pairs)} pairs, {len(gics_tags)} GICS-tagged symbols "
             f"(S&P 1500 scope, per gics.py's own disclosed coverage limit).")

    tagged = tag_same_sector(pairs, gics_tags)
    n_both_tagged = tagged["same_sector"].notna().sum()
    log.info(f"{n_both_tagged} of {len(pairs)} pairs ({n_both_tagged/len(pairs):.2%}) have BOTH "
             f"symbols GICS-tagged and can be classified same-sector/cross-sector; the rest "
             f"(GVKEY/PERMNO-labeled international/smaller names) are excluded from this test.")

    # RIGHT-CENSORING CONTROL (2026-09-02, real problem found live on the first real run):
    # the GICS tag list (gics.py) is a CURRENT S&P 1500 snapshot, so it disproportionately
    # captures RECENT discovery events -- 53% of GICS-tagged crisis-first pairs are from just
    # the 2 most recent episodes (2024, 2025), which the main episode-clustering analysis
    # already flagged as right-censored (too little subsequent history to observe
    # reappearance yet). The FIRST run of this test showed a flipped, highly-significant
    # result (crisis reappearing LESS than calm) purely from this compositional skew, not a
    # real sector effect -- confirmed by checking the year distribution directly. Excluding
    # the 2 most recent episodes (matching crisis_regime_episode_clustering_check.py's own
    # right-censoring exclusion) before running the sector-split test, for a fair comparison.
    tagged["first_window_end_date"] = pd.to_datetime(tagged["first_window_end_date"])
    censor_cutoff = tagged.loc[tagged["first_regime"] == "crisis", "first_window_end_date"].sort_values()
    if len(censor_cutoff) > 0:
        # Exclude the 2024-2025 episodes specifically (matching the main analysis's own cutoff),
        # not an arbitrary top-N-rows cut, since pair COUNTS per episode vary hugely.
        cutoff_date = pd.Timestamp("2022-06-01")  # after 2022-03 episode, before 2024-08 episode
        n_before = len(tagged)
        tagged_censored_excluded = tagged[
            (tagged["first_regime"] != "crisis") | (tagged["first_window_end_date"] < cutoff_date)
        ]
        log.info(f"Right-censoring control: excluding crisis-first pairs discovered on/after "
                 f"{cutoff_date.date()} (the 2024/2025 episodes) -- "
                 f"{n_before - len(tagged_censored_excluded)} pairs excluded.")
        tagged = tagged_censored_excluded

    results = crisis_vs_calm_reappearance_by_sector_match(tagged)
    for label, r in results.items():
        if r.get("insufficient_n"):
            log.warning(f"[{label}] insufficient n (crisis={r['n_crisis']}, calm={r['n_calm']}) "
                       f"-- reported, not tested.")
        else:
            log.info(f"[{label}] crisis reappearance={r['crisis_rate']:.2%} (n={r['n_crisis']}), "
                     f"calm reappearance={r['calm_rate']:.2%} (n={r['n_calm']}), "
                     f"z={r['z_stat']:.3f}, p={r['p_value']:.6f}")

    pd.DataFrame(results).T.to_parquet(_OUT_PATH)
    log.info(f"Saved -> {_OUT_PATH}")
    log.info("crisis_regime_same_sector_test.py complete")


if __name__ == "__main__":
    main()
