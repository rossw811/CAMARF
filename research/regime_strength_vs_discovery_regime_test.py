"""
research/regime_strength_vs_discovery_regime_test.py -- does a pair's
cointegration-regime STRENGTH (strong/moderate/weak, from §7.2's
cointegration_regime_segmentation.py) correlate with the VIX regime it was
FIRST DISCOVERED in (§5's crisis_regime_correlation_diagnostic.py)?

Motivation (2026-09-02, Ross: broader brainstorm item -- a third throughline
connection, testable now with existing data, no WRDS re-run needed): §5 and
§7.2 are both built on the same underlying Tier 3 windows data but have
never been joined against each other. If pairs discovered in a crisis
regime tend toward stronger (not just more frequent) genuine cointegration
spans, that would be a real, additional connection between the "regime
context is informative" thesis (§5) and the episodic-cointegration
market-structure finding (§7.2) -- neither of which currently speaks to
the other directly.

Method: for every pair with at least one "coint" span in
cointegration_regime_segments.parquet, join its FIRST-discovery regime
(crisis_regime_correlation_diagnostic_pairs.parquet) and record its
STRONGEST span (strong > moderate > weak, an ordinal reduction -- a pair
with 3 spans of mixed strength is characterized by its best one, not
averaged into a meaningless middle value). Chi-square test of independence
between discovery regime and strength category; reported regardless of
direction, same discipline as every other finding this session.

Verified against synthetic ground truth first:
debug/_verify_regime_strength_vs_discovery_regime_test.py.

Usage:
    python research/regime_strength_vs_discovery_regime_test.py
"""
import logging
import os
import sys

import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SEGMENTS_PATH = os.path.join(_ROOT, "output", "research", "cointegration_regime_segments.parquet")
_DISCOVERY_PATH = os.path.join(_ROOT, "output", "research",
                                "crisis_regime_correlation_diagnostic_pairs.parquet")
_OUT_PATH = os.path.join(_ROOT, "output", "research",
                          "regime_strength_vs_discovery_regime.parquet")

log = logging.getLogger("regime_strength_vs_discovery_regime_test")

_STRENGTH_RANK = {"strong": 3, "moderate": 2, "weak": 1}


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)


def strongest_span_per_pair(segments: pd.DataFrame) -> pd.DataFrame:
    """Reduces the (possibly many-rows-per-pair) regime-segments table to one
    row per pair: its STRONGEST coint-span strength label (strong beats
    moderate beats weak), for pairs with at least one genuine "coint" span.
    Pairs with only "not_coint" spans are excluded (nothing to characterize)."""
    coint = segments[segments["state"] == "coint"].copy()
    coint["strength_rank"] = coint["strength"].map(_STRENGTH_RANK)
    idx = coint.groupby(["symbol_a", "symbol_b"])["strength_rank"].idxmax()
    return coint.loc[idx, ["symbol_a", "symbol_b", "strength"]].reset_index(drop=True)


def build_joined_table(segments: pd.DataFrame, discovery: pd.DataFrame) -> pd.DataFrame:
    """Joins each pair's strongest-span strength label against its
    first-discovery regime. Inner join -- a pair must appear in both
    (have a coint span AND a recorded discovery regime) to be included."""
    strongest = strongest_span_per_pair(segments)
    disc = discovery[["symbol_a", "symbol_b", "first_regime"]]
    return strongest.merge(disc, on=["symbol_a", "symbol_b"], how="inner")


def chi_square_independence(joined: pd.DataFrame) -> dict:
    """Chi-square test of independence between first_regime and strength,
    via a contingency table. Returns the table, chi2 statistic, p-value,
    and degrees of freedom -- scipy's own implementation, not reimplemented."""
    table = pd.crosstab(joined["first_regime"], joined["strength"])
    chi2, p, dof, expected = stats.chi2_contingency(table)
    return {"table": table, "chi2": chi2, "p_value": p, "dof": dof}


def main():
    _setup_logging()
    log.info("=== regime_strength_vs_discovery_regime_test.py: does a pair's cointegration "
             "STRENGTH correlate with its FIRST-DISCOVERY VIX regime? ===")

    if not os.path.exists(_SEGMENTS_PATH) or not os.path.exists(_DISCOVERY_PATH):
        log.error("Required input files missing -- run cointegration_regime_segmentation.py "
                  "and crisis_regime_correlation_diagnostic.py first.")
        sys.exit(1)

    segments = pd.read_parquet(_SEGMENTS_PATH)
    discovery = pd.read_parquet(_DISCOVERY_PATH)
    log.info(f"Loaded {len(segments)} regime-segment rows, {len(discovery)} discovery-regime rows.")

    joined = build_joined_table(segments, discovery)
    log.info(f"{len(joined)} pairs have both a genuine coint span AND a recorded discovery "
             f"regime (inner join).")

    if len(joined) < 5:
        log.warning("Too few jointly-covered pairs for a meaningful test -- reporting the raw "
                    "table only, no chi-square.")
        pd.DataFrame({"symbol_a": [], "symbol_b": []}).to_parquet(_OUT_PATH)
        return

    result = chi_square_independence(joined)
    log.info(f"\nContingency table (rows=first_regime, columns=strength):\n{result['table']}")
    log.info(f"Chi-square test of independence: chi2={result['chi2']:.4f}, "
             f"dof={result['dof']}, p={result['p_value']:.6f}")

    joined.to_parquet(_OUT_PATH)
    log.info(f"Saved -> {_OUT_PATH}")
    log.info("regime_strength_vs_discovery_regime_test.py complete")


if __name__ == "__main__":
    main()
