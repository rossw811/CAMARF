"""
CAMARF research/pit_pair_discovery.py -- shared utility, NOT part of the
production pipeline (2026-08-04, task #5).

The PIT-safety adapter Ross asked for. Drop-in-shaped replacement for
ml._discover_confirmed_pairs() (same return shape: a list of
(symbol_a, symbol_b, tf_label) tuples), but sourced from the episodic,
point-in-time-safe confirmation pipeline instead of the standard
full-history EG+BH-FDR screen.

WHY THIS EXISTS: every one of Session 30's 7 comparison arms was found
(2026-08-03/04, see docs/FINDINGS.md's dedicated disclosure section and
PAPER.md §7.17) to source its pairs from ml._discover_confirmed_pairs(),
which reads analysis.py's full-history screen -- already disclosed as
NOT point-in-time-safe in PAPER.md §7.3.1 (a genuine deployment at any
past date would not have discovered or traded that same pair set). This
module is the fix: a pair-discovery function research scripts can call
INSTEAD that only ever uses information a real deployment at a given
as_of_date would actually have had.

HOW IT WORKS: wraps episodic_bhfdr_confirm_asof (research/
wrds_deep_history_episodic_scan.py, built 2026-08-02 as BUG-D106's fix,
verified 4/4 synthetically at build time) -- "as of date T, would this
pair have been episodically confirmed using only historical windows
that had ALREADY CONCLUDED by T." Reads the episodic scan's own final
Tier 3 output file directly (tier3_windows), which carries a real
window_end_date on every row as of the 2026-08-04/05 overnight re-scan
(the ONLY re-scan that has this field -- the prior 2026-07-28 cache
predates the fix and is explicitly rejected, not silently used, if
window_end_date is absent). Tier 1 (full-sample confirmation) is
deliberately excluded -- it is not point-in-time by construction, the
same reasoning behind this whole module's existence. **Tier 2 excluded
for the SAME reason as of BUG-D112 (2026-08-11)**: its candidate pool is
also a single whole-history correlation matrix, non-causal by
construction -- this was an inconsistency in the original exclusion
logic (Tier 1 excluded, Tier 2 wasn't, despite sharing the identical
non-causal candidate-selection mechanism), not a newly-introduced
restriction.

PATH UPDATE (2026-08-05): originally pointed at
`checkpoint_tier2_rolling.parquet`/`checkpoint_tier3_rolling.parquet` --
the IN-PROGRESS checkpoint files the scan wrote while running. On
successful completion the scan consolidates these into
`wrds_deep_history_episodic_scan_tier{2,3}_windows.parquet` and DELETES
the checkpoint files -- found live when the overnight scan finished and
this module's default paths silently pointed at nothing (caught before
it could return an empty result masquerading as "confirmed" -- see
`_load_pit_safe_rows`'s explicit warning-on-empty, which is what
surfaced this). Paths below now point at the final, complete files.

IMPORTANT SCOPE NOTE, disclosed directly: this covers the WRDS-sourced,
daily-and-coarser episodic universe (Tier 3 of the episodic scan only,
as of BUG-D112) -- it does NOT cover intraday timeframes, which analysis.py's standard
screen does test. Every returned tuple currently carries tf_label="1D"
for this reason. A research script switching to this adapter for an
intraday comparison arm should keep that limitation in mind rather than
assume full timeframe parity with ml._discover_confirmed_pairs().

Usage (as a library, not a standalone script):
    from pit_pair_discovery import discover_pit_confirmed_pairs
    pairs = discover_pit_confirmed_pairs(as_of_date="2026-08-04")
    # -> [(symbol_a, symbol_b, "1D"), ...], same shape as
    #    ml._discover_confirmed_pairs()
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from wrds_deep_history_episodic_scan import episodic_bhfdr_confirm_asof

_DEFAULT_CHECKPOINT_PATHS = (
    # Tier 2 REMOVED (BUG-D112, 2026-08-11): its candidate pool comes from a
    # single whole-history correlation matrix, non-causal by construction --
    # the SAME reason Tier 1 was already excluded from this PIT-safe set (see
    # module docstring). Tier 2's files still exist as a legitimate,
    # disclosed non-PIT-safe comparison arm; they just no longer feed the
    # PIT-safe pair-discovery path. Tier 3 only from here on.
    "output/research/wrds_deep_history_episodic_scan_tier3_windows.parquet",
)


def _load_pit_safe_rows(checkpoint_paths=_DEFAULT_CHECKPOINT_PATHS) -> list:
    """Loads every row from the given checkpoint/output files that carries
    a real window_end_date. Files lacking the column entirely (e.g. a
    pre-BUG-D106-fix cache) are skipped with a clear warning, never
    silently treated as PIT-safe -- an empty/wrong result here must never
    look identical to "no candidates found"."""
    rows = []
    skipped_files = []
    for path in checkpoint_paths:
        if not os.path.exists(path):
            continue
        df = pd.read_parquet(path)
        if "window_end_date" not in df.columns:
            skipped_files.append(path)
            continue
        rows.extend(df.to_dict("records"))
    if skipped_files:
        print(f"WARNING (pit_pair_discovery): skipped {len(skipped_files)} file(s) missing "
              f"window_end_date (pre-BUG-D106-fix data, not PIT-safe): {skipped_files}")
    return rows


def discover_pit_confirmed_pairs(
    as_of_date=None,
    alpha: float = 0.05,
    min_windows_confirmed: int = 1,
    checkpoint_paths=_DEFAULT_CHECKPOINT_PATHS,
    tf_label: str = "1D",
) -> list:
    """
    PIT-safe drop-in replacement for ml._discover_confirmed_pairs().
    Returns [(symbol_a, symbol_b, tf_label), ...].

    as_of_date: defaults to today (pd.Timestamp.now().normalize()) if not
    given -- "what would a deployment running RIGHT NOW have discovered."
    Pass an earlier date to ask what a deployment at THAT date would have
    known, for backtesting the discovery process itself (the same
    question pit_wfa.py asks of the standard screen).
    """
    if as_of_date is None:
        as_of_date = pd.Timestamp.now().normalize()
    else:
        as_of_date = pd.Timestamp(as_of_date)

    rows = _load_pit_safe_rows(checkpoint_paths)
    if not rows:
        print("pit_pair_discovery: no PIT-safe rows available (episodic scan not yet run with "
              "the BUG-D106 fix, or still in progress) -- returning empty list, NOT falling back "
              "to the non-PIT-safe screen silently.")
        return []

    confirmed = episodic_bhfdr_confirm_asof(rows, alpha, as_of_date, min_windows_confirmed)
    return [(c["symbol_a"], c["symbol_b"], tf_label) for c in confirmed]


def discover_pit_confirmed_pairs_with_detail(
    as_of_date=None, alpha: float = 0.05, min_windows_confirmed: int = 1,
    checkpoint_paths=_DEFAULT_CHECKPOINT_PATHS,
) -> list:
    """Same as discover_pit_confirmed_pairs but returns the full confirmation
    detail dicts (n_windows_tested, episodic_fraction_fdr, min_adjusted_pvalue,
    as_of_date) rather than just the (a, b, tf) tuple -- for callers that
    want to report confidence, not just get a pair list."""
    if as_of_date is None:
        as_of_date = pd.Timestamp.now().normalize()
    else:
        as_of_date = pd.Timestamp(as_of_date)
    rows = _load_pit_safe_rows(checkpoint_paths)
    if not rows:
        return []
    return episodic_bhfdr_confirm_asof(rows, alpha, as_of_date, min_windows_confirmed)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="PIT-safe pair discovery (adapter around episodic_bhfdr_confirm_asof)")
    p.add_argument("--as-of-date", type=str, default=None)
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--min-windows-confirmed", type=int, default=1)
    args = p.parse_args()

    detail = discover_pit_confirmed_pairs_with_detail(
        as_of_date=args.as_of_date, alpha=args.alpha, min_windows_confirmed=args.min_windows_confirmed,
    )
    print(f"{len(detail)} PIT-confirmed pairs as of "
          f"{args.as_of_date or pd.Timestamp.now().normalize().date()}:")
    for c in sorted(detail, key=lambda c: c["min_adjusted_pvalue"]):
        print(f"  {c['symbol_a']}/{c['symbol_b']}: "
              f"{c['n_windows_fdr_rejected']}/{c['n_windows_tested']} windows FDR-significant, "
              f"min_adj_p={c['min_adjusted_pvalue']:.4f}")
