"""
CAMARF research/earnings_lead_lag.py — comparison/diagnostic script, NOT
part of the production pipeline (2026-07-14, task #69 Piece B, built per
Ross's explicit direction: "earnings as a lead-lag arbitrage signal
between legs").

Question: for a cointegrated pair, does one leg's earnings-driven price
move predictably lead the OTHER leg's price move within some lag —
genuinely more than the pair's normal (non-earnings) lead-lag structure
would produce? This is distinct from the existing
--storm-earnings-blackout logic (which treats earnings proximity as a
reason to AVOID trading) — here earnings proximity is tested as a
candidate ENTRY signal in its own right.

Method: reuses lead_lag_scan.py's exact machinery (lagged_corr_scan,
best_lag) and earnings.py's EarningsCalendar. For each pair and each leg
as "announcer": pool gap-aware return bars from ALL of the announcer's
past earnings-window periods (+-window_days, calendar-date based) into
one sample, run the lagged-correlation scan + best-lag selection on the
pooled sample. Compare against a bootstrap null built by resampling the
SAME NUMBER of same-sized windows anchored at random (non-earnings) dates
from the pair's own history, many times, and running the identical scan
on each draw.

Honest limitations, stated up front rather than glossed over:
  - yfinance's earnings_dates typically covers several years but is
    finite (confirmed 2026-07-14: as little as 5-6 years for some
    symbols) — event count per pair is modest (roughly 4/year), so
    per-pair statistical power is limited. This is an exploratory
    comparison arm, not a production-ready signal.
  - Pooling multiple earnings-window periods into one sample is NOT the
    same statistical object as one continuous series — the bootstrap
    null (resampling whole windows, not individual bars) is used
    specifically to keep the null comparable in structure, but this is
    a coarser correction than eg_permutation_check.py's/
    lead_lag_permutation_check.py's circular-shift null on a genuinely
    contiguous series, which isn't well-defined for a discontiguous
    pooled sample.
  - Read-only: loads cached price data via aligned_pair_loader (never
    fetches) and earnings dates via EarningsCalendar (read-only yfinance
    metadata call, cached).

Usage:
    python research/earnings_lead_lag.py
    python research/earnings_lead_lag.py --tf 1h --window-days 3 --max-lag 10 --n-boot 500
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from earnings import EarningsCalendar
from data import _gap_aware_returns
from aligned_pair_loader import load_aligned_pair
from lead_lag_scan import lagged_corr_scan, best_lag

# Stable, already-vetted starting set (task #71's 1h investigation): real
# raw EG significance (p<0.001) confirmed directly on the current clean
# main cache, independent of the still-open BH-FDR/confirmed-pair-set
# question — a defensible fixed input for a first exploratory pass, not
# dependent on whichever confirmed-pair set PAPER.md eventually settles on.
_DEFAULT_PAIRS = [
    ("LNT", "VTR"), ("LNT", "WELL"), ("AME", "MAR"), ("CMS", "DUK"),
    ("EG", "WRB"), ("HAL", "NOV"), ("MET", "TMHC"), ("PFG", "STLD"),
    ("UMBF", "FHB"),
]


def _earnings_window_mask(index: pd.DatetimeIndex, earnings_dates, window_days: int) -> np.ndarray:
    if not earnings_dates:
        return np.zeros(len(index), dtype=bool)
    dates_only = index.normalize()
    mask = np.zeros(len(index), dtype=bool)
    for d in earnings_dates:
        d_norm = pd.Timestamp(d).normalize()
        mask |= (np.abs((dates_only - d_norm).days) <= window_days)
    return mask


def _pooled_scan(ret_a: pd.Series, ret_b: pd.Series, mask: np.ndarray, max_lag: int):
    if mask.sum() < 10:
        return None
    sub_a = ret_a[mask]
    sub_b = ret_b[mask]
    scan = lagged_corr_scan(sub_a, sub_b, max_lag)
    return best_lag(scan)


def run_pair(symbol_a, symbol_b, tf_label, window_days, max_lag, n_boot, seed, min_prior_earnings=2):
    rng = np.random.default_rng(seed)
    df_a, df_b = load_aligned_pair(symbol_a, symbol_b, tf_label)
    if df_a is None or df_b is None or df_a.empty or df_b.empty:
        return {"symbol_a": symbol_a, "symbol_b": symbol_b, "status": "no_data"}

    ret_a = pd.Series(_gap_aware_returns(df_a), index=df_a.index)
    ret_b = pd.Series(_gap_aware_returns(df_b), index=df_b.index)
    common_idx = ret_a.index.intersection(ret_b.index)
    ret_a, ret_b = ret_a.reindex(common_idx), ret_b.reindex(common_idx)

    cal = EarningsCalendar.load_or_build([symbol_a, symbol_b])
    now = pd.Timestamp.now()
    results = []
    for announcer, other in ((symbol_a, symbol_b), (symbol_b, symbol_a)):
        past_dates = [d for d in cal.dates_by_symbol.get(announcer, []) if d <= now]
        # Only count dates actually covered by the pair's overlapping price
        # history — an earnings date outside the loaded window contributes
        # no bars either way, but padding the "known events" count with it
        # would overstate how much real data backs the result.
        covered_dates = [
            d for d in past_dates
            if common_idx.min() <= d <= common_idx.max()
        ]
        if len(covered_dates) < min_prior_earnings:
            results.append({
                "announcer": announcer, "other_leg": other,
                "status": "insufficient_earnings_history",
                "n_earnings_events": len(covered_dates),
            })
            continue

        mask = _earnings_window_mask(common_idx, covered_dates, window_days)
        n_bars_in_windows = int(mask.sum())
        real = _pooled_scan(ret_a, ret_b, mask, max_lag)
        if real is None or real[0] is None:
            results.append({
                "announcer": announcer, "other_leg": other,
                "status": "insufficient_pooled_bars",
                "n_earnings_events": len(covered_dates),
                "n_bars_in_windows": n_bars_in_windows,
            })
            continue
        real_lag, real_corr, real_n = real

        # Bootstrap null: same number of same-sized windows, anchored at
        # random (non-earnings) calendar dates within the pair's own
        # available range.
        span_start, span_end = common_idx.min(), common_idx.max()
        span_days = (span_end - span_start).days
        null_abs_corrs = []
        for _ in range(n_boot):
            rand_anchors = [
                span_start + pd.Timedelta(days=int(rng.integers(0, span_days + 1)))
                for _ in range(len(covered_dates))
            ]
            null_mask = _earnings_window_mask(common_idx, rand_anchors, window_days)
            null_result = _pooled_scan(ret_a, ret_b, null_mask, max_lag)
            if null_result is not None and null_result[0] is not None:
                null_abs_corrs.append(abs(null_result[1]))

        if not null_abs_corrs:
            results.append({
                "announcer": announcer, "other_leg": other,
                "status": "bootstrap_failed",
                "n_earnings_events": len(covered_dates),
            })
            continue

        null_abs_corrs = np.array(null_abs_corrs)
        p_value = float(np.mean(null_abs_corrs >= abs(real_corr)))
        results.append({
            "announcer": announcer, "other_leg": other, "status": "ok",
            "n_earnings_events": len(covered_dates), "n_bars_in_windows": n_bars_in_windows,
            "real_best_lag": real_lag, "real_best_corr": real_corr, "real_n": real_n,
            "null_mean_abs_corr": float(null_abs_corrs.mean()),
            "null_p95_abs_corr": float(np.percentile(null_abs_corrs, 95)),
            "bootstrap_p_value": p_value,
        })
    return {"symbol_a": symbol_a, "symbol_b": symbol_b, "legs": results}


def main():
    p = argparse.ArgumentParser(description="Earnings-conditioned lead-lag test (2026-07-14)")
    p.add_argument("--tf", default="1h")
    p.add_argument("--window-days", type=int, default=3)
    p.add_argument("--max-lag", type=int, default=10)
    p.add_argument("--n-boot", type=int, default=500)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    all_rows = []
    for sym_a, sym_b in _DEFAULT_PAIRS:
        res = run_pair(sym_a, sym_b, args.tf, args.window_days, args.max_lag, args.n_boot, args.seed)
        if "legs" not in res:
            print(f"{sym_a}/{sym_b}: {res.get('status')}")
            continue
        for leg in res["legs"]:
            row = {"symbol_a": sym_a, "symbol_b": sym_b, **leg}
            all_rows.append(row)
            if leg["status"] == "ok":
                sig = "SIG" if leg["bootstrap_p_value"] < 0.05 else "ns "
                print(f"{sig} {leg['announcer']}->{leg['other_leg']} ({sym_a}/{sym_b}@{args.tf}): "
                      f"n_events={leg['n_earnings_events']} best_lag={leg['real_best_lag']} "
                      f"corr={leg['real_best_corr']:.3f} vs null_mean={leg['null_mean_abs_corr']:.3f} "
                      f"(p95={leg['null_p95_abs_corr']:.3f}) -> boot_p={leg['bootstrap_p_value']:.4f}")
            else:
                print(f"    {leg['announcer']}->{leg['other_leg']} ({sym_a}/{sym_b}@{args.tf}): "
                      f"{leg['status']} (n_events={leg.get('n_earnings_events', 'n/a')})")

    if not all_rows:
        print("No results.")
        return
    out_df = pd.DataFrame(all_rows)
    ok_df = out_df[out_df["status"] == "ok"]
    if not ok_df.empty:
        sig_df = ok_df[ok_df["bootstrap_p_value"] < 0.05]
        print(f"\n{len(sig_df)}/{len(ok_df)} announcer->other_leg tests significant "
              f"(bootstrap_p_value < 0.05).")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"earnings_lead_lag_{args.tf}.parquet")
    out_df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
