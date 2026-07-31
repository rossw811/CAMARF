"""
debug/_verify_wrds_deep_history_episodic_scan.py -- synthetic ground-truth
verification for research/wrds_deep_history_episodic_scan.py's Tier 2/3
episodic-discovery logic, BEFORE trusting it against real WRDS data.

This is the core claim being verified, stated precisely: a pair that is
cointegrated in only a sub-period of its history (not the whole sample)
should (a) FAIL a full-sample EG test (Tier 1's own gate -- confirming the
documented structural blind spot that motivated building Tier 2/3 at all),
while (b) being detected by the rolling-window EG + joint BH-FDR pipeline
(Tier 2/3's actual machinery, run_rolling_eg_pool + episodic_bhfdr_confirm --
not a reimplementation, the SAME functions main() calls).

Also verifies the joint-FDR-correction claim directly: many independent
null pairs (never related, in any window) tested naively per-window at
raw p<0.05 produce a materially inflated false-positive rate at the PAIR
level (>=1 of ~15 windows spuriously "significant" by chance), which the
joint BH-FDR correction (episodic_bhfdr_confirm) measurably reduces --
this is the concrete justification for NOT using the original draft's
naive per-window p<0.05 threshold at this larger (pair x window) scale.

Run: python debug/_verify_wrds_deep_history_episodic_scan.py
(All checks are synthetic/offline -- no WRDS connection needed, since this
verifies the statistical LOGIC, not real-data behavior.)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import _eg_worker
from config import Config
import research.wrds_deep_history_episodic_scan as scan


def check(name, cond):
    cond = bool(cond)  # a falsy short-circuited `and` can return a non-bool container
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


def make_episodic_pair(n_pre=300, n_coint=300, n_post=300, seed=0):
    """Synthetic log-price-like pair: independent random walks before AND
    after a cointegrated middle regime. The middle regime shares a common
    stochastic trend plus small stationary noise (a genuinely mean-reverting,
    hence cointegrated, spread); outside it the two series are unrelated.
    Each segment is anchored to the previous segment's endpoint so the whole
    thing is one continuous series (no artificial jumps at the seams)."""
    rng = np.random.RandomState(seed)
    a_pre = np.cumsum(rng.normal(0, 1.0, n_pre))
    b_pre = np.cumsum(rng.normal(0, 1.0, n_pre))

    common = np.cumsum(rng.normal(0, 1.0, n_coint))
    spread_noise = rng.normal(0, 0.3, n_coint)
    a_coint = a_pre[-1] + common
    b_coint = b_pre[-1] + common + spread_noise

    a_post = a_coint[-1] + np.cumsum(rng.normal(0, 1.0, n_post))
    b_post = b_coint[-1] + np.cumsum(rng.normal(0, 1.0, n_post))

    a = np.concatenate([a_pre, a_coint, a_post])
    b = np.concatenate([b_pre, b_coint, b_post])
    return a, b, (n_pre, n_pre + n_coint)  # (coint_start, coint_end) for reference


def make_null_pair(n, seed):
    """Two fully independent random walks, unrelated in every window --
    the true-null case for the multiple-testing demonstration below."""
    rng = np.random.RandomState(seed)
    a = np.cumsum(rng.normal(0, 1.0, n))
    b = np.cumsum(rng.normal(0, 1.0, n))
    return a, b


def verify_episodic_pair_fails_full_sample_but_found_by_rolling():
    print("\n=== 1. Episodic pair: FAILS full-sample EG (Tier 1), FOUND by rolling EG (Tier 2/3) ===")
    a, b, (coint_start, coint_end) = make_episodic_pair()
    max_lag = Config.ANALYSIS.EG_MAX_LAG

    full_ab = _eg_worker(("A", "B", a, b, max_lag, "synthetic"))
    full_ba = _eg_worker(("B", "A", b, a, max_lag, "synthetic"))
    ok = check("full-sample EG call succeeded", full_ab.get("ok") and full_ba.get("ok"))
    if not ok:
        return False
    full_sample_pvalue = max(full_ab["pvalue"], full_ba["pvalue"])
    ok &= check(f"full-sample EG does NOT confirm cointegration (p={full_sample_pvalue:.3f}, expect >0.05) "
                f"-- confirms Tier 1's structural blind spot for regime-only pairs",
                full_sample_pvalue > 0.05)

    pairs = [{"symbol_a": "A", "symbol_b": "B"}]
    log_price_df = pd.DataFrame({"A": a, "B": b})
    flat = scan.run_rolling_eg_pool(pairs, log_price_df, max_lag, window=200, step=50, workers=2)
    ok &= check(f"rolling EG produced window results ({len(flat)} windows tested)", len(flat) > 0)

    confirmed = scan.episodic_bhfdr_confirm(flat, alpha=0.05, min_windows_confirmed=1)
    ok &= check("Tier 2/3 machinery (rolling EG + joint BH-FDR) DOES confirm the episodic pair "
                "that Tier 1's full-sample test missed",
                len(confirmed) == 1 and confirmed[0]["symbol_a"] == "A" and confirmed[0]["symbol_b"] == "B")
    if confirmed:
        r = confirmed[0]
        print(f"    -> {r['n_windows_fdr_rejected']}/{r['n_windows_tested']} windows FDR-rejected, "
              f"min_adj_p={r['min_adjusted_pvalue']:.3e}")
    return ok


def verify_min_windows_confirmed_threshold():
    print("\n=== 2. episodic_bhfdr_confirm: min_windows_confirmed threshold respected ===")
    # Construct a flat result set where pair X has exactly 1 rejected window
    # and pair Y has 3 -- confirm the threshold parameter actually filters.
    flat = (
        [{"symbol_a": "X", "symbol_b": "Y1", "window_start": i * 50, "pvalue": 0.9}
         for i in range(5)]
        + [{"symbol_a": "X", "symbol_b": "Y1", "window_start": 250, "pvalue": 0.0001}]
        + [{"symbol_a": "P", "symbol_b": "Q", "window_start": i * 50, "pvalue": 0.0001}
           for i in range(3)]
        + [{"symbol_a": "P", "symbol_b": "Q", "window_start": 150, "pvalue": 0.9}
           for _ in range(2)]
    )
    confirmed_min1 = scan.episodic_bhfdr_confirm(flat, alpha=0.05, min_windows_confirmed=1)
    confirmed_min2 = scan.episodic_bhfdr_confirm(flat, alpha=0.05, min_windows_confirmed=2)

    names_min1 = {(r["symbol_a"], r["symbol_b"]) for r in confirmed_min1}
    names_min2 = {(r["symbol_a"], r["symbol_b"]) for r in confirmed_min2}
    ok = check("min_windows_confirmed=1: both X/Y1 (1 rejected) and P/Q (3 rejected) confirmed",
               ("X", "Y1") in names_min1 and ("P", "Q") in names_min1)
    ok &= check("min_windows_confirmed=2: X/Y1 (only 1 rejected window) correctly EXCLUDED",
                ("X", "Y1") not in names_min2)
    ok &= check("min_windows_confirmed=2: P/Q (3 rejected windows) still included",
                ("P", "Q") in names_min2)
    return ok


def verify_joint_fdr_reduces_false_positives_vs_naive():
    print("\n=== 3. Joint BH-FDR correction reduces false-positive PAIRS vs naive per-window p<0.05 ===")
    print("    (many independent null pairs, unrelated in every window -- true negatives throughout)")
    n_pairs = 20
    max_lag = Config.ANALYSIS.EG_MAX_LAG
    all_flat = []
    for i in range(n_pairs):
        a, b = make_null_pair(n=900, seed=1000 + i)
        pairs = [{"symbol_a": f"A{i}", "symbol_b": f"B{i}"}]
        log_price_df = pd.DataFrame({f"A{i}": a, f"B{i}": b})
        flat = scan.run_rolling_eg_pool(pairs, log_price_df, max_lag, window=200, step=50, workers=2)
        all_flat.extend(flat)

    by_pair = {}
    for r in all_flat:
        by_pair.setdefault((r["symbol_a"], r["symbol_b"]), []).append(r)

    naive_flagged = sum(
        1 for rows in by_pair.values() if any(r["pvalue"] < 0.05 for r in rows)
    )
    confirmed = scan.episodic_bhfdr_confirm(all_flat, alpha=0.05, min_windows_confirmed=1)
    fdr_flagged = len(confirmed)

    print(f"    {len(by_pair)} independent null pairs, ~{len(all_flat)//max(len(by_pair),1)} windows/pair")
    print(f"    naive (>=1 window raw p<0.05): {naive_flagged}/{len(by_pair)} pairs flagged")
    print(f"    joint BH-FDR (>=1 window FDR-rejected): {fdr_flagged}/{len(by_pair)} pairs flagged")

    ok = check("joint BH-FDR flags NO MORE pairs than naive per-window thresholding "
               "(BH-adjusted p-values are never below the raw p-value, by construction)",
               fdr_flagged <= naive_flagged)
    ok &= check("naive per-window thresholding shows the expected multiple-testing inflation "
                "(>=1 of ~15 windows spuriously significant by chance, at a true null)",
                naive_flagged >= 1)
    return ok


def verify_adv_gate_excludes_illiquid_windows_by_date():
    print("\n=== 4. build_rolling_eg_tasks: ADV gate excludes windows using DATE lookup, not position ===")
    # Two symbols, both cointegrated the whole time (a shared trend), over a
    # real DatetimeIndex (required -- .asof() needs date-like index, and the
    # whole point of this check is proving the gate uses the pair's OWN
    # masked dates, not raw array position, to look up each symbol's ADV).
    n = 900
    idx = pd.date_range("2000-01-01", periods=n, freq="B")
    rng = np.random.RandomState(0)
    common = np.cumsum(rng.normal(0, 1.0, n))
    log_price_df = pd.DataFrame({"A": common, "B": common + rng.normal(0, 0.1, n)}, index=idx)

    threshold = 25_000_000.0
    # A is always liquid. B is liquid for the first 450 days, then drops
    # below threshold for the remaining 450 -- a real regime change.
    adv_a = pd.Series(50_000_000.0, index=idx)
    adv_b = pd.Series(50_000_000.0, index=idx)
    adv_b.iloc[450:] = 1_000_000.0
    adv_by_symbol = {"A": adv_a, "B": adv_b}

    pairs = [{"symbol_a": "A", "symbol_b": "B"}]
    window, step = 200, 100

    gated_tasks, gated_meta = scan.build_rolling_eg_tasks(
        pairs, log_price_df, max_lag=5, window=window, step=step,
        adv_by_symbol=adv_by_symbol, adv_threshold=threshold,
    )
    gated_starts = {m[2] for m in gated_meta}

    ok = check("window starting at day 500 (B illiquid by then) is EXCLUDED",
               500 not in gated_starts)
    ok &= check("window starting at day 600 (B still illiquid) is EXCLUDED",
                600 not in gated_starts)
    ok &= check("window starting at day 0 (B still liquid then) is INCLUDED",
                0 in gated_starts)
    ok &= check("window starting at day 400 (B still liquid at this exact start date) is INCLUDED",
                400 in gated_starts)

    # Regression: with adv_by_symbol=None (the default, unchanged call
    # shape), ALL windows must be present regardless of the same synthetic
    # "illiquid" data above -- proves the gate is strictly opt-in.
    ungated_tasks, ungated_meta = scan.build_rolling_eg_tasks(
        pairs, log_price_df, max_lag=5, window=window, step=step,
    )
    ungated_starts = {m[2] for m in ungated_meta}
    ok &= check("with no adv_by_symbol passed, window starting at day 500 IS included (opt-in gate, no regression)",
                500 in ungated_starts)
    ok &= check("with no adv_by_symbol passed, the full expected window count is unchanged",
                len(ungated_starts) == len(range(0, n - window + 1, step)))
    return ok


def verify_batched_pool_matches_single_batch():
    print("\n=== 5. run_rolling_eg_pool/run_full_sample_eg_pool: batching produces IDENTICAL results "
          "to one big batch (memory fix doesn't change output) ===")
    # Multiple distinct pairs sharing symbols (to also exercise the array
    # cache being reused across pairs), forced into MULTIPLE batches via a
    # tiny pair_batch_size, compared against the same call with a batch
    # size large enough to process everything in one batch.
    n = 900
    idx = pd.date_range("2000-01-01", periods=n, freq="B")
    rng = np.random.RandomState(1)
    log_price_df = pd.DataFrame({
        sym: np.cumsum(rng.normal(0, 1.0, n)) for sym in ["A", "B", "C", "D"]
    }, index=idx)
    pairs = [
        {"symbol_a": "A", "symbol_b": "B"},
        {"symbol_a": "A", "symbol_b": "C"},
        {"symbol_a": "B", "symbol_b": "D"},
        {"symbol_a": "C", "symbol_b": "D"},
    ]

    single_batch = scan.run_rolling_eg_pool(pairs, log_price_df, max_lag=5, window=200, step=100,
                                             workers=2, pair_batch_size=500)
    multi_batch = scan.run_rolling_eg_pool(pairs, log_price_df, max_lag=5, window=200, step=100,
                                            workers=2, pair_batch_size=1)

    def _key(rows):
        return sorted((r["symbol_a"], r["symbol_b"], r["window_start"], round(r["pvalue"], 10)) for r in rows)

    ok = check(f"single-batch and multi-batch (pair_batch_size=1, forces 4 separate batches) produce "
               f"IDENTICAL results ({len(single_batch)} rows each)",
               len(single_batch) > 0 and _key(single_batch) == _key(multi_batch))

    # Same equivalence check for Tier 1's full-sample runner.
    single_fs = scan.run_full_sample_eg_pool(pairs, log_price_df, max_lag=5, workers=2, pair_batch_size=500)
    multi_fs = scan.run_full_sample_eg_pool(pairs, log_price_df, max_lag=5, workers=2, pair_batch_size=1)

    def _key_fs(rows):
        return sorted((r["symbol_a"], r["symbol_b"], round(r["pvalue"], 10)) for r in rows if r.get("ok"))

    ok &= check(f"Tier 1's single-batch and multi-batch (pair_batch_size=1) full-sample EG runs "
                f"produce IDENTICAL results ({len(single_fs)} rows each)",
                len(single_fs) > 0 and _key_fs(single_fs) == _key_fs(multi_fs))
    return ok


def verify_checkpoint_resume_matches_uninterrupted_run():
    print("\n=== 6. Checkpointing: resuming from a saved checkpoint matches an uninterrupted run "
          "(added directly after the real crash -- 'if the scripts crash, save progress') ===")
    n = 900
    idx = pd.date_range("2000-01-01", periods=n, freq="B")
    rng = np.random.RandomState(2)
    log_price_df = pd.DataFrame({
        sym: np.cumsum(rng.normal(0, 1.0, n)) for sym in ["A", "B", "C", "D", "E", "F"]
    }, index=idx)
    pairs = [
        {"symbol_a": "A", "symbol_b": "B"}, {"symbol_a": "A", "symbol_b": "C"},
        {"symbol_a": "B", "symbol_b": "D"}, {"symbol_a": "C", "symbol_b": "D"},
        {"symbol_a": "E", "symbol_b": "F"}, {"symbol_a": "A", "symbol_b": "F"},
    ]
    checkpoint_id = "TEST_ONLY_checkpoint_verification"
    scan.clear_checkpoint(checkpoint_id)  # in case a prior failed test run left one behind

    try:
        fresh = scan.run_full_sample_eg_pool(pairs, log_price_df, max_lag=5, workers=2, pair_batch_size=500)

        # Simulate a crash after only the first 2 pairs' worth of work by
        # manually saving a checkpoint for a PARTIAL result set, then calling
        # the function again with the SAME checkpoint_id and the FULL pairs
        # list -- it must resume from pair 2, not recompute pairs 0-1, and
        # the final combined result must match the fresh, uninterrupted run.
        partial = scan.run_full_sample_eg_pool(pairs[:2], log_price_df, max_lag=5, workers=2, pair_batch_size=500)
        scan._save_checkpoint(checkpoint_id, partial, n_pairs_done=2)

        resumed = scan.run_full_sample_eg_pool(pairs, log_price_df, max_lag=5, workers=2,
                                                pair_batch_size=500, checkpoint_id=checkpoint_id)

        def _key(rows):
            return sorted((r["symbol_a"], r["symbol_b"], round(r["pvalue"], 10)) for r in rows if r.get("ok"))

        ok = check(f"resumed run (checkpoint at pair 2/6) produces the SAME final results as an "
                   f"uninterrupted fresh run ({len(fresh)} rows each)",
                   len(fresh) > 0 and _key(fresh) == _key(resumed))

        checkpoint_data_path, checkpoint_meta_path = scan._checkpoint_paths(checkpoint_id)
        scan.clear_checkpoint(checkpoint_id)
        ok &= check("clear_checkpoint() actually removes both checkpoint files",
                    not os.path.exists(checkpoint_data_path) and not os.path.exists(checkpoint_meta_path))
        return ok
    finally:
        scan.clear_checkpoint(checkpoint_id)  # never leave test artifacts behind, even on failure


def main():
    results = [
        verify_episodic_pair_fails_full_sample_but_found_by_rolling(),
        verify_min_windows_confirmed_threshold(),
        verify_joint_fdr_reduces_false_positives_vs_naive(),
        verify_batched_pool_matches_single_batch(),
        verify_checkpoint_resume_matches_uninterrupted_run(),
        verify_adv_gate_excludes_illiquid_windows_by_date(),
    ]
    print("\n" + "=" * 60)
    if all(results):
        print("ALL CHECKS PASSED")
    else:
        print(f"FAILURES: {results.count(False)}/{len(results)} check groups failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
