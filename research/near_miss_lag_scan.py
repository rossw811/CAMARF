"""
CAMARF near_miss_lag_scan.py — exploratory diagnostic, NOT part of the
production pipeline.

Directly tests Ross's hypothesis (2026-06-24): a meaningful fraction of
pairs the production correlation pre-filter (MIN_PEARSON_CORR=0.40)
currently excludes might be missed only because the true relationship is
lagged, not absent — testing only lag 0 dilutes a genuine lagged signal
below threshold. This is the universe-wide counterpart to
lead_lag_scan.py, which only checked already-CONFIRMED pairs and, by
construction, could only ever find a near-null result there (those
pairs were selected BY a lag-0-only filter — see Development.md Session
11's lead_lag_scan.py entry: 36/37 confirmed pairs already sit at lag 0).

Scope, deliberately cheap ("cheap first probe," not the full expensive
build): ONE timeframe per run (default 1h), full-universe lag-0
correlation computed ONCE via the already-vectorized production kernel
(UniverseFilter.build_returns_matrix + correlation_matrix — reused
directly, not reimplemented). The (more expensive, relative to one
lag-0 pass) lagged-correlation sweep then runs ONLY on pairs landing in
a "near miss" band just below the production threshold — not the full
N^2 candidate space. This bounds the lag sweep's cost to a small,
already-interesting subset, mirroring the cheap-filter-then-confirm
architecture used everywhere else in this project.

IMPORTANT — this is a probe for SIGNAL, not a promotion mechanism. A
pair surfaced here as "near miss, some lag looks much better" is NOT a
new confirmed pair: searching K lags per pair is itself extra
researcher degrees of freedom (a "look-elsewhere effect") that
mechanically inflates the best-of-K correlation for ANY pair, including
pure noise — lead_lag_scan.py's own synthetic test already demonstrated
a version of this (even the deliberately-wrong alignment showed nominal
EG significance). Treat this script's output as a candidate list for a
permutation-corrected significance test (eg_permutation_check.py's
circular-shift null generalized to "best p-value across K lags" — see
lead_lag_permutation_check.py), not as evidence to wire into production
on its own.

BUG FOUND AND FIXED 2026-06-24 (Development.md Session 11 has the full
account — recorded here so this mistake is not repeated): the first
version of this script fed raw, per-symbol DataStore.load() dataframes
directly into UniverseFilter.build_returns_matrix(). That function pads
shorter series with NaN at the FRONT and right-aligns by row COUNT — a
precondition that is only valid when every asset already shares an
IDENTICAL calendar grid (true in production analysis.py, which ALWAYS
calls DataAligner.align_universe() first — see _run_one_tf, "Step 2:
align to NYSE master calendar"). Raw intraday caches do NOT share a
common grid (different listing dates AND different internal gap
patterns from accumulation history) — feeding them in directly produced
real, severe misalignment (verified directly: CATY/UCB's last 2810
bars matched on row-count but 1764/2810 — 62.8% — were the WRONG
calendar timestamp once checked). This produced a fully spurious
"9 pairs, sector-clustered lead-lag signal" finding (since retracted —
the misalignment fabricated an artificial corr-lag-0 dilution and an
artificial lift at lag ±1). Fixed by calling DataAligner.align_universe()
first, exactly matching analysis.py's own Step 2, before
build_returns_matrix ever sees the data. Caught by an independent
cross-check (lead_lag_permutation_check.py, which does correct direct-
DatetimeIndex joins per pair) disagreeing sharply with this script's
reported correlations for the same real symbols — exactly the kind of
"verify against ground truth, don't trust the first result" check this
project's discipline exists for.

Read-only. Loads cached price data directly via DataStore.load/glob —
never fetches.

Usage:
    python research/near_miss_lag_scan.py
    python research/near_miss_lag_scan.py --tf 1h --near-miss-low 0.25 --max-lag 10
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import Config, UniverseFilter
from data import DataAligner, DataStore
from lead_lag_scan import best_lag, lagged_corr_scan

_TF_LABEL_TO_SAFE = {
    "1m": "1min", "2m": "2min", "3m": "3min", "5m": "5min", "15m": "15min",
    "30m": "30min", "1h": "1hr", "4h": "4hr", "1D": "1day", "7D": "7day",
    "1M": "1mo", "3M": "3mo", "6M": "6mo",
}


def discover_symbols(tf_label, cache_dir=None):
    if cache_dir is None:
        cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "cache")
    safe = _TF_LABEL_TO_SAFE[tf_label]
    pattern = os.path.join(cache_dir, f"*_{safe}.parquet")
    files = glob.glob(pattern)
    suffix = f"_{safe}.parquet"
    symbols = [os.path.basename(f)[: -len(suffix)] for f in files]
    return sorted(symbols)


def find_lagged_near_misses(returns, syms, corr0, near_miss_low, near_miss_high, max_lag, min_lift):
    """Core, independently-testable logic (extracted 2026-06-24 so this
    can be synthetically verified without needing real cache files on
    disk for discover_symbols' glob — see debug/_verify_near_miss_lag_scan.py).
    Identify pairs with 0.25<=|corr_lag0|<0.40 (defaults), then run the
    lagged-correlation sweep only on that subset. Returns a DataFrame,
    empty if no near-miss pairs exist at this threshold band."""
    n = len(syms)
    near_miss = []
    for i in range(n):
        row = corr0[i]
        for j in range(i + 1, n):
            c = row[j]
            if np.isfinite(c) and near_miss_low <= abs(c) < near_miss_high:
                near_miss.append((i, j, float(c)))

    if not near_miss:
        return pd.DataFrame(columns=[
            "symbol_a", "symbol_b", "corr_lag0", "best_lag",
            "corr_at_best_lag", "n_at_best_lag", "lift", "flagged",
        ])

    rows = []
    for i, j, c0 in near_miss:
        ret_a = pd.Series(returns[i])
        ret_b = pd.Series(returns[j])
        scan = lagged_corr_scan(ret_a, ret_b, max_lag)
        k_star, c_star, n_star = best_lag(scan)
        if k_star is None:
            continue
        lift = abs(c_star) - abs(c0)
        flagged = (k_star != 0) and (lift >= min_lift)
        rows.append({
            "symbol_a": syms[i], "symbol_b": syms[j],
            "corr_lag0": c0, "best_lag": k_star, "corr_at_best_lag": c_star,
            "n_at_best_lag": n_star, "lift": lift, "flagged": flagged,
        })
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser(description="Near-miss lag scan — cheap universe-wide probe (2026-06-24)")
    p.add_argument("--tf", default="1h")
    p.add_argument("--near-miss-low", type=float, default=0.25)
    p.add_argument("--near-miss-high", type=float, default=None,
                    help="Defaults to Config.UNIVERSE.MIN_PEARSON_CORR")
    p.add_argument("--max-lag", type=int, default=10)
    p.add_argument("--min-lift", type=float, default=0.10,
                    help="Minimum |corr(k*)| - |corr(0)| to flag as worth a closer look — "
                         "higher than lead_lag_scan.py's 0.05 default, since near-miss "
                         "pairs start from a weaker base signal")
    args = p.parse_args()
    high = args.near_miss_high if args.near_miss_high is not None else Config.UNIVERSE.MIN_PEARSON_CORR

    symbols = discover_symbols(args.tf)
    print(f"Discovered {len(symbols)} symbols with cached {args.tf} data.")
    if not symbols:
        print("No cached symbols found for this TF.")
        return

    raw_data = {}
    for sym in symbols:
        df = DataStore.load(sym, args.tf)
        if df is not None and not df.empty:
            raw_data[sym] = df
    print(f"{len(raw_data)}/{len(symbols)} loaded with usable data.")

    # MUST align onto a shared calendar before build_returns_matrix —
    # see module docstring's "BUG FOUND AND FIXED" account. This exactly
    # mirrors analysis.py's AnalysisPipeline._run_one_tf "Step 2: align
    # to NYSE master calendar" — raw per-symbol caches do not share a
    # common grid and build_returns_matrix's right-pad-by-count scheme
    # silently misaligns them if fed in directly.
    aligned_data = DataAligner.align_universe(
        {f"{sym}_{args.tf}": df for sym, df in raw_data.items()}, args.tf
    )
    print(f"{len(aligned_data)}/{len(raw_data)} aligned onto a shared calendar.")

    returns, syms, _ = UniverseFilter.build_returns_matrix(aligned_data)
    if returns.size == 0:
        print("build_returns_matrix returned no usable symbols (min_overlap not met).")
        return
    print(f"Returns matrix: {returns.shape[0]} symbols x {returns.shape[1]} bars "
          f"(after build_returns_matrix's own min_overlap filter).")

    corr0 = UniverseFilter.correlation_matrix(returns)

    total_pairs = len(syms) * (len(syms) - 1) // 2
    result_df = find_lagged_near_misses(
        returns, syms, corr0, args.near_miss_low, high, args.max_lag, args.min_lift
    )
    n_near_miss = len(result_df)
    print(f"\n{n_near_miss} near-miss pairs found "
          f"({args.near_miss_low} <= |corr_lag0| < {high}) out of "
          f"{total_pairs} total pairs evaluated at lag 0.")

    if result_df.empty:
        print("No near-miss pairs at this threshold band — nothing to scan further.")
        return
    flagged_df = result_df[result_df["flagged"]].sort_values("lift", ascending=False)
    print(f"\n{len(flagged_df)}/{len(result_df)} near-miss pairs show a non-zero lag "
          f"with a lift >= {args.min_lift} over lag 0.")
    if not flagged_df.empty:
        print(flagged_df.head(40).to_string(index=False))

    if flagged_df.empty:
        verdict = ("No near-miss pairs show a material lift at this TF/threshold band — "
                   "the lag-dilution hypothesis finds no support here.")
    else:
        verdict = (f"{len(flagged_df)} near-miss pairs show a real lift — worth building "
                   f"the permutation-corrected significance test next before treating "
                   f"any of these as candidate pairs.")
    print(f"\nGATE RESULT: this is a SIGNAL PROBE ONLY (see module docstring — a "
          f"best-of-{2 * args.max_lag + 1}-lags search inflates the apparent "
          f"correlation for ANY pair, real or noise, by construction). {verdict}")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    # Collision-safe suffix for ONLY the TFs that actually collide on Windows'
    # case-insensitive filesystem (BUG found 2026-07-14): "1M"/"1m" and "3M"/"3m"
    # differ only in case. Confirmed directly: near_miss_lag_scan_1M.parquet and
    # _1m.parquet were byte-identical (df.equals()==True) before this fix -- the
    # "1M" run had been silently overwriting/reading the 1m-minute result, never a
    # real monthly one. Mirrors data.py's own comment on the identical issue
    # ("On Windows '1M' == '1m' -- both point to the same physical file").
    # Deliberately narrow: only remap the colliding labels via _TF_LABEL_TO_SAFE
    # (1M->1mo, 3M->3mo, 6M->6mo for naming consistency across the "months" group)
    # -- the other 10 TFs (1m/2m/3m/5m/15m/30m/1h/4h/1D/7D) do NOT collide under
    # their raw labels and already have real, correct output files on disk under
    # the raw-label convention; blanket-remapping every TF here would silently
    # change their future output filename too (e.g. 1h -> "1hr"), breaking
    # consistency with what's already completed rather than fixing anything.
    _COLLIDING_TFS = {"1M", "3M", "6M"}
    safe = _TF_LABEL_TO_SAFE[args.tf] if args.tf in _COLLIDING_TFS else args.tf
    out_path = os.path.join(out_dir, f"near_miss_lag_scan_{safe}.parquet")
    result_df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
