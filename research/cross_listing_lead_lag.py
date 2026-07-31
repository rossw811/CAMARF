"""
research/cross_listing_lead_lag.py -- tests whether the SAME underlying
company's price on one exchange listing predicts its own price on a
DIFFERENT exchange listing, added 2026-07-27 per Ross's direct request:
"i also want to test if assets on one exchange can predict the movement of
the same asset on another different exchange."

Genuinely different question from wrds_lead_lag_scan.py/lead_lag_scan.py
(which test lead-lag between DIFFERENT companies' confirmed pairs) -- this
tests lead-lag between DIFFERENT LISTINGS of the SAME company (same
Compustat Global gvkey, different iid -- e.g. a Tokyo JPY listing vs a
London GBP listing of the identical underlying equity). Time-zone-driven
information arrival is the specific, testable hypothesis: does the
later-closing listing's move predict the earlier-closing listing's NEXT
session, reflecting real cross-time-zone information flow, not
data-mining noise.

Honest prior expectation, stated up front rather than discovered after the
fact: two listings of the SAME company should be tightly linked already
(same underlying fundamental value, cross-listing arbitrage keeps prices
close) -- so finding SOME cointegration/correlation here is the LESS
interesting result; the genuinely interesting question is whether there is
a real, non-zero LAG (not just contemporaneous co-movement), which would
indicate exploitable cross-time-zone information flow rather than simple
arbitrage-enforced parity.

Reuses research/wrds_lead_lag_scan.py's exact methodology and functions
directly (lagged_corr_scan, best_lag, load_price_series, _eg_worker-based
confirm stage) -- not reimplemented, since the underlying question (find
the best lag, confirm with EG at that lag vs lag 0) is identical; only the
CANDIDATE-PAIR SOURCE differs (multi-listing gvkeys discovered from the
already-fetched Compustat Global cache, not the episodic scan's confirmed-
pair output).

Verified against synthetic ground truth first:
debug/_verify_cross_listing_lead_lag.py.

Usage:
    python research/cross_listing_lead_lag.py
    python research/cross_listing_lead_lag.py --max-lag 5 --min-lift 0.03
"""
import argparse
import glob
import logging
import os
import re
import sys
from collections import defaultdict

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from research.wrds_lead_lag_scan import scan_pair, _WRDS_CACHE_DIR, _RESEARCH_DIR

log = logging.getLogger("cross_listing_lead_lag")

_LABEL_PATTERN = re.compile(r"^GVKEY(\d+)_(\w+)$")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(os.path.join(os.path.dirname(_RESEARCH_DIR), "..",
                                           "latest_run_cross_listing_lead_lag.log"),
                              mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def find_multi_listing_gvkeys(cache_dir: str = _WRDS_CACHE_DIR):
    """
    Scans output/cache/wrds/ for GVKEY{gvkey}_{iid}_1D.parquet files and
    groups them by gvkey -- returns {gvkey: [label, ...]} for every gvkey
    with 2+ distinct iid listings actually fetched. Uses whatever's already
    on disk, not the original constituent list, so this reflects reality
    (a listing that failed to fetch, e.g. one of the 3 Compustat Global
    symbols with zero g_secd rows found earlier this session, correctly
    won't appear here).
    """
    by_gvkey = defaultdict(list)
    for path in glob.glob(os.path.join(cache_dir, "GVKEY*_1D.parquet")):
        fname = os.path.basename(path)[: -len("_1D.parquet")]
        m = _LABEL_PATTERN.match(fname)
        if not m:
            continue
        gvkey, iid = m.group(1), m.group(2)
        by_gvkey[gvkey].append(fname)
    return {g: labels for g, labels in by_gvkey.items() if len(labels) > 1}


def build_cross_listing_pairs(multi_listing: dict):
    """For each multi-listing gvkey, returns every unique (label_a, label_b)
    combination of its distinct listings -- e.g. 3 listings -> 3 pairs
    (AB, AC, BC), not 6 (no double-counting the same pair both directions;
    scan_pair itself tests both lag directions within lagged_corr_scan's
    own [-max_lag, max_lag] sweep)."""
    pairs = []
    for gvkey, labels in multi_listing.items():
        labels = sorted(labels)
        for i in range(len(labels)):
            for j in range(i + 1, len(labels)):
                pairs.append((gvkey, labels[i], labels[j]))
    return pairs


def main():
    p = argparse.ArgumentParser(description="Cross-listing lead-lag test (2026-07-27)")
    p.add_argument("--max-lag", type=int, default=Config.RESEARCH.LEAD_LAG_MAX_LAG)
    p.add_argument("--min-lift", type=float, default=0.05)
    args = p.parse_args()
    _setup_logging()
    max_eg_lag = Config.ANALYSIS.EG_MAX_LAG

    log.info("=== cross_listing_lead_lag.py: does one exchange listing predict the SAME "
             "company's price on a different exchange listing? ===")
    multi_listing = find_multi_listing_gvkeys()
    log.info(f"Found {len(multi_listing)} companies with 2+ distinct exchange listings fetched")
    if not multi_listing:
        log.warning("No multi-listing companies found -- has the international WRDS fetch run yet?")
        return

    cross_pairs = build_cross_listing_pairs(multi_listing)
    log.info(f"{len(cross_pairs)} cross-listing pairs to test")

    rows = []
    for gvkey, label_a, label_b in cross_pairs:
        result = scan_pair(label_a, label_b, args.max_lag, args.min_lift, max_eg_lag)
        if "skip_reason" in result:
            log.info(f"SKIP gvkey={gvkey} {label_a}/{label_b}: {result['skip_reason']}")
            continue
        result["gvkey"], result["label_a"], result["label_b"] = gvkey, label_a, label_b
        rows.append(result)
        status = "FLAG" if result["flagged_lag_worth_checking"] else "ok"
        log.info(f"{status:5s} gvkey={gvkey} {label_a}/{label_b}: best_lag={result['best_lag']} "
                 f"corr*={result['corr_at_best_lag']:.3f}(n={result['n_at_best_lag']}) "
                 f"corr0={result['corr_at_lag0']:.3f}(n={result['n_at_lag0']}) "
                 f"lift={result['corr_lift']:.3f}")

    if not rows:
        log.warning("No cross-listing pairs with sufficient data found.")
        return

    result_df = pd.DataFrame(rows)
    flagged_df = result_df[result_df["flagged_lag_worth_checking"]]
    nonzero_lag = result_df[result_df["best_lag"] != 0]
    log.info(f"=== {len(result_df)} cross-listing pairs tested ===")
    log.info(f"  {len(nonzero_lag)}/{len(result_df)} show a non-zero best lag at all "
             f"(before the min-lift gate)")
    log.info(f"  {len(flagged_df)}/{len(result_df)} clear the >= {args.min_lift} correlation-lift "
             f"gate -- genuine candidates for real cross-time-zone information flow, "
             f"not just contemporaneous arbitrage-enforced parity")

    os.makedirs(_RESEARCH_DIR, exist_ok=True)
    out_path = os.path.join(_RESEARCH_DIR, "cross_listing_lead_lag.parquet")
    result_df.to_parquet(out_path, index=False)
    log.info(f"Saved -> output/research/cross_listing_lead_lag.parquet")


if __name__ == "__main__":
    main()
