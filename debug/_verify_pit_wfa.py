"""
Synthetic verification of pit_wfa.py, BEFORE trusting it on the real
~1600-symbol universe (which costs ~45-50 min per fold). Two things are
tested:

  1. compute_fold_dates(): pure date arithmetic — verified against
     hand-computed timestamps for a known start/end/fold_spec.

  2. screen_universe_at_cutoff()'s core new invariant — NO LOOKAHEAD: a
     synthetic universe is constructed where two symbols are strongly
     cointegrated ONLY in the window AFTER train_end (i.e. only in what
     would be the fold's test period), and completely uncorrelated,
     independent random walks within [start, train_end]. If the point-in-
     time screen found this pair anyway, it would prove the truncation
     isn't actually restricting the screening step to train-only data —
     exactly the lookahead bug this whole module exists to eliminate. A
     second pair, cointegrated WITHIN the train window itself, confirms the
     screen still finds real pairs when the relationship genuinely exists
     before the cutoff (a pure "returns None/finds nothing" pass would be
     equally consistent with a totally broken screen, not just a correct
     point-in-time one).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from pit_wfa import compute_fold_dates, screen_universe_at_cutoff

rng = np.random.default_rng(21)


def main():
    failures = []

    # --- 1. compute_fold_dates pure arithmetic ---
    start = pd.Timestamp("2020-01-01")
    end = pd.Timestamp("2024-01-01")  # exactly 4 years = 1461 days
    fold = compute_fold_dates(start, end, (0.00, 0.20, 0.20, 0.50, "fold1_exp"))
    total_days = (end - start).days
    expected_train_end = start + pd.Timedelta(days=total_days * 0.20)
    expected_test_start = expected_train_end
    expected_test_end = start + pd.Timedelta(days=total_days * 0.50)
    if fold["train_start"] != start:
        failures.append(f"train_start mismatch: {fold['train_start']} != {start}")
    if abs((fold["train_end"] - expected_train_end).total_seconds()) > 1:
        failures.append(f"train_end mismatch: {fold['train_end']} != {expected_train_end}")
    if abs((fold["test_end"] - expected_test_end).total_seconds()) > 1:
        failures.append(f"test_end mismatch: {fold['test_end']} != {expected_test_end}")

    # --- 2. No-lookahead invariant ---
    # Build a business-hourly index spanning ~200 business days (enough for
    # a meaningful train/test split at 1h granularity), 9:30-15:30 ET, 7 bars/day.
    dates = pd.bdate_range("2023-01-02", periods=200, freq="B")
    hours = pd.timedelta_range("9:30:00", "15:30:00", freq="1h")
    idx = pd.DatetimeIndex(sorted(d + h for d in dates for h in hours))
    n = len(idx)
    cutoff_bar = n // 2  # cutoff roughly at the midpoint of the synthetic history

    # FUTURE_ONLY pair: independent random walks before cutoff_bar (genuinely
    # NOT cointegrated pre-cutoff — two unrelated non-stationary series), then
    # a SHARED cumulative trend post-cutoff with a STATIONARY (i.i.d., not
    # accumulated) noise offset between the two legs — genuinely cointegrated
    # only from cutoff_bar onward. Should be invisible to a correctly-
    # truncated point-in-time screen.
    indep_a = np.cumsum(rng.normal(scale=0.02, size=n))
    indep_b = np.cumsum(rng.normal(scale=0.02, size=n))
    shared_forward_trend = np.cumsum(rng.normal(scale=0.5, size=n))

    future_only_a = 100 + np.where(np.arange(n) < cutoff_bar, indep_a, indep_a[cutoff_bar - 1] + shared_forward_trend - shared_forward_trend[cutoff_bar - 1])
    future_only_b = (
        100 + np.where(np.arange(n) < cutoff_bar, indep_b, indep_b[cutoff_bar - 1] + shared_forward_trend - shared_forward_trend[cutoff_bar - 1])
        + np.where(np.arange(n) < cutoff_bar, 0.0, rng.normal(scale=0.3, size=n))
    )

    # WITHIN_TRAIN pair: genuinely COINTEGRATED throughout, including before
    # cutoff — noise added directly to the LEVEL (making a-b a stationary,
    # mean-reverting i.i.d. series), not accumulated inside the cumsum (an
    # earlier version of this test added noise before the cumsum, which
    # makes a-b itself a random walk — highly CORRELATED but NOT
    # cointegrated, the classic spurious-regression distinction; EG
    # correctly rejected it, which is what surfaced the test construction
    # bug rather than a real pit_wfa.py bug).
    shared_trend = np.cumsum(rng.normal(scale=0.5, size=n))
    within_train_a = 100 + shared_trend
    within_train_b = 100 + shared_trend + rng.normal(scale=0.3, size=n)

    # Padding symbols so UniverseFilter's Pearson pre-filter has a plausible
    # broader universe to run against (avoids degenerate n<10 edge cases).
    universe = {
        "FUTUREONLY_A": pd.DataFrame({"close": future_only_a}, index=idx),
        "FUTUREONLY_B": pd.DataFrame({"close": future_only_b}, index=idx),
        "WITHINTRAIN_A": pd.DataFrame({"close": within_train_a}, index=idx),
        "WITHINTRAIN_B": pd.DataFrame({"close": within_train_b}, index=idx),
    }
    for i in range(10):
        universe[f"NOISE_{i}"] = pd.DataFrame(
            {"close": 100 + np.cumsum(rng.normal(scale=0.02, size=n))}, index=idx
        )

    train_start = idx[0]
    train_end = idx[cutoff_bar - 1]

    confirmed = screen_universe_at_cutoff(universe, train_start, train_end, n_workers=4)
    confirmed_pairs = {(p.symbol_a, p.symbol_b) for p in confirmed} | {(p.symbol_b, p.symbol_a) for p in confirmed}

    if ("FUTUREONLY_A", "FUTUREONLY_B") in confirmed_pairs:
        failures.append(
            "LOOKAHEAD BUG: FUTUREONLY pair (cointegrated only AFTER train_end) "
            "was found by the point-in-time screen — truncation is not working."
        )
    if ("WITHINTRAIN_A", "WITHINTRAIN_B") not in confirmed_pairs:
        failures.append(
            "WITHINTRAIN pair (genuinely cointegrated within the train window) "
            "was NOT found — screen may be broken entirely, not just correctly "
            "point-in-time (a screen that finds nothing at all would trivially "
            "also pass the no-lookahead check above for the wrong reason)."
        )

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All pit_wfa checks passed.")
    print(f"  fold date arithmetic: train_end={fold['train_end'].date()}, test_end={fold['test_end'].date()}")
    print(f"  point-in-time screen found {len(confirmed)} pair(s) from train-only data: {confirmed_pairs}")


if __name__ == "__main__":
    main()
