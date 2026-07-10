"""
research/bias_budget.py — comparison/diagnostic method, NOT part of the
production pipeline.

Motivated by tonight's data-hygiene literature review's single most
actionable idea: a "bias budget" — instead of reporting one headline Sharpe
and separately, narratively, noting known biases (as Development.md's bug
registry and PAPER.md §8 already do), aggregate CAMARF's OWN already-
measured correction factors into one consolidated ledger a reader can see
at a glance.

Deliberately does NOT invent a single "de-biased Sharpe" number by applying
made-up percentage haircuts for each named bias — that would fabricate a
precision the underlying evidence doesn't support (exactly the "inflate a
confidence score... to look stronger than the evidence" CLAUDE.md rule 7
prohibits). Instead this pulls together every bias-relevant number CAMARF
has ALREADY computed, in its own natural units, so the reader draws their
own conclusion from real evidence rather than a synthetic composite score:

  1. Headline raw Sharpe: IS vs. OOS (output/backtest/portfolio_layer1*.parquet)
  2. Multiple-testing correction: Deflated Sharpe Ratio, already correcting
     for the actual number of tried configurations (deflated_sharpe.json)
  3. Overfitting signal: the IS-OOS Sharpe gap itself (computed directly
     here — a large gap is the single most direct empirical overfitting
     tell, no external model needed)
  4. Skill-vs-luck corroboration: the (now-corrected, circular-block-
     bootstrap) permutation test p-values (permutation_test_is/oos.json)
  5. Garden-of-forking-paths exposure: how many times the OOS holdout has
     been examined across this project's history (the
     `_holdout_exposure` block deflated_sharpe.py now also reports)
  6. Structural biases already mitigated AT THE CODE LEVEL (listed, not
     scored — these aren't haircuts on the number, they're why some
     commonly-cited biases don't need one): survivorship exclusion log,
     point-in-time hedge-ratio series (no lookahead), GapFlag/DATA_GAP
     masking, SPY/VOO structural exclusion.

Read-only. Never fetches, never recomputes any of the underlying diagnostics
it aggregates — if one is missing, this reports that gap rather than
recomputing it inline (keeps this a pure aggregator, not a second copy of
DSR/permutation-test logic that could drift from the real ones).

Usage:
    python research/bias_budget.py
"""
import json
import os

import numpy as np
import pandas as pd

_STATS_DIR = "output/stats"
_BACKTEST_DIR = "output/backtest"


def _load_json(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _load_portfolio_sharpe(label):
    path = os.path.join(_BACKTEST_DIR, f"portfolio_{label}.parquet")
    if not os.path.exists(path):
        return None
    df = pd.read_parquet(path)
    if df.empty:
        return None
    return float(df.iloc[0].get("sharpe_portfolio", np.nan))


def main():
    print("=" * 70)
    print("BIAS BUDGET — consolidated ledger, not a single invented score")
    print("=" * 70)

    sharpe_is = _load_portfolio_sharpe("layer1")
    sharpe_oos = _load_portfolio_sharpe("layer1_holdout")
    print(f"\n1. Headline raw Sharpe: IS={sharpe_is:.4f}  OOS={sharpe_oos:.4f}"
          if sharpe_is is not None and sharpe_oos is not None
          else "\n1. Headline raw Sharpe: MISSING (run backtest.py first)")

    if sharpe_is is not None and sharpe_oos is not None and sharpe_is != 0:
        gap_pct = 100 * (sharpe_is - sharpe_oos) / sharpe_is
        print(f"\n2. IS-OOS gap (direct overfitting signal): {gap_pct:+.1f}% "
              f"({'OOS underperforms IS' if gap_pct > 0 else 'OOS matches or exceeds IS — good sign'})")

    dsr = _load_json(os.path.join(_STATS_DIR, "deflated_sharpe.json"))
    if dsr:
        n_trials = dsr.get("layer1", {}).get("n_trials", "?")
        print(f"\n3. Deflated Sharpe Ratio (multiple-testing correction, n_trials={n_trials}):")
        for suffix, label in [("layer1", "IS"), ("layer1_holdout", "OOS")]:
            d = dsr.get(suffix)
            if d:
                print(f"   {label}: DSR={d['deflated_sharpe_ratio']:.4f} "
                      f"(P(true Sharpe>0) after correcting for {d['n_trials']} tried configs), "
                      f"z={d['z_stat']:.2f}")
        holdout_exp = dsr.get("_holdout_exposure")
        if holdout_exp:
            n_exp = holdout_exp["n_holdout_exposures"]
            print(f"\n4. Garden-of-forking-paths exposure: OOS holdout examined "
                  f"{n_exp} times across {len(holdout_exp['distinct_holdout_labels'])} distinct configs"
                  + (" — HIGH, treat any single OOS number as one look among many, not a final verdict"
                     if n_exp > 20 else ""))
    else:
        print("\n3. Deflated Sharpe Ratio: MISSING (run deflated_sharpe.py first)")

    perm_is = _load_json(os.path.join(_STATS_DIR, "permutation_test_is.json"))
    perm_oos = _load_json(os.path.join(_STATS_DIR, "permutation_test_oos.json"))
    print("\n5. Skill-vs-luck corroboration (circular block bootstrap permutation test):")
    for label, perm in [("IS", perm_is), ("OOS", perm_oos)]:
        if perm:
            print(f"   {label}: realized={perm['realized_closed_trade_sharpe']:.4f} "
                  f"perm_mean={perm['perm_mean_sharpe']:.4f} p={perm['pvalue']:.4f} "
                  f"({'significant' if perm['significant_at_0_05'] else 'NOT significant'} at 5%)")
        else:
            print(f"   {label}: MISSING (run stats.py first)")

    print("\n6. Structural biases already mitigated at the code level (not scored — "
          "why these don't need a haircut, not evidence they don't exist):")
    print("   - Survivorship: 378 delist events excluded via survivorship.py's OOS truncation")
    print("   - Hedge-ratio lookahead: point-in-time hedge_ratio_*_t series (analysis.py), "
          "not full-sample scalars")
    print("   - Calendar-padding/DATA_GAP: GapFlag masking on every spread/correlation calc")
    print("   - SPY/VOO structural pair: excluded from primary confirmed-pair set")

    print("\n" + "=" * 70)
    print("HONEST SUMMARY (read the numbers above, not a synthetic composite):")
    if sharpe_is is not None and sharpe_oos is not None:
        if dsr and dsr.get("layer1_holdout", {}).get("deflated_sharpe_ratio", 0) > 0.5 \
                and perm_oos and not perm_oos.get("significant_at_0_05", True):
            print("  DSR suggests the OOS Sharpe is likely genuine after multiple-testing correction,")
            print("  but the permutation test (a different, complementary check) does not reach")
            print("  significance on the current holdout sample size — both facts are true")
            print("  simultaneously and neither should be dropped in favor of the other.")
    print("=" * 70)


if __name__ == "__main__":
    main()
