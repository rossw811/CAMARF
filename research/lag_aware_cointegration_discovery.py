"""
CAMARF lag_aware_cointegration_discovery.py -- exploratory diagnostic, NOT
part of the production pipeline.

Ross's direction (2026-07-13): integrate lead-lag into pair discovery --
explicitly NOT to fix the DD-hub spurious-regression concentration problem
(a separate, already-resolved investigation via
research/trend_dominance_diagnostic.py), but to find genuinely DIFFERENT
arbitrage/cointegration/correlation setups the current contemporaneous-only
(lag-0) screen structurally cannot find.

Design (why this architecture, not a brute-force lagged sweep across the
whole universe): a blind lagged-EG sweep across the full 1h candidate space
would multiply an already-large test count (order 10^5 pairs) by however
many lags are checked, both computationally prohibitive and a much worse
multiple-testing burden. This project already has a cheap-prefilter-then-
confirm two-stage architecture everywhere else in the pipeline (Pearson
pre-filter -> EG test -> coint_fraction_rolling -> secondary-evidence
override), and already has the first stage of exactly this idea built:
research/near_miss_lag_scan.py tests pairs that FAIL the production lag-0
correlation pre-filter (0.25<=|corr|<0.40, i.e. never even reach EG testing
today) for lagged CORRELATION structure, with a real calendar-alignment-bug
history and permutation-correction discipline already built around it
(see Development.md Session 11's full account, including a 9-pair false
positive that was found and retracted).

That module stops at "found a real lagged correlation" -- it never takes
the next step CAMARF's own methodology requires before calling anything a
candidate pair (PAPER.md Section 4.7: correlation and cointegration test
categorically different things; only cointegration decides tradeability
in this project). This module is exactly that next step: for any near-miss
pair with a permutation-significant lagged correlation at its own
best-identified lag k, run a confirmatory EG cointegration test between
symbol_A(t) and symbol_B(t-k) -- ONLY at that pair's own specific,
already-identified lag, not a blind sweep -- via
lead_lag_permutation_check.py's already-built and already-verified
two-stage machinery (correlation-lag search -> EG confirm at that lag ->
circular-shift permutation p-value for both). This keeps the new test count
bounded (proportional to however many near-miss pairs show real lagged
correlation, not proportional to the full universe), matching this
project's established architecture.

Multiple-testing correction: Benjamini-Yekutieli (research/bh_fdr_dependence_check.py's
benjamini_yekutieli(), already built and synthetically verified this session,
dependence-robust) applied across however many confirmatory lagged-EG tests
actually get run here, count disclosed explicitly.

Sanity cross-check on any survivor: any pair that clears the confirmatory
test is checked against research/trend_dominance_diagnostic.py's Stage 2
spurious-regression-risk measure for each leg, to rule out rediscovering a
DD/MIDD-style artifact through a different door.

Read-only except for its own output parquet. Loads
output/research/near_miss_lag_scan_{tf}.parquet (must exist -- run
near_miss_lag_scan.py first) and cached price data via aligned_pair_loader.

Usage:
    python research/lag_aware_cointegration_discovery.py --tf 1h
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aligned_pair_loader import load_aligned_pair
from analysis import Config
from bh_fdr_dependence_check import benjamini_yekutieli
from data import _gap_aware_returns
from lead_lag_permutation_check import run_test
from lead_lag_scan import _gap_masked_log_price
from trend_dominance_diagnostic import spurious_regression_risk_score, symbols_for_suffix

_TF_LABEL_TO_SAFE = {
    "1m": "1min", "2m": "2min", "3m": "3min", "5m": "5min", "15m": "15min",
    "30m": "30min", "1h": "1hr", "4h": "4hr", "1D": "1day", "7D": "7day",
    "1M": "1mo", "3M": "3mo", "6M": "6mo",
}


def main():
    p = argparse.ArgumentParser(description="Lag-aware cointegration discovery -- confirmatory step (2026-07-13)")
    p.add_argument("--tf", default="1h")
    p.add_argument("--near-miss-file", default=None,
                    help="Defaults to output/research/near_miss_lag_scan_{tf}.parquet")
    p.add_argument("--min-lift", type=float, default=0.10,
                    help="Only near-miss pairs already flagged (real lift) get the confirmatory test")
    p.add_argument("--max-lag", type=int, default=10)
    p.add_argument("--n-perm", type=int, default=200)
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    # near_miss_lag_scan.py (BUG-D67's fix) only remaps the labels that
    # actually collide case-insensitively (1M/3M/6M -> 1mo/3mo/6mo), leaving
    # others (e.g. "1h") as-is on the write side -- this read path must
    # mirror that EXACT convention, not a full remap, or it silently reads
    # a differently-cased same-named file on Windows (Tier 2.1, confirmed
    # live bug, Grand Sweep 2026-07-20).
    _COLLIDING_TFS = {"1M", "3M", "6M"}
    near_miss_safe = _TF_LABEL_TO_SAFE[args.tf] if args.tf in _COLLIDING_TFS else args.tf
    near_miss_path = args.near_miss_file or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "output", "research", f"near_miss_lag_scan_{near_miss_safe}.parquet",
    )
    if not os.path.exists(near_miss_path):
        print(f"No near-miss scan output at {near_miss_path} -- run near_miss_lag_scan.py --tf {args.tf} first.")
        return

    near_miss_df = pd.read_parquet(near_miss_path)
    flagged = near_miss_df[near_miss_df["flagged"]].copy() if "flagged" in near_miss_df.columns else near_miss_df.copy()
    flagged = flagged[flagged["lift"] >= args.min_lift] if "lift" in flagged.columns else flagged
    print(f"Near-miss scan: {len(near_miss_df)} total near-miss pairs, {len(flagged)} flagged "
          f"with lift >= {args.min_lift} -- these get the confirmatory lagged-EG test.")

    if flagged.empty:
        print("No flagged near-miss pairs at this threshold -- nothing to confirm. "
              "This is itself a valid, honest result: no lag-diluted candidate pairs found "
              "at this TF/threshold band.")
        return

    max_eg_lag = Config.ANALYSIS.EG_MAX_LAG
    rows = []
    for _, row in flagged.iterrows():
        sym_a, sym_b = row["symbol_a"], row["symbol_b"]
        result = run_test(sym_a, sym_b, args.tf, max_lag=args.max_lag, n_perm=args.n_perm,
                           seed=args.seed, run_eg=True)
        if result.get("status") != "ok":
            print(f"  {sym_a}/{sym_b}: {result.get('status')}")
            continue
        rows.append(result)
        print(f"  {sym_a}/{sym_b}: best_lag={result['real_best_lag']} "
              f"eg_p={result['real_eg_p']} eg_perm_p={result['eg_perm_pvalue']}")

    if not rows:
        print("\nNo near-miss pairs produced a usable confirmatory EG result (insufficient "
              "data/overlap after shifting). No candidates to report.")
        return

    result_df = pd.DataFrame(rows)
    testable = result_df[result_df["eg_perm_pvalue"].notna()].copy()
    print(f"\n{len(testable)}/{len(result_df)} near-miss pairs produced a usable "
          f"permutation-corrected EG p-value.")

    if testable.empty:
        print("No testable confirmatory results -- nothing to correct for multiple testing.")
        return

    rejected, adjusted = benjamini_yekutieli(testable["eg_perm_pvalue"].values, args.alpha)
    testable["by_rejected"] = rejected
    testable["by_adjusted_pvalue"] = adjusted
    n_survivors = int(rejected.sum())
    print(f"\nBenjamini-Yekutieli correction across {len(testable)} confirmatory tests "
          f"(alpha={args.alpha}): {n_survivors} survivor(s).")

    survivors = testable[testable["by_rejected"]].copy()
    if survivors.empty:
        print("\nHONEST NULL RESULT: no near-miss pair's lagged cointegration survives "
              "multiple-testing correction. Consistent with this project's existing "
              "lead-lag findings (same-session null in lead_lag_scan.py, mostly-null "
              "cross-session in cross_session_leadlag.py) -- lag-aware discovery does not "
              "add tradeable diversity for this universe/TF/threshold band. This is a "
              "valid, citable result, not a failed search.")
    else:
        print(f"\n{len(survivors)} genuine survivor(s) -- running the DD/MIDD sanity "
              f"cross-check (trend_dominance_diagnostic.py Stage 2) on each leg before "
              f"treating any as a real candidate:")
        suffix = _TF_LABEL_TO_SAFE.get(args.tf, args.tf)
        all_syms = symbols_for_suffix(suffix)
        rng = np.random.default_rng(args.seed)
        cache = {}
        risk_rows = []
        for _, srow in survivors.iterrows():
            for leg in (srow["symbol_a"], srow["symbol_b"]):
                try:
                    score = spurious_regression_risk_score(leg, suffix, all_syms, 40, rng, cache)
                    score["symbol"] = leg
                except Exception as e:
                    score = {"symbol": leg, "risk_rate": None, "error": str(e)}
                risk_rows.append(score)
                rr = score.get("risk_rate")
                flag = " ** HIGH-RISK LEG (DD/MIDD-style artifact suspected) **" if (rr is not None and np.isfinite(rr) and rr > 0.30) else ""
                print(f"    {leg}: spurious-regression risk_rate={rr}{flag}")
        risk_df = pd.DataFrame(risk_rows)[["symbol", "n_ok", "n_rejected", "risk_rate"]] if risk_rows else pd.DataFrame()
        out_risk_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "output", "research",
            f"lag_aware_coint_discovery_survivor_risk_{_TF_LABEL_TO_SAFE.get(args.tf, args.tf.lower())}.parquet",
        )
        risk_df.to_parquet(out_risk_path)
        print(f"    Survivor leg risk scores written to {out_risk_path}")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(
        out_dir, f"lag_aware_cointegration_discovery_{_TF_LABEL_TO_SAFE.get(args.tf, args.tf.lower())}.parquet"
    )
    testable.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
