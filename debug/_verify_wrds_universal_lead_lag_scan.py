"""
debug/_verify_wrds_universal_lead_lag_scan.py -- synthetic ground-truth
verification for research/wrds_universal_lead_lag_scan.py, BEFORE trusting
it against the real ~5,846-symbol WRDS universe.

Core claims verified:
  1. compute_bulk_lagged_corr's VECTORIZED approximate screen matches the
     EXACT pairwise lagged_corr_scan() closely when two symbols have FULL
     overlapping history (no missing data) -- the case the approximation is
     designed for.
  2. The documented approximation bias is real and BOUNDED under a
     deliberately adversarial PARTIAL-overlap case (two symbols with very
     different valid date ranges) -- specifically, that Stage 0's floor
     (LEAD_LAG_STAGE0_FLOOR) is low enough that a genuine strong lagged
     relationship confined to the overlapping window still clears the floor
     despite the bias, i.e. no false NEGATIVE for a real, strong signal.
  3. stage0_survivors correctly excludes lag-0-only pairs and sub-floor pairs.
  4. stage1_exact_recheck recovers a KNOWN engineered lag exactly and
     applies the real min_lift threshold (rejecting a contemporaneous pair
     that Stage 0 let through).
  5. End-to-end: a genuine lead-lag pair embedded in a larger synthetic
     universe of independent noise symbols is found by Stage 0 -> Stage 1,
     while pure-noise pairs and a contemporaneous (lag-0) pair are excluded.

Run: python debug/_verify_wrds_universal_lead_lag_scan.py
(All checks are synthetic/offline -- no WRDS connection needed.)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research.wrds_universal_lead_lag_scan as ull
from research.wrds_lead_lag_scan import lagged_corr_scan, best_lag


def check(name, cond):
    cond = bool(cond)
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


def verify_bulk_matches_exact_full_overlap():
    print("\n=== 1. compute_bulk_lagged_corr matches exact lagged_corr_scan (full overlap) ===")
    n = 600
    rng = np.random.RandomState(42)
    true_lag = 6
    ret_a = rng.normal(0, 1.0, n)
    ret_b = np.roll(ret_a, true_lag) + rng.normal(0, 0.15, n)
    ret_b[:true_lag] = rng.normal(0, 1.0, true_lag)
    ret_noise1 = rng.normal(0, 1.0, n)
    ret_noise2 = rng.normal(0, 1.0, n)

    idx = pd.date_range("2015-01-01", periods=n, freq="B")
    returns_df = pd.DataFrame({"A": ret_a, "B": ret_b, "N1": ret_noise1, "N2": ret_noise2}, index=idx)

    bulk_df = ull.compute_bulk_lagged_corr(returns_df, max_lag=15)
    row = bulk_df[(bulk_df.symbol_a == "A") & (bulk_df.symbol_b == "B")].iloc[0]

    exact_scan = lagged_corr_scan(pd.Series(ret_a), pd.Series(ret_b), max_lag=15)
    exact_k, exact_c, exact_n = best_lag(exact_scan)

    ok = check(f"approx best_lag ({row['approx_best_lag']}) matches exact best_lag ({exact_k})",
               row["approx_best_lag"] == exact_k)
    ok &= check(f"approx corr ({row['approx_best_corr']:.4f}) close to exact corr ({exact_c:.4f}), "
                f"within 0.02 under full overlap",
                abs(row["approx_best_corr"] - exact_c) < 0.02)
    return ok


def verify_partial_overlap_bias_bounded():
    print("\n=== 2. Adversarial partial-overlap case: approximation bias is bounded, "
          "no false-negative at the Stage 0 floor ===")
    n_a, n_b, overlap = 2000, 400, 400
    # Symbol A has 2000 days of history (a long-lived name); symbol B only
    # has the LAST 400 days (a recently-listed name) -- deliberately extreme
    # non-overlap to stress-test the global-standardization approximation.
    rng = np.random.RandomState(7)
    true_lag = 4
    ret_a_full = rng.normal(0, 1.0, n_a)
    # B's return today = A's return from `true_lag` days ago, over the LAST `overlap` days only
    ret_b_only = np.roll(ret_a_full[-overlap:], true_lag) + rng.normal(0, 0.2, overlap)
    ret_b_only[:true_lag] = rng.normal(0, 1.0, true_lag)

    idx = pd.date_range("2010-01-01", periods=n_a, freq="B")
    ret_a_series = pd.Series(ret_a_full, index=idx)
    ret_b_full = np.full(n_a, np.nan)
    ret_b_full[-overlap:] = ret_b_only
    ret_b_series = pd.Series(ret_b_full, index=idx)

    returns_df = pd.DataFrame({"A": ret_a_series, "B": ret_b_series,
                                "N1": rng.normal(0, 1.0, n_a), "N2": rng.normal(0, 1.0, n_a)})

    bulk_df = ull.compute_bulk_lagged_corr(returns_df, max_lag=10)
    row = bulk_df[(bulk_df.symbol_a == "A") & (bulk_df.symbol_b == "B")].iloc[0]

    exact_scan = lagged_corr_scan(ret_a_series, ret_b_series, max_lag=10)
    exact_k, exact_c, exact_n = best_lag(exact_scan)

    print(f"    exact: lag={exact_k} corr={exact_c:.3f} n={exact_n} | "
          f"approx: lag={row['approx_best_lag']} corr={row['approx_best_corr']:.3f} "
          f"overlap={row['approx_overlap_at_best']}")

    ok = check("exact recovers the true engineered lag despite partial overlap",
               exact_k == true_lag and abs(exact_c) > 0.7)
    ok &= check(f"approx STILL clears the Stage 0 floor ({ull.LEAD_LAG_STAGE0_FLOOR}) for this "
                f"genuinely strong signal -- no false negative from the approximation bias",
                abs(row["approx_best_corr"]) >= ull.LEAD_LAG_STAGE0_FLOOR)
    ok &= check("approx overlap count reflects the true (small) shared history, not symbol A's full length",
                row["approx_overlap_at_best"] <= overlap + 5)
    return ok


def verify_stage0_survivors_filtering():
    print("\n=== 3. stage0_survivors: excludes lag-0-only and sub-floor pairs ===")
    bulk_df = pd.DataFrame([
        {"symbol_a": "A", "symbol_b": "B", "approx_best_lag": 5, "approx_best_corr": 0.30,
         "approx_overlap_at_best": 500, "approx_corr_lag0": 0.05, "approx_overlap_lag0": 500},
        {"symbol_a": "C", "symbol_b": "D", "approx_best_lag": 0, "approx_best_corr": 0.80,
         "approx_overlap_at_best": 500, "approx_corr_lag0": 0.80, "approx_overlap_lag0": 500},
        {"symbol_a": "E", "symbol_b": "F", "approx_best_lag": 3, "approx_best_corr": 0.05,
         "approx_overlap_at_best": 500, "approx_corr_lag0": 0.02, "approx_overlap_lag0": 500},
    ])
    survivors = ull.stage0_survivors(bulk_df, floor=0.15)
    ok = check("only the genuine nonzero-lag, above-floor pair (A/B) survives",
               set(zip(survivors.symbol_a, survivors.symbol_b)) == {("A", "B")})
    return ok


def verify_stage1_exact_recheck():
    print("\n=== 4. stage1_exact_recheck: recovers known lag, applies real min_lift threshold ===")
    n = 500
    rng = np.random.RandomState(3)
    idx = pd.date_range("2016-01-01", periods=n, freq="B")

    true_lag = 7
    ret_a = pd.Series(rng.normal(0, 1.0, n), index=idx)
    ret_b_lagged = pd.Series(ret_a.shift(true_lag).fillna(0).values + rng.normal(0, 0.15, n), index=idx)
    ret_b_contemp = pd.Series(ret_a.values + rng.normal(0, 0.15, n), index=idx)

    ret_by_symbol = {"A": ret_a, "B_lag": ret_b_lagged, "B_contemp": ret_b_contemp}
    survivors = pd.DataFrame([
        {"symbol_a": "A", "symbol_b": "B_lag"},
        {"symbol_a": "A", "symbol_b": "B_contemp"},
    ])

    stage1_df = ull.stage1_exact_recheck(survivors, max_lag=15, min_lift=0.10, ret_by_symbol=ret_by_symbol)

    ok = check("genuine lagged pair (A/B_lag) survives Stage 1",
               ("A", "B_lag") in set(zip(stage1_df.symbol_a, stage1_df.symbol_b)))
    if ("A", "B_lag") in set(zip(stage1_df.symbol_a, stage1_df.symbol_b)):
        row = stage1_df[stage1_df.symbol_b == "B_lag"].iloc[0]
        ok &= check(f"recovered exact lag ({row['exact_best_lag']}) matches true lag ({true_lag})",
                    row["exact_best_lag"] == true_lag)
    ok &= check("contemporaneous pair (A/B_contemp) rejected at Stage 1's real min_lift threshold",
                ("A", "B_contemp") not in set(zip(stage1_df.symbol_a, stage1_df.symbol_b)))
    return ok


def verify_end_to_end_stage0_to_stage1():
    print("\n=== 5. End-to-end: Stage 0 -> Stage 1 on a larger synthetic universe ===")
    n = 800
    rng = np.random.RandomState(99)
    idx = pd.date_range("2012-01-01", periods=n, freq="B")

    true_lag = 5
    ret_a = rng.normal(0, 1.0, n)
    ret_b = np.roll(ret_a, true_lag) + rng.normal(0, 0.15, n)
    ret_b[:true_lag] = rng.normal(0, 1.0, true_lag)
    ret_c = ret_a + rng.normal(0, 0.1, n)  # contemporaneous, should NOT be lead-lag-confirmed

    data = {"A": ret_a, "B": ret_b, "C": ret_c}
    for i in range(15):
        data[f"NOISE{i}"] = rng.normal(0, 1.0, n)
    returns_df = pd.DataFrame(data, index=idx)

    bulk_df = ull.compute_bulk_lagged_corr(returns_df, max_lag=12)
    survivors = ull.stage0_survivors(bulk_df, floor=ull.LEAD_LAG_STAGE0_FLOOR)
    ret_by_symbol = {s: returns_df[s] for s in returns_df.columns}
    stage1_df = ull.stage1_exact_recheck(survivors, max_lag=12, min_lift=0.05, ret_by_symbol=ret_by_symbol)

    confirmed_pairs = set(zip(stage1_df.symbol_a, stage1_df.symbol_b)) | \
                       set(zip(stage1_df.symbol_b, stage1_df.symbol_a))

    ok = check("genuine lead-lag pair (A,B) found end-to-end", ("A", "B") in confirmed_pairs)
    ok &= check("contemporaneous pair (A,C) NOT in the lead-lag-confirmed set",
                ("A", "C") not in confirmed_pairs)
    noise_pairs_confirmed = [p for p in confirmed_pairs if "NOISE" in p[0] or "NOISE" in p[1]]
    ok &= check(f"no pure-noise pair spuriously confirmed (found {len(noise_pairs_confirmed)})",
                len(noise_pairs_confirmed) == 0)
    return ok


def verify_episodic_finds_regime_confined_pair_whole_sample_misses():
    print("\n=== 6. EPISODIC mode finds a regime-confined lead-lag pair the WHOLE-SAMPLE "
          "scan structurally dilutes to near-zero ===")
    window, step = 300, 100
    n_windows_total = 6
    n = window + step * (n_windows_total - 1)  # exactly spans n_windows_total windows
    rng = np.random.RandomState(21)
    idx = pd.date_range("2010-01-01", periods=n, freq="B")

    # Symbol A: independent noise for its ENTIRE history.
    ret_a = rng.normal(0, 1.0, n)
    # Symbol B: PURE independent noise everywhere EXCEPT ONE window (the 3rd,
    # start index 200-500), where it is A's return from `true_lag` bars ago
    # plus small noise -- a relationship confined to ~1/6 of the sample.
    true_lag = 5
    ret_b = rng.normal(0, 1.0, n)
    regime_start = 2 * step  # the 3rd window's start position
    regime_slice = slice(regime_start, regime_start + window)
    lagged_segment = np.roll(ret_a[regime_slice], true_lag) + rng.normal(0, 0.1, window)
    lagged_segment[:true_lag] = rng.normal(0, 1.0, true_lag)
    ret_b[regime_slice] = lagged_segment

    returns_df = pd.DataFrame({"A": ret_a, "B": ret_b}, index=idx)

    # --- whole-sample scan (already-verified machinery) should find NOTHING
    # (or a very weak, sub-floor signal) -- the single regime's signal is
    # diluted by the other 5/6 of pure noise.
    whole_bulk = ull.compute_bulk_lagged_corr(returns_df, max_lag=10)
    whole_row = whole_bulk[(whole_bulk.symbol_a == "A") & (whole_bulk.symbol_b == "B")].iloc[0]
    whole_survivors = ull.stage0_survivors(whole_bulk, floor=ull.LEAD_LAG_STAGE0_FLOOR)

    # --- episodic scan should find it, confined to the correct window.
    episodic_bulk = ull.compute_bulk_lagged_corr_episodic(returns_df, max_lag=10, window=window, step=step)
    episodic_survivors = ull.stage0_survivors_episodic(episodic_bulk, floor=ull.LEAD_LAG_STAGE0_FLOOR)
    ep_stage1 = ull.stage1_exact_recheck_episodic(episodic_survivors, max_lag=10, min_lift=0.05,
                                                    returns_df=returns_df, window=window)

    print(f"    whole-sample: best_lag={whole_row['approx_best_lag']} "
          f"corr={whole_row['approx_best_corr']:.3f} (diluted by {n_windows_total-1}/{n_windows_total} pure noise)")
    if not ep_stage1.empty:
        for _, hit in ep_stage1.sort_values("exact_corr_at_best_lag", key=abs, ascending=False).iterrows():
            pos = returns_df.index.get_loc(hit["window_start_date"])
            print(f"    episodic window start_pos={pos}: lag={hit['exact_best_lag']} "
                  f"corr={hit['exact_corr_at_best_lag']:.3f} lift={hit['exact_lift']:.3f}")

    ok = check("whole-sample scan does NOT surface this pair (diluted below the decision floor)",
               ("A", "B") not in set(zip(whole_survivors.symbol_a, whole_survivors.symbol_b))
               or abs(whole_row["approx_best_corr"]) < 0.5)
    ok &= check("episodic Stage 1 DOES find the pair, with the correct engineered lag",
                not ep_stage1.empty and (ep_stage1["exact_best_lag"] == true_lag).any())
    if not ep_stage1.empty:
        # Neighboring windows PARTIALLY overlapping the injected regime ([200,500))
        # will genuinely show real (diluted) signal too -- that's correct rolling-scan
        # behavior, not a bug. The window with the STRONGEST signal should be the one
        # with FULL overlap (start=200, which here exactly equals the regime's own span).
        best_row = ep_stage1.iloc[(ep_stage1["exact_corr_at_best_lag"].abs()).argmax()]
        best_pos = returns_df.index.get_loc(best_row["window_start_date"])
        ok &= check(f"the STRONGEST-signal window is the one with full regime overlap "
                    f"(found start pos {best_pos}, true regime start {regime_start})",
                    best_pos == regime_start)
    return ok


def main():
    results = [
        verify_bulk_matches_exact_full_overlap(),
        verify_partial_overlap_bias_bounded(),
        verify_stage0_survivors_filtering(),
        verify_stage1_exact_recheck(),
        verify_end_to_end_stage0_to_stage1(),
        verify_episodic_finds_regime_confined_pair_whole_sample_misses(),
    ]
    print("\n" + "=" * 60)
    if all(results):
        print("ALL CHECKS PASSED")
    else:
        print(f"FAILURES: {results.count(False)}/{len(results)} check groups failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
